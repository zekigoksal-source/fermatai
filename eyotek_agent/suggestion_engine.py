"""
FermatAI — Suggestion Engine v1 (Faz 3)
========================================
Self-Observer + Self-Diagnosis çıktılarını analiz eder.
Düzeltme önerileri üretir, admin onayı için kuyruğa atar.

Akış:
  1. quality_log → düşük grade pattern'lar
  2. self_diagnosis → kök neden + çözüm
  3. Suggestion üret: "şu pattern'ı şuraya ekle / şu prompt kuralını güçlendir"
  4. improvement_proposals tablosuna yaz
  5. Admin "öneri listesi" / "öneri X onayla" diyebilir

Çalışma:
  python suggestion_engine.py             # Yeni öneriler üret
  python suggestion_engine.py --list      # Bekleyen önerileri listele
  python suggestion_engine.py --send      # Admin'e WP gönder
"""

import asyncio
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from loguru import logger
from db_pool import get_pool as _get_pool, db_fetch, db_fetchrow, db_fetchval, db_execute


SUGGESTION_TYPES = {
    'fast_response_pattern': {
        'risk': 'low',
        'label': 'Fast Response Pattern Ekle',
        'aciklama': 'fast_responses.py içine yeni regex pattern',
    },
    'prompt_kural': {
        'risk': 'medium',
        'label': 'Prompt Kuralı Güçlendir',
        'aciklama': 'fermat_core_agent.py system prompt iyileştirmesi',
    },
    'response_filter': {
        'risk': 'medium',
        'label': 'Response Filter Ekle',
        'aciklama': '_clean_response veya çıktı düzenleme',
    },
    'routing_rule': {
        'risk': 'low',
        'label': 'Routing Kuralı',
        'aciklama': 'llm_router'
                    '.py — bir intenti Claude/Ollama/Fast\'e yönlendir',
    },
    'data_fix': {
        'risk': 'low',
        'label': 'Veri Düzeltme',
        'aciklama': 'DB temizliği veya normalizasyon',
    },
    'tool_acl': {
        'risk': 'high',
        'label': 'Tool ACL Değişikliği',
        'aciklama': 'Tool yetki matrisi değişimi (admin onayı kritik)',
    },
}


async def ensure_table():
    """improvement_proposals tablosu yoksa olustur."""
    await db_execute("""
        CREATE TABLE IF NOT EXISTS improvement_proposals (
            id SERIAL PRIMARY KEY,
            tip TEXT,
            risk TEXT,
            baslik TEXT,
            sorun TEXT,
            cozum_ozeti TEXT,
            uygulama_detay TEXT,
            ornek_data JSONB,
            durum TEXT DEFAULT 'bekliyor',  -- bekliyor, onaylandi, reddedildi, uygulandi
            created_at TIMESTAMP DEFAULT NOW(),
            reviewed_at TIMESTAMP,
            reviewed_by TEXT,
            applied_at TIMESTAMP,
            unique_key TEXT UNIQUE  -- aynı önerinin tekrar üretilmesini engelle
        )
    """)


async def generate_suggestions_from_diagnosis(hours: int = 24) -> list:
    """Self-diagnosis çıktılarından öneri üret."""
    from self_diagnosis import diagnose_problems
    d = await diagnose_problems(hours)

    suggestions = []
    seen_keys = set()

    # 1. Kök nedenlerden direkt öneri
    for kn in d['kok_nedenler']:
        sorun = kn['sorun']
        cnt = kn['cnt']
        # Az kayitli sorunlari atla (gurultu)
        if cnt < 3:
            continue

        if sorun == 'tahmini_sayi':
            tip = 'prompt_kural'
            baslik = "Tahmin yasagi guclendir"
            cozum = "System prompt: query_analytics ZORUNLU. 'yaklasik/civari/tahmini' kelime yasagi."
            detay = ('fermat_core_agent.py SYSTEM_PROMPT icine: '
                     '"Veri sorulan her soruda query_analytics tool\'unu CAGIRMAK zorundasin. '
                     '\'yaklasik\', \'civari\', \'tahmini\' kelimelerini KULLANMA — kesin sayi ver veya \'veri yok\' de."')
        elif sorun == 'soru_metni_uyduruk':
            tip = 'prompt_kural'
            baslik = "Soru metni uydurma yasagi"
            cozum = "send_exam_image oncesi search_curriculum'dan gelen icerik mutlaka okunsun."
            detay = ('SYSTEM_PROMPT: "send_exam_image cagirmadan once search_curriculum\'dan donen \'icerik\' '
                     'alanini OKU. Soru metnini ASLA uydurma — icerik\'teki tam metni kullan."')
        elif sorun == 'tool_block_sizma':
            tip = 'response_filter'
            baslik = "ToolUseBlock sizma engelleme"
            cozum = "_clean_response: tool_use varken text bloklarini drop et"
            detay = ('fermat_core_agent.py icinde Claude response parse: '
                     'response.content icinde tool_use varsa, ayni response\'taki text bloklarini DROP et. '
                     'Sadece tool_use ile devam et.')
        elif sorun in ('cift_yildiz_bold', 'markdown_baslik', 'markdown_tablo'):
            tip = 'response_filter'
            baslik = "WhatsApp format donusumu guclendir"
            cozum = "_clean_response: **bold** → *bold*, # baslik → *baslik*, tablo → liste"
            detay = ('_clean_response icine regex: '
                     'r\"\\*\\*([^*]+)\\*\\*\" → r\"*\\1*\"; '
                     'r\"^#{1,6}\\s*(.+)$\" → r\"*\\1*\"; '
                     'tablo satirlarini bullet list\'e cevir.')
        elif sorun == 'kimlik_karisma':
            tip = 'fast_response_pattern'
            baslik = "Kimlik manipulasyonu pattern"
            cozum = "fast_responses.py: 'adim X, ben X' tarz manipulasyonlari yakala"
            detay = ('fast_responses.py SECURITY_PATTERNS icine: '
                     'r"\\b(adim|ismim|ben)\\s+(neo|admin|mudur|zeki|mahsum)\\b" → '
                     'kurumsal kibarlik mesaji + telefon kimligini hatirlat.')
        elif sorun == 'generic_fallback':
            tip = 'prompt_kural'
            baslik = "Veri yok cevaplarina alternatif"
            cozum = "'veri yok' dedikten sonra alternatif aksiyon oner"
            detay = ('SYSTEM_PROMPT: "Veri bulamadiginda asla bos cevap verme. '
                     'Soyle bir kalip kullan: \'Su an [X] verisi yok ama [alternatif]\' '
                     'ornegin: deneme yok → \'denemelere katildikca otomatik gelir, simdilik konu calismani onerebilirim\'"')
        else:
            continue

        unique_key = f"diag_{sorun}_{tip}"
        if unique_key in seen_keys:
            continue
        seen_keys.add(unique_key)

        suggestions.append({
            'tip': tip,
            'risk': SUGGESTION_TYPES[tip]['risk'],
            'baslik': baslik,
            'sorun': f"{sorun} ({cnt}x son {hours} saatte)",
            'cozum_ozeti': cozum,
            'uygulama_detay': detay,
            'ornek_data': {
                'pattern': sorun,
                'frekans': cnt,
                'kok_neden': kn['kok_neden'],
                'periyot_saat': hours,
            },
            'unique_key': unique_key,
        })

    # 2. Frustration sinyallerinden routing onerisi
    if d['frustration_sinyalleri']:
        sample = d['frustration_sinyalleri'][0]
        unique_key = f"frust_routing_{sample['content'][:30]}"
        if unique_key not in seen_keys:
            seen_keys.add(unique_key)
            suggestions.append({
                'tip': 'routing_rule',
                'risk': 'low',
                'baslik': "Frustration sinyali — routing iyilestir",
                'sorun': f"Tekrar mesaj: \"{sample['content'][:50]}\" ({sample['cnt']}x)",
                'cozum_ozeti': "Bu mesaj pattern'i Claude'a yonlendir (Ollama yetersiz)",
                'uygulama_detay': (
                    f"llm_router.py _CLOUD_KEYWORDS\'a ekle veya fast_response\'a pattern: "
                    f"\"{sample['content'][:30]}\" benzeri sorular Claude'a gitsin."
                ),
                'ornek_data': {
                    'mesaj': sample['content'][:100],
                    'tekrar': sample['cnt'],
                },
                'unique_key': unique_key,
            })

    # 3. Israrli kullanici → uzun konusma uyarisi
    if d['israrli_kullanicilar']:
        for u in d['israrli_kullanicilar'][:2]:
            ph = u['phone'][-4:] if u['phone'] else '?'
            unique_key = f"persistent_{u['phone']}_{u['msg_count']}"
            if unique_key in seen_keys:
                continue
            seen_keys.add(unique_key)
            suggestions.append({
                'tip': 'data_fix',
                'risk': 'low',
                'baslik': f"Israrli kullanici incele: ...{ph}",
                'sorun': f"{u['msg_count']} mesaj son {hours} saatte ({u['role']})",
                'cozum_ozeti': "Konusma akisini incele — context kayboluyor olabilir",
                'uygulama_detay': (
                    f"phone={u['phone']} agent_conversations'tan son 20 mesaj cek, "
                    "context kaybi / yanit tatmin etmeme nedeni belirle."
                ),
                'ornek_data': dict(u),
                'unique_key': unique_key,
            })

    return suggestions


async def save_suggestions(suggestions: list) -> dict:
    """Onerileri DB'ye yaz (dedupe ile)."""
    await ensure_table()
    pool = await _get_pool()
    eklenen = 0
    atlanan = 0
    async with pool.acquire() as conn:
        for s in suggestions:
            try:
                await conn.execute("""
                    INSERT INTO improvement_proposals
                      (tip, risk, baslik, sorun, cozum_ozeti, uygulama_detay, ornek_data, unique_key)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                    ON CONFLICT (unique_key) DO NOTHING
                """,
                    s['tip'], s['risk'], s['baslik'], s['sorun'],
                    s['cozum_ozeti'], s['uygulama_detay'],
                    json.dumps(s['ornek_data'], default=str), s['unique_key']
                )
                # ON CONFLICT olmadiysa eklendi
                row = await conn.fetchrow(
                    "SELECT id FROM improvement_proposals WHERE unique_key=$1",
                    s['unique_key']
                )
                if row:
                    eklenen += 1
            except Exception as e:
                logger.error(f"Suggestion save error: {e}")
                atlanan += 1
    return {'eklenen': eklenen, 'atlanan': atlanan, 'toplam': len(suggestions)}


async def list_pending_suggestions(limit: int = 10) -> str:
    """Bekleyen onerileri WhatsApp formatinda dondur."""
    await ensure_table()
    rows = await db_fetch("""
        SELECT id, tip, risk, baslik, sorun, cozum_ozeti, created_at
        FROM improvement_proposals
        WHERE durum = 'bekliyor'
        ORDER BY
          CASE risk WHEN 'low' THEN 1 WHEN 'medium' THEN 2 WHEN 'high' THEN 3 ELSE 4 END,
          created_at DESC
        LIMIT $1
    """, limit)

    if not rows:
        return "Bekleyen iyilestirme onerisi yok. _Sistem temiz._"

    lines = ["💡 *BEKLEYEN İYİLEŞTİRME ÖNERİLERİ*\n"]
    lines.append(f"_(Toplam {len(rows)} oneri)_\n")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━\n")

    for r in rows:
        risk_emoji = {'low': '🟢', 'medium': '🟡', 'high': '🔴'}.get(r['risk'], '⚪')
        lines.append(f"*#{r['id']}* {risk_emoji} _{r['risk']}_ — *{r['baslik']}*")
        lines.append(f"  📋 Sorun: {r['sorun']}")
        lines.append(f"  ✅ Cozum: {r['cozum_ozeti']}")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("_'oneri detay [ID]' tum detayi gor_")
    lines.append("_'oneri onayla [ID]' uygulamaya al_")
    lines.append("_'oneri reddet [ID]' iptal et_")
    return "\n".join(lines)


async def get_suggestion_detail(suggestion_id: int) -> str:
    """Tek onerinin tam detayi."""
    await ensure_table()
    r = await db_fetchrow(
        "SELECT * FROM improvement_proposals WHERE id = $1",
        suggestion_id
    )
    if not r:
        return f"Oneri bulunamadi: #{suggestion_id}"

    risk_emoji = {'low': '🟢', 'medium': '🟡', 'high': '🔴'}.get(r['risk'], '⚪')
    lines = [
        f"💡 *ÖNERİ #{r['id']}*\n",
        f"{risk_emoji} *Risk:* {r['risk']}",
        f"🏷️ *Tip:* {r['tip']}",
        f"📊 *Durum:* {r['durum']}",
        f"📅 *Olusturma:* {r['created_at'].strftime('%d.%m %H:%M')}",
        "",
        f"*Baslik:* {r['baslik']}",
        f"*Sorun:* {r['sorun']}",
        "",
        f"*Cozum Ozeti:*\n{r['cozum_ozeti']}",
        "",
        f"*Uygulama Detayi:*\n{r['uygulama_detay']}",
    ]

    if r['ornek_data']:
        try:
            data = json.loads(r['ornek_data']) if isinstance(r['ornek_data'], str) else r['ornek_data']
            lines.append("")
            lines.append(f"*Veri:*\n```{json.dumps(data, indent=2, default=str, ensure_ascii=False)}```")
        except Exception:
            pass

    return "\n".join(lines)


async def review_suggestion(suggestion_id: int, action: str, reviewer: str = "admin") -> str:
    """oneri onayla / reddet."""
    await ensure_table()
    r = await db_fetchrow(
        "SELECT id, baslik, durum FROM improvement_proposals WHERE id = $1",
        suggestion_id
    )
    if not r:
        return f"Oneri bulunamadi: #{suggestion_id}"
    if r['durum'] != 'bekliyor':
        return f"Oneri zaten {r['durum']} durumunda: #{suggestion_id}"

    yeni_durum = 'onaylandi' if action == 'onayla' else 'reddedildi'
    await db_execute("""
        UPDATE improvement_proposals
        SET durum = $1, reviewed_at = NOW(), reviewed_by = $2
        WHERE id = $3
    """, yeni_durum, reviewer, suggestion_id)

    if yeni_durum == 'onaylandi':
        return (f"✅ Oneri #{suggestion_id} ONAYLANDI: _{r['baslik']}_\n\n"
                f"_Bu oneri uygulama kuyrugunda — Claude Code/manuel uygulama bekliyor._")
    else:
        return f"❌ Oneri #{suggestion_id} REDDEDİLDİ: _{r['baslik']}_"


async def main():
    args = sys.argv[1:]

    if "--list" in args:
        rapor = await list_pending_suggestions(20)
        print(rapor)
    elif "--detail" in args:
        idx = args.index("--detail")
        sid = int(args[idx + 1])
        print(await get_suggestion_detail(sid))
    elif "--onayla" in args:
        idx = args.index("--onayla")
        sid = int(args[idx + 1])
        print(await review_suggestion(sid, 'onayla'))
    elif "--reddet" in args:
        idx = args.index("--reddet")
        sid = int(args[idx + 1])
        print(await review_suggestion(sid, 'reddet'))
    else:
        # Yeni oneriler uret
        hours = 24
        if "--hours" in args:
            hours = int(args[args.index("--hours") + 1])
        suggestions = await generate_suggestions_from_diagnosis(hours)
        result = await save_suggestions(suggestions)
        print(f"✅ {result['eklenen']} oneri DB'ye yazildi (toplam {result['toplam']}, atlanan {result['atlanan']})")

        if "--send" in args and result['eklenen']:
            try:
                from whatsapp_bridge import send_wa_message
                ADMIN = "905051256802"
                rapor = await list_pending_suggestions(10)
                # 22.1n-kural1
                await send_wa_message(ADMIN, rapor, _outreach=True, _reason="suggestion_engine")
                print("✅ Admin'e WP gonderildi")
            except Exception as e:
                print(f"❌ WP gonderim hatasi: {e}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
