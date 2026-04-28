"""
sync_etut_kontrol.py — Etut Ogrenci Kontrol periyodik sync (Oturum 25.29)
==========================================================================

Eyotek `Student/individual-lesson-control-student` sayfasini cektip
`etut_student_control` tablosunu yeniler.

Neo'nun bulundugu sorun (28 Nisan):
  Bot "Beyza 0 etut" diyordu ama Beyza Ilgin'in 11 etut'u vardi.
  Sebep: etut_student_control tablosu 8 Nisan'dan beri sync edilmemis,
         20 gun stale.

Bu modul:
  1. Eyotek individual-lesson-control-student sayfasina git (CDP)
  2. ARA tikla, modal kapali tut (default sezon/sube)
  3. Sayfalamayi gez, tum ogrenci-etut summary'sini topla
  4. etut_student_control UPSERT (soz_no PK)

Caller:
  - Manuel: python sync_etut_kontrol.py
  - precompute_nightly entegrasyon (her gece 03:00)

Cookie + CDP_PORT pattern eyotek_navigator ile ayni.
"""
from __future__ import annotations
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

from loguru import logger

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))


async def fetch_etut_student_control() -> list[dict]:
    """Eyotek'ten etut ogrenci kontrol verisini cek."""
    from playwright.async_api import async_playwright
    from eyotek_knowledge.eyotek_navigator import (
        _CDP_URL, _inject_cookies, _is_login,
    )

    pw = await async_playwright().start()
    page = None
    try:
        browser = await pw.chromium.connect_over_cdp(_CDP_URL)
        ctx = browser.contexts[0]
        await _inject_cookies(ctx)
        page = await ctx.new_page()

        url = "https://fermat.eyotek.com/v1/Pages/Student/individual-lesson-control-student"
        await page.goto(url, timeout=20000, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        if await _is_login(page):
            logger.error("[ETUT_KONTROL] Eyotek session expired")
            return []

        # ARA link tikla (sayfa hazir hale gelmesi icin)
        await page.evaluate("""
            () => {
                const links = document.querySelectorAll('a');
                for (const a of links) {
                    if (a.innerText.trim() === 'ARA' && a.offsetParent) {
                        a.click(); return true;
                    }
                }
                return false;
            }
        """)
        await page.wait_for_timeout(1500)

        # Modal acilirsa btnSearch tikla
        try:
            await page.click('#btnSearch', timeout=3000)
            await page.wait_for_timeout(3500)
        except Exception:
            # Modal yoksa ARA dogrudan tetiklemis olabilir
            pass

        # Sayfalama gez
        all_records: list[dict] = []
        page_num = 1
        while True:
            records = await page.evaluate("""
                () => {
                    const tables = document.querySelectorAll('table');
                    for (const tbl of tables) {
                        const ths = Array.from(tbl.querySelectorAll('th'))
                            .map(h => h.innerText.trim().toLowerCase());
                        if (!ths.some(h => h.includes('söz no') || h.includes('adı')))
                            continue;
                        const rows = [];
                        tbl.querySelectorAll('tbody tr').forEach(tr => {
                            const cells = Array.from(tr.querySelectorAll('td'))
                                .map(td => td.innerText.trim());
                            if (cells.length >= 4 && cells.some(c => c)) {
                                const row = {};
                                ths.forEach((h, i) => {
                                    if (cells[i] !== undefined) row[h] = cells[i];
                                });
                                rows.push(row);
                            }
                        });
                        return rows;
                    }
                    return [];
                }
            """)
            all_records.extend(records)
            logger.info(f"[ETUT_KONTROL] Sayfa {page_num}: {len(records)} kayit")

            page_num += 1
            next_clicked = await page.evaluate(f"""
                () => {{
                    const links = document.querySelectorAll('a');
                    for (const a of links) {{
                        if (a.innerText.trim() === '{page_num}' && a.offsetParent) {{
                            a.click(); return true;
                        }}
                    }}
                    return false;
                }}
            """)
            if not next_clicked:
                break
            await page.wait_for_timeout(2000)

        # Header -> kolon map
        fm = {
            "şube": "sube", "söz no": "soz_no", "okul no": "okul_no",
            "adı": "ad", "soyadı": "soyad", "devre": "devre",
            "sınıf": "sinif", "yapıldı": "yapildi",
            "öğrenci gelmedi": "gelmedi",
            "kontrol edilmedi": "kontrol_edilmedi", "toplam": "toplam",
        }
        mapped = []
        for r in all_records:
            row: dict = {}
            for k, v in r.items():
                if k in fm:
                    row[fm[k]] = v
            if row.get("soz_no"):
                mapped.append(row)
        return mapped
    except Exception as e:
        logger.exception(f"[ETUT_KONTROL] fetch fail: {e}")
        return []
    finally:
        try:
            if page:
                await page.close()
        except Exception:
            pass
        try:
            await pw.stop()
        except Exception:
            pass


def _to_int(v) -> int:
    try:
        return int(str(v or "0").strip().replace(",", ""))
    except (ValueError, TypeError):
        return 0


async def upsert_etut_student_control(records: list[dict]) -> dict:
    """Cekilen kayitlari etut_student_control'a yaz."""
    from db_pool import db_execute, get_pool
    if not records:
        return {"inserted": 0, "updated": 0, "skipped": 0}

    pool = await get_pool()
    inserted, updated, skipped = 0, 0, 0
    async with pool.acquire() as conn:
        for r in records:
            soz_no_raw = r.get("soz_no", "").strip()
            if not soz_no_raw:
                skipped += 1
                continue
            try:
                soz_no = int(soz_no_raw)
            except (ValueError, TypeError):
                skipped += 1
                continue
            ad = (r.get("ad", "") or "").strip()
            soyad = (r.get("soyad", "") or "").strip()
            full_name = f"{ad} {soyad}".strip()
            try:
                result = await conn.execute(
                    """INSERT INTO etut_student_control
                       (soz_no, adi, soyadi, full_name, devre, sinif,
                        yapildi, ogrenci_gelmedi, kontrol_edilmedi, toplam, updated_at)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,NOW())
                       ON CONFLICT (soz_no) DO UPDATE SET
                           adi=EXCLUDED.adi, soyadi=EXCLUDED.soyadi,
                           full_name=EXCLUDED.full_name,
                           devre=EXCLUDED.devre, sinif=EXCLUDED.sinif,
                           yapildi=EXCLUDED.yapildi,
                           ogrenci_gelmedi=EXCLUDED.ogrenci_gelmedi,
                           kontrol_edilmedi=EXCLUDED.kontrol_edilmedi,
                           toplam=EXCLUDED.toplam,
                           updated_at=NOW()""",
                    soz_no, ad, soyad, full_name,
                    (r.get("devre", "") or "").strip(),
                    (r.get("sinif", "") or "").strip(),
                    _to_int(r.get("yapildi")),
                    _to_int(r.get("gelmedi")),
                    _to_int(r.get("kontrol_edilmedi")),
                    _to_int(r.get("toplam")),
                )
                if "INSERT 0 1" in result:
                    inserted += 1
                else:
                    updated += 1
            except Exception as e:
                logger.debug(f"[ETUT_KONTROL] upsert fail soz_no={soz_no}: {e}")
                skipped += 1
    # data_freshness module update
    try:
        await db_execute(
            "UPDATE data_freshness SET last_sync=NOW() WHERE module='etut_student_control'"
        )
    except Exception:
        pass
    return {"inserted": inserted, "updated": updated, "skipped": skipped}


async def sync_etut_student_control(trigger: str = "manual") -> dict:
    """Tek nokta: cek + upsert + rapor."""
    started = datetime.now()
    rows = await fetch_etut_student_control()
    if not rows:
        return {
            "trigger": trigger,
            "started_at": started.isoformat(),
            "fetched": 0,
            "error": "Eyotek session expired or page failed to load",
        }
    rep = await upsert_etut_student_control(rows)
    rep["trigger"] = trigger
    rep["fetched"] = len(rows)
    rep["started_at"] = started.isoformat()
    rep["finished_at"] = datetime.now().isoformat()
    return rep


# ─── CLI ──────────────────────────────────────────────────────────────────────
async def _main():
    rep = await sync_etut_student_control(trigger="cli_manual")
    print("=" * 60)
    print("ETUT STUDENT CONTROL SYNC")
    print(f"  Fetched:   {rep.get('fetched', 0)}")
    print(f"  Inserted:  {rep.get('inserted', 0)}")
    print(f"  Updated:   {rep.get('updated', 0)}")
    print(f"  Skipped:   {rep.get('skipped', 0)}")
    if rep.get("error"):
        print(f"  ERROR:     {rep['error']}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(_main())
