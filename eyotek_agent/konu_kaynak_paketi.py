"""
Konu Kaynak Paketi — Çoklu Kaynak Sunucu (23 Nisan 2026)
=========================================================

Neo vizyonu (23 Nisan):
  "Sen konuyla ilgili bir YouTube playlist önermelisin sanki öğrenci adına
   arama yapmışsın gibi. Çocuk girdiğinde birden fazla kaynağı belirlediği
   konu ile ilgili alternatif olarak görebilirse daha anlamlı olur. Yani
   seçenekleri topluca sunup — 'şunu izle' değil 'bunlar var, şu linklerde
   var, Wikipedia üzerinden de bakabilirsin, OGM Materyal her zaman güvenilir'."

═══════════════════════════════════════════════════════════════════════════════
KAYNAK HİYERARŞİSİ (güvenilirliğe göre)
═══════════════════════════════════════════════════════════════════════════════
  1. OGM Materyal (MEB resmi)      — HER ZAMAN göster (en güvenilir)
  2. YouTube whitelist kanallar    — 3-5 farklı kanal, playlist hissi
  3. Wikipedia (tr → en fallback)  — 2-3 ansiklopedik kaynak
  4. RAG içerik (dâhili müfredat)  — konu anlatımı varsa

ÖĞRENCI "şu konuda video izlemek istiyorum" / "konu anlatımı lazım" /
"bu konuyu nasıl çalışırım" / "kaynak önerir misin" dediğinde AKTIF.
Bot kendi kendine video önermez — talep gelince paket sunar.
"""
from __future__ import annotations

import os
import re
from typing import Optional

try:
    from loguru import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)


# ─── Konu → YouTube arama query'si normalize ─────────────────────────────
def _youtube_query(konu: str, ders: str = "") -> str:
    """Öğrenci 'türev nedir' yazınca arama 'türev YKS konu anlatımı' olsun."""
    konu = (konu or "").strip()
    if ders:
        return f"{konu} {ders} YKS konu anlatımı"
    return f"{konu} YKS konu anlatımı"


# ═══════════════════════════════════════════════════════════════════════════════
# WIKIPEDIA — TR önce, boşsa EN fallback
# ═══════════════════════════════════════════════════════════════════════════════

# Wikipedia robot policy — User-Agent ZORUNLU (2025 kuralı)
_WIKI_UA = "FermatAI/1.0 (WhatsApp/LMS bot; contact: zeki.goksal@gmail.com)"


async def wikipedia_search(query: str, limit: int = 3, lang: str = "tr") -> list[dict]:
    """Wikipedia opensearch API — başlık + URL döndürür."""
    if not query:
        return []
    try:
        import httpx
        headers = {"User-Agent": _WIKI_UA, "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=6.0, headers=headers) as c:
            r = await c.get(
                f"https://{lang}.wikipedia.org/w/api.php",
                params={
                    "action": "opensearch",
                    "search": query,
                    "limit": limit,
                    "format": "json",
                    "namespace": 0,
                },
            )
            if r.status_code != 200:
                logger.debug(f"wiki {lang} status {r.status_code}: {r.text[:150]}")
                return []
            data = r.json()
            # [query, [titles...], [descriptions...], [urls...]]
            if not isinstance(data, list) or len(data) < 4:
                return []
            titles = data[1] or []
            descs = data[2] or []
            urls = data[3] or []

            results = []
            for i, title in enumerate(titles):
                desc = descs[i] if i < len(descs) else ""
                url = urls[i] if i < len(urls) else ""
                if not url:
                    continue
                results.append({
                    "baslik": title,
                    "aciklama": (desc or "")[:200],
                    "url": url,
                    "kaynak": f"Wikipedia ({lang.upper()})",
                })
            return results
    except Exception as e:
        logger.debug(f"wikipedia_search({lang}) hata: {e}")
        return []


async def wikipedia_bilingual(query: str, limit: int = 3) -> list[dict]:
    """Önce TR Wikipedia, boşsa EN — Türk öğrenci için TR her zaman önce."""
    tr = await wikipedia_search(query, limit=limit, lang="tr")
    if tr:
        return tr
    return await wikipedia_search(query, limit=2, lang="en")


# ═══════════════════════════════════════════════════════════════════════════════
# OGM MATERYAL — Ders bazlı resmi PDF/video
# ═══════════════════════════════════════════════════════════════════════════════

async def ogm_materyal_for_konu(ders: str = "", konu: str = "") -> list[dict]:
    """OGM kataloğundan ders bazlı ilgili kaynakları getir.

    Ders zorunlu, konu opsiyonel (fuzzy match konu adında).
    """
    if not ders:
        return []
    try:
        from ogm_catalog import yonlendir
        results = await yonlendir(ders=ders, tip="konu_ozeti")
        if not results:
            return []

        # Konu ile fuzzy match — konu adında veya içerik özetinde kelime geçiyorsa önceliklendir
        if konu:
            konu_low = konu.lower()
            konu_words = [w for w in konu_low.split() if len(w) > 2]

            def skor(r):
                ad = (r.get("konu_adi") or "").lower()
                oz = (r.get("icerik_ozet") or "").lower()
                s = 0
                for w in konu_words:
                    if w in ad:
                        s += 3
                    if w in oz:
                        s += 1
                return -s  # negatif: azalan sıralama

            results.sort(key=skor)

        # En iyi 2 sonuç
        return [
            {
                "baslik": r.get("konu_adi", ""),
                "url": r.get("url", ""),
                "aciklama": (r.get("icerik_ozet") or "")[:180],
                "kategori": r.get("icerik_tipi") or "",
                "ders": r.get("ders") or ders,
                "kaynak": "OGM Materyal (MEB)",
            }
            for r in results[:2]
            if r.get("url")
        ]
    except Exception as e:
        logger.debug(f"ogm_materyal_for_konu hata: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# RAG İÇ KAYNAK — Dâhili FermatAI müfredat bilgisi
# ═══════════════════════════════════════════════════════════════════════════════

async def rag_inner_resources(konu: str, ders: str = "", limit: int = 2) -> list[dict]:
    """Sistemin kendi RAG bankasından en alakalı konu anlatımı + link özeti."""
    try:
        from rag_engine import search_curriculum
        items = await search_curriculum(konu, ders=ders, limit=limit)
        results = []
        for it in items:
            if float(it.get("skor") or 0) < 0.55:
                continue
            kaynak = it.get("kaynak", "")
            # OGM Vision split kayıtları ayrı zaten — burada öncelikle konu anlatımı
            if "OGM Vision" in kaynak and "split" in kaynak:
                continue
            results.append({
                "baslik": it.get("baslik", "")[:80],
                "kaynak": kaynak,
                "ozet": (it.get("icerik") or "")[:220],
                "skor": float(it.get("skor") or 0),
            })
        return results[:limit]
    except Exception as e:
        logger.debug(f"rag_inner_resources hata: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# ANA TOOL — Konu Kaynak Paketi
# ═══════════════════════════════════════════════════════════════════════════════

async def konu_kaynak_paketi(
    konu: str,
    ders: str = "",
    youtube_adet: int = 4,
    wikipedia_adet: int = 2,
) -> dict:
    """Bir konu için çoklu kaynak paketi — playlist hissiyle sunum.

    Dönüş:
    {
      "konu": "Fotoelektrik Olayı",
      "ders": "Fizik",
      "paket": {
        "ogm": [{...}],          # MEB resmi, EN GÜVENILIR — her zaman ilk
        "youtube": [{...}],      # 3-5 whitelist video, farklı kanallardan
        "wikipedia": [{...}],    # 2 ansiklopedik makale (tr öncelikli)
        "dahili": [{...}]        # FermatAI RAG özeti varsa
      },
      "sunum_mesaji": "Öğrenciye sunum metni",
      "kaynak_toplam": N
    }
    """
    import asyncio

    konu = (konu or "").strip()
    if not konu:
        return {"error": "konu parametresi zorunlu"}

    # Paralel çek — hepsi bağımsız
    yt_query = _youtube_query(konu, ders)

    async def _yt():
        try:
            from external_apis import youtube_search
            return await youtube_search(yt_query, max_results=youtube_adet, strict_whitelist=True)
        except Exception:
            return []

    yt, wk, ogm, rag = await asyncio.gather(
        _yt(),
        wikipedia_bilingual(konu, limit=wikipedia_adet),
        ogm_materyal_for_konu(ders=ders, konu=konu),
        rag_inner_resources(konu, ders=ders, limit=2),
        return_exceptions=True,
    )

    # Exception olanları boş listeye dönüştür
    def _safe(x):
        return x if isinstance(x, list) else []

    yt = _safe(yt)
    wk = _safe(wk)
    ogm = _safe(ogm)
    rag = _safe(rag)

    toplam = len(yt) + len(wk) + len(ogm) + len(rag)

    # Sunum mesajı üret — bot doğrudan bu mesajı öğrenciye gönderebilir
    sunum = _sunum_mesaji(konu, ders, yt, wk, ogm, rag)

    return {
        "konu": konu,
        "ders": ders or "Genel",
        "paket": {
            "ogm": ogm,
            "youtube": yt,
            "wikipedia": wk,
            "dahili": rag,
        },
        "sunum_mesaji": sunum,
        "kaynak_toplam": toplam,
        "kullanim_rehberi": (
            "Öğrenciye 'sunum_mesaji' içeriğini doğrudan sun. Tek kaynak değil, çoklu "
            "alternatif göster — 'bunlar var, şuradan da bakabilirsin' tonuyla. "
            "OGM Materyal her zaman güvenilir — vurgula. YouTube'da beğenmediği kanal "
            "varsa sonraki videoyu seçebilir. Wikipedia hızlı tanım için."
        ),
    }


def _sunum_mesaji(konu: str, ders: str, yt: list, wk: list, ogm: list, rag: list) -> str:
    """Öğrenciye gösterilecek çoklu kaynak paketi — WhatsApp + web uyumlu."""
    lines = []

    # Başlık
    ders_txt = f" ({ders})" if ders else ""
    lines.append(f"📚 *{konu}* için kaynak paketi{ders_txt}:")
    lines.append("")

    # OGM — en üstte, vurgulu
    if ogm:
        lines.append("🟢 *MEB OGM Materyal — Resmi Kaynak* (en güvenilir)")
        for r in ogm:
            kat = r.get("kategori") or "Konu Özeti"
            lines.append(f"  • [{kat}] {r['baslik']}")
            lines.append(f"    🔗 {r['url']}")
        lines.append("")

    # YouTube — çeşitli kanallar
    if yt:
        lines.append(f"🎥 *Video Anlatımı* (onaylı kanallardan {len(yt)} farklı kaynak)")
        for v in yt:
            lines.append(f"  • {v['kanal']} — {v['baslik'][:60]}")
            lines.append(f"    🔗 {v['url']}")
        lines.append("")

    # Wikipedia
    if wk:
        lines.append("📖 *Ansiklopedik Bakış*")
        for w in wk:
            lines.append(f"  • {w['baslik']}")
            lines.append(f"    🔗 {w['url']}")
        lines.append("")

    # Dâhili RAG
    if rag:
        lines.append("📝 *FermatAI Müfredat Notları*")
        for r in rag:
            lines.append(f"  • {r['baslik']}")
        lines.append("  _(Konuyu burada WA üzerinden de anlatabilirim, 'anlat' de.)_")
        lines.append("")

    if not (yt or wk or ogm or rag):
        lines.append(
            "_Şu anda bu konuda onaylı kaynak paketinde sonuç bulamadım._\n"
            "Sana rastgele bir link önermem — bunun yerine konuyu birlikte adım adım "
            "gidelim ister misin? Anlatımı ben yaparım, sonra çıkmış sorulardan pekiştiririz. 🎯"
        )
    else:
        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("_Hangisinden başlamak istersin?_ 🎯")
        lines.append("_Takıldığın yerde soru gelir gelmez birlikte çözeriz._")

    return "\n".join(lines)


__all__ = [
    "konu_kaynak_paketi",
    "wikipedia_search",
    "wikipedia_bilingual",
    "ogm_materyal_for_konu",
    "rag_inner_resources",
]
