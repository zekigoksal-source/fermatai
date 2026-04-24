"""
FermatAI — OGM Vision İçerik Çıkarma
======================================
OGM Materyal'deki çıkmış soru kitaplarının sayfa görsellerini
Claude Vision API ile okur, soruları yapılandırılmış olarak çıkarır,
RAG'a kaydeder.

URL pattern: ogm-small-cdn.eba.gov.tr/ogm-test-images/{kitap_id}/pages/{n}.jpg

Kullanım:
  python ogm_vision_importer.py tyt              # TYT kitabını kaldığı yerden devam et
  python ogm_vision_importer.py ayt_ea           # AYT EA kitabını başlat/devam et
  python ogm_vision_importer.py all              # Tüm kitapları sırayla
  python ogm_vision_importer.py --stats          # İstatistik göster
  python ogm_vision_importer.py --fix            # Mevcut kayıtlarda sinav_turu düzelt
"""

import asyncio
import base64
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx
from anthropic import Anthropic
from dotenv import load_dotenv
from loguru import logger

load_dotenv(override=True)

sys.path.insert(0, str(Path(__file__).parent))

CDN_BASE = "https://ogm-small-cdn.eba.gov.tr/ogm-test-images"
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CACHE_DIR = Path("logs/ogm_vision_cache")

# ── Kitap Tanımları ──────────────────────────────────────────────
KITAPLAR = {
    "ayt_sayisal": {
        "id": "68b4eb6deb079be0e7709222",
        "sinav_turu": "AYT",
        "label": "AYT Sayısal (Mat, Fiz, Kim, Bio)",
        "start": 9,
        "end": 208,
    },
    "tyt": {
        "id": "68b4f2b4eb079be0e77092ba",
        "sinav_turu": "TYT",
        "label": "TYT (Türkçe, Mat, Fen, Sosyal)",
        "start": 9,
        "end": 367,
    },
    "ayt_ea": {
        "id": "68b1eedc7061abc463473e6b",
        "sinav_turu": "AYT",
        "label": "AYT EA (TDE, Tarih, Coğ, Mat)",
        "start": 9,
        "end": 300,
    },
    # ayt_sozel, tyt_din, ayt_sozel2 — ATLA (sözel öğrenci yok)
    # "ayt_sozel": {
    #     "id": "68b23238eb079be0e76eea27",
    #     "sinav_turu": "AYT",
    #     "label": "AYT Sözel (TDE, Tarih, Coğ, Felsefe, Sosyoloji)",
    #     "start": 9,
    #     "end": 300,
    # },
    # "tyt_din": {
    #     "id": "68d3a84fdbcaa9db10a16a1b",
    #     "sinav_turu": "TYT",
    #     "label": "TYT Din Kültürü",
    #     "start": 9,
    #     "end": 200,
    # },
    # "ayt_sozel2": {
    #     "id": "68d39ea3dbcaa9db10a1596a",
    #     "sinav_turu": "AYT",
    #     "label": "AYT Sözel-2 (Din Kültürü)",
    #     "start": 9,
    #     "end": 200,
    # },
}

# Gereksiz sayfalar — atla
SKIP_KEYWORDS = ["istiklal", "genclige hitabe", "isbn", "kapak", "milli egitim"]

VISION_PROMPT_SORU = """Bu bir YKS çıkmış soru sayfası. Her soruyu eksiksiz ve yüksek kalitede çıkar.

ÇIKARILACAK BİLGİLER:

1. Sayfanın üst kısmındaki DERS adı (Matematik/Fizik/Kimya/Biyoloji)
2. Sayfanın üst kısmındaki KONU başlığı (varsa, yeşil/renkli banner'da yazar)
3. Her soru için:
   a) Soru numarası (sayfadaki numara)
   b) Sınav yılı ve türü (sağ alt köşede yazar, ör: 2022-AYT, 2019-TYT)
   c) Soru metnini TAMAMEN ve EKSIKSIZ yaz — hiçbir cümleyi atlama
   d) Tüm şıkları yaz: A) ... B) ... C) ... D) ... E) ...
   e) Şekil/grafik/tablo varsa DETAYLI tarif et:
      - Grafik: eksenlerin adları, değerler, eğrinin şekli
      - Geometri: şeklin türü, açılar, kenar uzunlukları, işaretlemeler
      - Tablo: satır ve sütun başlıkları, hücre değerleri
      - Devre/şema: bileşenler ve bağlantılar
   f) Formülleri düz metin olarak yaz (LaTeX kullanma):
      - Kesirler: a/b şeklinde
      - Üs: x^2, x^n şeklinde
      - Karekök: kök(x) şeklinde
      - İntegral: integral(f(x)dx, a, b) şeklinde

FORMAT:
---
DERS: [ders adı]
KONU: [konu başlığı]

SORU [numara] | [yıl]-[sınav türü]
[soru metni tam olarak]
[varsa görsel açıklaması: ŞEKİL: ...]
A) [şık] B) [şık] C) [şık] D) [şık] E) [şık]
---

KURALLAR:
- Türkçe yaz
- Hiçbir soruyu ATLAMA — sayfadaki TÜM soruları çıkar
- Soru metnini kısaltma, tam yaz
- Şekil açıklamasını detaylı yaz — öğrenci şekli görmeden soruyu anlayabilmeli
- Sayfa numarası, logo, QR kod, footer bilgisi YAZMA
- Sayfa kapak/İstiklal Marşı/ISBN ise sadece "GEREKSIZ_SAYFA" yaz
- Cevap anahtarı sayfasıysa tüm cevapları yaz: CEVAP_ANAHTARI formatında"""


def download_page(kitap_id: str, page_num: int) -> bytes | None:
    """CDN'den sayfa görselini indir (cache ile)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{kitap_id}_p{page_num}.jpg"

    if cache_path.exists():
        return cache_path.read_bytes()

    url = f"{CDN_BASE}/{kitap_id}/pages/{page_num}.jpg"
    try:
        r = httpx.get(url, timeout=15)
        if r.status_code == 200:
            cache_path.write_bytes(r.content)
            return r.content
        elif r.status_code == 404:
            logger.info(f"  Sayfa {page_num}: 404 — kitap sonu")
            return None
    except Exception as e:
        logger.warning(f"İndirme hatası sayfa {page_num}: {e}")
    return None


def read_page_with_vision(image_data: bytes, prompt: str, max_retries: int = 3) -> str:
    """Claude Vision ile sayfa görselini oku — retry destekli."""
    client = Anthropic(api_key=ANTHROPIC_KEY)
    img_b64 = base64.standard_b64encode(image_data).decode("utf-8")

    for attempt in range(1, max_retries + 1):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=3000,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64}
                        },
                        {"type": "text", "text": prompt}
                    ]
                }]
            )
            return response.content[0].text
        except Exception as e:
            err_str = str(e)
            if "500" in err_str or "overloaded" in err_str.lower() or "529" in err_str:
                wait = 10 * attempt  # 10s, 20s, 30s
                logger.warning(f"  API hatası (deneme {attempt}/{max_retries}): {err_str[:80]}")
                logger.info(f"  {wait}s bekleniyor...")
                time.sleep(wait)
            else:
                raise  # Farklı hata — retry yapma
    raise Exception(f"API {max_retries} denemede de başarısız")


def get_already_imported_pages(kitap_id: str) -> set:
    """Vision text cache'den zaten işlenmiş sayfaları bul."""
    vision_cache_dir = CACHE_DIR / "vision_text"
    if not vision_cache_dir.exists():
        return set()
    done = set()
    prefix = kitap_id[:12]
    for f in vision_cache_dir.glob(f"{prefix}_p*.txt"):
        try:
            page = int(f.stem.split("_p")[1])
            done.add(page)
        except (ValueError, IndexError):
            pass
    return done


async def get_db_imported_pages(kitap_id: str) -> set:
    """DB'den zaten import edilmiş sayfaları bul."""
    from db_pool import db_fetch
    rows = await db_fetch(
        "SELECT kaynak FROM rag_content WHERE kaynak LIKE $1",
        f"%{kitap_id[:12]}%"
    )
    pages = set()
    for r in rows:
        m = re.search(r's\.(\d+)', r['kaynak'])
        if m:
            pages.add(int(m.group(1)))
        m2 = re.search(r'sayfa (\d+)', r['kaynak'])
        if m2:
            pages.add(int(m2.group(1)))
    return pages


async def import_pages(
    kitap_id: str,
    start_page: int = 9,
    end_page: int = 300,
    sinav_turu: str = "TYT",
    label: str = "",
) -> int:
    """Sayfa aralığını Vision ile okuyup RAG'a kaydet — resume destekli."""
    from rag_engine import add_content, init_db
    await init_db()

    prompt = VISION_PROMPT_SORU
    total_added = 0
    total_cost = 0
    total_skipped = 0
    consecutive_404 = 0

    # Vision çıktı cache — tekrar Vision API çağırmamak için
    vision_cache_dir = CACHE_DIR / "vision_text"
    vision_cache_dir.mkdir(parents=True, exist_ok=True)

    # Zaten DB'de olan sayfalar
    db_pages = await get_db_imported_pages(kitap_id)
    cache_pages = get_already_imported_pages(kitap_id)

    logger.info(f"{'='*60}")
    logger.info(f"Kitap: {label or kitap_id[:12]}")
    logger.info(f"Sinav: {sinav_turu} | Sayfa: {start_page}-{end_page}")
    logger.info(f"DB'de mevcut: {len(db_pages)} sayfa | Cache: {len(cache_pages)} sayfa")
    logger.info(f"{'='*60}")

    for page_num in range(start_page, end_page + 1):
        # Zaten DB'de varsa atla
        if page_num in db_pages:
            continue

        # Vision cache kontrolü — daha önce çekildiyse tekrar çekme
        cache_file = vision_cache_dir / f"{kitap_id[:12]}_p{page_num}.txt"
        if cache_file.exists():
            text = cache_file.read_text(encoding="utf-8")
            if "GEREKSIZ_SAYFA" in text or len(text.strip()) < 50:
                total_skipped += 1
                continue
            logger.info(f"[{page_num}/{end_page}] Cache'den ({len(text)} char)")
        else:
            logger.info(f"[{page_num}/{end_page}] Vision API...")

            # 1. İndir
            img_data = download_page(kitap_id, page_num)
            if not img_data:
                consecutive_404 += 1
                if consecutive_404 >= 5:
                    logger.info(f"  5 ardışık 404 — kitap sonu (sayfa {page_num})")
                    break
                continue
            consecutive_404 = 0

            # 2. Vision ile oku (retry destekli)
            try:
                text = read_page_with_vision(img_data, prompt)
                total_cost += 0.02
                # Cache'e kaydet
                cache_file.write_text(text, encoding="utf-8")
            except Exception as e:
                logger.error(f"  Vision hatası sayfa {page_num}: {e}")
                # 500 sonrası 60s bekle, devam et
                await asyncio.sleep(60)
                continue

            # Rate limit — API'yi yormamak için
            await asyncio.sleep(1)

        # 3. Gereksiz sayfa kontrolü
        if "GEREKSIZ_SAYFA" in text or len(text.strip()) < 50:
            total_skipped += 1
            continue

        # 4. Ders/konu çıkar
        ders = _extract_ders(text)
        konu = _extract_konu(text)

        # 4b. EA akıllı tarama — Matematik/Geometri sayfaları AYT Sayısal'da zaten var
        if kitap_id == KITAPLAR.get("ayt_ea", {}).get("id", ""):
            if ders in ("Matematik", "Geometri"):
                # AYT Sayısal'da bu soru zaten var mı kontrol et (soru numarasından)
                soru_nums = re.findall(r'SORU\s+(\d+)', text[:500])
                if soru_nums:
                    logger.info(f"  EA: {ders} sayfası — AYT Sayısal ile ortak, atlanıyor (s.{page_num})")
                    total_skipped += 1
                    continue

        # Soru sayısı tespiti
        soru_count = len(re.findall(r'SORU\s+\d+|^\d+\.', text, re.MULTILINE))
        if soru_count == 0:
            soru_count = text.count("-AYT") + text.count("-TYT")

        # 5. RAG'a kaydet
        try:
            await add_content(
                sinav_turu=sinav_turu,
                ders=ders,
                konu=konu,
                alt_konu=f"Sayfa {page_num}",
                icerik_turu="cikmis_soru",
                baslik=f"{ders} — {konu} (YKS Çıkmış s.{page_num})",
                icerik=text,
                kaynak=f"OGM Vision: {kitap_id[:12]} s.{page_num}",
                zorluk="orta",
                soru_sayisi=soru_count,
            )
            total_added += 1
            db_pages.add(page_num)
            logger.info(f"  + {ders}/{konu} — {soru_count} soru ({len(text)} char)")
        except Exception as e:
            logger.error(f"  RAG kayıt hatası: {e}")

    logger.info(f"\n{'='*60}")
    logger.info(f"SONUC: +{total_added} sayfa, {total_skipped} atlanan, ~${total_cost:.2f}")
    logger.info(f"DB toplam ({kitap_id[:8]}): {len(db_pages)} sayfa")
    logger.info(f"{'='*60}")
    return total_added


def _extract_ders(text: str) -> str:
    """Vision çıktısından ders adını çıkar."""
    ders_match = re.search(r'DERS:\s*(.+)', text[:400])
    if ders_match:
        raw = ders_match.group(1).strip().strip("*").strip()
        # Normalize
        ders_map = {
            "matematik": "Matematik", "mat": "Matematik",
            "fizik": "Fizik", "kimya": "Kimya",
            "biyoloji": "Biyoloji", "bio": "Biyoloji",
            "geometri": "Geometri", "geo": "Geometri",
            "turkce": "Turkce", "turk dili": "Turkce",
            "edebiyat": "Edebiyat", "tde": "Edebiyat",
            "tarih": "Tarih", "cografya": "Cografya",
            "felsefe": "Felsefe", "sosyoloji": "Sosyoloji",
            "din kulturu": "Din Kulturu", "mantik": "Mantik",
        }
        raw_lower = raw.lower().replace("İ", "i").replace("ı", "i")
        for key, val in ders_map.items():
            if key in raw_lower:
                return val
        return raw

    # Fallback — metin içinden ders adı bul
    for d in ["Matematik", "Fizik", "Kimya", "Biyoloji", "Geometri",
              "Edebiyat", "Tarih", "Cografya", "Felsefe", "Turkce"]:
        if d.lower() in text.lower()[:400]:
            return d
    return "Genel"


def _extract_konu(text: str) -> str:
    """Vision çıktısından konu başlığını çıkar."""
    konu_match = re.search(r'KONU:\s*(.+)', text[:500])
    if konu_match:
        konu = konu_match.group(1).strip().strip("*").strip()
        if len(konu) > 3:
            return konu

    # Fallback — ilk satırlardan anlamlı başlık
    lines = text.split("\n")
    for line in lines[:10]:
        line_clean = line.strip().strip('"').strip("*").strip("#").strip()
        if 3 < len(line_clean) < 60:
            if not any(skip in line_clean.lower() for skip in
                       ["ders:", "konu:", "soru", "---", "format", "cevap"]):
                return line_clean

    return "Cikmis Soru"


async def fix_sinav_turu():
    """Mevcut kayıtlarda yanlış sinav_turu düzelt."""
    from db_pool import get_pool as _get_pool
    pool = await _get_pool()
    async with pool.acquire() as conn:
        for key, kitap in KITAPLAR.items():
            kid = kitap["id"][:12]
            fixed = await conn.execute(
                f"UPDATE rag_content SET sinav_turu=$1 WHERE kaynak LIKE $2 AND sinav_turu != $1",
                kitap["sinav_turu"], f"%{kid}%"
            )
            if "UPDATE 0" not in fixed:
                print(f"  {key}: {fixed}")

    print("Sinav turu duzeltme tamamlandi.")


async def show_stats():
    """Kitap bazlı istatistik göster."""
    from db_pool import get_pool as _get_pool
    pool = await _get_pool()
    conn = await pool.acquire()

    total = await conn.fetchval("SELECT COUNT(*) FROM rag_content")
    vision = await conn.fetchval("SELECT COUNT(*) FROM rag_content WHERE kaynak LIKE '%OGM Vision%'")
    print(f"\nRAG toplam: {total} | Vision: {vision}")
    print(f"{'='*60}")

    for key, kitap in KITAPLAR.items():
        kid = kitap["id"][:12]
        cnt = await conn.fetchval(
            "SELECT COUNT(*) FROM rag_content WHERE kaynak LIKE $1", f"%{kid}%"
        )
        status = "TAMAMLANDI" if cnt > 100 else f"{cnt} sayfa"
        print(f"  {kitap['label'][:35]:35s} | {cnt:4d} kayit | {status}")

    # Ders dağılımı
    rows = await conn.fetch("""
        SELECT ders, sinav_turu, COUNT(*) as cnt FROM rag_content
        WHERE kaynak LIKE '%OGM Vision%'
        GROUP BY ders, sinav_turu ORDER BY cnt DESC
    """)
    print(f"\nDers dagilimi (Vision):")
    for r in rows:
        print(f"  {r['sinav_turu']:4s} | {r['ders']:15s} | {r['cnt']} kayit")

    await conn.close()


async def main():
    if "--stats" in sys.argv:
        await show_stats()
        return

    if "--fix" in sys.argv:
        await fix_sinav_turu()
        return

    if len(sys.argv) < 2:
        print("Kullanim:")
        print("  python ogm_vision_importer.py tyt          # TYT kitabi")
        print("  python ogm_vision_importer.py ayt_ea       # AYT EA kitabi")
        print("  python ogm_vision_importer.py all          # Tum kitaplar sirayla")
        print("  python ogm_vision_importer.py --stats      # Istatistik")
        print("  python ogm_vision_importer.py --fix        # sinav_turu duzelt")
        print(f"\nMevcut kitaplar: {', '.join(KITAPLAR.keys())}")
        return

    target = sys.argv[1].lower()

    if target == "all":
        kitap_list = list(KITAPLAR.keys())
    elif target in KITAPLAR:
        kitap_list = [target]
    else:
        # Eski stil — kitap ID direkt
        kitap_list = []
        sinav = "AYT"
        for key, k in KITAPLAR.items():
            if target in k["id"]:
                kitap_list = [key]
                break
        if not kitap_list:
            print(f"Bilinmeyen kitap: {target}")
            print(f"Mevcut: {', '.join(KITAPLAR.keys())}")
            return

    for key in kitap_list:
        kitap = KITAPLAR[key]
        start = int(sys.argv[sys.argv.index("--start") + 1]) if "--start" in sys.argv else kitap["start"]
        end = int(sys.argv[sys.argv.index("--end") + 1]) if "--end" in sys.argv else kitap["end"]

        added = await import_pages(
            kitap_id=kitap["id"],
            start_page=start,
            end_page=end,
            sinav_turu=kitap["sinav_turu"],
            label=kitap["label"],
        )
        print(f"\n{kitap['label']}: +{added} yeni sayfa")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
