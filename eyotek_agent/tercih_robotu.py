"""
Tercih Robotu — YKS Sonrası Öğrenci Asistan Modu (23 Nisan 2026)
==================================================================

Neo vizyonu (23 Nisan):
  "Öğrenciler sınava girmek üzere. Sınav sonrası yaz kampı başlayana kadar
   sistem bir tercih robotu gibi çalışıyor da olacak. Öğrenciler sıralamarını
   girip beklentilerini konuşup seninle tercih listeleri oluşturabilyor
   olacaklar o dönem. Özellikle YÖK Atlas'tan çektiğimiz veriler burada
   hayati olacak."

═══════════════════════════════════════════════════════════════════════════════
DÖNEMSELLİK
═══════════════════════════════════════════════════════════════════════════════
  • TYT:    13 Haziran 2026
  • AYT:    14 Haziran 2026
  • Sonuç:  ~3 Temmuz 2026 (ÖSYM açıklama)
  • Tercih: ~10 Temmuz – 25 Temmuz (yaklaşık)
  • Yaz Kampı: 1 Eylül 2026 öncesi

  Tercih Robotu aktif pencere:   1 Temmuz 2026 → 31 Ağustos 2026
  TERCIH_DONEMI_ACTIVE = False   (altyapı hazır, bayrak KAPALI)
  Neo admin komutuyla aç/kapat: "tercih modu ac" / "tercih modu kapa"

═══════════════════════════════════════════════════════════════════════════════
MİMARİ
═══════════════════════════════════════════════════════════════════════════════

  Öğrenci WP mesaj
      ↓
  is_tercih_modu_aktif()?  → Hayır → normal akış
      ↓ Evet
  Claude system prompt'a TERCIH_ROBOTU_PROMPT eklenir
      ↓
  Öğrenci konuşur: "sıralamam X, hedefim bilgisayar mühendisliği"
      ↓
  Tool: tercih_profili_kaydet → fermat.tercih_profil UPSERT
      ↓
  Bot: "Şehir tercihin? Burs durumun? Aile bütçesi?"
      ↓
  Tool: tercih_listesi_uret → universite_taban SELECT (±30 sıra)
       → 18 satır (3 garanti + 6 orta + 6 hedef + 3 hayal)
      ↓
  DB: fermat.tercih_listesi INSERT (versiyonlu)
      ↓
  Bot: Liste öğrenciye sunulur, değişiklik talepleri için döngü

═══════════════════════════════════════════════════════════════════════════════
KVKK
═══════════════════════════════════════════════════════════════════════════════
  • Her öğrenci SADECE kendi profilini görür
  • Rehber/Mudur SADECE okur (güvenlik katmanı role_access'te)
  • Öğrencinin sıralaması başka öğrenciye ASLA ifşa edilmez
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime
from typing import Optional

try:
    from loguru import logger
except Exception:  # pragma: no cover
    import logging
    logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# DÖNEM YÖNETİMİ
# ═══════════════════════════════════════════════════════════════════════════════

# Tarih pencereleri (her YKS yılı için güncellenir)
TERCIH_DONEMI_BASLANGIC = date(2026, 7, 1)
TERCIH_DONEMI_BITIS = date(2026, 8, 31)

# Env bayrağı — Neo manuel aç/kapa
_TERCIH_FLAG_CACHE = {"state": None, "ts": None}


async def is_tercih_modu_aktif() -> bool:
    """Tercih robotu modu aktif mi?

    İki kural birlikte çalışır:
    1. DB'de sistem ayarı TERCIH_DONEMI_ACTIVE=True olmalı (Neo manuel açar)
    2. Tarih pencere içinde olmalı (otomatik yürürlüğe girer)
    """
    # Cache 60 sn
    now = datetime.now()
    if _TERCIH_FLAG_CACHE["state"] is not None and _TERCIH_FLAG_CACHE["ts"]:
        if (now - _TERCIH_FLAG_CACHE["ts"]).total_seconds() < 60:
            return _TERCIH_FLAG_CACHE["state"]

    try:
        from db_pool import db_fetchval
        val = await db_fetchval(
            "SELECT value FROM fermat.sistem_ayar WHERE key='TERCIH_DONEMI_ACTIVE'"
        )
        manual_flag = str(val or "").strip().lower() == "true"
    except Exception:
        manual_flag = False

    # Tarih kontrolü (otomatik)
    today = date.today()
    tarih_icinde = TERCIH_DONEMI_BASLANGIC <= today <= TERCIH_DONEMI_BITIS

    # Mantık: Neo manuel "ac" dediyse TRUE, yoksa tarihe bak
    aktif = manual_flag or tarih_icinde

    _TERCIH_FLAG_CACHE["state"] = aktif
    _TERCIH_FLAG_CACHE["ts"] = now
    return aktif


async def set_tercih_modu(acik: bool, admin_phone: str = "") -> str:
    """Neo admin tarafından tercih modunu aç/kapa."""
    if admin_phone != "905051256802":
        return "YETKI: Sadece Neo tercih modunu degistirebilir."
    try:
        from db_pool import db_execute
        await db_execute(
            """
            INSERT INTO fermat.sistem_ayar (key, value, updated_at)
            VALUES ('TERCIH_DONEMI_ACTIVE', $1, NOW())
            ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()
            """,
            "true" if acik else "false",
        )
        _TERCIH_FLAG_CACHE["state"] = None  # cache reset
        return f"Tercih modu {'ACIK' if acik else 'KAPALI'} olarak ayarlandi."
    except Exception as e:
        return f"Hata: {e}"


# ═══════════════════════════════════════════════════════════════════════════════
# ÖĞRENCİ PROFİLİ
# ═══════════════════════════════════════════════════════════════════════════════

_PUAN_TURLERI = {"SAY", "EA", "SOZ", "DIL", "TYT"}
_GECERLI_BURSLAR = {"tam_burs", "yuzde_75", "yuzde_50", "yuzde_25", "ucretli", "belirsiz"}


def _normalize_puan_turu(pt: str) -> str:
    """SÖZ → SOZ, DİL → DIL (DB'deki format)."""
    if not pt:
        return ""
    pt = pt.strip().upper()
    return pt.replace("Ö", "O").replace("İ", "I").replace("Ü", "U")


async def tercih_profili_kaydet(
    soz_no: int,
    tyt_ham: Optional[float] = None,
    ayt_ham: Optional[float] = None,
    yerlesme_puani: Optional[float] = None,
    puan_turu: Optional[str] = None,       # SAY / EA / SÖZ / DİL
    siralama: Optional[int] = None,         # puan türündeki sıralama
    tercih_sehirler: Optional[list] = None, # ["Ankara", "Istanbul", "Izmir"]
    tercih_bolumler: Optional[list] = None, # ["Bilgisayar Muhendisligi", ...]
    kacinmak_istedigi: Optional[list] = None, # ["Hukuk", "Tip"]
    burs_durumu: Optional[str] = None,      # tam_burs / yuzde_75 / ...
    aile_butce_ust: Optional[int] = None,   # TL/yıl
    sehir_kisiti_katalik: bool = False,     # Sadece tercih_sehirler'deki şehirler
    ozel_not: Optional[str] = None,
) -> dict:
    """Öğrenci tercih profilini UPSERT eder.

    Her alan opsiyonel — parça parça doldurulabilir (konuşma ilerledikçe).
    Sadece gelen alanlar güncellenir, None gelen alanlar dokunulmaz.
    """
    from db_pool import db_execute, db_fetchrow

    if not soz_no:
        return {"error": "soz_no gerekli"}

    if puan_turu:
        puan_turu = _normalize_puan_turu(puan_turu)
        if puan_turu not in _PUAN_TURLERI:
            return {"error": f"Gecersiz puan_turu: {puan_turu}. Secenek: {_PUAN_TURLERI}"}

    if burs_durumu:
        burs_durumu = burs_durumu.lower().strip()
        if burs_durumu not in _GECERLI_BURSLAR:
            return {"error": f"Gecersiz burs_durumu. Secenek: {_GECERLI_BURSLAR}"}

    # UPSERT — mevcut varsa gelen alanları güncelle (None geçmez)
    try:
        existing = await db_fetchrow(
            "SELECT * FROM fermat.tercih_profil WHERE soz_no=$1", soz_no
        )
    except Exception:
        existing = None

    # None kalanlar için mevcuttan oku
    def _pick(new, key):
        if new is not None:
            return new
        return existing[key] if existing else None

    merged = {
        "tyt_ham": _pick(tyt_ham, "tyt_ham"),
        "ayt_ham": _pick(ayt_ham, "ayt_ham"),
        "yerlesme_puani": _pick(yerlesme_puani, "yerlesme_puani"),
        "puan_turu": _pick(puan_turu, "puan_turu"),
        "siralama": _pick(siralama, "siralama"),
        "tercih_sehirler": tercih_sehirler if tercih_sehirler is not None else (existing["tercih_sehirler"] if existing else None),
        "tercih_bolumler": tercih_bolumler if tercih_bolumler is not None else (existing["tercih_bolumler"] if existing else None),
        "kacinmak_istedigi": kacinmak_istedigi if kacinmak_istedigi is not None else (existing["kacinmak_istedigi"] if existing else None),
        "burs_durumu": _pick(burs_durumu, "burs_durumu"),
        "aile_butce_ust": _pick(aile_butce_ust, "aile_butce_ust"),
        "sehir_kisiti_katalik": sehir_kisiti_katalik if sehir_kisiti_katalik is not None else (existing["sehir_kisiti_katalik"] if existing else False),
        "ozel_not": _pick(ozel_not, "ozel_not"),
    }

    try:
        await db_execute(
            """
            INSERT INTO fermat.tercih_profil
                (soz_no, tyt_ham, ayt_ham, yerlesme_puani, puan_turu, siralama,
                 tercih_sehirler, tercih_bolumler, kacinmak_istedigi,
                 burs_durumu, aile_butce_ust, sehir_kisiti_katalik, ozel_not,
                 updated_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13, NOW())
            ON CONFLICT (soz_no) DO UPDATE SET
                tyt_ham=EXCLUDED.tyt_ham,
                ayt_ham=EXCLUDED.ayt_ham,
                yerlesme_puani=EXCLUDED.yerlesme_puani,
                puan_turu=EXCLUDED.puan_turu,
                siralama=EXCLUDED.siralama,
                tercih_sehirler=EXCLUDED.tercih_sehirler,
                tercih_bolumler=EXCLUDED.tercih_bolumler,
                kacinmak_istedigi=EXCLUDED.kacinmak_istedigi,
                burs_durumu=EXCLUDED.burs_durumu,
                aile_butce_ust=EXCLUDED.aile_butce_ust,
                sehir_kisiti_katalik=EXCLUDED.sehir_kisiti_katalik,
                ozel_not=EXCLUDED.ozel_not,
                updated_at=NOW()
            """,
            soz_no, merged["tyt_ham"], merged["ayt_ham"], merged["yerlesme_puani"],
            merged["puan_turu"], merged["siralama"],
            merged["tercih_sehirler"], merged["tercih_bolumler"], merged["kacinmak_istedigi"],
            merged["burs_durumu"], merged["aile_butce_ust"], merged["sehir_kisiti_katalik"],
            merged["ozel_not"],
        )
    except Exception as e:
        logger.error(f"tercih_profili_kaydet DB hata: {e}")
        return {"error": f"Kayit hatasi: {e}"}

    # Tamamlanma yüzdesi (hangi alanlar dolu?)
    alanlar = ["yerlesme_puani", "puan_turu", "siralama",
               "tercih_sehirler", "tercih_bolumler", "burs_durumu"]
    dolu = sum(1 for a in alanlar if merged.get(a))
    tamlik_yuzde = int(100 * dolu / len(alanlar))

    eksik = [a for a in alanlar if not merged.get(a)]

    return {
        "success": True,
        "soz_no": soz_no,
        "tamlik_yuzde": tamlik_yuzde,
        "eksik_alanlar": eksik,
        "mesaj": "Profilin guncellendi.",
    }


async def tercih_profili_getir(soz_no: int) -> dict:
    """Mevcut tercih profilini döndürür."""
    from db_pool import db_fetchrow
    try:
        row = await db_fetchrow(
            "SELECT * FROM fermat.tercih_profil WHERE soz_no=$1", soz_no
        )
    except Exception as e:
        return {"error": f"Okuma hatasi: {e}"}

    if not row:
        return {
            "soz_no": soz_no,
            "profil_var_mi": False,
            "mesaj": "Henuz tercih profilin olusturulmadi. Siralama ve beklentilerini paylasarak baslayabiliriz.",
        }
    d = dict(row)
    if "updated_at" in d and d["updated_at"]:
        d["updated_at"] = d["updated_at"].isoformat()
    d["profil_var_mi"] = True
    return d


# ═══════════════════════════════════════════════════════════════════════════════
# TERCİH LİSTESİ ÜRETİMİ
# ═══════════════════════════════════════════════════════════════════════════════

# Strateji: 18-24 satırlı liste — YÜZDE bazlı bantlar
# Sıralama 15.000 için: garanti = 15.000-16.500 / orta = 14.500-15.500 / hedef = 12.750-14.500 / hayal = 11.250-12.750
# Sıralama 50.000 için: garanti = 50.000-55.000 / orta = 48.000-52.000 / hedef = 42.500-48.000 / hayal = 37.500-42.500
#
# pct_alt, pct_ust — sıralaman * (1+pct/100) ve sıralaman * (1+pct/100)
# pct > 0: aşağıya (kolay), pct < 0: yukarıya (zor)
STRATEJI_BANDLARI_PCT = {
    "garanti":  (+10.0, +3.0),    # %3 – %10 daha aşağı: kesin girer
    "orta":     (+3.0, -3.0),     # ±%3: yerinde
    "hedef":    (-3.0, -15.0),    # %3 – %15 daha yukarı: biraz zorla
    "hayal":    (-15.0, -30.0),   # %15 – %30 daha yukarı: şans
}
# Küçük sıralamalarda (top 1000) yüzde yetersiz kalır, min 100 sıralık aralık uygulanır.
MIN_BAND_GENISLIK = 100

# Geriye dönük uyum için eski isim (okunaklılık adına)
STRATEJI_BANDLARI = STRATEJI_BANDLARI_PCT


async def tercih_listesi_uret(
    soz_no: int,
    max_satir: int = 24,
) -> dict:
    """Öğrencinin profiline + universite_taban'a göre tercih listesi üretir.

    universite_taban ŞEMA (35.584 kayıt, yıl bazlı):
      id, yil, universite, bolum, puan_turu (SAY/EA/SOZ/DIL),
      taban_puan, tavan_puan, siralama, kontenjan, doluluk_orani,
      sehir, tur (devlet/vakif), created_at

    Strateji: En güncel yıldaki kayıtları kullan. Sıralama bantlarına göre filtre.
    """
    from db_pool import db_fetchrow, db_fetch, db_execute

    profil = await tercih_profili_getir(soz_no)
    if not profil.get("profil_var_mi"):
        return {"error": "Once tercih_profili_kaydet ile profili olustur."}

    siralama = profil.get("siralama")
    puan_turu = _normalize_puan_turu(profil.get("puan_turu") or "")

    if not siralama or not puan_turu:
        return {
            "error": "Siralama ve puan_turu zorunlu.",
            "eksik": [a for a in ("siralama", "puan_turu") if not profil.get(a)],
        }

    tercih_sehirler = profil.get("tercih_sehirler") or []
    tercih_bolumler = profil.get("tercih_bolumler") or []
    kacinmak = profil.get("kacinmak_istedigi") or []
    burs_durumu = profil.get("burs_durumu")
    sehir_kisiti = profil.get("sehir_kisiti_katalik") or False

    # En güncel yıl (bütün bantlar aynı yılı kullanır)
    en_son_yil = await db_fetchrow(
        "SELECT MAX(yil) AS y FROM fermat.universite_taban WHERE puan_turu=$1",
        puan_turu,
    )
    guncel_yil = int(en_son_yil["y"]) if en_son_yil and en_son_yil["y"] else 2024

    # Her bant için SQL — YÜZDELİK BANTLAR
    liste = []
    for strateji, (pct_alt, pct_ust) in STRATEJI_BANDLARI_PCT.items():
        # pct > 0 → aşağıya (sıralaman + %)
        # pct < 0 → yukarıya (sıralaman - %, daha zor)
        # Büyük sıralama = kolay girer, küçük sıralama = zor
        pos_alt = siralama * (1.0 + pct_alt / 100.0)
        pos_ust = siralama * (1.0 + pct_ust / 100.0)

        band_min = int(min(pos_alt, pos_ust))
        band_max = int(max(pos_alt, pos_ust))

        # Minimum genişlik zorunluluğu (top 1000 gibi düşük sıralamalarda yüzde çok dar kalır)
        if band_max - band_min < MIN_BAND_GENISLIK:
            orta = (band_min + band_max) // 2
            band_min = max(1, orta - MIN_BAND_GENISLIK // 2)
            band_max = orta + MIN_BAND_GENISLIK // 2

        if band_min < 1:
            band_min = 1

        where_clauses = [
            "puan_turu = $1",
            "siralama BETWEEN $2 AND $3",
            "yil = $4",
        ]
        params = [puan_turu, band_min, band_max, guncel_yil]
        idx = 5

        # Türkçe karakter toleranslı: unaccent kullan
        if tercih_bolumler:
            bolum_or = " OR ".join(
                [f"unaccent(lower(bolum)) ILIKE unaccent(lower(${idx + i}))" for i in range(len(tercih_bolumler))]
            )
            where_clauses.append(f"({bolum_or})")
            for b in tercih_bolumler:
                params.append(f"%{b}%")
                idx += 1

        if kacinmak:
            for k in kacinmak:
                where_clauses.append(f"unaccent(lower(bolum)) NOT ILIKE unaccent(lower(${idx}))")
                params.append(f"%{k}%")
                idx += 1

        if sehir_kisiti and tercih_sehirler:
            sehir_or = " OR ".join(
                [f"unaccent(lower(sehir)) ILIKE unaccent(lower(${idx + i}))" for i in range(len(tercih_sehirler))]
            )
            where_clauses.append(f"({sehir_or})")
            for s in tercih_sehirler:
                params.append(f"%{s}%")
                idx += 1

        sql = f"""
            SELECT id, universite, bolum, sehir, tur,
                   taban_puan, tavan_puan, siralama, kontenjan, doluluk_orani, yil
            FROM fermat.universite_taban
            WHERE {' AND '.join(where_clauses)}
            ORDER BY siralama ASC
            LIMIT 50
        """

        try:
            rows = await db_fetch(sql, *params)
        except Exception as e:
            logger.warning(f"Band {strateji} SQL hata: {e}")
            continue

        # Öğrencinin tercih şehirlerini önceliklendir (kısıt değil, skor)
        def sehir_bonus(row):
            if not tercih_sehirler:
                return 0
            for ts in tercih_sehirler:
                if ts.lower() in (row["sehir"] or "").lower():
                    return 1
            return 0

        rows_sorted = sorted(rows, key=lambda r: (-sehir_bonus(r), r["siralama"]))

        # Bant başına hedef sayı
        hedef = {"garanti": 3, "orta": 6, "hedef": 6, "hayal": 3}.get(strateji, 3)

        for r in rows_sorted[:hedef]:
            liste.append({
                "strateji": strateji,
                "id": r["id"],
                "universite": r["universite"],
                "bolum": r["bolum"],
                "sehir": r["sehir"],
                "tur": r["tur"],  # devlet / vakif
                "taban_puan": float(r["taban_puan"] or 0),
                "tavan_puan": float(r["tavan_puan"] or 0) if r.get("tavan_puan") else None,
                "siralama": int(r["siralama"] or 0),
                "kontenjan": int(r["kontenjan"] or 0),
                "doluluk": float(r["doluluk_orani"] or 0) if r.get("doluluk_orani") else None,
                "yil": int(r["yil"] or guncel_yil),
                "fark": int(siralama) - int(r["siralama"] or 0),
            })

    liste = liste[:max_satir]

    # Versiyonla DB'ye kaydet
    try:
        await db_execute(
            """
            INSERT INTO fermat.tercih_listesi
                (soz_no, liste_json, created_at, max_satir)
            VALUES ($1, $2::jsonb, NOW(), $3)
            """,
            soz_no, __import__("json").dumps(liste, ensure_ascii=False), max_satir,
        )
    except Exception as e:
        logger.warning(f"tercih_listesi DB kayit hata: {e}")

    # Bant özeti
    bant_sayaci = {}
    for r in liste:
        bant_sayaci[r["strateji"]] = bant_sayaci.get(r["strateji"], 0) + 1

    return {
        "soz_no": soz_no,
        "siralama": siralama,
        "puan_turu": puan_turu,
        "liste": liste,
        "toplam_satir": len(liste),
        "bant_sayaci": bant_sayaci,
        "mesaj": (
            f"Sana {len(liste)} satirlik taslak tercih listesi hazirladim. "
            f"Bantlar: {bant_sayaci}. Istediğin bolumleri ekle/cikar, ben guncelleyeyim."
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# BÖLÜM KIYASLAMA
# ═══════════════════════════════════════════════════════════════════════════════

async def bolum_karsilastir(bolum_listesi: list, puan_turu: str = "SAY") -> dict:
    """Verilen bölümleri universite_taban'dan kıyaslar (taban puan, kontenjan, şehir)."""
    from db_pool import db_fetch, db_fetchrow

    if not bolum_listesi or len(bolum_listesi) < 2:
        return {"error": "En az 2 bolum gerekli"}

    puan_turu = _normalize_puan_turu(puan_turu)

    # En güncel yıl
    yr = await db_fetchrow(
        "SELECT MAX(yil) AS y FROM fermat.universite_taban WHERE puan_turu=$1", puan_turu,
    )
    guncel_yil = int(yr["y"]) if yr and yr["y"] else 2024

    karsilastirma = {}
    for bolum in bolum_listesi[:5]:  # en fazla 5
        rows = await db_fetch(
            """
            SELECT universite, sehir, tur, taban_puan, siralama, kontenjan
            FROM fermat.universite_taban
            WHERE puan_turu=$1
              AND unaccent(lower(bolum)) ILIKE unaccent(lower($2))
              AND yil=$3
            ORDER BY taban_puan DESC
            LIMIT 10
            """,
            puan_turu, f"%{bolum}%", guncel_yil,
        )

        if not rows:
            karsilastirma[bolum] = {"bulundu": False}
            continue

        karsilastirma[bolum] = {
            "bulundu": True,
            "en_yuksek_taban": float(rows[0]["taban_puan"]),
            "en_dusuk_taban": float(rows[-1]["taban_puan"]) if len(rows) > 1 else float(rows[0]["taban_puan"]),
            "en_yuksek_siralama": int(rows[0]["siralama"] or 0),
            "program_sayisi": len(rows),
            "yil": guncel_yil,
            "ornekler": [
                {
                    "universite": r["universite"],
                    "sehir": r["sehir"],
                    "tur": r["tur"],
                    "taban": float(r["taban_puan"]),
                    "siralama": int(r["siralama"] or 0),
                    "kontenjan": int(r["kontenjan"] or 0),
                }
                for r in rows[:3]
            ],
        }

    return {
        "puan_turu": puan_turu,
        "karsilastirma": karsilastirma,
        "tavsiye": (
            "Taban puanlar ve sehir tercihine gore dusunerek secmene yardim edebilirim. "
            "Hangisi ailene ve meslegi kabul etme surecine daha uygun, konusalim mi?"
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# DÖNEM DURUMU
# ═══════════════════════════════════════════════════════════════════════════════

async def tercih_donemi_durum() -> dict:
    """Tercih robotu aktif mi? Kaç gün kaldı? YKS tarihleri?"""
    today = date.today()
    aktif = await is_tercih_modu_aktif()

    # Bilgi: TYT/AYT/Sonuç/Tercih/Yaz Kampı
    kilometrelar = [
        ("TYT Sınavı", date(2026, 6, 13)),
        ("AYT Sınavı", date(2026, 6, 14)),
        ("ÖSYM Sonuç Açıklama", date(2026, 7, 3)),
        ("Tercih Dönemi Başlangıç", TERCIH_DONEMI_BASLANGIC),
        ("Tercih Dönemi Bitiş", TERCIH_DONEMI_BITIS),
        ("Yaz Kampı Öncesi", date(2026, 9, 1)),
    ]

    timeline = []
    for ad, tarih in kilometrelar:
        gun_fark = (tarih - today).days
        timeline.append({
            "olay": ad,
            "tarih": tarih.isoformat(),
            "kaldi_gun": gun_fark,
            "gecti_mi": gun_fark < 0,
        })

    return {
        "tercih_modu_aktif": aktif,
        "bugun": today.isoformat(),
        "timeline": timeline,
        "mesaj": (
            "Tercih robotu AKTIF — sonuçlarin üzerinden gidip tercih listesi hazirlayalim."
            if aktif else
            "Tercih robotu hazir ama henuz devrede degil. YKS sonuçları açıklandığında aktive edilecek."
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# CLAUDE PROMPT EK — ROLE-AWARE
# ═══════════════════════════════════════════════════════════════════════════════

TERCIH_ROBOTU_PROMPT_OGRENCI = """

═══════════════════════════════════════════════════════════════════════════════
🎯 TERCİH ROBOTU MODU — ŞU AN AKTİF
═══════════════════════════════════════════════════════════════════════════════

YKS sonuçları açıklandı. Bu dönem (Temmuz-Ağustos) sen öğrencinin TERCIH DANIŞMANISIN.

KURALLAR:
1. Öğrenci sıralama + beklenti paylaşırsa, derhal `tercih_profili_kaydet` tool'unu
   kullan. Her alan opsiyonel — parça parça topla (konuşma ilerledikçe).

2. Profil eksikse sırasıyla sor:
   • Yerleşme puanı ve puan türü (SAY/EA/SÖZ/DİL)
   • Sıralaman (puan türündeki sıralama)
   • Hangi şehirlerde okumak istersin? (birden fazla seçebilir)
   • Hangi bölüm/meslek? (birden fazla)
   • Kaçınmak istediğin bölüm var mı?
   • Burs durumu (tam_burs / yuzde_75 / yuzde_50 / yuzde_25 / ucretli)
   • Aile bütçe üst sınırı (yıllık TL, opsiyonel)

3. Profil yeterli olunca (en az: sıralama, puan_turu, tercih_bolumler)
   `tercih_listesi_uret` tool'unu çağır. 18-24 satırlı liste döner:
   • 3 garanti (kesin girersin)
   • 6 orta (±20 sıralama)
   • 6 hedef (biraz zorla)
   • 3 hayal (çok zorla, şans)

4. Listeyi öğrenciye sun. "Hangilerini çıkaralım?" "Eklemek istediğin var mı?" diye döngü kur.

5. İki bölüm karşılaştırılması istenirse `bolum_karsilastir` kullan.

6. KVKK: Başka öğrencinin sıralamasını, verisini, listesini ASLA ifşa etme.
   Sadece bu öğrencinin kendi profili üzerinden konuş.

7. TON: Danışman — sabırlı, objektif, aile baskısını dikkate al ama öğrenciyi
   kendi kararına yönlendir. "Hedefinden emin misin?" diye sorma hakkın var.
   "Sen ne istiyorsun?" — bu soru her zaman açık kalmalı.

8. YÖK Atlas verileri (universite_taban, 35.584 kayıt) senin ana kaynağın.
   Uydurma yapma — her önerinde taban puan + sıralama + şehir net olsun.
═══════════════════════════════════════════════════════════════════════════════
"""


TERCIH_ROBOTU_PROMPT_REHBER = """

═══════════════════════════════════════════════════════════════════════════════
🎯 TERCİH DÖNEMİ — REHBER ROLÜ
═══════════════════════════════════════════════════════════════════════════════

Tercih dönemindeyiz. Öğrencilerin sıralama + profil verileri `tercih_profil`
tablosunda birikiyor. `tercih_listesi` tablosunda üretilen taslaklar var.

Rehber olarak:
- `tercih_profili_getir(soz_no)` — öğrencinin güncel profilini gör
- Öğrencinin tercih listesini gözden geçir, veli görüşmesi hazırla
- Risk sinyalleri: sıralaması yüksek ama hedef çok küçük, veya tam tersi

Başka öğrencinin profilini sadece kurumsal ihtiyaçta aç — iki öğrenci
arasında sıralama kıyası yapma.
═══════════════════════════════════════════════════════════════════════════════
"""


def get_tercih_prompt(role: str) -> str:
    """Role göre tercih prompt döner."""
    if role == "ogrenci":
        return TERCIH_ROBOTU_PROMPT_OGRENCI
    if role == "rehber":
        return TERCIH_ROBOTU_PROMPT_REHBER
    return ""


__all__ = [
    "is_tercih_modu_aktif", "set_tercih_modu",
    "tercih_profili_kaydet", "tercih_profili_getir",
    "tercih_listesi_uret", "bolum_karsilastir",
    "tercih_donemi_durum",
    "get_tercih_prompt",
    "TERCIH_DONEMI_BASLANGIC", "TERCIH_DONEMI_BITIS",
]
