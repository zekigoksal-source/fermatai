"""
FermatAI Web Chat — FastAPI Router
====================================
Wix'e iframe ile gömülebilir chat arayüzü için backend route'ları.
whatsapp_bridge.py tarafından include edilir.

Route'lar (prefix /chat):
  GET  /chat               → HTML (login + chat UI, web_chat_ui.html)
  POST /chat/verify-otp    → OTP doğrula, cookie ver
  POST /chat/send          → Non-streaming mesaj gönder (Faz 1)
  GET  /chat/stream        → SSE streaming (Faz 2, şimdilik placeholder)
  GET  /chat/me            → Session bilgisi
  POST /chat/logout        → Session sonlandır

OTP gönderimi whatsapp_bridge.py fast_responses üzerinden — öğrenci WP'den
"web kodu" yazar, bot 6 haneli kod gönderir.
"""
import asyncio
import json
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request, Response, Cookie, HTTPException, status, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
from loguru import logger

from web_chat_auth import verify_otp, get_session, logout as auth_logout, list_active_sessions, logout_all

router = APIRouter(prefix="/chat", tags=["web-chat"])

HTML_FILE = Path(__file__).parent / "web_chat_ui.html"
COOKIE_NAME = "fermat_session"


# ─── Hybrid Auth — Cookie VEYA Header VEYA URL ?token= ──
# iOS Safari ITP iframe 3rd-party cookie'yi blokluyor. Fallback olarak
# Authorization: Bearer {token} header'ı da kabul ediyoruz.
# Oturum 25.10c (Neo dev erisimi): URL ?token= parametresi de destek
def _extract_token(request: Request, cookie_token: Optional[str]) -> Optional[str]:
    """Request'ten token çıkar: önce cookie, yoksa header, en son URL ?token=."""
    if cookie_token:
        return cookie_token
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:].strip()
    # X-Fermat-Token custom header de destekle (fallback)
    custom = request.headers.get("x-fermat-token", "")
    if custom:
        return custom.strip()
    # URL ?token= parametresi (Neo dev hizli erisim icin)
    qp_token = request.query_params.get("token", "")
    if qp_token:
        return qp_token.strip()
    return None


# ─── Schemas ──────────────────────────────────────────────

class VerifyOtpReq(BaseModel):
    phone: str
    otp: str


class SendMsgReq(BaseModel):
    message: str
    # 22.1n-fikir4: Arşiv oturumu devam — hangi günün mesajlarını context'e ekleyelim
    archive_day: Optional[str] = None  # "2026-04-15" gibi, varsa o günün mesajları context'e eklenir


# ─── Routes ───────────────────────────────────────────────

@router.get("/manifest.json")
async def pwa_manifest():
    """PWA manifest — telefona icon olarak sabitlenebilir uygulama.

    Oturum 25.40 (Neo): PNG iconlar + ABSOLUTE URL'ler.
    Sebep: Wix iframe-embed sayfasından (fermategitimkurumlari.com/fermatai)
    yüklendiğinde scope karışıyordu. Absolute URL'lerle PWA HER ZAMAN
    api.fermategitimkurumlari.com/chat'e yönlenir → Wix splash atlatılır.
    """
    BASE = "https://api.fermategitimkurumlari.com"
    manifest = {
        "name": "FermatAI — Akademik Koç",
        "short_name": "FermatAI",
        "description": "Fermat Eğitim Kurumları — Pedagojik Yapay Zeka Asistanı",
        # ABSOLUTE: Wix iframe parent atlatılır, direkt chat yüklenir
        "start_url": f"{BASE}/chat",
        "id": f"{BASE}/chat",  # PWA unique ID
        "scope": f"{BASE}/",
        "display": "standalone",
        "orientation": "portrait",
        # Splash background — dark theme uyumlu, FermatAI premium hissi
        "background_color": "#0F172A",
        "theme_color": "#C76F3E",
        "lang": "tr",
        "dir": "ltr",
        "icons": [
            {"src": f"{BASE}/static/img/fermatai-192.png", "sizes": "192x192",
             "type": "image/png", "purpose": "any"},
            {"src": f"{BASE}/static/img/fermatai-512.png", "sizes": "512x512",
             "type": "image/png", "purpose": "any"},
            {"src": f"{BASE}/static/img/fermatai-192-maskable.png", "sizes": "192x192",
             "type": "image/png", "purpose": "maskable"},
            {"src": f"{BASE}/static/img/fermatai-512-maskable.png", "sizes": "512x512",
             "type": "image/png", "purpose": "maskable"},
        ],
        "categories": ["education", "productivity"],
        "shortcuts": [
            {
                "name": "Yeni Soru Sor",
                "short_name": "Soru",
                "description": "Hemen yeni bir akademik soru sor",
                "url": f"{BASE}/chat?q=sor",
                "icons": [{"src": f"{BASE}/static/img/fermatai-shortcut-96.png", "sizes": "96x96"}],
            },
            {
                "name": "Çalışmam Paneli",
                "short_name": "Çalışmam",
                "description": "Günlük çalışma paneline git",
                "url": f"{BASE}/student-daily",
                "icons": [{"src": f"{BASE}/static/img/fermatai-shortcut-96.png", "sizes": "96x96"}],
            },
        ],
        "screenshots": [],
        "display_override": ["standalone", "minimal-ui"],
        "prefer_related_applications": False,
    }
    response = JSONResponse(manifest)
    response.headers["Cache-Control"] = "public, max-age=3600"
    return response


@router.get("/service-worker.js")
async def service_worker():
    """PWA Service Worker — offline cache + push notification.
    Oturum 25.40 (Neo): Render artifact'leri offline çalışsın diye SW.
    """
    sw_path = Path(__file__).parent / "static" / "service-worker.js"
    if not sw_path.exists():
        raise HTTPException(status_code=404, detail="service-worker.js bulunamadı")
    from fastapi.responses import FileResponse
    response = FileResponse(
        path=str(sw_path),
        media_type="application/javascript",
    )
    # SW dosyası — Service-Worker-Allowed scope geniş
    response.headers["Service-Worker-Allowed"] = "/"
    # Browser SW'i her zaman fresh çekmeli (kritik update)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@router.get("", response_class=HTMLResponse)
async def chat_ui():
    """Chat arayüzü HTML — Wix iframe buraya bağlanır.

    Cache kapalı — backend'deki her güncelleme anında Wix'e yansır,
    kullanıcı sayfayı yenilediğinde en son UI'ı görür.
    """
    if not HTML_FILE.exists():
        raise HTTPException(status_code=500, detail="web_chat_ui.html bulunamadı")
    html = HTML_FILE.read_text(encoding="utf-8")
    response = HTMLResponse(html)
    # Wix / fermategitimkurumlari iframe embed için CSP frame-ancestors
    response.headers["Content-Security-Policy"] = (
        "frame-ancestors 'self' "
        "https://*.wixsite.com "
        "https://*.wix.com "
        "https://*.filesusr.com "
        "https://*.editorx.com "
        "https://fermategitimkurumlari.com "
        "https://www.fermategitimkurumlari.com "
        "https://fermatvip.com "
        "https://www.fermatvip.com"
    )
    # X-Frame-Options legacy (bazi Wix setup icin)
    response.headers["X-Frame-Options"] = "ALLOWALL"
    # Oturum 25.41 (Neo bug 6 May): "Sisteme girdiğimde bot atıyor"
    # SEBEP: 5 dk cache + SW stale-while-revalidate → eski authFetch JS
    # geliyor → agresif logout. Ana HTML her zaman fresh olmalı.
    # YENİ: no-cache (server her seferinde yeni HTML kontrolü)
    # SW tarafında network-first stratejisi (offline'da fallback var)
    # Trade-off: ilk açılış ~200ms yavaş ama auth bug'ı yok.
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@router.post("/verify-otp")
async def verify_otp_endpoint(body: VerifyOtpReq, request: Request, response: Response):
    """OTP doğrula, başarılıysa cookie set et + token'ı JSON'da döndür (iPad Safari için)."""
    ip = request.client.host if request.client else ""
    ua = request.headers.get("user-agent", "")[:256]

    result = await verify_otp(body.phone, body.otp, ip=ip, user_agent=ua)

    if not result["success"]:
        return JSONResponse(
            status_code=401,
            content={"success": False, "message": result.get("message", "Giriş başarısız.")},
        )

    # Cookie set (iframe cross-origin: SameSite=None + Secure)
    # Chrome/Firefox/Edge çalışır. iOS Safari ITP cookie'yi BLOKLAYABILIR.
    response.set_cookie(
        key=COOKIE_NAME,
        value=result["token"],
        max_age=result.get("expires_hours", 2) * 3600,
        httponly=True,
        samesite="none",
        secure=True,
    )
    kicked = result.get("kicked_previous", 0)
    if kicked > 0:
        logger.info(f"🌐 Web chat giriş: {result['phone']} ({result['name']}) — {kicked} eski oturum kapatıldı")
    else:
        logger.info(f"🌐 Web chat giriş: {result['phone']} ({result['name']})")

    # iOS Safari FIX: token'ı JSON'da da döndür.
    # Frontend localStorage'a kaydedip Authorization: Bearer {token} header ile gönderir.
    # Safari cookie bloklasa bile session ayakta kalır.
    return {
        "success": True,
        "name": result["name"],
        "role": result["role"],
        "token": result["token"],        # iPad/Safari için
        "expires_hours": result.get("expires_hours", 2),
        "kicked_previous": kicked,
    }


@router.get("/me")
async def whoami(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """Mevcut session durumu — açılışta kontrol için."""
    token = _extract_token(request, fermat_session)
    if not token:
        return {"authenticated": False}
    sess = await get_session(token)
    if not sess:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "name": sess["name"],
        "role": sess["role"],
    }


@router.post("/send")
async def send_message(
    body: SendMsgReq,
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """Non-streaming chat mesajı. Faz 1."""
    token = _extract_token(request, fermat_session)
    if not token:
        raise HTTPException(status_code=401, detail="Oturum yok")

    sess = await get_session(token)
    if not sess:
        raise HTTPException(status_code=401, detail="Oturum geçersiz veya süresi dolmuş")

    msg = (body.message or "").strip()
    if not msg:
        return {"reply": "Boş mesaj gönderdin. Bir şey yazar mısın?"}

    if len(msg) > 2000:
        return {"reply": "Mesajın çok uzun (>2000). Kısalt veya parçala."}

    try:
        # Bridge'in mesaj işleme pipeline'ını kullan (aynı path: fast_response → Ollama → Claude)
        # channel="web" → WP'ya filler/post-followup gönderilmez (kanal çatışması önlemi)
        from whatsapp_bridge import process_message
        reply = await process_message(sess["phone"], msg, channel="web")

        if not reply:
            reply = "Bir şeyler ters gitti. Tekrar dener misin?"

        logger.info(f"🌐 Web chat: {sess['phone'][-4:]} → {len(reply)} char yanıt")
        return {"reply": reply, "name": sess["name"]}

    except Exception as e:
        logger.error(f"Web chat send hatası: {e}")
        return {"reply": "Teknik bir aksama var. Biraz sonra tekrar dene veya WhatsApp'tan yaz."}


# ─── D1 — FEEDBACK (👍/👎) ────────────────────────────────────────
# Her bot mesajının altında bir defa tıklanabilir, değiştirilebilir.
# Data: hangi cevap + hangi konu + hangi prompt → beğeniliyor/beğenilmiyor
# Admin haftalık raporda "en kötü cevap" mesajlarını görür → kalite iyileştirme.

class FeedbackReq(BaseModel):
    message_hash: str   # Mesaj içeriğinin kısa hash'i (tekrar engelleme için)
    user_prompt: str = ""      # Kullanıcının sorusu
    bot_response_preview: str = ""  # Bot cevabından ilk 200 char
    feedback: str       # 'up' / 'down'
    category: str = ""  # Opsiyonel: deneme/konu_anlatimi/analiz/genel


@router.post("/tts")
async def chat_tts(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """Oturum 25.35 — Web chat'te bot mesajına 'Sesli oku' butonu için TTS endpoint."""
    token = _extract_token(request, fermat_session)
    if not token:
        raise HTTPException(status_code=401, detail="Oturum yok")
    sess = await get_session(token)
    if not sess:
        raise HTTPException(status_code=401, detail="Oturum süresi doldu")
    try:
        body = await request.json()
        text = (body.get("text") or "").strip()
        if not text:
            return JSONResponse(status_code=400, content={"success": False, "error": "text bos"})
        from external_apis_v2 import text_to_speech
        r = await text_to_speech(text=text[:3500], voice=body.get("voice", "nova"))
        if r.get("success") and r.get("audio_filename"):
            import os
            base = os.getenv("PUBLIC_BASE_URL", "https://api.fermategitimkurumlari.com").rstrip("/")
            r["audio_url"] = f"{base}/audio/{r['audio_filename']}"
        return JSONResponse(content=r)
    except Exception as e:
        logger.warning(f"chat_tts hata: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@router.post("/pdf")
async def chat_pdf(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """Oturum 25.35 — Web chat'te bot mesajına 'PDF al' butonu için PDF endpoint."""
    token = _extract_token(request, fermat_session)
    if not token:
        raise HTTPException(status_code=401, detail="Oturum yok")
    sess = await get_session(token)
    if not sess:
        raise HTTPException(status_code=401, detail="Oturum süresi doldu")
    try:
        body = await request.json()
        html = (body.get("html_content") or "").strip()
        title = (body.get("title") or "FermatAI Yanıt")[:200]
        if not html:
            return JSONResponse(status_code=400, content={"success": False, "error": "html_content bos"})
        from external_apis_v2 import generate_pdf
        r = await generate_pdf(html_content=html, title=title)
        if r.get("success") and r.get("pdf_filename"):
            import os
            base = os.getenv("PUBLIC_BASE_URL", "https://api.fermategitimkurumlari.com").rstrip("/")
            r["pdf_url"] = f"{base}/pdfs/{r['pdf_filename']}"
        return JSONResponse(content=r)
    except Exception as e:
        logger.warning(f"chat_pdf hata: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@router.post("/feedback")
async def submit_feedback(
    body: FeedbackReq,
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """Bot mesajına 👍/👎 oyu ver. Değiştirilebilir (ON CONFLICT DO UPDATE)."""
    token = _extract_token(request, fermat_session)
    if not token:
        raise HTTPException(status_code=401, detail="Oturum yok")
    sess = await get_session(token)
    if not sess:
        raise HTTPException(status_code=401, detail="Oturum süresi doldu")

    if body.feedback not in ("up", "down"):
        return JSONResponse(status_code=400, content={"success": False, "message": "feedback 'up' veya 'down' olmalı"})

    try:
        from db_pool import db_execute
        await db_execute(
            """
            INSERT INTO feedback_log (phone, role, message_hash, user_prompt, bot_response_preview,
                                     feedback, channel, category)
            VALUES ($1, $2, $3, $4, $5, $6, 'web', $7)
            ON CONFLICT (phone, message_hash) DO UPDATE SET
                feedback = EXCLUDED.feedback,
                created_at = NOW()
            """,
            sess["phone"], sess.get("role", ""), body.message_hash,
            (body.user_prompt or "")[:500], (body.bot_response_preview or "")[:500],
            body.feedback, body.category[:40]
        )
        logger.info(f"👍/👎 Feedback: {sess['phone'][-4:]} → {body.feedback} ({body.category})")
        return {"success": True}
    except Exception as e:
        logger.error(f"Feedback kayıt hatası: {e}")
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)[:100]})


@router.get("/feedback/stats")
async def feedback_stats(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """Admin/mudur için son 7 gün feedback istatistiği."""
    token = _extract_token(request, fermat_session)
    if not token:
        raise HTTPException(status_code=401, detail="Oturum yok")
    sess = await get_session(token)
    if not sess or sess.get("role") not in ("admin", "mudur", "yonetim"):
        raise HTTPException(status_code=403, detail="Yetkin yok")

    try:
        from db_pool import db_fetch, db_fetchrow
        overall = await db_fetchrow(
            "SELECT "
            "COUNT(*) FILTER (WHERE feedback='up') AS begeni, "
            "COUNT(*) FILTER (WHERE feedback='down') AS begenmeme, "
            "COUNT(*) AS toplam "
            "FROM feedback_log WHERE created_at > NOW() - INTERVAL '7 days'"
        )

        # En kötü cevaplar (son 7 gün, 👎 olanlar)
        worst = await db_fetch(
            "SELECT phone, role, user_prompt, bot_response_preview, category, created_at "
            "FROM feedback_log "
            "WHERE feedback='down' AND created_at > NOW() - INTERVAL '7 days' "
            "ORDER BY created_at DESC LIMIT 10"
        )

        worst_list = [{
            "phone": r["phone"][-4:],
            "role": r["role"],
            "prompt": r["user_prompt"][:100],
            "response": r["bot_response_preview"][:150],
            "category": r["category"],
            "at": r["created_at"].isoformat() if r["created_at"] else "",
        } for r in worst]

        return {
            "success": True,
            "overall": dict(overall) if overall else {},
            "worst": worst_list,
        }
    except Exception as e:
        return {"success": False, "error": str(e)[:100]}


# ─── PDF RAPOR EXPORT (A9) ────────────────────────────────────────
# Öğrenci kendi raporunu, müdür herhangi öğrencinin raporunu PDF olarak indirir.
# ACL: öğrenci sadece kendi soz_no, mudur/rehber/admin herkesi alabilir.

@router.get("/pdf-report")
async def pdf_report(
    request: Request,
    soz_no: Optional[int] = None,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """PDF rapor indir. Öğrenci: kendi soz_no otomatik. Mudur/admin: ?soz_no=X query."""
    token = _extract_token(request, fermat_session)
    if not token:
        raise HTTPException(status_code=401, detail="Oturum yok")
    sess = await get_session(token)
    if not sess:
        raise HTTPException(status_code=401, detail="Oturum süresi doldu")

    role = sess.get("role", "ogrenci")
    phone = sess["phone"]

    # soz_no belirle
    target_soz = None
    if role == "ogrenci":
        # Öğrenci SADECE kendi raporunu alabilir
        from db_pool import db_fetchval
        target_soz = await db_fetchval(
            "SELECT soz_no FROM students WHERE REPLACE(phone,'+','')=$1 LIMIT 1",
            phone
        )
        if not target_soz:
            return JSONResponse(status_code=404, content={"success": False, "message": "Öğrenci kaydın bulunamadı."})
    elif role in ("mudur", "rehber", "admin", "yonetim"):
        # Başka öğrencinin raporunu alabilirler
        if not soz_no:
            return JSONResponse(status_code=400, content={"success": False, "message": "soz_no parametresi gerekli."})
        target_soz = soz_no
    else:
        return JSONResponse(status_code=403, content={"success": False, "message": "Yetkin yok."})

    try:
        from pdf_report import generate_student_pdf
        from fastapi.responses import FileResponse
        pdf_path = await generate_student_pdf(target_soz)
        if not pdf_path:
            return JSONResponse(status_code=404, content={"success": False, "message": "Öğrenci verisi bulunamadı."})

        # Güvenli dosya adı
        safe_name = f"fermatai_rapor_{target_soz}.pdf"
        logger.info(f"📄 PDF rapor indirildi: {phone[-4:]} → soz_no={target_soz}")
        return FileResponse(
            path=pdf_path,
            media_type="application/pdf",
            filename=safe_name,
        )
    except Exception as e:
        logger.error(f"PDF rapor hatası: {e}")
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)[:200]})


# ─── ARŞİV (Neo önerisi — kullanıcı tetikli) ──────────────────────
# Kullanıcı bot cevabının altındaki ⭐ ile ÖNEMLİ bulduğu mesajı arşivler.
# Her konuşma otomatik kaydedilmez (maliyet + gürültü önlemi).
# Archive'deki mesajlar drawer'ın "Arşivim" sekmesinde listelenir.

class ArchiveReq(BaseModel):
    title: str
    content: str
    category: str = "genel"  # genel/calisma_plani/konu_anlatimi/analiz/deneme/soru_cozum/kaynak/not
    context_prompt: str = ""  # Soruyu kaydet — ileride "benzer" oluşturmak için
    tags: str = ""  # Oturum 23 (Neo): virgülle etiket listesi (ör "fizik, türev, ayt")


@router.post("/archive")
async def archive_message(
    body: ArchiveReq,
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """Bot mesajını arşive ekle (⭐ butonuyla tetiklenir)."""
    token = _extract_token(request, fermat_session)
    if not token:
        raise HTTPException(status_code=401, detail="Oturum yok")
    sess = await get_session(token)
    if not sess:
        raise HTTPException(status_code=401, detail="Oturum süresi doldu")

    title = (body.title or "").strip()[:120]
    content = (body.content or "").strip()[:10000]
    if not content:
        return JSONResponse(status_code=400, content={"success": False, "message": "Boş içerik."})

    # Limit: kullanıcı başına max 100 arşiv
    try:
        from db_pool import db_fetchval, db_execute
        count = await db_fetchval("SELECT COUNT(*) FROM user_archive WHERE phone=$1", sess["phone"])
        if count and count >= 100:
            return JSONResponse(
                status_code=429,
                content={"success": False, "message": "Arşiv limiti doldu (100). Eskilerinden silmen gerek."}
            )

        # Oturum 23 (Neo): tags opsiyonel virgüllü etiket listesi
        # Virgülle bölüp temizle, maksimum 10 etiket + her biri 30 char
        tags_clean = ""
        if getattr(body, "tags", None):
            _raw = body.tags[:200].split(",")
            _list = [t.strip()[:30] for t in _raw if t.strip()][:10]
            tags_clean = ", ".join(_list)

        await db_execute(
            "INSERT INTO user_archive (phone, title, content, category, context_prompt, tags) "
            "VALUES ($1, $2, $3, $4, $5, $6)",
            sess["phone"], title or content[:50], content, body.category, body.context_prompt[:500],
            tags_clean
        )
        logger.info(f"⭐ Arşive eklendi: {sess['phone'][-4:]} → {title[:40]} (tags: {tags_clean or '-'})")

        # 25.37 (Neo): Mesaj içindeki render link'lerini OTOMATIK ARSIVLE
        # Mesaj kalır ama render artifact 30 günde expire olursa link çürür → auto-archive
        try:
            import re as _re
            # /render/{12-22 char alphanumeric+_-} pattern
            uuids = _re.findall(r"/render/([A-Za-z0-9_\-]{8,32})", content)
            uuids = list(set(uuids))  # unique
            if uuids:
                # render_artifacts'ta her birini archived=TRUE + expires_at=NULL yap
                # Sadece kullanıcının kendi mesajındaki UUID'leri archive et (zaten content'inde var)
                await db_execute(
                    """UPDATE render_artifacts
                       SET archived = TRUE,
                           archived_at = COALESCE(archived_at, NOW()),
                           archived_by_phone = COALESCE(archived_by_phone, $2),
                           archive_note = COALESCE(archive_note, 'auto: mesaj arşive eklendi'),
                           expires_at = NULL
                       WHERE uuid = ANY($1::text[])""",
                    uuids, sess["phone"]
                )
                logger.info(
                    f"  ⭐ Mesaj içi render auto-archive: {len(uuids)} artifact → kalıcı "
                    f"(uuids: {','.join(u[:6] for u in uuids[:3])}{'...' if len(uuids)>3 else ''})"
                )
        except Exception as _aa_e:
            logger.debug(f"  render auto-archive hata (kritik değil): {_aa_e}")

        return {"success": True, "title": title or content[:50]}
    except Exception as e:
        logger.error(f"Arşiv ekleme hatası: {e}")
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)[:100]})


@router.get("/archive")
async def list_archive(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """Kullanıcının arşivlenmiş mesajlarını listele.

    25.40z3-ARSIV-MERGE: 2 ayrı arşiv kaynağını TEK liste olarak döndürür:
    1. user_archive (mesaj arşivi: ⭐ ile arşivlenen bot cevapları)
    2. render_artifacts (render arşivi: ⭐ ile arşivlenen HTML simülasyon/grafik)

    Neo bug raporu (4 May 2026): Simülasyon arşivledi ama UI'da görünmedi
    çünkü UI sadece user_archive (chat) çekiyordu, render artifacts ayrı yerdeydi.
    """
    token = _extract_token(request, fermat_session)
    if not token:
        raise HTTPException(status_code=401, detail="Oturum yok")
    sess = await get_session(token)
    if not sess:
        raise HTTPException(status_code=401, detail="Oturum süresi doldu")

    try:
        from db_pool import db_fetch
        phone = sess["phone"]
        items = []

        # 1. Mesaj arşivi (user_archive)
        msg_rows = await db_fetch(
            "SELECT id, title, content, category, context_prompt, tags, created_at "
            "FROM user_archive WHERE phone=$1 ORDER BY created_at DESC LIMIT 100",
            phone,
        )
        for r in msg_rows:
            items.append({
                "id": r["id"],
                "type": "message",  # 25.40z3-MERGE: hangi arşiv kaynağı
                "title": r["title"],
                "content": r["content"],
                "category": r["category"],
                "context_prompt": r["context_prompt"],
                "tags": r.get("tags") or "",
                "created_at": r["created_at"].isoformat() if r["created_at"] else "",
                "preview": (r["content"] or "")[:200],
            })

        # 2. Render artifact arşivi (render_artifacts)
        # Phone normalize: render_artifacts'da '+' olabilir, user_archive'de yok
        phone_clean = phone.replace("+", "").replace(" ", "")[-20:]
        try:
            import os, json as _j
            base = os.getenv("PUBLIC_BASE_URL", "https://api.fermategitimkurumlari.com").rstrip("/")
            render_rows = await db_fetch(
                """SELECT uuid, title, archived_at, archive_note, view_count,
                          quality_score, creator_phone, archived_by_phone
                   FROM render_artifacts
                   WHERE archived = TRUE AND (
                       archived_by_phone = $1 OR creator_phone = $1
                       OR REPLACE(archived_by_phone, '+', '') = $1
                       OR REPLACE(creator_phone, '+', '') = $1
                   )
                   ORDER BY archived_at DESC LIMIT 50""",
                phone_clean,
            )
            for r in render_rows:
                # archive_note JSON ise parse et (yeni format), değilse plain text
                note_raw = r["archive_note"] or ""
                category = ""
                user_note = note_raw
                tags = ""
                if note_raw.startswith("{"):
                    try:
                        meta = _j.loads(note_raw)
                        category = meta.get("category", "")
                        user_note = meta.get("note", "") or ""
                        if meta.get("name"):
                            r_title = meta["name"]
                        else:
                            r_title = r["title"] or "Görsel"
                    except Exception:
                        r_title = r["title"] or "Görsel"
                else:
                    r_title = r["title"] or "Görsel"
                # Görsel kategori default
                if not category:
                    category = "gorsel_simulasyon"

                items.append({
                    "id": f"render_{r['uuid']}",  # benzersiz prefix
                    "type": "render",  # 25.40z3-MERGE
                    "title": r_title,
                    "content": user_note or f"Görsel: {r_title}",
                    "category": category,
                    "context_prompt": "",
                    "tags": tags,
                    "created_at": r["archived_at"].isoformat() if r["archived_at"] else "",
                    "preview": user_note[:200] if user_note else f"Görsel: {r_title}",
                    # Render-spesifik field'lar (UI bunları kullanabilir)
                    "render_url": f"{base}/render/{r['uuid']}",
                    "render_uuid": r["uuid"],
                    "quality_score": r["quality_score"] or 0,
                    "view_count": r["view_count"] or 0,
                })
        except Exception as _re:
            logger.warning(f"Render archive merge fail (mesaj arşivi yine döner): {_re}")

        # Tarihe göre sırala (en yeni üstte) — iki kaynak birleşince karışmasın
        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        return {"success": True, "count": len(items), "items": items}
    except Exception as e:
        logger.error(f"Arşiv listeleme hatası: {e}")
        return {"success": False, "items": [], "error": str(e)[:100]}


@router.delete("/archive/{archive_id}")
async def delete_archive(
    archive_id: int,
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """Arşivden kaldır (kullanıcı sadece kendi kayıtlarını silebilir)."""
    token = _extract_token(request, fermat_session)
    if not token:
        raise HTTPException(status_code=401, detail="Oturum yok")
    sess = await get_session(token)
    if not sess:
        raise HTTPException(status_code=401, detail="Oturum süresi doldu")

    try:
        from db_pool import db_execute
        await db_execute(
            "DELETE FROM user_archive WHERE id=$1 AND phone=$2",
            archive_id, sess["phone"]
        )
        return {"success": True}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)[:100]})


# Oturum 23 (Neo FAZ 1 A3): Arşivi PDF olarak indir
@router.get("/archive/export.pdf")
async def archive_export_pdf(
    request: Request,
    category: str = "",
    ids: str = "",  # virgüllü ID listesi: "1,5,7"
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """Kullanıcı arşivini PDF olarak indir.

    Query params:
        category: Kategori filtresi (opsiyonel, boş → tümü)
        ids: Spesifik ID'ler "1,5,7" (opsiyonel, boş → tümü veya category)
    """
    token = _extract_token(request, fermat_session)
    if not token:
        raise HTTPException(status_code=401, detail="Oturum yok")
    sess = await get_session(token)
    if not sess:
        raise HTTPException(status_code=401, detail="Oturum süresi doldu")

    # ID listesi parse
    archive_ids = None
    if ids:
        try:
            archive_ids = [int(x.strip()) for x in ids.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(status_code=400, detail="Geçersiz ids")
        if len(archive_ids) > 50:
            raise HTTPException(status_code=400, detail="Max 50 kayıt tek seferde")

    try:
        from archive_pdf_export import build_archive_pdf
        pdf_bytes = await build_archive_pdf(
            phone=sess["phone"],
            student_name=sess.get("name", ""),
            archive_ids=archive_ids,
            category=category,
        )
        from fastapi.responses import Response
        ts = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M")
        # Tek kayıt indirildiyse dosya adına başlığı koy (ör: Ogretmen-Ucret-Modeli_20260424.pdf)
        filename = f"FermatAI_Arsiv_{ts}.pdf"
        if archive_ids and len(archive_ids) == 1:
            try:
                from db_pool import db_fetchval
                title = await db_fetchval(
                    "SELECT title FROM user_archive WHERE id=$1 AND phone=$2",
                    archive_ids[0], sess["phone"],
                )
                if title:
                    # Dosya adı güvenli slug (ASCII-only, 60 char limit)
                    import re, unicodedata
                    slug = unicodedata.normalize("NFKD", title)
                    slug = slug.encode("ascii", "ignore").decode("ascii")
                    slug = re.sub(r"[^\w\s-]", "", slug).strip()
                    slug = re.sub(r"[-\s]+", "-", slug)[:60]
                    if slug:
                        filename = f"FermatAI_{slug}_{ts}.pdf"
            except Exception:
                pass  # fallback to default name
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except RuntimeError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Arşiv PDF export hatası: {e}")
        raise HTTPException(status_code=500, detail="PDF üretilemedi")


# Oturum 23 (Neo öneri 2): Arşiv kaydını rename — eski kayıtları yeniden isimlendir
class ArchiveUpdateReq(BaseModel):
    title: str = ""
    category: str = ""
    tags: str = ""


@router.patch("/archive/{archive_id}")
async def update_archive(
    archive_id: int,
    body: ArchiveUpdateReq,
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """Arşiv kaydının başlık/kategori/etiketini güncelle (yalnız sahibi)."""
    token = _extract_token(request, fermat_session)
    if not token:
        raise HTTPException(status_code=401, detail="Oturum yok")
    sess = await get_session(token)
    if not sess:
        raise HTTPException(status_code=401, detail="Oturum süresi doldu")

    # Hangi alanları güncellediğini tespit et
    sets = []
    args = []
    idx = 1
    if body.title:
        sets.append(f"title = ${idx}")
        args.append(body.title.strip()[:120])
        idx += 1
    if body.category:
        valid_cats = {"genel", "calisma_plani", "deneme", "konu_anlatimi",
                      "analiz", "soru_cozum", "kaynak", "not"}
        if body.category in valid_cats:
            sets.append(f"category = ${idx}")
            args.append(body.category)
            idx += 1
    if body.tags is not None:  # boş string bile geçerli (temizleme)
        _raw = body.tags[:200].split(",")
        _list = [t.strip()[:30] for t in _raw if t.strip()][:10]
        sets.append(f"tags = ${idx}")
        args.append(", ".join(_list))
        idx += 1

    if not sets:
        return {"success": False, "message": "Güncellenecek alan yok"}

    try:
        from db_pool import db_execute
        args.extend([archive_id, sess["phone"]])
        sql = f"UPDATE user_archive SET {', '.join(sets)} WHERE id=${idx} AND phone=${idx+1}"
        result = await db_execute(sql, *args)
        if result and "UPDATE 0" in result:
            return JSONResponse(status_code=404, content={"success": False, "message": "Kayıt bulunamadı veya yetkin yok"})
        return {"success": True}
    except Exception as e:
        logger.error(f"Arşiv update hatası: {e}")
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)[:100]})


# ─── A13 — HIZLI KOMUTLAR (rol-aware, context pollution YOK) ──────
# Her rol için önceden tanımlı prompt listesi. Kullanıcı yazmak yerine tıklar.
# Cevap DB'deki conversation history'e gider ama context'e inject edilmez
# (Neo'nun endişesi: maliyet + latency kontrolü).

# ═══════════════════════════════════════════════════════════════════════
# DASHBOARD — 4 rol icin ayri veri fonksiyonu (22.1i2)
# Neo felsefesi: "Ham veri degil pedagojik sinyal"
# Devamsizlik → SADECE rehber/mudur/admin ekranlarinda (ogrenci/veli'de YOK)
# ═══════════════════════════════════════════════════════════════════════

# 22.1m — LGS öğrenci özel dashboard (8. sınıf — 90 soru, 6 ders)
async def _dashboard_ogrenci_lgs(soz_no, student, sinif: str, phone: str) -> dict:
    """LGS öğrencisi için özel dashboard — YKS terminolojisi kullanilmaz."""
    try:
        from db_pool import db_fetch, db_fetchrow, db_fetchval
        from datetime import date

        # LGS 8 Haziran 2026 (resmi tarih, sonra güncellenebilir)
        today = date.today()
        lgs_date = date(2026, 6, 7)
        lgs_gun = (lgs_date - today).days

        # Son 5 LGS denemesi (exam_type='LGS' varsa, yoksa TYT'yi göster)
        trend = await db_fetch(
            """SELECT exam_name, exam_date, toplam, turkce, matematik,
                      fizik, kimya, biyoloji, tarih, cografya, din_kulturu
               FROM student_exams
               WHERE soz_no = $1 AND status='valid'
                 AND (exam_type='LGS' OR exam_type='TYT')
               ORDER BY exam_date DESC LIMIT 5""",
            int(soz_no)
        )
        trend_rev = list(reversed([
            {
                "name": (t["exam_name"] or "")[:25],
                "date": t["exam_date"].strftime("%d.%m") if t["exam_date"] else "",
                "toplam": float(t["toplam"] or 0),
                "turkce": float(t["turkce"] or 0),
                "matematik": float(t["matematik"] or 0),
                # LGS'de "fen" kolunda fizik+kimya+biyoloji karışık gelebilir
                "fen": float((t["fizik"] or 0) + (t["kimya"] or 0) + (t["biyoloji"] or 0)),
                "sosyal": float((t["tarih"] or 0) + (t["cografya"] or 0) + (t["din_kulturu"] or 0)),
            }
            for t in trend
        ]))

        last = trend[0] if trend else None
        last_exam = None
        if last:
            last_exam = {
                "name": (last["exam_name"] or "")[:25],
                "date": last["exam_date"].strftime("%d.%m.%Y") if last["exam_date"] else "",
                "toplam": float(last["toplam"] or 0),
            }

        # LGS zayıf konular (sinav_turu='LGS' seed edilmiş)
        weak = await db_fetch(
            """SELECT ders, konu, sinav_hata_yuzdesi
               FROM student_topic_tracker
               WHERE soz_no = $1 AND sinav_turu='LGS'
                 AND (tamamlandi IS NULL OR tamamlandi = FALSE)
               ORDER BY sinav_hata_yuzdesi ASC NULLS LAST LIMIT 5""",
            int(soz_no)
        )
        oncelik = []
        for w in weak:
            basari = float(w["sinav_hata_yuzdesi"] or 0)
            neden = ""
            if basari < 20:
                neden = f"Başarın %{int(basari)} — buradan başla, kolay kazanç"
            elif basari < 50:
                neden = f"Başarın %{int(basari)} — 2 hafta odaklan yeter"
            else:
                neden = f"Başarın %{int(basari)} — pratikle gelişir"
            oncelik.append({
                "ders": w["ders"],
                "konu": w["konu"],
                "basari": round(basari, 1),
                "neden": neden,
            })

        # 6 ders soru dağılımı bilgisi
        lgs_dagilim = {
            "Türkçe": 20,
            "Matematik": 20,
            "Fen Bilimleri": 20,
            "T.C. İnkılap Tarihi": 10,
            "Din Kültürü": 10,
            "İngilizce": 10,
        }

        # Pedagojik sinyal
        sinyal = "notr"
        sinyal_mesaj = "Veri yok"
        if len(trend_rev) >= 3:
            son_3 = [t["toplam"] for t in trend_rev[-3:]]
            if son_3[-1] > son_3[0] + 3:
                sinyal, sinyal_mesaj = "yukselis", f"Son 3 denemede toplam net +{round(son_3[-1]-son_3[0], 1)} artış"
            elif son_3[-1] < son_3[0] - 3:
                sinyal, sinyal_mesaj = "dusus", f"Son 3 denemede {round(son_3[0]-son_3[-1], 1)} net düşüş"
            else:
                sinyal, sinyal_mesaj = "stabil", "Son 3 denemede stabil seyir"

        # Foto gecmis
        foto_gecmis = await db_fetch(
            """SELECT konu, ders, zorluk, created_at FROM foto_questions
               WHERE soz_no::text = $1 OR phone = $2
               ORDER BY created_at DESC LIMIT 5""",
            str(soz_no), phone
        )
        foto_list = [
            {"konu": (f["konu"] or "?")[:60], "ders": f["ders"] or "",
             "zorluk": f["zorluk"] or "",
             "tarih": f["created_at"].strftime("%d.%m %H:%M") if f["created_at"] else ""}
            for f in foto_gecmis
        ]

        return {
            "success": True,
            "role": "ogrenci",
            "is_lgs": True,  # UI bu flag ile LGS modu acar
            "name": student["full_name"],
            "class": sinif,
            "lgs": {"gun": lgs_gun, "tarih": lgs_date.strftime("%d.%m.%Y")},
            "last_exam": last_exam,
            "trend": trend_rev,
            "ders_dagilim": lgs_dagilim,
            "oncelik_3_konu": oncelik[:3],
            "sinyal": {"yon": sinyal, "mesaj": sinyal_mesaj},
            "foto_gecmis": foto_list,
        }
    except Exception as e:
        logger.error(f"LGS dashboard hata: {e}")
        return {"success": False, "message": str(e)[:150]}


# 22.1l — VELI FLAG — Neo kurali: 1 Eylul 2026'da canliya alinacak
# Simdi altyapi hazir, bu flag False iken endpoint "hazir degil" der
VELI_DASHBOARD_ACTIVE = False


async def _dashboard_veli(phone: str) -> dict:
    """
    Veli Dashboard (22.1l — HAZIR AMA FLAG KAPALI)

    Neo felsefesi (project_dashboard_vision.md):
    - Büyük sinyal kartı: 🟢/🟡/🔴 + 1 cümle açıklama
    - Toplam net trendi (sade, son 5 deneme)
    - "Geçen aya göre +X net artış" yorumu
    - DEVAMSIZLIK YOK (Neo kuralı — veli ödeme azaltmak isteyebilir)
    - Rehber iletişim bilgisi

    ACTIVE olunca: phone eşleşmesinden çocuk bulunur (students.veliCep / anneCep / babaCep).
    """
    if not VELI_DASHBOARD_ACTIVE:
        return {
            "success": False,
            "message": "Veli paneli yeni sezonda (1 Eylul 2026) aktif olacak. Simdi chat araciligiyla iletisim.",
            "yeni_sezon": "1 Eylul 2026",
        }

    try:
        from db_pool import db_fetch, db_fetchrow
        # Veli telefonu → hangi ogrenci(ler)?
        ogr_list = await db_fetch(
            """SELECT soz_no, full_name, class_name FROM students
               WHERE (veliCep = $1 OR anneCep = $1 OR babaCep = $1) AND status='active'
               LIMIT 3""",
            phone
        )
        if not ogr_list:
            return {"success": False, "message": "Velisi oldugunuz ogrenci bulunamadi."}

        cocuklar = []
        for ogr in ogr_list:
            soz_no = ogr["soz_no"]
            # Son 5 deneme toplam net
            trend = await db_fetch(
                """SELECT exam_name, exam_date, toplam
                   FROM student_exams WHERE soz_no = $1 AND status='valid' AND exam_type='TYT'
                   ORDER BY exam_date DESC LIMIT 5""",
                int(soz_no)
            )
            trend_rev = list(reversed([
                {"name": (t["exam_name"] or "")[:20],
                 "date": t["exam_date"].strftime("%d.%m") if t["exam_date"] else "",
                 "net": float(t["toplam"] or 0)}
                for t in trend
            ]))

            # Sinyal yorumu (Neo pedagojik: 🟢/🟡/🔴)
            sinyal = "yesil"
            sinyal_mesaj = f"{ogr['full_name'].split()[0]} icin gelisim olumlu yonde."
            if len(trend_rev) >= 3:
                son_3 = [t["net"] for t in trend_rev[-3:]]
                if son_3[-1] < son_3[0] - 5:
                    sinyal = "kirmizi"
                    sinyal_mesaj = f"{ogr['full_name'].split()[0]} son denemelerde dustu. Rehber hocayla gorusmeniz onerilir."
                elif son_3[-1] < son_3[0] - 2:
                    sinyal = "sari"
                    sinyal_mesaj = f"{ogr['full_name'].split()[0]} icin bazi derslerde dikkat edilecek alanlar var."

            # Geçen aya göre fark (son vs 4 hafta once)
            gecen_ay = await db_fetchrow(
                """SELECT AVG(toplam) as ort FROM student_exams
                   WHERE soz_no = $1 AND status='valid' AND exam_type='TYT'
                     AND exam_date BETWEEN NOW() - INTERVAL '60 days' AND NOW() - INTERVAL '30 days'""",
                int(soz_no)
            )
            bu_ay = await db_fetchrow(
                """SELECT AVG(toplam) as ort FROM student_exams
                   WHERE soz_no = $1 AND status='valid' AND exam_type='TYT'
                     AND exam_date > NOW() - INTERVAL '30 days'""",
                int(soz_no)
            )
            ay_yorum = ""
            if gecen_ay and bu_ay and gecen_ay["ort"] and bu_ay["ort"]:
                fark = float(bu_ay["ort"]) - float(gecen_ay["ort"])
                if fark > 2:
                    ay_yorum = f"Gecen aya gore +{fark:.1f} net artis."
                elif fark < -2:
                    ay_yorum = f"Gecen aya gore {fark:.1f} net dustu."
                else:
                    ay_yorum = "Gecen ayla benzer seyir."

            cocuklar.append({
                "name": ogr["full_name"],
                "sinif": ogr["class_name"] or "",
                "sinyal": {"yon": sinyal, "mesaj": sinyal_mesaj},
                "trend": trend_rev,
                "ay_yorum": ay_yorum,
            })

        # Rehber iletisim (kurum sabit)
        rehber_iletisim = {
            "telefon": "+90 546 260 54 46",
            "randevu": "fermategitimkurumlari.com/randevu",
        }

        return {
            "success": True,
            "role": "veli",
            "cocuklar": cocuklar,
            "rehber": rehber_iletisim,
            "not": "Ham veri degil pedagojik sinyal — detay icin rehber ile iletisime gecin.",
        }
    except Exception as e:
        logger.error(f"Dashboard veli hata: {e}")
        return {"success": False, "message": str(e)[:150]}


async def _dashboard_ogretmen(phone: str) -> dict:
    """Ogretmen dashboard — program + etut performans + sinif dagilimi."""
    try:
        from db_pool import db_fetchrow, db_fetch, db_fetchval
        # Staff — kolon isimleri: full_name, first_name, last_name, gorev, brans, kullanici
        # Telefon eslemesi staff tablosunda yok → acl_users'tan isim al
        acl_row = await db_fetchrow(
            "SELECT full_name FROM acl_users WHERE REPLACE(phone,'+','') = $1 AND is_active LIMIT 1",
            phone
        )
        ogretmen_adi = (acl_row["full_name"] if acl_row else "") or ""
        # Staff detay
        gorev = ""
        brans = ""
        if ogretmen_adi:
            staff = await db_fetchrow(
                "SELECT full_name, gorev, brans FROM staff WHERE full_name ILIKE $1 LIMIT 1",
                f"%{ogretmen_adi}%"
            )
            if staff:
                gorev = staff["gorev"] or ""
                brans = staff["brans"] or ""

        # Haftalik program — teacher_timetable.ogretmen_ad
        program = []
        if ogretmen_adi:
            program_rows = await db_fetch(
                """SELECT gun, saat, sinif, ders FROM teacher_timetable
                   WHERE ogretmen_ad ILIKE $1 ORDER BY
                   CASE gun WHEN 'Pazartesi' THEN 1 WHEN 'Salı' THEN 2
                     WHEN 'Çarşamba' THEN 3 WHEN 'Perşembe' THEN 4
                     WHEN 'Cuma' THEN 5 WHEN 'Cumartesi' THEN 6 ELSE 7 END, saat
                   LIMIT 40""",
                f"%{ogretmen_adi}%"
            )
            program = [{"gun": p["gun"], "saat": p["saat"], "sinif": p["sinif"], "ders": p["ders"]} for p in program_rows]

        # Etut istatistik (bu sezon) — student_name yok, ogrenci_sayisi ve ders cesidi
        etut_stats = None
        son_30 = 0
        brans_perf = []
        if ogretmen_adi:
            etut_stats = await db_fetchrow(
                """SELECT COUNT(*) as toplam,
                          COALESCE(SUM(ogrenci_sayisi), 0) as toplam_ogrenci_katilim,
                          COUNT(DISTINCT ders) as ders_cesidi
                   FROM etut_history WHERE ogretmen ILIKE $1""",
                f"%{ogretmen_adi}%"
            )
            son_30 = await db_fetchval(
                """SELECT COUNT(*) FROM etut_history
                   WHERE ogretmen ILIKE $1 AND tarih > NOW() - INTERVAL '30 days'""",
                f"%{ogretmen_adi}%"
            ) or 0
            # Ders bazli etut dagilimi (etut_history'de sinif YOK, ders var)
            brans_perf = await db_fetch(
                """SELECT ders, COUNT(*) as etut_sayi,
                          COALESCE(SUM(ogrenci_sayisi), 0) as toplam_katilim
                   FROM etut_history
                   WHERE ogretmen ILIKE $1 AND tarih > NOW() - INTERVAL '60 days'
                     AND ders IS NOT NULL AND ders <> ''
                   GROUP BY ders ORDER BY etut_sayi DESC LIMIT 10""",
                f"%{ogretmen_adi}%"
            )
        sinif_list = [
            {"sinif": b["ders"], "etut_sayi": int(b["etut_sayi"]),
             "toplam_katilim": int(b["toplam_katilim"])}
            for b in brans_perf
        ]

        return {
            "success": True,
            "role": "ogretmen",
            "name": ogretmen_adi or "-",
            "gorev": gorev,
            "brans": brans,
            "kpi": {
                "toplam_etut": int(etut_stats["toplam"]) if etut_stats else 0,
                "son_30_etut": int(son_30 or 0),
                "ogrenci_sayisi": int(etut_stats["toplam_ogrenci_katilim"]) if etut_stats else 0,
            },
            "program": program,
            "siniflar": sinif_list,
        }
    except Exception as e:
        logger.error(f"Dashboard ogretmen hata: {e}")
        return {"success": False, "message": str(e)[:150]}


async def _dashboard_rehber(phone: str) -> dict:
    """Rehber dashboard — risk radari + duygu sinyali + randevu onerileri."""
    try:
        from db_pool import db_fetchrow, db_fetch, db_fetchval

        # Duygu sinyali — son 7 gun negatif (kriz/stres/motivasyon_dusuk)
        duygu_risk = await db_fetch(
            """SELECT DISTINCT ON (si.soz_no)
                      si.soz_no, si.insight_type, si.content, si.created_at,
                      s.full_name, s.class_name
               FROM student_insights si
               LEFT JOIN students s ON s.soz_no::text = si.soz_no::text
               WHERE si.insight_type IN ('kaygi','motivasyon','kriz','negatif','stres')
                 AND si.created_at > NOW() - INTERVAL '7 days'
               ORDER BY si.soz_no, si.created_at DESC
               LIMIT 10"""
        )
        risk_list = [
            {
                "name": r["full_name"], "sinif": r["class_name"] or "-",
                "tip": r["insight_type"], "note": (r["content"] or "")[:100],
                "gun": r["created_at"].strftime("%d.%m")
            }
            for r in duygu_risk
        ]

        # Net dususu olan ogrenciler (son 2 deneme) — type cast zorunlu
        net_dusus = await db_fetch(
            """WITH last_two AS (
                 SELECT soz_no, toplam, exam_date,
                        ROW_NUMBER() OVER (PARTITION BY soz_no ORDER BY exam_date DESC) as rn
                 FROM student_exams WHERE status='valid' AND exam_type='TYT' AND toplam IS NOT NULL
               )
               SELECT l1.soz_no, s.full_name, s.class_name,
                      l1.toplam as son, l2.toplam as onceki,
                      (l1.toplam - l2.toplam) as fark
               FROM last_two l1
               JOIN last_two l2 ON l1.soz_no = l2.soz_no AND l1.rn=1 AND l2.rn=2
               JOIN students s ON s.soz_no = l1.soz_no::text AND s.status='active'
               WHERE (l1.toplam - l2.toplam) < -5
               ORDER BY (l1.toplam - l2.toplam) ASC LIMIT 8"""
        )
        dusus_list = [
            {"name": r["full_name"], "sinif": r["class_name"] or "-",
             "son": float(r["son"] or 0), "onceki": float(r["onceki"] or 0),
             "fark": float(r["fark"] or 0)}
            for r in net_dusus
        ]

        # Kurum geneli rehberlik notu — son 30 gun (kolon: gorusme_tarihi)
        not_sayisi = await db_fetchval(
            "SELECT COUNT(*) FROM counsellor_notes WHERE gorusme_tarihi > NOW() - INTERVAL '30 days'"
        ) or 0

        # Yuksek devamsizlik (200+ saat)
        yuksek_dev = await db_fetch(
            """SELECT d.soz_no, d.toplam_saat, s.full_name, s.class_name
               FROM devamsizlik_sayisi d
               JOIN students s ON s.soz_no::text = d.soz_no::text
               WHERE d.toplam_saat > 150 AND s.status='active'
               ORDER BY d.toplam_saat DESC LIMIT 10"""
        )
        dev_list = [
            {"name": r["full_name"], "sinif": r["class_name"] or "-", "saat": int(r["toplam_saat"])}
            for r in yuksek_dev
        ]

        return {
            "success": True,
            "role": "rehber",
            "kpi": {
                "risk_duygu": len(risk_list),
                "net_dusus": len(dusus_list),
                "yuksek_dev": len(dev_list),
                "rehberlik_not_30g": int(not_sayisi),
            },
            "duygu_risk": risk_list,
            "net_dusus": dusus_list,
            "yuksek_devamsizlik": dev_list,
        }
    except Exception as e:
        logger.error(f"Dashboard rehber hata: {e}")
        return {"success": False, "message": str(e)[:150]}


async def _dashboard_admin_mudur(phone: str, role: str) -> dict:
    """Mudur/Admin/Yonetim dashboard — kurum KPI + sinif performans + risk."""
    try:
        from db_pool import db_fetchrow, db_fetch, db_fetchval

        # Kurum KPI
        ogrenci_sayi = await db_fetchval("SELECT COUNT(*) FROM students WHERE status='active'") or 0
        personel_sayi = await db_fetchval("SELECT COUNT(*) FROM staff") or 0
        sinif_sayi = await db_fetchval("SELECT COUNT(DISTINCT class_name) FROM students WHERE status='active' AND class_name IS NOT NULL") or 0
        etut_son30 = await db_fetchval(
            "SELECT COUNT(*) FROM etut_history WHERE tarih > NOW() - INTERVAL '30 days'"
        ) or 0

        # Sinif bazli performans (TYT toplam net ortalamasi — son 60 gun)
        # Not: students.soz_no=text, student_exams.soz_no=integer → cast
        sinif_perf = await db_fetch(
            """SELECT s.class_name, COUNT(DISTINCT e.soz_no) as ogrenci,
                      AVG(e.toplam) as ort_net
               FROM student_exams e
               JOIN students s ON s.soz_no = e.soz_no::text
               WHERE e.status='valid' AND e.exam_type='TYT'
                 AND e.exam_date > NOW() - INTERVAL '60 days'
                 AND s.class_name IS NOT NULL
               GROUP BY s.class_name
               HAVING COUNT(DISTINCT e.soz_no) >= 3
               ORDER BY ort_net DESC NULLS LAST LIMIT 15"""
        )
        sinif_list = [
            {"sinif": r["class_name"], "ogrenci": r["ogrenci"], "ort": round(float(r["ort_net"] or 0), 1)}
            for r in sinif_perf
        ]

        # En basarili 10 ogrenci — yerlesme_puani_ayt TEXT ('225,09' gibi virgul decimal)
        # REPLACE(',','.') + numeric cast
        top = await db_fetch(
            """SELECT sa.soz_no, s.full_name, s.class_name,
                      CAST(NULLIF(REPLACE(sa.yerlesme_puani_ayt, ',', '.'), '') AS numeric) as yer_puan
               FROM student_exam_analysis sa
               JOIN students s ON s.soz_no::text = sa.soz_no::text AND s.status='active'
               WHERE NULLIF(sa.yerlesme_puani_ayt,'') IS NOT NULL
                 AND CAST(NULLIF(REPLACE(sa.yerlesme_puani_ayt, ',', '.'), '') AS numeric) > 0
               ORDER BY yer_puan DESC LIMIT 10"""
        )
        top_list = [
            {"name": r["full_name"], "sinif": r["class_name"] or "-",
             "puan": round(float(r["yer_puan"] or 0), 2)}
            for r in top
        ]

        # Riskli ogrenciler (net dususu + yuksek devamsizlik)
        riskli = await db_fetch(
            """SELECT d.soz_no, s.full_name, s.class_name, d.toplam_saat
               FROM devamsizlik_sayisi d
               JOIN students s ON s.soz_no::text = d.soz_no::text AND s.status='active'
               WHERE d.toplam_saat > 150
               ORDER BY d.toplam_saat DESC LIMIT 10"""
        )
        risk_list = [
            {"name": r["full_name"], "sinif": r["class_name"] or "-", "saat": int(r["toplam_saat"])}
            for r in riskli
        ]

        # Admin icin ek: sistem health
        sistem = {}
        if role == "admin":
            routing_sayi = await db_fetchval(
                "SELECT COUNT(*) FROM routing_stats WHERE created_at > NOW() - INTERVAL '24 hours'"
            ) or 0
            claude_msg = await db_fetchval(
                "SELECT COUNT(*) FROM routing_stats WHERE response_source='claude' AND created_at > NOW() - INTERVAL '24 hours'"
            ) or 0
            ollama_msg = await db_fetchval(
                "SELECT COUNT(*) FROM routing_stats WHERE response_source='ollama' AND created_at > NOW() - INTERVAL '24 hours'"
            ) or 0
            fast_msg = await db_fetchval(
                "SELECT COUNT(*) FROM routing_stats WHERE response_source='fast_response' AND created_at > NOW() - INTERVAL '24 hours'"
            ) or 0

            # Kalite dagilim (son 7g)
            grade_dist = await db_fetch(
                """SELECT grade, COUNT(*) as sayi FROM quality_log
                   WHERE created_at > NOW() - INTERVAL '7 days'
                   GROUP BY grade ORDER BY grade"""
            )

            # Atlas yeni/regresyon
            atlas_new = await db_fetchval(
                "SELECT COUNT(*) FROM atlas_suggestions WHERE status='yeni'"
            ) or 0
            atlas_reg = await db_fetchval(
                "SELECT COUNT(*) FROM atlas_suggestions WHERE status='regresyon'"
            ) or 0

            sistem = {
                "routing_24h": int(routing_sayi),
                "claude_24h": int(claude_msg),
                "ollama_24h": int(ollama_msg),
                "fast_24h": int(fast_msg),
                "quality_grade": {r["grade"] or "?": int(r["sayi"]) for r in grade_dist},
                "atlas_yeni": int(atlas_new),
                "atlas_regresyon": int(atlas_reg),
            }

        return {
            "success": True,
            "role": role,
            "kpi": {
                "ogrenci": int(ogrenci_sayi),
                "personel": int(personel_sayi),
                "sinif": int(sinif_sayi),
                "etut_30g": int(etut_son30),
            },
            "sinif_perf": sinif_list,
            "top_10": top_list,
            "riskli": risk_list,
            "sistem": sistem,  # sadece admin dolu
        }
    except Exception as e:
        logger.error(f"Dashboard admin/mudur hata: {e}")
        return {"success": False, "message": str(e)[:150]}


QUICK_PROMPTS = {
    "ogrenci": [
        {"emoji": "📊", "title": "Dashboard", "action": "open_dashboard", "desc": "Gelişim trendin + öncelik konular — tek bakışta"},
        {"emoji": "📄", "title": "PDF Raporumu İndir", "prompt": "__pdf_report__", "desc": "Akademik durumun tek dosyada — paylaş"},
        {"emoji": "📊", "title": "Son denememi göster", "prompt": "son denememi göster", "desc": "Son sınav netlerin + ders bazlı tablo"},
        {"emoji": "📉", "title": "Zayıf konularım", "prompt": "zayıf konularım neler", "desc": "En çok hata yaptığın konular"},
        {"emoji": "📈", "title": "Deneme trendim", "prompt": "son 5 denememi grafikle göster", "desc": "Net değişimi canlı grafik"},
        {"emoji": "🎯", "title": "AYT/TYT puanım", "prompt": "ayt ve tyt puanlarımı göster", "desc": "Resmi yerleşme puanın"},
        {"emoji": "📅", "title": "Çalışma planı yap", "prompt": "bana haftalık kişisel çalışma planı yap", "desc": "YKS'ye kalan günle özel plan"},
        {"emoji": "🏫", "title": "Hedef üniversite", "prompt": "netlerimle hangi üniversiteye girebilirim", "desc": "Tercih önerileri"},
        {"emoji": "❓", "title": "YKS geri sayım", "prompt": "yks'ye kaç gün kaldı", "desc": "TYT/AYT tarihleri"},
        {"emoji": "📚", "title": "Çıkmış soru sor", "prompt": "2024 ayt matematik soruları", "desc": "Yıl + ders seçerek ara"},
        {"emoji": "💡", "title": "Kavram açıkla", "prompt": "türev nedir kısaca anlat", "desc": "İstediğin konuyu öğren"},
        {"emoji": "📸", "title": "Foto soru çözüm", "prompt": "foto ile soru nasıl çözerim", "desc": "Paperclip'ten soru at"},
        {"emoji": "📅", "title": "Devamsızlık", "prompt": "devamsızlığım kaç saat", "desc": "Toplam devamsızlık durumu"},
    ],
    "mudur": [
        {"emoji": "📊", "title": "Dashboard", "action": "open_dashboard", "desc": "Kurum KPI + sınıf performansı + riskli öğrenciler"},
        {"emoji": "🏢", "title": "Kurum özeti", "prompt": "kurum geneli öğrenci profili ve istatistik", "desc": "YKS/TYT/AYT sınıf dağılımı"},
        {"emoji": "🚨", "title": "Riskli öğrenciler", "prompt": "yüksek devamsızlık ve düşük net kombinasyonu olan riskli öğrenciler", "desc": "Veli görüşmesi gereken"},
        {"emoji": "👨‍🏫", "title": "Öğretmen performans", "prompt": "öğretmenlerin aylık performans raporunu grafiklerle göster", "desc": "Etüt sayısı + katılım"},
        {"emoji": "📊", "title": "Sınıf karşılaştırma", "prompt": "sınıflar arası net ortalaması karşılaştırması", "desc": "11/12 SAY/EA kıyas"},
        {"emoji": "📅", "title": "Bugünkü etütler", "prompt": "bugün planlanmış etütler ne", "desc": "Günlük etüt listesi"},
        {"emoji": "🏆", "title": "En başarılı öğrenciler", "prompt": "sınıf bazlı en başarılı 10 öğrenci", "desc": "AYT/TYT puan sıralaması"},
        {"emoji": "💬", "title": "Rehberlik notları", "prompt": "son bir haftaki rehberlik görüşmeleri", "desc": "Kritik not özet"},
        {"emoji": "📉", "title": "Net düşüş alarm", "prompt": "son 2 denemede net düşen öğrenciler", "desc": "Acil müdahale"},
    ],
    "rehber": [
        {"emoji": "📊", "title": "Dashboard", "action": "open_dashboard", "desc": "Risk radarı + duygu sinyali + devamsızlık + net düşüş"},
        {"emoji": "💙", "title": "Duygusal riskli öğrenciler", "prompt": "son 7 günde negatif duygu sinyali veren öğrenciler", "desc": "Kriz tespit"},
        {"emoji": "📝", "title": "Bugünkü rehberlik", "prompt": "bugün yapılacak rehberlik görüşmeleri", "desc": "Planlanan randevular"},
        {"emoji": "🎯", "title": "Motivasyon düşük", "prompt": "motivasyon sinyali zayıf olan öğrenciler", "desc": "Destek gerekenler"},
        {"emoji": "📊", "title": "Sınıf devamsızlık", "prompt": "sınıf bazlı devamsızlık raporu", "desc": "100 saat üstü uyarı"},
        {"emoji": "💬", "title": "Veli mesaj taslağı", "prompt": "riskli öğrenciler için veli mesaj taslağı oluştur", "desc": "Kişisel içerik"},
        {"emoji": "🧠", "title": "Öğrenci profil analiz", "prompt": "[öğrenci adı] için detaylı akademik + rehberlik profil", "desc": "İsim gir"},
    ],
    "ogretmen": [
        {"emoji": "📊", "title": "Dashboard", "action": "open_dashboard", "desc": "Program + etüt istatistik + sınıf performansı"},
        {"emoji": "📚", "title": "Haftalık programım", "prompt": "bu hafta ders programım", "desc": "Ders + etüt çizelgesi"},
        {"emoji": "🎯", "title": "Sınıfımın performansı", "prompt": "sınıfımdaki öğrencilerin son deneme performansı", "desc": "Net ortalaması"},
        {"emoji": "📉", "title": "Zayıf konu haritası", "prompt": "branşımda sınıf geneli en zayıf konular", "desc": "Etüt önceliği"},
        {"emoji": "📝", "title": "Etüt istatistiğim", "prompt": "bu sezon kaç etüt yaptım istatistik", "desc": "Aktiflik + katılım"},
    ],
    "yonetim": [
        {"emoji": "📊", "title": "Dashboard", "action": "open_dashboard", "desc": "Kurum KPI + sınıf performansı + en başarılı öğrenciler"},
        {"emoji": "🏢", "title": "Kurum dashboard", "prompt": "kurum geneli anlık durum özeti", "desc": "Öğrenci + öğretmen + finans-dışı"},
        {"emoji": "📊", "title": "Haftalık trend", "prompt": "son haftanın kullanım + kalite + öğrenci aktivitesi", "desc": "Yönetim KPI"},
        {"emoji": "🏆", "title": "En başarılı", "prompt": "sınıf bazlı en başarılı öğrenciler", "desc": "Üst sıralama"},
        {"emoji": "🚨", "title": "Kritik uyarılar", "prompt": "atlas_suggestions tablosundan yeni uyarıları göster", "desc": "Sistem tespitleri"},
    ],
    "admin": [
        {"emoji": "📊", "title": "Dashboard", "action": "open_dashboard", "desc": "Kurum KPI + sistem health + routing + atlas + kalite"},
        {"emoji": "🔧", "title": "Sistem durumu", "prompt": "sistem anlık durum ve son 24 saat özet", "desc": "Bridge + DB + API"},
        {"emoji": "📊", "title": "Routing istatistik", "prompt": "son 7 gün routing dağılımı ve p50/p95 süre", "desc": "Fast/Ollama/Claude"},
        {"emoji": "🧠", "title": "Atlas öneriler", "prompt": "atlas_suggestions yeni uyarıları göster", "desc": "Claude'un kendi tespitleri"},
        {"emoji": "📈", "title": "Günlük rapor", "prompt": "bugünün kullanım raporu", "desc": "Mesaj + kullanıcı + maliyet"},
        {"emoji": "🎯", "title": "Son deployment", "prompt": "son güncelleme ne yaptık", "desc": "KALDIGIM özet"},
        {"emoji": "🔴", "title": "Kritik alarmlar", "prompt": "son 24 saatteki kritik uyarılar ve durumları", "desc": "Müdahale gereken"},
        {"emoji": "📝", "title": "Not ekle", "prompt": "not et: ", "desc": "Talimat kaydet (sonuna yaz)"},
        {"emoji": "🎤", "title": "Web kodu", "prompt": "web kodu", "desc": "Test için OTP üret"},
    ],
}


# 22.1k — Dashboard cache (5dk TTL, per role+phone)
# 22.1l — Cache invalidation: yeni deneme/etut girildiginde cache temizle
_DASHBOARD_CACHE: dict = {}
_DASHBOARD_CACHE_TTL = 300  # 5 dakika


def _cache_get(key: str):
    import time
    entry = _DASHBOARD_CACHE.get(key)
    if not entry:
        return None
    if time.time() - entry["ts"] > _DASHBOARD_CACHE_TTL:
        _DASHBOARD_CACHE.pop(key, None)
        return None
    return entry["data"]


def _cache_set(key: str, data: dict):
    import time
    _DASHBOARD_CACHE[key] = {"ts": time.time(), "data": data}


def invalidate_cache(phone: str = "", role: str = "", all_roles: bool = False):
    """22.1l — Cache invalidation (external caller friendly).

    - phone+role: spesifik cache temizle
    - all_roles=True: tum dashboard cache sil (admin/mudur global event sonrasi)
    """
    if all_roles:
        _DASHBOARD_CACHE.clear()
        return
    if phone and role:
        _DASHBOARD_CACHE.pop(f"{role}:{phone}", None)
    elif phone:
        # Phone icin hangi role varsa hepsini sil
        for k in list(_DASHBOARD_CACHE.keys()):
            if k.endswith(f":{phone}"):
                _DASHBOARD_CACHE.pop(k, None)


# 22.1m — Çalışma planı takvim export (.ics)
@router.post("/plan-ics")
async def plan_ics_export(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """
    Çalışma planını .ics olarak indir. Body: {"plan": [{"gun","saat","sure_dk","ders","konu","yontem"}]}
    Kullanıcı Google Calendar / Apple Calendar'a tek tıkla ekler.
    """
    token = _extract_token(request, fermat_session)
    if not token:
        raise HTTPException(status_code=401, detail="Oturum yok")
    sess = await get_session(token)
    if not sess:
        raise HTTPException(status_code=401, detail="Oturum suresi doldu")

    try:
        body = await request.json()
        plan = body.get("plan") or []
        weeks = int(body.get("weeks") or 4)
        student_name = sess.get("name") or ""

        if not plan or not isinstance(plan, list):
            return JSONResponse(status_code=400,
                content={"success": False, "message": "Plan boş veya gecersiz"})

        from ics_export import plan_to_ics
        ics_content = plan_to_ics(plan, student_name=student_name, weeks=weeks)

        return Response(
            content=ics_content,
            media_type="text/calendar; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="fermat_calisma_plani.ics"',
            },
        )
    except Exception as e:
        logger.error(f"ICS export hata: {e}")
        return JSONResponse(status_code=500,
            content={"success": False, "message": str(e)[:200]})


@router.get("/dashboard")
async def student_dashboard(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """Öğrenci Dashboard (22.1i — pedagojik sinyal odaklı).

    Neo kuralı 19 Nisan 02:18:
    - Ham veri değil pedagojik sinyal
    - Son 10 deneme ders bazlı stacked area
    - Radar: ders güç profili
    - Öncelik 3 konu + NEDEN
    - DEVAMSIZLIK YOK (öğrenci ekranında gösterilmez)
    """
    token = _extract_token(request, fermat_session)
    if not token:
        raise HTTPException(status_code=401, detail="Oturum yok")
    sess = await get_session(token)
    if not sess:
        raise HTTPException(status_code=401, detail="Oturum süresi doldu")

    phone = sess["phone"]
    role = sess["role"]

    # 22.1k — Cache kontrol (5dk TTL, per phone+role)
    cache_key = f"{role}:{phone}"
    cached = _cache_get(cache_key)
    if cached:
        cached["_cached"] = True
        return cached

    # 22.1i2 — Rol bazli dashboard (her rol kendi veri seti)
    if role in ("admin", "mudur", "yonetim"):
        result = await _dashboard_admin_mudur(phone, role)
        if result.get("success"):
            _cache_set(cache_key, result)
        return result
    if role == "rehber":
        result = await _dashboard_rehber(phone)
        if result.get("success"):
            _cache_set(cache_key, result)
        return result
    if role == "ogretmen":
        result = await _dashboard_ogretmen(phone)
        if result.get("success"):
            _cache_set(cache_key, result)
        return result
    if role == "veli":
        # 22.1l — FLAG KAPALI: "yeni sezon" mesaji donuyor, aktif edilince kod hazir
        result = await _dashboard_veli(phone)
        if result.get("success"):
            _cache_set(cache_key, result)
        return result
    if role != "ogrenci":
        return {"success": False, "message": "Dashboard bu rol icin henuz hazir degil."}

    try:
        from db_pool import db_fetchrow, db_fetch
        student = await db_fetchrow(
            "SELECT soz_no, full_name, class_name FROM students "
            "WHERE REPLACE(phone,'+','') = $1 AND status='active' LIMIT 1",
            phone
        )
        if not student:
            return {"success": False, "message": "Öğrenci kaydı bulunamadı."}
        soz_no = student["soz_no"]
        sinif = student["class_name"] or ""

        # 22.1m — LGS öğrencisi için ayrı dashboard
        is_lgs = "8" in sinif or "LGS" in sinif.upper() or "6" in sinif
        if is_lgs:
            return await _dashboard_ogrenci_lgs(soz_no, student, sinif, phone)

        # Son 10 deneme (Neo: 5 değil 10) + ders bazlı netler
        trend = await db_fetch(
            """SELECT exam_name, exam_date, toplam, turkce, matematik,
                      fizik, kimya, biyoloji, tarih, cografya, felsefe, din_kulturu
               FROM student_exams
               WHERE soz_no::text = $1 AND status='valid' AND exam_type='TYT'
               ORDER BY exam_date DESC LIMIT 10""",
            str(soz_no)
        )
        trend_rev = list(reversed([
            {
                "name": (t["exam_name"] or "")[:25],
                "date": t["exam_date"].strftime("%d.%m") if t["exam_date"] else "",
                "toplam": float(t["toplam"] or 0),
                "turkce": float(t["turkce"] or 0),
                "matematik": float(t["matematik"] or 0),
                "fen": float((t["fizik"] or 0) + (t["kimya"] or 0) + (t["biyoloji"] or 0)),
                "sosyal": float((t["tarih"] or 0) + (t["cografya"] or 0) + (t["felsefe"] or 0) + (t["din_kulturu"] or 0)),
            }
            for t in trend
        ]))

        # Son deneme — KPI kartı için
        last = trend[0] if trend else None
        last_exam = None
        if last:
            last_exam = {
                "name": (last["exam_name"] or "")[:25],
                "date": last["exam_date"].strftime("%d.%m.%Y") if last["exam_date"] else "",
                "toplam": float(last["toplam"] or 0),
            }

        # Radar: ders güç profili (son 3 deneme ortalaması)
        # Her ders için ortalama net hesapla
        radar = {"Türkçe": 0, "Matematik": 0, "Fen": 0, "Sosyal": 0}
        if trend:
            n = min(3, len(trend))
            radar["Türkçe"] = round(sum(float(t["turkce"] or 0) for t in trend[:n]) / n, 1)
            radar["Matematik"] = round(sum(float(t["matematik"] or 0) for t in trend[:n]) / n, 1)
            radar["Fen"] = round(sum(float((t["fizik"] or 0) + (t["kimya"] or 0) + (t["biyoloji"] or 0)) for t in trend[:n]) / n, 1)
            radar["Sosyal"] = round(sum(float((t["tarih"] or 0) + (t["cografya"] or 0) + (t["felsefe"] or 0) + (t["din_kulturu"] or 0)) for t in trend[:n]) / n, 1)

        # Öncelik 3 konu — sinav_basari_yuzdesi düşük + NEDEN
        weak = await db_fetch(
            """SELECT ders, konu, sinav_hata_yuzdesi, sinav_hata_sayisi, tamamlandi
               FROM student_topic_tracker
               WHERE soz_no::text = $1 AND (tamamlandi IS NULL OR tamamlandi = FALSE)
               ORDER BY sinav_hata_yuzdesi ASC NULLS LAST LIMIT 3""",
            str(soz_no)
        )
        oncelik = []
        for w in weak:
            basari = float(w["sinav_hata_yuzdesi"] or 0)
            neden = ""
            if basari < 20:
                neden = f"Başarın %{int(basari)} — kazanım potansiyeli en yüksek"
            elif basari < 50:
                neden = f"Başarın %{int(basari)} — orta, 2 hafta çalışmayla yükselir"
            else:
                neden = f"Başarın %{int(basari)} — gelişime açık"
            oncelik.append({
                "ders": w["ders"],
                "konu": w["konu"],
                "basari": round(basari, 1),
                "neden": neden,
            })

        # YKS geri sayım
        from datetime import date
        today = date.today()
        yks_tyt = date(2026, 6, 13)
        yks_ayt = date(2026, 6, 14)
        days_tyt = (yks_tyt - today).days
        days_ayt = (yks_ayt - today).days

        # AYT puanı (text tipi — numeric cast)
        ayt = await db_fetchrow(
            """SELECT CAST(NULLIF(yerlesme_puani_ayt,'') AS numeric) as yer_puan
               FROM student_exam_analysis WHERE soz_no::text = $1""",
            str(soz_no)
        )
        ayt_puan = float(ayt["yer_puan"]) if ayt and ayt["yer_puan"] else None

        # 22.1m — Foto soru gecmisi (son 5)
        foto_gecmis = await db_fetch(
            """SELECT konu, ders, zorluk, created_at
               FROM foto_questions
               WHERE soz_no::text = $1 OR phone = $2
               ORDER BY created_at DESC LIMIT 5""",
            str(soz_no), phone
        )
        foto_list = [
            {
                "konu": (f["konu"] or "?")[:60],
                "ders": f["ders"] or "",
                "zorluk": f["zorluk"] or "",
                "tarih": f["created_at"].strftime("%d.%m %H:%M") if f["created_at"] else "",
            }
            for f in foto_gecmis
        ]

        # Pedagojik sinyal — trend yönü
        sinyal = "notr"
        sinyal_mesaj = "Veri yok"
        if len(trend_rev) >= 3:
            son_3 = [t["toplam"] for t in trend_rev[-3:]]
            if son_3[-1] > son_3[0] + 3:
                sinyal = "yukselis"
                sinyal_mesaj = f"Son 3 denemede toplam net +{round(son_3[-1]-son_3[0], 1)} artış"
            elif son_3[-1] < son_3[0] - 3:
                sinyal = "dusus"
                sinyal_mesaj = f"Son 3 denemede {round(son_3[0]-son_3[-1], 1)} net düşüş"
            else:
                sinyal = "stabil"
                sinyal_mesaj = "Son 3 denemede stabil seyir"

        result = {
            "success": True,
            "name": student["full_name"],
            "class": sinif,
            "yks": {"tyt_gun": days_tyt, "ayt_gun": days_ayt},
            "last_exam": last_exam,
            "trend": trend_rev,
            "radar": radar,
            "oncelik_3_konu": oncelik,
            "ayt_yerlesme_puani": ayt_puan,
            "sinyal": {"yon": sinyal, "mesaj": sinyal_mesaj},
            "foto_gecmis": foto_list,  # 22.1m — son 5 foto soru
            # NOT: devamsizlik_saat KALDIRILDI (Neo kuralı — öğrenci ekranında gösterilmez)
        }
        _cache_set(f"ogrenci:{phone}", result)  # 22.1k — 5dk cache
        return result
    except Exception as e:
        logger.error(f"Dashboard hatası: {e}")
        return {"success": False, "message": str(e)[:150]}


@router.get("/quick-prompts")
async def get_quick_prompts(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """Rol bazlı hazır prompt listesi — kullanıcı tıklayıp hızlı sorabilsin."""
    token = _extract_token(request, fermat_session)
    if not token:
        raise HTTPException(status_code=401, detail="Oturum yok")
    sess = await get_session(token)
    if not sess:
        raise HTTPException(status_code=401, detail="Oturum süresi doldu")

    role = sess.get("role", "ogrenci")
    # Admin = admin, diğerleri ana gruplarında
    prompts = QUICK_PROMPTS.get(role, QUICK_PROMPTS["ogrenci"])
    return {
        "role": role,
        "name": sess.get("name", ""),
        "prompts": prompts,
    }


@router.get("/history")
async def get_history(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """Gün bazlı sohbet geçmişi özeti (son 30 gün)."""
    token = _extract_token(request, fermat_session)
    if not token:
        raise HTTPException(status_code=401, detail="Oturum yok")
    sess = await get_session(token)
    if not sess:
        raise HTTPException(status_code=401, detail="Oturum süresi doldu")

    try:
        from db_pool import db_fetch
        rows = await db_fetch(
            """
            SELECT
                DATE(created_at) AS gun,
                COUNT(*) AS mesaj_sayisi,
                MIN(created_at) AS ilk_ts,
                MAX(created_at) AS son_ts,
                (ARRAY_AGG(content ORDER BY created_at)
                  FILTER (WHERE message_role='user' AND LENGTH(content) > 3 AND LENGTH(content) < 200))[1] AS ilk_soru
            FROM agent_conversations
            WHERE phone=$1 AND created_at > NOW() - INTERVAL '30 days'
            GROUP BY DATE(created_at)
            ORDER BY gun DESC
            LIMIT 30
            """,
            sess["phone"],
        )
        history = []
        for r in rows:
            history.append({
                "gun": r["gun"].isoformat() if r["gun"] else "",
                "mesaj_sayisi": r["mesaj_sayisi"],
                "ilk_soru": (r["ilk_soru"] or "")[:120],
                "saat": r["ilk_ts"].strftime("%H:%M") if r["ilk_ts"] else "",
            })
        return {"success": True, "history": history}
    except Exception as e:
        logger.error(f"History endpoint hatası: {e}")
        return {"success": False, "history": [], "error": str(e)[:100]}


@router.get("/history/{gun}")
async def get_history_day(
    gun: str,
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """Belirli bir günün tüm mesajları (yeniden yüklenecek)."""
    token = _extract_token(request, fermat_session)
    if not token:
        raise HTTPException(status_code=401, detail="Oturum yok")
    sess = await get_session(token)
    if not sess:
        raise HTTPException(status_code=401, detail="Oturum süresi doldu")

    # Tarih güvenlik — YYYY-MM-DD format kontrolü + date objesi parse (19 Nisan fix)
    import re as _re
    if not _re.match(r'^\d{4}-\d{2}-\d{2}$', gun):
        return JSONResponse(status_code=400, content={"success": False, "message": "Geçersiz tarih"})
    from datetime import date as _date
    try:
        gun_obj = _date.fromisoformat(gun)
    except ValueError:
        return JSONResponse(status_code=400, content={"success": False, "message": "Geçersiz tarih"})

    try:
        from db_pool import db_fetch
        rows = await db_fetch(
            """
            SELECT message_role, content, created_at
            FROM agent_conversations
            WHERE phone=$1 AND DATE(created_at) = $2
              AND message_role IN ('user', 'assistant')
              AND content IS NOT NULL AND LENGTH(content) > 0
              AND content NOT LIKE '[tool_calls:%'
              AND content NOT LIKE '[tool_results:%'
            ORDER BY created_at ASC
            """,
            sess["phone"], gun_obj,
        )
        messages = []
        for r in rows:
            messages.append({
                "role": "user" if r["message_role"] == "user" else "bot",
                "content": r["content"],
                "time": r["created_at"].strftime("%H:%M") if r["created_at"] else "",
            })
        return {"success": True, "gun": gun, "messages": messages}
    except Exception as e:
        logger.error(f"History day endpoint hatası: {e}")
        return {"success": False, "messages": [], "error": str(e)[:100]}


# ─── ADMIN VIEWS (22.1n-vizyon2) ─────────────────────────────────────────────
# Sadece admin/mudur rolü. Neo yeni sezon öncesi/sırasında insight doğrulama +
# outreach onay akışı için kullanır.

def _require_admin(sess: dict):
    if sess.get("role") not in ("admin", "mudur"):
        raise HTTPException(status_code=403, detail="Admin/Müdür yetkisi gerekli")


@router.get("/admin/insights/{soz_no}")
async def admin_insights(
    soz_no: int,
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """22.1n-vizyon2: Öğrenci insight'larını admin gözüyle listele.
    Aktif + pasif (supersede olmuş) tüm insight'lar + decay skorları.
    """
    token = _extract_token(request, fermat_session)
    sess = await get_session(token) if token else None
    if not sess:
        raise HTTPException(status_code=401, detail="Oturum yok")
    _require_admin(sess)

    try:
        from db_pool import db_fetch, db_fetchrow
        student = await db_fetchrow(
            "SELECT full_name, class_name FROM students WHERE soz_no::text=$1",
            str(soz_no),
        )
        rows = await db_fetch(
            """SELECT id, insight_type, content, confidence, source, active,
                      decay_score, stale_reason, created_at, last_seen_at,
                      superseded_by
               FROM student_insights
               WHERE soz_no=$1
               ORDER BY active DESC, decay_score DESC NULLS LAST, created_at DESC
               LIMIT 100""",
            int(soz_no),
        )
        return {
            "success": True,
            "student": dict(student) if student else {"full_name": "?", "class_name": "?"},
            "soz_no": soz_no,
            "insights": [
                {
                    "id": r["id"],
                    "tip": r["insight_type"],
                    "icerik": r["content"],
                    "kaynak": r["source"],
                    "aktif": r["active"],
                    "guven": round(float(r["decay_score"] or 0), 2),
                    "stale_reason": r["stale_reason"],
                    "superseded_by": r["superseded_by"],
                    "created": r["created_at"].isoformat() if r["created_at"] else None,
                    "son_gorulme": r["last_seen_at"].isoformat() if r["last_seen_at"] else None,
                }
                for r in rows
            ],
            "toplam": len(rows),
            "aktif_sayi": sum(1 for r in rows if r["active"]),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"admin_insights hata: {e}")
        return {"success": False, "error": str(e)[:100]}


@router.get("/admin/conversations", response_class=HTMLResponse)
async def admin_conversations(
    request: Request,
    days: int = 7,
    phone: Optional[str] = None,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """Oturum 25.6: Admin konusma log HTML viewer.

    Query params:
      - days=7 (default) | 1 | 3 | 30 | 0 (tum gecmis)
      - phone=905xxxxx (opsiyonel, tek kisi filtrele)

    Erisim: admin veya mudur rolu (_require_admin).
    Ornek: https://api.fermategitimkurumlari.com/admin/conversations?days=2
    """
    token = _extract_token(request, fermat_session)
    sess = await get_session(token) if token else None
    if not sess:
        # Session yoksa /chat/login-tarzi redirect
        raise HTTPException(status_code=401, detail="Oturum yok — önce /chat'e giriş yapın")
    _require_admin(sess)

    # Guvenlik: days makul araliga sabitle
    try:
        days = max(0, min(int(days), 365))
    except Exception:
        days = 7

    try:
        from conversation_viewer import get_conversations, generate_html
        conversations, users, period_label = await get_conversations(days=days)
        # Phone filtre — tek kisiye daralt
        if phone:
            phone_clean = phone.replace("+", "").strip()
            conversations = {
                p: msgs for p, msgs in conversations.items()
                if p == phone_clean or p.endswith(phone_clean[-4:])
            }
            period_label += f" | Filtre: {phone[-4:]}"
        html_out = generate_html(conversations, users, period_label)
        return HTMLResponse(content=html_out, status_code=200)
    except Exception as e:
        logger.error(f"admin_conversations hata: {e}")
        raise HTTPException(status_code=500, detail=f"HTML üretilemedi: {str(e)[:100]}")


@router.get("/admin/outreach-pending")
async def admin_outreach_pending(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """22.1n-vizyon2: outreach_pending tablosundaki onay bekleyen mesajlar.
    Neo yeni sezonda toplu onay verir / reddeder.
    """
    token = _extract_token(request, fermat_session)
    sess = await get_session(token) if token else None
    if not sess:
        raise HTTPException(status_code=401, detail="Oturum yok")
    _require_admin(sess)

    try:
        from db_pool import db_fetch, db_fetchval
        pending = await db_fetch(
            """SELECT id, to_phone, text, reason, status,
                      blocked_at, approved_by, approved_at, sent_at
               FROM outreach_pending
               WHERE status='pending'
               ORDER BY blocked_at DESC LIMIT 200"""
        )
        total = await db_fetchval("SELECT COUNT(*) FROM outreach_pending WHERE status='pending'")
        by_reason = await db_fetch(
            """SELECT reason, COUNT(*) AS cnt
               FROM outreach_pending WHERE status='pending'
               GROUP BY reason ORDER BY cnt DESC LIMIT 10"""
        )
        return {
            "success": True,
            "bekleyen": int(total or 0),
            "ozet_gerekce": [{"reason": r["reason"] or "?", "count": r["cnt"]} for r in by_reason],
            "mesajlar": [
                {
                    "id": r["id"],
                    "to": r["to_phone"],
                    "to_suffix": (r["to_phone"] or "")[-4:],
                    "text": r["text"],
                    "reason": r["reason"],
                    "blocked_at": r["blocked_at"].isoformat() if r["blocked_at"] else None,
                }
                for r in pending
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"admin_outreach_pending hata: {e}")
        return {"success": False, "error": str(e)[:100]}


@router.get("/admin/teacher-briefings")
async def admin_teacher_briefings(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
    status: str = "queued",
    limit: int = 50,
):
    """F1 (25.28): Öğretmen brief queue. Yeni sezonda WP gönderim aktive olur."""
    token = _extract_token(request, fermat_session)
    sess = await get_session(token) if token else None
    if not sess:
        raise HTTPException(status_code=401, detail="Oturum yok")
    _require_admin(sess)
    try:
        from db_pool import db_fetch, db_fetchval
        rows = await db_fetch(
            """SELECT id, teacher_name, class_name, lesson_label, scheduled_for,
                      LEFT(rendered_text, 400) AS preview, status, sent_at, created_at
               FROM teacher_briefing_queue
               WHERE status = $1
               ORDER BY scheduled_for ASC LIMIT $2""",
            status, limit
        )
        total = await db_fetchval(
            "SELECT COUNT(*) FROM teacher_briefing_queue WHERE status=$1", status
        )
        wp_active = await db_fetchval(
            "SELECT value FROM sistem_ayar WHERE key='TEACHER_BRIEFING_WP_ACTIVE'"
        )
        return {
            "success": True,
            "wp_active": (wp_active or "false").lower() == "true",
            "total": int(total or 0),
            "items": [dict(r) for r in rows],
        }
    except Exception as e:
        logger.error(f"admin_teacher_briefings hata: {e}")
        return {"success": False, "error": str(e)[:200]}


@router.get("/admin/student-followups")
async def admin_student_followups(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
    status: str = "queued",
    limit: int = 50,
):
    """F2 (25.28): Öğrenci follow-up queue."""
    token = _extract_token(request, fermat_session)
    sess = await get_session(token) if token else None
    if not sess:
        raise HTTPException(status_code=401, detail="Oturum yok")
    _require_admin(sess)
    try:
        from db_pool import db_fetch, db_fetchval
        rows = await db_fetch(
            """SELECT id, soz_no, student_name, trigger_event, priority,
                      LEFT(suggestion_text, 400) AS preview,
                      weak_topics, status, created_at
               FROM student_followups
               WHERE status = $1
               ORDER BY priority DESC, created_at DESC LIMIT $2""",
            status, limit
        )
        total = await db_fetchval(
            "SELECT COUNT(*) FROM student_followups WHERE status=$1", status
        )
        wp_active = await db_fetchval(
            "SELECT value FROM sistem_ayar WHERE key='FOLLOWUP_WP_ACTIVE'"
        )
        return {
            "success": True,
            "wp_active": (wp_active or "false").lower() == "true",
            "total": int(total or 0),
            "items": [dict(r) for r in rows],
        }
    except Exception as e:
        logger.error(f"admin_student_followups hata: {e}")
        return {"success": False, "error": str(e)[:200]}


@router.get("/admin/todo-escalations")
async def admin_todo_escalations(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
    status: str = "queued",
    limit: int = 50,
):
    """F4 (25.28): To-do reminder + escalation queue."""
    token = _extract_token(request, fermat_session)
    sess = await get_session(token) if token else None
    if not sess:
        raise HTTPException(status_code=401, detail="Oturum yok")
    _require_admin(sess)
    try:
        from db_pool import db_fetch, db_fetchval
        rows = await db_fetch(
            """SELECT id, todo_id, soz_no, student_name, target_role,
                      target_name, escalation_type, payload, status, created_at
               FROM todo_escalation_queue
               WHERE status = $1
               ORDER BY created_at DESC LIMIT $2""",
            status, limit
        )
        total = await db_fetchval(
            "SELECT COUNT(*) FROM todo_escalation_queue WHERE status=$1", status
        )
        wp_active = await db_fetchval(
            "SELECT value FROM sistem_ayar WHERE key='TODO_ESCALATION_WP_ACTIVE'"
        )
        return {
            "success": True,
            "wp_active": (wp_active or "false").lower() == "true",
            "total": int(total or 0),
            "items": [dict(r) for r in rows],
        }
    except Exception as e:
        logger.error(f"admin_todo_escalations hata: {e}")
        return {"success": False, "error": str(e)[:200]}


@router.post("/admin/tts-test")
async def admin_tts_test(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """F3 (25.28): TTS test endpoint — admin manuel ses üretip dinleyebilir."""
    token = _extract_token(request, fermat_session)
    sess = await get_session(token) if token else None
    if not sess:
        raise HTTPException(status_code=401, detail="Oturum yok")
    _require_admin(sess)
    try:
        body = await request.json()
        text = (body.get("text") or "").strip()
        voice = body.get("voice") or "nova"
        if not text:
            raise HTTPException(status_code=400, detail="text param zorunlu")
        from tts_handler import synthesize_speech
        result = await synthesize_speech(text, voice=voice)
        if not result:
            return {"success": False, "error": "TTS synth fail"}
        return {"success": True, **result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"admin_tts_test hata: {e}")
        return {"success": False, "error": str(e)[:200]}


@router.get("/student/daily/predicted-grade")
async def student_predicted_grade(
    request: Request,
    soz_no: int,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """F5 (25.28): Öğrenci Çalışmam panel YKS puan tahmin widget'ı."""
    token = _extract_token(request, fermat_session)
    sess = await get_session(token) if token else None
    if not sess:
        raise HTTPException(status_code=401, detail="Oturum yok")
    # Öğrenci sadece kendi soz_no'su için, admin/mudur herkes
    if sess.get("role") == "ogrenci":
        if int(sess.get("soz_no") or 0) != int(soz_no):
            raise HTTPException(status_code=403, detail="Yetki yok")
    try:
        from predicted_grade import get_widget_data
        data = await get_widget_data(soz_no)
        return {"success": True, **data}
    except Exception as e:
        logger.error(f"student_predicted_grade hata: {e}")
        return {"success": False, "error": str(e)[:200]}


class OutreachActionReq(BaseModel):
    action: str  # "approve" | "reject"
    ids: list[int] = []  # boş ise tümü


@router.post("/admin/outreach-action")
async def admin_outreach_action(
    body: OutreachActionReq,
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """22.1n-vizyon2: Outreach mesajlarını toplu onay/reddet.

    approve: status='approved' yapar (gönderim ayrı bir scheduler veya manuel ile gerçekleşir)
    reject:  status='rejected' yapar

    NOT: approve ETSEK bile OUTREACH_ENABLED=false iken gönderim yapılmaz!
    Neo önce onaylar, sonra env flag'i açar — iki aşamalı güvenlik.
    """
    token = _extract_token(request, fermat_session)
    sess = await get_session(token) if token else None
    if not sess:
        raise HTTPException(status_code=401, detail="Oturum yok")
    _require_admin(sess)

    action = body.action.strip().lower()
    if action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action: approve|reject")

    new_status = "approved" if action == "approve" else "rejected"
    approver = f"{sess.get('name','?')} ({sess['role']})"

    try:
        from db_pool import db_execute, db_fetchval
        if body.ids:
            await db_execute(
                """UPDATE outreach_pending
                   SET status=$1, approved_by=$2, approved_at=NOW()
                   WHERE id = ANY($3) AND status='pending'""",
                new_status, approver, body.ids,
            )
            count = len(body.ids)
        else:
            # Tümü
            rows = await db_fetchval("SELECT COUNT(*) FROM outreach_pending WHERE status='pending'")
            await db_execute(
                """UPDATE outreach_pending
                   SET status=$1, approved_by=$2, approved_at=NOW()
                   WHERE status='pending'""",
                new_status, approver,
            )
            count = int(rows or 0)

        return {"success": True, "action": action, "updated": count, "new_status": new_status}
    except Exception as e:
        logger.error(f"admin_outreach_action hata: {e}")
        return {"success": False, "error": str(e)[:100]}


@router.post("/logout")
async def logout_endpoint(
    response: Response,
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """Session sonlandır, cookie sil."""
    token = _extract_token(request, fermat_session)
    if token:
        await auth_logout(token)
    # delete_cookie — set_cookie'deki samesite/secure ile eşleşmeli
    response.delete_cookie(COOKIE_NAME, samesite="none", secure=True, httponly=True)
    return {"success": True}


# ═══════════════════════════════════════════════════════════════════════════════
# 25.40l (Neo direktif) — PWA PUSH NOTIFICATION ENDPOINTS
# Strateji: Öğrenciyi WhatsApp'tan PWA app'e ÇEKMENIN ana metodu.
# Flag KAPALI başlangıç — Yeni Sezon (1 Eyl) Neo aktive eder.
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/push/vapid-public-key")
async def get_vapid_public():
    """Frontend subscribe için VAPID public key. Anonim erişim OK (zaten public)."""
    try:
        from push_service import get_vapid_public_key
        key = get_vapid_public_key()
        if not key:
            return {"success": False, "error": "VAPID key yapılandırılmamış"}
        return {"success": True, "vapid_public_key": key}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/push/subscribe")
async def push_subscribe(
    payload: dict,
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """
    Kullanıcı bildirim izni verdi — subscription'ını backend'e gönder.

    Body:
      {
        "endpoint": "https://fcm.googleapis.com/...",
        "keys": {"p256dh": "...", "auth": "..."}
      }

    Auth: Cookie veya Bearer token gerek (anonim subscribe yasak — kim olduğunu bilmeliyiz).
    """
    token = _extract_token(request, fermat_session)
    if not token:
        raise HTTPException(status_code=401, detail="Oturum yok — önce giriş yap")
    sess = await get_session(token)
    if not sess:
        raise HTTPException(status_code=401, detail="Oturum geçersiz")

    sub = payload.get("subscription") or payload
    endpoint = sub.get("endpoint")
    keys = sub.get("keys") or {}
    p256dh = keys.get("p256dh")
    auth_key = keys.get("auth")

    if not endpoint or not p256dh or not auth_key:
        raise HTTPException(status_code=400, detail="endpoint+keys.p256dh+keys.auth zorunlu")

    user_agent = request.headers.get("user-agent", "")[:500]

    # soz_no çöz (öğrenci ise)
    soz_no = None
    try:
        from db_pool import db_fetchval
        phone_clean = (sess.get("phone") or "").replace("+", "")
        if phone_clean:
            soz_no = await db_fetchval(
                "SELECT soz_no FROM students WHERE REPLACE(phone, '+', '') = $1 AND status='active' LIMIT 1",
                phone_clean,
            )
    except Exception:
        pass

    try:
        from push_service import save_subscription
        result = await save_subscription(
            soz_no=int(soz_no) if soz_no else None,
            phone=sess.get("phone") or "",
            role=sess.get("role") or "ogrenci",
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth_key,
            user_agent=user_agent,
            user_name=sess.get("name") or "",
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Subscribe failed: {e}")


@router.post("/push/unsubscribe")
async def push_unsubscribe(
    payload: dict,
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """Kullanıcı izni iptal etti — subscription'ı pasifleştir."""
    token = _extract_token(request, fermat_session)
    if not token:
        raise HTTPException(status_code=401)
    sess = await get_session(token)
    if not sess:
        raise HTTPException(status_code=401)

    endpoint = (payload.get("endpoint") or "").strip()
    if not endpoint:
        raise HTTPException(status_code=400, detail="endpoint gerekli")

    try:
        from db_pool import db_execute
        await db_execute(
            "UPDATE push_subscriptions SET is_active=FALSE WHERE endpoint=$1 AND phone=$2",
            endpoint, (sess.get("phone") or "").replace("+", ""),
        )
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/push/test")
async def push_test(
    payload: dict,
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """
    Admin/mudur self-test — kendine push gönder.

    Body: {"title": "...", "body": "...", "click_url": "/chat"}  (hepsi opsiyonel)
    """
    token = _extract_token(request, fermat_session)
    if not token:
        raise HTTPException(status_code=401)
    sess = await get_session(token)
    if not sess or sess.get("role") not in ("admin", "mudur"):
        raise HTTPException(status_code=403, detail="Sadece admin/mudur")

    title = (payload.get("title") or "🎯 FermatAI Test").strip()[:80]
    body = (payload.get("body") or "Push notification altyapısı aktif. Sistem hazır.").strip()[:200]
    click_url = payload.get("click_url") or "/chat"

    try:
        from push_service import send_push_to_user
        result = await send_push_to_user(
            title=title,
            body=body,
            phone=sess.get("phone"),
            click_url=click_url,
            tag="fermatai_test",
            trigger_source="admin_test",
            force=True,  # Flag KAPALI olsa bile test geçsin
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/push/stats")
async def push_stats_endpoint(
    request: Request,
    days: int = 7,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """Admin/mudur push istatistik."""
    token = _extract_token(request, fermat_session)
    if not token:
        raise HTTPException(status_code=401)
    sess = await get_session(token)
    if not sess or sess.get("role") not in ("admin", "mudur", "yonetim"):
        raise HTTPException(status_code=403)

    try:
        from push_service import get_push_stats
        return await get_push_stats(days=max(1, min(days, 90)))
    except Exception as e:
        return {"error": str(e)}


@router.get("/sessions")
async def sessions_endpoint(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """Phone'un aktif tüm cihazlarını listele — kaç cihazda açık görmek için."""
    token = _extract_token(request, fermat_session)
    if not token:
        raise HTTPException(status_code=401, detail="Oturum yok")
    sess = await get_session(token)
    if not sess:
        raise HTTPException(status_code=401, detail="Oturum süresi doldu")
    active = await list_active_sessions(sess["phone"])
    # Şu anki token'ı işaretle
    for s in active:
        s["is_current"] = token.startswith(s["token_prefix"])
        # datetime'ları string'e çevir
        if s.get("otp_used_at"):
            s["giris"] = s["otp_used_at"].isoformat()
        if s.get("session_expires_at"):
            s["bitis"] = s["session_expires_at"].isoformat()
        if s.get("kalan"):
            total_sec = int(s["kalan"].total_seconds())
            s["kalan_dk"] = total_sec // 60
        # Orijinal datetime'ları kaldır (JSON serialize için)
        s.pop("otp_used_at", None)
        s.pop("session_expires_at", None)
        s.pop("kalan", None)
    return {"active": active, "count": len(active)}


@router.post("/logout-all")
async def logout_all_endpoint(
    response: Response,
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """Tüm cihazlardan çık (bu telefon numarasına bağlı)."""
    token = _extract_token(request, fermat_session)
    if not token:
        raise HTTPException(status_code=401, detail="Oturum yok")
    sess = await get_session(token)
    if not sess:
        raise HTTPException(status_code=401, detail="Oturum süresi doldu")
    n = await logout_all(sess["phone"])
    response.delete_cookie(COOKIE_NAME, samesite="none", secure=True, httponly=True)
    return {"success": True, "logged_out_count": n}


# ─── FOTO SORU ÇÖZÜM (Vision) ──────────────────────────────────

@router.post("/upload-photo")
async def upload_photo(
    request: Request,
    photo: UploadFile = File(...),
    caption: str = Form(default=""),
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """
    Foto soru çözümü — öğrenci fotoyu atar, Claude Vision çözer.
    Aynı WP pipeline — günlük 5 foto limiti paylaşılır.

    Accept: multipart/form-data
      - photo: image file (JPG/PNG, max 10MB)
      - caption: opsiyonel açıklama/soru metni
    Returns: {"success": bool, "solution": "...", "kalan_hak": int}
    """
    token = _extract_token(request, fermat_session)
    if not token:
        raise HTTPException(status_code=401, detail="Oturum yok")

    sess = await get_session(token)
    if not sess:
        raise HTTPException(status_code=401, detail="Oturum süresi doldu — tekrar giriş yap")

    # Dosya türü kontrolü
    content_type = (photo.content_type or "").lower()
    if not content_type.startswith("image/"):
        return JSONResponse(
            status_code=400,
            content={"success": False, "message": "Sadece JPG/PNG fotoğraf kabul edilir."}
        )

    # Boyut kontrolü (okumadan önce)
    image_bytes = await photo.read()
    if not image_bytes:
        return JSONResponse(
            status_code=400,
            content={"success": False, "message": "Boş dosya gönderildi."}
        )
    if len(image_bytes) > 10 * 1024 * 1024:
        return JSONResponse(
            status_code=413,
            content={"success": False, "message": "Fotoğraf çok büyük (max 10MB)."}
        )

    phone = sess["phone"]
    name = sess["name"]
    role = sess["role"]

    # Günlük limit kontrolü — WP ile PAYLAŞILAN _PHOTO_COUNTS
    try:
        from whatsapp_bridge import _PHOTO_COUNTS
        from datetime import date
        today_str = date.today().isoformat()
        pc = _PHOTO_COUNTS.get(phone, {"date": "", "count": 0})
        if pc["date"] != today_str:
            pc = {"date": today_str, "count": 0}
        # Admin/mudur/yonetim sınırsız, öğrenci 5/gün
        daily_limit = 999 if role in ("admin", "mudur", "yonetim") else 5
        if pc["count"] >= daily_limit:
            return JSONResponse(
                status_code=429,
                content={
                    "success": False,
                    "message": f"📸 Bugün foto hakkın doldu ({daily_limit}/gün). Yarın tekrar dene — veya soruyu yazarak sor.",
                    "kalan_hak": 0,
                }
            )
    except Exception as _lim_err:
        logger.warning(f"Foto limit kontrolü hatası: {_lim_err}")

    # Vision API çağrısı — WP ile aynı pipeline
    try:
        from whatsapp_bridge import _solve_photo_question
        solution = await _solve_photo_question(image_bytes, user_prompt=caption or "")
        if not solution or "API anahtari gerekli" in solution:
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "Vision API şu an erişilemiyor. Biraz sonra tekrar dene."}
            )

        # Limit sayacını artır
        pc["count"] = pc["count"] + 1
        _PHOTO_COUNTS[phone] = pc
        daily_limit = 999 if role in ("admin", "mudur", "yonetim") else 5
        kalan = max(0, daily_limit - pc["count"])

        # DB log
        try:
            from db_pool import db_execute
            await db_execute(
                "INSERT INTO agent_conversations (session_id, phone, role, message_role, content, tools_used) "
                "VALUES ($1,$2,$3,$4,$5,$6)",
                "web_photo", phone, role, "user", f"[FOTO SORU]{(' ' + caption) if caption else ''}", ["web_upload"]
            )
            # Oturum 23 (Neo UX): 4000→16000, Vision çözümleri uzun olabilir
            _sol_log = solution if len(solution) <= 16000 else (
                solution[:15800] + "\n\n[...devami log'a sigmadi — ogrenci tam metni aldi]"
            )
            await db_execute(
                "INSERT INTO agent_conversations (session_id, phone, role, message_role, content, tools_used) "
                "VALUES ($1,$2,$3,$4,$5,$6)",
                "web_photo", phone, role, "assistant", _sol_log, ["claude_vision"]
            )
        except Exception:
            pass

        logger.info(f"🌐📸 Web foto çözüm: {phone[-4:]} ({name}) kalan={kalan}/gün")
        return {
            "success": True,
            "solution": solution,
            "kalan_hak": kalan,
            "daily_limit": daily_limit,
        }

    except Exception as e:
        logger.error(f"Web foto çözüm hatası: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"Çözüm üretilemedi: {str(e)[:120]}"}
        )


# ─── STREAMING (Faz 2) ────────────────────────────────────────

# Akilli tokenize — kelime sinirlari + noktalama + emoji asamali
_CHUNK_RE = re.compile(r'(\S+\s*|\s+)', re.UNICODE)

# C16 — TTFT optimize (Oturum 22): Delay'ler %40 küçültüldü
# Önceki: cümle sonu 180ms, virgül 80ms, normal 35ms → ortalama 40-60 kelime/sn
# Şimdi: cümle sonu 110ms, virgül 50ms, normal 22ms → ortalama 65-90 kelime/sn
# Kullanıcı hızlı akış hisseder ama yine okunabilir.
def _chunk_delay(chunk: str) -> float:
    c = chunk.strip()
    if not c:
        return 0.003
    if c.endswith(('.', '!', '?', ':')):
        return 0.11  # önce 0.18
    if c.endswith((',', ';')):
        return 0.05  # önce 0.08
    if len(c) > 10:
        return 0.035  # önce 0.055
    return 0.022  # önce 0.035


async def _stream_text(text: str):
    """Metni kelime kelime SSE chunk'lari olarak gonder."""
    for m in _CHUNK_RE.finditer(text):
        chunk = m.group(0)
        if chunk:
            yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"
            await asyncio.sleep(_chunk_delay(chunk))
    yield f"data: {json.dumps({'done': True})}\n\n"


@router.post("/stream")
async def stream_message(
    body: SendMsgReq,
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """
    Streaming chat — Claude.ai deneyimi (pseudo-stream).
    Backend cevabı komple alır, kelime kelime SSE ile gönderir.
    Frontend ReadableStream ile okur, typing cursor ile gösterir.
    """
    fermat_session = _extract_token(request, fermat_session)
    if not fermat_session:
        raise HTTPException(status_code=401, detail="Oturum yok")

    sess = await get_session(fermat_session)
    if not sess:
        raise HTTPException(status_code=401, detail="Oturum geçersiz veya süresi dolmuş")

    msg = (body.message or "").strip()
    if not msg:
        async def empty_gen():
            yield f"data: {json.dumps({'chunk': 'Boş mesaj gönderdin. Bir şey yazar mısın?'}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        return StreamingResponse(empty_gen(), media_type="text/event-stream")

    # 22.1n-fikir4: Arşiv gününden gelen devamlı sohbet — context hazırla
    archive_context = ""
    if body.archive_day:
        try:
            from datetime import datetime as _dt
            gun_obj = _dt.strptime(body.archive_day, "%Y-%m-%d").date()
            from db_pool import db_fetch
            hist_rows = await db_fetch(
                """SELECT message_role, content FROM agent_conversations
                   WHERE phone=$1 AND DATE(created_at)=$2
                     AND message_role IN ('user', 'assistant')
                     AND content NOT LIKE '[tool_%'
                   ORDER BY created_at ASC LIMIT 30""",
                sess["phone"], gun_obj,
            )
            if hist_rows:
                lines = []
                for h in hist_rows[-20:]:  # Son 20 mesaj (token kontrolü)
                    who = "Öğrenci" if h["message_role"] == "user" else "Bot"
                    lines.append(f"{who}: {(h['content'] or '')[:300]}")
                archive_context = (
                    f"\n\n[ÖNCEKİ ARŞİV OTURUMU — {body.archive_day}]\n"
                    + "\n".join(lines)
                    + "\n[ARŞİV SONU — öğrenci şimdi buradan devam ediyor]\n"
                )
                logger.info(f"📂 Archive continuation: {body.archive_day} / {len(hist_rows)} msg")
        except Exception as _ae:
            logger.debug(f"archive context err: {_ae}")

    if len(msg) > 2000:
        async def too_long_gen():
            yield f"data: {json.dumps({'chunk': 'Mesajın çok uzun (>2000). Kısalt veya parçala.'}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        return StreamingResponse(too_long_gen(), media_type="text/event-stream")

    async def generator():
        try:
            # "Yazıyor..." event — frontend cursor'u hemen gostersin
            yield f"data: {json.dumps({'start': True, 'name': sess['name']}, ensure_ascii=False)}\n\n"

            # ── FAST PATH ── Fast response'a direkt bak, varsa ~5ms'de stream basla
            fast_reply = None
            try:
                from fast_responses import try_fast_response
                from fermat_core_agent import _get_caller_profile
                prof = await _get_caller_profile(sess["phone"])
                fast_reply = await try_fast_response(
                    message=msg,
                    role=sess["role"],
                    caller_phone=sess["phone"],
                    name=sess["name"],
                    soz_no=prof.get("soz_no"),
                    staff_name=prof.get("staff_name", ""),
                )
            except Exception as _fe:
                logger.debug(f"fast_response check err: {_fe}")

            if fast_reply:
                # Anında stream et — hiç bekleme yok
                logger.info(f"🌐 Web STREAM (fast): {sess['phone'][-4:]} → {len(fast_reply)}c")
                async for chunk_event in _stream_text(fast_reply):
                    yield chunk_event
                return

            # ── SLOW PATH — NATIVE STREAMING (Faz 4) ────────────────────
            # Claude API stream=True ile her token anında kullanıcıya.
            # Claude.ai ile birebir aynı deneyim — ilk kelime ~0.5-1s'de.
            yield f"data: {json.dumps({'thinking': 'Analiz ediyorum...'}, ensure_ascii=False)}\n\n"

            import asyncio as _aio
            from whatsapp_bridge import process_message

            # Queue: agent'tan SSE'ye chunk transport kanalı
            stream_q: _aio.Queue = _aio.Queue()

            # 22.1n-fikir4: Arşiv context varsa mesajın ÖNÜNE enjekte et (Claude okur, biz cevabımızı ayırırız)
            _msg_with_ctx = (archive_context + "\n\nYeni mesajım: " + msg) if archive_context else msg

            # Agent task — _stream_queue ile native stream
            agent_task = _aio.create_task(
                process_message(sess["phone"], _msg_with_ctx, channel="web", _stream_queue=stream_q)
            )

            thinking_cleared = False
            elapsed = 0.0
            QUEUE_POLL_SEC = 0.05  # C16: 0.1 → 0.05 (2x agresif, ilk chunk daha erken)
            _start_ts = _aio.get_event_loop().time()

            try:
                while True:
                    # Agent task bittiyse + queue boşsa çık
                    if agent_task.done() and stream_q.empty():
                        break

                    # Queue'dan event al (kısa timeout)
                    try:
                        ev = await _aio.wait_for(stream_q.get(), timeout=QUEUE_POLL_SEC)
                    except _aio.TimeoutError:
                        elapsed = _aio.get_event_loop().time() - _start_ts
                        # 25.41 (Neo bug 6 May): Render 170sn sürdü, kullanıcı 3dk
                        # boş gördü. Multi-stage heartbeat — her ~25sn'de yenile.
                        if not thinking_cleared:
                            _last_hb = getattr(stream_message, '_last_hb', {}).get(id(stream_q), 0)
                            if elapsed - _last_hb >= 25 or _last_hb == 0:
                                # Stage'e göre mesaj
                                if elapsed < 15:
                                    msg_text = "Düşünüyorum..."
                                elif elapsed < 40:
                                    msg_text = "🔍 Veriyi inceliyorum, biraz daha..."
                                elif elapsed < 80:
                                    msg_text = "🎨 Detaylı görsel/cevap hazırlıyorum (~1dk)..."
                                elif elapsed < 140:
                                    msg_text = "⏳ Karmaşık üretim — biraz daha sabır (~2dk)..."
                                elif elapsed < 200:
                                    msg_text = "🔍 İnce ayar yapıyorum, neredeyse hazır..."
                                else:
                                    msg_text = "⚙️ Hala çalışıyorum, vazgeçme..."
                                yield f"data: {json.dumps({'thinking': msg_text}, ensure_ascii=False)}\n\n"
                                if not hasattr(stream_message, '_last_hb'):
                                    stream_message._last_hb = {}
                                stream_message._last_hb[id(stream_q)] = elapsed
                        yield ": keepalive\n\n"
                        continue

                    ev_type, ev_data = ev

                    if ev_type == "chunk":
                        # İlk gerçek chunk gelince thinking'i temizle
                        if not thinking_cleared:
                            yield f"data: {json.dumps({'thinking_clear': True})}\n\n"
                            thinking_cleared = True
                        yield f"data: {json.dumps({'chunk': ev_data}, ensure_ascii=False)}\n\n"
                    elif ev_type == "tool_start":
                        # Oturum 25.31 — make_render_link ozel UX: text okunurken
                        # arka planda hazirlaniyor inline kart goster
                        if ev_data == "make_render_link":
                            yield f"data: {json.dumps({'render_pending': True})}\n\n"
                        else:
                            # Diger tool'lar icin klasik thinking
                            yield f"data: {json.dumps({'thinking': f'🔍 Veri çekiyorum ({ev_data})...'}, ensure_ascii=False)}\n\n"
                            thinking_cleared = False
                    elif ev_type == "tool_done":
                        # ev_data tuple olabilir: (tool_name, result_dict)
                        _tool_nm, _tool_res = (ev_data, None)
                        if isinstance(ev_data, tuple) and len(ev_data) == 2:
                            _tool_nm, _tool_res = ev_data
                        # make_render_link bittiginde URL ile inline buton
                        if _tool_nm == "make_render_link" and _tool_res and _tool_res.get("success"):
                            # 25.37 (Neo): quality_score + size_kb frontend'e ilet (badge için)
                            _payload = {
                                "url": _tool_res.get("url", ""),
                                "title": _tool_res.get("title") or "İnteraktif simülasyonu aç",
                                "quality_score": _tool_res.get("quality_score", 0),
                                "size_kb": _tool_res.get("size_kb", 0),
                                "uuid": _tool_res.get("uuid", "")
                            }
                            yield f"data: {json.dumps({'render_done': _payload}, ensure_ascii=False)}\n\n"
                        else:
                            yield f"data: {json.dumps({'thinking': '✓ Veriyi aldım, yazıyorum...'}, ensure_ascii=False)}\n\n"

                # Final sonucu al (timeout güvencesi)
                try:
                    reply = await _aio.wait_for(agent_task, timeout=5.0)
                except _aio.TimeoutError:
                    reply = ""

                # Eğer hiç chunk gelmediyse (fallback / hata) — reply'i yavaş akıt
                if not thinking_cleared and reply:
                    yield f"data: {json.dumps({'thinking_clear': True})}\n\n"
                    async for chunk_event in _stream_text(reply):
                        yield chunk_event

                elapsed = _aio.get_event_loop().time() - _start_ts
                logger.info(f"🌐 Web STREAM (native {elapsed:.1f}s): {sess['phone'][-4:]} → {len(reply or '')}c")

                # Akış bitti — done eventi
                yield f"data: {json.dumps({'done': True})}\n\n"

            except Exception as _str_err:
                logger.error(f"Native stream döngü hatası: {_str_err}")
                # Agent task iptal
                if not agent_task.done():
                    agent_task.cancel()
                raise

        except Exception as e:
            logger.error(f"Web chat stream hatası: {e}")
            err_chunk = "Teknik bir aksama var. Biraz sonra tekrar dene."
            yield f"data: {json.dumps({'chunk': err_chunk, 'error': True}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"

    headers = {
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",  # nginx/proxy buffer kapat
        "Connection": "keep-alive",
    }
    return StreamingResponse(generator(), media_type="text/event-stream", headers=headers)
