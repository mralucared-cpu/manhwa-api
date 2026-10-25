import gzip
import json
import re
import ssl
import urllib.parse
import urllib.request
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Global Manhwa Arabic API", version="14.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MD_API = "https://api.mangadex.org"

# اتصال آمن يتجاوز مشاكل الشهادات وفك الضغط
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
        with urllib.request.urlopen(req, timeout=25, context=ssl_ctx) as resp:
            raw = resp.read()
            if raw.startswith(b"\x1f\x8b"):
                raw = gzip.decompress(raw)
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="ignore")
        raise HTTPException(status_code=e.code, detail=err_msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
def home():
    return {
        "status": "online",
        "message": "Global Manhwa API is Running with Full Chapters! 🚀",
    }


# ========================================================
# 1. جلب آلاف المانهوات الكورية مع التقليب
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
# 2. جلب جميع فصول المانهوا بالكامل من الفصل 1 تصاعدياً
# ========================================================
@app.get("/api/chapters")
def get_chapters(manga_url: str):
    clean_id = manga_url.strip().strip("/").split("/")[-1]
    chapters = []
    seen_chapters = set()

    # 1. استخدام مسار الفيد المشفر لجلب الفصول الحقيقية حتى 500 فصل
    try:
        feed_params = [
            ("translatedLanguage[]", "en"),
            ("limit", 500),
            ("order[chapter]", "asc"),
            ("contentRating[]", "safe"),
            ("contentRating[]", "suggestive"),
            ("includeExternalUrl", 0),  # استبعاد الروابط الخارجية التي لا تحتوي على صور
        ]
        feed_url = f"{MD_API}/manga/{clean_id}/feed?{urllib.parse.urlencode(feed_params)}"
        feed_data = fetch_json(feed_url)
        raw_list = feed_data.get("data", [])

        temp_list = []
        for ch in raw_list:
            ch_id = ch.get("id")
            attr = ch.get("attributes", {})
            ch_num = attr.get("chapter")
            ch_title = attr.get("title")

            if not ch_id:
                continue

            # استخراج الرقم لترتيب تصاعدي دقيق
            if ch_num:
                num_match = re.findall(r"\d+(?:\.\d+)?", str(ch_num))
                val = float(num_match[0]) if num_match else 99999.0
                name = f"الفصل {ch_num}" + (f" - {ch_title}" if ch_title else "")
            else:
                val = 99999.0
                name = ch_title or "فصل بدون رقم"

            # منع تكرار نفس رقم الفصل
            key = f"{ch_num}" if ch_num else ch_id
            if key not in seen_chapters:
                seen_chapters.add(key)
                temp_list.append((val, name, ch_id))

        temp_list.sort(key=lambda x: x[0])
        for val, name, ch_id in temp_list:
            chapters.append({"title": name, "url": ch_id})
    except Exception:
        pass

    # 2. إذا لم يعثر على فصول عبر feed، نجرب Aggregate المشفر كخطة بديلة
    if not chapters:
        try:
            agg_params = [("translatedLanguage[]", "en")]
            agg_url = f"{MD_API}/manga/{clean_id}/aggregate?{urllib.parse.urlencode(agg_params)}"
            agg_data = fetch_json(agg_url)
            volumes = agg_data.get("volumes", {})

            temp_list = []
            for vol in volumes.values():
                for ch_k, ch_v in vol.get("chapters", {}).items():
                    ch_id = ch_v.get("id")
                    num_match = re.findall(r"\d+(?:\.\d+)?", str(ch_k))
                    val = float(num_match[0]) if num_match else 99999.0
                    temp_list.append((val, f"الفصل {ch_k}", ch_id))

            temp_list.sort(key=lambda x: x[0])
            for val, name, ch_id in temp_list:
                if not any(c["url"] == ch_id for c in chapters):
                    chapters.append({"title": name, "url": ch_id})
        except Exception:
            pass

    return {"total": len(chapters), "chapters": chapters}


# ========================================================
# 3. جلب جميع روابط صور الفصل
# ========================================================
@app.get("/api/pages")
def get_pages(chapter_url: str):
    clean_id = chapter_url.strip().strip("/").split("/")[-1]
    data = fetch_json(f"{MD_API}/at-home/server/{clean_id}")

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
