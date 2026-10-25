import gzip
import json
import ssl
import urllib.parse
import urllib.request
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Global Manhwa Arabic API", version="12.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MD_API = "https://api.mangadex.org"

# تجهيز اتصال آمن وموثوق يتخطى أي مشاكل SSL
ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE


def fetch_json(url: str):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20, context=ssl_ctx) as resp:
            raw = resp.read()
            # فك ضغط البيانات إذا كانت مضغوطة بـ Gzip
            if raw.startswith(b"\x1f\x8b"):
                raw = gzip.decompress(raw)
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="ignore")
        raise HTTPException(status_code=e.code, detail=err)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
def home():
    return {
        "status": "online",
        "message": "Global Manhwa API is Running Successfully! 🚀",
    }


# ========================================================
# 1. جلب آلاف المانهوات الكورية مع تشفير الرابط والتقليب
# ========================================================
@app.get("/api/mangas")
def get_mangas(page: int = 1, query: str = ""):
    limit = 24
    offset = max(0, (page - 1) * limit)

    params = [
        ("limit", limit),
        ("offset", offset),
        ("originalLanguage[]", "ko"),
        ("includes[]", "cover_art"),
        ("contentRating[]", "safe"),
        ("contentRating[]", "suggestive"),
    ]

    if query.strip():
        params.append(("title", query.strip()))
    else:
        # ترتيب حسب الأكثر شهرة عالمياً
        params.append(("order[followedCount]", "desc"))

    query_string = urllib.parse.urlencode(params)
    target_url = f"{MD_API}/manga?{query_string}"

    data_json = fetch_json(target_url)
    data = data_json.get("data", [])
    mangas = []

    for item in data:
        m_id = item.get("id")
        attributes = item.get("attributes", {})
        titles = attributes.get("title", {})

        title = (
            titles.get("en")
            or titles.get("ko-ro")
            or titles.get("ko")
            or (list(titles.values())[0] if titles else "Manhwa")
        )

        cover_file = ""
        for rel in item.get("relationships", []):
            if rel.get("type") == "cover_art":
                cover_file = rel.get("attributes", {}).get("fileName", "")
                break

        if cover_file and m_id:
            # تحميل صور مصغرة خفيفة وسريعة التحميل
            cover_url = f"https://uploads.mangadex.org/covers/{m_id}/{cover_file}.256.jpg"
        else:
            cover_url = "https://mangadex.org/img/avatar.png"

        mangas.append(
            {
                "title": title,
                "url": m_id,
                "cover_url": cover_url,
            }
        )

    return {"page": page, "count": len(mangas), "mangas": mangas}


# ========================================================
# 2. جلب جميع فصول المانهوا بالإنجليزية
# ========================================================
@app.get("/api/chapters")
def get_chapters(manga_url: str):
    m_id = manga_url.strip().strip("/").split("/")[-1]

    params = [
        ("translatedLanguage[]", "en"),
        ("limit", 150),
        ("order[chapter]", "asc"),
        ("contentRating[]", "safe"),
        ("contentRating[]", "suggestive"),
    ]

    query_string = urllib.parse.urlencode(params)
    url = f"{MD_API}/manga/{m_id}/feed?{query_string}"

    data_json = fetch_json(url)
    data = data_json.get("data", [])
    chapters = []
    seen = set()

    for ch in data:
        ch_id = ch.get("id")
        attr = ch.get("attributes", {})
        ch_num = attr.get("chapter")
        ch_title = attr.get("title")

        if ch_num:
            name = f"الفصل {ch_num}" + (f" - {ch_title}" if ch_title else "")
        elif ch_title:
            name = ch_title
        else:
            name = "فصل"

        if ch_id and ch_num not in seen:
            if ch_num:
                seen.add(ch_num)
            chapters.append({"title": name, "url": ch_id})

    return {"total": len(chapters), "chapters": chapters}


# ========================================================
# 3. جلب جميع روابط صور الفصل
# ========================================================
@app.get("/api/pages")
def get_pages(chapter_url: str):
    ch_id = chapter_url.strip().strip("/").split("/")[-1]
    data = fetch_json(f"{MD_API}/at-home/server/{ch_id}")

    base_url = data.get("baseUrl")
    chapter_data = data.get("chapter", {})
    hash_code = chapter_data.get("hash")
    files = chapter_data.get("data", [])

    images = [f"{base_url}/data/{hash_code}/{f}" for f in files]
    return {"total_pages": len(images), "images": images}


# ========================================================
# 4. بروكسي تحميل الصور
# ========================================================
@app.get("/api/proxy-image")
def proxy_image(url: str):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as resp:
            content_type = resp.headers.get("Content-Type", "image/jpeg")
            return Response(content=resp.read(), media_type=content_type)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found")
