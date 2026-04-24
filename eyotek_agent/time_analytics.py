"""
Time-of-Day Analytics — Kullanim Desenleri (23 Nisan)
=======================================================
Neo'nun sorusu: "Ne zaman en çok foto atıyorlar? Deneme analizi hep akşam
21:00'de mi?"

Bu modül:
  - Saat bazlı mesaj dağılımı (0-23 saat)
  - Peak saatler (top 3)
  - Gün bazlı pattern (hafta içi vs hafta sonu)
  - Intent bazlı zaman desenleri (foto/deneme/konu anlatım/sohbet)
  - Rol bazlı davranış (öğrenci gece, öğretmen gündüz vb.)
"""
from __future__ import annotations
from loguru import logger


async def get_hourly_distribution(days: int = 7) -> list[dict]:
    """Son N günün saat bazlı mesaj dağılımı."""
    try:
        from db_pool import db_fetch
        rows = await db_fetch(
            f"""
            SELECT
                EXTRACT(HOUR FROM created_at)::int AS saat,
                COUNT(*) AS mesaj,
                COUNT(DISTINCT phone) AS kisi
            FROM fermat.agent_conversations
            WHERE message_role = 'user'
              AND created_at >= NOW() - INTERVAL '{int(days)} days'
              AND COALESCE(session_id,'') NOT LIKE '_test_%'
            GROUP BY saat
            ORDER BY saat
            """
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.debug(f"hourly distribution hatasi: {e}")
        return []


async def get_peak_hours(days: int = 7, top: int = 3) -> list[dict]:
    """En yoğun saatler."""
    dist = await get_hourly_distribution(days)
    sorted_dist = sorted(dist, key=lambda x: x["mesaj"], reverse=True)
    return sorted_dist[:top]


async def get_weekday_vs_weekend(days: int = 14) -> dict:
    """Hafta içi vs hafta sonu kıyas."""
    try:
        from db_pool import db_fetchrow
        row = await db_fetchrow(
            f"""
            SELECT
                COUNT(*) FILTER (WHERE EXTRACT(DOW FROM created_at) BETWEEN 1 AND 5) AS haftaici,
                COUNT(*) FILTER (WHERE EXTRACT(DOW FROM created_at) IN (0, 6)) AS haftasonu,
                COUNT(DISTINCT phone) FILTER (WHERE EXTRACT(DOW FROM created_at) BETWEEN 1 AND 5) AS haftaici_kisi,
                COUNT(DISTINCT phone) FILTER (WHERE EXTRACT(DOW FROM created_at) IN (0, 6)) AS haftasonu_kisi
            FROM fermat.agent_conversations
            WHERE message_role = 'user'
              AND created_at >= NOW() - INTERVAL '{int(days)} days'
              AND COALESCE(session_id,'') NOT LIKE '_test_%'
            """
        )
        return dict(row) if row else {}
    except Exception as e:
        logger.debug(f"weekday vs weekend hatasi: {e}")
        return {}


async def get_intent_time_pattern(days: int = 7) -> list[dict]:
    """Intent (foto/deneme/genel) bazlı saat desenleri."""
    try:
        from db_pool import db_fetch
        # Mesaj içeriğinden heuristik intent
        rows = await db_fetch(
            f"""
            SELECT
                CASE
                    WHEN LOWER(content) LIKE '%[foto%' OR LOWER(content) LIKE '%foto soru%' THEN 'foto'
                    WHEN LOWER(content) LIKE '%deneme%' OR LOWER(content) LIKE '%sinav%' OR LOWER(content) LIKE '%sınav%' THEN 'sinav'
                    WHEN LOWER(content) LIKE '%nedir%' OR LOWER(content) LIKE '%acikla%' OR LOWER(content) LIKE '%açıkla%' THEN 'konu'
                    WHEN LOWER(content) LIKE '%plan%' OR LOWER(content) LIKE '%program%' THEN 'plan'
                    ELSE 'sohbet'
                END AS intent,
                EXTRACT(HOUR FROM created_at)::int AS saat,
                COUNT(*) AS adet
            FROM fermat.agent_conversations
            WHERE message_role = 'user'
              AND created_at >= NOW() - INTERVAL '{int(days)} days'
              AND COALESCE(session_id,'') NOT LIKE '_test_%'
            GROUP BY intent, saat
            ORDER BY intent, saat
            """
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.debug(f"intent time pattern hatasi: {e}")
        return []


async def get_role_time_pattern(days: int = 7) -> list[dict]:
    """Rol bazlı saat dağılımı (öğrenci gece mi, öğretmen gündüz mü?)"""
    try:
        from db_pool import db_fetch
        rows = await db_fetch(
            f"""
            SELECT
                COALESCE(a.role, 'bilinmiyor') AS rol,
                EXTRACT(HOUR FROM a.created_at)::int AS saat,
                COUNT(*) AS adet
            FROM fermat.agent_conversations a
            WHERE a.message_role = 'user'
              AND a.created_at >= NOW() - INTERVAL '{int(days)} days'
              AND COALESCE(a.session_id,'') NOT LIKE '_test_%'
            GROUP BY rol, saat
            ORDER BY rol, saat
            """
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.debug(f"role time pattern hatasi: {e}")
        return []


def _ascii_bar(value: int, max_value: int, width: int = 20) -> str:
    """Basit ASCII bar chart."""
    if max_value <= 0:
        return ""
    filled = int(value / max_value * width)
    return "█" * filled + "░" * (width - filled)


async def build_time_report(days: int = 7) -> str:
    """Neo'ya günlük/haftalık WhatsApp raporu."""
    try:
        dist = await get_hourly_distribution(days)
        peaks = await get_peak_hours(days, top=3)
        ww = await get_weekday_vs_weekend(days)
        intents = await get_intent_time_pattern(days)

        if not dist:
            return "📊 *Time Analytics* — son {} gün veri yok".format(days)

        lines = [f"⏰ *Time-of-Day Analitik — Son {days} Gün*", "━━━━━━━━━━━━━━━━━━━━━━"]

        # Saat dağılımı (bar chart)
        max_mesaj = max(d["mesaj"] for d in dist)
        toplam = sum(d["mesaj"] for d in dist)
        lines.append(f"📊 *Toplam:* {toplam} mesaj, {max((d.get('kisi') or 0) for d in dist)} kişi (pik saat)")
        lines.append("")
        lines.append("*Saat bazlı dağılım (pik saat + her 2 saat):*")
        for d in dist:
            h = d["saat"]
            if h % 2 == 0 or d == peaks[0] if peaks else False:
                bar = _ascii_bar(d["mesaj"], max_mesaj, 15)
                peak_mark = " 🔥" if peaks and d["saat"] == peaks[0]["saat"] else ""
                lines.append(f"  `{h:02d}:00` {bar} {d['mesaj']}{peak_mark}")

        # Peak 3
        lines.append("")
        lines.append("🥇 *En yoğun 3 saat:*")
        for i, p in enumerate(peaks, 1):
            emoji = ["🥇", "🥈", "🥉"][i - 1]
            lines.append(f"  {emoji} {p['saat']:02d}:00 — {p['mesaj']} mesaj")

        # Hafta içi vs hafta sonu
        if ww:
            hi = ww.get("haftaici", 0) or 0
            hs = ww.get("haftasonu", 0) or 0
            if hi + hs:
                lines.append("")
                hi_pct = round(hi / (hi + hs) * 100)
                lines.append(f"📅 *Hafta içi:* {hi} ({hi_pct}%) · *Hafta sonu:* {hs} ({100 - hi_pct}%)")

        # Intent bazlı peak
        if intents:
            intent_peak = {}
            for row in intents:
                it = row["intent"]
                if it not in intent_peak or row["adet"] > intent_peak[it]["adet"]:
                    intent_peak[it] = row
            lines.append("")
            lines.append("🎯 *Intent bazlı pik saatler:*")
            emoji_map = {"foto": "📸", "sinav": "📝", "konu": "📚", "plan": "📅", "sohbet": "💬"}
            for intent, peak in sorted(intent_peak.items(), key=lambda x: x[1]["adet"], reverse=True):
                em = emoji_map.get(intent, "•")
                lines.append(f"  {em} *{intent}*: {peak['saat']:02d}:00 ({peak['adet']} mesaj)")

        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"_Otomatik analiz — FermatAI Time Analytics_")
        return "\n".join(lines)
    except Exception as e:
        return f"Time analytics rapor hatası: {e}"


if __name__ == "__main__":
    import asyncio, sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    async def test():
        report = await build_time_report(days=14)
        print(report)

    asyncio.run(test())
