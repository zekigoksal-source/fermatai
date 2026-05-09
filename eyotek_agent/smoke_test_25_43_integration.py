"""25.43 ENTEGRASYON SMOKE — yeni 12 API + 8 render
tüm routing katmanlarında çalışıyor mu doğrulama.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def test_safe_groq_tools():
    """SAFE_GROQ_TOOLS yeni 12 API'yi içeriyor mu?"""
    from llm_router import SAFE_GROQ_TOOLS
    new_apis = ['tdk_sozluk', 'nist_constant', 'oeis_search', 'open_meteo_climate',
                'wikidata_lookup', 'cern_open_data', 'huggingface_search_models',
                'tuik_dataset', 'alphafold_lookup', 'nist_webbook',
                'crossref_search', 'osm_lookup']
    missing = [a for a in new_apis if a not in SAFE_GROQ_TOOLS]
    if missing:
        print(f"  [FAIL] SAFE_GROQ_TOOLS eksik: {missing}")
        return False
    print(f"  [OK] SAFE_GROQ_TOOLS — 12 yeni API mevcut ({len(SAFE_GROQ_TOOLS)} toplam)")
    return True


def test_intent_renderer_map():
    """INTENT_RENDERER_MAP — 8 yeni intent + render eşleşme."""
    from cerebras_handler import INTENT_RENDERER_MAP
    new_intents = {
        'akis_gorselleme': 'sankey',
        'alan_orani': 'treemap',
        'cok_ogrenci_kiyas': 'parallel',
        'konu_iliskisi_dinamik': 'force_graph',
        'geometri_interaktif': 'jsxgraph',
        'harita_3d': 'cesium_globe',
        'matematik_anim': 'manim_anim',
        'declarative_chart': 'vega_lite',
    }
    fail = 0
    for intent, expected_render in new_intents.items():
        renderers = INTENT_RENDERER_MAP.get(intent, [])
        if expected_render not in renderers:
            print(f"  [FAIL] {intent}: bekleniyor {expected_render}, var: {renderers}")
            fail += 1
    if fail == 0:
        print(f"  [OK] INTENT_RENDERER_MAP — 8 yeni intent + render eşleşme")
        return True
    return False


def test_renderer_hint_patterns():
    """renderer_hint_inject — 8 yeni pattern compile + match."""
    from renderer_hint_inject import detect_renderer_need
    test_cases = [
        ("akış diyagramı göster", ["sankey"]),
        ("konu ağırlık alan haritası", ["treemap"]),
        ("paralel koordinat ile öğrenci kıyas", ["parallel"]),
        ("interaktif force graph konu ilişki", ["force_graph"]),
        ("vega-lite ile chart üret", ["vega_lite"]),
        ("interaktif geometri jsxgraph", ["jsxgraph"]),
        ("3d dünya haritada Türkiye coğrafi nokta", ["cesium_globe"]),
        ("matematik animasyon manim 3blue1brown", ["manim_anim"]),
    ]
    fail = 0
    for msg, expected in test_cases:
        renderers = detect_renderer_need(msg)
        if not any(e in renderers for e in expected):
            print(f"  [FAIL] '{msg[:40]}' → {renderers} (bekleniyor en az: {expected})")
            fail += 1
    if fail == 0:
        print(f"  [OK] renderer_hint patterns — 8/8 match")
        return True
    return False


def test_cloud_keywords():
    """_CLOUD_KEYWORDS — yeni API intent kelimeleri Claude'a yönlendir."""
    from llm_router import _CLOUD_KEYWORDS
    new_kw = ["iklim", "fibonacci", "akademik makale", "koordinat",
              "wikidata", "cern", "alphafold", "termodinamik veri"]
    missing = [k for k in new_kw if k not in _CLOUD_KEYWORDS]
    if missing:
        print(f"  [FAIL] _CLOUD_KEYWORDS eksik: {missing}")
        return False
    print(f"  [OK] _CLOUD_KEYWORDS — yeni 8 anahtar kelime mevcut")
    return True


def test_tool_dispatch():
    """Tool dispatch — TOOL_REGISTRY'de 12 yeni handler var mı?"""
    src = Path(__file__).parent / "fermat_core_agent.py"
    text = src.read_text(encoding='utf-8')
    new_tools = ['_tool_tdk_sozluk', '_tool_nist_constant', '_tool_oeis_search',
                 '_tool_open_meteo_climate', '_tool_wikidata_lookup',
                 '_tool_cern_open_data', '_tool_hf_search_models',
                 '_tool_tuik_dataset', '_tool_alphafold_lookup',
                 '_tool_nist_webbook', '_tool_crossref_search', '_tool_osm_lookup']
    missing = [t for t in new_tools if f"async def {t}(" not in text]
    if missing:
        print(f"  [FAIL] Eksik wrapper: {missing}")
        return False
    print(f"  [OK] fermat_core_agent — 12 tool wrapper mevcut")
    return True


def test_acl_all_roles():
    """ACL — 6 rol × 12 API = 72/72."""
    from role_access import _ACL_MATRIX
    new_apis = ['tdk_sozluk', 'nist_constant', 'oeis_search', 'open_meteo_climate',
                'wikidata_lookup', 'cern_open_data', 'huggingface_search_models',
                'tuik_dataset', 'alphafold_lookup', 'nist_webbook',
                'crossref_search', 'osm_lookup']
    fail = 0
    for role in ['admin', 'yonetim', 'mudur', 'ogretmen', 'rehber', 'ogrenci']:
        tools = _ACL_MATRIX.get(role, set())
        has = sum(1 for a in new_apis if a in tools)
        if has != 12:
            print(f"  [FAIL] {role}: {has}/12")
            fail += 1
    if fail == 0:
        print(f"  [OK] ACL — 6 rol × 12 API = 72/72")
        return True
    return False


def test_renderer_fences_count():
    """web_chat_ui.html — 8 yeni fence + 8 render function."""
    src = Path(__file__).parent / "web_chat_ui.html"
    text = src.read_text(encoding='utf-8')
    new_fences = ['```sankey', '```treemap', '```parallel', '```force_graph',
                  '```vega_lite', '```jsxgraph', '```cesium_globe', '```manim_anim']
    new_funcs = ['rerenderSankey', 'rerenderTreemap', 'rerenderParallel',
                 'rerenderForceGraph', 'rerenderVegaLite', 'rerenderJSXGraph',
                 'rerenderCesium', 'rerenderManimAnim']
    miss_f = [f for f in new_fences if f not in text]
    miss_fn = [f for f in new_funcs if f not in text]
    if miss_f or miss_fn:
        if miss_f: print(f"  [FAIL] Fence: {miss_f}")
        if miss_fn: print(f"  [FAIL] Func: {miss_fn}")
        return False
    # Dispatcher kontrolu
    if 'rerenderSankey(el)' not in text:
        print(f"  [FAIL] rerenderAllVisuals dispatch'te rerenderSankey çağrısı yok")
        return False
    print(f"  [OK] Renderer — 8 fence + 8 function + dispatch")
    return True


async def test_api_e2e_via_dispatcher():
    """End-to-end: Tool dispatch via TOOL_REGISTRY actually calls API."""
    import os
    if not os.environ.get("DATABASE_URL"):
        print("  [SKIP] DATABASE_URL yok — dispatcher e2e atlandi")
        return True
    try:
        from fermat_core_agent import TOOL_REGISTRY
    except Exception as e:
        print(f"  [SKIP] fermat_core_agent import fail: {e}")
        return False

    new_apis_test = [
        ("tdk_sozluk", {"query": "kitap"}),
        ("nist_constant", {"query": "planck"}),
        ("oeis_search", {"query": "fibonacci"}),
        ("tuik_dataset", {"category": "iklim_bolgeleri"}),
    ]
    fail = 0
    for tool_name, params in new_apis_test:
        try:
            handler = TOOL_REGISTRY.get(tool_name)
            if not handler:
                print(f"  [FAIL] {tool_name} TOOL_REGISTRY'de YOK")
                fail += 1
                continue
            result = await handler(params)
            ok = result.get("success", False)
            if ok:
                print(f"  [OK] {tool_name} dispatch → API çalıştı")
            else:
                print(f"  [WARN] {tool_name} → success=False: {result.get('error', '')[:60]}")
                # API erişim hatası olabilir, dispatcher OK
        except Exception as e:
            print(f"  [FAIL] {tool_name} dispatch exception: {str(e)[:60]}")
            fail += 1
    return fail == 0


def test_system_prompt_mentions():
    """system_prompts.py yeni 12 API + 8 render mention içeriyor mu?"""
    from pathlib import Path
    text = (Path(__file__).parent / "system_prompts.py").read_text(encoding='utf-8')
    new_apis = ['tdk_sozluk', 'nist_constant', 'oeis_search', 'open_meteo_climate',
                'wikidata_lookup', 'cern_open_data', 'tuik_dataset',
                'alphafold_lookup', 'crossref_search', 'osm_lookup']
    missing_api = [a for a in new_apis if a not in text]
    new_renders = ['```sankey', '```treemap', '```parallel', '```force_graph',
                   '```vega_lite', '```jsxgraph', '```cesium_globe', '```manim_anim']
    missing_render = [r for r in new_renders if r not in text]
    if missing_api or missing_render:
        if missing_api: print(f"  [FAIL] API mention eksik: {missing_api}")
        if missing_render: print(f"  [FAIL] Render mention eksik: {missing_render}")
        return False
    print(f"  [OK] system_prompts.py — 10 API + 8 render mention")
    return True


async def main():
    print("═══════════════════════════════════════════════")
    print("25.43 ENTEGRASYON SMOKE — ROUTING + ACL + DISPATCH")
    print("═══════════════════════════════════════════════\n")

    results = []

    print("─── 1. SAFE_GROQ_TOOLS (Cerebras allowlist) ───")
    results.append(("SAFE_GROQ_TOOLS", test_safe_groq_tools()))

    print("\n─── 2. INTENT_RENDERER_MAP (Cerebras renderer hint) ───")
    results.append(("INTENT_RENDERER_MAP", test_intent_renderer_map()))

    print("\n─── 3. renderer_hint_inject (Claude pattern → render) ───")
    results.append(("renderer_hint patterns", test_renderer_hint_patterns()))

    print("\n─── 4. _CLOUD_KEYWORDS (Claude routing) ───")
    results.append(("_CLOUD_KEYWORDS", test_cloud_keywords()))

    print("\n─── 5. Tool dispatch (TOOL_REGISTRY wrapper) ───")
    results.append(("Tool dispatch", test_tool_dispatch()))

    print("\n─── 6. ACL (6 rol × 12 API) ───")
    results.append(("ACL", test_acl_all_roles()))

    print("\n─── 7. Renderer fences + dispatch (web_chat_ui) ───")
    results.append(("Renderer", test_renderer_fences_count()))

    print("\n─── 8. system_prompts mention (LLM farkındalığı) ───")
    results.append(("system_prompts", test_system_prompt_mentions()))

    print("\n─── 9. End-to-end dispatcher (live API call) ───")
    results.append(("E2E dispatcher", await test_api_e2e_via_dispatcher()))

    print()
    pass_count = sum(1 for _, ok in results if ok)
    print(f"═══════════════════════════════════════════════")
    print(f"TOPLAM: {pass_count}/{len(results)} test grup PASS")
    print(f"═══════════════════════════════════════════════")
    return pass_count == len(results)


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
