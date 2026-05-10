"""
sinav_resync.py — Eski/eksik sınavlar için tam liste re-sync + exam_code merge.

Neo direktif (11 May): V3 öncesi eski sınavlar (V2 multi-devre fix öncesi)
DB'de tek devre × 14 öğrenci olarak kayıtlı. Tam liste için Eyotek'ten yeniden
çekmek gerek. Aynı zamanda eski 'lazy_*' exam_code'ları gerçek native kod
(999000107 vb.) ile birleştirme.

İki mod:

1. MERGE_LAZY (default — risksiz, hızlı):
   DB'de exam_code LIKE 'lazy_%' olan kayıtları bul.
   Aynı (soz_no, exam_name, exam_date) için native kodlu kayıt varsa lazy_ sil.
   Yoksa lazy_ kalır (Eyotek'te kod yokmuş).

2. RESYNC (--resync flag, agresif):
   Son N gün (default 60) sınavlarını test-transferred'den listele.
   Her sinav_adi için sinav_drilldown çağır → V3 multi-devre + native kod.
   DB'ye upsert (lazy hook). Yeni kayıtlar gelir, eski lazy_'ler MERGE adımında temizlenir.

Kullanım:
    # Sadece lazy → native merge (hızlı)
    python sinav_resync.py

    # Tam re-sync + merge (yavaş ~5-10 dk, Eyotek session açık olmalı)
    python sinav_resync.py --resync --days 60

    # Dry run — sadece planı göster, DB değiştirme
    python sinav_resync.py --dry-run
"""
from __future__ import annotations
import asyncio
import sys
import argparse
from pathlib import Path
from datetime import date, timedelta

# Proje import path
sys.path.insert(0, str(Path(__file__).resolve().parent))


async def merge_lazy_to_native(dry_run: bool = False) -> dict:
    """DB'deki lazy_* exam_code'ları, aynı sınavın native kodluyla birleştir.

    Strateji:
      Aynı (soz_no, exam_date) için iki kayıt varsa biri 'lazy_X', biri '999000107':
      → native kayıt KORUNUR, lazy_X kayıt SILINIR

    Eğer sadece lazy_ kayıt varsa → bekle (resync ile native gelebilir).
    """
    from db_pool import db_fetch, db_execute, db_fetchval

    out = {
        "lazy_total": 0,
        "merge_candidates": 0,
        "merged": 0,
        "kept_lazy_no_native": 0,
    }

    # 1. lazy_* kayıtları topla
    lazy_rows = await db_fetch(
        """SELECT id, soz_no, student_name, exam_code, exam_name, exam_date
           FROM student_exams
           WHERE exam_code LIKE 'lazy_%'
           ORDER BY soz_no, exam_date"""
    )
    out["lazy_total"] = len(lazy_rows or [])

    if not lazy_rows:
        return out

    print(f"[MERGE] {out['lazy_total']} 'lazy_*' kayit incelenecek")

    for lr in lazy_rows:
        soz_no = lr.get("soz_no")
        exam_date = lr.get("exam_date")
        exam_name = (lr.get("exam_name") or "").strip()

        if not soz_no:
            continue

        # 2. Native kayıt arama — 2 stratejili (exam_date veya exam_name)
        # Eski V2 öncesi lazy'lerde exam_date NULL olabiliyor (date parse fail —
        # tarih yerine puan değeri yazılmış). Bu durumda exam_name fallback.
        native = None
        if exam_date:
            native = await db_fetchval(
                """SELECT exam_code FROM student_exams
                   WHERE soz_no = $1 AND exam_date = $2
                     AND exam_code NOT LIKE 'lazy_%'
                     AND exam_code ~ '^[0-9]+$'
                   LIMIT 1""",
                soz_no, exam_date,
            )

        # Date NULL veya date match yoksa → name match dene
        if not native and exam_name:
            native = await db_fetchval(
                """SELECT exam_code FROM student_exams
                   WHERE soz_no = $1 AND exam_name = $2
                     AND exam_code NOT LIKE 'lazy_%'
                     AND exam_code ~ '^[0-9]+$'
                   LIMIT 1""",
                soz_no, exam_name,
            )

        if not native:
            out["kept_lazy_no_native"] += 1
            continue

        out["merge_candidates"] += 1

        if dry_run:
            print(f"  [DRY] silinecek: id={lr['id']} soz_no={soz_no} {exam_date} "
                  f"lazy={lr['exam_code'][:30]} → native={native}")
            continue

        # 3. lazy_ sil
        await db_execute(
            "DELETE FROM student_exams WHERE id = $1",
            lr["id"],
        )
        out["merged"] += 1

    return out


async def resync_recent_sinavlar(days: int = 60, dry_run: bool = False) -> dict:
    """Son N günün sınavlarını test-transferred'den listele, her birini V3 drill et."""
    from eyotek_knowledge.eyotek_navigator import (
        _navigator_browser, _BASE_URL,
        _open_search_modal, _fill_text_input, _click_search,
        _is_login,
    )
    from playwright.async_api import async_playwright

    out = {
        "sinav_listed": 0,
        "drill_attempted": 0,
        "drill_success": 0,
        "drill_failed": 0,
        "total_synced_rows": 0,
        "details": [],
    }

    pw = await async_playwright().start()
    browser, ctx, _ = await _navigator_browser(pw)
    page = await ctx.new_page()
    try:
        # 1. Sınav listesi sayfasını aç
        await page.goto(f"{_BASE_URL}Student/test-transferred",
                        timeout=20000, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        if await _is_login(page):
            out["error"] = "Eyotek session expired"
            return out

        await _open_search_modal(page)
        await page.wait_for_timeout(1500)
        from_d = (date.today() - timedelta(days=days)).strftime("%d.%m.%Y")
        to_d = date.today().strftime("%d.%m.%Y")
        await _fill_text_input(page, ["#txtKayitBas"], from_d)
        await _fill_text_input(page, ["#txtKayitBit"], to_d)
        await _click_search(page)
        await page.wait_for_timeout(4000)

        # 2. UNIQUE sınav adlarını topla (devre satırları aynı sınav için tekrar eder)
        sinav_set = await page.evaluate(
            """() => {
                const trs = document.querySelectorAll('table tbody tr');
                const seen = new Set();
                const unique = [];
                for (const tr of trs) {
                    const cells = Array.from(tr.cells).map(c => (c.innerText||'').trim());
                    if (cells.length < 7) continue;
                    const ad = cells[6];   // Sınav Adı
                    const tarih = cells[2];
                    if (ad && ad.toLowerCase() !== 'sınav adı') {
                        const key = ad + '|' + tarih;
                        if (!seen.has(key)) {
                            seen.add(key);
                            unique.push({sinav_adi: ad, tarih: tarih});
                        }
                    }
                }
                return unique;
            }"""
        )

        out["sinav_listed"] = len(sinav_set)
        print(f"[RESYNC] Son {days} gun: {out['sinav_listed']} unique sinav listede")
        for s in sinav_set:
            print(f"  · {s['tarih']}  {s['sinav_adi']}")

        if dry_run:
            return out

    finally:
        try: await page.close()
        except Exception: pass
        try: await ctx.close()
        except Exception: pass
        try: await browser.close()
        except Exception: pass
        try: await pw.stop()
        except Exception: pass

    # 3. Her sınav için ayrı drill (yeni browser context — multi-devre flow stabil)
    from fermat_core_agent import _tool_sinav_sonuclari
    for s in sinav_set:
        out["drill_attempted"] += 1
        try:
            r = await _tool_sinav_sonuclari(
                sinav_adi=s["sinav_adi"],
                max_rows=200,
                date_from_days=days,
                _caller_role="admin",
            )
            if r.get("success"):
                out["drill_success"] += 1
                synced = (r.get("_lazy_synced") or {}).get("count", 0)
                out["total_synced_rows"] += synced
                out["details"].append({
                    "sinav_adi": s["sinav_adi"],
                    "tarih": s["tarih"],
                    "row_count": r.get("row_count"),
                    "devre_count": r.get("devre_count"),
                    "lazy_synced": synced,
                    "completeness": r.get("data_completeness"),
                })
                print(f"  ✓ {s['sinav_adi'][:40]:40s} | {r.get('row_count')} row | {synced} sync")
            else:
                out["drill_failed"] += 1
                out["details"].append({
                    "sinav_adi": s["sinav_adi"],
                    "error": r.get("error"),
                })
                print(f"  ✗ {s['sinav_adi'][:40]:40s} | {r.get('error')}")
        except Exception as e:
            out["drill_failed"] += 1
            print(f"  ✗ {s['sinav_adi'][:40]:40s} | Exception: {e}")

    return out


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resync", action="store_true",
                        help="Eyotek'ten son N gün sınavları yeniden çek (yavaş, ~5-10dk)")
    parser.add_argument("--days", type=int, default=60,
                        help="Re-sync için son N gün (default 60)")
    parser.add_argument("--dry-run", action="store_true",
                        help="DB'ye yazma, sadece plan göster")
    args = parser.parse_args()

    from dotenv import load_dotenv
    env = Path(__file__).resolve().parent.parent / ".env"
    if env.exists():
        load_dotenv(env)

    print("=" * 60)
    print("FermatAI Sınav Re-Sync + exam_code Merge")
    print("=" * 60)

    # Adım 1: Re-sync (opsiyonel — yavaş)
    if args.resync:
        print("\n[1/2] RE-SYNC — Eyotek son", args.days, "gün sınavları...")
        rs = await resync_recent_sinavlar(days=args.days, dry_run=args.dry_run)
        print(f"\n  Listede: {rs.get('sinav_listed')} sınav")
        print(f"  Drill başarı: {rs.get('drill_success')} / "
              f"{rs.get('drill_attempted')}")
        print(f"  Toplam yeni satır sync: {rs.get('total_synced_rows')}")
    else:
        print("\n[1/2] RE-SYNC atlandı (--resync flag yok)")

    # Adım 2: Lazy → Native merge (hızlı)
    print("\n[2/2] MERGE — lazy_* exam_code → native kod birleştirme...")
    mr = await merge_lazy_to_native(dry_run=args.dry_run)
    print(f"  Toplam lazy_* kayıt: {mr['lazy_total']}")
    print(f"  Merge edilebilir (native var): {mr['merge_candidates']}")
    print(f"  Native bekliyor (resync sonrası gelecek): {mr['kept_lazy_no_native']}")
    if not args.dry_run:
        print(f"  Silinen lazy_ kayıt: {mr['merged']}")
    else:
        print(f"  [DRY-RUN] Hiçbir kayıt silinmedi")

    print("\n" + "=" * 60)
    print("Tamamlandı.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
