"""
FermatAI — PDF Rapor Arsivi (Hafta 4.2)
========================================
Aylik toplu PDF rapor uretimi.
- Her ogrenci icin ay sonu raporu
- reports/YYYY-MM/ dizininde arsivlenir
- Admin'e ozet rapor + isteyene tek tek PDF gonderim

Kullanim:
  python pdf_archive.py                    # Bu ay icin tum ogrenci raporu
  python pdf_archive.py --ay 2026-03       # Belirli ay
  python pdf_archive.py --soz 230          # Tek ogrenci
  python pdf_archive.py --send-admin       # Admin'e ozet + dosya yollarini gonder

VELI'YE GONDERIM YASAK (Bu sezon — Mayis 2026 sonuna kadar).
"""

import asyncio
import os
import sys
from datetime import date, datetime
from pathlib import Path

from loguru import logger
from db_pool import db_fetch
ARCHIVE_ROOT = Path(__file__).parent / "reports"


async def _list_active_students() -> list:
    """Aktif ogrenciler (sinav verisi olanlar oncelikli)."""
    return await db_fetch("""
        SELECT DISTINCT s.soz_no, s.full_name, s.class_name
        FROM students s
        WHERE s.full_name IS NOT NULL
        AND s.full_name NOT LIKE '%TEST%'
        ORDER BY s.full_name
    """)


async def generate_monthly_archive(month_str: str = None) -> dict:
    """Belirtilen ay icin tum ogrenci PDF'lerini uret."""
    if not month_str:
        month_str = date.today().strftime("%Y-%m")

    target_dir = ARCHIVE_ROOT / month_str
    target_dir.mkdir(parents=True, exist_ok=True)

    students = await _list_active_students()
    logger.info(f"📊 {len(students)} ogrenci icin {month_str} raporu uretilecek")

    sonuc = {
        'ay': month_str,
        'toplam': len(students),
        'basarili': 0,
        'hatali': 0,
        'atlanan': 0,
        'dosyalar': [],
        'hatalar': [],
    }

    from pdf_report import generate_student_pdf

    for i, st in enumerate(students, 1):
        soz_no = st['soz_no']
        try:
            # Daha önce uretildiyse atla
            existing = list(target_dir.glob(f"*_{soz_no}_*.pdf"))
            if existing:
                sonuc['atlanan'] += 1
                continue

            path = await generate_student_pdf(soz_no)
            if path and os.path.exists(path):
                # Dosyayi ay arsiv klasorune tasi
                src = Path(path)
                # safe_name_YYYYMMDD.pdf → safe_name_sozno_YYYYMM.pdf (ay arsivi formati)
                new_name = f"{src.stem.rsplit('_', 1)[0]}_{soz_no}_{month_str}.pdf"
                dst = target_dir / new_name
                src.rename(dst)
                sonuc['basarili'] += 1
                sonuc['dosyalar'].append(str(dst))
                if i % 10 == 0:
                    logger.info(f"  ... {i}/{len(students)}")
            else:
                sonuc['atlanan'] += 1
        except Exception as e:
            sonuc['hatali'] += 1
            sonuc['hatalar'].append(f"{soz_no} ({st['full_name']}): {e}")
            logger.error(f"  HATA {soz_no}: {e}")

    logger.info(f"✅ Tamamlandi — basarili: {sonuc['basarili']}, atlanan: {sonuc['atlanan']}, hatali: {sonuc['hatali']}")
    return sonuc


def format_archive_summary(sonuc: dict) -> str:
    """Admin'e WP ozet."""
    lines = [
        f"📁 *AY ARŞİVİ — {sonuc['ay']}*\n",
        "━━━━━━━━━━━━━━━━━━━━━━━",
        f"📊 Toplam ogrenci: *{sonuc['toplam']}*",
        f"✅ Basarili PDF: *{sonuc['basarili']}*",
        f"⏭️ Atlanan: *{sonuc['atlanan']}*",
        f"❌ Hatali: *{sonuc['hatali']}*",
        "",
        f"📂 Konum: `reports/{sonuc['ay']}/`",
    ]
    if sonuc['hatalar']:
        lines.append("\n*Hatalar (ilk 5):*")
        for h in sonuc['hatalar'][:5]:
            lines.append(f"  • {h}")
    lines.append("\n_'rapor gonder [isim]' tek ogrenci PDF'i WP'den paylasilabilir._")
    lines.append("_⚠️ Veliye gonderim YASAK — sezon sonuna kadar._")
    return "\n".join(lines)


async def get_archive_for_student(soz_no: str, month_str: str = None) -> str:
    """Belirli ogrencinin arsivdeki PDF dosya yolunu dondur."""
    if not month_str:
        month_str = date.today().strftime("%Y-%m")
    target_dir = ARCHIVE_ROOT / month_str
    target_dir.mkdir(parents=True, exist_ok=True)

    matches = list(target_dir.glob(f"*_{soz_no}_*.pdf"))
    if matches:
        return str(matches[0])

    # Üret
    try:
        from pdf_report import generate_student_pdf
        path = await generate_student_pdf(int(soz_no))
        if not path or not os.path.exists(path):
            logger.error(f"PDF uretilmedi: soz_no={soz_no}")
            return None
        src = Path(path)
        new_name = f"{src.stem.rsplit('_', 1)[0]}_{soz_no}_{month_str}.pdf"
        dst = target_dir / new_name
        # Eger hedef varsa once sil
        if dst.exists():
            dst.unlink()
        src.rename(dst)
        return str(dst)
    except Exception as e:
        logger.error(f"PDF uretim hatasi (soz={soz_no}): {e}")
        return None


async def main():
    args = sys.argv[1:]
    month = None
    if "--ay" in args:
        month = args[args.index("--ay") + 1]

    if "--soz" in args:
        soz = args[args.index("--soz") + 1]
        path = await get_archive_for_student(soz, month)
        if path:
            print(f"✅ PDF: {path}")
        else:
            print("❌ Olusturulamadi")
        return

    sonuc = await generate_monthly_archive(month)
    print(format_archive_summary(sonuc))

    if "--send-admin" in args:
        try:
            from whatsapp_bridge import send_wa_message
            ADMIN = "905051256802"
            # 22.1n-kural1: outreach marker
            await send_wa_message(ADMIN, format_archive_summary(sonuc), _outreach=True, _reason="pdf_archive")
            print("\n✅ Admin'e WP gonderildi")
        except Exception as e:
            print(f"\n❌ WP gonderim hatasi: {e}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
