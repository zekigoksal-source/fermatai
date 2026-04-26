"""
Predictive Performance Model (Oturum 25.9)
============================================
Ogrencinin gelecek YKS puanini tahmin et.

Girdi:
  - Son 5 deneme (TYT + AYT)
  - Devamsizlik (toplam saat)
  - Zayif konu sayisi (ELO < 1100)
  - Sinava kalan gun
  - ELO ortalamasi (varsa)

Cikti:
  - predicted_tyt: TYT toplam net tahmin
  - predicted_ayt: AYT toplam net tahmin
  - predicted_yerlesme_puani: 0-560
  - confidence: 0-1
  - bottleneck_topics: top 3-5 kritik konu
  - target_probability: hedef bolum tutturma olasiligi (verilirse)

Algoritma:
  - Linear trend extrapolation (basit, agıklanabilir)
  - Devamsizlik penalty (her 50 saat -2 net)
  - Zayif konu penalty (her zayif konu -0.3 net)
  - Sinava yakinlasma boost/penalty (son 10 gunde -%5)
  - Klasik ML degil — explainable. Ileride sklearn fit edilebilir.

KVKK: tahmin yalnizca ogrencinin kendisine ve admin'e gosterilir.
Veliye/diger ogrenciye paylasilmaz.
"""
from __future__ import annotations
import asyncio
import json
from datetime import date, datetime
from typing import Optional

from loguru import logger

from db_pool import (
    db_execute as _exec,
    db_fetch as _fetch,
    db_fetchrow as _fetchrow,
    db_fetchval as _fetchval,
)
from sinav_takvimi import TYT_DATE, AYT_DATE, days_until_tyt, days_until_ayt


# ── HEURISTIC MODEL — v1 (transparent, explainable) ─────────────────────────

# Net → puan dönüşümü (yaklaşık 2025 ÖSYM tablosu)
# ham puan = 100 + 4 × dogru_net (TYT bazli) — gercek formula daha karmasik
# Bu basit projeksiyon, kalibrasyon icin OSYM tablolarına ek dogrulama gerekiyor
NET_TO_HAM_RATIO = 4.0    # Her 1 net ~ 4 ham puan
HAM_BASE = 100            # Baz puan

DEVAMSIZLIK_PENALTY_PER_50H = 2.0   # Her 50 saat -2 net
WEAK_TOPIC_PENALTY = 0.3            # Her zayıf konu (ELO<1100) -0.3 net
TREND_WEIGHT = 0.6                  # Son trend %60, ortalama %40
LAST_10D_PENALTY_DAY = 0.05         # Sinava 10 gunden az kaldıysa stress -%0.5/gün
MIN_CONFIDENCE_EXAM_COUNT = 3       # 3 sınavdan az ise confidence düşer


async def _get_exam_history(soz_no: int, exam_type: str = "TYT", limit: int = 5) -> list[dict]:
    """Son N denemeyi getir (en yeni en başta).

    UYARI (Oturum 25.14h): exam_type='AYT' satirlari TG (Tam Gun, TYT+AYT birlesik)
    icerigi tasiyor — toplam max 109. PURE AYT icin _get_pure_ayt_stats() kullan.
    Bu fonksiyon TYT icin guvenli, AYT trend icin uygun degil.
    """
    rows = await _fetch(
        """SELECT exam_date, exam_name, toplam, turkce, matematik, fizik, kimya, biyoloji, tarih, geometri
           FROM student_exams
           WHERE soz_no=$1 AND exam_type=$2 AND status='valid' AND toplam IS NOT NULL
           ORDER BY exam_date DESC NULLS LAST LIMIT $3""",
        soz_no, exam_type, limit,
    )
    return [dict(r) for r in (rows or [])]


async def _get_pure_ayt_stats(soz_no: int) -> dict:
    """Pure AYT net (TG karistirilmadan) — student_exam_analysis JSONB kaynak.

    Returns: {avg_net, exam_count, has_data} — trend turetilmiyor (cumulative)
    """
    row = await _fetchrow(
        """SELECT
              (REPLACE(elem->>'net', ',', '.'))::NUMERIC AS cum_net,
              (elem->>'soru')::INT AS cum_soru
           FROM student_exam_analysis sea,
                LATERAL jsonb_array_elements(sea.ders_netleri_ayt) AS elem
           WHERE sea.soz_no = $1::text
             AND sea.ders_netleri_ayt IS NOT NULL
             AND elem->>'ders' = 'Toplam'
             AND (elem->>'soru')::INT > 0
           LIMIT 1""",
        str(soz_no),
    )
    if not row or not row['cum_soru']:
        return {"avg_net": 0.0, "exam_count": 0, "has_data": False}
    exam_count = max(1, int(row['cum_soru']) // 80)
    avg_net = float(row['cum_net']) / exam_count
    return {"avg_net": round(avg_net, 2), "exam_count": exam_count, "has_data": True}


def _linear_trend(values: list[float]) -> tuple[float, float]:
    """Basit linear regression — eğim + son değer projeksiyonu.

    Returns: (slope, projected_next) — slope > 0 yükseliyor demek
    """
    if not values:
        return (0.0, 0.0)
    if len(values) == 1:
        return (0.0, values[0])

    n = len(values)
    # x = 0, 1, 2, ... (kronolojik)
    sum_x = sum(range(n))
    sum_y = sum(values)
    sum_xy = sum(i * v for i, v in enumerate(values))
    sum_x2 = sum(i * i for i in range(n))

    denom = n * sum_x2 - sum_x * sum_x
    if denom == 0:
        return (0.0, values[-1])

    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n

    # Sonraki nokta (x=n)
    projected = intercept + slope * n
    return (slope, max(0.0, projected))


async def _count_weak_topics(soz_no: int) -> int:
    """ELO < 1100 olan konu sayısı."""
    cnt = await _fetchval(
        """SELECT COUNT(*) FROM student_topic_elo
           WHERE soz_no=$1 AND rating < 1100 AND games_played >= 3""",
        soz_no,
    )
    return cnt or 0


async def _devamsizlik_saat(soz_no: int) -> float:
    """Toplam devamsızlık saati."""
    h = await _fetchval(
        "SELECT toplam_saat FROM devamsizlik_sayisi WHERE soz_no=$1",
        soz_no,
    )
    return float(h or 0)


def _net_to_yerlesme_puani(toplam_tyt_net: float, toplam_ayt_net: float = 0) -> float:
    """Net → yerleşme puanı yaklaşık dönüşüm.
    Yerleşme = TYT base + AYT bonus (alan dengelenmemiş).
    """
    tyt_puan = HAM_BASE + toplam_tyt_net * NET_TO_HAM_RATIO
    ayt_puan = HAM_BASE + toplam_ayt_net * NET_TO_HAM_RATIO if toplam_ayt_net else 0
    # Yerlesme hesabi: %40 TYT + %60 AYT (SAY/EA), kabaca ortalama
    if ayt_puan:
        return round(0.4 * tyt_puan + 0.6 * ayt_puan, 1)
    return round(tyt_puan, 1)


async def predict_student(soz_no: int) -> dict:
    """Ogrenci icin tahmin uret.

    Returns: {
      "predicted_tyt": 65.5,
      "predicted_ayt": 18.2,
      "predicted_yerlesme_puani": 387.0,
      "confidence": 0.72,
      "bottleneck_topics": [{ders, konu, rating}],
      "suggested_focus": "AYT Matematik 4 saat/hafta artır",
      "days_to_yks": 56,
      "factors": {...},   // Acıklayıcı
    }
    """
    # 1. Veri topla — paralel
    # Oturum 25.14h: AYT icin PURE AYT (TG karistirilmadan) — _get_pure_ayt_stats
    tyt_history, pure_ayt, weak_count, devamsiz_saat = await asyncio.gather(
        _get_exam_history(soz_no, "TYT", 5),
        _get_pure_ayt_stats(soz_no),
        _count_weak_topics(soz_no),
        _devamsizlik_saat(soz_no),
        return_exceptions=True,
    )

    if isinstance(tyt_history, Exception): tyt_history = []
    if isinstance(pure_ayt, Exception): pure_ayt = {"avg_net": 0.0, "exam_count": 0, "has_data": False}
    if isinstance(weak_count, Exception): weak_count = 0
    if isinstance(devamsiz_saat, Exception): devamsiz_saat = 0

    # Yetersiz veri — confidence düşür
    tyt_count = len(tyt_history)
    ayt_count = pure_ayt.get("exam_count", 0)

    if tyt_count == 0 and ayt_count == 0:
        return {
            "soz_no": soz_no,
            "error": "no_exam_data",
            "message": "Henuz yeterli sinav verisi yok, tahmin uretilemiyor.",
        }

    # 2. TYT tahmin (en yeni en başta — chronological reverse)
    tyt_nets = [float(e['toplam']) for e in reversed(tyt_history) if e.get('toplam')]
    tyt_slope, tyt_projected = _linear_trend(tyt_nets) if tyt_nets else (0, 0)

    # 3. AYT tahmin (PURE AYT — cumulative average, trend yok)
    ayt_avg = pure_ayt.get("avg_net", 0.0)
    ayt_nets = [ayt_avg] * ayt_count if ayt_count > 0 else []
    ayt_slope = 0.0  # Cumulative kaynaktan trend turetilemiyor
    ayt_projected = ayt_avg

    # 4. Penalty / boost uygulamalari
    devam_penalty = (devamsiz_saat / 50.0) * DEVAMSIZLIK_PENALTY_PER_50H
    weak_penalty = weak_count * WEAK_TOPIC_PENALTY

    days_left = max(0, days_until_tyt())

    # Stress penalty (son 10 günde)
    stress_penalty = 0
    if days_left < 10:
        stress_penalty = (10 - days_left) * LAST_10D_PENALTY_DAY

    final_tyt = max(0, tyt_projected - devam_penalty - weak_penalty - stress_penalty)
    final_ayt = max(0, ayt_projected - (devam_penalty * 0.5) - (weak_penalty * 0.5))

    # 5. Yerlesme puani
    yerlesme = _net_to_yerlesme_puani(final_tyt, final_ayt)

    # 6. Confidence
    confidence = 0.5
    if tyt_count >= MIN_CONFIDENCE_EXAM_COUNT:
        confidence += 0.2
    if ayt_count >= MIN_CONFIDENCE_EXAM_COUNT:
        confidence += 0.15
    if weak_count > 0:  # ELO data var
        confidence += 0.1
    # Trend istikrarsizliği — variance yüksekse confidence düşer
    if tyt_count >= 3:
        nets_recent = tyt_nets[-3:]
        if nets_recent:
            mean = sum(nets_recent) / len(nets_recent)
            var = sum((v - mean) ** 2 for v in nets_recent) / len(nets_recent)
            if var > 50:  # Yüksek volatilite
                confidence -= 0.15
    confidence = max(0.2, min(1.0, confidence))

    # 7. Bottleneck topics
    bottleneck = await _fetch(
        """SELECT ders, konu, rating FROM student_topic_elo
           WHERE soz_no=$1 AND rating < 1100 AND games_played >= 3
           ORDER BY rating ASC LIMIT 5""",
        soz_no,
    )
    bottleneck_list = [dict(r) for r in (bottleneck or [])]

    # 8. Suggested focus
    focus_msg = ""
    if final_ayt < 5 and ayt_count >= 2:
        focus_msg = "AYT'ye odaklan — net potansiyeli yuksek (sifira yakin sektor cok)"
    elif final_tyt < 60 and weak_count > 5:
        focus_msg = "TYT zayif konulari sik (ELO<1100 olan 5+ konu var)"
    elif tyt_slope < -1:
        focus_msg = "Son denemelerde dusus var, tempo dusurme — bakim haftasi"
    elif tyt_slope > 2:
        focus_msg = "Cok iyi gidiyor, tempoyu koru, yeni konu acma"
    else:
        focus_msg = "Stabil, mevcut programi surdur"

    result = {
        "soz_no": soz_no,
        "predicted_tyt": round(final_tyt, 1),
        "predicted_ayt": round(final_ayt, 1),
        "predicted_yerlesme_puani": yerlesme,
        "confidence": round(confidence, 2),
        "bottleneck_topics": bottleneck_list,
        "suggested_focus": focus_msg,
        "days_to_yks": days_left,
        "factors": {
            "tyt_son_5_ortalama": round(sum(tyt_nets) / len(tyt_nets), 1) if tyt_nets else None,
            "tyt_trend_slope": round(tyt_slope, 2),
            "ayt_son_5_ortalama": round(sum(ayt_nets) / len(ayt_nets), 1) if ayt_nets else None,
            "ayt_trend_slope": round(ayt_slope, 2),
            "devamsizlik_saat": round(devamsiz_saat, 1),
            "devam_penalty": round(devam_penalty, 1),
            "weak_topic_count": weak_count,
            "weak_penalty": round(weak_penalty, 1),
            "stress_penalty": round(stress_penalty, 1),
            "tyt_sample_size": tyt_count,
            "ayt_sample_size": ayt_count,
        },
    }

    # 9. DB'ye snapshot kaydet
    try:
        await _exec(
            """INSERT INTO student_predictions
               (soz_no, predicted_tyt, predicted_ayt, predicted_yerlesme_puani,
                confidence, bottleneck_topics, suggested_focus, days_to_yks,
                model_version)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'v1')""",
            soz_no, result["predicted_tyt"], result["predicted_ayt"],
            result["predicted_yerlesme_puani"], result["confidence"],
            json.dumps(bottleneck_list), focus_msg, days_left,
        )
    except Exception as e:
        logger.warning(f"prediction snapshot DB save fail: {e}")

    return result


async def predict_target_probability(
    soz_no: int,
    target_taban_puan: float,
    target_siralama: Optional[int] = None,
) -> dict:
    """Hedef bolum tutturma olasiligi.

    target_taban_puan: hedef bolumun gecen yil taban puani
    target_siralama: hedef siralama (opsiyonel, daha hassas hesap)

    Returns: {"probability": 0.42, "diff": 12.5, "narrative": "..."}
    """
    pred = await predict_student(soz_no)
    if pred.get("error"):
        return pred

    current = pred["predicted_yerlesme_puani"]
    diff = current - target_taban_puan
    confidence = pred["confidence"]

    # Olasilik hesabi: diff > +20 → %85, diff -20 → %15, lineer arada
    # confidence ile çarpılır
    if diff >= 30:
        prob = 0.95
    elif diff >= 20:
        prob = 0.85
    elif diff >= 10:
        prob = 0.70
    elif diff >= 5:
        prob = 0.55
    elif diff >= -5:
        prob = 0.40
    elif diff >= -15:
        prob = 0.25
    elif diff >= -25:
        prob = 0.12
    else:
        prob = 0.05

    # Confidence düzeltmesi
    final_prob = prob * confidence + 0.5 * (1 - confidence)  # Düşük confidence → 50%'ye yakınlaş

    if final_prob >= 0.7:
        narrative = f"Yuksek olasilik ({final_prob*100:.0f}%) — tempoyu koru, hedef ulaşılabilir."
    elif final_prob >= 0.4:
        narrative = f"Orta olasilik ({final_prob*100:.0f}%) — odakli calisirsan tutturursun."
    else:
        narrative = f"Dusuk olasilik ({final_prob*100:.0f}%) — alternatif hedefler de degerlendir veya yogun tempoya gec."

    return {
        "probability": round(final_prob, 2),
        "current_predicted": current,
        "target_taban_puan": target_taban_puan,
        "diff": round(diff, 1),
        "confidence": confidence,
        "narrative": narrative,
        "prediction": pred,
    }


async def get_latest_prediction(soz_no: int) -> Optional[dict]:
    """En son DB'ye yazılan tahmin snapshotu."""
    row = await _fetchrow(
        """SELECT predicted_tyt, predicted_ayt, predicted_yerlesme_puani,
                  confidence, bottleneck_topics, suggested_focus, days_to_yks,
                  prediction_date, created_at
           FROM student_predictions
           WHERE soz_no=$1
           ORDER BY created_at DESC LIMIT 1""",
        soz_no,
    )
    return dict(row) if row else None


async def predict_all_students(limit: int = 200) -> dict:
    """Tum aktif ogrenciler icin batch tahmin (cron icin)."""
    rows = await _fetch(
        """SELECT soz_no FROM students WHERE status='active'
           AND class_name NOT ILIKE '%mezun%'
           ORDER BY soz_no LIMIT $1""",
        limit,
    )
    success = 0
    fail = 0
    for r in (rows or []):
        try:
            res = await predict_student(r['soz_no'])
            if res.get('error'):
                fail += 1
            else:
                success += 1
        except Exception as e:
            logger.warning(f"predict_all_students fail soz_no={r['soz_no']}: {e}")
            fail += 1
    return {"success": success, "failed": fail, "total": len(rows or [])}


if __name__ == "__main__":
    # Test linear trend logic
    nets = [60, 62, 65, 63, 67]
    slope, projected = _linear_trend(nets)
    print(f"Trend test: nets={nets}")
    print(f"  slope={slope:.2f} (expected positive)")
    print(f"  projected next: {projected:.1f}")

    # Yerlesme puani conversion
    yp = _net_to_yerlesme_puani(60, 20)
    print(f"Yerlesme puani test (TYT=60, AYT=20): {yp} (expected ~340-360)")
