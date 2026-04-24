"""
Jarvis Yönetim Modülü (Neo-only, 23 Nisan)
============================================
Senin "Jarvis" vizyonunun admin tarafı — kurum kontrolü, KPI, öneri.
Sadece Neo (905051256802) erişir.

Self-awareness v2: sistemin kendi durumunu analiz + öneri.
"""
from __future__ import annotations
from loguru import logger


async def get_kurum_snapshot() -> dict:
    """Anlık kurum fotoğrafı — Neo'nun gününü bununla başlatır."""
    try:
        from db_pool import db_fetchval, db_fetch
        ogr_toplam = await db_fetchval("SELECT COUNT(*) FROM fermat.students WHERE status='active'") or 0
        aktif_bugun = await db_fetchval(
            "SELECT COUNT(DISTINCT phone) FROM fermat.agent_conversations "
            "WHERE created_at > NOW() - INTERVAL '24 hours' AND message_role='user' "
            "AND COALESCE(session_id,'') NOT LIKE '_test_%'"
        ) or 0
        aktif_hafta = await db_fetchval(
            "SELECT COUNT(DISTINCT phone) FROM fermat.agent_conversations "
            "WHERE created_at > NOW() - INTERVAL '7 days' AND message_role='user' "
            "AND COALESCE(session_id,'') NOT LIKE '_test_%'"
        ) or 0
        deneme_hafta = await db_fetchval(
            "SELECT COUNT(*) FROM fermat.student_exams "
            "WHERE exam_date > CURRENT_DATE - INTERVAL '7 days' AND status='valid'"
        ) or 0
        risk_ogrenci = await db_fetch(
            """
            SELECT s.full_name, s.class_name, COALESCE(d.toplam_saat, 0) AS devamsiz
            FROM fermat.students s
            LEFT JOIN fermat.devamsizlik_sayisi d ON d.soz_no = s.soz_no::int
            WHERE s.status='active' AND COALESCE(d.toplam_saat, 0) > 150
            ORDER BY d.toplam_saat DESC LIMIT 5
            """
        )
        return {
            "ogr_toplam": ogr_toplam,
            "aktif_bugun": aktif_bugun,
            "aktif_hafta": aktif_hafta,
            "engagement_ratio": round(aktif_hafta / max(ogr_toplam, 1) * 100, 1),
            "deneme_hafta": deneme_hafta,
            "risk_ogrenci": [dict(r) for r in risk_ogrenci],
        }
    except Exception as e:
        logger.debug(f"kurum_snapshot: {e}")
        return {}


async def system_self_report() -> str:
    """Self-awareness v2 — sistem kendi durumunu raporla (toplantı modu)."""
    try:
        from db_pool import db_fetchval
        lines = ["🤖 *Sistem Self-Report*", "━━━━━━━━━━━━━━━━━━━━━━"]

        # 1. Trafik
        sn = await get_kurum_snapshot()
        lines.append(f"👥 Öğrenci: {sn.get('ogr_toplam',0)} aktif")
        lines.append(f"📊 Bugün: {sn.get('aktif_bugun',0)} kişi mesaj, hafta {sn.get('aktif_hafta',0)} ({sn.get('engagement_ratio',0)}%)")

        # 2. Modül sağlığı
        tables = ["pedagoji_literatur", "anekdotlar", "pedagojik_sablonlar",
                   "rag_content", "student_topic_tracker", "student_exams"]
        lines.append("")
        lines.append("📦 *Enrichment data:*")
        for t in tables:
            try:
                c = await db_fetchval(f"SELECT COUNT(*) FROM fermat.{t}") or 0
                lines.append(f"  • {t}: {c}")
            except Exception:
                pass

        # 3. Modül engelleri/risk
        lines.append("")
        lines.append("⚙ *Modül durumları:*")
        try:
            import os
            enforce = os.getenv("TOKEN_BUDGET_ENFORCE", "false").lower() == "true"
            telafi = os.getenv("TELAFI_ACTIVE", "false").lower() == "true"
            lines.append(f"  • Classroom Enforce: {'🟢 aktif' if enforce else '🟡 ÖLÇÜM'}")
            lines.append(f"  • Telafi dış mesaj: {'🟢 aktif' if telafi else '🔴 kapalı (Neo onayı)'}")
        except Exception:
            pass

        # 4. Risk öğrenci
        if sn.get("risk_ogrenci"):
            lines.append("")
            lines.append("⚠ *Devamsızlık risk (150+ saat):*")
            for r in sn["risk_ogrenci"][:3]:
                lines.append(f"  • {r['full_name']} ({r['class_name']}) — {r['devamsiz']} saat")

        # 5. Önemli aksiyon önerileri
        lines.append("")
        lines.append("💡 *Öneri:*")
        eng = sn.get("engagement_ratio", 0)
        if eng < 30:
            lines.append(f"  🔴 Engagement %{eng} düşük — retention önlemleri aktif et (streak, proaktif push)")
        elif eng < 60:
            lines.append(f"  🟡 Engagement %{eng} orta — gamification canlıya al")
        else:
            lines.append(f"  🟢 Engagement %{eng} — seviye korundu")

        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        return "\n".join(lines)
    except Exception as e:
        return f"Self-report hatası: {e}"


async def proactive_insights_for_neo() -> list[str]:
    """Neo'ya sabah push olacak proaktif gözlemler."""
    insights = []
    try:
        from db_pool import db_fetch, db_fetchval
        # Uzaklaşan aktif öğrenciler (son 14 günde aktif, son 5 gün yok)
        uzak = await db_fetch(
            """
            WITH last_active AS (
              SELECT phone, MAX(created_at) AS son_mesaj
              FROM fermat.agent_conversations
              WHERE message_role='user' AND role='ogrenci'
                AND COALESCE(session_id,'') NOT LIKE '_test_%'
              GROUP BY phone
            )
            SELECT s.full_name, s.class_name, la.son_mesaj::date AS son_tarih
            FROM last_active la
            JOIN fermat.students s ON REPLACE(s.phone,'+','') = la.phone
            WHERE la.son_mesaj < NOW() - INTERVAL '5 days'
              AND la.son_mesaj > NOW() - INTERVAL '14 days'
              AND s.status = 'active'
            ORDER BY la.son_mesaj DESC LIMIT 5
            """
        )
        if uzak:
            ad_list = ", ".join((r["full_name"] or "?").split()[0] for r in uzak[:3])
            insights.append(f"🔴 {len(uzak)} öğrenci 5+ gün sessiz: {ad_list}...")

        # Net düşüş trend (son 2 denemede -5+)
        dusus = await db_fetchval(
            """
            WITH son_iki AS (
              SELECT soz_no, toplam,
                     ROW_NUMBER() OVER (PARTITION BY soz_no ORDER BY exam_date DESC) AS rn
              FROM fermat.student_exams WHERE status='valid'
            )
            SELECT COUNT(*)
            FROM (
              SELECT s1.soz_no, s1.toplam - s2.toplam AS fark
              FROM son_iki s1 JOIN son_iki s2 ON s1.soz_no = s2.soz_no
              WHERE s1.rn=1 AND s2.rn=2 AND s1.toplam - s2.toplam <= -5
            ) x
            """
        ) or 0
        if dusus > 0:
            insights.append(f"📉 {dusus} öğrenci son denemede -5+ net düşüş")

        # Yeni onboard (dün kayıt olup yazan)
        yeni = await db_fetchval(
            """
            SELECT COUNT(DISTINCT au.phone) FROM fermat.acl_users au
            WHERE au.welcomed_at > NOW() - INTERVAL '24 hours'
            """
        ) or 0
        if yeni > 0:
            insights.append(f"🎉 {yeni} kişi son 24h onboard oldu")

        # Crisis sinyal
        crisis = await db_fetchval(
            """
            SELECT COUNT(DISTINCT soz_no) FROM fermat.student_insights
            WHERE insight_type='crisis' AND created_at > NOW() - INTERVAL '3 days'
            """
        ) or 0
        if crisis > 0:
            insights.append(f"🚨 {crisis} öğrenci crisis sinyali verdi (son 3g)")

        return insights
    except Exception as e:
        logger.debug(f"proactive_insights: {e}")
        return []


async def build_neo_morning_brief() -> str:
    """Neo'nun sabah WhatsApp briefi."""
    insights = await proactive_insights_for_neo()
    if not insights:
        return "🌅 *Günaydın Zeki Bey* — sistemde özel bir sinyal yok, her şey normal akışında. ☕"
    lines = ["🌅 *Günaydın Zeki Bey — Jarvis Brief*", "━━━━━━━━━━━━━━━━━━━━━━", ""]
    lines.extend(insights)
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("_'sistem' yazarak detaylı self-report alabilirsin._")
    return "\n".join(lines)
