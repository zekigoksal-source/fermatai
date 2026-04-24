"""
FermatAI — Self-Diagnosis (Faz 2)
==================================
quality_log + agent_conversations'tan hata pattern'ları ve
kök neden analizi yapar. Suggestion Engine için hazırlık.

Çalışma:
  python self_diagnosis.py            # Son 24 saat tani raporu
  python self_diagnosis.py --hours 6  # Son 6 saat
  python self_diagnosis.py --send     # Admin'e WP gönder
"""

import asyncio
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from loguru import logger
from db_pool import get_pool as _get_pool


async def diagnose_problems(hours: int = 24) -> dict:
    """Hata pattern'larını tespit eder, kök neden çıkarır."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        # 1. Düşük grade cevaplar
        bad_responses = await conn.fetch(f"""
            SELECT q.user_message, q.bot_response, q.sorunlar, q.grade,
                   q.response_source, q.phone, q.role,
                   q.created_at
            FROM quality_log q
            WHERE q.grade IN ('D','F')
            AND q.created_at >= NOW() - INTERVAL '{hours} hours'
            ORDER BY q.created_at DESC LIMIT 100
        """)

        # 3. Tekrar eden user mesajları (frustration sinyali)
        repeated = await conn.fetch(f"""
            SELECT phone, content, COUNT(*) as cnt
            FROM agent_conversations
            WHERE message_role='user' AND created_at >= NOW() - INTERVAL '{hours} hours'
            AND LENGTH(content) > 5
            GROUP BY phone, content
            HAVING COUNT(*) >= 2
            ORDER BY cnt DESC LIMIT 10
        """)

        # 4. Uzun konuşmalar (kullanıcı ısrarcı = bot tatmin etmedi)
        persistent = await conn.fetch(f"""
            SELECT phone, role, COUNT(*) as msg_count
            FROM agent_conversations
            WHERE message_role='user' AND created_at >= NOW() - INTERVAL '{hours} hours'
            GROUP BY phone, role
            HAVING COUNT(*) >= 10
            ORDER BY COUNT(*) DESC LIMIT 10
        """)

        # 5. Routing dağılımı
        routing = await conn.fetch(f"""
            SELECT response_source, COUNT(*) as cnt
            FROM quality_log
            WHERE created_at >= NOW() - INTERVAL '{hours} hours'
            GROUP BY response_source
        """)

    # 2. En yaygın sorunlar (conn kapandiktan sonra)
    sorun_counter = Counter()
    sorun_examples = defaultdict(list)
    for r in bad_responses:
        for s in (r['sorunlar'] or []):
            sorun_counter[s] += 1
            if len(sorun_examples[s]) < 3:
                sorun_examples[s].append({
                    'user': (r['user_message'] or '')[:80],
                    'bot': (r['bot_response'] or '')[:120],
                    'phone': r['phone'][-4:] if r['phone'] else '?',
                })

    # 6. Kök neden çıkarımı
    kok_nedenler = []
    for sorun, cnt in sorun_counter.most_common(5):
        # Her sorun için pattern öner
        if sorun == 'tahmini_sayi':
            kok_nedenler.append({
                'sorun': sorun, 'cnt': cnt,
                'kok_neden': 'Bot SQL sorgusu yapmadan tahmin yürütüyor',
                'cozum': 'System prompt: query_analytics ZORUNLU + "yaklaşık" YASAK kuralı',
            })
        elif sorun == 'soru_metni_uyduruk':
            kok_nedenler.append({
                'sorun': sorun, 'cnt': cnt,
                'kok_neden': 'search_curriculum sonucundaki icerik OKUNMADAN cevap verildi',
                'cozum': 'send_exam_image öncesi mutlaka icerik\'ten soru metnini doğrula',
            })
        elif sorun == 'tool_block_sizma':
            kok_nedenler.append({
                'sorun': sorun, 'cnt': cnt,
                'kok_neden': 'Claude text + tool_use blok birlikte gönderdi, _clean_response yetersiz',
                'cozum': 'Tool call varken text bloklarını tamamen drop et',
            })
        elif sorun == 'cift_yildiz_bold' or sorun == 'markdown_baslik' or sorun == 'markdown_tablo':
            kok_nedenler.append({
                'sorun': sorun, 'cnt': cnt,
                'kok_neden': 'Claude WhatsApp formatına göre değil markdown üretti',
                'cozum': '_clean_response WhatsApp dönüşümü güçlendirilmeli',
            })
        elif sorun == 'kimlik_karisma':
            kok_nedenler.append({
                'sorun': sorun, 'cnt': cnt,
                'kok_neden': 'Bot kullanıcının "adım Neo" tarz manipulasyonuna kandı',
                'cozum': 'Fast response kimlik manipulasyon pattern\'ını güçlendir',
            })
        elif sorun == 'generic_fallback':
            kok_nedenler.append({
                'sorun': sorun, 'cnt': cnt,
                'kok_neden': 'Bot veri bulamayınca "veri yok" diyor — alternatif önermiyor',
                'cozum': 'Veri yok cevaplarına alternatif aksiyon önerisi ekle',
            })

    # 7. Tekrar pattern (kullanıcı aynı sorunu farklı sorduysa)
    frustration_signals = [
        r for r in repeated if r['cnt'] >= 3
    ]

    return {
        'periyot_saat': hours,
        'kotu_cevap_sayisi': len(bad_responses),
        'top_sorunlar': dict(sorun_counter.most_common(10)),
        'sorun_ornekleri': {k: v for k, v in sorun_examples.items() if k in dict(sorun_counter.most_common(5))},
        'tekrar_mesajlar': [dict(r) for r in repeated],
        'israrli_kullanicilar': [dict(r) for r in persistent],
        'routing_dagilim': {r['response_source']: r['cnt'] for r in routing},
        'kok_nedenler': kok_nedenler,
        'frustration_sinyalleri': frustration_signals,
    }


async def format_diagnosis_report(hours: int = 24) -> str:
    """WhatsApp formatında tanı raporu."""
    d = await diagnose_problems(hours)

    lines = [f"🔬 *SELF-DIAGNOSIS — Son {hours} Saat*\n"]
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━\n")

    # Genel durum
    routing = d['routing_dagilim']
    total = sum(routing.values())
    lines.append(f"📊 *Toplam değerlendirme:* {total} cevap")
    if total:
        for src, cnt in sorted(routing.items(), key=lambda x: -x[1]):
            pct = 100*cnt/total
            lines.append(f"  • {src}: {cnt} (%{pct:.0f})")

    lines.append(f"\n⚠️ *Düşük kalite cevap:* {d['kotu_cevap_sayisi']}")

    # Top sorunlar
    if d['top_sorunlar']:
        lines.append("\n🔍 *En Yaygın Sorunlar:*")
        for sorun, cnt in list(d['top_sorunlar'].items())[:5]:
            lines.append(f"  {cnt}x — _{sorun}_")

    # Kök nedenler + öneriler
    if d['kok_nedenler']:
        lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("💡 *KÖK NEDEN ANALİZİ:*\n")
        for kn in d['kok_nedenler'][:5]:
            lines.append(f"*🔸 {kn['sorun']}* ({kn['cnt']}x)")
            lines.append(f"   Sebep: _{kn['kok_neden']}_")
            lines.append(f"   ✅ Çözüm: {kn['cozum']}\n")

    # Israrcı kullanıcılar
    if d['israrli_kullanicilar']:
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("🚨 *Israrcı Kullanıcılar* (10+ mesaj):")
        for u in d['israrli_kullanicilar'][:5]:
            ph = u['phone'][-4:] if u['phone'] else '?'
            lines.append(f"  ...{ph} ({u['role']}): {u['msg_count']} mesaj")

    # Frustration
    if d['frustration_sinyalleri']:
        lines.append("\n💥 *Frustration Sinyalleri* (aynı mesaj 3+ kez):")
        for f in d['frustration_sinyalleri'][:3]:
            ph = f['phone'][-4:] if f['phone'] else '?'
            lines.append(f"  ...{ph}: \"{f['content'][:60]}\" → {f['cnt']}x")

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("_'kalite raporu' yazarak özet metriklere bakabilirsin_")
    lines.append("_'son hatalar' yazarak detayları görebilirsin_")

    return "\n".join(lines)


async def main():
    hours = 24
    if "--hours" in sys.argv:
        hours = int(sys.argv[sys.argv.index("--hours") + 1])

    rapor = await format_diagnosis_report(hours)
    print(rapor)

    if "--send" in sys.argv:
        try:
            from whatsapp_bridge import send_wa_message
            ADMIN = "905051256802"
            # 22.1n-kural1: outreach marker
            await send_wa_message(ADMIN, rapor, _outreach=True, _reason="self_diagnosis")
            print("\n✅ Admin'e gönderildi")
        except Exception as e:
            print(f"\n❌ Gönderim hatası: {e}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
