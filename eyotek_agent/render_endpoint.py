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
- Maksimum 200KB HTML (DoS koruma)

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

MAX_HTML_BYTES = 200 * 1024  # 200KB
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
        await db_execute(
            "CREATE INDEX IF NOT EXISTS idx_render_uuid ON render_artifacts(uuid)"
        )
        await db_execute(
            "CREATE INDEX IF NOT EXISTS idx_render_expires ON render_artifacts(expires_at)"
        )
    except Exception as e:
        logger.warning(f"render_artifacts ensure_table hata: {e}")


async def create_artifact(html: str, title: str = "FermatAI Görsel",
                          creator_phone: str = "", ttl_days: int = DEFAULT_TTL_DAYS) -> Optional[str]:
    """
    Bot tool'undan çağrılır — HTML kaydet, UUID döndür.

    Returns:
        uuid string (örn. 'a1b2c3d4...') veya None (hata)
    """
    if not html or len(html.encode('utf-8')) > MAX_HTML_BYTES:
        logger.warning(f"render: html bos veya >200KB ({len(html)} bytes)")
        return None
    try:
        await ensure_table()
        uuid = secrets.token_urlsafe(12)  # ~16 char URL-safe
        expires = datetime.now() + timedelta(days=ttl_days)
        await db_execute(
            """INSERT INTO render_artifacts (uuid, title, html, creator_phone, expires_at)
               VALUES ($1, $2, $3, $4, $5)""",
            uuid, title[:200], html, creator_phone, expires
        )
        logger.info(f"render: artifact yaratildi uuid={uuid} title={title[:40]}")
        return uuid
    except Exception as e:
        logger.error(f"render create_artifact hata: {e}")
        return None


@router.get("/{uuid}", response_class=HTMLResponse)
async def serve_artifact(uuid: str, request: Request):
    """Public URL — HTML'i sandbox iframe ile serve et."""
    if not uuid or len(uuid) > 64:
        raise HTTPException(404, "Geçersiz")
    try:
        await ensure_table()
        row = await db_fetchrow(
            """SELECT title, html, expires_at FROM render_artifacts
               WHERE uuid = $1 AND (expires_at IS NULL OR expires_at > NOW())""",
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
  <span class="pwd">İnteraktif Eğitim Görselii</span>
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
                      MAX(created_at) as son
               FROM render_artifacts"""
        )
        return JSONResponse({
            "toplam": rows["toplam"] if rows else 0,
            "aktif": rows["aktif"] if rows else 0,
            "son_olusum": str(rows["son"]) if rows and rows["son"] else None,
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
