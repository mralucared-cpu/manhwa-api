import gzip
import json
import re
import ssl
import urllib.parse
import urllib.request
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

# 1. تعريف التطبيق والسماح بالاتصال
app = FastAPI(title="Global Manhwa Arabic API", version="25.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MD_API = "https://api.mangadex.org"

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE


def fetch_json(url: str):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=25, context=ssl_ctx) as resp:
            raw = resp.read()
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
        "message": "Global Manhwa API with Extensions Support is Running! 🚀",
    }


# ========================================================
# 0. قائمة الإضافات (Extensions)
# ========================================================
@app.get("/api/extensions")
def get_extensions():
    return {
        "extensions": [
            {
                "id": "mangadex",
                "name": "MangaDex (كتالوج عالمي)",
                "base_url": "https://mangadex.org",
                "lang": "en",
                "icon_url": "https://mangadex.org/favicon.ico",
                "status": "online",
            },
            {
                "id": "mgeko",
                "name": "MangaGeko (سريع ومباشر)",
                "base_url": "https://www.mgeko.cc",
                "lang": "en",
                "icon_url": "https://www.mgeko.cc/favicon.ico",
                "status": "online",
            },
        ]
    }


# ========================================================
# 1. جلب المانهوات الكورية مع الأغلفة الحقيقية
# ========================================================
@app.get("/api/mangas")
def get_mangas(page: int = 1, query: str = "", source: str = "mangadex"):
    limit = 24
    offset = max(0, (page - 1) * limit)

    params = [
        ("limit", limit),
        ("offset", offset),
        ("originalLanguage[]", "ko"),
        ("includes[]", "cover_art"),
        ("contentRating[]", "safe"),
        ("contentRating[]", "suggestive"),
        ("contentRating[]", "erotica"),
    ]

    if query.strip():
        params.append(("title", query.strip()))
    else:
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
            cover_url = (
                f"https://uploads.mangadex.org/covers/{m_id}/{cover_file}.256.jpg"
            )
        else:
            cover_url = ""

        mangas.append(
            {
                "title": title,
                "url": m_id,
                "cover_url": cover_url,
                "source": source,
            }
        )

    return {"page": page, "count": len(mangas), "source": source, "mangas": mangas}


# ========================================================
# 2. جلب جميع فصول المانهوا بالكامل
# ========================================================
@app.get("/api/chapters")
def get_chapters(manga_url: str, source: str = "mangadex"):
    clean_id = manga_url.strip().strip("/").split("/")[-1]
    chapters = []
    seen = set()

    params = [
        ("limit", 500),
        ("order[chapter]", "asc"),
        ("translatedLanguage[]", "en"),
        ("contentRating[]", "safe"),
        ("contentRating[]", "suggestive"),
        ("contentRating[]", "erotica"),
    ]

    query_string = urllib.parse.urlencode(params)
    url = f"{MD_API}/manga/{clean_id}/feed?{query_string}"

    try:
        data_json = fetch_json(url)
        data = data_json.get("data", [])
        temp_list = []

        for ch in data:
            ch_id = ch.get("id")
            attr = ch.get("attributes", {})
            ch_num = attr.get("chapter")
            ch_title = attr.get("title")

            if not ch_id:
                continue

            if ch_num:
                name = f"الفصل {ch_num}" + (
                    f" - {ch_title}" if ch_title else ""
                )
                num_match = re.findall(r"\d+(?:\.\d+)?", str(ch_num))
                val = float(num_match[0]) if num_match else 99999.0
            else:
                name = ch_title or "فصل"
                val = 99999.0

            key = f"{ch_num}" if ch_num else ch_id
            if key not in seen:
                seen.add(key)
                temp_list.append((val, name, ch_id))

        temp_list.sort(key=lambda x: x[0])
        for val, name, ch_id in temp_list:
            chapters.append({"title": name, "url": ch_id})
    except Exception as e:
        print(f"Error fetching chapters: {e}")

    return {"total": len(chapters), "source": source, "chapters": chapters}


# ========================================================
# 3. جلب جميع صفحات الفصل للترجمة
# ========================================================
@app.get("/api/pages")
def get_pages(chapter_url: str, source: str = "mangadex"):
    clean_id = chapter_url.strip().strip("/").split("/")[-1]
    data = fetch_json(f"{MD_API}/at-home/server/{clean_id}")

    base_url = data.get("baseUrl")
    chapter_data = data.get("chapter", {})
    hash_code = chapter_data.get("hash")
    files = chapter_data.get("data", [])

    images = [f"{base_url}/data/{hash_code}/{f}" for f in files]
    return {"total_pages": len(images), "source": source, "images": images}


# ========================================================
# 4. بروكسي الأغلفة والصور لتجاوز حظر MangaDex
# ========================================================
@app.get("/api/proxy-image")
def proxy_image(url: str):
    req_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://mangadex.org/",
    }
    req = urllib.request.Request(url, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as resp:
            content_type = resp.headers.get("Content-Type", "image/jpeg")
            return Response(content=resp.content, media_type=content_type)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found")
