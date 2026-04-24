"""
OGM Catalog Seed — Statik URL Haritası (22.1n-ogm)
===================================================

Neo 19 Nisan 23:50: "ogmmateryal.eba.gov.tr'den yonlendirmek amaciyla
kullanabileceğimiz icerik yok mu projede işimize yarayacak bi inceleyip üstüne düşün"

Site taramasi ile 37+ stabil URL tespit edildi. Bu dosya ogm_catalog tablosuna
(ogm_catalog.py ile olusturulan) hepsini ekler. Boylece:
  - Claude `ogm_yonlendir(ders, sinav_turu, tip)` tool'u ile direkt link
  - Fast response "TYT matematik soru bankası" → 0 maliyet yanıt
  - search_curriculum sonucuna "🎓 OGM kaynak: [link]" ekle

Kullanim:
    python ogm_catalog_seed.py --apply
"""
import asyncio

OGM_BASE = "https://ogmmateryal.eba.gov.tr"

# ─── 3 ADIM SORU BANKASI (stable MongoDB IDs, 17 kayit) ──────────────
UC_ADIM_SORU = [
    # AYT Soru Bankasi (8 ders)
    ("AYT", "Matematik",  "66c63893ee84e884dba34c92"),
    ("AYT", "Fizik",      "66c633fbee84e884dba34c40"),
    ("AYT", "Kimya",      "66c6375eee84e884dba34c8e"),
    ("AYT", "Biyoloji",   "66c633a1ee84e884dba34c3c"),
    ("AYT", "Turkce",     "66c63ca2ee84e884dba34ca2"),  # Turkce/Edebiyat
    ("AYT", "Tarih",      "66c63a1fee84e884dba34c9e"),
    ("AYT", "Cografya",   "66c638eeee84e884dba34c96"),
    ("AYT", "Felsefe",    "66c63953ee84e884dba34c9a"),
    # TYT Soru Bankasi (8 ders)
    ("TYT", "Matematik",  "66c640b2ee84e884dba34cba"),
    ("TYT", "Fizik",      "66c63ffeee84e884dba34cb2"),
    ("TYT", "Kimya",      "66c64050ee84e884dba34cb6"),
    ("TYT", "Biyoloji",   "66c63f09ee84e884dba34ca6"),
    ("TYT", "Turkce",     "66c64136ee84e884dba34cc2"),
    ("TYT", "Tarih",      "66c640eeee84e884dba34cbe"),
    ("TYT", "Cografya",   "66c63f75ee84e884dba34caa"),
    ("TYT", "Felsefe",    "66c63fb1ee84e884dba34cae"),
    # YDT
    ("YDT", "Ingilizce",  "66c64188ee84e884dba34cc6"),
]

# ─── KONU OZETI KITAPLARI (stable IDs 176267-176285) ─────────────────
KONU_OZETLERI = [
    ("TYT", "Turkce",     176268),
    ("TYT", "Tarih",      176269),
    ("TYT", "Matematik",  176270),
    ("TYT", "Kimya",      176271),
    ("TYT", "Fizik",      176272),
    ("TYT", "Cografya",   176273),
    ("TYT", "Biyoloji",   176274),
    ("TYT", "Felsefe",    176275),
    # AYT icin ID'ler 176276-176285 arasi (turkleme bekliyor)
    ("AYT", "Matematik",  176276),
    ("AYT", "Fizik",      176277),
    ("AYT", "Kimya",      176278),
    ("AYT", "Biyoloji",   176279),
    ("AYT", "TDE",        176280),
    ("AYT", "Tarih",      176281),
    ("AYT", "Cografya",   176282),
    ("AYT", "Felsefe",    176283),
    ("AYT", "Sosyoloji",  176284),
    ("AYT", "Mantik",     176285),
    # YDT
    ("YDT", "Ingilizce",  176267),
]

# ─── GENEL YKS HUB LINKLERI (path-based, her biri sabit) ──────────────
GENEL_HUB = [
    ("YKS", "Genel",      "yks_hazirlik",       "/YKSHazirlik",
     "YKS Hazirlik ana sayfa — tum kaynaklar"),
    ("YKS", "Genel",      "yks_denemeleri",     "/mebi-yks-denemeleri",
     "MEBİ YKS Denemeleri — online denemeler"),
    ("YKS", "Genel",      "tarama_testi",       "/mebi-tarama-testi-kitaplari",
     "Tarama Testi Kitaplari — konu tamamlama"),
    ("YKS", "Genel",      "cikmis_sorular",     "/yks-cikmis-soru-kitaplari",
     "Cikmis Sorular — kitap seti"),
    ("YKS", "Genel",      "cikmis_cozumler",    "/yks-cikmis-soru-cozumleri",
     "Cikmis Soru Cozumleri — video"),
    ("YKS", "Genel",      "konu_pekistirme",    "/yks-konu-pekistirme",
     "Dort Dortluk Konu Pekistirme Testleri"),
    ("YKS", "Genel",      "konu_anlatim_video", "/yks-konu-anlatim",
     "Konu Anlatim Videolari"),
    ("YKS", "Genel",      "online_denemeler",   "/yks-deneme-sinavlari",
     "Cevrim Ici Denemeler"),
    ("YKS", "Genel",      "puan_hesaplama",     "/yks-puan-hesaplama",
     "YKS Puan Hesaplama Motoru (MEB resmi)"),
    ("YKS", "Genel",      "3_adim_deneme",      "/yks-uc-adim-deneme",
     "3 Adim Deneme Sinavlari"),
    ("YKS", "Genel",      "3_adim_soru",        "/yks-uc-adim",
     "3 Adim Soru Bankasi (hub)"),
]


CATALOG_ROWS = []

# 3 Adim Soru Bankasi
for sinav, ders, book_id in UC_ADIM_SORU:
    CATALOG_ROWS.append({
        "konu_adi": f"{sinav} {ders} — 3 Adım Soru Bankası",
        "ders": ders,
        "sinif": sinav,  # TYT/AYT/YDT
        "kitap_id": book_id,
        "url": f"{OGM_BASE}/ogm-test/book/{book_id}",
        "icerik_ozet": f"MEB OGM {sinav} {ders} 3 Adim Soru Bankasi — kazanim bazli test, MEB resmi kaynak.",
        "icerik_tipi": "3_adim_soru_bankasi",
    })

# Konu Ozetleri
for sinav, ders, content_id in KONU_OZETLERI:
    CATALOG_ROWS.append({
        "konu_adi": f"{sinav} {ders} — MEBİ Konu Özeti",
        "ders": ders,
        "sinif": sinav,
        "kitap_id": str(content_id),
        "url": f"{OGM_BASE}/icerik-goster/{content_id}",
        "icerik_ozet": f"MEB OGM {sinav} {ders} konu ozeti kitabi — PDF indirilebilir, online okunabilir.",
        "icerik_tipi": "konu_ozeti",
    })

# Genel hub linkleri
for sinav, ders, slug, path, ozet in GENEL_HUB:
    CATALOG_ROWS.append({
        "konu_adi": f"YKS — {slug}",
        "ders": ders,
        "sinif": sinav,
        "kitap_id": slug,
        "url": f"{OGM_BASE}{path}",
        "icerik_ozet": ozet,
        "icerik_tipi": "hub_link",
    })


async def apply():
    from db_pool import db_execute, db_fetchval
    # icerik_tipi kolonu yoksa ekle (ogm_catalog.py'de yoktu)
    await db_execute("""
        ALTER TABLE ogm_catalog ADD COLUMN IF NOT EXISTS icerik_tipi TEXT
    """)
    # Mevcut kayitlari temizle (seed idempotent olsun)
    await db_execute("DELETE FROM ogm_catalog WHERE kaynak_tipi = 'ogm_materyal_seed'")

    added = 0
    for r in CATALOG_ROWS:
        try:
            await db_execute(
                """INSERT INTO ogm_catalog
                   (konu_adi, ders, sinif, kitap_id, url, icerik_ozet, icerik_tipi, kaynak_tipi)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, 'ogm_materyal_seed')""",
                r["konu_adi"], r["ders"], r["sinif"], r["kitap_id"],
                r["url"], r["icerik_ozet"], r["icerik_tipi"]
            )
            added += 1
        except Exception as e:
            print(f"HATA: {r['konu_adi']}: {e}")

    total = await db_fetchval("SELECT COUNT(*) FROM ogm_catalog")
    print(f"Seed: {added} kayit eklendi, toplam ogm_catalog: {total}")


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv(override=True)

    if args.apply:
        asyncio.run(apply())
    else:
        print(f"DRY-RUN: {len(CATALOG_ROWS)} kayit eklenecek")
        for r in CATALOG_ROWS[:5]:
            print(f"  {r['konu_adi']:50} → {r['url']}")
        print(f"  ... ({len(CATALOG_ROWS) - 5} daha)")
        print("\n--apply ile calistir")
