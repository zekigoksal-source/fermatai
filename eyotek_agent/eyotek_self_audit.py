"""
eyotek_self_audit.py — Bot'un kendi gözleriyle teyit mekanizması.

Neo direktif (11 May 18:00): "Bot Eyotek'ten ss alarak ilerleyebiliyor — kendi
teyit mekanizmanı oluştur. Her adımda kendin ss alarak süreci kontrol et.
Kullanıcı acıp sana ss atmasın."

Mimari:
1. take_audit_screenshot(page, label, claim?) — Playwright sayfasının ss'sini al
2. verify_with_vision(ss_path, claim) — Claude Vision ile ss'i analiz et
3. audit_drill_completeness(...) — drill sonrası mismatch varsa otomatik audit
4. DB'ye kayıt: audit_log tablosu (timestamp, action, claim, screenshot,
   verdict, confidence, vision_response)

Kullanım:
    # 1. Playwright page'in açıkken ss al + Vision teyit
    ss = await take_audit_screenshot(page, "drill_apotemi", "Tabloda 60 satır var mı?")
    vision = await verify_with_vision(ss["path"], ss["claim"])
    print(vision["verdict"])  # TRUE / FALSE / KISMEN

    # 2. drill sonrası otomatik audit hook
    audit = await audit_drill_completeness(page, drill_result, sinav_adi)
    if audit["audited"] and audit["vision_result"]["verdict"] == "FALSE":
        # Bot ek aksiyon alabilir — filter sıfırla, retry vs.

Self-audit log dosyaları: /opt/fermatai/audit_screenshots/{YYYYMMDD}/
DB: audit_log tablosu (otomatik oluşturulur, init_audit_table() ile)
"""
from __future__ import annotations
import asyncio
import base64
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

# Optional, lazy import: anthropic
try:
    import anthropic  # type: ignore
    _HAS_ANTHROPIC = True
except ImportError:
    _HAS_ANTHROPIC = False

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────

AUDIT_BASE_DIR = Path(os.getenv("FERMAT_AUDIT_DIR", "/opt/fermatai/audit_screenshots"))
AUDIT_RETENTION_DAYS = int(os.getenv("FERMAT_AUDIT_RETENTION_DAYS", "14"))
AUDIT_VISION_MODEL = os.getenv("FERMAT_AUDIT_VISION_MODEL", "claude-sonnet-4-5")
AUDIT_ENABLED = os.getenv("FERMAT_AUDIT_ENABLED", "true").lower() == "true"


# ─────────────────────────────────────────────────────────────────────────
# 1. SCREENSHOT
# ─────────────────────────────────────────────────────────────────────────

async def take_audit_screenshot(
    page,  # playwright Page
    label: str,
    claim: Optional[str] = None,
    full_page: bool = False,
) -> dict:
    """Sayfa screenshot'ı al, /audit_screenshots/{YYYYMMDD}/ altına kaydet.

    Args:
        page: Playwright async Page
        label: dosya adı için etiket (örn: 'drill_apotemi_tyt3')
        claim: Vision verify için varsayılan iddia (örn: 'Tabloda 60 satır var mı?')
        full_page: True ise scroll edilmiş tam sayfa, False ise viewport

    Returns:
        {
            "path": "/opt/fermatai/audit_screenshots/20260511/170000_drill_apotemi.png",
            "timestamp": "2026-05-11T17:00:00",
            "label": "drill_apotemi",
            "claim": "...",
            "url": "https://fermat.eyotek.com/...",
            "size_kb": 120,
        }
    """
    if not AUDIT_ENABLED:
        return {"path": None, "skipped": "audit_disabled"}

    try:
        now = datetime.now()
        day_dir = AUDIT_BASE_DIR / now.strftime("%Y%m%d")
        day_dir.mkdir(parents=True, exist_ok=True)

        # Sanitize label (filesystem-safe)
        safe_label = re.sub(r'[^a-zA-Z0-9_-]', '_', label)[:60]
        filename = f"{now.strftime('%H%M%S')}_{safe_label}.png"
        path = day_dir / filename

        await page.screenshot(path=str(path), full_page=full_page, type="png")

        size_kb = path.stat().st_size // 1024

        return {
            "path": str(path),
            "timestamp": now.isoformat(timespec="seconds"),
            "label": label,
            "claim": claim,
            "url": page.url,
            "size_kb": size_kb,
        }
    except Exception as e:
        logger.warning(f"[AUDIT] screenshot fail: {e}")
        return {"path": None, "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────
# 2. VISION VERIFY (Claude Vision)
# ─────────────────────────────────────────────────────────────────────────

VISION_PROMPT_TEMPLATE = """Sen FermatAI sisteminin self-audit mekanizmasısın. Eyotek LMS sayfasının ss'sini inceleyip iddiayı doğrulayacaksın.

İddia: "{claim}"

Görevin:
1. Screenshot'ı dikkatle incele
2. İddianın doğru olup olmadığını saptama
3. Gözlem detaylarını (sayı/element/durum) raporla
4. Bir anomaly varsa (beklenmedik durum) belirt

YANIT FORMATI (sadece JSON, başka açıklama yok):
{{
  "verdict": "TRUE" / "FALSE" / "KISMEN" / "BELIRSIZ",
  "confidence": 0.0-1.0,
  "observation": "1-3 cümle gözlem (Türkçe)",
  "numbers": {{ "row_count": 42, "filtre_aktif": "12.Snf" }},
  "anomaly": "anomaly varsa açıklama / yoksa null"
}}

İpucu: Tabloda satır sayarken header satırını sayma — sadece veri satırları."""


async def verify_with_vision(
    screenshot_path: str,
    claim: str,
    model: Optional[str] = None,
) -> dict:
    """Claude Vision ile screenshot'ı analiz et, iddiayı doğrula."""
    if not AUDIT_ENABLED:
        return {"verdict": "DISABLED", "skipped": True}
    if not _HAS_ANTHROPIC:
        return {"verdict": "BELIRSIZ", "error": "anthropic SDK yok"}
    if not screenshot_path or not Path(screenshot_path).exists():
        return {"verdict": "BELIRSIZ", "error": "screenshot path geçersiz"}

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return {"verdict": "BELIRSIZ", "error": "ANTHROPIC_API_KEY yok"}

    try:
        with open(screenshot_path, "rb") as f:
            image_b64 = base64.standard_b64encode(f.read()).decode()

        client = anthropic.Anthropic(api_key=api_key)
        used_model = model or AUDIT_VISION_MODEL

        # Run sync API call in executor (avoid blocking event loop)
        prompt = VISION_PROMPT_TEMPLATE.format(claim=claim)
        loop = asyncio.get_event_loop()

        def _call():
            return client.messages.create(
                model=used_model,
                max_tokens=600,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": image_b64,
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
            )

        response = await loop.run_in_executor(None, _call)
        text = response.content[0].text.strip()

        # JSON parse
        # LLM bazen ```json ... ``` ile sarıyor — temizle
        text_clean = re.sub(r'^```json\s*', '', text)
        text_clean = re.sub(r'\s*```$', '', text_clean)
        try:
            parsed = json.loads(text_clean)
        except json.JSONDecodeError:
            # JSON parse fail — text döndür
            return {
                "verdict": "BELIRSIZ",
                "confidence": 0.0,
                "observation": text[:500],
                "raw_text": text,
                "parse_error": True,
            }

        # Token usage log
        usage = getattr(response, "usage", None)
        if usage:
            parsed["_tokens"] = {
                "input": getattr(usage, "input_tokens", 0),
                "output": getattr(usage, "output_tokens", 0),
            }
        parsed["_model"] = used_model

        return parsed

    except Exception as e:
        logger.exception(f"[AUDIT] vision verify fail: {e}")
        return {"verdict": "BELIRSIZ", "error": str(e)[:200]}


# ─────────────────────────────────────────────────────────────────────────
# 3. DB LOG TABLE
# ─────────────────────────────────────────────────────────────────────────

INIT_AUDIT_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS audit_log (
    id            SERIAL PRIMARY KEY,
    created_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    action        TEXT NOT NULL,
    claim         TEXT,
    screenshot    TEXT,
    page_url      TEXT,
    verdict       TEXT,
    confidence    REAL,
    observation   TEXT,
    numbers       JSONB,
    anomaly       TEXT,
    expected      INTEGER,
    actual        INTEGER,
    extra         JSONB
);
CREATE INDEX IF NOT EXISTS idx_audit_log_created  ON audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_action   ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_log_verdict  ON audit_log(verdict);
"""


async def init_audit_table() -> bool:
    """audit_log tablosu yoksa oluştur (idempotent)."""
    try:
        from db_pool import db_execute
        await db_execute(INIT_AUDIT_TABLE_SQL)
        return True
    except Exception as e:
        logger.warning(f"[AUDIT] init_audit_table fail: {e}")
        return False


async def log_audit(
    *,
    action: str,
    claim: Optional[str] = None,
    screenshot: Optional[str] = None,
    page_url: Optional[str] = None,
    vision_result: Optional[dict] = None,
    expected: Optional[int] = None,
    actual: Optional[int] = None,
    extra: Optional[dict] = None,
) -> Optional[int]:
    """Audit kaydını DB'ye yaz."""
    try:
        from db_pool import db_fetchval
        v = vision_result or {}
        row_id = await db_fetchval(
            """INSERT INTO audit_log
               (action, claim, screenshot, page_url, verdict, confidence,
                observation, numbers, anomaly, expected, actual, extra)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
               RETURNING id""",
            action,
            claim,
            screenshot,
            page_url,
            v.get("verdict"),
            float(v.get("confidence") or 0.0),
            v.get("observation"),
            json.dumps(v.get("numbers") or {}),
            v.get("anomaly"),
            expected,
            actual,
            json.dumps(extra or {}),
        )
        return int(row_id) if row_id else None
    except Exception as e:
        logger.warning(f"[AUDIT] log_audit fail: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────
# 4. DRILL HOOK — sinav_drilldown sonrası otomatik audit
# ─────────────────────────────────────────────────────────────────────────

async def audit_drill_completeness(
    page,
    drill_result: dict,
    sinav_adi: str,
    *,
    force: bool = False,
) -> dict:
    """sinav_drilldown sonucu mismatch varsa otomatik ss + Vision teyit.

    Trigger: completeness ratio < 0.85 (V3 self-aware drill)
    """
    if not AUDIT_ENABLED:
        return {"audited": False, "reason": "audit_disabled"}

    completeness = drill_result.get("data_completeness") or {}
    expected = completeness.get("expected")
    actual = drill_result.get("row_count") or 0
    ratio = completeness.get("ratio")

    should_audit = force or (expected and ratio is not None and ratio < 0.85)
    if not should_audit:
        return {"audited": False, "reason": "no_mismatch"}

    label = f"drill_{re.sub(r'[^a-zA-Z0-9]', '_', sinav_adi)[:40]}"
    claim = (
        f"Bu Eyotek dynamic-list sayfasında öğrenci listesi tablosunda "
        f"kaç tane veri satırı görünüyor? Header satırını sayma. "
        f"Beklenen sayı {expected}, drill {actual} kayıt çekti."
    )
    ss = await take_audit_screenshot(page, label, claim)
    if not ss.get("path"):
        return {"audited": False, "reason": "screenshot_fail",
                "ss_error": ss.get("error")}

    vision = await verify_with_vision(ss["path"], claim)
    log_id = await log_audit(
        action="sinav_drill_completeness",
        claim=claim,
        screenshot=ss.get("path"),
        page_url=ss.get("url"),
        vision_result=vision,
        expected=expected,
        actual=actual,
        extra={
            "sinav_adi": sinav_adi,
            "devre_count": drill_result.get("devre_count"),
            "ratio": ratio,
        },
    )
    return {
        "audited": True,
        "reason": "completeness_low" if not force else "forced",
        "screenshot": ss,
        "vision_result": vision,
        "audit_log_id": log_id,
    }


async def audit_action(
    page,
    *,
    action: str,
    claim: str,
    label: Optional[str] = None,
    expected: Optional[int] = None,
    actual: Optional[int] = None,
    extra: Optional[dict] = None,
) -> dict:
    """Generic audit helper — herhangi bir Eyotek aksiyonu için ss + Vision.

    Args:
        page: Playwright page (aksiyondan sonra hâlâ açık)
        action: tip ('write_etut', 'student_drill', 'eyotek_query', vs.)
        claim: Vision'a sorulacak iddia
        label: dosya adı için kısa etiket (varsayılan: action)
        expected/actual: sayısal karşılaştırma (varsa DB'ye yazılır)
        extra: ek metadata

    Returns: {audited, screenshot, vision_result, audit_log_id}
    """
    if not AUDIT_ENABLED:
        return {"audited": False, "reason": "audit_disabled"}

    ss = await take_audit_screenshot(page, label or action, claim)
    if not ss.get("path"):
        return {"audited": False, "reason": "screenshot_fail",
                "ss_error": ss.get("error")}

    vision = await verify_with_vision(ss["path"], claim)

    log_id = await log_audit(
        action=action,
        claim=claim,
        screenshot=ss.get("path"),
        page_url=ss.get("url"),
        vision_result=vision,
        expected=expected,
        actual=actual,
        extra=extra,
    )

    return {
        "audited": True,
        "screenshot": ss,
        "vision_result": vision,
        "audit_log_id": log_id,
    }


# ─── Spesifik audit helpers (her tool için anlamlı claim) ──────

async def audit_write_etut(page, *, ogrenci_adi: str, ogretmen: str,
                            tarih: str, saat: str, ders: str,
                            sinif: str = "") -> dict:
    """Etüt yazıldıktan sonra takvim sayfasında görünüyor mu teyit et."""
    claim = (
        f"Bu Eyotek takvim sayfasında {tarih} tarihli {saat} saatinde "
        f"{ogretmen} öğretmenin {ders} etüdü görünüyor mu? "
        f"Eğer öğrenci ekleme yapıldıysa {ogrenci_adi} adı tabloda var mı? "
        f"Etüt slot'u {ders} bilgisi ile dolu mu?"
    )
    return await audit_action(
        page,
        action="write_etut_verify",
        claim=claim,
        label=f"write_etut_{tarih}_{saat}",
        extra={
            "ogrenci_adi": ogrenci_adi, "ogretmen": ogretmen,
            "tarih": tarih, "saat": saat, "ders": ders, "sinif": sinif,
        },
    )


async def audit_write_counsellor(page, *, ogrenci_adi: str, not_turu: str,
                                  gorusulen: str = "") -> dict:
    """Rehberlik notu yazıldıktan sonra listede görünüyor mu teyit et."""
    short_not = (gorusulen[:60] + "...") if len(gorusulen) > 60 else gorusulen
    claim = (
        f"Bu Eyotek rehberlik notları sayfasında BUGÜN tarihli yeni bir not "
        f"görünüyor mu? Öğrenci: '{ogrenci_adi}', not türü '{not_turu}'. "
        f"Listenin başında bu kayıt var mı?"
    )
    return await audit_action(
        page,
        action="write_counsellor_verify",
        claim=claim,
        label=f"counsellor_{ogrenci_adi[:20]}",
        extra={"ogrenci_adi": ogrenci_adi, "not_turu": not_turu,
               "gorusulen_preview": short_not},
    )


async def audit_student_drill(page, *, student_identifier: str,
                               sub_page: str, row_count: int = 0) -> dict:
    """Öğrenci drill — doğru öğrenci profili açıldı mı + tablo sayısı doğru mu."""
    claim = (
        f"Bu Eyotek öğrenci profil sayfasında '{student_identifier}' adlı/sözlü "
        f"öğrencinin '{sub_page}' alt sayfası açık mı? "
        f"Tabloda {row_count} satır var mı (header hariç)? "
        f"Yanlış öğrenci profili açılmış olabilir mi?"
    )
    return await audit_action(
        page,
        action="student_drill_verify",
        claim=claim,
        label=f"student_{student_identifier[:30]}_{sub_page}",
        actual=row_count,
        extra={"student_identifier": student_identifier, "sub_page": sub_page},
    )


async def audit_navigate_query(page, *, page_path: str,
                                row_count: int = 0,
                                filters: Optional[dict] = None) -> dict:
    """Generic eyotek_query/navigate sonrası teyit."""
    filter_desc = ", ".join(f"{k}={v}" for k, v in (filters or {}).items()
                             if v) or "(filtre yok)"
    claim = (
        f"Bu Eyotek '{page_path}' sayfasında uygulanan filtreler: {filter_desc}. "
        f"Tabloda {row_count} satır göründü. Filtre durumu doğru mu, "
        f"sayfa boş mu, hata mesajı var mı?"
    )
    return await audit_action(
        page,
        action="navigate_query_verify",
        claim=claim,
        label=f"query_{page_path.replace('/','_')[:40]}",
        actual=row_count,
        extra={"page_path": page_path, "filters": filters},
    )
    """sinav_drilldown sonucu mismatch varsa otomatik ss + Vision teyit.

    Args:
        page: Playwright page (drill bittikten sonra hâlâ açık)
        drill_result: sinav_drilldown'ın return dict'i
        sinav_adi: orijinal arama
        force: True ise mismatch yoksa bile ss al (debug için)

    Returns:
        {
            "audited": bool,
            "reason": "no_mismatch" / "completeness_low" / ...
            "screenshot": {...} (varsa),
            "vision_result": {...} (varsa),
            "audit_log_id": int (varsa)
        }
    """
    if not AUDIT_ENABLED:
        return {"audited": False, "reason": "audit_disabled"}

    completeness = drill_result.get("data_completeness") or {}
    expected = completeness.get("expected")
    actual = drill_result.get("row_count") or 0
    ratio = completeness.get("ratio")

    # Trigger logic: force veya completeness eksik
    should_audit = force or (expected and ratio is not None and ratio < 0.85)

    if not should_audit:
        return {"audited": False, "reason": "no_mismatch"}

    # 1. Screenshot al
    label = f"drill_{re.sub(r'[^a-zA-Z0-9]', '_', sinav_adi)[:40]}"
    claim = (
        f"Bu Eyotek dynamic-list sayfasında öğrenci listesi tablosunda "
        f"kaç tane veri satırı görünüyor? Header satırını sayma. "
        f"Beklenen sayı {expected}, drill {actual} kayıt çekti."
    )
    ss = await take_audit_screenshot(page, label, claim)

    # 2. Vision verify
    if not ss.get("path"):
        return {"audited": False, "reason": "screenshot_fail", "ss_error": ss.get("error")}

    vision = await verify_with_vision(ss["path"], claim)

    # 3. DB'ye kaydet
    log_id = await log_audit(
        action="sinav_drill_completeness",
        claim=claim,
        screenshot=ss.get("path"),
        page_url=ss.get("url"),
        vision_result=vision,
        expected=expected,
        actual=actual,
        extra={
            "sinav_adi": sinav_adi,
            "devre_count": drill_result.get("devre_count"),
            "ratio": ratio,
        },
    )

    return {
        "audited": True,
        "reason": "completeness_low" if not force else "forced",
        "screenshot": ss,
        "vision_result": vision,
        "audit_log_id": log_id,
    }


# ─────────────────────────────────────────────────────────────────────────
# 5. CLEANUP — eski ss'leri sil (retention)
# ─────────────────────────────────────────────────────────────────────────

def cleanup_old_screenshots(days: int = AUDIT_RETENTION_DAYS) -> int:
    """N günden eski audit ss klasörlerini sil. Return: silinen klasör sayısı."""
    if not AUDIT_BASE_DIR.exists():
        return 0
    from datetime import timedelta
    cutoff = datetime.now() - timedelta(days=days)
    deleted = 0
    for day_dir in AUDIT_BASE_DIR.iterdir():
        if not day_dir.is_dir():
            continue
        try:
            dir_date = datetime.strptime(day_dir.name, "%Y%m%d")
            if dir_date < cutoff:
                import shutil
                shutil.rmtree(day_dir)
                deleted += 1
        except ValueError:
            continue
    return deleted


# ─────────────────────────────────────────────────────────────────────────
# 6. PUBLIC API
# ─────────────────────────────────────────────────────────────────────────

__all__ = [
    'take_audit_screenshot',
    'verify_with_vision',
    'audit_action',
    'audit_drill_completeness',
    'audit_write_etut',
    'audit_write_counsellor',
    'audit_student_drill',
    'audit_navigate_query',
    'init_audit_table',
    'log_audit',
    'cleanup_old_screenshots',
    'AUDIT_ENABLED',
]


# ─────────────────────────────────────────────────────────────────────────
# 7. SELF-TEST (CLI)
# ─────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    print(f"AUDIT_BASE_DIR: {AUDIT_BASE_DIR}")
    print(f"AUDIT_ENABLED:  {AUDIT_ENABLED}")
    print(f"AUDIT_VISION_MODEL: {AUDIT_VISION_MODEL}")
    print(f"_HAS_ANTHROPIC: {_HAS_ANTHROPIC}")

    if len(sys.argv) > 1 and sys.argv[1] == "init-table":
        from dotenv import load_dotenv
        env_path = Path(__file__).resolve().parent.parent / ".env"
        if env_path.exists():
            load_dotenv(env_path)
        ok = asyncio.run(init_audit_table())
        print(f"init_audit_table: {'OK' if ok else 'FAIL'}")
    elif len(sys.argv) > 1 and sys.argv[1] == "cleanup":
        n = cleanup_old_screenshots()
        print(f"Cleaned {n} old day directories")
    elif len(sys.argv) > 1 and sys.argv[1] == "stats":
        # Audit istatistikleri — bot ne kadar mantıklı tetikliyor?
        from dotenv import load_dotenv
        env_path = Path(__file__).resolve().parent.parent / ".env"
        if env_path.exists():
            load_dotenv(env_path)

        async def show_stats():
            from db_pool import db_fetch
            print("=" * 70)
            print("AUDIT İSTATİSTİKLERİ — Bot Tetikleme Mantığı")
            print("=" * 70)

            # Son 24 saat
            rows = await db_fetch("""
                SELECT action, verdict, COUNT(*) as cnt
                FROM audit_log
                WHERE created_at > NOW() - INTERVAL '24 hours'
                GROUP BY action, verdict
                ORDER BY action, verdict
            """) or []
            print(f"\nSon 24 saat — toplam: {sum(r.get('cnt', 0) for r in rows)} audit")
            print(f"{'action':<35} {'verdict':<12} {'count':>5}")
            print("-" * 60)
            for r in rows:
                print(f"  {r['action']:<33} {(r['verdict'] or '?'):<12} {r['cnt']:>5}")

            # Verdict dağılımı (toplam)
            vd = await db_fetch("""
                SELECT verdict, COUNT(*) as cnt
                FROM audit_log
                WHERE created_at > NOW() - INTERVAL '24 hours'
                GROUP BY verdict
                ORDER BY cnt DESC
            """) or []
            print(f"\nVerdict dağılımı (24 saat):")
            for r in vd:
                print(f"  {(r['verdict'] or '?'):<12} {r['cnt']:>5}")

            # Anomaly tespit edilenler (önemli!)
            anom = await db_fetch("""
                SELECT created_at, action, verdict, anomaly,
                       LEFT(observation, 100) as obs_short
                FROM audit_log
                WHERE created_at > NOW() - INTERVAL '24 hours'
                  AND verdict IN ('FALSE', 'KISMEN')
                ORDER BY created_at DESC LIMIT 10
            """) or []
            if anom:
                print(f"\nSon 10 ŞÜPHELI/YANLIŞ verdict (bot fark etti):")
                for r in anom:
                    ts = str(r.get('created_at', ''))[:19]
                    print(f"  [{ts}] {r['action']:<25} {r['verdict']:<8}")
                    if r.get('observation'):
                        print(f"     obs: {r.get('obs_short', '')}")
                    if r.get('anomaly'):
                        print(f"     anomaly: {(r['anomaly'] or '')[:120]}")

            # Maliyet tahmini
            total_24h = sum(r.get('cnt', 0) for r in rows)
            cost_per = 0.01  # ~$0.01/audit (Sonnet Vision)
            print(f"\nMaliyet tahmini: ~${total_24h * cost_per:.2f}/24h "
                  f"(${total_24h * cost_per * 30:.2f}/ay tahmin)")

        asyncio.run(show_stats())
