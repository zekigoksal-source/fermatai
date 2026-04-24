"""
FermatAI Günlük Rapor Sistemi
==============================
Her gün 20:00'da admin'e WP ile özet gönderir.

Rapor içeriği:
  - Kullanım istatistikleri (mesaj, kullanıcı, kaynak dağılımı)
  - En aktif öğrenciler
  - Riskli öğrenciler (stres, devamsızlık)
  - Token maliyet tahmini
  - Öğrenci geri bildirimleri

Kullanım:
  python daily_report.py              # Konsola yaz
  python daily_report.py --send       # WhatsApp ile gönder
"""

import asyncio
import os
import sys
from datetime import date, datetime

from dotenv import load_dotenv
load_dotenv(override=True)

from db_pool import get_pool as _get_pool

ADMIN_PHONE = "905051256802"
WP_BRIDGE_URL = "http://localhost:8001"


async def generate_report() -> str:
    """Günlük rapor oluştur."""
    today = date.today().strftime("%d.%m.%Y")
    pool = await _get_pool()
    async with pool.acquire() as conn:
        # 1. Kullanım istatistikleri
        stats = await conn.fetchrow("""
            SELECT
                COUNT(*) FILTER (WHERE message_role='user') as toplam_mesaj,
                COUNT(DISTINCT phone) as kullanici,
                COUNT(*) FILTER (WHERE tools_used::text LIKE '%fast%') as fast,
                COUNT(*) FILTER (WHERE tools_used::text LIKE '%ollama%') as ollama,
                COUNT(*) FILTER (WHERE tools_used::text = '{}' AND message_role='assistant') as claude,
                COUNT(*) FILTER (WHERE content LIKE '[tool_calls%') as tool_calls
            FROM agent_conversations
            WHERE created_at >= CURRENT_DATE
        """)

        # 2. En aktif öğrenciler
        aktif = await conn.fetch("""
            SELECT COALESCE(a.full_name, LEFT(ac.phone,8)) as isim,
                   COUNT(*) FILTER (WHERE ac.message_role='user') as mesaj
            FROM agent_conversations ac
            LEFT JOIN acl_users a ON REPLACE(ac.phone,'+','') = REPLACE(a.phone,'+','')
            WHERE ac.created_at >= CURRENT_DATE
            AND REPLACE(ac.phone,'+','') != $1
            GROUP BY COALESCE(a.full_name, LEFT(ac.phone,8))
            ORDER BY mesaj DESC LIMIT 5
        """, ADMIN_PHONE)

        # 3. Riskli öğrenciler — stres/motivasyon düşük
        riskli = await conn.fetch("""
            SELECT COALESCE(a.full_name, LEFT(ac.phone,8)) as isim,
                   LEFT(ac.content, 60) as mesaj
            FROM agent_conversations ac
            LEFT JOIN acl_users a ON REPLACE(ac.phone,'+','') = REPLACE(a.phone,'+','')
            WHERE ac.created_at >= CURRENT_DATE
            AND ac.message_role = 'user'
            AND (ac.content ILIKE '%stres%' OR ac.content ILIKE '%motivasyon%'
                 OR ac.content ILIKE '%yapamıyorum%' OR ac.content ILIKE '%bıktım%'
                 OR ac.content ILIKE '%intihar%' OR ac.content ILIKE '%pes%')
            LIMIT 5
        """)

        # 4. Geri bildirimler
        feedbacks = await conn.fetch("""
            SELECT full_name, LEFT(feedback, 60) as fb, category
            FROM user_feedback
            WHERE created_at >= CURRENT_DATE AND category = 'teknik'
            ORDER BY created_at DESC LIMIT 5
        """)

        # 5. Yeni lead'ler
        lead_count = await conn.fetchval("""
            SELECT COUNT(DISTINCT phone)
            FROM agent_conversations
            WHERE created_at >= CURRENT_DATE
            AND phone NOT IN (SELECT phone FROM acl_users WHERE phone IS NOT NULL)
        """) or 0

    mesaj = stats['toplam_mesaj'] or 0
    kullanici = stats['kullanici'] or 0
    fast = stats['fast'] or 0
    ollama = stats['ollama'] or 0
    claude = stats['claude'] or 0
    tools = stats['tool_calls'] or 0

    toplam_cevap = fast + ollama + claude
    fast_pct = round(fast / max(toplam_cevap, 1) * 100)
    claude_pct = round(claude / max(toplam_cevap, 1) * 100)
    ollama_pct = round(ollama / max(toplam_cevap, 1) * 100)

    # Maliyet tahmini
    maliyet = round((claude + tools) * 0.0135, 2)

    # Rapor oluştur
    lines = [
        f"📊 *FermatAI Günlük Rapor*",
        f"_{today}_\n",
        f"---\n",
        f"📈 *Kullanım*",
        f"  Mesaj: *{mesaj}* ({kullanici} kullanıcı)",
        f"  Fast: *{fast}* (%{fast_pct})",
        f"  Claude: *{claude}* (%{claude_pct})",
        f"  Ollama: *{ollama}* (%{ollama_pct})",
        f"  Tool call: {tools}",
        f"  💰 Tahmini maliyet: *${maliyet}*\n",
    ]

    if aktif:
        lines.append(f"👥 *En Aktif*")
        for i, a in enumerate(aktif, 1):
            lines.append(f"  {i}. {a['isim']} — {a['mesaj']} mesaj")
        lines.append("")

    if riskli:
        lines.append(f"⚠️ *Dikkat — Riskli Sinyaller*")
        for r in riskli:
            lines.append(f"  🔴 {r['isim']}: _{r['mesaj']}_")
        lines.append("")

    if feedbacks:
        lines.append(f"📋 *Teknik Geri Bildirimler*")
        for f in feedbacks:
            lines.append(f"  • {f['full_name'] or '?'}: {f['fb']}")
        lines.append("")

    if lead_count > 0:
        lines.append(f"🎯 *Yeni Lead:* {lead_count} potansiyel müşteri\n")

    lines.append(f"---")
    lines.append(f"_Otomatik rapor — FermatAI_")

    return "\n".join(lines)


async def send_report():
    """Raporu WP ile admin'e gönder."""
    import aiohttp
    report = await generate_report()

    # WP Bridge üzerinden gönder
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{WP_BRIDGE_URL}/send",
                json={"phone": ADMIN_PHONE, "message": report},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    print("✅ Rapor gönderildi!")
                else:
                    print(f"⚠️ Gönderme hatası: {resp.status}")
    except Exception as e:
        print(f"⚠️ Gönderme hatası: {e}")
        print("\nRapor içeriği:")
        print(report)


async def main():
    if "--send" in sys.argv:
        await send_report()
    else:
        report = await generate_report()
        print(report)


if __name__ == "__main__":
    asyncio.run(main())
