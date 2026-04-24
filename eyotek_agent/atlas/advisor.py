"""
ATLAS Advisor — observation'ları okur, kural-tabanlı suggestion'a dönüştürür.

v0.1: Kural-tabanlı (Claude API çağırmadan, sıfır maliyet)
v0.2 (gelecek): Claude ile rationale + impact zenginleştirme

Çalıştırma:
    python -m atlas advise              # son 24 saat observation'larından öneri üret
    python -m atlas advise --hours 168  # son 7 gün
"""
import asyncio
import asyncpg  # type hint icin
import os
import sys
import io
import json
from typing import List, Dict, Any

if os.name == 'nt':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from dotenv import load_dotenv
load_dotenv()

import sys as _sys
from pathlib import Path as _P
_parent = str(_P(__file__).resolve().parent.parent)
if _parent not in _sys.path:
    _sys.path.insert(0, _parent)
from db_pool import get_pool as _get_pool


# ─────────────────────────────────────────────────────────────────────────────
# RULE-BASED ADVISORS — her observation kategorisi için suggestion üretir
# ─────────────────────────────────────────────────────────────────────────────

def advise_frustration(obs: dict) -> Dict[str, Any]:
    ctx = json.loads(obs['context_jsonb']) if obs.get('context_jsonb') else {}
    samples = ctx.get('samples', [])
    samples_str = '\n'.join(f"  • {s}" for s in samples[:3])
    role = obs.get('affected_role', '?')
    phone_tail = (obs.get('affected_phone') or '????')[-4:]
    cnt = int(obs['metric_value'])
    return {
        "category": "frustration",
        "severity": obs['severity'],
        "title": f"{role.title()} kullanıcı (...{phone_tail}) frustrated — {cnt} negatif sinyal",
        "rationale": (
            f"Bu {role} son zaman diliminde {cnt} kez 'yanlış/anlamadın/hata/saçma' "
            f"tarzında bir tepki verdi. Örnekler:\n{samples_str}\n\n"
            f"Bot bu kullanıcıya ya tutarsız cevap veriyor ya da niyet anlama hatası yapıyor."
        ),
        "estimated_impact": (
            "Kısa vade: kullanıcı memnuniyeti. "
            "Uzun vade: bu pattern'lerden öğrenip handler eklenebilir."
        ),
        "suggested_change": (
            "1. agent_conversations'tan bu kullanıcının son 20 mesajını gözden geçir.\n"
            "2. Tekrar eden hataları tespit et.\n"
            "3. Eğer bir pattern varsa fast_responses.py'a handler ekle.\n"
            "4. Kullanıcıya 'dün sana yardım edememiştim, şimdi daha iyi bilgim var' tarzı telafi mesajı (B7 önerisi)."
        ),
        "target_files": ["fast_responses.py", "fermat_core_agent.py"],
    }


def advise_latency(obs: dict) -> Dict[str, Any]:
    ctx = json.loads(obs['context_jsonb']) if obs.get('context_jsonb') else {}
    src = ctx.get('source', '?')
    avg = ctx.get('avg_ms', 0)
    p95 = ctx.get('p95_ms', 0)
    cnt = ctx.get('count_over_5s', 0)
    return {
        "category": "latency",
        "severity": obs['severity'],
        "title": f"{src} latency yüksek — p95 {p95}ms",
        "rationale": (
            f"Son 24h'te {src} kaynağında {cnt} cevap >5s. "
            f"Ortalama {avg}ms, p95 {p95}ms. "
            f"Bu kullanıcı için 'donmuş gibi' hissi yaratıyor."
        ),
        "estimated_impact": (
            "%20-30 yanıt süresi iyileştirme potansiyeli (paralel tool, prompt küçültme, cache)."
        ),
        "suggested_change": (
            "1. Yavaş çağrıların hangi tool'larda olduğunu izle (tools_used kolonu).\n"
            "2. build_study_plan_context, get_student_analytics gibi ağır tool'ları cache'le.\n"
            "3. Claude için max_tokens'ı sorgu tipine göre dinamik ayarla.\n"
            "4. Ollama warm-up boot'ta (zaten var) — connection pooling kontrol et."
        ),
        "target_files": ["fermat_core_agent.py", "llm_router.py"],
    }


def advise_pattern_miss(obs: dict) -> Dict[str, Any]:
    ctx = json.loads(obs['context_jsonb']) if obs.get('context_jsonb') else {}
    msg = ctx.get('message', '?')
    cnt = ctx.get('occurrence', 0)
    avg_ms = ctx.get('avg_response_ms', 0)
    saving_per_week = (avg_ms - 50) * cnt / 1000  # saniye
    return {
        "category": "pattern_miss",
        "severity": obs['severity'],
        "title": f"'{msg}' fast_response'a alınabilir ({cnt}x agent'a düştü)",
        "rationale": (
            f"'{msg}' mesajı son 24h'te {cnt} kez agent'a (claude/ollama) düştü. "
            f"Ortalama {avg_ms}ms aldı. fast_response handler ile <50ms olur. "
            f"Tahmini haftalık tasarruf: ~{saving_per_week:.0f}sn + token maliyeti."
        ),
        "estimated_impact": f"~{saving_per_week:.0f}sn/hafta hız + token tasarrufu",
        "suggested_change": (
            f"fast_responses.py'a yeni pattern ekle:\n"
            f"  if re.search(r'\\b{msg}\\b', msg_lower):\n"
            f"      return '<uygun cevap>'\n\n"
            f"Cevap içeriği için bu kullanıcının önceki bot cevaplarına bak — kalıbı çıkar."
        ),
        "target_files": ["fast_responses.py"],
    }


def advise_sentiment(obs: dict) -> Dict[str, Any]:
    ctx = json.loads(obs['context_jsonb']) if obs.get('context_jsonb') else {}
    name = ctx.get('full_name', '?')
    cnt = ctx.get('signal_count', 0)
    types = ctx.get('sentiment_types', [])
    is_crisis = 'crisis' in types
    return {
        "category": "sentiment",
        "severity": "critical" if is_crisis else "warning",
        "title": f"{name} — duygu sinyali alarmı ({cnt} negatif {'+ KRİZ' if is_crisis else ''})",
        "rationale": (
            f"Öğrenci {name} son 24h'te {cnt} kez negatif sinyal verdi: {', '.join(types)}. "
            + ("Kriz işareti var — rehber öğretmene anında bildirim önerilir." if is_crisis else "Rehber öğretmene haftalık özet gönderilebilir.")
        ),
        "estimated_impact": "Erken müdahale → öğrenci motivasyonu + güvenlik",
        "suggested_change": (
            "1. alert_system.py'da bu öğrenci için rehber bildirimi tetikle.\n"
            "2. ALERTS_ACTIVE=True olduğunda bu otomatik olur (B1 önerisi).\n"
            "3. Geçici olarak: Neo'ya manuel WP bildirim gönder."
        ),
        "target_files": ["alert_system.py", "sentiment_tracker.py"],
    }


def advise_data_quality(obs: dict) -> Dict[str, Any]:
    ctx = json.loads(obs['context_jsonb']) if obs.get('context_jsonb') else {}
    samples = ctx.get('samples', [])
    samples_str = '\n'.join(f"  • {s}" for s in samples[:3])
    cnt = int(obs['metric_value'])
    return {
        "category": "data_quality",
        "severity": obs['severity'],
        "title": f"{cnt} admin notu DB'ye yazılmadı (lost feedback)",
        "rationale": (
            f"Son zaman diliminde Neo'nun {cnt} 'not et' komutu user_feedback'e yazılmamış. "
            f"Örnekler:\n{samples_str}\n\n"
            f"Olası sebep: Claude path'inden gelen 'not et' fast_response'u atlamış olabilir, "
            f"veya zaman damgası tam eşleşmediği için detector kaçırıyor olabilir."
        ),
        "estimated_impact": "Neo'nun talimatlarının hiçbiri kaybolmamalı — kritik veri",
        "suggested_change": (
            "1. backfill_admin_notes.py'ı tekrar çalıştır (idempotent).\n"
            "2. fermat_core_agent.py'a Claude için de 'not et' algılama ekle (system prompt + auto INSERT).\n"
            "3. Detector'da zaman aralığını 30sn'ye genişlet (mevcut: 10sn)."
        ),
        "target_files": ["fast_responses.py", "fermat_core_agent.py", "backfill_admin_notes.py"],
    }


CATEGORY_ADVISORS = {
    "frustration": advise_frustration,
    "latency": advise_latency,
    "pattern_miss": advise_pattern_miss,
    "sentiment": advise_sentiment,
    "data_quality": advise_data_quality,
}


# ─────────────────────────────────────────────────────────────────────────────
# RUNNER
# ─────────────────────────────────────────────────────────────────────────────

async def run_advise(hours: int = 24) -> int:
    """Son N saatteki observation'ları suggestion'a dönüştür. Yeni eklenen sayı döndürür."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        # Henüz suggestion'a dönüşmemiş observation'ları çek
        obs_rows = await conn.fetch("""
            SELECT id, category, severity, metric_name, metric_value, metric_unit,
                   affected_phone, affected_role, context_jsonb::text as context_jsonb, rationale, created_at
            FROM atlas_observations
            WHERE created_at > NOW() - ($1 || ' hours')::interval
              AND id NOT IN (
                SELECT UNNEST(observation_ids) FROM atlas_suggestions WHERE observation_ids IS NOT NULL
              )
            ORDER BY severity DESC, created_at DESC
        """, str(hours))

        if not obs_rows:
            print("Yeni observation yok (hepsi zaten suggestion'a bağlanmış).")
            return 0

        # Kategori bazında grupla
        by_cat: Dict[str, List[asyncpg.Record]] = {}
        for r in obs_rows:
            by_cat.setdefault(r['category'], []).append(r)

        inserted = 0
        for cat, lst in by_cat.items():
            advisor = CATEGORY_ADVISORS.get(cat)
            if not advisor:
                continue
            for o in lst:
                obs_dict = dict(o)
                try:
                    sug = advisor(obs_dict)
                except Exception as e:
                    print(f"  ⚠ advisor hatası ({cat}): {e}")
                    continue

                new_id = await conn.fetchval(
                    """
                    INSERT INTO atlas_suggestions (
                      observation_ids, category, severity, title, rationale,
                      estimated_impact, suggested_change, target_files, status
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'yeni')
                    RETURNING id
                    """,
                    [o['id']], sug['category'], sug['severity'], sug['title'],
                    sug['rationale'], sug.get('estimated_impact', ''),
                    sug.get('suggested_change', ''), sug.get('target_files', []),
                )
                inserted += 1

        # Konsol özeti
        print(f"\n{'='*70}")
        print(f"ATLAS ADVISOR — {inserted} yeni öneri üretildi")
        print(f"{'='*70}")
        sugs = await conn.fetch("""
            SELECT id, severity, title FROM atlas_suggestions
            WHERE status='yeni' ORDER BY
              CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
              created_at DESC
            LIMIT 15
        """)
        for s in sugs:
            sev_icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(s['severity'], "⚪")
            print(f"  {sev_icon} #{s['id']} {s['title']}")
        return inserted


async def main():
    hours = 24
    if len(sys.argv) > 1:
        for i, a in enumerate(sys.argv):
            if a == '--hours' and i + 1 < len(sys.argv):
                try:
                    hours = int(sys.argv[i + 1])
                except ValueError:
                    pass
    await run_advise(hours=hours)


if __name__ == '__main__':
    asyncio.run(main())
