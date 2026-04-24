"""
Atlas Self-Observing Lifecycle Yönetimi (Neo Oturum 22.1)

Mantık:
- Bot bir sorun tespit eder → signature üret (category + title hash)
- İlk defa mı? → yeni kayıt, occurrence_count=1
- Daha önce görüldü + AÇIK (status='yeni') → occurrence_count++, last_seen_at update
- Daha önce çözüldü (status='uygulandi') + tekrar geldiyse → REGRESSION
  regressed_count++, status='regresyon', tekrar incele uyarısı
- Admin "atlas trend" sorunca → gün/hafta/ay bazlı istatistik

Bu sayede sistem:
✅ Aynı sorunu tekrar tekrar yeni bug gibi göstermez
✅ Çözüm sonrası regresyonları yakalar
✅ Hangi tip problem sık — trend analizi yapabilir
✅ Zaman içinde sağlık metriği (problem/kullanıcı oranı)
"""
import hashlib
from datetime import datetime
from typing import Optional
from loguru import logger


def _make_signature(category: str, title: str) -> str:
    """Sorun kimliği — aynı category+title tekrarını bulmak için."""
    raw = f"{(category or '').lower().strip()}::{(title or '').lower().strip()}"
    return hashlib.md5(raw.encode('utf-8')).hexdigest()[:16]


async def upsert_suggestion(category: str, severity: str, title: str,
                            rationale: str = "", estimated_impact: str = "") -> dict:
    """
    Atlas suggestion ekle — varsa occurrence++, yoksa yeni kayıt.

    Returns:
        {"action": "new|recurrence|regression", "id": int, "occurrence": int}
    """
    from db_pool import db_fetchrow, db_execute

    sig = _make_signature(category, title)

    # Var mı?
    existing = await db_fetchrow(
        """
        SELECT id, status, occurrence_count, resolved_at, regressed_count
        FROM atlas_suggestions WHERE signature = $1
        ORDER BY created_at DESC LIMIT 1
        """,
        sig
    )

    if not existing:
        # YENİ SORUN
        row = await db_fetchrow(
            """
            INSERT INTO atlas_suggestions
                (category, severity, title, rationale, estimated_impact, status,
                 signature, first_seen_at, last_seen_at, occurrence_count, created_at)
            VALUES ($1, $2, $3, $4, $5, 'yeni', $6, NOW(), NOW(), 1, NOW())
            RETURNING id
            """,
            category, severity, title, rationale, estimated_impact, sig
        )
        logger.info(f"🆕 Atlas yeni sorun: [{severity}/{category}] {title[:50]}")
        return {"action": "new", "id": row["id"], "occurrence": 1}

    # VAR — durumuna bak
    if existing["status"] == "uygulandi":
        # REGRESYON — önceden çözülmüş, tekrar geldi
        await db_execute(
            """
            UPDATE atlas_suggestions
            SET status = 'regresyon',
                regressed_count = regressed_count + 1,
                occurrence_count = occurrence_count + 1,
                last_seen_at = NOW()
            WHERE id = $1
            """,
            existing["id"]
        )
        logger.warning(f"⚠️  Atlas REGRESSION: {title[:50]} (daha önce çözüldü, tekrar geldi)")
        return {
            "action": "regression",
            "id": existing["id"],
            "occurrence": existing["occurrence_count"] + 1,
            "regressed": existing["regressed_count"] + 1,
        }
    else:
        # TEKRAR — aynı açık sorun tekrar tetiklendi
        await db_execute(
            """
            UPDATE atlas_suggestions
            SET occurrence_count = occurrence_count + 1,
                last_seen_at = NOW()
            WHERE id = $1
            """,
            existing["id"]
        )
        return {
            "action": "recurrence",
            "id": existing["id"],
            "occurrence": existing["occurrence_count"] + 1,
        }


async def mark_resolved(suggestion_id: int, note: str = "") -> bool:
    """Bir suggestion'ı çözüldü olarak işaretle."""
    from db_pool import db_execute
    await db_execute(
        """
        UPDATE atlas_suggestions
        SET status = 'uygulandi', resolved_at = NOW()
        WHERE id = $1
        """,
        suggestion_id
    )
    logger.info(f"✅ Atlas #{suggestion_id} resolved")
    return True


async def get_trend(days: int = 30) -> dict:
    """Atlas trend — son N gün istatistik."""
    from db_pool import db_fetch, db_fetchrow

    # Özet rakamlar
    summary = await db_fetchrow(
        f"""
        SELECT
            COUNT(*) AS toplam,
            COUNT(*) FILTER (WHERE status='yeni') AS acik,
            COUNT(*) FILTER (WHERE status='uygulandi') AS cozulen,
            COUNT(*) FILTER (WHERE status='regresyon') AS regresyon,
            AVG(occurrence_count) AS ort_tekrar,
            MAX(occurrence_count) AS max_tekrar,
            SUM(regressed_count) AS toplam_regresyon
        FROM atlas_suggestions
        WHERE first_seen_at > NOW() - INTERVAL '{int(days)} days'
        """
    )

    # Kategori dağılımı
    by_category = await db_fetch(
        f"""
        SELECT category, COUNT(*) AS sayi, SUM(occurrence_count) AS tekrar
        FROM atlas_suggestions
        WHERE first_seen_at > NOW() - INTERVAL '{int(days)} days'
        GROUP BY category
        ORDER BY tekrar DESC LIMIT 10
        """
    )

    # Günlük yeni sorun trendi
    daily = await db_fetch(
        f"""
        SELECT DATE(first_seen_at) AS gun, COUNT(*) AS yeni
        FROM atlas_suggestions
        WHERE first_seen_at > NOW() - INTERVAL '{int(days)} days'
        GROUP BY DATE(first_seen_at)
        ORDER BY gun
        """
    )

    # En çok tekrar eden 5 sorun
    top_recurring = await db_fetch(
        """
        SELECT id, title, category, severity, occurrence_count, regressed_count,
               status, first_seen_at, last_seen_at
        FROM atlas_suggestions
        ORDER BY occurrence_count DESC
        LIMIT 5
        """
    )

    return {
        "days": days,
        "summary": dict(summary) if summary else {},
        "by_category": [dict(r) for r in by_category],
        "daily_new": [{"gun": r["gun"].isoformat(), "sayi": r["yeni"]} for r in daily],
        "top_recurring": [dict(r) for r in top_recurring],
    }


async def check_and_remind(phone: str, new_signature: str) -> Optional[str]:
    """
    Bot aynı sorunu tekrar tetiklemeden önce geçmişe baksın.
    Bu helper: "Bu sorunu daha önce çözmüştük" cevabı üretir.
    """
    from db_pool import db_fetchrow
    existing = await db_fetchrow(
        """
        SELECT status, resolved_at, occurrence_count
        FROM atlas_suggestions WHERE signature = $1
        """,
        new_signature
    )
    if existing and existing["status"] == "uygulandi":
        return (
            f"[Atlas — Zaten Çözüldü] Bu problemi daha önce "
            f"{existing['occurrence_count']}x tespit etmiştik, "
            f"{existing['resolved_at'].strftime('%d %b') if existing['resolved_at'] else 'önceden'} çözüldü. "
            f"Eğer sorun tekrar yaşanıyorsa REGRESYON olarak işaretliyorum."
        )
    return None
