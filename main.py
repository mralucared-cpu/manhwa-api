import urllib.parse
from curl_cffi import requests
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Global Manhwa Arabic API", version="10.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MD_API = "https://api.mangadex.org"
session = requests.Session(impersonate="chrome120")


@app.get("/")
def home():
    return {
        "status": "online",
        "message": "Global Manhwa API is Running Successfully! 🚀",
    }


# ========================================================
# 1. جلب آلاف المانهوات الكورية الأكثر شهرة مع التقليب
# ========================================================
@app.get("/api/mangas")
def get_mangas(page: int = 1, query: str = ""):
    limit = 24
    offset = max(0, (page - 1) * limit)

    if query.strip():
        encoded_q = urllib.parse.quote(query.strip())
        target_url = (
            f"{MD_API}/manga?limit={limit}&offset={offset}"
            f"&originalLanguage[]=ko&includes[]=cover_art"
            f"&contentRating[]=safe&contentRating[]=suggestive&title={encoded_q}"
        )
    else:
        target_url = (
            f"{MD_API}/manga?limit={limit}&offset={offset}"
            f"&originalLanguage[]=ko&includes[]=cover_art"
            f"&contentRating[]=safe&contentRating[]=suggestive&order[followedCount]=desc"
        )

    try:
        resp = session.get(target_url, timeout=20)
        if resp.status_code != 200:
            raise HTTPException(
                status_code=resp.status_code, detail="MangaDex error"
            )

        data = resp.json().get("data", [])
        mangas = []

        for item in data:
            m_id = item.get("id")
            attributes = item.get("attributes", {})

            # استخراج العنوان
            titles = attributes.get("title", {})
            title = (
                titles.get("en")
                or titles.get("ko")
                or (list(titles.values())[0] if titles else "Manhwa")
            )

            # استخراج الغلاف
            cover_file = ""
            for rel in item.get("relationships", []):
                if rel.get("type") == "cover_art":
                    cover_file = rel.get("attributes", {}).get("fileName", "")
                    break

            if cover_file and m_id:
                cover_url = (
                    f"https://uploads.mangadex.org/covers/{m_id}/{cover_file}"
                )
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========================================================
# 2. جلب جميع فصول المانهوا بالإنجليزية
# ========================================================
@app.get("/api/chapters")
def get_chapters(manga_url: str):
    m_id = manga_url.strip().strip("/").split("/")[-1]
    url = (
        f"{MD_API}/manga/{m_id}/feed?translatedLanguage[]=en"
        f"&limit=150&order[chapter]=asc&contentRating[]=safe&contentRating[]=suggestive"
    )

    try:
        resp = session.get(url, timeout=20)
        if resp.status_code != 200:
            raise HTTPException(
                status_code=500, detail="Failed to fetch feed"
            )

        data = resp.json().get("data", [])
        chapters = []
        seen = set()

        for ch in data:
            ch_id = ch.get("id")
            attr = ch.get("attributes", {})
            ch_num = attr.get("chapter")
            ch_title = attr.get("title")

            if ch_num:
                name = (
                    f"الفصل {ch_num}" + (f" - {ch_title}" if ch_title else "")
                )
            elif ch_title:
                name = ch_title
            else:
                name = "فصل"

            if ch_id and ch_num not in seen:
                if ch_num:
                    seen.add(ch_num)
                chapters.append({"title": name, "url": ch_id})

        return {"total": len(chapters), "chapters": chapters}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========================================================
# 3. جلب جميع روابط صور الفصل
# ========================================================
@app.get("/api/pages")
def get_pages(chapter_url: str):
    ch_id = chapter_url.strip().strip("/").split("/")[-1]

    try:
        resp = session.get(f"{MD_API}/at-home/server/{ch_id}", timeout=20)
        if resp.status_code != 200:
            raise HTTPException(
                status_code=500, detail="Failed to fetch pages"
            )

        data = resp.json()
        base_url = data.get("baseUrl")
        chapter_data = data.get("chapter", {})
        hash_code = chapter_data.get("hash")
        files = chapter_data.get("data", [])

        images = [f"{base_url}/data/{hash_code}/{f}" for f in files]
        return {"total_pages": len(images), "images": images}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========================================================
# 4. بروكسي تحميل الصور
# ========================================================
@app.get("/api/proxy-image")
def proxy_image(url: str):
    try:
        resp = session.get(url, timeout=15)
        content_type = resp.headers.get("content-type", "image/jpeg")
        return Response(content=resp.content, media_type=content_type)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found")
