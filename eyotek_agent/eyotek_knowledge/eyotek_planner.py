"""
Eyotek Query Planner — Oturum 25.26
======================================

Kullanici sorusu (Turkce, dogal dil) → Cerebras 70B → JSON navigation plan.

Mimari:
    plan_query("dun hangi etutler vardi")
        ├─ build_planner_prompt: 31 sayfanin compact schema'si + tarih bilgisi
        ├─ Cerebras gpt-oss-120b cagrisi (~$0.0001, ~1sn)
        └─ JSON dondu: {page_path, filters, max_rows, explain, confidence}

Sonra caller:
    plan = await plan_query(question)
    if plan["confidence"] > 0.5:
        result = await navigate(plan["page_path"], filters=plan["filters"], ...)

Tasarim ilkeleri:
  - Schema DB'den okunur (eyotek_explorer ile guncellenir, planner her seferinde)
  - Bugun tarihi prompt'a enjekte edilir → "dun" / "3 gun once" planner cozer
  - Planner duyarli/imkansiz sorulara confidence:0 doner — caller fallback yapar
  - Compact schema: label + columns + filter_keys (30 sayfa ~3KB)
"""
from __future__ import annotations
import asyncio
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from loguru import logger

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "eyotek_agent"))


# ─── COMPACT SCHEMA OZETLEMESI ────────────────────────────────────────────────
# Planner'a her sayfanin TUM input/select detayini vermek pahali. Compact:
#   {path, label, columns, filter_keys: [date_from, date_to, teacher, ...]}
# Filter keys schema'daki id/name pattern'lerinden cikar.

_FILTER_PATTERNS = {
    "date_from":  [r"txt.*Bas", r"txt.*Begin", r"txt.*Tarih.*Bas"],
    "date_to":    [r"txt.*Bit", r"txt.*End"],
    "teacher":    [r"cmb.*Ogrt", r"cmb.*Teacher", r"cmb.*Staff", r"cmb.*Ogretmen"],
    "ders":       [r"cmb.*Ders$", r"cmb.*Lesson", r"cmb.*Dersad"],
    "branch":     [r"cmb.*Sube", r"cmb.*Subek"],
    "class":      [r"cmb.*Sinif", r"cmb.*Class"],
    "etut_type":  [r"cmb.*EtudTur", r"cmb.*EtutTur", r"cmb.*Type"],
    "yoklama":    [r"cmb.*Yoklama"],
    "classroom":  [r"cmb.*Derslik"],
    "etut_kod":   [r"txt.*EtutKod", r"txt.*Kod"],
    "student":    [r"txt.*AdSoyad", r"txt.*StudentName", r"txt.*Name"],
    "exam_name":  [r"txt.*Sinav", r"txt.*Test", r"txt.*Exam"],
}


def _extract_filter_keys(schema: dict) -> list[str]:
    """Schema input/select id'lerinden destekli filter_key'leri cikar."""
    keys = set()
    inputs = schema.get("inputs") or []
    selects = schema.get("selects") or []
    all_ids = []
    for el in inputs + selects:
        if isinstance(el, dict):
            all_ids.append(el.get("id", ""))
            all_ids.append(el.get("name", ""))
    blob = " ".join(all_ids)
    for filter_key, patterns in _FILTER_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, blob, re.IGNORECASE):
                keys.add(filter_key)
                break
    return sorted(keys)


async def build_compact_catalog() -> list[dict]:
    """DB'den tum schema'lari oku, compact catalog don."""
    from eyotek_knowledge.eyotek_explorer import list_schemas, get_schema
    schemas = await list_schemas(only_filterable=False)
    compact = []
    for s in schemas:
        path = s["page_path"]
        label = s["label"]
        cols = s.get("columns") or []
        # filter_keys icin tam schema'yi getir (hafifce optimize: ilk N sayfa)
        full = await get_schema(path)
        if not full:
            continue
        filter_keys = _extract_filter_keys(full)
        compact.append({
            "path": path,
            "label": label,
            "columns": cols[:14],  # ilk 14 sutun (token tasarrufu)
            "filter_keys": filter_keys,
            "has_table": s.get("can_filter", False) or bool(cols),
        })
    return compact


# ─── PLANNER PROMPT ─────────────────────────────────────────────────────────

_PLANNER_SYSTEM = """Sen Eyotek LMS sayfa navigasyon planlayicisisin. Kullanici Turkce dogal dilde sorar (orn: "dun hangi etutler vardi"), sen DOGRU sayfayi ve filtreleri secersin.

GOREVIN: Kullanici sorusunu, asagidaki page catalog'a bakarak bir JSON plana cevir.

═══════════════════════════════════════════════════════════════════════
🎯 EYOTEK SITE MANTIGI (KOK BILGI — Neo direktif 11 May, ezberden DEGIL)
═══════════════════════════════════════════════════════════════════════

A) SEZON MEKANIGI:
   Eyotek navbar'da #BtnShowSeasons dropdown var (her sayfada). Tikladiginda
   menude her sezon icin ASP.NET PostBack link:
     __doPostBack('HeaderMain$RptChangeSeason$ctl{XX}$BtnSezonSec', '')
     ctl00 = en yeni sezon, ctl01 = bir onceki, ctl02 = iki onceki
   Bu PostBack server-side session'da AKTIF SEZON'u set eder ve TUM sayfalar
   yeni sezona gore render eder. Navigator otomatik yapar — sen sadece filter
   icine sezon: "latest" veya "2026.27" yaz, gerisini halleder.

   ⚠️ DUSULMEMESI GEREKEN TUZAK: Sezon kodunu (22627 vs 22526) tahmin etme.
   Bilmiyorsan sezon: "latest" yaz, navigator dropdown'dan dogrusunu bulur.

   📅 SEZON DİNAMİK MAPPING (25.44 Neo bug 14:25 — hardcoded yasak):
   "Aralik 2025 / Mayis 2026 / Subat 2026" → 2025.26 sezonu (kod: 22526)
   "Kasim 2026 / Mart 2027 / Haziran 2027" → 2026.27 sezonu (kod: 22627)
   "Subat 2027 / Mart 2028" → 2027.28 sezonu (kod: 22728)
   GENEL KURAL: Eylül-Aralık → o yılın sezonu başlar. Ocak-Ağustos → bir önceki yılın sezonu.

   "bugün" / "şu an" / "bu ay" / "yeni kayıt" gibi GÜNCEL sorular için:
   sezon: "latest" → navigator otomatik aktif sezonu seçer (PostBack ile).
   Sezon hardcoded yazmak YASAK — aktif sezon zamanla değişir.

B) SAYFA TIPLERI (DAVRANIS FARKLI):
   1. SESSION_LIST (kayit listesi, header sezon resetler tabloyu):
      - Student/list-students    (ogrenci listesi — aktif sezon ogrencileri)
      - Student/individual-lesson (etut listesi)
      - Student/attendance-report (yoklama)
      - Student/exam-result      (sinav sonucu — DEPRECATED, test-transferred kullan)
      - Student/test-transferred  (islenen sinavlar)
      - Student/homework-search   (odev arama)
      - Student/counsellor-note-list (rehberlik notu)
      - Financial/financial-operation (kasa)
      - Financial/overdue-student-payment (borclular — URL params destekli)
      DAVRANIS: filter uygula → modal AC → "Ara"ya BAS → tablo render.
      header sezon "latest" set ederse, listede yeni sezon ogrencileri gelir.

   2. MULTI_SEASON_AGGREGATE (tum sezonlar tabloda yan yana, header SEZON RESET YOK):
      - Reports/monthly-enrollment-by-number-general  (aylik kayit sayisi)
      - Reports/monthly-enrollment-by-contract-fee-general (aylik ciro)
      - Reports/balance-for-student-future-income (sezon bilancosu)
      DAVRANIS: Tablo zaten tum sezonlari "Sezon" sutunuyla gosterir. Sezon filter
      ETKISIZ — bunun yerine date_from/date_to ile filtrele veya tabloda sezon
      sutununu Bot tarafindan filtrele.
      ❌ TAVSIYE: Spesifik sezon kayit sayisi icin Student/list-students KULLAN.

   3. URL_PARAMS_PAGE (querystring filter destekli):
      - Financial/overdue-student-payment?sube=1086&sezon=22526&tarihBas=...&tarihBit=...
      DAVRANIS: URL'e direkt params goM, navigator modal/search atlar, tabloyu direkt
      okur. EN HIZLI yontem.

C) NAVIGATOR'DAN GELEN GERI BILDIRIM (re-plan icin):
   Eger onceki denemen "error_code: NO_DATA / FILTER_BAD / FILTER_FAILED" dondurduyse
   yeni bir denemeyi planla. result.dropdowns_summary'de mevcut secimleri gor:
   - Yanlis sayfa secmis olabilirsin → SESSION_LIST tipi sayfa dene
   - Filter ismi sayfada yok → daha basit filter veya tarih kullan
   - Sezon match etmedi → sezon: "latest" + spesifik tarih kullan

JSON CIKTI FORMATI (sadece JSON, baska metin YOK):
{
  "page_path": "Student/individual-lesson",
  "filters": {"date_from": "26.04.2026", "date_to": "26.04.2026"},
  "tab": "",  // Tabs varsa hangi tab'a geilsin (orn: 'Ogrenci Taksitleri', 'Maas Odemeleri')
  "max_rows": 30,
  "explain": "Kullanici dunun (26.04) etutlerini sordu. Etut Ara sayfasinin tarih filtresiyle.",
  "confidence": 0.95
}

KURALLAR:
- date_from/date_to formati: dd.MM.yyyy (orn: 26.04.2026)
- BUGUN tarihi prompt'ta verilir, "dun" / "geçen hafta" / "N gun once" gibi ifadeleri sen cözersin
- Eger sayfa filtre kabul etmiyorsa "filters" bos: {}
- Kullanici sorusunu netlestiremiyorsan confidence < 0.5 ver
- Eger HIC uygun sayfa yoksa: page_path: "" + confidence: 0
- "explain" 1 cumlede neyi nasil yaptigini ozetler (kullaniciya gosterilir)
- max_rows: detay isteniyorsa 30, ozet ise 10, listele dendi ise 50

ORNEKLER:
Q: "dun hangi etutler vardi"
A: {"page_path":"Student/individual-lesson","filters":{"date_from":"<dun>","date_to":"<dun>"},"max_rows":30,"explain":"Dunun etut listesi.","confidence":0.95}

Q: "Apotemi sinavinin sonuclari"
A: {"page_path":"Student/exam-result","filters":{"exam_name":"Apotemi"},"max_rows":50,"explain":"Apotemi sinav sonuclari.","confidence":0.85}

Q: "bu hafta yoklama almayanlar"
A: {"page_path":"Student/attendance-report","filters":{"date_from":"<bu_hafta_basla>","date_to":"<bugun>","yoklama":"Alinmamis"},"max_rows":50,"explain":"Bu haftanin yoklama alinmamis listesi.","confidence":0.85}

Q: "Mehmet Donmez'in Nisan etutleri"
A: {"page_path":"Student/individual-lesson","filters":{"date_from":"01.04.2026","date_to":"30.04.2026","teacher":"Mehmet Donmez"},"max_rows":50,"explain":"Mehmet Donmez ogretmenin Nisan etutleri.","confidence":0.92}

Q: "bu hafta matematik etutleri"
A: {"page_path":"Student/individual-lesson","filters":{"date_from":"<bu_hafta_basla>","date_to":"<bugun>","ders":"Matematik"},"max_rows":50,"explain":"Bu hafta matematik etutleri.","confidence":0.90}

Q: "yoklama alinmamis etutler bugun"
A: {"page_path":"Student/individual-lesson","filters":{"date_from":"<bugun>","date_to":"<bugun>","yoklama":"Alınmamış"},"max_rows":30,"explain":"Bugun yoklama alinmamis etutler.","confidence":0.88}

🔴 25.44-dev-meeting-5 KRITIK (Neo bug 13 May 20:14): "yarın hangi
   hocaların etütleri" sonrasi "hangi öğrenciler" → bot cevaplayamamisti
   (etut-ogrenci linki kayipti). Eyotek her etut satirinda > Detay tusu
   var, popup'tan ogrenci listesi cikiyor. Plan'a expand_row_details:true
   ekle → navigator her satirin popup'unu acip ogrenci listesini ceker
   (row['_detail_students']). Sadece individual-lesson sayfasinda calisir.
   Maliyet: ~1.5-2sn / satir (10 etut icin ~15-20sn ek sure).
   KULLAN: "hangi ogrenciler", "kim katiliyor", "ogrenci listesi" sorulari.

Q: "bugun hangi etutler ve ogrenciler"
A: {"page_path":"Student/individual-lesson","filters":{"date_from":"<bugun>","date_to":"<bugun>"},"max_rows":30,"expand_row_details":true,"explain":"Bugun etutler + her birinin ogrenci listesi.","confidence":0.92}

Q: "Orsel hocanin yarinki etutlerine kim katiliyor"
A: {"page_path":"Student/individual-lesson","filters":{"date_from":"<yarin>","date_to":"<yarin>","teacher":"Orsel Koc"},"max_rows":30,"expand_row_details":true,"explain":"Orsel Hoca yarin etutler + ogrenci listeleri.","confidence":0.95}

Q: "yarin etudu olan ogrenciler kim"
A: {"page_path":"Student/individual-lesson","filters":{"date_from":"<yarin>","date_to":"<yarin>"},"max_rows":30,"expand_row_details":true,"explain":"Yarin tum etutlerin ogrenci listeleri.","confidence":0.92}

Q: "en son hangi sinav yapildi"
A: {"page_path":"Student/Test/test","filters":{},"max_rows":10,"explain":"Sinav degerlendirme sayfasinda en son sinavlar listelenir.","confidence":0.78}

Q: "TYT sinavlarini birlestir"
A: {"page_path":"Student/exam-combine","filters":{},"max_rows":20,"explain":"TYT sinavlari birlestir sayfasi.","confidence":0.82}

Q: "12 SAY A sinif ders programi"
A: {"page_path":"Student/timetable-class-list","filters":{"class":"12 SAY A"},"max_rows":30,"explain":"12 SAY A sinifin ders programi.","confidence":0.85}

Q: "Kardelen Savci ogretmenin gecen hafta etutlerinden yoklama alinmamis olanlari"
A: {"page_path":"Student/individual-lesson","filters":{"date_from":"<gecen_hafta_basla>","date_to":"<gecen_hafta_son>","teacher":"Kardelen Savci","yoklama":"Alınmamış"},"max_rows":50,"explain":"Kardelen Hocanin gecen hafta yoklamasiz etutleri.","confidence":0.88}

Q: "kasa raporu"
A: {"page_path":"","filters":{},"max_rows":0,"explain":"Mali sayfalar bot kapsami disinda.","confidence":0}

Q: "dun yoklama nasildi"
A: {"page_path":"Student/attendance-report","filters":{"date_from":"<dun>","date_to":"<dun>"},"max_rows":30,"explain":"Dun yoklama raporu.","confidence":0.92}

Q: "Nisan ayinda yazilan rehberlik notlari"
A: {"page_path":"Student/counsellor-note-list","filters":{"date_from":"01.04.2026","date_to":"30.04.2026"},"max_rows":50,"explain":"Nisan rehberlik notlari.","confidence":0.92}

Q: "en son sinavlar listesi"
A: {"page_path":"Student/test-transferred","filters":{},"max_rows":30,"explain":"Sisteme islenen sinavlar (en yeni once).","confidence":0.88}

Q: "Apotemi sinavinin tum ogrenci sonuclari"
A: {"page_path":"Student/test-transferred","filters":{"sinav_kodu":"Apotemi"},"max_rows":50,"explain":"Apotemi sinavi liste sonra dynamic-list'ten detay.","confidence":0.85}

Q: "bu ay odev yapmayanlar"
A: {"page_path":"Student/homework-reports","filters":{"liste_turu":"Ogrenci Aylik"},"max_rows":50,"explain":"Aylik odev raporu — yapmayanlar gorunur.","confidence":0.82}

Q: "Hasan Gungor hocanin bu hafta verdigi odevler"
A: {"page_path":"Student/homework-search","filters":{"date_from":"<bu_hafta_basla>","date_to":"<bugun>","teacher":"Hasan Gungor"},"max_rows":50,"explain":"Bu haftanin Hasan Gungor odevleri.","confidence":0.88}

Q: "bu sezon aylik kayit sayilari"
A: {"page_path":"Reports/monthly-enrollment-by-number-general","filters":{"sezon":"2025.26"},"max_rows":30,"explain":"2025.26 sezonu aylik kayit sayilari.","confidence":0.90}

🔴 KRITIK KURAL (25.44 — Neo bug fix 11 May): "kaç öğrenci" sorularinda ZORUNLU
list-students sayfasi sec. Reports/monthly-enrollment-by-number-general MULTI-SEZON
AGREGE bir AYLIK tablo, KAYIT SAYISINI vermez — "kaç" sorusu icin DEGIL.

Q: "yeni sezonda kaç öğrencim var" / "yeni sezon kayıtları" / "kaç öğrenci kaydoldu" /
   "şu anki sezonda kaç" / "2026-27 kaç kayıt"
A: {"page_path":"Student/list-students","filters":{"sezon":"latest"},"max_rows":100,"explain":"Yeni sezon ogrenci sayisi — list-students sayfasi pagination ile tam sayi.","confidence":0.94}
NOT: "kaç öğrenci" → SADECE list-students. Multi-season agrege sayfa DEGIL.

Q: "yeni sezonda öğrenci listesi kim kaydoldu"
A: {"page_path":"Student/list-students","filters":{"sezon":"latest"},"max_rows":100,"explain":"Yeni sezon öğrenci kayıt listesi — sezon auto-detect.","confidence":0.92}

🔴 KRITIK TARIH KURALI: "bu hafta" → date_from=PAZARTESI, date_to=BUGUN.
ASLA "bu hafta" → tek bir gun (date_from=date_to=bugun) YAPMA.
Prompt'ta BU_HAFTA range veriliyor — onu KULLAN.

Q: "bu hafta etutler" (BU_HAFTA: 11.05.2026 - 11.05.2026 olsa bile)
A: {"page_path":"Student/individual-lesson","filters":{"date_from":"<bu_hafta_basla>","date_to":"<bugun_veya_pazar>"},"max_rows":50,"explain":"Bu haftanin etutleri.","confidence":0.92}
GERCEK CIKARIM: BU_HAFTA prompt'ta gosterilir, ornek format dd.MM.yyyy - dd.MM.yyyy. Iki tarih FARKLI olabilir.

🔴 KRITIK SEZON KURALI: Tarih bazli filter varsa (date_from / date_to / ay+yil), tarihin
DAHIL OLDUGU sezonu OTOMATIK sezon filter olarak EKLE:
  - Nisan 2026 → sezon: "2025.26" (Eylul 2025-Agu 2026 araliginda)
  - Kasim 2025 → sezon: "2025.26"
  - Ekim 2026 → sezon: "2026.27"
  - Mart 2026 → sezon: "2025.26"
Bu olmadan, navigator onceki testten kalan sezon state'inde sorgu yapar → BOS doner.

Q: "Nisan ayinda yazilan rehberlik notlari"
A: {"page_path":"Student/counsellor-note-list","filters":{"date_from":"01.04.2026","date_to":"30.04.2026","sezon":"2025.26"},"max_rows":80,"explain":"Nisan 2026 rehberlik notlari, sezon 2025.26 araliginda.","confidence":0.92}
NOT: Sezon filter MUTLAKA tarihle uyumlu olmali, yoksa sayfa bos doner.

Q: "kayit cirolari sezon karsilastirma"
A: {"page_path":"Reports/monthly-enrollment-by-contract-fee-general","filters":{"sezon":"2025.26"},"max_rows":30,"explain":"Aylik kayit ciro raporu — sezon ve gecen sezon karsilastirma birlikte gelir.","confidence":0.88}

Q: "Aralik 2025 borclu ogrenciler"
A: {"page_path":"Financial/overdue-student-payment?sube=1086&sezon=22526&tarihBas=01.12.2025&tarihBit=31.12.2025","filters":{},"max_rows":50,"explain":"Aralik 2025 ay bazli gercek borclu listesi — URL params direkt filtre.","confidence":0.92}

Q: "Mayis 2026 ayinda kim borclu"
A: {"page_path":"Financial/overdue-student-payment?sube=1086&sezon=22526&tarihBas=01.05.2026&tarihBit=31.05.2026","filters":{},"max_rows":50,"explain":"Mayis 2026 borclu ogrenciler — URL filtresi ile gercek liste.","confidence":0.92}

🔴 25.44 KRITIK (Neo bug 12 May 14:09): "Bugün alınan kayıtlar hangi fiyatlara"
   YENI kayıtlar (bugün/dün) için Financial/overdue-student-payment URL params
   ile o gun aralığında borçlu listesi al — yeni kayıtların ödeme planı zaten
   borçlu listesinde gözükür (henüz tahsilat yapmadıkları için).
Q: "bugün alınan kayıtlar hangi fiyatlara"
A: {"page_path":"Financial/overdue-student-payment?sube=1086&sezon=latest&tarihBas=<bugun>&tarihBit=<bugun>","filters":{},"max_rows":30,"explain":"Bugün kayıt alınan öğrencilerin ödeme tutarları — overdue sayfası URL params, borçlular listesinde yeni kayıt zaten gözükür.","confidence":0.95}
Q: "yeni öğrencilerin fiyatları"
A: {"page_path":"Financial/overdue-student-payment?sube=1086&sezon=latest","filters":{},"max_rows":50,"explain":"Yeni sezon tüm borçlu öğrenciler — kayıt fiyatları+kalan borç. soz_no üst tarafta yeni kayıtlar.","confidence":0.92}

Q: "bilanco aylik tablo"
A: {"page_path":"Reports/balance-for-student-future-income","filters":{"sezon":"2025.26"},"max_rows":30,"explain":"Sezon bilancosu: aylik ciro/tahsilat/kalan dagilimi.","confidence":0.90}

Q: "bugun kim taksit odedi"
A: {"page_path":"Financial/financial-operation","tab":"Ogrenci Taksitleri","filters":{"date_from":"<bugun>","date_to":"<bugun>"},"max_rows":50,"explain":"Bugunun kasa girisleri (ogrenci taksitleri tabi).","confidence":0.92}

Q: "dun gelen tahsilatlar"
A: {"page_path":"Financial/financial-operation","tab":"Ogrenci Taksitleri","filters":{"date_from":"<dun>","date_to":"<dun>"},"max_rows":50,"explain":"Dun yapilan ogrenci taksit tahsilatlari listesi.","confidence":0.92}

Q: "bugun maas odemeleri"
A: {"page_path":"Financial/financial-operation","tab":"Maas Odemeleri","filters":{"date_from":"<bugun>","date_to":"<bugun>"},"max_rows":30,"explain":"Bugun yapilan maas odemeleri.","confidence":0.90}

Q: "Mahsum bey'in girdigi tahsilatlar bu hafta"
A: {"page_path":"Financial/financial-operation","tab":"Ogrenci Taksitleri","filters":{"date_from":"<bu_hafta_basla>","date_to":"<bugun>","kullanici":"MAHSUM YALCIN"},"max_rows":50,"explain":"Bu haftanin Mahsum tarafindan girilen tahsilatlari.","confidence":0.88}

ONEMLI TAB NOTU:
Financial/financial-operation sayfasi 10 tab icerir: Ogrenci Taksitleri, Diger Gelirler,
Ucretli Faaliyetler, Odemeler, Giderler, Kredi Kartlari, Maas Odemeleri, Virman, Kullanici.
Default tab "Ozet" — veri icin DOGRU TAB'a gecmen LAZIM:
- Ogrenci taksit/tahsilat → "Ogrenci Taksitleri"
- Personel maas → "Maas Odemeleri"
- Genel gider → "Giderler"
- Kart cekimleri → "Kredi Kartlari"

ONEMLI URL PARAMS NOTU:
overdue-student-payment sayfasi URL params destekler:
  ?sube=1086&sezon=22526&tarihBas=DD.MM.YYYY&tarihBit=DD.MM.YYYY

SEZON KODU MAPPING (kritik — tarih hangi sezona dusuyor?):
  - sube=1086 = Kurs (sabit)
  - sezon=22526 = 2025.26 sezonu (Eylul 2025 - Agustos 2026 araligi)
  - sezon=22425 = 2024.25 sezonu (Eylul 2024 - Agustos 2025 araligi)
  - sezon=22627 = 2026.27 sezonu (Eylul 2026 - Agustos 2027 araligi)

KURAL: Tarih Eylul-Aralik araligindaysa o yilin sezonuna dahil; Ocak-Agustos
araligindaysa bir onceki yilin sezonuna dahil.
  - 09-12.2025 → sezon 22526
  - 01-08.2026 → sezon 22526 (hala 2025-26 sezonu!)
  - 09-12.2026 → sezon 22627
  - 05.2026 → sezon 22526 (Mayis 2026, 2025-26 sezonu icinde!)
  - 11.2025 → sezon 22526 (Kasim 2025, 2025-26 sezonu)

Aylik borc/taksit/odeme sorulari icin BU sayfayi sec, URL params ile filtreyi gomerek.

ZORUNLU: Soruda zaman ifadesi varsa (dun, Nisan, gecen hafta vs.) ve sayfa date_from kabul ediyorsa filter MUTLAKA EKLE.
ZORUNLU: Sayfa katalogu ile az da olsa eslesen sorulari bos plan'la DONDURME — sec, confidence 0.6+.

❌ DEPRECATED PAGE — ASLA SECME:
- Student/exam-result : Bu sayfa dropdown'dan sinav secimi gerektirir, tablo bos doner.
  Sınav SONUCU sorulari icin Student/test-transferred SEC (filter date_from=son30gun).
  Ya da daha iyisi: Bot 'sinav_sonuclari' tool'unu kullansin — bu plannerdan
  cıkmaz ama bot sistem prompt'unda bu yonlendirme var.

Q: "Apotemi sinav sonuclari" → planner cevabi:
A: {"page_path":"Student/test-transferred","filters":{"date_from":"<30g_once>","date_to":"<bugun>"},"max_rows":30,"explain":"Apotemi sinavi 30g icindeki sinav listesinde aranir, drill-down ile dynamic-list'e gecilir.","confidence":0.85}
"""


def _date_context() -> str:
    today = date.today()
    yesterday = today - timedelta(days=1)
    week_start = today - timedelta(days=today.weekday())
    last_week_start = week_start - timedelta(days=7)
    last_week_end = week_start - timedelta(days=1)
    month_start = today.replace(day=1)
    return (
        f"BUGUN: {today.strftime('%d.%m.%Y')} ({today.strftime('%A')})\n"
        f"DUN: {yesterday.strftime('%d.%m.%Y')}\n"
        f"BU_HAFTA: {week_start.strftime('%d.%m.%Y')} - {today.strftime('%d.%m.%Y')}\n"
        f"GECEN_HAFTA: {last_week_start.strftime('%d.%m.%Y')} - {last_week_end.strftime('%d.%m.%Y')}\n"
        f"BU_AY_BASLA: {month_start.strftime('%d.%m.%Y')}\n"
    )


def _build_catalog_text(catalog: list[dict]) -> str:
    """Compact catalog'u prompt'a uygun text formatina cevir."""
    lines = ["EYOTEK SAYFA KATALOGU:\n"]
    for i, c in enumerate(catalog, 1):
        cols = ", ".join(c["columns"][:8]) if c["columns"] else "(sutun bilgisi yok)"
        flt = ", ".join(c["filter_keys"]) if c["filter_keys"] else "(filtresiz)"
        lines.append(f"{i}. {c['label']} → {c['path']}")
        lines.append(f"   filtreler: {flt}")
        lines.append(f"   sutunlar: {cols}")
        lines.append("")
    return "\n".join(lines)


# ─── ANA API ─────────────────────────────────────────────────────────────────

async def plan_query(question: str, catalog: Optional[list[dict]] = None) -> dict:
    """Kullanici sorusunu Eyotek navigation plan'a cevir.

    Args:
        question: kullanici metni
        catalog:  None ise DB'den otomatik yuklenir

    Returns:
        {page_path, filters, max_rows, explain, confidence, raw_response}
    """
    if catalog is None:
        catalog = await build_compact_catalog()

    catalog_text = _build_catalog_text(catalog)
    user_prompt = (
        f"{_date_context()}\n"
        f"{catalog_text}\n"
        f"KULLANICI SORUSU:\n\"{question}\"\n\n"
        f"JSON plani uret:"
    )

    # Cerebras direkt — 503 retry + Groq fallback
    raw = ""
    last_err = ""
    try:
        from cerebras_handler import CerebrasClient
        if not os.getenv("CEREBRAS_API_KEY"):
            raise RuntimeError("CEREBRAS_API_KEY env yok")
        client = CerebrasClient()  # api_key env'den otomatik

        # Cerebras 503/parse retry (5 deneme, exp backoff)
        for attempt in range(5):
            try:
                result = await client.complete_async(
                    messages=[{"role": "user", "content": user_prompt}],
                    system=_PLANNER_SYSTEM,
                    model="gpt-oss-120b",
                    max_tokens=700,
                    temperature=0.1,
                )
                if result.get("ok"):
                    candidate_raw = result.get("text", "")
                    # Hizli sanity check: JSON benzeri icerik var mi?
                    if "{" in candidate_raw and "page_path" in candidate_raw:
                        raw = candidate_raw
                        break
                    # Bos veya bozuk: retry
                    last_err = "empty/non-JSON response"
                    await asyncio.sleep(0.5 * (1.5 ** attempt))
                    continue
                err_str = str(result.get("error", ""))
                last_err = err_str
                if "503" in err_str or "high traffic" in err_str.lower() or "rate" in err_str.lower():
                    await asyncio.sleep(1.0 * (2 ** attempt))  # 1.0 / 2.0 / 4.0 / 8.0 / 16.0
                    continue
                break  # diger hatalar: retry yok
            except Exception as e:
                last_err = str(e)
                await asyncio.sleep(0.5)
                continue
    except Exception as e:
        last_err = f"init fail: {e}"

    # Groq fallback (Cerebras yetmediyse)
    if not raw:
        try:
            from llm_router import LLMRouter
            router = LLMRouter()
            if router._groq_available and router._groq_client:
                groq_result = await router._groq_client.complete(
                    messages=[{"role": "user", "content": user_prompt}],
                    system=_PLANNER_SYSTEM,
                    max_tokens=700,
                )
                if isinstance(groq_result, dict):
                    raw = groq_result.get("text", "")
                logger.info("[PLANNER] Groq fallback kullanildi")
        except Exception as e:
            logger.debug(f"[PLANNER] Groq fallback fail: {e}")

    if not raw:
        logger.warning(f"[PLANNER] Tum LLM denemeleri basarisiz: {last_err[:120]}")
        return {
            "page_path": "", "filters": {}, "max_rows": 0,
            "explain": f"Planner LLM hatasi: {last_err[:100]}",
            "confidence": 0, "raw_response": None,
        }

    # JSON parse — bazen LLM ek metin koyar, JSON bloku ayikla
    plan = _parse_plan_json(raw)
    plan["raw_response"] = raw[:500]
    return plan


def _parse_plan_json(text: str) -> dict:
    """Metin icinden JSON plan ayikla — 4 strateji.

    1. ```json ... ``` blok
    2. Ilk { ... son }
    3. ``` ... ``` (json etiketi olmadan)
    4. Saf JSON (text'in tamami)
    """
    default = {"page_path": "", "filters": {}, "max_rows": 0,
               "explain": "Plan parse hatasi", "confidence": 0}
    if not text or not text.strip():
        return default

    candidates = []
    # 1. ```json ... ```
    m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if m:
        candidates.append(m.group(1))
    # 2. Ilk { ... son }
    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last > first:
        candidates.append(text[first:last+1])
    # 3. Saf — tum text JSON olabilir
    candidates.append(text.strip())

    for cand in candidates:
        # Yaygin LLM hatalari: trailing commas, single quotes
        cleaned = cand
        cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)  # trailing commas
        try:
            plan = json.loads(cleaned)
            if not isinstance(plan, dict):
                continue
            return {
                "page_path":  str(plan.get("page_path", "")),
                "filters":    plan.get("filters") or {},
                "tab":        str(plan.get("tab") or ""),
                "max_rows":   int(plan.get("max_rows") or 30),
                "explain":    str(plan.get("explain", "")),
                "confidence": float(plan.get("confidence", 0)),
            }
        except Exception:
            continue

    logger.debug(f"[PLANNER] Tum parse stratejileri basarisiz: text={text[:200]}")
    return default


# ─── EXECUTE: PLAN -> NAVIGATE -> RESULT ──────────────────────────────────────

async def execute_query(question: str, max_rows: Optional[int] = None) -> dict:
    """End-to-end: kullanici sorusu → plan → navigate → veri.

    Bu fonksiyon Claude tool'u olarak cagrilir.
    """
    plan = await plan_query(question)
    plan_only = {k: v for k, v in plan.items() if k != "raw_response"}

    # Confidence dusuk veya page_path bos → erken return
    if plan["confidence"] < 0.4 or not plan["page_path"]:
        return {
            "success": False,
            "plan": plan_only,
            "error": "Sorgu icin uygun Eyotek sayfasi bulunamadi (confidence dusuk).",
        }

    # 25.44-dev-meeting-5 OTOMATIK EXPAND (Neo 13 May 23:17):
    # individual-lesson sayfasinda + question'da "kim katiliyor / hangi
    # ogrenciler / ogrenci listesi" gecerse, planner LLM bunu sezmemis bile
    # olsa expand_row_details:True yap. Claude'a guvenmek yerine deterministic.
    if "individual-lesson" in plan["page_path"].lower():
        q_lower = question.lower()
        _expand_triggers = [
            "kim katiliyor", "kim katılıyor", "kim katiliyor",
            "hangi ogrenci", "hangi öğrenci",
            "ogrenci listesi", "öğrenci listesi",
            "ogrenciler kim", "öğrenciler kim",
            "ogrencileri kim", "öğrencileri kim",
            "kimler katiliyor", "kimler katılıyor",
            "ogrencileri ver", "öğrencileri ver",
            "kim var",  # "yarın etutte kim var"
            "etudune kim", "etüdüne kim",
            "etudunde kim", "etüdünde kim",
            "katilimci", "katılımcı",
        ]
        if any(t in q_lower for t in _expand_triggers):
            plan["expand_row_details"] = True
            plan_only["expand_row_details"] = True
            logger.info(f"[PLANNER] expand_row_details OTO-True (keyword match)")

    # Navigate (1. deneme)
    from eyotek_knowledge.eyotek_navigator import navigate
    eff_max = max_rows or plan["max_rows"] or 30
    nav = await navigate(
        page_path=plan["page_path"],
        filters=plan["filters"],
        max_rows=eff_max,
        tab=plan.get("tab") or None,
        # 25.44-dev-meeting-5 (Neo 13 May 23:17): plan'da expand_row_details=true
        # ise her etut satirinin > popup'i acilip ogrenci listesi cekilir.
        # individual-lesson sayfasinda calisir; diger sayfalarda yoksayilir.
        expand_row_details=bool(plan.get("expand_row_details", False)),
    )

    attempts = [{
        "plan": plan_only,
        "error_code": nav.get("error_code"),
        "row_count": nav.get("row_count", 0),
    }]

    # 25.44 (Neo direktif): Re-plan loop — navigator yetersiz cevap dondurduyse
    # planner'a DOM ozetiyle geri sor, max 1 retry (toplam 2 deneme).
    needs_replan = False
    nav_err = nav.get("error_code")
    if nav_err in ("NO_DATA", "FILTER_BAD") or (nav.get("success") and nav.get("row_count", 0) == 0):
        needs_replan = True

    if needs_replan:
        # Planner'a DOM özeti + hata bilgisini ver, yeni plan iste
        replan_context = {
            "previous_plan": plan_only,
            "previous_page": plan["page_path"],
            "previous_error": nav.get("error_code"),
            "previous_row_count": nav.get("row_count", 0),
            "available_season": (nav.get("season") or {}).get("available", []),
            "current_season": (nav.get("season") or {}).get("current_label"),
            "dropdowns_summary": nav.get("dropdowns_summary", []),
            "page_hint": (nav.get("debug") or {}).get("page_hint", {}),
            "filters_failed": nav.get("filters_failed", []),
            "final_url": nav.get("final_url"),
        }
        # Replan: original soruyu + context'i tek bir prompt'a koy
        retry_question = (
            f"{question}\n\n"
            f"[ONCEKI DENEME YETERSIZ — yeniden planla]\n"
            f"Onceki sayfa: {plan['page_path']}\n"
            f"Hata: {nav.get('error_code')} (row_count={nav.get('row_count', 0)})\n"
            f"Sayfa tipi (hint): {replan_context['page_hint'].get('type', 'unknown')}\n"
            f"Sayfadaki mevcut sezon: {replan_context['current_season']}\n"
            f"Available sezonlar: {[s.get('label') for s in replan_context['available_season']]}\n"
            f"Kayan filter'lar (sayfada yok): {replan_context['filters_failed']}\n\n"
            f"FIX KURALI:\n"
            f"  - Onceki sayfa multi_season_aggregate ise spesifik sezon icin "
            f"Student/list-students KULLAN.\n"
            f"  - Filter'lar fail oldu ise daha sade filter (sadece tarih veya sezon) dene.\n"
            f"  - Tablo bos ise sezon: 'latest' veya tarihi degistir."
        )
        plan2 = await plan_query(retry_question)
        plan2_only = {k: v for k, v in plan2.items() if k != "raw_response"}
        # Yeni plan onceki ile aynıysa retry'a gerek yok
        same_plan = (
            plan2.get("page_path") == plan["page_path"]
            and plan2.get("filters", {}) == plan["filters"]
        )
        if not same_plan and plan2.get("page_path") and plan2.get("confidence", 0) >= 0.4:
            nav2 = await navigate(
                page_path=plan2["page_path"],
                filters=plan2["filters"],
                max_rows=eff_max,
                tab=plan2.get("tab") or None,
            )
            attempts.append({
                "plan": plan2_only,
                "error_code": nav2.get("error_code"),
                "row_count": nav2.get("row_count", 0),
            })
            # 2. deneme daha iyiyse onu kullan
            if nav2.get("success") and nav2.get("row_count", 0) > nav.get("row_count", 0):
                nav = nav2
                plan_only = plan2_only

    final_result = {
        "success": nav.get("success", False),
        "plan": plan_only,
        "page": (plan_only.get("page_path") or plan["page_path"]),
        "attempts": attempts,
        "filters_applied": nav.get("filters_applied", {}),
        "filters_failed":  nav.get("filters_failed", []),
        "columns": nav.get("columns", []),
        "rows":    nav.get("rows", []),
        "row_count": nav.get("row_count", 0),
        # 25.44 (Neo direktif): bot artık sayfadaki sezon listesini görür + taze veri timestamp
        "season":             nav.get("season"),
        "dropdowns_summary":  nav.get("dropdowns_summary", []),
        "sezon_resolved":     (nav.get("debug") or {}).get("sezon_resolved"),
        "page_hint":          (nav.get("debug") or {}).get("page_hint", {}),
        "season_skip_reason": (nav.get("debug") or {}).get("season_skip_reason"),
        "final_url":          nav.get("final_url"),
        "pagination":         nav.get("pagination"),  # 25.44: total_pages, pages_read, total_rows_seen
        "data_fetched_at":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "error_code": nav.get("error_code"),
        "error":      nav.get("error"),
    }

    # 25.44 iter4 (Neo 11 May 21:51): execute_query path'inde de lazy_sync çağır.
    # Önceden sadece fermat_core_agent._tool_eyotek_query'de vardı — manuel direct
    # çağrılarda (test/CLI) hook atlanıyordu, DB güncellenmiyordu.
    if final_result.get("success") and final_result.get("rows"):
        try:
            import sys as _sys
            from pathlib import Path as _Path
            _agent_root = _Path(__file__).resolve().parent.parent
            if str(_agent_root) not in _sys.path:
                _sys.path.insert(0, str(_agent_root))
            from eyotek_lazy_sync import lazy_sync_after_query
            sync_info = await lazy_sync_after_query(final_result)
            if sync_info.get("synced"):
                final_result["_lazy_synced"] = sync_info
        except Exception as _le:
            logger.debug(f"[execute_query] lazy_sync skip: {_le}")

    return final_result


# ─── CLI ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Eyotek Query Planner")
    parser.add_argument("question", nargs="?", help="Kullanici sorusu")
    parser.add_argument("--plan-only", action="store_true", help="Sadece plan goster, navigate etme")
    parser.add_argument("--catalog", action="store_true", help="DB catalog'unu goster")
    args = parser.parse_args()

    async def _main():
        if args.catalog:
            cat = await build_compact_catalog()
            print(_build_catalog_text(cat))
            return
        if not args.question:
            parser.print_help()
            return
        if args.plan_only:
            plan = await plan_query(args.question)
            print(json.dumps({k: v for k, v in plan.items() if k != "raw_response"},
                             ensure_ascii=False, indent=2))
            return
        result = await execute_query(args.question)
        # Print compact summary
        print(f"PLAN: {json.dumps(result['plan'], ensure_ascii=False)}")
        print(f"SUCCESS: {result['success']}")
        print(f"ROWS: {result.get('row_count', 0)}")
        if result.get("filters_applied"):
            print(f"FILTERS APPLIED: {result['filters_applied']}")
        if result.get("error"):
            print(f"ERROR: {result['error']}")
        print(f"COLUMNS: {result.get('columns', [])[:10]}")
        for row in (result.get("rows") or [])[:3]:
            print(f"  ROW: {row}")

    asyncio.run(_main())
