"""
Session Tracker — Classroom Management Çekirdek #5
====================================================
Her öğrenci için "oturum" kavramı: bugün kaç mesaj, hangi konulardan,
son redirect ne zaman yapıldı (spam önleme).

Bu modül in-memory (per-worker) + Redis'e yansır.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional
from loguru import logger


# In-memory (Redis yoksa fallback)
_SESSIONS: dict[str, dict] = {}


def _get_session_key(phone: str) -> str:
    """Oturum anahtarı — gün bazlı (00:00'da sıfırlanır)."""
    today = datetime.now().strftime("%Y%m%d")
    return f"class_session:{phone}:{today}"


def _get_or_create(phone: str) -> dict:
    key = _get_session_key(phone)
    if key not in _SESSIONS:
        _SESSIONS[key] = {
            "phone": phone,
            "msg_count": 0,
            "konu_list": [],          # bu oturumda değinilen konular
            "last_redirect_at": None,  # spam önleme
            "redirect_count": 0,       # oturum başı max 2
            "last_msg_at": None,
            "last_phase": "isinma",
        }
    return _SESSIONS[key]


def get_session(phone: str) -> dict:
    """Mevcut oturum durumunu dön."""
    return _get_or_create(phone).copy()


def record_message(phone: str, konu: str = "") -> dict:
    """Yeni mesajı say. konu varsa listeye ekle (set-like)."""
    s = _get_or_create(phone)
    s["msg_count"] += 1
    s["last_msg_at"] = datetime.now().isoformat()
    if konu and konu not in s["konu_list"]:
        s["konu_list"].append(konu)
    return s.copy()


def can_redirect(phone: str, min_gap_minutes: int = 5, max_per_session: int = 2) -> bool:
    """Redirect spam önleme:
    - Son redirect'ten en az 5 dakika geçmiş
    - Oturum başına max 2 redirect
    """
    s = _get_or_create(phone)
    if s["redirect_count"] >= max_per_session:
        return False
    last = s.get("last_redirect_at")
    if last:
        try:
            last_dt = datetime.fromisoformat(last)
            if datetime.now() - last_dt < timedelta(minutes=min_gap_minutes):
                return False
        except Exception:
            pass
    return True


def record_redirect(phone: str):
    """Redirect yapıldı, sayacı artır."""
    s = _get_or_create(phone)
    s["last_redirect_at"] = datetime.now().isoformat()
    s["redirect_count"] += 1


def get_last_konu(phone: str) -> str:
    """Oturumda son değinilen konu (redirect için hedef_konu)."""
    s = _get_or_create(phone)
    if s["konu_list"]:
        return s["konu_list"][-1]
    return ""


async def get_auto_hedef_konu(phone: str, soz_no: Optional[int] = None) -> str:
    """Session'da konu yoksa öğrencinin EN ZAYIF konusunu DB'den al.

    1. Session'da konu varsa → onu kullan
    2. Yoksa student_topic_tracker'dan en yüksek hata yüzdeli konu
    3. Yoksa son denemede en düşük net olan ders

    Returns: "Matematik - Türev" gibi string (dominant ders+konu).
    """
    # 1) Session
    last = get_last_konu(phone)
    if last:
        return last

    if not soz_no:
        return ""

    # 2) En zayıf konu (topic_tracker)
    try:
        from db_pool import db_fetchrow
        row = await db_fetchrow(
            """
            SELECT ders, konu, sinav_hata_yuzdesi
            FROM student_topic_tracker
            WHERE soz_no = $1
              AND status = 'onerilen'
              AND sinav_hata_yuzdesi >= 50
            ORDER BY sinav_hata_yuzdesi DESC
            LIMIT 1
            """,
            soz_no,
        )
        if row and row.get("konu"):
            ders = row.get("ders", "")
            konu = row["konu"]
            return f"{ders} - {konu}" if ders else konu
    except Exception as e:
        logger.debug(f"get_auto_hedef_konu tracker hatasi: {e}")

    # 3) En düşük netli ders (son deneme)
    try:
        from db_pool import db_fetchrow
        row = await db_fetchrow(
            """
            SELECT LEAST(turkce, matematik, geometri, fizik, kimya, biyoloji) as min_net
            FROM student_exams
            WHERE soz_no = $1 AND exam_name NOT LIKE '[AYT]%'
            ORDER BY exam_date DESC NULLS LAST LIMIT 1
            """,
            soz_no,
        )
        if row:
            # Hangi ders min çıktı
            row_detail = await db_fetchrow(
                """
                SELECT turkce, matematik, geometri, fizik, kimya, biyoloji
                FROM student_exams
                WHERE soz_no = $1 AND exam_name NOT LIKE '[AYT]%'
                ORDER BY exam_date DESC NULLS LAST LIMIT 1
                """,
                soz_no,
            )
            if row_detail:
                min_ders = min(row_detail.items(), key=lambda x: x[1] or 999)
                return f"{min_ders[0].title()} (son denemede zayıf)"
    except Exception as e:
        logger.debug(f"get_auto_hedef_konu exam hatasi: {e}")

    return ""


def get_summary(phone: str) -> str:
    """Oturum özeti — kapanış mesajı için."""
    s = _get_or_create(phone)
    konu_str = ", ".join(s["konu_list"][-3:]) if s["konu_list"] else "genel sohbet"
    return (
        f"Bu oturum: {s['msg_count']} mesaj, "
        f"konuştuklarımız: {konu_str}, "
        f"redirect: {s['redirect_count']}"
    )


def cleanup_old():
    """Eski oturumları in-memory'den temizle (24 saat+)."""
    now = datetime.now()
    to_remove = []
    for key, s in _SESSIONS.items():
        last = s.get("last_msg_at")
        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                if now - last_dt > timedelta(hours=24):
                    to_remove.append(key)
            except Exception:
                pass
    for k in to_remove:
        del _SESSIONS[k]
    if to_remove:
        logger.debug(f"session_tracker cleanup: {len(to_remove)} eski oturum silindi")


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    phone = "905511111111"
    # İlk mesaj
    s = record_message(phone, "türev")
    print(f"Mesaj 1: {s['msg_count']} msg, konular: {s['konu_list']}")

    # 3 mesaj daha (farklı konu)
    record_message(phone, "türev")
    record_message(phone, "integral")
    record_message(phone, "limit")

    print(f"Son durum: {get_summary(phone)}")
    print(f"can_redirect: {can_redirect(phone)}")

    record_redirect(phone)
    print(f"\n1. redirect sonrası can_redirect: {can_redirect(phone)}")  # spam önleme (5dk)

    # Manuel zaman ayarlama ile test
    import time
    _SESSIONS[_get_session_key(phone)]["last_redirect_at"] = (datetime.now() - timedelta(minutes=6)).isoformat()
    print(f"6dk sonra can_redirect: {can_redirect(phone)}")  # True (gap geçti, count 1)

    record_redirect(phone)
    print(f"2. redirect sonrası can_redirect: {can_redirect(phone)}")  # False (max 2 doldu)
