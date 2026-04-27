"""
F1 — Live Teacher Briefing (Oturum 25.28)
==============================================

Öğretmen sınıfa girmeden ÖNCE 15-30dk önceden proaktif brief üretir.

Akış:
  1. Cron her saat başı + 30dk → bir sonraki 30-90dk içindeki dersleri tara
     (teacher_timetable + ders programı)
  2. Her ders için: sınıfın son durumu, riskli öğrenciler, zayıf konular,
     son denemelerden takdir edilebilecek kazanımlar
  3. Brief metni Cerebras gpt-oss-120b ile pedagojik formatta üretilir
  4. teacher_briefing_queue'ya yazılır (status='queued')
  5. WP gönderim: TEACHER_BRIEFING_WP_ACTIVE=true ise gönderir,
     False ise sadece queue'da kalır (admin görür)

ŞU AN: WP_ACTIVE=False — yeni sezon (1 Eylül) Neo aktive edecek.
Admin bu queue'yu /admin/teacher-briefings endpoint'inden görebilir.
"""
from __future__ import annotations
import asyncio
import json
import os
from datetime import datetime, timedelta, time
from typing import Optional
from loguru import logger


async def is_feature_active() -> bool:
    """sistem_ayar.TEACHER_BRIEFING_WP_ACTIVE oku."""
    try:
        from db_pool import db_fetchval
        v = await db_fetchval(
            "SELECT value FROM sistem_ayar WHERE key='TEACHER_BRIEFING_WP_ACTIVE'"
        )
        return (v or "").lower() == "true"
    except Exception:
        return False


async def is_dry_run() -> bool:
    try:
        from db_pool import db_fetchval
        v = await db_fetchval(
            "SELECT value FROM sistem_ayar WHERE key='NEW_FEATURES_DRY_RUN'"
        )
        return (v or "true").lower() == "true"
    except Exception:
        return True


async def get_upcoming_lessons(window_start_min: int = 15,
                                window_end_min: int = 90) -> list[dict]:
    """Önümüzdeki 15-90dk içinde başlayacak öğretmen derslerini getir.

    teacher_timetable yapısı: gun (Mon/Tue/...), saat_basla, saat_bit,
    dersad, sinif_adi, ogretmen_adi, sube
    """
    from db_pool import db_fetch
    now = datetime.now()
    window_start = now + timedelta(minutes=window_start_min)
    window_end = now + timedelta(minutes=window_end_min)

    # Türkçe gün adı
    gun_map = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    today_gun = gun_map[now.weekday()]

    # teacher_timetable kolonlarini kontrol et
    try:
        rows = await db_fetch(
            """SELECT teacher_name, lesson, class_name,
                      day, start_time, end_time
               FROM teacher_timetable
               WHERE day = $1
                 AND start_time::time BETWEEN $2::time AND $3::time""",
            today_gun, window_start.time(), window_end.time()
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.debug(f"[BRIEFING] teacher_timetable sema farkli: {e}, alternatif sorgu")
        # Sema farkliysa: basit bir liste don
        try:
            rows = await db_fetch(
                "SELECT * FROM teacher_timetable LIMIT 1"
            )
            if rows:
                cols = list(rows[0].keys())
                logger.info(f"[BRIEFING] teacher_timetable kolonlari: {cols}")
        except Exception:
            pass
        return []


async def gather_brief_data(teacher_name: str, class_name: str,
                             lesson: str) -> dict:
    """Sınıf için brief verisi topla — risk, focus, wins, stats."""
    from db_pool import db_fetch, db_fetchrow

    data = {
        "class_name": class_name,
        "teacher": teacher_name,
        "lesson": lesson,
        "risk_students": [],
        "focus_topics": [],
        "wins": [],
        "stats": {},
    }

    # 1. Sınıf öğrencilerinin son sınav trendi
    try:
        risk = await db_fetch(
            """WITH son_3 AS (
                 SELECT s.full_name, s.soz_no::int AS soz_no,
                        ROW_NUMBER() OVER (PARTITION BY s.soz_no ORDER BY se.exam_date DESC) AS rn,
                        se.toplam, se.fizik, se.matematik
                 FROM students s
                 JOIN student_exams se ON se.soz_no::text = s.soz_no
                 WHERE s.class_name ~* $1 AND se.exam_type = 'TYT'
               )
               SELECT full_name, soz_no, AVG(toplam) AS son3_ort, MIN(toplam) AS dip
               FROM son_3 WHERE rn <= 3
               GROUP BY full_name, soz_no
               HAVING AVG(toplam) < 35  -- riskli eşik
               ORDER BY AVG(toplam) ASC LIMIT 5""",
            class_name.replace(" A", "").replace(" B", "").strip()
        )
        data["risk_students"] = [dict(r) for r in risk]
    except Exception as e:
        logger.debug(f"[BRIEFING] risk sorgu fail: {e}")

    # 2. Sınıfın zayıf konuları (top 3)
    try:
        topics = await db_fetch(
            """SELECT konu, COUNT(*) AS yapamayan_ogr,
                      AVG(hata_orani) AS ort_hata
               FROM student_topic_tracker stt
               JOIN students s ON stt.soz_no = s.soz_no::int
               WHERE s.class_name ~* $1
                 AND stt.hata_orani >= 50
                 AND stt.ders ILIKE '%' || $2 || '%'
               GROUP BY konu
               ORDER BY yapamayan_ogr DESC, ort_hata DESC
               LIMIT 3""",
            class_name.replace(" A", "").replace(" B", "").strip(),
            lesson
        )
        data["focus_topics"] = [dict(r) for r in topics]
    except Exception as e:
        logger.debug(f"[BRIEFING] topics sorgu fail: {e}")

    # 3. Sınıf wins (son sınavda ders bazlı top 1)
    try:
        wins = await db_fetch(
            """WITH son_sinav AS (
                 SELECT s.full_name, s.soz_no::int AS soz_no, se.fizik,
                        se.matematik, se.exam_date,
                        ROW_NUMBER() OVER (PARTITION BY s.soz_no ORDER BY se.exam_date DESC) AS rn
                 FROM students s
                 JOIN student_exams se ON se.soz_no::text = s.soz_no
                 WHERE s.class_name ~* $1 AND se.exam_type = 'TYT'
               )
               SELECT full_name, fizik, matematik FROM son_sinav
               WHERE rn = 1 AND fizik IS NOT NULL
               ORDER BY fizik DESC LIMIT 2""",
            class_name.replace(" A", "").replace(" B", "").strip()
        )
        data["wins"] = [dict(r) for r in wins]
    except Exception as e:
        logger.debug(f"[BRIEFING] wins sorgu fail: {e}")

    # 4. Genel istatistikler
    try:
        stat = await db_fetchrow(
            """SELECT COUNT(DISTINCT soz_no::int) AS ogrenci_sayisi
               FROM students WHERE class_name ~* $1 AND status='active'""",
            class_name.replace(" A", "").replace(" B", "").strip()
        )
        if stat:
            data["stats"] = dict(stat)
    except Exception:
        pass

    return data


async def generate_brief_text(data: dict) -> str:
    """Cerebras 70B ile pedagojik brief metni üret (kısa, motive, eylem-odaklı)."""
    risk = data.get("risk_students", [])
    topics = data.get("focus_topics", [])
    wins = data.get("wins", [])
    stats = data.get("stats", {})

    # Cerebras yoksa fallback şablon
    try:
        from cerebras_handler import CerebrasClient
        if not os.getenv("CEREBRAS_API_KEY"):
            raise RuntimeError("no api key")

        client = CerebrasClient()
        prompt = f"""Aşağıdaki veriden bir öğretmene 30 saniye içinde okunabilir,
kısa, eylem odaklı brief mesajı yaz. Maks 280 karakter.
Format: emoji + bold + 3-4 madde. Türkçe.

Sınıf: {data['class_name']}
Ders: {data['lesson']}
Öğretmen: {data['teacher']}

Risk öğrenciler (son 3 deneme ort < 35 net):
{json.dumps([{'ad': r['full_name'], 'ort': float(r['son3_ort'] or 0)} for r in risk[:3]], ensure_ascii=False)}

Zayıf konular (sınıfın %50+ hatası):
{json.dumps([{'konu': t['konu'], 'kac_kisi': int(t['yapamayan_ogr'])} for t in topics[:3]], ensure_ascii=False)}

Tebrik edilebilir (son sınav top):
{json.dumps([{'ad': w['full_name'], 'fizik': float(w['fizik'] or 0)} for w in wins[:2]], ensure_ascii=False)}

Mesaj kuralları:
- Selamlama yok, direkt veriden başla
- Risk → "🚨 dikkat:" ile
- Konu → "📚 önerilen başlangıç:" ile
- Tebrik → "🎯 not:" ile
- Sonda 1 cümle eylem önerisi"""

        result = await client.complete_async(
            messages=[{"role": "user", "content": prompt}],
            system="Sen kıdemli bir eğitim koordinatörüsün. Öğretmenlere kısa, profesyonel brief yazarsın.",
            model="gpt-oss-120b",
            max_tokens=400,
            temperature=0.4,
        )
        if result.get("ok") and result.get("text"):
            return result["text"].strip()
    except Exception as e:
        logger.debug(f"[BRIEFING] Cerebras fail: {e}, fallback")

    # Fallback şablon
    lines = [f"📋 {data['lesson']} — {data['class_name']}"]
    if stats.get("ogrenci_sayisi"):
        lines.append(f"👥 {stats['ogrenci_sayisi']} öğrenci")
    if risk:
        names = ", ".join(r["full_name"].split()[0] + " " + r["full_name"].split()[-1][0]
                          for r in risk[:3])
        lines.append(f"🚨 Risk: {names}")
    if topics:
        konu_list = ", ".join(t["konu"] for t in topics[:2])
        lines.append(f"📚 Önerilen: {konu_list}")
    if wins:
        w = wins[0]
        lines.append(f"🎯 Tebrik: {w['full_name'].split()[0]} (fizik {w['fizik']})")
    return "\n".join(lines)


async def queue_briefings_for_window(window_start_min: int = 15,
                                      window_end_min: int = 90) -> dict:
    """Önümüzdeki dersleri al, brief üret, queue'ya yaz.

    Returns: {generated, queued, errors, dry_run, wp_active}
    """
    from db_pool import db_execute, db_fetchval

    feature_active = await is_feature_active()
    dry = await is_dry_run()
    report = {"generated": 0, "queued": 0, "errors": 0,
              "dry_run": dry, "wp_active": feature_active,
              "items": []}

    lessons = await get_upcoming_lessons(window_start_min, window_end_min)
    if not lessons:
        return report

    for l in lessons:
        try:
            # Aynı ders için son 1 saatte queue var mı? (dedup)
            existed = await db_fetchval(
                """SELECT id FROM teacher_briefing_queue
                   WHERE teacher_name = $1 AND class_name = $2
                     AND scheduled_for > NOW() - INTERVAL '60 minutes'
                   LIMIT 1""",
                l.get("teacher_name"), l.get("class_name")
            )
            if existed:
                continue

            data = await gather_brief_data(
                l.get("teacher_name", ""),
                l.get("class_name", ""),
                l.get("lesson", "")
            )
            text = await generate_brief_text(data)
            report["generated"] += 1

            # scheduled_for için tarih + saat birleştir
            now = datetime.now()
            try:
                t = l.get("start_time")
                if isinstance(t, str):
                    h, m = map(int, t.split(":")[:2])
                else:
                    h, m = t.hour, t.minute
                scheduled = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if scheduled < now:
                    scheduled += timedelta(days=1)
            except Exception:
                scheduled = now + timedelta(minutes=30)

            # teacher phone: staff tablosundan al
            phone = await db_fetchval(
                "SELECT phone FROM staff WHERE UPPER(full_name) = UPPER($1) LIMIT 1",
                l.get("teacher_name", "")
            )

            await db_execute(
                """INSERT INTO teacher_briefing_queue
                   (teacher_name, teacher_phone, class_name, lesson_label,
                    scheduled_for, brief_payload, rendered_text,
                    status, wp_active_at_queue)
                   VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,$8,$9)""",
                l.get("teacher_name"), phone, l.get("class_name"),
                l.get("lesson"), scheduled,
                json.dumps(data, default=str), text,
                "queued", feature_active
            )
            report["queued"] += 1
            report["items"].append({
                "teacher": l.get("teacher_name"),
                "class": l.get("class_name"),
                "lesson": l.get("lesson"),
                "preview": text[:120]
            })
        except Exception as e:
            logger.warning(f"[BRIEFING] item fail: {e}")
            report["errors"] += 1

    logger.info(f"🎯 [TEACHER_BRIEFING] {report['queued']} brief queued "
                f"(dry={dry}, wp_active={feature_active})")
    return report


async def deliver_pending_briefings() -> dict:
    """WP_ACTIVE=true ise queue'daki brief'leri WP'ye gönderir.

    ŞU AN: feature_active=False olduğunda gönderim YAPILMAZ — sadece log.
    """
    feature_active = await is_feature_active()
    if not feature_active:
        return {"delivered": 0, "reason": "feature_inactive (yeni sezon)"}

    # Yeni sezonda aktive olduğunda buraya gerçek delivery kodu gelir.
    # secure_messenger üzerinden onay+log ile gönderim.
    return {"delivered": 0, "reason": "delivery_not_implemented_yet"}


async def briefing_scheduler_loop():
    """Bridge lifespan'a takılır — her saat 15-30 ve 30dk'da bir tarama."""
    logger.info("📋 Teacher Briefing scheduler basladi (her 15dk tarama)")
    while True:
        try:
            await queue_briefings_for_window(15, 90)
        except Exception as e:
            logger.error(f"[BRIEFING_LOOP] {e}")
        await asyncio.sleep(900)  # 15dk


# ─── CLI ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    async def _main():
        if len(sys.argv) > 1 and sys.argv[1] == "queue":
            r = await queue_briefings_for_window(15, 240)  # genis pencere test
            print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
        elif len(sys.argv) > 1 and sys.argv[1] == "deliver":
            r = await deliver_pending_briefings()
            print(json.dumps(r, ensure_ascii=False, indent=2))
        else:
            print("Kullanim: python teacher_briefing.py [queue|deliver]")
    asyncio.run(_main())
