"""
FermatAI Güvenli Mesaj Gönderim Sistemi
========================================
Admin/müdür komutlarıyla WP üzerinden mesaj iletme.

GÜVENLİK PROTOKOLLERI:
  1. ONAY ZORUNLU — mesaj içeriği + alıcı gösterilir, admin "onayla" demeden gitmez
  2. TEK HEDEF — birden fazla eşleşme varsa liste gösterilir, seçim istenir
  3. ROLE KONTROLU — sadece admin/mudur mesaj gönderebilir
  4. LOG — her gönderilen mesaj DB'ye kaydedilir
  5. YASAKLI HEDEFLER — öğrencilere direkt mesaj admin izni gerektirir
"""

import asyncio
import os
from datetime import datetime
from typing import Optional

import httpx
from loguru import logger
from db_pool import db_fetch, db_execute

WA_TOKEN = os.getenv("WA_ACCESS_TOKEN", "")
WA_PHONE_ID = os.getenv("WA_PHONE_NUMBER_ID", "")


# Bilinen hedefler — hızlı erişim için
KNOWN_TARGETS = {
    # Tam isim → telefon eşleştirmesi
    "duygu": {"name": "Duygu Göksal", "phone": "905051256801", "role": "mudur"},
    "mahsum": {"name": "Mahsum Yalcın", "phone": "905462605446", "role": "mudur"},
    "örsel": {"name": "Örsel Koç", "phone": "905547043775", "role": "mudur"},
    "orsel": {"name": "Örsel Koç", "phone": "905547043775", "role": "mudur"},
    "kardelen": {"name": "Kardelen Koçak", "phone": "905533685087", "role": "rehber"},
    "elif": {"name": "Elif Sude Hunyas", "phone": "905312633238", "role": "rehber"},
    "vedat": {"name": "Vedat Öztekin", "phone": "905448240803", "role": "ogretmen"},
    "bilge": {"name": "Bilge Şarvan", "phone": "971585863751", "role": "yonetim"},
}


async def find_recipient(target_name: str) -> list[dict]:
    """Hedef kişiyi bul — birden fazla eşleşme olabilir."""
    target_lower = target_name.lower().strip()

    # 1. Bilinen hedefler — hızlı eşleşme
    if target_lower in KNOWN_TARGETS:
        return [KNOWN_TARGETS[target_lower]]

    # 2. DB'den ara — ACL tablosu
    matches = await db_fetch("""
        SELECT full_name, phone, role FROM acl_users
        WHERE is_active = true
        AND (LOWER(full_name) LIKE $1 OR TRANSLATE(UPPER(full_name),'ÇĞİÖŞÜ','CGIOSU') ILIKE UPPER($2))
        AND phone IS NOT NULL AND phone != ''
    """, f"%{target_lower}%", f"%{target_lower}%")

    return [{"name": r['full_name'], "phone": r['phone'].replace('+', ''), "role": r['role']} for r in matches]


def format_send_preview(recipient: dict, message: str) -> str:
    """Gönderim önizlemesi oluştur — onay için."""
    return (
        f"📨 *Mesaj Gönderim Onayı*\n\n"
        f"---\n\n"
        f"*Alıcı:* {recipient['name']} ({recipient['role']})\n"
        f"*Telefon:* {recipient['phone'][-4:]}\n\n"  # Son 4 hane güvenlik
        f"*Mesaj İçeriği:*\n"
        f"_{message[:300]}_\n\n"
        f"---\n\n"
        f"Bu mesajı göndermek için *'onayla'* yazın.\n"
        f"İptal için *'iptal'* yazın."
    )


def format_recipient_list(matches: list[dict]) -> str:
    """Birden fazla eşleşme — seçim listesi."""
    lines = [
        f"⚠️ *Birden fazla kişi bulundu:*\n",
        f"---\n",
    ]
    for i, m in enumerate(matches, 1):
        lines.append(f"  {i}. *{m['name']}* — {m['role']} (***{m['phone'][-4:]})")
    lines.append(f"\n---")
    lines.append(f"_Numara yazarak seçin (örn: '1')_")
    return "\n".join(lines)


async def send_wp_message(to_phone: str, message: str) -> bool:
    """WhatsApp mesajı gönder.

    TEST MODE GUARD (10 May Neo direktif): test mode'da gercek WP mesaj
    GONDERILMEZ — sadece log'a "dry-run" olarak yazilir.
    """
    phone_clean = to_phone.replace("+", "").strip()

    # ── Test mode bypass ──
    try:
        from test_mode import is_test_context
        if is_test_context():
            logger.warning(f"[WP_SEND] test mode → DRY-RUN (to={phone_clean[-4:]}, msg={message[:60]!r})")
            return True  # Test akisi devam etsin, gercek gonderim atlanir
    except Exception:
        pass

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"https://graph.facebook.com/v21.0/{WA_PHONE_ID}/messages",
                headers={
                    "Authorization": f"Bearer {WA_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={
                    "messaging_product": "whatsapp",
                    "to": phone_clean,
                    "type": "text",
                    "text": {"body": message},
                }
            )
            if r.status_code == 200:
                logger.info(f"WP mesaj gönderildi: {phone_clean}")
                return True
            else:
                logger.error(f"WP mesaj hatası: {r.status_code} — {r.text[:100]}")
                return False
    except Exception as e:
        logger.error(f"WP gönderim hatası: {e}")
        return False


async def log_sent_message(sender_phone: str, recipient: dict, message: str, success: bool):
    """Gönderilen mesajı DB'ye kaydet."""
    try:
        await db_execute("""
            INSERT INTO agent_conversations (session_id, phone, role, message_role, content, tools_used)
            VALUES ($1, $2, $3, $4, $5, $6)
        """, "wp_send", sender_phone, "admin", "assistant",
            f"[WP MESAJ → {recipient['name']}] {message[:500]}",
            ["wp_send"])
    except Exception:
        pass
