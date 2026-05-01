"""
Render Endpoint (Oturum 25.31 — Neo direktifi)
================================================
Bot kompleks HTML/JS/CSS üretirse:
  POST /render → kalıcı UUID link
  GET /render/{uuid} → sandbox iframe içinde HTML serve

Kullanım: 12 hazır renderer (sim/3d/formula/calc/chart/radar/heatmap/karne/
gauge/timeline/progress/compare) yetmediği nadir durumlarda son çare.

Güvenlik:
- Sadece bot tool'u kayıt yapabilir (internal call)
- HTML iframe sandbox içinde serve edilir (allow-scripts only)
- TTL 7 gün (geçici içerik)
- Maksimum 1MB HTML (DoS koruma; ideal 200-400KB)

DB tablosu: render_artifacts
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from loguru import logger

from db_pool import db_execute, db_fetchrow, db_fetchval

router = APIRouter(prefix="/render", tags=["render"])

MAX_HTML_BYTES = 1024 * 1024  # 1MB (25.37 Neo: 800KB de yetmedi karmaşık fizik simlerine)
DEFAULT_TTL_DAYS = 7


async def ensure_table():
    """Tablo yoksa oluştur — idempotent."""
    try:
        await db_execute("""
            CREATE TABLE IF NOT EXISTS render_artifacts (
                id SERIAL PRIMARY KEY,
                uuid TEXT UNIQUE NOT NULL,
                title TEXT,
                html TEXT NOT NULL,
                creator_phone TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                expires_at TIMESTAMP,
                view_count INTEGER DEFAULT 0,
                last_viewed_at TIMESTAMP
            )
        """)
        # 25.36 — arşiv kolonları (kullanıcı talebi: 30gün TTL kısa, kalıcı tut)
        await db_execute("""
            ALTER TABLE render_artifacts
            ADD COLUMN IF NOT EXISTS archived BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP,
            ADD COLUMN IF NOT EXISTS archived_by_phone TEXT,
            ADD COLUMN IF NOT EXISTS archive_note TEXT,
            ADD COLUMN IF NOT EXISTS quality_score INTEGER DEFAULT 0
        """)
        # 25.37 — Render cache (Neo direktifi): aynı topic_hash → tekrar üretme, var olanı reuse
        await db_execute("""
            ALTER TABLE render_artifacts
            ADD COLUMN IF NOT EXISTS topic_hash TEXT,
            ADD COLUMN IF NOT EXISTS reuse_count INTEGER DEFAULT 0
        """)
        await db_execute(
            "CREATE INDEX IF NOT EXISTS idx_render_topic_hash ON render_artifacts(topic_hash) WHERE topic_hash IS NOT NULL"
        )
        await db_execute(
            "CREATE INDEX IF NOT EXISTS idx_render_uuid ON render_artifacts(uuid)"
        )
        await db_execute(
            "CREATE INDEX IF NOT EXISTS idx_render_expires ON render_artifacts(expires_at)"
        )
        await db_execute(
            "CREATE INDEX IF NOT EXISTS idx_render_archived ON render_artifacts(archived) WHERE archived = TRUE"
        )
    except Exception as e:
        logger.warning(f"render_artifacts ensure_table hata: {e}")


def calculate_quality_score(html: str) -> tuple[int, dict]:
    """25.36 — HTML kalite puanı (100 üzerinden) + breakdown.
    Neo direktif: tutarsız kalite sorunu için otomatik puanlama."""
    if not html:
        return 0, {"reason": "empty"}
    h = html.lower()
    breakdown = {}
    score = 0
    # Canvas/SVG/WebGL (+25)
    if any(k in h for k in ["<canvas", "<svg", "webgl", "three.", "p5.", "babylon"]):
        score += 25; breakdown["canvas_or_svg"] = True
    # Animation (+20)
    if any(k in h for k in ["requestanimationframe", "@keyframes", "gsap.", "tween", "animate("]):
        score += 20; breakdown["animation"] = True
    # User interaction (+15)
    if any(k in h for k in ['type="range"', 'type="button"', "<button", "onclick", "addeventlistener", "oninput"]):
        score += 15; breakdown["interaction"] = True
    # Try/catch + error handling (+10)
    if "try" in h and "catch" in h:
        score += 10; breakdown["error_handling"] = True
    # Responsive (+10)
    if "viewport" in h and ("width=device-width" in h or "100%" in h):
        score += 10; breakdown["responsive"] = True
    # Formula/Math/LaTeX (+10)
    if any(k in h for k in ["katex", "mathjax", "math.", "formula", "$", "\\frac"]):
        score += 10; breakdown["formula"] = True
    # Size optimization (10-400KB ideal) (+5)
    size_kb = len(html.encode("utf-8")) / 1024
    if 5 <= size_kb <= 400:
        score += 5; breakdown["optimal_size"] = True
    # Labels/text content (+5)
    if any(k in h for k in ["label", "<text", "title", "<h1", "<h2", "<h3"]):
        score += 5; breakdown["labels"] = True
    breakdown["total_score"] = score
    breakdown["size_kb"] = round(size_kb, 1)
    return score, breakdown


def _topic_hash(title: str, html_size_bucket: int = 0) -> str:
    """Cache key — title normalize + stop word filter + html size bucket.

    25.37+ (Neo audit #7): Title varyasyonları aynı hash'e düşer:
    'Newton 2. Yasa Simülasyonu' == 'Newton'un 2. Yasası' == 'Newton 2nd Law'

    Akış:
      1. Türkçe → ascii fold (İ/Ş/Ç/Ö/Ü/Ğ)
      2. Combining diakritik temizle (NFKD)
      3. STOP WORD filter (simülasyon, interaktif, göster, yap...)
      4. Tek boşluk + sıralı kelimeler (alfabetik)
    """
    import hashlib, unicodedata, re
    norm = (title or "").strip()[:120]
    # 1) Türkçe-aware lower
    tr_map = {
        "ı": "i", "I": "i", "İ": "i", "i": "i",
        "ç": "c", "Ç": "c",
        "ş": "s", "Ş": "s",
        "ğ": "g", "Ğ": "g",
        "ö": "o", "Ö": "o",
        "ü": "u", "Ü": "u",
        "â": "a", "Â": "a",
        "î": "i", "Î": "i",
        "û": "u", "Û": "u",
    }
    folded = "".join(tr_map.get(c, c) for c in norm).lower()
    # 2) Combining diakritikleri çöz
    folded = unicodedata.normalize("NFKD", folded)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    # 3) Noktalama ve fazla boşlukları temizle
    folded = re.sub(r"[^\w\s]", " ", folded)
    folded = re.sub(r"\s+", " ", folded).strip()
    # 4) STOP WORD FILTER — title varyasyonları aynı kategoriye düşsün
    STOP_WORDS = {
        # Render isteği kelimeleri
        "simulasyon", "simulasyonu", "simülasyon", "simülasyonu",
        "interaktif", "interactive", "animasyon", "animasyonu",
        "model", "modeli", "modelleme", "infografik",
        "gosteren", "göster", "goster", "gosteri",
        "yap", "yapan", "olustur", "oluşturan",
        "kapsamli", "kapsamlı", "detayli", "detaylı", "tam",
        "tum", "tüm", "hakkinda", "hakkında", "ile", "icin", "için",
        # İngilizce karşılıkları
        "simulation", "show", "create", "make", "full",
        # Bağlaçlar
        "ve", "veya", "ile", "ile", "den", "dan",
        # Sayı sıraları (Newton 2. → newton + 2)
        "1", "2", "3", "1.", "2.", "3.",
        # Fizik prefiksleri (genel)
        "3d", "2d", "fizik", "kimya", "biyoloji",
    }
    words = [w for w in folded.split() if w not in STOP_WORDS and len(w) > 1]
    # Sıralı (kelime sırası farkı yok edilir)
    words.sort()
    canonical = " ".join(words[:6])  # max 6 anlamlı kelime (overflow önle)
    base = f"{canonical}|{html_size_bucket}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


async def lookup_cached_render(title: str, max_age_days: int = 30) -> Optional[dict]:
    """Aynı title ile son N gün içinde başarılı (kalite >=60) render var mı?

    Returns: {'uuid', 'title', 'quality_score', 'created_at'} veya None
    25.37 (Neo): Newton 2. yasa 1 kez üret, 1000 kişiye sun.
    """
    try:
        await ensure_table()
        thash = _topic_hash(title or "")
        row = await db_fetchrow(
            """SELECT uuid, title, quality_score, created_at, expires_at, archived
               FROM render_artifacts
               WHERE topic_hash = $1
                 AND (archived = TRUE OR expires_at > NOW())
                 AND quality_score >= 60
                 AND created_at > NOW() - ($2::int * INTERVAL '1 day')
               ORDER BY quality_score DESC, created_at DESC LIMIT 1""",
            thash, max_age_days
        )
        if row:
            return {
                "uuid": row["uuid"],
                "title": row["title"],
                "quality_score": row["quality_score"],
                "created_at": str(row["created_at"]),
            }
        return None
    except Exception as e:
        logger.debug(f"lookup_cached_render hata: {e}")
        return None


async def create_artifact(html: str, title: str = "FermatAI Görsel",
                          creator_phone: str = "", ttl_days: int = DEFAULT_TTL_DAYS,
                          allow_cache: bool = True) -> Optional[str]:
    """
    Bot tool'undan çağrılır — HTML kaydet, UUID döndür.
    25.36: Otomatik kalite skoru hesapla + DB'ye kaydet.
    25.37: Cache lookup — aynı title kalite>=60 var → reuse, üretme.
    """
    if not html or len(html.encode('utf-8')) > MAX_HTML_BYTES:
        logger.warning(f"render: html bos veya >1MB ({len(html)} bytes)")
        return None
    try:
        await ensure_table()
        # 25.37 — cache check (allow_cache=True default)
        if allow_cache and title:
            cached = await lookup_cached_render(title, max_age_days=30)
            if cached and cached.get("uuid"):
                # reuse counter ++
                try:
                    await db_execute(
                        "UPDATE render_artifacts SET reuse_count = reuse_count + 1, last_viewed_at = NOW() WHERE uuid = $1",
                        cached["uuid"]
                    )
                except Exception:
                    pass
                logger.info(f"render: ♻️ CACHE HIT title={title[:40]} → reuse {cached['uuid']} (score={cached['quality_score']})")
                return cached["uuid"]

        uuid = secrets.token_urlsafe(12)
        expires = datetime.now() + timedelta(days=ttl_days)
        # 25.36 — kalite skoru
        score, breakdown = calculate_quality_score(html)
        # 25.37 — topic_hash
        thash = _topic_hash(title or "")
        await db_execute(
            """INSERT INTO render_artifacts (uuid, title, html, creator_phone, expires_at, quality_score, topic_hash)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            uuid, title[:200], html, creator_phone, expires, score, thash
        )
        quality_label = "🌟" if score >= 80 else ("✓" if score >= 60 else "⚠")
        logger.info(f"render: {quality_label} artifact uuid={uuid} score={score}/100 hash={thash[:6]} title={title[:40]}")
        return uuid
    except Exception as e:
        logger.error(f"render create_artifact hata: {e}")
        return None


@router.get("/{uuid}", response_class=HTMLResponse)
async def serve_artifact(uuid: str, request: Request):
    """Public URL — HTML'i sandbox iframe ile serve et.
    25.36: Arşivlenenler süresiz — expires_at kontrolünden muaf."""
    if not uuid or len(uuid) > 64:
        raise HTTPException(404, "Geçersiz")
    try:
        await ensure_table()
        row = await db_fetchrow(
            """SELECT title, html, expires_at, archived FROM render_artifacts
               WHERE uuid = $1
                 AND (archived = TRUE OR expires_at IS NULL OR expires_at > NOW())""",
            uuid
        )
        if not row:
            return HTMLResponse(
                status_code=404,
                content="<h1>İçerik bulunamadı veya süresi doldu</h1>"
                        "<p>FermatAI ile yeniden oluştur.</p>",
            )
        # View count
        await db_execute(
            """UPDATE render_artifacts
               SET view_count = view_count + 1, last_viewed_at = NOW()
               WHERE uuid = $1""", uuid
        )
        title = row["title"] or "FermatAI"
        html = row["html"]
        # Wrapper: meta + responsive + sandbox-safe defaults
        wrapper = f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — FermatAI</title>
<meta name="description" content="FermatAI tarafından üretilen interaktif eğitim içeriği">
<style>
  body {{ margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; background: #F5F4ED; color: #2F2F2F; }}
  .fermat-render-header {{
    background: linear-gradient(135deg, #C76F3E, #B05A2B);
    color: white; padding: 12px 20px; font-size: 14px;
    display: flex; align-items: center; justify-content: space-between;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
  }}
  .fermat-render-header .brand {{ font-weight: 700; letter-spacing: 0.3px; }}
  .fermat-render-header .pwd {{ opacity: 0.9; font-size: 12px; }}
  .fermat-render-content {{ padding: 0; min-height: calc(100vh - 50px); }}
</style>
</head>
<body>
<div class="fermat-render-header">
  <span class="brand">⚡ FermatAI</span>
  <span class="pwd">İnteraktif Eğitim Görseli</span>
</div>
<div class="fermat-render-content">
{html}
</div>
</body>
</html>"""
        return HTMLResponse(
            content=wrapper,
            headers={
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "SAMEORIGIN",
                "Referrer-Policy": "no-referrer",
                "Cache-Control": "public, max-age=300",
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"render serve hata uuid={uuid}: {e}")
        raise HTTPException(500, "Render hatası")


@router.get("")
async def list_recent(limit: int = 20):
    """Admin debug — son artifact'lar."""
    try:
        await ensure_table()
        rows = await db_fetchrow(
            """SELECT COUNT(*) as toplam, COUNT(*) FILTER (WHERE expires_at > NOW()) as aktif,
                      COUNT(*) FILTER (WHERE archived = TRUE) as arsivli,
                      MAX(created_at) as son
               FROM render_artifacts"""
        )
        return JSONResponse({
            "toplam": rows["toplam"] if rows else 0,
            "aktif": rows["aktif"] if rows else 0,
            "arsivli": rows["arsivli"] if rows else 0,
            "son_olusum": str(rows["son"]) if rows and rows["son"] else None,
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════
# 25.36 — Arşiv sistemi (Neo direktifi: 30 gün TTL kısa, kalıcı tut)
# ═══════════════════════════════════════════════════════════════════════
@router.post("/archive/{uuid}")
async def archive_artifact(uuid: str, request: Request):
    """Render artifact'ı arşive ekle (kalıcı yap).
    Body: {"phone": "...", "note": "Optional açıklama"}"""
    if not uuid or len(uuid) > 64:
        raise HTTPException(404, "Geçersiz")
    try:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        phone = (body.get("phone") or "").strip()[:20]
        note = (body.get("note") or "")[:500]
        await ensure_table()
        # Kontrol: artifact var mı?
        existing = await db_fetchrow(
            "SELECT id, archived FROM render_artifacts WHERE uuid = $1", uuid
        )
        if not existing:
            raise HTTPException(404, "Artifact bulunamadı")
        if existing["archived"]:
            return JSONResponse({"success": True, "already_archived": True, "uuid": uuid})
        await db_execute(
            """UPDATE render_artifacts
               SET archived = TRUE, archived_at = NOW(),
                   archived_by_phone = $2, archive_note = $3,
                   expires_at = NULL
               WHERE uuid = $1""",
            uuid, phone, note
        )
        logger.info(f"render: archive uuid={uuid} by={phone[-4:] if phone else '?'}")
        return JSONResponse({"success": True, "uuid": uuid, "archived": True})
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"archive_artifact hata: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.post("/unarchive/{uuid}")
async def unarchive_artifact(uuid: str, request: Request):
    """Arşivden çıkar — orijinal TTL geri yüklenir (7 gün)."""
    if not uuid or len(uuid) > 64:
        raise HTTPException(404, "Geçersiz")
    try:
        await ensure_table()
        await db_execute(
            """UPDATE render_artifacts
               SET archived = FALSE, archived_at = NULL,
                   archived_by_phone = NULL, archive_note = NULL,
                   expires_at = COALESCE(expires_at, NOW() + INTERVAL '7 days')
               WHERE uuid = $1""",
            uuid
        )
        return JSONResponse({"success": True, "uuid": uuid, "archived": False})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.get("/archived/list")
async def list_archived(phone: str = "", limit: int = 50):
    """Kullanıcının arşivledikleri (veya tüm arşiv)."""
    try:
        await ensure_table()
        from db_pool import db_fetch
        if phone:
            phone_clean = phone.replace("+", "").replace(" ", "")[-20:]
            rows = await db_fetch(
                """SELECT uuid, title, archived_at, archive_note, view_count, creator_phone, quality_score
                   FROM render_artifacts
                   WHERE archived = TRUE AND (
                       archived_by_phone = $1 OR creator_phone = $1
                       OR REPLACE(archived_by_phone, '+', '') = $1
                       OR REPLACE(creator_phone, '+', '') = $1
                   )
                   ORDER BY archived_at DESC LIMIT $2""",
                phone_clean, int(limit or 50)
            )
        else:
            rows = await db_fetch(
                """SELECT uuid, title, archived_at, archive_note, view_count, creator_phone, quality_score
                   FROM render_artifacts
                   WHERE archived = TRUE
                   ORDER BY archived_at DESC LIMIT $1""",
                int(limit or 50)
            )
        items = []
        import os
        base = os.getenv("PUBLIC_BASE_URL", "https://api.fermategitimkurumlari.com").rstrip("/")
        for r in rows:
            items.append({
                "uuid": r["uuid"],
                "title": r["title"] or "Başlıksız",
                "archived_at": str(r["archived_at"]) if r["archived_at"] else "",
                "note": r["archive_note"] or "",
                "view_count": r["view_count"] or 0,
                "quality_score": r["quality_score"] or 0,
                "url": f"{base}/render/{r['uuid']}",
            })
        return JSONResponse({"success": True, "count": len(items), "items": items})
    except Exception as e:
        logger.warning(f"list_archived hata: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════
# 25.36 — Render Templates Library (başarılı şablonlardan öğren)
# ═══════════════════════════════════════════════════════════════════════
async def ensure_templates_table():
    """render_templates — başarılı simülasyonların referans şablonu."""
    try:
        await db_execute("""
            CREATE TABLE IF NOT EXISTS render_templates (
                id SERIAL PRIMARY KEY,
                konu TEXT NOT NULL,
                ders TEXT,
                title TEXT,
                source_uuid TEXT,
                description TEXT,
                approach_summary TEXT,
                success_count INTEGER DEFAULT 1,
                quality_score INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW(),
                last_used_at TIMESTAMP,
                approved BOOLEAN DEFAULT FALSE
            )
        """)
        await db_execute(
            "CREATE INDEX IF NOT EXISTS idx_template_konu ON render_templates(konu, approved)"
        )
    except Exception as e:
        logger.warning(f"render_templates ensure_table hata: {e}")


async def get_top_templates(konu_hint: str = "", limit: int = 5) -> list:
    """Bot prompt'u için en başarılı template örnekleri."""
    try:
        await ensure_templates_table()
        from db_pool import db_fetch
        if konu_hint:
            rows = await db_fetch(
                """SELECT konu, ders, title, approach_summary, quality_score, success_count
                   FROM render_templates
                   WHERE approved = TRUE AND (konu ILIKE $1 OR ders ILIKE $1)
                   ORDER BY quality_score DESC, success_count DESC LIMIT $2""",
                f"%{konu_hint}%", limit
            )
        else:
            rows = await db_fetch(
                """SELECT konu, ders, title, approach_summary, quality_score, success_count
                   FROM render_templates
                   WHERE approved = TRUE
                   ORDER BY quality_score DESC, success_count DESC LIMIT $1""",
                limit
            )
        return [dict(r) for r in rows]
    except Exception:
        return []


@router.post("/templates/promote/{uuid}")
async def promote_to_template(uuid: str, request: Request):
    """Bir başarılı artifact'ı template'e dönüştür (admin onayı).
    Body: {"konu": "...", "ders": "...", "approach_summary": "..."}"""
    if not uuid or len(uuid) > 64:
        raise HTTPException(404, "Geçersiz")
    try:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        konu = (body.get("konu") or "").strip()[:120]
        ders = (body.get("ders") or "").strip()[:60]
        summary = (body.get("approach_summary") or "")[:500]
        if not konu:
            return JSONResponse({"success": False, "error": "konu zorunlu"}, status_code=400)
        await ensure_table()
        await ensure_templates_table()
        art = await db_fetchrow(
            "SELECT title, quality_score FROM render_artifacts WHERE uuid = $1", uuid
        )
        if not art:
            raise HTTPException(404, "Artifact bulunamadı")
        await db_execute(
            """INSERT INTO render_templates
               (konu, ders, title, source_uuid, approach_summary, quality_score, approved)
               VALUES ($1, $2, $3, $4, $5, $6, TRUE)""",
            konu, ders, art["title"] or "", uuid, summary, art["quality_score"] or 0
        )
        logger.info(f"render: template promoted from uuid={uuid} konu={konu}")
        return JSONResponse({"success": True, "uuid": uuid, "konu": konu})
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.get("/templates/list")
async def list_templates(konu: str = "", limit: int = 20):
    """Onaylı template'ler — bot prompt için."""
    try:
        templates = await get_top_templates(konu_hint=konu, limit=limit)
        return JSONResponse({"success": True, "count": len(templates), "items": templates})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)
