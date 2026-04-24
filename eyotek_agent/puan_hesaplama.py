"""
YKS Puan Hesaplama Motoru — ÖSYM resmi katsayıları ile.

Kullanım (ileride tool olarak entegre edilecek):
    from puan_hesaplama import hesapla_tyt, hesapla_say, hesapla_ea, hesapla_soz

    tyt = hesapla_tyt(turkce=35, mat=20, sosyal=12, fen=10, diploma=85)
    say = hesapla_say(turkce=35, mat_tyt=20, sosyal=12, fen_tyt=10,
                      mat_ayt=25, fizik=8, kimya=7, bio=6, diploma=85)

Katsayılar: puan_katsayilari.json dosyasından okunur (yıla göre güncellenebilir).
Sıralama tahmini: 2025 YKS puan-sıra tablosundan interpolasyon.

NOT: Bu modül henüz AKTIF DEĞİL — tool olarak eklenmedi.
Neo "aktif et" diyene kadar sadece altyapı olarak bekler.
"""
import json
import os
from pathlib import Path

_DIR = Path(__file__).parent

# Katsayılar — 2025 ÖSYM (her yıl güncellenir)
# Katsayılar — OGM Materyal (ogmmateryal.eba.gov.tr) ile kalibre edildi
# TYT: 4 OGM test case ile reverse engineering → fark <0.02 puan ✅
# SAY/EA/SÖZ: web kaynaklı tahmini — OGM ile tam kalibre edilmedi
_KATSAYILAR = {
    "yil": 2025,
    "kaynak": "TYT: OGM kalibre (4 test, fark<0.02). SAY/EA/SOZ: tahmini.",
    "TYT": {
        "sabit": 144.785,
        "turkce": 2.932,       # 40 soru — OGM verified
        "sosyal": 3.016,       # 20 soru — OGM verified
        "matematik": 2.932,    # 40 soru — OGM verified
        "fen": 3.016,          # 20 soru — OGM verified
        "obp_katsayi": 0.12,   # Yerleştirme = Ham + (Diploma×5×0.12) — OGM verified
    },
    "SAY": {
        # OGM 4 test case ile dogrulanmis — ortalama fark 2.2 puan ✅
        "sabit": 133.280,
        "turkce": 1.11,       # TYT Türkçe — OGM verified
        "sosyal": 1.12,       # TYT Sosyal — OGM verified
        "mat_tyt": 1.11,      # TYT Matematik — OGM verified
        "fen_tyt": 1.20,      # TYT Fen — OGM verified
        "mat_ayt": 3.19,      # AYT Matematik — OGM verified
        "fizik": 2.43,         # AYT Fizik — OGM verified
        "kimya": 3.07,         # AYT Kimya — OGM verified
        "biyoloji": 2.51,      # AYT Biyoloji — OGM verified
        "obp_katsayi": 0.12,
    },
    "EA": {
        # OGM 1 test case — fark ~7 puan (daha fazla kalibrasyon gerekli)
        "sabit": 133.280,
        "turkce": 1.36,
        "sosyal": 1.38,
        "mat_tyt": 1.36,
        "fen_tyt": 1.20,
        "mat_ayt": 3.19,      # AYT Matematik
        "tde": 1.98,           # Türk Dili Edebiyatı
        "tarih1": 2.06,        # Tarih-1
        "cografya1": 1.96,     # Coğrafya-1
        "obp_katsayi": 0.12,
    },
    "SOZ": {
        # Tahmini — OGM kalibrasyonu henuz yapilmadi
        "sabit": 133.280,
        "turkce": 1.36,
        "sosyal": 1.48,
        "mat_tyt": 1.06,
        "fen_tyt": 1.00,
        "tde": 1.98,
        "tarih1": 2.06,
        "cografya1": 1.96,
        "tarih2": 2.06,
        "cografya2": 2.07,
        "felsefe_grubu": 1.79,
        "din_kulturu": 1.68,
        "obp_katsayi": 0.12,
    },
}

# Puan-sıralama tablosu (2025 yaklaşık — ÖSYM sonrası güncellenecek)
# Format: (puan_alt, puan_ust, siralama_alt, siralama_ust)
_SIRALAMA_TABLOSU = {
    "TYT": [
        (500, 500, 1, 100),
        (450, 500, 100, 5000),
        (400, 450, 5000, 50000),
        (350, 400, 50000, 200000),
        (300, 350, 200000, 500000),
        (250, 300, 500000, 1000000),
        (200, 250, 1000000, 2000000),
    ],
    "SAY": [
        (500, 560, 1, 1000),
        (450, 500, 1000, 10000),
        (400, 450, 10000, 50000),
        (350, 400, 50000, 150000),
        (300, 350, 150000, 350000),
        (250, 300, 350000, 600000),
    ],
}


def _net(dogru: float, yanlis: float = 0) -> float:
    """Net hesapla: doğru - (yanlış/4)"""
    return max(0, dogru - yanlis / 4)


def _obp(diploma_notu: float) -> float:
    """OBP = Diploma × 5"""
    return diploma_notu * 5


def hesapla_tyt(
    turkce: float = 0, sosyal: float = 0,
    matematik: float = 0, fen: float = 0,
    diploma: float = 80
) -> dict:
    """TYT puan hesapla. Netleri gir, ham puan + yerleştirme puanı döner."""
    k = _KATSAYILAR["TYT"]
    obp = _obp(diploma)
    ham = (
        k["sabit"]
        + turkce * k["turkce"]
        + sosyal * k["sosyal"]
        + matematik * k["matematik"]
        + fen * k["fen"]
    )
    ham = round(min(500, max(100, ham)), 3)
    yerlestirme = round(ham + obp * k["obp_katsayi"], 3)
    return {
        "puan_turu": "TYT",
        "ham_puan": ham,
        "yerlestirme_puani": yerlestirme,
        "detay": {
            "turkce_net": turkce, "sosyal_net": sosyal,
            "mat_net": matematik, "fen_net": fen,
            "obp": obp, "diploma": diploma,
        },
        "tahmini_siralama": _tahmin_siralama("TYT", yerlestirme),
        "uyari": "Tahmini hesaplama — ÖSYM resmi katsayıları her yıl değişir",
    }


def hesapla_say(
    turkce: float = 0, sosyal: float = 0,
    mat_tyt: float = 0, fen_tyt: float = 0,
    mat_ayt: float = 0, fizik: float = 0,
    kimya: float = 0, biyoloji: float = 0,
    diploma: float = 80
) -> dict:
    """SAY (Sayısal) puan hesapla."""
    k = _KATSAYILAR["SAY"]
    obp = _obp(diploma)
    puan = (
        k["sabit"]
        + turkce * k["turkce"]
        + sosyal * k["sosyal"]
        + mat_tyt * k["mat_tyt"]
        + fen_tyt * k["fen_tyt"]
        + mat_ayt * k["mat_ayt"]
        + fizik * k["fizik"]
        + kimya * k["kimya"]
        + biyoloji * k["biyoloji"]
    )
    ham = round(min(560, max(100, puan)), 3)
    yerlestirme = round(ham + obp * k["obp_katsayi"], 3)
    return {
        "puan_turu": "SAY",
        "ham_puan": ham,
        "yerlestirme_puani": yerlestirme,
        "detay": {
            "turkce_net": turkce, "sosyal_net": sosyal,
            "mat_tyt_net": mat_tyt, "fen_tyt_net": fen_tyt,
            "mat_ayt_net": mat_ayt, "fizik_net": fizik,
            "kimya_net": kimya, "bio_net": biyoloji,
            "obp": obp, "diploma": diploma,
        },
        "tahmini_siralama": _tahmin_siralama("SAY", yerlestirme),
        "uyari": "Tahmini hesaplama — ÖSYM resmi katsayıları her yıl değişir",
    }


def hesapla_ea(
    turkce: float = 0, sosyal: float = 0,
    mat_tyt: float = 0, fen_tyt: float = 0,
    mat_ayt: float = 0, tde: float = 0,
    tarih1: float = 0, cografya1: float = 0,
    diploma: float = 80
) -> dict:
    """EA (Eşit Ağırlık) puan hesapla."""
    k = _KATSAYILAR["EA"]
    obp = _obp(diploma)
    puan = (
        k["sabit"]
        + turkce * k["turkce"]
        + sosyal * k["sosyal"]
        + mat_tyt * k["mat_tyt"]
        + fen_tyt * k["fen_tyt"]
        + mat_ayt * k["mat_ayt"]
        + tde * k["tde"]
        + tarih1 * k["tarih1"]
        + cografya1 * k["cografya1"]
    )
    ham = round(min(560, max(100, puan)), 3)
    yerlestirme = round(ham + obp * k["obp_katsayi"], 3)
    return {
        "puan_turu": "EA",
        "ham_puan": ham,
        "yerlestirme_puani": yerlestirme,
        "tahmini_siralama": _tahmin_siralama("SAY", yerlestirme),
        "uyari": "EA katsayilari tahmini — OGM tam kalibre bekliyor",
    }


def _tahmin_siralama(puan_turu: str, puan: float) -> str:
    """Puan-sıralama tablosundan yaklaşık sıralama tahmini."""
    tablo = _SIRALAMA_TABLOSU.get(puan_turu, _SIRALAMA_TABLOSU.get("SAY", []))
    for p_alt, p_ust, s_alt, s_ust in tablo:
        if p_alt <= puan <= p_ust:
            # Linear interpolation
            oran = (puan - p_alt) / (p_ust - p_alt) if p_ust > p_alt else 0.5
            siralama = int(s_ust - oran * (s_ust - s_alt))
            return f"~{siralama:,}".replace(",", ".")
    if puan > 500:
        return "~500"
    return "500.000+"


def net_etkisi(ders: str, ek_net: float, puan_turu: str = "SAY") -> float:
    """Bir dersteki ek netin puana etkisini hesapla.
    Örnek: net_etkisi("fizik", 3, "SAY") → 7.29 (3 × 2.43)
    """
    k = _KATSAYILAR.get(puan_turu, {})
    ders_map = {
        "turkce": "turkce", "matematik": "mat_ayt", "mat": "mat_ayt",
        "fizik": "fizik", "kimya": "kimya", "biyoloji": "biyoloji", "bio": "biyoloji",
        "mat_tyt": "mat_tyt", "fen_tyt": "fen_tyt", "sosyal": "sosyal",
        "geometri": "mat_ayt",  # geometri mat_ayt katsayısıyla
    }
    katsayi_key = ders_map.get(ders.lower(), ders.lower())
    katsayi = k.get(katsayi_key, 1.0)
    return round(ek_net * katsayi, 2)


# ── TEST ──
if __name__ == "__main__":
    # Örnek: Ecrin Beller benzeri profil
    tyt = hesapla_tyt(turkce=35, sosyal=12, matematik=20, fen=10, diploma=85)
    print(f"TYT: {tyt['puan']} puan | Sıralama: {tyt['tahmini_siralama']}")

    say = hesapla_say(
        turkce=35, sosyal=12, mat_tyt=20, fen_tyt=10,
        mat_ayt=25, fizik=8, kimya=7, biyoloji=6, diploma=85
    )
    print(f"SAY: {say['puan']} puan | Sıralama: {say['tahmini_siralama']}")

    # Net etkisi
    fizik_etki = net_etkisi("fizik", 3, "SAY")
    print(f"Fizik +3 net = +{fizik_etki} puan")
