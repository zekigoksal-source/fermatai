"""
Admin Bildirim Helper (Oturum 25.10d — Neo karari)
======================================================
Tum sistem alarmlari/uyarilari bu helper'dan gecsin.

DAVRANIS:
  1. notifications tablosuna her zaman yaz (dashboard'da gorulur)
  2. WP — sadece izinli saatler (08:00-20:00) VE severity yeterince yuksekse
     - critical: HER zaman WP (kriz, sistem cokmesi)
     - warning:  sadece 08-20 WP
     - info:     ASLA WP, sadece panel
  3. force_wp parametresi: gece bile mecburi WP gerekirse (ozel kriz)

NEDEN:
  Neo 26 Nisan 05:38 sabah "Gece etüt sync başarısız" mesaji aldi.
  Konusulmustu: gece WP YASAK, panel kullan. Bu helper o kurali sistemlestiriyor.

KULLANIM:
  from admin_notify import notify_admin
  await notify_admin(
      severity="warning",  # critical|warning|info
      category="eyotek",   # system|eyotek|atlas|student|teacher|duygu
      title="Gece etüt sync başarısız",
      body="Sebep: ...",
      metadata={"job": "etut_sync", "time": "02:30"},
  )
"""
from __future__ import annotations
import json
from datetime import datetime
from typing import Optional

from loguru import logger


NEO_PHONE = "905051256802"
WP_QUIET_START = 20    # 20:00 sonrasi WP YASAK
WP_QUIET_END = 8       # 08:00 oncesi WP YASAK


def _is_quiet_hour(now: Optional[datetime] = None) -> bool:
    """Su an WP gonderim YASAK saatler mi (gece 20-08 arasi)."""
    h = (now or datetime.now()).hour
    # 20-23 veya 0-7 → quiet
    return h >= WP_QUIET_START or h < WP_QUIET_END


async def notify_admin(
    severity: str,
    category: str,
    title: str,
    body: str = "",
    metadata: Optional[dict] = None,
    force_wp: bool = False,
    related_soz_no: Optional[int] = None,
    related_phone: Optional[str] = None,
) -> dict:
    """Admin'e bildirim — panel + (kosula bagli) WP.

    Returns: {"notification_id": int, "wp_sent": bool, "reason": str}
    """
    severity = (severity or "info").lower()
    if severity not in ("critical", "warning", "info", "success"):
        severity = "info"

    result = {"notification_id": None, "wp_sent": False, "reason": ""}

    # 1. Notifications tablosuna kayit
    try:
        from db_pool import db_fetchval as _dfv
        nid = await _dfv(
            """INSERT INTO notifications
               (severity, category, title, body, related_soz_no, related_phone, metadata)
               VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id""",
            severity, category, title[:200], body[:2000],
            related_soz_no, related_phone,
            json.dumps(metadata) if metadata else None,
        )
        result["notification_id"] = nid
    except Exception as e:
        logger.warning(f"[notify_admin] DB insert fail: {e}")

    # 2. WP gonderim karari
    quiet = _is_quiet_hour()
    should_wp = False
    if force_wp:
        should_wp = True
        result["reason"] = "force_wp"
    elif severity == "critical":
        # Critical her zaman gider (gece bile)
        should_wp = True
        result["reason"] = "critical_severity"
    elif severity == "info":
        # Info ASLA WP, sadece panel
        should_wp = False
        result["reason"] = "info_panel_only"
    elif quiet:
        # Warning ama gece — sadece panel
        should_wp = False
        result["reason"] = "quiet_hours"
    else:
        # Warning + gunduz → WP
        should_wp = True
        result["reason"] = "warning_daytime"

    if should_wp:
        try:
            # Lazy import (circular önleme)
            from whatsapp_bridge import send_wa_message
            wp_msg = f"{title}\n\n{body[:500]}" if body else title
            await send_wa_message(
                NEO_PHONE, wp_msg,
                _outreach=True, _reason=f"notify_admin_{category}",
            )
            result["wp_sent"] = True
        except Exception as e:
            logger.warning(f"[notify_admin] WP send fail: {e}")
            result["wp_sent"] = False

    logger.info(
        f"[notify_admin] {severity}/{category}: {title[:60]} → "
        f"panel=#{result['notification_id']}, wp={result['wp_sent']} ({result['reason']})"
    )
    return result


if __name__ == "__main__":
    # Test quiet hours logic
    from datetime import datetime
    test_hours = [0, 5, 7, 8, 9, 12, 19, 20, 22, 23]
    for h in test_hours:
        d = datetime(2026, 4, 26, h, 0, 0)
        q = _is_quiet_hour(d)
        print(f"Saat {h:02d}:00 → quiet={q}")
