"""25.43 Smoke test — 12 API + 8 Render + ACL + tool dispatch dogrulamasi.

Calistirma (VPS):
    cd /opt/fermatai/eyotek_agent
    export DATABASE_URL='postgresql://...'
    /opt/fermatai/.venv/bin/python smoke_test_25_43.py
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


async def smoke_apis():
    """12 yeni API canli erisilebilirlik testi."""
    from external_apis_v3 import (
        tdk_sozluk, nist_constant, oeis_search, open_meteo_climate,
        wikidata_lookup, cern_open_data, huggingface_search_models,
        tuik_dataset, alphafold_lookup, nist_webbook, crossref_search, osm_lookup,
    )
    tests = [
        ("TDK", tdk_sozluk("müşfik")),
        ("NIST const", nist_constant("planck")),
        ("OEIS", oeis_search("1,1,2,3,5,8")),
        ("Open-Meteo", open_meteo_climate("Istanbul")),
        ("Wikidata", wikidata_lookup("Atatürk")),
        ("CERN", cern_open_data("higgs")),
        ("HF Search", huggingface_search_models("turkish bert")),
        ("TUIK", tuik_dataset("nufus_2024")),
        ("AlphaFold", alphafold_lookup("P69905")),
        ("NIST WebBook", nist_webbook("water")),
        ("Crossref", crossref_search("turkish education")),
        ("OSM", osm_lookup("Topkapi Sarayi")),
    ]
    pass_count = 0
    print("─── API Smoke (12 yeni) ───")
    for name, coro in tests:
        try:
            r = await coro
            if r.get("success"):
                pass_count += 1
                print(f"  [OK] {name}")
            else:
                print(f"  [FAIL] {name} — {r.get('error', '')[:60]}")
        except Exception as e:
            print(f"  [EXC] {name} — {str(e)[:60]}")
    return pass_count


def smoke_tool_definitions():
    """Tool definitions 12 yeni tool'u icermeli."""
    import tool_definitions as td
    new_tools = ['tdk_sozluk', 'nist_constant', 'oeis_search', 'open_meteo_climate',
                 'wikidata_lookup', 'cern_open_data', 'huggingface_search_models',
                 'tuik_dataset', 'alphafold_lookup', 'nist_webbook',
                 'crossref_search', 'osm_lookup']
    existing = {t['name'] for t in td.TOOLS_ACTIVE}
    missing = [n for n in new_tools if n not in existing]
    print("─── Tool definitions ───")
    if not missing:
        print(f"  [OK] 12/12 yeni tool TOOLS_ACTIVE'de mevcut")
        return True
    print(f"  [FAIL] Eksik: {missing}")
    return False


def smoke_acl():
    """ACL: 6 rol × 12 yeni API = 72/72 erisim."""
    from role_access import _ACL_MATRIX
    new_tools = ['tdk_sozluk', 'nist_constant', 'oeis_search', 'open_meteo_climate',
                 'wikidata_lookup', 'cern_open_data', 'huggingface_search_models',
                 'tuik_dataset', 'alphafold_lookup', 'nist_webbook',
                 'crossref_search', 'osm_lookup']
    print("─── ACL ───")
    total_ok = 0
    total = 0
    for role in ['admin', 'yonetim', 'mudur', 'ogretmen', 'rehber', 'ogrenci']:
        tools = _ACL_MATRIX.get(role, set())
        has = sum(1 for t in new_tools if t in tools)
        ok = has == 12
        total_ok += has
        total += 12
        sym = "OK" if ok else "FAIL"
        print(f"  [{sym}] {role}: {has}/12")
    return total_ok == total


def smoke_dispatcher():
    """fermat_core_agent.py TOOL_REGISTRY 12 yeni handler iceriyor mu?"""
    src = Path(__file__).parent / "fermat_core_agent.py"
    text = src.read_text(encoding='utf-8')
    new_handlers = [
        '_tool_tdk_sozluk', '_tool_nist_constant', '_tool_oeis_search',
        '_tool_open_meteo_climate', '_tool_wikidata_lookup', '_tool_cern_open_data',
        '_tool_hf_search_models', '_tool_tuik_dataset', '_tool_alphafold_lookup',
        '_tool_nist_webbook', '_tool_crossref_search', '_tool_osm_lookup',
    ]
    print("─── Dispatcher ───")
    missing = [h for h in new_handlers if f"async def {h}(" not in text]
    if not missing:
        print(f"  [OK] 12/12 wrapper fonksiyon fermat_core_agent.py'de mevcut")
        return True
    print(f"  [FAIL] Eksik wrapper: {missing}")
    return False


def smoke_renderers():
    """web_chat_ui.html 8 yeni render fence + render fonksiyon."""
    src = Path(__file__).parent / "web_chat_ui.html"
    text = src.read_text(encoding='utf-8')
    fences = ['```sankey', '```treemap', '```parallel', '```force_graph',
              '```vega_lite', '```jsxgraph', '```cesium_globe', '```manim_anim']
    funcs = ['rerenderSankey', 'rerenderTreemap', 'rerenderParallel',
             'rerenderForceGraph', 'rerenderVegaLite', 'rerenderJSXGraph',
             'rerenderCesium', 'rerenderManimAnim']
    print("─── Renderers ───")
    miss_fence = [f for f in fences if f not in text]
    miss_func = [f for f in funcs if f not in text]
    if not miss_fence and not miss_func:
        print(f"  [OK] 8/8 fence + 8/8 render function mevcut")
        return True
    if miss_fence: print(f"  [FAIL] Eksik fence: {miss_fence}")
    if miss_func: print(f"  [FAIL] Eksik func: {miss_func}")
    return False


def smoke_cdn():
    """CDN imports — ECharts, D3, Vega-Lite, JSXGraph, Cesium."""
    src = Path(__file__).parent / "web_chat_ui.html"
    text = src.read_text(encoding='utf-8')
    cdns = {
        'ECharts': 'echarts@5',
        'D3': 'd3@7',
        'Vega-Lite': 'vega-lite@5',
        'Vega-Embed': 'vega-embed@6',
        'JSXGraph': 'jsxgraph@1.10',
        'Cesium': 'cesium.com',
    }
    print("─── CDN imports ───")
    missing = []
    for name, marker in cdns.items():
        if marker in text:
            print(f"  [OK] {name}")
        else:
            print(f"  [FAIL] {name} ({marker})")
            missing.append(name)
    return not missing


async def main():
    print("═══════════════════════════════════════════════")
    print("25.43 SMOKE TEST — 12 API + 8 Render + ACL")
    print("═══════════════════════════════════════════════\n")

    api_ok = await smoke_apis()
    print()
    tool_ok = smoke_tool_definitions()
    print()
    acl_ok = smoke_acl()
    print()
    disp_ok = smoke_dispatcher()
    print()
    rend_ok = smoke_renderers()
    print()
    cdn_ok = smoke_cdn()
    print()

    total = (api_ok == 12) + tool_ok + acl_ok + disp_ok + rend_ok + cdn_ok
    print(f"═══════════════════════════════════════════════")
    print(f"TOPLAM: {total}/6 grup PASS — APIs {api_ok}/12 erisilebilir")
    print(f"═══════════════════════════════════════════════")
    return total == 6 and api_ok == 12


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
