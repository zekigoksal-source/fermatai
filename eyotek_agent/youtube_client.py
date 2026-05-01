"""
YouTube Data API v3 Client (Oturum 25.38)
==========================================
Konu bazlı kaliteli Türkçe ders videosu arama.

API docs: https://developers.google.com/youtube/v3/docs/search/list
Quota: 10K units/gün ücretsiz. search.list = 100 unit. Yani 100 arama/gün.

ENV:
  YOUTUBE_API_KEY  — Google Cloud Console'dan ücretsiz

Whitelist kanallar (Türkçe YKS): Tonguç, Hocalara Geldik, Benim Hocam, 3D Lise, MEB, Final Akademi vb.

Kullanım:
  from youtube_client import search_videos
  res = await search_videos("türev grafik yorumu", ders="Matematik")
  # res = [{title, channel, video_id, url, embed_block, duration_min}]
"""

import os
import re
from datetime import datetime, timezone

import httpx
from loguru import logger

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
YT_TIMEOUT = 12.0

# Türkçe YKS kanal whitelist (tercih sırası)
TR_YKS_CHANNELS_WHITELIST = {
    # Channel ID'leri tahminden ziyade isimlerle filtre yapacağız
    # search.list'in channelId parametresi var ama whitelist sayısı çok
    # Bu yüzden post-filter yapıyoruz title/channelTitle üzerinden
}

TR_YKS_CHANNELS_PREFER = [
    "tonguç", "tonguc",
    "hocalara geldik",
    "benim hocam",
    "3d lise",
    "konu anlatımı",
    "rehber matematik",
    "fizik öğretmeni",
    "kimya öğretmeni",
    "bil koleji",
    "limit yayınları",
    "fdd hoca",
    "soner hoca",
    "ayhan hoca",
    "barış hoca",
    "selin hoca",
    "mert hoca",
]

# Spam/zayıf kanallardan kaçın
TR_YKS_CHANNELS_AVOID = [
    "shorts", "tiktok", "duett",
]


def is_available() -> bool:
    return bool(YOUTUBE_API_KEY)


def _parse_iso8601_duration(iso: str) -> int:
    """ISO 8601 duration (PT15M30S) → toplam saniye."""
    if not iso or not iso.startswith("PT"):
        return 0
    h = m = s = 0
    iso = iso[2:]
    mh = re.match(r"(\d+)H", iso)
    if mh:
        h = int(mh.group(1))
        iso = iso[mh.end():]
    mm = re.match(r"(\d+)M", iso)
    if mm:
        m = int(mm.group(1))
        iso = iso[mm.end():]
    ms = re.match(r"(\d+)S", iso)
    if ms:
        s = int(ms.group(1))
    return h * 3600 + m * 60 + s


def _score_video(item: dict, prefer_keywords: list[str]) -> float:
    """Video puanla — kanal whitelist + view count + duration uygunluğu."""
    snippet = item.get("snippet", {})
    statistics = item.get("statistics", {})
    content_details = item.get("contentDetails", {})

    channel = (snippet.get("channelTitle") or "").lower()
    title = (snippet.get("title") or "").lower()

    score = 0.0

    # 1. Kanal whitelist
    for kw in TR_YKS_CHANNELS_PREFER:
        if kw in channel:
            score += 50
            break
    for kw in TR_YKS_CHANNELS_AVOID:
        if kw in channel or kw in title:
            score -= 100

    # 2. View count (logaritmik)
    views = int(statistics.get("viewCount", 0))
    if views > 0:
        import math
        score += min(20, math.log10(views) * 4)

    # 3. Like ratio
    likes = int(statistics.get("likeCount", 0))
    if views > 0 and likes > 0:
        ratio = likes / views
        score += min(10, ratio * 1000)

    # 4. Duration: 5-30dk ideal, <5 ya çok kısa, >30 çok uzun
    dur_sec = _parse_iso8601_duration(content_details.get("duration", ""))
    dur_min = dur_sec // 60
    if 5 <= dur_min <= 30:
        score += 10
    elif dur_min < 2 or dur_min > 60:
        score -= 20

    # 5. prefer_keywords (öğrenci sorduğu konuya yakınlık)
    for kw in prefer_keywords:
        kw_l = kw.lower()
        if kw_l in title:
            score += 5

    return score


def make_embed_block(video_id: str, title: str = "") -> str:
    """YouTube embed block — frontend'e direkt yapıştırılabilir."""
    safe_title = (title or "Video").replace('"', "'")
    return (
        f'<div class="yt-embed">\n'
        f'<iframe width="100%" height="315" '
        f'src="https://www.youtube.com/embed/{video_id}" '
        f'title="{safe_title}" frameborder="0" '
        f'allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" '
        f'allowfullscreen></iframe>\n'
        f'</div>'
    )


async def search_videos(konu: str, ders: str = "", limit: int = 3,
                        max_duration_min: int = 35) -> dict:
    """
    YouTube'da Türkçe YKS videosu ara, kalite skoruna göre sırala.

    Returns: {success, videos: [...]}
    """
    if not is_available():
        return {"success": False, "error": "YOUTUBE_API_KEY .env'de tanımsız"}

    # Sorgu: "X konu anlatımı YKS"
    query = f"{konu} konu anlatımı YKS" if not ders else f"{ders} {konu} konu anlatımı"

    try:
        async with httpx.AsyncClient(timeout=YT_TIMEOUT) as client:
            # 1. Search
            search_url = "https://www.googleapis.com/youtube/v3/search"
            r = await client.get(search_url, params={
                "key": YOUTUBE_API_KEY,
                "q": query,
                "part": "snippet",
                "type": "video",
                "maxResults": 15,  # post-filter ile en iyi N'i al
                "relevanceLanguage": "tr",
                "videoDuration": "medium",  # 4-20dk (bizim sıralamayla 5-30 hedef)
                "safeSearch": "strict",
            })
            r.raise_for_status()
            search_data = r.json()
            video_ids = [item["id"]["videoId"] for item in search_data.get("items", [])
                         if item.get("id", {}).get("videoId")]

            if not video_ids:
                return {"success": True, "videos": [], "query": query}

            # 2. Detay (statistics + contentDetails)
            video_url = "https://www.googleapis.com/youtube/v3/videos"
            r2 = await client.get(video_url, params={
                "key": YOUTUBE_API_KEY,
                "id": ",".join(video_ids),
                "part": "snippet,statistics,contentDetails",
            })
            r2.raise_for_status()
            video_data = r2.json()

        # 3. Skorla, filtrele, sırala
        prefer = [konu] + ([ders] if ders else [])
        scored = []
        for item in video_data.get("items", []):
            content_details = item.get("contentDetails", {})
            dur_sec = _parse_iso8601_duration(content_details.get("duration", ""))
            dur_min = dur_sec // 60

            # Süre filtresi
            if dur_min > max_duration_min or dur_min < 1:
                continue

            score = _score_video(item, prefer)
            if score < -50:
                continue

            sn = item.get("snippet", {})
            stat = item.get("statistics", {})
            vid = item["id"]
            scored.append({
                "video_id": vid,
                "title": sn.get("title"),
                "channel": sn.get("channelTitle"),
                "duration_min": dur_min,
                "views": int(stat.get("viewCount", 0)),
                "likes": int(stat.get("likeCount", 0)),
                "thumbnail": sn.get("thumbnails", {}).get("high", {}).get("url"),
                "url": f"https://www.youtube.com/watch?v={vid}",
                "embed_block": make_embed_block(vid, sn.get("title", "")),
                "score": round(score, 1),
            })

        scored.sort(key=lambda x: -x["score"])
        return {"success": True, "videos": scored[:limit], "query": query,
                "total_candidates": len(scored)}

    except httpx.HTTPStatusError as e:
        msg = f"YouTube API HTTP {e.response.status_code}"
        try:
            err = e.response.json().get("error", {}).get("message", "")
            msg += f": {err}"
        except Exception:
            pass
        logger.warning(msg)
        return {"success": False, "error": msg}
    except Exception as e:
        logger.warning(f"YouTube search hata: {e}")
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    import asyncio
    import sys
    if len(sys.argv) < 2:
        print(f"Available: {is_available()}")
        sys.exit(0)
    konu = sys.argv[1]
    ders = sys.argv[2] if len(sys.argv) > 2 else ""
    res = asyncio.run(search_videos(konu, ders))
    if res.get("success"):
        for v in res["videos"]:
            print(f"  [{v['score']}] {v['channel']} — {v['title']} ({v['duration_min']}dk, {v['views']:,} izlenme)")
            print(f"      {v['url']}")
    else:
        print(f"Error: {res.get('error')}")
