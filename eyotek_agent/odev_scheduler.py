"""
Ödev Zamanlayıcısı + Hatırlatıcı (23 Nisan)
=============================================
Öğretmen: "Ahmet'e yarına 20 soru ver" → DB'ye kaydet, yarın sabah 08:00 öğrenciye WP.
"""
from __future__ import annotations
from datetime import datetime, timedelta, date
from loguru import logger

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS fermat.odev_queue (
    id SERIAL PRIMARY KEY,
    ogrenci_soz_no INTEGER NOT NULL,
    ogretmen_id INTEGER,
    ogretmen_ad TEXT,
    odev_tanim TEXT NOT NULL,
    ders TEXT,
    konu TEXT,
    teslim_tarihi DATE,
    hatirlatma_saat INT DEFAULT 8,
    durum TEXT DEFAULT 'bekliyor',
    yaratilma_at TIMESTAMP DEFAULT NOW(),
    hatirlatildi_at TIMESTAMP,
    tamamlandi_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_odev_soz ON fermat.odev_queue(ogrenci_soz_no);
CREATE INDEX IF NOT EXISTS idx_odev_teslim ON fermat.odev_queue(teslim_tarihi, durum);
"""


async def ensure_schema():
    try:
        from db_pool import db_execute
        for stmt in [s.strip() for s in CREATE_SQL.split(";") if s.strip()]:
            await db_execute(stmt)
    except Exception as e:
        logger.debug(f"odev schema: {e}")


async def add_odev(ogrenci_soz_no: int, odev_tanim: str, ders: str = "",
                    konu: str = "", teslim_gun_sonra: int = 1,
                    ogretmen_ad: str = "") -> int:
    """Yeni ödev ekle."""
    try:
        from db_pool import db_fetchrow
        teslim = date.today() + timedelta(days=teslim_gun_sonra)
        row = await db_fetchrow(
            """
            INSERT INTO fermat.odev_queue (ogrenci_soz_no, odev_tanim, ders, konu, teslim_tarihi, ogretmen_ad)
            VALUES ($1, $2, $3, $4, $5, $6) RETURNING id
            """,
            ogrenci_soz_no, odev_tanim[:500], ders, konu, teslim, ogretmen_ad
        )
        return int(row["id"]) if row else 0
    except Exception as e:
        logger.debug(f"add_odev: {e}")
        return 0


async def get_due_reminders() -> list:
    """Bugün hatırlatılacak ödevler (scheduler çağırır 08:00)."""
    try:
        from db_pool import db_fetch
        rows = await db_fetch(
            """
            SELECT o.id, o.ogrenci_soz_no, o.odev_tanim, o.ders, o.konu,
                   o.teslim_tarihi, o.ogretmen_ad, s.full_name, s.phone
            FROM fermat.odev_queue o
            JOIN fermat.students s ON s.soz_no::text = o.ogrenci_soz_no::text
            WHERE o.durum = 'bekliyor'
              AND o.teslim_tarihi >= CURRENT_DATE
              AND (o.hatirlatildi_at IS NULL OR o.hatirlatildi_at::date < CURRENT_DATE)
            """
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.debug(f"due_reminders: {e}")
        return []


async def mark_reminded(odev_id: int):
    try:
        from db_pool import db_execute
        await db_execute(
            "UPDATE fermat.odev_queue SET hatirlatildi_at=NOW() WHERE id=$1", odev_id
        )
    except Exception:
        pass


async def mark_tamamlandi(odev_id: int):
    try:
        from db_pool import db_execute
        await db_execute(
            "UPDATE fermat.odev_queue SET durum='tamamlandi', tamamlandi_at=NOW() WHERE id=$1", odev_id
        )
    except Exception:
        pass


def format_reminder(name: str, odev_list: list) -> str:
    """WhatsApp reminder mesajı."""
    first = (name or "").split()[0] if name else ""
    if len(odev_list) == 1:
        o = odev_list[0]
        ders = f" · *{o['ders']}*" if o.get("ders") else ""
        tarih = o.get("teslim_tarihi", "").strftime("%d %B") if o.get("teslim_tarihi") else ""
        return (
            f"📝 *{first}*, bugün teslim etmen gereken bir ödev var!\n\n"
            f"---\n\n"
            f"• {o['odev_tanim'][:200]}{ders}\n"
            f"• Teslim: *{tarih}*\n\n"
            f"_Tamamladığında 'ödev tamam' yaz, düşeyim._ ✅"
        )
    lines = [f"📝 *{first}*, bu hafta {len(odev_list)} ödevin var:", "", "---", ""]
    for o in odev_list[:5]:
        tarih = o.get("teslim_tarihi", "").strftime("%d %B") if o.get("teslim_tarihi") else ""
        lines.append(f"  • {o['odev_tanim'][:80]} (teslim: *{tarih}*)")
    lines.append("\n_Öncelik sırasını birlikte belirleyelim mi?_ 🎯")
    return "\n".join(lines)
