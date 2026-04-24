"""
Ders Konu Dağılım Raporu — 8 Yıllık Çıkmış Soru Analizi (Oturum 23)
====================================================================

Neo talimatı (23 Nisan 18:20):
  "Fizik dersinde TYT ve AYT olarak detaylı konu dağılım analizi, informatikler,
   son 8 yılın konu dağılımları, hangi sıklıkta ne sorulmuş, bu yıl tahminler.
   Öğretmen arşivleyecek, uzun ve görsel, grafiklerle kaliteli detaylı."

Veri kaynağı: fermat.rag_content — OGM Vision split kayıtları
(her satır: SORU XX | YYYY-AYT/TYT format içerir, konu alanı temiz)

Kullanım:
    from ders_konu_dagilimi import konu_dagilimi_raporu
    rapor = await konu_dagilimi_raporu(ders="Fizik", sinav_turu="AYT")
    # Dönen dict: {konu_dagilimi, yil_trendi, tahmin_2026, chart_data}

Tool olarak Claude çağırır → arşivlenebilir kaliteli rapor üretir.
"""
from __future__ import annotations
from datetime import datetime
from collections import defaultdict
import re

try:
    from loguru import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)


# Ders normalizasyonu (DB'de çeşitli yazılışlar)
_DERS_ALIAS = {
    "fizik": "Fizik",
    "matematik": "Matematik", "mat": "Matematik", "tyt mat": "Matematik", "ayt mat": "Matematik",
    "geometri": "Geometri",
    "kimya": "Kimya",
    "biyoloji": "Biyoloji", "biyo": "Biyoloji",
    "türkçe": "Turkce", "turkce": "Turkce",
    "edebiyat": "TDE", "tde": "TDE", "türk dili": "TDE",
    "tarih": "Tarih", "tarih-1": "Tarih", "tarih-2": "Tarih",
    "coğrafya": "Cografya", "cografya": "Cografya",
    "felsefe": "Felsefe",
    "din": "Din Kulturu", "din kültürü": "Din Kulturu",
}


def _normalize_ders(ders: str) -> str:
    if not ders:
        return ""
    return _DERS_ALIAS.get(ders.lower().strip(), ders)


# Yıl bazlı trend → 2026 tahmini
def _tahmin_2026(yillar: list[int], toplam: int) -> dict:
    """Son 8 yılın verisine göre 2026 gelme olasılığı heuristik.

    - Her yıl gelen konu → YÜKSEK (>= 6/8 yıl)
    - Düzenli gelen (her 2 yılda 1) → ORTA
    - Son 3 yıldır gelmiyor → DÜŞÜK (ama tekrar gelebilir)
    - Sadece eski yıllarda gelmiş → NOSTALJIK (muhtemelen gelmez)
    """
    if not yillar:
        return {"tahmin": "DÜŞÜK", "gerekce": "Hiç çıkmamış"}

    yillar_set = set(yillar)
    son_3_yil = {2023, 2024, 2025}
    orta_yillar = {2020, 2021, 2022, 2023, 2024, 2025}
    son_3_kapsama = len(yillar_set & son_3_yil)
    orta_kapsama = len(yillar_set & orta_yillar)
    hepsi_kapsama = len(yillar_set)

    # Kural 1: Son 3 yılda 2+ kez gelmiş → Yüksek
    if son_3_kapsama >= 2:
        return {
            "tahmin": "YÜKSEK",
            "gerekce": f"Son 3 yılın {son_3_kapsama}'inde çıktı — seri sürüyor",
            "skor": 85,
        }
    # Kural 2: Toplam 5+ kez gelmiş + son 5 yılda gelmiş
    if toplam >= 5 and max(yillar) >= 2021:
        return {
            "tahmin": "YÜKSEK",
            "gerekce": f"{toplam} kez çıkmış, güncel (son: {max(yillar)})",
            "skor": 75,
        }
    # Kural 3: Son 3 yılda gelmemiş + ortaaralık var
    if son_3_kapsama == 0 and orta_kapsama >= 2:
        return {
            "tahmin": "ORTA-YÜKSEK",
            "gerekce": f"3 yıldır yok, geri dönüş olasılığı (önceden {orta_kapsama} kez)",
            "skor": 60,
        }
    # Kural 4: Az gelmiş ama son 5 yılda
    if 2 <= toplam <= 4 and max(yillar) >= 2020:
        return {
            "tahmin": "ORTA",
            "gerekce": f"{toplam} kez çıkmış, düzenli değil",
            "skor": 50,
        }
    # Kural 5: Sadece eski yıllarda (2018-2019)
    if max(yillar) <= 2019:
        return {
            "tahmin": "DÜŞÜK",
            "gerekce": f"Son çıkma {max(yillar)} — nostaljik olabilir",
            "skor": 20,
        }
    return {
        "tahmin": "DÜŞÜK-ORTA",
        "gerekce": "Düzensiz pattern",
        "skor": 35,
    }


async def konu_dagilimi_raporu(
    ders: str = "Fizik",
    sinav_turu: str = "AYT",
    yil_bas: int = 2018,
    yil_bit: int = 2025,
) -> dict:
    """Ders + sınav türü bazlı 8 yıllık konu dağılımı + tahmin.

    Returns:
        {
          "ders": "Fizik",
          "sinav_turu": "AYT",
          "yil_araligi": "2018-2025",
          "toplam_soru": 62,
          "konu_dagilimi": [
              {"konu": "Elektrik", "toplam": 8, "yillar": [2018, 2020, 2022, ...],
               "yil_tekrari": {2018: 1, 2020: 1, ...},
               "tahmin_2026": {"tahmin": "YÜKSEK", "gerekce": "...", "skor": 85}},
              ...
          ],
          "yil_bazli_sayilar": {2018: 7, 2019: 8, ...},
          "chart_konu_agirlik": { ...chart JSON (yığılmış çubuk)... },
          "chart_yil_trend": { ...chart JSON (çizgi)... },
          "ozet": "Fizik AYT son 8 yılda 62 soru. En sık: Elektrik (8x), Kuvvet (7x)..."
        }
    """
    from db_pool import db_fetch

    ders_norm = _normalize_ders(ders)
    if not ders_norm:
        return {"error": "ders parametresi zorunlu"}

    sinav_turu_norm = (sinav_turu or "AYT").upper().strip()
    if sinav_turu_norm not in ("TYT", "AYT"):
        return {"error": f"sinav_turu TYT veya AYT olmalı (aldık: {sinav_turu})"}

    # OGM Vision split kayıtları sorgula — baslik'te "SORU XX | YYYY-AYT" formatı
    rows = await db_fetch("""
        SELECT konu, baslik, sinav_turu, kaynak
        FROM fermat.rag_content
        WHERE ders = $1
          AND kaynak LIKE '%OGM Vision%'
          AND kaynak LIKE '%split%'
          AND sinav_turu = $2
        ORDER BY konu
    """, ders_norm, sinav_turu_norm)

    if not rows:
        return {
            "ders": ders_norm,
            "sinav_turu": sinav_turu_norm,
            "toplam_soru": 0,
            "mesaj": f"{ders_norm} {sinav_turu_norm} için veri yok — OGM Vision import yapılmış mı?",
        }

    # Başlıktan yıl çıkar
    konu_yillar = defaultdict(list)  # konu → [2018, 2020, ...]
    yil_konular = defaultdict(list)  # 2018 → [konu1, konu2, ...]

    yil_pattern = re.compile(r'(\d{4})\s*-\s*(AYT|TYT)', re.IGNORECASE)

    for r in rows:
        m = yil_pattern.search(r.get("baslik") or "")
        if not m:
            continue
        yil = int(m.group(1))
        if yil < yil_bas or yil > yil_bit:
            continue
        konu = (r.get("konu") or "Genel").strip()
        # Generic konuları atla
        if konu.lower() in ("fizik", "kimya", "biyoloji", "matematik", "genel", "biyoloji - genel"):
            konu = f"{ders_norm} (genel)"
        konu_yillar[konu].append(yil)
        yil_konular[yil].append(konu)

    # Konu bazlı detay — en sık çıkandan az çıkana sırala
    konu_detay = []
    for konu, yillar in konu_yillar.items():
        yil_tekrari = defaultdict(int)
        for y in yillar:
            yil_tekrari[y] += 1
        tahmin = _tahmin_2026(list(set(yillar)), len(yillar))
        konu_detay.append({
            "konu": konu,
            "toplam": len(yillar),
            "yillar": sorted(set(yillar)),
            "yil_tekrari": dict(yil_tekrari),
            "tahmin_2026": tahmin,
        })
    konu_detay.sort(key=lambda x: (-x["toplam"], x["konu"]))

    # Yıl bazlı toplam
    yil_toplam = {}
    for y in range(yil_bas, yil_bit + 1):
        yil_toplam[y] = len(yil_konular.get(y, []))

    toplam_soru = sum(len(v) for v in konu_yillar.values())

    # Chart: Konu ağırlık — yığılmış çubuk (konu başına yıl yıl)
    chart_konu_agirlik = {
        "type": "bar",
        "title": f"{ders_norm} {sinav_turu_norm} — 8 Yıl Konu Ağırlık Dağılımı",
        "labels": [k["konu"][:35] for k in konu_detay[:12]],
        "datasets": [{
            "label": "Toplam Soru",
            "data": [k["toplam"] for k in konu_detay[:12]],
            "backgroundColor": ["#C76F3E", "#6B8E7F", "#B08968", "#5C6B8C", "#A66B9C",
                               "#6B9E8E", "#D4A574", "#8C7B6B", "#7F8FAF", "#B08985",
                               "#969B83", "#A09570"][:12],
        }],
    }

    # Chart: Yıl trend
    chart_yil_trend = {
        "type": "line",
        "title": f"{ders_norm} {sinav_turu_norm} — Yıllık Toplam Soru Sayısı",
        "labels": [str(y) for y in sorted(yil_toplam.keys())],
        "datasets": [{
            "label": "Toplam soru",
            "data": [yil_toplam[y] for y in sorted(yil_toplam.keys())],
            "borderColor": "#C76F3E",
            "backgroundColor": "rgba(199, 111, 62, 0.15)",
            "tension": 0.3,
            "fill": True,
        }],
    }

    # Özet metni (insan okuyabilir)
    en_sik_3 = konu_detay[:3]
    en_sik_str = ", ".join(f"{k['konu']} ({k['toplam']}x)" for k in en_sik_3)

    yuksek_tahmin = [k for k in konu_detay if k["tahmin_2026"]["skor"] >= 70]
    dusuk_tahmin = [k for k in konu_detay if k["tahmin_2026"]["skor"] <= 30]

    ozet_satirlari = [
        f"{ders_norm} {sinav_turu_norm} son 8 yıl ({yil_bas}-{yil_bit}): toplam {toplam_soru} soru, {len(konu_detay)} farklı konu",
        f"En sık sorulan: {en_sik_str}",
    ]
    if yuksek_tahmin:
        ozet_satirlari.append(
            f"2026'da yüksek olasılıkla gelecek ({len(yuksek_tahmin)} konu): " +
            ", ".join(k["konu"] for k in yuksek_tahmin[:5])
        )
    if dusuk_tahmin:
        ozet_satirlari.append(
            f"Bu yıl düşük olasılık ({len(dusuk_tahmin)} konu): " +
            ", ".join(k["konu"] for k in dusuk_tahmin[:3])
        )

    return {
        "ders": ders_norm,
        "sinav_turu": sinav_turu_norm,
        "yil_araligi": f"{yil_bas}-{yil_bit}",
        "toplam_soru": toplam_soru,
        "konu_sayisi": len(konu_detay),
        "konu_dagilimi": konu_detay[:15],  # ilk 15 konu (detay)
        "yil_bazli_sayilar": yil_toplam,
        "chart_konu_agirlik": chart_konu_agirlik,
        "chart_yil_trend": chart_yil_trend,
        "ozet": " | ".join(ozet_satirlari),
        "kullanim": (
            "Claude: Bu veriyi kullanarak öğretmene/rehberliğe DETAYLI rapor yaz. "
            "Her konu için: toplam frekans, son yıl, 2026 tahmin gerekçe. "
            "Grafikleri ```chart bloklarıyla mesaja ekle. Arşivlenebilir kaliteli."
        ),
    }


__all__ = ["konu_dagilimi_raporu"]
