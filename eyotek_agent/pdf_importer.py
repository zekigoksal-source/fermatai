"""
FermatAI — PDF Kaynak Import Pipeline
=======================================
PDF dosyalarını okur, chunk'lara böler, embedding yapar, pgvector'e kaydeder.
NotebookLM tarzı: kaynak at → sistem öğrensin → öğrencilere sunsun.

İki katman:
  1. Akademik: YKS soru bankaları, konu anlatım → öğrenciye ders/soru
  2. Pedagojik: Eğitim metodolojisi kitapları → bot davranış rehberi

Kullanım:
  python pdf_importer.py dosya.pdf                    # Tek dosya import
  python pdf_importer.py /path/to/klasor              # Klasördeki tüm PDF'ler
  python pdf_importer.py dosya.pdf --type pedagojik   # Pedagojik kaynak olarak
  python pdf_importer.py --stats                      # RAG istatistikleri

Klasör yapısı:
  FermatAI/kaynaklar/akademik/   → YKS soru bankaları, konu notları
  FermatAI/kaynaklar/pedagojik/  → Eğitim kitapları, koçluk rehberleri
"""

import asyncio
import os
import re
import sys
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
from loguru import logger

sys.path.insert(0, str(Path(__file__).parent))

# Kaynak klasörleri
KAYNAK_DIR = Path(__file__).parent.parent / "kaynaklar"
AKADEMIK_DIR = KAYNAK_DIR / "akademik"
PEDAGOJIK_DIR = KAYNAK_DIR / "pedagojik"

# Chunk ayarları
CHUNK_SIZE = 800       # Karakter — embedding için optimal
CHUNK_OVERLAP = 100    # Örtüşme — bağlam korunması
MIN_CHUNK_LEN = 50     # Çok kısa parçaları atla


def extract_text_from_pdf(pdf_path: str) -> list[dict]:
    """PDF'den sayfa bazlı metin çıkar."""
    pages = []
    try:
        doc = fitz.open(pdf_path)
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text("text")
            if text and len(text.strip()) > 20:
                pages.append({
                    "page": page_num + 1,
                    "text": text.strip(),
                })
        doc.close()
        logger.info(f"  PDF: {len(pages)} sayfa metin cikarildi ({pdf_path})")
    except Exception as e:
        logger.error(f"  PDF okuma hatasi: {e}")
    return pages


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE,
               overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Metni anlamlı parçalara böl."""
    # Önce paragraf bazlı böl
    paragraphs = re.split(r'\n{2,}', text)

    chunks = []
    current_chunk = ""

    for para in paragraphs:
        para = para.strip()
        if not para or len(para) < 10:
            continue

        # Paragraf chunk_size'dan küçükse birleştir
        if len(current_chunk) + len(para) < chunk_size:
            current_chunk += "\n\n" + para if current_chunk else para
        else:
            # Mevcut chunk'ı kaydet
            if len(current_chunk) >= MIN_CHUNK_LEN:
                chunks.append(current_chunk.strip())

            # Yeni chunk başlat (overlap ile)
            if overlap > 0 and current_chunk:
                # Son overlap karakteri koru
                tail = current_chunk[-overlap:] if len(current_chunk) > overlap else ""
                current_chunk = tail + "\n\n" + para
            else:
                current_chunk = para

    # Son chunk
    if len(current_chunk) >= MIN_CHUNK_LEN:
        chunks.append(current_chunk.strip())

    return chunks


def detect_subject_topic(text: str, filename: str) -> tuple[str, str]:
    """Metin ve dosya adından ders ve konu tahmin et."""
    text_lower = (text + " " + filename).lower()

    # Ders tespiti
    ders_map = {
        "matematik": ["matematik", "denklem", "fonksiyon", "türev", "integral",
                       "olasılık", "istatistik", "sayı", "geometri"],
        "fizik": ["fizik", "newton", "kuvvet", "hareket", "enerji", "dalga",
                  "elektrik", "manyetik", "optik", "termodinamik"],
        "kimya": ["kimya", "atom", "periyodik", "mol", "tepkime", "asit",
                  "baz", "organik", "inorganik", "element"],
        "biyoloji": ["biyoloji", "hücre", "genetik", "evrim", "ekoloji",
                     "solunum", "fotosentez", "sindirim", "dolaşım"],
        "türkçe": ["türkçe", "paragraf", "anlam", "dil bilgisi", "sözcük",
                   "cümle", "yazım", "noktalama", "edebiyat"],
        "tarih": ["tarih", "osmanlı", "atatürk", "inkılap", "savaş",
                  "cumhuriyet", "milli mücadele"],
        "coğrafya": ["coğrafya", "iklim", "nüfus", "harita", "yerşekli"],
        "geometri": ["geometri", "üçgen", "çember", "alan", "hacim",
                     "prizma", "piramit", "dörtgen"],
    }

    ders = "Genel"
    max_score = 0
    for d, keywords in ders_map.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > max_score:
            max_score = score
            ders = d.capitalize()

    # Konu tespiti — dosya adından veya ilk satırlardan
    first_lines = text[:200].split('\n')
    konu = first_lines[0][:60] if first_lines else filename

    return ders, konu


async def import_pdf(
    pdf_path: str,
    content_type: str = "akademik",
    sinav_turu: str = "TYT",
    ders_override: str = "",
    konu_override: str = "",
) -> int:
    """Tek PDF'i RAG'a import et."""
    from rag_engine import add_content, init_db
    await init_db()

    path = Path(pdf_path)
    if not path.exists():
        logger.error(f"Dosya bulunamadi: {pdf_path}")
        return 0

    logger.info(f"Import: {path.name} ({content_type})")

    # 1. PDF'den metin çıkar
    pages = extract_text_from_pdf(str(path))
    if not pages:
        logger.warning("  Metin cikarilmadi — bos PDF veya taranmis goruntu")
        return 0

    # 2. Tüm metni birleştir ve chunk'la
    full_text = "\n\n".join(p["text"] for p in pages)
    chunks = chunk_text(full_text)
    logger.info(f"  {len(chunks)} chunk olusturuldu")

    # 3. Her chunk'ı embedding'le ve kaydet
    added = 0
    for i, chunk in enumerate(chunks):
        # Ders/konu tespiti
        ders = ders_override or detect_subject_topic(chunk, path.stem)[0]
        konu = konu_override or f"{path.stem} (sayfa grubu {i+1})"

        # Hangi sayfadan geldiğini bul
        page_num = 0
        char_count = 0
        for p in pages:
            char_count += len(p["text"])
            if char_count >= i * CHUNK_SIZE:
                page_num = p["page"]
                break

        try:
            new_id = await add_content(
                sinav_turu=sinav_turu,
                ders=ders,
                konu=konu,
                alt_konu=f"Sayfa {page_num}",
                icerik_turu=content_type,
                baslik=f"{path.stem} — Bölüm {i+1}",
                icerik=chunk,
                kaynak=f"PDF: {path.name} (s.{page_num})",
                zorluk="orta",
                soru_sayisi=0,
            )
            added += 1
        except Exception as e:
            logger.warning(f"  Chunk {i+1} kayit hatasi: {e}")

    logger.info(f"  ✅ {added}/{len(chunks)} chunk kaydedildi")
    return added


async def import_directory(dir_path: str, content_type: str = "akademik") -> int:
    """Klasördeki tüm PDF'leri import et."""
    path = Path(dir_path)
    if not path.is_dir():
        logger.error(f"Klasor bulunamadi: {dir_path}")
        return 0

    pdf_files = list(path.glob("*.pdf")) + list(path.glob("**/*.pdf"))
    logger.info(f"Klasor: {path} — {len(pdf_files)} PDF bulundu")

    total = 0
    for pdf in pdf_files:
        count = await import_pdf(str(pdf), content_type)
        total += count

    return total


async def show_stats():
    """RAG istatistikleri."""
    from rag_engine import get_stats
    stats = await get_stats()
    print(f"\n📊 RAG İstatistikleri:")
    print(f"   Toplam kayıt: {stats['toplam']}")
    if stats.get('ders_dagilimi'):
        print(f"   Ders dağılımı:")
        for ders, cnt in stats['ders_dagilimi'].items():
            print(f"     {ders}: {cnt}")


async def main():
    if "--stats" in sys.argv:
        await show_stats()
        return

    if len(sys.argv) < 2:
        print("Kullanım:")
        print("  python pdf_importer.py dosya.pdf")
        print("  python pdf_importer.py /klasor/yolu")
        print("  python pdf_importer.py dosya.pdf --type pedagojik")
        print("  python pdf_importer.py --stats")
        return

    target = sys.argv[1]
    content_type = "pedagojik" if "--type" in sys.argv and "pedagojik" in sys.argv else "akademik"

    # Kaynak klasörlerini oluştur
    AKADEMIK_DIR.mkdir(parents=True, exist_ok=True)
    PEDAGOJIK_DIR.mkdir(parents=True, exist_ok=True)

    path = Path(target)
    if path.is_file() and path.suffix.lower() == ".pdf":
        count = await import_pdf(str(path), content_type)
        print(f"\n✅ {count} chunk import edildi")
    elif path.is_dir():
        count = await import_directory(str(path), content_type)
        print(f"\n✅ Toplam {count} chunk import edildi ({path})")
    else:
        print(f"❌ Geçersiz hedef: {target}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
