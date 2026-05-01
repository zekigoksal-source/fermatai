"""
Behavior Rules — Dinamik Davranış Kuralı Sistemi
================================================
25.37 (Neo direktif): system_prompt şişmesin diye kuralları DB'ye yaz,
sadece role/scope ile filtrelenmiş aktif kurallar prompt'a inject olsun.

Tablo: bot_behavior_rules
  - rule_id        SERIAL PK
  - scope          TEXT — 'global' | 'admin' | 'mudur' | 'ogretmen' | 'rehber' | 'ogrenci' | 'veli'
  - category       TEXT — 'data_priority' | 'naming' | 'safety' | 'tone' | 'format' | 'misc'
  - rule_text      TEXT — Claude'a inject edilecek tek satır kural
  - priority       INT — 1 (kritik) - 10 (önemsiz)
  - active         BOOLEAN
  - created_by     TEXT — phone (Neo)
  - created_at     TIMESTAMP
  - expires_at     TIMESTAMP — NULL = kalici
  - usage_count    INT — kuralı görmüş cevap sayısı (analytics)

Public API:
  - add_rule(scope, category, rule_text, priority, expires_at, created_by)
  - list_rules(scope_filter, only_active=True, limit=50)
  - get_active_rules_for_role(role) -> [rule_text, ...]  → prompt inject için
  - deactivate_rule(rule_id)
  - update_rule(rule_id, ...)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Optional
from loguru import logger

from db_pool import db_execute, db_fetch, db_fetchrow, db_fetchval


VALID_SCOPES = {"global", "admin", "mudur", "ogretmen", "rehber", "ogrenci", "veli"}
VALID_CATEGORIES = {
    "data_priority", "naming", "safety", "tone", "format", "render", "misc"
}


async def ensure_table():
    """Tablo yoksa oluştur — idempotent."""
    try:
        await db_execute("""
            CREATE TABLE IF NOT EXISTS bot_behavior_rules (
                rule_id SERIAL PRIMARY KEY,
                scope TEXT NOT NULL DEFAULT 'global',
                category TEXT NOT NULL DEFAULT 'misc',
                rule_text TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 5,
                active BOOLEAN NOT NULL DEFAULT TRUE,
                created_by TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                expires_at TIMESTAMP,
                usage_count INTEGER DEFAULT 0,
                CONSTRAINT chk_scope CHECK (
                    scope IN ('global','admin','mudur','ogretmen','rehber','ogrenci','veli')
                ),
                CONSTRAINT chk_priority CHECK (priority BETWEEN 1 AND 10)
            )
        """)
        await db_execute(
            "CREATE INDEX IF NOT EXISTS idx_brules_active ON bot_behavior_rules(active, scope) WHERE active = TRUE"
        )
        await db_execute(
            "CREATE INDEX IF NOT EXISTS idx_brules_expires ON bot_behavior_rules(expires_at) WHERE expires_at IS NOT NULL"
        )
        logger.debug("bot_behavior_rules ensure_table OK")
    except Exception as e:
        logger.warning(f"bot_behavior_rules ensure_table hata: {e}")


async def add_rule(
    rule_text: str,
    scope: str = "global",
    category: str = "misc",
    priority: int = 5,
    expires_at: Optional[datetime] = None,
    created_by: str = "",
) -> dict:
    """Yeni davranış kuralı ekle. Neo veya admin tarafından çağrılır."""
    rule_text = (rule_text or "").strip()
    if not rule_text:
        return {"success": False, "error": "rule_text boş olamaz"}
    if len(rule_text) > 800:
        return {"success": False, "error": f"rule_text çok uzun ({len(rule_text)}/800 char)"}
    if scope not in VALID_SCOPES:
        return {"success": False, "error": f"scope geçersiz: {scope} (geçerli: {VALID_SCOPES})"}
    if category not in VALID_CATEGORIES:
        category = "misc"
    priority = max(1, min(10, priority))
    try:
        await ensure_table()
        rule_id = await db_fetchval(
            """INSERT INTO bot_behavior_rules
               (scope, category, rule_text, priority, expires_at, created_by)
               VALUES ($1, $2, $3, $4, $5, $6) RETURNING rule_id""",
            scope, category, rule_text, priority, expires_at, created_by[:20]
        )
        logger.info(f"behavior_rule eklendi: id={rule_id} scope={scope} cat={category} by={created_by[-4:] if created_by else '?'}")
        return {"success": True, "rule_id": rule_id, "scope": scope, "category": category}
    except Exception as e:
        logger.error(f"add_rule hata: {e}")
        return {"success": False, "error": str(e)}


async def list_rules(
    scope_filter: str = "",
    category_filter: str = "",
    only_active: bool = True,
    limit: int = 50,
) -> list[dict]:
    """Mevcut kuralları listele."""
    try:
        await ensure_table()
        conditions = []
        args = []
        if only_active:
            conditions.append("active = TRUE")
            conditions.append("(expires_at IS NULL OR expires_at > NOW())")
        if scope_filter and scope_filter in VALID_SCOPES:
            args.append(scope_filter)
            conditions.append(f"scope = ${len(args)}")
        if category_filter:
            args.append(category_filter)
            conditions.append(f"category = ${len(args)}")
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        args.append(int(limit or 50))
        sql = f"""SELECT rule_id, scope, category, rule_text, priority, active,
                         created_at, expires_at, usage_count, created_by
                  FROM bot_behavior_rules{where}
                  ORDER BY priority ASC, created_at DESC LIMIT ${len(args)}"""
        rows = await db_fetch(sql, *args)
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"list_rules hata: {e}")
        return []


async def get_active_rules_for_role(role: str, limit: int = 30) -> list[str]:
    """Prompt inject için aktif kural metinleri.
    Hem 'global' hem rolspesifik kurallar gelir, prio sırasında.
    Returns: [rule_text, ...] (sade string liste — prompt'a hazır).
    """
    try:
        await ensure_table()
        rows = await db_fetch(
            """SELECT rule_id, rule_text FROM bot_behavior_rules
               WHERE active = TRUE
                 AND (expires_at IS NULL OR expires_at > NOW())
                 AND (scope = 'global' OR scope = $1)
               ORDER BY priority ASC, created_at DESC
               LIMIT $2""",
            role, int(limit or 30)
        )
        # Async fire-and-forget: usage_count++
        if rows:
            ids = [r["rule_id"] for r in rows]
            asyncio.create_task(_inc_usage(ids))
        return [r["rule_text"] for r in rows]
    except Exception as e:
        logger.debug(f"get_active_rules_for_role hata: {e}")
        return []


async def _inc_usage(rule_ids: list[int]) -> None:
    try:
        await db_execute(
            "UPDATE bot_behavior_rules SET usage_count = usage_count + 1 WHERE rule_id = ANY($1)",
            rule_ids
        )
    except Exception:
        pass


async def deactivate_rule(rule_id: int) -> dict:
    try:
        await ensure_table()
        await db_execute(
            "UPDATE bot_behavior_rules SET active = FALSE WHERE rule_id = $1",
            int(rule_id)
        )
        logger.info(f"behavior_rule deaktive: id={rule_id}")
        return {"success": True, "rule_id": rule_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def update_rule(
    rule_id: int,
    rule_text: Optional[str] = None,
    priority: Optional[int] = None,
    active: Optional[bool] = None,
) -> dict:
    """Mevcut kuralı güncelle."""
    try:
        await ensure_table()
        sets = []
        args = []
        if rule_text is not None:
            args.append(rule_text[:800])
            sets.append(f"rule_text = ${len(args)}")
        if priority is not None:
            args.append(max(1, min(10, int(priority))))
            sets.append(f"priority = ${len(args)}")
        if active is not None:
            args.append(bool(active))
            sets.append(f"active = ${len(args)}")
        if not sets:
            return {"success": False, "error": "Güncellenecek alan yok"}
        args.append(int(rule_id))
        sql = f"UPDATE bot_behavior_rules SET {', '.join(sets)} WHERE rule_id = ${len(args)}"
        await db_execute(sql, *args)
        return {"success": True, "rule_id": rule_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def build_rules_prompt_block(role: str, message_hint: str = "") -> str:
    """Prompt'a inject edilecek tam blok metni.

    25.37+ (Neo audit #9): CONTEXT-AWARE FİLTER.
    Bağlamsız kuralları çıkar — token tasarrufu (~500 tok/cevap):
      - Render kuralları SADECE konu/sim/quiz mesajlarında
      - Naming kuralı SADECE yönetim/iletişim mesajlarında
      - Safety + data_priority HER ZAMAN (kritik)
      - Diğer kategoriler her zaman (varsayılan)

    Boşsa boş string döner.
    """
    try:
        await ensure_table()
        # Tüm aktif kuralları rule_id + category ile çek (filter için lazım)
        rows = await db_fetch(
            """SELECT rule_id, rule_text, category, priority FROM bot_behavior_rules
               WHERE active = TRUE
                 AND (expires_at IS NULL OR expires_at > NOW())
                 AND (scope = 'global' OR scope = $1)
               ORDER BY priority ASC, created_at DESC LIMIT 30""",
            role
        )
    except Exception as e:
        logger.debug(f"build_rules_prompt_block fetch hata: {e}")
        return ""

    if not rows:
        return ""

    msg_lower = (message_hint or "").lower()

    # Context detection — hangi kategoriler aktif olmalı?
    # Render keyword'leri → render kuralları aktif
    has_render_context = bool(re.search(
        r'\b(simul|3d|gostcr|göster|interaktif|grafik|chart|kavram|nedir|anlat|formul|formül|'
        r'qu[iı]z|test|sınav|sinav|kıyas|kar[şs]ıla[şs]t|fark|graph|harita|hedef|plan)',
        msg_lower
    ))
    # Yönetim keyword'leri → naming kuralı aktif
    has_naming_context = bool(re.search(
        r'\b(yönet|yonet|m[uü]d[uü]r|patron|y[öo]netici|kim[\s\?]|kime\s+ula[şs])',
        msg_lower
    ))
    # Veri sorgusu keyword'leri → data_priority kuralı aktif
    has_data_context = bool(re.search(
        r'\b(bug[uü]n|yarın|yarin|bu\s+hafta|hangi|kac\s+tane|kaç\s+tane|toplam|kim\s+geldi)',
        msg_lower
    ))

    # Filter logic
    filtered = []
    for r in rows:
        cat = (r["category"] or "misc").lower()
        prio = r["priority"]
        # P1 safety + data_priority HER ZAMAN gönderilir (kritik)
        if cat in ("safety", "data_priority") and prio <= 1:
            filtered.append(r["rule_text"])
            continue
        # Render kuralları sadece render context'inde
        if cat == "render":
            if has_render_context or message_hint == "":
                filtered.append(r["rule_text"])
            continue
        # Naming kuralı sadece yönetim context'inde
        if cat == "naming":
            if has_naming_context or message_hint == "":
                filtered.append(r["rule_text"])
            continue
        # Data priority her veri context'inde
        if cat == "data_priority":
            if has_data_context or prio <= 2 or message_hint == "":
                filtered.append(r["rule_text"])
            continue
        # Diğer kategoriler (misc, tone, format) her zaman gönder
        filtered.append(r["rule_text"])

    if not filtered:
        return ""

    # Async fire-forget: usage_count++
    try:
        rule_ids = [r["rule_id"] for r in rows if r["rule_text"] in filtered]
        if rule_ids:
            asyncio.create_task(_inc_usage(rule_ids))
    except Exception:
        pass

    lines = ["", "═══════════════════════════════════════════════════════════════════════",
             f"📋 DİNAMİK DAVRANIŞ KURALLARI ({len(filtered)}/{len(rows)} bağlamsal filtre, Neo onayli)",
             "═══════════════════════════════════════════════════════════════════════"]
    for i, r in enumerate(filtered, 1):
        lines.append(f"{i}. {r}")
    lines.append("")
    return "\n".join(lines)


# CLI helper — manual test
async def _cli():
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "list":
        rows = await list_rules()
        for r in rows:
            print(f"#{r['rule_id']} [{r['scope']}/{r['category']}] p={r['priority']} usage={r['usage_count']}")
            print(f"  {r['rule_text'][:200]}")
    elif cmd == "add":
        result = await add_rule(
            rule_text=sys.argv[2],
            scope=sys.argv[3] if len(sys.argv) > 3 else "global",
            category=sys.argv[4] if len(sys.argv) > 4 else "misc",
            created_by="cli"
        )
        print(result)
    elif cmd == "deactivate":
        result = await deactivate_rule(int(sys.argv[2]))
        print(result)
    elif cmd == "ensure":
        await ensure_table()
        print("OK")
    else:
        print("Kullanım: behavior_rules.py [list|add|deactivate|ensure] [args]")


if __name__ == "__main__":
    asyncio.run(_cli())
