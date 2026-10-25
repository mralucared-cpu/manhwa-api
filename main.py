import urllib.parse
from bs4 import BeautifulSoup
from curl_cffi import requests
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Manhwa Arabic API", version="4.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_URL = "https://www.mgeko.cc"
FALLBACK_COVER = f"{BASE_URL}/static/img/logo_200x200.png"
session = requests.Session(impersonate="chrome120")


def normalize_manga_url(url: str) -> str:
    """إزالة query/fragment والشرطة الأخيرة لتوحيد روابط المانها."""
    parsed = urllib.parse.urlsplit(url.strip())
    path = (parsed.path or "").rstrip("/")
    return urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, "", ""))


def is_real_manga_url(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    path = (parsed.path or "").lower()
    if "/jumbo/manga/" in path:
        return False
    if "/manga/" not in path:
        return False
    if path.rstrip("/") in ("/manga", ""):
        return False
    return True


@app.get("/")
def home():
    return {
        "status": "online",
        "message": "Manhwa Arabic Cloud Server is Running Successfully!",
        "version": "4.1.0",
    }


def parse_mangas(html_content: str):
    soup = BeautifulSoup(html_content, "html.parser")
    mangas = []
    seen_urls = set()

    for a in soup.select("a[href*='/manga/']"):
        href = (a.get("href") or "").strip()
        if not href:
            continue

        href = urllib.parse.urljoin(BASE_URL, href)
        parsed_href = urllib.parse.urlsplit(href)
        # لا نعامل صفحات التصنيفات/التصفية كأنها مانها مستقلة.
        if "/jumbo/manga/" in (parsed_href.path or "").lower():
            continue

        # روابط الموقع الخاصة بالمانها فقط؛ تجاهل صفحة /manga/ العامة.
        if not is_real_manga_url(href):
            continue

        canonical_url = normalize_manga_url(href)
        if canonical_url in seen_urls:
            continue

        img = a.select_one("img")
        if not img and a.parent:
            img = a.parent.select_one("img")
        if not img:
            img = a.find_previous("img")

        cover = ""
        if img:
            cover = (
                img.get("data-src")
                or img.get("data-lazy-src")
                or img.get("data-original")
                or img.get("src")
                or ""
            ).strip()

        if cover.startswith("//"):
            cover = "https:" + cover
        elif cover.startswith("/"):
            cover = urllib.parse.urljoin(BASE_URL, cover)

        if not cover.startswith(("http://", "https://")):
            cover = FALLBACK_COVER

        title = (img.get("alt") or "").strip() if img else ""
        if not title:
            title_el = a.select_one("h2, h3, h4, .title, .novel-title, .manga-title, span")
            if title_el:
                title = title_el.get_text(" ", strip=True)
        if not title:
            title = a.get_text(" ", strip=True)

        title = " ".join(title.split())
        ignore_words = {
            "read now", "read manga", "manga", "view more", "details", "all chapters"
        }
        if len(title) < 3 or title.lower() in ignore_words:
            continue

        seen_urls.add(canonical_url)
        mangas.append({"title": title, "url": canonical_url + "/", "cover_url": cover})

    return mangas


@app.get("/api/mangas")
def get_mangas(
    page: int = Query(default=1, ge=1),
    query: str = Query(default="", max_length=120),
):
    query = query.strip()

    if query:
        encoded = urllib.parse.quote(query)
        target_urls = [f"{BASE_URL}/autocomplete?term={encoded}"]
    elif page == 1:
        target_urls = [
            BASE_URL,
            f"{BASE_URL}/browse-comics/?sort=recently_added&page=1",
        ]
    else:
        target_urls = [
            f"{BASE_URL}/browse-comics/?sort=recently_added&page={page}"
        ]

    all_mangas = []
    seen_urls = set()

    for target_url in target_urls:
        try:
            resp = session.get(
                target_url,
                headers={"Referer": BASE_URL, "User-Agent": "Mozilla/5.0"},
                timeout=20,
            )
            if resp.status_code != 200:
                continue

            for item in parse_mangas(resp.text):
                key = normalize_manga_url(item["url"])
                if key not in seen_urls:
                    seen_urls.add(key)
                    all_mangas.append(item)
        except Exception:
            continue

    return {"page": page, "query": query, "count": len(all_mangas), "mangas": all_mangas}


@app.get("/api/chapters")
def get_chapters(manga_url: str):
    clean_url = manga_url.strip()
    if not clean_url.startswith(("http://", "https://")):
        clean_url = urllib.parse.urljoin(BASE_URL, f"/manga/{clean_url.strip('/')}/")

    parsed = urllib.parse.urlsplit(clean_url)
    if parsed.netloc.lower() not in {"www.mgeko.cc", "mgeko.cc"}:
        raise HTTPException(status_code=400, detail="Unsupported manga URL")

    all_chapters_url = clean_url.rstrip("/") + "/all-chapters/"
    chapters = []
    seen = set()

    try:
        resp = session.get(all_chapters_url, headers={"Referer": BASE_URL}, timeout=20)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.select("a[href*='/reader/']"):
                title = a.get_text(" ", strip=True)
                href = urllib.parse.urljoin(BASE_URL, a.get("href", ""))
                if title and href not in seen:
                    seen.add(href)
                    chapters.append({"title": title, "url": href})
    except Exception:
        pass

    if not chapters:
        try:
            resp = session.get(clean_url, headers={"Referer": BASE_URL}, timeout=20)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                for a in soup.select(".chapter-list a, #chapters-list a, a[href*='/reader/']"):
                    title = a.get_text(" ", strip=True)
                    href = urllib.parse.urljoin(BASE_URL, a.get("href", ""))
                    if title and href not in seen:
                        seen.add(href)
                        chapters.append({"title": title, "url": href})
        except Exception:
            pass

    chapters.reverse()
    return {"total": len(chapters), "chapters": chapters}


@app.get("/api/pages")
def get_pages(chapter_url: str):
    parsed = urllib.parse.urlsplit(chapter_url)
    if parsed.scheme not in ("http", "https") or parsed.netloc.lower() not in {"www.mgeko.cc", "mgeko.cc"}:
        raise HTTPException(status_code=400, detail="Unsupported chapter URL")

    try:
        resp = session.get(chapter_url, headers={"Referer": BASE_URL}, timeout=20)
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Failed to load chapter pages")

        soup = BeautifulSoup(resp.text, "html.parser")
        images = []
        seen_images = set()
        for img in soup.select("#chapter-reader img, .chapter-images img"):
            src = (
                img.get("data-src")
                or img.get("data-lazy-src")
                or img.get("data-original")
                or img.get("src")
                or ""
            ).strip()
            if not src:
                continue
            src = urllib.parse.urljoin(BASE_URL, src)
            low = src.lower()
            if "logo" in low or "advert" in low or "/ads/" in low:
                continue
            if src not in seen_images:
                seen_images.add(src)
                images.append(src)

        return {"total_pages": len(images), "images": images}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not fetch chapter: {e}")


@app.get("/api/proxy-image")
def proxy_image(url: str):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Invalid image URL")

    try:
        resp = session.get(url, headers={"Referer": BASE_URL}, timeout=15)
        if resp.status_code != 200:
            raise HTTPException(status_code=404, detail="Image not found")
        content_type = resp.headers.get("content-type", "image/jpeg")
        if not content_type.lower().startswith("image/"):
            raise HTTPException(status_code=415, detail="URL did not return an image")
        return Response(content=resp.content, media_type=content_type)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found")
