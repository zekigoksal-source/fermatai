"""
B4 — İletişim Telafi Mekanizması

Mantık:
1. Öğrenci frustration sinyali gönderdiğinde (chatgpt'ye gidiyom, anlamıyorsun,
   sıkıcı, bıktım) → frustration_log'a kayıt (follow_up_pending=true)
2. Arka plan scheduler her 30 dakikada bir bekleyenleri kontrol eder
3. Şartlar: 08-20 arası + en az 30dk geçmiş + max 24 saat geçmemiş
4. Telafi mesajı: "az önce [konu] için daha iyi anlayabilirdim, denemek ister misin?"

Neo onayı ile aktif olur — ALERTS_ACTIVE True olmalı (alarm sistemi).
"""
import asyncio
import os
from datetime import datetime, timedelta
from loguru import logger

# Telafi özellikleri
# 22.1n-kural1 (Neo 20 Nisan): KULLANICIYA MESAJ YASAK — yeni sezon 1 Eylul'e kadar.
# Eski onay (18 Nisan) iptal edildi — son 50 gunde riske girmeyecek.
# Yeni sezon: TELAFI_ACTIVE=True + OUTREACH_ENABLED=true yapilacak.
TELAFI_ACTIVE = os.getenv("TELAFI_ACTIVE", "false").lower() in ("1", "true", "yes")

TELAFI_MIN_DELAY_MIN = 30   # En az 30dk sonra
TELAFI_MAX_AGE_HOURS = 24   # 24 saat geçmişse iptal
TELAFI_HOUR_MIN = 10        # 10:00 öncesi YOK (Neo talebi: kahvaltı + toparlanma payı)
TELAFI_HOUR_MAX = 21        # 21:00 sonrası YOK (gece mesaj yasağı)

TELAFI_TEMPLATES = [
    # Neo 19 Nisan 00:00 — bazı templatelerde web tavsiyesi (ileri deneyim için)
    "Az önce {konu} hakkında sorun vardı — o zaman daha iyi açıklayabilirdim. "
    "Şimdi denesen daha net anlatabilirim. 💙",

    "Dünyükü {konu} konusuna geri dönsek — bu sefer adım adım gidelim, "
    "nerede takıldığını anla da çözelim. 🎯",

    "Biraz önceki {konu} için daha iyi olabilirdim, biliyorum. "
    "Tekrar deneyelim istersen? 🙏",

    "Az önceki {konu} konuşması pek iyi gitmedi — özür dilerim. "
    "Bu sefer grafik ve tabloyla daha net görürüz, web'de daha detaylı konuşabiliriz:\n"
    "🌐 *fermategitimkurumlari.com/fermatai*\n"
    "WP'den \"web kodu\" yaz, hemen girebilirsin. 💙",

    "{konu} hakkındaki son konuşmamız beni de tatmin etmedi — haklıydın. "
    "Web arayüzünde grafik + tablo + LaTeX ile çok daha net anlatabilirim. "
    "İstersen _\"web kodu\"_ yaz, orada konuşalım. 🎯",

    "Biraz önce {konu} için zayıf kaldığımı fark ettim. Tekrar deneyelim mi? "
    "Eğer uzun bir analiz olacaksa web arayüzüm daha rahat görürsün:\n"
    "fermategitimkurumlari.com/fermatai — \"web kodu\" ile gir. 🙏",
]


async def log_frustration(phone: str, trigger_msg: str, context_summary: str = ""):
    """Frustration sinyali kaydet — telafi kuyruğuna ekle."""
    if not TELAFI_ACTIVE:
        return False  # Pasif — sadece log
    try:
        from db_pool import db_execute
        await db_execute(
            "INSERT INTO frustration_log (phone, trigger_msg, context_summary) VALUES ($1, $2, $3)",
            phone, (trigger_msg or "")[:300], (context_summary or "")[:1000]
        )
        logger.info(f"😔 Frustration kayıt: {phone[-4:]} — '{trigger_msg[:40]}'")
        return True
    except Exception as e:
        logger.warning(f"Frustration log hatası: {e}")
        return False


async def check_and_send_telafi(send_wa_func=None):
    """
    Bekleyen telafi mesajlarını gönder. Scheduler çağırır (30 dk periyodla).
    send_wa_func: whatsapp_bridge.send_wa_message
    """
    if not TELAFI_ACTIVE:
        return {"sent": 0, "pending": 0, "reason": "TELAFI_ACTIVE=False"}

    now = datetime.now()
    if not (TELAFI_HOUR_MIN <= now.hour < TELAFI_HOUR_MAX):
        return {"sent": 0, "pending": 0, "reason": f"Saat dışı ({TELAFI_HOUR_MIN:02d}:00-{TELAFI_HOUR_MAX:02d}:00)"}

    try:
        from db_pool import db_fetch, db_execute
        rows = await db_fetch(
            """
            SELECT id, phone, trigger_msg, context_summary, created_at
            FROM frustration_log
            WHERE follow_up_pending = TRUE
              AND created_at < NOW() - INTERVAL '30 minutes'
              AND created_at > NOW() - INTERVAL '24 hours'
            ORDER BY created_at ASC
            LIMIT 10
            """
        )
        sent = 0
        import random
        for r in rows:
            # Konu tahmini — context'ten anahtar kelime
            ctx = (r["context_summary"] or "").lower()
            konu = "o konu"
            for k in ["matematik", "fizik", "kimya", "biyoloji", "türkçe", "geometri",
                     "deneme", "çalışma planı", "zayıf konu"]:
                if k in ctx:
                    konu = k
                    break

            msg = random.choice(TELAFI_TEMPLATES).format(konu=konu)
            try:
                if send_wa_func:
                    # 22.1n-kural1: outreach marker (TELAFI_ACTIVE=False iken buraya hic gelmez)
                    try:
                        await send_wa_func(r["phone"], msg, _outreach=True, _reason="frustration_telafi")
                    except TypeError:
                        # Eski interface — sadece iki parametre kabul ediyorsa fallback
                        await send_wa_func(r["phone"], msg)
                await db_execute(
                    "UPDATE frustration_log SET follow_up_pending=FALSE, follow_up_sent_at=NOW() WHERE id=$1",
                    r["id"]
                )
                sent += 1
                logger.info(f"✨ Telafi gönderildi: {r['phone'][-4:]} → {konu}")
            except Exception as e:
                logger.warning(f"Telafi gönderim hatası: {e}")

        # 24 saatten eskileri iptal et (expired)
        await db_execute(
            "UPDATE frustration_log SET follow_up_pending=FALSE "
            "WHERE follow_up_pending=TRUE AND created_at < NOW() - INTERVAL '24 hours'"
        )

        return {"sent": sent, "pending": len(rows) - sent}

    except Exception as e:
        logger.error(f"Telafi kontrol hatası: {e}")
        return {"sent": 0, "error": str(e)[:100]}


async def stats():
    """Telafi istatistikleri (admin görebilsin)."""
    try:
        from db_pool import db_fetchrow
        r = await db_fetchrow(
            """
            SELECT
                COUNT(*) FILTER (WHERE follow_up_pending) AS bekleyen,
                COUNT(*) FILTER (WHERE follow_up_sent_at IS NOT NULL) AS gonderildi,
                COUNT(*) AS toplam
            FROM frustration_log
            WHERE created_at > NOW() - INTERVAL '7 days'
            """
        )
        return dict(r) if r else {}
    except Exception:
        return {}
