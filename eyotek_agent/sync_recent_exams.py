"""
Auto Eyotek -> DB Sinav Sync (Oturum 25.29)
==============================================

Yeni sinavlar otomatik student_exams tablosuna akar.
Akış:
  1. Eyotek `Student/test-transferred` (son N gun)
  2. Her sinav icin: DB'de exam_code zaten var mi?
  3. Yoksa: `sinav_drilldown` ile dynamic-list -> hazir liste -> ARA -> GridView1 oku
  4. Türkçe_NET / Matematik_NET / Fizik_NET ... kolonlarini map et -> upsert
  5. exam_log tablosuna kayit (ne zaman + kac sinav + kac kayit)

Periyot: precompute_nightly.py icinden cagiriliyor (her gece 03:00).
Manuel:  python sync_recent_exams.py [--days N] [--dry-run]

KRITIK: Onaysiz WP mesaji gondermez. Sadece DB'ye yazar.
        Neo'ya bildirim icin sistem_ayar.SYNC_NOTIFY_NEO_WP=true gerekli.
"""
from __future__ import annotations
import argparse
import asyncio
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from loguru import logger

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))

# Ders adi varyantlarini DB kolonuna map (lowercase, no diacritic)
_SUBJECT_MAP = {
    "turkce": "turkce",
    "tarih": "tarih",
    "cografya": "cografya",
    "felsefe": "felsefe",
    "din": "din_kulturu",       # DinKültürü, Din Kult, Din Kulturu
    "dinkulturu": "din_kulturu",
    "dinkultur": "din_kulturu",
    "matematik": "matematik",
    "geometri": "geometri",
    "fizik": "fizik",
    "kimya": "kimya",
    "biyoloji": "biyoloji",
    # AYT kolonlari da ayni isim ile gelir
}

# Turkce karakter -> ASCII (hem buyuk hem kucuk)
_TR_ASCII = str.maketrans({
    "ç": "c", "Ç": "c", "ğ": "g", "Ğ": "g",
    "ı": "i", "İ": "i", "I": "i",
    "ö": "o", "Ö": "o", "ş": "s", "Ş": "s",
    "ü": "u", "Ü": "u",
})


def _normalize_subject(col: str) -> Optional[str]:
    """`Türkçe_NET` -> `turkce`. None doner ders bilinmiyorsa."""
    if not col or "_NET" not in col:
        return None
    base = col.split("_NET")[0]
    base = base.translate(_TR_ASCII).lower()
    base = re.sub(r"[^a-z]", "", base)
    return _SUBJECT_MAP.get(base)


def _parse_net(val: Any) -> Optional[float]:
    """`28,50` -> 28.5. Bos / hata -> None."""
    if val is None:
        return None
    s = str(val).strip().replace(",", ".")
    if not s or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_exam_date(s: str) -> Optional[date]:
    """`22.04.2026` veya `2026-04-22` -> date."""
    if not s:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


# ─── EYOTEK: SON SINAV LISTESI ───────────────────────────────────────────────
async def list_recent_exams(days: int = 30) -> list[dict]:
    """`Student/test-transferred` sayfasindan son N gunun sinavlarini cek.

    Returns: [{exam_code, exam_name, exam_date(date), exam_type, sube}]
    """
    from playwright.async_api import async_playwright
    from eyotek_knowledge.eyotek_navigator import (
        _CDP_URL, _inject_cookies, _is_login,
        _open_search_modal, _fill_text_input, _click_search,
    )

    rows_out: list[dict] = []
    pw = None
    page = None
    browser = None
    try:
        # 25.41 (Neo bug 7 May): VPS'te CDP yok — headless launch
        from eyotek_browser_helper import get_eyotek_page
        browser, ctx, page = await get_eyotek_page()
        await page.goto("https://fermat.eyotek.com/v1/Pages/Student/test-transferred",
                        timeout=20000, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        if await _is_login(page):
            logger.error("[SYNC] Eyotek session expired")
            return []

        await _open_search_modal(page)
        await page.wait_for_timeout(1000)
        from_d = (date.today() - timedelta(days=days)).strftime("%d.%m.%Y")
        to_d = date.today().strftime("%d.%m.%Y")
        await _fill_text_input(page, ["#txtKayitBas"], from_d)
        await _fill_text_input(page, ["#txtKayitBit"], to_d)
        await _click_search(page)
        await page.wait_for_timeout(4500)

        # GridView1 satirlari — sutunlar: ?, Sube, Tarih, Kod, Tur, Kategori, Adi
        info = await page.evaluate(
            """() => {
                const tbls = Array.from(document.querySelectorAll('table'));
                const grid = tbls.find(t => (t.id||'').toLowerCase().includes('gridview'))
                          || tbls.find(t => t.querySelectorAll('tbody tr').length > 0
                                            && !((t.className||'').includes('checkbox-list')));
                if (!grid) return [];
                const rows = Array.from(grid.querySelectorAll('tbody tr'));
                return rows.map(tr => Array.from(tr.cells).map(c => (c.innerText||'').trim()));
            }"""
        )
        for cells in info:
            if len(cells) < 7:
                continue
            sube = cells[1]
            tarih = cells[2]
            kod = cells[3]
            tur = cells[4]
            kategori = cells[5]
            adi = cells[6]
            if not adi or not kod:
                continue
            d = _parse_exam_date(tarih)
            if not d:
                continue
            rows_out.append({
                "exam_code": kod.strip(),
                "exam_name": adi.strip(),
                "exam_date": d,
                "exam_type": (tur or "").strip(),
                "sube": (sube or "").strip(),
            })
    except Exception as e:
        logger.exception(f"[SYNC] list_recent_exams fail: {e}")
    finally:
        try:
            if page:
                await page.close()
        except Exception:
            pass
        # 25.41: helper browser'ı kapat (CDP'ye bağlı değil artık, kendi browser)
        try:
            if browser:
                await browser.close()
        except Exception:
            pass
        try:
            if pw:
                await pw.stop()
        except Exception:
            pass

    return rows_out


# ─── DB ───────────────────────────────────────────────────────────────────────
async def existing_exam_codes() -> set[str]:
    from db_pool import db_fetch
    try:
        rows = await db_fetch("SELECT DISTINCT exam_code FROM student_exams WHERE exam_code IS NOT NULL")
        return {r["exam_code"] for r in rows}
    except Exception as e:
        logger.error(f"[SYNC] existing_exam_codes fail: {e}")
        return set()


async def already_imported_for_exam(exam_code: str) -> int:
    """Kac ogrencinin verisi bu exam_code icin var?"""
    from db_pool import db_fetchval
    try:
        n = await db_fetchval(
            "SELECT COUNT(*) FROM student_exams WHERE exam_code = $1 AND turkce IS NOT NULL",
            exam_code
        )
        return int(n or 0)
    except Exception:
        return 0


async def upsert_student_exam_row(row_dict: dict, exam_meta: dict) -> bool:
    """Bir ogrencinin sinav kaydini DB'ye yaz (UPSERT).

    row_dict: dynamic-list satiri {SnvKod, SözNo, Adı, Soyadı, Türkçe_NET, ...}
    exam_meta: {exam_code, exam_name, exam_date, exam_type}
    """
    from db_pool import db_execute

    soz_no_raw = row_dict.get("SözNo") or row_dict.get("Sözno") or row_dict.get("SozNo")
    if not soz_no_raw:
        return False
    try:
        soz_no = int(str(soz_no_raw).strip())
    except (ValueError, TypeError):
        return False

    ad = (row_dict.get("Adı") or row_dict.get("Adi") or "").strip()
    soyad = (row_dict.get("Soyadı") or row_dict.get("Soyadi") or "").strip()
    student_name = f"{ad} {soyad}".strip() if (ad or soyad) else None

    # Net kolonlarini topla
    nets: dict[str, Optional[float]] = {
        "turkce": None, "tarih": None, "cografya": None, "felsefe": None,
        "din_kulturu": None, "matematik": None, "geometri": None,
        "fizik": None, "kimya": None, "biyoloji": None,
    }
    toplam_val: Optional[float] = None
    for col, val in row_dict.items():
        if "TOPLAM" in col.upper() and "_NET" in col.upper():
            tv = _parse_net(val)
            if tv is not None:
                toplam_val = tv
            continue
        sub = _normalize_subject(col)
        if sub and sub in nets:
            nets[sub] = _parse_net(val)

    if all(v is None for v in nets.values()) and toplam_val is None:
        # Hic net yok — atla
        return False

    if toplam_val is None:
        toplam_val = sum((v or 0.0) for v in nets.values()) or None

    try:
        await db_execute(
            """INSERT INTO student_exams
               (soz_no, student_name, exam_code, exam_name, exam_date,
                turkce, tarih, cografya, felsefe, din_kulturu,
                matematik, geometri, fizik, kimya, biyoloji,
                toplam, exam_type, status)
               VALUES ($1,$2,$3,$4,$5,
                       $6,$7,$8,$9,$10,
                       $11,$12,$13,$14,$15,
                       $16,$17,'valid')
               ON CONFLICT (soz_no, exam_code) DO UPDATE SET
                   student_name = COALESCE(EXCLUDED.student_name, student_exams.student_name),
                   exam_name    = COALESCE(EXCLUDED.exam_name, student_exams.exam_name),
                   exam_date    = COALESCE(EXCLUDED.exam_date, student_exams.exam_date),
                   turkce       = COALESCE(EXCLUDED.turkce, student_exams.turkce),
                   tarih        = COALESCE(EXCLUDED.tarih, student_exams.tarih),
                   cografya     = COALESCE(EXCLUDED.cografya, student_exams.cografya),
                   felsefe      = COALESCE(EXCLUDED.felsefe, student_exams.felsefe),
                   din_kulturu  = COALESCE(EXCLUDED.din_kulturu, student_exams.din_kulturu),
                   matematik    = COALESCE(EXCLUDED.matematik, student_exams.matematik),
                   geometri     = COALESCE(EXCLUDED.geometri, student_exams.geometri),
                   fizik        = COALESCE(EXCLUDED.fizik, student_exams.fizik),
                   kimya        = COALESCE(EXCLUDED.kimya, student_exams.kimya),
                   biyoloji     = COALESCE(EXCLUDED.biyoloji, student_exams.biyoloji),
                   toplam       = COALESCE(EXCLUDED.toplam, student_exams.toplam),
                   exam_type    = COALESCE(EXCLUDED.exam_type, student_exams.exam_type)""",
            soz_no, student_name, exam_meta["exam_code"], exam_meta["exam_name"],
            exam_meta["exam_date"],
            nets["turkce"], nets["tarih"], nets["cografya"], nets["felsefe"], nets["din_kulturu"],
            nets["matematik"], nets["geometri"], nets["fizik"], nets["kimya"], nets["biyoloji"],
            toplam_val, exam_meta.get("exam_type") or None,
        )
        return True
    except Exception as e:
        logger.debug(f"[SYNC] upsert fail soz_no={soz_no}: {e}")
        return False


async def log_sync_run(report: dict) -> None:
    """sync_run_log tablosuna kayit (yoksa olustur)."""
    from db_pool import db_execute
    try:
        await db_execute(
            """CREATE TABLE IF NOT EXISTS sync_run_log (
                   id SERIAL PRIMARY KEY,
                   run_at TIMESTAMP DEFAULT NOW(),
                   trigger TEXT,
                   exams_seen INT,
                   exams_new INT,
                   rows_inserted INT,
                   error TEXT,
                   detail JSONB
               )"""
        )
        import json as _json
        await db_execute(
            """INSERT INTO sync_run_log (trigger, exams_seen, exams_new, rows_inserted, error, detail)
               VALUES ($1,$2,$3,$4,$5,$6::jsonb)""",
            report.get("trigger") or "manual",
            int(report.get("exams_seen", 0)),
            int(report.get("exams_new", 0)),
            int(report.get("rows_inserted", 0)),
            report.get("error"),
            _json.dumps(report.get("detail") or {}, ensure_ascii=False, default=str),
        )
    except Exception as e:
        logger.debug(f"[SYNC] log_sync_run fail: {e}")


# ─── ANA SYNC ────────────────────────────────────────────────────────────────
async def sync_recent_exams(
    days: int = 30,
    dry_run: bool = False,
    trigger: str = "manual",
    max_exams_per_run: int = 5,
    force_codes: Optional[list[str]] = None,
) -> dict:
    """Son N gun icindeki sinavlardan eksik olanlari DB'ye al.

    max_exams_per_run: bir kostu cok uzun surmemesi icin tek run'da kac sinav
                       drill-down yapilacagi (default 5).
    """
    report: dict = {
        "trigger": trigger,
        "days": days,
        "started_at": datetime.now().isoformat(),
        "exams_seen": 0, "exams_new": 0,
        "rows_inserted": 0, "rows_updated": 0,
        "drilled": [], "skipped": [],
        "error": None,
    }

    try:
        recent = await list_recent_exams(days=days)
        report["exams_seen"] = len(recent)
        if not recent:
            logger.info("[SYNC] Eyotek'te son sinav yok / session sorunu")
            return report

        existing = await existing_exam_codes()
        force_set = set(force_codes or [])
        # Aynı exam_code'u birden fazla şube için listede görebiliriz — dedup
        seen_codes: set[str] = set()
        new_exams: list[dict] = []
        for e in recent:
            if e["exam_code"] in seen_codes:
                continue
            # force_codes icindeyse drill et (mevcut olsa bile — backfill icin)
            if e["exam_code"] in existing and e["exam_code"] not in force_set:
                continue
            seen_codes.add(e["exam_code"])
            new_exams.append(e)
        report["exams_new"] = len(new_exams)
        logger.info(
            f"[SYNC] Toplam {len(recent)} sinav, yeni={len(new_exams)}"
            f"{f' (force: {len(force_set)})' if force_set else ''}"
        )

        # Yenileri tarihe gore en yeni once
        new_exams.sort(key=lambda e: e["exam_date"], reverse=True)
        new_exams = new_exams[:max_exams_per_run]

        if dry_run:
            report["detail"] = {"dry_run_new_exams": [
                {"code": e["exam_code"], "name": e["exam_name"], "date": str(e["exam_date"])}
                for e in new_exams
            ]}
            return report

        from eyotek_knowledge.eyotek_navigator import sinav_drilldown

        for exam in new_exams:
            logger.info(f"[SYNC] Drill: {exam['exam_name']} ({exam['exam_date']})")
            drill = await sinav_drilldown(
                sinav_adi=exam["exam_name"],
                max_rows=200,
                date_from_days=days,
            )
            if not drill.get("success") or not drill.get("rows"):
                report["skipped"].append({
                    "exam_code": exam["exam_code"],
                    "exam_name": exam["exam_name"],
                    "reason": drill.get("error_code") or "no_data",
                    "error": drill.get("error"),
                })
                logger.warning(f"  -> SKIP: {drill.get('error') or 'no_data'}")
                continue

            inserted = 0
            for row in drill["rows"]:
                ok = await upsert_student_exam_row(row, exam)
                if ok:
                    inserted += 1

            report["rows_inserted"] += inserted
            report["drilled"].append({
                "exam_code": exam["exam_code"],
                "exam_name": exam["exam_name"],
                "row_count": drill.get("row_count", 0),
                "inserted": inserted,
            })
            logger.info(f"  -> OK: {drill.get('row_count')} satir, {inserted} upsert")

            # Eyotek'i yormamak icin sinavlar arasinda nefes payi
            await asyncio.sleep(2.0)

    except Exception as e:
        report["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        logger.exception("[SYNC] sync_recent_exams")

    report["finished_at"] = datetime.now().isoformat()
    await log_sync_run(report)

    # data_freshness — Oturum 25.29: success/failure ayrimi
    try:
        from data_freshness_helper import mark_success, mark_failure
        if report.get("error") or report.get("exams_seen", 0) == 0:
            await mark_failure(
                "exam_results",
                error=report.get("error") or "no exams seen (session?)",
                count=report.get("rows_inserted", 0),
            )
        else:
            await mark_success(
                "exam_results",
                count=report.get("rows_inserted", 0),
                notes=f"trigger={report.get('trigger')} new={report.get('exams_new', 0)}",
            )
    except Exception:
        pass
    return report


# ─── CLI ──────────────────────────────────────────────────────────────────────
def _print_report(report: dict) -> None:
    print("=" * 60)
    print(f"SYNC RECENT EXAMS — {report.get('trigger')}")
    print(f"  Period: son {report.get('days')} gun")
    print(f"  Sinavlar gorulen: {report.get('exams_seen')}")
    print(f"  Yeni sinav: {report.get('exams_new')}")
    print(f"  Eklenen ogrenci-sinav satiri: {report.get('rows_inserted')}")
    if report.get("drilled"):
        print("  Drill-down sonuclari:")
        for d in report["drilled"]:
            print(f"    * {d['exam_name']}: {d['inserted']}/{d['row_count']} satir")
    if report.get("skipped"):
        print("  Atlanan:")
        for d in report["skipped"]:
            print(f"    - {d['exam_name']}: {d['reason']}")
    if report.get("error"):
        print(f"  HATA: {report['error']}")
    print("=" * 60)


async def _main():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=30, help="Son kac gun (default 30)")
    p.add_argument("--dry-run", action="store_true", help="DB'ye yazma, sadece raporla")
    p.add_argument("--trigger", default="manual", help="Log'a yazilacak tetik etiketi")
    p.add_argument("--max", type=int, default=5, help="Tek run'da kac yeni sinav drill yapilsin")
    p.add_argument("--force-codes", default="",
                   help="Virgul ile exam_code listesi — DB'de olsa bile yeniden drill (backfill)")
    args = p.parse_args()

    fc = [c.strip() for c in args.force_codes.split(",") if c.strip()] if args.force_codes else None
    report = await sync_recent_exams(
        days=args.days,
        dry_run=args.dry_run,
        trigger=args.trigger,
        max_exams_per_run=args.max,
        force_codes=fc,
    )
    _print_report(report)


if __name__ == "__main__":
    asyncio.run(_main())
