"""
FermatAI — Profesyonel Çalışma Planı Veri Paketi
==================================================
Claude'a öğrencinin tüm akademik verilerini hazır paket olarak sunar.
Claude bu veriyle kişiselleştirilmiş, detaylı çalışma planı üretir.

Kullanım (tool olarak):
  context = await build_study_plan_context(soz_no=230)
"""

import asyncio
import time
from datetime import datetime, date, timedelta
from typing import Optional

from loguru import logger
from dotenv import load_dotenv as _lde
_lde(override=True)

from db_pool import (
    get_pool as _get_pool,
    db_fetch as _fetch,
    db_fetchrow as _fetchrow,
    db_fetchval as _fetchval,
)

# Oturum 25.8 fix — Tek kaynak (sinav_takvimi.py).
# Onceden 13 Haziran hardcoded idi; resmi OSYM 2026 takvimi 20 Haziran (Cumartesi).
# Deren'in plani 25 Nisan'da 49 gune kalibre edilmisti -> dogrusu 56 gun.
from sinav_takvimi import TYT_DATE as YKS_DATE  # 20 Haziran 2026

# 22.1n-neo Paket B: build_study_plan_context sonuc cache
# Damla Keskin gibi tekrarlanan plan dusenlemeleri icin 30dk TTL
# Her ogrenci icin son sonuç bellekte — bridge memory OK (125 ogr × ~5KB = 625KB)
_PLAN_CACHE: dict = {}
_PLAN_CACHE_TTL = 1800  # 30 dakika


def invalidate_plan_cache(soz_no: int = None):
    """Plan degisikligi sonrasi cache temizle (spesifik ogrenci veya tumu)."""
    if soz_no:
        _PLAN_CACHE.pop(int(soz_no), None)
    else:
        _PLAN_CACHE.clear()


async def build_study_plan_context(soz_no, force_refresh: bool = False) -> dict:
    """
    Öğrencinin çalışma planı için gerekli TÜM verilerini toplar.
    Claude bu paketi alıp profesyonel plan üretir.
    Oturum 18: 10 sırali query → gather ile paralel (45s+ → 5-8s)
    22.1n-neo Paket B: 30 dk TTL cache (5-8s → <100ms cache hit)
    """
    # Cache kontrolu
    try:
        key = int(soz_no)
        if not force_refresh and key in _PLAN_CACHE:
            cached = _PLAN_CACHE[key]
            if time.time() - cached["_ts"] < _PLAN_CACHE_TTL:
                logger.info(f"  [PLAN_CACHE HIT] soz_no={key} (yaş: {int(time.time()-cached['_ts'])}s)")
                result = {k: v for k, v in cached.items() if k != "_ts"}
                result["_cached"] = True
                return result
    except (ValueError, TypeError):
        pass
    # Type safety — soz_no int olmalı
    try:
        soz_no = int(soz_no)
    except (ValueError, TypeError):
        return {"error": f"Geçersiz soz_no: {soz_no}"}

    result = {}

    try:
        # ── 1. Öğrenci Profili (SIRALI — digerleri bunun sonucuna bagli) ──
        profile = await _fetchrow("""
            SELECT full_name, class_name, soz_no, program
            FROM students WHERE soz_no::int = $1
        """, soz_no)

        if not profile:
            return {"error": f"Öğrenci bulunamadı (soz_no={soz_no})"}

        name = profile['full_name'] or "?"
        cls = profile['class_name'] or "?"
        result["ogrenci"] = {
            "isim": name,
            "sinif": cls,
            "soz_no": soz_no,
        }

        # Sınıf seviyesi belirle
        is_12_mezun = any(x in str(cls) for x in ['12', 'Mez', 'MEZ'])
        is_lgs = any(x in str(cls) for x in ['7', '8', 'LGS'])

        # YKS'ye kalan gün
        today = date.today()
        days_left = (YKS_DATE - today).days
        result["yks_kalan_gun"] = max(0, days_left)

        # ── Query 2-10: PARALEL (Oturum 18 hot fix) ────────────────────
        # 8 bagimsiz query ayni anda — conversation_memory pattern'i
        student_first = (name or '').split()[0] if name else ''
        hedef, exams, zayif, guclu, devam, program, etutler, analysis = await asyncio.gather(
            _fetchval("""
                SELECT content FROM student_insights
                WHERE soz_no = $1 AND insight_type = 'akademik' AND is_active = TRUE
                ORDER BY created_at DESC LIMIT 1
            """, soz_no),
            _fetch("""
                SELECT DISTINCT ON (exam_date)
                    exam_name, exam_date, turkce, matematik, geometri,
                    fizik, kimya, biyoloji, toplam,
                    tarih, cografya, felsefe, din_kulturu
                FROM student_exams
                WHERE soz_no = $1 AND exam_name NOT LIKE '[AYT]%%' AND toplam > 5
                ORDER BY exam_date DESC NULLS LAST LIMIT 5
            """, soz_no),
            _fetch("""
                SELECT ders, konu, sinav_hata_yuzdesi, sinav_hata_sayisi, status
                FROM student_topic_tracker
                WHERE soz_no = $1 AND tamamlandi = FALSE
                  AND COALESCE(status,'') != 'metadata'
                  AND konu NOT LIKE 'Ortalama %'
                ORDER BY sinav_hata_yuzdesi DESC NULLS LAST
                LIMIT 10
            """, soz_no),
            _fetch("""
                SELECT ders, konu, sinav_hata_yuzdesi, sinav_hata_sayisi
                FROM student_topic_tracker
                WHERE soz_no = $1 AND sinav_hata_yuzdesi < 25 AND sinav_hata_sayisi > 3
                  AND COALESCE(status,'') != 'metadata'
                  AND konu NOT LIKE 'Ortalama %'
                ORDER BY sinav_hata_yuzdesi ASC
                LIMIT 5
            """, soz_no),
            _fetchval(
                "SELECT toplam_saat FROM devamsizlik_sayisi WHERE soz_no = $1", soz_no),
            _fetch("""
                SELECT gun, saat, ders, ogretmen
                FROM class_timetable
                WHERE sinif = $1
                ORDER BY CASE gun
                    WHEN 'Pazartesi' THEN 1 WHEN 'Salı' THEN 2 WHEN 'Çarşamba' THEN 3
                    WHEN 'Perşembe' THEN 4 WHEN 'Cuma' THEN 5 WHEN 'Cumartesi' THEN 6
                    WHEN 'Pazar' THEN 7 END, saat
            """, cls) if cls else _fetch("SELECT 1 WHERE FALSE"),
            _fetch("""
                SELECT tarih, ders, konu, ogretmen, yoklama
                FROM etut_history
                WHERE tarih >= CURRENT_DATE - INTERVAL '30 days'
                AND yoklama ILIKE $1
                ORDER BY tarih DESC
                LIMIT 10
            """, f"%{student_first}%") if student_first else _fetch("SELECT 1 WHERE FALSE"),
            _fetchrow("""
                SELECT oncelikli_konular, ders_netleri, ham_puan
                FROM student_exam_analysis
                WHERE soz_no::int = $1
                LIMIT 1
            """, soz_no),
            return_exceptions=True
        )
        # Exception'lari None/bos ile ikame et
        if isinstance(hedef, Exception): hedef = None
        if isinstance(exams, Exception): exams = []
        if isinstance(zayif, Exception): zayif = []
        if isinstance(guclu, Exception): guclu = []
        if isinstance(devam, Exception): devam = None
        if isinstance(program, Exception): program = []
        if isinstance(etutler, Exception): etutler = []
        if isinstance(analysis, Exception): analysis = None

        # Sonuclari result'a islet (gather'dan gelen verilerle)
        result["hedef"] = hedef or "Belirtilmemiş"

        # ── 3+4. Deneme Trendi + Ders Trendi ─────────────────────────
        deneme_trend = []
        for e in reversed(exams):  # eskiden yeniye
            d = {
                "sinav": (e['exam_name'] or '?')[:40],
                "tarih": e['exam_date'].strftime('%d.%m.%Y') if e['exam_date'] else '?',
                "toplam": round(e['toplam'], 1) if e['toplam'] else 0,
            }
            # Ders bazlı netler
            for ders, col in [("turkce", "turkce"), ("matematik", "matematik"),
                              ("geometri", "geometri"), ("fizik", "fizik"),
                              ("kimya", "kimya"), ("biyoloji", "biyoloji"),
                              ("tarih", "tarih"), ("cografya", "cografya"),
                              ("felsefe", "felsefe")]:
                val = e.get(col)
                if val is not None and val > 0:
                    d[ders] = round(val, 1)
            deneme_trend.append(d)
        result["deneme_trend"] = deneme_trend

        # ── 4. Ders Bazlı Ortalama + Trend Yönü ─────────────────────
        if len(exams) >= 2:
            son = exams[0]  # en yeni
            onceki = exams[1]  # bir önceki
            ders_trend = {}
            for ders, col, max_net in [
                ("Türkçe", "turkce", 40), ("Matematik", "matematik", 30),
                ("Geometri", "geometri", 20), ("Fizik", "fizik", 10),
                ("Kimya", "kimya", 10), ("Biyoloji", "biyoloji", 10),
            ]:
                s = son.get(col) or 0
                o = onceki.get(col) or 0
                diff = s - o
                if s > 0 or o > 0:
                    yon = "artis" if diff > 1 else ("dusus" if diff < -1 else "stabil")
                    ders_trend[ders] = {
                        "son_net": round(s, 1),
                        "onceki_net": round(o, 1),
                        "degisim": round(diff, 1),
                        "max_net": max_net,
                        "yon": yon,
                    }
            result["ders_trend"] = ders_trend

        # Genel ortalama
        if exams:
            ort = sum((e['toplam'] or 0) for e in exams) / len(exams)
            max_net = max((e['toplam'] or 0) for e in exams)
            min_net = min((e['toplam'] or 0) for e in exams if (e['toplam'] or 0) > 5)
            result["genel_ortalama"] = round(ort, 1)
            result["max_net"] = round(max_net, 1)
            result["min_net"] = round(min_net, 1)
            result["deneme_sayisi"] = len(exams)

        # ── 5. Zayıf Konular (gather'dan geldi) ────────────────────
        zayif_konular = []
        for z in zayif:
            hata_pct = z['sinav_hata_yuzdesi'] or 0
            if hata_pct < 20:
                continue  # çok düşük hata = güçlü konu, atla
            seviye = "kritik" if hata_pct >= 70 else ("zayif" if hata_pct >= 40 else "gelistirilmeli")
            zayif_konular.append({
                "ders": z['ders'],
                "konu": z['konu'],
                "hata_yuzdesi": round(hata_pct),
                "hata_sayisi": z['sinav_hata_sayisi'] or 0,
                "seviye": seviye,
            })
        result["zayif_konular"] = zayif_konular

        # ── 6. Güçlü Konular (gather'dan geldi) ──────────────────
        guclu_konular = []
        for g in guclu:
            guclu_konular.append({
                "ders": g['ders'],
                "konu": g['konu'],
                "basari_yuzdesi": round(100 - (g['sinav_hata_yuzdesi'] or 0)),
            })
        result["guclu_konular"] = guclu_konular

        # ── 7. Devamsızlık (gather'dan geldi) ────────────────────
        result["devamsizlik_saat"] = devam or 0

        # ── 8. Ders Programı (gather'dan geldi) ──────────────────
        if program:
            ders_programi = {}
            for p in program:
                gun = p['gun']
                if gun not in ders_programi:
                    ders_programi[gun] = []
                ders_programi[gun].append({
                    "saat": p['saat'],
                    "ders": p['ders'],
                    "ogretmen": (p['ogretmen'] or '')[:20],
                })
            result["ders_programi"] = ders_programi
            # Boş günler = müsait günler
            tum_gunler = {"Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"}
            dolu_gunler = set(ders_programi.keys())
            result["bos_gunler"] = list(tum_gunler - dolu_gunler)

        # ── 9. Son Etüt Geçmişi (gather'dan geldi) ──────────────
        if etutler:
            result["son_etutler"] = [
                {"tarih": str(e["tarih"]), "ders": e["ders"], "konu": e["konu"], "ogretmen": e["ogretmen"]}
                for e in etutler
            ]
        else:
            result["son_etutler_not"] = "Son 30 gunde etut katilimi bulunamadi"

        # ── 10. Öncelikli Konular (gather'dan geldi) ─────────────
        if analysis and analysis.get('oncelikli_konular'):
            import json
            try:
                pk = analysis['oncelikli_konular']
                if isinstance(pk, str):
                    pk = json.loads(pk)
                # Level 1 konuları
                oncelik_1 = []
                oncelik_2 = []
                for level_group in pk:
                    level = level_group.get('level', 0)
                    konular = level_group.get('konular', [])
                    for k in konular[:5]:
                        item = {
                            "konu": k.get('konu', '?'),
                            "soru_sayisi": k.get('soru', '0'),
                            "yanlis": k.get('yanlis', '0'),
                            "hata_yuzdesi": k.get('yuzde', '?'),
                        }
                        if level == 1:
                            oncelik_1.append(item)
                        elif level == 2:
                            oncelik_2.append(item)
                if oncelik_1:
                    result["oncelik_1_konular"] = oncelik_1
                if oncelik_2:
                    result["oncelik_2_konular"] = oncelik_2
            except Exception:
                pass

        # ── 11. Net Kazanım Potansiyeli ──────────────────────────────
        # Hangi derste en kolay net kazanılır?
        if result.get("ders_trend"):
            potansiyel = []
            for ders, info in result["ders_trend"].items():
                son = info["son_net"]
                max_n = info["max_net"]
                boşluk = max_n - son
                if boşluk > 2:
                    potansiyel.append({
                        "ders": ders,
                        "su_an": son,
                        "max_puan": max_n,
                        "kazanilabilir": round(boşluk, 1),
                        "yorum": f"{ders}'te {boşluk:.0f} net daha kazanılabilir"
                    })
            potansiyel.sort(key=lambda x: x['kazanilabilir'], reverse=True)
            result["net_potansiyeli"] = potansiyel[:5]

        # 25.51 (Neo dikey-AI): Bilimsel öğrenci modeli — FSRS tekrar takvimi +
        # BKT-kalibre ustalık. Plan artık spekülatif değil, kanıtlanmış algoritmaya
        # dayanır (hangi konu BUGÜN tekrar edilmeli + ders bazlı ustalık/trend).
        try:
            from knowledge_state import get_knowledge_state
            ks = await get_knowledge_state(soz_no)
            result["bilgi_durumu"] = {
                "ders_ustalik": ks.get("ders_ozet", {}),
                "tekrar_zamani_gelenler": ks.get("review_due", [])[:8],
                "fsrs_aktif": ks.get("fsrs_active", False),
            }
        except Exception as _kse:
            logger.debug(f"[study_plan] knowledge_state eklenemedi: {_kse}")

    except Exception as e:
        logger.error(f"Study plan context hatası: {e}")
        result["error"] = str(e)

    # 22.1n-neo Paket B: cache'e yaz (sadece basarili ise)
    try:
        if not result.get("error"):
            _PLAN_CACHE[int(soz_no)] = {**result, "_ts": time.time()}
            # Memory guard: 150+ ogrenci biriktiyse eski olanlari sil
            if len(_PLAN_CACHE) > 150:
                oldest = sorted(_PLAN_CACHE.items(), key=lambda x: x[1]["_ts"])[:30]
                for k, _ in oldest:
                    _PLAN_CACHE.pop(k, None)
    except Exception:
        pass

    return result


# ── Test ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json
    import sys
    sys.stdout.reconfigure(encoding='utf-8')

    soz = int(sys.argv[1]) if len(sys.argv) > 1 else 230

    async def test():
        ctx = await build_study_plan_context(soz)
        print(json.dumps(ctx, ensure_ascii=False, indent=2, default=str))

    asyncio.run(test())
