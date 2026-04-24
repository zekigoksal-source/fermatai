"""
Multi-Question RAG Chunk Splitter (22.1n-atlas#12-derin)
========================================================

Problem (Neo, 19 Nisan 2026):
OGM Vision import ettiginde bir PDF sayfasi birden fazla soru iceriyorsa
hepsi tek chunk olarak DB'ye yazildi. Her sorunun kendi konusu var ama
chunk'in tek konu metadata'si var → semantik arama yanliş konuya
eşleştiriyor. Örnek: s.141 "Fotoelektrik" meta'sı, ama içinde SORU 106
Fotoelektrik (2024), SORU 107 Compton (2022), SORU 108 Görüntüleme (2019).

Cozum:
1. Multi-question chunk'lari yakala (SORU N | YIL-AYT 2+ kez geciyor)
2. Her soruyu ayri kayit olarak cikart (konu detection icerik icinden)
3. nomic-embed-text ile yerel embedding (0 maliyet)
4. rag_content'e yeni kayit → INSERT
5. Eski multi-chunk kalir (sayfa-seviye arama icin hala yararli)

Kullanim:
    # Dry-run
    python split_multi_question_rag.py --preview

    # Uygula (tum multi-chunk'lar)
    python split_multi_question_rag.py --apply

    # Tek ID uygula
    python split_multi_question_rag.py --apply --id 4583
"""
import asyncio
import re
import sys
from typing import Optional

from loguru import logger


_SORU_PATTERN = re.compile(
    r"SORU\s+(\d+)\s*\|\s*(\d{4})[-–](AYT|TYT)", re.IGNORECASE
)
_KONU_PATTERN = re.compile(r"KONU:\s*([^\n]{3,120})")

# Icerik-bazli konu tespiti (Vision yanlis etiketlediyse fallback)
# Anahtar: konu_adi, deger: tetikleyici keyword seti (en 2 tanesi gecmeli)
_KONU_KEYWORDS = {
    "Fotoelektrik Olayı": ["eşik enerji", "eşik frekans", "fotoelektrik", "foton", "elektron kopar", "maksimum kinetik", "metal yüzey"],
    "Compton Saçılması": ["saçıl", "x-ışın", "karbon hedef", "serbest elektron", "foton açı"],
    "De Broglie Dalga Boyu": ["de broglie", "madde dalga", "dalga boyu λ"],
    "Görüntüleme Teknolojileri": ["termal kamera", "pet görüntü", "sonar", "mri", "röntgen", "ultrason"],
    "Manyetizma": ["manyetik alan", "manyetik akı", "bobin", "solenoid", "mıknatıs", "akım halka"],
    "Elektrik": ["elektrik alan", "gerilim", "potansiyel fark", "akım şiddeti", "direnç ω"],
    "Dalga": ["dalga boyu", "frekans", "girişim", "kırınım", "periyot"],
    "Optik": ["yansıma", "kırılma", "mercek", "prizma", "odak uzaklığı"],
    "Atom Fiziği": ["enerji seviyesi", "temel hal", "uyarılmış", "bohr", "orbital"],
}


def _score_konu_by_content(block_text: str) -> str:
    """Icerikteki keyword'lere gore konu belirle (lowercase eşleştirme)."""
    lo = block_text.lower()
    best = ("", 0)
    for konu, kws in _KONU_KEYWORDS.items():
        score = sum(1 for kw in kws if kw in lo)
        if score > best[1]:
            best = (konu, score)
    return best[0] if best[1] >= 2 else ""


def find_konu_for_soru(full_text: str, soru_pos: int, block_text: str = "",
                        parent_konu: str = "") -> str:
    """Verilen SORU için en iyi konu tespiti.

    Sıra:
    1. Blok içeriğinden keyword-based tespit (en güvenilir)
    2. SORU'dan ONCE gelen en yakın KONU header (Vision doğru diyse)
    3. parent_konu (rag_content.konu metadata)
    """
    # 1. Keyword tabanli
    if block_text:
        kk = _score_konu_by_content(block_text)
        if kk:
            return kk

    # 2. Inline KONU header
    last_konu = ""
    for m in _KONU_PATTERN.finditer(full_text):
        if m.start() < soru_pos:
            k = m.group(1).strip()
            if not re.search(r"belirtilm|(başlığı|baslik).*(yok|degil)|—|\[|\(|belirti", k.lower()):
                last_konu = k
        else:
            break
    if last_konu:
        return last_konu

    # 3. Parent fallback
    return parent_konu


def split_into_questions(icerik: str, parent_konu: str) -> list[dict]:
    """Chunk'i SORU blokları olarak böl.

    Returns: [{"soru_no": 103, "yil": 2018, "sinav": "AYT",
               "konu": "Fotoelektrik Olay", "icerik": "..."}, ...]
    """
    matches = list(_SORU_PATTERN.finditer(icerik))
    if len(matches) < 2:
        return []  # Zaten tek soru, bolmeye gerek yok

    blocks = []
    for i, m in enumerate(matches):
        soru_no = int(m.group(1))
        yil = int(m.group(2))
        sinav = m.group(3).upper()

        start = m.start()
        # Sondaki SORU: bir sonraki SORU'dan bir sonraki non-SORU baslayinca biter
        end = matches[i + 1].start() if i + 1 < len(matches) else len(icerik)
        block_text = icerik[start:end].strip()

        # Konu tespiti: blok icinde veya ondan once (parent konu)
        konu = find_konu_for_soru(icerik[:end], start, block_text=block_text, parent_konu=parent_konu)
        if not konu:
            konu = parent_konu or "Genel"

        # Temizle: "---\nDERS: Fizik\nKONU: X\n\n" baslik kismini cikar
        cleaned = block_text
        # Basa standart header ekle
        header = f"DERS: {_DERS_FROM_PARENT(parent_konu)}\nKONU: {konu}\n\n"
        wrapped = "---\n" + header + cleaned

        blocks.append({
            "soru_no": soru_no,
            "yil": yil,
            "sinav": sinav,
            "konu": konu,
            "icerik": wrapped,
        })
    return blocks


def _DERS_FROM_PARENT(s: str) -> str:
    # Bu fallback; caller'dan zaten parent ders geliyor
    return "Fizik"  # placeholder — caller overwrite eder


async def embed_text(text: str) -> Optional[list[float]]:
    """Yerel nomic-embed-text ile 768-boyutlu embedding uret."""
    try:
        import ollama
        client = ollama.Client(host="http://localhost:11434", timeout=30)
        r = client.embeddings(model="nomic-embed-text", prompt=text[:3000])
        return r.get("embedding") or None
    except Exception as e:
        logger.error(f"Embedding hatasi: {e}")
        return None


async def process_chunk(row: dict, apply: bool = False) -> dict:
    """Tek multi-chunk'i isle. Dry-run ise sadece raporla."""
    from db_pool import db_execute

    icerik = row["icerik"] or ""
    parent_konu = row["konu"] or ""
    ders = row["ders"] or ""

    blocks = split_into_questions(icerik, parent_konu)
    if not blocks:
        return {"id": row["id"], "status": "single_or_empty"}

    # ders field'ini doldur
    for b in blocks:
        b["icerik"] = b["icerik"].replace("DERS: Fizik\n", f"DERS: {ders}\n", 1)

    added = []
    for b in blocks:
        if not apply:
            added.append(b)
            continue

        emb = await embed_text(b["icerik"])
        if not emb:
            logger.warning(f"Embed yok, atlandi: id={row['id']} soru={b['soru_no']}")
            continue

        # pgvector insert
        emb_str = "[" + ",".join(str(x) for x in emb) + "]"
        try:
            await db_execute(
                """INSERT INTO rag_content
                   (sinav_turu, ders, konu, baslik, icerik, embedding,
                    zorluk, soru_sayisi, kaynak, icerik_turu)
                   VALUES ($1, $2, $3, $4, $5, $6::vector, $7, $8, $9, $10)""",
                b["sinav"], ders, b["konu"],
                f"SORU {b['soru_no']} | {b['yil']}-{b['sinav']}",
                b["icerik"], emb_str,
                "orta", 1,
                row["kaynak"] + f" (split Q{b['soru_no']})",
                "cikmis_soru",
            )
            added.append(b)
        except Exception as e:
            logger.error(f"INSERT hata id={row['id']} q{b['soru_no']}: {e}")

    return {
        "id": row["id"],
        "kaynak": row["kaynak"],
        "parent_konu": parent_konu,
        "split_count": len(blocks),
        "added": len(added),
        "topics": [f"Q{b['soru_no']} {b['yil']}-{b['sinav']}: {b['konu'][:30]}" for b in blocks],
    }


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true", help="Sadece raporla, uygulama")
    parser.add_argument("--apply", action="store_true", help="DB'ye yeni chunk'lari ekle")
    parser.add_argument("--id", type=int, help="Tek rag_content id'si isle")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv(override=True)
    from db_pool import db_fetch

    # Multi-question chunk'lari bul
    if args.id:
        rows = await db_fetch(
            "SELECT id, ders, konu, kaynak, icerik FROM rag_content WHERE id=$1",
            args.id
        )
    else:
        all_rows = await db_fetch(
            "SELECT id, ders, konu, kaynak, icerik FROM rag_content "
            "WHERE kaynak LIKE 'OGM Vision%' AND kaynak NOT LIKE '%split%'"
        )
        rows = []
        for r in all_rows:
            matches = _SORU_PATTERN.findall(r["icerik"] or "")
            if len(matches) >= 2:
                rows.append(r)

    logger.info(f"Isle: {len(rows)} multi-question chunk")
    total_split = 0
    apply = bool(args.apply)

    for r in rows:
        res = await process_chunk(dict(r), apply=apply)
        if res.get("split_count"):
            total_split += res["added"]
            mode = "APPLY" if apply else "PREVIEW"
            print(f"[{mode}] id={res['id']} → {res['added']}/{res['split_count']} chunk")
            for t in res.get("topics", [])[:5]:
                print(f"    {t}")

    print(f"\nToplam: {len(rows)} chunk taranır, {total_split} yeni kayit {'eklendi' if apply else 'eklenebilir (dry-run)'}")


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    asyncio.run(main())
