"""
LGS Topic Tracker Seed (Oturum 22.1m)
======================================

LGS öğrencileri için `student_topic_tracker` tablosuna MEB 8.sınıf müfredatını
seed eder. Mevcut tablo yapısı korunur, sadece `sinav_turu='LGS'` eklenir.

Kullanim:
    python lgs_topic_seed.py            # tum LGS ogrencilerine seed
    python lgs_topic_seed.py --soz_no 450   # spesifik ogrenci

LGS Müfredat (MEB 2025-26, 90 soru toplam):
- Matematik 20 soru (12 konu)
- Türkçe 20 soru (6 ana konu)
- Fen 20 soru (8 ana konu)
- T.C. İnkılap Tarihi 10 soru (7 ünite)
- Din Kültürü 10 soru (6 konu)
- İngilizce 10 soru (8 ünite)
"""
import asyncio
import sys
import io
from typing import Optional

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


# ═════════════════════════════════════════════════════════════════════
# MEB LGS MÜFREDAT (8. sınıf)
# ═════════════════════════════════════════════════════════════════════
LGS_MUFREDAT = {
    "Matematik": [
        "Çarpanlar ve Katlar",
        "Üslü İfadeler",
        "Kareköklü İfadeler",
        "Veri Analizi",
        "Basit Olayların Olma Olasılığı",
        "Cebirsel İfadeler ve Özdeşlikler",
        "Doğrusal Denklemler",
        "Eşitsizlikler",
        "Üçgenler",
        "Eşlik ve Benzerlik",
        "Dönüşüm Geometri",
        "Geometrik Cisimler",
    ],
    "Türkçe": [
        "Sözcükte Anlam",
        "Cümlede Anlam",
        "Paragrafta Anlam",
        "Metin Türleri",
        "Yazım ve Noktalama",
        "Söz Sanatları",
    ],
    "Fen Bilimleri": [
        "Mevsimler ve İklim",
        "DNA ve Genetik Kod",
        "Basınç",
        "Madde ve Endüstri",
        "Basit Makineler",
        "Enerji Dönüşümleri ve Çevre",
        "Elektrik Yükleri ve Elektrik Enerjisi",
        "Canlılar ve Enerji İlişkileri",
    ],
    "T.C. İnkılap Tarihi": [
        "Bir Kahraman Doğuyor",
        "Milli Uyanış: Bağımsızlık Yolunda",
        "Ya İstiklal Ya Ölüm",
        "Çağdaş Türkiye Yolunda Adımlar",
        "Demokratikleşme Çabaları",
        "Atatürkçülük ve Çağdaşlaşan Türkiye",
        "Atatürk Sonrası Türkiye",
    ],
    "Din Kültürü": [
        "Kader ve Kaza İnancı",
        "Zekat, Sadaka ve Hac",
        "Din ve Hayat",
        "Hz. Muhammed'in Örnekliği",
        "Kur'an-ı Kerim ve Özellikleri",
        "İslam Düşüncesinde Yorumlar",
    ],
    "İngilizce": [
        "Friendship",
        "Teen Life",
        "In the Kitchen",
        "On the Phone",
        "The Internet",
        "Adventures",
        "Tourism",
        "Chores",
    ],
}


async def get_lgs_students():
    """LGS sinavina girecek ogrencileri bul (8. sinif veya class_name 'LGS' icerir)."""
    from db_pool import db_fetch
    rows = await db_fetch(
        """SELECT soz_no, full_name, class_name
           FROM students
           WHERE (class_name LIKE '%8%' OR class_name ILIKE '%LGS%')
             AND status='active'
           ORDER BY soz_no"""
    )
    return rows


async def seed_student(soz_no: int) -> dict:
    """Bir LGS öğrencisine tüm LGS konularını seed et."""
    from db_pool import db_fetchval, db_execute, db_fetchrow

    # Öğrenci var mı? — students.soz_no TEXT
    ogr = await db_fetchrow(
        "SELECT soz_no, full_name FROM students WHERE soz_no = $1 AND status='active'",
        str(soz_no)
    )
    if not ogr:
        return {"soz_no": soz_no, "eklenen": 0, "hata": "Öğrenci bulunamadi"}

    eklenen = 0
    atlanan = 0
    for ders, konular in LGS_MUFREDAT.items():
        for konu in konular:
            # Mevcut kayıt var mı?
            exists = await db_fetchval(
                """SELECT 1 FROM student_topic_tracker
                   WHERE soz_no=$1 AND ders=$2 AND konu=$3 AND sinav_turu='LGS' LIMIT 1""",
                int(soz_no), ders, konu
            )
            if exists:
                atlanan += 1
                continue
            try:
                await db_execute(
                    """INSERT INTO student_topic_tracker
                         (soz_no, ders, konu, status, sinav_turu, sinav_hata_sayisi, sinav_hata_yuzdesi, tamamlandi)
                       VALUES ($1, $2, $3, 'yeni', 'LGS', 0, NULL, FALSE)""",
                    int(soz_no), ders, konu
                )
                eklenen += 1
            except Exception as e:
                pass  # unique constraint veya diğer

    return {
        "soz_no": soz_no,
        "isim": ogr["full_name"],
        "eklenen": eklenen,
        "atlanan": atlanan,
        "toplam_konu": sum(len(v) for v in LGS_MUFREDAT.values()),
    }


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--soz_no", type=int, help="Spesifik öğrenci")
    parser.add_argument("--dry-run", action="store_true", help="Sadece simülasyon")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv(override=True)

    print("=" * 60)
    print(f"LGS TOPIC TRACKER SEED")
    print(f"Mufredat: {sum(len(v) for v in LGS_MUFREDAT.values())} konu, "
          f"{len(LGS_MUFREDAT)} ders")
    print("=" * 60)

    if args.soz_no:
        students = [{"soz_no": args.soz_no, "full_name": "?", "class_name": ""}]
    else:
        students = await get_lgs_students()
        print(f"\nLGS ogrencileri: {len(students)}")
        for s in students:
            print(f"  {s['soz_no']}: {s['full_name']} ({s['class_name']})")
        print()

    if args.dry_run:
        print("DRY-RUN — hiçbir kayıt eklenmeyecek")
        return

    total_eklenen = 0
    for s in students:
        result = await seed_student(s["soz_no"])
        print(f"  {result['soz_no']} ({result.get('isim','?')}): "
              f"+{result['eklenen']} konu ({result['atlanan']} zaten vardı)")
        total_eklenen += result["eklenen"]

    print(f"\n✅ Toplam {total_eklenen} kayit eklendi.")


if __name__ == "__main__":
    asyncio.run(main())
