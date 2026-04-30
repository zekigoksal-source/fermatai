"""
Active Recall — Ebbinghaus Spaced Repetition
=============================================
25.37 (Neo direktif): pasif izleme → aktif öğrenme.

Render edildikten sonra → 24/72/168 saat sonra konuyu öğrenciye geri sor.
Eğer konuyu hala biliyor → interval x2.5 (Anki algoritması).
Bilmiyor → 24h reset.

Tablo: active_recalls
  - recall_id   SERIAL PK
  - soz_no      INT
  - konu        TEXT
  - ders        TEXT
  - context_summary TEXT — ilk render edildiğinde ne anlatıldı
  - scheduled_at TIMESTAMP — geri sorulacak zaman
  - completed_at TIMESTAMP — öğrenci yanıt verdi
  - success     BOOLEAN — hatırladı mı
  - interval_days INT — sonraki interval
  - created_at  TIMESTAMP
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta
from typing import Optional
from loguru import logger
from db_pool import db_execute, db_fetch, db_fetchrow, db_fetchval


async def ensure_table():
    try:
        await db_execute("""
            CREATE TABLE IF NOT EXISTS active_recalls (
                recall_id SERIAL PRIMARY KEY,
                soz_no INTEGER NOT NULL,
                konu TEXT NOT NULL,
                ders TEXT,
                context_summary TEXT,
                scheduled_at TIMESTAMP NOT NULL,
                completed_at TIMESTAMP,
                success BOOLEAN,
                interval_days INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT NOW(),
                triggered BOOLEAN DEFAULT FALSE
            )
        """)
        await db_execute(
            "CREATE INDEX IF NOT EXISTS idx_recall_pending ON active_recalls(scheduled_at, completed_at) WHERE completed_at IS NULL"
        )
        await db_execute(
            "CREATE INDEX IF NOT EXISTS idx_recall_soz ON active_recalls(soz_no, completed_at)"
        )
    except Exception as e:
        logger.warning(f"active_recalls ensure_table hata: {e}")


async def schedule_recall(
    soz_no: int,
    konu: str,
    ders: str = "",
    context_summary: str = "",
    recall_after_hours: int = 24,
) -> dict:
    """N saat sonra hatırlat. Default 24h (Ebbinghaus 1. interval)."""
    if not soz_no or not konu:
        return {"success": False, "error": "soz_no ve konu zorunlu"}
    try:
        await ensure_table()
        # Aynı öğrenci + aynı konu son 6 saatte zaten schedule edildiyse skip
        recent = await db_fetchval(
            """SELECT recall_id FROM active_recalls
               WHERE soz_no = $1 AND konu = $2
                 AND created_at > NOW() - INTERVAL '6 hours'
                 AND completed_at IS NULL
               LIMIT 1""",
            int(soz_no), konu[:120]
        )
        if recent:
            return {
                "success": True, "skipped": True, "existing_recall_id": recent,
                "reason": "Aynı konu son 6 saatte schedule edildi"
            }
        scheduled = datetime.now() + timedelta(hours=int(recall_after_hours or 24))
        recall_id = await db_fetchval(
            """INSERT INTO active_recalls
               (soz_no, konu, ders, context_summary, scheduled_at, interval_days)
               VALUES ($1, $2, $3, $4, $5, $6) RETURNING recall_id""",
            int(soz_no), konu[:120], ders[:60],
            context_summary[:500], scheduled,
            max(1, int(recall_after_hours / 24))
        )
        logger.info(f"recall scheduled: id={recall_id} soz={soz_no} konu={konu[:30]} +{recall_after_hours}h")
        return {
            "success": True, "recall_id": recall_id,
            "scheduled_at": scheduled.isoformat(),
            "konu": konu, "interval_hours": recall_after_hours,
        }
    except Exception as e:
        logger.error(f"schedule_recall hata: {e}")
        return {"success": False, "error": str(e)}


async def get_pending_recalls(soz_no: int, limit: int = 20) -> list[dict]:
    """Bekleyen + scheduled_at geçmiş recall'lar."""
    if not soz_no:
        return []
    try:
        await ensure_table()
        rows = await db_fetch(
            """SELECT recall_id, konu, ders, context_summary, scheduled_at, interval_days
               FROM active_recalls
               WHERE soz_no = $1 AND completed_at IS NULL
                 AND scheduled_at <= NOW() + INTERVAL '1 hour'
               ORDER BY scheduled_at ASC LIMIT $2""",
            int(soz_no), int(limit or 20)
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"get_pending_recalls hata: {e}")
        return []


async def mark_completed(recall_id: int, success: bool) -> dict:
    """Öğrenci yanıt verdi → hatırladı mı kayıt et + sonraki interval planla."""
    try:
        await ensure_table()
        row = await db_fetchrow(
            "SELECT soz_no, konu, ders, context_summary, interval_days FROM active_recalls WHERE recall_id = $1",
            int(recall_id)
        )
        if not row:
            return {"success": False, "error": "Recall bulunamadı"}
        await db_execute(
            "UPDATE active_recalls SET completed_at = NOW(), success = $2 WHERE recall_id = $1",
            int(recall_id), bool(success)
        )
        # Spaced repetition: başardıysa interval x2.5, başaramadıysa reset 24h
        if success:
            new_interval = max(1, int(row["interval_days"] * 2.5))
            # Max 30 gün — daha sonra anlamı yok
            new_interval = min(new_interval, 30)
        else:
            new_interval = 1  # reset
        # Sıradaki recall planla
        await schedule_recall(
            soz_no=row["soz_no"], konu=row["konu"], ders=row["ders"] or "",
            context_summary=row["context_summary"] or "",
            recall_after_hours=new_interval * 24
        )
        return {
            "success": True, "next_interval_days": new_interval,
            "spaced_rep": "anki-style"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def get_due_recalls_for_admin(limit: int = 50) -> list[dict]:
    """Admin: tüm öğrencilerin pending recall'larını gör."""
    try:
        await ensure_table()
        rows = await db_fetch(
            """SELECT r.recall_id, r.soz_no, r.konu, r.ders, r.scheduled_at,
                      s.full_name, s.phone
               FROM active_recalls r
               LEFT JOIN students s ON s.soz_no = r.soz_no
               WHERE r.completed_at IS NULL AND r.scheduled_at <= NOW()
               ORDER BY r.scheduled_at ASC LIMIT $1""",
            int(limit or 50)
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"get_due_recalls hata: {e}")
        return []


async def cleanup_old_completed(days: int = 90) -> int:
    """90 gün+ tamamlanmış recall'ları sil (DB temiz tut)."""
    try:
        await ensure_table()
        result = await db_execute(
            "DELETE FROM active_recalls WHERE completed_at < NOW() - INTERVAL '%s days'" % int(days),
        )
        return 0
    except Exception:
        return 0


# CLI
async def _cli():
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "ensure"
    if cmd == "ensure":
        await ensure_table()
        print("OK")
    elif cmd == "due":
        rows = await get_due_recalls_for_admin()
        for r in rows:
            print(f"{r['scheduled_at']} #{r['recall_id']} {r['full_name']} → {r['konu']}")
    elif cmd == "schedule":
        # python active_recall.py schedule SOZ_NO "KONU" "DERS"
        r = await schedule_recall(
            soz_no=int(sys.argv[2]),
            konu=sys.argv[3],
            ders=sys.argv[4] if len(sys.argv) > 4 else "",
            recall_after_hours=24
        )
        print(r)


if __name__ == "__main__":
    asyncio.run(_cli())
