"""
Yaz Kampı Altyapı Modülü (22.1n-fikir6)
========================================

Neo 20 Nisan 13:51:
> "Temmuzun son haftası tyt yaz kampı ile başlıyor 5 hafta boyunca
>  haftanın 5 günü ders veriyoruz"
> "40 civarı öğrenci aldım yakında eyotekten yeni sezon"

ÖZELLİKLER:
1. Yaz kampı grubu — `yaz_kampi_members` tablosu (soz_no + kamp_id)
2. Günlük değerlendirme — 5 sorulu self-report (öğrenci aktif ederse)
3. Haftalık mini rapor — kamp süresince progress
4. Özel dashboard — yoğun takip modu
5. FLAG: YAZ_KAMPI_ACTIVE=False default, Neo Temmuz'da True yapacak

GÜVENLİK (22.1n-kural1):
- Bu modül OTOMATİK MESAJ ATMAZ. Öğrenci WP'dan gelirse bot dashboard'a yönlendirir.
- Yaz kampı aktif bile olsa outreach_pending guard devrede.
"""
import asyncio
import os
from datetime import datetime, date, timedelta

from loguru import logger

YAZ_KAMPI_ACTIVE = os.getenv("YAZ_KAMPI_ACTIVE", "false").lower() in ("1", "true", "yes")

# 2026 yaz kampı tarihleri (Neo takvim — yaklaşık)
KAMP_BASLANGIC = date(2026, 7, 28)   # Temmuz son haftası (Salı)
KAMP_BITIS     = date(2026, 8, 30)   # 5 hafta sonrası (ağustos sonuna yakın)


# ─── DB ───────────────────────────────────────────────────────────────────────
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS yaz_kampi_members (
    id SERIAL PRIMARY KEY,
    soz_no INT NOT NULL,
    kamp_donemi TEXT NOT NULL DEFAULT '2026_yaz',
    kaydedildi_tarih DATE DEFAULT CURRENT_DATE,
    aktif BOOLEAN DEFAULT TRUE,
    UNIQUE(soz_no, kamp_donemi)
);

CREATE TABLE IF NOT EXISTS yaz_kampi_gunluk (
    id SERIAL PRIMARY KEY,
    soz_no INT NOT NULL,
    kamp_donemi TEXT NOT NULL DEFAULT '2026_yaz',
    tarih DATE DEFAULT CURRENT_DATE,
    enerji_1_10 INT,
    anladigi_ders TEXT,
    zorlandigi_konu TEXT,
    soru_sayisi INT,
    motivasyon_1_10 INT,
    not_metni TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(soz_no, kamp_donemi, tarih)
);

CREATE INDEX IF NOT EXISTS idx_yk_gunluk_soz ON yaz_kampi_gunluk(soz_no, kamp_donemi, tarih DESC);
"""


async def init_db():
    """Yaz kampı tablolarını oluştur (idempotent)."""
    from db_pool import db_execute
    await db_execute(SCHEMA_SQL)
    logger.info("Yaz kampi tablolari hazir")


async def add_member(soz_no: int, donem: str = "2026_yaz") -> bool:
    """Öğrenciyi yaz kampına ekle."""
    from db_pool import db_execute
    try:
        await db_execute(
            """INSERT INTO yaz_kampi_members (soz_no, kamp_donemi)
               VALUES ($1, $2) ON CONFLICT (soz_no, kamp_donemi) DO UPDATE SET aktif=TRUE""",
            int(soz_no), donem,
        )
        logger.info(f"Yaz kampi uye eklendi: soz_no={soz_no}")
        return True
    except Exception as e:
        logger.error(f"add_member hata: {e}")
        return False


async def list_members(donem: str = "2026_yaz") -> list:
    """Yaz kampı üyelerini listele."""
    from db_pool import db_fetch
    rows = await db_fetch(
        """SELECT m.soz_no, s.full_name, s.class_name, m.kaydedildi_tarih
           FROM yaz_kampi_members m
           LEFT JOIN students s ON s.soz_no = m.soz_no
           WHERE m.kamp_donemi=$1 AND m.aktif=TRUE
           ORDER BY s.full_name""",
        donem,
    )
    return [dict(r) for r in rows]


async def kayit_gunluk(soz_no: int, *, enerji: int = None, anladigi: str = "",
                       zorlandigi: str = "", soru_sayisi: int = None,
                       motivasyon: int = None, not_metni: str = "",
                       donem: str = "2026_yaz") -> bool:
    """Öğrenci günlük değerlendirme kaydı."""
    from db_pool import db_execute
    try:
        await db_execute(
            """INSERT INTO yaz_kampi_gunluk
               (soz_no, kamp_donemi, tarih, enerji_1_10, anladigi_ders,
                zorlandigi_konu, soru_sayisi, motivasyon_1_10, not_metni)
               VALUES ($1, $2, CURRENT_DATE, $3, $4, $5, $6, $7, $8)
               ON CONFLICT (soz_no, kamp_donemi, tarih) DO UPDATE SET
                 enerji_1_10 = COALESCE(EXCLUDED.enerji_1_10, yaz_kampi_gunluk.enerji_1_10),
                 anladigi_ders = COALESCE(NULLIF(EXCLUDED.anladigi_ders,''), yaz_kampi_gunluk.anladigi_ders),
                 zorlandigi_konu = COALESCE(NULLIF(EXCLUDED.zorlandigi_konu,''), yaz_kampi_gunluk.zorlandigi_konu),
                 soru_sayisi = COALESCE(EXCLUDED.soru_sayisi, yaz_kampi_gunluk.soru_sayisi),
                 motivasyon_1_10 = COALESCE(EXCLUDED.motivasyon_1_10, yaz_kampi_gunluk.motivasyon_1_10),
                 not_metni = COALESCE(NULLIF(EXCLUDED.not_metni,''), yaz_kampi_gunluk.not_metni)""",
            int(soz_no), donem, enerji, anladigi[:50], zorlandigi[:100],
            soru_sayisi, motivasyon, not_metni[:1000],
        )
        return True
    except Exception as e:
        logger.error(f"kayit_gunluk hata: {e}")
        return False


async def progress_raporu(soz_no: int, donem: str = "2026_yaz") -> dict:
    """Öğrencinin yaz kampı süresince gelişim raporu."""
    from db_pool import db_fetch, db_fetchrow
    rows = await db_fetch(
        """SELECT tarih, enerji_1_10, motivasyon_1_10, soru_sayisi,
                  anladigi_ders, zorlandigi_konu, not_metni
           FROM yaz_kampi_gunluk
           WHERE soz_no=$1 AND kamp_donemi=$2
           ORDER BY tarih""",
        int(soz_no), donem,
    )
    if not rows:
        return {"hazir_gun": 0, "mesaj": "Henüz günlük değerlendirme yok"}

    ort_enerji = sum(r["enerji_1_10"] or 0 for r in rows) / max(1, sum(1 for r in rows if r["enerji_1_10"]))
    ort_motiv  = sum(r["motivasyon_1_10"] or 0 for r in rows) / max(1, sum(1 for r in rows if r["motivasyon_1_10"]))
    top_soru   = sum(r["soru_sayisi"] or 0 for r in rows)

    # En sık zorlandığı konular
    zorlandiklari = {}
    for r in rows:
        z = (r["zorlandigi_konu"] or "").strip().lower()
        if z:
            zorlandiklari[z] = zorlandiklari.get(z, 0) + 1
    zorlandik_top = sorted(zorlandiklari.items(), key=lambda x: -x[1])[:5]

    return {
        "hazir_gun": len(rows),
        "ortalama_enerji": round(ort_enerji, 1),
        "ortalama_motivasyon": round(ort_motiv, 1),
        "toplam_soru": top_soru,
        "en_sik_zorlandigi": [k for k, _ in zorlandik_top],
    }


async def kamp_ozet_tum() -> dict:
    """Kamp süresince tüm öğrencilerin agregasyonu (admin görür)."""
    from db_pool import db_fetchval
    if not YAZ_KAMPI_ACTIVE:
        return {"aktif": False, "mesaj": "Yaz kampi flag KAPALI. Neo aktive edecek."}

    toplam_uye = await db_fetchval("SELECT COUNT(*) FROM yaz_kampi_members WHERE aktif=TRUE AND kamp_donemi='2026_yaz'")
    aktif_gun = await db_fetchval("SELECT COUNT(DISTINCT soz_no) FROM yaz_kampi_gunluk WHERE kamp_donemi='2026_yaz' AND tarih > CURRENT_DATE - INTERVAL '7 days'")
    ort_ener = await db_fetchval("SELECT ROUND(AVG(enerji_1_10)::numeric,1) FROM yaz_kampi_gunluk WHERE kamp_donemi='2026_yaz'")

    return {
        "aktif": True,
        "toplam_uye": int(toplam_uye or 0),
        "son_7gun_aktif": int(aktif_gun or 0),
        "ortalama_enerji": float(ort_ener) if ort_ener else None,
        "kamp_baslangic": KAMP_BASLANGIC.isoformat(),
        "kamp_bitis": KAMP_BITIS.isoformat(),
        "gecen_gun": max(0, (date.today() - KAMP_BASLANGIC).days),
    }


# ─── CLI ──────────────────────────────────────────────────────────────────────
async def main():
    import argparse, json, sys, io
    parser = argparse.ArgumentParser()
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--add", type=int, help="Uye ekle (soz_no)")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--ozet", action="store_true")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv(override=True)

    if args.init:
        await init_db()
        print("OK")
    if args.add:
        await add_member(args.add)
        print(f"Eklendi: {args.add}")
    if args.list:
        members = await list_members()
        print(f"Uye: {len(members)}")
        for m in members:
            print(f"  {m['soz_no']} — {m.get('full_name') or '?'} ({m.get('class_name') or '?'})")
    if args.ozet:
        ozet = await kamp_ozet_tum()
        print(json.dumps(ozet, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    import io
    import sys as _sys
    _sys.stdout = io.TextIOWrapper(_sys.stdout.buffer, encoding="utf-8", errors="replace")
    asyncio.run(main())
