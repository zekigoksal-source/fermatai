"""
DB Retention Policy (Oturum 25.24)
====================================

Eski log/conversation kayıtlarını arşivle veya sil — DB sınırsız büyümesin.

Politika:
- agent_conversations: 90 gün öncesi → arşive (CSV export) sonra DELETE
- routing_stats: 60 gün öncesi → DELETE (analitik için 60 gün yeter)
- usage_log: 180 gün öncesi → DELETE (maliyet 6 ay yeter)
- query_cache: 30 gün öncesi → DELETE (TTL zaten kısa)
- alert_log: 365 gün tutma (audit önemli)

Cron: Haftalık Pazar 04:30 (yeni cron eklenir whatsapp_bridge.py'a)

KVKK: agent_conversations arşivde de telefon hash'lenir (SHA256[:16]).
"""
from __future__ import annotations
import asyncio
import hashlib
import csv
import os
from datetime import datetime, timedelta
from pathlib import Path
from loguru import logger


ARCHIVE_DIR = Path("/opt/fermatai/archive")


async def archive_agent_conversations(days_old: int = 90) -> dict:
    """90 gün öncesi konuşmaları CSV'ye arşivle, sonra DB'den sil."""
    from db_pool import db_fetch, db_execute
    cutoff = datetime.now() - timedelta(days=days_old)

    rows = await db_fetch(
        "SELECT id, session_id, phone, role, message_role, content, tools_used, created_at FROM agent_conversations WHERE created_at < $1",
        cutoff
    )
    if not rows:
        return {"archived": 0, "deleted": 0}

    # Arşiv dizini
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive_file = ARCHIVE_DIR / f"agent_conversations_{cutoff.date().isoformat()}.csv"

    with archive_file.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "session_id", "phone_hash", "role", "message_role",
                    "content_truncated", "tools_used", "created_at"])
        for r in rows:
            # Telefon hash (KVKK)
            phone = r["phone"] or ""
            phone_hash = hashlib.sha256(phone.encode()).hexdigest()[:16]
            content = (r["content"] or "")[:500]  # özet
            w.writerow([
                r["id"], r["session_id"], phone_hash, r["role"], r["message_role"],
                content, str(r["tools_used"] or ""), r["created_at"].isoformat()
            ])

    archived = len(rows)
    # Sil
    deleted = await db_execute(
        "DELETE FROM agent_conversations WHERE created_at < $1",
        cutoff
    )
    logger.info(f"📦 agent_conversations: {archived} kayit arsivlendi → {archive_file}, {deleted} silindi")
    return {"archived": archived, "deleted": archived, "file": str(archive_file)}


async def cleanup_routing_stats(days_old: int = 60) -> dict:
    """60 gün öncesi routing_stats sil (analitik için 60 gün yeter)."""
    from db_pool import db_execute
    cutoff = datetime.now() - timedelta(days=days_old)
    result = await db_execute(
        "DELETE FROM routing_stats WHERE created_at < $1",
        cutoff
    )
    logger.info(f"🗑️  routing_stats: {days_old}+ gün silindi")
    return {"days_old": days_old}


async def cleanup_usage_log(days_old: int = 180) -> dict:
    """180 gün öncesi usage_log sil (maliyet 6 ay yeter)."""
    from db_pool import db_execute
    cutoff = datetime.now() - timedelta(days=days_old)
    await db_execute(
        "DELETE FROM usage_log WHERE created_at < $1",
        cutoff
    )
    logger.info(f"🗑️  usage_log: {days_old}+ gün silindi")
    return {"days_old": days_old}


async def cleanup_query_cache(days_old: int = 30) -> dict:
    """30 gün öncesi query_cache sil."""
    from db_pool import db_execute
    cutoff = datetime.now() - timedelta(days=days_old)
    await db_execute(
        "DELETE FROM query_cache WHERE created_at < $1",
        cutoff
    )
    logger.info(f"🗑️  query_cache: {days_old}+ gün silindi")
    return {"days_old": days_old}


async def run_full_retention() -> dict:
    """Tüm retention policy'leri tek seferde çalıştır."""
    results = {}
    try:
        results["agent_conversations"] = await archive_agent_conversations(90)
    except Exception as e:
        logger.warning(f"agent_conversations arşiv hata: {e}")
        results["agent_conversations"] = {"error": str(e)[:200]}

    for fn, name in [
        (lambda: cleanup_routing_stats(60), "routing_stats"),
        (lambda: cleanup_usage_log(180), "usage_log"),
        (lambda: cleanup_query_cache(30), "query_cache"),
    ]:
        try:
            results[name] = await fn()
        except Exception as e:
            logger.warning(f"{name} cleanup hata: {e}")
            results[name] = {"error": str(e)[:200]}

    logger.info(f"✅ DB retention tamamlandi: {results}")
    return results


if __name__ == "__main__":
    asyncio.run(run_full_retention())
