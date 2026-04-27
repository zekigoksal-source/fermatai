"""
F2 — Auto Follow-Up Engine (Oturum 25.28)
==============================================

Sınav sync sonrası her öğrenci için pedagojik öneri otomatik üretilir.

Trigger:
  - exam_sync (sync_exams.py / smart_sync.py'den çağrılır)
  - manual (Neo komut ile)

Akış:
  1. Sınav sonrası student_topic_tracker güncellenir (zaten yapılıyor)
  2. Bu module: her öğrenci için top 3 zayıf konu çıkar
  3. Cerebras 70B ile pedagojik öneri üretir (kısa, motive, çağrı eylem-odaklı)
  4. RAG'dan ilgili kaynak bul (rag_content tablosu)
  5. student_followups queue'ya yaz
  6. WP gönderim: FOLLOWUP_WP_ACTIVE=true ise gönderir
     False ise queue'da kalır (admin görür)

ŞU AN: WP_ACTIVE=False — yeni sezon Neo aktive edecek.
"""
from __future__ import annotations
import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import Optional
from loguru import logger


async def is_feature_active() -> bool:
    try:
        from db_pool import db_fetchval
        v = await db_fetchval(
            "SELECT value FROM sistem_ayar WHERE key='FOLLOWUP_WP_ACTIVE'"
        )
        return (v or "").lower() == "true"
    except Exception:
        return False


async def get_student_weak_topics(soz_no: int, limit: int = 3) -> list[dict]:
    """student_topic_tracker'dan top N zayıf konu."""
    from db_pool import db_fetch
    try:
        rows = await db_fetch(
            """SELECT ders, konu, sinav_hata_yuzdesi AS hata_orani,
                      status AS calisma_durumu
               FROM student_topic_tracker
               WHERE soz_no = $1
                 AND sinav_hata_yuzdesi >= 40
                 AND tamamlandi = false
               ORDER BY sinav_hata_yuzdesi DESC, calisti_tarih DESC NULLS LAST
               LIMIT $2""",
            soz_no, limit
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.debug(f"[FOLLOWUP] weak topics fail: {e}")
        return []


async def get_resources_for_topic(ders: str, konu: str, limit: int = 3) -> list[dict]:
    """rag_content'tan konu ile ilgili kaynak öner (semantic search)."""
    from db_pool import db_fetch
    try:
        # Basit ders + konu LIKE araması (semantic için ayrıca rag_engine kullanılabilir)
        rows = await db_fetch(
            """SELECT id, sinav_turu, ders, konu, LEFT(icerik, 200) AS preview
               FROM rag_content
               WHERE ders ILIKE '%' || $1 || '%'
                 AND (konu ILIKE '%' || $2 || '%' OR icerik ILIKE '%' || $2 || '%')
               LIMIT $3""",
            ders, konu, limit
        )
        return [dict(r) for r in rows]
    except Exception:
        return []


async def generate_suggestion_text(student_name: str, weak_topics: list[dict],
                                     resources: list[dict]) -> str:
    """Cerebras ile motivasyonel + eylem-odaklı öneri."""
    if not weak_topics:
        return ""

    try:
        from cerebras_handler import CerebrasClient
        if not os.getenv("CEREBRAS_API_KEY"):
            raise RuntimeError("no api key")

        client = CerebrasClient()
        first_name = student_name.split()[0] if student_name else "Arkadaşım"
        topics_str = "\n".join(
            f"- {t['ders']}: {t['konu']} (%{int(t['sinav_hata_yuzdesi'])} hata)"
            for t in weak_topics[:3]
        )

        prompt = f"""Bu öğrenciye sınav sonrası 240 karakterlik motivasyon mesajı yaz.
Türkçe, samimi, eylem odaklı.

Öğrenci: {first_name}
Son sınavda zayıf çıkan konular:
{topics_str}

Mesaj kuralları:
- "{first_name}" diye samimi başla
- 1 cümle: "fark ettim X konusunda zorlanmışsın" (ders ismiyle)
- 1 cümle: somut çalışma önerisi (X video / 5 soru / 30dk)
- 1 cümle: motivasyon (kısa, yapay değil)
- Suçlayıcı/üzücü ton YOK"""

        result = await client.complete_async(
            messages=[{"role": "user", "content": prompt}],
            system="Sen samimi bir öğretmen koçusun. Öğrencinin sınav sonrası "
                   "moralini bozmadan eyleme yönlendirirsin. Türkçe, sıcak ton.",
            model="gpt-oss-120b",
            max_tokens=300,
            temperature=0.5,
        )
        if result.get("ok") and result.get("text"):
            return result["text"].strip()
    except Exception as e:
        logger.debug(f"[FOLLOWUP] Cerebras fail: {e}")

    # Fallback şablon
    fname = student_name.split()[0] if student_name else "Arkadaşım"
    t = weak_topics[0]
    return (f"{fname}, son sınavda {t['ders']}/{t['konu']} konusunda "
            f"zorlanmışsın (%{int(t['sinav_hata_yuzdesi'])} hata). "
            f"Bu hafta 30dk bu konuya odaklan, sonra 5 örnek soru çöz. "
            f"Bir adım atmak yeter, devamını birlikte planlarız 💪")


async def queue_followup_for_student(soz_no: int, trigger: str = "exam_sync",
                                       trigger_ref: str = "") -> Optional[int]:
    """Tek öğrenci için follow-up üret + queue'ya yaz."""
    from db_pool import db_fetchrow, db_fetchval, db_execute

    student = await db_fetchrow(
        "SELECT full_name FROM students WHERE soz_no::int = $1 AND status='active'",
        soz_no
    )
    if not student:
        return None

    weak = await get_student_weak_topics(soz_no, limit=3)
    if not weak:
        return None

    # Kaynak öner (ilk konu için)
    resources = []
    if weak:
        resources = await get_resources_for_topic(weak[0]["ders"], weak[0]["konu"], limit=3)

    suggestion = await generate_suggestion_text(student["full_name"], weak, resources)
    if not suggestion:
        return None

    # Dedup: son 24 saatte aynı trigger ile queue var mı?
    existed = await db_fetchval(
        """SELECT id FROM student_followups
           WHERE soz_no = $1 AND trigger_event = $2
             AND created_at > NOW() - INTERVAL '24 hours'
           LIMIT 1""",
        soz_no, trigger
    )
    if existed:
        return int(existed)

    feature_active = await is_feature_active()

    # Priority: en yüksek hata oranına göre
    avg_hata = sum(t["sinav_hata_yuzdesi"] for t in weak) / len(weak)
    priority = "urgent" if avg_hata >= 70 else "high" if avg_hata >= 55 else "normal"

    new_id = await db_fetchval(
        """INSERT INTO student_followups
           (soz_no, student_name, trigger_event, trigger_ref,
            weak_topics, suggestion_text, suggested_resources,
            priority, status, wp_active_at_queue, expires_at)
           VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7::jsonb,$8,'queued',$9,$10)
           RETURNING id""",
        soz_no, student["full_name"], trigger, trigger_ref,
        json.dumps(weak, default=str), suggestion,
        json.dumps([{"id": r["id"], "ders": r["ders"], "konu": r["konu"]}
                    for r in resources], default=str),
        priority, feature_active, datetime.now() + timedelta(days=7)
    )
    return int(new_id) if new_id else None


async def queue_followups_for_all_active(trigger: str = "exam_sync") -> dict:
    """Tüm aktif öğrenciler için tarama + queue."""
    from db_pool import db_fetch

    students = await db_fetch(
        "SELECT soz_no::int AS soz_no, full_name FROM students "
        "WHERE status='active' ORDER BY soz_no LIMIT 200"
    )

    report = {"checked": 0, "queued": 0, "skipped_no_weak": 0, "skipped_dedup": 0}
    for s in students:
        report["checked"] += 1
        try:
            new_id = await queue_followup_for_student(s["soz_no"], trigger)
            if new_id:
                report["queued"] += 1
            else:
                report["skipped_no_weak"] += 1
        except Exception as e:
            logger.debug(f"[FOLLOWUP] {s['soz_no']} fail: {e}")
        # Eyotek/Cerebras'i bunaltmamak icin
        await asyncio.sleep(0.2)

    logger.info(f"🔁 [FOLLOWUP] {report['queued']}/{report['checked']} ogrenci icin queue olustu")
    return report


async def deliver_pending_followups() -> dict:
    """WP_ACTIVE=true ise queued follow-up'lari WP'ye gonderir."""
    feature_active = await is_feature_active()
    if not feature_active:
        return {"delivered": 0, "reason": "feature_inactive (yeni sezon)"}
    # Yeni sezon aktive olduğunda gerçek delivery kodu burada
    return {"delivered": 0, "reason": "delivery_not_implemented_yet"}


# ─── CLI ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    async def _main():
        if len(sys.argv) > 1 and sys.argv[1] == "all":
            r = await queue_followups_for_all_active("manual_test")
            print(json.dumps(r, ensure_ascii=False, indent=2))
        elif len(sys.argv) > 2 and sys.argv[1] == "student":
            soz = int(sys.argv[2])
            new_id = await queue_followup_for_student(soz, "manual_test")
            print(f"queued id={new_id}")
        else:
            print("Kullanim: python followup_engine.py [all|student <soz_no>]")
    asyncio.run(_main())
