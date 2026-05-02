"""
LGS Yeni Nesil Soru Bank Generator (Oturum 25.40n — Neo direktif)
==================================================================

Vakası: Vedat hoca 2 May 18:24 → "yeni nesil 6. sınıf matematik" istedi,
bot 20 KLASİK 1-adımlı formül sorusu üretti (akademik kalite 2/10).

Çözüm: MEB Maarif 2024 müfredatına göre 6/7/8. sınıf için tam yeni nesil
örnek bank — RAG'a yüklenir, bot bir sonraki "yeni nesil" talebinde
bu örneklerden çekip adapte eder.

Stratejik konum:
- Şu an 6. sınıf öğrencimiz YOK ama seneye 7-8. sınıf KESİN olacak
- 6'yı da dahil et — eğitsel boşluk kalmasın
- Ortaokul içeriği MEB Maarif (2024) + LGS ÖSYM standartlarında

Maliyet: Claude Sonnet ile ~$3-5 (kalite > maliyet — Vedat tarzı bir daha olmasın)
Üretim: ~95 konu × 1 paket (3-5 örnek) = 95 RAG kaydı

Kullanım:
  cd eyotek_agent
  /opt/fermatai/.venv/bin/python -X utf8 generate_lgs_yeni_nesil_bank.py [--dry-run] [--ders matematik] [--sinif 6]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
load_dotenv(override=True)

from loguru import logger

# Anthropic Claude
try:
    from anthropic import Anthropic
    _ANTHROPIC_OK = True
except ImportError:
    _ANTHROPIC_OK = False


# ═══════════════════════════════════════════════════════════════════════════════
# MEB MAARIF MÜFREDATI 2024 — 6/7/8. SINIF KONU HARİTASI
# ═══════════════════════════════════════════════════════════════════════════════

CURRICULUM = {
    "6_sinif": {
        "Matematik": [
            "Kümeler ve Küme İşlemleri",
            "Doğal Sayılarda İşlemler (Asal Çarpanlar, EBOB, EKOK)",
            "Tam Sayılar (Toplama, Çıkarma, Çarpma, Bölme)",
            "Kesirlerle İşlemler (Toplama, Çıkarma, Çarpma, Bölme)",
            "Ondalık Gösterim ve Ondalık İşlemler",
            "Yüzdeler",
            "Oran ve Orantı",
            "Cebirsel İfadeler",
            "Açılar (Komşu, Doğrusal, Dik, Bütünler, Tümler)",
            "Çokgenler (Üçgen, Dörtgen, Düzgün Çokgenler — iç ve dış açılar)",
            "Çember ve Daire (Çevre, Alan)",
            "Geometrik Cisimler (Prizma, Küre — yüzey alanı, hacim)",
            "Veri Analizi (Tablo, Grafik, Aritmetik Ortalama)",
            "Olasılık (Olası Durumlar, Basit Olayların Olasılığı)",
        ],
        "Fen Bilimleri": [
            "Hücre ve Yapısı (Bitki/Hayvan Hücresi, Mikroskop)",
            "Vücudumuzdaki Sistemler (Sindirim, Dolaşım, Solunum, Boşaltım)",
            "Kuvvet ve Hareket (Sabit Süratli Hareket, Sürtünme)",
            "Madde ve Isı (Erime/Donma/Kaynama, Isı-Sıcaklık Farkı)",
            "Ses ve Özellikleri (Yayılma, Yansıma, Soğurulma)",
            "Işık ve Yansıma (Düzlem Ayna, Gölge Oluşumu)",
            "Elektriğin İletimi (Elektrik Devresi, İletken/Yalıtkan)",
            "Bitki ve Hayvanlarda Üreme, Büyüme ve Gelişme",
        ],
        "Türkçe": [
            "Sözcük Türleri (İsim, Sıfat, Zamir)",
            "Cümlede Anlam ve Anlatım Bozuklukları",
            "Paragrafta Yapı ve Anlam",
            "Yazım Kuralları ve Noktalama",
            "Metin Türleri (Bilgilendirici, Anlatımcı, Öyküleyici)",
        ],
        "Sosyal Bilgiler": [
            "Birey ve Toplum (Sosyal Roller, Hak ve Sorumluluklar)",
            "Kültür ve Miras (Tarih Öncesi Çağlar, İlk Türk Devletleri)",
            "İnsanlar, Yerler ve Çevreler (Türkiye'nin İklimi, Coğrafi Konumu)",
            "Etkin Vatandaşlık ve Yönetim (Demokratik Yaşam, T.B.M.M.)",
            "Üretim, Dağıtım ve Tüketim (Ekonomi, Türkiye'nin Geçim Kaynakları)",
        ],
        "İngilizce": [
            "Daily Routines and Habits",
            "Holidays and Travel",
            "Food and Healthy Eating",
            "Weather and Seasons",
        ],
    },
    "7_sinif": {
        "Matematik": [
            "Tam Sayılarla Çarpma ve Bölme İşlemleri",
            "Rasyonel Sayılar ve İşlemleri",
            "Cebirsel İfadeler ve Eşitlik (1. Dereceden Bir Bilinmeyenli Denklemler)",
            "Oran-Orantı (Doğru/Ters Orantı, Yüzde, Faiz)",
            "Doğrular ve Açılar (Yöndeş, İç/Dış Ters)",
            "Çokgenler (Kongrüans, Benzerlik, İç Açı, Dış Açı)",
            "Çember (Yay, Kiriş, Teğet, Çevre, Alan)",
            "Geometrik Cisimler (Dik Prizma, Dik Piramit, Koni — yüzey alanı/hacim)",
            "Dönüşüm Geometrisi (Yansıma, Öteleme)",
            "Veri Analizi (Aritmetik Ortalama, Ortanca, Tepe Değer)",
            "Basit Olayların Olasılığı",
        ],
        "Fen Bilimleri": [
            "Güneş Sistemi ve Ötesi (Gezegenler, Galaksiler)",
            "Hücre ve Bölünmeler (Mitoz, Mayoz)",
            "Kuvvet ve Enerji (İş, Güç, Kinetik/Potansiyel Enerji)",
            "Saf Madde ve Karışımlar (Element, Bileşik, Ayırma Yöntemleri)",
            "Işığın Madde ile Etkileşimi (Mercekler, Aynalar)",
            "Canlılarda Üreme, Büyüme ve Gelişme",
            "İnsan ve Çevre (Ekosistem, Madde Döngüsü)",
            "Elektrik Devreleri (Seri/Paralel, Direnç, Akım)",
        ],
        "Türkçe": [
            "Sözcük Türleri (Fiil, Zarf, Edat, Bağlaç, Ünlem)",
            "Cümlenin Ögeleri (Yüklem, Özne, Nesne, Tümleç)",
            "Anlatım Bozuklukları",
            "Metin İnceleme (Şiir, Hikaye, Anı, Deneme)",
            "Yazım ve Noktalama (Birleşik Sözcükler, Tırnak)",
        ],
        "Sosyal Bilgiler": [
            "İletişim ve İnsan İlişkileri (Medya, Sorumlu Vatandaşlık)",
            "Türk Tarihinde Yolculuk (Anadolu Selçuklu, Beylikler, Osmanlı)",
            "Türkiye'de Nüfus (Yerleşme, Göç)",
            "Türk-İslam Medeniyetinin Doğuşu",
            "Üretim, Dağıtım, Tüketim ve Türkiye'nin Ekonomik Gelişimi",
        ],
        "İngilizce": [
            "Appearances and Personality",
            "Biographies of Famous People",
            "Sports and Healthy Lifestyle",
            "Environmental Awareness",
        ],
    },
    "8_sinif_lgs": {
        "Matematik": [
            "Çarpanlar ve Katlar (Asal Çarpan, EBOB-EKOK Uygulamaları)",
            "Üslü İfadeler (Çarpma, Bölme, Tabanı/Üssü Eşit, 10'un Kuvvetleri)",
            "Köklü Sayılar (Kareli Sayılar, Köklü İfadelerde Toplama/Çıkarma)",
            "Veri Analizi (Sütun, Çizgi, Daire Grafiği — Karşılaştırma)",
            "Olasılık (Bağımlı/Bağımsız Olaylar, Bileşik Olaylar)",
            "Cebirsel İfadeler (Çarpma, Özdeşlikler — kare, iki kare farkı)",
            "Doğrusal Denklemler (Eğim, y=ax+b, Grafik)",
            "Eşitsizlikler (Birinci Dereceden Bir Bilinmeyenli)",
            "Üçgenler (Kenar Bağıntısı, Pisagor, Dik Üçgen Özellikleri)",
            "Dönüşüm Geometrisi (Yansıma, Öteleme, Dönme)",
            "Geometrik Cisimler (Dik Prizma, Dik Piramit, Dik Dairesel Silindir — Yüzey Alanı/Hacim)",
        ],
        "Fen Bilimleri": [
            "Mevsimler ve İklim (Eksenel Eğiklik, İklim-Hava Olayları Farkı)",
            "DNA ve Genetik Kod (Mendel Yasaları, Mutasyon, Modifikasyon, Adaptasyon)",
            "Basınç (Sıvı/Gaz/Katı Basıncı — Günlük Hayat Uygulamaları)",
            "Madde ve Endüstri (Periyodik Sistem, Asit-Baz, Tepkimeler)",
            "Basit Makineler (Sabit/Hareketli Makara, Kaldıraç, Eğik Düzlem)",
            "Enerji Dönüşümleri ve Çevre Bilimi",
            "Elektrik Yükleri ve Elektrik Enerjisi (Akım, Gerilim, Direnç, Joule)",
            "Canlılar ve Enerji İlişkileri (Fotosentez, Solunum)",
        ],
        "Türkçe": [
            "Fiilimsi (İsim-Fiil, Sıfat-Fiil, Zarf-Fiil)",
            "Cümlenin Ögeleri ve Cümle Türleri",
            "Anlatım Bozuklukları",
            "Sözcük Anlamı ve Söz Sanatları",
            "Metin Türleri ve İnceleme (Roman, Hikaye, Şiir)",
        ],
        "T.C. İnkılap Tarihi": [
            "Bir Kahraman Doğuyor (Mustafa Kemal'in Hayatı, Eğitimi, Askerlik)",
            "Milli Uyanış (Mondros, İşgaller, Yararlı/Zararlı Cemiyetler, Mustafa Kemal'in Samsun'a Çıkışı)",
            "Ya İstiklal Ya Ölüm (Kongreler, Misak-ı Milli, Kurtuluş Savaşı Cepheleri)",
            "Çağdaş Türkiye Yolunda Adımlar (Saltanat ve Hilafetin Kaldırılması, İnkılaplar)",
            "Demokratikleşme Çabaları ve Dış Politika (Atatürk Dönemi)",
            "Atatürk İlkeleri (Cumhuriyetçilik, Milliyetçilik, Halkçılık, Devletçilik, Laiklik, İnkılapçılık)",
        ],
        "İngilizce": [
            "Friendship and Personal Qualities",
            "Teen Life and School Life",
            "In the Kitchen and Recipes",
            "Communication and Social Media",
            "Adventure and Tourism",
        ],
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# CLAUDE SONNET PROMPT — KALİTE GARANTİ
# ═══════════════════════════════════════════════════════════════════════════════

GENERATION_PROMPT = """Sen MEB Maarif 2024 müfredatı uzmanı bir akademik içerik üreticisisin. \
Konuya göre 4 adet **YENİ NESİL** örnek soru üreteceksin.

Sınıf: {sinif}
Ders: {ders}
Konu: {konu}

═══ YENI NESİL SORU 7 ZORUNLU KRİTERİ ═══
1. **Bağlamlı:** Gerçek hayat senaryosu (Ahmet ailesiyle..., bir spor sahası..., bir tarif...)
2. **Çok adımlı:** 2-4 alt soru (a, b, c, d) veya birden fazla işlem
3. **Görsel ipucu:** Şekil/tablo/grafik referansı (metin olarak tanımla)
4. **Anlamlı/akıl yürütme:** En az bir alt soru "neden", "açıklayın", "doğru mu?" sentezi
5. **Disiplinler arası:** Mat+Fen, Mat+Coğrafya gibi köprü kur (mümkünse)
6. **Veri yorumu:** En az 1 soruda tablo/grafik veriyor olarak çık
7. **Açık uçlu sentez:** En az 1 soru tek doğru cevap dışında "yorum" ister

═══ ASLA ═══
✗ "X sayısının asal çarpanları" (1 adım, klasik)
✗ "Beşgenin iç açıları toplamı" (formül uygulama)
✗ Tek cümle, bağlamsız soru
✗ "Hesaplayın" tek başına emir → "düşününüz, açıklayınız" sentez

═══ ÇIKTI FORMATI (JSON) ═══
{{
  "ders": "{ders}",
  "konu": "{konu}",
  "sinif": "{sinif}",
  "kazanim": "MEB Maarif 2024 kazanım metni (2-3 cümle)",
  "ornekler": [
    {{
      "baslik": "Soru başlığı (örn: 'BAHCE PIKNIGINDE ORAN-ORANTI')",
      "soru_metni": "Tam soru metni — bağlam (2-4 cümle) + verilen bilgi + a/b/c alt sorular",
      "cevap_anahtari": "a) ... b) ... c) ... (her alt soru için adım adım çözüm)",
      "neden_yeni_nesil": "Bu sorunun yeni nesil olma sebebi (bağlam + sentez + ...)"
    }}
  ],
  "ogretmen_notlari": "Bu konuyu işlerken öğretmenin dikkat etmesi gerekenler (3-5 cümle)",
  "yaygin_hatalar": "Öğrencilerin yaptığı tipik hatalar (3-4 madde)"
}}

KRITIK: Sadece geçerli JSON döndür, kod bloğu yok, markdown yok.
3 örnek soru üret, hepsi 7 kriteri karşılasın. Türkçe yaz, akademik dil kullan.
Soru senaryoları çocuk/ortaokul yaşına UYGUN olsun (çok kompleks değil)."""


# ═══════════════════════════════════════════════════════════════════════════════
# ÜRETIM
# ═══════════════════════════════════════════════════════════════════════════════

async def generate_one_topic(client, sinif: str, ders: str, konu: str) -> Optional[dict]:
    """Tek bir konu için yeni nesil örnek paket üret."""
    prompt = GENERATION_PROMPT.format(
        sinif=sinif.replace("_sinif", ". Sınıf").replace("_lgs", " (LGS)"),
        ders=ders,
        konu=konu,
    )

    try:
        # Sync Anthropic SDK — async wrap + STREAMING (timeout problemi cozumu)
        # Mevcut sistemin model adi env'den (FERMAT_MODEL, default sonnet-4-6)
        _model = os.getenv("FERMAT_MODEL", "claude-sonnet-4-6")
        def _do_stream():
            chunks = []
            with client.messages.stream(
                model=_model,
                max_tokens=4000,  # 3 ornek paket + ogretmen notlari yeterli
                temperature=0.5,
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                for text in stream.text_stream:
                    chunks.append(text)
            return "".join(chunks)
        text = (await asyncio.to_thread(_do_stream)).strip()

        # Markdown JSON kod bloğu varsa temizle
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(l for l in lines if not l.startswith("```")).strip()
            if text.startswith("json"):
                text = text[4:].strip()

        parsed = json.loads(text)
        return parsed
    except json.JSONDecodeError as e:
        logger.warning(f"  [GEN] JSON parse fail: {e} (text head: {text[:150]})")
        return None
    except Exception as e:
        logger.warning(f"  [GEN] Hata: {e}")
        return None


def _build_rag_content(parsed: dict, sinif: str, ders: str, konu: str) -> str:
    """parsed JSON'i RAG'a yazmak icin tek string halinde formatla."""
    ornekler_text = ""
    for i, o in enumerate(parsed.get("ornekler", []), 1):
        ornekler_text += f"\n\n## Örnek {i}: {o.get('baslik', '')}\n"
        ornekler_text += f"\n{o.get('soru_metni', '')}\n"
        ornekler_text += f"\n**Cevap Anahtarı:**\n{o.get('cevap_anahtari', '')}\n"
        ornekler_text += f"\n**Neden Yeni Nesil:** {o.get('neden_yeni_nesil', '')}\n"

    return f"""# {sinif} — {ders} — {konu}

## MEB Maarif 2024 Kazanım
{parsed.get('kazanim', '')}

## Yeni Nesil Örnek Sorular (4 adet)
{ornekler_text}

## Öğretmen Notları
{parsed.get('ogretmen_notlari', '')}

## Yaygın Hatalar (öğrenciler en sık burada takılır)
{parsed.get('yaygin_hatalar', '')}
"""


async def insert_to_rag(parsed: dict, sinif: str, ders: str, konu: str) -> bool:
    """Üretilen paketi rag_content'e ekle (embedding ile)."""
    from db_pool import get_pool

    sinav_turu_map = {
        "6_sinif": "LGS_HAZIRLIK_6",
        "7_sinif": "LGS_HAZIRLIK_7",
        "8_sinif_lgs": "LGS",
    }
    sinav_turu = sinav_turu_map.get(sinif, "LGS")

    icerik = _build_rag_content(parsed, sinif, ders, konu)
    baslik = f"{sinif.replace('_sinif', '. Sınıf').replace('_lgs', ' (LGS)')} — {ders} — {konu} (Yeni Nesil Örnek Paket)"

    # Embedding üret (rag_engine.embed_text sync — to_thread ile wrap)
    try:
        from rag_engine import embed_text
        emb = await asyncio.to_thread(embed_text, icerik[:3000])
        if not emb or len(emb) < 100:
            logger.warning(f"  [RAG] embedding fail (None or empty)")
            return False
    except Exception as e:
        logger.warning(f"  [RAG] embedding hata: {e}")
        return False

    # Anahtar kelimeler
    keywords = [
        sinif.replace("_sinif", ". sınıf").replace("_lgs", " LGS"),
        ders.lower(),
        konu.lower()[:50],
        "yeni nesil",
        "Maarif 2024",
        "örnek soru",
    ]

    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                """
                INSERT INTO rag_content
                  (sinav_turu, ders, konu, alt_konu, icerik_turu, baslik, icerik,
                   kaynak, zorluk, soru_sayisi, anahtar_kelimeler, embedding, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, NOW(), NOW())
                """,
                sinav_turu, ders, konu,
                None,  # alt_konu
                "yeni_nesil_ornek_paket",
                baslik, icerik,
                "MEB Maarif 2024 — Claude Sonnet üretim",
                "orta",
                len(parsed.get("ornekler", [])),
                keywords,
                str(emb),  # pgvector formatı: '[0.1, 0.2, ...]'
            )
            return True
        except Exception as e:
            logger.warning(f"  [RAG] INSERT hata: {e}")
            return False


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Üretim yap ama DB'ye yazma")
    parser.add_argument("--sinif", choices=["6_sinif", "7_sinif", "8_sinif_lgs", "all"],
                       default="all", help="Hangi sınıf (default: all)")
    parser.add_argument("--ders", default=None, help="Tek ders (örn: Matematik)")
    parser.add_argument("--max-konu", type=int, default=None, help="Konu sınırı (test için)")
    args = parser.parse_args()

    if not _ANTHROPIC_OK:
        print("[!] anthropic SDK kurulu degil.")
        sys.exit(1)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("[!] ANTHROPIC_API_KEY .env'de yok.")
        sys.exit(1)

    client = Anthropic(api_key=api_key, max_retries=3, timeout=90.0)

    # Hedef konu listesi
    targets = []
    classes = list(CURRICULUM.keys()) if args.sinif == "all" else [args.sinif]
    for sinif_key in classes:
        for ders_name, konular in CURRICULUM[sinif_key].items():
            if args.ders and args.ders.lower() not in ders_name.lower():
                continue
            for konu in konular:
                targets.append((sinif_key, ders_name, konu))

    if args.max_konu:
        targets = targets[:args.max_konu]

    print(f"[*] Toplam hedef konu: {len(targets)}")
    print(f"[*] Tahmini maliyet: ~${len(targets) * 0.04:.2f} (Claude Sonnet, ~4K token/konu)")
    print(f"[*] Dry-run: {args.dry_run}\n")

    success = 0
    failed = 0
    skipped_existing = 0

    # Mevcut RAG'da bu konu/sinif var mı kontrol — duplicate atla
    if not args.dry_run:
        from db_pool import db_fetch
        existing = await db_fetch(
            """SELECT sinav_turu, ders, konu FROM rag_content
               WHERE icerik_turu='yeni_nesil_ornek_paket'"""
        )
        existing_set = {(r['sinav_turu'], r['ders'], r['konu']) for r in existing}
    else:
        existing_set = set()

    sinav_turu_map = {
        "6_sinif": "LGS_HAZIRLIK_6",
        "7_sinif": "LGS_HAZIRLIK_7",
        "8_sinif_lgs": "LGS",
    }

    # Duplicate filtre
    todo = []
    for sinif, ders, konu in targets:
        st = sinav_turu_map.get(sinif, "LGS")
        if (st, ders, konu) in existing_set:
            skipped_existing += 1
            continue
        todo.append((sinif, ders, konu))
    print(f"[*] Skip (zaten var): {skipped_existing}, Yeni üretilecek: {len(todo)}\n")

    # ── PARALLEL üretim — 5 konu eş zamanlı (rate limit + maliyet dengesi)
    PARALLEL = 5

    async def process_one(idx: int, sinif: str, ders: str, konu: str) -> tuple[bool, str]:
        """Tek konu üret + insert. Returns (success, log_line)."""
        try:
            parsed = await generate_one_topic(client, sinif, ders, konu)
            if not parsed:
                return False, f"  [{idx}] FAIL gen | {sinif} | {ders} | {konu[:40]}"
            if args.dry_run:
                return True, f"  [{idx}] OK dry-run, {len(parsed.get('ornekler', []))} ornek | {sinif} | {ders} | {konu[:40]}"
            ok = await insert_to_rag(parsed, sinif, ders, konu)
            if ok:
                return True, f"  [{idx}] OK insert + embedding | {sinif} | {ders} | {konu[:40]}"
            return False, f"  [{idx}] FAIL insert | {sinif} | {ders} | {konu[:40]}"
        except Exception as e:
            return False, f"  [{idx}] EXCEPTION {e} | {sinif} | {ders} | {konu[:40]}"

    # Batch'lerde işle (her batch içi paralel)
    for batch_start in range(0, len(todo), PARALLEL):
        batch = todo[batch_start:batch_start + PARALLEL]
        tasks = [process_one(batch_start + i + 1, s, d, k) for i, (s, d, k) in enumerate(batch)]
        results = await asyncio.gather(*tasks)
        for ok, line in results:
            print(line, flush=True)
            if ok:
                success += 1
            else:
                failed += 1

    print(f"\n[+] Bitti: {success} basarili, {failed} fail, {skipped_existing} skip")
    if not args.dry_run and success > 0:
        print(f"[+] RAG'a {success} yeni paket eklendi (sinav_turu: LGS_HAZIRLIK_6/7/LGS)")


if __name__ == "__main__":
    asyncio.run(main())
