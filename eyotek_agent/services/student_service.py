"""
student_service — Öğrenci profili + ACL + arama (Oturum 25.29)
==================================================================

Sorumluluk alanı:
  - students tablosu (profil, sınıf, sezon, telefon, veli)
  - acl_users (rol, durum)
  - search_students helper (Türkçe karakter normalize)
  - devamsizlik_sayisi (toplam saat)

DRY: mevcut SQL pattern'larını gruplar — yeni kuyruk açmaz.
"""
from __future__ import annotations
import asyncio
from typing import Optional
from loguru import logger


# Türkçe karakter normalize tablosu (mevcut sistem ile uyumlu)
_TR_UPPER = str.maketrans("iığşüöç", "İIĞŞÜÖÇ")


async def get_profile(soz_no: int) -> Optional[dict]:
    """Öğrenci profili (basic info)."""
    from db_pool import db_fetchrow
    try:
        row = await db_fetchrow(
            """SELECT soz_no, full_name, first_name, last_name, class_name,
                      sezon, sube, program, devre, kur, status,
                      phone, parent_name, eyotek_id, kayit_tarihi
               FROM students
               WHERE soz_no::int = $1
               LIMIT 1""",
            soz_no,
        )
        return dict(row) if row else None
    except Exception as e:
        logger.debug(f"[student_service] get_profile fail: {e}")
        return None


async def get_profile_by_phone(phone: str) -> Optional[dict]:
    """Telefondan profil — bot kanal entry point."""
    from db_pool import db_fetchrow
    if not phone:
        return None
    phone_clean = phone.replace("+", "").strip()
    try:
        row = await db_fetchrow(
            """SELECT soz_no, full_name, first_name, last_name, class_name,
                      sezon, status, phone
               FROM students
               WHERE REPLACE(phone, '+', '') = $1
               LIMIT 1""",
            phone_clean,
        )
        return dict(row) if row else None
    except Exception as e:
        logger.debug(f"[student_service] get_profile_by_phone fail: {e}")
        return None


async def search_by_name(query: str, limit: int = 10) -> list[dict]:
    """Türkçe karakter normalize ile öğrenci ara."""
    from db_pool import db_fetch
    if not query or len(query) < 2:
        return []
    q = query.strip()
    q_upper = q.translate(_TR_UPPER).upper()
    try:
        rows = await db_fetch(
            """SELECT soz_no, full_name, class_name, status, phone
               FROM students
               WHERE UPPER(full_name) ILIKE '%' || $1 || '%'
                  OR full_name ILIKE '%' || $2 || '%'
               ORDER BY
                 CASE WHEN status = 'active' THEN 0 ELSE 1 END,
                 full_name
               LIMIT $3""",
            q_upper, q, limit,
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.debug(f"[student_service] search_by_name fail: {e}")
        return []


async def get_acl(phone: str) -> Optional[dict]:
    """ACL rolü + aktiflik."""
    from db_pool import db_fetchrow
    if not phone:
        return None
    phone_clean = phone.replace("+", "").strip()
    try:
        row = await db_fetchrow(
            """SELECT phone, full_name, role, is_active
               FROM acl_users
               WHERE REPLACE(phone, '+', '') = $1
               LIMIT 1""",
            phone_clean,
        )
        return dict(row) if row else None
    except Exception:
        return None


async def get_attendance_total(soz_no: int) -> int:
    """devamsizlik_sayisi.toplam_saat döner."""
    from db_pool import db_fetchval
    try:
        v = await db_fetchval(
            "SELECT toplam_saat FROM devamsizlik_sayisi WHERE soz_no = $1",
            soz_no,
        )
        return int(v or 0)
    except Exception:
        return 0


async def get_class_students(class_name: str) -> list[dict]:
    """Sınıf bazlı aktif öğrenci listesi."""
    from db_pool import db_fetch
    try:
        rows = await db_fetch(
            """SELECT soz_no, full_name, class_name, status
               FROM students
               WHERE class_name ILIKE '%' || $1 || '%'
                 AND status = 'active'
               ORDER BY full_name""",
            class_name,
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.debug(f"[student_service] get_class_students fail: {e}")
        return []


async def count_active() -> dict:
    """Toplam aktif öğrenci sayısı + sınıf dağılımı."""
    from db_pool import db_fetch, db_fetchval
    try:
        total = await db_fetchval(
            "SELECT COUNT(*) FROM students WHERE status='active'"
        )
        rows = await db_fetch(
            """SELECT class_name, COUNT(*) AS n
               FROM students WHERE status='active'
               GROUP BY class_name
               ORDER BY n DESC LIMIT 20"""
        )
        return {
            "total_active": int(total or 0),
            "by_class": [{"class_name": r["class_name"], "n": int(r["n"])} for r in rows],
        }
    except Exception as e:
        logger.debug(f"[student_service] count_active fail: {e}")
        return {"total_active": 0, "by_class": []}


# ─── CLI test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys, json
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    async def _test(arg):
        if arg.isdigit():
            print(f"=== student_service — get_profile({arg}) ===")
            p = await get_profile(int(arg))
            print(json.dumps(p, indent=2, ensure_ascii=False, default=str))
            print()
            ab = await get_attendance_total(int(arg))
            print(f"Devamsızlık total: {ab} saat")
        else:
            print(f"=== student_service — search_by_name({arg!r}) ===")
            results = await search_by_name(arg, limit=5)
            for r in results:
                print(f"  - [{r['soz_no']}] {r['full_name']} ({r['class_name']})")
        print()
        c = await count_active()
        print(f"Toplam aktif: {c['total_active']}")

    arg = sys.argv[1] if len(sys.argv) > 1 else "244"
    asyncio.run(_test(arg))
