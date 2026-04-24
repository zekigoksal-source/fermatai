"""
Eyotek Otonom Derin Keşif Scripti  (v3 – Self-Healing)
=======================================================
Çalışma mantığı:
  1. Chrome'a CDP ile bağlan (port 9222)
  2. Staff/home üzerinden oturumu doğrula → giriş gerekirsek bekle
  3. Öğrenci listesi Arama modalını tam haritala (tüm select seçenekleri)
  4. İlk öğrencinin "..." bağlam menüsünü aç → St_Id URL'ini keşfet
  5. student-detail?St_Id=... sayfasının tüm sekmelerini gez
  6. Yoklama / Etüt / Rehberlik / Sınav sayfalarını haritala
  7. profile_map.json'a yaz

GÜVENLİK: Sil, İptal, Kaydet, Güncelle, SMS Gönder butonlarına asla tıklanmaz.
"""

import asyncio
import json
import os
import re
import subprocess
import time
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger
from playwright.async_api import async_playwright, Page

load_dotenv()

BASE_URL     = os.getenv("EYOTEK_URL", "https://fermat.eyotek.com/v1")
CDP_PORT     = int(os.getenv("CDP_PORT", "9222"))
CDP_URL      = f"http://127.0.0.1:{CDP_PORT}"
SESSION_FILE = Path(os.getenv("SESSION_FILE", ".eyotek_session.json"))
OUTPUT_FILE  = Path("profile_map.json")

# ── Güvenlik: Bu metinleri içeren butonlara hiç dokunma ────────────────────
FORBIDDEN_BTN_TEXTS = {
    "sil", "delete", "kaldır", "remove", "temizle", "clear",
    "güncelle", "update", "kaydet", "save",
    "sms gönder", "gönder", "send",
    "tümünü sil", "tümünü kaldır",
    "iptal et",   # "iptal" tek başına bazen filtre temizleme = OK değil
}


def is_safe_button(text: str) -> bool:
    t = text.lower().strip()
    return not any(f in t for f in FORBIDDEN_BTN_TEXTS)


# ════════════════════════════════════════════════════════════════════════════
# SESSION YÖNETİMİ
# ════════════════════════════════════════════════════════════════════════════

def load_saved_cookies() -> list[dict] | None:
    if SESSION_FILE.exists():
        try:
            data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return data
        except Exception:
            pass
    return None


def save_cookies(cookies: list[dict]) -> None:
    SESSION_FILE.write_text(
        json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.success(f"✅ Cookies kaydedildi ({len(cookies)} adet)")


def find_chrome() -> str | None:
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    return next((p for p in candidates if Path(p).exists()), None)


async def validate_and_refresh_session(page: Page, context) -> bool:
    """
    Chrome'daki mevcut oturumu doğrular.

    Strateji (önemli not):
      - Script asla login sayfasına YÖNLENDİRMEZ.
      - Oturum geçersizse kullanıcıdan Chrome'da MANUEL giriş yapmasını ister,
        sayfaya dokunmaz. Böylece Cloudflare Turnstile sorunu yaşanmaz.
      - Kayıtlı cookie'leri sessizce dener ama görünür bir Chrome açılışı yapmaz.

    Döner: True = oturum hazır
    """
    def is_authenticated(url: str) -> bool:
        return (
            "fermat.eyotek.com" in url
            and "/v1/" in url
            and "/Pages/" in url
            and "default.aspx" not in url
            and url.rstrip("/") != BASE_URL.rstrip("/")
        )

    # ── Adım 1: Mevcut browser session'ını sınaymadan test et ─────────────
    logger.info("🔐 Oturum doğrulanıyor → Staff/home")
    try:
        await page.goto(f"{BASE_URL}/Pages/Staff/home",
                        wait_until="domcontentloaded", timeout=10000)
        await asyncio.sleep(2)
    except Exception:
        await asyncio.sleep(2)

    if is_authenticated(page.url):
        logger.success(f"✅ Oturum aktif: {page.url}")
        all_c = await context.cookies()
        fresh = [c for c in all_c if "eyotek.com" in c.get("domain", "")]
        if fresh:
            save_cookies(fresh)
        return True

    # ── Adım 2: Kayıtlı cookie'leri sessizce dene ─────────────────────────
    saved = load_saved_cookies()
    if saved:
        logger.info(f"  Kayıtlı cookies deneniyor ({len(saved)} adet)...")
        await context.add_cookies(saved)
        try:
            await page.goto(f"{BASE_URL}/Pages/Staff/home",
                            wait_until="domcontentloaded", timeout=10000)
            await asyncio.sleep(2)
        except Exception:
            await asyncio.sleep(2)
        if is_authenticated(page.url):
            logger.success("✅ Kayıtlı cookies ile oturum açıldı.")
            return True

    # ── Adım 3: Manuel giriş — SAYFAYA DOKUNMADAN bekle ──────────────────
    #
    # ÖNEMLİ: Script burada Chrome'u login sayfasına YÖNLENDİRMİYOR.
    # Cloudflare Turnstile, CDP bağlantılı Chrome'da GİRİŞ butonunu
    # devre dışı bırakabiliyor. Bu yüzden kullanıcı KENDI açık Chrome
    # penceresinden giriş yapmalı.
    #
    logger.warning("⚠️  Eyotek oturumu açık değil veya süresi dolmuş.")
    print()
    print("=" * 65)
    print("🔐  MANUEL GİRİŞ GEREKİYOR")
    print()
    print("  1. Chrome'da  fermat.eyotek.com/v1  adresini açın")
    print("  2. Kullanıcı adı + şifreyi girin ve GİRİŞ'e tıklayın")
    print("  3. Ana sayfa/dashboard yüklendikten sonra buraya dönün")
    print("  4. ENTER'a basın — script otomatik devam eder")
    print()
    print("  (CDP portuna bağlı aynı Chrome penceresinde giriş yapın)")
    print("=" * 65)
    input("ENTER → ")

    # Giriş sonrası cookies'leri oku
    try:
        await page.goto(f"{BASE_URL}/Pages/Staff/home",
                        wait_until="domcontentloaded", timeout=10000)
        await asyncio.sleep(2)
    except Exception:
        await asyncio.sleep(2)

    all_c = await context.cookies()
    fresh = [c for c in all_c if "eyotek.com" in c.get("domain", "")]
    if fresh:
        save_cookies(fresh)

    if is_authenticated(page.url):
        logger.success("✅ Giriş başarılı. Cookies kaydedildi.")
        return True

    logger.error("❌ Giriş doğrulanamadı.")
    return False


# ════════════════════════════════════════════════════════════════════════════
# YARDIMCI FONKSİYONLAR
# ════════════════════════════════════════════════════════════════════════════

async def safe_goto(page: Page, url: str, wait: float = 2.5) -> bool:
    """Sayfaya git, hata alırsa False döndür."""
    try:
        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(wait)
        return True
    except Exception as e:
        logger.warning(f"  safe_goto hata: {e}")
        return False


async def click_ara(page: Page, timeout_ms: int = 8000) -> str | None:
    """
    Sayfadaki ARA butonunu tıkla (self-healing: birden fazla strateji).
    Güvenli butonlar listesinde ARA var, tıklanabilir.
    """
    # Strateji 1: text içeriğine göre
    result = await page.evaluate("""
        () => {
            const all = document.querySelectorAll(
                'a, button, input[type=button], input[type=submit]');
            for (const el of all) {
                const t = (el.innerText || el.value || '').toUpperCase().trim();
                if (t === 'ARA' && el.offsetParent !== null) {
                    el.click();
                    return 'click:' + el.tagName + ':' + t;
                }
            }
            return null;
        }
    """)
    if result:
        return result

    # Strateji 2: buton ikonları (fa-search içeren)
    result2 = await page.evaluate("""
        () => {
            const icons = document.querySelectorAll('.fa-search, [class*=search]');
            for (const ic of icons) {
                const btn = ic.closest('a,button');
                if (btn && btn.offsetParent !== null) {
                    btn.click();
                    return 'icon:search';
                }
            }
            return null;
        }
    """)
    return result2


async def wait_for_grid(page: Page, timeout_ms: int = 12000) -> bool:
    """DevExpress grid satırı çıkana kadar bekle."""
    try:
        await page.wait_for_selector("table tbody tr td", timeout=timeout_ms)
        return True
    except Exception:
        return False


async def get_all_selects(page: Page) -> list[dict]:
    """Sayfadaki tüm select'lerin ID + seçeneklerini döndür."""
    return await page.evaluate("""
        () => Array.from(document.querySelectorAll('select')).map(sel => ({
            id:   sel.id   || '',
            name: sel.name || '',
            label: (() => {
                const lbl = document.querySelector('label[for="' + sel.id + '"]');
                return lbl ? lbl.innerText.trim() : '';
            })(),
            options: Array.from(sel.options).map(o => ({
                value: o.value, text: o.text.trim()
            })).filter(o => o.text)
        }))
    """)


async def get_visible_buttons(page: Page) -> list[dict]:
    """Görünür tüm butonları döndür (güvenlik bilgisiyle birlikte)."""
    btns = await page.evaluate("""
        () => Array.from(document.querySelectorAll(
            'a, button, input[type=button], input[type=submit]'))
          .filter(el => el.offsetParent !== null)
          .map(el => ({
              text: (el.innerText || el.value || '').trim(),
              id:   el.id || '',
              cls:  el.className || '',
              href: el.href || ''
          }))
          .filter(el => el.text.length > 0 && el.text.length < 60)
    """)
    for b in btns:
        b["safe"] = is_safe_button(b["text"])
    return btns


async def get_tables(page: Page, max_rows: int = 5) -> list[dict]:
    return await page.evaluate(f"""
        () => Array.from(document.querySelectorAll('table')).map(tbl => ({{
            headers: Array.from(tbl.querySelectorAll(
                'th, tr.dxgvHeader td, tr:first-child td'))
                .map(h => h.innerText.trim()).filter(h => h && h !== '\\xa0'),
            rows: Array.from(tbl.querySelectorAll('tbody tr'))
                .slice(0, {max_rows})
                .map(r => Array.from(r.querySelectorAll('td'))
                    .map(td => td.innerText.trim()))
                .filter(r => r.some(c => c.length > 0))
        }})).filter(t => t.headers.length > 0 || t.rows.length > 0)
    """)


# ════════════════════════════════════════════════════════════════════════════
# KEŞİF FONKSİYONLARI
# ════════════════════════════════════════════════════════════════════════════

async def explore_student_ara_modal(page: Page, results: dict) -> None:
    """
    Öğrenci listesi sayfasındaki ARA modalını tam olarak haritala.
    Tüm select seçeneklerini (Sezon, Şube, Sınıf, Devre, Kur…) kaydet.
    """
    logger.info("=" * 60)
    logger.info("🔍 ARA MODAL HARİTALAMA — Pages/Student/student")

    if not await safe_goto(page, f"{BASE_URL}/Pages/Student/student", wait=3.0):
        results["ara_modal_error"] = "sayfa açılamadı"
        return

    if "student" not in page.url:
        results["ara_modal_error"] = f"yönlendirme: {page.url}"
        logger.error(f"  Yönlendirme: {page.url}")
        return

    # ARA butonuna tıkla → modal açılır
    ara_result = None
    for attempt in range(3):
        ara_result = await click_ara(page)
        if ara_result:
            break
        logger.info(f"  ARA denemesi {attempt+1}/3 — 2s bekleniyor...")
        await asyncio.sleep(2)

    logger.info(f"  ARA sonucu: {ara_result}")
    await asyncio.sleep(1.5)

    # Modalın açıldığını bekle — Eyotek custom popup (Bootstrap modal değil!)
    # Bilinen close button id: btnCloseSearchModal
    try:
        await page.wait_for_selector(
            "#btnCloseSearchModal, [id*=CloseSearch], [id*=SearchModal],"
            " #SearchModal, .popup-container, .search-popup",
            timeout=8000)
        logger.info("  ✅ Custom popup (btnCloseSearchModal) bulundu")
    except Exception:
        # Bootstrap modal'a da bak
        try:
            await page.wait_for_selector(".modal-content, .modal-body, [role=dialog]",
                                         timeout=3000)
        except Exception:
            pass

    # Modal HTML debug dump
    # Önce bilinen close button'dan parent'a doğru çıkarak gerçek konteyneri bul
    modal_html_debug = await page.evaluate("""
        () => {
            // Strateji 1: Bilinen close button'dan parent'a doğru yürü
            const closeBtn = document.querySelector(
                '#btnCloseSearchModal, [id*=CloseSearchModal], [id*=btnClose]');
            if (closeBtn) {
                let el = closeBtn.parentElement;
                const walked = [];
                while (el && !['BODY', 'HTML'].includes(el.tagName)) {
                    walked.push(el.tagName + '#' + (el.id||'') + '.' + (el.className||'').split(' ')[0]);
                    const selCount = el.querySelectorAll('select').length;
                    const inpCount = el.querySelectorAll('input:not([type=hidden])').length;
                    // Modal konteyneri: select veya input barındırıyor olmalı
                    if (selCount > 0 || inpCount > 1) {
                        return {
                            selector: 'walked_up_from_closeBtn',
                            walk_path: walked.join(' → '),
                            tag: el.tagName,
                            id: el.id || '',
                            cls: el.className || '',
                            select_count: selCount,
                            input_count: inpCount,
                            html: el.innerHTML.substring(0, 5000)
                        };
                    }
                    // En azından büyük bir div bulduk (height > 200 veya id içeriyor)
                    if (el.offsetHeight > 200 || el.id.toLowerCase().includes('search')) {
                        return {
                            selector: 'walked_up_large_div',
                            walk_path: walked.join(' → '),
                            tag: el.tagName,
                            id: el.id || '',
                            cls: el.className || '',
                            select_count: selCount,
                            input_count: inpCount,
                            html: el.innerHTML.substring(0, 5000)
                        };
                    }
                    el = el.parentElement;
                }
                // Close button bulundu ama container yürüme başarısız — son parent'ı ver
                return {
                    selector: 'walked_up_fallback',
                    walk_path: walked.join(' → '),
                    tag: '', id: '', cls: '',
                    html: closeBtn.closest('div,section,article')?.innerHTML?.substring(0,5000) || ''
                };
            }

            // Strateji 2: Standart Bootstrap selectors
            const bsSelectors = [
                '.modal-content', '.modal-body', '[role=dialog]',
                '.dxpc-mainDiv', '.dxpc-content',
            ];
            for (const sel of bsSelectors) {
                const el = document.querySelector(sel);
                if (el && el.offsetParent !== null) {
                    return { selector: sel, id: el.id||'', cls: el.className||'',
                             html: el.innerHTML.substring(0, 5000) };
                }
            }

            // Strateji 3: Görünür büyük div'ler (overlay/popup olabilir)
            const allDivs = Array.from(document.querySelectorAll('div, section'))
                .filter(el => el.offsetParent !== null && el.offsetHeight > 200
                    && el.querySelectorAll('select').length > 0);
            for (const d of allDivs) {
                return { selector: 'large_visible_div_with_selects',
                         id: d.id||'', cls: d.className||'',
                         html: d.innerHTML.substring(0, 5000) };
            }

            // Hiç modal yoksa tüm visible input'ları dök
            return {
                selector: 'MODAL_NOT_FOUND — full page dump',
                id: '',
                cls: '',
                html: document.body.innerHTML.substring(0, 2000)
            };
        }
    """)
    logger.info(f"  Modal debug → selector={modal_html_debug.get('selector')} "
                f"id={modal_html_debug.get('id')}")
    results["ara_modal_html_debug"] = modal_html_debug

    # Modal içindeki tüm inputları/select'leri al
    # — KURAL: Önce btnCloseSearchModal'dan parent yürüyüşü yap (gerçek konteyneri bul)
    # — Select2 / Bootstrap-Select özel widget'ları da yakala
    modal_inputs = await page.evaluate("""
        () => {
            // Modal/popup konteyneri bul
            let scope = null;

            // Öncelik 1: Bilinen close button'dan yukarı yürü
            const closeBtn = document.querySelector(
                '#btnCloseSearchModal, [id*=CloseSearchModal], [id*=btnCloseSearch]');
            if (closeBtn) {
                let el = closeBtn.parentElement;
                while (el && !['BODY', 'HTML'].includes(el.tagName)) {
                    if (el.querySelectorAll('select').length > 0
                        || el.querySelectorAll('input:not([type=hidden])').length > 1) {
                        scope = el; break;
                    }
                    // Büyük div → muhtemelen modal container
                    if (el.offsetHeight > 200 || el.id.toLowerCase().includes('search')
                        || el.id.toLowerCase().includes('modal')) {
                        scope = el; break;
                    }
                    el = el.parentElement;
                }
            }

            // Öncelik 2: Bootstrap modal selectors
            if (!scope) {
                for (const sel of ['.modal-content', '.modal-body', '[role=dialog]',
                                   '.dxpc-mainDiv', '.dxpc-content']) {
                    const el = document.querySelector(sel);
                    if (el) { scope = el; break; }
                }
            }

            // Öncelik 3: DevExpress popup
            if (!scope) {
                for (const p of document.querySelectorAll(
                    '[id*="PopupControl"], .dxpc-shadow, [class*=dxpc]')) {
                    if (p.style.visibility !== 'hidden' && p.style.display !== 'none') {
                        scope = p; break;
                    }
                }
            }

            const root = scope || document;

            const result = [];
            const seen = new Set();

            // 1) Native input / select / textarea (hidden dahil — Select2 gizler)
            root.querySelectorAll('input, select, textarea').forEach(el => {
                if (el.type === 'hidden' && el.tagName !== 'SELECT') return;
                const key = el.id || el.name || el.className;
                if (seen.has(key)) return;
                seen.add(key);
                const lbl = (el.id
                    ? document.querySelector('label[for="' + el.id + '"]')
                    : null)
                    || el.closest('.form-group, .control-group, tr')
                       ?.querySelector('label, th, .control-label');
                result.push({
                    type:    el.type || el.tagName.toLowerCase(),
                    id:      el.id   || '',
                    name:    el.name || '',
                    label:   lbl ? (lbl.innerText || lbl.textContent || '').trim() : '',
                    placeholder: el.placeholder || '',
                    visible: el.offsetParent !== null,
                    options: el.tagName === 'SELECT'
                        ? Array.from(el.options).map(o => ({
                            value: o.value, text: o.text.trim()
                          })).filter(o => o.text)
                        : []
                });
            });

            // 2) Select2 custom dropdown container'ları
            root.querySelectorAll(
                '.select2-container, [class*="select2-container"]')
              .forEach(el => {
                const forId = el.getAttribute('data-select2-id')
                           || el.id.replace(/^s2id_/, '');
                const orig = forId ? document.getElementById(forId) : null;
                const text = el.querySelector('.select2-selection__rendered,'+
                    '.select2-chosen')?.innerText?.trim() || '';
                const opts = orig
                    ? Array.from(orig.options).map(o => ({
                          value: o.value, text: o.text.trim()
                      })).filter(o => o.text)
                    : [];
                if (!seen.has('s2_' + (forId || el.id))) {
                    seen.add('s2_' + (forId || el.id));
                    const lbl = (forId
                        ? document.querySelector('label[for="' + forId + '"]')
                        : null)
                        || el.closest('.form-group, tr')
                           ?.querySelector('label, .control-label, th');
                    result.push({
                        type: 'select2',
                        id: forId || el.id || '',
                        name: '',
                        label: lbl ? (lbl.innerText||'').trim() : '',
                        placeholder: text,
                        visible: el.offsetParent !== null,
                        options: opts
                    });
                }
            });

            // 3) DevExpress ComboBox / TextBox editörleri
            root.querySelectorAll(
                '[id$="_DI"], [class*="dxeComboBoxSys"], [class*="dxeTextBoxSys"],'
                + '[id*="DdlSearch"], [id*="DdlAra"], [id*="LstSearch"]')
              .forEach(el => {
                if (seen.has('dx_' + el.id)) return;
                seen.add('dx_' + el.id);
                const lbl = document.querySelector('label[for="' + el.id + '"]')
                    || el.closest('tr')?.querySelector('td:first-child');
                result.push({
                    type: 'devexpress_' + (el.tagName.toLowerCase()),
                    id: el.id || '',
                    name: el.name || '',
                    label: lbl ? (lbl.innerText||'').trim() : '',
                    placeholder: el.placeholder || el.value || '',
                    visible: el.offsetParent !== null,
                    options: []
                });
            });

            return result;
        }
    """)

    logger.info(f"  Modal input sayısı: {len(modal_inputs)}")
    for inp in modal_inputs:
        opts = f" [{', '.join(o['text'] for o in inp['options'][:8])}]" \
               if inp["options"] else ""
        logger.info(f"    [{inp['id'] or inp['name']}] "
                    f"type={inp['type']} label='{inp['label']}'{opts}")

    # Modal butonları
    modal_btns = await page.evaluate("""
        () => {
            const modal = document.querySelector(
                '.modal-content, .modal-body, [role=dialog], .dxpc-mainDiv');
            const scope = modal || document;
            return Array.from(scope.querySelectorAll(
                'a, button, input[type=button], input[type=submit]'))
              .filter(el => el.offsetParent !== null || modal)
              .map(el => ({
                  text: (el.innerText || el.value || '').trim(),
                  id: el.id || ''
              })).filter(el => el.text.length > 0);
        }
    """)

    results["ara_modal"] = {
        "url": page.url,
        "ara_result": ara_result,
        "inputs": modal_inputs,
        "buttons": modal_btns,
    }
    logger.success(f"  ✅ ARA Modal haritası çıkarıldı — "
                   f"{len(modal_inputs)} input, {len(modal_btns)} buton")

    # Modal içinde ARA butonuna tıkla (tüm öğrencileri getir — filtre yok)
    # Strateji: modalı KAPATMADAN içindeki ARA/LİSTELE butonunu tıkla
    ara_in_modal = await page.evaluate("""
        () => {
            // Görünür modal/popup içinde ARA butonunu bul
            const containerSelectors = [
                '.modal-content', '.modal-body', '[role=dialog]',
                '.dxpc-mainDiv', '.dxpc-content',
            ];
            let scope = null;
            for (const sel of containerSelectors) {
                const el = document.querySelector(sel);
                if (el) { scope = el; break; }
            }
            if (!scope) {
                // DevExpress popup
                const dxPopups = Array.from(document.querySelectorAll('.dxpc-shadow'));
                for (const p of dxPopups) {
                    if (p.style.visibility !== 'hidden' && p.style.display !== 'none') {
                        scope = p; break;
                    }
                }
            }
            const root = scope || document;
            const btns = root.querySelectorAll(
                'a, button, input[type=button], input[type=submit]');
            for (const b of btns) {
                const t = (b.innerText || b.value || '').toUpperCase().trim();
                if (t === 'ARA' || t === 'LİSTELE' || t === 'LISTELE'
                    || t === 'SEARCH' || t === 'FILTRELE') {
                    b.click();
                    return 'clicked: ' + t + ' in ' + (scope ? scope.tagName : 'doc');
                }
            }
            // Fallback: tüm sayfada ARA butonunu bul
            for (const b of document.querySelectorAll(
                'a, button, input[type=button], input[type=submit]')) {
                const t = (b.innerText || b.value || '').toUpperCase().trim();
                if (t === 'ARA' && b.offsetParent !== null) {
                    b.click();
                    return 'fallback_click: ' + t;
                }
            }
            return null;
        }
    """)
    logger.info(f"  Modal içi ARA: {ara_in_modal}")
    # Grid yüklenene kadar bekle (uzun timeout — DevExpress grid yavaş olabilir)
    await asyncio.sleep(2)
    grid_loaded = await wait_for_grid(page, timeout_ms=15000)
    logger.info(f"  Grid yüklendi: {grid_loaded}")

    # Eğer modal kapanmadıysa ESC ile kapat
    await page.keyboard.press("Escape")
    await asyncio.sleep(1)

    # Son kontrol: grid hâlâ boşsa doğrudan student sayfasına gidip ARA
    row_count = await page.evaluate("""
        () => document.querySelectorAll('table tbody tr td').length
    """)
    logger.info(f"  Grid satır hücresi sayısı: {row_count}")

    if row_count == 0:
        logger.warning("  Grid boş — student sayfasına yeniden gidip ARA deneniyor...")
        await safe_goto(page, f"{BASE_URL}/Pages/Student/student", wait=2.0)
        await click_ara(page)
        await asyncio.sleep(1.5)
        # Modal açılırsa içindeki ARA'ya bas
        await page.evaluate("""
            () => {
                const btns = document.querySelectorAll(
                    '.modal-content a, .modal-body a, [role=dialog] a,'
                    + '.dxpc-mainDiv a, .modal-content button, .dxpc-mainDiv button');
                for (const b of btns) {
                    const t = (b.innerText || '').toUpperCase().trim();
                    if (t === 'ARA' || t === 'LİSTELE') { b.click(); return; }
                }
            }
        """)
        await asyncio.sleep(2)
        await wait_for_grid(page, timeout_ms=15000)


async def explore_student_context_menu(page: Page, results: dict) -> str | None:
    """
    Öğrenci listesindeki ilk satırın '...' (ellipsis) butonunu tıkla.
    Açılan bağlam menüsündeki tüm linkleri haritalandır.
    Returns: student-detail URL (St_Id ile)
    """
    logger.info("=" * 60)
    logger.info("📂 ÖĞRENCİ BAĞLAM MENÜSÜ KEŞFİ")

    # Önce listedeki satırları bul (retry ile)
    async def fetch_student_rows():
        return await page.evaluate("""
            () => {
                const rows = document.querySelectorAll('table tbody tr');
                const result = [];
                for (const row of rows) {
                    const cells = Array.from(row.querySelectorAll('td'))
                        .map(td => td.innerText.trim());
                    const nonEmpty = cells.filter(c => c.length > 0);
                    if (nonEmpty.length >= 3) {
                        result.push({
                            cells: cells.slice(0, 8),
                            hasDotBtn: !!row.querySelector(
                                'button, a.btn, [class*=ellipsis], [class*=more],'
                                + '[class*=btn-icon], [class*=dropdown]')
                        });
                    }
                }
                return result.slice(0, 5);
            }
        """)

    student_rows = await fetch_student_rows()
    logger.info(f"  Öğrenci satırları ({len(student_rows)}): "
                f"{[r['cells'][:4] for r in student_rows[:2]]}")

    # Grid boşsa: student sayfasına git, ARA → modal → ARA (3 deneme)
    if not student_rows:
        logger.warning("  Grid boş — student sayfasına gidip ARA denenecek...")
        for attempt in range(3):
            logger.info(f"  Deneme {attempt+1}/3...")
            if "student" not in page.url or attempt > 0:
                await safe_goto(page, f"{BASE_URL}/Pages/Student/student", wait=3.0)
            # Dış ARA → modal açar
            ara = await click_ara(page)
            logger.info(f"  ARA: {ara}")
            await asyncio.sleep(2)
            # Modal içi ARA → listeyi getir
            clicked_inner = await page.evaluate("""
                () => {
                    const containers = [
                        document.querySelector('.modal-content'),
                        document.querySelector('[role=dialog]'),
                        document.querySelector('.dxpc-mainDiv'),
                        document.querySelector('.dxpc-content'),
                    ].filter(Boolean);
                    for (const c of containers) {
                        for (const b of c.querySelectorAll(
                            'a, button, input[type=button], input[type=submit]')) {
                            const t = (b.innerText || b.value || '').toUpperCase().trim();
                            if (t === 'ARA' || t === 'LİSTELE' || t === 'LISTELE') {
                                b.click(); return 'inner:' + t;
                            }
                        }
                    }
                    // Modal yoksa direkt sayfadaki ilk ARA
                    for (const b of document.querySelectorAll(
                        'a, button, input[type=button], input[type=submit]')) {
                        const t = (b.innerText || b.value || '').toUpperCase().trim();
                        if (t === 'ARA' && b.offsetParent !== null) {
                            b.click(); return 'page:' + t;
                        }
                    }
                    return null;
                }
            """)
            logger.info(f"  İç ARA: {clicked_inner}")
            await asyncio.sleep(3)
            await wait_for_grid(page, timeout_ms=15000)
            await page.keyboard.press("Escape")
            await asyncio.sleep(1)
            student_rows = await fetch_student_rows()
            logger.info(f"  Deneme {attempt+1} sonuç: {len(student_rows)} satır")
            if student_rows:
                break

    logger.info(f"  Final öğrenci satırları ({len(student_rows)}): "
                f"{[r['cells'][:4] for r in student_rows[:2]]}")

    if not student_rows:
        logger.warning("  Liste hâlâ boş — sayfanın tüm butonları loglanıyor...")
        all_btns = await get_visible_buttons(page)
        logger.info(f"  Sayfadaki tüm butonlar: {[b['text'] for b in all_btns]}")
        # Sayfadaki tablo satırlarını da dök
        raw_rows = await page.evaluate("""
            () => Array.from(document.querySelectorAll('table tbody tr'))
                  .slice(0, 5)
                  .map(r => Array.from(r.querySelectorAll('td'))
                       .map(td => td.innerText.trim()).filter(Boolean))
        """)
        logger.info(f"  Ham tablo satırları: {raw_rows}")
        results["context_menu"] = {
            "error": "liste_bos",
            "page_url": page.url,
            "visible_buttons": all_btns,
            "raw_table_rows": raw_rows,
        }
        return None

    # Click öncesi: mevcut tüm görünür popup/dropdown'ları kaydet (karşılaştırma için)
    pre_click_menus = await page.evaluate("""
        () => Array.from(document.querySelectorAll(
            '.dropdown-menu, [class*=row-menu], [class*=custom-menu], [class*=action-menu]'))
          .filter(el => el.offsetParent !== null)
          .map(el => el.id || el.className || el.tagName)
    """)
    logger.info(f"  Click öncesi görünür menü sayısı: {len(pre_click_menus)}")

    # İlk satırdaki "..." butonuna tıkla — SADECE custom-row-menu-button ara
    clicked = await page.evaluate("""
        () => {
            const rows = document.querySelectorAll('table tbody tr');
            for (const row of rows) {
                const cells = Array.from(row.querySelectorAll('td'))
                    .map(td => td.innerText.trim());
                if (cells.filter(c => c.length > 0).length < 3) continue;

                // Öncelik 1: custom-row-menu-button (Eyotek özel sınıfı)
                const customBtn = row.querySelector('.custom-row-menu-button, [class*=custom-row]');
                if (customBtn && customBtn.offsetParent !== null) {
                    customBtn.click();
                    return { tag: customBtn.tagName, cls: customBtn.className,
                             text: customBtn.innerText.trim(), method: 'custom-row-menu-button',
                             row_cells: cells.slice(0,5) };
                }

                // Öncelik 2: metin içeriğine göre
                const byText = Array.from(row.querySelectorAll(
                    'a, button, span[role=button]'))
                    .find(el => {
                        const t = (el.innerText || el.title || el.textContent || '').trim();
                        return t === '...' || t === '⋮' || t === '…'
                            || t === 'İşlemler' || t.toLowerCase() === 'işlemler';
                    });
                if (byText && byText.offsetParent !== null) {
                    byText.click();
                    return { tag: byText.tagName, cls: byText.className,
                             text: byText.innerText.trim(), method: 'text',
                             row_cells: cells.slice(0,5) };
                }

                // Öncelik 3: class içeren butonlar (btn-icon hariç standart dropdown değil)
                const byCls = [
                    row.querySelector('[class*=ellipsis]'),
                    row.querySelector('[class*=btn-icon]'),
                    row.querySelector('[class*=action-btn]'),
                    row.querySelector('[data-toggle=dropdown]'),
                    row.querySelector('button:not(.btn-default)'),
                    row.querySelector('a.btn'),
                ];
                for (const el of byCls) {
                    if (el && el.offsetParent !== null) {
                        el.click();
                        return { tag: el.tagName, cls: el.className,
                                 text: el.innerText.trim(), method: 'class',
                                 row_cells: cells.slice(0,5) };
                    }
                }
            }
            return null;
        }
    """)
    logger.info(f"  Tıklanan buton: {clicked}")
    await asyncio.sleep(1.5)

    # Açılan popup'u yakala — ÖNCE satır-özel popup, sonra genel dropdown
    menu_links = await page.evaluate("""
        () => {
            // ── Öncelik 1: custom-row-menu (Eyotek özel — tıklanan butonun kardeşi) ──
            // custom-row-menu-button'ın parent'ındaki kardeş elementi ara
            const rowBtns = document.querySelectorAll('.custom-row-menu-button.active, .custom-row-menu-button[aria-expanded=true]');
            for (const btn of rowBtns) {
                // Kardeş veya parent içindeki liste
                const siblings = [
                    btn.nextElementSibling,
                    btn.parentElement?.querySelector('ul, [class*=menu], [class*=dropdown]'),
                    btn.closest('td')?.querySelector('ul, [class*=menu]'),
                    btn.closest('tr')?.querySelector('ul, [class*=menu]'),
                ];
                for (const sib of siblings) {
                    if (sib && sib !== btn && sib.offsetParent !== null) {
                        const links = Array.from(sib.querySelectorAll('a, li[onclick], button'))
                            .map(a => ({ text: (a.innerText||a.textContent||'').trim(),
                                         href: a.href || '', cls: a.className || '' }))
                            .filter(l => l.text.length > 0);
                        if (links.length > 0) return links;
                    }
                }
            }

            // ── Öncelik 2: Sayfaya yeni eklenen CUSTOM popup (click sonrası DOM değişimi) ──
            // 'custom-row-menu' sınıfını veya benzeri içeren görünür elementler
            for (const sel of [
                '[class*=custom-row-menu]:not(.custom-row-menu-button)',
                '[class*=row-menu]:not([class*=button])',
                '[class*=action-popup]', '[class*=student-menu]',
                '[class*=context-popup]',
            ]) {
                const menu = document.querySelector(sel);
                if (menu && menu.offsetParent !== null) {
                    const links = Array.from(menu.querySelectorAll('a, button, li'))
                        .map(a => ({ text: (a.innerText||'').trim(),
                                     href: a.href||'', cls: a.className||'' }))
                        .filter(l => l.text.length > 0);
                    if (links.length > 0) return links;
                }
            }

            // ── Öncelik 3: Bootstrap dropdown (SADECE student sayfası içinde) ──
            // Kullanıcı avatar dropdown'ını DİŞLAMA: Staff/internal-message vb. link içermemeli
            const menuSelectors = [
                '.dropdown-menu.open',
                '.dropdown-menu[style*="display: block"]',
                '.dropdown-menu[style*="display:block"]',
                '.open > .dropdown-menu',
                '.open .dropdown-menu',
            ];
            for (const sel of menuSelectors) {
                // 'a[href*="/Pages/"]' şeklindeki doğrudan link selectorlar
                if (sel.includes('[href')) {
                    const links = Array.from(document.querySelectorAll(sel));
                    if (links.length > 0) {
                        return links.map(a => ({
                            text: a.innerText.trim(),
                            href: a.href || '',
                            cls: a.className || ''
                        })).filter(l => l.text.length > 0);
                    }
                    continue;
                }
                const menu = document.querySelector(sel);
                if (menu && menu.offsetParent !== null) {
                    const links = Array.from(menu.querySelectorAll('a, button'))
                        .map(a => ({
                            text: a.innerText.trim(),
                            href: a.href || '',
                            cls: a.className || ''
                        })).filter(l => l.text.length > 0);
                    if (links.length > 0) return links;
                }
            }

            // Fallback: Bootstrap dropdown — kullanıcı nav dropdown'ını hariç tut
            // Kullanıcı nav dropdown'ı = Mesajlar, Ajanda, Profil Resmi, Şifre Değiştir
            const NAV_LINKS = ['mesajlar','ajanda','profil resmi','şifre değiştir',
                               'internal-message','change-password','staff/image','staff/agenda'];
            const isNavLink = (text, href) => NAV_LINKS.some(n =>
                text.toLowerCase().includes(n) || href.toLowerCase().includes(n));

            for (const m of document.querySelectorAll('.dropdown-menu')) {
                const items = Array.from(m.querySelectorAll('li a, a, button'))
                    .filter(el => el.offsetParent !== null);
                const links = items.map(a => ({
                    text: (a.innerText||'').trim(),
                    href: a.href||'', cls: a.className||''
                })).filter(l => l.text.length > 0 && !isNavLink(l.text, l.href));
                if (links.length > 0) return links;
            }

            // Son çare: Sayfadaki STUDENT ile ilgili tüm linkleri listele
            // student-detail veya öğrenci-specific sayfalara işaret eden
            const studentPaths = [
                'student-detail', 'counsellor-note', 'attendance', 'individual-lesson',
                'exam', 'communication', 'financial/student', 'etut'
            ];
            const studentLinks = Array.from(document.querySelectorAll('a[href*="/Pages/"]'))
                .filter(a => a.offsetParent !== null)
                .filter(a => studentPaths.some(p => a.href.includes(p)))
                .slice(0, 30)
                .map(a => ({ text: a.innerText.trim(), href: a.href,
                             cls: a.className, note: 'student_page_links' }));

            if (studentLinks.length > 0) return studentLinks;

            // Gerçek son çare: görünür tüm /Pages/ linkleri (debug için)
            return Array.from(document.querySelectorAll('a[href*="/Pages/"]'))
                .filter(a => a.offsetParent !== null && !isNavLink(a.innerText||'', a.href))
                .slice(0, 30)
                .map(a => ({ text: a.innerText.trim(), href: a.href,
                             cls: a.className, note: 'fallback_all_pages_links' }));
        }
    """)

    # Eğer hiç student-related link yoksa DOM'un popup durumunu debug et
    has_student_link = any(
        p in lnk.get("href","") for lnk in menu_links
        for p in ("student-detail","counsellor","attendance","individual","exam","etut")
    )
    if not has_student_link:
        popup_debug = await page.evaluate("""
            () => {
                // Sayfadaki tüm görünür popup/menu elementlerini listele
                const els = Array.from(document.querySelectorAll(
                    '[class*=menu], [class*=popup], [class*=dropdown], [class*=row]'))
                  .filter(el => el.offsetParent !== null && el !== document.body)
                  .map(el => ({
                    tag: el.tagName, id: el.id||'', cls: el.className||'',
                    text: el.innerText?.substring(0,100)||'',
                    html: el.outerHTML?.substring(0,300)||''
                  }));
                return els.slice(0, 20);
            }
        """)
        logger.warning(f"  ⚠️  Student link yok — DOM popup debug ({len(popup_debug)}):")
        for pe in popup_debug[:10]:
            logger.info(f"    [{pe['tag']}#{pe['id']}.{pe['cls'][:40]}] {pe['text'][:80]!r}")

    logger.info(f"  Bağlam menü linkleri ({len(menu_links)}):")
    for lnk in menu_links:
        logger.info(f"    {lnk['text']!r:25s}  →  {lnk['href'][:80]}")

    # Context menu linklerinden PostBack formatını tespit et
    # Örnek: javascript:__doPostBack('GridView1$ctl02$btnGenel','')
    postback_map = {}
    for lnk in menu_links:
        m = re.search(r"__doPostBack\('([^']+)','([^']*)'\)", lnk["href"])
        if m:
            postback_map[lnk["text"]] = {
                "target": m.group(1), "arg": m.group(2),
                "href": lnk["href"]
            }

    logger.info(f"  PostBack map ({len(postback_map)} adet):"
                f" {list(postback_map.keys())[:10]}")

    # GridView1$ctlXX$btnGenel formatından satır indeksini çıkar
    row_index = None
    genel_pb = postback_map.get("Genel Bilgiler")
    if genel_pb:
        m2 = re.search(r"GridView1\$(ctl\d+)\$", genel_pb["target"])
        if m2:
            row_index = m2.group(1)
            logger.info(f"  Satır indeksi: {row_index}")

    # St_Id'yi almak için Genel Bilgiler PostBack'ini çalıştır
    # → sayfa student-detail?St_Id=... adresine gider
    st_id = None
    detail_url = None

    if genel_pb:
        logger.info(f"  📖 Genel Bilgiler PostBack çalıştırılıyor: {genel_pb['target']}")
        try:
            # Escape ile önce menüyü kapat
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.3)
            # PostBack'i çalıştır
            await page.evaluate(
                f"__doPostBack('{genel_pb['target']}', '{genel_pb['arg']}')")
            await asyncio.sleep(3)
            current_url = page.url
            logger.info(f"  PostBack sonrası URL: {current_url}")

            if "student-detail" in current_url:
                detail_url = current_url
                m3 = re.search(r"St_Id=([^&]+)", current_url)
                if m3:
                    st_id = m3.group(1)
                    logger.success(f"  ✅ St_Id bulundu (PostBack): {st_id[:30]}...")
            else:
                # URL beklenmedik — sayfanın URL'ini kontrol et
                logger.warning(f"  Beklenen student-detail değil: {current_url}")
                # Sayfa başlığı veya içeriğinden St_Id almayı dene
                st_id_from_page = await page.evaluate("""
                    () => {
                        // URL parametresi
                        const p = new URLSearchParams(window.location.search);
                        if (p.has('St_Id')) return p.get('St_Id');
                        // Hidden field
                        const hid = document.querySelector(
                            'input[name*="StId"], input[name*="St_Id"],'
                            + 'input[id*="StId"], input[id*="hdnStudentId"]');
                        return hid ? hid.value : null;
                    }
                """)
                if st_id_from_page:
                    st_id = st_id_from_page
                    detail_url = page.url
                    logger.success(f"  ✅ St_Id (hidden field): {st_id[:30]}...")
        except Exception as e:
            logger.warning(f"  PostBack hatası: {e}")
            await asyncio.sleep(1)
    else:
        # PostBack yoksa fallback: doğrudan URL içinde St_Id ara
        for lnk in menu_links:
            if "student-detail" in lnk.get("href","") or "St_Id" in lnk.get("href",""):
                detail_url = lnk["href"]
                m4 = re.search(r"St_Id=([^&]+)", detail_url)
                if m4:
                    st_id = m4.group(1)
                break

    results["context_menu"] = {
        "clicked_btn": clicked,
        "menu_links": menu_links,
        "postback_map": postback_map,
        "row_index": row_index,
        "detail_url": detail_url,
        "st_id": st_id,
    }

    if not detail_url:
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.5)

    return detail_url


async def _reload_student_list_grid(page: Page) -> bool:
    """
    Öğrenci listesi sayfasına gidip ızgarayı yükler.
    Döner: True = grid yüklendi, False = başarısız.
    """
    if "Pages/Student/student" not in page.url or "student-detail" in page.url:
        if not await safe_goto(page,
                               f"{BASE_URL}/Pages/Student/student", wait=2.0):
            return False

    # ARA butonuna tıkla
    await click_ara(page)
    await asyncio.sleep(1.2)

    # Modal içindeki ARA'ya tıkla (closeBtn walk-up stratejisi)
    await page.evaluate("""
        () => {
            const closeBtn = document.querySelector(
                '#btnCloseSearchModal, [id*=CloseSearchModal]');
            if (closeBtn) {
                let el = closeBtn.parentElement;
                while (el && !['BODY','HTML'].includes(el.tagName)) {
                    for (const btn of el.querySelectorAll(
                            'a, button, input[type=submit]')) {
                        const t = (btn.innerText||btn.value||'').toUpperCase().trim();
                        if (t === 'ARA') { btn.click(); return 'modal_ara'; }
                    }
                    if (el.querySelectorAll('select').length > 0) break;
                    el = el.parentElement;
                }
            }
            // Fallback: görünür ARA butonu
            for (const b of document.querySelectorAll(
                    'a, button, input[type=submit]')) {
                const t = (b.innerText||b.value||'').toUpperCase().trim();
                if (t === 'ARA' && b.offsetParent !== null) {
                    b.click(); return 'fallback_ara';
                }
            }
        }
    """)
    await asyncio.sleep(2)
    await wait_for_grid(page, timeout_ms=12000)
    await page.keyboard.press("Escape")
    await asyncio.sleep(0.8)

    # Grid dolu mu kontrol et
    row_count = await page.evaluate("""
        () => document.querySelectorAll('table tbody tr td').length
    """)
    return row_count > 0


async def _execute_context_postback_and_get_url(
        page: Page, postback_target: str, postback_arg: str = "") -> str | None:
    """
    İlk öğrenci satırındaki '...' menüsünü açmadan doğrudan PostBack çalıştırır.
    Grid yüklü olduğu varsayılır.
    Döner: yönlendirilen URL (varsa) veya None.
    """
    try:
        await page.evaluate(
            f"__doPostBack('{postback_target}', '{postback_arg}')")
        await asyncio.sleep(3.0)
        return page.url
    except Exception as e:
        logger.warning(f"  PostBack hatası ({postback_target}): {e}")
        return None


async def discover_section_urls_via_postback(
        page: Page, results: dict) -> dict[str, str]:
    """
    context_menu PostBack haritasını kullanarak önemli bölüm URL'lerini keşfeder.
    Her PostBack için:
      1. Öğrenci listesine git + grid yükle
      2. PostBack çalıştır
      3. Sonuç URL'ini kaydet

    Döner: {bölüm_adı: url}
    """
    postback_map: dict = (results.get("context_menu") or {}).get(
        "postback_map", {})
    if not postback_map:
        logger.warning("  PostBack haritası yok — bölüm URL keşfi atlandı")
        return {}

    # Eyotek'te önemli olan öğrenci bölümleri (ilk 8)
    KEY_SECTIONS = [
        "Özel Bilgiler",
        "Yoklama",
        "Etüt",
        "Rehberlik Notu",
        "Sınav",
        "Ödev",
        "Ders Programı",
        "Ödeme",
    ]

    section_urls: dict[str, str] = {}

    for section_name in KEY_SECTIONS:
        pb = postback_map.get(section_name)
        if not pb:
            logger.info(f"  [{section_name}] PostBack yok — atlandı")
            continue

        logger.info(f"  ▶ Bölüm keşfi: {section_name!r} → {pb['target']}")

        # Grid'i yükle
        ok = await _reload_student_list_grid(page)
        if not ok:
            logger.warning(f"  [{section_name}] Grid yüklenemedi — atlandı")
            continue

        # PostBack çalıştır
        dest_url = await _execute_context_postback_and_get_url(
            page, pb["target"], pb.get("arg", ""))

        if dest_url and "eyotek.com" in dest_url:
            section_urls[section_name] = dest_url
            logger.success(
                f"  ✅ {section_name!r} → {dest_url.split('?')[0].split('/')[-1]}"
                f"  (St_Id={'✓' if 'St_Id' in dest_url else '✗'})")
        else:
            logger.warning(f"  [{section_name}] Beklenmedik URL: {dest_url}")

    return section_urls


async def explore_student_detail_tabs(page: Page, results: dict,
                                      detail_url: str) -> None:
    """
    Öğrenci bölüm sayfalarını üç aşamalı stratejiyle keşfeder.

    Strateji 1 (hızlı): student-detail sayfasında St_Id taşıyan bağlantılar.
    Strateji 2 (güvenilir): context_menu PostBack haritasından bölüm URL keşfi.
    Strateji 3 (fallback): site_map'ten bilinen yollar + St_Id parametresi.
    """
    logger.info("=" * 60)
    logger.info("👤 ÖĞRENCİ DETAY SAYFALARI KEŞFİ")
    logger.info(f"   URL: {detail_url[:80]}")

    # student-detail sayfasına git (henüz orada değilsek)
    if "student-detail" not in page.url:
        if not await safe_goto(page, detail_url, wait=3.0):
            results["student_detail_error"] = "sayfa açılamadı"
            return

    actual_url = page.url
    logger.info(f"  Gerçek URL: {actual_url}")

    # St_Id'yi URL'den çıkar
    m_st = re.search(r"St_Id=([^&\s]+)", actual_url)
    st_id = m_st.group(1) if m_st else None
    logger.info(f"  St_Id: {st_id[:30] if st_id else 'bulunamadı'}...")

    # ── Temel sayfa yapısı (Genel Bilgiler) ────────────────────────────────
    label_values = await page.evaluate("""
        () => {
            const result = {};
            document.querySelectorAll('input[type=text], input[type=email]')
                .forEach(inp => {
                    const lbl = document.querySelector(
                        'label[for="' + inp.id + '"]');
                    if (lbl && inp.value)
                        result[lbl.innerText.trim()] = inp.value;
                });
            document.querySelectorAll('.control-label, td.label, th')
                .forEach(lbl => {
                    const sib = lbl.nextElementSibling
                              || lbl.parentElement?.nextElementSibling;
                    if (sib) {
                        const v = sib.innerText.trim();
                        if (v && v.length < 100)
                            result[lbl.innerText.trim()] = v;
                    }
                });
            return result;
        }
    """)
    logger.info(f"  Label-value çiftleri ({len(label_values)}): "
                f"{list(label_values.keys())[:10]}")

    page_struct = {
        "url":     actual_url,
        "title":   await page.title(),
        "selects": await get_all_selects(page),
        "buttons": await get_visible_buttons(page),
        "tables":  await get_tables(page, max_rows=3),
    }

    # ── STRATEJİ 1: Sayfadaki St_Id bağlantıları ──────────────────────────
    tab_links: list[dict] = []
    if st_id:
        # st_id Playwright arg olarak geçirilir — JS içine güvensiz interpolasyon yok
        st_id_links = await page.evaluate("""
            (stId) => {
                const stIdEnc = encodeURIComponent(stId);
                const currentHref = location.href;
                const links = [];
                const seen = new Set([currentHref]);

                document.querySelectorAll('a[href]').forEach(a => {
                    const rawHref  = a.getAttribute('href') || '';
                    const absHref  = a.href;
                    const text     = (a.innerText || '').trim()
                                       .replace(/\\s+/g,' ');
                    if (!text || seen.has(absHref)) return;
                    // St_Id içermeli ve farklı bir sayfaya gitmiş olmalı
                    const hasStId = rawHref.includes(stId)
                                 || rawHref.includes(stIdEnc);
                    if (hasStId) {
                        seen.add(absHref);
                        links.push({
                            text, href: absHref,
                            samePath: absHref.split('?')[0] ===
                                      currentHref.split('?')[0],
                            strategy: 'stId_link'
                        });
                    }
                });
                return links;
            }
        """, st_id)
        # Farklı sayfa URL'lerine işaret eden linkleri önceliklendir
        diff_page = [l for l in st_id_links if not l.get("samePath")]
        all_st_links = diff_page or st_id_links
        logger.info(f"  St_Id link stratejisi: toplam={len(st_id_links)} "
                    f"farklı_sayfa={len(diff_page)}")
        if all_st_links:
            tab_links = all_st_links
            logger.info(f"  Strateji 1 kullanılıyor: "
                        f"{[l['text'] for l in tab_links[:8]]}")

    # ── STRATEJİ 2: PostBack haritasından bölüm URL keşfi ─────────────────
    section_urls: dict[str, str] = {}
    if not tab_links:
        logger.info("  Strateji 1 başarısız → Strateji 2: PostBack URL keşfi")
        section_urls = await discover_section_urls_via_postback(page, results)

        # Her keşfedilen URL'i sekme olarak ekle
        for s_name, s_url in section_urls.items():
            tab_links.append({"text": s_name, "href": s_url,
                               "strategy": "postback"})

        # student-detail sayfasına geri dön
        if "student-detail" not in page.url:
            await safe_goto(page, detail_url, wait=3.0)
            await asyncio.sleep(1.0)

    # ── STRATEJİ 3: Bilinen yollar + St_Id parametresi ────────────────────
    if not tab_links and st_id:
        logger.info("  Strateji 2 başarısız → Strateji 3: Bilinen yollar")
        KNOWN_SECTIONS = [
            ("Yoklama",        "attendance-check-multi"),
            ("Etüt",           "individual-lesson"),
            ("Rehberlik Notu", "counsellor-note-list"),
            ("Sınav",          "exam"),
            ("Ödev",           "homework-assignment"),
            ("Ders Programı",  "timetable-class-list"),
            ("Ödeme",          "financial-service-type-list"),
            ("Boy & Kilo",     "height-weight-clothing-size-list"),
        ]
        from urllib.parse import quote
        st_id_enc = quote(st_id, safe="")
        for s_name, s_path in KNOWN_SECTIONS:
            candidate = (f"{BASE_URL}/Pages/Student/{s_path}"
                         f"?St_Id={st_id_enc}")
            tab_links.append({"text": s_name, "href": candidate,
                               "strategy": "known_path"})
        logger.info(f"  Strateji 3: {len(tab_links)} bilinen yol eklendi")

    logger.info(f"  Toplam keşfedilecek sekme: {len(tab_links)} "
                f"— {[t['text'] for t in tab_links[:12]]}")

    # ── Her sekmeye git ve yapısını al ────────────────────────────────────
    tab_details: dict[str, dict] = {}

    # Önce Genel Bilgiler'i (mevcut sayfa) kaydet
    genel_struct = {
        "url":               actual_url,
        "title":             page_struct["title"],
        "selects":           page_struct["selects"],
        "buttons":           [b for b in page_struct["buttons"] if b["safe"]],
        "forbidden_buttons": [b for b in page_struct["buttons"]
                              if not b["safe"]],
        "tables":            page_struct["tables"],
        "label_values":      label_values,
    }
    tab_details["Genel Bilgiler"] = genel_struct

    for tab in tab_links[:20]:
        tab_name = tab["text"].strip()
        tab_href = tab["href"]
        if not tab_name or not tab_href:
            continue
        if tab_name == "Genel Bilgiler":
            continue  # Zaten yukarıda eklendi

        logger.info(f"  📑 Sekme: {tab_name!r} → "
                    f"{tab_href.split('/')[-1][:60]}")
        try:
            if not await safe_goto(page, tab_href, wait=2.5):
                tab_details[tab_name] = {"error": "sayfa açılamadı",
                                         "href": tab_href}
                continue

            all_btns = await get_visible_buttons(page)
            tab_struct = {
                "url":               page.url,
                "title":             await page.title(),
                "selects":           await get_all_selects(page),
                "buttons":           [b for b in all_btns if b["safe"]],
                "forbidden_buttons": [b for b in all_btns if not b["safe"]],
                "tables":            await get_tables(page, max_rows=5),
                "strategy":          tab.get("strategy", ""),
            }
            logger.info(f"     selects={len(tab_struct['selects'])} "
                        f"tables={len(tab_struct['tables'])} "
                        f"title={tab_struct['title'][-40:]!r}")
            tab_details[tab_name] = tab_struct
        except Exception as e:
            logger.warning(f"  Sekme hatası ({tab_name}): {e}")
            tab_details[tab_name] = {"error": str(e)}

    results["student_detail"] = {
        "base_url":     actual_url,
        "st_id":        st_id,
        "label_values": label_values,
        "section_urls": section_urls,
        "page_structure": page_struct,
        "tab_details":  tab_details,
    }
    logger.success(f"  ✅ Öğrenci detay keşfi tamamlandı: "
                   f"{len(tab_details)} sekme")


async def explore_attendance_form(page: Page, results: dict) -> None:
    """Yoklama giriş formu — sınıf seç → checkbox yapısını keşfet."""
    logger.info("=" * 60)
    logger.info("✅ YOKLAMA GİRİŞ KEŞFİ — attendance-check-multi")

    if not await safe_goto(page, f"{BASE_URL}/Pages/Student/attendance-check-multi",
                           wait=2.5):
        results["attendance_input"] = {"error": "sayfa açılamadı"}
        return

    # Yoklama sayfasının tüm butonlarını gör — ARA gerekli mi?
    page_btns = await get_visible_buttons(page)
    logger.info(f"  Sayfa butonları: {[b['text'] for b in page_btns[:15]]}")

    # ARA butonu varsa tıkla (sınıf listesi ARA modalının arkasında olabilir)
    if any(b["text"].upper() == "ARA" for b in page_btns):
        ara_r = await click_ara(page)
        logger.info(f"  Yoklama ARA: {ara_r}")
        await asyncio.sleep(1.5)
        # Custom popup veya modal
        ara_in_modal = await page.evaluate("""
            () => {
                const closeBtns = document.querySelectorAll(
                    '[id*=CloseSearch], #btnCloseSearchModal, [id*=btnClose]');
                for (const cb of closeBtns) {
                    const container = cb.closest('div,section,form');
                    if (!container) continue;
                    for (const b of container.querySelectorAll(
                        'a, button, input[type=submit]')) {
                        const t = (b.innerText||b.value||'').toUpperCase().trim();
                        if (t === 'ARA' || t === 'LİSTELE') { b.click(); return t; }
                    }
                }
                // Modal yoksa sayfa genelinde ARA
                for (const b of document.querySelectorAll(
                    'a, button, input[type=submit]')) {
                    const t = (b.innerText||b.value||'').toUpperCase().trim();
                    if (t === 'ARA' && b.offsetParent !== null) {
                        b.click(); return 'fallback:' + t;
                    }
                }
                return null;
            }
        """)
        logger.info(f"  Modal içi ARA: {ara_in_modal}")
        await asyncio.sleep(3)
        await wait_for_grid(page, timeout_ms=12000)
        await page.keyboard.press("Escape")
        await asyncio.sleep(1)

    # Sınıf listesi
    class_rows = await page.evaluate("""
        () => Array.from(document.querySelectorAll('table tbody tr')).map(row => ({
            cells: Array.from(row.querySelectorAll('td')).map(td => td.innerText.trim()),
            links: Array.from(row.querySelectorAll('a')).map(a => ({
                text: a.innerText.trim(), href: a.href
            }))
        })).filter(r => r.links.length > 0 || r.cells.some(c => c.length > 1))
    """)
    logger.info(f"  Sınıf satırları ({len(class_rows)}): "
                f"{[r['cells'][:3] for r in class_rows[:3]]}")

    # İlk sınıfı seç (PostBack)
    attendance_form = None
    first_link = None
    if class_rows:
        for row in class_rows:
            if row["links"]:
                first_link = row["links"][0]["href"]
                break

    if first_link:
        logger.info(f"  ➡  Sınıf tıklanıyor: {first_link[:70]}")
        if "__doPostBack" in first_link or first_link.startswith("javascript:"):
            m = re.search(r"__doPostBack\('([^']+)','([^']*)'\)", first_link)
            if m:
                await page.evaluate(f"__doPostBack('{m.group(1)}', '{m.group(2)}')")
            else:
                await page.evaluate("""
                    () => {
                        const links = document.querySelectorAll('table tbody tr td a');
                        if (links.length) links[0].click();
                    }
                """)
        else:
            await safe_goto(page, first_link, wait=2.5)
        await asyncio.sleep(3)

        # Yoklama formunun yapısı
        attendance_form = {
            "url": page.url,
            "selects": await get_all_selects(page),
            "tables":  await get_tables(page, max_rows=10),
            "buttons": await get_visible_buttons(page),
        }
        # Checkbox'ları say (yoklama işaretleri)
        checkbox_count = await page.evaluate("""
            () => document.querySelectorAll('input[type=checkbox]').length
        """)
        attendance_form["checkbox_count"] = checkbox_count
        logger.info(f"  Yoklama URL: {page.url}")
        logger.info(f"  Checkbox: {checkbox_count}, "
                    f"Tablo: {len(attendance_form['tables'])}")

    results["attendance_input"] = {
        "url": f"{BASE_URL}/Pages/Student/attendance-check-multi",
        "class_rows": class_rows[:10],
        "first_class_url": first_link,
        "form_after_class_select": attendance_form,
    }
    logger.success("  ✅ Yoklama keşfi tamamlandı.")


async def explore_counsellor_note(page: Page, results: dict) -> None:
    """Rehberlik notu listesi — öğrencinin '...' menüsünden notu aç."""
    logger.info("=" * 60)
    logger.info("💬 REHBERLİK NOTU KEŞFİ")

    if not await safe_goto(page, f"{BASE_URL}/Pages/Student/counsellor-note-list",
                           wait=2.5):
        results["counsellor_note"] = {"error": "sayfa açılamadı"}
        return

    # ARA → öğrenci listesi yükle
    ara = await click_ara(page)
    logger.info(f"  ARA: {ara}")
    await asyncio.sleep(3)
    await wait_for_grid(page)

    tables = await get_tables(page, max_rows=5)
    buttons = await get_visible_buttons(page)
    logger.info(f"  Tablolar: {[(t['headers'][:3], t['rows']) for t in tables[:2]]}")
    logger.info(f"  Butonlar: {[b['text'] for b in buttons[:10]]}")

    # '...' veya satır linklerine bak
    row_links = await page.evaluate("""
        () => {
            const rows = document.querySelectorAll('table tbody tr');
            for (const row of rows) {
                const cells = Array.from(row.querySelectorAll('td'))
                    .map(td => td.innerText.trim());
                if (cells.filter(c => c.length > 0).length < 2) continue;
                const links = Array.from(row.querySelectorAll('a')).map(a => ({
                    text: a.innerText.trim(),
                    href: a.href || ''
                }));
                if (links.length > 0) return { cells, links };
            }
            return null;
        }
    """)
    logger.info(f"  İlk satır linkleri: {row_links}")

    # EKLE butonunu haritala (tıklamıyoruz — güvenlik)
    ekle_info = await page.evaluate("""
        () => {
            const btns = document.querySelectorAll('a, button, input[type=button]');
            for (const b of btns) {
                const t = (b.innerText || b.value || '').trim().toUpperCase();
                if (t === 'EKLE' || t.includes('YENİ NOT') || t === 'NOT EKLE') {
                    return {
                        text: (b.innerText || b.value || '').trim(),
                        id: b.id || '', cls: b.className,
                        href: b.href || '',
                        onclick: b.getAttribute('onclick') || ''
                    };
                }
            }
            return null;
        }
    """)
    logger.info(f"  EKLE butonu (haritalandı, tıklanmadı): {ekle_info}")

    results["counsellor_note"] = {
        "url": page.url,
        "tables": tables,
        "buttons": [b for b in buttons if b["safe"]],
        "forbidden_buttons": [b for b in buttons if not b["safe"]],
        "ekle_button_map": ekle_info,
        "first_row_links": row_links,
    }
    logger.success("  ✅ Rehberlik notu keşfi tamamlandı.")


async def explore_counsellor_note_form(
        page: Page, results: dict, st_id: str) -> None:
    """
    Keşfedilen gerçek URL'de Rehberlik Notu EKLE formunu haritalandır.

    student-counsellor-note?ST_Id=... adresine gidip btnAddNote'a tıklar,
    açılan paneldeki tüm form elemanlarının ID ve seçeneklerini kaydeder.
    Bu sayede write_counsellor_note() içindeki textarea ID bilinecek.
    """
    logger.info("=" * 60)
    logger.info("💬 REHBERLİK NOTU FORM KEŞFİ (student-counsellor-note)")

    if not st_id:
        logger.warning("  St_Id yok — form keşfi atlandı.")
        results["counsellor_note_form"] = {"error": "st_id bilinmiyor"}
        return

    from urllib.parse import quote as _quote
    url = (f"{BASE_URL}/Pages/Student/student-counsellor-note"
           f"?ST_Id={_quote(st_id, safe='')}")
    logger.info(f"  URL: {url.split('?')[0].split('/')[-1]}?ST_Id=…")

    if not await safe_goto(page, url, wait=3.0):
        results["counsellor_note_form"] = {"error": "sayfa açılamadı"}
        return

    # Sayfa durumunu kaydet (EKLE öncesi)
    before_selects  = await get_all_selects(page)
    before_textareas = await page.evaluate("""
        () => Array.from(document.querySelectorAll(
                'textarea, [contenteditable="true"]'))
             .map(el => ({
                 id: el.id || '', cls: el.className.slice(0,40),
                 tagName: el.tagName, visible: el.offsetParent !== null,
                 placeholder: el.getAttribute('placeholder') || ''
             }))
    """)
    before_inputs = await page.evaluate("""
        () => Array.from(document.querySelectorAll('input[type=text]'))
             .filter(el => el.offsetParent !== null && !el.readOnly)
             .map(el => ({id: el.id, name: el.name, placeholder: el.placeholder}))
    """)
    logger.info(f"  EKLE öncesi — selects:{len(before_selects)} "
                f"textareas:{len(before_textareas)} inputs:{len(before_inputs)}")

    # btnAddNote'a tıkla
    clicked = await page.evaluate("""
        () => {
            const byId = document.getElementById('btnAddNote');
            if (byId) { byId.click(); return 'btnAddNote'; }
            for (const b of document.querySelectorAll(
                    'a, button, input[type=button]')) {
                const t = (b.innerText || b.value || '').trim().toUpperCase();
                if ((t === 'EKLE' || t === 'NOT EKLE' || t.includes('YENİ NOT'))
                    && b.offsetParent !== null) {
                    b.click(); return b.id || b.className || t;
                }
            }
            return null;
        }
    """)
    logger.info(f"  EKLE tıklandı: {clicked}")

    if not clicked:
        results["counsellor_note_form"] = {
            "url": url, "error": "btnAddNote bulunamadı",
            "before_selects": before_selects,
        }
        return

    await asyncio.sleep(2.5)  # panel / modal animasyonu bekle

    # EKLE sonrası form elemanları
    after_selects  = await get_all_selects(page)
    after_textareas = await page.evaluate("""
        () => Array.from(document.querySelectorAll(
                'textarea, [contenteditable="true"]'))
             .map(el => ({
                 id: el.id || '', name: el.getAttribute('name') || '',
                 cls: el.className.slice(0,60), tagName: el.tagName,
                 visible: el.offsetParent !== null,
                 placeholder: el.getAttribute('placeholder') || '',
                 value: (el.value || el.innerText || '').slice(0, 50)
             }))
    """)
    after_inputs = await page.evaluate("""
        () => Array.from(document.querySelectorAll('input[type=text]'))
             .filter(el => el.offsetParent !== null && !el.readOnly)
             .map(el => ({id: el.id, name: el.name, placeholder: el.placeholder,
                          cls: el.className.slice(0,40)}))
    """)
    after_buttons = await get_visible_buttons(page)

    # Yeni eklenenler (önceden yoktu)
    before_select_ids = {s["id"] for s in before_selects}
    new_selects = [s for s in after_selects if s["id"] not in before_select_ids]

    before_ta_ids = {t["id"] for t in before_textareas}
    new_textareas = [t for t in after_textareas if t["id"] not in before_ta_ids]
    visible_textareas = [t for t in after_textareas if t["visible"]]

    before_inp_ids = {i["id"] for i in before_inputs}
    new_inputs = [i for i in after_inputs if i["id"] not in before_inp_ids]

    logger.info(f"  EKLE sonrası — selects:{len(after_selects)} "
                f"textareas:{len(after_textareas)} inputs:{len(after_inputs)}")
    logger.info(f"  YENİ selects  : {[s['id'] for s in new_selects]}")
    logger.info(f"  YENİ textareas: {[t['id'] for t in new_textareas]}")
    logger.info(f"  Görünür textarea: {[t['id'] for t in visible_textareas]}")
    logger.info(f"  YENİ inputs   : {[i['id'] for i in new_inputs]}")
    logger.info(f"  Tüm butonlar  : {[b['text'] for b in after_buttons[:15]]}")

    results["counsellor_note_form"] = {
        "url": url,
        "ekle_clicked": clicked,
        "before": {
            "selects":   before_selects,
            "textareas": before_textareas,
            "inputs":    before_inputs,
        },
        "after": {
            "selects":   after_selects,
            "textareas": after_textareas,
            "inputs":    after_inputs,
            "buttons":   [b for b in after_buttons if b["safe"]],
        },
        "new_selects":   new_selects,
        "new_textareas": new_textareas,
        "new_inputs":    new_inputs,
        "visible_textareas": visible_textareas,
    }
    logger.success("  ✅ Rehberlik notu form keşfi tamamlandı.")


async def explore_etut_input(page: Page, results: dict) -> None:
    """Etüt giriş formu — tüm select ID'leri ve seçenekleri."""
    logger.info("=" * 60)
    logger.info("📝 ETÜT GİRİŞ KEŞFİ")

    if not await safe_goto(page,
                           f"{BASE_URL}/Pages/Student/individual-lesson-input",
                           wait=2.5):
        results["etut_input"] = {"error": "sayfa açılamadı"}
        return

    selects = await get_all_selects(page)
    buttons = await get_visible_buttons(page)

    logger.info(f"  Select sayısı: {len(selects)}")
    for sel in selects:
        logger.info(f"    [{sel['id'] or sel['name']}] "
                    f"label='{sel['label']}': "
                    f"{[o['text'] for o in sel['options'][:8]]}")

    # Tarih alanları (DevExpress DateEdit)
    date_fields = await page.evaluate("""
        () => Array.from(document.querySelectorAll(
            '[id*="Date"], [id*="date"], [id*="Tarih"], [id*="tarih"]'))
          .filter(el => el.offsetParent !== null)
          .map(el => ({ id: el.id, type: el.type, value: el.value }))
    """)

    results["etut_input"] = {
        "url": page.url,
        "selects": selects,
        "date_fields": date_fields,
        "safe_buttons": [b for b in buttons if b["safe"]],
        "forbidden_buttons": [b for b in buttons if not b["safe"]],
    }
    logger.success(f"  ✅ Etüt giriş keşfi: {len(selects)} select")


async def explore_exam_pages(page: Page, results: dict) -> None:
    """Sınav sayfalarını haritala."""
    logger.info("=" * 60)
    logger.info("📊 SINAV SAYFALARI KEŞFİ")

    exam_pages = [
        ("test_list", f"{BASE_URL}/Pages/Student/Test/test", "Sınav Listesi"),
        ("exam_grade", f"{BASE_URL}/Pages/Student/exam-grade-list", "Notlar"),
        ("exam_student", f"{BASE_URL}/Pages/Student/exam", "Sınav Öğrenci"),
    ]

    exam_results = {}
    for key, url, label in exam_pages:
        if not await safe_goto(page, url, wait=2.5):
            exam_results[key] = {"error": "sayfa açılamadı"}
            continue

        # ARA → içeriği yükle
        await click_ara(page)
        await asyncio.sleep(2.5)
        await wait_for_grid(page, timeout_ms=8000)

        exam_results[key] = {
            "url": page.url,
            "tables": await get_tables(page, max_rows=3),
            "selects": await get_all_selects(page),
            "buttons": [b for b in await get_visible_buttons(page) if b["safe"]],
        }
        logger.info(f"  {label}: {len(exam_results[key]['tables'])} tablo")

    results["exam_pages"] = exam_results
    logger.success("  ✅ Sınav keşfi tamamlandı.")


async def explore_form_page(page: Page, results: dict,
                            key: str, url: str, label: str) -> None:
    """Genel form sayfası keşfi (ARA dahil)."""
    logger.info(f"📝 FORM: {label}")

    if not await safe_goto(page, url, wait=2.5):
        results[key] = {"error": "sayfa açılamadı"}
        return

    await click_ara(page)
    await asyncio.sleep(2.0)

    struct = {
        "url": page.url,
        "selects": await get_all_selects(page),
        "tables": await get_tables(page, max_rows=3),
        "safe_buttons": [b for b in await get_visible_buttons(page) if b["safe"]],
        "forbidden_buttons": [b for b in await get_visible_buttons(page)
                              if not b["safe"]],
    }
    logger.info(f"  {label}: {len(struct['selects'])} select, "
                f"{len(struct['tables'])} tablo")
    results[key] = struct


# ════════════════════════════════════════════════════════════════════════════
# ANA AKIŞ
# ════════════════════════════════════════════════════════════════════════════

async def main():
    logger.info("🚀 Eyotek Otonom Derin Keşif Başlıyor (v3 Self-Healing)")
    logger.info(f"   Hedef: {BASE_URL}")

    results = {
        "base_url": BASE_URL,
        "explored_at": __import__("datetime").datetime.now().isoformat(),
        "version": "v3",
    }

    async with async_playwright() as p:

        # ── Chrome'a bağlan ────────────────────────────────────────────────
        browser = None
        try:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
            logger.info("✅ Mevcut Chrome'a bağlandı.")
        except Exception:
            logger.info("Chrome açık değil, başlatılıyor...")
            chrome_exe = find_chrome()
            if not chrome_exe:
                logger.error("❌ Chrome bulunamadı! Manuel olarak açın ve 9222 portunu etkinleştirin.")
                return
            profile = Path.home() / ".fermatai_chrome_profile"
            profile.mkdir(exist_ok=True)
            subprocess.Popen(
                [chrome_exe, f"--remote-debugging-port={CDP_PORT}",
                 f"--user-data-dir={profile}", "--no-first-run",
                 "--no-default-browser-check", BASE_URL],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            time.sleep(4)
            try:
                browser = await p.chromium.connect_over_cdp(CDP_URL)
            except Exception as e:
                logger.error(f"❌ CDP bağlantısı başarısız: {e}")
                return

        context = browser.contexts[0]
        page = context.pages[0] if context.pages else await context.new_page()

        # ── ADIM 1: Oturum doğrula ────────────────────────────────────────
        if not await validate_and_refresh_session(page, context):
            logger.error("❌ Oturum doğrulanamadı. Çıkılıyor.")
            await browser.close()
            return

        # ── ADIM 2: ARA Modal tam haritası ────────────────────────────────
        try:
            await explore_student_ara_modal(page, results)
        except Exception as e:
            logger.error(f"ARA modal hatası: {e}")
            results["ara_modal_error"] = str(e)

        # ── ADIM 3: "..." Bağlam menüsü → PostBack → St_Id ──────────────
        detail_url = None
        try:
            # Eğer hâlâ student listesi sayfasındaysak, grid dolu olmalı
            # explore_student_ara_modal grid'i doldurdu → direkt devam
            student_page_url = f"{BASE_URL}/Pages/Student/student"
            if "student" not in page.url and "student-detail" not in page.url:
                logger.info("  Öğrenci listesine dönülüyor...")
                await safe_goto(page, student_page_url, wait=3.0)
                await click_ara(page)
                await asyncio.sleep(1.5)
                # Modal içi ARA
                await page.evaluate("""
                    () => {
                        const containers = [
                            document.querySelector('#btnCloseSearchModal')
                                ?.closest('div,section'),
                            document.querySelector('.modal-content'),
                            document.querySelector('.dxpc-mainDiv'),
                        ].filter(Boolean);
                        for (const c of containers) {
                            for (const b of c.querySelectorAll(
                                'a, button, input[type=submit]')) {
                                const t = (b.innerText||b.value||'').toUpperCase().trim();
                                if (t === 'ARA') { b.click(); return; }
                            }
                        }
                    }
                """)
                await asyncio.sleep(2)
                await wait_for_grid(page, timeout_ms=15000)
                await page.keyboard.press("Escape")
                await asyncio.sleep(1)
            detail_url = await explore_student_context_menu(page, results)
        except Exception as e:
            logger.error(f"Bağlam menüsü hatası: {e}")
            results["context_menu_error"] = str(e)

        # ── ADIM 4: Öğrenci detay sekmeleri ──────────────────────────────
        # PostBack sonrası sayfa zaten student-detail'e gitmiş olabilir
        if detail_url:
            try:
                await explore_student_detail_tabs(page, results, detail_url)
            except Exception as e:
                logger.error(f"Öğrenci detay hatası: {e}")
                results["student_detail_error"] = str(e)
        else:
            logger.warning("  St_Id bulunamadı — öğrenci detay keşfi atlandı")
            # Fallback: Zaten student-detail'de miyiz?
            if "student-detail" in page.url:
                logger.info("  Mevcut sayfa student-detail — keşif yapılıyor...")
                try:
                    await explore_student_detail_tabs(page, results, page.url)
                except Exception as e:
                    logger.error(f"Öğrenci detay (fallback) hatası: {e}")

        # ── ADIM 5: Etüt giriş formu ──────────────────────────────────────
        try:
            await explore_etut_input(page, results)
        except Exception as e:
            logger.error(f"Etüt giriş hatası: {e}")

        # ── ADIM 6: Yoklama ───────────────────────────────────────────────
        try:
            await explore_attendance_form(page, results)
        except Exception as e:
            logger.error(f"Yoklama hatası: {e}")

        # ── ADIM 7: Rehberlik notu ────────────────────────────────────────
        try:
            await explore_counsellor_note(page, results)
        except Exception as e:
            logger.error(f"Rehberlik notu hatası: {e}")

        # ── ADIM 7b: Rehberlik Notu EKLE formu (student-counsellor-note) ──
        # St_Id student_detail keşfinde bulunmuştur (ADIM 5)
        try:
            _sd_st_id = (results.get("student_detail") or {}).get("st_id", "")
            if not _sd_st_id:
                # context_menu'den de dene
                _sd_st_id = (results.get("context_menu") or {}).get("st_id", "")
            await explore_counsellor_note_form(page, results, _sd_st_id)
        except Exception as e:
            logger.error(f"Rehberlik notu form hatası: {e}")

        # ── ADIM 8: Sınav sayfaları ───────────────────────────────────────
        try:
            await explore_exam_pages(page, results)
        except Exception as e:
            logger.error(f"Sınav hatası: {e}")

        # ── ADIM 9: Diğer kritik form sayfaları ──────────────────────────
        other_pages = [
            ("homework_assignment",
             f"{BASE_URL}/Pages/Student/homework-assignment", "Ödev Ver"),
            ("individual_lesson_search",
             f"{BASE_URL}/Pages/Student/individual-lesson", "Etüt Listesi"),
            ("attendance_today",
             f"{BASE_URL}/Pages/Student/attendance-today", "Bugün Gelmeyenler"),
            ("class_list",
             f"{BASE_URL}/Pages/Student/class-list", "Sınıf Listesi"),
            ("student_communication_sms",
             f"{BASE_URL}/Pages/Student/communication-sms-special-text", "SMS"),
            ("financial_student",
             f"{BASE_URL}/Pages/Financial/student-financial-operation",
             "Öğrenci Ödeme"),
            ("staff_my_students",
             f"{BASE_URL}/Pages/Staff/my-counsellor-students",
             "Rehber Öğrencilerim"),
            ("weekly_plan",
             f"{BASE_URL}/Pages/Staff/weekly-working-plan", "Haftalık Plan"),
            ("teacher_timetable",
             f"{BASE_URL}/Pages/Staff/timetable-watch-place",
             "Öğretmen Ders Programı"),
        ]
        for key, url, label in other_pages:
            try:
                await explore_form_page(page, results, key, url, label)
            except Exception as e:
                logger.error(f"{label} hatası: {e}")
                results[key] = {"error": str(e)}

        await browser.close()

    # ── Kaydet ────────────────────────────────────────────────────────────
    OUTPUT_FILE.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.success(f"\n✅ Keşif tamamlandı! → {OUTPUT_FILE}")
    keys = [k for k in results if k not in ("base_url", "explored_at", "version")]
    logger.info(f"   Keşfedilen bölümler ({len(keys)}): {keys}")

    # Özet rapor
    if "context_menu" in results:
        cm = results["context_menu"]
        if cm.get("st_id"):
            logger.success(f"   🔑 St_Id keşfedildi: {cm['st_id'][:30]}...")
            logger.success(f"   👤 {len(cm.get('menu_links', []))} alt sayfa bulundu")
    if "ara_modal" in results:
        logger.success(f"   🔍 ARA Modal: "
                       f"{len(results['ara_modal'].get('inputs', []))} input")
    if "student_detail" in results:
        td = results["student_detail"].get("tab_details", {})
        logger.success(f"   📑 Öğrenci Detay: {len(td)} sekme")
    if "counsellor_note_form" in results:
        cnf = results["counsellor_note_form"]
        if cnf.get("error"):
            logger.warning(f"   💬 Rehberlik Notu Formu: HATA — {cnf['error']}")
        else:
            vis_ta = cnf.get("visible_textareas", [])
            new_sel = cnf.get("new_selects", [])
            logger.success(
                f"   💬 Rehberlik Notu EKLE formu: "
                f"tıklanan={cnf.get('ekle_clicked')}, "
                f"yeni select={[s['id'] for s in new_sel]}, "
                f"görünür textarea={[t['id'] for t in vis_ta]}"
            )


if __name__ == "__main__":
    asyncio.run(main())
