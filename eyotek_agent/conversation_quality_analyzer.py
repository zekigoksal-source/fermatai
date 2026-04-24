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
import sys
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

from dotenv import load_dotenv
load_dotenv(override=True)

from db_pool import db_fetch
from groq_handler import GroqClient
from loguru import logger


ANALYSIS_PROMPT = """Asagida FermatAI (YKS/LGS bot) ile bir kullanici arasinda gecmis konusma var.
Konusma uzunlugu: {turn_count} mesaj. Kullanici rolu: {role}.

Gorevin: Bu konusmayi pedagojik ve teknik kalite acisindan INCELE.
Cikti JSON olmali (markdown kod blogu DEGIL, sadece JSON):

{{
  "ozet": "1-2 cumle konu",
  "frustration": [
    {{"mesaj_idx": 3, "sebep": "bot 2. kez ayni hatayi yapti", "aciklama": "..."}}
  ],
  "bot_hatasi": [
    {{"tip": "halusinasyon|yanlis_data|baglam_kaybi|dil|ton", "mesaj_idx": 5, "aciklama": "..."}}
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


async def analyze_burst(client: GroqClient, burst: dict) -> dict | None:
    """Bir konusma parcasini Groq'a gonder, JSON sonuc al."""
    transcript = format_transcript(burst["messages"])
    if len(transcript) > 12000:
        transcript = transcript[:12000] + "\n[...truncated]"

    prompt = ANALYSIS_PROMPT.format(
        turn_count=burst["msg_count"],
        role=burst.get("role") or "ogrenci",
        transcript=transcript,
    )

    try:
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
    }


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=48)
    parser.add_argument("--min-turns", type=int, default=3)
    parser.add_argument("--max-bursts", type=int, default=50,
                       help="Analiz edilecek maksimum konusma sayisi (maliyet kontrolu)")
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


if __name__ == "__main__":
    asyncio.run(main())
