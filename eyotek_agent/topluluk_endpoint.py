"""
Topluluk Sohbet Modülü — 25.46+ (Neo 17 May QuitNow tarzı vizyon)

Öğrencilerin ortak yazışabileceği WhatsApp-grubu-tarzı sohbet alanı.
- Phone-based auth (kendi adıyla giriş, ACL ile rol)
- 1 dakika polling (WebSocket faz 2'de)
- Moderasyon: küfür/spam filtresi
- Bot @mention → otomatik cevap
- Mobile-first UI

Endpoint listesi:
  GET  /topluluk          → HTML UI sayfası
  GET  /topluluk/messages → JSON son N mesaj
  POST /topluluk/send     → Yeni mesaj gönder
  POST /topluluk/react    → Reaksiyon ekle/çıkar
  GET  /topluluk/online   → Çevrimiçi öğrenci sayısı (presence)
"""
from fastapi import APIRouter, HTTPException, Request, Body
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, List
from pathlib import Path
import re
import time
from loguru import logger

router = APIRouter(prefix="/topluluk", tags=["topluluk"])

# ─── KVKK: İsim maskeleme ───
def mask_name(full_name: str) -> str:
    """'Enes Karadaş' → 'Enes K.', 'Ahmet Mehmet Can' → 'Ahmet C.', tek ad → as-is."""
    if not full_name:
        return "Kullanıcı"
    parts = full_name.strip().split()
    if len(parts) == 1:
        return parts[0]
    first = parts[0]
    last_initial = parts[-1][0].upper() if parts[-1] else ""
    return f"{first} {last_initial}." if last_initial else first

# ─── Moderasyon: kufur/spam/KVKK ───
_BAD_WORDS = {
    "amk", "aq", "sg", "sik", "siktir", "orospu", "piç", "pic", "götveren",
    "ananı", "ananizi", "yarrak", "amına", "amına koyayım",
    # Spam patterns
    "casino", "bahis", "kumar", "tıkla kazan", "kazandın",
}
# KVKK koruma — mesajda gecmemesi gereken patternler
_TC_KIMLIK = re.compile(r"\b[1-9]\d{10}\b")           # 11 haneli, ilk hane >0
_PHONE_TR = re.compile(r"\b(0?5\d{2}[\s.-]?\d{3}[\s.-]?\d{2}[\s.-]?\d{2})\b")
_EMAIL = re.compile(r"\b[\w._%+-]+@[\w.-]+\.[a-z]{2,}\b", re.IGNORECASE)
_IBAN = re.compile(r"\bTR\d{2}[\s]?(?:\d{4}[\s]?){5}\d{2}\b")

def _moderate(text: str) -> Optional[str]:
    """Mesajı filtrele. Sorun varsa hata string'i döner, temizse None."""
    if not text or len(text.strip()) < 1:
        return "Boş mesaj gönderilemez."
    if len(text) > 500:
        return "Mesaj çok uzun (max 500 karakter)."
    lower = text.lower()
    for bad in _BAD_WORDS:
        if bad in lower:
            return "Mesajında uygunsuz ifade var, düzelt ve tekrar gönder."
    # Spam: aynı karakter 10+ tekrarı
    if re.search(r"(.)\1{10,}", text):
        return "Spam algılandı (tekrar eden karakter)."
    # KVKK: kişisel veri paylaşımı engelle
    if _TC_KIMLIK.search(text):
        return "🔒 KVKK: TC kimlik numarası paylaşma. Mesajını düzelt."
    if _PHONE_TR.search(text):
        return "🔒 KVKK: Telefon numarası paylaşma. Mesajını düzelt."
    if _EMAIL.search(text):
        return "🔒 KVKK: E-posta adresi paylaşma. Mesajını düzelt."
    if _IBAN.search(text):
        return "🔒 KVKK: IBAN paylaşma. Mesajını düzelt."
    return None

# ─── Rate limit (per-phone, in-memory) ───
_rate_log: dict = {}
def _rate_check(phone: str, max_per_minute: int = 6) -> bool:
    now = time.time()
    hist = _rate_log.get(phone, [])
    hist = [t for t in hist if now - t < 60]
    if len(hist) >= max_per_minute:
        return False
    hist.append(now)
    _rate_log[phone] = hist
    return True

# ─── Presence (çevrimiçi takip) ───
_presence: dict = {}  # phone -> last_seen_ts
def _mark_online(phone: str):
    _presence[phone] = time.time()
def _online_count() -> int:
    now = time.time()
    return sum(1 for ts in _presence.values() if now - ts < 120)  # 2dk içinde aktif

# ─── ENDPOINTS ───

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def topluluk_ui(request: Request):
    """Topluluk sohbet HTML sayfası."""
    html_path = Path(__file__).parent / "static" / "topluluk_ui.html"
    if not html_path.exists():
        raise HTTPException(404, "topluluk_ui.html bulunamadı")
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


class MessageOut(BaseModel):
    id: int
    user_name: str
    user_role: str
    message: str
    reply_to_id: Optional[int] = None
    reactions: dict = {}
    is_pinned: bool = False
    created_at: str
    is_me: bool = False


@router.get("/messages")
async def get_messages(request: Request, limit: int = 50, before_id: Optional[int] = None):
    """Son N mesajı çek (en yeni üstte)."""
    from db_pool import db_fetch
    caller_phone = await _get_caller_phone(request)
    if caller_phone:
        _mark_online(caller_phone)

    if before_id:
        sql = """
            SELECT id, user_phone, user_name, user_role, message, reply_to_id,
                   reactions, is_pinned, created_at
            FROM topluluk_messages
            WHERE is_deleted = FALSE AND id < $1
            ORDER BY id DESC
            LIMIT $2
        """
        rows = await db_fetch(sql, before_id, limit)
    else:
        sql = """
            SELECT id, user_phone, user_name, user_role, message, reply_to_id,
                   reactions, is_pinned, created_at
            FROM topluluk_messages
            WHERE is_deleted = FALSE
            ORDER BY id DESC
            LIMIT $1
        """
        rows = await db_fetch(sql, limit)

    msgs = []
    for r in rows:
        is_me = (r["user_phone"] == caller_phone) if caller_phone else False
        # KVKK: Baskalarinin tam ismini gosterme — sadece "Ad S." formati
        # Kendi mesajinda is_me=True, frontend zaten isim gostermiyor (msg.me .msg-header gizli)
        display_name = r["user_name"] if is_me else mask_name(r["user_name"])
        msgs.append({
            "id": r["id"],
            "user_name": display_name,
            "user_role": r["user_role"],
            "message": r["message"],
            "reply_to_id": r["reply_to_id"],
            "reactions": r["reactions"] or {},
            "is_pinned": r["is_pinned"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else "",
            "is_me": is_me,
        })
    return {"messages": list(reversed(msgs)), "online_count": _online_count()}


class SendBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)
    reply_to_id: Optional[int] = None


@router.post("/send")
async def send_message(request: Request, body: SendBody = Body(...)):
    """Yeni mesaj gönder."""
    from db_pool import db_fetchrow
    caller_phone = await _get_caller_phone(request)
    if not caller_phone:
        raise HTTPException(401, "Giriş yapmalısın.")

    # Rate limit
    if not _rate_check(caller_phone):
        raise HTTPException(429, "Çok hızlı yazıyorsun. Dakikada 6 mesajdan fazla olmaz.")

    # Moderasyon
    err = _moderate(body.message)
    if err:
        raise HTTPException(400, err)

    # User bilgi (acl_users + students)
    user_name, user_role = await _get_user_info(caller_phone)

    _mark_online(caller_phone)

    row = await db_fetchrow(
        """
        INSERT INTO topluluk_messages (user_phone, user_name, user_role, message, reply_to_id)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id, created_at
        """,
        caller_phone, user_name, user_role, body.message.strip(), body.reply_to_id
    )
    return {
        "success": True,
        "id": row["id"],
        "user_name": user_name,  # Kendi mesaj — tam isim (frontend zaten kendisi)
        "user_name_masked": mask_name(user_name),  # KVKK: baskalarinin gorecegi format
        "user_role": user_role,
        "created_at": row["created_at"].isoformat(),
    }


class ReactBody(BaseModel):
    message_id: int
    emoji: str = Field(..., min_length=1, max_length=4)


@router.post("/react")
async def react_message(request: Request, body: ReactBody = Body(...)):
    """Mesaja reaksiyon ekle/çıkar."""
    from db_pool import db_fetchrow
    caller_phone = await _get_caller_phone(request)
    if not caller_phone:
        raise HTTPException(401, "Giriş yapmalısın.")
    if body.emoji not in {"👍", "❤️", "😂", "😮", "😢", "🔥", "🎯", "💪"}:
        raise HTTPException(400, "Sadece şu emojiler: 👍 ❤️ 😂 😮 😢 🔥 🎯 💪")

    row = await db_fetchrow(
        "SELECT reactions FROM topluluk_messages WHERE id = $1 AND is_deleted = FALSE",
        body.message_id
    )
    if not row:
        raise HTTPException(404, "Mesaj bulunamadı.")
    reactions = row["reactions"] or {}
    users = set(reactions.get(body.emoji, []))
    if caller_phone in users:
        users.remove(caller_phone)
    else:
        users.add(caller_phone)
    if users:
        reactions[body.emoji] = list(users)
    elif body.emoji in reactions:
        del reactions[body.emoji]

    await db_fetchrow(
        "UPDATE topluluk_messages SET reactions = $1::jsonb WHERE id = $2 RETURNING id",
        __import__("json").dumps(reactions), body.message_id
    )
    return {"success": True, "reactions": reactions}


@router.get("/online")
async def online_count(request: Request):
    """Çevrimiçi öğrenci sayısı."""
    caller_phone = await _get_caller_phone(request)
    if caller_phone:
        _mark_online(caller_phone)
    return {"online": _online_count()}


# ─── HELPERS ───

async def _get_caller_phone(request: Request) -> Optional[str]:
    """Cookie/session'dan caller phone çek. web_chat token pattern ile."""
    try:
        from web_chat import _extract_token, COOKIE_NAME
        from web_chat_auth import get_session
        cookie_token = request.cookies.get(COOKIE_NAME)
        token = _extract_token(request, cookie_token)
        if not token:
            return None
        sess = await get_session(token)
        if not sess:
            return None
        return sess.get("phone")
    except Exception as e:
        logger.warning(f"_get_caller_phone hata: {e}")
        return None


async def _get_user_info(phone: str) -> tuple:
    """Phone'dan kullanıcı adı + rol çek (acl_users, students fallback)."""
    from db_pool import db_fetchrow
    # 1) acl_users
    row = await db_fetchrow(
        "SELECT full_name, role FROM acl_users WHERE phone = $1 AND is_active = TRUE",
        phone
    )
    if row:
        return row["full_name"] or "Misafir", row["role"] or "ogrenci"
    # 2) students
    row = await db_fetchrow(
        """SELECT full_name FROM students
           WHERE phone = $1 OR veli_cep = $1 OR anne_cep = $1 OR baba_cep = $1
           LIMIT 1""",
        phone
    )
    if row:
        return row["full_name"] or "Öğrenci", "ogrenci"
    return "Misafir", "guest"
