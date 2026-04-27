"""
Eyotek Generic Navigator — Oturum 25.26
=========================================

Parametrik, agentic-dostu Eyotek sayfa gezgini.

Felsefe:
  - Eski: her sayfa icin ayri fonksiyon (sabit filtre)
  - Yeni: tek fonksiyon, her sayfaya esnek parametre verir.

Tek API:
    navigate(page_path, filters={...}, max_rows=50, drill={...}) -> dict

Ornekler:
    # 26 Nisan'in etutleri
    await navigate("Student/individual-lesson",
                   filters={"date_from":"26.04.2026", "date_to":"26.04.2026"})

    # Belirli bir ogretmenin Nisan etutleri
    await navigate("Student/individual-lesson",
                   filters={"date_from":"01.04.2026", "date_to":"30.04.2026",
                            "teacher":"Hasan Gungor"})

    # En yeni sinav sonuclari
    await navigate("Student/exam-result",
                   filters={"date_from":"20.04.2026", "exam_name":"Apotemi"})

    # Ogrenci listesi + ilk satira drill (profil sayfasi)
    await navigate("Student/student",
                   filters={"name":"Ali"},
                   drill={"row":0, "link_text":"Detay"})

Filter normalize (alias-aware):
  Ortak alias'lar — bot ne soylerse soylesin yakalar.
  - date_from, basla, baslangic, ilkTarih  -> txtKayitBas
  - date_to, bitis, sonTarih               -> txtKayitBit
  - class, sinif                           -> DdlClasses / DdlClass
  - teacher, ogretmen                      -> DdlTeachers / DdlStaff
  - ders, lesson, brans                    -> DdlLessons / DdlLesson
  - student, ogrenci, name, ad             -> text input (ad-soyad arama)
  - exam_name, sinav_adi                   -> text input (sinav adi alani)

Auth:
  .eyotek_session.json'dan cookie inject edilir (eyotek_reader gibi).
  Login sayfasina dusulurse net hata doner.

Hata UX (3 ayri durum):
  1. AUTH_EXPIRED  -> cookie inject edildi ama hala login -> Neo'ya bildirim
  2. NO_DATA       -> filtreler dogru, ama tablo bos       -> "veri yok"
  3. FILTER_BAD    -> filtre adi sayfada bulunamadi        -> "filter X bilinmiyor"
"""
from __future__ import annotations
import asyncio
import json
import os
import re
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any, Optional

from loguru import logger

# Module config
_ROOT = Path(__file__).resolve().parent.parent.parent
_BASE_URL = "https://fermat.eyotek.com/v1/Pages/"
_SESSION_FILE = Path(os.getenv("SESSION_FILE") or (_ROOT / ".eyotek_session.json"))
_CDP_PORT = int(os.getenv("CDP_PORT", "9222"))
_CDP_URL = f"http://localhost:{_CDP_PORT}"

# ─── FILTER ALIAS HARITASI ────────────────────────────────────────────────────
# Bot/planner ne kullanirsa kullansin, yakalanir.
_FILTER_ALIAS = {
    "date_from":     ["basla", "baslangic", "ilk_tarih", "tarih_bas", "from", "start"],
    "date_to":       ["bitis", "son_tarih", "tarih_bit", "to", "end"],
    "class":         ["sinif", "klass", "class_name"],
    "teacher":       ["ogretmen", "hoca", "staff", "teacher_name", "ogrt"],
    "ders":          ["lesson", "brans", "subject", "dersad"],
    "student":       ["ogrenci", "name", "ad_soyad", "student_name", "ogrenci_ad"],
    "exam_name":     ["sinav_adi", "sinav", "test_name", "test"],
    "school":        ["okul"],
    "branch":        ["sube", "subek"],
    "etut_type":     ["etut_tur", "tur"],
    "classroom":     ["derslik"],
    "yoklama":       ["attendance", "yoklama_durum"],
    "etut_kod":      ["etut_kodu", "kod"],
}

# Filtreyi standart isme cevirir.
def _canon_filter(key: str) -> str:
    k = key.lower().strip()
    for canon, aliases in _FILTER_ALIAS.items():
        if k == canon or k in aliases:
            return canon
    return k  # bilinmeyen → olduğu gibi (custom selector ile eslesebilir)


# ─── INPUT SELECTOR HARITASI ──────────────────────────────────────────────────
# Eyotek (ASP.NET WebForms) standart kontrol id pattern'lari:
#   - Tarih:      txtKayitBas, txtKayitBit, txtBas, txtBit, txtTarih, txtBeginDate
#   - Dropdown:   Ddl* (DdlClasses, DdlTeachers, DdlLessons, DdlSubek, DdlOkul)
#   - Text:       txtAdSoyad, txtSinavAdi, txtSearch, txtFilter
# Multiple fallback selectors — ilki tutmazsa siradakine gec.
# Eyotek gercek pattern'leri (inspect ile kanitlanmis):
#   - txt* (date, kod, ad gibi metin alanlari)
#   - cmb* (combobox/select — DdlClasses degil cmbSubeler kullaniyor!)
#   - chk* (checkbox)
#   - btn* (buton)
# ASP.NET Select2 wrapper'lari: visible olan #s2id_autogenN inputlari, ama
# select_option underlying <select>'e (cmb*) calisiyor.
_SELECTOR_CANDIDATES = {
    # Tarih (text input, datepicker) — Eyotek farkli sayfalarda farkli id
    # txtKayitBas/Bit (Etut Ara, Counsellor) | txtBaslangic/Bitis (Attendance) | txtBegin/End (Reports)
    "date_from": ["#txtKayitBas", "#txtBaslangic", "#txtBeginDate", "#txtBas",
                  "#txtTarihBas", "#txtBegin", "#txtBaslamaTarihi",
                  "input[id*='Baslangic']", "input[id*='Bas']:not([id*='Bit']):not([id*='Save'])",
                  "input[name*='Baslangic']", "input[name*='Bas']:not([name*='Bit'])"],
    "date_to":   ["#txtKayitBit", "#txtBitis", "#txtEndDate", "#txtBit",
                  "#txtTarihBit", "#txtEnd", "#txtBitisTarihi",
                  "input[id*='Bitis']", "input[id*='Bit']:not([id*='Save'])",
                  "input[name*='Bitis']", "input[name*='Bit']"],

    # Subesi (cmbSubeler — Kurs vb.)
    "branch":    ["#cmbSubeler", "#cmbSube", "#cmbSchool",
                  "select[id*='Subek' i]", "select[id*='Sube' i]"],
    "school":    ["#cmbOkul", "#cmbOkullar", "#cmbSchools",
                  "select[id*='School' i]", "select[id*='Okul' i]"],

    # Sinif
    "class":     ["#cmbSinif", "#cmbSiniflar", "#cmbClasses", "#cmbClass",
                  "select[id*='Sinif' i]", "select[id*='Class' i]"],

    # Ogretmen (cmbOgrtAd — pratikte boyle)
    "teacher":   ["#cmbOgrtAd", "#cmbOgretmen", "#cmbStaff", "#cmbTeacher", "#cmbTeachers",
                  "select[id*='Ogrt' i]", "select[id*='Ogretmen' i]",
                  "select[id*='Teacher' i]", "select[id*='Staff' i]"],

    # Ders (cmbDers — pratikte boyle)
    "ders":      ["#cmbDers", "#cmbLesson", "#cmbLessons",
                  "select[id*='Ders' i]:not([id*='Derslik'])",
                  "select[id*='Lesson' i]"],

    # Derslik
    "classroom": ["#cmbDerslik", "#cmbClassroom",
                  "select[id*='Derslik' i]", "select[id*='Classroom' i]"],

    # Etut tur
    "etut_type": ["#cmbEtudTuru", "#cmbEtutTuru", "#cmbEtudType",
                  "select[id*='EtudTur' i]", "select[id*='EtutTur' i]",
                  "select[id*='IndividualLessonType' i]"],

    # Yoklama durumu (Alinmis/Alinmamis)
    "yoklama":   ["#cmbYoklama", "select[id*='Yoklama' i]"],

    # Etut kodu
    "etut_kod":  ["#txtEtutKodu", "input[id*='EtutKod' i]"],

    # Ogrenci adi (text input — Select2 olabilir)
    "student":   ["#txtAdSoyad", "#TxtAdSoyad", "#txtStudentName", "#txtName",
                  "input[id*='AdSoyad' i]", "input[id*='StudentName' i]"],

    # Sinav adi
    "exam_name": ["#txtSinavAdi", "#TxtSinavAdi", "#txtTestName",
                  "input[id*='Sinav' i]", "input[id*='TestName' i]", "input[id*='ExamName' i]"],
}

# Search button candidates (in order of priority)
_SEARCH_BTN_CANDIDATES = [
    "#btnSearch", "#BtnSearch", "#btnAra", "#BtnAra",
    "input[id*='btnSearch']", "input[id*='Search']:not([id*='Result'])",
    "button[id*='Search']", "a[id*='Search']",
]

# Modal opener (on table view, click this to open filter modal)
_MODAL_OPEN_CANDIDATES = [
    "a.btn-circle.yellow", "#btnQuickSearch", "#btnFilter",
    "a[onclick*='Search']", "button[onclick*='Modal']",
]


def _load_cookies() -> list[dict]:
    if not _SESSION_FILE.exists():
        return []
    try:
        data = json.loads(_SESSION_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


async def _inject_cookies(ctx) -> int:
    """File'dan cookie'leri ctx'e merge et."""
    raw = _load_cookies()
    if not raw:
        return 0
    cookies = []
    for c in raw:
        if not c.get("name") or c.get("value") is None:
            continue
        cookies.append({
            "name": c["name"],
            "value": c["value"],
            "domain": c.get("domain") or "fermat.eyotek.com",
            "path": c.get("path") or "/",
            **{k: c[k] for k in ("expires", "httpOnly", "secure", "sameSite") if k in c and c[k] is not None}
        })
    if cookies:
        try:
            await ctx.add_cookies(cookies)
        except Exception as e:
            logger.warning(f"[NAV] Cookie inject fail: {e}")
            return 0
    return len(cookies)


async def _is_login(page) -> bool:
    """Sayfa login ekraninda mi?"""
    try:
        url = page.url.lower()
        if "login" in url or url.rstrip("/").endswith("/v1"):
            return True
        return await page.evaluate(
            "() => !!document.querySelector('input[type=password]') || !!document.getElementById('btnLogin')"
        )
    except Exception:
        return False


async def _try_selector(page, candidates: list[str], timeout_per_candidate: int = 600):
    """Adaylar arasindan ilk gorunur olani don. None doner bulamazsa.

    Her candidate icin wait_for_selector(state='visible', timeout=N) — modal
    animasyonu surdugunde de yakalar. is_visible() sync ve timeout almaz, o yuzden
    wait_for_selector kullaniyoruz.
    """
    for sel in candidates:
        try:
            el = await page.wait_for_selector(sel, state="visible", timeout=timeout_per_candidate)
            if el:
                return el, sel
        except Exception:
            continue
    return None, None


async def _fill_text_input(page, candidates: list[str], value: str) -> Optional[str]:
    """Text input'u doldur — Bootstrap datepicker + Select2 + plain text uyumlu.

    Strateji:
      1. element bul
      2. Native fill + Tab
      3. JS ile value set + change/input event dispatch + jQuery trigger
      4. (datepicker tarihiyse) bootstrap-datepicker API hook dene
    """
    el, sel = await _try_selector(page, candidates)
    if not el:
        return None
    try:
        # Adim 1: Native fill (input/change events triggers)
        try:
            await el.fill("")
            await el.fill(str(value))
        except Exception:
            pass

        # Adim 2: JS ile direkt value set + olaylari mecbur dispatch
        try:
            await page.evaluate("""
                ([selector, value]) => {
                    const el = document.querySelector(selector);
                    if (!el) return false;
                    el.value = value;
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.dispatchEvent(new Event('blur', { bubbles: true }));
                    // Bootstrap-datepicker (Eyotek'te kullaniliyor)
                    if (window.jQuery) {
                        try {
                            const $el = window.jQuery(el);
                            $el.trigger('change');
                            // bootstrap-datepicker hook
                            if (typeof $el.datepicker === 'function') {
                                try { $el.datepicker('update', value); } catch(e) {}
                            }
                        } catch(e) {}
                    }
                    return true;
                }
            """, [sel, str(value)])
        except Exception as e:
            logger.debug(f"[NAV] JS fill fail {sel}: {e}")

        # Adim 3: Tab press (focus disina cik, validation tetikle)
        try:
            await el.press("Tab")
        except Exception:
            pass

        return sel
    except Exception as e:
        logger.debug(f"[NAV] fill_text fail {sel}: {e}")
        return None


async def _fill_dropdown(page, candidates: list[str], value: str) -> Optional[str]:
    """Dropdown'da label veya value matchle. Hangi selector'la doldugunu donder."""
    el, sel = await _try_selector(page, candidates)
    if not el:
        return None
    try:
        # Once label match dene
        try:
            await el.select_option(label=str(value))
            return sel
        except Exception:
            pass
        # Sonra value match
        try:
            await el.select_option(value=str(value))
            return sel
        except Exception:
            pass
        # Fuzzy: text contains
        opts = await el.query_selector_all("option")
        for opt in opts:
            text = ((await opt.text_content()) or "").strip()
            if value.lower() in text.lower():
                opt_value = await opt.get_attribute("value")
                if opt_value:
                    await el.select_option(value=opt_value)
                    return sel
        return None
    except Exception as e:
        logger.debug(f"[NAV] fill_dropdown fail {sel}: {e}")
        return None


async def _open_search_modal(page) -> bool:
    """Eger sayfada filtre modal'i varsa ac. Aciksa True don.

    'Acik' tanimi: bir .modal element'i .show veya .in class'ina sahip OLUP
    icinde gorunur input'lar var (style 'display: block' tek basina yetersiz).
    """
    # Once: zaten acik mi?
    try:
        already_open = await page.evaluate("""
            () => {
                const ms = document.querySelectorAll('.modal.show, .modal.in');
                for (const m of ms) {
                    const r = m.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0) return true;
                }
                return false;
            }
        """)
        if already_open:
            return True
    except Exception:
        pass

    # Aday butonlardan birini tikla
    el, sel = await _try_selector(page, _MODAL_OPEN_CANDIDATES, timeout_per_candidate=1500)
    if not el:
        return False
    try:
        await el.click()
        # Modal fade animation: ~300-500ms. Inputs interactable olsun diye 1200ms bekle.
        # Ek olarak, gercekten acildi mi onaylamak icin .modal.show'u bekle.
        try:
            await page.wait_for_selector(".modal.show, .modal.in", state="visible", timeout=2500)
        except Exception:
            pass
        await page.wait_for_timeout(800)  # Inputs render bekle
        return True
    except Exception:
        return False


async def _click_search(page) -> Optional[str]:
    """Ara/Search butonuna tikla."""
    el, sel = await _try_selector(page, _SEARCH_BTN_CANDIDATES, timeout_per_candidate=1500)
    if not el:
        return None
    try:
        await el.click()
        return sel
    except Exception as e:
        logger.debug(f"[NAV] search click fail {sel}: {e}")
        return None


async def _read_table(page, max_rows: int) -> tuple[list[str], list[dict]]:
    """Sayfadaki ilk anlamli tabloyu oku (en cok satira sahip olan).

    Crash-safe: tablo yoksa bos ([], []) doner.
    """
    try:
        # Tek evaluate icinde header+rows topla — JSHandle null sorunu yok
        result = await page.evaluate(f"""
            () => {{
                const tables = Array.from(document.querySelectorAll('table'));
                if (!tables.length) return {{ headers: [], rows: [] }};
                // En cok tbody tr'ye sahip table
                tables.sort((a, b) => b.querySelectorAll('tbody tr').length - a.querySelectorAll('tbody tr').length);
                const t = tables[0];
                const ths = t.querySelectorAll('thead th, tr:first-child th');
                const headers = Array.from(ths).map(th => (th.innerText || '').trim());
                const trs = Array.from(t.querySelectorAll('tbody tr')).slice(0, {max_rows});
                const rows = trs.map(tr =>
                    Array.from(tr.querySelectorAll('td')).map(td => (td.innerText || '').trim())
                );
                return {{ headers, rows }};
            }}
        """)
    except Exception as e:
        logger.debug(f"[NAV] _read_table fail: {e}")
        return [], []

    headers = result.get("headers", [])
    raw_rows = result.get("rows", [])
    rows_data = []
    for r in raw_rows:
        row = {}
        for i, cell in enumerate(r):
            col = headers[i] if i < len(headers) else f"col_{i}"
            row[col] = cell
        if any((v or "").strip() for v in row.values()):
            rows_data.append(row)
    return headers, rows_data


_INSPECT_JS = """
() => {
    function descLabel(el) {
        if (el.id) {
            const lbl = document.querySelector(`label[for="${el.id}"]`);
            if (lbl) return (lbl.innerText || '').trim();
        }
        const fg = el.closest('.form-group, .col, .row, td, div');
        if (fg) {
            const lbl = fg.querySelector('label');
            if (lbl) return (lbl.innerText || '').trim();
        }
        return el.placeholder || '';
    }
    const visible = el => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
    };
    const inputs = Array.from(document.querySelectorAll('input')).filter(visible).map(el => ({
        id: el.id, name: el.name || '', type: el.type,
        placeholder: el.placeholder || '',
        value: el.value || '',
        label: descLabel(el),
        cls: el.className || '',
    }));
    const selects = Array.from(document.querySelectorAll('select')).filter(visible).map(el => ({
        id: el.id, name: el.name || '',
        label: descLabel(el),
        options: Array.from(el.options).slice(0, 10).map(o => ({v: o.value, t: (o.innerText || '').trim()})),
        optionCount: el.options.length,
    }));
    const buttons = Array.from(document.querySelectorAll('button, input[type=button], input[type=submit], a.btn'))
        .filter(visible).slice(0, 30).map(el => ({
            id: el.id, name: el.name || '',
            text: (el.innerText || el.value || '').trim().slice(0, 60),
            cls: el.className || '',
        }));
    // Modal'lari say (ister hidden ister visible)
    const modals = Array.from(document.querySelectorAll('.modal, [role=dialog], .ui-dialog'));
    const modalsList = modals.map(m => ({
        id: m.id || '',
        cls: m.className || '',
        visible: visible(m),
        innerInputs: m.querySelectorAll('input, select').length,
    }));
    const tables = document.querySelectorAll('table').length;
    const tbodyRows = document.querySelectorAll('table tbody tr').length;
    return { inputs, selects, buttons, modals: modalsList, tables, tbodyRows };
}
"""


async def inspect_page_form(page_path: str, mode: str = "auto") -> dict:
    """Sayfadaki TUM form input/select/button'lari listele — schema discovery icin.

    mode:
      - "auto"   : modal varsa ac, sonra inspect
      - "raw"    : modal acmadan oldugu gibi
      - "modal"  : modal'i zorla ac (ARA gibi butonu tikla)
      - "after_search" : Search/ARA tikla, sonra inspect (tablo state'i)

    Returns: {url, inputs, selects, buttons, modals, tables, tbodyRows}
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {"error": "Playwright kurulu degil"}

    pw = None
    page = None
    try:
        pw = await async_playwright().start()
        browser = await pw.chromium.connect_over_cdp(_CDP_URL)
        ctx = browser.contexts[0]
        await _inject_cookies(ctx)
        page = await ctx.new_page()
        await page.goto(f"{_BASE_URL}{page_path}", timeout=20000, wait_until="domcontentloaded")
        await page.wait_for_timeout(2500)
        if await _is_login(page):
            return {"error": "AUTH_EXPIRED", "url": page.url}

        # MODE'a gore aksiyon
        if mode == "auto":
            await _open_search_modal(page)
            await page.wait_for_timeout(800)
        elif mode == "modal":
            # Tum candidates'i sirayla dene
            for sel in _MODAL_OPEN_CANDIDATES:
                try:
                    el = await page.query_selector(sel)
                    if el and await el.is_visible():
                        await el.click()
                        await page.wait_for_timeout(1200)
                        break
                except Exception:
                    continue
        elif mode == "after_search":
            # Once modal ac
            await _open_search_modal(page)
            await page.wait_for_timeout(500)
            # Sonra search
            await _click_search(page)
            await page.wait_for_timeout(4000)
        # raw: hicbir sey yapma

        info = await page.evaluate(_INSPECT_JS)
        info["url"] = page.url
        info["page_path"] = page_path
        info["mode"] = mode
        return info
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:200]}"}
    finally:
        try:
            if page:
                await page.close()
        except Exception:
            pass
        try:
            if pw:
                await pw.stop()
        except Exception:
            pass


# ─── PUBLIC API ───────────────────────────────────────────────────────────────

async def navigate(
    page_path: str,
    filters: Optional[dict] = None,
    max_rows: int = 50,
    drill: Optional[dict] = None,
    custom_selectors: Optional[dict] = None,
    wait_after_search_ms: int = 4500,
) -> dict:
    """Generic Eyotek page navigator.

    Args:
        page_path: "Student/individual-lesson" (BASE_URL'a eklenir)
        filters:  {"date_from":"26.04.2026", "ders":"Matematik", ...}
        max_rows: tabloda max kac satir okunsun
        drill:    {"row":0, "link_text":"Detay"} — bir satira tikla, alt sayfayi oku (opsiyonel)
        custom_selectors: site_map.json'dan page-specific override (filter selector overrides)
        wait_after_search_ms: search butonuna basildiktan sonra tablo render bekleme

    Returns:
        {
            "success": bool,
            "page_path": str,
            "final_url": str,
            "columns": [...],
            "rows": [...],
            "row_count": int,
            "filters_applied": {filter: selector_used} | {},
            "filters_failed":  [filter,...],
            "modal_opened": bool,
            "search_clicked": bool,
            "drill": {...} | None,
            "error_code": "AUTH_EXPIRED" | "NO_DATA" | "FILTER_BAD" | "TIMEOUT" | None,
            "error": str | None,
            "debug": {...}
        }
    """
    filters = filters or {}
    custom_selectors = custom_selectors or {}
    result = {
        "success": False, "page_path": page_path, "final_url": None,
        "columns": [], "rows": [], "row_count": 0,
        "filters_applied": {}, "filters_failed": [],
        "modal_opened": False, "search_clicked": False, "drill": None,
        "error_code": None, "error": None, "debug": {},
    }

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        result["error_code"] = "ENV"
        result["error"] = "Playwright kurulu degil"
        return result

    pw = None
    page = None
    try:
        pw = await async_playwright().start()
        browser = await pw.chromium.connect_over_cdp(_CDP_URL)
        ctx = browser.contexts[0]

        injected = await _inject_cookies(ctx)
        result["debug"]["cookies_injected"] = injected

        page = await ctx.new_page()
        try:
            await page.goto(f"{_BASE_URL}{page_path}", timeout=20000, wait_until="domcontentloaded")
        except Exception as e:
            result["error_code"] = "TIMEOUT"
            result["error"] = f"Sayfa goto timeout: {str(e)[:200]}"
            return result

        await page.wait_for_timeout(2500)
        result["final_url"] = page.url

        # AUTH check
        if await _is_login(page):
            result["error_code"] = "AUTH_EXPIRED"
            result["error"] = (
                f"Eyotek oturumu gecersiz (cookie inject={injected} ama login'e dusuldu). "
                f"Neo: 'eyotek baglan' yaz."
            )
            return result

        # MODAL ac (gerekiyorsa)
        modal_opened = await _open_search_modal(page)
        result["modal_opened"] = modal_opened
        if modal_opened:
            await page.wait_for_timeout(1200)  # Inputs interactable olsun

        # FILTRELERI UYGULA
        for raw_key, raw_value in filters.items():
            if raw_value in (None, "", []):
                continue
            canon = _canon_filter(raw_key)
            # Page-specific override?
            override = custom_selectors.get(canon) or custom_selectors.get(raw_key)
            candidates = ([override] if override else []) + _SELECTOR_CANDIDATES.get(canon, [])
            if not candidates:
                # Custom selector verilmemis ve standart map'te yok
                # Doğrudan raw_key'i CSS selector olarak dene (#txtSomething gibi)
                if raw_key.startswith(("#", ".", "input", "select")):
                    candidates = [raw_key]
                else:
                    result["filters_failed"].append(raw_key)
                    continue

            # Tarih ve metin alanlari -> text input; cmb* -> dropdown
            is_dropdown = canon in ("class", "teacher", "ders", "school", "branch",
                                     "etut_type", "classroom", "yoklama")
            if is_dropdown:
                used = await _fill_dropdown(page, candidates, str(raw_value))
            else:
                used = await _fill_text_input(page, candidates, str(raw_value))

            if used:
                result["filters_applied"][canon] = used
            else:
                result["filters_failed"].append(canon)

        # SEARCH
        if filters or modal_opened:
            search_used = await _click_search(page)
            if search_used:
                result["search_clicked"] = True
                result["debug"]["search_btn"] = search_used
                # Tablo render icin bekle
                await page.wait_for_timeout(wait_after_search_ms)

        # TABLO OKU
        cols, rows_data = await _read_table(page, max_rows)
        result["columns"] = cols
        result["rows"] = rows_data
        result["row_count"] = len(rows_data)

        # DRILL (opsiyonel)
        if drill and rows_data:
            row_idx = int(drill.get("row", 0))
            link_text = drill.get("link_text", "")
            try:
                # Satira git ve ilgili linki tikla
                drilled = await page.evaluate(f"""
                    (linkText) => {{
                        const tables = document.querySelectorAll('table');
                        let bestTable = null;
                        let maxRows = 0;
                        for (const t of tables) {{
                            const n = t.querySelectorAll('tbody tr').length;
                            if (n > maxRows) {{ maxRows = n; bestTable = t; }}
                        }}
                        if (!bestTable) return null;
                        const rows = bestTable.querySelectorAll('tbody tr');
                        const tr = rows[{row_idx}];
                        if (!tr) return null;
                        const links = tr.querySelectorAll('a, button, input[type=button]');
                        for (const a of links) {{
                            const txt = (a.innerText || a.value || '').trim().toLowerCase();
                            if (!linkText || txt.includes(linkText.toLowerCase())) {{
                                a.click();
                                return txt;
                            }}
                        }}
                        return null;
                    }}
                """, link_text)
                await page.wait_for_timeout(3000)
                if drilled:
                    drill_cols, drill_rows = await _read_table(page, max_rows)
                    result["drill"] = {
                        "clicked_link": drilled,
                        "url": page.url,
                        "columns": drill_cols,
                        "rows": drill_rows,
                    }
            except Exception as e:
                result["drill"] = {"error": f"drill fail: {str(e)[:200]}"}

        # SUCCESS / NO_DATA ayrimi
        result["success"] = True
        if not rows_data and result["search_clicked"] and not result["filters_failed"]:
            result["error_code"] = "NO_DATA"
            result["error"] = "Filtreler uygulandi ama tablo bos — kayit yok."

        if result["filters_failed"]:
            # Yumusak hata: bazi filtreler bulunamadi ama yine de tablo okuduk
            result["error_code"] = "FILTER_BAD"
            result["error"] = (
                f"Bilinmeyen/eslesmeyen filtreler: {result['filters_failed']}. "
                f"Sayfada bu input'lar yok veya isim farkli."
            )

        return result

    except Exception as e:
        result["error_code"] = "EXCEPTION"
        result["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        logger.exception(f"[NAV] navigate exception")
        return result

    finally:
        try:
            if page:
                await page.close()
        except Exception:
            pass
        try:
            if pw:
                await pw.stop()
        except Exception:
            pass


# ─── HIZLI YARDIMCILAR ────────────────────────────────────────────────────────

def _tr_date(d) -> str:
    """date veya datetime -> dd.mm.yyyy (Eyotek formati)."""
    if isinstance(d, str):
        return d
    if isinstance(d, (date, datetime)):
        return d.strftime("%d.%m.%Y")
    return str(d)


def date_range_for(label: str) -> tuple[str, str]:
    """Dogal dil tarih label -> (date_from, date_to) Eyotek format.

    Destekli labels:
      - bugun, today
      - dun, yesterday
      - yarin, tomorrow
      - geçen_hafta, last_week
      - bu_hafta, this_week
      - bu_ay, this_month
      - geçen_ay, last_month
      - son_7_gun, last_7_days
      - son_30_gun, last_30_days
      - 3_gun_once -> 3 gun once tek gun
      - N_gun_once (N integer)
    """
    today = date.today()
    label_l = label.lower().replace(" ", "_").replace("-", "_")

    if label_l in ("bugun", "today"):
        return _tr_date(today), _tr_date(today)
    if label_l in ("dun", "yesterday"):
        d = today - timedelta(days=1)
        return _tr_date(d), _tr_date(d)
    if label_l in ("yarin", "tomorrow"):
        d = today + timedelta(days=1)
        return _tr_date(d), _tr_date(d)
    if label_l in ("bu_hafta", "this_week"):
        start = today - timedelta(days=today.weekday())
        return _tr_date(start), _tr_date(today)
    if label_l in ("gecen_hafta", "last_week", "geçen_hafta"):
        start = today - timedelta(days=today.weekday() + 7)
        end = start + timedelta(days=6)
        return _tr_date(start), _tr_date(end)
    if label_l in ("bu_ay", "this_month"):
        start = today.replace(day=1)
        return _tr_date(start), _tr_date(today)
    if label_l in ("gecen_ay", "last_month", "geçen_ay"):
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        first_prev = last_prev.replace(day=1)
        return _tr_date(first_prev), _tr_date(last_prev)
    if label_l in ("son_7_gun", "last_7_days"):
        return _tr_date(today - timedelta(days=7)), _tr_date(today)
    if label_l in ("son_30_gun", "last_30_days"):
        return _tr_date(today - timedelta(days=30)), _tr_date(today)

    # "N_gun_once" pattern
    m = re.match(r"^(\d+)_?gun_?once$", label_l)
    if m:
        n = int(m.group(1))
        d = today - timedelta(days=n)
        return _tr_date(d), _tr_date(d)

    # Fallback: today only
    return _tr_date(today), _tr_date(today)


# ─── CLI / SMOKE TEST ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    async def _smoke():
        path = sys.argv[1] if len(sys.argv) > 1 else "Student/individual-lesson"
        from_d = sys.argv[2] if len(sys.argv) > 2 else _tr_date(date.today() - timedelta(days=3))
        to_d = sys.argv[3] if len(sys.argv) > 3 else _tr_date(date.today())
        print(f"--- Navigate to {path} | filters: date_from={from_d}, date_to={to_d} ---")
        r = await navigate(path, filters={"date_from": from_d, "date_to": to_d}, max_rows=10)
        print(f"success={r['success']} rows={r['row_count']} err={r.get('error_code')}/{(r.get('error') or '')[:120]}")
        print(f"filters_applied={r['filters_applied']}")
        print(f"filters_failed={r['filters_failed']}")
        print(f"columns={r['columns'][:8]}")
        for row in r["rows"][:3]:
            print(f"  ROW: {row}")

    async def _inspect():
        # CLI: python -m eyotek_navigator inspect <path> [mode]
        path = sys.argv[2] if len(sys.argv) > 2 else "Student/individual-lesson"
        mode = sys.argv[3] if len(sys.argv) > 3 else "auto"
        print(f"--- INSPECT {path} (mode={mode}) ---")
        info = await inspect_page_form(path, mode=mode)
        if info.get("error"):
            print(f"ERROR: {info['error']}")
            return
        print(f"URL: {info.get('url')}")
        print(f"Tables: {info.get('tables', 0)}  tbody_rows: {info.get('tbodyRows', 0)}")
        print(f"\n=== MODALS ({len(info.get('modals', []))}) ===")
        for m in info.get("modals", []):
            print(f"  #{m.get('id') or '<noid>'} visible={m.get('visible')} inner_inputs={m.get('innerInputs')} cls='{m.get('cls','')[:50]}'")
        print(f"\n=== INPUTS ({len(info.get('inputs', []))}) ===")
        for i in info.get("inputs", []):
            extra = f" name='{i['name']}'" if i.get("name") else ""
            print(f"  [{i['type']}] #{i.get('id') or '<noid>'}{extra} label='{i.get('label','')[:40]}' placeholder='{i.get('placeholder','')[:30]}'")
        print(f"\n=== SELECTS ({len(info.get('selects', []))}) ===")
        for s in info.get("selects", []):
            print(f"  #{s.get('id') or '<noid>'} name='{s.get('name','')}' label='{s.get('label','')[:40]}' options={s.get('optionCount', 0)}")
            for o in s.get("options", [])[:3]:
                print(f"      - {o.get('v','')}: {o.get('t','')[:50]}")
        print(f"\n=== BUTTONS ({len(info.get('buttons', []))}) ===")
        for b in info.get("buttons", [])[:15]:
            print(f"  #{b.get('id') or '<noid>'} '{b.get('text','')}' cls='{b.get('cls','')[:40]}'")

    if len(sys.argv) > 1 and sys.argv[1] == "inspect":
        asyncio.run(_inspect())
    else:
        asyncio.run(_smoke())
