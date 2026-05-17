"""
ATLAS Daily Category Rotation — Oturum 25.46+ (Neo 18 May)
============================================================

Atlas-2 her gece 02:00'de SADECE frustration analizi yapıyordu →
suggestion havuzu monoton, çoğu aynı pattern'i tekrarlıyor.

Bu modül 7 farklı teknik kategoriyi rotasyona alır. Her gün BAŞKA bir
boyutta inceleme:

  Pazartesi → frustration_analizi      (mevcut, kullanıcı şikayetleri)
  Salı       → token_efficiency        (system_prompts.py duplikasyon/uzunluk)
  Çarşamba   → routing_balance         (Fast/Cerebras/Claude oran sağlığı)
  Perşembe   → hallucination_audit     (Neo 17 May vakası: sezon/ilk kez)
  Cuma       → dead_code               (kullanılmayan fonksiyon + obsolete import)
  Cumartesi  → db_health               (yavaş sorgu, eski sync, eksik index)
  Pazar      → response_quality_drift  (D/F response %, retry oranı)

Her kategori için özel detector ve LLM prompt template var.

Neo direktif (18 May): "Boş öneri yerine periyotlarla teknik kategorisel
öneriler. Boşu boşuna kodu uzattırmaya gerek yok. Self-awareness."
"""
from __future__ import annotations
import re
from datetime import date
from pathlib import Path
from typing import Callable

from loguru import logger

EYOTEK_AGENT_ROOT = Path(__file__).resolve().parent.parent


# ── DAILY ROTATION TABLE ─────────────────────────────────────────────────
# weekday(): 0=Pazartesi ... 6=Pazar
_DAILY_CATEGORIES = {
    0: "frustration_analizi",
    1: "token_efficiency",
    2: "routing_balance",
    3: "hallucination_audit",
    4: "dead_code",
    5: "db_health",
    6: "response_quality_drift",
}


def get_today_category() -> str:
    """Bugün hangi kategori taranacak?"""
    return _DAILY_CATEGORIES[date.today().weekday()]


def get_category_focus_prompt(category: str) -> str:
    """LLM'e verilecek kategori odak metni."""
    prompts = {
        "frustration_analizi": (
            "ODAK: Kullanıcı şikayetleri ve frustration kalıpları. "
            "'Yanlış anladın', 'anlamıyorsun', tekrarlayan sorular. "
            "Hangi mesaj tipinde bot yetersiz kalıyor?"
        ),
        "token_efficiency": (
            "ODAK: system_prompts.py duplikasyon ve gereksiz uzunluk. "
            "Aynı kuralın 3 farklı yerde tekrarı, çok uzun örnek listeleri, "
            "obsolete bölümler. Hedef: prompt boyutu küçültme (token tasarrufu) "
            "DAVRANIS DEGISIKLIGI YAPMADAN. Her öneri için: hangi satır aralığı "
            "+ tahmini token tasarrufu + risk değerlendirmesi (low/med/high)."
        ),
        "routing_balance": (
            "ODAK: Fast/Cerebras/Claude routing dağılımı sağlığı. "
            "Eğer Claude payı %30'u geçiyorsa hangi mesaj tiplerinde gereksiz "
            "Claude'a gidiyor? fast_response veya Cerebras pre-check'e taşınabilir mi? "
            "Hedef: maliyet azalt + cevap süresi azalt, kalite koruma."
        ),
        "hallucination_audit": (
            "ODAK: Bot'un veri uydurma riskleri. Sayısal iddialar (kayıt sayısı, "
            "tarih, isim), 'ilk kez/sezon boyunca/hep böyle' tipi historical iddialar. "
            "Tool çıktısının zaman penceresi ile bot cevabındaki kapsamı karşılaştır. "
            "Stale data (last_sync > 7 gün) sunumu uyarısı eksikse rapor et."
        ),
        "dead_code": (
            "ODAK: Kullanılmayan fonksiyon, obsolete import, asla çağrılmayan tool "
            "definitionları. Hedef: kod sadeleştirme. ÖNEMLI: 'kullanılmıyor' "
            "iddiası için en az 3 dosyada arama yapıldı sonucu raporla."
        ),
        "db_health": (
            "ODAK: Veritabanı sağlığı — yavaş sorgular (>500ms), stale tablolar "
            "(last_sync > 14 gün), eksik index, kullanılmayan tablolar. "
            "agent_conversations boyutu, routing_stats büyüme hızı."
        ),
        "response_quality_drift": (
            "ODAK: Cevap kalitesi düşüşü. D/F yanıt oranı, retry oranı (kullanıcı "
            "aynı soruyu tekrar soruyor mu), kısa veya boş cevaplar. Routing kararı "
            "yanlış mı (basit mesaja Claude, kompleks mesaja fast)?"
        ),
    }
    return prompts.get(category, prompts["frustration_analizi"])


# ── KATEGORI-OZEL DETECTOR'lar ───────────────────────────────────────────
# Her detector "problems" listesi döner — prompt_optimizer._detect_problems
# ile aynı format: [{type, ...detaylar}]


async def detect_token_efficiency_issues(hours: int = 168) -> list[dict]:
    """system_prompts.py'da duplikasyon tespit.

    Heuristik: aynı 50+ karakterlik cümle 2+ kez geçiyorsa duplicate.
    """
    sp = EYOTEK_AGENT_ROOT / "system_prompts.py"
    if not sp.exists():
        return []

    try:
        text = sp.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []

    # Cümleleri parçala (yarı-naïve)
    sentences = re.findall(r"[A-ZÇĞIİÖŞÜ][^.!?]{50,200}[.!?]", text)
    seen: dict[str, int] = {}
    for s in sentences:
        key = re.sub(r"\s+", " ", s.lower().strip())[:150]
        seen[key] = seen.get(key, 0) + 1

    problems = []
    for key, count in seen.items():
        if count >= 2:
            problems.append({
                "type": "token_duplicate",
                "file": "system_prompts.py",
                "occurrences": count,
                "snippet": key[:100],
            })
        if len(problems) >= 10:
            break

    # Prompt toplam boyut
    total_chars = len(text)
    if total_chars > 250000:  # ~62K token
        problems.append({
            "type": "prompt_size_warning",
            "file": "system_prompts.py",
            "chars": total_chars,
            "estimated_tokens": total_chars // 4,
        })

    return problems


async def detect_routing_balance_issues(hours: int = 168) -> list[dict]:
    """Routing dağılımı sağlığı."""
    from db_pool import db_fetch
    rows = await db_fetch(
        """SELECT response_source, COUNT(*) AS cnt,
                  AVG(response_ms) AS avg_ms,
                  percentile_cont(0.95) WITHIN GROUP (ORDER BY response_ms) AS p95
           FROM routing_stats
           WHERE created_at > NOW() - ($1 || ' hours')::interval
             AND (phone IS NULL OR phone NOT LIKE '9059900%')
           GROUP BY response_source
           ORDER BY cnt DESC""",
        str(hours),
    )
    if not rows:
        return []

    total = sum(r["cnt"] for r in rows)
    problems = []
    for r in rows:
        pct = (r["cnt"] / total) * 100 if total else 0
        avg_ms = float(r["avg_ms"] or 0)
        p95 = float(r["p95"] or 0)
        src = r["response_source"]
        # Heuristik: Claude > %35 ise alarm (hedef %25)
        if src == "claude" and pct > 35:
            problems.append({
                "type": "routing_claude_overuse",
                "source": src,
                "percent": round(pct, 1),
                "avg_ms": int(avg_ms),
                "p95_ms": int(p95),
                "count": r["cnt"],
            })
        # Fast > %60 ise basit mesajlar çok, kompleks azaltılmış olabilir (denge düşük)
        if src == "fast_response" and pct > 65:
            problems.append({
                "type": "routing_fast_dominant",
                "source": src,
                "percent": round(pct, 1),
                "count": r["cnt"],
            })
        # Avg > 30s ise UX kötü
        if avg_ms > 30000:
            problems.append({
                "type": "routing_slow_avg",
                "source": src,
                "avg_ms": int(avg_ms),
                "p95_ms": int(p95),
            })
    return problems


async def detect_hallucination_audit_issues(hours: int = 168) -> list[dict]:
    """Halüsinasyon riski yüksek bot cevapları (sezon boyunca/ilk kez)."""
    from db_pool import db_fetch
    rows = await db_fetch(
        """SELECT phone, role, content, created_at
           FROM agent_conversations
           WHERE message_role='assistant'
             AND created_at > NOW() - ($1 || ' hours')::interval
             AND (phone IS NULL OR phone NOT LIKE '9059900%')
             AND content !~ '\\[tool_calls'
             AND content ~* '(sezon boyunca|ilk kez|ilk defa|daha önce hiç|hep böyle|hiç olmadı|sadece bireysel|tamamen)'
           ORDER BY created_at DESC
           LIMIT 30""",
        str(hours),
    )
    problems = []
    for r in rows:
        problems.append({
            "type": "hallucination_risk_claim",
            "phone": r["phone"],
            "role": r["role"],
            "snippet": (r["content"] or "")[:300],
        })
    return problems


async def detect_db_health_issues(hours: int = 168) -> list[dict]:
    """DB sağlık taraması."""
    from db_pool import db_fetch, db_fetchval
    problems = []

    # 1. Stale tables
    stale_tables = [
        ("devamsizlik_sayisi", "last_sync"),
        ("etut_history", "olusturma_tarihi"),
        ("counsellor_notes", "last_sync"),
        ("student_exams", "olusturma_tarihi"),
    ]
    for tbl, col in stale_tables:
        try:
            latest = await db_fetchval(f"SELECT MAX({col}) FROM fermat.{tbl}")
            if latest:
                from datetime import datetime
                age_days = (datetime.now() - latest).days
                if age_days > 14:
                    problems.append({
                        "type": "db_stale_table",
                        "table": tbl,
                        "last_update": str(latest),
                        "age_days": age_days,
                    })
        except Exception:
            pass

    # 2. agent_conversations büyüme
    try:
        conv_count = await db_fetchval("SELECT COUNT(*) FROM fermat.agent_conversations")
        if conv_count and conv_count > 100000:
            problems.append({
                "type": "db_table_huge",
                "table": "agent_conversations",
                "row_count": conv_count,
                "note": "Retention politikası gerekebilir (90+ gün eski sil).",
            })
    except Exception:
        pass

    # 3. routing_stats büyüme
    try:
        rs_count = await db_fetchval("SELECT COUNT(*) FROM fermat.routing_stats")
        if rs_count and rs_count > 50000:
            problems.append({
                "type": "db_table_huge",
                "table": "routing_stats",
                "row_count": rs_count,
                "note": "Aggregate'leme + eski satır arşivleme gerekebilir.",
            })
    except Exception:
        pass

    return problems


async def detect_dead_code_issues() -> list[dict]:
    """Heuristik dead-code taraması.

    Bir fonksiyon eyotek_agent/*.py içinde tanımlı ama HİÇBİR yerden
    çağrılmıyorsa rapor et.
    NOT: Bu yüksek false-positive riski taşır (dış çağrılar, dinamik import,
    test dosyaları). Bu yüzden bulguları "incelenebilir" olarak etiketle.
    """
    import os
    problems = []

    # Sadece eyotek_agent root + tools/ + atlas/ taranır
    scan_roots = [
        EYOTEK_AGENT_ROOT,
        EYOTEK_AGENT_ROOT / "tools",
        EYOTEK_AGENT_ROOT / "atlas",
    ]
    all_py: list[Path] = []
    for r in scan_roots:
        if r.exists():
            all_py.extend([p for p in r.glob("*.py") if not p.name.startswith("__")])

    # Tüm dosyaların metnini birleştir (basit memory load)
    combined = ""
    for p in all_py:
        try:
            combined += p.read_text(encoding="utf-8", errors="replace") + "\n"
        except Exception:
            pass

    # Her dosyada tanımlanan top-level fonksiyonları çıkar
    for p in all_py:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        # Sadece async/non-underscore top-level def
        defs = re.findall(r"^(?:async\s+)?def\s+([a-z][a-z0-9_]{4,})\s*\(", text, re.MULTILINE)
        for fn in set(defs):
            # Tanımdan başka yerde geçiyor mu? — pattern: "fn(" veya "fn," veya ".fn"
            pattern = re.compile(rf"\b{fn}\s*\(|\b{fn}\s*,|\.{fn}\b")
            occurrences = len(pattern.findall(combined))
            # 1 = sadece kendi tanımı + dahili çağrı, 0 = hiç bulunamadı (rare)
            if occurrences <= 1:
                problems.append({
                    "type": "dead_function_candidate",
                    "file": p.name,
                    "function": fn,
                    "note": "Eyotek_agent içinde başka çağrı bulunamadı (dış/dinamik çağrı ihtimali var).",
                })
                if len(problems) >= 15:
                    return problems
    return problems


# ── KATEGORI → DETECTOR MAPPING ──────────────────────────────────────────
CATEGORY_DETECTORS: dict[str, Callable] = {
    "token_efficiency":     detect_token_efficiency_issues,
    "routing_balance":      detect_routing_balance_issues,
    "hallucination_audit":  detect_hallucination_audit_issues,
    "db_health":            detect_db_health_issues,
    "dead_code":            detect_dead_code_issues,
    # frustration_analizi + response_quality_drift → prompt_optimizer._detect_problems
    # (mevcut kod, frustration_analizi default detector kullanır)
}


async def run_category_detector(category: str) -> list[dict]:
    """Bugünkü kategorinin detector'ını çalıştır.

    "frustration_analizi" ve "response_quality_drift" için None döner —
    caller mevcut prompt_optimizer._detect_problems kullanır.
    """
    detector = CATEGORY_DETECTORS.get(category)
    if detector is None:
        return []  # caller fallback
    try:
        if category == "dead_code":
            return await detector()  # parametresiz
        return await detector(hours=168)  # 1 hafta
    except Exception as e:
        logger.warning(f"[atlas-categories] {category} detector hata: {e}")
        return []


if __name__ == "__main__":
    import asyncio
    import json

    async def main():
        cat = get_today_category()
        print(f"Bugünün kategorisi: {cat}")
        print(f"Odak: {get_category_focus_prompt(cat)[:200]}")
        print("\n--- Detector çalıştır ---")
        problems = await run_category_detector(cat)
        print(f"Bulgu: {len(problems)}")
        print(json.dumps(problems[:5], indent=2, ensure_ascii=False, default=str))

    asyncio.run(main())
