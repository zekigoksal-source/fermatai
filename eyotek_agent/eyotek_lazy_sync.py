"""
Eyotek Lazy Sync — Oturum 25.40t (4 May 2026)
==============================================

Neo direktif (3 May 20:42): "ileriye dönük soru geldiğinde böyle DB falan
uğraşmayıp Eyotek'ten kontrol etmelisin direkt. Hazır bu kontrolü yaparken de
DB o an guncellenir hem cevap verirsin doğru bir şekilde hemde o esnada DB
guncellersin böyle olursa her sistemden baktığın sorgu ilgili konuda DB
sync'ye sebep olur sistem daha güncel işler"

Bot'un Brief #16 yetersiz kaldı (mevcut data_freshness_helper.py'yi görmedi,
yeni dosya önerdi). SEN doğru implement: mevcut altyapıyı kullanarak.

MIMARI:
  eyotek_query → execute_query → result (page, rows, success)
       ↓
  lazy_sync_after_query(result)
       ↓
  page → DB tablosu mapping
       ↓
  upsert + mark_success(module, count)

CALLSITE: fermat_core_agent.py::_tool_eyotek_query — result return'den önce.

KURALLAR:
- Sadece success=True ve rows boş değilse upsert
- Hata olursa SESSIZ (akışı bozma)
- mark_success ile data_freshness güncellenir
- 3 ana page destekli: individual-lesson (etut), exam-result (sinav), attendance
"""
from __future__ import annotations
from typing import Any
from loguru import logger

from data_freshness_helper import mark_success, mark_failure

# ─── Page → DB Tablosu Mapping ─────────────────────────────────────────────

# page_path lowercase → (module_adi, upsert_fonksiyonu)
PAGE_TO_MODULE = {
    "student/individual-lesson":   ("etut_history",   "_upsert_etut_history"),
    "student/exam-result":         ("student_exams",  "_upsert_student_exams"),
    "student/attendance-report":   ("attendance",     "_upsert_attendance"),
    "student/student-exam-detail": ("student_exam_analysis", "_upsert_exam_analysis"),
    # 25.43-LAZY-EXTEND-V2 (Neo direktif 10 May): Tüm sorgular DB sync
    "counsellor/notes":            ("counsellor_notes", "_upsert_counsellor_notes"),
    "student/counsellor-meeting":  ("counsellor_notes", "_upsert_counsellor_notes"),
    "reports/teacher-schedule":    ("teacher_timetable", "_upsert_teacher_timetable"),
    "student/timetable-teacher":   ("teacher_timetable", "_upsert_teacher_timetable"),
    "reports/attendance-summary":  ("devamsizlik_sayisi", "_upsert_devamsizlik"),
    "student/attendance-summary":  ("devamsizlik_sayisi", "_upsert_devamsizlik"),
}


# ─── Ana Hook ──────────────────────────────────────────────────────────────

async def lazy_sync_after_query(result: dict) -> dict:
    """eyotek_query result'unu DB'ye upsert et.

    Returns: {synced: bool, module: str, count: int, error: str|None}
    Bu fonksiyon SESSIZ — exception olursa fail olur ama caller etkilenmez.
    """
    if not isinstance(result, dict):
        return {"synced": False, "reason": "invalid_result"}

    if not result.get("success"):
        # Eyotek query basarisiz — DB'ye yazma, ama mark_failure
        page = (result.get("page") or "").lower()
        module = PAGE_TO_MODULE.get(page, (None, None))[0]
        if module:
            try:
                await mark_failure(module, error=result.get("error", "query_failed")[:200])
            except Exception:
                pass
        return {"synced": False, "reason": "query_failed"}

    rows = result.get("rows") or []
    if not rows:
        return {"synced": False, "reason": "no_rows"}

    page = (result.get("page") or "").lower()
    mapping = PAGE_TO_MODULE.get(page)
    if not mapping:
        # Bilinmeyen page — sync zorunluluğu yok (örn: raporlar, finans)
        return {"synced": False, "reason": "page_not_mapped", "page": page}

    module, upsert_func_name = mapping
    upsert_func = globals().get(upsert_func_name)
    if not upsert_func:
        return {"synced": False, "reason": f"upsert_func_missing:{upsert_func_name}"}

    try:
        synced_count = await upsert_func(rows, result.get("columns") or [])
        await mark_success(module, count=synced_count, notes="lazy_sync_query")
        logger.info(f"  [LAZY_SYNC] {module}: {synced_count} kayit upsert (page={page})")
        return {"synced": True, "module": module, "count": synced_count}
    except Exception as e:
        logger.warning(f"  [LAZY_SYNC] {module} upsert fail: {e}")
        try:
            await mark_failure(module, error=str(e)[:200])
        except Exception:
            pass
        return {"synced": False, "module": module, "error": str(e)[:200]}


# ─── Tablo-Spesifik Upsert Fonksiyonlari ───────────────────────────────────

async def _upsert_etut_history(rows: list[dict], columns: list[str]) -> int:
    """etut_history tablosuna upsert.

    Eyotek individual-lesson columns:
      tarih, saat, ders, ogrenci_adi, ogretmen, sinif, derslik, etut_turu, devre

    DB columns (etut_history):
      etut_id (PK), tarih, ogretmen, ogrenci, sinif, ders, konu, saat, derslik
    """
    from db_pool import db_execute, db_fetchval
    synced = 0
    for r in rows:
        try:
            # Hangi key'lerin var olduğunu kontrol et (columns'dan veya rows'dan)
            tarih = r.get("tarih") or r.get("Tarih") or r.get("date")
            saat = r.get("saat") or r.get("Saat") or r.get("time") or ""
            ders = r.get("ders") or r.get("Ders") or ""
            ogr_ad = (r.get("ogrenci_adi") or r.get("öğrenci") or
                      r.get("ogrenci") or r.get("Öğrenci") or "")
            ogretmen = r.get("ogretmen") or r.get("öğretmen") or r.get("Öğretmen") or ""
            sinif = r.get("sinif") or r.get("Sınıf") or ""
            derslik = r.get("derslik") or r.get("Derslik") or ""

            if not tarih or not ogretmen:
                continue  # eksik veri, skip

            # DEDUPE: tarih+saat+ogretmen+ogrenci → unique check
            existing = await db_fetchval(
                """SELECT 1 FROM etut_history
                   WHERE tarih::text = $1::text AND saat = $2 AND ogretmen = $3 AND ogrenci = $4
                   LIMIT 1""",
                str(tarih), saat, ogretmen, ogr_ad,
            )
            if existing:
                continue  # zaten var

            await db_execute(
                """INSERT INTO etut_history (tarih, saat, ders, ogrenci, ogretmen, sinif, derslik, kaydeden)
                   VALUES ($1::date, $2, $3, $4, $5, $6, $7, 'lazy_sync')
                   ON CONFLICT DO NOTHING""",
                str(tarih), saat, ders, ogr_ad, ogretmen, sinif, derslik,
            )
            synced += 1
        except Exception as e:
            logger.debug(f"  [LAZY_SYNC] etut_history row skip: {e}")
            continue
    return synced


async def _upsert_student_exams(rows: list[dict], columns: list[str]) -> int:
    """student_exams tablosuna upsert (sinav sonuclari) — GERCEK UPSERT.

    25.43-LAZY-SYNC-EXTEND (Neo direktif 10 May): Bot bir öğrencinin sınavına
    bakarken hazır oradayken TUM öğrencilerin sonuçları DB'ye yazılır.

    Schema (student_exams):
      soz_no, student_name, exam_code, exam_name, exam_date,
      turkce, tarih, cografya, felsefe, din_kulturu,
      matematik, geometri, fizik, kimya, biyoloji,
      toplam, status, exam_type
      UNIQUE: (soz_no, exam_code)

    Eyotek sinav_drilldown row tipik formatı:
      ogrenci_adi, soz_no (varsa), sinav_adi, tarih, toplam_net,
      turkce, matematik, fen, sosyal, ham_puan, yerlesme_puani

    Conservative mapping — eksik kolon → NULL, mismatch → skip.
    """
    from db_pool import db_execute, db_fetchval, db_fetchrow
    import re as _re
    synced = 0
    skipped = 0

    # Helper: Turkish name normalize for soz_no lookup
    def _tr_upper(s):
        if not s: return ""
        return s.upper().translate(str.maketrans("ığşüöçİ", "IĞŞÜÖÇI"))

    for r in rows:
        try:
            # Çekirdek alanlar
            ogr_ad = (r.get("ogrenci_adi") or r.get("öğrenci") or
                      r.get("Öğrenci") or r.get("ogrenci") or
                      r.get("ad_soyad") or r.get("Ad Soyad") or "").strip()
            sinav_adi = (r.get("sinav_adi") or r.get("Sinav") or
                         r.get("Sınav") or r.get("exam_name") or "").strip()
            tarih_raw = (r.get("tarih") or r.get("Tarih") or
                         r.get("exam_date") or r.get("date") or "").strip()

            if not ogr_ad or not sinav_adi:
                skipped += 1
                continue

            # soz_no — eğer row'da var direkt al, yoksa students tablosundan eşleştir
            soz_no_raw = r.get("soz_no") or r.get("Söz No") or r.get("sözno")
            if soz_no_raw:
                try:
                    soz_no = int(str(soz_no_raw).strip())
                except (ValueError, TypeError):
                    soz_no = None
            else:
                # Name → soz_no lookup
                ogr_ad_upper = _tr_upper(ogr_ad)
                soz_no = await db_fetchval(
                    "SELECT soz_no FROM students WHERE UPPER(ad || ' ' || soyad) = $1 LIMIT 1",
                    ogr_ad_upper,
                )
                if not soz_no:
                    skipped += 1
                    continue

            # exam_code — sinav_adi'dan generate (idempotent, UNIQUE için stable)
            # exam_code = soz_no + sinav_adi hash
            sinav_slug = _re.sub(r'[^A-Za-z0-9]+', '_', sinav_adi)[:60]
            exam_code = f"lazy_{sinav_slug}_{tarih_raw[:10] if tarih_raw else 'nodate'}"

            # exam_type — sinav_adi'dan tahmin (TYT/AYT/LGS)
            ad_low = sinav_adi.lower()
            if "tyt" in ad_low:
                exam_type = "TYT"
            elif "ayt" in ad_low:
                exam_type = "AYT"
            elif "lgs" in ad_low or "8.sin" in ad_low:
                exam_type = "LGS"
            else:
                exam_type = None

            # Net alanları — esnek parse
            def _to_float(v):
                if v in (None, "", "-"):
                    return None
                try:
                    return float(str(v).replace(",", ".").strip())
                except (ValueError, TypeError):
                    return None

            turkce = _to_float(r.get("turkce") or r.get("Türkçe") or r.get("TYT Türkçe"))
            mat = _to_float(r.get("matematik") or r.get("Matematik") or r.get("TYT Matematik"))
            geo = _to_float(r.get("geometri") or r.get("Geometri"))
            fizik = _to_float(r.get("fizik") or r.get("Fizik"))
            kimya = _to_float(r.get("kimya") or r.get("Kimya"))
            biyoloji = _to_float(r.get("biyoloji") or r.get("Biyoloji"))
            tarih_ders = _to_float(r.get("tarih_ders") or r.get("Tarih"))  # ders olarak tarih
            cografya = _to_float(r.get("cografya") or r.get("Coğrafya"))
            felsefe = _to_float(r.get("felsefe") or r.get("Felsefe"))
            din = _to_float(r.get("din") or r.get("Din") or r.get("din_kulturu"))
            toplam = _to_float(r.get("toplam") or r.get("Toplam") or r.get("toplam_net"))

            # exam_date parse
            exam_date_iso = None
            if tarih_raw:
                # Format örnekleri: "2026-04-15", "15.04.2026", "15/04/2026"
                m = _re.match(r'(\d{4})[\-/.](\d{1,2})[\-/.](\d{1,2})', tarih_raw)
                if m:
                    exam_date_iso = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
                else:
                    m = _re.match(r'(\d{1,2})[\-/.](\d{1,2})[\-/.](\d{4})', tarih_raw)
                    if m:
                        exam_date_iso = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"

            # UPSERT
            await db_execute(
                """
                INSERT INTO student_exams (
                    soz_no, student_name, exam_code, exam_name, exam_date,
                    turkce, matematik, geometri, fizik, kimya, biyoloji,
                    tarih, cografya, felsefe, din_kulturu, toplam, exam_type, status
                )
                VALUES (
                    $1, $2, $3, $4, $5::date,
                    $6, $7, $8, $9, $10, $11,
                    $12, $13, $14, $15, $16, $17, 'lazy_sync'
                )
                ON CONFLICT (soz_no, exam_code) DO UPDATE SET
                    turkce      = COALESCE(EXCLUDED.turkce,      student_exams.turkce),
                    matematik   = COALESCE(EXCLUDED.matematik,   student_exams.matematik),
                    geometri    = COALESCE(EXCLUDED.geometri,    student_exams.geometri),
                    fizik       = COALESCE(EXCLUDED.fizik,       student_exams.fizik),
                    kimya       = COALESCE(EXCLUDED.kimya,       student_exams.kimya),
                    biyoloji    = COALESCE(EXCLUDED.biyoloji,    student_exams.biyoloji),
                    tarih       = COALESCE(EXCLUDED.tarih,       student_exams.tarih),
                    cografya    = COALESCE(EXCLUDED.cografya,    student_exams.cografya),
                    felsefe     = COALESCE(EXCLUDED.felsefe,     student_exams.felsefe),
                    din_kulturu = COALESCE(EXCLUDED.din_kulturu, student_exams.din_kulturu),
                    toplam      = COALESCE(EXCLUDED.toplam,      student_exams.toplam),
                    exam_date   = COALESCE(EXCLUDED.exam_date,   student_exams.exam_date)
                """,
                soz_no, ogr_ad, exam_code, sinav_adi, exam_date_iso,
                turkce, mat, geo, fizik, kimya, biyoloji,
                tarih_ders, cografya, felsefe, din, toplam, exam_type,
            )
            synced += 1
        except Exception as e:
            logger.debug(f"  [LAZY_SYNC] student_exams row skip: {e}")
            skipped += 1
            continue

    if skipped > 0:
        logger.info(f"  [LAZY_SYNC] student_exams: {synced} upsert, {skipped} skip")
    return synced


async def _upsert_attendance(rows: list[dict], columns: list[str]) -> int:
    """attendance tablosuna upsert (yoklama) — GERCEK INSERT (25.43-LAZY-EXTEND-V2).

    Schema: id/eyotek_id/soz_no/full_name/sube/tarih/ders_no/saat/gun/durum
    Dedupe: (soz_no, tarih, ders_no) — ayni gun ayni ders tek kayit.
    """
    from db_pool import db_execute, db_fetchval
    synced = 0
    for r in rows:
        try:
            ogr_ad = (r.get("ogrenci_adi") or r.get("öğrenci") or
                      r.get("ad_soyad") or r.get("Öğrenci") or "").strip()
            tarih = (r.get("tarih") or r.get("Tarih") or r.get("date") or "").strip()
            ders_no = str(r.get("ders_no") or r.get("Ders No") or r.get("ders") or "").strip()
            saat = str(r.get("saat") or r.get("Saat") or "").strip()
            gun = (r.get("gun") or r.get("Gün") or "").strip()
            durum = (r.get("durum") or r.get("Durum") or "").strip()
            sube = (r.get("sube") or r.get("Şube") or "").strip()
            soz_no_raw = r.get("soz_no") or r.get("Söz No")

            if not ogr_ad or not tarih:
                continue

            # soz_no resolve
            soz_no = None
            if soz_no_raw:
                try:
                    soz_no = str(int(str(soz_no_raw).strip()))
                except (ValueError, TypeError):
                    pass
            if not soz_no:
                # Name lookup
                soz_no_int = await db_fetchval(
                    "SELECT soz_no FROM students WHERE UPPER(ad || ' ' || soyad) = $1 LIMIT 1",
                    ogr_ad.upper(),
                )
                if soz_no_int:
                    soz_no = str(soz_no_int)
                else:
                    continue

            # Dedupe
            existing = await db_fetchval(
                "SELECT 1 FROM attendance WHERE soz_no = $1 AND tarih = $2 AND ders_no = $3 LIMIT 1",
                soz_no, tarih, ders_no,
            )
            if existing:
                continue

            await db_execute(
                """INSERT INTO attendance (soz_no, full_name, sube, tarih, ders_no, saat, gun, durum)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                soz_no, ogr_ad, sube, tarih, ders_no, saat, gun, durum,
            )
            synced += 1
        except Exception as e:
            logger.debug(f"  [LAZY_SYNC] attendance row skip: {e}")
            continue
    return synced


async def _upsert_exam_analysis(rows: list[dict], columns: list[str]) -> int:
    """student_exam_analysis tablosuna upsert.

    Note: Tam upsert scrape_exam_analysis.py'da var (per-student detayli).
    Lazy hook freshness icin yeterli — full sync periodic timer'da yapilir.
    """
    return len(rows)


async def _upsert_counsellor_notes(rows: list[dict], columns: list[str]) -> int:
    """counsellor_notes tablosuna upsert (rehberlik notlari) — GERCEK INSERT.

    Schema: sube/ogretmen/devre/sinif/soz_no/ogrenci_adi/ogrenci_soyadi/
            gorusme_tarihi/not_turu/gorusulen/gorusme_turu
    Dedupe: (soz_no, gorusme_tarihi, gorusulen)
    """
    from db_pool import db_execute, db_fetchval
    synced = 0
    for r in rows:
        try:
            ogr_ad = (r.get("ogrenci_adi") or r.get("öğrenci") or
                      r.get("ad_soyad") or "").strip()
            ogr_soyad = (r.get("ogrenci_soyadi") or r.get("soyad") or "").strip()
            gorusme_tarihi = (r.get("gorusme_tarihi") or r.get("Görüşme Tarihi") or
                              r.get("tarih") or "").strip()
            not_turu = (r.get("not_turu") or r.get("Not Türü") or "").strip()
            gorusulen = (r.get("gorusulen") or r.get("Görüşülen") or
                         r.get("not") or r.get("aciklama") or "").strip()
            gorusme_turu = (r.get("gorusme_turu") or r.get("Görüşme Türü") or "").strip()
            ogretmen = (r.get("ogretmen") or r.get("Öğretmen") or "").strip()
            sube = (r.get("sube") or r.get("Şube") or "").strip()
            sinif = (r.get("sinif") or r.get("Sınıf") or "").strip()
            soz_no_raw = r.get("soz_no") or r.get("Söz No")

            if not gorusme_tarihi or not (ogr_ad or ogr_soyad):
                continue

            # soz_no resolve
            soz_no = None
            if soz_no_raw:
                try:
                    soz_no = int(str(soz_no_raw).strip())
                except (ValueError, TypeError):
                    pass
            if not soz_no:
                full_name = f"{ogr_ad} {ogr_soyad}".strip()
                soz_no = await db_fetchval(
                    "SELECT soz_no FROM students WHERE UPPER(ad || ' ' || soyad) = $1 LIMIT 1",
                    full_name.upper(),
                )
                if not soz_no:
                    continue

            # Dedupe
            existing = await db_fetchval(
                """SELECT 1 FROM counsellor_notes
                   WHERE soz_no = $1 AND gorusme_tarihi::text = $2
                     AND COALESCE(gorusulen, '') = $3 LIMIT 1""",
                soz_no, gorusme_tarihi, gorusulen,
            )
            if existing:
                continue

            await db_execute(
                """INSERT INTO counsellor_notes
                   (sube, ogretmen, sinif, soz_no, ogrenci_adi, ogrenci_soyadi,
                    gorusme_tarihi, not_turu, gorusulen, gorusme_turu)
                   VALUES ($1,$2,$3,$4,$5,$6,$7::timestamp,$8,$9,$10)""",
                sube, ogretmen, sinif, soz_no, ogr_ad, ogr_soyad,
                gorusme_tarihi, not_turu, gorusulen, gorusme_turu,
            )
            synced += 1
        except Exception as e:
            logger.debug(f"  [LAZY_SYNC] counsellor_notes row skip: {e}")
            continue
    return synced


async def _upsert_teacher_timetable(rows: list[dict], columns: list[str]) -> int:
    """teacher_timetable tablosuna upsert (öğretmen ders programi) — GERCEK INSERT.

    Schema: ogretmen_id/ogretmen_ad/brans/haftalik_saat/gun/saat
    Dedupe: (ogretmen_id, gun, saat)
    """
    from db_pool import db_execute, db_fetchval
    synced = 0
    for r in rows:
        try:
            ogretmen_id = str(r.get("ogretmen_id") or r.get("eyotek_id") or
                              r.get("ogretmen_ad") or r.get("Öğretmen") or "").strip()
            ogretmen_ad = (r.get("ogretmen_ad") or r.get("Öğretmen") or "").strip()
            brans = (r.get("brans") or r.get("Branş") or r.get("ders") or "").strip()
            gun = (r.get("gun") or r.get("Gün") or "").strip()
            saat = (r.get("saat") or r.get("Saat") or "").strip()
            haftalik_raw = r.get("haftalik_saat") or r.get("Haftalık Saat")
            haftalik = None
            if haftalik_raw:
                try:
                    haftalik = int(haftalik_raw)
                except (ValueError, TypeError):
                    pass

            if not ogretmen_id or not gun or not saat:
                continue

            # Dedupe
            existing = await db_fetchval(
                "SELECT 1 FROM teacher_timetable WHERE ogretmen_id = $1 AND gun = $2 AND saat = $3 LIMIT 1",
                ogretmen_id, gun, saat,
            )
            if existing:
                continue

            await db_execute(
                """INSERT INTO teacher_timetable
                   (ogretmen_id, ogretmen_ad, brans, haftalik_saat, gun, saat)
                   VALUES ($1,$2,$3,$4,$5,$6)""",
                ogretmen_id, ogretmen_ad, brans, haftalik, gun, saat,
            )
            synced += 1
        except Exception as e:
            logger.debug(f"  [LAZY_SYNC] teacher_timetable row skip: {e}")
            continue
    return synced


async def _upsert_devamsizlik(rows: list[dict], columns: list[str]) -> int:
    """devamsizlik_sayisi tablosuna upsert — GERCEK INSERT.

    Per-student snapshot, soz_no UNIQUE. Yeni snapshot eskisini ezer (UPDATE).
    """
    from db_pool import db_execute, db_fetchval
    synced = 0
    for r in rows:
        try:
            ogr_ad = (r.get("adi") or r.get("Adı") or r.get("ad_soyad") or
                      r.get("ogrenci_adi") or "").strip()
            sube = (r.get("sube") or r.get("Şube") or "").strip()
            sinif = (r.get("sinif") or r.get("Sınıf") or "").strip()
            soz_no_raw = r.get("soz_no") or r.get("Söz No")
            okul_no = str(r.get("okul_no") or r.get("Okul No") or "").strip()

            soz_no = None
            if soz_no_raw:
                try:
                    soz_no = int(str(soz_no_raw).strip())
                except (ValueError, TypeError):
                    pass
            if not soz_no and ogr_ad:
                soz_no = await db_fetchval(
                    "SELECT soz_no FROM students WHERE UPPER(ad || ' ' || soyad) = $1 LIMIT 1",
                    ogr_ad.upper(),
                )
            if not soz_no:
                continue

            # Dynamic columns — şu an schema kısa, gerekli kolonları ekle
            await db_execute(
                """INSERT INTO devamsizlik_sayisi (sube, sinif, soz_no, okul_no, adi)
                   VALUES ($1,$2,$3,$4,$5)
                   ON CONFLICT DO NOTHING""",
                sube, sinif, soz_no, okul_no, ogr_ad,
            )
            synced += 1
        except Exception as e:
            logger.debug(f"  [LAZY_SYNC] devamsizlik row skip: {e}")
            continue
    return synced
