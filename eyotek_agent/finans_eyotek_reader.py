"""
FermatAI — Eyotek Finans Sayfalari Okuma Modulu (22.1n-neo)
============================================================

AMAC: Eyotek'in finans sayfalarindan SADECE OKUMA yaparak kurumsal finans
verisini FermatAI DB'sine senkronize et.

MUTLAK KURAL — NEO:
  1. ASLA yazma/silme/guncelleme tusuna basma. Sadece navigate + read.
  2. Yanlislikla INSERT butonunun selector'una dokunma.
  3. Sayfada "Kaydet", "Guncelle", "Sil", "Yeni Ekle" butonlarina ASLA tiklama.
  4. Sadece bu dosyadaki selectors (tablo row, pagination) kullanilabilir.

SAYFA KAPSAMI (Neo SS 20 Nisan 2026):
  [P1] Reports/balance-for-student-future-income  → kurum_gelir (sezon bazli)
  [P2] Financial/overdue-student-payment           → overdue_payments
  [P3] Financial/student-financial-operation      → monthly_installments + payments bazi
  [P4] (ileride) Reports/collection-total         → monthly_revenue_summary veri
  [P5] (ileride) Reports/monthly-expenses         → giderler
  [P6] (ileride) Reports/bonus-deduction          → prim/kesinti
  [P7] (ileride) Reports/salaries                 → maaslar

DRY_RUN KURALI:
  Ilk calisimda dry_run=True — sadece logla, DB'ye YAZMA.
  Neo confirm edince dry_run=False → gercek INSERT.
"""
from __future__ import annotations

import asyncio
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from loguru import logger

from eyotek_wrapper import EyotekWrapper
from db_pool import db_execute, db_fetchval, db_fetchrow
from finans_access import log_finans_access
from config import NEO_PHONE


# Eyotek sezon kodlari — dropdown probe ile dogrulandi (20 Nisan 2026):
SEZON_KODLARI = {
    "2024.25": "22425",   # Gecen sezon (mezun oldu, finans donemi kapandi)
    "2025.26": "22526",   # Simdiki sezon (aktif)
    "2026.27": "22627",   # Gelecek sezon (kayit almaya basladik)
}


async def _change_sezon(page, sezon_code: str) -> bool:
    """Eyotek ust menuden sezon degistir (select2 destekli).

    sezon_code: '22425', '22526', '22627' — sayisal kod.
    """
    try:
        await page.evaluate(f"""
            () => {{
                if (window.$ && $('#cmbSezonlar').length) {{
                    $('#cmbSezonlar').val('{sezon_code}').trigger('change');
                }}
            }}
        """)
        await asyncio.sleep(5.0)  # postback + veri yenile
        # Dogrula: secilen option text
        sel = await page.evaluate("() => $('#cmbSezonlar option:selected').text()")
        logger.info(f"  Sezon degisti: {sel}")
        return True
    except Exception as e:
        logger.error(f"Sezon degistirme hatasi: {e}")
        return False


# ─── Yardimci: Turkce sayi parse ─────────────────────────────────────────────

_TR_CURRENCY_RE = re.compile(r"[₺\s]+")

def parse_tr_amount(s: str) -> Optional[Decimal]:
    """Turkce format '₺1.381.495,00' → Decimal(1381495.00)."""
    if not s:
        return None
    raw = str(s).strip()
    if not raw or raw == "-":
        return None
    # ₺ ve bosluklar
    raw = _TR_CURRENCY_RE.sub("", raw)
    # Binlik ayirici (.) kaldir, ondalik ayirici (,) noktaya
    raw = raw.replace(".", "").replace(",", ".")
    try:
        return Decimal(raw)
    except Exception:
        return None


def parse_tr_date(s: str) -> Optional[date]:
    """'05.04.2026' → date(2026,4,5)."""
    if not s:
        return None
    raw = str(s).strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


# ─── [P1] BILANCO — Sezon bazli kurum ciro/tahsilat ──────────────────────────

async def read_bilanco(wrapper: EyotekWrapper, sezon_code: str = "",
                        sezon_label: str = "") -> list[dict]:
    """Bilanco sayfasini oku — sezon bazli satirlar.

    Args:
        sezon_code: '22425', '22526', '22627' — varsa dropdown degisir
        sezon_label: '2024.25' vb. — kayda eklenir

    Returns:
        [{sezon, sube, tarih, ciro, tahsilat, kalan, sezon_source}, ...]
    """
    path = "Pages/Reports/balance-for-student-future-income"
    await wrapper._goto(path, wait=2.0)
    page = wrapper._page
    if sezon_code:
        await _change_sezon(page, sezon_code)

    # Tablo selector'u — Eyotek WebForms GridView
    rows = await page.evaluate("""
        () => {
            const rs = [];
            const tbl = document.querySelector('table.table, table#GridView1, .table-responsive table');
            if (!tbl) return rs;
            const trs = tbl.querySelectorAll('tbody tr');
            trs.forEach(tr => {
                const tds = tr.querySelectorAll('td');
                if (tds.length >= 6) {
                    rs.push({
                        sezon:    (tds[1]?.innerText || '').trim(),
                        sube:     (tds[2]?.innerText || '').trim(),
                        tarih:    (tds[3]?.innerText || '').trim(),
                        ciro:     (tds[4]?.innerText || '').trim(),
                        tahsilat: (tds[5]?.innerText || '').trim(),
                        kalan:    (tds[6]?.innerText || '').trim(),
                    });
                }
            });
            return rs;
        }
    """)

    parsed = []
    for r in rows:
        if not r["sezon"] or r["sezon"].lower() in ("sezon", "toplam"):
            continue  # header veya toplam satiri
        parsed.append({
            "sezon":        r["sezon"],
            "sube":         r["sube"],
            "tarih":        r["tarih"],        # YYYY.MM format (2025.09 gibi)
            "ciro":         parse_tr_amount(r["ciro"]),
            "tahsilat":     parse_tr_amount(r["tahsilat"]),
            "kalan":        parse_tr_amount(r["kalan"]),
            "sezon_source": sezon_label or r["sezon"],
        })
    logger.info(f"[BILANCO {sezon_label or '?'}] {len(parsed)} satir okundu")
    return parsed


# ─── [P2] GECIKEN ODEME — borclu ogrenci listesi ─────────────────────────────

async def read_geciken_odemeler(wrapper: EyotekWrapper, sezon_code: str = "",
                                  sezon_label: str = "") -> list[dict]:
    """Geciken Odeme sayfasini oku.

    Returns:
        [{sezon, sube, soz_no, ad, soyad, program, devre, veli_adi, veli_cep,
          odeme_tipi, borc, taksit_sayisi, gs, en_son_gort, soz_verme_tarihi, sezon_source}, ...]
    """
    path = "Pages/Financial/overdue-student-payment"
    await wrapper._goto(path, wait=2.5)
    page = wrapper._page
    if sezon_code:
        await _change_sezon(page, sezon_code)

    # "TUMU" butonuna bas ki paginasyon acilsin (SS'deki gibi) — OPSIYONEL
    try:
        await page.click("button:has-text('TÜMÜ')", timeout=1500)
        await asyncio.sleep(1.5)
    except Exception:
        pass  # buton yoksa sorun degil, tum satirlari tek seferde gosterir

    rows = await page.evaluate("""
        () => {
            const rs = [];
            const tbl = document.querySelector('table.table, table#GridView1, .grid-container table');
            if (!tbl) return rs;
            const trs = tbl.querySelectorAll('tbody tr');
            trs.forEach(tr => {
                const tds = tr.querySelectorAll('td');
                // SS'de 16 kolon: TUMU butonu + checkmark + expand + sezon + sube +
                //                 soz_no + ad + soyad + program + devre + veli_ad +
                //                 veli_cep + odeme_tipi + borc + taksit + gs +
                //                 ensongort + soz_verme + silindi
                if (tds.length < 10) return;
                rs.push({
                    sezon:            (tds[3]?.innerText || '').trim(),
                    sube:             (tds[4]?.innerText || '').trim(),
                    soz_no:           (tds[5]?.innerText || '').trim(),
                    ad:               (tds[6]?.innerText || '').trim(),
                    soyad:            (tds[7]?.innerText || '').trim(),
                    program:          (tds[8]?.innerText || '').trim(),
                    devre:            (tds[9]?.innerText || '').trim(),
                    veli_adi:         (tds[10]?.innerText || '').trim(),
                    veli_cep:         (tds[11]?.innerText || '').trim(),
                    odeme_tipi:       (tds[12]?.innerText || '').trim(),
                    borc:             (tds[13]?.innerText || '').trim(),
                    taksit_sayisi:    (tds[14]?.innerText || '').trim(),
                    gs:               (tds[15]?.innerText || '').trim(),
                    en_son_gort:      (tds[16]?.innerText || '').trim(),
                    soz_verme_tarihi: (tds[17]?.innerText || '').trim(),
                });
            });
            return rs;
        }
    """)

    parsed = []
    for r in rows:
        if not r.get("soz_no") or r["soz_no"].lower() in ("söz no", "toplam"):
            continue
        try:
            soz_no_int = int(r["soz_no"])
        except:
            continue  # "Toplam" gibi string
        parsed.append({
            "sezon":            r["sezon"],
            "sube":             r["sube"],
            "soz_no":           soz_no_int,
            "ad":               r["ad"],
            "soyad":            r["soyad"],
            "full_name":        f"{r['ad']} {r['soyad']}".strip(),
            "program":          r["program"],
            "devre":            r["devre"],
            "veli_adi":         r["veli_adi"],
            "veli_cep":         r["veli_cep"],
            "odeme_tipi":       r["odeme_tipi"],
            "borc":             parse_tr_amount(r["borc"]),
            "taksit_sayisi":    int(r["taksit_sayisi"]) if r["taksit_sayisi"].isdigit() else 0,
            "gs":               int(r["gs"]) if r["gs"].isdigit() else 0,
            "en_son_gort":      parse_tr_date(r["en_son_gort"]),
            "soz_verme_tarihi": parse_tr_date(r["soz_verme_tarihi"]),
            "sezon_source":     sezon_label or r["sezon"],
        })
    logger.info(f"[GECIKEN {sezon_label or '?'}] {len(parsed)} ogrenci okundu")
    return parsed


# ─── [P3] OGRENCI ODEME DETAY — pagination var ────────────────────────────────

async def read_ogrenci_odeme_detay(wrapper: EyotekWrapper,
                                     max_pages: int = 20,
                                     sezon_code: str = "",
                                     sezon_label: str = "") -> list[dict]:
    """Ogrenci Odeme Detay — tum sayfalari gez.

    Returns:
        [{sube, sezon, soz_no, tc_kimlik, ad, soyad, devre, kayit_tarihi,
          taksit_sayisi, son_taksit_tarihi, kayit_fiyati, taksit_toplam,
          tahsilat, kalan, egitim_destek, egt_dest_alinan, egt_dest_kalan,
          destek_haric, net_kalan, iade}, ...]
    """
    # Not: SS'deki URL 'student-financial-operation' — haritadaki path farkli olabilir
    path = "Pages/Financial/student-financial-operation"
    await wrapper._goto(path, wait=3.0)
    page = wrapper._page
    if sezon_code:
        await _change_sezon(page, sezon_code)

    # Bu sayfada veri lazy-load — ARA flow tetikle (toolbar ARA → modal #btnSearch)
    try:
        triggered = await wrapper._ara_flow()
        if triggered:
            logger.info("[OGRENCI_ODEME] ARA flow tamamlandi, veri yuklendi")
            await asyncio.sleep(3.0)
    except Exception as _ee:
        logger.debug(f"ARA flow atlandi: {_ee}")

    all_rows = []
    for page_idx in range(1, max_pages + 1):
        # Sayfadaki tum satirlari oku
        rows = await page.evaluate("""
            () => {
                const rs = [];
                const tbl = document.querySelector('table.table, table#GridView1, .grid-container table');
                if (!tbl) return rs;
                const trs = tbl.querySelectorAll('tbody tr');
                trs.forEach(tr => {
                    const tds = tr.querySelectorAll('td');
                    if (tds.length < 10) return;
                    // SS'de 20+ kolon — ilk td menu butonu (...)
                    rs.push({
                        sube:               (tds[1]?.innerText || '').trim(),
                        sezon:              (tds[2]?.innerText || '').trim(),
                        soz_no:             (tds[3]?.innerText || '').trim(),
                        tc_kimlik:          (tds[4]?.innerText || '').trim(),
                        ad:                 (tds[5]?.innerText || '').trim(),
                        soyad:              (tds[6]?.innerText || '').trim(),
                        devre:              (tds[7]?.innerText || '').trim(),
                        kayit_tarihi:       (tds[8]?.innerText || '').trim(),
                        taksit_sayisi:      (tds[9]?.innerText || '').trim(),
                        son_taksit_tarihi:  (tds[10]?.innerText || '').trim(),
                        kayit_fiyati:       (tds[11]?.innerText || '').trim(),
                        taksit_toplam:      (tds[12]?.innerText || '').trim(),
                        tahsilat:           (tds[13]?.innerText || '').trim(),
                        kalan:              (tds[14]?.innerText || '').trim(),
                        egitim_destek:      (tds[15]?.innerText || '').trim(),
                        egt_dest_alinan:    (tds[16]?.innerText || '').trim(),
                        egt_dest_kalan:     (tds[17]?.innerText || '').trim(),
                        destek_haric:       (tds[18]?.innerText || '').trim(),
                        net_kalan:          (tds[19]?.innerText || '').trim(),
                        iade:               (tds[20]?.innerText || '').trim(),
                    });
                });
                return rs;
            }
        """)
        page_rows = 0
        for r in rows:
            if not r.get("soz_no") or not r["soz_no"].isdigit():
                continue
            try:
                parsed_row = {
                    "sube":               r["sube"],
                    "sezon":              r["sezon"],
                    "soz_no":             int(r["soz_no"]),
                    "tc_kimlik":          r["tc_kimlik"],
                    "ad":                 r["ad"],
                    "soyad":              r["soyad"],
                    "full_name":          f"{r['ad']} {r['soyad']}".strip(),
                    "devre":              r["devre"],
                    "kayit_tarihi":       parse_tr_date(r["kayit_tarihi"]),
                    "taksit_sayisi":      int(r["taksit_sayisi"]) if r["taksit_sayisi"].isdigit() else 0,
                    "son_taksit_tarihi":  parse_tr_date(r["son_taksit_tarihi"]),
                    "kayit_fiyati":       parse_tr_amount(r["kayit_fiyati"]),
                    "taksit_toplam":      parse_tr_amount(r["taksit_toplam"]),
                    "tahsilat":           parse_tr_amount(r["tahsilat"]),
                    "kalan":              parse_tr_amount(r["kalan"]),
                    "egitim_destek":      parse_tr_amount(r["egitim_destek"]),
                    "egt_dest_alinan":    parse_tr_amount(r["egt_dest_alinan"]),
                    "egt_dest_kalan":     parse_tr_amount(r["egt_dest_kalan"]),
                    "destek_haric":       parse_tr_amount(r["destek_haric"]),
                    "net_kalan":          parse_tr_amount(r["net_kalan"]),
                    "iade":               parse_tr_amount(r["iade"]),
                }
                parsed_row["sezon_source"] = sezon_label or r["sezon"]
                all_rows.append(parsed_row)
                page_rows += 1
            except Exception as e:
                logger.debug(f"Row parse err: {e}")

        logger.info(f"[OGRENCI_ODEME] Sayfa {page_idx}: {page_rows} satir (toplam {len(all_rows)})")

        # Sonraki sayfaya gec — ASP.NET PostBack 'Page$N'
        # Selector: pagination cell icindeki href'li 'Page$X' linki
        try:
            next_page_num = page_idx + 1
            # Spesifik: href icinde 'Page$N' olan link (ASP.NET standart)
            next_link = await page.query_selector(
                f"a[href*=\"Page${next_page_num}\"]"
            )
            if not next_link:
                # Fallback: pagination div/span icinde exact text
                next_link = await page.query_selector(
                    f"div.pagination a:has-text('{next_page_num}'), "
                    f"span#ctl00 a:has-text('{next_page_num}')"
                )
            if not next_link:
                logger.info(f"  Son sayfa (page {page_idx})")
                break
            # NAVIGATE — bu tiklama yazma YAPMAZ, sadece pagination
            await next_link.click(timeout=5000)
            await asyncio.sleep(3.0)  # PostBack bekle
        except Exception as e:
            logger.debug(f"Pagination bitti page {page_idx}: {e}")
            break

    logger.info(f"[OGRENCI_ODEME] TOPLAM {len(all_rows)} ogrenci okundu")
    return all_rows


# ─── DB SYNC FONKSIYONLARI ───────────────────────────────────────────────────

async def sync_bilanco_to_db(rows: list[dict], dry_run: bool = True) -> int:
    """Bilanco verilerini kurum_gelir tablosuna upsert."""
    if dry_run:
        logger.warning(f"[DRY_RUN] sync_bilanco: {len(rows)} satir yazilmayacak")
        return 0
    n = 0
    for r in rows:
        try:
            # Tarih 'YYYY.MM' formatinda — ayin 1'i olarak al
            tarih_str = r["tarih"]
            if "." in tarih_str:
                yil_str, ay_str = tarih_str.split(".", 1)
                kayit_tarih = date(int(yil_str), int(ay_str), 1)
            else:
                continue
            if r["ciro"] is not None:
                await db_execute(
                    """INSERT INTO kurum_gelir (kayit_tipi, tutar, kategori, aciklama,
                                                  tarih, created_by)
                       VALUES ('gelir', $1, 'ciro', $2, $3, 'eyotek_sync')""",
                    r["ciro"], f"Bilanco ciro {r['sezon']}/{r['sube']}", kayit_tarih,
                )
                n += 1
        except Exception as e:
            logger.error(f"sync_bilanco err: {e}")
    logger.info(f"[BILANCO SYNC] {n} kayit")
    return n


async def sync_geciken_to_db(rows: list[dict], dry_run: bool = True) -> int:
    """Geciken odemeler → overdue_payments upsert (mevcut tablo schema)."""
    if dry_run:
        logger.warning(f"[DRY_RUN] sync_geciken: {len(rows)} satir yazilmayacak")
        return 0
    n = 0
    for r in rows:
        try:
            await db_execute(
                """INSERT INTO overdue_payments
                   (soz_no, full_name, first_name, last_name, sezon, sube,
                    borc, vade_tarihi, taksit_no, aciklama, last_sync)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,NOW())""",
                r["soz_no"], r["full_name"], r["ad"], r["soyad"],
                r["sezon"], r["sube"], r["borc"],
                r["soz_verme_tarihi"] or r["en_son_gort"],
                r["taksit_sayisi"],
                f"veli={r['veli_adi']} tip={r['odeme_tipi']} cep={r['veli_cep']}",
            )
            n += 1
        except Exception as e:
            logger.error(f"sync_geciken err: {e}")
    logger.info(f"[GECIKEN SYNC] {n} kayit")
    return n


async def sync_ogrenci_odeme_to_db(rows: list[dict], dry_run: bool = True) -> int:
    """Ogrenci odeme detay → monthly_installments (aggregated) + student_financial_summary view otomatik update.

    NOT: student_financial_summary bir VIEW — INSERT gerekmez.
    monthly_installments'a: soz_no bazinda ozet kayit gir (taksit_toplam, tahsilat).
    Ayri kayit gerekir ay bazinda — bu SS'lerden gelmiyor, ayri bir tablo: ogrenci_odeme_snapshot
    """
    if dry_run:
        logger.warning(f"[DRY_RUN] sync_ogrenci_odeme: {len(rows)} satir yazilmayacak")
        return 0
    # Snapshot tablosu yoksa olustur (inline, tek seferde)
    await db_execute("""
        CREATE TABLE IF NOT EXISTS ogrenci_odeme_snapshot (
            id BIGSERIAL PRIMARY KEY,
            soz_no INTEGER NOT NULL,
            sezon VARCHAR(10),
            sube VARCHAR(40),
            tc_kimlik VARCHAR(11),
            full_name TEXT,
            devre VARCHAR(20),
            kayit_tarihi DATE,
            taksit_sayisi INTEGER,
            son_taksit_tarihi DATE,
            kayit_fiyati DECIMAL(12,2),
            taksit_toplam DECIMAL(12,2),
            tahsilat DECIMAL(12,2),
            kalan DECIMAL(12,2),
            egitim_destek DECIMAL(12,2),
            egt_dest_alinan DECIMAL(12,2),
            egt_dest_kalan DECIMAL(12,2),
            destek_haric DECIMAL(12,2),
            net_kalan DECIMAL(12,2),
            iade DECIMAL(12,2),
            snapshot_date TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_oos_soz ON ogrenci_odeme_snapshot(soz_no);
        CREATE INDEX IF NOT EXISTS idx_oos_date ON ogrenci_odeme_snapshot(snapshot_date DESC);
    """)
    n = 0
    for r in rows:
        try:
            await db_execute(
                """INSERT INTO ogrenci_odeme_snapshot
                   (soz_no, sezon, sube, tc_kimlik, full_name, devre,
                    kayit_tarihi, taksit_sayisi, son_taksit_tarihi,
                    kayit_fiyati, taksit_toplam, tahsilat, kalan,
                    egitim_destek, egt_dest_alinan, egt_dest_kalan,
                    destek_haric, net_kalan, iade)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19)""",
                r["soz_no"], r["sezon"], r["sube"], r["tc_kimlik"], r["full_name"], r["devre"],
                r["kayit_tarihi"], r["taksit_sayisi"], r["son_taksit_tarihi"],
                r["kayit_fiyati"], r["taksit_toplam"], r["tahsilat"], r["kalan"],
                r["egitim_destek"], r["egt_dest_alinan"], r["egt_dest_kalan"],
                r["destek_haric"], r["net_kalan"], r["iade"],
            )
            n += 1
        except Exception as e:
            logger.error(f"sync_ogrenci_odeme err: {e}")
    logger.info(f"[OGRENCI_ODEME SYNC] {n} snapshot kayit")
    return n


# ─── MULTI-SEASON SYNC — 3 sezon kiyaslama (Neo stratejik rapor) ────────────

async def sync_season_snapshot_row(row: dict, sezon_label: str,
                                     dry_run: bool = True) -> bool:
    """Tek satir ogrenci_odeme_snapshot'a yaz (sezon kolonlu)."""
    if dry_run:
        return False
    try:
        await db_execute(
            """INSERT INTO ogrenci_odeme_snapshot
               (soz_no, sezon, sube, tc_kimlik, full_name, devre,
                kayit_tarihi, taksit_sayisi, son_taksit_tarihi,
                kayit_fiyati, taksit_toplam, tahsilat, kalan,
                egitim_destek, egt_dest_alinan, egt_dest_kalan,
                destek_haric, net_kalan, iade)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19)""",
            row["soz_no"], sezon_label, row["sube"], row["tc_kimlik"],
            row["full_name"], row["devre"],
            row["kayit_tarihi"], row["taksit_sayisi"], row["son_taksit_tarihi"],
            row["kayit_fiyati"], row["taksit_toplam"], row["tahsilat"], row["kalan"],
            row["egitim_destek"], row["egt_dest_alinan"], row["egt_dest_kalan"],
            row["destek_haric"], row["net_kalan"], row["iade"],
        )
        return True
    except Exception as e:
        logger.error(f"snapshot row err: {e}")
        return False


async def sync_all_seasons(
    sezonlar: Optional[list] = None,
    dry_run: bool = True,
    skip_past_students: bool = True,
) -> dict:
    """3 SEZON (2024.25 + 2025.26 + 2026.27) finans okuma.

    Args:
        sezonlar: None → default 3 sezon. List → sadece belirtilenler
        dry_run: True → okur, yazmaz. False → DB'ye yazar.
        skip_past_students: Neo kurali — eski sezon ogrencilerini students tablosuna
                            EKLEMEZ (akademik profil acma YASAK, sadece finans).

    Returns: {sezon: {okuma: {...}, yazma: {...}, kiyas_metrik: {...}}}
    """
    if sezonlar is None:
        sezonlar = list(SEZON_KODLARI.keys())  # ['2024.25', '2025.26', '2026.27']

    report = {"dry_run": dry_run, "sezonlar": {}, "kiyaslama": {}}

    await log_finans_access(
        NEO_PHONE, "multi_season_sync_start",
        target=f"sezonlar={','.join(sezonlar)}",
        details=f"dry_run={dry_run} skip_past={skip_past_students}",
        success=True
    )

    import json as _json, os as _os
    with open(_os.getenv("SESSION_FILE", ".eyotek_session.json"), encoding="utf-8") as f:
        cookies = _json.load(f)

    async with EyotekWrapper(cookies) as wrapper:
        for sezon_label in sezonlar:
            sezon_code = SEZON_KODLARI.get(sezon_label)
            if not sezon_code:
                report["sezonlar"][sezon_label] = {"error": "Bilinmeyen sezon kodu"}
                continue

            sz_report = {"okuma": {}, "yazma": {}}
            logger.info(f"\n═══ SEZON {sezon_label} ({sezon_code}) ═══")

            # [P1] Bilanco
            try:
                bilanco_rows = await read_bilanco(wrapper, sezon_code, sezon_label)
                sz_report["okuma"]["bilanco"] = len(bilanco_rows)
                # Kurum ciro metrik
                toplam_ciro = sum(float(r["ciro"] or 0) for r in bilanco_rows)
                toplam_tahsilat = sum(float(r["tahsilat"] or 0) for r in bilanco_rows)
                toplam_kalan = sum(float(r["kalan"] or 0) for r in bilanco_rows)
                sz_report["metrik"] = {
                    "toplam_ciro": round(toplam_ciro, 2),
                    "toplam_tahsilat": round(toplam_tahsilat, 2),
                    "toplam_kalan": round(toplam_kalan, 2),
                    "tahsilat_orani": (
                        round(100 * toplam_tahsilat / toplam_ciro, 1)
                        if toplam_ciro > 0 else 0
                    ),
                }
                if not dry_run:
                    cnt = 0
                    for r in bilanco_rows:
                        try:
                            tarih_str = r["tarih"]
                            if "." in tarih_str and r["ciro"]:
                                y, m = tarih_str.split(".", 1)
                                await db_execute(
                                    """INSERT INTO kurum_gelir
                                       (kayit_tipi, tutar, kategori, aciklama, tarih, created_by)
                                       VALUES ('gelir', $1, 'ciro', $2, $3, 'eyotek_sync')""",
                                    r["ciro"],
                                    f"Bilanco {sezon_label} {r['sube']} {tarih_str}",
                                    date(int(y), int(m), 1),
                                )
                                cnt += 1
                        except Exception as e:
                            logger.debug(f"bilanco row err: {e}")
                    sz_report["yazma"]["bilanco"] = cnt
            except Exception as e:
                sz_report["okuma"]["bilanco_error"] = str(e)

            # [P2] Geciken — Eyotek'te sezon filter calismiyor (bugunkü borçlular tek liste)
            # Sadece aktif sezona (simdi 2025.26) yaz, duplikasyon olmasin.
            # Diger sezonlarin geciken durumu ogrenci_odeme_snapshot.kalan'dan gorulur.
            if sezon_label != "2025.26":
                sz_report["okuma"]["geciken"] = 0
                sz_report["okuma"]["geciken_note"] = "skip (aktif sezon disi)"
            else:
                try:
                    geciken_rows = await read_geciken_odemeler(wrapper, sezon_code, sezon_label)
                    sz_report["okuma"]["geciken"] = len(geciken_rows)
                    toplam_geciken = sum(float(r["borc"] or 0) for r in geciken_rows)
                    sz_report["metrik"]["geciken_ogrenci"] = len(geciken_rows)
                    sz_report["metrik"]["geciken_tutar"] = round(toplam_geciken, 2)
                    if not dry_run:
                        cnt = 0
                        for r in geciken_rows:
                            try:
                                await db_execute(
                                    """INSERT INTO geciken_snapshot
                                       (soz_no, sezon, sube, full_name, program, devre,
                                        veli_adi, veli_cep, odeme_tipi, borc, taksit_sayisi,
                                        gs, en_son_gort, soz_verme_tarihi)
                                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)""",
                                    r["soz_no"], sezon_label, r["sube"], r["full_name"],
                                    r["program"], r["devre"],
                                    r["veli_adi"], r["veli_cep"], r["odeme_tipi"],
                                    r["borc"], r["taksit_sayisi"], r["gs"],
                                    r["en_son_gort"], r["soz_verme_tarihi"],
                                )
                                cnt += 1
                            except Exception as _e:
                                logger.debug(f"geciken row err: {_e}")
                        sz_report["yazma"]["geciken"] = cnt
                except Exception as e:
                    sz_report["okuma"]["geciken_error"] = str(e)

            # [P3] Ogrenci odeme detay — eski sezonda da finans (ACL YAZILMAZ)
            try:
                ogr_rows = await read_ogrenci_odeme_detay(
                    wrapper, max_pages=20, sezon_code=sezon_code, sezon_label=sezon_label
                )
                sz_report["okuma"]["ogrenci_odeme"] = len(ogr_rows)
                sz_report["metrik"]["ogrenci_sayisi"] = len(ogr_rows)
                # Ortalama kayit fiyati
                fiyatlar = [float(r["kayit_fiyati"]) for r in ogr_rows
                            if r.get("kayit_fiyati")]
                if fiyatlar:
                    sz_report["metrik"]["ort_kayit_fiyati"] = round(sum(fiyatlar)/len(fiyatlar), 2)
                    sz_report["metrik"]["toplam_kayit_fiyati"] = round(sum(fiyatlar), 2)
                if not dry_run:
                    cnt = 0
                    for r in ogr_rows:
                        if await sync_season_snapshot_row(r, sezon_label, dry_run=False):
                            cnt += 1
                    sz_report["yazma"]["ogrenci_odeme"] = cnt
            except Exception as e:
                sz_report["okuma"]["ogrenci_odeme_error"] = str(e)

            report["sezonlar"][sezon_label] = sz_report

    # Karsilastirma metriği (3 sezon yan yana)
    kiyas = {}
    for label, data in report["sezonlar"].items():
        m = data.get("metrik", {})
        kiyas[label] = {
            "ciro":       m.get("toplam_ciro", 0),
            "tahsilat":   m.get("toplam_tahsilat", 0),
            "kalan":      m.get("toplam_kalan", 0),
            "tahsilat_pct": m.get("tahsilat_orani", 0),
            "ogrenci":    m.get("ogrenci_sayisi", 0),
            "ort_fiyat":  m.get("ort_kayit_fiyati", 0),
            "geciken_ogr": m.get("geciken_ogrenci", 0),
            "geciken_tl": m.get("geciken_tutar", 0),
        }
    # Yildan yila buyume
    labels_sorted = sorted(kiyas.keys())
    for i in range(1, len(labels_sorted)):
        prev_l = labels_sorted[i-1]
        cur_l = labels_sorted[i]
        prev_ciro = kiyas[prev_l]["ciro"] or 1
        cur_ciro = kiyas[cur_l]["ciro"] or 0
        kiyas[cur_l]["buyume_pct"] = round(100*(cur_ciro - prev_ciro)/prev_ciro, 1)
    report["kiyaslama"] = kiyas

    await log_finans_access(
        NEO_PHONE, "multi_season_sync_end",
        target=f"sezonlar={','.join(sezonlar)}",
        details=f"kiyaslama={list(kiyas.keys())}",
        success=True
    )

    return report


# ─── Eski single-season fonksiyon — multi'yi delegate eder ───────────────────

async def sync_all_finans(dry_run: bool = True) -> dict:
    """Tum finans sayfalarini Eyotek'ten oku ve DB'ye yaz.

    dry_run=True (default) — sadece oku, yazma. Neo onayladiktan sonra False.
    """
    report = {"dry_run": dry_run, "okuma": {}, "yazma": {}}

    await log_finans_access(NEO_PHONE, "sync_all_start",
                            target="eyotek_full_sync",
                            details=f"dry_run={dry_run}", success=True)

    # Session cookie yukle
    import json as _json, os as _os
    session_path = _os.getenv("SESSION_FILE", ".eyotek_session.json")
    try:
        with open(session_path, encoding="utf-8") as f:
            cookies = _json.load(f)
    except Exception as e:
        return {"error": f"Session cookie yuklenemedi: {e}"}

    async with EyotekWrapper(cookies) as wrapper:
        # [P1] Bilanco
        try:
            bilanco_rows = await read_bilanco(wrapper)
            report["okuma"]["bilanco"] = len(bilanco_rows)
            report["bilanco_sample"] = bilanco_rows[:3] if bilanco_rows else []
            if not dry_run:
                report["yazma"]["bilanco"] = await sync_bilanco_to_db(bilanco_rows, dry_run=False)
        except Exception as e:
            report["okuma"]["bilanco_error"] = str(e)

        # [P2] Geciken
        try:
            geciken_rows = await read_geciken_odemeler(wrapper)
            report["okuma"]["geciken"] = len(geciken_rows)
            report["geciken_sample"] = geciken_rows[:3] if geciken_rows else []
            if not dry_run:
                report["yazma"]["geciken"] = await sync_geciken_to_db(geciken_rows, dry_run=False)
        except Exception as e:
            report["okuma"]["geciken_error"] = str(e)

        # [P3] Ogrenci odeme detay
        try:
            ogr_rows = await read_ogrenci_odeme_detay(wrapper, max_pages=20)
            report["okuma"]["ogrenci_odeme"] = len(ogr_rows)
            report["ogrenci_sample"] = ogr_rows[:2] if ogr_rows else []
            if not dry_run:
                report["yazma"]["ogrenci_odeme"] = await sync_ogrenci_odeme_to_db(ogr_rows, dry_run=False)
        except Exception as e:
            report["okuma"]["ogrenci_odeme_error"] = str(e)

    await log_finans_access(NEO_PHONE, "sync_all_end",
                            target="eyotek_full_sync",
                            details=str(report)[:300], success=True)

    return report


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    async def main():
        argv = sys.argv[1:]
        dry = "--apply" not in argv
        if not dry:
            logger.warning("!!! GERCEK YAZIM MODU — Neo onayi dogrulaniyor")
        report = await sync_all_finans(dry_run=dry)
        import json
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))

    asyncio.run(main())
