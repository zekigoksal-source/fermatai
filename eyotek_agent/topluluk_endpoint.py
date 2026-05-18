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

# ─── Nickname Sistemi (25.46+ Neo 17 May) ───
_RESERVED_NICKS = {
    "admin", "yonetici", "moderator", "mod", "fermat", "fermatai",
    "bot", "system", "sistem", "ai", "gpt", "claude", "chatgpt",
    "zekigoksal", "zeki", "murathan", "mahsum", "duygu", "orsel",
    "ogretmen", "ogrenci", "mudur", "rehber", "yonetim",
    "null", "undefined", "none", "anonymous", "test", "deneme",
    "hocam", "hoca", "destek",
}
_NICK_BAD_WORDS = {
    "amk", "aq", "sg", "siktir", "orospu", "piç", "götveren",
    "amına", "yarrak", "ananı", "gibi",
    "casino", "bahis", "porn", "sex", "yasak",
}
_NICK_PATTERN = re.compile(r"^[a-zA-Z0-9_À-ſ][a-zA-Z0-9_À-ſ.]{1,28}[a-zA-Z0-9_À-ſ]$")

def validate_nickname(nick: str) -> Optional[str]:
    """Nickname format + içerik kontrol. Sorun string'i döner, OK ise None."""
    if not nick or not nick.strip():
        return "Nickname boş olamaz."
    nick = nick.strip()
    if len(nick) < 3:
        return "Nickname en az 3 karakter olmalı."
    if len(nick) > 30:
        return "Nickname en fazla 30 karakter olmalı."
    if not _NICK_PATTERN.match(nick):
        return "Nickname: harf/rakam/_/. ve nokta. Boşluk veya özel karakter olmaz."
    low = nick.lower()
    if low in _RESERVED_NICKS:
        return f"'{nick}' rezerve. Başka bir nickname seç."
    for bad in _NICK_BAD_WORDS:
        if bad in low:
            return "Nickname uygunsuz ifade içeriyor."
    return None

# Display-name cache (5dk TTL) — her mesaj icin DB hit etmemek icin
_display_cache: dict = {}  # phone → (display_name, expires_ts)

def _cache_get(phone: str) -> Optional[str]:
    e = _display_cache.get(phone)
    if not e: return None
    name, exp = e
    if time.time() > exp:
        del _display_cache[phone]
        return None
    return name

def _cache_set(phone: str, name: str):
    _display_cache[phone] = (name, time.time() + 300)  # 5dk

def _cache_invalidate(phone: str):
    if phone in _display_cache:
        del _display_cache[phone]

async def get_display_name(phone: str) -> str:
    """Phone → nickname VARSA onu, yoksa mask_name(real_name). Cache'li."""
    cached = _cache_get(phone)
    if cached:
        return cached
    from db_pool import db_fetchrow
    # 1) Nickname var mı?
    nick_row = await db_fetchrow(
        "SELECT nickname FROM topluluk_nicknames WHERE user_phone = $1",
        phone
    )
    if nick_row and nick_row["nickname"]:
        _cache_set(phone, nick_row["nickname"])
        return nick_row["nickname"]
    # 2) Yoksa mask_name(real_name)
    real_name, _ = await _get_user_info(phone)
    masked = mask_name(real_name)
    _cache_set(phone, masked)
    return masked

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
    """Son N mesajı çek (en yeni üstte).

    25.46+ (Neo 18 May): role-gate eklendi — onceden AUTH check YOKTU,
    anyone could view all messages without login. Simdi
    admin/mudur/yonetim/rehber/ogrenci dışı 403 alir.
    """
    from db_pool import db_fetch
    # 25.46+ Topluluk role-gate (mesaj icerik gizliligi icin sart)
    caller_phone, _topl_block = await _check_topluluk_access(request)
    if not caller_phone:
        raise HTTPException(401, _topl_block or "Giriş yapmalısın.")
    if _topl_block:
        raise HTTPException(403, _topl_block)
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

    # 25.46+: Nickname-aware display. Her phone icin nickname VARSA onu, yoksa mask_name.
    # Performans: tek query'de tum farkli phone'lari batch cek.
    phones = list({r["user_phone"] for r in rows})
    nick_map = {}
    if phones:
        from db_pool import db_fetch
        nick_rows = await db_fetch(
            "SELECT user_phone, nickname FROM topluluk_nicknames WHERE user_phone = ANY($1::text[])",
            phones
        )
        nick_map = {n["user_phone"]: n["nickname"] for n in nick_rows}

    msgs = []
    for r in rows:
        is_me = (r["user_phone"] == caller_phone) if caller_phone else False
        # Nickname varsa onu, yoksa mask_name
        nick = nick_map.get(r["user_phone"])
        if nick:
            display_name = nick
        else:
            display_name = mask_name(r["user_name"])
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
            "has_nickname": bool(nick),
        })
    return {"messages": list(reversed(msgs)), "online_count": _online_count()}


# ─── NICKNAME ENDPOINTS (25.46+ Neo 17 May) ───

@router.get("/me")
async def get_my_profile(request: Request):
    """Kendi profil: nickname, real_name (masked), can_change_at."""
    from db_pool import db_fetchrow
    # 25.46+ Topluluk role-gate (whitelist: admin/mudur/yonetim/rehber/ogrenci)
    caller_phone, _topl_block = await _check_topluluk_access(request)
    if not caller_phone:
        raise HTTPException(401, _topl_block or "Giriş yapmalısın.")
    if _topl_block:
        raise HTTPException(403, _topl_block)
    real_name, role = await _get_user_info(caller_phone)
    nick_row = await db_fetchrow(
        "SELECT nickname, change_count, last_changed_at FROM topluluk_nicknames WHERE user_phone = $1",
        caller_phone
    )
    nickname = nick_row["nickname"] if nick_row else None
    display = nickname if nickname else mask_name(real_name)
    # Cooldown: son degisiklikten 60sn sonra tekrar degistirebilir
    can_change_at = None
    if nick_row and nick_row["last_changed_at"]:
        from datetime import datetime, timedelta
        next_at = nick_row["last_changed_at"] + timedelta(seconds=60)
        if next_at > datetime.utcnow():
            can_change_at = next_at.isoformat()
    return {
        "phone_masked": "***" + caller_phone[-4:] if caller_phone else "",
        "real_name_masked": mask_name(real_name),
        "real_name_self": real_name,  # Sadece kendisi gorur
        "role": role,
        "nickname": nickname,
        "display_name": display,
        "change_count": nick_row["change_count"] if nick_row else 0,
        "can_change_at": can_change_at,
    }


class NicknameBody(BaseModel):
    nickname: str = Field(..., min_length=3, max_length=30)


@router.post("/nickname")
async def set_nickname(request: Request, body: NicknameBody = Body(...)):
    """Nickname belirle/değiştir. 60sn cooldown, 24h içinde max 5 değişim."""
    from db_pool import db_fetchrow, db_fetch
    # 25.46+ Topluluk role-gate (whitelist: admin/mudur/yonetim/rehber/ogrenci)
    caller_phone, _topl_block = await _check_topluluk_access(request)
    if not caller_phone:
        raise HTTPException(401, _topl_block or "Giriş yapmalısın.")
    if _topl_block:
        raise HTTPException(403, _topl_block)

    nick = body.nickname.strip()
    err = validate_nickname(nick)
    if err:
        raise HTTPException(400, err)

    # Cooldown + 24h limit kontrol
    existing = await db_fetchrow(
        "SELECT nickname, change_count, last_changed_at FROM topluluk_nicknames WHERE user_phone = $1",
        caller_phone
    )
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    if existing:
        if existing["last_changed_at"]:
            elapsed = (now - existing["last_changed_at"]).total_seconds()
            if elapsed < 60:
                raise HTTPException(429, f"60 saniye sonra değiştirebilirsin ({int(60-elapsed)}sn kaldı).")
        # 24h içinde max 5 değişim
        recent_changes = await db_fetchrow(
            """SELECT change_count FROM topluluk_nicknames
               WHERE user_phone = $1 AND last_changed_at > $2""",
            caller_phone, now - timedelta(hours=24)
        )
        if recent_changes and recent_changes["change_count"] >= 5:
            raise HTTPException(429, "24 saat içinde 5 değişim limitini aştın. Yarın tekrar dene.")

    # Çakışma: başka biri aynı nick'i mi kullanıyor?
    conflict = await db_fetchrow(
        "SELECT user_phone FROM topluluk_nicknames WHERE LOWER(nickname) = LOWER($1) AND user_phone != $2",
        nick, caller_phone
    )
    if conflict:
        raise HTTPException(409, f"'{nick}' zaten kullanılıyor. Başka bir nickname seç.")

    real_name, _ = await _get_user_info(caller_phone)
    old_nick = existing["nickname"] if existing else None
    history_entry = {"old": old_nick, "new": nick, "at": now.isoformat()}
    import json
    if existing:
        await db_fetchrow(
            """UPDATE topluluk_nicknames
               SET nickname = $1, real_name_snapshot = $2,
                   last_changed_at = NOW(), change_count = change_count + 1,
                   history = COALESCE(history, '[]'::jsonb) || $3::jsonb,
                   updated_at = NOW()
               WHERE user_phone = $4 RETURNING user_phone""",
            nick, real_name, json.dumps([history_entry]), caller_phone
        )
    else:
        await db_fetchrow(
            """INSERT INTO topluluk_nicknames
               (user_phone, nickname, real_name_snapshot, change_count, history)
               VALUES ($1, $2, $3, 1, $4::jsonb) RETURNING user_phone""",
            caller_phone, nick, real_name, json.dumps([history_entry])
        )

    _cache_invalidate(caller_phone)
    logger.info(f"[TOPLULUK_NICK] {caller_phone[-4:]} → '{nick}' (eski: '{old_nick}')")
    return {"success": True, "nickname": nick, "old_nickname": old_nick}


@router.delete("/nickname")
async def remove_nickname(request: Request):
    """Nickname kaldır → mask_name(real_name) default'a dön."""
    from db_pool import db_fetchrow
    # 25.46+ Topluluk role-gate (whitelist: admin/mudur/yonetim/rehber/ogrenci)
    caller_phone, _topl_block = await _check_topluluk_access(request)
    if not caller_phone:
        raise HTTPException(401, _topl_block or "Giriş yapmalısın.")
    if _topl_block:
        raise HTTPException(403, _topl_block)
    await db_fetchrow(
        "DELETE FROM topluluk_nicknames WHERE user_phone = $1 RETURNING user_phone",
        caller_phone
    )
    _cache_invalidate(caller_phone)
    real_name, _ = await _get_user_info(caller_phone)
    return {"success": True, "display_name": mask_name(real_name)}


# ─── ADMIN: Identity reveal (audit'li) ───

@router.get("/admin/identity/{message_id}")
async def admin_reveal_identity(request: Request, message_id: int, reason: str = ""):
    """Sadece admin: mesajın gerçek sahibini gör (audit'li)."""
    from db_pool import db_fetchrow
    # 25.46+ Topluluk role-gate (whitelist: admin/mudur/yonetim/rehber/ogrenci)
    caller_phone, _topl_block = await _check_topluluk_access(request)
    if not caller_phone:
        raise HTTPException(401, _topl_block or "Giriş yapmalısın.")
    if _topl_block:
        raise HTTPException(403, _topl_block)
    _, role = await _get_user_info(caller_phone)
    if role not in ("admin", "mudur"):
        raise HTTPException(403, "Bu işlem sadece admin/müdür için.")

    msg = await db_fetchrow(
        "SELECT user_phone, user_name FROM topluluk_messages WHERE id = $1",
        message_id
    )
    if not msg:
        raise HTTPException(404, "Mesaj bulunamadı.")
    nick_row = await db_fetchrow(
        "SELECT nickname FROM topluluk_nicknames WHERE user_phone = $1",
        msg["user_phone"]
    )
    revealed_nick = nick_row["nickname"] if nick_row else None

    # AUDIT — kim kimi ne sebeple açtı
    await db_fetchrow(
        """INSERT INTO topluluk_identity_audit
           (admin_phone, message_id, revealed_phone, revealed_real_name, revealed_nickname, reason)
           VALUES ($1, $2, $3, $4, $5, $6) RETURNING id""",
        caller_phone, message_id, msg["user_phone"],
        msg["user_name"], revealed_nick, (reason or "")[:200]
    )
    logger.warning(f"[KVKK_REVEAL] {caller_phone[-4:]} reveal msg#{message_id} → {msg['user_name']}")
    return {
        "message_id": message_id,
        "real_name": msg["user_name"],
        "phone": msg["user_phone"],
        "nickname": revealed_nick,
        "audit_logged": True,
    }


class SendBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)
    reply_to_id: Optional[int] = None


@router.post("/send")
async def send_message(request: Request, body: SendBody = Body(...)):
    """Yeni mesaj gönder."""
    from db_pool import db_fetchrow
    # 25.46+ Topluluk role-gate (whitelist: admin/mudur/yonetim/rehber/ogrenci)
    caller_phone, _topl_block = await _check_topluluk_access(request)
    if not caller_phone:
        raise HTTPException(401, _topl_block or "Giriş yapmalısın.")
    if _topl_block:
        raise HTTPException(403, _topl_block)

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
    # Nickname VARSA frontend optimistic update icin onu donder
    display = await get_display_name(caller_phone)
    return {
        "success": True,
        "id": row["id"],
        "user_name": user_name,  # Tam isim (sadece kendisine)
        "user_name_masked": mask_name(user_name),
        "display_name": display,  # nickname veya mask_name (digerleri ne goruyor)
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
    # 25.46+ Topluluk role-gate (whitelist: admin/mudur/yonetim/rehber/ogrenci)
    caller_phone, _topl_block = await _check_topluluk_access(request)
    if not caller_phone:
        raise HTTPException(401, _topl_block or "Giriş yapmalısın.")
    if _topl_block:
        raise HTTPException(403, _topl_block)
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

# 25.46+ (Neo 18 May): Topluluk role whitelist — sadece izinli rollerden
# kullanicilar topluluğa girebilir. Neo direktif:
#   IZINLI: admin (Neo), mudur (Duygu/Mahsum/Orsel), yonetim (Bilge/Murathan),
#           rehber (kurum rehberi), ogrenci (asil hedef)
#   YASAK:  ogretmen (simdilik kapali — sonra acabiliriz), veli (kesinlikle
#           kapali — ic dialog), misafir/guest (test eden risk dogurabilir)
# Neo: "Ogrenciler mesajlasiyor olacak, kontrolsuz dialog risk dogurabilir."
TOPLULUK_ALLOWED_ROLES = {"admin", "mudur", "yonetim", "rehber", "ogrenci"}
TOPLULUK_BLOCKED_ROLES = {"ogretmen", "veli", "misafir", "guest", "visitor"}


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


async def _check_topluluk_access(request: Request) -> tuple[Optional[str], Optional[str]]:
    """25.46+ Topluluk role-based access gate.

    Returns: (caller_phone, error_message)
      - (phone, None): erisim onayli
      - (None, "Giris yapmalisin"): authentication eksik
      - (phone, "Bu ozellik {role} rolu icin kapali"): role engellendi

    Caller mutlaka TOPLULUK_ALLOWED_ROLES icinde olmali. Aksi halde 403.
    """
    caller_phone = await _get_caller_phone(request)
    if not caller_phone:
        return None, "Giris yapmalisin."
    try:
        _, role = await _get_user_info(caller_phone)
    except Exception:
        role = ""
    role = (role or "").lower().strip()
    if role in TOPLULUK_BLOCKED_ROLES:
        return caller_phone, (
            f"Bu ozellik '{role}' rolu icin kapali. Topluluk sadece "
            "ogrenci, rehber ve yonetim icin acik."
        )
    if role not in TOPLULUK_ALLOWED_ROLES:
        return caller_phone, (
            f"Bu ozellik kullanima acik degil ('{role or 'tanimsiz'}' rolu). "
            "Topluluk yalniz dogrulanmis kurum uyeleri icin."
        )
    return caller_phone, None


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
