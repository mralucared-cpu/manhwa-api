import urllib.parse
from bs4 import BeautifulSoup
from curl_cffi import requests
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Manhwa Arabic API", version="1.1.0")

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


# ========================================================
# 1. جلب قائمة المانهوات (يدعم الصفحات والبحث الفوري)
# ========================================================
@app.get("/api/mangas")
def get_mangas(page: int = 1, query: str = ""):
    query = query.strip()

    if query:
        encoded = urllib.parse.quote(query)
        # استخدام مسار البحث المباشر السريع الذي يرجع HTML جاهز
        target_url = f"{BASE_URL}/autocomplete?term={encoded}"
    elif page == 1:
        target_url = BASE_URL
    else:
        # ترقيم صفحات التصفح في mgeko يعتمد على results=
        target_url = f"{BASE_URL}/browse-comics/?results={page}&filter=New"

    try:
        resp = session.get(
            target_url, headers={"Referer": BASE_URL}, timeout=15
        )
        if resp.status_code != 200:
            raise HTTPException(
                status_code=resp.status_code, detail="Failed to fetch from site"
            )

        soup = BeautifulSoup(resp.text, "html.parser")
        mangas = []

        # البحث عن كل الروابط التي تشير إلى المانجا
        for a in soup.select("a[href*='/manga/'], li a"):
            href = a.get("href", "")
            if not href or "/manga/" not in href:
                continue

            if not href.startswith("http"):
                href = urllib.parse.urljoin(BASE_URL, href)
            if href.endswith("/all-chapters/"):
                href = href.replace("/all-chapters/", "/")

            img = (
                a.select_one("img")
                or a.find_previous("img")
                or a.find_next("img")
            )

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

            title = ""
            if img and img.get("alt"):
                title = img.get("alt").strip()
            if not title:
                t_el = a.select_one("h2, h3, h4, .title, .novel-title, span")
                if t_el:
                    title = t_el.get_text(strip=True)
            if not title:
                title = a.get_text(strip=True)

            if (
                title
                and len(title) > 2
                and not any(m["url"] == href for m in mangas)
            ):
                mangas.append(
                    {
                        "title": title,
                        "url": href,
                        "cover_url": (
                            cover
                            if cover.startswith("http")
                            else "https://www.mgeko.cc/static/img/logo_200x200.png"
                        ),
                    }
                )

        return {"page": page, "count": len(mangas), "mangas": mangas}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
