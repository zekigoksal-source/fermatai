"""SAY/EA katsayı kalibrasyonu — OGM'den 4+ test case ile reverse engineering."""
import asyncio, sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

async def ogm_test(flat: list, diploma: int) -> list:
    from playwright.async_api import async_playwright
    pw = await async_playwright().start()
    browser = await pw.chromium.connect_over_cdp('http://localhost:9222')
    page = await browser.contexts[0].new_page()
    try:
        await page.goto('https://ogmmateryal.eba.gov.tr/yks-puan-hesaplama', timeout=15000)
        await page.wait_for_timeout(2000)
        d = await page.query_selector('#puan1')
        if d: await d.fill(str(diploma))
        selects = await page.query_selector_all('.form-select')
        for i, sel in enumerate(selects):
            if i < len(flat):
                try: await sel.select_option(str(flat[i]))
                except: pass
        await page.wait_for_timeout(500)
        for b in await page.query_selector_all('button'):
            if 'SONUCU' in (await b.text_content() or ''):
                await b.click(); break
        await page.wait_for_timeout(3000)
        txt = await page.evaluate('document.body.innerText')
        scores = [float(s) for s in re.findall(r'\d{3}\.\d{2,3}', txt)]
        return scores[:10]
    finally:
        await page.close(); await pw.stop()

async def main():
    # SAY profiller — 32 select: TYT(8) + AYT(24)
    # AYT sira: Ede(2) Tar1(2) Cog1(2) Tar2(2) Cog2(2) Fels(2) Din(2) Mat(2) Fiz(2) Kim(2) Bio(2) YDT(2)
    # AYT SAY icin: sadece Mat+Fiz+Kim+Bio (index 14-21 icinde: Mat=14,15 Fiz=16,17 Kim=18,19 Bio=20,21)

    tests = [
        # SAY Test A: Yuksek (Hacettepe profili)
        {"label": "SAY_HIGH",
         "flat": [34,1, 19,1, 39,1, 20,0,  # TYT: Tr33.75 Sos18.75 Mat38.75 Fen20
                  0,0,0,0,0,0,0,0,0,0,0,0,0,0,  # AYT Sozel bos (14 select)
                  38,2, 14,0, 13,0, 12,1,  # AYT: Mat37.5 Fiz14 Kim13 Bio11.75
                  0,0],  # YDT bos
         "diploma": 90},
        # SAY Test B: Orta-yuksek
        {"label": "SAY_MID_HIGH",
         "flat": [30,4, 12,4, 25,5, 14,2,  # TYT: Tr29 Sos11 Mat23.75 Fen13.5
                  0,0,0,0,0,0,0,0,0,0,0,0,0,0,
                  30,5, 10,2, 9,2, 8,2,  # AYT: Mat28.75 Fiz9.5 Kim8.5 Bio7.5
                  0,0],
         "diploma": 85},
        # SAY Test C: Orta
        {"label": "SAY_MID",
         "flat": [28,6, 10,5, 18,8, 10,4,  # TYT: Tr26.5 Sos8.75 Mat16 Fen9
                  0,0,0,0,0,0,0,0,0,0,0,0,0,0,
                  20,8, 7,3, 6,3, 5,3,  # AYT: Mat18 Fiz6.25 Kim5.25 Bio4.25
                  0,0],
         "diploma": 80},
        # SAY Test D: Dusuk
        {"label": "SAY_LOW",
         "flat": [25,8, 8,6, 12,10, 6,6,  # TYT: Tr23 Sos6.5 Mat9.5 Fen4.5
                  0,0,0,0,0,0,0,0,0,0,0,0,0,0,
                  10,10, 4,4, 3,3, 3,3,  # AYT: Mat7.5 Fiz3 Kim2.25 Bio2.25
                  0,0],
         "diploma": 75},
        # EA Test A: Orta-yuksek
        {"label": "EA_MID",
         "flat": [32,4, 14,3, 28,6, 12,4,  # TYT: Tr31 Sos13.25 Mat26.5 Fen11
                  20,4, 8,2, 5,1,  # AYT Ede: 19 Tar1:7.5 Cog1:4.75
                  0,0,0,0,0,0,0,0,  # Tar2,Cog2,Fels,Din bos (SAY icin)
                  25,5,  # AYT Mat: 23.75
                  0,0,0,0,0,0,  # Fiz,Kim,Bio bos (EA icin)
                  0,0],
         "diploma": 85},
    ]

    for t in tests:
        print(f"\n=== {t['label']} ===")
        scores = await ogm_test(t['flat'], t['diploma'])
        f = t['flat']
        # Netleri hesapla
        tr = f[0]-f[1]*0.25; sos = f[2]-f[3]*0.25; mat = f[4]-f[5]*0.25; fen = f[6]-f[7]*0.25
        print(f"  TYT: Tr={tr:.2f} Sos={sos:.2f} Mat={mat:.2f} Fen={fen:.2f}")
        # AYT SAY netleri
        ayt_mat = f[22]-f[23]*0.25; ayt_fiz = f[24]-f[25]*0.25
        ayt_kim = f[26]-f[27]*0.25; ayt_bio = f[28]-f[29]*0.25
        if ayt_mat > 0:
            print(f"  AYT: Mat={ayt_mat:.2f} Fiz={ayt_fiz:.2f} Kim={ayt_kim:.2f} Bio={ayt_bio:.2f}")
        # AYT EA netleri
        if f[8] > 0:  # Edebiyat
            ayt_ede = f[8]-f[9]*0.25; ayt_tar1 = f[10]-f[11]*0.25; ayt_cog1 = f[12]-f[13]*0.25
            print(f"  AYT EA: Ede={ayt_ede:.2f} Tar1={ayt_tar1:.2f} Cog1={ayt_cog1:.2f} Mat={ayt_mat:.2f}")

        print(f"  OGM puanlar: {scores}")
        # TYT=idx0,1 | EA=idx2,3 | SAY=idx4,5
        if len(scores) >= 6:
            print(f"  TYT ham={scores[0]} yer={scores[1]}")
            print(f"  EA  ham={scores[2]} yer={scores[3]}")
            print(f"  SAY ham={scores[4]} yer={scores[5]}")
        elif len(scores) >= 2:
            print(f"  TYT ham={scores[0]} yer={scores[1]}")

asyncio.run(main())
