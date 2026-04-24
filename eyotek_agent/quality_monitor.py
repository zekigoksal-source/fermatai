"""
FermatAI Konuşma Kalitesi Otomatik İzleme
==========================================
Her gün konuşmaları tarayarak sorunları tespit eder:
  - Frustration tespiti (öğrenci memnuniyetsiz)
  - Tekrarlı aynı cevap (kısır döngü)
  - Ollama kalite düşüşü
  - Fast response yanlış tetikleme
  - Cevapsız kalan mesajlar

Kullanım:
  python quality_monitor.py              # Son 24 saat raporu
  python quality_monitor.py --send       # Raporu admin'e WP ile gönder
"""

import asyncio
import os
import re
import sys
from datetime import date

from loguru import logger
from db_pool import get_pool as _get_pool


async def generate_quality_report() -> str:
    """Konuşma kalite raporu oluştur."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        # 1. Routing dağılımı
        routing = await conn.fetchrow("""
            SELECT
                COUNT(*) FILTER (WHERE tools_used::text LIKE '%fast%') as fast,
                COUNT(*) FILTER (WHERE tools_used::text LIKE '%ollama%') as ollama,
                COUNT(*) FILTER (WHERE tools_used::text = '{}' AND message_role='assistant') as claude,
                COUNT(*) FILTER (WHERE content LIKE '[tool_calls%') as tools,
                COUNT(*) FILTER (WHERE message_role='user') as mesaj,
                COUNT(DISTINCT phone) as kullanici
            FROM agent_conversations
            WHERE created_at >= CURRENT_DATE
        """)

        # 2. Frustration tespiti — öğrenci yanlış anladığını söylüyor
        frustrations = await conn.fetch("""
            SELECT COALESCE(a.full_name, LEFT(ac.phone,8)) as isim,
                   LEFT(REPLACE(ac.content, E'\n', ' '), 60) as mesaj
            FROM agent_conversations ac
            LEFT JOIN acl_users a ON REPLACE(ac.phone,'+','') = REPLACE(a.phone,'+','')
            WHERE ac.created_at >= CURRENT_DATE
            AND ac.message_role = 'user'
            AND (ac.content ILIKE '%yanlış%' OR ac.content ILIKE '%anlamadın%'
                 OR ac.content ILIKE '%istemedim%' OR ac.content ILIKE '%saçmalama%'
                 OR ac.content ILIKE '%yardımcı olam%' OR ac.content ILIKE '%işe yaram%')
            LIMIT 10
        """)

        # 3. Tekrarlı cevap
        repeats = await conn.fetch("""
            SELECT COALESCE(a.full_name, LEFT(ac.phone,8)) as isim,
                   LEFT(REPLACE(ac.content, E'\n', ' '), 50) as cevap,
                   COUNT(*) as tekrar
            FROM agent_conversations ac
            LEFT JOIN acl_users a ON REPLACE(ac.phone,'+','') = REPLACE(a.phone,'+','')
            WHERE ac.created_at >= CURRENT_DATE
            AND ac.message_role = 'assistant'
            AND ac.content NOT LIKE '[tool_calls%'
            GROUP BY ac.phone, LEFT(REPLACE(ac.content, E'\n', ' '), 50), a.full_name
            HAVING COUNT(*) >= 3
            ORDER BY COUNT(*) DESC
            LIMIT 5
        """)

        # 4. Cevapsız kalan mesajlar
        unanswered = await conn.fetchval("""
            SELECT COUNT(*)
            FROM agent_conversations u
            WHERE u.created_at >= CURRENT_DATE
            AND u.message_role = 'user'
            AND NOT EXISTS (
                SELECT 1 FROM agent_conversations a
                WHERE a.phone = u.phone
                AND a.message_role = 'assistant'
                AND a.created_at > u.created_at
                AND a.created_at < u.created_at + INTERVAL '2 minutes'
            )
        """) or 0

        # 5. Ollama kalite
        ollama_quality = await conn.fetchrow("""
            SELECT
                COUNT(*) as toplam,
                COUNT(*) FILTER (WHERE content LIKE '%*%') as bold_var,
                COUNT(*) FILTER (WHERE content LIKE '%---%') as sep_var
            FROM agent_conversations
            WHERE created_at >= CURRENT_DATE
            AND tools_used::text LIKE '%ollama%'
            AND message_role = 'assistant'
        """)

    fast = routing['fast'] or 0
    ollama = routing['ollama'] or 0
    claude = routing['claude'] or 0
    tools = routing['tools'] or 0
    mesaj = routing['mesaj'] or 0
    kullanici = routing['kullanici'] or 0
    toplam_cevap = fast + ollama + claude
    maliyet = round((claude + tools) * 0.0135, 2)

    # Rapor oluştur
    lines = [
        f"🔍 *FermatAI Kalite Raporu*",
        f"_{date.today().strftime('%d.%m.%Y')}_\n",
        f"---\n",
        f"📊 *Routing Dağılımı*",
        f"  Mesaj: *{mesaj}* ({kullanici} kullanıcı)",
    ]

    if toplam_cevap > 0:
        lines.append(f"  Fast: *{fast}* (%{round(fast/toplam_cevap*100)})")
        lines.append(f"  Ollama: *{ollama}* (%{round(ollama/toplam_cevap*100)})")
        lines.append(f"  Claude: *{claude}* (%{round(claude/toplam_cevap*100)})")
    lines.append(f"  💰 Maliyet: *${maliyet}*\n")

    # Hedef karşılaştırma
    if toplam_cevap > 0:
        fast_pct = round(fast / toplam_cevap * 100)
        if fast_pct >= 50:
            lines.append(f"  ✅ Fast Response hedef üstünde (%{fast_pct})")
        else:
            lines.append(f"  ⚠️ Fast Response hedef altında (%{fast_pct} — hedef %50+)")

    if frustrations:
        lines.append(f"\n⚠️ *Memnuniyetsizlik Sinyalleri ({len(frustrations)})*")
        for f_item in frustrations[:5]:
            lines.append(f"  🔴 {f_item['isim']}: _{f_item['mesaj']}_")

    if repeats:
        lines.append(f"\n🔄 *Tekrarlı Cevaplar ({len(repeats)})*")
        for r in repeats:
            lines.append(f"  ⚠️ {r['isim']}: \"{r['cevap']}\" ({r['tekrar']}x)")

    if unanswered > 0:
        lines.append(f"\n❌ *Cevapsız Mesaj:* {unanswered} adet")

    if ollama_quality and ollama_quality['toplam'] > 0:
        oll_total = ollama_quality['toplam']
        oll_bold = ollama_quality['bold_var'] or 0
        oll_sep = ollama_quality['sep_var'] or 0
        bold_pct = round(oll_bold / oll_total * 100)
        lines.append(f"\n🤖 *Ollama Kalite*")
        lines.append(f"  {oll_total} cevap | Bold: %{bold_pct} | Ayırıcı: %{round(oll_sep/oll_total*100)}")
        if bold_pct < 70:
            lines.append(f"  ⚠️ Görsel kalite düşük — format kuralları güçlendirilmeli")

    if not frustrations and not repeats and unanswered == 0:
        lines.append(f"\n✅ *Kalite durumu iyi — sorun tespit edilmedi*")

    lines.append(f"\n---")
    lines.append(f"_Otomatik kalite raporu — FermatAI_")

    return "\n".join(lines)


async def main():
    report = await generate_quality_report()
    print(report)


if __name__ == "__main__":
    asyncio.run(main())
