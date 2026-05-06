"""
Pedagoji V2 — DB Seeder (25.41 Neo)
====================================

output/output_anekdot.json + output/output_kavram.json → DB INSERT.
KATEGORILER → pedagoji_kategori.

Idempotent (ON CONFLICT UPDATE).

Kullanım:
  python pedagoji/seeder.py             # Tüm hidrate
  python pedagoji/seeder.py kategori    # Sadece kategori
  python pedagoji/seeder.py kavram      # Sadece kavram
  python pedagoji/seeder.py anekdot     # Sadece anekdot
"""
from __future__ import annotations
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from db_pool import db_execute, db_fetchval


async def hydrate_kategori() -> int:
    from pedagoji.kategoriler import KATEGORILER
    n = 0
    for slug, k in KATEGORILER.items():
        await db_execute("""
            INSERT INTO pedagoji_kategori
              (slug, baslik, aciklama, trigger_patterns, keyword_boost,
               oneri_formul, default_konum)
            VALUES ($1,$2,$3,$4,$5,$6,$7)
            ON CONFLICT (slug) DO UPDATE SET
              baslik=EXCLUDED.baslik, aciklama=EXCLUDED.aciklama,
              trigger_patterns=EXCLUDED.trigger_patterns,
              keyword_boost=EXCLUDED.keyword_boost,
              oneri_formul=EXCLUDED.oneri_formul,
              default_konum=EXCLUDED.default_konum
        """, slug, k["baslik"], k["aciklama"], k["trigger_patterns"],
             ",".join(k["keyword_boost"]), k["oneri_formul"], k["default_konum"])
        n += 1
    return n


async def hydrate_kavram() -> int:
    path = Path(__file__).parent / "output" / "output_kavram.json"
    if not path.exists():
        logger.warning(f"Kavram output bulunamadı: {path}")
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    n = 0
    seen_slugs = set()
    for k in data:
        if k["slug"] in seen_slugs:
            continue
        seen_slugs.add(k["slug"])
        await db_execute("""
            INSERT INTO pedagoji_kavram_v2
              (slug, baslik, kategori, kisaca, aciklama, kullanim_ornegi,
               trigger_patterns, kaynak, etiketler)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            ON CONFLICT (slug) DO UPDATE SET
              baslik=EXCLUDED.baslik, kategori=EXCLUDED.kategori,
              kisaca=EXCLUDED.kisaca, aciklama=EXCLUDED.aciklama,
              kullanim_ornegi=EXCLUDED.kullanim_ornegi,
              trigger_patterns=EXCLUDED.trigger_patterns,
              kaynak=EXCLUDED.kaynak, etiketler=EXCLUDED.etiketler
        """, k["slug"], k["baslik"], k["kategori"], k["kisaca"],
             k["aciklama"], k["kullanim_ornegi"], k["trigger_patterns"],
             k["kaynak"], k["etiketler"])
        n += 1
    return n


async def hydrate_anekdot() -> int:
    path = Path(__file__).parent / "output" / "output_anekdot.json"
    if not path.exists():
        logger.warning(f"Anekdot output bulunamadı: {path}")
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    n = 0
    seen_slugs = set()
    for a in data:
        if a["slug"] in seen_slugs:
            continue
        seen_slugs.add(a["slug"])
        await db_execute("""
            INSERT INTO pedagoji_anekdot_v2
              (slug, kim, kategori, konu, baslik, metin, ders,
               duygusal_hedef, kaynak, etiketler)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            ON CONFLICT (slug) DO UPDATE SET
              kim=EXCLUDED.kim, kategori=EXCLUDED.kategori,
              konu=EXCLUDED.konu, baslik=EXCLUDED.baslik,
              metin=EXCLUDED.metin, ders=EXCLUDED.ders,
              duygusal_hedef=EXCLUDED.duygusal_hedef,
              kaynak=EXCLUDED.kaynak, etiketler=EXCLUDED.etiketler
        """, a["slug"], a["kim"], a["kategori"], a.get("konu", ""),
             a.get("baslik", ""), a["metin"], a.get("ders", ""),
             a["duygusal_hedef"], a["kaynak"], a["etiketler"])
        n += 1
    return n


async def main():
    sys.stdout.reconfigure(encoding="utf-8")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"

    if cmd in ("kategori", "all"):
        n = await hydrate_kategori()
        logger.success(f"✅ {n} kategori")

    if cmd in ("kavram", "all"):
        n = await hydrate_kavram()
        logger.success(f"✅ {n} kavram (v2)")

    if cmd in ("anekdot", "all"):
        n = await hydrate_anekdot()
        logger.success(f"✅ {n} anekdot (v2)")

    # Verify counts
    kat_count = await db_fetchval("SELECT COUNT(*) FROM pedagoji_kategori")
    kav_count = await db_fetchval("SELECT COUNT(*) FROM pedagoji_kavram_v2")
    ane_count = await db_fetchval("SELECT COUNT(*) FROM pedagoji_anekdot_v2")
    logger.info(f"📊 DB: {kat_count} kategori, {kav_count} kavram, {ane_count} anekdot")


if __name__ == "__main__":
    asyncio.run(main())
