"""
Insight Backfill — Geçmiş konuşmalardan retrospektif çıkarım (22.1n-vizyon)
===========================================================================

Mevcut öğrenci konuşmaları üzerinden insight_extractor çalıştırıp
eski kayıtlardan da mood/active_topic/weak_belief vs çıkarır.

Amaç: Yeni sezon başında context zengin olsun — öğrenci ilk mesaj
attığında "sende son zamanda şöyle bir pattern gördüm" bağlamı kurulsun.

KURAL (22.1n-kural1):
- Bu script MESAJ ATMAZ. Sadece DB okur + yazar.
- Ollama kullanır ($0 maliyet).
- Her öğrenci için max 50 mesaj → en fazla 50 insight çıkar.

KULLANIM:
  python insight_backfill.py --days 30              # son 30 gün
  python insight_backfill.py --soz_no 174 --days 60 # tek öğrenci
  python insight_backfill.py --dry-run              # çalıştırma, sadece sayım
"""
import asyncio
import sys
from datetime import datetime, timedelta

from loguru import logger


async def get_students_with_messages(days: int = 30) -> list[dict]:
    """Son N gün mesaj atan öğrenciler."""
    from db_pool import db_fetch
    rows = await db_fetch(
        """SELECT DISTINCT s.soz_no, s.full_name, s.phone,
                  COUNT(ac.id) AS mesaj_sayisi
           FROM students s
           JOIN agent_conversations ac ON REPLACE(s.phone,'+','') = ac.phone
           WHERE s.status='active' AND ac.message_role='user'
             AND ac.created_at > NOW() - INTERVAL '%d days'
           GROUP BY s.soz_no, s.full_name, s.phone
           ORDER BY COUNT(ac.id) DESC""" % int(days)
    )
    return [dict(r) for r in rows]


async def get_student_messages(soz_no: int, phone: str, days: int = 30,
                                limit: int = 50) -> list[dict]:
    """Öğrencinin son N gün user mesajları (en uzun olanlar)."""
    from db_pool import db_fetch
    phone_clean = (phone or "").replace("+", "")
    rows = await db_fetch(
        f"""SELECT ac.content, ac.created_at,
                   LEAD(ac2.content) OVER (ORDER BY ac.id) AS bot_reply
            FROM agent_conversations ac
            LEFT JOIN agent_conversations ac2
              ON ac2.phone = ac.phone AND ac2.id = ac.id + 1
              AND ac2.message_role = 'assistant'
            WHERE ac.phone = $1 AND ac.message_role = 'user'
              AND ac.created_at > NOW() - INTERVAL '{int(days)} days'
              AND LENGTH(ac.content) > 20
              AND ac.content NOT LIKE '[%'
            ORDER BY LENGTH(ac.content) DESC LIMIT {int(limit)}""",
        phone_clean,
    )
    return [dict(r) for r in rows]


async def backfill_student(soz_no: int, phone: str, days: int = 30,
                            max_msgs: int = 30, dry_run: bool = False) -> dict:
    """Tek öğrenci için backfill."""
    from insight_extractor import run_extraction_background, INSIGHT_TTL

    msgs = await get_student_messages(soz_no, phone, days, limit=max_msgs)
    if not msgs:
        return {"soz_no": soz_no, "msg_count": 0, "extracted": 0}

    extracted = 0
    for m in msgs:
        user_msg = (m.get("content") or "")[:800]
        bot_reply = (m.get("bot_reply") or "")[:400]
        if not user_msg or len(user_msg) < 15:
            continue
        if dry_run:
            extracted += 1
            continue
        try:
            await run_extraction_background(
                phone=phone, soz_no=soz_no,
                user_msg=user_msg, bot_msg=bot_reply,
            )
            extracted += 1
        except Exception as e:
            logger.debug(f"  backfill err: {e}")

    return {"soz_no": soz_no, "msg_count": len(msgs), "extracted": extracted}


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--soz_no", type=int, default=0, help="Tek ogrenci icin")
    parser.add_argument("--max-msgs", type=int, default=30, help="Ogrenci basina max mesaj")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--min-messages", type=int, default=5,
                        help="Bu kadar mesajdan az atan ogrencileri atla")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv(override=True)

    if args.soz_no:
        from db_pool import db_fetchrow
        row = await db_fetchrow(
            "SELECT soz_no, phone, full_name FROM students WHERE soz_no=$1",
            args.soz_no,
        )
        if not row:
            print(f"Ogrenci bulunamadi: {args.soz_no}")
            return
        students = [dict(row)]
    else:
        students = await get_students_with_messages(args.days)
        students = [s for s in students if s["mesaj_sayisi"] >= args.min_messages]

    print(f"{'[DRY-RUN] ' if args.dry_run else ''}Backfill: {len(students)} ogrenci, son {args.days} gun, max {args.max_msgs} mesaj/ogrenci")

    total_extracted = 0
    for i, s in enumerate(students, 1):
        r = await backfill_student(
            s["soz_no"], s["phone"],
            days=args.days, max_msgs=args.max_msgs, dry_run=args.dry_run,
        )
        total_extracted += r["extracted"]
        print(f"  [{i}/{len(students)}] {s.get('full_name','?')[:30]:30} — {r['msg_count']} msg, {r['extracted']} islendi")

    print(f"\nToplam: {total_extracted} mesaj işlendi")
    if args.dry_run:
        print("(DRY-RUN: insight yazilmadi)")


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    asyncio.run(main())
