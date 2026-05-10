"""
FermatAI – Eyotek LMS Wrapper
==============================
Projedeki Eyotek etkileşimlerinin tamamını kapsayan Python sınıfı.
API olmadan, Playwright CDP üzerinden gerçek Chrome ile çalışır.

Kullanım:
    from eyotek_wrapper import EyotekWrapper, get_session

    async def main():
        cookies = await get_session()
        async with EyotekWrapper(cookies) as ew:
            # Öğrenci listesi
            students = await ew.get_student_list()

            # Tek öğrenci profili
            profile = await ew.get_student_profile("12345")

            # Yoklama – bugün gelmeyenler
            absent = await ew.get_today_absences()

            # Sınav sonuçları
            results = await ew.get_exam_results()

            # Etüt kaydet
            ok = await ew.write_etut("12345", "2026-04-06", "Matematik", period=1)

Fonksiyon Referansı (projeden):
    get_student_list()               → list[dict]
    get_student_profile(id)          → dict
    get_class_list()                 → list[dict]
    get_exam_results(code?)          → list[dict]
    get_weekly_plan()                → dict
    get_teacher_schedule()           → list[dict]
    get_teacher_attendance()         → list[dict]
    get_today_absences()             → list[dict]
    get_counsellor_notes(student_id) → list[dict]
    get_student_payments(student_id) → list[dict]
    get_homework_list()              → list[dict]
    get_etut_list()                  → list[dict]
    write_etut(student_id, date, subject, period)
    write_counsellor_note(student_id, note, type)
    send_sms(student_ids, message)
"""

import asyncio
import json
import os
import time
import subprocess
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv
from loguru import logger
from playwright.async_api import async_playwright, BrowserContext, Page

# 25.43-OPS-FIX: Explicit parent .env path (eyotek_agent cwd'den parent .env bulamiyor)
_PARENT_ENV = Path(__file__).resolve().parent.parent / ".env"
if _PARENT_ENV.exists():
    load_dotenv(_PARENT_ENV, override=True)
else:
    load_dotenv(override=True)

BASE_URL    = os.getenv("EYOTEK_URL", "https://fermat.eyotek.com/v1")
CDP_PORT    = int(os.getenv("CDP_PORT", "9222"))
CDP_URL     = f"http://127.0.0.1:{CDP_PORT}"
SESSION_FILE = Path(os.getenv("SESSION_FILE", ".eyotek_session.json"))

# ─── Keşfedilen öğrenci bölüm URL haritası (explore v3.2, 06 Nisan 2026) ─────
# Önemli: bu sayfalar "ST_Id" (büyük T) parametresi kullanır.
# Genel Bilgiler sayfası farklı: "St_Id" (küçük t) kullanır.
# Parametre adını kendiniz yapıştırın; _student_section_url() kullanın.
STUDENT_SECTION_PATHS: dict[str, str] = {
    "Genel Bilgiler":       "student-detail",                      # St_Id (farklı)
    "Özel Bilgiler":        "student-detail-specific",             # ST_Id
    "Yoklama":              "student-attendance",                  # ST_Id
    "Etüt":                 "student-individual-lesson",           # ST_Id
    "Rehberlik Notu":       "student-counsellor-note",             # ST_Id
    "Sınıf Rehberliği":     "student-counsellor-class-note",       # ST_Id
    "Sınav":                "student-test",                        # ST_Id
    "Ödev":                 "student-homework",                    # ST_Id
    "Ders Programı":        "student-timetable",                   # ST_Id
    "Ödeme":                "student-financial-operation-collection", # ST_Id
    "Ekstra Sınıf & Kulüp":"student-subclasses-clubs",             # ST_Id
    "MEB Yazılı Notları":   "student-grade-official",              # ST_Id
    "Yazılı Notları":       "student-exam-grades",                 # ST_Id
    "Yazılı Konuları":      "student-written-exam-subjects",       # ST_Id
    "Hedef Soru":           "student-question-assignment",         # ST_Id
    "Davranış":             "student-behaviour",                   # ST_Id
    "Etkinlik":             "student-activity",                    # ST_Id
    "Bülten":               "student-newsletter",                  # ST_Id
    "Başarı Belgesi":       "student-achievement-certificate",     # ST_Id
    "Online Anket":         "student-online-survey",               # ST_Id
    "Rehberlik Anketi":     "student-online-survey-counsellor",    # ST_Id
    "Boy & Kilo & Beden":   "student-height-weight-clothing-size", # ST_Id
    "Uyku":                 "student-sleep",                       # ST_Id
    "Yemek":                "student-food-menu",                   # ST_Id
    "Kitaplar":             "student-library-book-operations",     # ST_Id
    "Revir":                "student-infirmary",                   # ST_Id
    "SMS":                  "student-sms",                         # ST_Id
    "Bildirim":             "student-notification",                # ST_Id
    "Servis":               "student-school-bus",                  # ST_Id
}


# ─── Session yardımcıları ────────────────────────────────────────────────────

def load_session() -> list[dict] | None:
    if SESSION_FILE.exists():
        try:
            data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return data
        except Exception:
            pass
    return None


def save_session(cookies: list[dict]) -> None:
    SESSION_FILE.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")


def cookies_to_header(cookies: list[dict]) -> str:
    return "; ".join(f"{c['name']}={c['value']}" for c in cookies)


async def session_is_valid(cookies: list[dict]) -> bool:
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=10) as client:
            r = await client.get(
                f"{BASE_URL}/Pages/Staff/home",
                headers={"Cookie": cookies_to_header(cookies),
                         "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            return r.status_code == 200
    except Exception:
        return False


async def get_session() -> list[dict] | None:
    """
    Geçerli session cookie'lerini döndür.

    Önce mevcut CDP Chrome'un oturumunu doğrular.
    Geçersizse sayfaya DOKUNMADAN kullanıcıdan manuel giriş ister.
    (Cloudflare Turnstile sorununu önlemek için script login sayfasını açmaz.)
    """
    # CDP üzerinden bağlan ve mevcut oturumu test et
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
        except Exception:
            logger.warning("Chrome CDP'ye bağlanılamadı (port 9222 açık mı?)")
            print("\n" + "=" * 60)
            print("⚠️  Chrome --remote-debugging-port=9222 ile başlatılmalı.")
            print("    Eyotek'e giriş yapıp ENTER'a basın.")
            print("=" * 60)
            input("ENTER → ")
            try:
                browser = await p.chromium.connect_over_cdp(CDP_URL)
            except Exception as e:
                logger.error(f"CDP bağlantısı başarısız: {e}")
                return None

        context = browser.contexts[0]
        page = context.pages[0] if context.pages else await context.new_page()

        # Mevcut oturumu test et
        def is_auth(url: str) -> bool:
            return (
                "fermat.eyotek.com" in url
                and "/Pages/" in url
                and "default.aspx" not in url
            )

        try:
            await page.goto(f"{BASE_URL}/Pages/Staff/home",
                            wait_until="domcontentloaded", timeout=10000)
            await asyncio.sleep(2)
        except Exception:
            await asyncio.sleep(2)

        if is_auth(page.url):
            all_c = await context.cookies()
            cookies = [c for c in all_c if "eyotek.com" in c.get("domain", "")]
            await browser.close()
            if cookies:
                save_session(cookies)
                logger.success(f"✅ Oturum aktif ({len(cookies)} cookie).")
                return cookies

        # Oturum geçersiz — sayfaya dokunmadan bekle
        logger.warning("⚠️  Eyotek oturumu geçersiz.")
        print()
        print("=" * 60)
        print("🔐  MANUEL GİRİŞ GEREKİYOR")
        print()
        print("  1. Chrome'da fermat.eyotek.com/v1 adresini açın")
        print("  2. Giriş yapın, ana sayfa yüklensin")
        print("  3. Buraya dönüp ENTER'a basın")
        print("=" * 60)
        input("ENTER → ")

        try:
            await page.goto(f"{BASE_URL}/Pages/Staff/home",
                            wait_until="domcontentloaded", timeout=10000)
            await asyncio.sleep(2)
        except Exception:
            await asyncio.sleep(2)

        all_c = await context.cookies()
        cookies = [c for c in all_c if "eyotek.com" in c.get("domain", "")]
        await browser.close()

    if cookies:
        save_session(cookies)
        logger.success(f"✅ Giriş başarılı ({len(cookies)} cookie kaydedildi).")
        return cookies
    return None


# ─── Sayfa etkileşim yardımcıları ───────────────────────────────────────────

async def _click_ara(page: Page, timeout: float = 2.0) -> bool:
    """Toolbar ARA butonuna JS ile tıkla."""
    result = await page.evaluate("""
        () => {
            const els = document.querySelectorAll(
                'a, button, input[type=button], input[type=submit]'
            );
            for (const el of els) {
                const txt = (el.innerText || el.value || '').toUpperCase().trim();
                if ((txt === 'ARA' || txt.endsWith('ARA')) &&
                    !txt.includes('İPTAL') && el.offsetParent !== null) {
                    el.click();
                    return true;
                }
            }
            return false;
        }
    """)
    await asyncio.sleep(timeout)
    return bool(result)


async def _click_modal_ara(page: Page) -> bool:
    """
    Eyotek custom ARA popup içindeki ARA butonuna tıkla.
    Eyotek #btnCloseSearchModal'ı içeren custom popup kullanır
    (Bootstrap .modal-content değil).
    """
    result = await page.evaluate("""
        () => {
            // Öncelik 1: Eyotek custom popup — closeBtn'dan container'a yürü
            const closeBtn = document.querySelector(
                '#btnCloseSearchModal, [id*=CloseSearchModal], [id*=btnCloseSearch]');
            if (closeBtn) {
                let el = closeBtn.parentElement;
                while (el && !['BODY', 'HTML'].includes(el.tagName)) {
                    if (el.querySelectorAll('select').length > 0
                        || el.querySelectorAll('input:not([type=hidden])').length > 1
                        || el.offsetHeight > 200) {
                        // Bu container'da ARA butonunu bul
                        for (const btn of el.querySelectorAll(
                            'a, button, input[type=button], input[type=submit]')) {
                            const t = (btn.innerText||btn.value||'').toUpperCase().trim();
                            if (t === 'ARA' || t === 'LİSTELE') {
                                btn.click(); return 'custom_popup';
                            }
                        }
                        break;
                    }
                    el = el.parentElement;
                }
            }
            // Öncelik 2: Bootstrap modal
            for (const sel of ['.modal-content', '.modal-body', '.modal-footer',
                                '[role=dialog]', '.dxpc-mainDiv']) {
                const modal = document.querySelector(sel);
                if (!modal) continue;
                for (const btn of modal.querySelectorAll(
                    'a, button, input[type=button], input[type=submit]')) {
                    const t = (btn.innerText || btn.value || '').toUpperCase().trim();
                    if (t === 'ARA' || t === 'LİSTELE') { btn.click(); return 'bootstrap'; }
                }
            }
            // Fallback: sayfadaki son görünür ARA
            const all = Array.from(document.querySelectorAll(
                'a, button, input[type=button], input[type=submit]'
            )).filter(el => {
                const t = (el.innerText || el.value || '').toUpperCase();
                return t === 'ARA' && el.offsetParent !== null;
            });
            if (all.length > 0) { all[all.length - 1].click(); return 'fallback'; }
            return false;
        }
    """)
    await asyncio.sleep(2)
    return bool(result)


def _build_student_section_url(st_id: str, section: str = "Genel Bilgiler") -> str:
    """
    Keşfedilen URL haritasından öğrenci bölüm URL'i oluşturur.

    Genel Bilgiler sayfası → ?St_Id= (küçük t)
    Diğer tüm bölümler     → ?ST_Id= (büyük T)

    Örnek:
        _build_student_section_url("oFEBL3t2Fetnw0TO57t7yg==", "Rehberlik Notu")
        → "https://…/student-counsellor-note?ST_Id=oFEBL3t2Fetnw0TO57t7yg%3D%3D"
    """
    from urllib.parse import quote
    path = STUDENT_SECTION_PATHS.get(section, "student-detail")
    # Genel Bilgiler → St_Id (küçük t), diğerleri → ST_Id (büyük T)
    param = "St_Id" if section == "Genel Bilgiler" else "ST_Id"
    return f"{BASE_URL}/Pages/Student/{path}?{param}={quote(st_id, safe='')}"


async def _open_ara_and_search(
    page: Page,
    filters: dict | None = None,
    wait_for_grid_ms: int = 15000,
) -> bool:
    """
    ARA modalını aç, opsiyonel filtre doldur, ARA'ya bas, grid'i bekle.
    filters örn: {"txtAd": "Ali", "cmbSezonlar": "2025.26"}
    Dönüş: grid yüklendi mi
    """
    import re as _re
    # Dış ARA → custom popup aç
    outer_ara = await page.evaluate("""
        () => {
            for (const el of document.querySelectorAll(
                'a, button, input[type=button], input[type=submit]')) {
                const t = (el.innerText || el.value || '').toUpperCase().trim();
                if (t === 'ARA' && el.offsetParent !== null) { el.click(); return true; }
            }
            return false;
        }
    """)
    await asyncio.sleep(1.5)

    # Custom popup açıldı mı?
    try:
        await page.wait_for_selector(
            '#btnCloseSearchModal, [id*=CloseSearchModal], .modal-content',
            timeout=6000)
    except Exception:
        pass

    # Filtreleri doldur
    if filters:
        for field_id, value in filters.items():
            # Select2 field → orijinal hidden <select>'i ayarla
            await page.evaluate(f"""
                () => {{
                    const el = document.getElementById('{field_id}');
                    if (!el) return;
                    if (el.tagName === 'SELECT') {{
                        // Seçenek metnine göre eşleştir
                        for (const opt of el.options) {{
                            if (opt.text.includes('{value}') || opt.value === '{value}') {{
                                el.value = opt.value;
                                el.dispatchEvent(new Event('change', {{bubbles: true}}));
                                return;
                            }}
                        }}
                    }} else {{
                        const setter = Object.getOwnPropertyDescriptor(
                            HTMLInputElement.prototype, 'value').set;
                        setter.call(el, '{value}');
                        el.dispatchEvent(new Event('input', {{bubbles: true}}));
                        el.dispatchEvent(new Event('change', {{bubbles: true}}));
                    }}
                }}
            """)

    # Modal içi ARA bas
    await _click_modal_ara(page)
    await asyncio.sleep(1)

    # Grid yüklenene kadar bekle
    loaded = await _wait_for_grid(page, wait_for_grid_ms)

    # Popup hâlâ açıksa ESC ile kapat
    await page.keyboard.press("Escape")
    await asyncio.sleep(0.5)
    return loaded


async def _wait_for_grid(page: Page, timeout: int = 15000) -> bool:
    """DevExpress GridView yüklenene kadar bekle."""
    for sel in ["tr.dxgvDataRow", "tr.dxgvDataRowAlt",
                "tr[class*='dxgvDataRow']", "table tbody tr td"]:
        try:
            await page.wait_for_selector(sel, timeout=timeout)
            return True
        except Exception:
            continue
    return False


def _build_header_map_local(headers: list[str], field_map: dict) -> dict[int, str]:
    """
    Başlık listesinden sütun_indeks → alan_adı haritası.
    eyotek_agent.py bağımsız — circular import önlenir.
    """
    sorted_map = sorted(field_map.items(), key=lambda x: -len(x[0]))
    header_map: dict[int, str] = {}
    for i, h in enumerate(headers):
        h_clean = h.strip().lower()
        if not h_clean or h_clean in ('\xa0', ' ', ''):
            continue
        if h_clean in field_map:
            header_map[i] = field_map[h_clean]
            continue
        for key, field in sorted_map:
            if key in h_clean:
                header_map[i] = field
                break
    return header_map


async def _read_grid_page_local(page: Page, field_map: dict) -> tuple[dict, list[dict]]:
    """Grid sayfasını oku — eyotek_agent bağımsız."""
    headers: list[str] = []
    for loc in [
        "tr.dxgvHeader td", "tr.dxgvHeader th",
        "table th", "table tr:first-child td",
    ]:
        h = await page.locator(loc).all_text_contents()
        if h:
            headers = h
            break

    header_map = _build_header_map_local(headers, field_map) if headers else {}
    records: list[dict] = []

    rows = await page.locator(
        "tr.dxgvDataRow, tr.dxgvDataRowAlt, tr[class*='dxgvDataRow']"
    ).all()
    if not rows:
        rows = await page.locator("table tbody tr").all()

    for row in rows:
        cells = await row.locator("td").all_text_contents()
        cells_c = [c.strip() for c in cells]
        if len([c for c in cells_c if c and c != '\xa0']) < 2:
            continue
        rec = {
            field: cells_c[idx]
            for idx, field in header_map.items()
            if idx < len(cells_c) and cells_c[idx] and cells_c[idx] != '\xa0'
        }
        if rec:
            records.append(rec)

    return header_map, records


async def _read_all_grid_pages(page: Page, field_map: dict) -> list[dict]:
    """
    DevExpress grid'in TÜM sayfalarını oku.
    field_map: { "türkçe başlık" → "db_field" }
    circular import YOK — eyotek_agent bağımsız.
    """
    all_records: list[dict] = []

    # Toplam sayfa sayısı
    total = await page.evaluate("""
        () => {
            const pager = Array.from(document.querySelectorAll(
                'td.dxp-num, a.dxp-num, .dxPager a'
            )).filter(el => /^\\d+$/.test(el.innerText.trim()) && el.offsetParent !== null)
             .map(el => parseInt(el.innerText.trim()));
            if (pager.length) return Math.max(...pager);
            const all = Array.from(document.querySelectorAll('a, span, td'))
                .filter(el => /^\\d{1,2}$/.test(el.innerText.trim()) && el.offsetParent !== null)
                .map(el => parseInt(el.innerText.trim()))
                .filter(n => n <= 50);
            return all.length > 0 ? Math.max(...all) : 1;
        }
    """)

    _, records = await _read_grid_page_local(page, field_map)
    all_records.extend(records)
    logger.info(f"  Sayfa 1: {len(records)} kayıt  (toplam ~{total} sayfa)")

    for pg in range(2, min(total + 1, 201)):
        clicked = await page.evaluate(f"""
            () => {{
                const target = '{pg}';
                for (const el of document.querySelectorAll('a.dxp-num, td.dxp-num, .dxPager a')) {{
                    if (el.innerText.trim() === target && el.offsetParent !== null) {{
                        el.click(); return 'dxpager';
                    }}
                }}
                for (const el of document.querySelectorAll('a, td, span')) {{
                    if (el.innerText.trim() === target && el.offsetParent !== null) {{
                        el.click(); return 'generic';
                    }}
                }}
                return null;
            }}
        """)
        if not clicked:
            break
        await asyncio.sleep(2)
        try:
            await page.wait_for_selector("table tbody tr td", timeout=10000)
        except Exception:
            pass
        _, records = await _read_grid_page_local(page, field_map)
        all_records.extend(records)
        logger.info(f"  Sayfa {pg}: {len(records)} kayıt")
        if not records:
            break

    return all_records


async def _set_field(page: Page, field_id_or_name: str, value: str) -> bool:
    """Bir input/select alanına değer set et (JS ile)."""
    result = await page.evaluate(f"""
        () => {{
            const el = document.getElementById('{field_id_or_name}')
                    || document.querySelector('[name="{field_id_or_name}"]')
                    || document.querySelector('[id*="{field_id_or_name}"]');
            if (!el) return false;
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value').set;
            nativeInputValueSetter.call(el, '{value}');
            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            return true;
        }}
    """)
    return bool(result)


async def _click_button_by_text(page: Page, text: str) -> bool:
    """Metne göre butona tıkla."""
    result = await page.evaluate(f"""
        () => {{
            const els = document.querySelectorAll(
                'a, button, input[type=button], input[type=submit]'
            );
            for (const el of els) {{
                const t = (el.innerText || el.value || '').trim().toUpperCase();
                if (t === '{text.upper()}' && el.offsetParent !== null) {{
                    el.click();
                    return true;
                }}
            }}
            return false;
        }}
    """)
    return bool(result)


# ─── Ana Wrapper Sınıfı ──────────────────────────────────────────────────────

class EyotekWrapper:
    """
    Eyotek LMS için yüksek seviyeli Python API.
    Playwright CDP ile Chrome üzerinden çalışır.
    """

    def __init__(self, cookies: list[dict]):
        self.cookies = cookies
        self._pw = None
        self._browser = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def __aenter__(self) -> "EyotekWrapper":
        """CDP onceligi: laptop'ta CDP acilmissa onu kullan. Aksi halde
        (Oturum 25.4 VPS) headless Chromium'u cookie'lerle launch et."""
        self._pw = await async_playwright().start()
        self._cdp_mode = False  # headless vs cdp ayrimini disaridan gorebilelim

        # 1) CDP dene (laptop)
        try:
            self._browser = await self._pw.chromium.connect_over_cdp(CDP_URL)
            self._context = self._browser.contexts[0]
            self._cdp_mode = True
            logger.info("[EYOTEK] CDP baglantisi aktif (laptop modu)")
        except Exception:
            # 2) Headless fallback (VPS) — cookie'lerle yeni context
            if not self.cookies:
                logger.error("[EYOTEK] CDP yok + cookie yok — laptop'tan login gerek (BASLAT_EYOTEK.bat)")
                raise RuntimeError("Eyotek oturumu yok. Laptop'tan BASLAT_EYOTEK.bat ile login.")
            logger.info("[EYOTEK] CDP yok, headless Chromium ile cookie mode")
            self._browser = await self._pw.chromium.launch(headless=True)
            self._context = await self._browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                viewport={"width": 1366, "height": 768},
                locale="tr-TR",
            )

        await self._context.add_cookies(self.cookies)
        self._page = await self._context.new_page()
        return self

    async def __aexit__(self, *args):
        # Sayfayi kapat
        if self._page:
            try:
                await self._page.close()
            except Exception:
                pass
        # Oturum 25.4: Headless modda browser'i da kapat (kaynak sizintisi olmasin).
        # CDP modunda Chrome'a dokunma (kullanici tab'lari korunsun).
        if not getattr(self, "_cdp_mode", False) and self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._pw:
            await self._pw.stop()

    # ── Navigasyon ──────────────────────────────────────────────────────────

    async def _goto(self, path: str, wait: float = 2.0) -> None:
        url = f"{BASE_URL}/{path}" if not path.startswith("http") else path
        await self._page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(wait)
        # Session suresi dolmus mu? Login sayfasina dusmus mu?
        current_url = self._page.url
        if current_url.rstrip("/").endswith("/v1") or "login" in current_url.lower():
            has_login = await self._page.evaluate(
                "() => !!document.getElementById('btnLogin')"
            )
            if has_login:
                logger.warning("Session suresi dolmus — login sayfasina dusuldu")
                # Chrome'dan taze cookie al
                await self._refresh_session_from_chrome()
                # Tekrar dene
                await self._page.goto(url, wait_until="domcontentloaded")
                await asyncio.sleep(wait)

    async def _refresh_session_from_chrome(self) -> None:
        """Chrome'daki diger tab'lardan taze Eyotek cookie'lerini al."""
        logger.info("  Chrome'dan taze session aliniyor...")
        cookies = await self._context.cookies()
        eyotek_cookies = [c for c in cookies if "eyotek" in c.get("domain", "")]
        if eyotek_cookies:
            await self._context.add_cookies(eyotek_cookies)
            # Session dosyasini guncelle
            import json as _json
            session_path = os.getenv("SESSION_FILE", ".eyotek_session.json")
            with open(session_path, "w", encoding="utf-8") as f:
                _json.dump(eyotek_cookies, f, indent=2)
            logger.info(f"  Session guncellendi: {len(eyotek_cookies)} cookie")

    async def _ara_flow(self) -> bool:
        """Toolbar ARA → Modal ARA akışı."""
        await _click_ara(self._page, timeout=1.0)
        await asyncio.sleep(0.5)
        await _click_modal_ara(self._page)
        return await _wait_for_grid(self._page)

    # ════════════════════════════════════════════════════════════════════════
    # READ OPERASYONLARI
    # ════════════════════════════════════════════════════════════════════════

    # ── Öğrenci Listesi ─────────────────────────────────────────────────────
    async def get_student_list(
        self,
        sezon: str = "",
        sube: str = "",
        class_name: str = "",
    ) -> list[dict]:
        """
        Tüm öğrencileri çek (filtre opsiyonel).
        Döndürür: eyotek_id, soz_no, full_name, first_name, last_name, sezon, sube, class_name, status
        """
        logger.info("📋 get_student_list() çağrıldı")
        await self._goto("Pages/Student/student")

        # Gerçek Eyotek ARA modal field ID'leri (profile_map.json'dan):
        #   cmbSezonlar → Sezon (Select2)
        #   cmbSubeler  → Şube (Select2)
        #   txtAd       → Adı
        #   txtSoyad    → Soyadı
        #   txtOgNo     → Söz No
        #   txtOkulNo   → Okul No
        #   txtTcKimlik → TC Kimlik No
        filters = {}
        if sezon:
            filters["cmbSezonlar"] = sezon
        if sube:
            filters["cmbSubeler"] = sube
        # class_name için cmbExtraClasses veya txtAd — şimdilik filtre yok
        await _open_ara_and_search(self._page, filters if filters else None)

        field_map = {
            "söz no": "soz_no", "okul no": "eyotek_id", "öğrenci no": "eyotek_id",
            "kayıt tarihi": "kayit_tarihi", "soyadı": "last_name",
            "adı soyadı": "full_name", "adı": "first_name",
            "sezon": "sezon", "şube": "sube", "sınıfı": "class_name",
            "sınıf": "class_name", "durum": "status", "kur": "kur",
            "program": "program", "devre": "devre",
        }
        records = await _read_all_grid_pages(self._page, field_map)

        # full_name türet
        for r in records:
            if "full_name" not in r:
                r["full_name"] = f"{r.get('first_name','')} {r.get('last_name','')}".strip()
            if "eyotek_id" not in r and "soz_no" in r:
                r["eyotek_id"] = r["soz_no"]

        logger.success(f"  → {len(records)} öğrenci")
        return records

    # ── Öğrenci Profili ─────────────────────────────────────────────────────
    async def get_student_profile(self, eyotek_id: str) -> dict:
        """
        Belirli bir öğrencinin tam profil detayını döndür.

        Keşfedilen gerçek Eyotek davranışı (profile_map.json v3.1):
          1. Pages/Student/student → ARA → custom popup (#btnCloseSearchModal)
          2. Söz No / Okul No filtresini doldur → modal içi ARA → grid
          3. Satırdaki .custom-row-menu-button tıkla (metin boş, ikon)
          4. Açılan popup: TÜM bağlantılar javascript:__doPostBack(...)
             Örn: GridView1$ctl02$btnGenel, GridView1$ctl02$btnYoklama…
          5. __doPostBack('GridView1$ctlXX$btnGenel','') → student-detail?St_Id=...
          6. St_Id'yi URL'den çıkar → profil sayfasını oku

        Döner: {eyotek_id, st_id, profile_url, basic_info, postback_map, tabs}
        """
        import re as _re
        logger.info(f"👤 get_student_profile({eyotek_id})")
        await self._goto("Pages/Student/student", wait=3.0)

        # ── ARA modal aç + öğrenciyi filtrele ─────────────────────────────
        # Söz No'ya göre ara (txtOgNo), ya da Okul No (txtOkulNo)
        # (id sayısal formatta, sözleşme numarası olabilir)
        filters = {}
        if eyotek_id and eyotek_id.strip().isdigit():
            filters["txtOgNo"] = eyotek_id.strip()
        elif eyotek_id and eyotek_id.strip():
            # İsim parçası olabilir
            parts = eyotek_id.strip().split()
            if len(parts) >= 2:
                filters["txtAd"] = parts[0]
                filters["txtSoyad"] = parts[-1]
            else:
                filters["txtAd"] = eyotek_id.strip()

        loaded = await _open_ara_and_search(self._page, filters)
        if not loaded:
            logger.warning("  Grid yüklenmedi — filtresiz yeniden deniyor...")
            await _open_ara_and_search(self._page, {})
        await asyncio.sleep(1)

        # ── Öğrenci satırını bul ve custom-row-menu-button tıkla ──────────
        # Önce tüm satırları listele (eşleşme için)
        rows_info = await self._page.evaluate(f"""
            () => {{
                const rows = document.querySelectorAll('table tbody tr');
                const result = [];
                for (const row of rows) {{
                    const cells = Array.from(row.querySelectorAll('td'))
                        .map(td => td.innerText.trim());
                    const nonEmpty = cells.filter(c => c.length > 0);
                    if (nonEmpty.length < 2) continue;
                    const hasId = cells.some(c =>
                        c === '{eyotek_id}' || c.includes('{eyotek_id}'));
                    result.push({{ cells: cells.slice(0, 8), hasId }});
                }}
                return result.slice(0, 10);
            }}
        """)
        logger.info(f"  Satır sayısı: {len(rows_info)}, "
                    f"ID eşleşme: {sum(1 for r in rows_info if r['hasId'])}")

        # Eşleşen satırı tıkla (yoksa ilk satırı)
        clicked = await self._page.evaluate(f"""
            () => {{
                const rows = document.querySelectorAll('table tbody tr');
                let targetRow = null;
                for (const row of rows) {{
                    const cells = Array.from(row.querySelectorAll('td'))
                        .map(td => td.innerText.trim());
                    if (cells.filter(c => c.length > 0).length < 2) continue;
                    const hasId = cells.some(c =>
                        c === '{eyotek_id}' || c.includes('{eyotek_id}'));
                    if (hasId) {{ targetRow = row; break; }}
                    if (!targetRow) targetRow = row;  // ilk satır fallback
                }}
                if (!targetRow) return null;
                const cells = Array.from(targetRow.querySelectorAll('td'))
                    .map(td => td.innerText.trim());
                // custom-row-menu-button (Eyotek'in gerçek sınıfı)
                const btn = targetRow.querySelector('.custom-row-menu-button')
                          || targetRow.querySelector('[class*=custom-row]')
                          || targetRow.querySelector('a.btn')
                          || targetRow.querySelector('button');
                if (btn && btn.offsetParent !== null) {{
                    btn.click();
                    return {{ tag: btn.tagName, cls: btn.className,
                             cells: cells.slice(0, 6) }};
                }}
                return null;
            }}
        """)

        if not clicked:
            logger.warning(f"  custom-row-menu-button bulunamadı: {eyotek_id}")
            return {"eyotek_id": eyotek_id, "error": "button_not_found"}

        logger.info(f"  Tıklanan buton: {clicked['cls'][:60]}")
        logger.info(f"  Satır hücreleri: {clicked['cells'][:5]}")
        await asyncio.sleep(1.5)

        # ── PostBack menü linklerini oku ───────────────────────────────────
        # Popup: [class*=custom-row-menu]:not(.custom-row-menu-button) VEYA
        #        .dropdown-menu ile içerik (student NavLinks değil)
        NAV_EXCLUSIONS = ['mesajlar','ajanda','profil resmi','şifre değiştir',
                          'internal-message','change-password','staff/image']
        menu_raw = await self._page.evaluate("""
            () => {
                // Öncelik 1: custom-row-menu active button'un kardeşi/parent
                const btn = document.querySelector(
                    '.custom-row-menu-button.active, .custom-row-menu-button');
                if (btn) {
                    const sib = btn.nextElementSibling
                              || btn.parentElement?.querySelector(
                                  'ul, [class*=menu]:not(.custom-row-menu-button)');
                    if (sib && sib !== btn) {
                        const links = Array.from(
                            sib.querySelectorAll('a, li[onclick], button'))
                          .map(a => ({ text: (a.innerText||'').trim(),
                                       href: a.href||a.getAttribute('onclick')||'' }))
                          .filter(l => l.text.length > 0);
                        if (links.length > 2) return links;
                    }
                }
                // Öncelik 2: görünür dropdown-menu (student sayfasına özgü)
                for (const m of document.querySelectorAll('.dropdown-menu')) {
                    const links = Array.from(m.querySelectorAll('a'))
                        .filter(a => a.offsetParent !== null);
                    if (links.length > 2) {
                        return links.map(a => ({
                            text: a.innerText.trim(), href: a.href||''
                        })).filter(l => l.text.length > 0);
                    }
                }
                return [];
            }
        """)

        # Nav linklerini filtrele
        menu_links = [
            l for l in menu_raw
            if not any(ex in l["href"].lower() or ex in l["text"].lower()
                       for ex in NAV_EXCLUSIONS)
        ]
        logger.info(f"  Popup linkleri ({len(menu_links)}): "
                    f"{[l['text'] for l in menu_links[:10]]}")

        # PostBack map'i çıkar
        postback_map = {}
        for lnk in menu_links:
            m_pb = _re.search(r"__doPostBack\('([^']+)','([^']*)'\)", lnk["href"])
            if m_pb:
                postback_map[lnk["text"]] = {
                    "target": m_pb.group(1), "arg": m_pb.group(2)
                }

        # ── Genel Bilgiler PostBack → student-detail?St_Id=... ────────────
        st_id = None
        detail_url = None
        genel_pb = postback_map.get("Genel Bilgiler")
        if genel_pb:
            logger.info(f"  PostBack çalıştırılıyor: {genel_pb['target']}")
            await self._page.keyboard.press("Escape")
            await asyncio.sleep(0.3)
            try:
                await self._page.evaluate(
                    f"__doPostBack('{genel_pb['target']}', '{genel_pb['arg']}')")
                await asyncio.sleep(3)
                if "student-detail" in self._page.url:
                    detail_url = self._page.url
                    m3 = _re.search(r"St_Id=([^&\s]+)", detail_url)
                    if m3:
                        st_id = m3.group(1)
                        logger.success(f"  ✅ St_Id: {st_id[:30]}...")
                else:
                    logger.warning(f"  PostBack sonrası URL: {self._page.url}")
                    # Hidden field'dan dene
                    st_id_hid = await self._page.evaluate("""
                        () => {
                            const p = new URLSearchParams(window.location.search);
                            if (p.has('St_Id')) return p.get('St_Id');
                            const h = document.querySelector(
                                '[name*=StId],[id*=StId],[id*=hdnStudent]');
                            return h ? h.value : null;
                        }
                    """)
                    if st_id_hid:
                        st_id = st_id_hid
                        detail_url = self._page.url
            except Exception as e:
                logger.warning(f"  PostBack hatası: {e}")
        else:
            logger.warning("  'Genel Bilgiler' PostBack bulunamadı!")
            logger.warning(f"  Mevcut postback_map: {list(postback_map.keys())[:8]}")

        if not detail_url:
            return {
                "eyotek_id": eyotek_id,
                "error": "no_st_id",
                "clicked_cells": clicked.get("cells"),
                "postback_map": postback_map,
                "menu_links": menu_links[:10],
            }

        profile = {
            "eyotek_id": eyotek_id,
            "st_id": st_id,
            "profile_url": detail_url,
            "postback_map": postback_map,
            "tabs": {},
        }

        # ── student-detail'deyiz — temel bilgileri oku ────────────────────
        basic_info = await self._page.evaluate("""
            () => {
                const result = {};
                document.querySelectorAll('input[type=text], input[type=email],'+
                    'input[readonly]')
                    .forEach(inp => {
                        const lbl = document.querySelector('label[for="'+inp.id+'"]');
                        if (lbl && inp.value) result[lbl.innerText.trim()] = inp.value;
                    });
                document.querySelectorAll(
                    '.control-label, td.label, th, .form-group label')
                    .forEach(lbl => {
                        const sib = lbl.nextElementSibling
                                  || lbl.parentElement?.nextElementSibling;
                        if (sib) {
                            const v = (sib.innerText || sib.value || '').trim();
                            if (v && v.length < 120)
                                result[lbl.innerText.trim()] = v;
                        }
                    });
                return result;
            }
        """)
        profile["basic_info"] = basic_info
        logger.info(f"  Temel bilgiler ({len(basic_info)}): "
                    f"{list(basic_info.keys())[:8]}")

        # Öğrenci bölüm linkleri — St_Id DEĞER'ini taşıyan tüm linkler
        # (Student-detail sayfası: St_Id küçük t; bölüm sayfaları: ST_Id büyük T;
        #  ikisi de aynı değeri taşıdığından değer üzerinden arama yapılır)
        tab_links = await self._page.evaluate("""
            (stId) => {
                const stIdEnc = encodeURIComponent(stId);
                const currentHref = location.href;
                const links = [];
                const seen = new Set([currentHref]);
                document.querySelectorAll('a[href]').forEach(a => {
                    const raw = a.getAttribute('href') || '';
                    const abs = a.href;
                    const text = (a.innerText || '').trim().replace(/\\s+/g,' ');
                    if (!text || seen.has(abs)) return;
                    if (raw.includes(stId) || raw.includes(stIdEnc)) {
                        seen.add(abs);
                        links.push({ text, href: abs });
                    }
                });
                return links;
            }
        """, st_id or "")
        profile["tab_links"] = tab_links
        logger.info(f"  Sekmeler ({len(tab_links)}): "
                    f"{[t['text'] for t in tab_links[:12]]}")

        # Tüm tablolar
        profile["tables"] = await self._page.evaluate("""
            () => Array.from(document.querySelectorAll('table')).map(tbl => ({
                headers: Array.from(tbl.querySelectorAll('th,tr:first-child td'))
                    .map(h => h.innerText.trim()).filter(h => h),
                rows: Array.from(tbl.querySelectorAll('tbody tr')).slice(0, 5)
                    .map(r => Array.from(r.querySelectorAll('td'))
                         .map(td => td.innerText.trim()))
            })).filter(t => t.headers.length > 0 || t.rows.length > 0)
        """)

        # Her sekmeye git ve yapısını al
        for tab in tab_links[:15]:
            try:
                await self._page.goto(tab["href"], wait_until="domcontentloaded")
                await asyncio.sleep(1.5)
                profile["tabs"][tab["text"]] = {
                    "url": self._page.url,
                    "tables": await self._page.evaluate("""
                        () => Array.from(document.querySelectorAll('table'))
                          .map(tbl => ({
                            headers: Array.from(tbl.querySelectorAll('th,tr:first-child td'))
                                .map(h => h.innerText.trim()).filter(h => h),
                            rows: Array.from(tbl.querySelectorAll('tbody tr')).slice(0,5)
                                .map(r => Array.from(r.querySelectorAll('td'))
                                     .map(td => td.innerText.trim()))
                          })).filter(t => t.headers.length > 0)
                    """),
                }
            except Exception as e:
                profile["tabs"][tab["text"]] = {"error": str(e)}

        logger.success(f"  → Profil alındı: st_id={st_id} | "
                       f"{len(profile['tabs'])} sekme")
        return profile

    # ── Sınıf Listesi ───────────────────────────────────────────────────────
    async def get_class_list(self) -> list[dict]:
        """Tüm sınıfları döndür: sınıf adı, devre, öğrenci sayısı, URL."""
        logger.info("🏫 get_class_list()")
        await self._goto("Pages/Student/class-list")

        classes = await self._page.evaluate("""
            () => Array.from(document.querySelectorAll('table tbody tr')).map(row => {
                const cells = Array.from(row.querySelectorAll('td')).map(td => td.innerText.trim());
                const link = row.querySelector('a[href]');
                return {
                    name: cells[0] || '',
                    devre: cells[1] || '',
                    student_count: cells[2] || '',
                    url: link ? link.href : ''
                };
            }).filter(c => c.name)
        """)
        logger.success(f"  → {len(classes)} sınıf")
        return classes

    # ── Yoklama Kontrol (Tum Sezon) ─────────────────────────────────────────
    async def scrape_attendance_control(self, days_back: int = 1) -> list[dict]:
        """
        Yoklama Kontrol sayfası — 'bugün/şimdi' hangi derslerin yoklaması
        alınmış/alınmamış kontrolü.

        Oturum 23 fix (Neo audit): Sayfa TARİH FİLTRESİ YOK — sadece şube/öğretmen/sınıf
        filtreleri. Eski kod StartDate/EndDate selector'larını arıyor → timeout.
        Yeni akış: btnSearch ile filtreleri uygula, grid oku.

        days_back parametresi artık kullanılmıyor — sayfa zaten güncel yoklamaya bakar.
        """
        logger.info(f"📋 scrape_attendance_control(days_back={days_back})")
        await self._goto("Pages/Student/attendance-report")
        await asyncio.sleep(2)

        # ARA — btnSearch modal içi invisible olabilir. dispatch_event visibility
        # check'siz doğrudan onclick handler'ı çağırır (Oturum 23 Neo sync audit fix).
        try:
            has_btn = await self._page.locator('#btnSearch').count() > 0
            if has_btn:
                await self._page.dispatch_event('#btnSearch', 'click')
                await asyncio.sleep(3)
            else:
                # Fallback: btn-circle yellow (modal aç butonu) + modalın içindeki sbmt
                logger.warning("  btnSearch bulunamadi — varsayilan filtre ile grid oku")
        except Exception as e:
            logger.warning(f"  btnSearch dispatch fail: {e}")

        field_map = {
            "gün": "gun", "tarih": "tarih", "sınıf": "sinif", "ders": "ders",
            "öğretmen": "ogretmen", "ders başlangıç": "ders_baslangic",
            "ders bitiş": "ders_bitis", "yoklama": "yoklama",
        }
        try:
            records = await _read_all_grid_pages(self._page, field_map)
            logger.success(f"  → {len(records)} yoklama kaydı")
            return records
        except Exception as e:
            logger.error(f"  Yoklama scrape hatası: {e}")
            raise  # Oturum 23: sessiz 0 kayıt YOK, gerçek hata üstüne iletilir

    # ── Bugün Gelmeyenler ───────────────────────────────────────────────────
    async def get_today_absences(self) -> list[dict]:
        """Bugün gelmeyen öğrencilerin listesi."""
        logger.info("📋 get_today_absences()")
        await self._goto("Pages/Student/attendance-today")
        await self._ara_flow()

        field_map = {
            "söz no": "soz_no", "okul no": "eyotek_id",
            "adı soyadı": "full_name", "adı": "first_name", "soyadı": "last_name",
            "şube": "sube", "tarih": "tarih", "ders": "ders_no",
            "saat": "saat", "gün": "gun", "durum": "durum",
        }
        records = await _read_all_grid_pages(self._page, field_map)
        logger.success(f"  → {len(records)} devamsızlık kaydı")
        return records

    # ── Sınav Sonuçları ─────────────────────────────────────────────────────
    async def get_exam_results(self, sinav_kodu: str = "") -> list[dict]:
        """
        Sınav değerlendirme sonuçları.
        sinav_kodu verilirse sadece o sınavın sonuçları döner.
        """
        logger.info(f"📊 get_exam_results(sinav_kodu={sinav_kodu!r})")
        await self._goto("Pages/Student/Test/test")
        await self._ara_flow()

        field_map = {
            "sezon": "sezon", "şube": "sube", "sınav kodu": "sinav_kodu",
            "sınav adı": "sinav_adi", "sınav türü": "sinav_turu",
            "tarih": "tarih", "devre": "devre", "sınıf": "sinif",
            "net": "net", "puan": "puan", "sıra": "sira",
            "okul sıra": "okul_sira", "doğru": "dogru",
            "yanlış": "yanlis", "boş": "bos",
        }
        records = await _read_all_grid_pages(self._page, field_map)

        if sinav_kodu:
            records = [r for r in records if r.get("sinav_kodu", "") == sinav_kodu]

        logger.success(f"  → {len(records)} sınav kaydı")
        return records

    # ── Sınav Listesi ────────────────────────────────────────────────────────
    async def get_exam_list(self) -> list[dict]:
        """Tüm sınavları döndür: kod, ad, tür, tarih."""
        logger.info("📝 get_exam_list()")
        await self._goto("Pages/Student/test-transferred")
        await self._ara_flow()

        field_map = {
            "şube": "sube", "tarih": "tarih", "sınav kodu": "sinav_kodu",
            "sınav türü": "sinav_turu", "sınav kategori": "sinav_kategori",
            "sınav adı": "sinav_adi", "sezon": "sezon", "devre": "devre",
        }
        records = await _read_all_grid_pages(self._page, field_map)
        logger.success(f"  → {len(records)} sınav")
        return records

    # ── Haftalık Çalışma Planı ───────────────────────────────────────────────
    async def get_weekly_plan(self) -> dict:
        """Personelin haftalık çalışma planını döndür."""
        logger.info("📅 get_weekly_plan()")
        await self._goto("Pages/Staff/weekly-working-plan")
        await asyncio.sleep(1)

        tables = await self._page.evaluate("""
            () => Array.from(document.querySelectorAll('table')).map(tbl => ({
                headers: Array.from(tbl.querySelectorAll('th, tr:first-child td'))
                    .map(h => h.innerText.trim()).filter(h => h),
                rows: Array.from(tbl.querySelectorAll('tbody tr')).map(row =>
                    Array.from(row.querySelectorAll('td')).map(td => td.innerText.trim())
                )
            }))
        """)
        return {"tables": tables}

    # ── Öğretmen Ders Programı ───────────────────────────────────────────────
    async def get_teacher_schedule(self) -> list[dict]:
        """Öğretmenlerin ders programını döndür."""
        logger.info("📆 get_teacher_schedule()")
        await self._goto("Pages/Student/timetable-staff-list")
        await asyncio.sleep(1)

        field_map = {
            "id": "id", "adı soyadı": "full_name",
            "branş": "brans", "saat": "saat",
        }
        records = await _read_all_grid_pages(self._page, field_map)
        logger.success(f"  → {len(records)} öğretmen programı")
        return records

    # ── Personel Devam Takip ─────────────────────────────────────────────────
    async def get_teacher_attendance(self) -> list[dict]:
        """Personel devam takibi."""
        logger.info("✅ get_teacher_attendance()")
        await self._goto("Pages/Staff/working-hours-check-list")
        await asyncio.sleep(2)

        field_map = {
            "id": "ik_no", "adı soyadı": "full_name", "görevi": "gorevi",
            "branş": "brans", "giriş": "giris_saati", "çıkış": "cikis_saati",
            "tarih": "tarih", "durum": "durum",
        }
        records = await _read_all_grid_pages(self._page, field_map)
        logger.success(f"  → {len(records)} devam kaydı")
        return records

    # ── Rehberlik Notları ────────────────────────────────────────────────────
    async def get_student_section_data(
        self, st_id: str, section: str = "Rehberlik Notu"
    ) -> dict:
        """
        Keşfedilen URL haritasını kullanarak öğrenci bölüm sayfasına git
        ve ham sayfa yapısını döndür (tablolar, butonlar, select'ler).

        Örnek:
            data = await ew.get_student_section_data(st_id, "Rehberlik Notu")
            # → {"url": "…", "title": "…", "tables": […], "selects": […], …}
        """
        import re as _re
        url = _build_student_section_url(st_id, section)
        logger.info(f"📄 get_student_section_data({section!r})")
        logger.info(f"   URL: {url.split('?')[0].split('/')[-1]}")
        await self._page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(2.5)
        title = await self._page.title()
        tables = await self._page.evaluate("""
            () => Array.from(document.querySelectorAll('table')).map(tbl => ({
                headers: Array.from(tbl.querySelectorAll('th, tr:first-child td'))
                    .map(h => h.innerText.trim()).filter(Boolean),
                rows: Array.from(tbl.querySelectorAll('tbody tr')).slice(0, 5)
                    .map(r => Array.from(r.querySelectorAll('td'))
                         .map(td => td.innerText.trim()))
            })).filter(t => t.headers.length > 0 || t.rows.length > 0)
        """)
        selects = await self._page.evaluate("""
            () => Array.from(document.querySelectorAll('select, .select2-container'))
                .filter(el => el.offsetParent !== null)
                .map(el => ({
                    id: el.id || '',
                    tag: el.tagName,
                    opts: Array.from(el.querySelectorAll
                         ? el.querySelectorAll('option')
                         : []).slice(0, 10).map(o => o.innerText.trim())
                }))
        """)
        buttons = await self._page.evaluate("""
            () => Array.from(document.querySelectorAll('a, button, input[type=button]'))
                .filter(b => b.offsetParent !== null)
                .map(b => (b.innerText || b.value || '').trim())
                .filter(Boolean)
        """)
        return {
            "url": self._page.url, "title": title,
            "tables": tables, "selects": selects, "buttons": buttons,
        }

    async def get_counsellor_notes(self, student_id: str = "",
                                   st_id: str = "") -> list[dict]:
        """
        Rehberlik notlarını döndür.

        - st_id verilirse: student-counsellor-note?ST_Id=... ile direkt eriş
        - student_id verilirse: counsellor-note-list ARA akışı kullan
        - İkisi de verilmezse: tüm notları listele
        """
        logger.info(f"💬 get_counsellor_notes(student_id={student_id!r})")
        if st_id:
            # Direkt öğrenci bölümü: student-counsellor-note?ST_Id=...
            url = _build_student_section_url(st_id, "Rehberlik Notu")
            await self._page.goto(url, wait_until="domcontentloaded")
            await asyncio.sleep(2.5)
        else:
            await self._goto("Pages/Student/counsellor-note-list")
            await self._ara_flow()

        field_map = {
            "söz no": "soz_no", "okul no": "eyotek_id",
            "adı soyadı": "full_name", "adı": "first_name", "soyadı": "last_name",
            "tarih": "tarih", "konu": "konu", "not": "not_metni",
            "rehber": "rehber", "tür": "tur", "görüşme": "gorusme_turu",
        }
        records = await _read_all_grid_pages(self._page, field_map)
        if student_id:
            records = [r for r in records if r.get("eyotek_id") == student_id
                       or r.get("soz_no") == student_id]
        logger.success(f"  → {len(records)} rehberlik notu")
        return records

    # ── Öğrenci Ödemeleri ────────────────────────────────────────────────────
    async def get_student_payments(self, student_id: str = "") -> list[dict]:
        """
        Geciken ödemeleri ve ödeme detaylarını döndür.
        student_id verilirse sadece o öğrencinin ödemeleri.
        """
        logger.info(f"💰 get_student_payments(student_id={student_id!r})")
        await self._goto("Pages/Financial/overdue-student-payment")
        await self._ara_flow()

        field_map = {
            "söz no": "soz_no", "okul no": "eyotek_id",
            "adı soyadı": "full_name", "adı": "first_name", "soyadı": "last_name",
            "sezon": "sezon", "şube": "sube", "tutar": "tutar",
            "borç": "borc", "ödeme": "odeme", "bakiye": "bakiye",
            "vade": "vade_tarihi", "taksit": "taksit_no",
        }
        records = await _read_all_grid_pages(self._page, field_map)
        if student_id:
            records = [r for r in records if r.get("eyotek_id") == student_id
                       or r.get("soz_no") == student_id]
        logger.success(f"  → {len(records)} ödeme kaydı")
        return records

    # ── Ödev Listesi ────────────────────────────────────────────────────────
    async def get_homework_list(self, class_name: str = "") -> list[dict]:
        """Ödev listesini döndür."""
        logger.info("📚 get_homework_list()")
        await self._goto("Pages/Student/homework-search")
        await self._ara_flow()

        field_map = {
            "sınıf": "sinif", "tarih": "tarih", "ders": "ders",
            "ödev": "odev_adi", "öğretmen": "ogretmen",
            "durum": "durum", "tür": "tur",
        }
        records = await _read_all_grid_pages(self._page, field_map)
        if class_name:
            records = [r for r in records if class_name in r.get("sinif", "")]
        logger.success(f"  → {len(records)} ödev")
        return records

    # ── Etüt Listesi ─────────────────────────────────────────────────────────
    async def get_etut_list(self, student_id: str = "") -> list[dict]:
        """Etüt kayıtlarını döndür."""
        logger.info("📖 get_etut_list()")
        await self._goto("Pages/Student/individual-lesson")
        await self._ara_flow()

        field_map = {
            "söz no": "soz_no", "okul no": "eyotek_id",
            "adı soyadı": "full_name", "tarih": "tarih",
            "ders": "ders", "öğretmen": "ogretmen",
            "sınıf": "sinif", "saat": "saat", "durum": "durum",
        }
        records = await _read_all_grid_pages(self._page, field_map)
        if student_id:
            records = [r for r in records if r.get("eyotek_id") == student_id
                       or r.get("soz_no") == student_id]
        logger.success(f"  → {len(records)} etüt kaydı")
        return records

    # ── Günlük Etüt Listesi (tarih filtreli) ─────────────────────────────
    async def get_daily_etut(self, target_date: str = "") -> list[dict]:
        """
        Belirli bir günün etüt kayıtlarını döndür.
        target_date: DD.MM.YYYY formatında (boşsa bugün)
        ARA modalında tarih filtresi uygular.
        """
        from datetime import date as _d
        if not target_date:
            target_date = _d.today().strftime("%d.%m.%Y")
        logger.info(f"📖 get_daily_etut({target_date})")
        await self._goto("Pages/Student/individual-lesson")

        # ARA modalını aç ve tarih filtresi uygula
        await asyncio.sleep(2)
        # ARA butonuna tıkla
        await self._page.evaluate("""
            () => {
                const btn = document.querySelector('[id*="btnSearch"], [id*="btnAra"]')
                    || Array.from(document.querySelectorAll('a,button'))
                        .find(b => (b.innerText||'').trim() === 'ARA');
                if (btn) btn.click();
            }
        """)
        await asyncio.sleep(2)

        # Tarih alanlarını doldur (başlangıç ve bitiş aynı gün)
        await self._page.evaluate(f"""
            (dateStr) => {{
                const inputs = document.querySelectorAll('input[type=text]');
                for (const inp of inputs) {{
                    if (inp.offsetParent && (inp.id.toLowerCase().includes('tarih')
                        || inp.id.toLowerCase().includes('date')
                        || inp.placeholder?.includes('Tarih'))) {{
                        inp.value = dateStr;
                        inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                    }}
                }}
            }}
        """, target_date)
        await asyncio.sleep(0.5)

        # ARA butonuna tıkla (modal içi)
        await self._page.evaluate("""
            () => {
                const btns = document.querySelectorAll('a,button,input[type=button]');
                for (const b of btns) {
                    const t = (b.innerText || b.value || '').trim();
                    if (t === 'ARA' && b.offsetParent && b.closest('[class*="modal"], [class*="popup"], [role="dialog"]')) {
                        b.click();
                        return true;
                    }
                }
                // Fallback — herhangi bir ARA butonu
                for (const b of btns) {
                    if ((b.innerText||b.value||'').trim() === 'ARA' && b.offsetParent) {
                        b.click();
                        return true;
                    }
                }
                return false;
            }
        """)
        await asyncio.sleep(3)

        field_map = {
            "söz no": "soz_no", "okul no": "eyotek_id",
            "adı soyadı": "full_name", "tarih": "tarih",
            "ders": "ders", "öğretmen": "ogretmen",
            "sınıf": "sinif", "saat": "saat", "durum": "durum",
            "süre": "sure", "yoklama": "yoklama", "kaydeden": "kaydeden",
            "etüt türü": "etut_turu", "derslik": "derslik",
        }
        records = await _read_all_grid_pages(self._page, field_map)
        logger.success(f"  → {len(records)} etüt ({target_date})")
        return records

    # ── Etüt Raporları (öğretmen bazlı) ────────────────────────────────
    async def get_etut_reports(self) -> list[dict]:
        """
        Etüt Raporları sayfası — öğretmen bazlı etüt istatistikleri.
        URL: Pages/Student/individual-lesson-reports
        Sütunlar: Öğretmen Id, Şube, Tarih, Ad-Soyad, Toplam Mesai,
                  Toplam Ders, Toplam Etüt, Öğrenci Sayısı, Başarı
        """
        logger.info("[RAPOR] get_etut_reports()")
        await self._goto("Pages/Student/individual-lesson-reports")
        await asyncio.sleep(2)
        # Sag ustteki ARA linkine tikla → modal acar
        await self._page.evaluate("""
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
        await asyncio.sleep(2)
        # Modal icindeki btnSearch butonuna tikla
        await self._page.click('#btnSearch')
        await asyncio.sleep(3)

        # Dogrudan JavaScript ile tablo oku (GridView1)
        records = await self._page.evaluate("""
            () => {
                const tbl = document.getElementById('GridView1')
                    || document.querySelector('table');
                if (!tbl) return [];
                const ths = Array.from(tbl.querySelectorAll('th'))
                    .map(h => h.innerText.trim().toLowerCase());
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
        """)
        # Field map donusumu
        fm = {
            "öğretmen id": "ogretmen_id", "şube": "sube", "tarih": "tarih",
            "ad-soyad": "full_name", "toplam mesai": "toplam_mesai",
            "toplam ders": "toplam_ders", "toplam etüt": "toplam_etut",
            "öğrenci sayısı": "ogrenci_sayisi", "başarı": "basari",
        }
        mapped = []
        for r in records:
            row = {}
            for k, v in r.items():
                if k in fm:
                    row[fm[k]] = v
                else:
                    row[k] = v
            mapped.append(row)
        logger.success(f"  -> {len(mapped)} ogretmen etut raporu")
        return mapped

    # ── Etüt Öğrenci Kontrol ────────────────────────────────────────────
    async def get_etut_student_control(self) -> list[dict]:
        """
        Etüt Öğrenci Kontrol sayfası — öğrenci bazlı etüt katılım durumu.
        URL: Pages/Student/individual-lesson-control-student
        Sütunlar: Şube, Söz No, Okul No, Adı, Soyadı, Devre, Sınıf,
                  Yapıldı, Öğrenci gelmedi, Kontrol edilmedi, Toplam
        """
        logger.info("[KONTROL] get_etut_student_control()")
        await self._goto("Pages/Student/individual-lesson-control-student")
        await asyncio.sleep(2)
        # ARA link → modal → btnSearch
        await self._page.evaluate("""
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
        await asyncio.sleep(2)
        await self._page.click('#btnSearch')
        await asyncio.sleep(3)

        # Sayfalamali JavaScript tablo okuma
        all_records = []
        page_num = 1
        while True:
            records = await self._page.evaluate("""
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
            logger.info(f"  Sayfa {page_num}: {len(records)} kayit")

            # Sonraki sayfa
            page_num += 1
            next_clicked = await self._page.evaluate(f"""
                () => {{
                    const links = document.querySelectorAll('a');
                    for (const a of links) {{
                        if (a.innerText.trim() === '{page_num}' && a.offsetParent) {{
                            a.click();
                            return true;
                        }}
                    }}
                    return false;
                }}
            """)
            if not next_clicked:
                break
            await asyncio.sleep(2)

        # Field map donusumu
        fm = {
            "şube": "sube", "söz no": "soz_no", "okul no": "okul_no",
            "adı": "ad", "soyadı": "soyad", "devre": "devre",
            "sınıf": "sinif", "yapıldı": "yapildi",
            "öğrenci gelmedi": "gelmedi",
            "kontrol edilmedi": "kontrol_edilmedi", "toplam": "toplam",
        }
        mapped = []
        for r in all_records:
            row = {}
            for k, v in r.items():
                if k in fm:
                    row[fm[k]] = v
                else:
                    row[k] = v
            mapped.append(row)
        logger.success(f"  -> {len(mapped)} ogrenci etut kontrol")
        return mapped

    # ── Öğrenci Etüt Detay (per-student) ────────────────────────────────
    async def get_student_etut_details(self, st_id: str) -> dict:
        """
        Bireysel öğrenci etüt geçmişi + istatistik.
        URL: Pages/Student/student-individual-lesson?St_Id=...
        Grid: Tarih, Saat, Süre, Tür, Ders, Konu, Öğretmen, Derslik, Kontrol
        Sağ taraf: Etüt Grafik (pasta — yapıldı/gelmedi/kontrol edilmedi)
        """
        logger.info(f"[ETUT-DETAY] get_student_etut_details(st_id={st_id[:10]}...)")
        url = _build_student_section_url(st_id, "Etüt")
        await self._page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        # Grid verisi
        field_map = {
            "tarih": "tarih", "saat": "saat", "süre": "sure",
            "tür": "tur", "ders": "ders", "konu": "konu",
            "öğretmen": "ogretmen", "derslik": "derslik",
            "kontrol": "kontrol",
        }
        records = await _read_all_grid_pages(self._page, field_map)

        # Pasta grafik istatistik (sag taraftaki ozet)
        stats = await self._page.evaluate("""
            () => {
                const result = {yapildi: 0, gelmedi: 0, kontrol_edilmedi: 0, toplam: 0};
                // Sayilari bul: "Yapildi 11", "Ogrenci gelmedi 3" gibi
                const allText = document.body.innerText;
                const yMatch = allText.match(/Yap[ıi]ld[ıi]\\s+(\\d+)/i);
                const gMatch = allText.match(/[Öö][ğg]renci gelmedi\\s+(\\d+)/i);
                const kMatch = allText.match(/Kontrol edilmedi\\s+(\\d+)/i);
                const tMatch = allText.match(/BULUNAN KAYIT SAYISI\\s*:\\s*(\\d+)/i);
                if (yMatch) result.yapildi = parseInt(yMatch[1]);
                if (gMatch) result.gelmedi = parseInt(gMatch[1]);
                if (kMatch) result.kontrol_edilmedi = parseInt(kMatch[1]);
                if (tMatch) result.toplam = parseInt(tMatch[1]);
                return result;
            }
        """)

        logger.success(f"  -> {len(records)} etut kaydi, stats={stats}")
        return {"records": records, "stats": stats}

    # ── Öğretmen El Programı (haftalık) ─────────────────────────────────
    async def get_teacher_timetable(self, teacher_id: str = "") -> dict:
        """
        Öğretmen El Programı — öğretmen listesi + seçilen öğretmenin haftalık programı.
        URL: Pages/Student/timetable-staff-list
        Sol: Öğretmen listesi (Id, Ad Soyad, Branş, Saat)
        Sağ: Haftalık ders programı grid (Pazartesi-Pazar, saat slotları)
        """
        logger.info(f"[OGRETMEN-PROGRAM] get_teacher_timetable(teacher_id={teacher_id!r})")
        await self._goto("Pages/Student/timetable-staff-list")
        await asyncio.sleep(2)

        # Sol taraf: ogretmen listesi
        teachers = await self._page.evaluate("""
            () => {
                const result = [];
                const rows = document.querySelectorAll('table tr');
                for (const tr of rows) {
                    const cells = Array.from(tr.querySelectorAll('td'));
                    if (cells.length >= 3) {
                        const checkbox = tr.querySelector('input[type=checkbox]');
                        result.push({
                            id: cells[0]?.innerText?.trim() || '',
                            full_name: cells[1]?.innerText?.trim() || '',
                            brans: cells[2]?.innerText?.trim() || '',
                            saat: cells[3]?.innerText?.trim() || '',
                            checked: checkbox ? checkbox.checked : false
                        });
                    }
                }
                return result.filter(r => r.id && /^\\d+$/.test(r.id));
            }
        """)

        # Eger teacher_id verilmisse, o ogretmene tikla
        if teacher_id:
            clicked = await self._page.evaluate(f"""
                (tid) => {{
                    const rows = document.querySelectorAll('table tr');
                    for (const tr of rows) {{
                        const cells = Array.from(tr.querySelectorAll('td'));
                        if (cells.length >= 1 && cells[0].innerText.trim() === tid) {{
                            const cb = tr.querySelector('input[type=checkbox]');
                            if (cb) {{ cb.click(); return true; }}
                            const arrow = tr.querySelector('a, button, span[onclick]');
                            if (arrow) {{ arrow.click(); return true; }}
                            tr.click();
                            return true;
                        }}
                    }}
                    return false;
                }}
            """, teacher_id)
            if clicked:
                await asyncio.sleep(2)

        # Sag taraf: haftalik program tablosu
        timetable = await self._page.evaluate("""
            () => {
                // "Ders Programi" tab'indeki tablo
                const tables = document.querySelectorAll('table');
                let bestTable = null;
                let bestCols = 0;
                for (const tbl of tables) {
                    const ths = tbl.querySelectorAll('th');
                    if (ths.length > bestCols) {
                        bestCols = ths.length;
                        bestTable = tbl;
                    }
                }
                if (!bestTable || bestCols < 5) return {headers: [], rows: [], found: false};

                const headers = Array.from(bestTable.querySelectorAll('th'))
                    .map(h => h.innerText.trim());
                const rows = [];
                bestTable.querySelectorAll('tbody tr').forEach(tr => {
                    const cells = Array.from(tr.querySelectorAll('td'))
                        .map(td => td.innerText.trim());
                    if (cells.some(c => c)) rows.push(cells);
                });
                return {headers, rows, found: true};
            }
        """)

        logger.success(f"  -> {len(teachers)} ogretmen, program={'var' if timetable.get('found') else 'yok'}")
        return {"teachers": teachers, "timetable": timetable}

    # ── Çarşaf Liste (tüm sınıfların haftalık programı) ──────────────────
    async def get_timetable_branch_list(self, day: str = "") -> dict:
        """
        Çarşaf Liste — tüm sınıfların haftalık ders programı.
        URL: Pages/Student/timetable-branch-list
        Sütunlar: 14 ders slotu (09:00-19:50)
        Satırlar: Sınıf grupları ([1] 12 SAY A, [11] MEZUN SAY B vb.)
        Her hücre: Öğretmen, Ders, Derslik
        """
        logger.info(f"[CARSAF] get_timetable_branch_list(day={day!r})")
        await self._goto("Pages/Student/timetable-branch-list")
        await asyncio.sleep(2)

        # Gun filtresi (dropdown varsa)
        if day:
            await self._page.evaluate(f"""
                (dayName) => {{
                    const selects = document.querySelectorAll('select');
                    for (const sel of selects) {{
                        for (const opt of sel.options) {{
                            if (opt.text.trim().toLowerCase().includes(dayName.toLowerCase())) {{
                                sel.value = opt.value;
                                sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                                return true;
                            }}
                        }}
                    }}
                    return false;
                }}
            """, day)
            await asyncio.sleep(2)

        # Mevcut gun
        selected_day = await self._page.evaluate("""
            () => {
                const selects = document.querySelectorAll('select');
                for (const sel of selects) {
                    if (sel.selectedIndex >= 0) {
                        const txt = sel.options[sel.selectedIndex].text.trim();
                        if (['Pazartesi','Salı','Çarşamba','Perşembe','Cuma','Cumartesi','Pazar']
                            .some(d => txt.includes(d))) return txt;
                    }
                }
                return '';
            }
        """)

        # Tablo verisi (en buyuk tablo)
        data = await self._page.evaluate("""
            () => {
                const tables = document.querySelectorAll('table');
                let bestTable = null;
                let bestCols = 0;
                for (const tbl of tables) {
                    const ths = tbl.querySelectorAll('th');
                    if (ths.length > bestCols) {
                        bestCols = ths.length;
                        bestTable = tbl;
                    }
                }
                if (!bestTable) return {headers: [], rows: [], found: false};

                const headers = Array.from(bestTable.querySelectorAll('th'))
                    .map(h => h.innerText.trim());
                const rows = [];
                bestTable.querySelectorAll('tbody tr').forEach(tr => {
                    const cells = Array.from(tr.querySelectorAll('td'))
                        .map(td => td.innerText.trim());
                    if (cells.some(c => c)) rows.push(cells);
                });
                return {headers, rows, found: true};
            }
        """)

        logger.success(f"  -> gun={selected_day}, {len(data.get('rows',[]))} satir")
        return {"day": selected_day, "timetable": data}

    # ── Sınıf Ders Programı ────────────────────────────────────────────
    async def get_class_timetable(self, class_id: str = "") -> dict:
        """
        Sınıf Ders Programı — sınıf listesi + seçilen sınıfın haftalık programı.
        URL: Pages/Student/timetable-class-list
        Sol: Sınıf listesi (Devre, Sınıf, Saat — 13 sınıf)
        Sağ: Haftalık ders programı (Pazartesi-Pazar, saat slotları)
        Her hücre: Ders, Öğretmen, Derslik
        Tabs: Sınıflar, Ekstra Sınıflar, Kulüpler
        """
        logger.info(f"[SINIF-PROGRAM] get_class_timetable(class_id={class_id!r})")
        await self._goto("Pages/Student/timetable-class-list")
        await asyncio.sleep(2)

        # Sol taraf: sinif listesi
        classes = await self._page.evaluate("""
            () => {
                const result = [];
                const rows = document.querySelectorAll('table tr');
                for (const tr of rows) {
                    const cells = Array.from(tr.querySelectorAll('td'));
                    if (cells.length >= 3) {
                        const checkbox = tr.querySelector('input[type=checkbox]');
                        result.push({
                            devre: cells[0]?.innerText?.trim() || '',
                            sinif: cells[1]?.innerText?.trim() || '',
                            saat: cells[2]?.innerText?.trim() || '',
                            checked: checkbox ? checkbox.checked : false
                        });
                    }
                }
                return result.filter(r => r.sinif && r.sinif !== 'Sınıf');
            }
        """)

        # Eger class_id verilmisse, o sinifa tikla
        if class_id:
            await self._page.evaluate(f"""
                (cid) => {{
                    const rows = document.querySelectorAll('table tr');
                    for (const tr of rows) {{
                        const cells = Array.from(tr.querySelectorAll('td'));
                        if (cells.length >= 2 && cells[1].innerText.trim().includes(cid)) {{
                            const cb = tr.querySelector('input[type=checkbox]');
                            if (cb) {{ cb.click(); return true; }}
                            tr.click();
                            return true;
                        }}
                    }}
                    return false;
                }}
            """, class_id)
            await asyncio.sleep(2)

        # Sag taraf: haftalik ders programi
        timetable = await self._page.evaluate("""
            () => {
                const tables = document.querySelectorAll('table');
                let bestTable = null;
                let bestCols = 0;
                for (const tbl of tables) {
                    const ths = tbl.querySelectorAll('th');
                    if (ths.length > bestCols) {
                        bestCols = ths.length;
                        bestTable = tbl;
                    }
                }
                if (!bestTable || bestCols < 5) return {headers: [], rows: [], found: false};
                const headers = Array.from(bestTable.querySelectorAll('th'))
                    .map(h => h.innerText.trim());
                const rows = [];
                bestTable.querySelectorAll('tbody tr').forEach(tr => {
                    const cells = Array.from(tr.querySelectorAll('td'))
                        .map(td => td.innerText.trim());
                    if (cells.some(c => c)) rows.push(cells);
                });
                return {headers, rows, found: true};
            }
        """)

        logger.success(f"  -> {len(classes)} sinif, program={'var' if timetable.get('found') else 'yok'}")
        return {"classes": classes, "timetable": timetable}

    # ── Sınıf Listesi (öğrenci kadrosu) ─────────────────────────────────
    async def get_class_roster(self, class_name: str = "") -> dict:
        """
        Sınıf Listesi — sınıf seçimi + o sınıftaki öğrenci kadrosu.
        URL: Pages/Student/class-list
        Mekanizma: Mavi ok (btn-info) tıkla → sağ panelde öğrenci listesi açılır.
        """
        logger.info(f"[SINIF-KADRO] get_class_roster(class_name={class_name!r})")
        await self._goto("Pages/Student/class-list")
        await asyncio.sleep(2)

        # GrdClasses tablosundan sinif listesi
        classes = await self._page.evaluate("""
            () => {
                const tbl = document.getElementById('GrdClasses');
                if (!tbl) return [];
                const result = [];
                tbl.querySelectorAll('tbody tr, tr').forEach((tr, idx) => {
                    const cells = Array.from(tr.querySelectorAll('td'));
                    if (cells.length < 3) return;
                    const texts = cells.map(c => c.innerText.trim()).filter(t => t !== '');
                    if (texts.length >= 2 && texts[0].startsWith('[')) {
                        result.push({
                            sinif: texts[0], devre: texts[1],
                            ogrenci_sayisi: texts[2] || '0', index: idx
                        });
                    }
                });
                return result;
            }
        """)

        # Eger class_name verilmisse, o sinifin mavi okuna tikla
        if class_name:
            await self._page.evaluate(f"""
                (cname) => {{
                    const tbl = document.getElementById('GrdClasses');
                    if (!tbl) return false;
                    const rows = tbl.querySelectorAll('tbody tr, tr');
                    for (let i = 0; i < rows.length; i++) {{
                        const cells = Array.from(rows[i].querySelectorAll('td'));
                        const texts = cells.map(c => c.innerText.trim()).filter(t => t);
                        if (texts.some(t => t.includes(cname))) {{
                            const arrow = rows[i].querySelector('a.btn-info');
                            if (arrow) {{ arrow.click(); return true; }}
                        }}
                    }}
                    return false;
                }}
            """, class_name)
            await asyncio.sleep(2)

        # Sag taraftaki ogrenci tablosu
        students = await self._read_student_panel()

        logger.success(f"  -> {len(classes)} sinif, {len(students)} ogrenci")
        return {"classes": classes, "students": students}

    async def _read_student_panel(self) -> list[dict]:
        """Sağ paneldeki öğrenci listesi tablosunu oku (Söz No, Adı, Soyadı vb.)."""
        return await self._page.evaluate("""
            () => {
                const tables = document.querySelectorAll('table');
                for (const tbl of tables) {
                    const ths = Array.from(tbl.querySelectorAll('th'))
                        .map(h => h.innerText.trim());
                    if (!ths.some(h => h === 'Söz No' || h === 'Adı')) continue;
                    const headers = ths.map(h => h.toLowerCase());
                    const rows = [];
                    tbl.querySelectorAll('tbody tr').forEach(tr => {
                        const cells = Array.from(tr.querySelectorAll('td'))
                            .map(td => td.innerText.trim());
                        if (cells.length >= 3) {
                            const row = {};
                            headers.forEach((h, i) => {
                                if (cells[i] && h) row[h] = cells[i];
                            });
                            rows.push(row);
                        }
                    });
                    return rows;
                }
                return [];
            }
        """)

    # ── Tüm Sınıfların Öğrenci Kadrosunu Toplu Çek ─────────────────────
    async def get_all_class_rosters(self) -> dict:
        """
        Tüm sınıfları tek tek mavi ok butonuna tıklayıp
        her birinin öğrenci kadrosunu çeker.
        Mekanizma: Mavi ok (btn-info) → sağ panelde öğrenci listesi açılır.
        """
        logger.info("[TOPLU-KADRO] get_all_class_rosters()")
        await self._goto("Pages/Student/class-list")
        await asyncio.sleep(2)

        # GrdClasses tablosundan sinif listesi + mavi ok index'i
        classes = await self._page.evaluate("""
            () => {
                const tbl = document.getElementById('GrdClasses');
                if (!tbl) return [];
                const result = [];
                const rows = tbl.querySelectorAll('tbody tr, tr');
                rows.forEach((tr, idx) => {
                    const cells = Array.from(tr.querySelectorAll('td'));
                    if (cells.length < 3) return;
                    // Non-empty text cells (skip checkbox & arrow columns)
                    const texts = cells.map(c => c.innerText.trim()).filter(t => t !== '');
                    if (texts.length >= 2 && texts[0].startsWith('[')) {
                        result.push({
                            sinif: texts[0],
                            devre: texts[1],
                            ogrenci_sayisi: parseInt(texts[2]) || 0,
                            rowIndex: idx
                        });
                    }
                });
                return result;
            }
        """)

        all_rosters = {}
        for i, cls in enumerate(classes):
            sinif_name = cls["sinif"]
            logger.info(f"  -> [{i+1}/{len(classes)}] {sinif_name} kadrosu cekiliyor...")

            # Mavi ok butonuna tikla (btn-info, GrdClasses icindeki i. ok)
            clicked = await self._page.evaluate(f"""
                (idx) => {{
                    const tbl = document.getElementById('GrdClasses');
                    if (!tbl) return false;
                    const arrows = tbl.querySelectorAll('a.btn-info');
                    if (idx < arrows.length) {{
                        arrows[idx].click();
                        return true;
                    }}
                    return false;
                }}
            """, i)

            if not clicked:
                logger.warning(f"    {sinif_name}: mavi ok bulunamadi, atlanıyor")
                continue

            await asyncio.sleep(2)

            # Sag taraftaki ogrenci tablosunu oku
            students = await self._page.evaluate("""
                () => {
                    const tables = document.querySelectorAll('table');
                    for (const tbl of tables) {
                        const ths = Array.from(tbl.querySelectorAll('th'))
                            .map(h => h.innerText.trim());
                        if (!ths.some(h => h === 'Söz No' || h === 'Adı')) continue;
                        const headers = ths.map(h => h.toLowerCase());
                        const rows = [];
                        tbl.querySelectorAll('tbody tr').forEach(tr => {
                            const cells = Array.from(tr.querySelectorAll('td'))
                                .map(td => td.innerText.trim());
                            if (cells.length >= 3) {
                                const row = {};
                                headers.forEach((h, i) => {
                                    if (cells[i] && h) row[h] = cells[i];
                                });
                                rows.push(row);
                            }
                        });
                        return rows;
                    }
                    return [];
                }
            """)

            all_rosters[sinif_name] = {
                "devre": cls["devre"],
                "ogrenci_sayisi": cls["ogrenci_sayisi"],
                "students": students
            }
            logger.info(f"    {sinif_name}: {len(students)} ogrenci")

        total = sum(len(v["students"]) for v in all_rosters.values())
        logger.success(f"  -> Toplam {len(all_rosters)} sinif, {total} ogrenci")
        return all_rosters

    # ── İstatistik Raporları ──────────────────────────────────────────
    async def get_student_count_report(self) -> dict:
        """Öğrenci sayısı istatistik raporu."""
        logger.info("📊 get_student_count_report()")
        await self._goto("Pages/Reports/student-count")
        await asyncio.sleep(3)
        data = await self._page.evaluate("""
            () => {
                const tables = [];
                document.querySelectorAll('table').forEach(tbl => {
                    const headers = Array.from(tbl.querySelectorAll('th'))
                        .map(h => h.innerText.trim());
                    if (headers.length < 2) return;
                    const rows = [];
                    tbl.querySelectorAll('tbody tr').forEach(tr => {
                        const cells = Array.from(tr.querySelectorAll('td'))
                            .map(td => td.innerText.trim());
                        if (cells.length >= 2) rows.push(cells);
                    });
                    if (rows.length > 0) tables.push({headers, rows});
                });
                return tables;
            }
        """)
        return {"report": "student_count", "tables": data}

    # ── Öğrenci Sınav Sonuçları (per-student) ────────────────────────────
    async def get_student_exams(self, st_id: str) -> list[dict]:
        """Bireysel öğrenci sınav sonuçlarını çeker (student-test sayfası)."""
        logger.info(f"📝 get_student_exams(st_id={st_id[:10]}...)")
        url = _build_student_section_url(st_id, "Sınav")
        await self._page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(3)
        rows = await self._page.evaluate("""
            () => {
                const result = [];
                document.querySelectorAll('table').forEach(tbl => {
                    const headers = Array.from(tbl.querySelectorAll('th'))
                        .map(h => h.innerText.trim().toLowerCase());
                    if (headers.length < 3) return;
                    tbl.querySelectorAll('tbody tr, tr.dxgvDataRow').forEach(tr => {
                        const cells = Array.from(tr.querySelectorAll('td'))
                            .map(td => td.innerText.trim());
                        if (cells.length >= 3) {
                            const row = {};
                            headers.forEach((h, i) => { if (cells[i]) row[h] = cells[i]; });
                            result.push(row);
                        }
                    });
                });
                return result;
            }
        """)
        logger.success(f"  → {len(rows)} sınav sonucu")
        return rows

    # ── Öğrenci Davranış Kayıtları ────────────────────────────────────
    async def get_student_behaviour(self, st_id: str) -> list[dict]:
        """Öğrenci davranış kayıtlarını çeker (student-behaviour sayfası)."""
        logger.info(f"⭐ get_student_behaviour(st_id={st_id[:10]}...)")
        url = _build_student_section_url(st_id, "Davranış")
        await self._page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(3)
        rows = await self._page.evaluate("""
            () => {
                const result = [];
                document.querySelectorAll('table').forEach(tbl => {
                    const headers = Array.from(tbl.querySelectorAll('th'))
                        .map(h => h.innerText.trim().toLowerCase());
                    if (headers.length < 2) return;
                    tbl.querySelectorAll('tbody tr, tr.dxgvDataRow').forEach(tr => {
                        const cells = Array.from(tr.querySelectorAll('td'))
                            .map(td => td.innerText.trim());
                        if (cells.length >= 2) {
                            const row = {};
                            headers.forEach((h, i) => { if (cells[i]) row[h] = cells[i]; });
                            result.push(row);
                        }
                    });
                });
                return result;
            }
        """)
        logger.success(f"  → {len(rows)} davranış kaydı")
        return rows

    # ── Öğrenci Ders Programı ─────────────────────────────────────────
    async def get_student_timetable(self, st_id: str) -> dict:
        """Öğrenci haftalık ders programını çeker (student-timetable sayfası)."""
        logger.info(f"📅 get_student_timetable(st_id={st_id[:10]}...)")
        url = _build_student_section_url(st_id, "Ders Programı")
        await self._page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(3)
        data = await self._page.evaluate("""
            () => {
                const tables = document.querySelectorAll('table');
                for (const tbl of tables) {
                    const headers = Array.from(tbl.querySelectorAll('th'))
                        .map(h => h.innerText.trim());
                    if (headers.length < 5) continue;
                    const rows = [];
                    tbl.querySelectorAll('tbody tr').forEach(tr => {
                        const cells = Array.from(tr.querySelectorAll('td'))
                            .map(td => td.innerText.trim());
                        if (cells.length >= 2) rows.push(cells);
                    });
                    return {headers, rows, found: true};
                }
                return {headers: [], rows: [], found: false};
            }
        """)
        logger.success(f"  → {len(data.get('rows', []))} ders satırı")
        return data

    # ── Öğrenci Yazılı Notları ────────────────────────────────────────
    async def get_student_grades(self, st_id: str) -> list[dict]:
        """Öğrenci yazılı notlarını çeker (student-exam-grades sayfası)."""
        logger.info(f"📊 get_student_grades(st_id={st_id[:10]}...)")
        url = _build_student_section_url(st_id, "Yazılı Notları")
        await self._page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(3)
        rows = await self._page.evaluate("""
            () => {
                const result = [];
                document.querySelectorAll('table').forEach(tbl => {
                    const headers = Array.from(tbl.querySelectorAll('th'))
                        .map(h => h.innerText.trim().toLowerCase());
                    if (headers.length < 2) return;
                    tbl.querySelectorAll('tbody tr, tr.dxgvDataRow').forEach(tr => {
                        const cells = Array.from(tr.querySelectorAll('td'))
                            .map(td => td.innerText.trim());
                        if (cells.length >= 2) {
                            const row = {};
                            headers.forEach((h, i) => { if (cells[i]) row[h] = cells[i]; });
                            result.push(row);
                        }
                    });
                });
                return result;
            }
        """)
        logger.success(f"  → {len(rows)} yazılı notu")
        return rows

    # ── Öğrenci Özel Bilgileri ────────────────────────────────────────
    async def get_student_specific_details(self, st_id: str) -> dict:
        """Öğrenci özel bilgilerini çeker (student-detail-specific)."""
        logger.info(f"🔍 get_student_specific_details(st_id={st_id[:10]}...)")
        url = _build_student_section_url(st_id, "Özel Bilgiler")
        await self._page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(3)
        data = await self._page.evaluate("""
            () => {
                const fields = {};
                // Label-value ciftlerini tara
                document.querySelectorAll('label, span, td').forEach(el => {
                    const text = el.innerText.trim();
                    const next = el.nextElementSibling;
                    if (next && text && text.length < 30) {
                        const val = next.value || next.innerText?.trim() || '';
                        if (val && val.length < 200) fields[text] = val;
                    }
                });
                // Input degerlerini de tara
                document.querySelectorAll('input[type=text], textarea, select').forEach(el => {
                    if (el.id && el.value) fields[el.id] = el.value;
                });
                return fields;
            }
        """)
        logger.success(f"  → {len(data)} alan")
        return data

    # ── Sınav Birleştirme & Konu Analizi ────────────────────────────────
    async def get_student_exam_analysis(self, st_id: str, diploma_notu: int = 95) -> dict:
        """
        Öğrencinin tüm sınavlarını birleştirip detaylı konu analizi çeker.
        Akış: student-test → tüm sınavları seç → BİRLEŞTİR → diploma notu (95) → rapor
        Bu fonksiyon READ-ONLY — öğrenci verisini DEĞİŞTİRMEZ, sadece rapor üretir.
        """
        logger.info(f"📊 get_student_exam_analysis(st_id={st_id[:10]}..., diploma={diploma_notu})")
        url = _build_student_section_url(st_id, "Sınav")
        await self._page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        # Adım 1: Tüm sınav checkbox'larını seç
        selected = await self._page.evaluate("""
            () => {
                const checkboxes = document.querySelectorAll('input[type="checkbox"]');
                let count = 0;
                for (const cb of checkboxes) {
                    if (cb.offsetParent !== null && !cb.checked) {
                        cb.checked = true;
                        cb.dispatchEvent(new Event('change', {bubbles: true}));
                        count++;
                    }
                }
                return count;
            }
        """)
        logger.info(f"  {selected} sınav seçildi")
        await asyncio.sleep(0.5)

        # Adım 2: "SEÇİLİ SINAVLARI BİRLEŞTİR" butonuna tıkla
        merged = await self._page.evaluate("""
            () => {
                const btns = document.querySelectorAll('a, button, input[type=button]');
                for (const b of btns) {
                    const t = (b.innerText || b.value || '').trim();
                    if (t.includes('BİRLEŞTİR') && b.offsetParent !== null) {
                        b.click();
                        return t;
                    }
                }
                return null;
            }
        """)
        if not merged:
            logger.warning("  BİRLEŞTİR butonu bulunamadı")
            return {"success": False, "message": "Birleştir butonu bulunamadı"}
        logger.info(f"  BİRLEŞTİR tıklandı: {merged}")
        await asyncio.sleep(2)

        # Adım 3: Diploma Notu modal — 95 yaz ve DEVAM ET
        await self._page.evaluate(f"""
            () => {{
                const inputs = document.querySelectorAll('input[type=text], input[type=number]');
                for (const inp of inputs) {{
                    if (inp.offsetParent !== null) {{
                        inp.value = '{diploma_notu}';
                        inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                        inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                        return;
                    }}
                }}
            }}
        """)
        await asyncio.sleep(0.5)

        # DEVAM ET butonuna tıkla
        await self._page.evaluate("""
            () => {
                const btns = document.querySelectorAll('a, button, input[type=button]');
                for (const b of btns) {
                    const t = (b.innerText || b.value || '').trim();
                    if (t.includes('DEVAM') && b.offsetParent !== null) {
                        b.click();
                        return true;
                    }
                }
                return false;
            }
        """)
        await asyncio.sleep(5)  # Rapor üretimi biraz sürer

        # Adım 4: Rapor verilerini çek
        report = await self._page.evaluate("""
            () => {
                const result = {success: true, tables: [], puan: {}, ders_kayip: [], oncelikli: []};

                // Tüm tabloları tara
                document.querySelectorAll('table').forEach((tbl, idx) => {
                    const headers = Array.from(tbl.querySelectorAll('th'))
                        .map(h => h.innerText.trim());
                    const rows = [];
                    tbl.querySelectorAll('tbody tr, tr').forEach(tr => {
                        if (tr.querySelector('th')) return; // header row skip
                        const cells = Array.from(tr.querySelectorAll('td'))
                            .map(td => td.innerText.trim());
                        if (cells.length >= 2) rows.push(cells);
                    });
                    if (headers.length >= 2 || rows.length >= 1) {
                        result.tables.push({idx, headers, rows: rows.slice(0, 50)});
                    }
                });

                // Puan kartlarını bul
                document.querySelectorAll('[class*="card"], [class*="panel"], div').forEach(el => {
                    const text = el.innerText || '';
                    if (text.includes('HAM PUAN') || text.includes('YERLEŞME')) {
                        const nums = text.match(/[\\d.,]+/g);
                        if (nums && nums.length >= 1) {
                            if (text.includes('HAM PUAN')) result.puan.ham = nums[0];
                            if (text.includes('YERLEŞME')) result.puan.yerlesme = nums[0];
                        }
                    }
                });

                // ÖSYM sıralama verisi
                const osymItems = [];
                document.querySelectorAll('td, span, div').forEach(el => {
                    const t = el.innerText.trim();
                    if (t.match(/ÖSYM|OSYM/) || t.match(/^20[0-9]{2}$/)) {
                        osymItems.push(t);
                    }
                });
                result.osym_raw = osymItems.slice(0, 20);

                // Öncelikli konular bölümü
                const sections = document.querySelectorAll('[class*="priority"], [class*="oncelik"]');
                // Fallback: div/section içinde "1. Öncelik" gibi metin ara
                document.querySelectorAll('*').forEach(el => {
                    const t = el.innerText?.trim();
                    if (t && (t.includes('1. Öncelik') || t.includes('2. Öncelik') || t.includes('3. Öncelik'))) {
                        const nearby = el.closest('div, section');
                        if (nearby) {
                            const tbl = nearby.querySelector('table');
                            if (tbl) {
                                const tblHeaders = Array.from(tbl.querySelectorAll('th'))
                                    .map(h => h.innerText.trim());
                                const tblRows = [];
                                tbl.querySelectorAll('tbody tr').forEach(tr => {
                                    const cells = Array.from(tr.querySelectorAll('td'))
                                        .map(td => td.innerText.trim());
                                    if (cells.length >= 2) tblRows.push(cells);
                                });
                                result.oncelikli.push({level: t.substring(0,12), headers: tblHeaders, rows: tblRows});
                            }
                        }
                    }
                });

                return result;
            }
        """)

        logger.success(f"  → {len(report.get('tables', []))} tablo, puan={report.get('puan', {})}")
        return report

    # ── Per-Student Yoklama (kişiye özel devamsızlık geçmişi) ─────────
    async def get_student_attendance(self, st_id: str) -> list[dict]:
        """Bireysel öğrenci yoklama geçmişini çeker (student-attendance)."""
        logger.info(f"📋 get_student_attendance(st_id={st_id[:10]}...)")
        url = _build_student_section_url(st_id, "Yoklama")
        await self._page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(3)
        rows = await self._page.evaluate("""
            () => {
                const result = [];
                document.querySelectorAll('table').forEach(tbl => {
                    const headers = Array.from(tbl.querySelectorAll('th'))
                        .map(h => h.innerText.trim().toLowerCase());
                    if (headers.length < 2) return;
                    tbl.querySelectorAll('tbody tr, tr.dxgvDataRow').forEach(tr => {
                        const cells = Array.from(tr.querySelectorAll('td'))
                            .map(td => td.innerText.trim());
                        if (cells.length >= 2) {
                            const row = {};
                            headers.forEach((h, i) => { if (cells[i]) row[h] = cells[i]; });
                            result.push(row);
                        }
                    });
                });
                return result;
            }
        """)
        logger.success(f"  → {len(rows)} yoklama kaydı")
        return rows

    # ════════════════════════════════════════════════════════════════════════
    # WRITE OPERASYONLARI
    # ════════════════════════════════════════════════════════════════════════

    # ── PostBack yardımcı metodu (ASP.NET UpdatePanel) ─────────────────────────
    async def _postback(self, target: str, argument: str = "", wait: float = 2.5) -> None:
        """ASP.NET __doPostBack tetikle, UpdatePanel yanıtını bekle."""
        await self._page.evaluate(f"__doPostBack(\'{target}\', \'{argument}\')")
        await asyncio.sleep(wait)

    # ─────────────────────────────────────────────────────────────────────────
    # ETÜ T KAYDET — v2.0 Tam Uygulama (06 Nisan 2026)
    # Keşfedilen ID'ler (Chrome DOM inspect + JavaScript reverse):
    #
    #  Takvim Grid:
    #   • Satır = tarih (tablo satırı, hücre[0] = "DD.MM.YYYY Gün")
    #   • Sütun = Ders No 1-15 (zaman dilimi)
    #   • "+" butonu: <a id="GrdIndividualLessons_bi{dersNo}_1_{rowIdx}">
    #   • PostBack hedefi: GrdIndividualLessons$ctl{rowIdx+2}$bi{dersNo}_1
    #   → btn.click() ile doğrudan tetikle (JS href="javascript:__doPostBack(…)")
    #
    #  Modal — Normal Mod (Tür=N, RblIndividulaLessonCatagory_0):
    #   • TxtAddStudentNameNormal        → Öğrenci Adı arama
    #   • DdlAddClassesNormal            → Sınıf (format "[id] ClassName")
    #   • BtnSearchStudent  [PostBack]   → LİSTELE
    #   • LstAddStudentsNormal           → Öğrenci listesi (multiple select)
    #   • BtnLstAddSelectAllStudents [PostBack] → Tümünü Seç / seçilenleri aktar
    #   • DdlAddIndividualLessonTypeNormal → 1=Etüt 2=Ek Ders 3=Özel Ders 4=Seminer 5=Sınıf Etüdü
    #   • DdlAddLevelNormal              → Devre (1.Snf, 2.Snf … 9.Snf-Hzr)
    #   • DdlAddDurationNormal           → Etüt Süresi (35 = 35dk)
    #   • DdlAddRepeatNormal             → Haftalık Tekrar (1-10)
    #   • TxtAddRemoteLinkNormal         → Uzaktan Eğitim linki (opsiyonel)
    #   • DdlAddLessonNormal             → Ders (154 seçenek)
    #   • DdlAddSubjectNormal            → Konu (AJAX, ders seçince dolar)
    #   • DdlAddClassroomWatchPlaceNormal→ Derslik (D-2=2, D-3=3, D-4=4, D-5=5, D-6=6)
    #   • DdlTeachers                    → Öğretmen (18 seçenek)
    #   • BtnAddIndividualLessonSaveNormal [PostBack] → KAYDET ✅
    # ─────────────────────────────────────────────────────────────────────────
    async def write_etut(
        self,
        class_name: str,
        student_id_or_name: str,
        lesson: str,
        target_date: str,           # "DD.MM.YYYY" formatında tarih, ör. "07.04.2026"
        ders_no: int = 5,           # Zaman dilimi sütunu 1-15 (5 = 12:00-12:35)
        etut_type: str = "Etüt",    # Etüt / Ek Ders / Özel Ders / Seminer / Sınıf Etüdü
        devre: str = "",            # Devre: "1.Snf", "2.Snf", … (DdlAddLevelNormal)
        duration: int = 35,         # Etüt Süresi dakika
        repeat: int = 1,            # Haftalık Tekrar (1-10)
        subject_topic: str = "",    # Konu (opsiyonel, AJAX)
        classroom: str = "",        # Derslik: "D-2", "D-3" vb.
        teacher: str = "",          # Öğretmen adı kısmı (opsiyonel, varsayılan: giriş yapan)
        select_all_in_class: bool = False,  # True = sınıftaki tüm öğrencileri seç
        dry_run: bool = True,
    ) -> dict:
        """
        Etüt Girişi sayfasında takvim slotu seçerek etüt kaydı oluştur.

        DRY RUN MODU (varsayılan): Gerçek yazma yapılmaz, form parametreleri döner.
        Gerçek kayıt için: dry_run=False geçirilmeli (fermat_core_agent ACL+onay kontrolü yapar).

        Akış:
          1. Sayfaya git
          2. target_date + ders_no sütunundaki "+" butonuna tıkla → modal açılır
          3. Sınıf + öğrenci ara → BtnSearchStudent PostBack
          4. Öğrencileri seç → BtnLstAddSelectAllStudents PostBack
          5. Form alanlarını doldur (tür, devre, süre, tekrar, ders, konu, derslik)
          6. BtnAddIndividualLessonSaveNormal PostBack → KAYDET
          7. Sonucu döndür
        """
        log_tag = f"write_etut(sinif={class_name!r}, ogrenci={student_id_or_name!r}, ders={lesson!r}, tarih={target_date}, dersNo={ders_no})"
        logger.info(f"✏️  {log_tag}")

        # ── DRY RUN notu ──────────────────────────────────────────────────
        # dry_run=True olsa bile formu sonuna kadar doldurur, sadece KAYDET'e basmaz.
        # Boylece tum form adimlarinin dogru calistigini dogrulariz.
        if dry_run:
            logger.info(f"  DRY RUN — form doldurulacak, KAYDET atlanacak ({log_tag})")

        # Eski hizli dry_run blogu kaldirildi — form her durumda acilir
        _dry_run_preview = {
                    "class_name": class_name,
                    "student": student_id_or_name,
                    "lesson": lesson,
                    "target_date": target_date,
                    "ders_no": ders_no,
                    "etut_type": etut_type,
                    "devre": devre,
                    "duration": duration,
                    "repeat": repeat,
                    "classroom": classroom,
                    "teacher": teacher,
                    "select_all_in_class": select_all_in_class,
                }

        # ── Etüt Türü normaliz ── geçersiz tip → "Etüt" ──────────────────
        _ETUT_TYPE_ALIASES = {
            "seviye belirleme": "Etüt",
            "seviye": "Etüt",
            "bilinmiyor": "Etüt",
            "ek ders": "Ek Ders",
            "özel ders": "Özel Ders",
            "seminer": "Seminer",
            "sınıf etüdü": "Sınıf Etüdü",
            "sinif etüdü": "Sınıf Etüdü",
        }
        _VALID_TYPES = {"Etüt", "Ek Ders", "Özel Ders", "Seminer", "Sınıf Etüdü"}
        if etut_type not in _VALID_TYPES:
            normalized = _ETUT_TYPE_ALIASES.get(etut_type.lower().strip(), "Etüt")
            logger.warning(f"  ⚠️ etut_type='{etut_type}' geçersiz → '{normalized}' olarak normaliz edildi")
            etut_type = normalized

        # ── target_date zorunlu kontrol ───────────────────────────────────
        if not target_date:
            logger.error("  ❌ target_date boş — etüt yazılamaz. DD.MM.YYYY formatında tarih gerekli.")
            return {
                "success": False,
                "message": "target_date gerekli (DD.MM.YYYY). Örnek: '07.04.2026'",
                "step": "target_date_missing",
            }

        # ── ADIM 1: Etüt Girişi sayfasına git ────────────────────────────
        logger.info(f"  🗓 Tarih: {target_date}, DersNo: {ders_no}, Tür: {etut_type}")
        await self._goto("Pages/Student/individual-lesson-input")
        await asyncio.sleep(2)

        # ── ADIM 2: Öğretmen seç (opsiyonel) ─────────────────────────────
        if teacher:
            teacher_set = await self._page.evaluate(f"""
                () => {{
                    const sel = document.getElementById('DdlTeachers');
                    if (!sel) return false;
                    const q = '{teacher.lower()}';
                    for (const o of sel.options) {{
                        if (o.text.toLowerCase().includes(q)) {{
                            sel.value = o.value;
                            sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                            return o.text;
                        }}
                    }}
                    return false;
                }}
            """)
            logger.info(f"  Öğretmen: {teacher_set}")
            if not teacher_set:
                logger.warning(f"  Öğretmen bulunamadı: {teacher!r}")

        # ── ADIM 3: Takvim grid'de hedef tarihin "+" butonuna tıkla ──────
        slot_result = await self._page.evaluate(f"""
            () => {{
                const table = document.querySelector('table.ozel');
                if (!table) return 'HATA:table_not_found';
                const dateTarget = '{target_date}';
                const dersNo = {ders_no};
                for (const row of table.rows) {{
                    const dateCell = row.cells[0];
                    if (!dateCell) continue;
                    const dateTxt = dateCell.textContent.replace(/\\s+/g,' ').trim();
                    if (!dateTxt.includes(dateTarget)) continue;
                    const slotCell = row.cells[dersNo];
                    if (!slotCell) return 'HATA:cell_not_found:dersNo=' + dersNo;
                    const btn = slotCell.querySelector('a.btn');
                    if (!btn) {{
                        return 'DOLU:' + slotCell.textContent.trim();
                    }}
                    btn.click();
                    return 'OK:' + btn.id;
                }}
                return 'HATA:date_not_found:' + dateTarget;
            }}
        """)
        logger.info(f"  Slot: {slot_result}")
        if str(slot_result).startswith("HATA:"):
            return {"success": False, "message": f"Slot bulunamadı: {slot_result}", "step": "slot_click"}
        if str(slot_result).startswith("DOLU:"):
            return {"success": False, "message": f"Bu slot zaten dolu: {slot_result}", "step": "slot_click"}

        # Modal açılmasını bekle (PostBack + UpdatePanel yenileme)
        await asyncio.sleep(3)

        # ── ADIM 4: Öğrenci adı filtresi (bireysel için) ─────────────────
        if student_id_or_name and not select_all_in_class:
            # Eyotek ogrenci aramasi kucuk harfle calisiyor (Turkce karakter duyarli!)
            # Python .lower() Turkce İ'yi yanlis cevirir: İ → i̇ (combining dot)
            # Kendi Turkce kucuk harf fonksiyonumuzu kullaniyoruz
            _TR_TO_LOWER = str.maketrans("ABCÇDEFGĞHIİJKLMNOÖPRSŞTUÜVYZ", "abcçdefgğhıijklmnoöprsştuüvyz")
            search_parts = student_id_or_name.strip().split()
            search_term = search_parts[0].translate(_TR_TO_LOWER)  # "ALİ" → "ali", "İREM" → "irem"
            stu_name_esc = search_term.replace("'", "\\'")
            logger.info(f"  Ogrenci arama: '{search_term}' (tam ad: {student_id_or_name})")
            await self._page.evaluate(f"""
                () => {{
                    const inp = document.getElementById('TxtAddStudentNameNormal');
                    if (inp) {{
                        inp.value = '{stu_name_esc}';
                        inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                        inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                    }}
                }}
            """)

        # ── ADIM 5: Sınıf seç (DdlAddClassesNormal) ──────────────────────
        # class_name boşsa atla — öğrenci adı filtresi yeterli olabilir
        if class_name:
            class_result = await self._page.evaluate(f"""
                () => {{
                    const sel = document.getElementById('DdlAddClassesNormal');
                    if (!sel) return 'HATA:DdlAddClassesNormal_not_found';
                    const q = '{class_name.lower()}';
                    for (const o of sel.options) {{
                        if (o.text.toLowerCase().includes(q)) {{
                            sel.value = o.value;
                            sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                            return 'OK:' + o.text;
                        }}
                    }}
                    const mevcut = Array.from(sel.options).slice(1,6).map(o=>o.text).join(' | ');
                    return 'HATA:not_found | Mevcut: ' + mevcut;
                }}
            """)
            logger.info(f"  Sınıf: {class_result}")
            if str(class_result).startswith("HATA:"):
                logger.warning(f"  Sınıf seçilemedi ({class_result}) — tüm öğrenciler arasında aranacak")
                # Hata olsa bile devam et; öğrenci adı filtresiyle bulunabilir
        else:
            logger.info("  class_name boş — sınıf filtresi atlanıyor, öğrenci adıyla aranacak")
            class_result = "ATLANDI"

        # ── ADIM 6: LİSTELE — öğrencileri yükle ─────────────────────────
        # ASP.NET UpdatePanel icinde __doPostBack calismayabilir
        # Fiziksel buton tiklamasi + fallback olarak PostBack dene
        search_clicked = await self._page.evaluate("""
            () => {
                const btn = document.getElementById('BtnSearchStudent');
                if (btn && btn.offsetParent) {
                    const rect = btn.getBoundingClientRect();
                    return {x: Math.round(rect.x + rect.width/2), y: Math.round(rect.y + rect.height/2)};
                }
                return null;
            }
        """)
        if search_clicked:
            await self._page.mouse.click(search_clicked["x"], search_clicked["y"])
            logger.info(f"  LİSTELE fiziksel tiklandi: ({search_clicked['x']},{search_clicked['y']})")
        else:
            # Fallback: PostBack
            await self._postback("BtnSearchStudent")
            logger.info("  LİSTELE PostBack fallback kullanildi")
        await asyncio.sleep(3)

        # ── ADIM 7: Öğrenci seçimi ────────────────────────────────────────
        if select_all_in_class:
            logger.info("  Tüm sınıf öğrencileri seçiliyor…")
            await self._postback("BtnLstAddSelectAllStudents", wait=2.0)
        else:
            # Turkce buyuk harf normalizasyonu
            _tr_upper_map = str.maketrans("iığşüöç", "İIĞŞÜÖÇ")
            stu_query_upper = student_id_or_name.translate(_tr_upper_map).upper()
            stu_query_esc = stu_query_upper.replace("'", "\\'")

            # SADECE hedef ogrenciyi sec — sol listede tiklayinca otomatik saga gecer!
            # Eyotek mekanizmasi: option'a tiklama = dogrudan saga transfer
            stu_result = await self._page.evaluate(f"""
                () => {{
                    const lst = document.getElementById('LstAddStudentsNormal');
                    if (!lst) return 'HATA:LstAddStudentsNormal_not_found';
                    const fullName = '{stu_query_esc}';
                    let bestMatch = null;
                    let bestIdx = -1;
                    let bestScore = 0;

                    for (let i = 0; i < lst.options.length; i++) {{
                        const o = lst.options[i];
                        const txt = o.text.toUpperCase();
                        const optName = txt.split('(')[0].trim();

                        if (optName === fullName) {{
                            bestMatch = o; bestIdx = i; bestScore = 100; break;
                        }}
                        if (txt.includes(fullName) && bestScore < 90) {{
                            bestMatch = o; bestIdx = i; bestScore = 90;
                        }}
                        const nameParts = fullName.split(' ');
                        const surname = nameParts[nameParts.length - 1];
                        if (optName.includes(surname) && bestScore < 50) {{
                            bestMatch = o; bestIdx = i; bestScore = 50;
                        }}
                    }}

                    if (!bestMatch) return 'HATA:not_found | toplam=' + lst.options.length;

                    // Option'in koordinatini dondur — fiziksel tiklama icin
                    const rect = bestMatch.getBoundingClientRect();
                    return JSON.stringify({{
                        status: 'OK',
                        name: bestMatch.text.split('(')[0].trim(),
                        score: bestScore,
                        idx: bestIdx,
                        x: Math.round(rect.x + rect.width/2),
                        y: Math.round(rect.y + rect.height/2)
                    }});
                }}
            """)
            logger.info(f"  Öğrenci bulundu: {stu_result}")

            if str(stu_result).startswith("HATA:"):
                return {
                    "success": False,
                    "message": f"Öğrenci listede bulunamadı: {student_id_or_name} ({stu_result})",
                    "step": "student_select",
                }

            # Parse JSON result
            import json as _json
            try:
                match_info = _json.loads(stu_result)
            except Exception:
                match_info = {"x": 0, "y": 0, "name": "?"}

            # Sol listede ogrenciye FIZIKSEL tikla — otomatik saga gecer
            if match_info.get("x", 0) > 0 and match_info.get("y", 0) > 0:
                await self._page.mouse.click(match_info["x"], match_info["y"])
                logger.info(f"  Ogrenci tiklandi → saga aktarildi: {match_info.get('name','?')}")
            else:
                # Fallback: option index ile sec + TUMUNU SEC
                await self._page.evaluate(f"""() => {{
                    const lst = document.getElementById('LstAddStudentsNormal');
                    lst.selectedIndex = {match_info.get('idx', 0)};
                    lst.options[{match_info.get('idx', 0)}].selected = true;
                    lst.dispatchEvent(new Event('change', {{bubbles:true}}));
                    lst.dispatchEvent(new Event('dblclick', {{bubbles:true}}));
                }}""")
                logger.info("  Ogrenci index ile secildi (fallback)")
            await asyncio.sleep(2)

        # ── ADIM 8: Etüt Türü ────────────────────────────────────────────
        # etut_type yukarıda normaliz edildi (Etüt/Ek Ders/Özel Ders/Seminer/Sınıf Etüdü)
        _ETUT_TYPE_MAP = {"Etüt": "1", "Ek Ders": "2", "Özel Ders": "3", "Seminer": "4", "Sınıf Etüdü": "5"}
        type_val = _ETUT_TYPE_MAP.get(etut_type, "1")
        await self._page.evaluate(f"""
            () => {{
                const sel = document.getElementById('DdlAddIndividualLessonTypeNormal');
                if (sel) {{
                    sel.value = '{type_val}';
                    sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                }}
            }}
        """)
        logger.info(f"  Etüt Türü: {etut_type} → val={type_val}")

        # ── ADIM 9: Devre (DdlAddLevelNormal) ────────────────────────────
        if devre:
            devre_result = await self._page.evaluate(f"""
                () => {{
                    const sel = document.getElementById('DdlAddLevelNormal');
                    if (!sel) return 'HATA:not_found';
                    const q = '{devre.lower()}';
                    for (const o of sel.options) {{
                        if (o.text.toLowerCase().includes(q) || o.value.toLowerCase().includes(q)) {{
                            sel.value = o.value;
                            sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                            return 'OK:' + o.text;
                        }}
                    }}
                    const mevcut = Array.from(sel.options).slice(1,5).map(o=>o.text).join(',');
                    return 'WARN:not_found | Mevcut: ' + mevcut;
                }}
            """)
            logger.info(f"  Devre ({devre}): {devre_result}")

        # ── ADIM 10: Etüt Süresi (DdlAddDurationNormal) ──────────────────
        await self._page.evaluate(f"""
            () => {{
                const sel = document.getElementById('DdlAddDurationNormal');
                if (!sel) return;
                for (const o of sel.options) {{
                    if (o.value == '{duration}' || o.text.includes('{duration}')) {{
                        sel.value = o.value;
                        sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                        return;
                    }}
                }}
            }}
        """)

        # ── ADIM 11: Haftalık Tekrar (DdlAddRepeatNormal) ─────────────────
        await self._page.evaluate(f"""
            () => {{
                const sel = document.getElementById('DdlAddRepeatNormal');
                if (sel) {{
                    sel.value = '{repeat}';
                    sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                }}
            }}
        """)

        # ── ADIM 12: Ders (DdlAddLessonNormal) ────────────────────────────
        lesson_result = await self._page.evaluate(f"""
            () => {{
                const sel = document.getElementById('DdlAddLessonNormal');
                if (!sel) return 'HATA:DdlAddLessonNormal_not_found';
                const q = '{lesson.lower()}';
                for (const o of sel.options) {{
                    if (o.text.toLowerCase().includes(q)) {{
                        sel.value = o.value;
                        sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                        return 'OK:' + o.text;
                    }}
                }}
                return 'HATA:not_found';
            }}
        """)
        logger.info(f"  Ders ({lesson}): {lesson_result}")
        if str(lesson_result).startswith("HATA:"):
            return {"success": False, "message": f"Ders bulunamadı: {lesson}", "step": "lesson_select"}

        await asyncio.sleep(1.5)  # DdlAddSubjectNormal AJAX yüklemesi

        # ── ADIM 13: Konu (opsiyonel, DdlAddSubjectNormal) ────────────────
        if subject_topic:
            await self._page.evaluate(f"""
                () => {{
                    const sel = document.getElementById('DdlAddSubjectNormal');
                    if (!sel) return;
                    const q = '{subject_topic.lower()}';
                    for (const o of sel.options) {{
                        if (o.text.toLowerCase().includes(q)) {{
                            sel.value = o.value;
                            sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                            return;
                        }}
                    }}
                }}
            """)

        # ── ADIM 14: Derslik (opsiyonel, DdlAddClassroomWatchPlaceNormal) ─
        if classroom:
            await self._page.evaluate(f"""
                () => {{
                    const sel = document.getElementById('DdlAddClassroomWatchPlaceNormal');
                    if (!sel) return;
                    const q = '{classroom.lower()}';
                    for (const o of sel.options) {{
                        if (o.text.toLowerCase().includes(q) || o.value == q.replace('d-','')) {{
                            sel.value = o.value;
                            sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                            return;
                        }}
                    }}
                }}
            """)

        # ── DRY RUN KONTROLU — form dolduruldu, KAYDET atlanacak ─────────
        if dry_run:
            logger.info("  DRY RUN TAMAMLANDI — form dolduruldu, KAYDET basilmadi")
            # Formdaki mevcut degerleri oku (dogrulama icin)
            form_state = await self._page.evaluate("""
                () => ({
                    etutType: document.getElementById('DdlAddIndividualLessonTypeNormal')?.selectedOptions?.[0]?.text || '',
                    lesson: document.getElementById('DdlAddLessonNormal')?.selectedOptions?.[0]?.text || '',
                    devre: document.getElementById('DdlAddLevelNormal')?.selectedOptions?.[0]?.text || '',
                    duration: document.getElementById('DdlAddDurationNormal')?.value || '',
                    classroom: document.getElementById('DdlAddClassroomWatchPlaceNormal')?.selectedOptions?.[0]?.text || '',
                })
            """)
            return {
                "dry_run": True,
                "success": True,
                "message": "DRY RUN — form basariyla dolduruldu, KAYDET basilmadi",
                "preview": _dry_run_preview,
                "form_state": form_state,
            }

        # ── ADIM 15: KAYDET — BtnAddIndividualLessonSaveNormal PostBack ───
        logger.info("  KAYDET PostBack gönderiliyor…")
        await self._postback("BtnAddIndividualLessonSaveNormal", wait=3.0)

        # ── ADIM 16: Sonuç kontrolü ────────────────────────────────────────
        result = await self._page.evaluate("""
            () => {
                const conflictSels = ['[id*="Conflict"]', '[id*="conflict"]', '.modal.in .modal-body', '.swal2-container'];
                for (const cs of conflictSels) {
                    const el = document.querySelector(cs);
                    if (el && el.offsetParent !== null) {
                        const txt = el.innerText.trim();
                        if (txt && (txt.includes('çakış') || txt.includes('Çakış') || txt.includes('conflict'))) {
                            return {type: 'conflict', msg: txt.substring(0, 300)};
                        }
                    }
                }
                const msgSels = ['.swal2-html-container', '.sweet-alert p', '.alert-success', '.alert-danger', '.alert-warning', '.alert', '#lblResult', '#lblMessage', '[id*=Message]', '[id*=Result]'];
                for (const sel of msgSels) {
                    const el = document.querySelector(sel);
                    if (el && el.offsetParent !== null && el.innerText.trim()) {
                        return {type: sel, msg: el.innerText.trim().substring(0, 300)};
                    }
                }
                return {type: 'no_message', msg: 'Kaydet PostBack tamamlandı — görünür mesaj yok'};
            }
        """)

        msg   = result.get("msg", "")
        rtype = result.get("type", "")
        is_conflict = rtype == "conflict"
        is_error    = "danger" in rtype or "error" in rtype.lower() or "hata" in msg.lower()
        success     = not is_conflict and not is_error

        if is_conflict:
            logger.warning(f"  ⚠️ Çakışma tespit edildi: {msg[:100]}")
        elif success:
            logger.success(f"  ✅ Etüt kaydedildi: {msg[:100]}")
        else:
            logger.error(f"  ❌ Etüt kaydedilemedi: {msg[:100]}")

        # 25.43-AUDIT-V2: write_etut audit hook — KAYDET sonrası takvimde
        # gerçekten oluştu mu Vision teyit. dry_run değilse + success ise.
        audit_info = None
        try:
            from eyotek_self_audit import audit_write_etut, AUDIT_ENABLED
            if AUDIT_ENABLED and not dry_run and success:
                _SAAT_MAP = {1:"09:00",2:"09:45",3:"10:30",4:"11:15",5:"12:00",
                             6:"12:45",7:"14:00",8:"14:45",9:"15:30",10:"16:15",
                             11:"17:00",12:"17:45",13:"18:30",14:"19:15",15:"20:00"}
                saat_str = _SAAT_MAP.get(int(ders_no), "?")
                audit_info = await audit_write_etut(
                    self._page,
                    ogrenci_adi=str(student_id_or_name),
                    ogretmen=teacher or "(seçili)",
                    tarih=target_date,
                    saat=saat_str,
                    ders=lesson,
                    sinif=class_name,
                )
                if audit_info.get("audited"):
                    v = audit_info.get("vision_result") or {}
                    logger.info(f"[AUDIT] write_etut verdict={v.get('verdict')} "
                                f"obs='{(v.get('observation') or '')[:80]}'")
        except Exception as _ae:
            logger.debug(f"[WRAP] write_etut audit skip: {_ae}")

        ret = {
            "success": success,
            "message": msg,
            "type": rtype,
            "conflict": is_conflict,
            "params": {
                "class_name": class_name,
                "student": student_id_or_name,
                "lesson": lesson,
                "target_date": target_date,
                "ders_no": ders_no,
                "etut_type": etut_type,
                "devre": devre,
                "duration": duration,
                "repeat": repeat,
                "classroom": classroom,
            },
        }
        if audit_info and audit_info.get("audited"):
            ret["_audit"] = audit_info
        return ret

    # ── Sınıf Etüt Kaydı (tüm sınıf için) ──────────────────────────────────
    async def write_etut_for_class(
        self,
        class_name: str,
        lesson: str,
        target_date: str,               # "DD.MM.YYYY" formatında
        ders_no: int = 5,               # Zaman dilimi sütunu 1-15
        etut_type: str = "Sınıf Etüdü",
        devre: str = "",
        duration: int = 35,
        repeat: int = 1,
        subject_topic: str = "",
        classroom: str = "",
        teacher: str = "",
        dry_run: bool = True,
    ) -> dict:
        """
        Tüm sınıf için tek seferde etüt kaydı oluştur.
        write_etut() fonksiyonuna select_all_in_class=True ile delege eder.
        """
        logger.info(f"✏️  write_etut_for_class(sinif={class_name!r}, ders={lesson!r}, tarih={target_date})")
        return await self.write_etut(
            class_name=class_name,
            student_id_or_name="",
            lesson=lesson,
            target_date=target_date,
            ders_no=ders_no,
            etut_type=etut_type,
            devre=devre,
            duration=duration,
            repeat=repeat,
            subject_topic=subject_topic,
            classroom=classroom,
            teacher=teacher,
            select_all_in_class=True,
            dry_run=dry_run,
        )


    # ── Rehberlik Notu Yaz ───────────────────────────────────────────────────
    async def write_counsellor_note(
        self,
        student_id: str,
        note: str,
        note_type: str = "Genel",
        meeting_type: str = "Yüz Yüze",
        dry_run: bool = True,
    ) -> dict:
        """
        Öğrenci için rehberlik notu ekle.
        Döndürür: {"success": bool, "message": str}
        """
        logger.info(f"💬 write_counsellor_note(student={student_id})")

        # ── St_Id'yi bul (öğrenci profil URL'i için gerekli) ──────────────
        # get_student_profile() ile St_Id alınabilir, ama hız için önce
        # doğrudan student-counsellor-note sayfasına gitmeyi dene.
        # St_Id biliniyorsa (ya da profil dict'i geçildiyse) hızlı path kullan.
        import re as _re
        st_id = None
        # student_id bir dict ise (profil nesnesi) → st_id direkt al
        if isinstance(student_id, dict):
            st_id = student_id.get("st_id")
            student_id = student_id.get("eyotek_id", "")
        if not st_id:
            # Öğrenci profilinden st_id al
            logger.info("  St_Id için profil alınıyor...")
            prof = await self.get_student_profile(str(student_id))
            st_id = prof.get("st_id")

        if not st_id:
            logger.warning("  St_Id bulunamadı — counsellor-note-list fallback")
            target_url = f"{BASE_URL}/Pages/Student/counsellor-note-list"
        else:
            # Keşfedilen gerçek URL: student-counsellor-note?ST_Id=...
            target_url = _build_student_section_url(st_id, "Rehberlik Notu")
            logger.info(f"  Hedef: {target_url.split('?')[0].split('/')[-1]}")

        await self._page.goto(target_url, wait_until="domcontentloaded")
        await asyncio.sleep(2.5)

        # ── Sayfa durumunu logla (debug) ──────────────────────────────────
        page_info = await self._page.evaluate("""
            () => ({
                url: location.href,
                btns: Array.from(document.querySelectorAll(
                    'a,button,input[type=button],input[type=submit]'))
                    .filter(b => b.offsetParent !== null)
                    .map(b => ({ id: b.id, t: (b.innerText||b.value||'').trim().slice(0,30) }))
                    .filter(b => b.t)
                    .slice(0, 20)
            })
        """)
        logger.info(f"  Sayfa: {page_info.get('url','')[-50:]}")
        logger.info(f"  Görünür butonlar: {[b['id'] or b['t'] for b in page_info.get('btns', [])]}")

        # ── EKLE butonuna tıkla ───────────────────────────────────────────
        # Eyotek'in student-counsellor-note sayfasında farklı ID patternleri:
        # - btnAddNote   (profil sayfasında)
        # - btnAdd       (bazı varyantlarda)
        # - input[value=EKLE]  (PostBack form)
        add_clicked = await self._page.evaluate("""
            () => {
                // Öncelik 1: Bilinen ID'ler
                for (const id of ['btnAddNote', 'btnAdd', 'btnEkle', 'BtnAdd']) {
                    const el = document.getElementById(id);
                    if (el && el.offsetParent !== null) {
                        el.click();
                        return id;
                    }
                }
                // Öncelik 2: input[type=button] value=EKLE
                for (const b of document.querySelectorAll('input[type=button],input[type=submit]')) {
                    const v = (b.value || '').trim().toUpperCase();
                    if ((v === 'EKLE' || v === 'YENİ EKLE') && b.offsetParent !== null) {
                        b.click();
                        return 'input_value:' + b.id;
                    }
                }
                // Öncelik 3: a/button text
                for (const b of document.querySelectorAll('a, button')) {
                    const t = (b.innerText || '').trim().toUpperCase();
                    if ((t === 'EKLE' || t === 'NOT EKLE' || t === 'YENİ NOT' || t === 'YENİ EKLE')
                        && b.offsetParent !== null) {
                        b.click();
                        return b.id || ('text:' + t);
                    }
                }
                return null;
            }
        """)

        if not add_clicked:
            logger.warning("  'EKLE / btnAddNote' butonu bulunamadı.")
            return {"success": False, "message": "Ekle butonu bulunamadı"}

        logger.info(f"  EKLE tıklandı: {add_clicked}")
        await asyncio.sleep(2)

        # ── Form alanlarını doldur ────────────────────────────────────────
        # Keşfedilen alan ID'leri (student-counsellor-note sayfası):
        #   cmbNotTuru      : Kanaat(O) | Olay(E) | Telefon(P) | Yüz Yüze(F)
        #   cmbGorusmeTuru  : Öğrenci(STU) | Veli(PAR) | Anne(MOT) | Baba(FAT)
        #   cmbGorunsun     : Öğrenci(S) | Veli(P) | Her İkisi(PS)
        #   textarea/richtext: not metni

        # Not türü → cmbNotTuru (değer olarak "O","E","P","F" gönder)
        NOTE_TYPE_MAP = {
            "kanaat": "O", "olay": "E", "telefon": "P", "yüz yüze": "F",
            "genel": "O",  # fallback
        }
        note_type_val = NOTE_TYPE_MAP.get(note_type.lower().strip(), "O")

        # Görüşme türü → cmbGorusmeTuru
        MEETING_TYPE_MAP = {
            "öğrenci": "STU", "veli": "PAR", "anne": "MOT", "baba": "FAT",
            "kardeş": "SIB", "yüz yüze": "STU",  # fallback
        }
        meeting_type_val = MEETING_TYPE_MAP.get(meeting_type.lower().strip(), "STU")

        await self._page.evaluate(f"""
            () => {{
                // cmbNotTuru
                const notTuru = document.getElementById('cmbNotTuru');
                if (notTuru) {{
                    notTuru.value = '{note_type_val}';
                    notTuru.dispatchEvent(new Event('change', {{bubbles: true}}));
                }}
                // cmbGorusmeTuru
                const gorusmeTuru = document.getElementById('cmbGorusmeTuru');
                if (gorusmeTuru) {{
                    gorusmeTuru.value = '{meeting_type_val}';
                    gorusmeTuru.dispatchEvent(new Event('change', {{bubbles: true}}));
                }}
            }}
        """)
        await asyncio.sleep(0.5)

        # Not metnini yaz (textarea veya contenteditable)
        filled = await self._page.evaluate("""
            (noteText) => {
                // Görünür textarea ara
                const areas = Array.from(document.querySelectorAll(
                    'textarea, [contenteditable=true]'))
                    .filter(el => el.offsetParent !== null);
                if (areas.length > 0) {
                    const ta = areas[0];
                    if (ta.tagName === 'TEXTAREA') {
                        ta.value = noteText;
                    } else {
                        ta.innerText = noteText;
                    }
                    ta.dispatchEvent(new Event('input', {bubbles: true}));
                    ta.dispatchEvent(new Event('change', {bubbles: true}));
                    return ta.id || ta.tagName;
                }
                // Metin giriş alanı fallback
                const inputs = Array.from(document.querySelectorAll('input[type=text]'))
                    .filter(el => el.offsetParent !== null
                                  && !el.id.startsWith('s2id')
                                  && !el.readOnly);
                if (inputs.length > 0) {
                    inputs[0].value = noteText;
                    inputs[0].dispatchEvent(new Event('input', {bubbles: true}));
                    return inputs[0].id || 'text_input';
                }
                return null;
            }
        """, note)
        logger.info(f"  Not metni girildi: {filled}")
        await asyncio.sleep(1)

        # ── DRY RUN kontrolu ─────────────────────────────────────────────
        if dry_run:
            logger.info("  DRY RUN — KAYDET tiklanmadi, preview donduruluyor")
            return {
                "success": True,
                "dry_run": True,
                "message": "DRY RUN — not kaydedilmedi, sadece form dolduruldu",
                "student_id": str(student_id),
                "note_type": note_type_val,
                "meeting_type": meeting_type_val,
                "note_preview": note[:200],
                "add_btn": add_clicked,
                "textarea": filled,
            }

        # ── KAYDET ────────────────────────────────────────────────────────
        saved = await self._page.evaluate("""
            () => {
                for (const id of ['btnSave', 'btnKaydet', 'btnSaveNote']) {
                    const el = document.getElementById(id);
                    if (el && el.offsetParent !== null) { el.click(); return id; }
                }
                for (const b of document.querySelectorAll(
                        'a,button,input[type=button],input[type=submit]')) {
                    const t = (b.innerText || b.value || '').trim().toUpperCase();
                    if ((t === 'KAYDET' || t === 'KAYDET VE KAPAT') && b.offsetParent !== null) {
                        b.click(); return 'text:' + t;
                    }
                }
                return null;
            }
        """)
        logger.info(f"  KAYDET: {saved}")
        await asyncio.sleep(2.5)

        # Sonucu kontrol et — toast, alert veya hata mesajı
        result_info = await self._page.evaluate("""
            () => {
                for (const sel of [
                    '.swal2-html-container', '.toast-body', '.alert-success',
                    '.alert-danger', '.alert', '[id*=Message]', '[id*=Result]',
                    '[class*=success]', '[class*=error]',
                ]) {
                    const el = document.querySelector(sel);
                    if (el && el.offsetParent !== null && el.innerText.trim()) {
                        return { sel, msg: el.innerText.trim().slice(0, 200) };
                    }
                }
                return null;
            }
        """)

        # 25.43-AUDIT-V2: write_counsellor_note audit hook — KAYDET sonrası
        # rehberlik notları listesinde bugün kaydı görünüyor mu Vision teyit.
        async def _audit_counsellor():
            try:
                from eyotek_self_audit import audit_write_counsellor, AUDIT_ENABLED
                if not AUDIT_ENABLED:
                    return None
                return await audit_write_counsellor(
                    self._page,
                    ogrenci_adi=str(student_id),
                    not_turu=note_type_val,
                    gorusulen=note[:200],
                )
            except Exception as _ae:
                logger.debug(f"[WRAP] write_counsellor audit skip: {_ae}")
                return None

        if result_info:
            is_error = any(w in result_info["sel"] for w in ["danger", "error"])
            logger.info(f"  Sonuç: {result_info['msg']}")
            ret = {
                "success": not is_error,
                "message": result_info["msg"],
                "note_type": note_type_val,
                "meeting_type": meeting_type_val,
                "save_btn": saved,
            }
            if not is_error:
                ai = await _audit_counsellor()
                if ai and ai.get("audited"):
                    ret["_audit"] = ai
                    v = ai.get("vision_result") or {}
                    logger.info(f"[AUDIT] write_counsellor verdict={v.get('verdict')} "
                                f"obs='{(v.get('observation') or '')[:80]}'")
            return ret

        # Toast yok — screenshot al ve metni döndür
        await self._page.screenshot(path="counsellor_note_result.png")
        page_text = await self._page.evaluate("() => document.body.innerText.slice(0,400)")
        has_error = any(w in page_text.lower() for w in ["hata", "error", "başarısız"])
        ret = {
            "success": not has_error,
            "message": "Sonuç algılanamadı — screenshot: counsellor_note_result.png",
            "note_type": note_type_val,
            "meeting_type": meeting_type_val,
            "save_btn": saved,
        }
        if not has_error:
            ai = await _audit_counsellor()
            if ai and ai.get("audited"):
                ret["_audit"] = ai
                v = ai.get("vision_result") or {}
                logger.info(f"[AUDIT] write_counsellor (no-toast) verdict={v.get('verdict')}")
        return ret

    # ── SMS Gönder ───────────────────────────────────────────────────────────
    async def send_sms(
        self,
        message: str,
        student_ids: list[str] | None = None,
        class_name: str = "",
        devre: str = "",
        program: str = "",
        dry_run: bool = False,
    ) -> dict:
        """
        Seçili öğrencilere / sınıfa SMS gönder.

        Eyotek SMS akışı (profile_map.json'dan keşfedildi):
          1. Pages/Student/communication-sms-special-text aç
          2. Filtreler: cmbSubeler, cmbProgram, lstDevre, cmbKur
          3. DEVAM ET (id=btnGetNotify) → öğrenci listesi yüklenir
          4. Tüm checkbox'ları seç (veya belirli öğrenciler)
          5. Mesajı textarea'ya yaz → GÖNDER

        dry_run=True → Gönderme, sadece öğrenci listesini döndür (test amaçlı)
        """
        logger.info(f"📱 send_sms(class={class_name!r}, dry_run={dry_run})")
        await self._goto("Pages/Student/communication-sms-special-text")
        await asyncio.sleep(2)

        # ── ADIM 1: Filtre seç (isteğe bağlı) ────────────────────────────
        if devre:
            await self._page.evaluate(f"""
                () => {{
                    const sel = document.getElementById('lstDevre');
                    if (!sel) return;
                    for (const opt of sel.options) {{
                        if (opt.value === '{devre}' || opt.text.includes('{devre}')) {{
                            opt.selected = true;
                        }}
                    }}
                    sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                }}
            """)
            logger.info(f"  Devre filtresi: {devre}")

        if program:
            await self._page.evaluate(f"""
                () => {{
                    const sel = document.getElementById('cmbProgram');
                    if (!sel) return;
                    for (const opt of sel.options) {{
                        if (opt.text.toLowerCase().includes('{program.lower()}')) {{
                            sel.value = opt.value;
                            sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                            return;
                        }}
                    }}
                }}
            """)
            logger.info(f"  Program filtresi: {program}")

        # ── ADIM 2: DEVAM ET (btnGetNotify) → öğrenci listesini yükle ────
        devam_clicked = await self._page.evaluate("""
            () => {
                // profile_map.json'dan doğrulandı: id=btnGetNotify, text=DEVAM ET
                const btn = document.getElementById('btnGetNotify');
                if (btn && btn.offsetParent !== null) { btn.click(); return 'btnGetNotify'; }
                for (const b of document.querySelectorAll('a,button,input[type=button]')) {
                    const t = (b.innerText || b.value || '').trim().toUpperCase();
                    if (t === 'DEVAM ET' && b.offsetParent !== null) {
                        b.click(); return 'devam_et_text';
                    }
                }
                return null;
            }
        """)
        logger.info(f"  DEVAM ET: {devam_clicked}")
        await asyncio.sleep(3)

        # ── ADIM 3: Öğrenci listesini oku ────────────────────────────────
        student_count = await self._page.evaluate("""
            () => {
                const checks = document.querySelectorAll(
                    'input[type=checkbox][id*=chk], input[type=checkbox][name*=chk]'
                );
                if (checks.length > 0) return checks.length;
                // Multiselect veya grid
                return document.querySelectorAll('table tbody tr').length;
            }
        """)
        logger.info(f"  Yüklenen öğrenci: {student_count}")

        if dry_run:
            return {"success": True, "student_count": student_count, "message": "dry_run — gönderilmedi"}

        # ── ADIM 4: Öğrenci seç ──────────────────────────────────────────
        if student_ids:
            # Belirli öğrenciler
            selected = await self._page.evaluate(f"""
                () => {{
                    const ids = {student_ids};
                    let count = 0;
                    document.querySelectorAll('input[type=checkbox]').forEach(cb => {{
                        const row = cb.closest('tr');
                        if (!row) return;
                        const txt = row.innerText;
                        if (ids.some(id => txt.includes(id))) {{
                            cb.checked = true;
                            cb.dispatchEvent(new Event('change', {{bubbles: true}}));
                            count++;
                        }}
                    }});
                    return count;
                }}
            """)
            logger.info(f"  Seçilen: {selected} öğrenci")
        else:
            # Hepsini seç (tümünü seç checkbox)
            await self._page.evaluate("""
                () => {
                    // "Tümünü Seç" checkbox'ı
                    const all = document.querySelector(
                        'input[id*=chkAll], input[id*=SelectAll], input[id*=chkSelectAll]'
                    );
                    if (all) { all.checked = true; all.click(); return; }
                    // Tüm row checkbox'larını seç
                    document.querySelectorAll(
                        'input[type=checkbox][id*=chk], table tbody input[type=checkbox]'
                    ).forEach(cb => { cb.checked = true; });
                }
            """)
            logger.info("  Tüm öğrenciler seçildi")

        # ── ADIM 5: Mesajı yaz ───────────────────────────────────────────
        msg_escaped = message.replace("'", "\\'").replace("\n", "\\n")
        filled = await self._page.evaluate(f"""
            () => {{
                const areas = Array.from(document.querySelectorAll('textarea'))
                    .filter(ta => ta.offsetParent !== null);
                if (areas.length > 0) {{
                    areas[0].value = '{msg_escaped}';
                    areas[0].dispatchEvent(new Event('input', {{bubbles: true}}));
                    return areas[0].id || 'textarea';
                }}
                return null;
            }}
        """)
        logger.info(f"  Mesaj alanı: {filled}")

        if not filled:
            return {"success": False, "message": "Mesaj alanı bulunamadı", "student_count": student_count}

        # ── ADIM 6: GÖNDER ────────────────────────────────────────────────
        sent = await self._page.evaluate("""
            () => {
                for (const id of ['btnSend', 'btnGonder', 'btnSmsSend']) {
                    const el = document.getElementById(id);
                    if (el && el.offsetParent !== null) { el.click(); return id; }
                }
                for (const b of document.querySelectorAll('a,button,input[type=button]')) {
                    const t = (b.innerText || b.value || '').trim().toUpperCase();
                    if ((t === 'GÖNDER' || t === 'SMS GÖNDER') && b.offsetParent !== null) {
                        b.click(); return 'text:' + t;
                    }
                }
                return null;
            }
        """)
        logger.info(f"  GÖNDER: {sent}")
        await asyncio.sleep(3)

        result = await self._page.evaluate("""
            () => {
                for (const sel of ['.swal2-html-container','.toast-body','.alert']) {
                    const el = document.querySelector(sel);
                    if (el && el.innerText.trim()) return el.innerText.trim().slice(0,200);
                }
                return null;
            }
        """)
        success = bool(sent) and not (result and "hata" in result.lower())
        return {
            "success": success,
            "message": result or ("SMS gönderildi" if success else "Gönderim sonucu alınamadı"),
            "student_count": student_count,
            "send_btn": sent,
        }


# ════════════════════════════════════════════════════════════════════════════
# Standalone kullanım
# ════════════════════════════════════════════════════════════════════════════

async def demo():
    """Tüm fonksiyonları test et ve sonuçları göster."""
    cookies = load_session()
    if not cookies:
        logger.error("Session bulunamadı. Önce eyotek_agent.py ile giriş yapın.")
        return

    async with EyotekWrapper(cookies) as ew:

        # 1. Sınıf listesi
        classes = await ew.get_class_list()
        logger.info(f"\n📚 SINIFLAR ({len(classes)}):")
        for c in classes[:5]:
            logger.info(f"  {c}")

        # 2. Öğrenci listesi (ilk 5)
        students = await ew.get_student_list()
        logger.info(f"\n👥 ÖĞRENCİLER ({len(students)} toplam, ilk 3):")
        for s in students[:3]:
            logger.info(f"  {s.get('eyotek_id')} | {s.get('full_name')} | {s.get('sube')}")

        # 3. Bugünkü devamsızlıklar
        absent = await ew.get_today_absences()
        logger.info(f"\n❌ BUGÜN GELMEYENLER ({len(absent)}):")
        for a in absent[:3]:
            logger.info(f"  {a}")

        # 4. Sınav listesi
        exams = await ew.get_exam_list()
        logger.info(f"\n📝 SINAVLAR ({len(exams)}):")
        for e in exams[:3]:
            logger.info(f"  {e}")

        # 5. Öğrenci profili (ilk öğrenci)
        if students:
            first_id = students[0].get("eyotek_id", "")
            if first_id:
                profile = await ew.get_student_profile(first_id)
                logger.info(f"\n👤 PROFİL ({first_id}):")
                logger.info(f"  URL: {profile.get('profile_url')}")
                logger.info(f"  Tablar: {list(profile.get('tabs', {}).keys())}")


if __name__ == "__main__":
    asyncio.run(demo())
