"""
FermatAI — MEB OGM Materyal Scraper
======================================
ogmmateryal.eba.gov.tr sitesinden YKS hazırlık materyallerini
otomatik indirir ve RAG'a import eder.

İçerik: Konu özetleri, soru bankaları, çıkmış sorular (PDF)
Yöntem: Playwright CDP + HTTP download + pdf_importer

Kullanım:
  python ogm_scraper.py                    # Tüm konu özetlerini indir + import
  python ogm_scraper.py --list             # Mevcut materyalleri listele
  python ogm_scraper.py --download-only    # Sadece indir, import etme
"""

import asyncio
import os
import sys
from pathlib import Path

import httpx
from loguru import logger

sys.path.insert(0, str(Path(__file__).parent))

BASE_URL = "https://ogmmateryal.eba.gov.tr"
DOWNLOAD_DIR = Path(__file__).parent.parent / "kaynaklar" / "ogm_materyal"

# Keşfedilen içerik haritası
OGM_CONTENT = {
    "konu_ozetleri": {
        "page_url": "/mebi-konu-ozetleri",
        "download_pattern": "/mebi-ozet-indir?id={id}",
        "items": {
            # TYT Konu Özetleri
            "TYT_Biyoloji": 176267,
            "TYT_Cografya": 176268,
            "TYT_Felsefe": 176269,
            "TYT_Fizik": 176270,
            "TYT_Kimya": 176271,
            "TYT_Matematik": 176272,
            "TYT_Tarih": 176273,
            "TYT_Turkce": 176274,
            # AYT Konu Özetleri
            "AYT_01": 176275,
            "AYT_02": 176276,
            "AYT_03": 176277,
            "AYT_04": 176278,
            "AYT_05": 176279,
            "AYT_06": 176280,
            "AYT_07": 176281,
            "AYT_08": 176282,
            "AYT_09": 176283,
            "AYT_10": 176284,
            "AYT_11": 176285,
        }
    },
    "cikmis_sorular": {
        "page_url": "/yks-cikmis-soru-kitaplari",
        "download_pattern": "/mebi-ozet-indir?id={id}",
        "items": {
            "YKS_Cikmis_01": 176293,
            "YKS_Cikmis_02": 176294,
            "YKS_Cikmis_03": 176295,
            "YKS_Cikmis_04": 176296,
            "YKS_Cikmis_05": 176297,
            "YKS_Cikmis_06": 176298,
            "YKS_Cikmis_07": 176299,
        }
    },
    "tarama_testleri": {
        "page_url": "/mebi-tarama-testi-kitaplari",
        "download_pattern": "/mebi-ozet-indir?id={id}",
        "items": {k: v for k, v in zip(
            [f"Tarama_{i:02d}" for i in range(1, 18)],
            range(176302, 176319)
        )}
    },
}


async def download_pdf(item_id: int, filename: str, category_dir: Path) -> Path | None:
    """OGM'den PDF indir."""
    url = f"{BASE_URL}/mebi-ozet-indir?id={item_id}"
    filepath = category_dir / f"{filename}.pdf"

    if filepath.exists() and filepath.stat().st_size > 10000:
        logger.info(f"  Zaten var: {filepath.name} ({filepath.stat().st_size/1024:.0f}KB)")
        return filepath

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=120) as client:
            r = await client.get(url)
            ct = r.headers.get("content-type", "")

            if r.status_code == 200 and (
                "pdf" in ct or len(r.content) > 50000
            ):
                filepath.write_bytes(r.content)
                logger.info(f"  Indirildi: {filepath.name} ({len(r.content)/1024:.0f}KB)")
                return filepath
            else:
                logger.warning(f"  Indirilemedi: {filename} status={r.status_code} ct={ct}")
                return None
    except Exception as e:
        logger.error(f"  Download hatasi {filename}: {e}")
        return None


async def download_all_konu_ozetleri() -> list[Path]:
    """Tüm TYT+AYT konu özetlerini indir."""
    category = OGM_CONTENT["konu_ozetleri"]
    category_dir = DOWNLOAD_DIR / "konu_ozetleri"
    category_dir.mkdir(parents=True, exist_ok=True)

    downloaded = []
    items = category["items"]

    logger.info(f"Konu Ozetleri indiriliyor: {len(items)} kitap")

    for name, item_id in items.items():
        path = await download_pdf(item_id, name, category_dir)
        if path:
            downloaded.append(path)
        await asyncio.sleep(1)  # Rate limit

    logger.info(f"Toplam: {len(downloaded)}/{len(items)} indirildi")
    return downloaded


async def import_to_rag(pdf_paths: list[Path]):
    """İndirilen PDF'leri RAG'a import et."""
    from pdf_importer import import_pdf

    total = 0
    for pdf in pdf_paths:
        name = pdf.stem
        # TYT_Matematik → sinav=TYT, ders=Matematik
        parts = name.split("_", 1)
        sinav_turu = parts[0] if parts else "TYT"
        ders = parts[1] if len(parts) > 1 else name

        logger.info(f"RAG import: {name} ({sinav_turu}/{ders})")
        count = await import_pdf(
            str(pdf),
            content_type="akademik",
            sinav_turu=sinav_turu,
            ders_override=ders,
        )
        total += count

    logger.info(f"RAG import tamamlandi: {total} chunk")
    return total


async def list_available():
    """Mevcut indirilen dosyaları listele."""
    print(f"\n📚 OGM Materyal Dosyaları:")
    print(f"   Klasör: {DOWNLOAD_DIR}")

    if not DOWNLOAD_DIR.exists():
        print("   Henüz indirilmemiş!")
        return

    total_files = 0
    total_size = 0
    for subdir in sorted(DOWNLOAD_DIR.iterdir()):
        if subdir.is_dir():
            files = list(subdir.glob("*.pdf"))
            size = sum(f.stat().st_size for f in files)
            total_files += len(files)
            total_size += size
            print(f"\n   📁 {subdir.name} ({len(files)} dosya, {size/1024/1024:.1f}MB)")
            for f in sorted(files):
                print(f"      {f.name} ({f.stat().st_size/1024:.0f}KB)")

    print(f"\n   Toplam: {total_files} dosya, {total_size/1024/1024:.1f}MB")


async def main():
    if "--list" in sys.argv:
        await list_available()
        return

    download_only = "--download-only" in sys.argv

    # 1. İndir
    logger.info("MEB OGM Materyal Scraper baslatildi")
    paths = await download_all_konu_ozetleri()

    if not paths:
        logger.warning("Hicbir dosya indirilemedi!")
        return

    # 2. RAG'a import (isteğe bağlı)
    if not download_only:
        logger.info("RAG import basliyor...")
        await import_to_rag(paths)
    else:
        logger.info("--download-only: RAG import atlandı")

    logger.info("Tamamlandi!")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
