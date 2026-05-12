"""
B8 — Günlük Push Bildirim

Sabah 08:15 aktif öğrencilere WP push:
- Bugünkü zayıf konu hatırlatması (en yüksek 1-2)
- Varsa etüt saatleri
- Yarınki deneme hatırlatması
- YKS geri sayım

Neo onayı ile PUSH_ACTIVE=True olur. Aksi halde sadece dry-run log.
"""
import asyncio
from datetime import datetime, date
from loguru import logger

PUSH_ACTIVE = False  # Neo onayi ile aktif
PUSH_HOUR = 8   # Sabah 08:15
PUSH_MIN = 15


async def build_student_push(soz_no, full_name, class_name) -> str | None:
    """Öğrenci için kişisel push mesajı oluştur."""
    try:
        from db_pool import db_fetch, db_fetchrow, db_fetchval
        fname = full_name.split()[0] if full_name else ""

        # 25.44 (Neo bug 14:25): YKS tarihi sinav_takvimi.py'dan (sezon başında otomatik 2027'ye geçer)
        from sinav_takvimi import TYT_DATE as yks
        gun = (yks - date.today()).days
        if gun < 0:
            return None  # YKS geçmiş

        # En yüksek 2 zayıf konu — sinav_hata_yuzdesi = HATA% (yüksek=zayıf)
        # Metadata satırları + "Ortalama X/Y net" pseudo-konular hariç
        weak = await db_fetch(
            "SELECT ders, konu FROM student_topic_tracker "
            "WHERE soz_no::text = $1::text "
            "  AND COALESCE(status,'') NOT IN ('calisildi','metadata') "
            "  AND konu NOT LIKE 'Ortalama %' "
            "  AND sinav_hata_yuzdesi >= 25 "
            "ORDER BY sinav_hata_yuzdesi DESC NULLS LAST LIMIT 2",
            str(soz_no)
        )

        # Bugün etüt var mı (öğrenci için)
        etut = await db_fetchval(
            "SELECT COUNT(*) FROM etut_history "
            "WHERE tarih = CURRENT_DATE "
            "  AND UPPER(yoklama) LIKE $1",
            f"%{full_name.upper() if full_name else ''}%"
        ) or 0

        msg = f"Günaydın *{fname}* 🌅\n\n"
        msg += f"YKS'ye *{gun} gün* kaldı.\n\n"

        if weak:
            msg += "📉 *Bugün odaklanmanı önerdiğim konular:*\n"
            for w in weak:
                msg += f"• {w['ders']} — {w['konu']}\n"
            msg += "\n"

        if etut > 0:
            msg += f"📅 Bugün *{etut} etüdün* var — unutma!\n\n"

        msg += "_Detay için 'zayıf konularım' yaz ya da web'e gir._ 🎯"
        return msg

    except Exception as e:
        logger.warning(f"Push mesaj üretme hatası (soz={soz_no}): {e}")
        return None


async def send_daily_push(send_wa_func=None, dry_run=True):
    """
    Sabah push gönderimi. Scheduler bunu 08:15'te çağırır.
    dry_run=True: sadece log, gönderme.
    """
    now = datetime.now()

    # Saat kontrolü
    if now.hour != PUSH_HOUR or now.minute >= PUSH_MIN + 15:
        logger.debug(f"Push saati değil ({now.hour:02d}:{now.minute:02d})")
        return {"sent": 0, "reason": "saat dışı"}

    if not PUSH_ACTIVE and not dry_run:
        return {"sent": 0, "reason": "PUSH_ACTIVE=False"}

    try:
        from db_pool import db_fetch
        students = await db_fetch(
            "SELECT s.soz_no, s.full_name, s.class_name, s.phone "
            "FROM students s WHERE s.status='active' "
            "  AND s.phone IS NOT NULL AND s.phone != '' "
            "  AND EXISTS (SELECT 1 FROM acl_users a WHERE REPLACE(a.phone,'+','') = REPLACE(s.phone,'+','') "
            "               AND a.is_active = TRUE)"
        )
        sent = 0
        for st in students:
            msg = await build_student_push(st["soz_no"], st["full_name"], st["class_name"])
            if not msg:
                continue
            if dry_run or not PUSH_ACTIVE:
                logger.info(f"📬 [DRY-RUN] Push {st['phone'][-4:]} ({st['full_name'][:20]}) → {len(msg)}c")
            else:
                try:
                    if send_wa_func:
                        await send_wa_func(st["phone"].replace("+", ""), msg)
                    sent += 1
                    logger.info(f"📬 Push gönderildi: {st['phone'][-4:]} ({st['full_name'][:20]})")
                except Exception as e:
                    logger.warning(f"Push gönderim hatası: {e}")
            # Rate limit — Meta API 20/sec
            await asyncio.sleep(0.2)

        return {"sent": sent, "total": len(students), "dry_run": dry_run}
    except Exception as e:
        logger.error(f"Daily push hatası: {e}")
        return {"sent": 0, "error": str(e)[:100]}
