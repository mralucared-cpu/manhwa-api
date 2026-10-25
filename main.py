import gzip
import json
import re
import ssl
import urllib.parse
import urllib.request
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Global Manhwa Arabic API", version="13.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MD_API = "https://api.mangadex.org"
COMICK_API = "https://api.comick.fun"

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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
def home():
    return {
        "status": "online",
        "message": "Global Complete Manhwa API is Running Successfully! 🚀",
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
# 2. جلب جميع فصول المانهوا من الفصل 1 بترتيب رقمي كامل
# ========================================================
@app.get("/api/chapters")
def get_chapters(manga_url: str):
    clean_id = manga_url.strip().strip("/").split("/")[-1]

    # إذا كان معرف فصل من Comick
    if clean_id.startswith("cmk_"):
        comic_hid = clean_id.replace("cmk_", "")
        return fetch_comick_chapters(comic_hid)

    chapters = []

    # 1. محاولة جلب الفصول الكاملة من MangaDex Aggregate
    try:
        agg_url = f"{MD_API}/manga/{clean_id}/aggregate?translatedLanguage[]=en"
        agg_data = fetch_json(agg_url)
        volumes = agg_data.get("volumes", {})

        temp_list = []
        for vol in volumes.values():
            for ch_num, ch_data in vol.get("chapters", {}).items():
                ch_id = ch_data.get("id")
                # استخراج الرقم لترتيب تصاعدي صحيح
                num_match = re.findall(r"\d+(?:\.\d+)?", str(ch_num))
                val = float(num_match[0]) if num_match else 99999.0
                temp_list.append((val, f"الفصل {ch_num}", ch_id))

        temp_list.sort(key=lambda x: x[0])

        for val, name, ch_id in temp_list:
            if not any(c["url"] == ch_id for c in chapters):
                chapters.append({"title": name, "url": ch_id})
    except Exception:
        pass

    # 2. إذا كانت المانهوا تبدأ بعد الفصل 5 (محذوف بدايتها)، نسحب الفصول من المصدر البديل التلقائي
    first_chapter_num = 99999.0
    if chapters:
        first_match = re.findall(r"\d+(?:\.\d+)?", chapters[0]["title"])
        if first_match:
            first_chapter_num = float(first_match[0])

    if not chapters or first_chapter_num > 5.0:
        try:
            # البحث عن اسم المانهوا في Comick لجلب الفصول من 1
            manga_info = fetch_json(f"{MD_API}/manga/{clean_id}")
            titles = manga_info.get("data", {}).get("attributes", {}).get("title", {})
            search_title = titles.get("en") or list(titles.values())[0]

            encoded_title = urllib.parse.quote(search_title)
            comick_search = fetch_json(f"{COMICK_API}/v1.0/search?q={encoded_title}&limit=1")
            if comick_search:
                hid = comick_search[0].get("hid")
                cmk_res = fetch_comick_chapters(hid)
                if cmk_res.get("chapters"):
                    return cmk_res
        except Exception:
            pass

    return {"total": len(chapters), "chapters": chapters}


def fetch_comick_chapters(hid: str):
    url = f"{COMICK_API}/comic/{hid}/chapters?lang=en&limit=300&page=1"
    data = fetch_json(url)
    raw_chapters = data.get("chapters", [])
    chapters = []
    seen = set()

    temp_list = []
    for ch in raw_chapters:
        ch_num = ch.get("chap")
        ch_id = ch.get("hid")
        title = ch.get("title")

        if ch_num:
            name = f"الفصل {ch_num}" + (f" - {title}" if title else "")
            num_match = re.findall(r"\d+(?:\.\d+)?", str(ch_num))
            val = float(num_match[0]) if num_match else 99999.0
        else:
            name = title or "فصل"
            val = 99999.0

        if ch_id and ch_num not in seen:
            if ch_num:
                seen.add(ch_num)
            temp_list.append((val, name, f"cmk_ch_{ch_id}"))

    temp_list.sort(key=lambda x: x[0])
    for val, name, ch_id in temp_list:
        chapters.append({"title": name, "url": ch_id})

    return {"total": len(chapters), "chapters": chapters}


# ========================================================
# 3. جلب روابط صور الفصل
# ========================================================
@app.get("/api/pages")
def get_pages(chapter_url: str):
    clean_id = chapter_url.strip().strip("/").split("/")[-1]

    # إذا كان فصلاً من المصدر المكتمل Comick
    if clean_id.startswith("cmk_ch_"):
        hid = clean_id.replace("cmk_ch_", "")
        data = fetch_json(f"{COMICK_API}/chapter/{hid}")
        images_data = data.get("chapter", {}).get("images", [])
        images = [f"https://meo.comick.pictures/{img.get('b2key')}" for img in images_data if img.get("b2key")]
        return {"total_pages": len(images), "images": images}

    # المصدر الأساسي MangaDex
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
            ),
            "Referer": "https://comick.io/",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as resp:
            content_type = resp.headers.get("Content-Type", "image/jpeg")
            return Response(content=resp.read(), media_type=content_type)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found")
