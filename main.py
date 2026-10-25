import gzip
import json
import re
import ssl
import urllib.parse
import urllib.request
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Multi-Source Manhwa Arabic API", version="19.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MD_API = "https://api.mangadex.org"
PILL_URL = "https://mangapill.com"

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE


def fetch_raw(url: str, referer: str = ""):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
    }
    if referer:
        headers["Referer"] = referer

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=25, context=ssl_ctx) as resp:
            raw = resp.read()
            if raw.startswith(b"\x1f\x8b"):
                raw = gzip.decompress(raw)
            return raw
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def fetch_json(url: str):
    raw = fetch_raw(url)
    return json.loads(raw.decode("utf-8"))


def fetch_html(url: str, referer: str = ""):
    raw = fetch_raw(url, referer)
    return raw.decode("utf-8", errors="ignore")


@app.get("/")
def home():
    return {
        "status": "online",
        "message": "Multi-Source Manhwa API is Running (MangaDex + Mangapill)! 🚀",
    }


# ========================================================
# 1. جلب المانهوات من المصدرين (MangaDex + المصدر المكتمل)
# ========================================================
@app.get("/api/mangas")
def get_mangas(page: int = 1, query: str = ""):
    all_mangas = []

    # --- المصدر 1: MangaDex ---
    try:
        limit = 15
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

        q_str = urllib.parse.urlencode(params)
        data = fetch_json(f"{MD_API}/manga?{q_str}").get("data", [])

        for item in data:
            m_id = item.get("id")
            attr = item.get("attributes", {})
            titles = attr.get("title", {})
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

            cover_url = (
                f"https://uploads.mangadex.org/covers/{m_id}/{cover_file}.256.jpg"
                if cover_file
                else "https://mangadex.org/img/avatar.png"
            )

            all_mangas.append(
                {
                    "title": f"[MD] {title}",
                    "url": f"md:{m_id}",
                    "cover_url": cover_url,
                }
            )
    except Exception:
        pass

    # --- المصدر 2: Mangapill (فصول كاملة من الفصل 1) ---
    try:
        if query.strip():
            encoded_q = urllib.parse.quote(query.strip())
            pill_url = f"{PILL_URL}/search?q={encoded_q}&page={page}"
        else:
            pill_url = f"{PILL_URL}/mangas/new?page={page}"

        html = fetch_html(pill_url, referer=PILL_URL)

        # استخراج البطاقات بواسطة Regex فائق السرعة
        cards = re.findall(
            r'<div[^>]*class="[^"]*border[^"]*"[\s\S]*?</div>\s*</div>', html
        )
        if not cards:
            cards = re.findall(
                r'<a[^>]*href="(/manga/\d+/[^"]+)"[\s\S]*?</a>', html
            )

        for block in cards:
            link_match = re.search(
                r'<a[^>]*href="(/manga/\d+/[^"]+)"[^>]*>([^<]+)</a>', block
            )
            img_match = re.search(r'<img[^>]*(?:data-src|src)="([^"]+)"', block)

            if link_match:
                href = link_match.group(1).strip()
                title = link_match.group(2).strip()
                cover = img_match.group(1).strip() if img_match else ""

                if not cover.startswith("http"):
                    cover = urllib.parse.urljoin(PILL_URL, cover)

                all_mangas.append(
                    {
                        "title": f"[كاملة] {title}",
                        "url": f"pill:{href}",
                        "cover_url": cover,
                    }
                )
    except Exception:
        pass

    return {"page": page, "count": len(all_mangas), "mangas": all_mangas}


# ========================================================
# 2. جلب فصول المانهوا حسب المصدر المختار
# ========================================================
@app.get("/api/chapters")
def get_chapters(manga_url: str):
    clean_url = manga_url.strip()
    chapters = []

    # إذا كانت من المصدر الثاني (Mangapill - تبدأ من الفصل 1)
    if clean_url.startswith("pill:"):
        path = clean_url.replace("pill:", "")
        target_url = urllib.parse.urljoin(PILL_URL, path)
        html = fetch_html(target_url, referer=PILL_URL)

        matches = re.finditer(
            r'<a[^>]*href="(/chapters/\d+-[^"]+)"[^>]*>([^<]+)</a>', html
        )
        temp_list = []
        for m in matches:
            href = m.group(1).strip()
            title = m.group(2).strip()
            num_match = re.findall(r"\d+(?:\.\d+)?", title)
            val = float(num_match[0]) if num_match else 99999.0
            temp_list.append((val, title, f"pill_ch:{href}"))

        # الترتيب من الفصل 1 تصاعدياً
        temp_list.sort(key=lambda x: x[0])
        for val, name, href in temp_list:
            chapters.append({"title": name, "url": href})

        return {"total": len(chapters), "chapters": chapters}

    # إذا كانت من MangaDex
    m_id = clean_url.replace("md:", "").strip("/").split("/")[-1]
    params = [
        ("limit", 500),
        ("order[chapter]", "asc"),
        ("contentRating[]", "safe"),
        ("contentRating[]", "suggestive"),
        ("translatedLanguage[]", "en"),
    ]
    q_str = urllib.parse.urlencode(params)
    feed_url = f"{MD_API}/manga/{m_id}/feed?{q_str}"

    try:
        data = fetch_json(feed_url).get("data", [])
        temp_list = []
        seen = set()

        for ch in data:
            ch_id = ch.get("id")
            attr = ch.get("attributes", {})
            ch_num = attr.get("chapter")
            ch_title = attr.get("title")

            if not ch_id:
                continue

            if ch_num:
                name = (
                    f"الفصل {ch_num}" + (f" - {ch_title}" if ch_title else "")
                )
                num_match = re.findall(r"\d+(?:\.\d+)?", str(ch_num))
                val = float(num_match[0]) if num_match else 99999.0
            else:
                name = ch_title or "فصل"
                val = 99999.0

            key = f"{ch_num}" if ch_num else ch_id
            if key not in seen:
                seen.add(key)
                temp_list.append((val, name, f"md_ch:{ch_id}"))

        temp_list.sort(key=lambda x: x[0])
        for val, name, ch_id in temp_list:
            chapters.append({"title": name, "url": ch_id})
    except Exception:
        pass

    return {"total": len(chapters), "chapters": chapters}


# ========================================================
# 3. جلب جميع صفحات الفصل
# ========================================================
@app.get("/api/pages")
def get_pages(chapter_url: str):
    clean_url = chapter_url.strip()

    # إذا كان فصلاً من المصدر الثاني (Mangapill)
    if clean_url.startswith("pill_ch:"):
        path = clean_url.replace("pill_ch:", "")
        target_url = urllib.parse.urljoin(PILL_URL, path)
        html = fetch_html(target_url, referer=PILL_URL)

        img_matches = re.findall(r'<img[^>]*data-src="([^"]+)"', html)
        if not img_matches:
            img_matches = re.findall(
                r'<img[^>]*class="[^"]*js-page[^"]*"[^>]*src="([^"]+)"', html
            )

        images = [
            src.strip()
            for src in img_matches
            if "logo" not in src.lower() and src.strip().startswith("http")
        ]
        return {"total_pages": len(images), "images": images}

    # إذا كان فصلاً من MangaDex
    ch_id = clean_url.replace("md_ch:", "").strip("/").split("/")[-1]
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
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Referer": PILL_URL,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as resp:
            content_type = resp.headers.get("Content-Type", "image/jpeg")
            return Response(content=resp.read(), media_type=content_type)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found")
