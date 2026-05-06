"""
Pedagoji V2 — Trigger Engine (25.41 Neo)
=========================================

Mesajdan kategori bul (regex + keyword) → kategori paketi getir.

Akış:
  message → match_category() → kategori_slug | None
        → get_paket(kategori) → {kavram, anekdot, oneri, _token_size}

Token bilinçli — paket sadece match olduğunda hesaplanır.
"""
from __future__ import annotations
import re
import random
from typing import Optional
from db_pool import db_fetch, db_fetchrow, db_execute

from pedagoji.kategoriler import KATEGORILER


# ─── COMPILED REGEX CACHE ────────────────────────────────

_COMPILED_PATTERNS: dict[str, re.Pattern] = {}


def _get_compiled(kategori_slug: str) -> Optional[re.Pattern]:
    if kategori_slug in _COMPILED_PATTERNS:
        return _COMPILED_PATTERNS[kategori_slug]
    kat = KATEGORILER.get(kategori_slug)
    if not kat:
        return None
    try:
        pat = re.compile(kat["trigger_patterns"], re.IGNORECASE)
        _COMPILED_PATTERNS[kategori_slug] = pat
        return pat
    except re.error:
        return None


# ─── MATCH ───────────────────────────────────────────────

def match_category(message: str) -> tuple[Optional[str], Optional[str]]:
    """Mesajdan kategori belirle.

    Returns: (kategori_slug, match_kelime) — match yoksa (None, None)
    """
    if not message or len(message) < 3:
        return None, None

    msg_lower = message.lower()

    # Her kategoriyi sırayla dene (priority order: en spesifik önce)
    # Sıra: STRES (panik > genel) → AZIM → MOTIVASYON → ODAK → DISIPLIN → KIMLIK → OGRENME → HAFIZA
    priority = ["STRES", "AZIM", "MOTIVASYON", "ODAK", "DISIPLIN", "KIMLIK", "OGRENME", "HAFIZA"]

    for kat_slug in priority:
        pat = _get_compiled(kat_slug)
        if not pat:
            continue
        m = pat.search(msg_lower)
        if m:
            return kat_slug, m.group(0)

    return None, None


# ─── PAKET BUILDER ───────────────────────────────────────

async def get_kategori_paket(
    kategori_slug: str,
    ders: str = "",
    soz_no: Optional[str] = None,
) -> Optional[dict]:
    """Kategori için Claude CTX paketi.

    Returns:
      {
        "kategori": "MOTIVASYON",
        "kavram": {slug, baslik, kullanim_ornegi},
        "anekdot": {kim, baslik, metin},
        "oneri_formul": "...",
        "_token_size": 280  # tahmini
      }
    """
    kat = KATEGORILER.get(kategori_slug)
    if not kat:
        return None

    # Kavram seç (kategorideki rastgele 1)
    kavram_query = """
        SELECT slug, baslik, kullanim_ornegi
        FROM pedagoji_kavram_v2 WHERE kategori = $1
        ORDER BY RANDOM() LIMIT 1
    """
    kavram_row = await db_fetchrow(kavram_query, kategori_slug)

    # Anekdot seç (ders match önce, yoksa rastgele)
    if ders:
        anekdot_query = """
            SELECT kim, baslik, metin FROM pedagoji_anekdot_v2
            WHERE kategori = $1 AND (ders = $2 OR ders = '')
            ORDER BY (CASE WHEN ders=$2 THEN 0 ELSE 1 END), RANDOM()
            LIMIT 1
        """
        anekdot_row = await db_fetchrow(anekdot_query, kategori_slug, ders)
    else:
        anekdot_query = """
            SELECT kim, baslik, metin FROM pedagoji_anekdot_v2
            WHERE kategori = $1 ORDER BY RANDOM() LIMIT 1
        """
        anekdot_row = await db_fetchrow(anekdot_query, kategori_slug)

    if not kavram_row and not anekdot_row:
        return None

    paket = {
        "kategori": kategori_slug,
        "kategori_baslik": kat["baslik"],
        "default_konum": kat["default_konum"],
        "kavram": dict(kavram_row) if kavram_row else None,
        "anekdot": dict(anekdot_row) if anekdot_row else None,
        "oneri_formul": kat["oneri_formul"],
    }
    # Tahmini token (kabaca chars/3)
    text = format_paket_for_prompt(paket)
    paket["_token_size"] = len(text) // 3
    return paket


def format_paket_for_prompt(paket: dict) -> str:
    """Paketi Claude system prompt'una eklenecek formatına çevir.

    Token bilinçli — 200-280 token aralığı hedef.
    """
    if not paket:
        return ""
    lines = [paket["default_konum"]]
    if paket.get("kavram"):
        k = paket["kavram"]
        lines.append(f"📖 {k['baslik']}")
        if k.get("kullanim_ornegi"):
            # 240 → 180 char (öğrenci dialogu yeterli)
            lines.append(f"  → {k['kullanim_ornegi'][:180]}")
    if paket.get("anekdot"):
        a = paket["anekdot"]
        # Anekdot metni 280 → 220 char (öz korur)
        metin = a['metin']
        if len(metin) > 220:
            # Cümle sonuna kadar kırp (.)
            cut = metin[:220]
            last_period = cut.rfind('.')
            if last_period > 100:
                metin = cut[:last_period+1]
            else:
                metin = cut + "..."
        lines.append(f"📚 {a['kim']}: {metin}")
    # Sentez 200 → 100 char (referans yeter)
    lines.append(f"💡 {paket['oneri_formul'][:100]}")
    lines.append("⚠️ Doğal anlat — 'biliyor musun' kullan, 'literatür' DEME.")
    return "\n".join(lines)


# ─── KULLANIM LOG ────────────────────────────────────────

async def log_kullanim(
    kategori: str,
    kavram_slug: Optional[str],
    anekdot_slug: Optional[str],
    soz_no: Optional[str],
    mesaj: str,
    trigger_kelime: Optional[str],
    olcum: str = "auto_match",
):
    """Hangi paket nereden tetiklendi — analitik için."""
    try:
        await db_execute("""
            INSERT INTO pedagoji_kullanim_log
              (kategori, kavram_slug, anekdot_slug, soz_no,
               mesaj_excerpt, trigger_kelime, olcum)
            VALUES ($1,$2,$3,$4,$5,$6,$7)
        """, kategori, kavram_slug, anekdot_slug, soz_no,
             (mesaj or "")[:100], trigger_kelime, olcum)
    except Exception:
        pass  # log bozulsa da sistem çalışsın


# ─── TEST ────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    test_messages = [
        "ben fizik yapamam, hep böyle olmaz",                 # MOTIVASYON
        "geçen ay öğrendiğimi unuttum",                       # HAFIZA
        "odaklanamıyorum, 2 saat oturuyorum verim yok",       # ODAK
        "sınava 1 hafta var, panikteyim donup kalıyorum",     # STRES
        "düzensizim, sürekli erteliyorum",                    # DISIPLIN
        "ailem zorluyor, kendim için değil",                  # KIMLIK
        "anlamıyorum, çok karışık",                           # OGRENME
        "yine başarısızım, reddedildim",                      # AZIM
        "merhaba",                                            # NONE
        "evet",                                               # NONE
    ]

    print("🧪 Trigger Match Test\n")
    for msg in test_messages:
        cat, word = match_category(msg)
        match_str = f"{cat}/'{word}'" if cat else "—"
        print(f"  {msg:55s} → {match_str}")
