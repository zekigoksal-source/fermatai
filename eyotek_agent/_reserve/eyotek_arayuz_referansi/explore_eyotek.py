"""
FermatAI - Eyotek Site Keşif Scripti
=====================================
Çalıştır: python explore_eyotek.py
- Mevcut Chrome'a CDP ile bağlanır (port 9222)
- Sol menüdeki tüm linkleri ziyaret eder
- Her sayfada mevcut tabloların başlıklarını, form alanlarını kaydeder
- Sonucu site_map.json ve site_map.txt olarak yazar
"""

import asyncio
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.async_api import async_playwright
from loguru import logger

CDP_URL = "http://127.0.0.1:9222"
BASE_URL = "https://fermat.eyotek.com/v1"
OUTPUT_JSON = Path("site_map.json")
OUTPUT_TXT = Path("site_map.txt")

# Ziyaret edilecek / edilmeyecek pattern'lar
SKIP_PATTERNS = [
    "/logout", "/signout", "/cikis",
    "javascript:", "mailto:", "#",
    "/Pages/Staff/home",  # ana sayfa, başlangıçta ziyaret edilecek
]

visited = set()
site_map = {}


def should_skip(url: str) -> bool:
    if not url:
        return True
    for p in SKIP_PATTERNS:
        if p in url.lower():
            return True
    if not url.startswith("http"):
        return True
    if "eyotek.com" not in url:
        return True
    return False


async def extract_page_info(page) -> dict:
    """Sayfadaki önemli yapıyı çıkar."""
    info = {
        "title": await page.title(),
        "url": page.url,
        "tables": [],
        "forms": [],
        "buttons": [],
        "sub_links": [],
    }

    # Tablo başlıkları
    try:
        tables = await page.locator("table").all()
        for i, tbl in enumerate(tables[:5]):  # max 5 tablo
            headers = await tbl.locator("th, tr:first-child td").all_text_contents()
            headers = [h.strip() for h in headers if h.strip()]
            row_count = await tbl.locator("tbody tr, tr").count()
            if headers:
                info["tables"].append({
                    "index": i,
                    "headers": headers[:20],
                    "row_count": row_count
                })
    except Exception:
        pass

    # Form alanları
    try:
        inputs = await page.locator("input:not([type=hidden]), select, textarea").all()
        for inp in inputs[:15]:
            try:
                label = await inp.get_attribute("placeholder") or \
                        await inp.get_attribute("name") or \
                        await inp.get_attribute("id") or "?"
                itype = await inp.get_attribute("type") or inp.element_handle() and "select"
                info["forms"].append(f"{itype}:{label}")
            except Exception:
                pass
    except Exception:
        pass

    # Görünür buton/link metinleri (sayfaya özel)
    try:
        btns = await page.locator("button, .btn, input[type=submit]").all()
        for b in btns[:10]:
            try:
                txt = (await b.inner_text()).strip()
                if txt and len(txt) < 40:
                    info["buttons"].append(txt)
            except Exception:
                pass
    except Exception:
        pass

    # İçerik alanındaki linkler (menü hariç)
    try:
        content_links = await page.locator(
            "main a, .content a, #content a, .panel a, table a"
        ).all()
        for lnk in content_links[:20]:
            try:
                href = await lnk.get_attribute("href")
                txt = (await lnk.inner_text()).strip()
                if href and txt and "eyotek.com" in urljoin(BASE_URL, href):
                    full = urljoin(BASE_URL, href)
                    info["sub_links"].append({"text": txt[:50], "url": full})
            except Exception:
                pass
    except Exception:
        pass

    return info


async def get_nav_links(page) -> list[dict]:
    """Sayfadaki tüm /Pages/ linklerini JS ile topla."""
    links = []
    try:
        raw = await page.evaluate("""
            () => {
                return Array.from(document.querySelectorAll('a[href]'))
                    .map(a => ({
                        text: (a.innerText || a.title || a.getAttribute('data-title') || '').trim(),
                        href: a.href
                    }))
                    .filter(x =>
                        x.href.includes('/Pages/') &&
                        x.href.includes('eyotek.com') &&
                        x.text.length > 0 &&
                        x.text.length < 80
                    );
            }
        """)
        seen = set()
        for item in raw:
            url = item["href"]
            txt = item["text"]
            if url not in seen and not should_skip(url):
                seen.add(url)
                links.append({"text": txt, "url": url})
        logger.info(f"📋 JS ile {len(links)} link bulundu.")
    except Exception as e:
        logger.warning(f"Nav link hatası: {e}")
    return links


async def visit_page(page, url: str, depth: int = 0) -> dict | None:
    """Bir sayfayı ziyaret et ve bilgileri döndür."""
    if url in visited or depth > 2:
        return None
    visited.add(url)

    logger.info(f"{'  ' * depth}📄 [{depth}] {url}")

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(1.5)  # Dinamik içerik için bekle

        # Sayfa login'e yönlendirdiyse dur
        current = page.url
        if "/v1/" not in current and "eyotek.com" in current:
            logger.warning(f"  Yönlendirme: {current} → session sona ermiş olabilir")
            return None

        info = await extract_page_info(page)
        info["depth"] = depth

        logger.info(f"  {'  ' * depth}↳ '{info['title']}' | "
                    f"tablolar: {len(info['tables'])} | "
                    f"butonlar: {info['buttons'][:3]}")

        return info

    except Exception as e:
        logger.warning(f"  Hata ({url}): {e}")
        return None


async def main():
    logger.info("🔍 Eyotek Site Keşfi başlıyor...")
    logger.info(f"  Chrome CDP: {CDP_URL}")

    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
        except Exception as e:
            logger.error(f"❌ Chrome'a bağlanılamadı: {e}")
            logger.error("   Chrome'un açık ve port 9222'de çalıştığından emin olun.")
            logger.error("   eyotek_agent.py'yi çalıştırıp giriş yapın.")
            return

        context = browser.contexts[0]
        page = context.pages[0] if context.pages else await context.new_page()

        # Ana sayfaya git ve menüyü al
        home_url = f"{BASE_URL}/Pages/Staff/home"
        logger.info(f"🏠 Ana sayfa ziyaret ediliyor: {home_url}")
        await page.goto(home_url, wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(2)

        # Menü linklerini topla
        nav_links = await get_nav_links(page)
        logger.info(f"📋 {len(nav_links)} navigasyon linki bulundu.")

        # Tekrar etmeyen linkleri tut
        unique_links = {}
        for lnk in nav_links:
            u = lnk["url"]
            if u not in unique_links:
                unique_links[u] = lnk["text"]

        logger.info(f"🔗 Benzersiz sayfa sayısı: {len(unique_links)}")

        # Her sayfayı ziyaret et
        results = {}

        for url, text in unique_links.items():
            if url in visited:
                continue
            info = await visit_page(page, url, depth=0)
            if info:
                results[url] = {
                    "menu_text": text,
                    **info
                }

                # Alt linkleri de ziyaret et (depth=1)
                for sub in info.get("sub_links", []):
                    sub_url = sub["url"]
                    if sub_url not in visited and sub_url not in unique_links:
                        sub_info = await visit_page(page, sub_url, depth=1)
                        if sub_info:
                            results[sub_url] = {
                                "menu_text": f"{text} > {sub['text']}",
                                **sub_info
                            }

            await asyncio.sleep(0.5)

        await browser.close()

    # JSON kaydet
    OUTPUT_JSON.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # Okunabilir TXT raporu oluştur
    lines = ["=" * 70, "FERMAT EYOTEK SİTE HARİTASI", "=" * 70, ""]
    for url, data in results.items():
        lines.append(f"📍 {data.get('menu_text', '?')} [{data.get('depth', 0)}. seviye]")
        lines.append(f"   URL: {url}")
        lines.append(f"   Başlık: {data.get('title', '?')}")

        for tbl in data.get("tables", []):
            lines.append(f"   📊 Tablo {tbl['index']}: {tbl['headers']} ({tbl['row_count']} satır)")

        if data.get("forms"):
            lines.append(f"   📝 Form alanları: {data['forms'][:8]}")

        if data.get("buttons"):
            lines.append(f"   🔘 Butonlar: {data['buttons'][:5]}")

        lines.append("")

    OUTPUT_TXT.write_text("\n".join(lines), encoding="utf-8")

    logger.success(f"✅ Keşif tamamlandı!")
    logger.success(f"   📊 {len(results)} sayfa keşfedildi")
    logger.success(f"   📄 Rapor: {OUTPUT_TXT.absolute()}")
    logger.success(f"   🗺️  JSON: {OUTPUT_JSON.absolute()}")


if __name__ == "__main__":
    asyncio.run(main())
