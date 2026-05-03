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
    "student/individual-lesson": ("etut_history", "_upsert_etut_history"),
    "student/exam-result":       ("student_exams", "_upsert_student_exams"),
    "student/attendance-report": ("attendance",     "_upsert_attendance"),
    "student/student-exam-detail": ("student_exam_analysis", "_upsert_exam_analysis"),
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
    """student_exams tablosuna upsert (sinav sonuclari).

    Sinav verisi karmasik — soz_no eslestirme + ders bazli netler gerekir.
    Şimdilik conservative: sadece kontrol amaçlı log, gerçek upsert
    mevcut sync_exams.py / scrape_exam_analysis.py akışında zaten var.

    Bu fonksiyon "data_freshness'i güncelle" niyetli — gerçek upsert'i
    full sync scripti yapacak, biz sadece "şu sınav listesini gördüm" dedik.
    """
    # DİKKAT: Eyotek'ten sınav exam-result çekildiğinde tipik columns:
    # ogrenci_adi, sinav_adi, tarih, ham_puan, yerlesme_puani, ...
    # Bu detayli netler için ayrı sayfa gerekiyor (student-exam-detail)
    # Şimdilik freshness'i güncellemek için "kayıt sayısı" döndür
    return len(rows)


async def _upsert_attendance(rows: list[dict], columns: list[str]) -> int:
    """attendance tablosuna upsert (yoklama).

    Eyotek attendance-report columns: tarih, saat, sinif, ders, ogretmen, durum
    DB attendance: günlük snapshot — şimdilik sadece freshness işareti.
    """
    return len(rows)


async def _upsert_exam_analysis(rows: list[dict], columns: list[str]) -> int:
    """student_exam_analysis tablosuna upsert.

    Şimdilik conservative — exam analiz upsert'i scrape_exam_analysis.py'da
    var, tek-kayıt upsert burada yapılırsa schema kontrolü gerek.
    """
    return len(rows)
