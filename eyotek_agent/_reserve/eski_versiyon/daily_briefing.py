"""
FermatAI Sabah Briefing
========================
Her sabah admin'e gunluk ozet gonderir:
  - Devamsiz ogrenciler
  - Yuksek riskli profiller
  - Gunun planli etutleri
  - Genel kurum istatistikleri

Kullanim:
  python daily_briefing.py              # Ozeti konsola yaz
  python daily_briefing.py --send       # Ozeti WhatsApp ile gonder
"""

import asyncio
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import asyncpg
from dotenv import load_dotenv
from loguru import logger

load_dotenv(override=True)

DATABASE_URL = os.getenv("DATABASE_URL", "")
ADMIN_PHONE = os.getenv("ADMIN_PHONE", "+905051256802")


async def _db_fetch(sql: str, *args) -> list[dict]:
    if not DATABASE_URL:
        return []
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        rows = await conn.fetch(sql, *args)
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def generate_briefing() -> str:
    """Gunluk briefing metnini olustur."""
    today = date.today()
    today_str = today.strftime("%d.%m.%Y")
    day_name_tr = {
        "Monday": "Pazartesi", "Tuesday": "Sali", "Wednesday": "Carsamba",
        "Thursday": "Persembe", "Friday": "Cuma",
        "Saturday": "Cumartesi", "Sunday": "Pazar",
    }
    gun = day_name_tr.get(today.strftime("%A"), today.strftime("%A"))

    lines = []
    lines.append(f"FERMAT AI - SABAH BRIEFING")
    lines.append(f"{today_str} {gun}")
    lines.append("=" * 35)

    # 1. Ogrenci sayisi
    students = await _db_fetch("SELECT COUNT(*) as cnt FROM students WHERE status != 'Silindi' OR status IS NULL")
    total_students = students[0]["cnt"] if students else 0
    lines.append(f"\nKurum: {total_students} aktif ogrenci")

    # 2. Bugunun devamsizlari
    absences = await _db_fetch(
        "SELECT full_name, sube, ders_no FROM attendance WHERE tarih = $1",
        today_str,
    )
    if absences:
        lines.append(f"\nBUGUN DEVAMSIZ: {len(absences)} kayit")
        # Ogrenci bazli grupla
        by_student = {}
        for a in absences:
            name = a.get("full_name", "?")
            if name not in by_student:
                by_student[name] = {"sube": a.get("sube", ""), "ders": []}
            by_student[name]["ders"].append(a.get("ders_no", "?"))
        for name, info in sorted(by_student.items()):
            dersler = ",".join(str(d) for d in info["ders"])
            lines.append(f"  - {name} ({info['sube']}) ders:{dersler}")
    else:
        lines.append(f"\nDevamsizlik verisi yok (henuz sync edilmemis olabilir)")

    # 3. Yuksek riskli ogrenciler (devamsizlik > 10 veya son 7 gunde 3+ devamsizlik)
    week_ago = (today - timedelta(days=7)).strftime("%d.%m.%Y")
    risk_students = await _db_fetch("""
        SELECT a.full_name, a.sube, COUNT(*) as devamsizlik_sayisi
        FROM attendance a
        WHERE a.tarih >= $1
        GROUP BY a.full_name, a.sube
        HAVING COUNT(*) >= 3
        ORDER BY COUNT(*) DESC
        LIMIT 10
    """, week_ago)

    if risk_students:
        lines.append(f"\nRISKLI PROFILLER (son 7 gun):")
        for r in risk_students:
            lines.append(f"  ! {r['full_name']} ({r['sube']}) - {r['devamsizlik_sayisi']} devamsizlik")

    # 4. Personel ozeti
    staff = await _db_fetch("SELECT COUNT(*) as cnt FROM staff WHERE status = 'Aktif' OR status IS NULL")
    staff_cnt = staff[0]["cnt"] if staff else 0
    lines.append(f"\nPersonel: {staff_cnt} aktif")

    # 5. Son 24 saatte agent kullanimi
    agent_usage = await _db_fetch("""
        SELECT COUNT(*) as cnt FROM agent_conversations
        WHERE created_at >= NOW() - INTERVAL '24 hours'
    """)
    usage_cnt = agent_usage[0]["cnt"] if agent_usage else 0
    if usage_cnt > 0:
        lines.append(f"Agent kullanimi (24s): {usage_cnt} mesaj")

    # 6. Son eyotek aksiyonlari
    actions = await _db_fetch("""
        SELECT action, COUNT(*) as cnt, SUM(CASE WHEN success THEN 1 ELSE 0 END) as basarili
        FROM eyotek_action_log
        WHERE created_at >= NOW() - INTERVAL '24 hours'
        GROUP BY action
    """)
    if actions:
        lines.append(f"\nEyotek aksiyonlari (24s):")
        for a in actions:
            lines.append(f"  {a['action']}: {a['cnt']} islem ({a['basarili']} basarili)")

    lines.append("\n" + "=" * 35)
    lines.append("FermatAI v1.0 | Otonom Egitim Asistani")

    return "\n".join(lines)


async def main():
    briefing = await generate_briefing()
    print(briefing)

    if "--send" in sys.argv:
        # WhatsApp ile gonder
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            from whatsapp_bridge import send_wa_message
            sent = await send_wa_message(ADMIN_PHONE, briefing)
            if sent:
                logger.success(f"Briefing WhatsApp ile gonderildi: {ADMIN_PHONE}")
            else:
                logger.warning("WhatsApp gonderimi basarisiz (WA config eksik olabilir)")
        except Exception as e:
            logger.error(f"WhatsApp gonderim hatasi: {e}")


if __name__ == "__main__":
    asyncio.run(main())
