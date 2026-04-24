"""
OGM PDF Konu → Sayfa Index Pipeline (22.1n-fikir2)
===================================================

Neo 20 Nisan 22:26-28:
> "ogmdeki tüm içeriği n razından hangi konu hangi PDF sayfasında
>  otomatik bağlayacak bir sistem olabilir mi?
>  Bunu sen yapabilir misin?"

ÇÖZÜM:
1. Her OGM PDF'in ilk 10 sayfasında "İÇİNDEKİLER" varsa bul
2. İçindekilerdeki her konu başlığını → sayfa numarasına map et
3. `pdf_konu_index` tablosuna yaz (pdf_adi, konu, sayfa_start, sayfa_end)
4. search_curriculum semantik arama sonucunu bu map ile zenginleştirir:
   "Fotoelektrik TYT_Fizik.pdf → s.45-52" direkt bilinir

BONUS:
- MEB OGM konu özeti PDF'lerinin 47 tanesi var (ogm_catalog) — hepsine uygula
- Ayrıca /icerik-indir/{id} URL ile PDF indirilebilir → otomatik import

KULLANIM:
  python pdf_konu_index.py --pdf TYT_Fizik.pdf           # tek PDF
  python pdf_konu_index.py --all                          # tum mevcut PDF
  python pdf_konu_index.py --search "fotoelektrik"       # konu ara

GÜVENLİK: Bu modül MESAJ ATMAZ. Sadece PDF okur + DB yazar.
"""
import asyncio
import re
from pathlib import Path
from typing import Optional

from loguru import logger


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS pdf_konu_index (
    id SERIAL PRIMARY KEY,
    pdf_adi TEXT NOT NULL,
    ders TEXT,
    sinav_turu TEXT,
    konu TEXT NOT NULL,
    sayfa_start INT,
    sayfa_end INT,
    parent_konu TEXT,
    level INT DEFAULT 1,
    source TEXT DEFAULT 'toc_auto',
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(pdf_adi, konu, sayfa_start)
);
CREATE INDEX IF NOT EXISTS idx_pdf_konu_konu ON pdf_konu_index(LOWER(konu));
CREATE INDEX IF NOT EXISTS idx_pdf_konu_pdf  ON pdf_konu_index(pdf_adi);
"""


# Içindekiler sayfasi pattern'leri — Turkce PDF'lerde yaygın biçimler
TOC_PATTERNS = [
    # "1. Fotoelektrik Olayı .................. 45"
    re.compile(r"^\s*(?:\d+\.\s*)?([A-ZÇĞİÖŞÜa-zçğıöşü][A-ZÇĞİÖŞÜa-zçğıöşü\s\-–,/&()0-9]{3,80})\s*[\.…]{3,}\s*(\d{1,4})\s*$", re.MULTILINE),
    # "Fotoelektrik Olayı     45"
    re.compile(r"^\s*([A-ZÇĞİÖŞÜ][A-ZÇĞİÖŞÜa-zçğıöşü\s\-–,&()/0-9]{3,60})\s+(\d{2,4})\s*$", re.MULTILINE),
]

TOC_PAGE_HINTS = ["İÇİNDEKİLER", "İÇİNDEKİ LER", "ICINDEKILER", "İÇİNDEKILER", "İçindekiler", "CONTENTS"]


async def init_db():
    from db_pool import db_execute
    await db_execute(SCHEMA_SQL)
    logger.info("pdf_konu_index tablosu hazir")


def _extract_toc_from_text(text: str) -> list[tuple[str, int]]:
    """TOC text'inden (konu, sayfa) listesi çıkar."""
    entries = []
    for pat in TOC_PATTERNS:
        for m in pat.finditer(text):
            konu = m.group(1).strip()
            sayfa = int(m.group(2))
            # Kötü eşleşmeleri filtrele
            if len(konu) < 4 or len(konu) > 100:
                continue
            if sayfa < 1 or sayfa > 2000:
                continue
            # Sadece nokta/sayı olan isimleri atla
            if not re.search(r"[A-Za-zÇĞİÖŞÜçğıöşü]", konu):
                continue
            # Yaygın lobby text'lerini atla
            bad = ["İçindekiler", "Contents", "İÇİNDEKİLER", "Ünite Sayfa", "Üniteler"]
            if any(b in konu for b in bad):
                continue
            entries.append((konu, sayfa))
    # Dedup — aynı (konu, sayfa) ikilisi
    seen = set()
    out = []
    for konu, sayfa in entries:
        key = (konu.lower(), sayfa)
        if key in seen:
            continue
        seen.add(key)
        out.append((konu, sayfa))
    return out


def extract_toc_from_pdf(pdf_path: Path, toc_page_limit: int = 15) -> list[tuple[str, int]]:
    """PDF'in ilk N sayfasında İÇİNDEKİLER arar, konu-sayfa listesi döner."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.error("PyMuPDF yuklu degil (pip install PyMuPDF)")
        return []

    if not pdf_path.exists():
        logger.error(f"PDF bulunamadi: {pdf_path}")
        return []

    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        logger.error(f"PDF acilamadi: {e}")
        return []

    # Önce yerleşik TOC dene (PyMuPDF)
    try:
        builtin_toc = doc.get_toc()
        if builtin_toc and len(builtin_toc) >= 5:
            result = [(entry[1].strip(), int(entry[2])) for entry in builtin_toc
                      if len(entry) >= 3 and entry[1] and entry[2]]
            if len(result) >= 5:
                logger.info(f"  PyMuPDF builtin TOC: {len(result)} konu")
                doc.close()
                return result
    except Exception:
        pass

    # İçindekiler sayfasını metinden tara
    all_entries = []
    for i in range(min(toc_page_limit, len(doc))):
        try:
            text = doc[i].get_text("text")
            # İÇİNDEKİLER başlığı yakın mı?
            if any(hint in text for hint in TOC_PAGE_HINTS) or i < 3:
                entries = _extract_toc_from_text(text)
                if entries:
                    all_entries.extend(entries)
        except Exception:
            continue

    doc.close()
    # Dedup ve sort by sayfa
    unique = {}
    for konu, sayfa in all_entries:
        key = konu.lower().strip()
        if key not in unique:
            unique[key] = (konu, sayfa)
    result = sorted(unique.values(), key=lambda x: x[1])
    logger.info(f"  Metinden TOC cikarimi: {len(result)} konu")
    return result


def detect_ders_sinav(pdf_adi: str) -> tuple[str, str]:
    """PDF adından ders ve sınav türü tahmin et."""
    name = pdf_adi.lower()
    ders = ""
    sinav = ""
    # Ders
    for d_key, d_val in [
        ("matematik", "Matematik"), ("fizik", "Fizik"), ("kimya", "Kimya"),
        ("biyoloji", "Biyoloji"), ("turkce", "Turkce"), ("türkçe", "Turkce"),
        ("tarih", "Tarih"), ("cografya", "Cografya"), ("felsefe", "Felsefe"),
        ("edebiyat", "TDE"),
    ]:
        if d_key in name:
            ders = d_val
            break
    # Sınav
    if "tyt" in name:
        sinav = "TYT"
    elif "ayt" in name:
        sinav = "AYT"
    elif "ydt" in name or "ingilizce" in name:
        sinav = "YDT"
    return ders, sinav


async def index_pdf(pdf_path: Path) -> int:
    """Tek PDF'i index'le. Kaç konu eklendi dön."""
    from db_pool import db_execute

    pdf_adi = pdf_path.name
    ders, sinav = detect_ders_sinav(pdf_adi)

    entries = extract_toc_from_pdf(pdf_path)
    if not entries:
        logger.warning(f"  {pdf_adi}: TOC bulunamadi")
        return 0

    # sayfa_end hesabi — bir sonraki konunun sayfa_start'ı -1
    sorted_e = sorted(entries, key=lambda x: x[1])
    enriched = []
    for i, (konu, start) in enumerate(sorted_e):
        end = sorted_e[i + 1][1] - 1 if i + 1 < len(sorted_e) else start + 10
        enriched.append((konu, start, end))

    added = 0
    for konu, start, end in enriched:
        try:
            await db_execute(
                """INSERT INTO pdf_konu_index
                   (pdf_adi, ders, sinav_turu, konu, sayfa_start, sayfa_end, source)
                   VALUES ($1, $2, $3, $4, $5, $6, 'toc_auto')
                   ON CONFLICT (pdf_adi, konu, sayfa_start) DO NOTHING""",
                pdf_adi, ders, sinav, konu[:200], start, end,
            )
            added += 1
        except Exception as e:
            logger.debug(f"    Insert skip ({konu[:30]}): {e}")

    logger.info(f"  {pdf_adi}: {added} konu indekslendi (ders={ders or '?'} sinav={sinav or '?'})")
    return added


async def search_konu(konu: str, ders: str = "") -> list[dict]:
    """Konu arat — hangi PDF'in hangi sayfa aralığında."""
    from db_pool import db_fetch
    filters = ["LOWER(konu) ILIKE LOWER($1)"]
    params = [f"%{konu}%"]
    idx = 2
    if ders:
        filters.append(f"ders = ${idx}")
        params.append(ders)
        idx += 1
    where = " AND ".join(filters)
    rows = await db_fetch(
        f"""SELECT pdf_adi, ders, sinav_turu, konu, sayfa_start, sayfa_end
            FROM pdf_konu_index WHERE {where}
            ORDER BY
              CASE WHEN LOWER(konu) = LOWER($1) THEN 1 ELSE 2 END,
              sayfa_start ASC
            LIMIT 10""",
        *params,
    )
    return [dict(r) for r in rows]


async def index_all_pdfs(base_dirs: list[Path] = None) -> dict:
    """Tüm mevcut PDF'leri tara + index."""
    if base_dirs is None:
        base_dirs = [
            Path("kaynaklar/akademik"),
            Path("kaynaklar/pedagojik"),
            Path("ogm_materyal"),
        ]

    total_pdf = 0
    total_konu = 0
    for base in base_dirs:
        if not base.exists():
            logger.debug(f"  Dizin yok: {base}")
            continue
        for pdf in base.rglob("*.pdf"):
            total_pdf += 1
            try:
                added = await index_pdf(pdf)
                total_konu += added
            except Exception as e:
                logger.warning(f"  {pdf.name}: {e}")

    return {"pdf": total_pdf, "konu": total_konu}


# ─── CLI ──────────────────────────────────────────────────────────────────────
async def main():
    import argparse, sys, io, json
    parser = argparse.ArgumentParser()
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--pdf", type=str, help="Tek PDF indexle")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--search", type=str, help="Konu arat")
    parser.add_argument("--ders", type=str, default="")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv(override=True)

    if args.init:
        await init_db()
        print("OK")

    if args.pdf:
        pdf_path = Path(args.pdf)
        if not pdf_path.exists():
            # kaynaklar içinde ara
            for base in ["kaynaklar/akademik", "kaynaklar/pedagojik"]:
                candidate = Path(base) / args.pdf
                if candidate.exists():
                    pdf_path = candidate
                    break
        n = await index_pdf(pdf_path)
        print(f"{pdf_path.name}: {n} konu eklendi")

    if args.all:
        r = await index_all_pdfs()
        print(f"Toplam: {r['pdf']} PDF, {r['konu']} konu kaydi")

    if args.search:
        r = await search_konu(args.search, args.ders)
        print(f"Sonuc: {len(r)}")
        for x in r:
            print(f"  [{x['ders'] or '?'}/{x['sinav_turu'] or '?'}] {x['pdf_adi']} s.{x['sayfa_start']}-{x['sayfa_end']}: {x['konu']}")


if __name__ == "__main__":
    import io as _io, sys as _sys
    _sys.stdout = _io.TextIOWrapper(_sys.stdout.buffer, encoding="utf-8", errors="replace")
    asyncio.run(main())
