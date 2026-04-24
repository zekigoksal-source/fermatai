"""
OGM Catalog — Konu İndeks (22.1n)
===================================

Bot 19 Nisan 22:28'de Neo'ya öneri: "OGM Catalog Scraper — Playwright ile
içindekiler sayfalarını tarayan Python scripti".

Amaç: MEB OGM materyallerinin (ogmmateryal.eba.gov.tr) içindekiler haritası
`ogm_catalog` tablosuna indekslensin → `search_curriculum` konuyu RAG'da
bulamazsa buraya fallback → MEB kaynakli konu metni geri döner.

Tablo: ogm_catalog (konu_adi, ders, sinif, kitap_id, sayfa, url)
Durum: ALTYAPI HAZIR, scrape işi arka plan + manuel trigger.

Kullanım:
    # DB init
    python ogm_catalog.py --init

    # Manuel arama (scrape YERINE test)
    python ogm_catalog.py --search "turev"

22.1n: Sadece tablo + arama fonksiyonu. Playwright scrape yeni sezon işi
(Neo "altyapı hazır, yeni sezon aktif" pattern'ı).
"""
import asyncio
import sys
import io
from typing import Optional
from loguru import logger


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS ogm_catalog (
    id SERIAL PRIMARY KEY,
    konu_adi TEXT NOT NULL,
    ders TEXT NOT NULL,
    sinif TEXT,
    kitap_id TEXT,
    sayfa INT,
    sayfa_range TEXT,
    url TEXT,
    icerik_ozet TEXT,
    kaynak_tipi TEXT DEFAULT 'ogm_materyal',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ogm_konu ON ogm_catalog (konu_adi);
CREATE INDEX IF NOT EXISTS idx_ogm_ders ON ogm_catalog (ders);
CREATE INDEX IF NOT EXISTS idx_ogm_sinif ON ogm_catalog (sinif);
"""


async def init_db():
    """Tablo olustur."""
    from db_pool import db_execute
    await db_execute(CREATE_TABLE_SQL)
    logger.info("OGM Catalog tablosu hazir")


async def search_catalog(konu: str, ders: str = "", sinif: str = "",
                         limit: int = 5) -> list[dict]:
    """
    OGM catalog'ta konu ara (RAG fallback için).

    RAG'da benzer konu bulunamadığında search_curriculum bu fonksiyonu çağırabilir.
    Sonuç: {konu_adi, ders, sinif, url, sayfa, icerik_ozet}
    """
    from db_pool import db_fetch
    filters = ["konu_adi ILIKE $1"]
    params = [f"%{konu}%"]
    idx = 2
    if ders:
        filters.append(f"ders ILIKE ${idx}")
        params.append(f"%{ders}%")
        idx += 1
    if sinif:
        filters.append(f"sinif ILIKE ${idx}")
        params.append(f"%{sinif}%")
        idx += 1

    where = " AND ".join(filters)
    sql = f"""
        SELECT konu_adi, ders, sinif, kitap_id, sayfa, sayfa_range, url, icerik_ozet
        FROM ogm_catalog
        WHERE {where}
        ORDER BY
          CASE WHEN konu_adi ILIKE $1 THEN 1 ELSE 2 END,
          created_at DESC
        LIMIT {int(limit)}
    """
    rows = await db_fetch(sql, *params)
    return [dict(r) for r in rows]


async def add_catalog_entry(konu_adi: str, ders: str, sinif: str = "",
                            kitap_id: str = "", sayfa: int = 0,
                            sayfa_range: str = "", url: str = "",
                            icerik_ozet: str = "") -> int:
    """Manuel kayıt ekleme (scrape sonrası veya admin manual)."""
    from db_pool import db_fetchval
    new_id = await db_fetchval(
        """INSERT INTO ogm_catalog (konu_adi, ders, sinif, kitap_id, sayfa, sayfa_range, url, icerik_ozet)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id""",
        konu_adi, ders, sinif, kitap_id, int(sayfa or 0), sayfa_range, url, icerik_ozet
    )
    logger.info(f"OGM catalog ekle: id={new_id} konu={konu_adi}")
    return int(new_id or 0)


async def yonlendir(ders: str = "", sinav_turu: str = "", tip: str = "") -> list[dict]:
    """
    OGM Materyal yonlendirme — Neo vizyonu (22.1n-ogm):
    Ogrenci/ogretmen akademik konusma sirasinda ilgili MEB OGM resmi kaynagina
    yonlendirilsin. Claude tool_call ile veya fast_response ile kullanilir.

    Args:
        ders: Fizik, Matematik, Kimya, Biyoloji, Turkce, Tarih, Cografya, Felsefe, TDE, Ingilizce
        sinav_turu: TYT, AYT, YDT, YKS (hub)
        tip: 3_adim_soru_bankasi, konu_ozeti, hub_link, konu_anlatim_video vb.
             Bos ise tum tipler dondurulur.

    Returns: [{konu_adi, url, icerik_ozet, icerik_tipi, sinif, ders}, ...]
    """
    from db_pool import db_fetch
    filters = []
    params = []
    idx = 1
    if ders:
        filters.append(f"ders ILIKE ${idx}")
        params.append(f"%{ders}%")
        idx += 1
    if sinav_turu:
        filters.append(f"sinif = ${idx}")
        params.append(sinav_turu.upper())
        idx += 1
    if tip:
        filters.append(f"icerik_tipi = ${idx}")
        params.append(tip)
        idx += 1

    where = " AND ".join(filters) if filters else "TRUE"
    sql = f"""
        SELECT konu_adi, ders, sinif, url, icerik_ozet, icerik_tipi
        FROM ogm_catalog
        WHERE {where} AND kaynak_tipi = 'ogm_materyal_seed'
        ORDER BY
          CASE icerik_tipi
            WHEN '3_adim_soru_bankasi' THEN 1
            WHEN 'konu_ozeti' THEN 2
            WHEN 'hub_link' THEN 3
            ELSE 4
          END,
          ders
        LIMIT 10
    """
    rows = await db_fetch(sql, *params)
    return [dict(r) for r in rows]


async def get_stats() -> dict:
    """Catalog istatistikleri."""
    from db_pool import db_fetchval, db_fetch
    total = await db_fetchval("SELECT COUNT(*) FROM ogm_catalog") or 0
    by_ders = await db_fetch(
        "SELECT ders, COUNT(*) as sayi FROM ogm_catalog GROUP BY ders ORDER BY sayi DESC"
    )
    return {
        "toplam": int(total),
        "ders_dagilimi": {r["ders"]: int(r["sayi"]) for r in by_ders},
    }


# ─── CLI ─────────────────────────────────────────────────────────
async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--search", type=str, help="Konu ara")
    parser.add_argument("--ders", type=str, default="")
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv(override=True)

    if args.init:
        await init_db()
        print("OGM catalog tablosu OK")

    if args.search:
        results = await search_catalog(args.search, ders=args.ders)
        print(f"\nSonuc: {len(results)}")
        for r in results:
            print(f"  [{r['ders']}/{r.get('sinif','')}] {r['konu_adi']}")
            if r.get('url'):
                print(f"    URL: {r['url']}")
            if r.get('icerik_ozet'):
                print(f"    Ozet: {r['icerik_ozet'][:100]}")

    if args.stats:
        stats = await get_stats()
        print(f"\nToplam: {stats['toplam']}")
        print(f"Ders dağılımı: {stats['ders_dagilimi']}")


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    asyncio.run(main())
