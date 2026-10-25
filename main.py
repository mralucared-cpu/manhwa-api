# ========================================================
# 1. جلب المانهوات الكورية (مع أغلفة مضمونة)
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

        # رابط الغلاف
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
# 2. جلب جميع فصول المانهوا بدون تقييد صارم
# ========================================================
@app.get("/api/chapters")
def get_chapters(manga_url: str, source: str = "mangadex"):
    clean_id = manga_url.strip().strip("/").split("/")[-1]
    chapters = []
    seen = set()

    # طلب الفصول مع دعم عدة لغات إنكليزية شائعة
    params = [
        ("limit", 500),
        ("order[chapter]", "asc"),
        ("contentRating[]", "safe"),
        ("contentRating[]", "suggestive"),
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
            ch_lang = attr.get("translatedLanguage")

            # نأخذ الفصول الإنجليزية فقط
            if ch_lang != "en":
                continue

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
