"""
F5 — Predicted Grade Widget (Oturum 25.28)
==============================================

Öğrencinin Çalışmam panel daily brief'ine "tahmin edilen YKS puan" widget'ı.

Mevcut altyapı: predictive_model.py (zaten var)
Bu modülün ek katkısı:
  - Günlük cache (predicted_grade_cache tablosu, 24h refresh)
  - JSON endpoint: GET /student/daily/predicted-grade?soz_no=X
  - Daily brief'e otomatik enjekte
  - Trend göstergesi (up/flat/down) + hedefe gap

WP YASAK — sadece Çalışmam panel + admin görür.
"""
from __future__ import annotations
import asyncio
import json
from datetime import datetime, timedelta
from typing import Optional
from loguru import logger


async def get_cached_prediction(soz_no: int) -> Optional[dict]:
    from db_pool import db_fetchrow
    row = await db_fetchrow(
        """SELECT * FROM predicted_grade_cache
           WHERE soz_no = $1 AND (expires_at IS NULL OR expires_at > NOW())""",
        soz_no
    )
    return dict(row) if row else None


async def compute_prediction(soz_no: int, force: bool = False) -> Optional[dict]:
    """Predictive model çalıştır + DB cache yenile."""
    from db_pool import db_fetchrow, db_execute, db_fetch

    # Force değilse cache kontrol
    if not force:
        cached = await get_cached_prediction(soz_no)
        if cached:
            return cached

    # 1. Son 6 TYT denemesi
    rows = await db_fetch(
        """SELECT exam_date, toplam, turkce, matematik, fizik, kimya, biyoloji,
                  tarih, cografya
           FROM student_exams
           WHERE soz_no::int = $1 AND exam_type = 'TYT'
             AND status NOT ILIKE '%katilmadi%'
           ORDER BY exam_date DESC LIMIT 6""",
        soz_no
    )
    if not rows or len(rows) < 2:
        return None

    # 2. Son 3 ortalama + önceki 3 (trend)
    son_3 = rows[:3]
    onceki_3 = rows[3:6] if len(rows) >= 6 else []

    son_3_avg = sum(float(r["toplam"] or 0) for r in son_3) / len(son_3)
    if onceki_3:
        onceki_3_avg = sum(float(r["toplam"] or 0) for r in onceki_3) / len(onceki_3)
        trend_magnitude = round(son_3_avg - onceki_3_avg, 2)
    else:
        trend_magnitude = 0.0

    if trend_magnitude > 2.0:
        trend_direction = "up"
    elif trend_magnitude < -2.0:
        trend_direction = "down"
    else:
        trend_direction = "flat"

    # 3. YKS puan tahmin (basit linear approximation, Fermat 2025-26 calibrasyonu)
    # TYT toplam net → puan: ~yaklaşık (net × 3.5) + 100 (ham puan, 100-220 arası)
    # YKS yerleşim puanı için OBP+OYP karması gerekir; predictive_model.py daha doğru
    try:
        from predictive_model import predict_yks_score
        pred = predict_yks_score(soz_no, sinav_turu="TYT")
        if pred and isinstance(pred, dict):
            predicted_score = pred.get("predicted") or pred.get("score") or (son_3_avg * 3.5 + 100)
            confidence = pred.get("confidence", 0.7)
            bottleneck = pred.get("bottleneck_topics", [])
        else:
            raise RuntimeError("predictive_model returned None")
    except Exception:
        # Fallback hesap (linear)
        predicted_score = round(son_3_avg * 3.5 + 100, 1)
        confidence = 0.6
        # Bottleneck — student_topic_tracker'dan top 3 zayıf
        try:
            tt = await db_fetch(
                """SELECT ders, konu, hata_orani
                   FROM student_topic_tracker
                   WHERE soz_no = $1 AND hata_orani >= 50
                   ORDER BY hata_orani DESC LIMIT 3""",
                soz_no
            )
            bottleneck = [{"ders": t["ders"], "konu": t["konu"],
                           "neta_etki": float(t["hata_orani"]) / 10}
                          for t in tt]
        except Exception:
            bottleneck = []

    # 4. Hedef puan (acl_users veya students.hedef_puan kolonundan)
    target_score = None
    try:
        target_score = await db_fetchrow(
            "SELECT hedef_puan FROM students WHERE soz_no::int = $1", soz_no
        )
        target_score = float(target_score["hedef_puan"]) if target_score and target_score.get("hedef_puan") else None
    except Exception:
        target_score = None

    if target_score is None:
        target_score = max(predicted_score + 30, 350)  # default hedef tahminden +30

    gap_to_target = round(target_score - predicted_score, 1)
    # Aylık net artış gerek (kalan ay × her ay X net = gap puana ulaş)
    months_to_yks = max(1, (datetime(2026, 6, 13) - datetime.now()).days / 30)
    monthly_uplift_needed = round((gap_to_target / 3.5) / months_to_yks, 2) if gap_to_target > 0 else 0

    # 5. Student name
    name_row = await db_fetchrow(
        "SELECT full_name FROM students WHERE soz_no::int = $1", soz_no
    )
    student_name = name_row["full_name"] if name_row else ""

    # 6. Cache yaz
    await db_execute(
        """INSERT INTO predicted_grade_cache
           (soz_no, student_name, sinav_turu, last_3_avg_net, predicted_score,
            confidence, trend_direction, trend_magnitude,
            target_score, gap_to_target, bottleneck_topics,
            monthly_uplift_needed, last_computed, expires_at)
           VALUES ($1,$2,'TYT',$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11,NOW(),NOW() + INTERVAL '24 hours')
           ON CONFLICT (soz_no) DO UPDATE SET
             student_name=EXCLUDED.student_name,
             last_3_avg_net=EXCLUDED.last_3_avg_net,
             predicted_score=EXCLUDED.predicted_score,
             confidence=EXCLUDED.confidence,
             trend_direction=EXCLUDED.trend_direction,
             trend_magnitude=EXCLUDED.trend_magnitude,
             target_score=EXCLUDED.target_score,
             gap_to_target=EXCLUDED.gap_to_target,
             bottleneck_topics=EXCLUDED.bottleneck_topics,
             monthly_uplift_needed=EXCLUDED.monthly_uplift_needed,
             last_computed=NOW(),
             expires_at=NOW() + INTERVAL '24 hours'""",
        soz_no, student_name, round(son_3_avg, 2), predicted_score,
        confidence, trend_direction, trend_magnitude,
        target_score, gap_to_target,
        json.dumps(bottleneck, default=str),
        monthly_uplift_needed
    )

    return await get_cached_prediction(soz_no)


async def get_widget_data(soz_no: int) -> dict:
    """Çalışmam panel widget formatında ver."""
    pred = await compute_prediction(soz_no)
    if not pred:
        return {"available": False, "reason": "Henüz yeterli sınav verisi yok (≥2 deneme gerek)"}

    trend_emoji = {"up": "📈", "flat": "➡️", "down": "📉"}.get(
        pred.get("trend_direction", "flat"), "➡️"
    )

    # Mesaj formatları
    last3 = float(pred.get("last_3_avg_net") or 0)
    predicted = float(pred.get("predicted_score") or 0)
    target = float(pred.get("target_score") or 0)
    gap = float(pred.get("gap_to_target") or 0)
    monthly = float(pred.get("monthly_uplift_needed") or 0)

    return {
        "available": True,
        "student_name": pred.get("student_name"),
        "last_3_avg_net": last3,
        "predicted_score": predicted,
        "confidence": float(pred.get("confidence") or 0),
        "target_score": target,
        "gap_to_target": gap,
        "trend_direction": pred.get("trend_direction"),
        "trend_emoji": trend_emoji,
        "trend_magnitude": float(pred.get("trend_magnitude") or 0),
        "monthly_uplift_needed": monthly,
        "bottleneck_topics": pred.get("bottleneck_topics") or [],
        "computed_at": pred.get("last_computed"),
        "headline": (
            f"{trend_emoji} YKS tahminim: ~{predicted:.0f} puan "
            f"(hedef {target:.0f}, fark {gap:.1f})"
        ),
        "subline": (
            f"Bu tempoda gidersen hedef için ayda +{monthly:.1f} net gerek"
            if gap > 0 else "Hedefi aşıyorsun, momentumu koru 🎯"
        ),
    }


async def refresh_all_predictions(limit: int = 200) -> dict:
    """Tüm aktif öğrenciler için tahmin cache yenile (gece cron)."""
    from db_pool import db_fetch
    students = await db_fetch(
        "SELECT soz_no::int AS soz_no FROM students "
        "WHERE status='active' ORDER BY soz_no LIMIT $1", limit
    )
    refreshed = 0
    skipped = 0
    for s in students:
        try:
            r = await compute_prediction(s["soz_no"], force=True)
            if r:
                refreshed += 1
            else:
                skipped += 1
        except Exception as e:
            logger.debug(f"[PRED_GRADE] {s['soz_no']} fail: {e}")
            skipped += 1
        await asyncio.sleep(0.05)
    logger.info(f"📊 [PRED_GRADE] {refreshed}/{len(students)} ogrenci tahmin yenilendi")
    return {"refreshed": refreshed, "skipped": skipped, "total": len(students)}


# ─── CLI ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    async def _main():
        if len(sys.argv) > 1 and sys.argv[1] == "all":
            r = await refresh_all_predictions()
            print(json.dumps(r, indent=2))
        elif len(sys.argv) > 2 and sys.argv[1] == "student":
            soz = int(sys.argv[2])
            r = await get_widget_data(soz)
            print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
        else:
            print("Kullanim: python predicted_grade.py [all|student <soz_no>]")
    asyncio.run(_main())
