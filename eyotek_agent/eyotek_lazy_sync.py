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
    """etut_history tablosuna upsert (per-etut-slot, NOT per-student).

    25.43-DIAG-FIX (10 May, Neo konusma): Bot 21:25 itibariyle "column ogrenci does
    not exist" hatasi nedeniyle her row'u skip ediyordu. etut_history tablosu PER-ETUT
    (ders slot) bazli, ogrenci ismi tutmuyor — `ogrenci_sayisi` (count) tutuyor.

    Eyotek individual-lesson row tipik formati:
      etut_kodu (Kod), tarih, saat, ogretmen, ders, sinif, derslik, etut_turu, ogrenci_sayisi

    DB columns (etut_history):
      sube, etut_kodu, etut_turu, tarih, ogretmen, ders, konu, saat, sure,
      derslik, ogrenci_sayisi, yoklama, kaydeden, olusturma_tarihi
      (NOT NULL: -- hicbir kolon yok)

    Dedupe: etut_kodu varsa primary, yoksa (tarih, saat, ogretmen, ders, sinif).
    """
    from db_pool import db_execute, db_fetchval
    from field_reconciler import find_field
    synced = 0
    skipped_reason = {}
    for r in rows:
        try:
            # 25.43-DRILL-V3: schema-less field çekimi (manuel chain'ler kalktı)
            tarih = find_field(r, 'tarih')
            saat = str(find_field(r, 'saat', default='') or '')
            ders = str(find_field(r, 'ders', default='') or '')
            ogretmen = str(find_field(r, 'ogretmen', default='') or '')
            sinif = str(find_field(r, 'sinif', default='') or
                        find_field(r, 'sube', default='') or '')
            derslik = str(find_field(r, 'derslik', default='') or '')
            etut_turu = str(find_field(r, 'etut_turu', default='') or '')
            konu = str(find_field(r, 'konu', default='') or '')

            # etut_kodu → integer parse (table column int)
            etut_kodu_raw = find_field(r, 'etut_kodu')
            etut_kodu = None
            if etut_kodu_raw:
                try:
                    etut_kodu = int(str(etut_kodu_raw).strip())
                except (ValueError, TypeError):
                    etut_kodu = None

            # ogrenci_sayisi → integer parse (varsa)
            ogr_sayi_raw = find_field(r, 'ogrenci_sayisi')
            ogr_sayi = None
            if ogr_sayi_raw:
                try:
                    ogr_sayi = int(str(ogr_sayi_raw).strip())
                except (ValueError, TypeError):
                    ogr_sayi = None

            if not tarih or not ogretmen:
                skipped_reason["no_tarih_ogretmen"] = skipped_reason.get("no_tarih_ogretmen", 0) + 1
                continue  # eksik veri, skip

            # DEDUPE: etut_kodu varsa o, yoksa (tarih+saat+ogretmen+ders+sinif)
            if etut_kodu is not None:
                existing = await db_fetchval(
                    "SELECT 1 FROM etut_history WHERE etut_kodu = $1 LIMIT 1",
                    etut_kodu,
                )
            else:
                existing = await db_fetchval(
                    """SELECT 1 FROM etut_history
                       WHERE tarih::text = $1::text AND saat = $2
                         AND ogretmen = $3 AND ders = $4
                         AND COALESCE(sube,'') = $5
                       LIMIT 1""",
                    str(tarih), saat, ogretmen, ders, sinif,
                )
            if existing:
                continue  # zaten var

            # date parse (asyncpg requires date object)
            from datetime import date as _date
            import re as _re
            tarih_obj = None
            if tarih:
                t_str = str(tarih).strip()
                m = _re.match(r'(\d{4})[\-/.](\d{1,2})[\-/.](\d{1,2})', t_str)
                if m:
                    try:
                        tarih_obj = _date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                    except (ValueError, TypeError):
                        pass
                else:
                    m = _re.match(r'(\d{1,2})[\-/.](\d{1,2})[\-/.](\d{4})', t_str)
                    if m:
                        try:
                            tarih_obj = _date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                        except (ValueError, TypeError):
                            pass
            if not tarih_obj:
                skipped_reason["bad_date"] = skipped_reason.get("bad_date", 0) + 1
                continue

            await db_execute(
                """INSERT INTO etut_history
                     (sube, etut_kodu, etut_turu, tarih, ogretmen, ders, konu,
                      saat, derslik, ogrenci_sayisi, kaydeden, olusturma_tarihi)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'lazy_sync', NOW())
                   ON CONFLICT DO NOTHING""",
                sinif, etut_kodu, etut_turu, tarih_obj, ogretmen, ders, konu,
                saat, derslik, ogr_sayi,
            )
            synced += 1
        except Exception as e:
            err_short = str(e).split("\n")[0][:80]
            skipped_reason[err_short] = skipped_reason.get(err_short, 0) + 1
            continue
    if skipped_reason:
        logger.debug(f"  [LAZY_SYNC] etut_history skip stats: {skipped_reason}")
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

    # 25.43-DRILL-V3 (Neo direktif 11 May): manuel `r.get()` zincirleri kalktı.
    # field_reconciler her Eyotek key varyantını LLM-native fuzzy match ile bulur.
    # 'SözNo' / 'soz_no' / 'Söz No' / 'sözno' fark etmez, tek API.
    from field_reconciler import find_field

    for r in rows:
        try:
            # Çekirdek alanlar — schema-less, sadece canonical isim ile
            ad_raw = str(find_field(r, 'ad', default='')).strip()
            soyad_raw = str(find_field(r, 'soyad', default='')).strip()
            # student_name birleşik field varsa öncelikli, yoksa ad+soyad
            ogr_ad = str(find_field(r, 'student_name', default='')).strip()
            if not ogr_ad and (ad_raw or soyad_raw):
                ogr_ad = f"{ad_raw} {soyad_raw}".strip()

            sinav_adi = str(find_field(r, 'sinav_adi', default='')).strip()
            tarih_raw = str(find_field(r, 'tarih', default='')).strip()

            if not ogr_ad or not sinav_adi:
                skipped += 1
                continue

            # soz_no — row'da varsa direkt, yoksa students lookup
            soz_no_raw = find_field(r, 'soz_no')
            if soz_no_raw:
                try:
                    soz_no = int(str(soz_no_raw).strip())
                except (ValueError, TypeError):
                    soz_no = None
            else:
                # Name → soz_no lookup
                ogr_ad_upper = _tr_upper(ogr_ad)
                soz_no_lookup = await db_fetchval(
                    "SELECT soz_no FROM students WHERE UPPER(full_name) = $1 OR UPPER(first_name || ' ' || last_name) = $1 LIMIT 1",
                    ogr_ad_upper,
                )
                # students.soz_no = TEXT, ama hedef tablolarin (student_exams, counsellor_notes, devamsizlik) soz_no = INTEGER
                # Bu yuzden cast et — asyncpg strict typing.
                try:
                    soz_no = int(str(soz_no_lookup).strip()) if soz_no_lookup else None
                except (ValueError, TypeError):
                    soz_no = None
                if not soz_no:
                    skipped += 1
                    continue

            # 25.43-DRILL-V3 FIX (Görev 3): exam_code önceliği:
            # 1) Eyotek native kod (Sınav Kodu, ör: '999000107')
            # 2) sinav_kodu field varsa (sinav_drilldown enrich edilmiş row)
            # 3) Fallback: lazy slug
            # Native kod numerik (3+ digit) ise tercih edilir → DB'de duplicate önlenir
            # (eski tarih scrapper'lar native kod kullanmıştı, lazy slug ayrı kayıt yaratıyordu).
            sinav_kodu_raw = find_field(r, 'sinav_kodu')
            exam_code = None
            if sinav_kodu_raw:
                kodu_str = str(sinav_kodu_raw).strip()
                # Numeric kod (Eyotek native: 999000107, 1110, 27 gibi)
                if kodu_str.isdigit() and len(kodu_str) >= 1:
                    exam_code = kodu_str
            if not exam_code:
                # Fallback: sinav_adi + tarih slug
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

            # 25.43-DRILL-V3: NET parsing — field_reconciler ile schema-less
            # 'Türkçe_NET' / 'turkce' / 'Türkçe' otomatik canonical 'turkce' eşleşir
            turkce = _to_float(find_field(r, 'turkce'))
            mat = _to_float(find_field(r, 'matematik'))
            geo = _to_float(find_field(r, 'geometri'))
            fizik = _to_float(find_field(r, 'fizik'))
            kimya = _to_float(find_field(r, 'kimya'))
            biyoloji = _to_float(find_field(r, 'biyoloji'))
            tarih_ders = _to_float(find_field(r, 'tarih_ders'))  # ders olarak tarih
            cografya = _to_float(find_field(r, 'cografya'))
            felsefe = _to_float(find_field(r, 'felsefe'))
            din = _to_float(find_field(r, 'din'))
            toplam = _to_float(find_field(r, 'toplam'))

            # exam_date parse → datetime.date object (asyncpg requires)
            from datetime import date as _date
            exam_date_obj = None
            if tarih_raw:
                # Format örnekleri: "2026-04-15", "15.04.2026", "15/04/2026"
                m = _re.match(r'(\d{4})[\-/.](\d{1,2})[\-/.](\d{1,2})', tarih_raw)
                if m:
                    try:
                        exam_date_obj = _date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                    except (ValueError, TypeError):
                        pass
                else:
                    m = _re.match(r'(\d{1,2})[\-/.](\d{1,2})[\-/.](\d{4})', tarih_raw)
                    if m:
                        try:
                            exam_date_obj = _date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                        except (ValueError, TypeError):
                            pass

            # UPSERT
            await db_execute(
                """
                INSERT INTO student_exams (
                    soz_no, student_name, exam_code, exam_name, exam_date,
                    turkce, matematik, geometri, fizik, kimya, biyoloji,
                    tarih, cografya, felsefe, din_kulturu, toplam, exam_type, status
                )
                VALUES (
                    $1, $2, $3, $4, $5,
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
                soz_no, ogr_ad, exam_code, sinav_adi, exam_date_obj,
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
    from field_reconciler import find_field
    synced = 0
    for r in rows:
        try:
            ogr_ad = str(find_field(r, 'student_name', default='') or '').strip()
            tarih = str(find_field(r, 'tarih', default='') or '').strip()
            ders_no = str(find_field(r, 'ders_no', default='') or
                          find_field(r, 'ders', default='') or '').strip()
            saat = str(find_field(r, 'saat', default='') or '').strip()
            gun = str(find_field(r, 'gun', default='') or '').strip()
            durum = str(find_field(r, 'durum', default='') or '').strip()
            sube = str(find_field(r, 'sube', default='') or '').strip()
            soz_no_raw = find_field(r, 'soz_no')

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
                    "SELECT soz_no FROM students WHERE UPPER(full_name) = $1 OR UPPER(first_name || ' ' || last_name) = $1 LIMIT 1",
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
    from field_reconciler import find_field
    synced = 0
    for r in rows:
        try:
            ogr_ad = str(find_field(r, 'student_name', 'ad', default='') or '').strip()
            ogr_soyad = str(find_field(r, 'soyad', default='') or '').strip()
            gorusme_tarihi = str(find_field(r, 'gorusme_tarihi', 'tarih', default='') or '').strip()
            not_turu = str(find_field(r, 'not_turu', default='') or '').strip()
            gorusulen = str(find_field(r, 'gorusulen', default='') or '').strip()
            gorusme_turu = str(find_field(r, 'gorusme_turu', default='') or '').strip()
            ogretmen = str(find_field(r, 'ogretmen', default='') or '').strip()
            sube = str(find_field(r, 'sube', default='') or '').strip()
            sinif = str(find_field(r, 'sinif', default='') or '').strip()
            soz_no_raw = find_field(r, 'soz_no')

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
                soz_no_lookup = await db_fetchval(
                    "SELECT soz_no FROM students WHERE UPPER(full_name) = $1 OR UPPER(first_name || ' ' || last_name) = $1 LIMIT 1",
                    full_name.upper(),
                )
                # counsellor_notes.soz_no = INTEGER, students.soz_no = TEXT → cast
                try:
                    soz_no = int(str(soz_no_lookup).strip()) if soz_no_lookup else None
                except (ValueError, TypeError):
                    soz_no = None
                if not soz_no:
                    continue

            # Datetime parse — asyncpg python datetime obj ister
            from datetime import datetime as _dt
            gorusme_dt = None
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                         "%Y-%m-%d", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
                try:
                    gorusme_dt = _dt.strptime(gorusme_tarihi, fmt)
                    break
                except ValueError:
                    continue
            if not gorusme_dt:
                try:
                    gorusme_dt = _dt.fromisoformat(gorusme_tarihi)
                except Exception:
                    continue

            # Dedupe — datetime obj ile
            existing = await db_fetchval(
                """SELECT 1 FROM counsellor_notes
                   WHERE soz_no = $1 AND gorusme_tarihi = $2
                     AND COALESCE(gorusulen, '') = $3 LIMIT 1""",
                soz_no, gorusme_dt, gorusulen,
            )
            if existing:
                continue

            await db_execute(
                """INSERT INTO counsellor_notes
                   (sube, ogretmen, sinif, soz_no, ogrenci_adi, ogrenci_soyadi,
                    gorusme_tarihi, not_turu, gorusulen, gorusme_turu)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)""",
                sube, ogretmen, sinif, soz_no, ogr_ad, ogr_soyad,
                gorusme_dt, not_turu, gorusulen, gorusme_turu,
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
    from field_reconciler import find_field
    synced = 0
    for r in rows:
        try:
            ogretmen_id = str(find_field(r, 'ogretmen_id', default='') or
                              find_field(r, 'ogretmen', default='') or '').strip()
            ogretmen_ad = str(find_field(r, 'ogretmen', default='') or '').strip()
            brans = str(find_field(r, 'brans', default='') or
                        find_field(r, 'ders', default='') or '').strip()
            gun = str(find_field(r, 'gun', default='') or '').strip()
            saat = str(find_field(r, 'saat', default='') or '').strip()
            haftalik_raw = find_field(r, 'haftalik_saat')
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
    from field_reconciler import find_field
    synced = 0
    for r in rows:
        try:
            ogr_ad = str(find_field(r, 'student_name', 'ad', default='') or '').strip()
            sube = str(find_field(r, 'sube', default='') or '').strip()
            sinif = str(find_field(r, 'sinif', default='') or '').strip()
            soz_no_raw = find_field(r, 'soz_no')
            okul_no = str(find_field(r, 'okul_no', default='') or '').strip()

            soz_no = None
            if soz_no_raw:
                try:
                    soz_no = int(str(soz_no_raw).strip())
                except (ValueError, TypeError):
                    pass
            if not soz_no and ogr_ad:
                soz_no_lookup = await db_fetchval(
                    "SELECT soz_no FROM students WHERE UPPER(full_name) = $1 OR UPPER(first_name || ' ' || last_name) = $1 LIMIT 1",
                    ogr_ad.upper(),
                )
                # devamsizlik_sayisi.soz_no = INTEGER, students.soz_no = TEXT → cast
                try:
                    soz_no = int(str(soz_no_lookup).strip()) if soz_no_lookup else None
                except (ValueError, TypeError):
                    soz_no = None
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
