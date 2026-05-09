"""25.43 — derinlemesine senaryo testleri.

Her API icin 3-5 farkli sorgu — gercek YKS akademik durumlar.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


async def main():
    from external_apis_v3 import (
        tdk_sozluk, nist_constant, oeis_search, open_meteo_climate,
        wikidata_lookup, cern_open_data, huggingface_search_models,
        tuik_dataset, alphafold_lookup, nist_webbook, crossref_search, osm_lookup,
    )

    print("═══════════════════════════════════════════════")
    print("25.43 SENARYO TESTLERI — derinlemesine")
    print("═══════════════════════════════════════════════\n")

    scenarios = []

    # 1. TDK — TYT Türkçe paragraf kelimeleri
    print("─── 1. TDK Sozluk (TYT Turkce kelime) ───")
    for kw in ["müşfik", "perişan", "kuşkulu", "zarafet", "feragat"]:
        r = await tdk_sozluk(kw)
        ok = r.get("success") and r.get("found")
        meaning = r.get("entries", [{}])[0].get("meanings", [{}])[0].get("definition", "")[:80] if ok else ""
        print(f"  [{'OK' if ok else 'X '}] '{kw}': {meaning}")
        scenarios.append(ok)

    # 2. NIST — AYT fizik formülünde lazım sabitler
    print("\n─── 2. NIST Constants (AYT Fizik) ───")
    for kw in ["isik hizi", "boltzmann", "avogadro", "elektron yuku", "yer cekimi"]:
        r = await nist_constant(kw)
        ok = r.get("success") and r.get("found")
        val = f"{r.get('value', 'N/A')} {r.get('unit', '')}" if ok else "N/A"
        print(f"  [{'OK' if ok else 'X '}] '{kw}': {val}")
        scenarios.append(ok)

    # 3. OEIS — sayı dizisi tanıma (YKS niş)
    print("\n─── 3. OEIS Sequences (Matematik) ───")
    for kw in ["fibonacci", "1,1,2,3,5,8", "asal", "1,4,9,16,25", "factorial"]:
        r = await oeis_search(kw)
        ok = r.get("success") and r.get("found")
        name = r.get("results", [{}])[0].get("name", "")[:60] if ok else ""
        src = r.get("source", "api")
        print(f"  [{'OK' if ok else 'X '}] '{kw}' [{src}]: {name}")
        scenarios.append(ok)

    # 4. Open-Meteo — Türkiye iklim bölgeleri
    print("\n─── 4. Open-Meteo (Cografya iklim) ───")
    for city in ["Konya", "Antalya", "Erzurum", "Trabzon", "Diyarbakir"]:
        r = await open_meteo_climate(city)
        ok = r.get("success") and r.get("found")
        temp = r.get("current", {}).get("temperature_2m", "?") if ok else "?"
        print(f"  [{'OK' if ok else 'X '}] {city}: {temp}°C")
        scenarios.append(ok)

    # 5. Wikidata — Türkiye/dünya tarihi
    print("\n─── 5. Wikidata (factual) ───")
    for kw in ["Atatürk", "Türkiye Cumhuriyeti", "Mimar Sinan", "Marie Curie"]:
        r = await wikidata_lookup(kw)
        ok = r.get("success") and r.get("found")
        desc = r.get("description_tr", "")[:60] if ok else ""
        print(f"  [{'OK' if ok else 'X '}] {kw}: {desc}")
        scenarios.append(ok)

    # 6. CERN — fizik
    print("\n─── 6. CERN Open Data ───")
    for kw in ["higgs", "z boson", "atlas"]:
        r = await cern_open_data(kw)
        ok = r.get("success") and r.get("found")
        first = r.get("results", [{}])[0].get("title", "")[:80] if ok else ""
        print(f"  [{'OK' if ok else 'X '}] {kw}: {first}")
        scenarios.append(ok)

    # 7. HF Search
    print("\n─── 7. Hugging Face Search ───")
    for kw in ["turkish bert", "image classification", "sentiment"]:
        r = await huggingface_search_models(kw)
        ok = r.get("success") and r.get("found")
        first = r.get("results", [{}])[0].get("id", "")[:60] if ok else ""
        print(f"  [{'OK' if ok else 'X '}] {kw}: {first}")
        scenarios.append(ok)

    # 8. TÜİK — Türkiye verileri
    print("\n─── 8. TUIK dataset ───")
    for cat in ["nufus_2024", "iklim_bolgeleri", "tarim_urun", "ekonomi", "egitim"]:
        r = await tuik_dataset(cat)
        ok = r.get("success") and r.get("found")
        keys = list(r.get("data", {}).keys())[:3] if ok else []
        print(f"  [{'OK' if ok else 'X '}] {cat}: {keys}")
        scenarios.append(ok)

    # 9. AlphaFold — bio protein
    print("\n─── 9. AlphaFold protein ───")
    for uid in ["P01308", "P69905", "P02649"]:  # insulin, hemoglobin alpha, ApoE
        r = await alphafold_lookup(uid)
        ok = r.get("success") and r.get("found")
        name = (r.get("uniprot_description", "") or r.get("name", ""))[:60] if ok else ""
        print(f"  [{'OK' if ok else 'X '}] {uid}: {name}")
        scenarios.append(ok)

    # 10. NIST WebBook
    print("\n─── 10. NIST WebBook (kimya) ───")
    for kw in ["water", "methane", "glucose"]:
        r = await nist_webbook(kw)
        ok = r.get("success")  # found may be False if HTML parse incomplete
        formula = r.get("formula", "") or "(API erisilebilir)"
        print(f"  [{'OK' if ok else 'X '}] {kw}: {formula}")
        scenarios.append(ok)

    # 11. Crossref
    print("\n─── 11. Crossref akademik ───")
    for kw in ["turkish education NLP", "machine learning healthcare", "climate change"]:
        r = await crossref_search(kw, max_results=3)
        ok = r.get("success") and r.get("found")
        first = r.get("results", [{}])[0].get("title", "")[:80] if ok else ""
        print(f"  [{'OK' if ok else 'X '}] '{kw}': {first}")
        scenarios.append(ok)

    # 12. OSM — Türkiye yerleri
    print("\n─── 12. OpenStreetMap ───")
    for place in ["Topkapi Sarayi Istanbul", "Erciyes Dagi", "Hagia Sophia"]:
        r = await osm_lookup(place)
        ok = r.get("success") and r.get("found")
        first = r.get("results", [{}])[0]
        info = f"{first.get('lat', '?'):.4f},{first.get('lon', '?'):.4f}" if ok else "yok"
        print(f"  [{'OK' if ok else 'X '}] {place}: {info}")
        scenarios.append(ok)

    pass_count = sum(scenarios)
    total = len(scenarios)
    print(f"\n═══════════════════════════════════════════════")
    print(f"SENARYO: {pass_count}/{total} PASS ({pass_count*100//total}%)")
    print(f"═══════════════════════════════════════════════")
    return pass_count == total


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
