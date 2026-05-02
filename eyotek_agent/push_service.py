"""
FermatAI PWA Push Notification Service (Oturum 25.40l — Neo direktif)
=====================================================================

Stratejik konum: Öğrenciyi WhatsApp'tan PWA app'e ÇEKMENIN ana metodu.
WhatsApp = hızlı işlemler. PWA = uzun streaming + zengin format.
Push bildirim = nazik tetikleyici (mesaj atmak gibi taciz değil).

Kullanım senaryoları (Yeni Sezon — 1 Eyl 2026 sonrası):
  • Yeni deneme sonucu → "Analiz hazır, bak" + chat'e auto-deep-link
  • Etüt hatırlat (24h, 1h, başlama)
  • Sentiment alarm (3 gün sessizse "naber" tetikleyici)
  • Haftalık motivasyon ("Bu hafta 5 net ilerledin 💪")
  • Veli haftalık özet bildirimi
  • Karne / sınav günü hatırlatma

KURUMSAL PRO TASARIM:
  • Logo: fermatai-512.png (kurumsal kırmızı elma + glow)
  • Badge: fermatai-192.png (Android status bar)
  • Başlık: max 50 char, premium dil ("Yeni denemen analiz edildi")
  • Body: max 120 char, kişiselleştirilmiş ("{ad}, son denemen 92 net...")
  • Click: chat URL'ine yönlendirir + opsiyonel deep link (?soru=X)
  • Tag: notification grouping (aynı tip yeni gelirse eski silinir)
  • Actions: opsiyonel ["Aç", "Sonra"] butonları

GÜVENLİK + KVKK:
  • Sadece kayıtlı kullanıcı subscribe edebilir (auth gerek)
  • Subscription DB'de soz_no + phone bağlı (kim ne aldı denetlenebilir)
  • push_log tüm gönderimleri kaydeder (fail dahil)
  • 410 Gone gelirse subscription pasifleştir (eski cihaz)

FLAG: PUSH_NOTIFICATIONS_ACTIVE (.env, default false)
  • Yeni Sezon (1 Eyl 2026) Neo açar
  • Açıkken send_push() pywebpush ile gerçek HTTP gönderim yapar
  • Kapalıyken: push_log'a 'flag_off' kayıt + subscription tetiklemez
"""
from __future__ import annotations

import json
import os
import time
from typing import Optional

from loguru import logger

# pywebpush import (lazy — kurulu değilse module hata vermez)
try:
    from pywebpush import webpush, WebPushException
    _PYWEBPUSH_AVAIL = True
except ImportError:
    _PYWEBPUSH_AVAIL = False
    logger.warning("[PUSH] pywebpush kurulu degil — install: pip install pywebpush")


# .env'den oku
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")

# PEM private key — 2 mod desteği:
#   1. VAPID_PRIVATE_KEY_PATH (önerilen, multi-line PEM güvenli) — secrets/vapid_private.pem
#   2. VAPID_PRIVATE_KEY (.env raw, literal '\n' destekli — yedek)
def _load_vapid_private_key() -> str:
    pem_path = os.getenv("VAPID_PRIVATE_KEY_PATH", "/opt/fermatai/secrets/vapid_private.pem")
    if pem_path and os.path.exists(pem_path):
        try:
            with open(pem_path, "r", encoding="utf-8") as f:
                pem = f.read().strip()
            if pem.startswith("-----BEGIN"):
                return pem
        except Exception as e:
            logger.warning(f"[PUSH] PEM dosya okuma hatasi {pem_path}: {e}")
    raw = os.getenv("VAPID_PRIVATE_KEY", "")
    if raw:
        return raw.replace("\\n", "\n")
    return ""

VAPID_PRIVATE_KEY = _load_vapid_private_key()
VAPID_CLAIMS_EMAIL = os.getenv("VAPID_CLAIMS_EMAIL", "fermatvipegitim@gmail.com")
PUSH_NOTIFICATIONS_ACTIVE = os.getenv("PUSH_NOTIFICATIONS_ACTIVE", "false").lower() == "true"

# Default brand
PUSH_DEFAULT_ICON = "https://api.fermategitimkurumlari.com/static/img/fermatai-192.png"
PUSH_DEFAULT_BADGE = "https://api.fermategitimkurumlari.com/static/img/fermatai-192.png"
PUSH_DEFAULT_CLICK = "https://api.fermategitimkurumlari.com/chat"


# ═══════════════════════════════════════════════════════════════════════════════
# SUBSCRIPTION YONETIMI
# ═══════════════════════════════════════════════════════════════════════════════

async def save_subscription(
    soz_no: Optional[int],
    phone: str,
    role: str,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: str = "",
    user_name: str = "",
) -> dict:
    """
    Yeni subscription kaydet veya mevcut endpoint'i güncelle.
    Tek endpoint per cihaz — UNIQUE constraint.
    """
    from db_pool import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            # UPSERT — eski endpoint varsa güncelle (cihaz yeni izin verdi)
            row = await conn.fetchrow(
                """
                INSERT INTO push_subscriptions
                  (soz_no, phone, role, endpoint, p256dh, auth, user_agent, user_name, last_used_at, is_active)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW(), TRUE)
                ON CONFLICT (endpoint) DO UPDATE SET
                  soz_no = COALESCE(EXCLUDED.soz_no, push_subscriptions.soz_no),
                  phone = COALESCE(EXCLUDED.phone, push_subscriptions.phone),
                  role = COALESCE(EXCLUDED.role, push_subscriptions.role),
                  p256dh = EXCLUDED.p256dh,
                  auth = EXCLUDED.auth,
                  user_agent = EXCLUDED.user_agent,
                  user_name = EXCLUDED.user_name,
                  last_used_at = NOW(),
                  is_active = TRUE,
                  fail_count = 0
                RETURNING id, soz_no, phone, role
                """,
                soz_no, phone, role, endpoint, p256dh, auth, user_agent[:500], user_name[:200],
            )
            logger.info(f"[PUSH] Subscription kaydedildi: id={row['id']}, soz={row['soz_no']}, phone=...{(phone or '')[-4:]}")
            return {"success": True, "subscription_id": row["id"]}
        except Exception as e:
            logger.warning(f"[PUSH] Subscription kayit hatasi: {e}")
            return {"success": False, "error": str(e)}


async def get_subscriptions(
    soz_no: Optional[int] = None,
    phone: Optional[str] = None,
    role: Optional[str] = None,
) -> list[dict]:
    """Aktif subscription'lari getir (filtre opsiyonel)."""
    from db_pool import db_fetch

    where_parts = ["is_active=TRUE", "(fail_count < 5 OR fail_count IS NULL)"]
    params = []
    pid = 1

    if soz_no:
        where_parts.append(f"soz_no = ${pid}")
        params.append(soz_no)
        pid += 1
    if phone:
        where_parts.append(f"phone = ${pid}")
        params.append(phone.replace("+", ""))
        pid += 1
    if role:
        where_parts.append(f"role = ${pid}")
        params.append(role)
        pid += 1

    where_sql = " AND ".join(where_parts)
    rows = await db_fetch(
        f"""
        SELECT id, soz_no, phone, role, endpoint, p256dh, auth, user_agent, user_name
        FROM push_subscriptions
        WHERE {where_sql}
        ORDER BY last_used_at DESC NULLS LAST
        """,
        *params,
    )
    return [dict(r) for r in rows]


async def deactivate_subscription(subscription_id: int, reason: str = "manual") -> bool:
    """Subscription pasifleştir (kullanıcı PWA sildi, 410 Gone vb.)."""
    from db_pool import db_execute
    await db_execute(
        "UPDATE push_subscriptions SET is_active=FALSE, last_failed_at=NOW() WHERE id=$1",
        subscription_id,
    )
    logger.info(f"[PUSH] Subscription pasifleştirildi: id={subscription_id}, reason={reason}")
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# PUSH GONDERIM
# ═══════════════════════════════════════════════════════════════════════════════

def _build_payload(
    title: str,
    body: str,
    click_url: Optional[str] = None,
    icon: Optional[str] = None,
    badge: Optional[str] = None,
    image: Optional[str] = None,
    tag: Optional[str] = None,
    actions: Optional[list[dict]] = None,
    extra_data: Optional[dict] = None,
) -> dict:
    """
    Push payload — kurumsal pro tasarim.
    Service Worker push handler bu JSON'i parse edip notification gosterir.
    """
    payload = {
        "title": title[:80],  # iOS Safari sınırı
        "body": body[:200],   # Android max ~150-200
        "icon": icon or PUSH_DEFAULT_ICON,
        "badge": badge or PUSH_DEFAULT_BADGE,
        "click_url": click_url or PUSH_DEFAULT_CLICK,
        "tag": tag or "fermatai_default",
        "renotify": False,  # Aynı tag varsa yenisini gösterme (spam önleme)
        "vibrate": [100, 50, 100],  # iki kısa nazik titreşim
        "requireInteraction": False,  # Kullanıcı kapamazsa otomatik gider
        "silent": False,
        "timestamp": int(time.time() * 1000),
    }
    if image:
        payload["image"] = image  # Android — büyük hero görseli
    if actions:
        payload["actions"] = actions  # [{"action": "open", "title": "Aç"}]
    if extra_data:
        payload["data"] = extra_data
    return payload


async def send_push(
    subscription: dict,
    title: str,
    body: str,
    click_url: Optional[str] = None,
    icon: Optional[str] = None,
    image: Optional[str] = None,
    tag: Optional[str] = None,
    actions: Optional[list[dict]] = None,
    extra_data: Optional[dict] = None,
    trigger_source: str = "manual",
    force: bool = False,
) -> dict:
    """
    Tek subscription'a push gönder.

    Args:
      subscription: get_subscriptions() döndüren dict (id, endpoint, p256dh, auth, ...)
      force: True ise PUSH_NOTIFICATIONS_ACTIVE flag'i bypass — admin self-test için

    Returns: {success: bool, status: int, error: str|None}
    """
    payload = _build_payload(
        title=title, body=body, click_url=click_url, icon=icon, image=image,
        tag=tag, actions=actions, extra_data=extra_data,
    )
    payload_json = json.dumps(payload, ensure_ascii=False)

    # Flag kontrolü
    if not PUSH_NOTIFICATIONS_ACTIVE and not force:
        logger.debug(f"[PUSH] flag KAPALI — push gonderilmedi (sub_id={subscription.get('id')})")
        await _log_push(subscription, title, body, click_url, tag, trigger_source,
                        success=False, error_msg="flag_off")
        return {"success": False, "status": 0, "error": "PUSH_NOTIFICATIONS_ACTIVE=false"}

    if not _PYWEBPUSH_AVAIL:
        logger.error("[PUSH] pywebpush kurulu DEGIL — gonderim atlandi")
        return {"success": False, "status": 0, "error": "pywebpush_not_installed"}

    if not VAPID_PRIVATE_KEY:
        logger.error("[PUSH] VAPID_PRIVATE_KEY yok — gonderim atlandi")
        return {"success": False, "status": 0, "error": "vapid_key_missing"}

    sub_info = {
        "endpoint": subscription["endpoint"],
        "keys": {
            "p256dh": subscription["p256dh"],
            "auth": subscription["auth"],
        },
    }

    try:
        # Sync pywebpush — async wrap
        import asyncio
        def _do_send():
            return webpush(
                subscription_info=sub_info,
                data=payload_json,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": f"mailto:{VAPID_CLAIMS_EMAIL}"},
                ttl=86400,  # 24 saat geçerli
            )

        response = await asyncio.to_thread(_do_send)
        status = getattr(response, "status_code", 201)

        # Last-used update
        try:
            from db_pool import db_execute
            await db_execute(
                "UPDATE push_subscriptions SET last_used_at=NOW(), fail_count=0 WHERE id=$1",
                subscription["id"],
            )
        except Exception:
            pass

        await _log_push(subscription, title, body, click_url, tag, trigger_source,
                        success=True)
        logger.info(f"[PUSH] Gonderildi: sub_id={subscription['id']}, status={status}")
        return {"success": True, "status": status, "error": None}

    except WebPushException as e:
        status_code = getattr(e.response, "status_code", 0) if hasattr(e, "response") else 0
        # 410 Gone = subscription expire/sil — pasifleştir
        if status_code in (404, 410):
            await deactivate_subscription(subscription["id"], reason=f"http_{status_code}")
        else:
            try:
                from db_pool import db_execute
                await db_execute(
                    "UPDATE push_subscriptions SET fail_count=COALESCE(fail_count,0)+1, last_failed_at=NOW() WHERE id=$1",
                    subscription["id"],
                )
            except Exception:
                pass
        await _log_push(subscription, title, body, click_url, tag, trigger_source,
                        success=False, error_msg=f"WebPushException status={status_code}: {str(e)[:200]}")
        logger.warning(f"[PUSH] WebPushException sub={subscription['id']}: status={status_code} {str(e)[:100]}")
        return {"success": False, "status": status_code, "error": str(e)[:200]}

    except Exception as e:
        await _log_push(subscription, title, body, click_url, tag, trigger_source,
                        success=False, error_msg=str(e)[:200])
        logger.exception(f"[PUSH] Beklenmedik hata sub={subscription['id']}")
        return {"success": False, "status": 0, "error": str(e)[:200]}


async def send_push_to_user(
    title: str,
    body: str,
    *,
    soz_no: Optional[int] = None,
    phone: Optional[str] = None,
    click_url: Optional[str] = None,
    icon: Optional[str] = None,
    image: Optional[str] = None,
    tag: Optional[str] = None,
    actions: Optional[list[dict]] = None,
    extra_data: Optional[dict] = None,
    trigger_source: str = "manual",
    force: bool = False,
) -> dict:
    """
    Kullanıcının TÜM aktif subscription'larına gönder (ör: telefon + tablet + bilgisayar).
    En az biri kayıtlıysa cihaz başına ayrı push gönderir.
    """
    if not soz_no and not phone:
        return {"success": False, "error": "soz_no veya phone gerekli"}

    subs = await get_subscriptions(soz_no=soz_no, phone=phone)
    if not subs:
        logger.info(f"[PUSH] Subscription yok: soz={soz_no}, phone=...{(phone or '')[-4:]}")
        return {"success": False, "sent": 0, "total": 0, "reason": "no_subscriptions"}

    sent = 0
    failed = 0
    for sub in subs:
        result = await send_push(
            subscription=sub, title=title, body=body, click_url=click_url,
            icon=icon, image=image, tag=tag, actions=actions, extra_data=extra_data,
            trigger_source=trigger_source, force=force,
        )
        if result["success"]:
            sent += 1
        else:
            failed += 1

    return {
        "success": sent > 0,
        "sent": sent,
        "failed": failed,
        "total": len(subs),
    }


async def _log_push(subscription: dict, title: str, body: str, click_url: Optional[str],
                    tag: Optional[str], trigger_source: str,
                    success: bool, error_msg: Optional[str] = None):
    """Push gönderim log'u DB'ye yaz."""
    try:
        from db_pool import db_execute
        await db_execute(
            """
            INSERT INTO push_log
              (soz_no, phone, title, body, click_url, tag, trigger_source, success, error_msg, subscription_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
            subscription.get("soz_no"),
            subscription.get("phone"),
            title[:200],
            body[:500],
            click_url,
            tag,
            trigger_source,
            success,
            error_msg[:500] if error_msg else None,
            subscription.get("id"),
        )
    except Exception as e:
        logger.debug(f"[PUSH] Log DB hatasi (yutuldu): {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# ADMIN UTILITIES
# ═══════════════════════════════════════════════════════════════════════════════

def get_vapid_public_key() -> str:
    """Frontend subscribe için VAPID public key (base64 url-safe)."""
    return VAPID_PUBLIC_KEY


async def get_push_stats(days: int = 7) -> dict:
    """Admin: son N gün push istatistiği."""
    from db_pool import db_fetchrow
    row = await db_fetchrow(
        """
        SELECT
          COUNT(*) as toplam_gonderim,
          COUNT(*) FILTER (WHERE success) as basarili,
          COUNT(*) FILTER (WHERE NOT success) as basarisiz,
          COUNT(DISTINCT soz_no) as unique_kullanici,
          COUNT(DISTINCT trigger_source) as trigger_cesidi
        FROM push_log
        WHERE sent_at > NOW() - INTERVAL '1 day' * $1
        """,
        days,
    )
    sub_row = await db_fetchrow(
        "SELECT COUNT(*) AS aktif FROM push_subscriptions WHERE is_active=TRUE",
    )
    return {
        "donem_gun": days,
        "toplam_gonderim": row["toplam_gonderim"] if row else 0,
        "basarili": row["basarili"] if row else 0,
        "basarisiz": row["basarisiz"] if row else 0,
        "unique_kullanici": row["unique_kullanici"] if row else 0,
        "trigger_cesidi": row["trigger_cesidi"] if row else 0,
        "aktif_subscription": sub_row["aktif"] if sub_row else 0,
        "flag_aktif": PUSH_NOTIFICATIONS_ACTIVE,
    }
