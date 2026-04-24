"""
FermatAI Eyotek Agent v10
=========================
Mimari:
  - Gerçek Chrome + CDP ile Cloudflare Turnstile bypass
  - Cookie tabanlı session yönetimi (otomatik yenileme)
  - Jenerik DevExpress GridView scraper (tüm modüller için)
  - Çoklu modül: öğrenci, yoklama, sınavlar, geciken ödeme, personel
  - asyncpg ile PostgreSQL upsert / snapshot

Kullanım:
  python eyotek_agent.py                  → tüm modülleri scrape et
  python eyotek_agent.py students         → sadece öğrencileri scrape et
  python eyotek_agent.py attendance       → sadece yoklamayı scrape et
  python eyotek_agent.py exams            → sadece sınavları scrape et
  python eyotek_agent.py overdue          → sadece geciken ödemeleri scrape et
  python eyotek_agent.py staff            → sadece personeli scrape et
  python eyotek_agent.py exam_results     → sadece sınav değerlendirmeyi scrape et
"""

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import asyncpg
import httpx
from dotenv import load_dotenv
from loguru import logger
from playwright.async_api import async_playwright

# ---------------------------------------------------------------------------
# Konfigürasyon
# ---------------------------------------------------------------------------

load_dotenv()

CONFIG = {
    "base_url":     os.getenv("EYOTEK_URL", "https://fermat.eyotek.com/v1"),
    "username":     os.getenv("EYOTEK_USER", ""),
    "password":     os.getenv("EYOTEK_PASS", ""),
    "session_file": Path(os.getenv("SESSION_FILE", ".eyotek_session.json")),
    "database_url": os.getenv("DATABASE_URL", ""),
    "agent_mode":   os.getenv("AGENT_MODE", "scraping"),
    "cdp_port":     int(os.getenv("CDP_PORT", "9222")),
    "headless":     os.getenv("HEADLESS", "false").lower() == "true",
}

CDP_URL = f"http://127.0.0.1:{CONFIG['cdp_port']}"


# ---------------------------------------------------------------------------
# Modül Konfigürasyonları
# ---------------------------------------------------------------------------

def get_module_configs() -> dict:
    """
    Scrape edilecek tüm modüllerin tam konfigürasyonu.
    Her modül: url, field_map, db_table, primary_key, create_sql tanımlar.
    """
    base = CONFIG["base_url"]
    return {

        # ── Öğrenciler ──────────────────────────────────────────────────────
        "students": {
            "name":       "Öğrenciler",
            "url":        f"{base}/Pages/Student/student",
            "needs_ara":  True,
            "field_map": {
                "söz no":       "soz_no",
                "okul no":      "eyotek_id",
                "öğrenci no":   "eyotek_id",
                "kayıt tarihi": "kayit_tarihi",
                "tc kimlik":    "tc_no",
                "t.c. kimlik":  "tc_no",
                "soyadı":       "last_name",
                "adı soyadı":   "full_name",
                "ad soyad":     "full_name",
                "adı":          "first_name",
                "sezon":        "sezon",
                "şube":         "sube",
                "program":      "program",
                "sınıfı":       "class_name",
                "sınıf":        "class_name",
                "devre":        "devre",
                "kurs":         "kur",
                "kur":          "kur",
                "durum":        "status",
                "kayıt":        "status",
                "cinsiyet":     "gender",
                "doğum":        "birth_date",
                "gsm":          "phone",
                "telefon":      "phone",
                "veli adı":     "parent_name",
                "veli":         "parent_name",
                "t.c":          "tc_no",
                "tc":           "tc_no",
                "kimlik":       "tc_no",
            },
            "db_table":    "students",
            "primary_key": "eyotek_id",
            "upsert_mode": "pk",   # upsert on primary key
            "create_sql": """
                CREATE TABLE IF NOT EXISTS students (
                    eyotek_id    TEXT PRIMARY KEY,
                    soz_no       TEXT,
                    full_name    TEXT,
                    first_name   TEXT,
                    last_name    TEXT,
                    sezon        TEXT,
                    sube         TEXT,
                    class_name   TEXT,
                    program      TEXT,
                    devre        TEXT,
                    kur          TEXT,
                    kayit_tarihi TEXT,
                    tc_no        TEXT,
                    gender       TEXT,
                    birth_date   TEXT,
                    phone        TEXT,
                    parent_name  TEXT,
                    status       TEXT,
                    last_sync    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """,
            "migrations": [
                "ALTER TABLE students ADD COLUMN IF NOT EXISTS soz_no       TEXT",
                "ALTER TABLE students ADD COLUMN IF NOT EXISTS full_name     TEXT",
                "ALTER TABLE students ADD COLUMN IF NOT EXISTS first_name    TEXT",
                "ALTER TABLE students ADD COLUMN IF NOT EXISTS last_name     TEXT",
                "ALTER TABLE students ADD COLUMN IF NOT EXISTS sezon         TEXT",
                "ALTER TABLE students ADD COLUMN IF NOT EXISTS sube          TEXT",
                "ALTER TABLE students ADD COLUMN IF NOT EXISTS class_name    TEXT",
                "ALTER TABLE students ADD COLUMN IF NOT EXISTS program       TEXT",
                "ALTER TABLE students ADD COLUMN IF NOT EXISTS devre         TEXT",
                "ALTER TABLE students ADD COLUMN IF NOT EXISTS kur           TEXT",
                "ALTER TABLE students ADD COLUMN IF NOT EXISTS kayit_tarihi  TEXT",
                "ALTER TABLE students ADD COLUMN IF NOT EXISTS tc_no         TEXT",
                "ALTER TABLE students ADD COLUMN IF NOT EXISTS gender        TEXT",
                "ALTER TABLE students ADD COLUMN IF NOT EXISTS birth_date    TEXT",
                "ALTER TABLE students ADD COLUMN IF NOT EXISTS phone         TEXT",
                "ALTER TABLE students ADD COLUMN IF NOT EXISTS parent_name   TEXT",
                "ALTER TABLE students ADD COLUMN IF NOT EXISTS status        TEXT",
                "ALTER TABLE students ADD COLUMN IF NOT EXISTS last_sync     TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            ],
        },

        # ── Yoklama – Bugün Gelmeyenler ─────────────────────────────────────
        "attendance": {
            "name":       "Yoklama (Bugün Gelmeyenler)",
            "url":        f"{base}/Pages/Student/attendance-today",
            "needs_ara":  True,
            "field_map": {
                "söz no":       "soz_no",
                "okul no":      "eyotek_id",
                "adı soyadı":   "full_name",
                "ad soyad":     "full_name",
                "adı":          "first_name",
                "soyadı":       "last_name",
                "şube":         "sube",
                "tarih":        "tarih",
                "ders":         "ders_no",
                "saat":         "saat",
                "gün":          "gun",
                "durum":        "durum",
                "izin":         "izin_turu",
                "açıklama":     "aciklama",
                "mesaj":        "mesaj",
                "sezon":        "sezon",
            },
            "db_table":    "attendance",
            "primary_key": None,
            "upsert_mode": "snapshot",  # Günlük snapshot: bugünü temizle + ekle
            "create_sql": """
                CREATE TABLE IF NOT EXISTS attendance (
                    id          SERIAL PRIMARY KEY,
                    eyotek_id   TEXT,
                    soz_no      TEXT,
                    full_name   TEXT,
                    first_name  TEXT,
                    last_name   TEXT,
                    sube        TEXT,
                    tarih       TEXT,
                    ders_no     TEXT,
                    saat        TEXT,
                    gun         TEXT,
                    durum       TEXT,
                    izin_turu   TEXT,
                    aciklama    TEXT,
                    mesaj       TEXT,
                    sezon       TEXT,
                    last_sync   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """,
            "migrations": [],
        },

        # ── Sınavlar ────────────────────────────────────────────────────────
        "exams": {
            "name":       "Sınavlar",
            "url":        f"{base}/Pages/Student/test-transferred",
            "needs_ara":  True,
            "field_map": {
                "şube":          "sube",
                "tarih":         "tarih",
                "sınav kodu":    "sinav_kodu",
                "sınav türü":    "sinav_turu",
                "sınav kategori":"sinav_kategori",
                "sınav adı":     "sinav_adi",
                "sezon":         "sezon",
                "devre":         "devre",
                "sınıf":         "sinif",
                "durum":         "durum",
                "aktif":         "aktif",
                "kod":           "sinav_kodu",
                "adı":           "sinav_adi",
                "tür":           "sinav_turu",
                "kategori":      "sinav_kategori",
            },
            "db_table":    "exams",
            "primary_key": "sinav_kodu",
            "upsert_mode": "pk",
            "create_sql": """
                CREATE TABLE IF NOT EXISTS exams (
                    sinav_kodu      TEXT PRIMARY KEY,
                    sinav_adi       TEXT,
                    sinav_turu      TEXT,
                    sinav_kategori  TEXT,
                    sube            TEXT,
                    tarih           TEXT,
                    sezon           TEXT,
                    devre           TEXT,
                    sinif           TEXT,
                    durum           TEXT,
                    aktif           TEXT,
                    last_sync       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """,
            "migrations": [],
        },

        # ── Sınav Değerlendirme ─────────────────────────────────────────────
        "exam_results": {
            "name":       "Sınav Değerlendirme",
            "url":        f"{base}/Pages/Student/Test/test",
            "needs_ara":  True,
            "field_map": {
                "sezon":         "sezon",
                "şube":          "sube",
                "sınav kodu":    "sinav_kodu",
                "sınav adı":     "sinav_adi",
                "sınav türü":    "sinav_turu",
                "tarih":         "tarih",
                "devre":         "devre",
                "sınıf":         "sinif",
                "durum":         "durum",
                "net":           "net",
                "puan":          "puan",
                "sıra":          "sira",
                "okul sıra":     "okul_sira",
                "genel sıra":    "genel_sira",
                "doğru":         "dogru",
                "yanlış":        "yanlis",
                "boş":           "bos",
            },
            "db_table":    "exam_results",
            "primary_key": None,
            "upsert_mode": "snapshot",
            "create_sql": """
                CREATE TABLE IF NOT EXISTS exam_results (
                    id           SERIAL PRIMARY KEY,
                    sezon        TEXT,
                    sube         TEXT,
                    sinav_kodu   TEXT,
                    sinav_adi    TEXT,
                    sinav_turu   TEXT,
                    tarih        TEXT,
                    devre        TEXT,
                    sinif        TEXT,
                    durum        TEXT,
                    net          TEXT,
                    puan         TEXT,
                    sira         TEXT,
                    okul_sira    TEXT,
                    genel_sira   TEXT,
                    dogru        TEXT,
                    yanlis       TEXT,
                    bos          TEXT,
                    last_sync    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """,
            "migrations": [],
        },

        # ── Geciken Ödemeler ────────────────────────────────────────────────
        "overdue": {
            "name":       "Geciken Ödemeler",
            "url":        f"{base}/Pages/Financial/overdue-student-payment",
            "needs_ara":  True,
            "field_map": {
                "söz no":       "soz_no",
                "okul no":      "eyotek_id",
                "adı soyadı":   "full_name",
                "ad soyad":     "full_name",
                "adı":          "first_name",
                "soyadı":       "last_name",
                "sezon":        "sezon",
                "şube":         "sube",
                "tutar":        "tutar",
                "borç":         "borc",
                "ödeme":        "odeme",
                "bakiye":       "bakiye",
                "vade":         "vade_tarihi",
                "tarih":        "tarih",
                "taksit":       "taksit_no",
                "mesaj":        "mesaj",
                "açıklama":     "aciklama",
            },
            "db_table":    "overdue_payments",
            "primary_key": None,
            "upsert_mode": "snapshot",  # Her çalıştırmada taze snapshot
            "create_sql": """
                CREATE TABLE IF NOT EXISTS overdue_payments (
                    id           SERIAL PRIMARY KEY,
                    eyotek_id    TEXT,
                    soz_no       TEXT,
                    full_name    TEXT,
                    first_name   TEXT,
                    last_name    TEXT,
                    sezon        TEXT,
                    sube         TEXT,
                    tutar        TEXT,
                    borc         TEXT,
                    odeme        TEXT,
                    bakiye       TEXT,
                    vade_tarihi  TEXT,
                    tarih        TEXT,
                    taksit_no    TEXT,
                    mesaj        TEXT,
                    aciklama     TEXT,
                    last_sync    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """,
            "migrations": [],
        },

        # ── Personel ────────────────────────────────────────────────────────
        "staff": {
            "name":       "Personel",
            "url":        f"{base}/Pages/Staff/staff",
            "needs_ara":  True,   # Sayfa başta boş gelir, btnSearch ile yükle
            "field_map": {
                "id":            "eyotek_id",
                "i̇k no":         "ik_no",
                "ik no":         "ik_no",
                "adı soyadı":    "full_name",
                "ad soyad":      "full_name",
                "adı":           "first_name",
                "soyadı":        "last_name",
                "görevi":        "gorev",
                "görevi":        "gorev",
                "branş":         "brans",
                "brans":         "brans",
                "şube":          "sube",
                "söz tarihi":    "soz_tarihi",
                "çıkış tar":     "cikis_tar",
                "e-posta":       "email",
                "mail":          "email",
                "kullanıcı adı": "kullanici",
                "kullanici":     "kullanici",
                "atama sayı":    "atama_sayi",
                "durum":         "status",
                "sezon":         "sezon",
            },
            "db_table":    "staff",
            "primary_key": "eyotek_id",
            "upsert_mode": "pk",
            "create_sql": """
                CREATE TABLE IF NOT EXISTS staff (
                    eyotek_id   TEXT PRIMARY KEY,
                    ik_no       TEXT,
                    full_name   TEXT,
                    first_name  TEXT,
                    last_name   TEXT,
                    gorev       TEXT,
                    brans       TEXT,
                    email       TEXT,
                    kullanici   TEXT,
                    sezon       TEXT,
                    sube        TEXT,
                    soz_tarihi  TEXT,
                    cikis_tar   TEXT,
                    atama_sayi  TEXT,
                    status      TEXT DEFAULT 'Aktif',
                    last_sync   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """,
            "migrations": [],
        },

    }


# ---------------------------------------------------------------------------
# Session Yönetimi
# ---------------------------------------------------------------------------

def load_session() -> list[dict] | None:
    sf = CONFIG["session_file"]
    if sf.exists():
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                logger.info(f"📂 Session yüklendi: {sf} ({len(data)} cookie)")
                return data
        except Exception as e:
            logger.warning(f"Session dosyası okunamadı: {e}")
    return None


def save_session(cookies: list[dict]) -> None:
    sf = CONFIG["session_file"]
    sf.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.success(f"💾 Session kaydedildi: {sf} ({len(cookies)} cookie)")


def cookies_to_header(cookies: list[dict]) -> str:
    return "; ".join(f"{c['name']}={c['value']}" for c in cookies)


async def session_is_valid(cookies: list[dict]) -> bool:
    headers = {
        "Cookie": cookies_to_header(cookies),
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/130.0.0.0 Safari/537.36"
        ),
    }
    check_url = f"{CONFIG['base_url']}/Pages/Staff/home"
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=15) as client:
            r = await client.get(check_url, headers=headers)
            valid = r.status_code == 200
            logger.info(f"🔍 Session kontrol: {r.status_code} → {'✅ Geçerli' if valid else '❌ Geçersiz'}")
            return valid
    except Exception as e:
        logger.warning(f"Session kontrol hatası: {e}")
        return False


# ---------------------------------------------------------------------------
# Chrome başlatma + CDP
# ---------------------------------------------------------------------------

def find_chrome_path() -> str | None:
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    return None


def launch_chrome(port: int) -> subprocess.Popen | None:
    chrome_path = find_chrome_path()
    if not chrome_path:
        logger.error("❌ Chrome bulunamadı!")
        return None

    profile_dir = Path.home() / ".fermatai_chrome_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        chrome_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        CONFIG["base_url"],
    ]
    logger.info(f"🌐 Chrome başlatılıyor: port={port}")
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(3)
        return proc
    except Exception as e:
        logger.error(f"Chrome başlatılamadı: {e}")
        return None


async def login_via_chrome_cdp() -> list[dict] | None:
    port = CONFIG["cdp_port"]
    proc = launch_chrome(port)
    if not proc:
        return None

    print("\n" + "=" * 60)
    print("🔐 EYOTEK GİRİŞ GEREKİYOR")
    print("=" * 60)
    print(f"Chrome açıldı → {CONFIG['base_url']}")
    print("Lütfen Eyotek'e giriş yapın.")
    print("Giriş tamamlandıktan sonra buraya dönün ve ENTER'a basın.")
    print("=" * 60)
    input("ENTER → ")

    cookies = []
    try:
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
            context = browser.contexts[0] if browser.contexts else None
            if not context:
                logger.error("CDP context bulunamadı.")
                return None
            all_cookies = await context.cookies()
            cookies = [c for c in all_cookies if "eyotek.com" in c.get("domain", "")]
            logger.info(f"🍪 {len(cookies)} eyotek cookie alındı")
            await browser.close()
    except Exception as e:
        logger.error(f"CDP bağlantı hatası: {e}")
        if proc:
            proc.terminate()
        return None

    if cookies:
        save_session(cookies)
        return cookies
    else:
        logger.error("❌ Cookie alınamadı.")
        return None


async def get_valid_session() -> list[dict] | None:
    cookies = load_session()
    if cookies and await session_is_valid(cookies):
        return cookies
    logger.info("🔄 Session geçersiz veya yok, yeniden giriş yapılıyor...")
    return await login_via_chrome_cdp()


async def validate_and_refresh_session(page, cookies: list[dict]) -> list[dict]:
    """
    Sayfa üzerinde session kontrolü yap. Düştüyse CDP üzerinden cookie'leri
    yenile ve sayfayı tekrar yükle. Inline kullanım için (pagination sırasında).
    """
    current_url = page.url
    is_auth = (
        "fermat.eyotek.com" in current_url
        and "/Pages/" in current_url
        and "default.aspx" not in current_url
        and "login" not in current_url.lower()
    )
    if is_auth:
        return cookies  # Hâlâ aktif

    logger.warning("⚠️  Inline session düştü — yenileniyor...")
    try:
        context = page.context
        all_c = await context.cookies()
        fresh = [c for c in all_c if "eyotek.com" in c.get("domain", "")]
        if fresh:
            save_session(fresh)
            logger.success(f"✅ Session inline yenilendi ({len(fresh)} cookie)")
            return fresh
    except Exception as e:
        logger.warning(f"  Cookie yenileme hatası: {e}")

    # Kullanıcıdan giriş iste (interaktif değilse uyar)
    logger.error("❌ Session otomatik yenilenemedi. Chrome'da manuel giriş gerekebilir.")
    return cookies


# ---------------------------------------------------------------------------
# Jenerik Header Eşleştirme
# ---------------------------------------------------------------------------

def build_header_map(headers: list[str], field_map: dict) -> dict[int, str]:
    """
    Başlık listesinden sütun_indeks → alan_adı haritası oluştur.
    1. Tam eşleşme  2. Uzun→kısa substring
    """
    sorted_map = sorted(field_map.items(), key=lambda x: -len(x[0]))
    header_map = {}

    for i, h in enumerate(headers):
        h_clean = h.strip().lower()
        if not h_clean or h_clean in ('\xa0', ' ', ''):
            continue

        # 1. Tam eşleşme
        if h_clean in field_map:
            header_map[i] = field_map[h_clean]
            continue

        # 2. Substring (uzun → kısa)
        for key, field in sorted_map:
            if key in h_clean:
                header_map[i] = field
                break

    return header_map


# ---------------------------------------------------------------------------
# Jenerik Grid Okuma
# ---------------------------------------------------------------------------

def extract_record(cells: list[str], header_map: dict) -> dict | None:
    """Hücre listesinden field_map'e göre bir kayıt dict'i oluştur."""
    if len(cells) < 2:
        return None
    non_empty = [c.strip() for c in cells if c.strip() and c.strip() != '\xa0']
    if not non_empty:
        return None

    record = {}
    for col_idx, field_name in header_map.items():
        if col_idx < len(cells):
            val = cells[col_idx].strip()
            if val and val != '\xa0':
                record[field_name] = val

    return record if record else None


async def read_grid_page(page, field_map: dict) -> tuple[dict, list[dict]]:
    """
    DevExpress GridView sayfasını oku.
    Döndürür: (header_map, kayıtlar)
    """
    headers = []

    # Başlıkları oku — üç yöntem dene
    dxgv_headers = await page.locator("tr.dxgvHeader td, tr.dxgvHeader th").all_text_contents()
    if dxgv_headers:
        headers = dxgv_headers
        logger.debug(f"  📋 DevExpress başlıklar: {headers[:8]}")

    if not headers:
        th_headers = await page.locator("table th").all_text_contents()
        if th_headers:
            headers = th_headers
            logger.debug(f"  📋 th başlıklar: {headers[:8]}")

    if not headers:
        first_row = await page.locator("table tr:first-child td").all_text_contents()
        if first_row:
            headers = first_row
            logger.debug(f"  📋 İlk-satır başlıklar: {headers[:8]}")

    header_map = {}
    if headers:
        header_map = build_header_map(headers, field_map)
        logger.info(f"  🗺️  Sütun eşleştirme: {header_map}")

    # Veri satırlarını oku
    records = []
    data_rows = await page.locator(
        "tr.dxgvDataRow, tr.dxgvDataRowAlt, tr[class*='dxgvDataRow']"
    ).all()

    if not data_rows:
        data_rows = await page.locator("table tbody tr").all()

    if not data_rows:
        all_rows = await page.locator("table tr").all()
        data_rows = all_rows[1:] if len(all_rows) > 1 else []

    logger.info(f"  📊 {len(data_rows)} satır bulundu")

    for row in data_rows:
        cells = await row.locator("td").all_text_contents()
        rec = extract_record(cells, header_map)
        if rec:
            records.append(rec)

    return header_map, records


# ---------------------------------------------------------------------------
# Jenerik Browser Scraper
# ---------------------------------------------------------------------------

async def scrape_module_via_browser(
    cookies: list[dict],
    module_config: dict,
    browser_context=None,
) -> list[dict]:
    """
    Herhangi bir Eyotek modülünü (DevExpress grid) scrape et.
    browser_context verilirse mevcut context kullanılır (Chrome'u yeniden açmaz).
    """
    all_records = []
    mod_name   = module_config["name"]
    url        = module_config["url"]
    field_map  = module_config["field_map"]
    needs_ara  = module_config.get("needs_ara", True)

    owns_browser = browser_context is None

    async with async_playwright() as p:
        if owns_browser:
            try:
                browser = await p.chromium.connect_over_cdp(CDP_URL)
            except Exception:
                logger.warning("Chrome açık değil, başlatılıyor...")
                proc = launch_chrome(CONFIG["cdp_port"])
                if not proc:
                    return all_records
                await asyncio.sleep(3)
                browser = await p.chromium.connect_over_cdp(CDP_URL)
            context = browser.contexts[0]
        else:
            browser  = browser_context["browser"]
            context  = browser_context["context"]

        page = context.pages[0] if context.pages else await context.new_page()

        logger.info(f"\n{'='*55}")
        logger.info(f"📦 MODÜL: {mod_name}")
        logger.info(f"📍 URL: {url}")
        logger.info(f"{'='*55}")

        await context.add_cookies(cookies)
        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(2)

        # ── ARA akışı (sadece needs_ara=True modüllerde) ─────────────────
        if needs_ara:
            # ADIM 1: Toolbar ARA — dış ARA butonuna tıkla (popup açar)
            logger.info("🔍 Toolbar ARA butonu aranıyor...")
            clicked = await page.evaluate("""
                () => {
                    const els = document.querySelectorAll(
                        'a, button, input[type=button], input[type=submit]'
                    );
                    for (const el of els) {
                        const txt = (el.innerText || el.value || '').toUpperCase().trim();
                        if (txt === 'ARA' && el.offsetParent !== null) {
                            el.click();
                            return true;
                        }
                    }
                    return false;
                }
            """)

            if not clicked:
                await page.screenshot(path=f"error_{module_config['db_table']}_ara.png")
                logger.error(f"❌ Toolbar ARA bulunamadı ({mod_name}). Ekran görüntüsü kaydedildi.")
                if owns_browser:
                    await browser.close()
                return all_records

            logger.success("🚀 Toolbar ARA tıklandı!")

            # ADIM 2: Eyotek custom popup bekle (#btnCloseSearchModal veya #btnSearch)
            # ÖNEMLİ: Eyotek .modal-content DEĞİL, custom popup kullanıyor.
            popup_opened = False
            for sel in [
                "#btnCloseSearchModal",
                "[id*=CloseSearchModal]",
                "#btnSearch",
                ".modal-content",   # fallback (bazı sayfalar standart modal)
            ]:
                try:
                    await page.wait_for_selector(sel, timeout=5000)
                    popup_opened = True
                    logger.info(f"  Popup açıldı: {sel}")
                    break
                except Exception:
                    continue
            if not popup_opened:
                logger.warning("  Popup selector'ı bulunamadı, 1.5s bekleniyor...")
                await asyncio.sleep(1.5)

            # ADIM 3: Eyotek custom popup içindeki ARA butonuna tıkla
            # Eyotek popup'ı: #btnCloseSearchModal kardeş/parent üzerinden container'a yürü,
            # içinde #btnSearch veya btn.sbmt bul — bu pattern explore v3.2 ile doğrulandı.
            modal_clicked = await page.evaluate("""
                () => {
                    // Öncelik 1: Eyotek custom popup — btnCloseSearchModal'dan container'a yürü
                    const closeBtn = document.querySelector(
                        '#btnCloseSearchModal, [id*=CloseSearchModal], [id*=btnCloseSearch]'
                    );
                    if (closeBtn) {
                        let el = closeBtn.parentElement;
                        while (el && !['BODY', 'HTML'].includes(el.tagName)) {
                            const btns = el.querySelectorAll(
                                'a, button, input[type=button], input[type=submit]'
                            );
                            for (const btn of btns) {
                                const t = (btn.innerText || btn.value || '').toUpperCase().trim();
                                if (t === 'ARA' || t === 'LİSTELE') {
                                    btn.click();
                                    return 'eyotek_custom:' + (btn.id || t);
                                }
                            }
                            if (el.querySelectorAll('select').length > 2 ||
                                el.querySelectorAll('input:not([type=hidden])').length > 3) break;
                            el = el.parentElement;
                        }
                    }
                    // Öncelik 2: #btnSearch (profile_map.json'dan doğrulandı)
                    const btnSearch = document.getElementById('btnSearch');
                    if (btnSearch && btnSearch.offsetParent !== null) {
                        btnSearch.click();
                        return 'btnSearch';
                    }
                    // Öncelik 3: .sbmt class'ı (Eyotek ARA butonu stili)
                    const sbmt = document.querySelector('.sbmt, a.sbmt, button.sbmt');
                    if (sbmt && sbmt.offsetParent !== null) {
                        sbmt.click();
                        return 'sbmt:' + sbmt.innerText;
                    }
                    // Fallback: sayfadaki son görünür ARA
                    const araEls = Array.from(document.querySelectorAll(
                        'a, button, input[type=button], input[type=submit]'
                    )).filter(el => {
                        const t = (el.innerText || el.value || '').toUpperCase().trim();
                        return t === 'ARA' && el.offsetParent !== null;
                    });
                    if (araEls.length > 0) {
                        araEls[araEls.length - 1].click();
                        return 'fallback_page:' + araEls.length;
                    }
                    return null;
                }
            """)

            if modal_clicked:
                logger.success(f"🚀 Modal ARA tıklandı: {modal_clicked}")
            else:
                logger.warning("Modal ARA bulunamadı, devam ediliyor...")

            await asyncio.sleep(2)

        # ── Grid yüklenene kadar bekle ────────────────────────────────────
        logger.info("⏳ Grid yükleniyor...")
        loaded = False
        for sel in [
            "tr.dxgvDataRow", "tr.dxgvDataRowAlt",
            "tr[class*='dxgvDataRow']", "table tbody tr td",
        ]:
            try:
                await page.wait_for_selector(sel, timeout=20000)
                loaded = True
                break
            except Exception:
                continue

        if not loaded:
            logger.warning("Grid yükleme zaman aşımı.")
            await page.screenshot(path=f"error_{module_config['db_table']}_grid.png")

        # ── Toplam sayfa sayısını tespit et ──────────────────────────────
        # NOT: DevExpress pager yalnızca 7 sayfa numarası gösterir (kayan pencere).
        # Sadece görünen maksimum sayıyı okumak yanlış — gerçek sayfa sayısı çok daha fazla olabilir.
        # Bu yüzden total_pages'i "Last Page" butonundan okumaya çalışıyoruz; bulamazsak 9999 kullanıyoruz.
        total_pages = await page.evaluate("""
            () => {
                // 1. ASP.NET GridView pager: href="javascript:__doPostBack('GridView1','Page$N')"
                //    Son görünen sayfa numarasını al
                const aspnetLinks = Array.from(document.querySelectorAll('a[href*="Page$"]'))
                    .map(a => {
                        const m = a.href.match(/Page\\$(\\d+)/);
                        return m ? parseInt(m[1]) : 0;
                    })
                    .filter(n => n > 0);
                if (aspnetLinks.length > 0) return Math.max(...aspnetLinks);

                // 2. DevExpress PBN pattern fallback
                const lastPageSelectors = [
                    'td[title*="Last"], a[title*="Last"]',
                    'td[title*="Son"], a[title*="Son"]',
                ];
                for (const sel of lastPageSelectors) {
                    for (const el of document.querySelectorAll(sel)) {
                        if (el.offsetParent === null) continue;
                        const oc = el.getAttribute('onclick') || '';
                        const m = oc.match(/PBN(\\d+)|PN(\\d+)/);
                        if (m) return parseInt(m[1] || m[2]);
                    }
                }

                // 3. Görünen sayısal linkler (fallback)
                const pagerCandidates = Array.from(
                    document.querySelectorAll('td.dxp-num, a.dxp-num, .dxp a, .dxPager a, .dxp-sp')
                ).filter(el => /^\\d+$/.test(el.innerText.trim()) && el.offsetParent !== null)
                 .map(el => parseInt(el.innerText.trim()));
                if (pagerCandidates.length > 0) return Math.max(...pagerCandidates);

                // 4. Genel fallback
                const all = Array.from(document.querySelectorAll('a, span, td'));
                const nums = all
                    .filter(el => /^\\d{1,2}$/.test(el.innerText.trim()) && el.offsetParent !== null)
                    .map(el => parseInt(el.innerText.trim()))
                    .filter(n => n <= 50);
                return nums.length > 0 ? Math.max(...nums) : 1;
            }
        """)
        # ASP.NET pager: a[href*="Page$N"] ile son sayfa numarasını aldık.
        # total_pages > 1 ise güvenilir — direkt kullan.
        # Bulunamazsa (1 döndü) fallback olarak 9999 ile tara; boş/tekrar sayfa gelince dur.
        if total_pages > 1:
            effective_total = total_pages
            logger.info(f"📑 Toplam sayfa: {total_pages}  (ASP.NET pager'dan)")
        else:
            effective_total = 9999
            logger.info(f"📑 Sayfa sayısı belirlenemedi → sonsuz tara modunda (boş/tekrar sayfa gelince durur)")

        # ── Sayfa 1 ───────────────────────────────────────────────────────
        logger.info("📊 Sayfa 1 okunuyor...")
        _, page_records = await read_grid_page(page, field_map)
        all_records.extend(page_records)
        logger.info(f"  └─ Sayfa 1: {len(page_records)} kayıt")

        # ── Sayfa 2+ ──────────────────────────────────────────────────────
        SESSION_CHECK_INTERVAL = 10  # Her 10 sayfada bir session kontrolü
        for page_num in range(2, min(effective_total + 1, 500)):  # max 500 sayfa güvenlik sınırı
            logger.info(f"📄 Sayfa {page_num} yükleniyor...")

            # Inline session recovery — her SESSION_CHECK_INTERVAL sayfada kontrol
            if page_num % SESSION_CHECK_INTERVAL == 0:
                cookies = await validate_and_refresh_session(page, cookies)
                # Cookie güncellemesini context'e uygula
                try:
                    await context.add_cookies(cookies)
                except Exception:
                    pass

            # ── ASP.NET GridView PostBack ile sayfa geç ──────────────────────
            # Eyotek öğrenci grid'i __doPostBack('GridView1','Page$N') kullanıyor.
            # Yöntem 1: Playwright native locator ile link tıkla (PostBack navigation'ı düzgün handle eder)
            # Yöntem 2: href'i 'Page$N' içeren link bulunamazsa __doPostBack doğrudan çağır

            clicked = None
            page_link_selector = f'a[href*="Page${page_num}"]'

            # Önce tıklamadan önce ilk satırın Söz No'sunu kaydet (değişim tespiti için)
            try:
                first_sozno_before = await page.evaluate("""
                    () => {
                        const tbl = document.querySelector('#GridView1, table.dataTable');
                        if (!tbl) return '';
                        const rows = tbl.querySelectorAll('tbody tr');
                        for (const row of rows) {
                            const cells = row.querySelectorAll('td');
                            if (cells.length >= 5) return cells[4].innerText.trim(); // Söz No = sütun 4
                        }
                        return '';
                    }
                """)
            except Exception:
                first_sozno_before = ""

            try:
                link_count = await page.locator(page_link_selector).count()
                if link_count > 0:
                    # Playwright native click — PostBack + navigation'ı otomatik bekler
                    async with page.expect_response(
                        lambda r: r.url.endswith('/student') or '/student' in r.url,
                        timeout=20000
                    ) as resp_info:
                        await page.locator(page_link_selector).first.click()
                    clicked = f'postback:{page_num}'
                else:
                    # Link DOM'da yok — __doPostBack doğrudan çağır (sayfa penceresi kaydıkça)
                    has_postback = await page.evaluate("typeof __doPostBack !== 'undefined'")
                    if has_postback:
                        async with page.expect_response(
                            lambda r: r.url.endswith('/student') or '/student' in r.url,
                            timeout=20000
                        ) as resp_info:
                            await page.evaluate(f"__doPostBack('GridView1','Page${page_num}')")
                        clicked = f'dopostback:{page_num}'
            except Exception as nav_err:
                logger.warning(f"  Sayfa {page_num} navigasyon hatası: {nav_err}")

            if not clicked:
                logger.warning(f"  Sayfa {page_num}: pager linki bulunamadı — sayfalama tamamlandı.")
                break

            logger.debug(f"  Sayfa tıklandı: {clicked}")

            # PostBack sonrası grid'in gerçekten yenilenmesini bekle
            await asyncio.sleep(1.5)
            try:
                await page.wait_for_selector('#GridView1 tbody tr td, table.dataTable tbody tr td', timeout=10000)
            except Exception:
                pass

            # Söz No değişti mi kontrol et
            try:
                first_sozno_after = await page.evaluate("""
                    () => {
                        const tbl = document.querySelector('#GridView1, table.dataTable');
                        if (!tbl) return '';
                        const rows = tbl.querySelectorAll('tbody tr');
                        for (const row of rows) {
                            const cells = row.querySelectorAll('td');
                            if (cells.length >= 5) return cells[4].innerText.trim();
                        }
                        return '';
                    }
                """)
                if first_sozno_after and first_sozno_after == first_sozno_before:
                    logger.warning(f"  Sayfa {page_num}: içerik değişmedi → son sayfayı aştık, duruyorum.")
                    break
                else:
                    logger.debug(f"  Sayfa {page_num}: grid güncellendi ✓ ({first_sozno_before}→{first_sozno_after})")
            except Exception:
                pass

            _, page_records = await read_grid_page(page, field_map)
            all_records.extend(page_records)
            logger.info(f"  └─ Sayfa {page_num}: {len(page_records)} kayıt")

            if not page_records:
                logger.warning("Boş sayfa, sayfalama durduruluyor.")
                break

        logger.info(f"✅ {mod_name}: {len(all_records)} kayıt toplandı.")

        if owns_browser:
            await browser.close()

    return all_records


# ---------------------------------------------------------------------------
# PostgreSQL – Jenerik Tablo Yönetimi
# ---------------------------------------------------------------------------

async def ensure_module_table(conn: asyncpg.Connection, module_config: dict) -> None:
    """Modül tablosunu oluştur ve migration uygula."""
    await conn.execute(module_config["create_sql"])
    for sql in module_config.get("migrations", []):
        try:
            await conn.execute(sql)
        except Exception:
            pass


async def save_sync_log(conn: asyncpg.Connection, module_key: str, count: int, errors: int) -> None:
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_log (
                id           SERIAL PRIMARY KEY,
                synced_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                module       TEXT,
                record_count INTEGER,
                errors       INTEGER,
                notes        TEXT
            )
        """)
        # Add module column if missing (backwards compat)
        try:
            await conn.execute("ALTER TABLE sync_log ADD COLUMN IF NOT EXISTS module TEXT")
            await conn.execute("ALTER TABLE sync_log ADD COLUMN IF NOT EXISTS errors INTEGER")
        except Exception:
            pass
        await conn.execute(
            "INSERT INTO sync_log (module, record_count, errors) VALUES ($1, $2, $3)",
            module_key, count, errors
        )
    except Exception as e:
        logger.warning(f"sync_log yazma hatası: {e}")


# ---------------------------------------------------------------------------
# Öğrenci Kaydetme (primary key upsert + ID türetme)
# ---------------------------------------------------------------------------

async def save_students(conn: asyncpg.Connection, records: list[dict], module_config: dict) -> tuple[int, int]:
    saved, errors = 0, 0
    for s in records:
        eid = s.get("eyotek_id", "").strip()
        if not eid:
            name  = s.get("full_name") or s.get("first_name", "BILINMIYOR")
            sezon = s.get("sezon", "")
            eid   = f"NOID_{name}_{sezon}".replace(" ", "_")

        # full_name birleştir
        if "full_name" not in s:
            fn = s.get("first_name", "")
            ln = s.get("last_name", "")
            if fn or ln:
                s["full_name"] = f"{fn} {ln}".strip()

        # eyotek_id → soz_no fallback
        if "eyotek_id" not in s and "soz_no" in s:
            eid = s["soz_no"]

        try:
            await conn.execute("""
                INSERT INTO students (
                    eyotek_id, soz_no, full_name, first_name, last_name,
                    sezon, sube, class_name, program, devre, kur,
                    kayit_tarihi, tc_no, gender, birth_date,
                    phone, parent_name, status, last_sync
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,
                    CURRENT_TIMESTAMP
                )
                ON CONFLICT (eyotek_id) DO UPDATE SET
                    soz_no        = EXCLUDED.soz_no,
                    full_name     = EXCLUDED.full_name,
                    first_name    = EXCLUDED.first_name,
                    last_name     = EXCLUDED.last_name,
                    sezon         = EXCLUDED.sezon,
                    sube          = EXCLUDED.sube,
                    class_name    = EXCLUDED.class_name,
                    program       = EXCLUDED.program,
                    devre         = EXCLUDED.devre,
                    kur           = EXCLUDED.kur,
                    kayit_tarihi  = EXCLUDED.kayit_tarihi,
                    tc_no         = EXCLUDED.tc_no,
                    gender        = EXCLUDED.gender,
                    birth_date    = EXCLUDED.birth_date,
                    phone         = EXCLUDED.phone,
                    parent_name   = EXCLUDED.parent_name,
                    status        = EXCLUDED.status,
                    last_sync     = CURRENT_TIMESTAMP
            """,
                eid,
                s.get("soz_no"), s.get("full_name"),
                s.get("first_name"), s.get("last_name"),
                s.get("sezon"), s.get("sube"), s.get("class_name"),
                s.get("program"), s.get("devre"), s.get("kur"),
                s.get("kayit_tarihi"), s.get("tc_no"), s.get("gender"),
                s.get("birth_date"), s.get("phone"), s.get("parent_name"),
                s.get("status"),
            )
            saved += 1
        except Exception as e:
            logger.warning(f"  Öğrenci kayıt hatası ({eid}): {e}")
            errors += 1

    return saved, errors


# ---------------------------------------------------------------------------
# Exam Kaydetme (sinav_kodu primary key)
# ---------------------------------------------------------------------------

async def save_exams(conn: asyncpg.Connection, records: list[dict]) -> tuple[int, int]:
    saved, errors = 0, 0
    for r in records:
        kod = r.get("sinav_kodu", "").strip()
        if not kod:
            continue
        try:
            await conn.execute("""
                INSERT INTO exams (
                    sinav_kodu, sinav_adi, sinav_turu, sinav_kategori,
                    sube, tarih, sezon, devre, sinif, durum, aktif, last_sync
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11, CURRENT_TIMESTAMP)
                ON CONFLICT (sinav_kodu) DO UPDATE SET
                    sinav_adi      = EXCLUDED.sinav_adi,
                    sinav_turu     = EXCLUDED.sinav_turu,
                    sinav_kategori = EXCLUDED.sinav_kategori,
                    sube           = EXCLUDED.sube,
                    tarih          = EXCLUDED.tarih,
                    sezon          = EXCLUDED.sezon,
                    devre          = EXCLUDED.devre,
                    sinif          = EXCLUDED.sinif,
                    durum          = EXCLUDED.durum,
                    aktif          = EXCLUDED.aktif,
                    last_sync      = CURRENT_TIMESTAMP
            """,
                kod, r.get("sinav_adi"), r.get("sinav_turu"), r.get("sinav_kategori"),
                r.get("sube"), r.get("tarih"), r.get("sezon"), r.get("devre"),
                r.get("sinif"), r.get("durum"), r.get("aktif"),
            )
            saved += 1
        except Exception as e:
            logger.warning(f"  Sınav kayıt hatası ({kod}): {e}")
            errors += 1
    return saved, errors


# ---------------------------------------------------------------------------
# Personel Kaydetme (ik_no primary key)
# ---------------------------------------------------------------------------

async def save_staff(conn: asyncpg.Connection, records: list[dict]) -> tuple[int, int]:
    saved, errors = 0, 0
    for r in records:
        eyotek_id = r.get("eyotek_id", "").strip()
        if not eyotek_id:
            # Fallback: ik_no varsa eyotek_id olarak kullan
            eyotek_id = r.get("ik_no", "").strip()
        if not eyotek_id:
            continue
        # full_name birleştir
        if not r.get("full_name"):
            fn = r.get("first_name", "")
            ln = r.get("last_name", "")
            r["full_name"] = f"{fn} {ln}".strip() if (fn or ln) else ""
        try:
            await conn.execute("""
                INSERT INTO staff (
                    eyotek_id, ik_no, full_name, first_name, last_name,
                    gorev, brans, email, kullanici,
                    sezon, sube, soz_tarihi, cikis_tar,
                    atama_sayi, status, last_sync
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15, CURRENT_TIMESTAMP)
                ON CONFLICT (eyotek_id) DO UPDATE SET
                    ik_no      = EXCLUDED.ik_no,
                    full_name  = EXCLUDED.full_name,
                    first_name = EXCLUDED.first_name,
                    last_name  = EXCLUDED.last_name,
                    gorev      = EXCLUDED.gorev,
                    brans      = EXCLUDED.brans,
                    email      = EXCLUDED.email,
                    kullanici  = EXCLUDED.kullanici,
                    sezon      = EXCLUDED.sezon,
                    sube       = EXCLUDED.sube,
                    soz_tarihi = EXCLUDED.soz_tarihi,
                    cikis_tar  = EXCLUDED.cikis_tar,
                    atama_sayi = EXCLUDED.atama_sayi,
                    status     = EXCLUDED.status,
                    last_sync  = CURRENT_TIMESTAMP
            """,
                eyotek_id,
                r.get("ik_no", ""),
                r.get("full_name", ""),
                r.get("first_name", ""),
                r.get("last_name", ""),
                r.get("gorev", r.get("gorevi", "")),
                r.get("brans", ""),
                r.get("email", ""),
                r.get("kullanici", ""),
                r.get("sezon", ""),
                r.get("sube", ""),
                r.get("soz_tarihi", ""),
                r.get("cikis_tar", ""),
                r.get("atama_sayi", ""),
                r.get("status", "Aktif"),
            )
            saved += 1
        except Exception as e:
            logger.warning(f"  Personel kayıt hatası ({eyotek_id}): {e}")
            errors += 1
    return saved, errors


# ---------------------------------------------------------------------------
# Jenerik Snapshot Kaydetme (SERIAL pk'li tablolar için)
# ---------------------------------------------------------------------------

async def save_snapshot(
    conn: asyncpg.Connection,
    records: list[dict],
    table: str,
    columns: list[str],
) -> tuple[int, int]:
    """
    Tüm mevcut kayıtları sil, yenilerini ekle.
    columns = tablodaki alan adları listesi (SERIAL id ve last_sync hariç)
    """
    await conn.execute(f"DELETE FROM {table}")
    saved, errors = 0, 0
    placeholders = ", ".join(f"${i+1}" for i in range(len(columns)))
    col_names    = ", ".join(columns)
    sql = (
        f"INSERT INTO {table} ({col_names}, last_sync) "
        f"VALUES ({placeholders}, CURRENT_TIMESTAMP)"
    )
    for r in records:
        vals = [r.get(col) for col in columns]
        try:
            await conn.execute(sql, *vals)
            saved += 1
        except Exception as e:
            logger.warning(f"  Snapshot kayıt hatası ({table}): {e}")
            errors += 1
    return saved, errors


# ---------------------------------------------------------------------------
# Ana Modül Kaydetme Dispatcher
# ---------------------------------------------------------------------------

ATTENDANCE_COLS = [
    "eyotek_id", "soz_no", "full_name", "first_name", "last_name",
    "sube", "tarih", "ders_no", "saat", "gun", "durum",
    "izin_turu", "aciklama", "mesaj", "sezon",
]

EXAM_RESULTS_COLS = [
    "sezon", "sube", "sinav_kodu", "sinav_adi", "sinav_turu",
    "tarih", "devre", "sinif", "durum", "net", "puan",
    "sira", "okul_sira", "genel_sira", "dogru", "yanlis", "bos",
]

OVERDUE_COLS = [
    "eyotek_id", "soz_no", "full_name", "first_name", "last_name",
    "sezon", "sube", "tutar", "borc", "odeme", "bakiye",
    "vade_tarihi", "tarih", "taksit_no", "mesaj", "aciklama",
]


async def save_module_records(
    records: list[dict],
    module_key: str,
    module_config: dict,
) -> None:
    """Modül kayıtlarını PostgreSQL'e kaydet."""
    if not records:
        logger.warning(f"⚠️  {module_config['name']}: kaydedilecek veri yok.")
        return

    if not CONFIG["database_url"]:
        logger.error("DATABASE_URL ayarlanmamış!")
        return

    conn = await asyncpg.connect(CONFIG["database_url"])
    try:
        await ensure_module_table(conn, module_config)

        if module_key == "students":
            saved, errors = await save_students(conn, records, module_config)

        elif module_key == "exams":
            saved, errors = await save_exams(conn, records)

        elif module_key == "staff":
            saved, errors = await save_staff(conn, records)

        elif module_key == "attendance":
            # full_name türet
            for r in records:
                if "full_name" not in r:
                    fn = r.get("first_name", "")
                    ln = r.get("last_name", "")
                    if fn or ln:
                        r["full_name"] = f"{fn} {ln}".strip()
            saved, errors = await save_snapshot(conn, records, "attendance", ATTENDANCE_COLS)

        elif module_key == "exam_results":
            saved, errors = await save_snapshot(conn, records, "exam_results", EXAM_RESULTS_COLS)

        elif module_key == "overdue":
            # full_name türet
            for r in records:
                if "full_name" not in r:
                    fn = r.get("first_name", "")
                    ln = r.get("last_name", "")
                    if fn or ln:
                        r["full_name"] = f"{fn} {ln}".strip()
            saved, errors = await save_snapshot(conn, records, "overdue_payments", OVERDUE_COLS)

        else:
            logger.warning(f"Bilinmeyen modül: {module_key}")
            saved, errors = 0, 0

        await save_sync_log(conn, module_key, saved, errors)
        logger.success(f"✅ {module_config['name']}: {saved} kayıt ({errors} hata)")

    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Ana İş Akışı
# ---------------------------------------------------------------------------

async def run_scraping_mode(selected_modules: list[str] | None = None) -> None:
    """
    Scraping modu.
    selected_modules=None → tüm modüller
    selected_modules=['students', 'attendance'] → sadece bunlar
    """
    logger.info("🕷️  Scraping modu başlıyor...")

    cookies = await get_valid_session()
    if not cookies:
        logger.error("❌ Session alınamadı. Program sonlandırılıyor.")
        return

    all_configs = get_module_configs()

    if selected_modules:
        run_keys = [k for k in selected_modules if k in all_configs]
        unknown  = [k for k in selected_modules if k not in all_configs]
        if unknown:
            logger.warning(f"⚠️  Bilinmeyen modül(ler) atlandı: {unknown}")
    else:
        run_keys = list(all_configs.keys())

    logger.info(f"📋 Çalışacak modüller: {run_keys}")

    summary = []
    for key in run_keys:
        cfg = all_configs[key]
        try:
            records = await scrape_module_via_browser(cookies, cfg)
            await save_module_records(records, key, cfg)
            summary.append((cfg["name"], len(records), "✅"))
        except Exception as e:
            logger.error(f"❌ {cfg['name']} modülü başarısız: {e}")
            summary.append((cfg["name"], 0, "❌"))

    # Özet tablo
    print("\n" + "=" * 55)
    print("📊 SENKRONIZASYON ÖZETİ")
    print("=" * 55)
    for name, count, status in summary:
        print(f"  {status}  {name:<35} {count:>5} kayıt")
    print("=" * 55)


async def main() -> None:
    logger.info("🚀 FermatAI Eyotek Agent v10 başlıyor...")
    logger.info(f"   Hedef: {CONFIG['base_url']}")

    # Komut satırından modül seçimi
    selected = sys.argv[1:] if len(sys.argv) > 1 else None
    if selected:
        logger.info(f"   Seçili modüller: {selected}")
    else:
        logger.info("   Tüm modüller çalışacak.")

    mode = CONFIG["agent_mode"].lower()
    if mode == "scraping":
        await run_scraping_mode(selected)
    else:
        logger.error(f"❌ Bilinmeyen AGENT_MODE: '{mode}'.")


if __name__ == "__main__":
    asyncio.run(main())
