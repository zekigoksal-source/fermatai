"""
Pedagoji V2 — Lazy Loader (25.41 Neo)
======================================

Claude system_prompt'una eklenecek dinamik blok üretici.

Akış:
  build_pedagoji_block(message, ders, soz_no, detected_mood)
    → trigger_engine.match_category(message)
    → match varsa get_kategori_paket() → format_paket_for_prompt()
    → string döner ("" eğer match yok = 0 token)

Token bilinçli:
  - Match yok: 0 token
  - Match var: ~280-350 token (TEK paket)
  - Eski sistem: ~1080 token (3 blok aynı anda) — %67 tasarruf
"""
from __future__ import annotations
import sys
from pathlib import Path

# Allow direct execution + module import
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from typing import Optional
from loguru import logger

from pedagoji.trigger_engine import (
    match_category,
    get_kategori_paket,
    format_paket_for_prompt,
    log_kullanim,
)


# Mood → kategori mapping (egitim_psikoloji ile uyum)
_MOOD_KATEGORI_MAP = {
    "sinav_kaygisi": "STRES",
    "motivasyon_dusuk": "MOTIVASYON",
    "ogrenme_bloku": "OGRENME",
    "perfeksiyonizm": "AZIM",
    "kiyas_travmasi": "KIMLIK",
    "vazgecme": "MOTIVASYON",
    "panik": "STRES",
    "donup_kaldim": "STRES",
    "umutsuz": "AZIM",
    "yalniz": "KIMLIK",
}


# Ders detect — anekdot içinde kullanılır
_DERS_KEYWORDS = {
    "matematik": ["turev", "integral", "limit", "fonksiyon", "denklem", "matematik", "geometri"],
    "fizik": ["kuvvet", "enerji", "hiz", "manyetik", "elektrik", "fizik", "optik"],
    "kimya": ["atom", "molekul", "bag", "asit", "kimya", "tepkime"],
    "biyoloji": ["hucre", "dna", "protein", "biyoloji", "evrim", "ekosistem"],
    "edebiyat": ["siir", "roman", "yazar", "edebiyat", "dil", "anlatim"],
    "tarih": ["osmanli", "savas", "tarih", "medeniyet", "imparatorluk"],
}


def _detect_ders(message: str) -> str:
    msg = (message or "").lower()
    for ders, kws in _DERS_KEYWORDS.items():
        if any(k in msg for k in kws):
            return ders
    return ""


async def build_pedagoji_block(
    message: str,
    ders: str = "",
    soz_no: Optional[str] = None,
    detected_mood: Optional[str] = None,
) -> str:
    """Mesaj → uygun pedagoji paketi (system_prompt eki).

    Returns:
      "" (match yoksa, 0 token)
      VEYA
      "📚 BU MESAJDA ... \nKategori: ...\n📖 Yöntem: ...\n📚 Hikaye: ...\n💡 Sentez: ...\n⚠️ Doğal anlat..."
      (~280-350 token)
    """
    if not message or len(message) < 3:
        return ""

    # ─── Kategori belirle ────────────────────────────────
    kategori = None
    trigger_word = None

    # 1. Önce duygu tespit (mood) — daha güvenilir
    if detected_mood and detected_mood in _MOOD_KATEGORI_MAP:
        kategori = _MOOD_KATEGORI_MAP[detected_mood]
        trigger_word = f"mood:{detected_mood}"

    # 2. Mood yoksa mesaj regex match
    if not kategori:
        kategori, trigger_word = match_category(message)

    if not kategori:
        return ""  # 0 token

    # ─── Ders detect (anekdot match için) ─────────────────
    if not ders:
        ders = _detect_ders(message)

    # ─── Paket çek ───────────────────────────────────────
    try:
        paket = await get_kategori_paket(kategori, ders=ders, soz_no=soz_no)
    except Exception as e:
        logger.debug(f"[pedagoji_lazy] paket fail: {e}")
        return ""

    if not paket:
        return ""

    # ─── Format ──────────────────────────────────────────
    block = format_paket_for_prompt(paket)

    # ─── Asenkron log (silent fail OK) ────────────────────
    try:
        await log_kullanim(
            kategori=kategori,
            kavram_slug=paket.get("kavram", {}).get("slug"),
            anekdot_slug=None,  # paket içinde slug yok, sonra ekleyebilir
            soz_no=soz_no,
            mesaj=message,
            trigger_kelime=trigger_word,
            olcum="auto_match",
        )
    except Exception:
        pass

    return "\n\n" + block


# ─── MINI INDEX (system prompt sabit) ──────────────────────

def get_mini_index() -> str:
    """Claude system_prompt'a eklenir — sabit, ~245 token.

    ESKİ sistem (system_prompts.py 1958-1996, ~600 token statik) yerine.
    Yalnızca kategori isimleri + protokol özeti.
    """
    from pedagoji.kategoriler import KATEGORILER
    lines = ["📚 PEDAGOJI MOTORU (8 kategori, 41 kavram + 76 anekdot DB):"]
    for slug, k in KATEGORILER.items():
        lines.append(f"  • {slug}: {k['aciklama'][:55]}")
    lines.append(
        "Trigger otomatik (mesaj→kategori→CTX paket). "
        "search_pedagoji(durum) tool ile manuel çek. "
        "Doğal anlat — 'literatür/akademik' DEME, 'biliyor musun' kullan."
    )
    return "\n".join(lines)


if __name__ == "__main__":
    import asyncio, sys
    sys.stdout.reconfigure(encoding="utf-8")

    async def test():
        print("🧪 Lazy Loader Test\n")
        print("=== MINI INDEX ===")
        idx = get_mini_index()
        print(idx)
        print(f"\n[mini_index] {len(idx)} char ≈ {len(idx)//3} token\n")

        tests = [
            ("Ben fizik yapamam, vazgeçeceğim", None),
            ("Geçen ay öğrendiğimi unuttum", None),
            ("Sınava 1 hafta var, panikteyim", None),
            ("merhaba", None),
        ]
        for msg, mood in tests:
            block = await build_pedagoji_block(msg, detected_mood=mood)
            tok = len(block) // 3 if block else 0
            print(f"---\nMesaj: {msg}")
            if block:
                print(f"Token: ~{tok}")
                print(block[:300] + "...")
            else:
                print(f"Token: 0 (match yok)")

    asyncio.run(test())
