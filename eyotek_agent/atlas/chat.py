"""
ATLAS Chat — Neo ile diyalog katmanı (terminal + WP backend)

Terminal kullanımı:
    python -m atlas chat

WP entegrasyonu:
    Bu dosya `process_atlas_command(phone, message)` fonksiyonunu da export eder.
    whatsapp_bridge.py admin handler'da çağırılır.

Komutlar (terminal & WP):
    list           - bekleyen tüm önerileri listele
    detay <ID>     - öneri detay göster
    onayla <ID>    - öneriyi onayla (claude_code kuyruğuna alır)
    reddet <ID>    - öneriyi reddet
    not <ID> <metin> - öneriye not ekle
    yeniden tara   - observer + advisor çalıştır
    durum          - özet istatistik
    yardim         - bu listeyi göster
    cikis          - terminal modunda çık
"""
import asyncio
import os
import sys
import io
import re
from typing import Optional, Tuple

if os.name == 'nt':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from dotenv import load_dotenv
load_dotenv()

import sys as _sys
from pathlib import Path as _P
_parent = str(_P(__file__).resolve().parent.parent)
if _parent not in _sys.path:
    _sys.path.insert(0, _parent)
from db_pool import get_pool as _get_pool

NEO_PHONE = "905051256802"


async def _db():
    # Merkezi pool'dan connection acquire — caller close edecek
    pool = await _get_pool()
    return await pool.acquire()


# ─────────────────────────────────────────────────────────────────────────────
# CORE COMMANDS
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_list(channel: str = "terminal") -> str:
    """Bekleyen önerileri listele."""
    conn = await _db()
    try:
        rows = await conn.fetch("""
            SELECT id, severity, category, title, created_at
            FROM atlas_suggestions
            WHERE status='yeni'
            ORDER BY
              CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1
                            WHEN 'medium' THEN 2 ELSE 3 END,
              created_at DESC
            LIMIT 20
        """)
        if not rows:
            return "✨ Bekleyen öneri yok. 'yeniden tara' diyebilirsin."

        lines = ["📋 *BEKLEYEN ÖNERİLER*", ""]
        for r in rows:
            sev_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}.get(r['severity'], "⚪")
            lines.append(f"{sev_icon} #{r['id']} [{r['category']}] {r['title']}")
        lines.append("")
        lines.append("_'detay <ID>' ile aç, 'onayla <ID>' / 'reddet <ID>' ile karar ver_")
        return "\n".join(lines)
    finally:
        await conn.close()


async def cmd_detail(suggestion_id: int, channel: str = "terminal") -> str:
    """Öneri detayını göster."""
    conn = await _db()
    try:
        r = await conn.fetchrow("""
            SELECT id, severity, category, title, rationale, estimated_impact,
                   suggested_change, target_files, status, created_at, neo_note
            FROM atlas_suggestions WHERE id=$1
        """, suggestion_id)
        if not r:
            return f"❌ Öneri #{suggestion_id} bulunamadı."

        sev_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}.get(r['severity'], "⚪")
        lines = [
            f"{sev_icon} *ÖNERİ #{r['id']}* — {r['title']}",
            f"_Kategori: {r['category']} | Statü: {r['status']}_",
            "",
            "*🔍 Gerekçe:*",
            r['rationale'],
            "",
            "*📊 Beklenen Etki:*",
            r['estimated_impact'] or "(belirtilmemiş)",
            "",
            "*🛠 Önerilen Değişiklik:*",
            r['suggested_change'] or "(belirtilmemiş)",
            "",
            f"*📁 Etkilenen Dosyalar:* {', '.join(r['target_files'] or [])}",
        ]
        if r['neo_note']:
            lines.extend(["", f"*📝 Neo Notu:* {r['neo_note']}"])
        lines.extend([
            "",
            f"_'onayla {r['id']}' / 'reddet {r['id']}' / 'not {r['id']} <metin>' kullanabilirsin_"
        ])
        return "\n".join(lines)
    finally:
        await conn.close()


async def cmd_approve(suggestion_id: int, channel: str = "terminal") -> str:
    """Öneriyi onayla."""
    conn = await _db()
    try:
        r = await conn.fetchrow("""
            UPDATE atlas_suggestions
            SET status='onaylandi', approved_at=NOW()
            WHERE id=$1 AND status='yeni'
            RETURNING title
        """, suggestion_id)
        if not r:
            return f"❌ Öneri #{suggestion_id} onaylanamadı (zaten karara bağlanmış veya yok)."
        return (
            f"✅ *#{suggestion_id} ONAYLANDI*\n\n"
            f"📌 {r['title']}\n\n"
            f"_Bir sonraki Claude Code oturumunda implementasyon önerilecek._"
        )
    finally:
        await conn.close()


async def cmd_reject(suggestion_id: int, channel: str = "terminal") -> str:
    """Öneriyi reddet."""
    conn = await _db()
    try:
        r = await conn.fetchrow("""
            UPDATE atlas_suggestions
            SET status='reddedildi'
            WHERE id=$1 AND status='yeni'
            RETURNING title
        """, suggestion_id)
        if not r:
            return f"❌ Öneri #{suggestion_id} reddedilemedi (zaten karara bağlanmış veya yok)."
        return f"🚫 *#{suggestion_id} reddedildi*\n_'{r['title']}'_"
    finally:
        await conn.close()


async def cmd_note(suggestion_id: int, note: str, channel: str = "terminal") -> str:
    """Öneriye not ekle."""
    conn = await _db()
    try:
        r = await conn.fetchrow("""
            UPDATE atlas_suggestions
            SET neo_note=$2 WHERE id=$1
            RETURNING title
        """, suggestion_id, note)
        if not r:
            return f"❌ Öneri #{suggestion_id} bulunamadı."
        return f"📝 *#{suggestion_id} notu kaydedildi:* _{note}_"
    finally:
        await conn.close()


async def cmd_status(channel: str = "terminal") -> str:
    """Genel durum özeti."""
    conn = await _db()
    try:
        total_obs = await conn.fetchval("SELECT COUNT(*) FROM atlas_observations")
        new_sugs = await conn.fetchval("SELECT COUNT(*) FROM atlas_suggestions WHERE status='yeni'")
        approved = await conn.fetchval("SELECT COUNT(*) FROM atlas_suggestions WHERE status='onaylandi'")
        applied = await conn.fetchval("SELECT COUNT(*) FROM atlas_suggestions WHERE status='uygulandi'")
        rejected = await conn.fetchval("SELECT COUNT(*) FROM atlas_suggestions WHERE status='reddedildi'")
        last_scan = await conn.fetchval("SELECT MAX(created_at) FROM atlas_observations")

        critical_new = await conn.fetchval(
            "SELECT COUNT(*) FROM atlas_suggestions WHERE status='yeni' AND severity='critical'"
        )

        lines = [
            "🧠 *ATLAS DURUM*",
            "",
            f"📊 Toplam observation: {total_obs}",
            f"📋 Bekleyen öneri: *{new_sugs}* ({critical_new} kritik 🔴)",
            f"✅ Onaylanmış: {approved}",
            f"🛠 Uygulanmış: {applied}",
            f"🚫 Reddedilmiş: {rejected}",
            "",
            f"⏰ Son tarama: {last_scan.strftime('%d %b %H:%M') if last_scan else 'henüz yok'}",
        ]
        return "\n".join(lines)
    finally:
        await conn.close()


async def cmd_rescan(channel: str = "terminal") -> str:
    """Observer + Advisor çalıştır."""
    from atlas.observer import run_observation_scan
    from atlas.advisor import run_advise

    scan_id = await run_observation_scan(hours=24)
    new_sugs = await run_advise(hours=24)
    return (
        f"🔄 *YENİDEN TARAMA TAMAM*\n\n"
        f"Scan #{scan_id} (24h kapsam)\n"
        f"Yeni öneri: *{new_sugs}*\n\n"
        f"_'list' ile bak_"
    )


HELP_TEXT = """🧠 *ATLAS — İç Zihin Komutları*

📋 `list` — bekleyen önerileri listele
🔍 `detay <ID>` — öneri detay göster
✅ `onayla <ID>` — öneriyi onayla
🚫 `reddet <ID>` — öneriyi reddet
📝 `not <ID> <metin>` — öneriye not ekle
🔄 `yeniden tara` — observer + advisor çalıştır
📊 `durum` — özet istatistik
❓ `yardim` — bu listeyi göster

_Terminal modunda: `cikis` ile çıkış_"""


# ─────────────────────────────────────────────────────────────────────────────
# COMMAND PARSER — terminal + WP ortak
# ─────────────────────────────────────────────────────────────────────────────

async def process_atlas_command(message: str, channel: str = "terminal", phone: str = NEO_PHONE) -> str:
    """
    ATLAS komutu işle. WhatsApp bridge ve terminal ortak entry point.

    Sadece Neo (admin) için çalışır. Diğer roller None döndürür → bridge yetkisiz mesajı verir.
    """
    if phone != NEO_PHONE:
        return "🔒 ATLAS sadece admin (Neo) için açık."

    msg = message.strip().lower()

    # Komutsuz / boş / sadece "/atlas" geldiyse → menü göster
    if not msg or msg in ("/atlas", "atlas", "?", ""):
        status = await cmd_status(channel)
        listing = await cmd_list(channel)
        return f"{status}\n\n{'─' * 30}\n\n{listing}\n\n{'─' * 30}\n\n{HELP_TEXT}"

    if msg in ("yardim", "yardım", "help", "?"):
        return HELP_TEXT
    if msg in ("durum", "status"):
        return await cmd_status(channel)
    if msg in ("list", "liste", "öneriler", "oneriler"):
        return await cmd_list(channel)
    if msg in ("yeniden tara", "tara", "rescan", "yeniden"):
        return await cmd_rescan(channel)

    # Pattern komutlar
    m = re.match(r"^(detay|göster|goster|aç|ac)\s+(\d+)", msg)
    if m:
        return await cmd_detail(int(m.group(2)), channel)

    m = re.match(r"^(onayla|onay|kabul|evet)\s+(\d+)", msg)
    if m:
        return await cmd_approve(int(m.group(2)), channel)

    m = re.match(r"^(reddet|red|hayır|hayir|iptal)\s+(\d+)", msg)
    if m:
        return await cmd_reject(int(m.group(2)), channel)

    m = re.match(r"^(not|nottu)\s+(\d+)\s+(.+)", msg, re.IGNORECASE)
    if m:
        return await cmd_note(int(m.group(2)), m.group(3).strip(), channel)

    return f"❓ Anlamadım: '{message}'\n\n{HELP_TEXT}"


# ─────────────────────────────────────────────────────────────────────────────
# TERMINAL ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

async def terminal_chat():
    print("\n" + "=" * 70)
    print("ATLAS — FermatAI İç Zihin (Terminal Modu)")
    print("=" * 70)
    print(await cmd_status("terminal"))
    print("\n" + HELP_TEXT)
    print()

    while True:
        try:
            line = input("\n🧠 atlas> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGörüşmek üzere Reis. ⚡")
            break

        if not line:
            continue
        if line.lower() in ("cikis", "çıkış", "exit", "quit", "q"):
            print("Görüşmek üzere Reis. ⚡")
            break

        try:
            response = await process_atlas_command(line, channel="terminal")
            print()
            print(response)
        except Exception as e:
            print(f"⚠ Hata: {e}")


async def main():
    if len(sys.argv) > 1 and sys.argv[1] == "chat":
        await terminal_chat()
    else:
        # Default: durum + liste
        print(await cmd_status("terminal"))
        print()
        print(await cmd_list("terminal"))


if __name__ == '__main__':
    asyncio.run(main())
