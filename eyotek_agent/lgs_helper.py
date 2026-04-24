"""
LGS Öğrenci Yardımcı Modülü (Oturum 23 — FAZ 1 A2)
====================================================
LGS 7 Haziran 2026 — 45 gün kaldı.

Durum (23 Nisan):
- 8 LGS/LGS-aday öğrenci (7. ve 8. sınıf)
- topic_tracker'da 235 konu kaydı (Matematik, Fen Bilimleri, Türkçe, İngilizce,
  İnkılap Tarihi, Din Kültürü)
- Ama sinav_hata_yuzdesi hepsi 0/null — çünkü LGS sınavlarında ders-bazlı
  net bilgisi DB'de yok (sadece toplam puan ~79-88/100 arası)
- LGS sınav veri akışı YKS'den FARKLI — toplam skor, ders bazlı net yok

Tool amacı:
- LGS öğrencisi "zayıf konularım / müfredatım" sorduğunda:
  * LGS ders + konu listesi göster (müfredat)
  * Varsa hata yüzdesi, yoksa "henüz veri yok"
  * LGS'ye kalan gün + çalışma önerisi
- Bot LGS öğrencisini tespit ederse LGS mantığına geçer (YKS değil)
"""
from __future__ import annotations
from datetime import date, timedelta

try:
    from loguru import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)


LGS_DATE = date(2026, 6, 7)

# LGS Müfredatı (MEB resmi, 2026 sezonu)
LGS_DERS_KONU_REF = {
    "Matematik": [
        "Çarpanlar ve Katlar", "Üslü İfadeler", "Kareköklü İfadeler",
        "Veri Analizi", "Basit Olayların Olma Olasılığı",
        "Cebirsel İfadeler ve Özdeşlikler", "Doğrusal Denklemler",
        "Eşitsizlikler", "Üçgenler", "Eşlik ve Benzerlik",
        "Dönüşüm Geometri", "Geometrik Cisimler",
    ],
    "Fen Bilimleri": [
        "Mevsimler ve İklim", "DNA ve Genetik Kod",
        "Basınç", "Madde ve Endüstri", "Basit Makineler",
        "Enerji Dönüşümleri ve Çevre Bilimi", "Elektrik Yükleri ve Elektrik Enerjisi",
        "Canlılar ve Enerji İlişkileri",
    ],
    "Türkçe": [
        "Sözcükte Anlam", "Cümlede Anlam", "Paragrafta Anlam",
        "Anlatım Biçimleri", "Sözel Mantık", "Fiilimsi",
        "Cümlenin Öğeleri", "Cümle Türleri", "Anlatım Bozuklukları",
        "Yazım Kuralları", "Noktalama İşaretleri",
    ],
    "İngilizce": [
        "Friendship", "Teen Life", "In the Kitchen",
        "On the Phone", "The Internet", "Adventures",
        "Tourism", "Chores", "Science", "Natural Forces",
    ],
    "T.C. İnkılap Tarihi": [
        "Bir Kahraman Doğuyor", "Millî Uyanış (İç ve Dış Gelişmeler)",
        "Millî Bir Destan — Ya İstiklal Ya Ölüm",
        "Atatürkçülük ve Çağdaşlaşan Türkiye",
        "Demokratikleşme Çabaları", "Atatürk Dönemi Türk Dış Politikası",
        "Atatürk'ün Ölümü", "Atatürk'ten Sonra Türkiye — 2. Dünya Savaşı ve Sonrası",
    ],
    "Din Kültürü ve Ahlak Bilgisi": [
        "Kader İnancı", "Zekât ve Sadaka",
        "Din ve Hayat", "Hz. Muhammed'in Örnekliği",
        "Kur'an-ı Kerim ve Özellikleri",
    ],
}

# LGS sınav soru sayıları (puanlama sistemi)
LGS_SINAV_DAGILIM = {
    "Türkçe": 20,
    "Matematik": 20,
    "Fen Bilimleri": 20,
    "T.C. İnkılap Tarihi": 10,
    "Din Kültürü ve Ahlak Bilgisi": 10,
    "İngilizce": 10,
}


async def is_lgs_student(soz_no: int) -> bool:
    """Öğrenci LGS hazırlığı yapıyor mu?"""
    try:
        from db_pool import db_fetchval
        cls = await db_fetchval(
            "SELECT class_name FROM fermat.students WHERE soz_no::int = $1",
            soz_no,
        )
        if not cls:
            return False
        cls_up = str(cls).upper()
        # 7 ve 8. sınıf + LGS etiketli sınıflar
        return ("LGS" in cls_up or
                cls.strip() in ("7", "8") or
                "7-A" in cls_up or "8-A" in cls_up or
                "LGS A" in cls_up)
    except Exception:
        return False


async def get_lgs_konu_durumu(soz_no: int) -> dict:
    """LGS öğrencisinin konu durumu + kalan gün + çalışma önerisi.

    Returns:
      {
        "is_lgs": True,
        "soz_no": 141,
        "full_name": "ADA BARIŞCAN",
        "class_name": "8",
        "lgs_tarih": "2026-06-07",
        "kalan_gun": 45,
        "son_sinav": {"exam_name": "...", "toplam": 79.33, "tarih": "..."},
        "son_sinav_trend": [79.33, 82.1, ...],  # son 5
        "dersler": {
          "Matematik": {
            "toplam_konu": 12,
            "mufredat": [...],
            "durumu": [
              {"konu": "Üslü İfadeler", "status": "yeni", "hata_yuzde": null},
              ...
            ],
          },
          ...
        },
        "oneri": "..."
      }
    """
    from db_pool import db_fetchval, db_fetchrow, db_fetch

    if not await is_lgs_student(soz_no):
        return {
            "is_lgs": False,
            "soz_no": soz_no,
            "mesaj": "Bu öğrenci LGS hazırlığı yapmıyor (YKS mantığında analiz edilmeli)",
        }

    # Öğrenci bilgi
    ogr = await db_fetchrow(
        "SELECT soz_no, full_name, class_name FROM fermat.students WHERE soz_no::int = $1",
        soz_no,
    )
    if not ogr:
        return {"is_lgs": False, "error": f"Öğrenci bulunamadı: soz_no={soz_no}"}

    # Son sınav + trend (son 5)
    sinavlar = await db_fetch(
        """SELECT exam_name, exam_date, toplam FROM fermat.student_exams
           WHERE soz_no = $1 AND toplam IS NOT NULL
           ORDER BY exam_date DESC LIMIT 5""",
        soz_no,
    )
    son_sinav = None
    trend = []
    if sinavlar:
        son_sinav = {
            "exam_name": sinavlar[0]["exam_name"],
            "toplam": float(sinavlar[0]["toplam"]) if sinavlar[0]["toplam"] else None,
            "tarih": sinavlar[0]["exam_date"].isoformat() if sinavlar[0]["exam_date"] else None,
        }
        trend = [float(s["toplam"]) for s in sinavlar if s["toplam"]]

    # Ders bazlı konu durumu
    tracker_rows = await db_fetch(
        """SELECT ders, konu, sinav_hata_yuzdesi, status
           FROM fermat.student_topic_tracker
           WHERE soz_no = $1
             AND COALESCE(status,'') != 'metadata'
           ORDER BY ders, konu""",
        soz_no,
    )

    dersler = {}
    for ders in LGS_DERS_KONU_REF:
        mufredat = LGS_DERS_KONU_REF[ders]
        # DB'deki bu dersin konuları
        ders_konular = [r for r in tracker_rows if (r.get("ders") or "").strip() == ders]
        durumu = []
        for r in ders_konular:
            durumu.append({
                "konu": r.get("konu"),
                "status": r.get("status") or "bilinmiyor",
                "hata_yuzde": (float(r["sinav_hata_yuzdesi"])
                              if r.get("sinav_hata_yuzdesi") is not None else None),
            })
        dersler[ders] = {
            "soru_sayisi": LGS_SINAV_DAGILIM.get(ders, 0),
            "mufredat_konu_sayisi": len(mufredat),
            "mufredat": mufredat,
            "db_konu_sayisi": len(ders_konular),
            "durumu": durumu,
        }

    # Kalan gün + öneri
    today = date.today()
    kalan_gun = (LGS_DATE - today).days

    # Son sınava göre öneri (75 altı → acil, 75-85 orta, 85+ sağlam)
    if son_sinav and son_sinav.get("toplam"):
        tp = son_sinav["toplam"]
        if tp >= 85:
            oneri = "Çok başarılısın! Şu an seviyeni korumak + eksik konuları kapatmak."
        elif tp >= 75:
            oneri = "Orta-iyi seviye. Zayıf 2-3 konuya odaklan, deneme sıklığını artır."
        elif tp >= 65:
            oneri = "Geliştirilebilir. Her hafta 1 konuyu tam öğren + deneme çöz."
        else:
            oneri = "Acil — matematik ve fen ağırlıklı çalış, rehberle görüş."
    else:
        oneri = "Henüz sınav verisi yok. İlk LGS denemesi için bol soru çöz."

    return {
        "is_lgs": True,
        "soz_no": soz_no,
        "full_name": ogr["full_name"],
        "class_name": ogr["class_name"],
        "lgs_tarih": LGS_DATE.isoformat(),
        "kalan_gun": kalan_gun,
        "son_sinav": son_sinav,
        "son_sinav_trend": trend,
        "dersler": dersler,
        "oneri": oneri,
        "kullanim": (
            "Claude: LGS öğrencisi için YKS terimleri kullanma (TYT/AYT yok). "
            "Dersler: Türkçe, Matematik, Fen Bilimleri (TEK ders — Fizik/Kimya/Biyoloji ayrı DEĞİL), "
            "T.C. İnkılap Tarihi, Din Kültürü, İngilizce. "
            "LGS 7 Haziran — motivasyon ton önemli. Çocuk 13-14 yaşında, soru sıklığı + "
            "basit dil kullan. Başarıyı kutla, zayıf konuda destek ver — demoralize etme."
        ),
    }


__all__ = [
    "LGS_DATE", "LGS_DERS_KONU_REF", "LGS_SINAV_DAGILIM",
    "is_lgs_student", "get_lgs_konu_durumu",
]
