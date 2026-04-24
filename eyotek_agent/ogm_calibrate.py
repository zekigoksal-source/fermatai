"""OGM'den gerçek puanlarla katsayı kalibrasyonu."""
import asyncio, sys, io, json, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

async def ogm_quick(netleri_flat: list, diploma: int = 80) -> list:
    """OGM'ye netleri gonder, puanlari al. netleri_flat: [TrD,TrY, SosD,SosY, MatD,MatY, FenD,FenY, ...AYT 24 select..., ] """
    from playwright.async_api import async_playwright
    pw = await async_playwright().start()
    browser = await pw.chromium.connect_over_cdp('http://localhost:9222')
    page = await browser.contexts[0].new_page()
    try:
        await page.goto('https://ogmmateryal.eba.gov.tr/yks-puan-hesaplama', timeout=15000)
        await page.wait_for_timeout(2000)
        # Diploma
        d = await page.query_selector('#puan1')
        if d: await d.fill(str(diploma))
        # Select'ler
        selects = await page.query_selector_all('.form-select')
        for i, sel in enumerate(selects):
            if i < len(netleri_flat):
                try: await sel.select_option(str(netleri_flat[i]))
                except: pass
        await page.wait_for_timeout(500)
        # Hesapla
        for b in await page.query_selector_all('button'):
            if 'SONUCU' in (await b.text_content() or ''):
                await b.click(); break
        await page.wait_for_timeout(3000)
        txt = await page.evaluate('document.body.innerText')
        scores = re.findall(r'\d{3}\.\d{2,3}', txt)
        return [float(s) for s in scores[:10]]
    finally:
        await page.close(); await pw.stop()

async def main():
    # 32 select: TYT(8) + AYT(24: Ede2, Tar12, Cog12, Tar22, Cog22, Fels2, Din2, Mat2, Fiz2, Kim2, Bio2, YDT2)
    tests = [
        # Test A: Sadece TYT (AYT sifir)
        {"label": "TYT_ONLY (Tr30/4 Sos10/4 Mat20/8 Fen10/4)",
         "flat": [30,4, 10,4, 20,8, 10,4] + [0]*24, "diploma": 80},
        # Test B: Sadece TYT yuksek
        {"label": "TYT_HIGH (Tr38/2 Sos18/2 Mat36/4 Fen18/2)",
         "flat": [38,2, 18,2, 36,4, 18,2] + [0]*24, "diploma": 85},
        # Test C: SAY profili (TYT + AYT fen)
        {"label": "SAY (Tr34/2 Sos15/3 Mat30/5 Fen16/2 + AYT Mat35/3 Fiz12/1 Kim11/1 Bio10/1)",
         "flat": [34,2, 15,3, 30,5, 16,2,  0,0,0,0,0,0,0,0,0,0,0,0,0,0, 35,3, 12,1, 11,1, 10,1, 0,0], "diploma": 85},
        # Test D: Dusuk profil
        {"label": "LOW (Tr20/10 Sos5/5 Mat10/10 Fen5/5)",
         "flat": [20,10, 5,5, 10,10, 5,5] + [0]*24, "diploma": 75},
    ]

    from puan_hesaplama import hesapla_tyt, hesapla_say

    for t in tests:
        print(f"\n=== {t['label']} ===")
        scores = await ogm_quick(t['flat'], t['diploma'])
        print(f"  OGM puanlar: {scores}")

        # Netleri hesapla
        f = t['flat']
        tr_net = f[0] - f[1]*0.25
        sos_net = f[2] - f[3]*0.25
        mat_net = f[4] - f[5]*0.25
        fen_net = f[6] - f[7]*0.25

        my_tyt = hesapla_tyt(tr_net, sos_net, mat_net, fen_net, t['diploma'])
        print(f"  Benim TYT: ham={my_tyt['ham_puan']}, yer={my_tyt['yerlestirme_puani']}")
        if scores:
            ogm_ham = scores[0]
            ogm_yer = scores[1] if len(scores) > 1 else None
            print(f"  OGM TYT:   ham={ogm_ham}, yer={ogm_yer}")
            print(f"  FARK (ham): {my_tyt['ham_puan'] - ogm_ham:+.1f}")

        # SAY varsa
        if sum(f[8:]) > 0:
            ayt_mat_net = f[22] - f[23]*0.25
            ayt_fiz_net = f[24] - f[25]*0.25
            ayt_kim_net = f[26] - f[27]*0.25
            ayt_bio_net = f[28] - f[29]*0.25
            my_say = hesapla_say(tr_net, sos_net, mat_net, fen_net,
                                  ayt_mat_net, ayt_fiz_net, ayt_kim_net, ayt_bio_net, t['diploma'])
            print(f"  Benim SAY: ham={my_say['ham_puan']}, yer={my_say['yerlestirme_puani']}")
            if len(scores) >= 6:
                print(f"  OGM SAY:   ham={scores[4]}, yer={scores[5]}")
                print(f"  FARK (yer): {my_say['yerlestirme_puani'] - scores[5]:+.1f}")

asyncio.run(main())
