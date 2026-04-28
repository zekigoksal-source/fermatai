"""
FermatAI Web Chat — Auth Modülü
================================
OTP tabanlı giriş: öğrenci WhatsApp'tan "web kodu" ister,
bot 6 haneli kod verir, web'de kod + telefon ile giriş yapar.

Güvenlik:
- OTP 15dk, session 2 saat
- Günlük max 5 OTP/öğrenci
- Sadece ACL'de kayıtlı öğrenciler (WP bazlı dual-channel)
- Session token cookie: HttpOnly + SameSite=Lax
"""
import secrets
import string
from datetime import datetime, timedelta
from typing import Optional

from db_pool import db_fetch, db_fetchrow, db_fetchval, db_execute

OTP_LENGTH = 6
OTP_VALIDITY_MIN = 15
# Oturum 25.29 (Neo geri bildirim): 2h cok kisa — kullanici okurken atildi
# 8h + sliding refresh: aktif kullanici asla atilmaz, 8h tamamen inaktif kalirsa cikar
SESSION_VALIDITY_HOURS = 8
SESSION_SLIDING_REFRESH = True  # her get_session'da expires_at = NOW() + 8h ileri
DAILY_OTP_LIMIT = 5


def _gen_otp() -> str:
    """6 haneli OTP (123456 gibi — okunaklı, rakam)."""
    return ''.join(secrets.choice(string.digits) for _ in range(OTP_LENGTH))


def _gen_session_token() -> str:
    """URL-safe 32 byte random token."""
    return secrets.token_urlsafe(32)


async def request_otp(phone: str) -> dict:
    """
    OTP üret ve DB'ye kaydet. Öğrenci WP'den "web kodu" dediğinde çağrılır.

    Returns: {"success": bool, "code": "482193", "message": "...", "expires_min": 15}
    """
    phone_clean = phone.replace("+", "").strip()

    # ACL + students tablosunda var mı?
    profile = await db_fetchrow(
        """
        SELECT
            COALESCE(a.phone, s.phone) AS phone,
            COALESCE(a.full_name, s.full_name) AS full_name,
            COALESCE(a.role, 'ogrenci') AS role
        FROM (SELECT $1::text AS p) x
        LEFT JOIN acl_users  a ON REPLACE(a.phone,'+','') = x.p AND a.is_active
        LEFT JOIN students   s ON REPLACE(s.phone,'+','') = x.p
        WHERE a.phone IS NOT NULL OR s.phone IS NOT NULL
        LIMIT 1
        """,
        phone_clean,
    )

    if not profile:
        return {
            "success": False,
            "message": "Telefon numaran sistemde kayıtlı değil. Öğretmenine veya yönetime başvur.",
        }

    # Günlük limit kontrolü — admin/mudur/yonetim için daha yüksek limit
    today_count = await db_fetchval(
        "SELECT COUNT(*) FROM web_sessions WHERE phone=$1 AND otp_created_at::date=CURRENT_DATE",
        phone_clean,
    ) or 0

    # Admin ve üst yönetim geliştirme + test için daha fazla hak
    role = (profile["role"] or "ogrenci").lower()
    limit = 999 if role in ("admin", "mudur", "yonetim") else DAILY_OTP_LIMIT

    if today_count >= limit:
        return {
            "success": False,
            "message": f"Günde en fazla {limit} kez web kodu alabilirsin. Yarın tekrar dene.",
        }

    # 19 Nisan — OTP burst koruma: son 60 saniyede max 3 istek (brute force + spam onler)
    burst_count = await db_fetchval(
        "SELECT COUNT(*) FROM web_sessions WHERE phone=$1 AND otp_created_at > NOW() - INTERVAL '60 seconds'",
        phone_clean,
    ) or 0
    if burst_count >= 3:
        return {
            "success": False,
            "message": "Cok hizli kod talep ettin. 1 dakika bekleyip tekrar dene.",
        }

    # OTP üret
    code = _gen_otp()
    now = datetime.now()
    expires = now + timedelta(minutes=OTP_VALIDITY_MIN)

    await db_execute(
        """
        INSERT INTO web_sessions
            (phone, full_name, role, otp_code, otp_created_at, otp_expires_at)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        phone_clean,
        profile["full_name"] or "",
        profile["role"] or "ogrenci",
        code,
        now,
        expires,
    )

    # NOT: Eskiden ngrok URL linki de eklerdik ama Neo geribildirimiyle kaldırıldı
    # (güvenilmez gözüküyor + Wix analytics için tek kanal). Öğrenci kurumsal
    # siteden giriyor, Wix'ten geçip iframe'e ulaşıyor. Ana platform bağı korunuyor.
    return {
        "success": True,
        "code": code,
        "name": profile["full_name"] or "",
        "role": profile["role"] or "ogrenci",
        "expires_min": OTP_VALIDITY_MIN,
        "message": (
            f"🔐 *Web Kodun: {code}*\n\n"
            f"🌐 *https://www.fermategitimkurumlari.com/fermatai* adresinde "
            f"telefonun + bu kod ile giriş yap.\n\n"
            f"_Kod {OTP_VALIDITY_MIN} dakika geçerli._"
        ),
    }


async def verify_otp(phone: str, code: str, ip: str = "", user_agent: str = "") -> dict:
    """
    OTP doğrula, session token üret, cookie için döndür.

    Returns: {"success": bool, "token": "...", "name": "...", "role": "..."}
    """
    phone_clean = phone.replace("+", "").strip()
    code = code.strip()

    if not phone_clean or not code or len(code) != OTP_LENGTH:
        return {"success": False, "message": "Telefon ve kod gerekli."}

    # 19 Nisan — Brute force koruma: son 5dk'da 5+ yanlis deneme varsa bloklama uyarisi
    # hack_tracker tablosunu kullan (web_auth_fail namespace)
    try:
        from hack_tracker import is_hack_blocked
        if await is_hack_blocked(f"web_auth_{phone_clean}"):
            return {"success": False, "message": "Cok fazla yanlis kod denemesi. 1 saat bekle."}
    except Exception:
        pass

    # En son aktif (used edilmemiş, süresi dolmamış) OTP kaydını bul
    row = await db_fetchrow(
        """
        SELECT id, full_name, role, otp_expires_at
        FROM web_sessions
        WHERE phone=$1 AND otp_code=$2 AND otp_used_at IS NULL
        ORDER BY otp_created_at DESC
        LIMIT 1
        """,
        phone_clean,
        code,
    )

    if not row:
        # Yanlis girisi kaydet (brute force sayaci)
        try:
            from hack_tracker import record_attempt
            await record_attempt(f"web_auth_{phone_clean}")
        except Exception:
            pass
        return {"success": False, "message": "Kod hatalı veya süresi dolmuş. Yeni kod iste."}

    if row["otp_expires_at"] and row["otp_expires_at"] < datetime.now():
        return {"success": False, "message": "Kod süresi dolmuş. Yeni kod iste."}

    # TEK OTURUM vs MULTI-DEVICE kuralı (A12):
    # - Öğrenci/öğretmen/rehber: TEK oturum (WhatsApp Web mantığı)
    # - Admin/mudur/yonetim: MULTI-DEVICE izni (PC + iPad aynı anda)
    # Neo talebi — kurum yöneticileri hem masaüstü hem mobilden bakabilmeli.
    role_lower = (row["role"] or "ogrenci").lower()
    allow_multi_device = role_lower in ("admin", "mudur", "yonetim")

    if allow_multi_device:
        # Multi-device — eski session'lara DOKUNMA
        kicked = "UPDATE 0"
    else:
        # Tek oturum — eski session'ları kapat
        kicked = await db_execute(
            """
            UPDATE web_sessions
            SET session_expires_at = NOW()
            WHERE phone = $1
              AND session_expires_at > NOW()
              AND session_token IS NOT NULL
            """,
            phone_clean,
        )

    # Session token üret
    token = _gen_session_token()
    session_exp = datetime.now() + timedelta(hours=SESSION_VALIDITY_HOURS)

    await db_execute(
        """
        UPDATE web_sessions
        SET otp_used_at=NOW(),
            session_token=$1,
            session_expires_at=$2,
            ip_address=$3,
            user_agent=$4
        WHERE id=$5
        """,
        token, session_exp, ip[:64], user_agent[:256], row["id"],
    )

    # Kaç eski oturum kapatıldı logla
    try:
        kicked_count = int(str(kicked).split()[-1]) if kicked else 0
    except Exception:
        kicked_count = 0

    return {
        "success": True,
        "token": token,
        "name": row["full_name"] or "Öğrenci",
        "role": row["role"] or "ogrenci",
        "phone": phone_clean,
        "expires_hours": SESSION_VALIDITY_HOURS,
        "kicked_previous": kicked_count,  # eski cihaz sayısı (bilgi amaçlı)
    }


async def get_session(token: str) -> Optional[dict]:
    """
    Cookie'deki session_token'dan profil çöz.

    Returns: {"phone", "name", "role"} veya None (geçersiz/süresi dolmuş)

    Oturum 25.10c (Neo karari): ADMIN_API_KEY env eslemesi varsa direkt admin
    session olusturur. URL ?token=xxx ile dashboard'a hizli erisim icin.
    Kullanim: https://api.fermategitimkurumlari.com/admin/dashboard?token=ADMIN_API_KEY
    """
    if not token or len(token) < 8:
        return None

    # Oturum 25.10c: ADMIN_API_KEY shortcut (Neo dev erisimi icin)
    import os
    _admin_key = os.getenv("ADMIN_API_KEY") or os.getenv("AGENT_API_KEY")
    if _admin_key and token == _admin_key:
        return {
            "phone": "905051256802",
            "full_name": "Neo (API key)",
            "role": "admin",
            "name": "Neo",
        }

    if len(token) < 20:
        return None

    row = await db_fetchrow(
        """
        SELECT phone, full_name, role, session_expires_at
        FROM web_sessions
        WHERE session_token=$1
        LIMIT 1
        """,
        token,
    )

    if not row:
        return None

    if row["session_expires_at"] and row["session_expires_at"] < datetime.now():
        return None

    # Oturum 25.29: SLIDING REFRESH — her erisimde TTL ileri sar
    # Aktif kullanici asla atilmaz, sadece tam inaktif kalanlar cikar
    if SESSION_SLIDING_REFRESH:
        try:
            new_exp = datetime.now() + timedelta(hours=SESSION_VALIDITY_HOURS)
            await db_execute(
                "UPDATE web_sessions SET session_expires_at=$1 WHERE session_token=$2",
                new_exp, token,
            )
        except Exception:
            pass  # sliding fail kritik degil, session yine de gecerli

    return {
        "phone": row["phone"],
        "name": row["full_name"] or "Öğrenci",
        "role": row["role"] or "ogrenci",
    }


async def logout(token: str) -> bool:
    """Session'ı sonlandır — token'ı invalidate et."""
    if not token:
        return False
    await db_execute(
        "UPDATE web_sessions SET session_expires_at=NOW() WHERE session_token=$1",
        token,
    )
    return True


async def list_active_sessions(phone: str) -> list:
    """Phone'un aktif (süresi dolmamış) tüm web session'larını listele — cihaz takibi."""
    phone_clean = phone.replace("+", "").strip()
    rows = await db_fetch(
        """
        SELECT
            id,
            LEFT(session_token, 12) AS token_prefix,
            ip_address,
            LEFT(user_agent, 80) AS ua_short,
            otp_used_at,
            session_expires_at,
            (session_expires_at - NOW()) AS kalan
        FROM web_sessions
        WHERE phone = $1
          AND session_token IS NOT NULL
          AND session_expires_at > NOW()
        ORDER BY otp_used_at DESC
        """,
        phone_clean,
    )
    return [dict(r) for r in rows]


async def logout_all(phone: str) -> int:
    """Phone'un TÜM aktif session'larını sonlandır (tüm cihazlardan çık)."""
    phone_clean = phone.replace("+", "").strip()
    result = await db_execute(
        """
        UPDATE web_sessions SET session_expires_at = NOW()
        WHERE phone = $1 AND session_expires_at > NOW()
        """,
        phone_clean,
    )
    # asyncpg execute → "UPDATE N" string döner
    try:
        n = int(result.split()[-1])
    except Exception:
        n = 0
    return n


async def cleanup_expired():
    """24 saatten eski session kayıtlarını sil (bakım)."""
    await db_execute(
        "DELETE FROM web_sessions WHERE created_at < NOW() - INTERVAL '7 days'"
    )
