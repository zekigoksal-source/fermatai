"""
Gamification Katmanı (23 Nisan Neo vizyonu)
=============================================
Streak, Achievement, Haftalık liderlik — dopamine hook.
"""
from __future__ import annotations
from datetime import datetime, date
from loguru import logger

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS fermat.ogrenci_streak (
    soz_no INTEGER PRIMARY KEY,
    current_streak INT DEFAULT 0,
    best_streak INT DEFAULT 0,
    last_activity_date DATE,
    total_days_active INT DEFAULT 0
);
CREATE TABLE IF NOT EXISTS fermat.ogrenci_achievements (
    id SERIAL PRIMARY KEY,
    soz_no INTEGER NOT NULL,
    achievement_code TEXT NOT NULL,
    baslik TEXT,
    aciklama TEXT,
    kazanildi_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(soz_no, achievement_code)
);
CREATE INDEX IF NOT EXISTS idx_ach_soz_no ON fermat.ogrenci_achievements(soz_no);
"""

ACHIEVEMENTS = {
    "ilk_sohbet": ("🎉 Hoş Geldin", "İlk mesaj attın, sisteme adım attın"),
    "3_gun_streak": ("🔥 3 Günlük Seri", "3 gün üst üste sistemle çalıştın"),
    "7_gun_streak": ("🔥🔥 Haftalık Ritim", "1 hafta kesintisiz"),
    "30_gun_streak": ("🔥🔥🔥 Alışkanlık", "1 ay boyunca her gün"),
    "ilk_deneme": ("📝 İlk Deneme", "Sisteme ilk denemen geldi"),
    "5_net_artis": ("📈 +5 Net", "Toplam netin 5 arttı"),
    "10_net_artis": ("🚀 +10 Net", "Toplam netin 10 arttı"),
    "zayif_kapama": ("🎯 Konu Fatih", "Zayıf bir konuyu tamamladın"),
    "ilk_plan": ("📅 Planlı Başlangıç", "İlk çalışma planını oluşturdun"),
    "10_konu_sorusu": ("📚 Meraklı", "10 farklı konu sordun"),
    "foto_5": ("📸 Foto Uzmanı", "5 foto soru çözümü"),
    "erken_kus": ("🌅 Erken Kuş", "Sabah 08:00 öncesi aktif"),
    "gece_yarisi": ("🦉 Gece Kuşu", "23:00 sonrası çalışma"),
}


async def ensure_schema():
    try:
        from db_pool import db_execute
        for stmt in [s.strip() for s in CREATE_SQL.split(";") if s.strip()]:
            await db_execute(stmt)
    except Exception as e:
        logger.debug(f"gami schema: {e}")


async def tick_streak(soz_no: int) -> dict:
    """Öğrenci aktiflik sinyali — streak güncelle."""
    try:
        from db_pool import db_fetchrow, db_execute
        today = date.today()
        row = await db_fetchrow(
            "SELECT current_streak, best_streak, last_activity_date, total_days_active "
            "FROM fermat.ogrenci_streak WHERE soz_no=$1", soz_no
        )
        if not row:
            await db_execute(
                "INSERT INTO fermat.ogrenci_streak (soz_no, current_streak, best_streak, last_activity_date, total_days_active) "
                "VALUES ($1, 1, 1, $2, 1) ON CONFLICT (soz_no) DO NOTHING",
                soz_no, today
            )
            await unlock(soz_no, "ilk_sohbet")
            return {"current": 1, "best": 1, "new_milestone": "ilk_sohbet"}

        last = row["last_activity_date"]
        curr = row["current_streak"] or 0
        best = row["best_streak"] or 0
        total = row["total_days_active"] or 0

        if last == today:
            return {"current": curr, "best": best, "new_milestone": None}

        delta_days = (today - last).days if last else 999
        if delta_days == 1:
            curr += 1
            total += 1
        else:
            curr = 1
            total += 1

        best = max(best, curr)
        new_ms = None
        if curr == 3:
            new_ms = "3_gun_streak"
            await unlock(soz_no, new_ms)
        elif curr == 7:
            new_ms = "7_gun_streak"
            await unlock(soz_no, new_ms)
        elif curr == 30:
            new_ms = "30_gun_streak"
            await unlock(soz_no, new_ms)

        await db_execute(
            "UPDATE fermat.ogrenci_streak SET current_streak=$1, best_streak=$2, "
            "last_activity_date=$3, total_days_active=$4 WHERE soz_no=$5",
            curr, best, today, total, soz_no
        )
        return {"current": curr, "best": best, "new_milestone": new_ms}
    except Exception as e:
        logger.debug(f"tick_streak: {e}")
        return {"current": 0, "best": 0, "new_milestone": None}


async def unlock(soz_no: int, achievement_code: str) -> bool:
    """Achievement aç."""
    if achievement_code not in ACHIEVEMENTS:
        return False
    baslik, aciklama = ACHIEVEMENTS[achievement_code]
    try:
        from db_pool import db_execute
        await db_execute(
            "INSERT INTO fermat.ogrenci_achievements (soz_no, achievement_code, baslik, aciklama) "
            "VALUES ($1,$2,$3,$4) ON CONFLICT (soz_no, achievement_code) DO NOTHING",
            soz_no, achievement_code, baslik, aciklama
        )
        return True
    except Exception as e:
        logger.debug(f"unlock: {e}")
        return False


async def get_stats(soz_no: int) -> dict:
    """Öğrencinin gamification durumu."""
    try:
        from db_pool import db_fetchrow, db_fetch
        streak = await db_fetchrow(
            "SELECT current_streak, best_streak, total_days_active "
            "FROM fermat.ogrenci_streak WHERE soz_no=$1", soz_no
        )
        achievements = await db_fetch(
            "SELECT achievement_code, baslik FROM fermat.ogrenci_achievements WHERE soz_no=$1 "
            "ORDER BY kazanildi_at DESC", soz_no
        )
        return {
            "current_streak": (streak or {}).get("current_streak", 0),
            "best_streak": (streak or {}).get("best_streak", 0),
            "total_days": (streak or {}).get("total_days_active", 0),
            "achievements": [dict(a) for a in achievements],
        }
    except Exception:
        return {"current_streak": 0, "best_streak": 0, "total_days": 0, "achievements": []}


async def format_celebration(soz_no: int, milestone: str, name: str) -> str | None:
    """Yeni achievement kazanıldığında kutlama mesajı."""
    if not milestone or milestone not in ACHIEVEMENTS:
        return None
    baslik, aciklama = ACHIEVEMENTS[milestone]
    first = (name or "").split()[0] if name else ""
    return (
        f"{baslik}\n\n"
        f"*{first}*, {aciklama}! 🎉\n\n"
        f"_Devam et, sen harikasın!_"
    )
