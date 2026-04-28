"""
exam_service — Sınav verisi + zayıf konu API'si (Oturum 25.29)
==================================================================

Sorumluluk alanı:
  - student_exams (TYT/AYT net verileri)
  - student_topic_tracker (zayıf konu, status, hata yüzdesi)
  - student_exam_analysis (Eyotek detay analiz)

Yeni sorgu yazmaz; mevcut DB pattern'larını gruplar (DRY).
context_engine + bot tools + predictive_engine bu servisi çağırır.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, date
from typing import Optional

from loguru import logger


async def get_summary(soz_no: int, last_n: int = 3) -> dict:
    """Son N TYT denemesi + ortalama + trend.

    Returns:
        {
          "son_n": [{exam_name, exam_date, toplam, ders_netleri...}, ...],
          "ortalama_net": float,
          "trend": "yukari"|"asagi"|"yatay"|None,
          "count": int,
        }
    """
    from db_pool import db_fetch
    try:
        rows = await db_fetch(
            """SELECT exam_name, exam_date, toplam,
                      turkce, matematik, fizik, kimya, biyoloji,
                      tarih, cografya, felsefe, din_kulturu, geometri,
                      exam_type
               FROM student_exams
               WHERE soz_no = $1 AND toplam IS NOT NULL AND toplam > 5
                 AND exam_name NOT LIKE '[AYT]%'
               ORDER BY exam_date DESC NULLS LAST
               LIMIT $2""",
            soz_no, last_n,
        )
        son_n = [dict(r) for r in rows]
        if not son_n:
            return {"son_n": [], "ortalama_net": 0.0, "trend": None, "count": 0}
        nets = [r.get("toplam") or 0 for r in son_n]
        avg = sum(nets) / len(nets)
        trend = None
        if len(nets) >= 2:
            diff = nets[0] - nets[1]
            trend = "yukari" if diff > 3 else "asagi" if diff < -3 else "yatay"
        return {
            "son_n": son_n,
            "ortalama_net": round(avg, 1),
            "trend": trend,
            "count": len(son_n),
        }
    except Exception as e:
        logger.debug(f"[exam_service] get_summary fail: {e}")
        return {"son_n": [], "ortalama_net": 0.0, "trend": None, "count": 0}


async def get_ayt_summary(soz_no: int, last_n: int = 3) -> dict:
    """Son N AYT denemesi (sadece [AYT] etiketli)."""
    from db_pool import db_fetch
    try:
        rows = await db_fetch(
            """SELECT exam_name, exam_date, toplam,
                      matematik, fizik, kimya, biyoloji, geometri,
                      exam_type
               FROM student_exams
               WHERE soz_no = $1 AND toplam IS NOT NULL AND toplam > 0
                 AND exam_name LIKE '[AYT]%'
               ORDER BY exam_date DESC NULLS LAST
               LIMIT $2""",
            soz_no, last_n,
        )
        son_n = [dict(r) for r in rows]
        if not son_n:
            return {"son_n": [], "ortalama_net": 0.0, "count": 0}
        avg = sum(r.get("toplam") or 0 for r in son_n) / len(son_n)
        return {
            "son_n": son_n,
            "ortalama_net": round(avg, 1),
            "count": len(son_n),
        }
    except Exception as e:
        logger.debug(f"[exam_service] get_ayt_summary fail: {e}")
        return {"son_n": [], "ortalama_net": 0.0, "count": 0}


async def get_weak_topics(
    soz_no: int,
    top_k: int = 5,
    min_error_pct: float = 40.0,
    only_active: bool = True,
) -> list[dict]:
    """En yüksek hata oranlı zayıf konular.

    Args:
        top_k: max sonuç
        min_error_pct: minimum hata yüzdesi (%40 default)
        only_active: tamamlandi=false olanlar
    """
    from db_pool import db_fetch
    try:
        sql = """SELECT ders, konu, sinav_hata_yuzdesi, status,
                        calisti_tarih, tamamlandi
                 FROM student_topic_tracker
                 WHERE soz_no = $1 AND sinav_hata_yuzdesi >= $2"""
        if only_active:
            sql += " AND tamamlandi = false"
        sql += " ORDER BY sinav_hata_yuzdesi DESC LIMIT $3"
        rows = await db_fetch(sql, soz_no, min_error_pct, top_k)
        return [dict(r) for r in rows]
    except Exception as e:
        logger.debug(f"[exam_service] get_weak_topics fail: {e}")
        return []


async def get_strong_topics(
    soz_no: int,
    top_k: int = 5,
) -> list[dict]:
    """En iyi performansli konular (hata oranı düşük)."""
    from db_pool import db_fetch
    try:
        rows = await db_fetch(
            """SELECT ders, konu, sinav_hata_yuzdesi
               FROM student_topic_tracker
               WHERE soz_no = $1 AND sinav_hata_yuzdesi <= 20
                 AND sinav_hata_yuzdesi IS NOT NULL
               ORDER BY sinav_hata_yuzdesi ASC LIMIT $2""",
            soz_no, top_k,
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.debug(f"[exam_service] get_strong_topics fail: {e}")
        return []


async def get_trend_analysis(soz_no: int, last_n: int = 5) -> dict:
    """Net değişim trendi — son N deneme arasında."""
    summary = await get_summary(soz_no, last_n=last_n)
    son = summary.get("son_n", [])
    if len(son) < 2:
        return {"trend": None, "delta": 0.0, "raw": son}

    en_yeni = son[0].get("toplam") or 0
    en_eski = son[-1].get("toplam") or 0
    delta = en_yeni - en_eski

    if delta > 5:
        trend_label = "yukseli"
    elif delta < -5:
        trend_label = "dusus"
    else:
        trend_label = "yatay"

    return {
        "trend": trend_label,
        "delta": round(delta, 1),
        "en_yeni_net": round(en_yeni, 1),
        "en_eski_net": round(en_eski, 1),
        "deneme_sayisi": len(son),
    }


async def get_exam_analysis(soz_no: int) -> Optional[dict]:
    """student_exam_analysis tablosundan birleştirilmiş analiz (varsa)."""
    from db_pool import db_fetchrow
    try:
        row = await db_fetchrow(
            """SELECT * FROM student_exam_analysis
               WHERE soz_no = $1
               ORDER BY analiz_tarihi DESC NULLS LAST
               LIMIT 1""",
            soz_no,
        )
        return dict(row) if row else None
    except Exception as e:
        logger.debug(f"[exam_service] get_exam_analysis fail: {e}")
        return None


# ─── CLI test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys, json
    from pathlib import Path
    # CLI'dan calistirildiginda parent dir'i path'e ekle
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    async def _test(soz_no: int):
        print(f"=== exam_service — soz_no={soz_no} ===\n")
        s = await get_summary(soz_no, last_n=3)
        print(f"SUMMARY: ort={s['ortalama_net']}, trend={s['trend']}, count={s['count']}")
        if s["son_n"]:
            print(f"  Son: {s['son_n'][0]['exam_name']} → {s['son_n'][0]['toplam']:.1f} net")
        print()
        ayt = await get_ayt_summary(soz_no, last_n=3)
        print(f"AYT SUMMARY: ort={ayt['ortalama_net']}, count={ayt['count']}")
        print()
        weak = await get_weak_topics(soz_no, top_k=3)
        print(f"WEAK TOPICS ({len(weak)}):")
        for w in weak:
            print(f"  - {w['ders']}/{w['konu'][:30]} (%{int(w['sinav_hata_yuzdesi'])})")
        print()
        strong = await get_strong_topics(soz_no, top_k=3)
        print(f"STRONG TOPICS ({len(strong)}):")
        for s in strong:
            print(f"  - {s['ders']}/{s['konu'][:30]} (%{int(s['sinav_hata_yuzdesi'])})")
        print()
        trend = await get_trend_analysis(soz_no, last_n=5)
        print(f"TREND: {trend}")

    soz_no = int(sys.argv[1]) if len(sys.argv) > 1 else 244
    asyncio.run(_test(soz_no))
