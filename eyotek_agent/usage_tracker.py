"""
Usage Tracker — Kullanici etkilesim loglari ve gunluk istatistikler.

Her mesajda: kim, ne zaman, hangi kaynaktan yanitlandi, kac ms, kac token.
Gunluk ozet: toplam mesaj, benzersiz kullanici, rol dagilimi, maliyet.
"""
import asyncio
import time
from datetime import datetime, date
from typing import Optional
from db_pool import get_pool as _get_pool


async def log_event(
    phone: str,
    role: str = "",
    full_name: str = "",
    event_type: str = "message",  # message, blocked, unknown, flood, error
    response_source: str = "",     # fast_response, ollama, claude, cache
    response_ms: int = 0,
    token_input: int = 0,
    token_output: int = 0,
):
    """Tek bir etkilesimi logla."""
    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO usage_log (phone, role, full_name, event_type,
                    response_source, response_ms, token_input, token_output)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """, phone, role, full_name, event_type,
                response_source, response_ms, token_input, token_output)
    except Exception:
        pass  # Log hatasi sistemi durdurmasin


async def update_daily_stats():
    """Gunluk istatistikleri hesapla ve kaydet."""
    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            today = date.today()
            today_str = today.isoformat()

            stats = await conn.fetchrow(f"""
                SELECT
                    COUNT(*) as total_messages,
                    COUNT(DISTINCT phone) as unique_users,
                    COUNT(*) FILTER (WHERE role = 'ogrenci') as ogrenci_messages,
                    COUNT(*) FILTER (WHERE role = 'ogretmen') as ogretmen_messages,
                    COUNT(*) FILTER (WHERE role IN ('admin','mudur')) as admin_messages,
                    COUNT(*) FILTER (WHERE response_source = 'fast_response') as fast_responses,
                    COUNT(*) FILTER (WHERE response_source = 'ollama') as ollama_responses,
                    COUNT(*) FILTER (WHERE response_source = 'claude') as claude_responses,
                    COALESCE(SUM(token_input), 0) as total_input_tokens,
                    COALESCE(SUM(token_output), 0) as total_output_tokens,
                    COALESCE(AVG(response_ms) FILTER (WHERE response_ms > 0), 0)::int as avg_response_ms,
                    COUNT(*) FILTER (WHERE event_type = 'blocked') as blocked_attempts,
                    COUNT(*) FILTER (WHERE event_type = 'unknown') as unknown_attempts
                FROM usage_log
                WHERE created_at::date = $1 AND event_type = 'message'
            """, today)

            await conn.execute("""
                INSERT INTO daily_stats (stat_date, total_messages, unique_users,
                    ogrenci_messages, ogretmen_messages, admin_messages,
                    fast_responses, ollama_responses, claude_responses,
                    total_input_tokens, total_output_tokens, avg_response_ms,
                    blocked_attempts, unknown_attempts, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, NOW())
                ON CONFLICT (stat_date) DO UPDATE SET
                    total_messages = EXCLUDED.total_messages,
                    unique_users = EXCLUDED.unique_users,
                    ogrenci_messages = EXCLUDED.ogrenci_messages,
                    ogretmen_messages = EXCLUDED.ogretmen_messages,
                    admin_messages = EXCLUDED.admin_messages,
                    fast_responses = EXCLUDED.fast_responses,
                    ollama_responses = EXCLUDED.ollama_responses,
                    claude_responses = EXCLUDED.claude_responses,
                    total_input_tokens = EXCLUDED.total_input_tokens,
                    total_output_tokens = EXCLUDED.total_output_tokens,
                    avg_response_ms = EXCLUDED.avg_response_ms,
                    blocked_attempts = EXCLUDED.blocked_attempts,
                    unknown_attempts = EXCLUDED.unknown_attempts,
                    updated_at = NOW()
            """, today, stats['total_messages'], stats['unique_users'],
                stats['ogrenci_messages'], stats['ogretmen_messages'], stats['admin_messages'],
                stats['fast_responses'], stats['ollama_responses'], stats['claude_responses'],
                stats['total_input_tokens'], stats['total_output_tokens'], stats['avg_response_ms'],
                stats['blocked_attempts'], stats['unknown_attempts'])
    except Exception:
        pass


async def get_today_summary() -> str:
    """Bugunku ozet — admin dashboard icin."""
    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            today = date.today()

            s = await conn.fetchrow("""
                SELECT COUNT(*) as msg,
                    COUNT(DISTINCT phone) as users,
                    COUNT(*) FILTER (WHERE role='ogrenci') as ogrenci,
                    COUNT(*) FILTER (WHERE role='ogretmen') as ogretmen,
                    COUNT(*) FILTER (WHERE role IN ('admin','mudur')) as yonetim,
                    COUNT(*) FILTER (WHERE response_source='fast_response') as fast,
                    COUNT(*) FILTER (WHERE response_source='ollama') as ollama,
                    COUNT(*) FILTER (WHERE response_source='claude') as claude,
                    COALESCE(SUM(token_input),0) as t_in,
                    COALESCE(SUM(token_output),0) as t_out,
                    COALESCE(AVG(response_ms) FILTER (WHERE response_ms>0),0)::int as avg_ms,
                    COUNT(*) FILTER (WHERE event_type='blocked') as blocked,
                    COUNT(*) FILTER (WHERE event_type='unknown') as unknown
                FROM usage_log WHERE created_at::date = $1
            """, today)

            # Aktif kullanicilar (son 1 saat)
            active = await conn.fetch("""
                SELECT phone, full_name, role, COUNT(*) as msg_count,
                    MAX(created_at) as son_mesaj
                FROM usage_log
                WHERE created_at >= NOW() - INTERVAL '1 hour' AND event_type='message'
                GROUP BY phone, full_name, role
                ORDER BY son_mesaj DESC LIMIT 10
            """)

            lines = [
                f"*Gunluk Rapor — {today.strftime('%d.%m.%Y')}*\n",
                f"Toplam mesaj: *{s['msg']}*",
                f"Benzersiz kullanici: *{s['users']}*",
                f"  Ogrenci: {s['ogrenci']} | Ogretmen: {s['ogretmen']} | Yonetim: {s['yonetim']}",
                f"\nYanit kaynaklari:",
                f"  Hizli: {s['fast']} | Ollama: {s['ollama']} | Claude: {s['claude']}",
                f"  Ort. yanit suresi: {s['avg_ms']}ms",
                f"\nToken kullanimi:",
                f"  Giris: {s['t_in']:,} | Cikis: {s['t_out']:,}",
                f"\nGuvenlik:",
                f"  Engellenen: {s['blocked']} | Kayitsiz: {s['unknown']}",
            ]

            if active:
                lines.append(f"\n*Son 1 saat aktif ({len(active)} kisi):*")
                for a in active:
                    lines.append(f"  {a['full_name'] or a['phone'][:8]} ({a['role']}) — {a['msg_count']} mesaj")

            return "\n".join(lines)
    except Exception as e:
        return f"Rapor hatasi: {e}"


async def get_weekly_trend() -> str:
    """Haftalik trend — admin icin."""
    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT stat_date, total_messages, unique_users, avg_response_ms,
                    fast_responses, claude_responses, total_input_tokens
                FROM daily_stats
                ORDER BY stat_date DESC LIMIT 7
            """)
            if not rows:
                return "Henuz gunluk istatistik yok."
            lines = ["*Haftalik Trend:*\n",
                     "Tarih       | Mesaj | Kullanici | Ort.ms | Hizli | Claude | Token"]
            for r in rows:
                lines.append(
                    f"{r['stat_date']} | {r['total_messages']:5d} | {r['unique_users']:9d} | "
                    f"{r['avg_response_ms']:6d} | {r['fast_responses']:5d} | {r['claude_responses']:6d} | "
                    f"{r['total_input_tokens']:,}")
            return "\n".join(lines)
    except Exception as e:
        return f"Trend hatasi: {e}"
