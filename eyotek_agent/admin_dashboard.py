"""
FermatAI BATCOMPUTER — Mühendislik & CEO Dashboard
====================================================
Sistem performansı, geliştirme süreci, maliyet, altyapı raporu.
Akademik veri YOK (o WP'den konuşuluyor).

Zaman filtresi: today | 7d | 30d | all
"""
import asyncio
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger
from db_pool import (
    get_pool as _pool,
    db_fetch as _fetch,
    db_fetchrow as _fetchone,
    db_fetchval as _fetchval,
)


# ═══════════════════════════════════════════════════════════════════════
# Zaman filtresi — SQL WHERE clause uretir
# ═══════════════════════════════════════════════════════════════════════

def time_filter(period: str, col: str = "created_at") -> str:
    """SQL WHERE clause'u uretir (period: today|7d|30d|all)."""
    if period == "today":
        return f"{col} >= CURRENT_DATE"
    elif period == "7d":
        return f"{col} >= NOW() - INTERVAL '7 days'"
    elif period == "30d":
        return f"{col} >= NOW() - INTERVAL '30 days'"
    elif period == "90d":
        return f"{col} >= NOW() - INTERVAL '90 days'"
    else:  # all
        return "1=1"


def period_label(period: str) -> str:
    return {"today": "Bugün", "7d": "Son 7 Gün", "30d": "Son 30 Gün",
            "90d": "Son 90 Gün", "all": "Tüm Zamanlar"}.get(period, period)


# ═══════════════════════════════════════════════════════════════════════
# LIFETIME — projenin başından beri
# ═══════════════════════════════════════════════════════════════════════

async def get_lifetime():
    """Projenin başından beri tüm zaman toplamları."""
    # Toplam mesaj
    msg_total = await _fetchone("""
        SELECT
            COUNT(*) FILTER (WHERE message_role='user') as user_msg,
            COUNT(*) FILTER (WHERE message_role='assistant') as bot_msg,
            COUNT(*) FILTER (WHERE message_role='student_interaction') as interact_msg,
            COUNT(DISTINCT phone) as kisi,
            MIN(created_at) as ilk_mesaj,
            MAX(created_at) as son_mesaj
        FROM agent_conversations
    """)

    # Toplam Claude çağrısı (tahmini token + maliyet)
    claude_total = await _fetchval("""
        SELECT COUNT(*) FROM agent_conversations
        WHERE message_role='assistant'
          AND (tools_used::text NOT LIKE '%ollama%' AND tools_used::text NOT LIKE '%fast%')
    """) or 0

    ollama_total = await _fetchval("""
        SELECT COUNT(*) FROM agent_conversations
        WHERE message_role='assistant' AND tools_used::text LIKE '%ollama%'
    """) or 0

    fast_total = await _fetchval("""
        SELECT COUNT(*) FROM agent_conversations
        WHERE message_role='assistant' AND tools_used::text LIKE '%fast%'
    """) or 0

    # Token tahmin: claude çağrısı başına ~2000 input + 500 output
    input_tokens = claude_total * 2000
    output_tokens = claude_total * 500
    total_tokens = input_tokens + output_tokens

    # Maliyet: cache hit %70 varsayımla
    cache_hit = 0.70
    eff_in_cost = (1 - cache_hit) * input_tokens * 3 / 1_000_000 + cache_hit * input_tokens * 0.30 / 1_000_000
    out_cost = output_tokens * 15 / 1_000_000
    total_usd = eff_in_cost + out_cost
    TL_RATE = 33.0

    # Eğer hep Claude olsaydı (cache YOK varsayımı) → tasarruf hesabı
    no_cache_in = input_tokens * 3 / 1_000_000
    no_fast_no_ollama = (fast_total + ollama_total) * 2500 * 3 / 1_000_000  # bu çağrılar Claude olsaydı
    potential_cost = no_cache_in + out_cost + no_fast_no_ollama
    saving_usd = potential_cost - total_usd

    # Sistem yaşı (gün)
    if msg_total and msg_total['ilk_mesaj']:
        sistem_yasi = (datetime.now() - msg_total['ilk_mesaj'].replace(tzinfo=None)).days
    else:
        sistem_yasi = 0

    # Toplam kayıtlı kullanıcı
    total_users = await _fetchval("SELECT COUNT(*) FROM acl_users WHERE is_active=TRUE") or 0
    total_students = await _fetchval("SELECT COUNT(*) FROM students") or 0

    # Lifetime aktif kullanıcı (en az 1 mesaj atmış)
    active_lifetime = await _fetchval("""
        SELECT COUNT(DISTINCT phone) FROM agent_conversations
        WHERE message_role='user'
    """) or 0

    return {
        "toplam_mesaj_user": msg_total['user_msg'] if msg_total else 0,
        "toplam_mesaj_bot": msg_total['bot_msg'] if msg_total else 0,
        "toplam_interaction": msg_total['interact_msg'] if msg_total else 0,
        "toplam_kisi_konusan": msg_total['kisi'] if msg_total else 0,
        "ilk_mesaj": str(msg_total['ilk_mesaj']) if msg_total and msg_total['ilk_mesaj'] else None,
        "son_mesaj": str(msg_total['son_mesaj']) if msg_total and msg_total['son_mesaj'] else None,
        "sistem_yasi_gun": sistem_yasi,
        "claude_total": claude_total,
        "ollama_total": ollama_total,
        "fast_total": fast_total,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_usd, 2),
        "total_cost_tl": round(total_usd * TL_RATE, 2),
        "potential_cost_tl": round(potential_cost * TL_RATE, 2),
        "tasarruf_tl": round(saving_usd * TL_RATE, 2),
        "tasarruf_yuzde": round(saving_usd / max(potential_cost, 0.001) * 100, 1),
        "kayitli_kullanici": total_users,
        "kayitli_ogrenci": total_students,
        "aktif_kullanici_lifetime": active_lifetime,
    }


# ═══════════════════════════════════════════════════════════════════════
# FILTRELI METRIKLER (period: today|7d|30d|all)
# ═══════════════════════════════════════════════════════════════════════

async def get_messages_by_period(period: str):
    """Belirli zaman aralığındaki mesaj istatistiği."""
    tf = time_filter(period)
    r = await _fetchone(f"""
        SELECT
            COUNT(*) FILTER (WHERE message_role='user') as user_msg,
            COUNT(*) FILTER (WHERE message_role='assistant') as bot_msg,
            COUNT(DISTINCT phone) as kisi
        FROM agent_conversations WHERE {tf}
    """)

    # Trend grafiği — period uzunluğuna göre granularite
    if period == "today":
        # Saatlik
        rows = await _fetch(f"""
            SELECT EXTRACT(HOUR FROM created_at) as bucket, COUNT(*) as cnt
            FROM agent_conversations WHERE {tf} AND message_role='user'
            GROUP BY bucket ORDER BY bucket
        """)
        trend = [{"label": f"{int(r['bucket'])}h", "val": r['cnt']} for r in rows]
    elif period == "7d":
        # Günlük
        rows = await _fetch(f"""
            SELECT DATE(created_at) as bucket, COUNT(*) as cnt
            FROM agent_conversations WHERE {tf} AND message_role='user'
            GROUP BY bucket ORDER BY bucket
        """)
        trend = [{"label": str(r['bucket'])[5:], "val": r['cnt']} for r in rows]
    elif period == "30d":
        # Günlük
        rows = await _fetch(f"""
            SELECT DATE(created_at) as bucket, COUNT(*) as cnt
            FROM agent_conversations WHERE {tf} AND message_role='user'
            GROUP BY bucket ORDER BY bucket
        """)
        trend = [{"label": str(r['bucket'])[5:], "val": r['cnt']} for r in rows]
    else:  # all — haftalık
        rows = await _fetch(f"""
            SELECT DATE_TRUNC('week', created_at)::date as bucket, COUNT(*) as cnt
            FROM agent_conversations WHERE {tf} AND message_role='user'
            GROUP BY bucket ORDER BY bucket
        """)
        trend = [{"label": str(r['bucket'])[5:], "val": r['cnt']} for r in rows]

    return {
        "user": r['user_msg'] if r else 0,
        "bot": r['bot_msg'] if r else 0,
        "kisi": r['kisi'] if r else 0,
        "trend": trend,
    }


async def get_routing_by_period(period: str):
    """LLM routing dağılımı (filtreli)."""
    tf = time_filter(period)
    # Routing breakdown — agent_conversations'tan tahmin
    fast = await _fetchval(f"""
        SELECT COUNT(*) FROM agent_conversations
        WHERE {tf} AND message_role='assistant' AND tools_used::text LIKE '%fast%'
    """) or 0
    ollama = await _fetchval(f"""
        SELECT COUNT(*) FROM agent_conversations
        WHERE {tf} AND message_role='assistant' AND tools_used::text LIKE '%ollama%'
    """) or 0
    claude = await _fetchval(f"""
        SELECT COUNT(*) FROM agent_conversations
        WHERE {tf} AND message_role='assistant'
          AND tools_used::text NOT LIKE '%ollama%'
          AND tools_used::text NOT LIKE '%fast%'
    """) or 0

    total = fast + ollama + claude

    # Performance — routing_stats'tan
    perf = await _fetchone(f"""
        SELECT
            AVG(response_ms)::int as avg_ms,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY response_ms)::int as p50,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY response_ms)::int as p95,
            MAX(response_ms) as max_ms
        FROM routing_stats WHERE {tf}
    """)

    return {
        "fast": fast,
        "ollama": ollama,
        "claude": claude,
        "total": total,
        "fast_pct": round(fast / max(total, 1) * 100, 1),
        "ollama_pct": round(ollama / max(total, 1) * 100, 1),
        "claude_pct": round(claude / max(total, 1) * 100, 1),
        "perf": {
            "avg": perf['avg_ms'] if perf and perf['avg_ms'] else 0,
            "p50": perf['p50'] if perf and perf['p50'] else 0,
            "p95": perf['p95'] if perf and perf['p95'] else 0,
            "max": perf['max_ms'] if perf and perf['max_ms'] else 0,
        }
    }


async def get_cost_by_period(period: str):
    """Maliyet & token (filtreli)."""
    tf = time_filter(period)
    claude_calls = await _fetchval(f"""
        SELECT COUNT(*) FROM agent_conversations
        WHERE {tf} AND message_role='assistant'
          AND tools_used::text NOT LIKE '%ollama%' AND tools_used::text NOT LIKE '%fast%'
    """) or 0

    input_tokens = claude_calls * 2000
    output_tokens = claude_calls * 500

    cache_hit = 0.70
    eff_in_cost = (1 - cache_hit) * input_tokens * 3 / 1_000_000 + cache_hit * input_tokens * 0.30 / 1_000_000
    out_cost = output_tokens * 15 / 1_000_000
    total_usd = eff_in_cost + out_cost
    TL_RATE = 33.0

    return {
        "claude_calls": claude_calls,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "cost_usd": round(total_usd, 4),
        "cost_tl": round(total_usd * TL_RATE, 2),
    }


async def get_tools_by_period(period: str):
    """Tool kullanımı (filtreli, top 15)."""
    tf = time_filter(period)
    rows = await _fetch(f"""
        SELECT unnest(tools_used) as tool_name, COUNT(*) as cnt
        FROM agent_conversations
        WHERE {tf} AND message_role='assistant' AND array_length(tools_used, 1) > 0
        GROUP BY tool_name
        ORDER BY cnt DESC
        LIMIT 15
    """)
    return [{"tool": r['tool_name'], "cnt": r['cnt']} for r in rows]


async def get_users_by_period(period: str):
    """Kullanıcı istatistikleri (filtreli)."""
    tf = time_filter(period)

    # Aktif kullanıcı (filtreli)
    aktif = await _fetchval(f"""
        SELECT COUNT(DISTINCT phone) FROM agent_conversations
        WHERE {tf} AND message_role='user'
    """) or 0

    # Rol bazlı aktif
    rol_aktif = await _fetch(f"""
        SELECT COALESCE(a.role, 'unknown') as rol, COUNT(DISTINCT ac.phone) as cnt
        FROM agent_conversations ac
        LEFT JOIN acl_users a ON a.phone = ac.phone
        WHERE {tf.replace('created_at', 'ac.created_at')} AND ac.message_role='user'
        GROUP BY a.role
        ORDER BY cnt DESC
    """)

    # Top 10 aktif kullanıcı (filtreli)
    top = await _fetch(f"""
        SELECT ac.phone, a.role, a.full_name, COUNT(*) as msg
        FROM agent_conversations ac
        LEFT JOIN acl_users a ON a.phone = ac.phone
        WHERE {tf.replace('created_at', 'ac.created_at')} AND ac.message_role='user'
        GROUP BY ac.phone, a.role, a.full_name
        ORDER BY msg DESC
        LIMIT 10
    """)

    def mask(n):
        if not n: return "?"
        parts = n.split()
        return f"{parts[0][0]}. {parts[-1]}" if len(parts) > 1 else parts[0][0] + "."

    return {
        "aktif": aktif,
        "rol_dagilim": [{"rol": r['rol'], "cnt": r['cnt']} for r in rol_aktif],
        "top": [{
            "isim": mask(r['full_name']),
            "rol": r['role'] or "?",
            "msg": r['msg'],
        } for r in top]
    }


# ═══════════════════════════════════════════════════════════════════════
# ENGINEERING METRICS — geliştirme süreci
# ═══════════════════════════════════════════════════════════════════════

async def get_engineering():
    """Mühendislik metrikleri — kod, test, bridge versiyon, geliştirme hızı."""
    base = Path(__file__).parent

    # Aktif kod satırı
    py_files = list(base.glob("*.py"))
    py_lines = 0
    for f in py_files:
        if "_reserve" in str(f) or ".venv" in str(f) or "__pycache__" in str(f):
            continue
        try:
            py_lines += sum(1 for _ in open(f, encoding='utf-8', errors='ignore'))
        except Exception:
            pass

    # Aktif modül sayısı
    aktif_modul = len([f for f in py_files if "_reserve" not in str(f) and "__" not in f.name])

    # Test sayısı
    test_count = 0
    test_files = (base / "tests").glob("test_*.py") if (base / "tests").exists() else []
    for f in test_files:
        try:
            with open(f, encoding='utf-8') as fp:
                test_count += sum(1 for line in fp if line.strip().startswith('def test_') or line.strip().startswith('async def test_'))
        except Exception:
            pass

    # Bridge versiyon sayısı (log dosyaları)
    log_dir = base / "logs"
    bridge_versions = len(list(log_dir.glob("bridge_v*.log"))) if log_dir.exists() else 0
    archive_versions = len(list((log_dir / "archive_2026-04").glob("bridge_v*.log"))) if (log_dir / "archive_2026-04").exists() else 0

    # En son bridge versiyon
    latest_bridge = None
    if log_dir.exists():
        bridge_logs = sorted(log_dir.glob("bridge_v*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
        if bridge_logs:
            name = bridge_logs[0].stem  # bridge_v35
            latest_bridge = name.replace("bridge_", "")

    # Reserve klasörü (envanterleştirilmiş)
    reserve_count = 0
    reserve_dir = base / "_reserve"
    if reserve_dir.exists():
        reserve_count = len(list(reserve_dir.rglob("*.py")))

    # RAG kayıt
    try:
        rag_count = await _fetchval("SELECT COUNT(*) FROM rag_content") or 0
    except Exception:
        rag_count = 0

    # Geliştirme oturumu sayısı (KALDIGIM.md'den manuel)
    kaldigim = base.parent / "KALDIGIM.md"
    oturum_sayisi = 18  # default
    if kaldigim.exists():
        try:
            content = kaldigim.read_text(encoding='utf-8')
            import re
            matches = re.findall(r'Oturum (\d+)', content)
            if matches:
                oturum_sayisi = max(int(m) for m in matches)
        except Exception:
            pass

    return {
        "kod_satiri": py_lines,
        "aktif_modul": aktif_modul,
        "test_count": test_count,
        "bridge_aktif_versiyon": latest_bridge or "?",
        "bridge_toplam_restart": bridge_versions + archive_versions,
        "reserve_dosya": reserve_count,
        "rag_kayit": rag_count,
        "oturum_sayisi": oturum_sayisi,
    }


async def get_system_health():
    """Sistem altyapı sağlık."""
    base = Path(__file__).parent
    cache_file = base / ".analytics_cache.json"
    cache_age_min = 999
    if cache_file.exists():
        cache_age_min = (time.time() - cache_file.stat().st_mtime) / 60

    status_file = base / ".eyotek_status.json"
    eyotek_status = "unknown"
    eyotek_uptime = 0
    if status_file.exists():
        try:
            import json as _j
            data = _j.loads(status_file.read_text(encoding="utf-8"))
            eyotek_status = data.get("eyotek_session", "unknown")
            us = data.get("uptime_start")
            if us:
                eyotek_uptime = (time.time() - datetime.fromisoformat(us).timestamp()) / 3600
        except Exception:
            pass

    # Disk kullanımı
    log_size_mb = 0
    log_dir = base / "logs"
    if log_dir.exists():
        for f in log_dir.rglob("*"):
            if f.is_file():
                log_size_mb += f.stat().st_size
        log_size_mb = round(log_size_mb / 1024 / 1024, 1)

    # Bridge uptime
    bridge_uptime_h = 0
    if log_dir.exists():
        latest = sorted(log_dir.glob("bridge_v*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
        if latest:
            bridge_uptime_h = (time.time() - latest[0].stat().st_ctime) / 3600

    return {
        "eyotek_status": eyotek_status,
        "eyotek_uptime_h": round(eyotek_uptime, 1),
        "bridge_uptime_h": round(bridge_uptime_h, 1),
        "cache_yas_dk": round(cache_age_min, 1),
        "cache_saglikli": cache_age_min < 60,
        "log_disk_mb": log_size_mb,
        "db_pool": "healthy",
        "ollama_warm": True,
        "session_keeper": "active" if eyotek_status == "online" else "offline",
    }


async def get_security_signals(period: str):
    """Güvenlik sinyalleri (filtreli)."""
    tf = time_filter(period)

    hack = await _fetchval(f"""
        SELECT COUNT(*) FROM agent_conversations
        WHERE {tf} AND message_role='user'
          AND (content ILIKE '%unut%kural%' OR content ILIKE '%ignore%instruct%'
               OR content ILIKE '%jailbreak%' OR content ILIKE '%sistem prompt%'
               OR content ILIKE '%system prompt%' OR content ILIKE '%gizli mod%')
    """) or 0

    frust = await _fetchval(f"""
        SELECT COUNT(*) FROM agent_conversations
        WHERE {tf} AND message_role='user'
          AND (content ILIKE '%yanlis%' OR content ILIKE '%yanlış%'
               OR content ILIKE '%anlamadın%' OR content ILIKE '%uydurma%')
    """) or 0

    try:
        blocked = await _fetchval("SELECT COUNT(*) FROM blocked_numbers") or 0
    except Exception:
        blocked = 0

    # Bridge log'undan API hata sayısı (today)
    api_errors_today = 0
    log_file = Path(__file__).parent / "logs" / "bridge_2026-04-16.log"
    if not log_file.exists():
        # Fallback: en son bridge log
        log_dir = Path(__file__).parent / "logs"
        latest = sorted(log_dir.glob("bridge_v*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
        if latest:
            log_file = latest[0]
    if log_file.exists():
        try:
            with open(log_file, encoding='utf-8', errors='ignore') as f:
                content = f.read()
                api_errors_today = content.count("Agent hatasi") + content.count("Error code: 5")
        except Exception:
            pass

    return {
        "hack_deneme": hack,
        "frustration": frust,
        "blocked_numaralar": blocked,
        "api_hata_son_log": api_errors_today,
    }


async def get_activity_feed():
    """Son 15 olay."""
    rows = await _fetch("""
        SELECT ac.phone, ac.message_role, LEFT(ac.content, 60) as snippet,
               ac.tools_used, ac.created_at
        FROM agent_conversations ac
        WHERE ac.created_at >= NOW() - INTERVAL '2 hours'
          AND ac.message_role IN ('user','assistant')
        ORDER BY ac.created_at DESC
        LIMIT 15
    """)
    events = []
    for r in rows:
        phone_mask = f"***{r['phone'][-4:]}" if r['phone'] else "?"
        kaynak = "?"
        if r['tools_used']:
            tu = str(r['tools_used'])
            if 'fast' in tu: kaynak = "⚡fast"
            elif 'ollama' in tu: kaynak = "🔬ollama"
            elif 'execute_eyotek' in tu: kaynak = "✏️etüt"
            elif 'get_ayt' in tu: kaynak = "📊AYT"
            elif 'search_curriculum' in tu: kaynak = "📚RAG"
            elif 'send_exam_image' in tu: kaynak = "🖼️görsel"
            else: kaynak = "🧠claude"
        events.append({
            "tarih": r['created_at'].strftime("%H:%M:%S"),
            "kim": phone_mask,
            "rol": "👤" if r['message_role']=='user' else "🤖",
            "kaynak": kaynak,
            "snippet": (r['snippet'] or "").replace("\n", " ")[:50],
        })
    return events


# ═══════════════════════════════════════════════════════════════════════
# Ana fonksiyon
# ═══════════════════════════════════════════════════════════════════════

async def get_dashboard_data(period: str = "today") -> dict:
    """Tum metrikleri paralel topla. period: today|7d|30d|all"""
    if period not in ("today", "7d", "30d", "90d", "all"):
        period = "today"

    (lifetime, messages, routing, cost, tools, users,
     engineering, health, security, activity) = await asyncio.gather(
        get_lifetime(),
        get_messages_by_period(period),
        get_routing_by_period(period),
        get_cost_by_period(period),
        get_tools_by_period(period),
        get_users_by_period(period),
        get_engineering(),
        get_system_health(),
        get_security_signals(period),
        get_activity_feed(),
        return_exceptions=True
    )

    def safe(x, default=None):
        if isinstance(x, Exception):
            logger.warning(f"Dashboard metrik hatasi: {x}")
            return default
        return x

    return {
        "ts": datetime.now().isoformat(),
        "period": period,
        "period_label": period_label(period),
        "lifetime": safe(lifetime, {}),
        "messages": safe(messages, {}),
        "routing": safe(routing, {}),
        "cost": safe(cost, {}),
        "tools": safe(tools, []),
        "users": safe(users, {}),
        "engineering": safe(engineering, {}),
        "health": safe(health, {}),
        "security": safe(security, {}),
        "activity": safe(activity, []),
    }


if __name__ == "__main__":
    import json
    import sys
    period = sys.argv[1] if len(sys.argv) > 1 else "today"
    data = asyncio.run(get_dashboard_data(period))
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
