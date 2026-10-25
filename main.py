import gzip
import json
import re
import ssl
import urllib.parse
import urllib.request
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Complete Manhwa Arabic API", version="16.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_URL = "https://manganato.com"
CHAP_URL = "https://chapmanganato.to"

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Referer": "https://chapmanganato.to/",
}


# معالج ذكي للتحويلات التلقائية يمنع فقدان الهيدر أو الحظر
class SmartRedirectHandler(urllib.request.HTTPRedirectHandler):

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_req:
            new_req.headers["User-Agent"] = req.headers.get("User-Agent")
            new_req.headers["Referer"] = "https://chapmanganato.to/"
        return new_req


opener = urllib.request.build_opener(
    SmartRedirectHandler(), urllib.request.HTTPSHandler(context=ssl_ctx)
)


def fetch_html(url: str, referer: str = "https://chapmanganato.to/"):
    req_headers = HEADERS.copy()
    req_headers["Referer"] = referer

    req = urllib.request.Request(url, headers=req_headers)
    try:
        with opener.open(req, timeout=25) as resp:
            raw = resp.read()
            if raw.startswith(b"\x1f\x8b"):
                raw = gzip.decompress(raw)
            return raw.decode("utf-8", errors="ignore")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
def home():
    return {
        "status": "online",
        "message": "Complete Manhwa (Chapter 1 to End) API is Live! 🚀",
    }


# ========================================================
# 1. جلب المانهوات الكورية الأكثر شهرة مع التقليب اللانهائي
# ========================================================
@app.get("/api/mangas")
def get_mangas(page: int = 1, query: str = ""):
    query = query.strip()

    if query:
        clean_q = re.sub(r"[^a-zA-Z0-9 ]", "", query).replace(" ", "_")
        target_url = f"https://manganato.com/search/story/{clean_q}?page={page}"
    else:
        target_url = f"https://manganato.com/genre-all/{page}?type=topview&category=all"

    html = fetch_html(target_url, referer="https://manganato.com/")
    soup = BeautifulSoup(html, "html.parser")
    mangas = []

    items = soup.select(".content-genres-item, .search-story-item")
    for item in items:
        link_el = item.select_one(
            ".genres-item-name, .item-title, h3 a, a.genres-item-name"
        )
        img_el = item.select_one("img")

        if not link_el or not img_el:
            continue

        title = link_el.get_text(strip=True)
        href = link_el.get("href", "")
        cover = img_el.get("src", "") or img_el.get("data-src", "")

        # توجيه الرابط مباشرة إلى سيرفر الفصول لتفادي مشاكل التحويل
        if "manganato.com/manga-" in href:
            href = href.replace(
                "https://manganato.com/manga-",
                "https://chapmanganato.to/manga-",
            )

        last_ch_el = item.select_one(
            ".genres-item-chap, .item-chapter, a[href*='chapter']"
        )
        last_ch = (
            last_ch_el.get_text(strip=True) if last_ch_el else "الفصل متاح"
        )

        if title and href:
            mangas.append(
                {
                    "title": title,
                    "url": href,
                    "cover_url": cover,
                    "latestChapter": last_ch,
                }
            )

    return {"page": page, "count": len(mangas), "mangas": mangas}


# ========================================================
# 2. جلب جميع فصول المانهوا كاملة من الفصل 1 حتى الأخير
# ========================================================
@app.get("/api/chapters")
def get_chapters(manga_url: str):
    clean_url = manga_url.strip()
    if not clean_url.startswith("http"):
        clean_url = f"https://chapmanganato.to/{clean_url}"

    # توحيد الرابط لسيرفر الفصول الفعلي
    clean_url = clean_url.replace(
        "https://manganato.com/", "https://chapmanganato.to/"
    ).replace("https://readmanganato.com/", "https://chapmanganato.to/")

    html = fetch_html(clean_url, referer="https://chapmanganato.to/")
    soup = BeautifulSoup(html, "html.parser")
    chapters = []

    # استخراج كل الروابط التي تشير إلى فصول في الصفحة
    ch_elements = soup.select(
        "a[href*='chapter'], .row-content-chapter a, .chapter-name, ul.row-content-chapter a, .panel-manga-chapter a"
    )

    temp_list = []
    for el in ch_elements:
        href = el.get("href", "")
        title = el.get_text(strip=True)

        if not href or not title or "chapter" not in href.lower():
            continue

        if not href.startswith("http"):
            href = urllib.parse.urljoin(clean_url, href)

        # استخراج رقم الفصل لترتيبه بدقة من الفصل 1
        num_match = re.findall(r"chapter[ -_]+(\d+(?:\.\d+)?)", href, re.I)
        if not num_match:
            num_match = re.findall(r"\d+(?:\.\d+)?", title)

        val = float(num_match[0]) if num_match else 99999.0

        if not any(c[2] == href for c in temp_list):
            temp_list.append((val, title, href))

    # الترتيب تصاعدياً من الفصل 1 إلى الأخير
    temp_list.sort(key=lambda x: x[0])

    for val, name, href in temp_list:
        chapters.append({"title": name, "url": href})

    return {"total": len(chapters), "chapters": chapters}


# ========================================================
# 3. جلب جميع صفحات الفصل عالية الدقة
# ========================================================
@app.get("/api/pages")
def get_pages(chapter_url: str):
    clean_url = chapter_url.strip()
    html = fetch_html(clean_url, referer="https://chapmanganato.to/")
    soup = BeautifulSoup(html, "html.parser")

    images = []
    for img in soup.select(
        ".container-chapter-reader img, .panel-read-story img, #vungdoc img, .read-content img"
    ):
        src = img.get("src") or img.get("data-src") or ""
        if src and "logo" not in src.lower():
            images.append(src.strip())

    return {"total_pages": len(images), "images": images}


# ========================================================
# 4. بروكسي تحميل الصور وتخطي حماية الموقع
# ========================================================
@app.get("/api/proxy-image")
def proxy_image(url: str):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Referer": "https://chapmanganato.to/",
        },
    )
    try:
        with opener.open(req, timeout=15) as resp:
            content_type = resp.headers.get("Content-Type", "image/jpeg")
            return Response(content=resp.content, media_type=content_type)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found")
