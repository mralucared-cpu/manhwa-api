import gzip
import json
import re
import ssl
import urllib.parse
import urllib.request
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Complete Manhwa Arabic API", version="17.0.0")

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
    mangas = []

    # استخراج عناصر المانجا عبر بايثون الصافي بدون الحاجة لمكتبة bs4
    cards = re.findall(
        r'<div class="(?:content-genres-item|search-story-item)"[\s\S]*?</div>\s*</div>',
        html,
    )

    for block in cards:
        title_match = re.search(
            r'<a[^>]*class="[^"]*genres-item-name[^"]*"[^>]*href="([^"]+)"[^>]*title="([^"]+)"',
            block,
        )
        if not title_match:
            title_match = re.search(
                r'<h3[^>]*><a[^>]*href="([^"]+)"[^>]*title="([^"]+)"', block
            )
        if not title_match:
            title_match = re.search(
                r'<a[^>]*href="([^"]*manga-[^"]*)"[^>]*title="([^"]+)"', block
            )

        img_match = re.search(r'<img[^>]*(?:src|data-src)="([^"]+)"', block)
        chap_match = re.search(
            r'<a[^>]*class="[^"]*genres-item-chap[^"]*"[^>]*>([^<]+)</a>',
            block,
        )

        if title_match:
            href = title_match.group(1).strip()
            title = title_match.group(2).strip()
            cover = img_match.group(1).strip() if img_match else ""
            last_ch = (
                chap_match.group(1).strip() if chap_match else "الفصل متاح"
            )

            # توجيه مباشر إلى سيرفر الفصول
            href = href.replace(
                "https://manganato.com/manga-",
                "https://chapmanganato.to/manga-",
            )

            if not any(m["url"] == href for m in mangas):
                mangas.append(
                    {
                        "title": title,
                        "url": href,
                        "cover_url": cover,
                        "latestChapter": last_ch,
                    }
                )

    # خطة بديلة لضمان عدم خلو القائمة أبداً
    if not mangas:
        for m in re.finditer(
            r'<a[^>]*href="([^"]*manga-[^"]*)"[^>]*title="([^"]+)"[^>]*>',
            html,
        ):
            href = m.group(1).replace(
                "https://manganato.com/manga-",
                "https://chapmanganato.to/manga-",
            )
            title = m.group(2).strip()
            if not any(x["url"] == href for x in mangas):
                mangas.append(
                    {
                        "title": title,
                        "url": href,
                        "cover_url": "https://manganato.com/favicon.ico",
                        "latestChapter": "فصول كاملة",
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

    clean_url = clean_url.replace(
        "https://manganato.com/", "https://chapmanganato.to/"
    ).replace("https://readmanganato.com/", "https://chapmanganato.to/")

    html = fetch_html(clean_url, referer="https://chapmanganato.to/")
    chapters = []
    temp_list = []

    # استخراج كل الروابط التي تحتوي على كلمة chapter من الفصل 1
    chapter_matches = re.finditer(
        r'<a[^>]*class="[^"]*chapter-name[^"]*"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>',
        html,
    )
    for m in chapter_matches:
        href = m.group(1).strip()
        title = m.group(2).strip()

        num_match = re.findall(r"chapter[ -_]+(\d+(?:\.\d+)?)", href, re.I)
        if not num_match:
            num_match = re.findall(r"\d+(?:\.\d+)?", title)
        val = float(num_match[0]) if num_match else 99999.0

        if not any(c[2] == href for c in temp_list):
            temp_list.append((val, title, href))

    # خطة استخراج بديلة لجميع أشكال الروابط
    if not temp_list:
        for m in re.finditer(
            r'<a[^>]*href="([^"]*chapter[^"]*)"[^>]*>([^<]+)</a>', html
        ):
            href = m.group(1).strip()
            title = m.group(2).strip()
            if "manga-" in href and len(title) > 0:
                num_match = re.findall(r"\d+(?:\.\d+)?", href)
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

    reader_block = re.search(
        r'<div[^>]*class="[^"]*(?:container-chapter-reader|panel-read-story)[^"]*"[\s\S]*?</div>',
        html,
    )
    block = reader_block.group(0) if reader_block else html

    img_matches = re.findall(
        r'<img[^>]*(?:src|data-src)="([^"]+)"', block, re.I
    )
    images = [
        src.strip()
        for src in img_matches
        if "logo" not in src.lower() and src.strip().startswith("http")
    ]

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
