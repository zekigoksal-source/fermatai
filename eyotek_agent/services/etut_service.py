"""
etut_service — Etüt + plan tool'ları (Oturum 25.41-REFACTOR, 9 May)
====================================================================

fermat_core_agent.py'den taşınan etüt/plan tool fonksiyonları:
  - build_study_plan      (57 satır) — çalışma planı için akademik veri toplama
  - get_class_plan        (71 satır) — öğrenci ders programı + günlük etüt
  - log_eyotek_action     (helper)   — Eyotek aksiyon DB log

Mimari ilke:
    "Brain centralized (fermat_core_agent), execution modular (services/)"
"""
from __future__ import annotations
from typing import Any


# ─────────────────────────────────────────────────────────────────────────
# tool_build_study_plan (taşındı — fermat_core_agent.py:741-795)
# ─────────────────────────────────────────────────────────────────────────

async def build_study_plan(student_id: str = "") -> dict:
    """Çalışma planı için öğrencinin tüm akademik verilerini toplar."""
    from study_plan_builder import build_study_plan_context

    # 1) Direkt int veya int'e cast olabilen string
    if isinstance(student_id, int):
        return await build_study_plan_context(student_id)

    s = str(student_id).strip()
    if not s:
        return {"error": "student_id bos. soz_no (int) veya isim string ver."}

    # 2) Sayisal string mi?
    try:
        soz = int(s)
        return await build_study_plan_context(soz)
    except ValueError:
        pass

    # 3) İsim string — students tablosunda lookup (Türkçe normalize)
    try:
        from db_pool import db_fetchval
        # (a) Tam isim ILIKE
        soz = await db_fetchval(
            "SELECT soz_no FROM students WHERE full_name ILIKE $1 LIMIT 1",
            f"%{s}%"
        )
        # (b) Türkçe büyük harf normalize
        if not soz:
            tr_lower = s.translate(str.maketrans("İIĞŞÜÖÇ", "iığşüöç")).lower()
            soz = await db_fetchval(
                "SELECT soz_no FROM students WHERE LOWER(full_name) LIKE $1 LIMIT 1",
                f"%{tr_lower}%"
            )
        # (c) İlk kelime fallback
        if not soz and " " in s:
            first_word = s.split()[0].translate(str.maketrans("İIĞŞÜÖÇ", "iığşüöç")).lower()
            soz = await db_fetchval(
                "SELECT soz_no FROM students WHERE LOWER(full_name) LIKE $1 LIMIT 1",
                f"%{first_word}%"
            )
        if soz:
            return await build_study_plan_context(int(soz))
        return {"error": f"'{s}' isminde ogrenci bulunamadi. Once query_analytics ile soz_no'yu bul."}
    except Exception as e:
        return {"error": f"Lookup hata: {e}"}


# ─────────────────────────────────────────────────────────────────────────
# tool_get_class_plan (taşındı — fermat_core_agent.py:798-846)
# ─────────────────────────────────────────────────────────────────────────

async def get_class_plan(student_id: str = "", date: str = "") -> dict:
    """Öğrenci ders programı + günlük etüt listesi — çakışma kontrolü için."""
    from db_pool import db_fetch as _db_fetch
    result: dict[str, Any] = {}

    # Günlük etüt listesi
    if date or not student_id:
        from datetime import date as _d
        target = date or _d.today().strftime("%d.%m.%Y")
        etut_rows = await _db_fetch(
            """SELECT full_name, lesson, target_date, ders_no, teacher, classroom, etut_type
               FROM etut_records WHERE target_date = $1 ORDER BY ders_no""",
            target,
        )
        result["daily_etut"] = etut_rows
        result["etut_date"] = target
        result["etut_count"] = len(etut_rows)

    # Öğrenci ders programı
    if student_id:
        students = await _db_fetch(
            """SELECT eyotek_id, full_name, class_name FROM students
               WHERE eyotek_id = $1 OR full_name ILIKE $2 OR soz_no = $1 LIMIT 1""",
            student_id, f"%{student_id}%",
        )
        if students:
            eid = students[0]["eyotek_id"]
            timetable = await _db_fetch(
                """SELECT gun, ders_no, saat, ders, ogretmen, derslik
                   FROM student_timetable WHERE eyotek_id = $1 ORDER BY gun, ders_no""",
                eid,
            )
            result["student"] = students[0]["full_name"]
            result["timetable"] = timetable
            result["timetable_count"] = len(timetable)

            # Bu öğrencinin mevcut etütlerini de getir
            student_etut = await _db_fetch(
                """SELECT lesson, target_date, ders_no, teacher, classroom
                   FROM etut_records WHERE eyotek_id = $1 OR full_name = $2
                   ORDER BY target_date DESC LIMIT 10""",
                eid, students[0]["full_name"],
            )
            result["student_etut"] = student_etut

    if not result:
        result["message"] = "Ogrenci veya tarih belirtilmedi"

    return result


# ─────────────────────────────────────────────────────────────────────────
# log_eyotek_action helper (taşındı — fermat_core_agent.py:849-866)
# ─────────────────────────────────────────────────────────────────────────

async def log_eyotek_action(
    phone: str, role: str, action: str,
    params: dict, reason: str, success: bool, result_msg: str,
) -> None:
    """Eyotek aksiyonunu eyotek_action_log tablosuna yaz (hata olsa geçer)."""
    import json
    import os
    from loguru import logger
    from db_pool import db_execute as _db_execute, DB_URL as DATABASE_URL

    if not DATABASE_URL:
        return
    try:
        await _db_execute(
            """INSERT INTO eyotek_action_log
               (phone, role, action, params, reason, success, result_msg)
               VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7)""",
            phone, role, action,
            json.dumps(params, ensure_ascii=False, default=str),
            reason, success, result_msg[:500],
        )
    except Exception as e:
        logger.warning(f"Aksiyon log yazılamadı: {e}")


__all__ = ["build_study_plan", "get_class_plan", "log_eyotek_action"]
