"""
Anki .apkg Export (Oturum 25.38)
=================================
Öğrencinin active_recall + topic_tracker zayıf konularından Anki deck üret.
.apkg dosyası = SQLite + medya. Anki Mobile/Desktop direkt açar.

Kütüphane: genanki ($0, MIT lisans, pip install genanki)

Kullanım:
  from anki_exporter import build_deck_for_student
  apkg_path = await build_deck_for_student(soz_no=215, max_cards=30)

Deck içeriği:
  - Zayıf konulardan kart (sınav_hata_yuzdesi > 40)
  - active_recall'da bekleyen recall'lar
  - Format: ön=konu sorusu, arka=cevap+ders+tarih
"""

import os
import random
import secrets
import time
from pathlib import Path
from typing import Optional

from loguru import logger

EXPORT_DIR = Path(__file__).parent / "static" / "anki"
EXPORT_DIR.mkdir(parents=True, exist_ok=True)


def is_available() -> bool:
    """genanki kurulu mu?"""
    try:
        import genanki  # noqa: F401
        return True
    except ImportError:
        return False


# Sabit deck ID'ler (kararlı — yeniden import güncelleme yapsın)
FERMAT_MODEL_ID = 1607392319  # rastgele ama sabit
FERMAT_DECK_BASE_ID = 2059400110


def _make_card_template():
    """Anki kart şablonu (ön/arka)."""
    import genanki
    return genanki.Model(
        FERMAT_MODEL_ID,
        "FermatAI YKS Card",
        fields=[
            {"name": "Soru"},
            {"name": "Cevap"},
            {"name": "Ders"},
            {"name": "Konu"},
            {"name": "Notlar"},
        ],
        templates=[
            {
                "name": "Card 1",
                "qfmt": (
                    '<div class="ders">{{Ders}} — {{Konu}}</div>'
                    '<hr>'
                    '<div class="soru">{{Soru}}</div>'
                ),
                "afmt": (
                    '{{FrontSide}}'
                    '<hr id="answer">'
                    '<div class="cevap">{{Cevap}}</div>'
                    '<div class="notlar">{{Notlar}}</div>'
                    '<div class="brand">📚 FermatAI</div>'
                ),
            },
        ],
        css=(
            ".card { font-family: -apple-system, sans-serif; font-size: 18px; "
            "text-align: left; color: #1f2937; background: white; padding: 16px; }"
            ".ders { font-size: 13px; color: #6366f1; font-weight: 600; "
            "text-transform: uppercase; letter-spacing: 0.5px; }"
            ".soru { font-size: 22px; margin: 14px 0; line-height: 1.4; }"
            ".cevap { font-size: 18px; margin: 12px 0; color: #047857; "
            "background: #ecfdf5; padding: 12px; border-radius: 8px; }"
            ".notlar { font-size: 14px; color: #6b7280; margin-top: 12px; "
            "font-style: italic; }"
            ".brand { font-size: 11px; color: #9ca3af; margin-top: 18px; "
            "text-align: right; }"
            "hr { border: none; border-top: 1px solid #e5e7eb; }"
        ),
    )


async def _gather_cards(soz_no: int, max_cards: int = 30,
                       ders_filter: Optional[str] = None) -> list[dict]:
    """DB'den kart datası topla."""
    from db_pool import db_fetch

    cards = []

    # 1. Zayıf konular (topic_tracker)
    where_ders = "AND ders ILIKE $2" if ders_filter else ""
    args = [str(soz_no)]
    if ders_filter:
        args.append(f"%{ders_filter}%")

    weak_topics = await db_fetch(f"""
        SELECT ders, konu, sinav_hata_yuzdesi, sinav_hata_sayisi
        FROM student_topic_tracker
        WHERE soz_no::text = $1
          AND (sinav_hata_yuzdesi IS NULL OR sinav_hata_yuzdesi >= 40)
          {where_ders}
        ORDER BY sinav_hata_yuzdesi DESC NULLS LAST, sinav_hata_sayisi DESC NULLS LAST
        LIMIT {max_cards}
    """, *args)

    for row in weak_topics:
        ders = row.get("ders") or "Genel"
        konu = row.get("konu") or "Konu"
        hata = row.get("sinav_hata_yuzdesi")
        cards.append({
            "soru": f"{konu} konusunu kısaca açıkla. Hangi formülleri kullanırsın?",
            "cevap": "(Aklından geçenleri yazdıktan sonra konu özetini gözden geçir.)",
            "ders": ders,
            "konu": konu,
            "notlar": (
                f"Sınavlarda hata oranın: %{int(hata)}" if hata else
                "Bu konu öncelikli — denemelerden gelen verin yetersiz."
            ),
        })

    # 2. Active recall — bekleyen kartlar (eğer tablo varsa)
    try:
        recalls = await db_fetch(f"""
            SELECT ders, konu, context_summary, scheduled_at
            FROM active_recalls
            WHERE soz_no::text = $1
              AND completed_at IS NULL
              AND scheduled_at <= NOW() + INTERVAL '14 days'
            ORDER BY scheduled_at ASC
            LIMIT {max(0, max_cards - len(cards))}
        """, str(soz_no))
        for row in recalls:
            ders = row.get("ders") or "Genel"
            konu = row.get("konu") or "Recall"
            ctx = row.get("context_summary") or ""
            cards.append({
                "soru": f"{konu} konusunda ne biliyorsun? Anlattığın için tekrar et.",
                "cevap": ctx or "(Hatırlamaya çalış, sonra not aldıklarınla karşılaştır.)",
                "ders": ders,
                "konu": konu,
                "notlar": f"Aktif hatırlama planı (Ebbinghaus) — planlanan: {row.get('scheduled_at')}",
            })
    except Exception as e:
        logger.debug(f"active_recalls okuma hata (boş kart): {e}")

    return cards[:max_cards]


async def build_deck_for_student(soz_no: int, max_cards: int = 30,
                                 ders_filter: Optional[str] = None) -> dict:
    """
    Öğrenci için Anki .apkg deck üret.

    Returns: {success, apkg_path, download_url, card_count, deck_name}
    """
    if not is_available():
        return {"success": False,
                "error": "genanki kurulu değil — 'pip install genanki' çalıştır"}

    cards = await _gather_cards(soz_no, max_cards, ders_filter)
    if not cards:
        return {"success": False, "error": "Bu öğrenci için kart üretilecek veri yok"}

    import genanki
    model = _make_card_template()

    # Deck adı + ID
    suffix = ders_filter or "Genel"
    deck_name = f"FermatAI — Öğrenci {soz_no} — {suffix}"
    # Deck ID stable per soz_no+ders (re-import güncellesin)
    deck_id = FERMAT_DECK_BASE_ID + (int(soz_no) * 10) + (hash(suffix) % 100)
    deck = genanki.Deck(deck_id, deck_name)

    for c in cards:
        note = genanki.Note(
            model=model,
            fields=[
                c["soru"][:1000],
                c["cevap"][:1000],
                c["ders"][:50],
                c["konu"][:200],
                c["notlar"][:500],
            ],
            guid=genanki.guid_for(f"{soz_no}-{c['ders']}-{c['konu']}"),
        )
        deck.add_note(note)

    # Yaz
    token = secrets.token_urlsafe(8)
    fname = f"fermatai-{soz_no}-{int(time.time())}-{token}.apkg"
    out = EXPORT_DIR / fname
    pkg = genanki.Package(deck)
    pkg.write_to_file(str(out))

    return {
        "success": True,
        "apkg_path": str(out),
        "apkg_filename": fname,
        "download_url": f"/static/anki/{fname}",
        "card_count": len(cards),
        "deck_name": deck_name,
        "size_kb": round(out.stat().st_size / 1024, 1),
    }


if __name__ == "__main__":
    import asyncio
    import sys
    if len(sys.argv) < 2:
        print(f"Available: {is_available()}")
        if is_available():
            print("✓ genanki kurulu")
        else:
            print("✗ pip install genanki")
        print("Kullanım: python anki_exporter.py <soz_no> [ders]")
        sys.exit(0)

    soz_no = int(sys.argv[1])
    ders = sys.argv[2] if len(sys.argv) > 2 else None
    res = asyncio.run(build_deck_for_student(soz_no, ders_filter=ders))
    print(res)
