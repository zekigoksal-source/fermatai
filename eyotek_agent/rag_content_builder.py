"""
FermatAI — RAG İçerik Üretici
================================
DB'deki en sık yanlış yapılan konuları tespit eder,
Claude API ile YKS-odaklı konu anlatımı üretir,
pgvector'e embed edip kaydeder.

Kullanım:
  python rag_content_builder.py              # Tüm öncelikli konular
  python rag_content_builder.py 5            # İlk 5 konu (test)
  python rag_content_builder.py --stats      # Mevcut RAG istatistikleri
"""

import asyncio
import json
import os
import sys
from datetime import datetime

from anthropic import Anthropic
from dotenv import load_dotenv
from loguru import logger

load_dotenv(override=True)

from db_pool import get_pool as _get_pool

ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# TYT soru dağılımı
TYT_SORU_DAGILIMI = {
    "Türkçe": 40, "Matematik": 30, "Geometri": 10,
    "Fizik": 7, "Kimya": 7, "Biyoloji": 6,
    "Tarih": 5, "Coğrafya": 5, "Felsefe": 5, "Din Kültürü": 5,
}

CONTENT_PROMPT = """Sen YKS'ye hazırlanan öğrencilere konu anlatan bir eğitimcisin.

Aşağıdaki konu için YKS'ye yönelik kısa ve etkili bir anlatım yaz.

📚 DERS: {ders}
📝 KONU: {konu}
🎯 SINAV: {sinav_turu}
📊 TYT'de bu dersten {soru_sayisi} soru çıkıyor
⚠️ {ogrenci_sayisi} öğrencimizin %{hata_ort:.0f}'ı bu konuda hata yapıyor

FORMAT (WhatsApp markdown):
1. *Konu Özeti* — 3-5 cümle ile konuyu açıkla (basit, anlaşılır)
2. *Temel Kurallar/Formüller* — madde madde, en önemli 3-5 kural
3. *Soru Tipleri* — YKS'de bu konudan nasıl sorular çıkıyor (2-3 tip)
4. *Dikkat Edilmesi Gerekenler* — Sık yapılan hatalar, tuzaklar
5. *Çalışma Yöntemi* — Bu konuyu çalışırken ne yapmalı (pratik adımlar)

KURALLAR:
- Türkçe yaz, akademik ama anlaşılır dil
- WhatsApp'ta okunacak — *bold*, _italik_ kullan ama ### KULLANMA
- Toplam 400-600 kelime, fazla uzatma
- Formülleri düz metin olarak yaz (LaTeX yok)
- Gerçek hayat örnekleri ver
- "Biliyor muydun?" ile dikkat çek
- Motivasyonel bir kapanış cümlesi ekle
"""


async def get_priority_topics(limit: int = 35, ders_filter: list[str] | None = None) -> list[dict]:
    """DB'den en sık yanlış yapılan konuları getir.

    22.1n-K3: ders_filter=["Biyoloji","Geometri"] → sadece bu dersler.
    """
    _ders_filter = ders_filter if ders_filter else None
    pool = await _get_pool()
    async with pool.acquire() as conn:
        topics = await conn.fetch("""
            SELECT ders, konu,
                   COUNT(DISTINCT soz_no) as ogrenci_sayisi,
                   AVG(sinav_hata_yuzdesi) as ort_hata,
                   SUM(sinav_hata_sayisi) as toplam_hata
            FROM student_topic_tracker
            WHERE sinav_hata_yuzdesi > 30
            AND konu NOT LIKE 'Ortalama%'
            AND konu NOT LIKE 'TYT%'
            AND konu NOT LIKE 'AYT%'
            """ + ("AND ders = ANY($2)" if _ders_filter else "") + """
            GROUP BY ders, konu
            HAVING COUNT(DISTINCT soz_no) >= 3
            ORDER BY COUNT(DISTINCT soz_no) DESC, AVG(sinav_hata_yuzdesi) DESC
            LIMIT $1
        """, limit, *([_ders_filter] if _ders_filter else []))

        # Zaten RAG'da olanları filtrele
        existing = await conn.fetch("SELECT ders, konu FROM rag_content")
        existing_set = {(r['ders'], r['konu']) for r in existing}

    result = []
    for t in topics:
        if (t['ders'], t['konu']) not in existing_set:
            result.append({
                "ders": t['ders'],
                "konu": t['konu'],
                "ogrenci_sayisi": t['ogrenci_sayisi'],
                "hata_ort": float(t['ort_hata'] or 0),
                "toplam_hata": t['toplam_hata'] or 0,
            })

    return result


def generate_content(ders: str, konu: str, sinav_turu: str,
                     soru_sayisi: int, ogrenci_sayisi: int, hata_ort: float) -> str:
    """Claude API ile konu anlatımı üret (daha pahalı, yüksek kalite)."""
    client = Anthropic(api_key=ANTHROPIC_KEY)

    prompt = CONTENT_PROMPT.format(
        ders=ders, konu=konu, sinav_turu=sinav_turu,
        soru_sayisi=soru_sayisi, ogrenci_sayisi=ogrenci_sayisi,
        hata_ort=hata_ort
    )

    response = client.messages.create(
        # 25.58-C: claude-sonnet-4-20250514 EOL 15 Haz 2026 — env-driven güncel model
        model=os.getenv("FERMAT_MODEL", "claude-sonnet-4-6"),
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )

    return response.content[0].text


async def generate_content_groq(ders: str, konu: str, sinav_turu: str,
                                soru_sayisi: int, ogrenci_sayisi: int,
                                hata_ort: float) -> str:
    """Groq 70B ile konu anlatimi uret (Oturum 24: ~$0.003/konu, Claude'un 1/7'si).

    Llama 3.3 70B Turkce'de Claude Sonnet'e yakin kalitede, ~1sn yanit.
    """
    from groq_handler import GroqClient
    client = GroqClient()

    prompt = CONTENT_PROMPT.format(
        ders=ders, konu=konu, sinav_turu=sinav_turu,
        soru_sayisi=soru_sayisi, ogrenci_sayisi=ogrenci_sayisi,
        hata_ort=hata_ort
    )

    result = await client.complete(
        messages=[{"role": "user", "content": prompt}],
        system="Sen YKS konu anlatimi uzmanisin. Akademik ama samimi bir tonla, WhatsApp formatina uygun, Turkce yazarsin. Sadece markdown *bold* ve _italik_ kullan; ### YASAK, kod blogu YASAK.",
        max_tokens=1500,
        temperature=0.4,
    )
    return result.get("text", "")


async def build_content(limit: int = 35, ders_filter: list[str] | None = None,
                        use_groq: bool = False):
    """Öncelikli konular için içerik üret ve RAG'a kaydet.

    use_groq=True -> Groq 70B (Oturum 24): ~$0.003/konu, 7x ucuz, 23x hizli.
    use_groq=False -> Claude Sonnet: referans kalite (aynı konuya hazır olanlar icin ya da az sayıda uretim).
    """
    from rag_engine import add_content, init_db

    await init_db()

    topics = await get_priority_topics(limit, ders_filter=ders_filter)
    logger.info(f"Üretilecek konu: {len(topics)} | Motor: {'Groq 70B' if use_groq else 'Claude Sonnet'}")

    if not topics:
        logger.info("Tüm öncelikli konular zaten RAG'da!")
        return

    total_added = 0
    total_cost = 0.0
    per_cost = 0.003 if use_groq else 0.02
    kaynak_label = (
        "Groq llama-3.3-70b (YKS odaklı üretim)"
        if use_groq else "Claude Sonnet (YKS odaklı üretim)"
    )

    for i, topic in enumerate(topics):
        ders = topic['ders']
        konu = topic['konu']
        ogrenci = topic['ogrenci_sayisi']
        hata = topic['hata_ort']

        # Sınav türü belirleme
        sinav_turu = "TYT"
        soru_sayisi = TYT_SORU_DAGILIMI.get(ders, 5)

        logger.info(f"[{i+1}/{len(topics)}] {ders} — {konu} ({ogrenci} öğr, %{hata:.0f} hata)")

        try:
            if use_groq:
                content = await generate_content_groq(
                    ders, konu, sinav_turu, soru_sayisi, ogrenci, hata)
            else:
                content = generate_content(
                    ders, konu, sinav_turu, soru_sayisi, ogrenci, hata)

            if not content or len(content.strip()) < 100:
                logger.warning(f"  [!] Icerik cok kisa/bos, atlaniyor")
                continue

            new_id = await add_content(
                sinav_turu=sinav_turu,
                ders=ders,
                konu=konu,
                icerik_turu="konu_anlatimi",
                baslik=f"{ders} — {konu}",
                icerik=content,
                kaynak=kaynak_label,
                zorluk="orta" if hata < 70 else "zor",
                soru_sayisi=soru_sayisi,
            )

            total_added += 1
            total_cost += per_cost
            logger.info(f"  OK kaydedildi (id={new_id})")

        except Exception as e:
            logger.error(f"  HATA: {e}")

        # Rate limit — Groq daha hizli, Claude'a gore daha kisa bekleme
        await asyncio.sleep(0.2 if use_groq else 0.5)

    logger.info(f"\n{'='*50}")
    logger.info(f"TAMAMLANDI: {total_added} konu üretildi, tahmini maliyet: ~${total_cost:.3f}")


async def show_stats():
    """Mevcut RAG istatistikleri."""
    from rag_engine import get_stats
    stats = await get_stats()
    print(f"\n📊 RAG İstatistikleri:")
    print(f"   Toplam kayıt: {stats['toplam']}")
    if stats.get('ders_dagilimi'):
        print(f"   Ders dağılımı:")
        for ders, cnt in stats['ders_dagilimi'].items():
            print(f"     {ders}: {cnt}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")

    if "--stats" in sys.argv:
        asyncio.run(show_stats())
    else:
        limit = 35
        ders_filter = None
        use_groq = "--groq" in sys.argv  # Oturum 24: hizli/ucuz motor
        # 22.1n-K3: --ders Biyoloji,Geometri
        for i, arg in enumerate(sys.argv[1:]):
            if arg.isdigit():
                limit = int(arg)
            elif arg == "--ders" and i + 2 <= len(sys.argv) - 1:
                ders_filter = [d.strip() for d in sys.argv[i + 2].split(",") if d.strip()]

        asyncio.run(build_content(limit, ders_filter=ders_filter, use_groq=use_groq))
