"""
FermatAI Konusma Kalite Analizoru
==================================
Oturum 24 (Neo ekli, Apr 2026).

Son N saatlik WhatsApp + web konusmalarini Groq 70B'ye oku, raporla:
- Frustration anlari (kullanici botu duzeltiyor mu?)
- Bot halusinasyonlari
- Eksik pattern'lar (fast_response'a eklenebilir)
- Pedagojik eksiklikler

Groq 70B ucuz ($0.59/M input) — yuzlerce konusmayi ~$0.10'a analiz eder.

Kullanim:
    python conversation_quality_analyzer.py [--hours 48] [--min-turns 3]

Cikti: logs/kalite_raporu_YYYY-MM-DD.json + konsol ozeti.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from wa_config import GRAPH_BASE  # 25.50 Graph API tek-kaynak (wa_config.py)
import sys
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

from dotenv import load_dotenv
load_dotenv(override=True)

from db_pool import db_fetch
from groq_handler import GroqClient
# 25.23: Cerebras-first (Groq daily limit dolup duruyordu)
try:
    from cerebras_handler import CerebrasClient
    _CEREBRAS_AVAIL = bool(os.getenv("CEREBRAS_API_KEY"))
except ImportError:
    _CEREBRAS_AVAIL = False
from loguru import logger


ANALYSIS_PROMPT = """Asagida FermatAI (YKS/LGS bot) ile bir kullanici arasinda gecmis konusma var.
Konusma uzunlugu: {turn_count} mesaj. Kullanici rolu: {role}.

Gorevin: Bu konusmayi pedagojik ve teknik kalite acisindan INCELE.
25.40p Neo direktif: yeni intent kalite skorlari (test/soru/yeni_nesil) + renderer kullanim.
Cikti JSON olmali (markdown kod blogu DEGIL, sadece JSON):

{{
  "ozet": "1-2 cumle konu",
  "frustration": [
    {{"mesaj_idx": 3, "sebep": "bot 2. kez ayni hatayi yapti", "aciklama": "..."}}
  ],
  "bot_hatasi": [
    {{"tip": "halusinasyon|yanlis_data|baglam_kaybi|dil|ton", "mesaj_idx": 5, "aciklama": "..."}}
  ],
  "yeni_intent_kalite": [
    {{"intent": "test_olusturma|soru_uret|yeni_nesil_uret|konu_anlatim_uzun|karsilastirma|ornek_paket_uret",
      "mesaj_idx": 7,
      "skor": 1-10,
      "yeni_nesil_kriter_sayisi": 0-7,
      "rag_kullanildi_mi": true,
      "renderer_var_mi": true,
      "renderer_tipleri": ["quiz", "steps", "chart"],
      "aciklama": "iceriğe gore kalite degerlendirmesi"}}
  ],
  "eksik_pattern": [
    {{"kullanici_mesaji": "...", "oneri": "fast_responses'a eklenecek pattern"}}
  ],
  "pedagojik_puan": 5,
  "pedagojik_not": "empati + yonlendirme bakımından nasıl?",
  "onemli_bulgu": "varsa kritik bir gozlem"
}}

Kurallar:
- `frustration`, `bot_hatasi`, `eksik_pattern` listeler BOS olabilir
- mesaj_idx 0-indexli (ilk mesaj 0)
- `pedagojik_puan` 1-10 (10=mukemmel)
- Sadece gercek tespitler yaz, icat etme
- Turkce yaz

KONUSMA:
{transcript}

Simdi JSON'u uret:"""


async def fetch_conversations(hours: int = 48, min_turns: int = 3) -> list[dict]:
    """
    Son N saatin konusmalarini cek, phone + burst bazli gruplandir.
    Burst = aralarinda <30dk gecen mesajlar (ayni session).
    """
    rows = await db_fetch("""
        SELECT phone, role, message_role, content, created_at
        FROM agent_conversations
        WHERE created_at >= NOW() - INTERVAL '%s hours'
          AND message_role IN ('user', 'assistant')
          AND content NOT LIKE '[tool_calls%%]%%'
        ORDER BY phone, created_at ASC
    """ % hours)

    # Burst gruplari
    bursts: dict[tuple[str, int], list] = defaultdict(list)
    last_seen: dict[str, datetime] = {}
    burst_idx: dict[str, int] = defaultdict(int)

    for r in rows:
        phone = r['phone']
        ts = r['created_at']
        prev = last_seen.get(phone)
        if prev and (ts - prev) > timedelta(minutes=30):
            burst_idx[phone] += 1
        bursts[(phone, burst_idx[phone])].append(dict(r))
        last_seen[phone] = ts

    # Min turn filtre (user mesaji sayisi)
    filtered = []
    for (phone, idx), msgs in bursts.items():
        user_count = sum(1 for m in msgs if m['message_role'] == 'user')
        if user_count >= min_turns:
            filtered.append({
                "phone": phone,
                "burst_idx": idx,
                "role": msgs[0].get('role', 'ogrenci'),
                "msg_count": len(msgs),
                "user_count": user_count,
                "started_at": msgs[0]['created_at'].isoformat(),
                "messages": msgs,
            })
    return filtered


def format_transcript(messages: list[dict]) -> str:
    """Konusmayi indexli ve kirpilmis formata cevir."""
    lines = []
    for i, m in enumerate(messages):
        role = "Kullanici" if m['message_role'] == 'user' else "Bot"
        content = (m['content'] or "")[:600]  # Her mesaj max 600 char
        lines.append(f"[{i}] {role}: {content}")
    return "\n".join(lines)


async def analyze_burst(client, burst: dict) -> dict | None:
    """Bir konusma parcasini LLM'e gonder, JSON sonuc al.
    25.23: client tipi: GroqClient veya CerebrasClient (her ikisi de complete() destekler).
    """
    transcript = format_transcript(burst["messages"])
    if len(transcript) > 12000:
        transcript = transcript[:12000] + "\n[...truncated]"

    prompt = ANALYSIS_PROMPT.format(
        turn_count=burst["msg_count"],
        role=burst.get("role") or "ogrenci",
        transcript=transcript,
    )

    try:
        # Hem Groq hem Cerebras complete() metodu var — async destek
        if hasattr(client, 'complete_async'):
            result = await client.complete_async(
                messages=[{"role": "user", "content": prompt}],
                system="Sen FermatAI kalite denetcisisin. Objektif, net, Turkce JSON uretirsin.",
                model="gpt-oss-120b" if _CEREBRAS_AVAIL else None,
                max_tokens=1200,
                temperature=0.3,
            )
        else:
            result = await client.complete(
                messages=[{"role": "user", "content": prompt}],
                system="Sen FermatAI kalite denetcisisin. Objektif, net, Turkce JSON uretirsin.",
                max_tokens=1200,
                temperature=0.3,
            )
        text = result.get("text", "").strip()
        # JSON kod blogunu sil
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
            if text.endswith("```"):
                text = text[:-3].strip()
        # Parse
        parsed = json.loads(text)
        parsed["_phone"] = burst["phone"]
        parsed["_burst_idx"] = burst["burst_idx"]
        parsed["_role"] = burst.get("role")
        parsed["_msg_count"] = burst["msg_count"]
        parsed["_started_at"] = burst["started_at"]
        return parsed
    except json.JSONDecodeError as e:
        logger.warning(f"JSON parse fail ({burst['phone']}): {e}. Raw: {text[:200]}")
        return None
    except Exception as e:
        logger.warning(f"Groq analiz hatasi ({burst['phone']}): {e}")
        return None


def aggregate(results: list[dict]) -> dict:
    """Tum burst analizlerini tek rapor halinde birlestir."""
    if not results:
        return {"toplam_konusma": 0, "bulgular": []}

    all_frustration = []
    all_bot_errors = []
    all_missing_patterns = []
    scores = []
    kritik_bulgular = []
    # 25.40p — yeni intent kalite metrikleri
    new_intent_scores = []  # tum yeni intent kayitlari
    rag_kullanilan = 0
    rag_toplam = 0
    renderer_kullanilan = 0
    renderer_toplam = 0
    yeni_nesil_kriter_toplam = 0
    yeni_nesil_kriter_sayisi = 0

    for r in results:
        phone = r.get("_phone")
        for f in r.get("frustration", []):
            all_frustration.append({**f, "phone": phone})
        for b in r.get("bot_hatasi", []):
            all_bot_errors.append({**b, "phone": phone})
        for p in r.get("eksik_pattern", []):
            all_missing_patterns.append({**p, "phone": phone})
        if isinstance(r.get("pedagojik_puan"), (int, float)):
            scores.append(r["pedagojik_puan"])
        if r.get("onemli_bulgu"):
            kritik_bulgular.append({"phone": phone, "bulgu": r["onemli_bulgu"]})
        # 25.40p — yeni intent kalite
        for it in (r.get("yeni_intent_kalite") or []):
            new_intent_scores.append({**it, "phone": phone})
            rag_toplam += 1
            renderer_toplam += 1
            if it.get("rag_kullanildi_mi"):
                rag_kullanilan += 1
            if it.get("renderer_var_mi"):
                renderer_kullanilan += 1
            if isinstance(it.get("yeni_nesil_kriter_sayisi"), (int, float)):
                yeni_nesil_kriter_toplam += it["yeni_nesil_kriter_sayisi"]
                yeni_nesil_kriter_sayisi += 1

    # Bot hata tipi dagilimi
    err_types = defaultdict(int)
    for e in all_bot_errors:
        err_types[e.get("tip", "bilinmeyen")] += 1

    return {
        "toplam_konusma": len(results),
        "ortalama_pedagojik_puan": round(sum(scores) / len(scores), 2) if scores else None,
        "frustration_sayisi": len(all_frustration),
        "bot_hata_sayisi": len(all_bot_errors),
        "bot_hata_tipleri": dict(err_types),
        "eksik_pattern_sayisi": len(all_missing_patterns),
        "top_frustration": all_frustration[:10],
        "top_bot_hatalari": all_bot_errors[:10],
        "top_eksik_patternler": all_missing_patterns[:15],
        "kritik_bulgular": kritik_bulgular[:10],
        # 25.40p (Neo direktif): yeni intent kalite ozeti
        "yeni_intent_metrikleri": {
            "toplam_yeni_intent": len(new_intent_scores),
            "rag_kullanim_orani": round(rag_kullanilan / rag_toplam * 100, 1) if rag_toplam else 0,
            "renderer_kullanim_orani": round(renderer_kullanilan / renderer_toplam * 100, 1) if renderer_toplam else 0,
            "yeni_nesil_kriter_ortalama": round(yeni_nesil_kriter_toplam / yeni_nesil_kriter_sayisi, 1) if yeni_nesil_kriter_sayisi else 0,
        },
        "yeni_intent_detay": new_intent_scores[:15],
    }


async def persist_to_db(report: dict, raw_path: str, period_hours: int, alarm_triggered: bool, results: list[dict]) -> int | None:
    """
    Quality run sonucunu DB'ye persist et (25.40j Neo direktif).
    Returns: run_id (next time için trend hesaplama).
    """
    from db_pool import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        # 1) Master run kayit
        run_id = await conn.fetchval(
            """INSERT INTO conversation_quality_score
               (period_hours, bursts_analyzed, avg_pedagogical_score,
                frustration_count, bot_error_count, missing_pattern_count,
                bot_error_types, critical_findings, raw_report_path, alarm_triggered)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
               RETURNING id""",
            period_hours,
            report.get("toplam_konusma", 0),
            report.get("ortalama_pedagojik_puan"),
            report.get("frustration_sayisi", 0),
            report.get("bot_hata_sayisi", 0),
            report.get("eksik_pattern_sayisi", 0),
            json.dumps(report.get("bot_hata_tipleri", {}), ensure_ascii=False),
            json.dumps(report.get("kritik_bulgular", []), ensure_ascii=False, default=str),
            raw_path,
            alarm_triggered,
        )

        # 2) Burst-level kayitlar
        for r in results:
            try:
                await conn.execute(
                    """INSERT INTO conversation_quality_burst
                       (run_id, phone, burst_idx, role, msg_count, started_at,
                        pedagogical_score, frustration_count, bot_error_count,
                        summary, important_finding, raw_json)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)""",
                    run_id,
                    r.get("_phone") or "",
                    r.get("_burst_idx", 0),
                    r.get("_role") or "ogrenci",
                    r.get("_msg_count", 0),
                    datetime.fromisoformat(r["_started_at"]) if r.get("_started_at") else None,
                    int(r["pedagojik_puan"]) if isinstance(r.get("pedagojik_puan"), (int, float)) else None,
                    len(r.get("frustration", [])),
                    len(r.get("bot_hatasi", [])),
                    (r.get("ozet") or "")[:500],
                    (r.get("onemli_bulgu") or "")[:500],
                    json.dumps(r, ensure_ascii=False, default=str),
                )
            except Exception as _be:
                logger.warning(f"Burst persist hatasi ({r.get('_phone')}): {_be}")
        return run_id


async def check_alarm_and_notify(report: dict, run_id: int | None) -> bool:
    """
    Kalite eşik altına düştüyse Neo'ya WP rapor gönder (25.40j).
    Eşikler:
      - Ortalama puan < 6.0 → ALARM
      - Frustration > 5 → ALARM
      - Bot hata > 8 → ALARM
      - Bir burst score < 4 → ALARM (kritik tek konusma)
    """
    avg = report.get("ortalama_pedagojik_puan") or 10.0
    frust = report.get("frustration_sayisi", 0)
    err = report.get("bot_hata_sayisi", 0)
    kritik = report.get("kritik_bulgular", [])

    triggers = []
    if avg < 6.0:
        triggers.append(f"📉 Ortalama puan dustu: *{avg}/10* (esik 6.0)")
    if frust > 5:
        triggers.append(f"😤 Frustration: *{frust}* (esik 5)")
    if err > 8:
        triggers.append(f"⚠ Bot hatasi: *{err}* (esik 8)")
    if len(kritik) > 0:
        triggers.append(f"🚨 Kritik bulgu: *{len(kritik)}*")

    # 25.40p — yeni intent kalite alarmlari
    yim = report.get("yeni_intent_metrikleri", {})
    if yim.get("toplam_yeni_intent", 0) > 5:  # Yeterli sample varsa
        if yim.get("rag_kullanim_orani", 100) < 50:
            triggers.append(f"📚 RAG kullanim dustu: *{yim['rag_kullanim_orani']}%* (esik 50%)")
        if yim.get("renderer_kullanim_orani", 100) < 60:
            triggers.append(f"🎨 Renderer kullanim dustu: *{yim['renderer_kullanim_orani']}%* (esik 60%)")
        if yim.get("yeni_nesil_kriter_ortalama", 7) < 5:
            triggers.append(f"📋 Yeni nesil kriter ortalama: *{yim['yeni_nesil_kriter_ortalama']}/7* (esik 5)")

    if not triggers:
        logger.info(f"[QUALITY] Esik altinda kalan yok, alarm yok (avg={avg}, frust={frust}, err={err})")
        return False

    # Alarm tetiklendi → Neo'ya WP rapor
    msg = "🩺 *FermatAI Konusma Kalite Alarmi*\n\n"
    for t in triggers:
        msg += f"  {t}\n"
    msg += f"\n📊 *Donem:* son {report.get('_meta', {}).get('hours', 48)}h | *Konusma:* {report['toplam_konusma']}\n"
    if report.get("bot_hata_tipleri"):
        msg += f"📋 *Hata tipleri:* {dict(report['bot_hata_tipleri'])}\n"
    if kritik:
        msg += "\n🔍 *Kritik Bulgular:*\n"
        for k in kritik[:3]:
            phone_tail = (k.get('phone') or '')[-4:]
            msg += f"  • ...{phone_tail}: {k.get('bulgu', '')[:120]}\n"
    msg += f"\n_Detay: logs/kalite_raporu_*.json (run_id={run_id})_"

    try:
        # Neo'ya direkt WP gonder (admin)
        import os, httpx
        token = os.getenv("WA_ACCESS_TOKEN")
        phone_id = os.getenv("WA_PHONE_NUMBER_ID")
        if not token or not phone_id:
            logger.warning("[QUALITY ALARM] WA token/phone_id yok, mesaj atilamadi")
            return True
        url = f"{GRAPH_BASE}/{phone_id}/messages"
        async with httpx.AsyncClient(timeout=15.0) as client:
            await client.post(
                url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"messaging_product": "whatsapp", "to": "905051256802",
                      "type": "text", "text": {"body": msg, "preview_url": False}},
            )
        logger.info(f"[QUALITY ALARM] Neo'ya WP gonderildi: {len(triggers)} tetikleyici")
        return True
    except Exception as e:
        logger.warning(f"[QUALITY ALARM] WP gonderim hatasi: {e}")
        return True  # Yine de alarm tetiklendi sayilir


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=48)
    parser.add_argument("--min-turns", type=int, default=3)
    parser.add_argument("--max-bursts", type=int, default=50,
                       help="Analiz edilecek maksimum konusma sayisi (maliyet kontrolu)")
    parser.add_argument("--no-alarm", action="store_true", help="Neo'ya WP alarm gonderme")
    parser.add_argument("--no-db", action="store_true", help="DB'ye persist etme (sadece JSON)")
    args = parser.parse_args()

    print(f"[*] Son {args.hours} saatin konusmalari cekiliyor...")
    bursts = await fetch_conversations(hours=args.hours, min_turns=args.min_turns)
    print(f"[+] {len(bursts)} konusma bulundu (min {args.min_turns} turn).")

    if not bursts:
        print("[!] Analiz edilecek konusma yok.")
        return

    if len(bursts) > args.max_bursts:
        print(f"[!] Sinir: ilk {args.max_bursts} konusma analiz ediliyor.")
        bursts = bursts[:args.max_bursts]

    # 25.23: Cerebras-first (Groq daily limit dolup duruyor)
    if _CEREBRAS_AVAIL:
        client = CerebrasClient()
        print(f"[*] Cerebras gpt-oss-120b ile analiz basliyor ({len(bursts)} konusma)...")
    else:
        client = GroqClient()
        print(f"[*] Groq 70B ile analiz basliyor ({len(bursts)} konusma)...")

    results = []
    for i, burst in enumerate(bursts, 1):
        print(f"  [{i}/{len(bursts)}] {burst['phone'][-4:]} burst {burst['burst_idx']} ({burst['msg_count']} msg)... ", end="", flush=True)
        r = await analyze_burst(client, burst)
        if r:
            results.append(r)
            print(f"OK (puan {r.get('pedagojik_puan', '?')})")
        else:
            print("FAIL")

    report = aggregate(results)
    report["_meta"] = {
        "hours": args.hours,
        "min_turns": args.min_turns,
        "bursts_analiz_edilen": len(results),
        "bursts_toplam": len(bursts),
        "zaman": datetime.now().isoformat(),
    }

    # Kaydet
    logs_dir = Path(__file__).parent / "logs"
    logs_dir.mkdir(exist_ok=True)
    out = logs_dir / f"kalite_raporu_{datetime.now().strftime('%Y-%m-%d_%H%M')}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\n[+] Rapor kaydedildi: {out}")

    # 25.40j: DB'ye persist + alarm kontrolu
    run_id = None
    alarm = False
    if not args.no_db:
        try:
            # Alarm kontrolunu once yap (alarm flag'i DB'ye yazilir)
            if not args.no_alarm:
                alarm = await check_alarm_and_notify(report, run_id=None)  # run_id sonra yazilir
            run_id = await persist_to_db(report, str(out), args.hours, alarm, results)
            print(f"[+] DB'ye persist: run_id={run_id}, alarm={alarm}")
        except Exception as e:
            print(f"[!] DB persist hatasi: {e}")
    elif not args.no_alarm:
        alarm = await check_alarm_and_notify(report, run_id=None)
        print(f"[+] Alarm kontrolu: {alarm}")

    # Ozet konsola
    print("\n" + "=" * 60)
    print(f"ANALIZ OZETI — {report['toplam_konusma']} konusma")
    print("=" * 60)
    print(f"Ortalama pedagojik puan: {report.get('ortalama_pedagojik_puan', 'N/A')}/10")
    print(f"Frustration: {report['frustration_sayisi']} | Bot hatasi: {report['bot_hata_sayisi']} | Eksik pattern: {report['eksik_pattern_sayisi']}")
    if report['bot_hata_tipleri']:
        print(f"Bot hata tipleri: {report['bot_hata_tipleri']}")

    if report.get("kritik_bulgular"):
        print("\nKRITIK BULGULAR:")
        for k in report["kritik_bulgular"][:5]:
            print(f"  - {k['phone'][-4:]}: {k['bulgu'][:120]}")

    if alarm:
        print("\n🚨 ALARM TETIKLENDI — Neo'ya WP gonderildi")


if __name__ == "__main__":
    asyncio.run(main())
