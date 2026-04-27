"""
F4 — Conditional Assignments + Eskalasyon (Oturum 25.28)
==============================================================

Öğretmen / rehber → öğrenciye deadline'lı to-do atar.
Sistem otomatik:
  - Deadline'a 2 gün kala reminder (öğrenciye)
  - Deadline geçti + tamamlanmadı → eskalasyon (atayan + opsiyonel veli)

Bot tool: assign_todo_with_deadline(student, task, deadline_days, ...)

ŞU AN: TODO_ESCALATION_WP_ACTIVE=False — eskalasyon WP gönderim kapalı,
sadece todo_escalation_queue'ya yazılır (admin görür).
"""
from __future__ import annotations
import asyncio
import json
from datetime import datetime, timedelta
from typing import Optional
from loguru import logger


async def is_escalation_wp_active() -> bool:
    try:
        from db_pool import db_fetchval
        v = await db_fetchval(
            "SELECT value FROM sistem_ayar WHERE key='TODO_ESCALATION_WP_ACTIVE'"
        )
        return (v or "").lower() == "true"
    except Exception:
        return False


async def assign_todo_with_deadline(
    soz_no: int,
    title: str,
    description: str = "",
    deadline_days: int = 7,
    assigned_by_phone: str = "",
    assigned_by_role: str = "teacher",
    topic_ref: str = "",
    resource_links: Optional[list] = None,
    priority: str = "normal",
) -> Optional[int]:
    """student_todo'ya deadline'lı kayıt + reminder/eskalasyon timeline ayarla.

    Returns: new todo id or None.
    """
    from db_pool import db_fetchval

    if not soz_no or not title:
        return None

    deadline = datetime.now() + timedelta(days=deadline_days)
    reminder_at = deadline - timedelta(days=2)

    # Eskalasyon hedefi: atayan rolüne göre
    escalation_target = "teacher" if assigned_by_role == "teacher" else "rehber"

    new_id = await db_fetchval(
        """INSERT INTO student_todo
           (soz_no, title, priority, deadline, reminder_at,
            escalation_target, topic_ref, resource_links)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb)
           RETURNING id""",
        soz_no, title, priority, deadline, reminder_at,
        escalation_target, topic_ref,
        json.dumps(resource_links or [], default=str)
    )
    logger.info(f"📌 [TODO] {soz_no} icin '{title}' atandi (deadline: {deadline:%d.%m})")
    return int(new_id) if new_id else None


async def find_pending_reminders() -> list[dict]:
    """Reminder zamanı gelmiş ama henüz gönderilmemiş todo'ları getir."""
    from db_pool import db_fetch
    rows = await db_fetch(
        """SELECT t.id, t.soz_no, t.title, t.deadline, t.reminder_at,
                  s.full_name, s.phone
           FROM student_todo t
           JOIN students s ON s.soz_no = t.soz_no::text
           WHERE t.completed = false
             AND t.reminder_at IS NOT NULL
             AND t.reminder_at <= NOW()
             AND t.reminder_sent_at IS NULL
             AND t.deadline > NOW()
           ORDER BY t.deadline ASC LIMIT 100"""
    )
    return [dict(r) for r in rows]


async def find_passed_deadlines() -> list[dict]:
    """Deadline geçmiş ama tamamlanmamış + eskale edilmemiş todo'lar."""
    from db_pool import db_fetch
    rows = await db_fetch(
        """SELECT t.id, t.soz_no, t.title, t.deadline,
                  t.escalation_target, t.escalated_at,
                  s.full_name, s.phone
           FROM student_todo t
           JOIN students s ON s.soz_no = t.soz_no::text
           WHERE t.completed = false
             AND t.deadline IS NOT NULL
             AND t.deadline <= NOW()
             AND t.escalated_at IS NULL
           ORDER BY t.deadline DESC LIMIT 100"""
    )
    return [dict(r) for r in rows]


async def queue_reminder(todo: dict) -> Optional[int]:
    """Hatırlatma queue'ya yaz (öğrenciye, deadline yaklaşıyor)."""
    from db_pool import db_fetchval, db_execute

    feature_active = await is_escalation_wp_active()
    deadline = todo["deadline"]
    days_left = max(1, (deadline - datetime.now()).days) if deadline else 2

    payload = {
        "todo_id": todo["id"],
        "title": todo["title"],
        "deadline": deadline.isoformat() if deadline else None,
        "days_left": days_left,
        "message": f"📌 {days_left} gün kaldı: '{todo['title']}'. Bugün başlayalım mı?",
    }

    new_id = await db_fetchval(
        """INSERT INTO todo_escalation_queue
           (todo_id, soz_no, student_name, target_role, target_phone, target_name,
            escalation_type, payload, wp_active_at_queue)
           VALUES ($1,$2,$3,'student',$4,$5,'reminder_2d',$6::jsonb,$7)
           RETURNING id""",
        todo["id"], todo["soz_no"], todo["full_name"],
        todo.get("phone"), todo["full_name"],
        json.dumps(payload, default=str), feature_active
    )

    # student_todo'da reminder_sent_at işaretle (queue'lanma anı)
    await db_execute(
        "UPDATE student_todo SET reminder_sent_at=NOW() WHERE id=$1",
        todo["id"]
    )
    return int(new_id) if new_id else None


async def queue_escalation(todo: dict) -> Optional[int]:
    """Deadline geçti — atayan/rehber'e bildirim queue."""
    from db_pool import db_fetchval, db_execute

    feature_active = await is_escalation_wp_active()
    target_role = todo.get("escalation_target", "rehber")

    # Rehber phone bul (acl_users'tan)
    target_phone = None
    target_name = ""
    try:
        from db_pool import db_fetchrow
        if target_role == "teacher":
            # Atanani bilemiyoruz, rehber'e default
            target_role = "rehber"
        row = await db_fetchrow(
            "SELECT phone, full_name FROM acl_users "
            "WHERE LOWER(role) IN ('rehber', 'admin', 'mudur') "
            "ORDER BY CASE role WHEN 'rehber' THEN 1 WHEN 'mudur' THEN 2 ELSE 3 END LIMIT 1"
        )
        if row:
            target_phone = row["phone"]
            target_name = row["full_name"]
    except Exception:
        pass

    payload = {
        "todo_id": todo["id"],
        "title": todo["title"],
        "deadline": todo["deadline"].isoformat() if todo.get("deadline") else None,
        "student": todo["full_name"],
        "message": (f"⚠️ {todo['full_name']} '{todo['title']}' görevini "
                    f"deadline ({todo['deadline']:%d.%m}) geçti, tamamlamadı."),
    }

    new_id = await db_fetchval(
        """INSERT INTO todo_escalation_queue
           (todo_id, soz_no, student_name, target_role, target_phone, target_name,
            escalation_type, payload, wp_active_at_queue)
           VALUES ($1,$2,$3,$4,$5,$6,'deadline_passed',$7::jsonb,$8)
           RETURNING id""",
        todo["id"], todo["soz_no"], todo["full_name"],
        target_role, target_phone, target_name,
        json.dumps(payload, default=str), feature_active
    )

    # student_todo'da escalated_at işaretle
    await db_execute(
        "UPDATE student_todo SET escalated_at=NOW() WHERE id=$1",
        todo["id"]
    )
    return int(new_id) if new_id else None


async def process_reminders_and_escalations() -> dict:
    """Tüm bekleyen reminder + escalation'ları queue'ya yaz.

    WP gönderim feature_active'e göre — ŞU AN false (yeni sezon).
    """
    pending_reminders = await find_pending_reminders()
    passed_deadlines = await find_passed_deadlines()

    rem_count = 0
    esc_count = 0
    for r in pending_reminders:
        try:
            if await queue_reminder(r):
                rem_count += 1
        except Exception as e:
            logger.warning(f"[TODO_REMINDER] {r['id']} fail: {e}")

    for d in passed_deadlines:
        try:
            if await queue_escalation(d):
                esc_count += 1
        except Exception as e:
            logger.warning(f"[TODO_ESCALATION] {d['id']} fail: {e}")

    return {
        "reminders_queued": rem_count,
        "escalations_queued": esc_count,
        "wp_active": await is_escalation_wp_active(),
    }


async def deliver_pending() -> dict:
    """WP_ACTIVE=true ise queue'daki bildirim mesajlarını gönderir."""
    feature_active = await is_escalation_wp_active()
    if not feature_active:
        return {"delivered": 0, "reason": "feature_inactive (yeni sezon)"}
    return {"delivered": 0, "reason": "delivery_not_implemented_yet"}


async def todo_scheduler_loop():
    """Bridge lifespan loop — her 30dk reminder/escalation tarama."""
    logger.info("📌 Todo Assignment scheduler basladi (30dk periyod)")
    while True:
        try:
            r = await process_reminders_and_escalations()
            if r["reminders_queued"] or r["escalations_queued"]:
                logger.info(f"📌 [TODO_SCHED] {r}")
        except Exception as e:
            logger.error(f"[TODO_LOOP] {e}")
        await asyncio.sleep(1800)  # 30dk


# ─── CLI ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    async def _main():
        if len(sys.argv) > 1 and sys.argv[1] == "process":
            r = await process_reminders_and_escalations()
            print(json.dumps(r, ensure_ascii=False, indent=2))
        elif len(sys.argv) > 4 and sys.argv[1] == "assign":
            soz = int(sys.argv[2])
            title = sys.argv[3]
            days = int(sys.argv[4])
            new_id = await assign_todo_with_deadline(soz, title, deadline_days=days)
            print(f"todo id={new_id}")
        else:
            print("Kullanim: python todo_assignment.py [process|assign <soz_no> <title> <days>]")
    asyncio.run(_main())
