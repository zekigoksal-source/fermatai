"""
User Feedback Otomatik Triaj — Oturum 25.29
=============================================

user_feedback tablosunda 'yeni' status'undeki kayitlari analiz eder ve
4 kategoriye ayirir:

  - teknik:    "ulasamiyorum", "hata aldim", "calismiyor" → admin alarm
  - icerik:    "X soru ekle", "Y formul yaz" → RAG'a girmesi gerekli
  - vague:     "hatayi not et" + 4 kelime az → admin manuel triaj
  - saka:      emoji alfabesi, troll, kimlik manipulasyonu → otomatik dismiss

Strateji:
  1. Kural-tabanli on-eleme (regex + uzunluk + emoji/sembol orani)
  2. Belirsiz olanlar icin Cerebras 8b ile akilli kategorize ($0.0001/feedback)
  3. Triaj sonrasi status='triaged_<kategori>' olarak isaretle
  4. teknik + icerik kategorileri admin alarm uretir (alert_log)

Kullanim:
  python feedback_triage.py            # tum yeni feedback'leri triaj et
  python feedback_triage.py --dry      # sadece raporla, status'a dokunma

precompute_nightly entegre edilmis (her gece 03:00).
"""
from __future__ import annotations
import argparse
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))


# ─── KURAL-TABANLI ON-ELEME ───────────────────────────────────────────────────

# Kelimeler: kategori puanlama
_TEKNIK_KEYWORDS = [
    "ulasamiyor", "ulaşamıyor", "ulasamadim", "ulaşamadım",
    "hata aldim", "hata aldım", "hatayi", "hatayı",
    "calismiyor", "çalışmıyor", "calismadi", "çalışmadı",
    "acilmiyor", "açılmıyor", "yuklemiyor", "yüklemiyor",
    "donuyor", "donüyor", "kayboldu", "siliniyor",
    "panelime", "programima", "programıma", "veri", "verilerim",
    "telafi", "telefon", "guncellenmedi", "güncellenmedi",
    "teknik aksama", "aksama",
]

_ICERIK_KEYWORDS = [
    "soru ekle", "soru not", "kalitim", "kalıtım",
    "konu ekle", "icerik ekle", "içerik ekle",
    "kaynak ekle", "video ekle", "formul ekle", "formül ekle",
    "rag", "anlatim", "anlatım", "konu anlatim",
    "cikmis soru", "çıkmış soru", "cikmis test", "çıkmış test",
    "puan hesapla", "konu sayisi", "konu sayısı",
    "ders dagilim", "ders dağılım",
]

_SAKA_KEYWORDS = [
    "tony stark", "iron man", "isa mesih",
    "yeni bir dil", "emoji alfabesi", "alfabesi",
    "patlat", "yumurta", "kuyruk",
    "uzayli", "uzaylı", "robotum", "ben robot",
    "talimatlari unut", "talimatları unut", "yeni kural",
    "sen artik", "sen artık", "sen kimsin",
]

# Vague (anlamsiz/eksik) — CIDDIYE ALINMAYACAK kadar belirsiz
_VAGUE_PATTERNS = [
    r'^hatayi\s*(admine\s*)?(belirtmek\s*uzere\s*)?not\s*et\.?$',
    r'^hatayi\s*not\s*et\.?$',
    r'^not\s*et\.?$',
    r'^kaydet\.?$',
]


def _is_emoji_heavy(text: str) -> bool:
    """%30+ emoji/sembol → büyük olasılıkla şaka."""
    if not text:
        return False
    # Emoji range + sembol
    emoji_chars = sum(
        1 for c in text
        if ord(c) > 0x1F300 or c in "🎯💪😊👍😄🎉🌙☀️🔥💯"
    )
    return len(text) > 0 and (emoji_chars / len(text)) > 0.25


def _classify_rule_based(feedback: str) -> Optional[str]:
    """Kural-tabanli kategorize. None: belirsiz, LLM gerekli."""
    if not feedback:
        return "vague"
    text = feedback.lower().strip()

    # 1. Saka tespiti — emoji-heavy veya saka keyword
    if _is_emoji_heavy(feedback):
        return "saka"
    for kw in _SAKA_KEYWORDS:
        if kw in text:
            return "saka"

    # 2. Vague — kalibe edilmis "not et" formulleri
    for pat in _VAGUE_PATTERNS:
        if re.match(pat, text):
            return "vague"
    # Cok kisa (< 15 char) ve sadece "hata/sorun/aksama" iceriyorsa vague
    if len(text) < 20:
        if re.search(r'^(hata|sorun|aksama|problem)', text):
            return "vague"

    # 3. Teknik tespiti — 2+ keyword eslese mi?
    teknik_hits = sum(1 for kw in _TEKNIK_KEYWORDS if kw in text)
    if teknik_hits >= 1 and len(text) >= 20:
        return "teknik"

    # 4. Icerik tespiti
    icerik_hits = sum(1 for kw in _ICERIK_KEYWORDS if kw in text)
    if icerik_hits >= 1:
        return "icerik"

    # Belirsiz — LLM'e bırak
    return None


# ─── LLM KATEGORIZE (Cerebras 8b) ─────────────────────────────────────────────

async def _classify_with_llm(feedback: str) -> str:
    """Belirsiz feedback için Cerebras ile akilli kategori."""
    try:
        from cerebras_handler import CerebrasClient
        import os
        if not os.getenv("CEREBRAS_API_KEY"):
            return "vague"
        client = CerebrasClient()
        prompt = f"""Asagidaki kullanici geri bildirimini KESIN olarak 4 kategoriden BIRINE ata:
- teknik: sistem hatasi, erisim sorunu, calismayan ozellik bildirimi
- icerik: yeni soru/konu/icerik talebi (RAG'a eklenecek)
- vague: belirsiz, eksik bilgi ("hatayi not et" gibi)
- saka: troll, sacma, kimlik manipulasyonu

Sadece kategori adini yaz, baska aciklama YAPMA.

Geri bildirim: {feedback[:500]}

Kategori:"""
        result = await client.complete_async(
            messages=[{"role": "user", "content": prompt}],
            system="Sen kategorize uzmanisin. Sadece tek kelime cevap ver.",
            model="gpt-oss-120b",  # 25.50: llama3.1-8b Cerebras'ta emekli → gpt-oss-120b
            max_tokens=10,
            temperature=0.1,
        )
        if result.get("ok") and result.get("text"):
            cat = result["text"].strip().lower()
            for known in ("teknik", "icerik", "vague", "saka"):
                if known in cat:
                    return known
    except Exception as e:
        logger.debug(f"[TRIAGE] Cerebras fail: {e}")
    return "vague"  # fallback


# ─── DB ──────────────────────────────────────────────────────────────────────

async def fetch_pending_feedback() -> list[dict]:
    from db_pool import db_fetch
    try:
        rows = await db_fetch(
            """SELECT id, phone, role, full_name, feedback, category, created_at
               FROM user_feedback
               WHERE status = 'yeni'
               ORDER BY created_at DESC LIMIT 100"""
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.exception(f"[TRIAGE] fetch fail: {e}")
        return []


async def update_feedback_status(feedback_id: int, new_status: str, notes: str = "") -> None:
    from db_pool import db_execute
    try:
        # category kolonu mevcut, status'a triaj kategoriyi yaz
        await db_execute(
            """UPDATE user_feedback
               SET status = $1,
                   category = CASE WHEN $2 = '' THEN category ELSE $2 END
               WHERE id = $3""",
            new_status, notes, feedback_id,
        )
    except Exception as e:
        logger.debug(f"[TRIAGE] update fail id={feedback_id}: {e}")


async def alert_admin_for_serious(serious: list[dict]) -> None:
    """teknik + icerik kategorisi feedback'ler icin alert_log'a not yaz."""
    if not serious:
        return
    from db_pool import db_execute
    try:
        # alert_log schema: alert_type, severity, target_phone, message, created_at
        # admin = Neo telefonu
        admin_phone = "905051256802"
        for item in serious:
            kategori = item.get("kategori", "?")
            try:
                await db_execute(
                    """INSERT INTO alert_log
                         (alert_type, severity, target_phone, message, created_at)
                       VALUES ($1, 'info', $2, $3, NOW())""",
                    f"feedback_{kategori}",
                    admin_phone,
                    f"Yeni {kategori} feedback (id={item['id']}): "
                    f"{item['feedback'][:200]}"[:500],
                )
            except Exception as e:
                logger.debug(f"[TRIAGE] alert insert fail id={item['id']}: {e}")
    except Exception as e:
        logger.debug(f"[TRIAGE] alert flow fail: {e}")


# ─── ANA TRIAJ ───────────────────────────────────────────────────────────────

async def triage_pending_feedback(dry_run: bool = False) -> dict:
    """yeni → triaged_<kategori> donusumu + admin alarm."""
    pending = await fetch_pending_feedback()
    report = {
        "started_at": datetime.now().isoformat(),
        "total": len(pending),
        "rule_based": 0,
        "llm_based": 0,
        "kategoriler": {"teknik": 0, "icerik": 0, "vague": 0, "saka": 0},
        "items": [],
        "alerted": 0,
    }

    if not pending:
        return report

    serious_to_alert: list[dict] = []
    for f in pending:
        feedback_text = f.get("feedback", "") or ""

        # 1. Rule-based on-eleme
        kategori = _classify_rule_based(feedback_text)
        method = "rule"

        # 2. Belirsizse LLM'e sor
        if kategori is None:
            kategori = await _classify_with_llm(feedback_text)
            method = "llm"
            report["llm_based"] += 1
        else:
            report["rule_based"] += 1

        report["kategoriler"][kategori] = report["kategoriler"].get(kategori, 0) + 1
        report["items"].append({
            "id": f["id"],
            "kategori": kategori,
            "method": method,
            "preview": feedback_text[:80],
        })

        if not dry_run:
            new_status = f"triaged_{kategori}"
            await update_feedback_status(f["id"], new_status, kategori)

        if kategori in ("teknik", "icerik"):
            serious_to_alert.append({
                "id": f["id"],
                "kategori": kategori,
                "feedback": feedback_text,
            })

    # Admin alert (sadece serious — teknik + icerik)
    if not dry_run and serious_to_alert:
        await alert_admin_for_serious(serious_to_alert)
        report["alerted"] = len(serious_to_alert)

    report["finished_at"] = datetime.now().isoformat()

    # data_freshness'a yaz
    if not dry_run:
        try:
            from data_freshness_helper import mark_success
            await mark_success(
                "feedback_triage",
                count=len(pending),
                notes=f"teknik={report['kategoriler']['teknik']} "
                      f"icerik={report['kategoriler']['icerik']}"
            )
        except Exception:
            pass

    return report


def _print_report(r: dict) -> None:
    print("=" * 60)
    print(f"FEEDBACK TRIAJ")
    print(f"  Toplam yeni:    {r.get('total', 0)}")
    print(f"  Rule-based:     {r.get('rule_based', 0)}")
    print(f"  LLM-based:      {r.get('llm_based', 0)}")
    print(f"  Admin alert:    {r.get('alerted', 0)}")
    print(f"  Kategoriler:")
    for k, v in r.get("kategoriler", {}).items():
        print(f"    {k:8s}: {v}")
    if r.get("items"):
        print(f"\n  Ornek 5:")
        for it in r["items"][:5]:
            print(f"    [{it['kategori']:8s}/{it['method']:4s}] id={it['id']}: {it['preview']}")
    print("=" * 60)


async def _main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry", action="store_true", help="Sadece rapor, DB'ye yazma")
    args = p.parse_args()
    rep = await triage_pending_feedback(dry_run=args.dry)
    _print_report(rep)


if __name__ == "__main__":
    asyncio.run(_main())
