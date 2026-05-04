"""
ATLAS Observer — sistem log'larını tarar, anomalileri atlas_observations tablosuna yazar.

Çalıştırma:
    python -m atlas observe              # son 24 saat tarama
    python -m atlas observe --hours 168  # son 7 gün

Çıktı: konsol özeti + DB kayıt
"""
import asyncio
import os
import sys
import io
import uuid
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any

if os.name == 'nt':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from dotenv import load_dotenv
load_dotenv()

# db_pool merkezi pool — DSN tek yerden
import sys as _sys
from pathlib import Path as _P
_parent = str(_P(__file__).resolve().parent.parent)
if _parent not in _sys.path:
    _sys.path.insert(0, _parent)
from db_pool import get_pool as _get_pool, DB_URL


# ─────────────────────────────────────────────────────────────────────────────
# DETECTOR'lar — her biri (List[Observation]) döner
# Observation = {"category", "severity", "metric_name", "metric_value", "metric_unit",
#                "affected_phone", "affected_role", "context_jsonb", "rationale"}
# ─────────────────────────────────────────────────────────────────────────────

async def detect_frustration_spike(conn, hours: int) -> List[Dict[str, Any]]:
    """Bir kullanıcı son N saatte 3+ kez 'yanlış/anlamadın/hata' demişse uyar."""
    obs = []
    rows = await conn.fetch("""
        SELECT phone, role, COUNT(*) as cnt,
               array_agg(LEFT(content, 60) ORDER BY created_at DESC) FILTER (WHERE content IS NOT NULL) as samples
        FROM agent_conversations
        WHERE message_role='user'
          AND created_at > NOW() - ($1 || ' hours')::interval
          AND (
            LOWER(content) ~ '(yanl[ıi]ş|yanlis|anlamad[ıi]n|hata|saçma|sacma|kötü|kotu|berbat|aptal|salak)'
          )
        GROUP BY phone, role
        HAVING COUNT(*) >= 3
        ORDER BY cnt DESC
    """, str(hours))
    for r in rows:
        sev = "critical" if r['cnt'] >= 5 else "warning"
        obs.append({
            "category": "frustration",
            "severity": sev,
            "metric_name": f"frustration_signals_{hours}h",
            "metric_value": float(r['cnt']),
            "metric_unit": "count",
            "affected_phone": r['phone'],
            "affected_role": r['role'],
            "context_jsonb": json.dumps({"samples": list(r['samples'] or [])[:5]}),
            "rationale": f"Son {hours}h içinde {r['cnt']} negatif sinyal — kullanıcı {r['role']} ({r['phone'][-4:]})",
        })
    return obs


async def detect_latency_anomalies(conn, hours: int) -> List[Dict[str, Any]]:
    """5 saniyeden uzun süren cevap rotalarını tespit et."""
    obs = []
    rows = await conn.fetch("""
        SELECT response_source,
               COUNT(*) as cnt,
               AVG(response_ms) as avg_ms,
               MAX(response_ms) as max_ms,
               percentile_cont(0.95) WITHIN GROUP (ORDER BY response_ms) as p95
        FROM routing_stats
        WHERE created_at > NOW() - ($1 || ' hours')::interval
          AND response_ms > 5000
        GROUP BY response_source
        HAVING COUNT(*) >= 3
    """, str(hours))
    for r in rows:
        avg = float(r['avg_ms'] or 0)
        sev = "critical" if avg > 20000 else "warning"
        obs.append({
            "category": "latency",
            "severity": sev,
            "metric_name": f"slow_responses_{r['response_source']}",
            "metric_value": avg,
            "metric_unit": "ms",
            "affected_phone": None,
            "affected_role": None,
            "context_jsonb": json.dumps({
                "source": r['response_source'],
                "count_over_5s": r['cnt'],
                "avg_ms": int(avg),
                "max_ms": int(r['max_ms'] or 0),
                "p95_ms": int(r['p95'] or 0),
            }),
            "rationale": f"{r['response_source']} kaynağında {r['cnt']} cevap >5s (avg {int(avg)}ms, p95 {int(r['p95'] or 0)}ms)",
        })
    return obs


def _check_pattern_in_fast_responses(message: str) -> bool:
    """fast_responses.py'da bu mesaj kalıbı için pattern var mı?

    25.40z3-ATLAS FIX: Atlas önceden "web kodu fast_response'a alınabilir" önerdi
    AMA pattern zaten vardı (line 1672) - tetiklenmiyordu farklı sebepten.
    Bu kontrol artık Atlas'ı doğru yönlendirir: pattern var ama tetiklenmiyor →
    farklı problem (auth gate, route override, vb.)
    """
    try:
        import re
        from pathlib import Path
        fr_path = Path(__file__).resolve().parent.parent / "fast_responses.py"
        if not fr_path.exists():
            return False
        content = fr_path.read_text(encoding='utf-8', errors='replace').lower()
        # Mesajın ilk kelimesi pattern'da geçiyor mu?
        first_word = re.split(r'\s+', message.strip().lower())[0] if message else ''
        if not first_word or len(first_word) < 2:
            return False
        # Hem regex pattern hem keyword arama
        return (first_word in content or
                f"'{first_word}'" in content or
                f'"{first_word}"' in content)
    except Exception:
        return False


async def detect_pattern_miss(conn, hours: int) -> List[Dict[str, Any]]:
    """Claude/Ollama'ya giden basit mesaj kalıpları — fast_response'a alınabilir.

    25.40z3-ATLAS FIX: Önce fast_responses.py'da pattern var mı KOD KONTROLÜ yap.
    - Pattern YOK → klasik "fast_response'a alınabilir" önerisi (info/warning)
    - Pattern VAR → "tetiklenmiyor, route/auth bug ihtimali" (warning, farklı kategori)
    """
    obs = []
    rows = await conn.fetch("""
        SELECT LOWER(TRIM(message)) as norm_msg,
               COUNT(*) as cnt,
               array_agg(DISTINCT phone) as phones,
               AVG(response_ms) as avg_ms
        FROM routing_stats
        WHERE created_at > NOW() - ($1 || ' hours')::interval
          AND response_source IN ('claude', 'ollama')
          AND LENGTH(TRIM(message)) BETWEEN 4 AND 30
          AND message NOT LIKE '%not et%'
        GROUP BY LOWER(TRIM(message))
        HAVING COUNT(*) >= 3
        ORDER BY cnt DESC
        LIMIT 10
    """, str(hours))
    for r in rows:
        msg = r['norm_msg'] or ''
        pattern_exists = _check_pattern_in_fast_responses(msg)

        if pattern_exists:
            # Pattern VAR ama tetiklenmiyor — farklı bir problem
            obs.append({
                "category": "routing_bug",  # pattern_miss değil — routing problemi
                "severity": "warning",
                "metric_name": "pattern_exists_but_misses",
                "metric_value": float(r['cnt']),
                "metric_unit": "count",
                "affected_phone": None,
                "affected_role": None,
                "context_jsonb": json.dumps({
                    "message": msg,
                    "occurrence": r['cnt'],
                    "unique_users": len(r['phones'] or []),
                    "avg_response_ms": int(float(r['avg_ms'] or 0)),
                    "fast_pattern_exists": True,
                }),
                "rationale": f"'{msg}' mesajı {r['cnt']}x agent'a düştü AMA fast_responses.py'da pattern ZATEN VAR — auth gate / route override / öncelik bug ihtimali. Pattern yazma değil, tetikleme problemini ara.",
            })
        else:
            # Klasik öneri: pattern yok, ekleme adayı
            sev = "warning" if r['cnt'] >= 5 else "info"
            obs.append({
                "category": "pattern_miss",
                "severity": sev,
                "metric_name": "fast_response_candidate",
                "metric_value": float(r['cnt']),
                "metric_unit": "count",
                "affected_phone": None,
                "affected_role": None,
                "context_jsonb": json.dumps({
                    "message": msg,
                    "occurrence": r['cnt'],
                    "unique_users": len(r['phones'] or []),
                    "avg_response_ms": int(float(r['avg_ms'] or 0)),
                    "fast_pattern_exists": False,
                }),
                "rationale": f"'{msg}' mesajı {r['cnt']}x agent'a düştü ({int(float(r['avg_ms'] or 0))}ms ort.) — fast_response'a alınabilir",
            })
    return obs


async def detect_negative_sentiment_cluster(conn, hours: int) -> List[Dict[str, Any]]:
    """Bir öğrencide art arda negatif duygu sinyali — rehbere bildirim adayı."""
    obs = []
    try:
        rows = await conn.fetch("""
            SELECT phone, full_name, COUNT(*) as cnt,
                   array_agg(DISTINCT sentiment) as types
            FROM student_insights
            WHERE created_at > NOW() - ($1 || ' hours')::interval
              AND sentiment IN ('crisis', 'stressed', 'negative', 'angry')
            GROUP BY phone, full_name
            HAVING COUNT(*) >= 3
            ORDER BY cnt DESC
        """, str(hours))
    except Exception:
        # student_insights tablosu yoksa veya sentiment kolonu yoksa atla
        return obs
    for r in rows:
        types_list = list(r['types'] or [])
        sev = "critical" if 'crisis' in types_list else "warning"
        obs.append({
            "category": "sentiment",
            "severity": sev,
            "metric_name": f"negative_sentiment_{hours}h",
            "metric_value": float(r['cnt']),
            "metric_unit": "count",
            "affected_phone": r['phone'],
            "affected_role": "ogrenci",
            "context_jsonb": json.dumps({
                "full_name": r['full_name'],
                "signal_count": r['cnt'],
                "sentiment_types": types_list,
            }),
            "rationale": f"{r['full_name']} son {hours}h: {r['cnt']} negatif sinyal ({', '.join(types_list)})",
        })
    return obs


async def detect_kayip_admin_notlari(conn, hours: int) -> List[Dict[str, Any]]:
    """Neo'nun 'not et' dediği ama user_feedback'te kaydı olmayan mesajlar."""
    obs = []
    rows = await conn.fetch("""
        SELECT ac.created_at, ac.content
        FROM agent_conversations ac
        WHERE ac.phone='905051256802'
          AND ac.message_role='user'
          AND ac.created_at > NOW() - ($1 || ' hours')::interval
          AND LOWER(ac.content) LIKE '%not et%'
          AND NOT EXISTS (
            SELECT 1 FROM user_feedback uf
            WHERE uf.phone='905051256802'
              AND uf.created_at BETWEEN ac.created_at - INTERVAL '10 seconds' AND ac.created_at + INTERVAL '10 seconds'
              AND uf.feedback = ac.content
          )
        ORDER BY ac.created_at DESC
    """, str(hours))
    if rows:
        obs.append({
            "category": "data_quality",
            "severity": "warning",
            "metric_name": "lost_admin_notes",
            "metric_value": float(len(rows)),
            "metric_unit": "count",
            "affected_phone": "905051256802",
            "affected_role": "admin",
            "context_jsonb": json.dumps({
                "samples": [r['content'][:80] for r in rows[:5]],
                "first_lost_at": rows[-1]['created_at'].isoformat(),
                "last_lost_at": rows[0]['created_at'].isoformat(),
            }),
            "rationale": f"Son {hours}h: Neo'nun {len(rows)} 'not et' komutu user_feedback'e yazılmamış — backfill veya bug fix gerekli",
        })
    return obs


# ─────────────────────────────────────────────────────────────────────────────
# RUNNER
# ─────────────────────────────────────────────────────────────────────────────

async def run_observation_scan(hours: int = 24) -> str:
    """Tüm detector'ları çalıştır, observation'ları DB'ye yaz, scan_run_id döndür."""
    scan_run_id = str(uuid.uuid4())[:8]
    pool = await _get_pool()
    async with pool.acquire() as conn:
        all_obs: List[Dict[str, Any]] = []
        for detector in (
            detect_frustration_spike,
            detect_latency_anomalies,
            detect_pattern_miss,
            detect_negative_sentiment_cluster,
            detect_kayip_admin_notlari,
        ):
            try:
                results = await detector(conn, hours)
                all_obs.extend(results)
            except Exception as e:
                print(f"  ⚠ {detector.__name__} HATA: {e}")

        # Toplu insert
        for o in all_obs:
            await conn.execute(
                """
                INSERT INTO atlas_observations (
                  scan_run_id, category, severity, metric_name, metric_value,
                  metric_unit, affected_phone, affected_role, context_jsonb, rationale
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10)
                """,
                scan_run_id, o['category'], o['severity'], o['metric_name'],
                o['metric_value'], o['metric_unit'], o.get('affected_phone'),
                o.get('affected_role'), o['context_jsonb'], o['rationale'],
            )

        # Konsol özeti
        print(f"\n{'='*70}")
        print(f"ATLAS OBSERVER — Scan #{scan_run_id} ({hours}h kapsam)")
        print(f"{'='*70}")
        if not all_obs:
            print("Hiç anomali tespit edilmedi. Sistem normal.")
        else:
            by_cat: Dict[str, list] = {}
            for o in all_obs:
                by_cat.setdefault(o['category'], []).append(o)
            for cat, lst in by_cat.items():
                print(f"\n[{cat.upper()}] {len(lst)} sinyal:")
                for o in lst[:5]:
                    sev_icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(o['severity'], "⚪")
                    print(f"  {sev_icon} {o['rationale']}")
        print(f"\n{len(all_obs)} observation atlas_observations'a yazıldı.")
        return scan_run_id


async def main():
    hours = 24
    if len(sys.argv) > 1:
        for i, a in enumerate(sys.argv):
            if a == '--hours' and i + 1 < len(sys.argv):
                try:
                    hours = int(sys.argv[i + 1])
                except ValueError:
                    pass
    await run_observation_scan(hours=hours)


if __name__ == '__main__':
    asyncio.run(main())
