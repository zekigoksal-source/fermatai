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


# 25.41 (Neo bug 7 May): Chrome cleanup → CDP regression fix.
# eski: connect_over_cdp(localhost:9333) → Chrome kapandı → bağlantı kopyu
# yeni: önce CDP dene, fail olursa headless launch + cookie inject (helper pattern)
async def _navigator_browser(pw):
    """Navigator için browser+context döner — CDP fail'da headless launch.

    Returns: (browser, ctx) — caller browser.close() yapmalı.
    """
    # 1. CDP'ye dene (eski kod uyumlu)
    try:
        browser = await pw.chromium.connect_over_cdp(_CDP_URL)
        ctx = browser.contexts[0]
        return browser, ctx, "cdp"
    except Exception:
        pass

    # 2. Fail → headless launch + cookie inject (smart_sync ile aynı pattern)
    browser = await pw.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage",
              "--disable-setuid-sandbox", "--disable-gpu"],
    )
    ctx = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1366, "height": 768},
        locale="tr-TR",
    )
    # Cookie inject
    try:
        # Mevcut SESSION_FILE'dan cookie yükle (helper'a benzer)
        if _SESSION_FILE.exists():
            import json as _j
            cookies = _j.loads(_SESSION_FILE.read_text(encoding="utf-8"))
            if isinstance(cookies, list) and cookies:
                await ctx.add_cookies(cookies)
                logger.debug(f"[NAVIGATOR] Cookie inject: {len(cookies)} cookie")
    except Exception as _ce:
        logger.warning(f"[NAVIGATOR] Cookie inject hata: {_ce}")
    return browser, ctx, "headless"

# ─── FILTER ALIAS HARITASI ────────────────────────────────────────────────────
# Bot/planner ne kullanirsa kullansin, yakalanir.
_FILTER_ALIAS = {
    "date_from":     ["basla", "baslangic", "ilk_tarih", "tarih_bas", "from", "start", "veris_bas"],
    "date_to":       ["bitis", "son_tarih", "tarih_bit", "to", "end", "veris_bit"],
    "class":         ["sinif", "klass", "class_name"],
    "teacher":       ["ogretmen", "hoca", "staff", "teacher_name", "ogrt"],
    "ders":          ["lesson", "brans", "subject", "dersad"],
    "student":       ["ogrenci", "name", "ad_soyad", "student_name", "ogrenci_ad"],
    "exam_name":     ["sinav_adi", "sinav_ad", "test_name", "test"],
    "school":        ["okul"],
    "branch":        ["sube", "subek"],
    "etut_type":     ["etut_tur"],
    "classroom":     ["derslik"],
    "yoklama":       ["attendance", "yoklama_durum"],
    "etut_kod":      ["etut_kodu"],
    "sinav_kodu":    ["snv_kod", "kod_sinav"],
    "sinav_turu":    ["snv_tur", "exam_type"],
    "sinav_kategori":["snv_kategori"],
    "devre":         ["donem", "term"],
    "odev_tur":      ["homework_tur", "odev_type"],
    "durum":         ["status", "kontrol_durumu"],
    "student_first": ["ad", "first_name"],
    "student_last":  ["soyad", "last_name"],
    "liste_turu":    ["list_type"],
    "kontrol_from":  ["kontrol_bas", "control_from"],
    "kontrol_to":    ["kontrol_bit", "control_to"],
    "sezon":         ["season", "donem_yili"],
    "currency":      ["para_birimi"],
    "ic_dis":        ["in_out"],
    "silinenleri_cikar": ["silinmis_haric", "exclude_deleted"],
    "odeme_sekli":   ["payment_method", "odeme_tipi"],
    "kullanici":     ["user", "operator", "kim_girdi"],
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
    # txtKayitBas/Bit (Etut, Counsellor, test-transferred) | txtBaslangic/Bitis (Attendance) |
    # txtVerisBas/Bit (homework-reports) | txtKayitBasVer/BitVer (homework-search)
    "date_from": ["#txtKayitBas", "#txtBaslangic", "#txtVerisBas", "#txtKayitBasVer",
                  "#txtBeginDate", "#txtBas", "#txtTarihBas", "#txtBegin", "#txtBaslamaTarihi",
                  "input[id*='Baslangic']", "input[id*='VerisBas']", "input[id*='KayitBas']:not([id*='Kont']):not([id*='Bit'])",
                  "input[id*='Bas']:not([id*='Bit']):not([id*='Save']):not([id*='Kont'])",
                  "input[name*='Baslangic']", "input[name*='Bas']:not([name*='Bit'])"],
    "date_to":   ["#txtKayitBit", "#txtBitis", "#txtVerisBit", "#txtKayitBitVer",
                  "#txtEndDate", "#txtBit", "#txtTarihBit", "#txtEnd", "#txtBitisTarihi",
                  "input[id*='Bitis']", "input[id*='VerisBit']", "input[id*='KayitBit']:not([id*='Kont'])",
                  "input[id*='Bit']:not([id*='Save']):not([id*='Kont'])",
                  "input[name*='Bitis']", "input[name*='Bit']:not([name*='Kont'])"],
    # Kontrol Tarihi — odev sayfalarinda ayri filter
    "kontrol_from": ["#txtKayitBasKont", "#txtKontrolBas", "input[id*='KontrolBas']", "input[id*='KayitBasKont']"],
    "kontrol_to":   ["#txtKayitBitKont", "#txtKontrolBit", "input[id*='KontrolBit']", "input[id*='KayitBitKont']"],

    # Subesi — Eyotek varyantlari: cmbSubeler (etut/raporlar) | cmbsube lowercase (financial-operation)
    "branch":    ["#cmbSubeler", "#cmbSube", "#cmbsube", "#cmbSchool",
                  "select[id*='Subek' i]", "select[id*='Sube' i]"],
    "school":    ["#cmbOkul", "#cmbOkullar", "#cmbSchools",
                  "select[id*='School' i]", "select[id*='Okul' i]"],

    # Sinif
    "class":     ["#cmbSinif", "#cmbSiniflar", "#cmbClasses", "#cmbClass",
                  "select[id*='Sinif' i]", "select[id*='Class' i]"],

    # Ogretmen — Eyotek 3 farkli isim kullaniyor: cmbOgrtAd / cmbOgretmenler / cmbHoca
    "teacher":   ["#cmbOgrtAd", "#cmbOgretmenler", "#cmbHoca", "#cmbOgretmen",
                  "#cmbStaff", "#cmbTeacher", "#cmbTeachers",
                  "select[id*='Ogrt' i]", "select[id*='Ogretmen' i]",
                  "select[id*='Hoca' i]", "select[id*='Teacher' i]", "select[id*='Staff' i]"],

    # Ders — cmbDers (etut/odev-search) | cmbBrans (odev-reports)
    "ders":      ["#cmbDers", "#cmbBrans", "#cmbLesson", "#cmbLessons",
                  "select[id*='Brans' i]",
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

    # Sinav kodu (test-transferred sayfasinda)
    "sinav_kodu": ["#txtKod", "input[id*='SnvKod' i]", "input[id*='SinavKod' i]"],

    # Sinav turu (LGS / TYT / YKS) — test-transferred
    "sinav_turu": ["#cmbSinavTuru", "#cmbSnvTur", "select[id*='SinavTur' i]"],

    # Sinav kategori — test-transferred
    "sinav_kategori": ["#cmbSinavKategori", "select[id*='SinavKategori' i]"],

    # Devre (1.Snf, 2.Snf, Mezun) — test-transferred + raporlar
    "devre":     ["#cmbDevre", "select[id*='Devre' i]"],

    # Odev turu (Odev / Online Odev) — homework-search/reports
    "odev_tur":  ["#cmbTur", "select[id*='Tur' i]:not([id*='Turu' i])"],

    # Durum (Kontrol edildi / edilmedi) — homework-search
    "durum":     ["#cmbDurum", "select[id*='Durum' i]"],

    # Ogrenci adi (homework sayfalarinda ayri ad/soyad)
    "student_first": ["#txtAd", "input[id*='txtAd' i]:not([id*='Soyad'])"],
    "student_last":  ["#txtSoyad", "input[id*='Soyad' i]"],

    # Liste turu (homework-reports — Ogrenci Aylik / Ogretmen Aylik vs)
    "liste_turu": ["#lstKnt", "select[id*='Liste' i]"],

    # Sezon — cmbSezonlar (raporlar) | cmbSezon (financial-operation)
    "sezon":     ["#cmbSezonlar", "#cmbSezon", "select[id*='Sezon' i]"],

    # Odeme sekli (Nakit/Banka/Cek/Senet/Kart) — financial-operation
    "odeme_sekli": ["#cmbOdemeSekli", "select[id*='OdemeSekli' i]", "select[id*='Odeme' i]"],

    # Kullanici (kim girdi — Mahsum Yalcin vs) — financial-operation
    "kullanici":   ["#cmbUser", "#cmbKullanici", "select[id*='User' i]:not([id*='Search'])"],

    # Para birimi (Turk Lirasi default)
    "currency":  ["#DdlCurrency", "select[id*='Currency' i]"],

    # Ic/Dis filtre (kayit raporlarinda)
    "ic_dis":    ["#CbInOut", "input[id*='InOut' i][type=checkbox]"],

    # Silinenleri cikar (kayit raporlarinda)
    "silinenleri_cikar": ["#chkSilinen", "input[id*='Silinen' i][type=checkbox]"],
}

# Search button candidates (in order of priority)
# NOT: financial-operation #btnSearchGunluk modal-internal, #btnSearch outer
_SEARCH_BTN_CANDIDATES = [
    "#btnSearchGunluk",  # financial-operation modal'i icindeki ARA
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
        # Oturum 25.29 KRITIK FIX: bootstrap-datepicker('update', value) cagrisi
        # SADECE deger tarih formatindaysa yapilir. Aksi halde "Cagan" gibi isimleri
        # datepicker bugunun tarihiyle (today fallback) overwrite ediyordu.
        # Tespit: drill_inspect testi → txtAdQuick'e 'Cagan' yazildi, sonra deger
        # '04/28/2026' oldu — bu, datepicker'in 'Cagan'i parse edemeyince today
        # default'una donmesi yuzunden.
        import re as _re_mod
        is_date_like = bool(_re_mod.match(
            r"^\s*\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\s*$", str(value or "")
        ))
        try:
            await page.evaluate("""
                ([selector, value, isDate]) => {
                    const el = document.querySelector(selector);
                    if (!el) return false;
                    el.value = value;
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.dispatchEvent(new Event('blur', { bubbles: true }));
                    if (window.jQuery) {
                        try {
                            const $el = window.jQuery(el);
                            $el.trigger('change');
                            // bootstrap-datepicker hook — SADECE tarih formatinda
                            if (isDate && typeof $el.datepicker === 'function') {
                                try { $el.datepicker('update', value); } catch(e) {}
                            }
                        } catch(e) {}
                    }
                    return true;
                }
            """, [sel, str(value), is_date_like])
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
    """Dropdown'da label veya value matchle. Select2 wrapper destekli.

    Eyotek'in select'leri genelde Select2 ile sarmalanmis — visible degil,
    Select2 wrapper interceptlemiyor. Strateji:
      1. query_selector (visibility check YOK — underlying <select> hidden olabilir)
      2. select_option (label/value/fuzzy) — Playwright native
      3. JS: el.value = optionValue + dispatch change events
      4. jQuery Select2 API: $(el).select2('val', val).trigger('change') —
         Select2 component'i bu sekilde update eder.
    """
    el = None
    sel = None
    # query_selector ile bul (wait_for visible KULLANMA — Select2 wrapper hidden)
    for s in candidates:
        try:
            cand = await page.query_selector(s)
            if cand:
                el = cand
                sel = s
                break
        except Exception:
            continue
    if not el:
        return None

    try:
        # Adim 1: Playwright native select_option (label match)
        try:
            await el.select_option(label=str(value))
            # Select2'i bilgilendir
            await page.evaluate(
                """([s]) => {
                    const e = document.querySelector(s);
                    if (e && window.jQuery) {
                        try { window.jQuery(e).trigger('change'); } catch(_){}
                    }
                }""",
                [sel],
            )
            return sel
        except Exception:
            pass
        # Adim 2: value match
        try:
            await el.select_option(value=str(value))
            await page.evaluate(
                """([s]) => {
                    const e = document.querySelector(s);
                    if (e && window.jQuery) {
                        try { window.jQuery(e).trigger('change'); } catch(_){}
                    }
                }""",
                [sel],
            )
            return sel
        except Exception:
            pass

        # Adim 3: Fuzzy text contains — value attribute alip select
        try:
            opts = await el.query_selector_all("option")
            for opt in opts:
                text = ((await opt.text_content()) or "").strip()
                if value.lower() in text.lower():
                    opt_value = await opt.get_attribute("value")
                    if opt_value:
                        try:
                            await el.select_option(value=opt_value)
                        except Exception:
                            pass
                        # JS direkt set + jQuery trigger
                        await page.evaluate(
                            """([s, optVal]) => {
                                const e = document.querySelector(s);
                                if (!e) return false;
                                e.value = optVal;
                                e.dispatchEvent(new Event('change', {bubbles: true}));
                                if (window.jQuery) {
                                    try {
                                        const $e = window.jQuery(e);
                                        $e.val(optVal).trigger('change');
                                        // Select2 ozel API
                                        if (typeof $e.select2 === 'function') {
                                            try { $e.select2('val', optVal); } catch(_){}
                                        }
                                    } catch(_){}
                                }
                                return true;
                            }""",
                            [sel, opt_value],
                        )
                        return sel
        except Exception:
            pass

        # Adim 4: Pure JS — Select2 jQuery API (label/value bilinmiyorsa text match'le bul)
        used = await page.evaluate(
            """([s, val]) => {
                const e = document.querySelector(s);
                if (!e) return false;
                const valLower = String(val).toLowerCase();
                let optValue = null;
                for (const opt of e.options) {
                    const t = (opt.text || '').toLowerCase();
                    const v = (opt.value || '').toLowerCase();
                    if (t === valLower || v === valLower || t.includes(valLower)) {
                        optValue = opt.value;
                        break;
                    }
                }
                if (!optValue) return false;
                e.value = optValue;
                e.dispatchEvent(new Event('change', {bubbles: true}));
                if (window.jQuery) {
                    try {
                        const $e = window.jQuery(e);
                        $e.val(optValue).trigger('change');
                        if (typeof $e.select2 === 'function') {
                            try { $e.select2('val', optValue); } catch(_){}
                        }
                    } catch(_){}
                }
                return optValue;
            }""",
            [sel, str(value)],
        )
        return sel if used else None
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
                const all = Array.from(document.querySelectorAll('table'));
                if (!all.length) return {{ headers: [], rows: [] }};
                // UI tablolarini disla (checkbox-list, column-selector vb.)
                const isUiTable = (t) => {{
                    const cls = (t.className || '').toLowerCase();
                    const id  = (t.id || '').toLowerCase();
                    if (cls.includes('checkbox-list')) return true;
                    if (cls.includes('column-list')) return true;
                    // chk* id pattern (chkEkalan, chkColumns vs)
                    if (/^chk/.test(id)) return true;
                    // role-grid degil ama tbody'de input checkbox cogunlukta?
                    const tdCount = t.querySelectorAll('tbody td').length || 1;
                    const cbCount = t.querySelectorAll('tbody input[type=checkbox]').length;
                    if (cbCount > 0 && cbCount / tdCount > 0.6) return true;
                    return false;
                }};
                // 1) thead+th olan ve UI olmayan tablolar
                let cands = all.filter(t => !isUiTable(t)
                    && t.querySelectorAll('thead th').length > 0);
                // 2) thead yoksa, ilk satirda th olan (header-row tablolar)
                if (!cands.length) {{
                    cands = all.filter(t => !isUiTable(t)
                        && t.querySelectorAll('tr:first-child th').length > 0);
                }}
                // 3) Hala yok — UI olmayan tum tablolar
                if (!cands.length) {{
                    cands = all.filter(t => !isUiTable(t));
                }}
                // 4) Fallback — orijinal davranis
                if (!cands.length) cands = all;
                cands.sort((a, b) => b.querySelectorAll('tbody tr').length - a.querySelectorAll('tbody tr').length);
                const t = cands[0];
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
        # 25.41: CDP fail'da headless launch + cookie inject
        browser, ctx, _bmode = await _navigator_browser(pw)
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

_TAB_NAME_TO_ID = {
    # financial-operation tab map (Neo screenshot)
    "ogrenci taksitleri": "ogrenciTab",
    "ogrenci": "ogrenciTab",
    "taksit": "ogrenciTab",
    "ozet": "ozetTab",
    "diger gelirler": "digerGelirlerTab",
    "ucretli faaliyetler": "ekstraOgrenciGelirTab",
    "odemeler": "odemeTab",
    "odeme": "odemeTab",
    "giderler": "giderTab",
    "gider": "giderTab",
    "kredi kartlari": "kartTab",
    "maas odemeleri": "maasTab",
    "maas": "maasTab",
    "virman": "virmanTab",
    "kullanici": "kullaniciTab",
}


async def _click_tab(page, tab_name_or_id: str) -> Optional[str]:
    """Tab adina veya id'ye gore Bootstrap tab tikla. None doner bulamazsa."""
    target = tab_name_or_id.strip().lower()
    # Map'le canonical id'ye cevir
    tab_id = _TAB_NAME_TO_ID.get(target, tab_name_or_id.replace(" ", ""))
    # selector adaylari (id ile veya text match)
    candidates = [
        f'a[href="#{tab_id}"]',
        f'a[href$="#{tab_id}"]',
        f'#{tab_id}-link',
    ]
    el, sel = await _try_selector(page, candidates, timeout_per_candidate=800)
    if not el:
        # Text match fallback
        try:
            await page.evaluate(f"""
                () => {{
                    const tabs = Array.from(document.querySelectorAll('a[data-toggle="tab"], .nav-tabs a'));
                    const target = '{target}';
                    const found = tabs.find(t => (t.innerText || '').toLowerCase().includes(target));
                    if (found) found.click();
                    return !!found;
                }}
            """)
            await page.wait_for_timeout(800)
            return f"text-match:{target}"
        except Exception:
            return None
    try:
        await el.click()
        await page.wait_for_timeout(800)
        return sel
    except Exception:
        return None


async def navigate(
    page_path: str,
    filters: Optional[dict] = None,
    max_rows: int = 50,
    drill: Optional[dict] = None,
    custom_selectors: Optional[dict] = None,
    wait_after_search_ms: int = 4500,
    tab: Optional[str] = None,
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
        "tab_clicked": None,
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
        # 25.41: CDP fail'da headless launch + cookie inject
        browser, ctx, _bmode = await _navigator_browser(pw)

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

        # URL params ile gelmissek (?sezon=&tarihBas= gibi) sayfa zaten filtreyi
        # otomatik calistirdi — modal acma + search click YAPMA. Tabloyu direkt oku.
        has_url_params = "?" in page_path or (filters and any(k.startswith("_url_") for k in filters))
        if has_url_params and not filters:
            # Sadece tablo oku, hicbir aksiyon yapma
            await page.wait_for_timeout(2500)  # Server filter render bekle
            cols, rows_data = await _read_table(page, max_rows)
            result["columns"] = cols
            result["rows"] = rows_data
            result["row_count"] = len(rows_data)
            result["success"] = True
            result["debug"]["mode"] = "url_params_only"
            if not rows_data:
                result["error_code"] = "NO_DATA"
                result["error"] = "URL filtresi uygulandi, tablo bos."
            return result

        # TAB tikla (gerekiyorsa) — sayfa-uzeri tab degisir, MODAL'dan once gerek
        if tab:
            tab_used = await _click_tab(page, tab)
            result["tab_clicked"] = tab_used
            if tab_used:
                await page.wait_for_timeout(800)

        # MODAL ac (gerekiyorsa) — URL params yoksa
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

            # Tarih ve metin alanlari -> text input; cmb* (select) -> dropdown
            is_dropdown = canon in ("class", "teacher", "ders", "school", "branch",
                                     "etut_type", "classroom", "yoklama",
                                     "sinav_turu", "sinav_kategori", "devre",
                                     "odev_tur", "durum", "liste_turu",
                                     "sezon", "currency", "odeme_sekli", "kullanici")
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


# ─── OGRENCI DRILL-DOWN ────────────────────────────────────────────────────
# Eyotek ogrenci profil alt sayfalari (ST_Id encrypted token ile):
# Genel Bilgiler, Etut, Yoklama, Odev, Rehberlik Notu, Sinav, MEB Notu,
# Davranis, Yazili Notlari, Hedef Soru, Boy/Kilo/Beden, vb.
#
# Mimari:
#   1. Student/student ana listesine git
#   2. Ad/Soyad/SozNo ile filtre + ARA
#   3. Ilk satirda ⋯ context-menu btn'una tikla
#   4. Acilan dropdown'da hedef alt sayfa linkine tikla
#   5. Yeni sayfada (ST_Id encrypted URL) tabloyu oku

_OGRENCI_ALT_SAYFA_MAP = {
    # User-facing label → menu link text (Eyotek dropdown'unda gozuken text)
    "etut":            ["Etüt", "Etut"],
    "etutleri":        ["Etüt", "Etut"],
    # Finansal alt sayfalar (admin-only ACL — fermat_core_agent.py icinde)
    "odeme":           ["Ödeme", "Odeme"],
    "taksit":          ["Ödeme", "Odeme"],   # taksit detayi odeme sayfasi icinde
    "borc":            ["Ödeme", "Odeme"],
    "indirim":         ["İndirimler", "Indirimler"],
    "yoklama":         ["Yoklama"],
    "devamsizlik":     ["Yoklama"],
    "odev":            ["Ödev", "Odev"],
    "odevleri":        ["Ödev", "Odev"],
    "rehberlik":       ["Rehberlik Notu", "Rehberlik"],
    "rehberlik_notu":  ["Rehberlik Notu"],
    "sinav":           ["Sınav", "Sinav"],
    "sinav_sonuclari": ["Sınav", "Sinav"],
    "davranis":        ["Davranış", "Davranis"],
    "yazili":          ["Yazılı Notları", "Yazili Notlari"],
    "yazili_notlari":  ["Yazılı Notları", "Yazili Notlari"],
    "yazili_konulari": ["Yazılı Konuları", "Yazili Konulari"],
    "meb_notlari":     ["MEB Yazılı Notları", "MEB Yazili Notlari"],
    "hedef_soru":      ["Hedef Soru"],
    "boy_kilo":        ["Boy & Kilo & Beden", "Boy"],
    "ders_programi":   ["Ders Programı", "Ders Programi"],
    "genel":           ["Genel Bilgiler"],
    "ozel":            ["Özel Bilgiler", "Ozel Bilgiler"],
    "ekstra_sinif":    ["Ekstra Sınıf", "Ekstra Sinif"],
    "kitaplar":        ["Kitaplar"],
    "etkinlik":        ["Etkinlik"],
}


async def sinav_drilldown(
    sinav_adi: str,
    max_rows: int = 100,
    date_from_days: int = 30,
) -> dict:
    """Sınav adına göre Eyotek'ten sınav sonuç tablosunu çek (drill-down).

    Akış (25.43-DRILL-V2 — Neo bug 11 May): Eyotek test-transferred listesinde aynı
    sınav her DEVRE için ayrı satır olarak listeleniyor (12.Snf, Mezun, 11.Snf...).
    Her satırın ⋯ → Dinamik Liste'si SADECE o devrenin öğrencilerini gösteriyor
    (URL'de encrypted Devre param). Eski kod ilk satıra tıkladığı için ~46 öğrenci
    (Mezun + diğer devreler) atlanıyordu.

    YENI Akış:
      1. Student/test-transferred sayfasına git + tarih filtre
      2. Sınav adına LIKE eşleşen TÜM satırları bul (her devre = ayrı satır)
      3. Her satıra sırayla ⋯ → Dinamik Liste aç
         3a. Dynamic-list'te cmbDevre + cmbSinif dropdown'larını BOŞALT ('Tümü')
         3b. cmbHazirListe seç (TYT/AYT/LGS Net-Puan)
         3c. ARA → tabloyu oku
      4. Tüm devre satırlarının sonuçlarını BİRLEŞTİR (soz_no UNIQUE)
      5. Birleşik sonucu döndür

    Args:
        sinav_adi: "Apotemi" veya "Apotemi TG TYT-3" (LIKE eşleşme)
        max_rows: max öğrenci satırı
        date_from_days: filtre — son kaç gün

    Returns: {success, sinav_found, page_url, columns, rows, row_count, devre_count, error}
    """
    result = {
        "success": False, "sinav_found": None, "page_url": None,
        "columns": [], "rows": [], "row_count": 0,
        "devre_count": 0, "devre_breakdown": [],
        "error_code": None, "error": None,
    }

    page = None
    try:
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        browser, ctx, _bmode = await _navigator_browser(pw)
        page = await ctx.new_page()

        # 1. Sınav listesi sayfasına git
        await page.goto(f"{_BASE_URL}Student/test-transferred",
                        timeout=20000, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        if await _is_login(page):
            result["error_code"] = "AUTH_EXPIRED"
            result["error"] = "Eyotek session expired."
            return result

        # 2. Modal aç + tarih filtresi
        await _open_search_modal(page)
        await page.wait_for_timeout(1200)

        from_d = (date.today() - timedelta(days=date_from_days)).strftime("%d.%m.%Y")
        to_d = date.today().strftime("%d.%m.%Y")
        await _fill_text_input(page, ["#txtKayitBas"], from_d)
        await _fill_text_input(page, ["#txtKayitBit"], to_d)

        # 3. ARA
        await _click_search(page)
        await page.wait_for_timeout(3500)

        # 4. (V2) Sınav adı LIKE eşleşen TÜM satırları bul (her devre ayrı satır)
        # Eyotek listesi: aynı sınav 12.Snf, Mezun, 11.Snf devreleri için ayrı satır.
        # Eski kod ilk satıra tıkladığı için diğer devreler atlanıyordu.
        all_matches = await page.evaluate(
            """(adi) => {
                // 25.43-DRILL-V2-FIX2 (Neo bug 11 May): Türkçe İ → toLowerCase →
                // 'i + combining dot above (U+0307)' birleşik karakter olusuyordu.
                // 'apotemi'.includes('apotemİ_lower') match etmiyordu.
                // FIX: NFD normalize → diakritik (combining) silme → toLowerCase
                // Bu hem 'İ' hem 'Ç' hem 'Ş' hem 'Ğ' hem 'Ü' hem 'Ö' düzgün ascii'ye çevirir.
                const _norm = (s) => (s||'')
                    .normalize('NFD')
                    .replace(/[\\u0300-\\u036f]/g, '')  // tum combining diakritikleri sil
                    .toLowerCase()
                    .replace(/ı/g, 'i');  // ı (NFD'de ayrılmaz) — manuel
                const rows = document.querySelectorAll('table tbody tr');
                if (!rows.length) return {error: 'no_rows', matches: []};
                const al = _norm(adi);
                const matches = [];
                for (let i = 0; i < rows.length; i++) {
                    const cells = Array.from(rows[i].cells).map(c => (c.innerText||'').trim());
                    if (cells.length < 6) continue;  // header / boş
                    const fullText = _norm(cells.join(' | '));
                    if (fullText.includes(al)) {
                        // Devre kolonu (typically index 7: Şube|Tarih|Kod|Tür|Kategori|Adı|Devre|...)
                        const devre = cells[7] || '?';
                        const sinav_kodu = cells[3] || '';
                        matches.push({
                            row_index: i,
                            sinav: cells.slice(0, 8),
                            devre: devre,
                            sinav_kodu: sinav_kodu,
                        });
                    }
                }
                return {matches: matches};
            }""",
            sinav_adi
        )

        matches = all_matches.get("matches", [])
        if not matches:
            result["error_code"] = "SINAV_NOT_FOUND"
            result["error"] = f"Sinav '{sinav_adi}' listede bulunamadi"
            return result

        # İlk satırın meta bilgisini sınav header olarak ata
        result["sinav_found"] = matches[0].get("sinav", [])
        result["devre_count"] = len(matches)

        logger.info(f"[NAV] sinav_drilldown: {sinav_adi} → {len(matches)} devre satırı")
        for m in matches:
            logger.info(f"  · Devre={m['devre']} kod={m['sinav_kodu']} row_idx={m['row_index']}")

        # 5. Her devre satırı için ayrı drill-down → sonuçları birleştir
        adi_lo = (sinav_adi or "").lower()
        if "ayt" in adi_lo or "yks" in adi_lo:
            tip_kw = "ayt net"
        elif "lgs" in adi_lo:
            tip_kw = "lgs"
        else:
            tip_kw = "tyt net"

        all_rows = []
        all_columns = []
        seen_soz_no = set()  # dedupe across devre satırları

        for idx, match in enumerate(matches):
            row_idx = match["row_index"]
            devre = match["devre"]

            # 5.1. Bu satırın ⋯ butonuna tıkla
            click_res = await page.evaluate(
                """(rowIdx) => {
                    const rows = document.querySelectorAll('table tbody tr');
                    if (rowIdx >= rows.length) return {error: 'row_index_out_of_range'};
                    const tr = rows[rowIdx];
                    const btns = tr.querySelectorAll('a, button');
                    for (const b of btns) {
                        const cls = (b.className||'').toLowerCase();
                        if (cls.includes('cust') || cls.includes('dropdown-toggle')) {
                            b.click();
                            return {clicked: true};
                        }
                    }
                    return {error: 'no_dropdown_btn'};
                }""",
                row_idx
            )

            if click_res.get("error"):
                logger.warning(f"  [NAV] devre={devre} ⋯ click fail: {click_res}")
                continue
            await page.wait_for_timeout(1500)

            # 5.2. "Dinamik Liste" tıkla
            dl_clicked = await page.evaluate(
                """() => {
                    const links = Array.from(document.querySelectorAll('a, button, .dropdown-menu li, .dropdown-menu a'));
                    const visible = links.filter(el => { const r = el.getBoundingClientRect(); return r.width>0 && r.height>0; });
                    for (const el of visible) {
                        const t = (el.innerText||'').trim().toLowerCase();
                        if (t === 'dinamik liste' || t.includes('dinamik liste')) {
                            el.click();
                            return {clicked: true};
                        }
                    }
                    return {error: 'no_dinamik_liste_link'};
                }"""
            )
            if dl_clicked.get("error"):
                logger.warning(f"  [NAV] devre={devre} Dinamik Liste link fail")
                continue

            # 5.3. Dynamic-list sayfasını bekle
            await page.wait_for_timeout(4500)
            if not result["page_url"]:
                result["page_url"] = page.url

            # 5.4. cmbHazirListe seç (TYT/AYT/LGS Net-Puan)
            await page.evaluate(
                """(kw) => {
                    if (!window.$ || !$('#cmbHazirListe').length) return false;
                    const opt = $('#cmbHazirListe option').filter(function(){
                        const t = $(this).text().toLowerCase();
                        return t.includes(kw) || t.includes('net-puan');
                    }).first().val();
                    if (opt) { $('#cmbHazirListe').val(opt).trigger('change'); return true; }
                    return false;
                }""",
                tip_kw
            )
            await page.wait_for_timeout(1500)

            # 5.5. (V2 KRITIK) cmbSinif boşalt — tüm sınıflar (sınıf default kalmasın)
            # cmbDevre URL'den gelmiş, dropdown'da o devre seçili — bu DOĞRU çünkü her
            # devre satırı için ayrı drill yapıyoruz. cmbSinif ise '' olmalı.
            await page.evaluate(
                """() => {
                    if (window.$ && $('#cmbSinif').length) {
                        $('#cmbSinif').val('').trigger('change');
                    }
                }"""
            )
            await page.wait_for_timeout(800)

            # 5.6. ARA (btnControl)
            try:
                await page.click("#btnControl", timeout=4000)
            except Exception:
                try:
                    await page.click("input[type=submit][value*='ARA']", timeout=2000)
                except Exception:
                    pass
            await page.wait_for_timeout(6000)

            # 5.7. Tabloyu oku
            cols, rows_data = await _read_table(page, max_rows)
            if cols and not all_columns:
                all_columns = cols

            devre_added = 0
            for r in rows_data:
                # Dedupe by soz_no
                soz_no = None
                if isinstance(r, dict):
                    soz_no = (r.get("soz_no") or r.get("Söz No") or
                              r.get("sözno") or r.get("SözNo"))
                if soz_no:
                    soz_str = str(soz_no).strip()
                    if soz_str in seen_soz_no:
                        continue
                    seen_soz_no.add(soz_str)
                # devre tag'i ekle (debug + analiz için)
                if isinstance(r, dict):
                    r.setdefault("_devre", devre)
                all_rows.append(r)
                devre_added += 1

            result["devre_breakdown"].append({
                "devre": devre, "rows": devre_added, "total_in_table": len(rows_data),
            })
            logger.info(f"  [NAV] devre={devre} → {devre_added} kayit (tabloda {len(rows_data)})")

            # 5.8. max_rows ulaşıldıysa erken çıkış
            if len(all_rows) >= max_rows:
                logger.info(f"  [NAV] max_rows={max_rows} ulasildi, devre dongusu durdu")
                break

            # 5.9. Bir sonraki devre için listeye geri dön
            # (son devre değilse — gereksiz back navigation önlemi)
            if idx < len(matches) - 1:
                try:
                    await page.go_back(wait_until="domcontentloaded", timeout=10000)
                    await page.wait_for_timeout(2500)
                    # Modal yine aç + tarih filtresi (state kaybı olabilir)
                    await _open_search_modal(page)
                    await page.wait_for_timeout(1000)
                    await _fill_text_input(page, ["#txtKayitBas"], from_d)
                    await _fill_text_input(page, ["#txtKayitBit"], to_d)
                    await _click_search(page)
                    await page.wait_for_timeout(3500)
                except Exception as _be:
                    logger.warning(f"  [NAV] back nav fail: {_be}")
                    break

        # 6. Sonuç birleştirme
        result["columns"] = all_columns
        result["rows"] = all_rows[:max_rows]
        result["row_count"] = len(result["rows"])
        result["success"] = True

        # 25.43-DRILL-V3 (Neo direktif): Self-aware completeness — Eyotek
        # 'Şube Katılım' rakamı ile actual rows karşılaştır. Bot kullanıcıya açık
        # belirtsin: "60 katılımcı vardı, 30 verisi geldi" gibi.
        try:
            from field_reconciler import check_data_completeness
            completeness = check_data_completeness(
                sinav_found=result.get("sinav_found") or [],
                actual_rows=result["row_count"],
                devre_count=result.get("devre_count") or 1,
            )
            result["data_completeness"] = completeness
            if completeness.get("warning"):
                logger.warning(f"[NAV] data_completeness: {completeness['warning']}")
        except Exception as _ce:
            logger.debug(f"[NAV] completeness check skip: {_ce}")

        if not all_rows:
            result["error_code"] = "NO_DATA"
            result["error"] = "Hicbir devre satirinda ogrenci verisi yok."

        return result

    except Exception as e:
        result["error_code"] = "EXCEPTION"
        result["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        logger.exception("[NAV] sinav_drilldown exception")
        return result
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


async def student_drilldown(
    student_identifier: str,
    sub_page: str,
    max_rows: int = 50,
    search_field: str = "auto",  # "auto" | "ad" | "soyad" | "soz_no"
) -> dict:
    """Bir ogrencinin profil alt sayfasina drill-down (Eyotek context menu uzeri).

    Args:
        student_identifier: "Mahmut Taha" (ad/soyad), "182" (soz_no), "AKKAYA" (soyad)
        sub_page: "etut" | "yoklama" | "rehberlik" | "sinav" | "davranis" | "yazili" | ...
        max_rows: max satir
        search_field: hangi alanda ara (auto: numerikse soz_no, harfliyse ad+soyad)

    Returns: {success, student_found, profile_url, columns, rows, error}
    """
    result = {
        "success": False, "student_found": None, "profile_url": None,
        "columns": [], "rows": [], "row_count": 0,
        "sub_page": sub_page, "error_code": None, "error": None,
    }

    canon = sub_page.lower().strip().replace(" ", "_").replace("ş", "s").replace("ı", "i")
    candidates_text = _OGRENCI_ALT_SAYFA_MAP.get(canon)
    if not candidates_text:
        # Fallback: kullanicinin verdigi metin direkt menude eslesir mi?
        candidates_text = [sub_page]

    try:
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        # 25.41: CDP fail'da headless launch + cookie inject
        browser, ctx, _bmode = await _navigator_browser(pw)
        page = await ctx.new_page()

        # 1. Student listesine git
        await page.goto(f"{_BASE_URL}Student/student", timeout=20000, wait_until="domcontentloaded")
        await page.wait_for_timeout(2500)

        if await _is_login(page):
            result["error_code"] = "AUTH_EXPIRED"
            result["error"] = "Eyotek session expired."
            return result

        # 2. STRATEGY (Oturum 25.29 fix): Modal ACMA — sayfa ustundeki txtAdQuick
        # direkt kullan + Enter. Modal default state'inde checkbox'lar
        # (chkSilinen, chkSilinmeyen, ...) HEPSI checked=false oluyor → Eyotek
        # filtresiyle "hicbir ogrenciyi gosterme" anlamiyor → her aramada
        # "Kayıt bulunamadı" donduruyor.
        #
        # Test sonucu (28 Nisan): Sayfa ustundeki txtAdQuick + Enter ile
        # 'Çağan' arama sorunsuz ÇAĞAN YAKAY satirini donduruyordu (sezon
        # 2025.26 / sube Kurs default'lariyla).
        s = student_identifier.strip()

        # Numerik input ise (soz_no), DB'den ismi cek + onunla ara
        # Eyotek txtAdQuick "Adı Soyadı / TC Kimlik" ile esler, soz_no ile DEGIL.
        # Direkt "244" arandiginda baska ogrencinin TC'sine takilabilir.
        if s.isdigit():
            try:
                from db_pool import db_fetchrow
                row = await db_fetchrow(
                    "SELECT full_name FROM students WHERE soz_no::text=$1 LIMIT 1", s
                )
                if row and row.get("full_name"):
                    s = row["full_name"].strip()
                    logger.info(f"[NAV] soz_no resolved to name: {s}")
            except Exception:
                pass

        # Hemen sayfa ustundeki txtAdQuick'i doldur — modal acmaya gerek yok
        quick_filled = await page.evaluate(
            """(value) => {
                const el = document.querySelector('input[placeholder*="Adı Soyadı"]') ||
                           document.querySelector('#txtAdQuick') ||
                           document.querySelector('input[id*="AdQuick" i]');
                if (!el) return {ok: false, err: 'no_quick_input'};
                el.value = value;
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
                return {ok: true, id: el.id};
            }""",
            s
        )

        if not quick_filled.get("ok"):
            # Fallback: modal yolu (checkbox'lari TRUE set ederek)
            await _open_search_modal(page)
            await page.wait_for_timeout(1500)
            # Default checkbox'lar checked=false → bunlari aktive et
            await page.evaluate("""() => {
                ['chkSilinmeyen','cbEgitimDestek'].forEach(id => {
                    const el = document.getElementById(id);
                    if (el && !el.checked) {
                        el.checked = true;
                        el.dispatchEvent(new Event('change', {bubbles: true}));
                    }
                });
            }""")
            await _fill_dropdown(page, ["#cmbSubeler"], "Kurs")
            await page.wait_for_timeout(400)
            if s.isdigit():
                await _fill_text_input(page, ["#txtSozNo", "input[id*='SozNo' i]"], s)
            else:
                quick_used = await _fill_text_input(
                    page, ["#txtAdQuick", "input[id*='AdQuick' i]"], s
                )
                if not quick_used:
                    parts = s.split()
                    if len(parts) == 1:
                        await _fill_text_input(page, ["#txtSoyad"], s)
                    else:
                        await _fill_text_input(page, ["#txtAd"], " ".join(parts[:-1]))
                        await _fill_text_input(page, ["#txtSoyad"], parts[-1])
            await _click_search(page)
            await page.wait_for_timeout(4000)
        else:
            # Top-bar yolu: Enter tusu basarak arama tetikle
            try:
                await page.keyboard.press("Enter")
            except Exception:
                pass
            await page.wait_for_timeout(4500)

        # 3. DATA satirini bul + context menu butonuna tikla
        # Eyotek'in tbody'sinde HEADER row da (Sezon/Sube/...) bulunabiliyor.
        # Skip kurali: cells sadece header kelimeleri iceriyorsa veya 'th'lerden
        # olusuyorsa atla. Data row arıyoruz.
        clicked_menu = await page.evaluate("""
            () => {
                const HEADER_KEYWORDS = ['sezon','şube','kayıt tarihi','söz no','okul no','adı','soyadı','program'];
                const rows = Array.from(document.querySelectorAll('table tbody tr'));
                if (!rows.length) return {error: 'no_student'};
                // Helper: row data row mu?
                const isHeaderRow = (tr) => {
                    if (tr.querySelector('th')) return true;  // tr icinde th varsa header
                    const cells = Array.from(tr.cells).map(c => (c.innerText||'').trim().toLowerCase());
                    const txt = cells.join(' ');
                    if (cells.includes('kayıt bulunamadı!')) return false;  // bu special, no_match
                    // Kac kelime header keyword? 3+ varsa header'dir
                    let hits = 0;
                    for (const k of HEADER_KEYWORDS) if (txt.includes(k)) hits++;
                    return hits >= 3;
                };
                let dataRow = null;
                for (const tr of rows) {
                    const cells = Array.from(tr.cells).map(c => (c.innerText||'').trim());
                    if (cells.includes('Kayıt bulunamadı!')) return {error: 'no_match'};
                    if (!isHeaderRow(tr)) {
                        dataRow = tr;
                        break;
                    }
                }
                if (!dataRow) return {error: 'no_data_row', total_rows: rows.length};
                const cells = Array.from(dataRow.cells).map(c => (c.innerText||'').trim());
                const btns = dataRow.querySelectorAll('a, button');
                for (const b of btns) {
                    const cls = b.className || '';
                    const text = (b.innerText||'').trim();
                    if (cls.includes('cust') || cls.includes('dropdown-toggle') || text === '⋯' || text === '...') {
                        b.click();
                        return {clicked: true, cells_preview: cells.slice(0, 10)};
                    }
                }
                if (btns.length) {
                    btns[0].click();
                    return {clicked: 'first', cells_preview: cells.slice(0, 10)};
                }
                return {error: 'no_button', cells_preview: cells.slice(0, 10)};
            }
        """)

        if clicked_menu.get("error"):
            result["error_code"] = "STUDENT_NOT_FOUND"
            result["error"] = f"Ogrenci bulunamadi: {clicked_menu['error']}"
            return result

        result["student_found"] = clicked_menu.get("cells_preview", [])
        await page.wait_for_timeout(1200)

        # 4. Acilan dropdown'da hedef link'i bul ve tikla
        link_candidates_js = json.dumps(candidates_text)
        clicked_link = await page.evaluate(f"""
            (candidates) => {{
                // Tum visible link/button'lara bak (dropdown menu olarak acilanlar)
                const all = Array.from(document.querySelectorAll('a, button, .dropdown-menu a, .dropdown-menu li'));
                const visible = all.filter(el => {{
                    const r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0;
                }});
                for (const cand of candidates) {{
                    const lower = cand.toLowerCase();
                    for (const el of visible) {{
                        const t = (el.innerText || '').trim().toLowerCase();
                        if (t === lower || t.includes(lower)) {{
                            // Bu element'i tikla
                            const href = el.getAttribute('href') || '';
                            el.click();
                            return {{clicked: true, text: el.innerText.trim().slice(0,50), href}};
                        }}
                    }}
                }}
                return {{error: 'no_link', candidates_tried: candidates}};
            }}
        """, candidates_text)

        if clicked_link.get("error"):
            result["error_code"] = "SUBPAGE_LINK_NOT_FOUND"
            result["error"] = f"Alt sayfa link bulunamadi: {candidates_text}"
            return result

        # 5. Yeni sayfayi bekle + tabloyu oku
        await page.wait_for_timeout(3500)
        result["profile_url"] = page.url

        cols, rows_data = await _read_table(page, max_rows)
        result["columns"] = cols
        result["rows"] = rows_data
        result["row_count"] = len(rows_data)
        result["success"] = True
        if not rows_data:
            result["error_code"] = "NO_DATA"
            result["error"] = "Alt sayfa acildi ama tablo bos."
        return result

    except Exception as e:
        result["error_code"] = "EXCEPTION"
        result["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        logger.exception("[NAV] student_drilldown exception")
        return result
    finally:
        try:
            await page.close()
        except Exception:
            pass
        try:
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
