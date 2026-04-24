"""OGM Puan Hesaplama API testi — CDP ile form doldur, sonucu al, kalibre et."""
import asyncio, sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

async def ogm_hesapla(netleri: dict, diploma: int = 85) -> dict:
    """OGM sitesinde puan hesapla — CDP ile form doldur, sonucu al.

    netleri: {
        'turkce_d': 34, 'turkce_y': 2,     # TYT Türkçe doğru/yanlış
        'sosyal_d': 15, 'sosyal_y': 3,     # TYT Sosyal
        'mat_d': 30, 'mat_y': 5,           # TYT Matematik
        'fen_d': 16, 'fen_y': 2,           # TYT Fen
        'ayt_mat_d': 35, 'ayt_mat_y': 3,  # AYT Matematik
        'ayt_fiz_d': 12, 'ayt_fiz_y': 1,  # AYT Fizik
        'ayt_kim_d': 11, 'ayt_kim_y': 1,  # AYT Kimya
        'ayt_bio_d': 10, 'ayt_bio_y': 1,  # AYT Biyoloji
    }
    """
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    browser = await pw.chromium.connect_over_cdp('http://localhost:9222')
    ctx = browser.contexts[0]
    page = await ctx.new_page()

    try:
        await page.goto('https://ogmmateryal.eba.gov.tr/yks-puan-hesaplama', timeout=15000)
        await page.wait_for_timeout(2000)

        # Diploma notu gir
        diploma_input = await page.query_selector('#puan1')
        if diploma_input:
            await diploma_input.fill(str(diploma))

        # Select'leri doldur — sıra: TYT(Tr D,Y | Sos D,Y | Mat D,Y | Fen D,Y) + AYT...
        selects = await page.query_selector_all('.form-select')

        # İlk 8 select: TYT (4 ders × 2: doğru + yanlış)
        tyt_values = [
            netleri.get('turkce_d', 0), netleri.get('turkce_y', 0),
            netleri.get('sosyal_d', 0), netleri.get('sosyal_y', 0),
            netleri.get('mat_d', 0), netleri.get('mat_y', 0),
            netleri.get('fen_d', 0), netleri.get('fen_y', 0),
        ]

        # AYT select'leri: Edebiyat(2) + Tarih1(2) + Cog1(2) + Tarih2(2) + Cog2(2) + Felsefe(2) + Din(2) + Mat(2) + Fiz(2) + Kim(2) + Bio(2) + YDT(2) = 24 select
        ayt_values = [
            0, 0,  # Edebiyat D, Y
            0, 0,  # Tarih-1 D, Y
            0, 0,  # Coğrafya-1 D, Y
            0, 0,  # Tarih-2 D, Y
            0, 0,  # Coğrafya-2 D, Y
            0, 0,  # Felsefe D, Y
            0, 0,  # Din D, Y
            netleri.get('ayt_mat_d', 0), netleri.get('ayt_mat_y', 0),
            netleri.get('ayt_fiz_d', 0), netleri.get('ayt_fiz_y', 0),
            netleri.get('ayt_kim_d', 0), netleri.get('ayt_kim_y', 0),
            netleri.get('ayt_bio_d', 0), netleri.get('ayt_bio_y', 0),
            0, 0,  # YDT D, Y
        ]

        all_values = tyt_values + ayt_values

        for i, sel in enumerate(selects):
            if i < len(all_values):
                val = str(all_values[i])
                try:
                    await sel.select_option(val)
                except Exception:
                    pass

        await page.wait_for_timeout(500)

        # HESAPLA butonuna tıkla
        buttons = await page.query_selector_all('button')
        for b in buttons:
            txt = (await b.text_content() or '').strip()
            if 'SONUCU' in txt or 'HESAPLA' in txt:
                await b.click()
                break

        await page.wait_for_timeout(3000)

        # Sonucu oku
        result_text = await page.evaluate('document.body.innerText')

        # Puanları parse et
        results = {}
        for line in result_text.split('\n'):
            line = line.strip()
            if 'TYT' in line and ('puan' in line.lower() or any(c.isdigit() for c in line)):
                results['raw_tyt'] = line
            if 'SAY' in line and any(c.isdigit() for c in line):
                results['raw_say'] = line
            if 'EA' in line and any(c.isdigit() for c in line) and 'EA' == line[:2]:
                results['raw_ea'] = line

        # Tüm sayısal sonuçları yakala
        import re
        numbers = re.findall(r'\d{3}[.,]\d{2,3}', result_text)
        if numbers:
            results['all_scores'] = numbers[:10]

        return results

    finally:
        await page.close()
        await pw.stop()


async def main():
    # Test 1: Hacettepe Tıp profili (gerçek netler)
    print("=== TEST 1: Hacettepe Tip profili ===")
    r = await ogm_hesapla({
        'turkce_d': 34, 'turkce_y': 1,     # ~33.75 net
        'sosyal_d': 19, 'sosyal_y': 1,     # ~18.75 net
        'mat_d': 39, 'mat_y': 1,           # ~38.75 net
        'fen_d': 20, 'fen_y': 0,           # 20 net
        'ayt_mat_d': 38, 'ayt_mat_y': 2,  # ~37.5 net
        'ayt_fiz_d': 14, 'ayt_fiz_y': 0,  # 14 net
        'ayt_kim_d': 13, 'ayt_kim_y': 0,  # 13 net
        'ayt_bio_d': 12, 'ayt_bio_y': 1,  # ~11.75 net
    }, diploma=90)
    print(f"OGM sonuc: {json.dumps(r, indent=2, ensure_ascii=False)}")

    # Test 2: Orta seviye öğrenci
    print("\n=== TEST 2: Orta seviye ===")
    r2 = await ogm_hesapla({
        'turkce_d': 30, 'turkce_y': 4,     # ~29 net
        'sosyal_d': 10, 'sosyal_y': 4,     # ~9 net
        'mat_d': 20, 'mat_y': 8,           # ~18 net
        'fen_d': 10, 'fen_y': 4,           # ~9 net
        'ayt_mat_d': 0, 'ayt_mat_y': 0,
        'ayt_fiz_d': 0, 'ayt_fiz_y': 0,
        'ayt_kim_d': 0, 'ayt_kim_y': 0,
        'ayt_bio_d': 0, 'ayt_bio_y': 0,
    }, diploma=80)
    print(f"OGM sonuc: {json.dumps(r2, indent=2, ensure_ascii=False)}")


if __name__ == '__main__':
    asyncio.run(main())
