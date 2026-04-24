"""
FermatAI — Wikipedia Anekdot Scraper (22.1n-neo FAZ 1.3+)
===========================================================

Neo onayiyla calisir — default dry_run.

TR Wikipedia bilim insani biyografilerinin ILK BOLUMUNU ceker,
ogrenciye uygun anekdotlara donusturur (Claude onaylar).

KAYNAKLAR:
  - TR Wikipedia: Turk bilim insanlari + edebiyat
  - Nobel laureates: ilginc gercekler
  - Istek halinde ek liste

KULLANIM:
  python wikipedia_anekdot_scraper.py                 # dry-run, liste gosterir
  python wikipedia_anekdot_scraper.py --apply          # Claude'a gonderip DB'ye ekle

GUVENLIK:
  - Sadece public Wikipedia API (https://tr.wikipedia.org/api/rest_v1/page/summary)
  - Rate limit: 1 saniye/istek
  - Claude onaylamamis icerik DB'ye GIRMEZ
"""
from __future__ import annotations

import asyncio
import re
import sys
from typing import Optional
import httpx
from loguru import logger


# Hedef kisiler — Neo'nun istegi + kurumsal kimlik
HEDEF_KISILER = {
    # Turk bilim — Neo priority
    "Cahit Arf": {"konu": "matematik", "hedef": "ilham,matematik_korkusu", "ders": "matematik"},
    "Oktay Sinanoğlu": {"konu": "kimya", "hedef": "yas,hedef", "ders": "kimya"},
    "Aziz Sancar": {"konu": "baslamak", "hedef": "baslangic,sartlar", "ders": ""},
    "Ali Kuşçu": {"konu": "fizik", "hedef": "ilham,bilim", "ders": "fizik"},
    "Mustafa İnan": {"konu": "muhendislik", "hedef": "azim,odak", "ders": ""},
    "Feza Gürsey": {"konu": "fizik", "hedef": "ilham,matematik", "ders": "fizik"},
    "Erdal İnönü": {"konu": "fizik", "hedef": "bilim,siyaset", "ders": "fizik"},
    "Behram Kurşunoğlu": {"konu": "fizik", "hedef": "bilim", "ders": "fizik"},
    # Turk edebiyat — Neo yeni istek
    "Reşat Nuri Güntekin": {"konu": "edebiyat", "hedef": "ogretmen,sabir", "ders": "edebiyat"},
    "Ali Canip Yöntem": {"konu": "edebiyat", "hedef": "dilgecmis,ogrenci", "ders": "edebiyat"},
    "Halide Edip Adıvar": {"konu": "edebiyat", "hedef": "kadin,azim", "ders": "edebiyat"},
    "Ömer Seyfettin": {"konu": "edebiyat", "hedef": "erken_baslama,oyku", "ders": "edebiyat"},
    "Yahya Kemal Beyatlı": {"konu": "edebiyat", "hedef": "sair,kimlik", "ders": "edebiyat"},
    # Nobel — dunya bilim
    "Marie Curie": {"konu": "azim", "hedef": "sartlar,kadin", "ders": ""},
    "Richard Feynman": {"konu": "ogrenme", "hedef": "teknik,ogrenme", "ders": "fizik"},
    "Barbara McClintock": {"konu": "azim", "hedef": "reddedilme,kadin", "ders": "biyoloji"},
    "Santiago Ramón y Cajal": {"konu": "basarisizlik", "hedef": "ogretmen_fikir_degistir", "ders": "biyoloji"},
    # Felsefe/sanat — lateral
    "Pierre de Fermat": {"konu": "matematik", "hedef": "kurum_kimlik,teorem", "ders": "matematik"},
    "İbn-i Sina": {"konu": "genclik", "hedef": "erken_basari,hedef", "ders": ""},
    "Harezmi": {"konu": "matematik", "hedef": "kok,islam", "ders": "matematik"},
}


WIKI_API = "https://tr.wikipedia.org/api/rest_v1/page/summary/{title}"


async def fetch_wiki_summary(title: str) -> Optional[dict]:
    """Wikipedia'dan sayfa ozetini cek (ilk paragraf + temel bilgi)."""
    from urllib.parse import quote
    url = WIKI_API.format(title=quote(title.replace(" ", "_"), safe=""))
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as s:
        try:
            r = await s.get(url, headers={"User-Agent": "FermatAI-Bot/1.0 (educational)"})
            if r.status_code != 200:
                return None
            data = r.json()
            return {
                "title": data.get("title"),
                "extract": data.get("extract", ""),
                "description": data.get("description", ""),
                "page_url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
            }
        except Exception as e:
            logger.debug(f"Wiki fetch err {title}: {e}")
            return None


def _kisalt_ozet(extract: str, max_len: int = 300) -> str:
    """Wikipedia extract'i ogrenci-uygun kisa anekdota cevir.

    İlk 1-2 cumle + en ilginc cumleleri sec.
    """
    if not extract:
        return ""
    # Cumlelere bol
    sentences = re.split(r'(?<=[.!?])\s+', extract)
    if not sentences:
        return extract[:max_len]
    # İlk 2 cumle baslangic + 1 ilginc cumle
    result = " ".join(sentences[:2])
    # Devamda "ilginc" anahtar kelime iceren cumle varsa ekle
    interesting_keywords = ("dünya", "ilk", "en", "sayıldı", "ödül", "keşfetti",
                             "ilk kez", "çığır", "devrim", "Nobel", "genç yaş")
    for s in sentences[2:8]:
        if any(kw in s for kw in interesting_keywords):
            result += " " + s
            break
    return result[:max_len]


async def collect_anekdot_candidates(delay_sec: float = 1.0) -> list[dict]:
    """Tum hedef kisilerden anekdot aday listesi don.

    Claude onay sart — bu fonksiyon SADECE ham veri cikarir, DB'ye YAZMAZ.
    """
    candidates = []
    for name, meta in HEDEF_KISILER.items():
        data = await fetch_wiki_summary(name)
        if not data:
            continue
        kisa_metin = _kisalt_ozet(data.get("extract", ""))
        if len(kisa_metin) < 100:
            continue  # cok kisa — yararsiz
        candidates.append({
            "slug": f"wiki_{name.lower().replace(' ', '_').replace('ö','o').replace('ı','i').replace('ç','c').replace('ğ','g').replace('ş','s').replace('ü','u')}",
            "kim": name,
            "konu": meta["konu"],
            "baslik": data.get("title"),
            "metin": kisa_metin,
            "ders": meta.get("ders", ""),
            "duygusal_hedef": meta["hedef"],
            "kaynak": f"Wikipedia TR — {data.get('page_url', name)}",
            "etiketler": f"wiki,turk_bilim,{meta['konu']}",
        })
        await asyncio.sleep(delay_sec)  # rate limit
    return candidates


async def apply_to_db(candidates: list[dict]) -> int:
    """Aday anekdotlari DB'ye ekle (Neo onaylamis)."""
    from db_pool import db_execute
    n = 0
    for c in candidates:
        try:
            await db_execute(
                """INSERT INTO anekdotlar (slug, kim, konu, baslik, metin, ders,
                                            duygusal_hedef, kaynak, etiketler)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                   ON CONFLICT (slug) DO NOTHING""",
                c["slug"], c["kim"], c["konu"], c["baslik"],
                c["metin"], c["ders"], c["duygusal_hedef"],
                c["kaynak"], c["etiketler"]
            )
            n += 1
        except Exception as e:
            logger.debug(f"insert err {c['slug']}: {e}")
    return n


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    apply = "--apply" in sys.argv
    async def main():
        print("🔍 Wikipedia Anekdot Scraping — {} hedef kisi\n".format(len(HEDEF_KISILER)))
        if not apply:
            print("MODE: DRY-RUN (cikarir, DB'ye YAZMAZ). Gercek yazim: --apply flag\n")
        c = await collect_anekdot_candidates()
        print(f"\n✓ {len(c)} anekdot adayi bulundu:\n")
        for a in c[:5]:
            print(f"  📖 {a['kim']}")
            print(f"     {a['metin'][:150]}...")
            print()
        if apply:
            print("\n! UYGULANYOR — Neo onayli sync")
            n = await apply_to_db(c)
            print(f"✅ {n} anekdot DB'ye eklendi")
        else:
            print("\n(Neo onay verirse: --apply flag ile tekrar calistir)")
    asyncio.run(main())
