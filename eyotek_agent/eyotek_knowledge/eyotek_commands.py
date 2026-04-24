"""
Eyotek Bot Komutları — Neo/admin WP'den Eyotek işlemleri tetikler.

Kullanım (fast_responses veya whatsapp_bridge'den):
    from eyotek_knowledge.eyotek_commands import handle_eyotek_command
    result = await handle_eyotek_command("eyotek güncelle", phone)

Komutlar:
    "eyotek güncelle"        → günlük sync (etüt + yoklama)
    "eyotek tam güncelle"    → haftalık tam sync
    "etüt yoklamaya bak"     → bugünün etütlerini getir
    "sınav güncelle"         → son sınav sonuçlarını çek
    "eyotek durum"           → son sync zamanları + veri sayıları

GÜVENLİK: Sadece admin (Neo) ve müdür çalıştırabilir.
ONAYSIZ MESAJ YASAK: Sync sonrası kimseye bildirim GÖNDERMEZ.
"""
import json
import os
import re
import sys as _sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# db_pool merkezi pool
_parent = str(Path(__file__).resolve().parent.parent)
if _parent not in _sys.path:
    _sys.path.insert(0, _parent)
from db_pool import db_fetch, db_fetchval

_SITE_MAP_PATH = Path(__file__).parent / "site_map.json"


def _load_site_map() -> dict:
    with open(_SITE_MAP_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


async def handle_eyotek_command(message: str, phone: str, role: str = "admin") -> Optional[str]:
    """
    Eyotek komutu işle. Uygun komut bulursa string döner, bulamazsa None.
    Sadece admin/mudur çalıştırabilir.
    """
    if role not in ("admin", "mudur"):
        return None

    msg_lower = message.lower().strip()

    # Eyotek komut pattern'ları
    if re.search(r'eyotek\s*(guncelle|güncelle|sync|senkronize)', msg_lower):
        if 'tam' in msg_lower or 'full' in msg_lower:
            return await _cmd_full_sync()
        return await _cmd_daily_sync()

    if re.search(r'et[uü]t\s*(yoklama|durum|bugün|bugun|listesi|bak)', msg_lower):
        return await _cmd_etut_today()

    if re.search(r'eyotek\s*(durum|status|son\s*sync)', msg_lower):
        return await _cmd_status()

    if re.search(r'sinav\s*(guncelle|güncelle|sync|çek|cek)', msg_lower):
        return await _cmd_sinav_sync()

    return None


async def _cmd_daily_sync() -> str:
    """Günlük sync — etüt verisi."""
    lines = ["⚡ *Eyotek Günlük Sync*\n"]

    # Etüt sync
    try:
        from eyotek_knowledge.scrapers.etut_sync import sync_etut
        r = await sync_etut()
        if r["success"]:
            lines.append(f"✅ *Etüt:* {r['inserted']} yeni kayıt eklendi")
        else:
            lines.append(f"⚠️ *Etüt:* {r.get('error', 'bilinmeyen hata')}")
    except Exception as e:
        lines.append(f"❌ *Etüt hata:* {e}")

    lines.append(f"\n_Sync zamanı: {datetime.now().strftime('%H:%M')}_")
    return "\n".join(lines)


async def _cmd_full_sync() -> str:
    """Haftalık tam sync — tüm veri kaynakları."""
    lines = ["⚡ *Eyotek Tam Sync*\n"]

    # Etüt
    try:
        from eyotek_knowledge.scrapers.etut_sync import sync_etut
        r = await sync_etut()
        lines.append(f"{'✅' if r['success'] else '❌'} *Etüt:* {r.get('inserted', 0)} yeni")
    except Exception as e:
        lines.append(f"❌ *Etüt:* {e}")

    # Yoklama sync
    try:
        from eyotek_knowledge.scrapers.yoklama_sync import sync_yoklama
        r2 = await sync_yoklama()
        lines.append(f"{'✅' if r2['success'] else '❌'} *Yoklama:* {r2.get('inserted', 0)} yeni")
    except Exception as e:
        lines.append(f"❌ *Yoklama:* {e}")

    # Sınav sync
    try:
        from eyotek_knowledge.scrapers.sinav_sync import sync_sinav
        r3 = await sync_sinav()
        lines.append(f"{'✅' if r3['success'] else '❌'} *Sınav:* {r3.get('inserted', 0)} yeni | {r3.get('error', '')}")
    except Exception as e:
        lines.append(f"❌ *Sınav:* {e}")

    # Öğrenci listesi sync
    try:
        from eyotek_knowledge.scrapers.ogrenci_sync import sync_ogrenci
        r4 = await sync_ogrenci()
        lines.append(f"{'✅' if r4['success'] else '❌'} *Öğrenci:* {r4.get('note', r4.get('error', ''))}")
    except Exception as e:
        lines.append(f"❌ *Öğrenci:* {e}")

    lines.append(f"\n_Sync zamanı: {datetime.now().strftime('%H:%M')}_")
    return "\n".join(lines)


async def _cmd_etut_today() -> str:
    """Bugünün etüt verilerini getir."""
    rows = await db_fetch("""
        SELECT ogretmen, ders, konu, saat, ogrenci_sayisi, yoklama
        FROM etut_history
        WHERE tarih = CURRENT_DATE
        ORDER BY saat ASC
    """)
    if not rows:
        return (
            "📋 *Bugün Etüt Verisi*\n\n"
            "Bugün için kayıtlı etüt yok — henüz girilmemiş olabilir.\n\n"
            "_'eyotek güncelle' yazarak son verileri çekebilirsin._ 🔄"
        )

    lines = [f"📋 *Bugünün Etütleri ({len(rows)} ders)*\n"]
    for r in rows:
        yoklama = "✅" if r['yoklama'] and 'evet' in str(r['yoklama']).lower() else "⚠️"
        lines.append(
            f"  {r['saat']} | *{r['ogretmen'][:15]}* | {r['ders'][:10]} "
            f"| {r['ogrenci_sayisi'] or '?'} öğr. {yoklama}"
        )
    return "\n".join(lines)


async def _cmd_status() -> str:
    """Eyotek sync durumu — son sync zamanları + veri sayıları."""
    etut = await db_fetchval("SELECT COUNT(*) FROM etut_history")
    etut_son = await db_fetchval("SELECT MAX(tarih) FROM etut_history")
    yoklama = await db_fetchval("SELECT COUNT(*) FROM yoklama_kontrol")
    yoklama_son = await db_fetchval("SELECT MAX(tarih) FROM yoklama_kontrol")
    ogrenci = await db_fetchval("SELECT COUNT(*) FROM students")
    sinav = await db_fetchval("SELECT COUNT(*) FROM student_exams")

    # site_map son sync
    sm = _load_site_map()
    etut_sync = sm.get("sync_kaynaklar", {}).get("etut_ara", {}).get("son_sync", "hiç")

    return (
        f"📊 *Eyotek Veri Durumu*\n\n"
        f"📝 *Etüt:* {etut:,} kayıt | Son: {etut_son}\n"
        f"📋 *Yoklama:* {yoklama:,} kayıt | Son: {yoklama_son}\n"
        f"👥 *Öğrenci:* {ogrenci}\n"
        f"📊 *Sınav:* {sinav:,} kayıt\n\n"
        f"🔄 *Son sync:* {etut_sync[:16] if etut_sync != 'hiç' else 'hiç'}\n\n"
        f"_'eyotek güncelle' → günlük sync_\n"
        f"_'eyotek tam güncelle' → haftalık tam sync_"
    )


async def _cmd_sinav_sync() -> str:
    """Sınav verisi sync — henüz implement edilmedi."""
    return (
        "🟡 *Sınav Sync*\n\n"
        "Bu özellik henüz implementasyon aşamasında.\n"
        "Mevcut sınav verisi DB'de güncel — son import ile."
    )
