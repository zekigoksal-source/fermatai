"""
ATLAS Completion Awareness — Oturum 25.29
============================================

Atlas advisor öneri üretirken geçmişte yapılan işleri kontrol eder.
Aynı kategori + target_files kombinasyonu için son 90 günde:
  1. atlas_suggestions.status = 'yapildi' kayıt var mı?
  2. deployments tablosunda ilgili dosya commit edilmiş mi?
  3. KALDIGIM.md'de "✅ kapatildi" / "fix" notu var mı?

Eğer iş daha önce yapılmışsa:
  - Yeni suggestion oluşturma (rationale'ye eski commit hash'i ekle)
  - VEYA severity düşür + "alternatif yaklaşım" notu ile devam

Kullanım:
  from atlas.completion_awareness import is_already_done, get_recent_work

  done = await is_already_done(
      category="latency",
      target_files=["llm_router.py", "fermat_core_agent.py"]
  )
  if done:
      logger.info(f"Bu is daha once yapildi: {done['evidence']}")
"""
from __future__ import annotations
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

_PARENT = str(Path(__file__).resolve().parent.parent)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)


# ─── 1. atlas_suggestions geçmiş kontrol ─────────────────────────────────────

async def find_completed_suggestions(
    category: str,
    target_files: list[str] | None = None,
    days: int = 90,
) -> list[dict]:
    """Atlas'ta status='yapildi' veya 'incelendi' olan benzer öneriler."""
    from db_pool import db_fetch
    target_files = target_files or []
    try:
        if target_files:
            rows = await db_fetch(
                """SELECT id, title, rationale, status, target_files, created_at
                   FROM atlas_suggestions
                   WHERE category = $1
                     AND status IN ('yapildi', 'incelendi')
                     AND created_at > NOW() - ($2 || ' days')::interval
                     AND target_files && $3::text[]
                   ORDER BY created_at DESC LIMIT 5""",
                category, str(days), target_files,
            )
        else:
            rows = await db_fetch(
                """SELECT id, title, rationale, status, target_files, created_at
                   FROM atlas_suggestions
                   WHERE category = $1
                     AND status IN ('yapildi', 'incelendi')
                     AND created_at > NOW() - ($2 || ' days')::interval
                   ORDER BY created_at DESC LIMIT 5""",
                category, str(days),
            )
        return [dict(r) for r in rows]
    except Exception:
        return []


# ─── 2. deployments tablosu — commit takibi ──────────────────────────────────

async def find_recent_deployments_touching(
    target_files: list[str],
    days: int = 30,
) -> list[dict]:
    """Son N günde target_files'i değiştiren commit'ler.

    deployments.notes alanında dosya adı geçiyor mu kontrolü.
    Eğer notes yoksa son tarihler döndürülür (genel kontrol).
    """
    from db_pool import db_fetch
    if not target_files:
        return []
    try:
        # notes'ta dosya adı geçen commit'leri ara
        like_clauses = " OR ".join([f"notes ILIKE $1{i}" for i in range(2, len(target_files) + 2)])
        if not like_clauses:
            return []
        # Basitleştirilmiş query — tek dosya için
        primary_file = target_files[0]
        rows = await db_fetch(
            """SELECT version, deployed_at, notes
               FROM deployments
               WHERE notes ILIKE '%' || $1 || '%'
                 AND deployed_at > NOW() - ($2 || ' days')::interval
               ORDER BY deployed_at DESC LIMIT 5""",
            primary_file, str(days),
        )
        return [dict(r) for r in rows]
    except Exception:
        return []


# ─── 3. KALDIGIM.md "✅ kapatildi" notu ─────────────────────────────────────

def find_kaldigim_mentions(keywords: list[str]) -> list[str]:
    """KALDIGIM.md'de keyword + "✅" / "fix" / "tamamlandi" arar."""
    try:
        kaldigim_path = Path(__file__).resolve().parent.parent.parent / "KALDIGIM.md"
        if not kaldigim_path.exists():
            return []
        text = kaldigim_path.read_text(encoding="utf-8", errors="replace")
        text_lower = text.lower()
        hits = []
        for kw in keywords:
            kw_lower = kw.lower()
            # Keyword'un geçtiği satırları bul
            for line in text.split("\n"):
                line_lower = line.lower()
                if kw_lower in line_lower and any(
                    marker in line_lower for marker in
                    ["✅", "fix", "tamamlandi", "tamamlandı", "bitti", "kapatildi", "kapatıldı", "çözüldü", "cozuldu"]
                ):
                    hits.append(line.strip()[:150])
        return list(dict.fromkeys(hits))[:5]  # dedup, ilk 5
    except Exception:
        return []


# ─── ANA API ─────────────────────────────────────────────────────────────────

def find_blueprint_decision(keywords: list[str]) -> list[str]:
    """BLUEPRINT.md'de mimari karar / mevcut kapasite tespiti.

    Atlas öneri vermeden önce: "Bu zaten BLUEPRINT'te mimari karari mi?"
    """
    if not keywords:
        return []
    try:
        # blueprint_awareness ana modülde — atlas/'dan göreceli import
        import sys
        from pathlib import Path
        parent = Path(__file__).resolve().parent.parent
        if str(parent) not in sys.path:
            sys.path.insert(0, str(parent))
        from blueprint_awareness import search_blueprint
        hits = []
        for kw in keywords:
            results = search_blueprint(kw, max_results=2)
            for r in results:
                hits.append(
                    f"BLUEPRINT #{r['num']} ({r['title'][:50]}): {r['snippet'][:120]}"
                )
        return hits[:3]
    except Exception:
        return []


async def is_already_done(
    category: str,
    target_files: list[str] | None = None,
    keywords: list[str] | None = None,
    days: int = 90,
) -> Optional[dict]:
    """Geçmişte yapılan işi tespit et.

    4 kaynak kontrolü (Oturum 25.29):
      1. atlas_suggestions.status='yapildi' (90 gün)
      2. deployments tablosu (30 gün, dosya bazlı)
      3. KALDIGIM.md "✅ kapatildi" notları
      4. BLUEPRINT.md mimari karar / kapasite (yeni)

    Args:
        category: atlas suggestion category
        target_files: ilgili kod dosyaları
        keywords: rationale'de aranacak kelimeler (örn ['routing', 'latency'])
        days: kaç günlük geçmiş

    Returns:
        None: yapılmamış. Yeni suggestion üretilebilir.
        dict: {evidence: [...], summary: "..."} yapılmış. Suggestion'da göster.
    """
    target_files = target_files or []
    keywords = keywords or []

    completed = await find_completed_suggestions(category, target_files, days)
    deployments = await find_recent_deployments_touching(target_files, days=30) if target_files else []
    kaldigim_hits = find_kaldigim_mentions(keywords) if keywords else []
    blueprint_hits = find_blueprint_decision(keywords) if keywords else []

    if not (completed or deployments or kaldigim_hits or blueprint_hits):
        return None

    evidence = []
    if completed:
        for c in completed[:3]:
            evidence.append(
                f"Atlas #{c['id']} ({c['status']}, "
                f"{c['created_at'].strftime('%d.%m')}): {c['title'][:80]}"
            )
    if deployments:
        for d in deployments[:3]:
            v = d.get("version", "?")
            ts = d["deployed_at"].strftime("%d.%m") if d.get("deployed_at") else "?"
            note_short = (d.get("notes") or "")[:80]
            evidence.append(f"Deploy {v[:8]} ({ts}): {note_short}")
    if kaldigim_hits:
        for k in kaldigim_hits[:2]:
            evidence.append(f"KALDIGIM: {k}")
    if blueprint_hits:
        for b in blueprint_hits[:2]:
            evidence.append(b)

    return {
        "evidence": evidence,
        "summary": (
            f"Bu kategori ({category}) son {days} günde "
            f"{len(evidence)} farklı yerde adres edilmiş — alternatif yaklaşım gerekli."
        ),
        "completed_count": len(completed),
        "deployment_count": len(deployments),
        "kaldigim_count": len(kaldigim_hits),
        "blueprint_count": len(blueprint_hits),
    }


async def get_recent_work(days: int = 14) -> dict:
    """Son N gündeki tamamlanan işler — bot tool için.

    Bot bir öneri verirken "geçmişte ne yaptık?" sorusunda kullanır.
    """
    from db_pool import db_fetch
    try:
        completed = await db_fetch(
            """SELECT category, title, status, created_at
               FROM atlas_suggestions
               WHERE status IN ('yapildi', 'incelendi')
                 AND created_at > NOW() - ($1 || ' days')::interval
               ORDER BY created_at DESC LIMIT 30""",
            str(days),
        )
        deploys = await db_fetch(
            """SELECT version, deployed_at, LEFT(notes, 200) AS notes
               FROM deployments
               WHERE deployed_at > NOW() - ($1 || ' days')::interval
               ORDER BY deployed_at DESC LIMIT 30""",
            str(days),
        )
        return {
            "days": days,
            "atlas_completed": [dict(r) for r in completed],
            "recent_deployments": [dict(r) for r in deploys],
            "summary": (
                f"Son {days} günde {len(completed)} Atlas önerisi tamamlandı, "
                f"{len(deploys)} deploy yapıldı."
            ),
        }
    except Exception as e:
        return {"error": str(e)[:200]}


# ─── CLI test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import asyncio

    async def _test():
        # Test: latency kategorisinde geçmişte yapılmış mı?
        result = await is_already_done(
            category="latency",
            target_files=["llm_router.py", "fermat_core_agent.py"],
            keywords=["routing", "cerebras"],
        )
        print("=" * 60)
        print("is_already_done(latency):")
        print(json.dumps(result, indent=2, default=str, ensure_ascii=False))
        print()
        # Son 14 günün özeti
        recent = await get_recent_work(days=14)
        print("=" * 60)
        print("get_recent_work(days=14):")
        print(json.dumps(recent, indent=2, default=str, ensure_ascii=False)[:2000])

    asyncio.run(_test())
