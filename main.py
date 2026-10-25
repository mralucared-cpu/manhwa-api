import gzip
import json
import re
import ssl
import urllib.parse
import urllib.request
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Complete Manhwa Arabic API", version="21.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SOURCE_URL = "https://mangaclash.com"

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE


def fetch_html(url: str, referer: str = "https://mangaclash.com/"):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": referer,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=25, context=ssl_ctx) as resp:
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
        encoded = urllib.parse.quote(query)
        target_url = f"{SOURCE_URL}/page/{page}/?s={encoded}&post_type=wp-manga"
    else:
        # ترتيب حسب المشاهدات والأكثر شعبية
        target_url = f"{SOURCE_URL}/manga-genre/manhwa/page/{page}/?m_orderby=views"

    html = fetch_html(target_url)
    mangas = []

    # استخراج الكروت بواسطة بايثون المدمج
    items = re.findall(
        r'<div[^>]*class="[^"]*(?:page-item-detail|badge-pos-1)[^"]*"[\s\S]*?</div>\s*</div>\s*</div>',
        html,
    )
    if not items:
        items = re.findall(
            r'<div[^>]*class="[^"]*item-thumb[^"]*"[\s\S]*?</div>\s*</div>',
            html,
        )

    for block in items:
        # استخراج الرابط والعنوان
        title_match = re.search(
            r'<h3[^>]*class="[^"]*h5[^"]*"[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>([^<]+)</a>',
            block,
        )
        if not title_match:
            title_match = re.search(
                r'<a[^>]*href="([^"]+/manga/[^"]+/)"[^>]*title="([^"]+)"',
                block,
            )
        if not title_match:
            title_match = re.search(
                r'<a[^>]*href="([^"]+/manga/[^"]+/)"[^>]*>([^<]+)</a>', block
            )

        # استخراج صورة الغلاف الأصلية
        img_match = re.search(r'<img[^>]*(?:data-src|src)="([^"]+)"', block)

        # استخراج آخر فصل
        chap_match = re.search(
            r'<span[^>]*class="[^"]*chapter[^"]*"[^>]*>\s*<a[^>]*href="[^"]*"[^>]*>([^<]+)</a>',
            block,
        )

        if title_match:
            href = title_match.group(1).strip()
            title = title_match.group(2).strip()
            cover = img_match.group(1).strip() if img_match else ""
            last_ch = (
                chap_match.group(1).strip() if chap_match else "فصول كاملة"
            )

            # تنظيف رابط الصورة
            if cover.startswith("//"):
                cover = "https:" + cover

            if title and href and not any(m["url"] == href for m in mangas):
                mangas.append(
                    {
                        "title": title,
                        "url": href,
                        "cover_url": cover,
                        "latestChapter": last_ch,
                    }
                )

    # خطة بديلة احتياطية لضمان عدم خلو القائمة
    if not mangas:
        matches = re.finditer(
            r'<a[^>]*href="([^"]+/manga/[^"/]+/)"[^>]*>\s*<img[^>]*(?:data-src|src)="([^"]+)"[^>]*alt="([^"]+)"',
            html,
        )
        for m in matches:
            href = m.group(1).strip()
            cover = m.group(2).strip()
            title = m.group(3).strip()
            if not any(x["url"] == href for x in mangas):
                mangas.append(
                    {
                        "title": title,
                        "url": href,
                        "cover_url": cover,
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
    if not clean_url.endswith("/"):
        clean_url += "/"

    # موقع MangaClash يضع قائمته الكاملة عبر طلب ajax الفصول لضمان جلب كل الفصول
    ajax_url = f"{clean_url}ajax/chapters/"
    try:
        html = fetch_html(ajax_url, referer=clean_url)
    except Exception:
        html = fetch_html(clean_url, referer=clean_url)

    chapters = []
    temp_list = []

    matches = re.finditer(
        r'<li[^>]*class="[^"]*wp-manga-chapter[^"]*"[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>([^<]+)</a>',
        html,
    )
    for m in matches:
        href = m.group(1).strip()
        title = m.group(2).strip()

        # استخراج رقم الفصل لترتيبه تصاعدياً من الفصل 1
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
# 3. جلب جميع صفحات الفصل عالية الدقة للقراءة والترجمة
# ========================================================
@app.get("/api/pages")
def get_pages(chapter_url: str):
    clean_url = chapter_url.strip()
    html = fetch_html(clean_url, referer=clean_url)

    img_matches = re.findall(
        r'<img[^>]*(?:data-src|src)="([^"]+)"[^>]*class="[^"]*wp-manga-chapter-img[^"]*"',
        html,
    )
    if not img_matches:
        img_matches = re.findall(
            r'<div[^>]*class="[^"]*page-break[^"]*"[\s\S]*?<img[^>]*(?:data-src|src)="([^"]+)"',
            html,
        )

    images = [
        src.strip()
        for src in img_matches
        if "logo" not in src.lower() and src.strip().startswith("http")
    ]

    return {"total_pages": len(images), "images": images}


# ========================================================
# 4. بروكسي تحميل الصور بدون أي حظر
# ========================================================
@app.get("/api/proxy-image")
def proxy_image(url: str):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": SOURCE_URL,
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as resp:
            content_type = resp.headers.get("Content-Type", "image/jpeg")
            return Response(content=resp.read(), media_type=content_type)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found")
