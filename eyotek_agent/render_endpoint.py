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


def calculate_quality_score(html: str, title: str = "") -> tuple[int, dict]:
    """25.39 — HTML kalite puanı (100) + breakdown (Neo: max kalite zorunlu).

    25.40z3-RENDER-FIX (Neo bug 4 May 18:32 "gene bomboş çıktı"):
    - three@0.149+ /examples/js/ DEPRECATED → 404 → silent JS fail → BOŞ canvas
    - Doğru: three@0.147 (UMD destekli son versiyon) → /examples/js/ HTTP 200
    - Eğer HTML 0.149+ + /examples/js/ kombinasyonu içeriyor → -40 puan + uyarı
    """
    if not html:
        return 0, {"reason": "empty"}
    h = html.lower()
    title_lower = (title or "").lower()
    breakdown = {}
    score = 0

    # 25.40z3-RENDER-FIX: CDN URL guard (Neo "gene bomboş" bug)
    # Three.js 0.149+ ESM-only, examples/js/ kalktı. Bot bu kombinasyonu kullanırsa
    # OrbitControls 404 → silent fail → boş canvas. Otomatik puan kesimi:
    import re as _re_check
    bad_three_combo = bool(_re_check.search(r'three@0\.(149|15\d|16\d|17\d|18\d|19\d|2\d{2})/examples/js/', h))
    if bad_three_combo:
        breakdown["cdn_warning"] = "three@0.149+/examples/js/ DEPRECATED — silent fail riski (-40 puan)"
        breakdown["cdn_fix"] = "three@0.147 kullan (UMD destekli son versiyon, examples/js/ çalışır)"

    # Title'dan render tipi tahmini
    is_3d_request = any(k in title_lower for k in [
        "3d", "simulasyon", "simülasyon", "evrim", "yıldız", "yildiz",
        "galaksi", "kuantum", "kara delik", "molekül", "molekul",
        "atom", "evren", "kozmik", "uzay", "yörünge", "yorunge",
    ])

    # ─── Gerçek 3D scene kontrolü (Neo: simulasyonda ZORUNLU) ───────────────
    has_three_scene = "new three.scene" in h or "= new scene(" in h
    has_camera = any(k in h for k in [
        "perspectivecamera", "orthographiccamera", "camera = new", "new threee.perspectivecamera"
    ])
    has_renderer = any(k in h for k in [
        "webglrenderer", "renderer = new", "renderer.setsize", "canvasrenderer"
    ])
    has_scene_add = "scene.add" in h or ".add(mesh" in h or "add(this.scene" in h
    has_animate_loop = "requestanimationframe" in h
    has_3d_objects = any(k in h for k in [
        "new three.mesh", "new three.points", "buffergeometry", "spheregeometry",
        "boxgeometry", "planegeometry", "linegeometry", "torusgeometry"
    ])
    has_lights = any(k in h for k in [
        "ambientlight", "pointlight", "directionallight", "spotlight", "hemispherelight"
    ])
    has_controls = any(k in h for k in [
        "orbitcontrols", "trackballcontrols", "flycontrols", "controls.update"
    ])

    is_real_3d = has_three_scene and has_camera and has_renderer and has_scene_add and has_3d_objects
    breakdown["3d_scene_complete"] = is_real_3d
    breakdown["3d_components"] = {
        "Scene": has_three_scene, "Camera": has_camera, "Renderer": has_renderer,
        "scene.add": has_scene_add, "3D objects": has_3d_objects,
        "Lights": has_lights, "Controls": has_controls, "animate()": has_animate_loop,
    }

    # ─── PUANLAMA ───────────────────────────────────────────────────────────
    # 1. Görsel motor (+30 max)
    if is_real_3d:
        # Tam 3D scene → 30 puan
        score += 30; breakdown["visual_engine"] = "3D_complete"
    elif "<canvas" in h and ("getcontext" in h or "ctx.fillrect" in h or "ctx.beginpath" in h):
        # 2D Canvas API kullanımı (gerçek çizim)
        score += 22; breakdown["visual_engine"] = "2D_canvas"
    elif "<svg" in h and ("<circle" in h or "<rect" in h or "<path" in h or "<line" in h):
        # SVG gerçek geometri
        score += 20; breakdown["visual_engine"] = "SVG"
    elif "p5." in h or "babylon" in h:
        score += 18; breakdown["visual_engine"] = "framework_detected"
    elif "<canvas" in h or "<svg" in h:
        # Sadece tag, gerçek çizim yok
        score += 8; breakdown["visual_engine"] = "empty_canvas/svg"

    # 2. Animation (+15)
    if has_animate_loop:
        score += 15; breakdown["animation"] = True
    elif "@keyframes" in h or "gsap." in h or "tween" in h:
        score += 8; breakdown["animation"] = "css_only"

    # 3. User interaction (+15)
    interaction_patterns = ['type="range"', 'type="button"', "<button", "onclick=",
                            "addeventlistener", "oninput", "onchange", "onmousedown"]
    interaction_count = sum(1 for p in interaction_patterns if p in h)
    if interaction_count >= 3:
        score += 15; breakdown["interaction"] = "rich"
    elif interaction_count >= 1:
        score += 8; breakdown["interaction"] = "basic"

    # 4. Lights + Controls (3D bonus) (+10)
    if is_real_3d and has_lights and has_controls:
        score += 10; breakdown["3d_polish"] = "lights_and_controls"
    elif is_real_3d and (has_lights or has_controls):
        score += 5; breakdown["3d_polish"] = "partial"

    # 5. Error handling (+5)
    if "try" in h and "catch" in h:
        score += 5; breakdown["error_handling"] = True

    # 6. Responsive (+5)
    if "viewport" in h and ("width=device-width" in h or "100%" in h):
        score += 5; breakdown["responsive"] = True

    # 7. Formula/Math (+5)
    if any(k in h for k in ["katex", "mathjax", "math.sin", "math.cos", "math.pi", "\\frac"]):
        score += 5; breakdown["formula"] = True

    # 8. Optimal size (10-600KB) (+5)
    size_kb = len(html.encode("utf-8")) / 1024
    if 10 <= size_kb <= 600:
        score += 5; breakdown["optimal_size"] = True
    elif size_kb < 10:
        breakdown["optimal_size"] = "TOO_SMALL"

    # 9. Labels/UI (+5)
    if any(k in h for k in ["<label", "<h1", "<h2", "<h3", "info", "title"]):
        score += 5; breakdown["labels"] = True

    # 10. Pedagojik içerik (+5) — formül, açıklama, etiketler
    if all(k in h for k in ["<h", "<p"]) and any(k in h for k in ["açıklama", "formül", "formula", "info"]):
        score += 5; breakdown["pedagogical"] = True

    # ─── 11. AKADEMİK SEVİYE — Neo 25.40 direktif (+10 max) ──────────────
    # Lise son + üniversite hazırlık standardı: gerçek formül + sabit + paragraf
    physics_constants_used = sum(1 for c in [
        "6.67", "2.998", "1.989", "1.381", "1.055", "3.828",  # G, c, M☉, k_B, ℏ, L_☉
    ] if c in h)
    has_katex_formula = "katex.render" in h or "\\\\frac" in h or "$$" in h
    has_paragraphs = h.count("<p") >= 3
    advanced_terms = sum(1 for term in [
        "schwarzschild", "tolman", "oppenheim", "eddington", "doppler",
        "lensing", "akresyon", "accretion", "horizon", "ergosphere",
        "magnetar", "pulsar", "quark", "neutrino", "redshift", "blueshift",
        "kepler", "newton", "einstein", "planck", "compton",
    ] if term in h)
    academic_bonus = 0
    if physics_constants_used >= 2: academic_bonus += 3
    if has_katex_formula: academic_bonus += 4
    if has_paragraphs: academic_bonus += 2
    if advanced_terms >= 3: academic_bonus += 3
    academic_bonus = min(academic_bonus, 12)  # max 12 bonus
    if academic_bonus > 0:
        score += academic_bonus
        breakdown["academic_level"] = {
            "physics_constants": physics_constants_used,
            "katex_formula": has_katex_formula,
            "paragraphs_3+": has_paragraphs,
            "advanced_terms": advanced_terms,
            "bonus_added": academic_bonus,
        }

    # ─── 12. RESPONSIVE LAYOUT — Neo bug 25.40 (max +5) ──────────────────
    # Tam ekran butonlar sığmıyordu; layout zorunlulukları
    layout_score = 0
    if "viewport" in h and "device-width" in h: layout_score += 1
    if "@media" in h: layout_score += 2
    if "position: fixed" in h or "position:fixed" in h: layout_score += 1
    if "z-index" in h: layout_score += 1
    if layout_score > 0:
        score += layout_score
        breakdown["layout_responsive"] = layout_score

    # ─── KRITIK CEZALAR (Neo: simulasyon istendi ama yok) ───────────────────
    if is_3d_request and not is_real_3d:
        # Simulasyon istendi ama 3D scene yok — TAVAN 30
        original = score
        score = min(score, 30)
        breakdown["penalty"] = f"3D_REQUEST_BUT_NO_SCENE (orig {original} → max 30)"

    if size_kb < 5:
        score = min(score, 15)
        breakdown["penalty"] = breakdown.get("penalty", "") + " | TOO_TINY"

    # 25.40z3-RENDER-FIX: CDN bozuk → silent fail → TAVAN 25 (Neo "gene bomboş")
    if bad_three_combo:
        original = score
        score = min(score, 25)
        breakdown["penalty"] = breakdown.get("penalty", "") + f" | BAD_THREE_CDN (orig {original} → max 25, three@0.149+ + examples/js/ = 404)"

    # 25.40z3-RENDER-FIX: Blueprint/node-graph 3D ama içerik az (Neo bug "3D oldu içerik koyamadı")
    # Title'da blueprint/mimari/sistem/grafiğ varsa + 3D scene var ama ICERIK az → TAVAN 60
    is_blueprint_request = any(k in title_lower for k in [
        "blueprint", "mimari", "sistem", "ağ", "graf", "neural", "node",
        "bilgi grafı", "infographic", "yapı", "harita",
    ])
    if is_blueprint_request and is_real_3d:
        # Içerik metriği: NODES + paneller + click handler + tooltip + sub-info
        content_indicators = sum([
            h.count("nodes") >= 3,           # NODES dizisi
            h.count("desc") >= 5,            # node açıklamaları
            h.count("meta") >= 5,            # meta bilgiler
            "subs" in h or "children" in h,  # alt-node yapısı
            "raycaster" in h,                # click detection
            h.count("innerhtml") >= 3,       # dinamik panel doldurma
            "tooltip" in h or "panel" in h,  # info panel UI
            len(html.encode('utf-8')) >= 35_000,  # min 35KB rich content
        ])
        breakdown["blueprint_content"] = f"{content_indicators}/8 zenginlik göstergesi"
        if content_indicators < 4:
            original = score
            score = min(score, 60)
            breakdown["penalty"] = breakdown.get("penalty", "") + f" | BLUEPRINT_LIGHT_CONTENT (orig {original} → max 60, {content_indicators}/8 zenginlik; NODES/desc/raycaster/panel ekle)"

    # Cap to 100
    score = min(score, 100)
    breakdown["total_score"] = score
    breakdown["size_kb"] = round(size_kb, 1)
    breakdown["is_3d_request"] = is_3d_request
    breakdown["is_real_3d"] = is_real_3d
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
    """Aynı title ile son N gün içinde HIGH-QUALITY render var mı?

    Returns: {'uuid', 'title', 'quality_score', 'created_at'} veya None

    25.37 (Neo): Newton 2. yasa 1 kez üret, 1000 kişiye sun.
    25.39 (Neo bug fix): 3D/simulasyon istekleri için cache eşiği SIKILAŞTI
        — score >= 75 (eski 60). Eski scorer 90 puan veriyordu boş 3D'ye,
        bu yüzden aynı boş cache yeniden dönüyordu. Yeni scorer ile DB'deki
        yanlış score'lu kayıtlar 30'a düşürüldü, artık reuse edilmiyor.
    """
    try:
        await ensure_table()
        thash = _topic_hash(title or "")
        # 3D / simulasyon istekleri için min eşik 75 (kalite garantisi)
        title_lower = (title or "").lower()
        is_3d_request = any(k in title_lower for k in [
            "3d", "simulasyon", "simülasyon", "evrim", "yıldız", "yildiz",
            "galaksi", "kuantum", "kara delik", "molekül", "molekul",
            "atom", "evren", "kozmik", "uzay", "yörünge", "yorunge",
        ])
        min_score = 75 if is_3d_request else 60
        row = await db_fetchrow(
            """SELECT uuid, title, quality_score, created_at, expires_at, archived
               FROM render_artifacts
               WHERE topic_hash = $1
                 AND (archived = TRUE OR expires_at > NOW())
                 AND quality_score >= $3
                 AND created_at > NOW() - ($2::int * INTERVAL '1 day')
               ORDER BY quality_score DESC, created_at DESC LIMIT 1""",
            thash, max_age_days, min_score,
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
        # 25.36 — kalite skoru (25.39: title da geçiyor — 3D/simulasyon istek tespiti için)
        score, breakdown = calculate_quality_score(html, title=title or "")
        # 25.37 — topic_hash
        thash = _topic_hash(title or "")

        # 25.41 (Neo direktif): TÜM ROLLER İÇİN PREMİUM KALİTE
        # 3D/simulasyon istekleri için min_score 60 — altı atlasta kayda alınır
        # Düşük kaliteli render üretildiğinde Neo'ya alarm (atlas_observations)
        title_lower = (title or "").lower()
        is_3d_request = any(k in title_lower for k in [
            "3d", "simulasyon", "simülasyon", "evrim", "yıldız", "yildiz",
            "galaksi", "kuantum", "kara delik", "molekül", "molekul",
            "atom", "evren", "kozmik", "uzay", "yörünge", "yorunge",
        ])
        if is_3d_request and score < 60:
            logger.warning(
                f"⚠️  LOW-QUALITY 3D RENDER (score={score}/100) — title='{title[:50]}' "
                f"creator={creator_phone[-4:] if creator_phone else 'N/A'}. "
                f"Breakdown: {breakdown}. Neo direktif: ROL BAĞIMSIZ premium hedefi."
            )
            # Atlas'a kaydet — Neo trend takibi için
            try:
                await db_execute(
                    """INSERT INTO atlas_observations (kategori, baslik, detay, severity, created_at)
                       VALUES ('render_quality', $1, $2, 'warning', NOW())""",
                    f"Düşük kaliteli 3D render: score={score}",
                    f"title={title[:100]} | creator={creator_phone[-4:] if creator_phone else 'N/A'} | "
                    f"breakdown={breakdown}"
                )
            except Exception:
                pass  # atlas tablosu yoksa sessiz fail

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
  /* 25.47 (Neo 22 May — Bug #140): render sayfasında geri dönüş yoktu, sekme kapatmak
     gerekiyordu. Header'a 44px dokunmatik-dostu "Geri" butonu. */
  .fermat-render-header .back-btn {{
    background: rgba(255,255,255,0.18); color:#fff; border:1px solid rgba(255,255,255,0.35);
    border-radius:8px; padding:8px 14px; font-size:14px; font-weight:600; cursor:pointer;
    min-height:40px; display:inline-flex; align-items:center; gap:4px;
    -webkit-tap-highlight-color:transparent;
  }}
  .fermat-render-header .back-btn:active {{ background: rgba(255,255,255,0.32); }}
</style>
</head>
<body>
<div class="fermat-render-header">
  <button class="back-btn" onclick="fermatGoBack()" title="Geri dön">← Geri</button>
  <span class="brand">⚡ FermatAI</span>
  <span class="pwd">İnteraktif Eğitim Görseli</span>
</div>
<div class="fermat-render-content">
{html}
</div>
<script>
function fermatGoBack() {{
  try {{
    var sameHost = document.referrer && document.referrer.indexOf(location.host) !== -1;
    if (sameHost && window.history.length > 1) {{ window.history.back(); return; }}
  }} catch (e) {{}}
  // Yeni sekmede açıldıysa kapatmayı dene; olmazsa ana sohbete dön.
  window.close();
  setTimeout(function() {{ if (!window.closed) location.href = '/chat'; }}, 200);
}}
</script>
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
    Body: {"phone": "...", "note": "...", "name": "...", "category": "..."}

    Oturum 25.39 (Neo): Kategori + isim opsiyonel parametreler.
    name → render_artifacts.title güncellenir (kullanıcının verdiği isim).
    category + note → archive_note JSON formatında saklanır."""
    if not uuid or len(uuid) > 64:
        raise HTTPException(404, "Geçersiz")
    try:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        phone = (body.get("phone") or "").strip()[:20]
        raw_note = (body.get("note") or "")[:600]
        name = (body.get("name") or "").strip()[:80]
        category = (body.get("category") or "").strip()[:30]

        # Note: eğer JSON ise direkt kabul et, değilse kategori + note birleştir
        note_payload = raw_note
        if not raw_note.startswith("{"):
            # Eski API uyumlu: sadece note geldiyse (kategori yok), JSON'a wrap et
            import json as _j
            note_payload = _j.dumps({
                "name": name, "category": category, "note": raw_note,
            }, ensure_ascii=False)

        await ensure_table()
        existing = await db_fetchrow(
            "SELECT id, archived, title FROM render_artifacts WHERE uuid = $1", uuid
        )
        if not existing:
            raise HTTPException(404, "Artifact bulunamadı")
        if existing["archived"]:
            return JSONResponse({"success": True, "already_archived": True, "uuid": uuid})

        # Eğer kullanıcı isim verdiyse title'ı güncelle (eski title default'tu)
        if name:
            await db_execute(
                """UPDATE render_artifacts
                   SET archived = TRUE, archived_at = NOW(),
                       archived_by_phone = $2, archive_note = $3,
                       title = $4,
                       expires_at = NULL
                   WHERE uuid = $1""",
                uuid, phone, note_payload, name,
            )
        else:
            await db_execute(
                """UPDATE render_artifacts
                   SET archived = TRUE, archived_at = NOW(),
                       archived_by_phone = $2, archive_note = $3,
                       expires_at = NULL
                   WHERE uuid = $1""",
                uuid, phone, note_payload,
            )
        logger.info(f"render: archive uuid={uuid} by={phone[-4:] if phone else '?'} "
                    f"name='{name[:30]}' cat={category}")
        return JSONResponse({
            "success": True, "uuid": uuid, "archived": True,
            "name": name or existing["title"], "category": category,
        })
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
        logger.warning(f"unarchive_artifact hata: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════
# 25.40z3-ARSIV: Render artifact KALICI silme (sadece sahibi)
# ═══════════════════════════════════════════════════════════════════════
@router.post("/delete/{uuid}")
async def delete_artifact(uuid: str, request: Request):
    """Render artifact'ı KALICI sil — sadece sahibi (creator_phone) silebilir.

    25.40z3-ARSIV: Neo direktifi: "Arşivlediğim simülasyonlar kalıcı olsun,
    ne zaman silersem o zaman silinsin."

    Phone kaynağı (öncelik sırası):
    1. Body {"phone": "..."} (mobile/script çağrısı)
    2. Session cookie 'fermat_session' → web_chat session lookup (web UI çağrısı)

    Güvenlik: phone NORMALIZE edilip creator_phone VEYA archived_by_phone
    ile eşleşmeli, yoksa 403 Forbidden.
    """
    if not uuid or len(uuid) > 64:
        raise HTTPException(404, "Geçersiz")
    try:
        # Phone tespit (body veya session)
        phone = ""
        try:
            body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
            phone = (body.get("phone") or "").strip()[:20]
        except Exception:
            body = {}

        if not phone:
            # Session cookie'den dene
            try:
                from web_chat import COOKIE_NAME, get_session, _extract_token
                token = _extract_token(request, request.cookies.get(COOKIE_NAME))
                if token:
                    sess = await get_session(token)
                    if sess:
                        phone = (sess.get("phone") or "")[:20]
            except Exception:
                pass

        if not phone:
            raise HTTPException(401, "phone gerekli (body veya session)")

        # Sahip kontrolü
        phone_clean = phone.replace("+", "").replace(" ", "")[-20:]
        existing = await db_fetchrow(
            """SELECT uuid, creator_phone, archived_by_phone, archived, title
               FROM render_artifacts WHERE uuid = $1""",
            uuid,
        )
        if not existing:
            raise HTTPException(404, "Artifact bulunamadı")

        creator_clean = (existing["creator_phone"] or "").replace("+", "").replace(" ", "")[-20:]
        archiver_clean = (existing["archived_by_phone"] or "").replace("+", "").replace(" ", "")[-20:]
        if phone_clean not in (creator_clean, archiver_clean):
            raise HTTPException(403, "Sadece sahip silebilir")

        # KALICI sil
        await db_execute("DELETE FROM render_artifacts WHERE uuid = $1", uuid)
        logger.info(f"render: 🗑 DELETE uuid={uuid} by={phone[-4:]} title='{(existing['title'] or '')[:40]}'")
        return JSONResponse({
            "success": True, "uuid": uuid, "deleted": True,
            "title": existing["title"],
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"delete_artifact hata: {e}")
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
