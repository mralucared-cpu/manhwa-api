import re
import urllib.parse
from bs4 import BeautifulSoup
from curl_cffi import requests
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Manhwa Arabic API", version="7.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_URL = "https://www.mgeko.cc"
session = requests.Session(impersonate="chrome120")


@app.get("/")
def home():
    return {
        "status": "online",
        "message": "Manhwa Arabic Cloud Server is Running Successfully! 🚀",
    }


def extract_mangas_from_html(html_text: str):
    soup = BeautifulSoup(html_text, "html.parser")
    mangas = []

    for a in soup.select("a[href*='/manga/']"):
        href = a.get("href", "")
        if not href or href in [
            "/manga/",
            "/manga",
            "/manga/all-chapters/",
            f"{BASE_URL}/manga/",
        ]:
            continue

        if not href.startswith("http"):
            href = urllib.parse.urljoin(BASE_URL, href)
        if href.endswith("/all-chapters/"):
            href = href.replace("/all-chapters/", "/")

        if any(m["url"] == href for m in mangas):
            continue

        container = a.find_parent(
            lambda tag: tag.name in ["li", "div", "article"]
            and tag.select_one("img") is not None
        )
        if not container:
            container = a.parent

        img = a.select_one("img")
        if not img and container:
            img = container.select_one("img")

        cover = ""
        if img:
            cover = (
                img.get("data-src")
                or img.get("data-lazy-src")
                or img.get("src")
                or ""
            ).strip()
            if cover.startswith("//"):
                cover = "https:" + cover
            elif cover.startswith("/"):
                cover = urllib.parse.urljoin(BASE_URL, cover)

        if not cover or not cover.startswith("http"):
            cover = "https://www.mgeko.cc/static/img/logo_200x200.png"

        title = ""
        if a.get_text(strip=True):
            title = a.get_text(strip=True)
        if (not title or len(title) < 2) and img and img.get("alt"):
            title = img.get("alt").strip()
        if (not title or len(title) < 2) and container:
            heading = container.select_one(
                "h1, h2, h3, h4, h5, .title, .novel-title"
            )
            if heading:
                title = heading.get_text(strip=True)

        # تنظيف شارات NEW و التقييمات مثل NEW5.0 من اسم المانجا
        title = re.sub(r"^NEW\s*[\d.]*\s*", "", title, flags=re.I)
        title = re.sub(r"^HOT\s*", "", title, flags=re.I)
        title = title.strip()

        ignore_words = [
            "read now",
            "read manga",
            "manga",
            "view more",
            "details",
            "all chapters",
            "read",
            "chapters",
        ]

        if (
            title
            and len(title) > 2
            and title.lower() not in ignore_words
            and not title.lower().startswith("chapter")
        ):
            mangas.append({"title": title, "url": href, "cover_url": cover})

    return mangas


# ========================================================
# 1. نظام التصفح الحقيقي للتقليب (صفحة 1، 2، 3، 4...)
# ========================================================
@app.get("/api/mangas")
def get_mangas(page: int = 1, query: str = ""):
    query = query.strip()

    if query:
        encoded = urllib.parse.quote(query)
        target_urls = [f"{BASE_URL}/autocomplete?term={encoded}"]
    elif page <= 1:
        # الصفحة الأولى: الواجهة + أول صفحة تصفح
        target_urls = [
            BASE_URL,
            f"{BASE_URL}/browse-comics/?sort=recently_added&page=1",
        ]
    else:
        # الصفحات التالية عند السحب لأسفل: صفحة 2، صفحة 3، صفحة 4...
        target_urls = [
            f"{BASE_URL}/browse-comics/?sort=recently_added&page={page}"
        ]

    all_mangas = []

    for url in target_urls:
        try:
            resp = session.get(url, headers={"Referer": BASE_URL}, timeout=15)
            if resp.status_code == 200:
                extracted = extract_mangas_from_html(resp.text)
                for item in extracted:
                    if not any(m["url"] == item["url"] for m in all_mangas):
                        all_mangas.append(item)
        except Exception:
            continue

    return {"page": page, "count": len(all_mangas), "mangas": all_mangas}


# ========================================================
# 2. جلب جميع فصول أي مانجا
# ========================================================
@app.get("/api/chapters")
def get_chapters(manga_url: str):
    clean_url = manga_url.strip()
    if not clean_url.startswith("http"):
        clean_url = f"{BASE_URL}/manga/{clean_url}/"

    all_chapters_url = clean_url.rstrip("/") + "/all-chapters/"
    chapters = []

    try:
        resp = session.get(
            all_chapters_url, headers={"Referer": BASE_URL}, timeout=12
        )
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.select("a[href*='/reader/']"):
                title = a.get_text(strip=True)
                href = a.get("href", "")
                if not href.startswith("http"):
                    href = urllib.parse.urljoin(BASE_URL, href)
                if title and not any(c["url"] == href for c in chapters):
                    chapters.append({"title": title, "url": href})
    except Exception:
        pass

    if not chapters:
        try:
            resp = session.get(
                clean_url, headers={"Referer": BASE_URL}, timeout=12
            )
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                for a in soup.select(
                    ".chapter-list a, #chapters-list a, a[href*='/reader/']"
                ):
                    title = a.get_text(strip=True)
                    href = a.get("href", "")
                    if not href.startswith("http"):
                        href = urllib.parse.urljoin(BASE_URL, href)
                    if title and not any(c["url"] == href for c in chapters):
                        chapters.append({"title": title, "url": href})
        except Exception:
            pass

    chapters.reverse()
    return {"total": len(chapters), "chapters": chapters}


# ========================================================
# 3. استخراج روابط صور الفصل
# ========================================================
@app.get("/api/pages")
def get_pages(chapter_url: str):
    try:
        resp = session.get(chapter_url, headers={"Referer": BASE_URL}, timeout=15)
        if resp.status_code != 200:
            raise HTTPException(
                status_code=500, detail="Failed to load chapter pages"
            )

        soup = BeautifulSoup(resp.text, "html.parser")
        images = []

        for img in soup.select("#chapter-reader img, .chapter-images img"):
            src = (
                img.get("data-src")
                or img.get("data-lazy-src")
                or img.get("src")
                or ""
            ).strip()
            if src and "logo" not in src and "ad" not in src:
                if src.startswith("//"):
                    src = "https:" + src
                elif src.startswith("/"):
                    src = urllib.parse.urljoin(BASE_URL, src)
                images.append(src)

        return {"total_pages": len(images), "images": images}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========================================================
# 4. بروكسي تحميل الصور
# ========================================================
@app.get("/api/proxy-image")
def proxy_image(url: str):
    try:
        resp = session.get(url, headers={"Referer": BASE_URL}, timeout=10)
        content_type = resp.headers.get("content-type", "image/jpeg")
        return Response(content=resp.content, media_type=content_type)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found")
