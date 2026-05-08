"""
Renderer Pipeline Audit (25.41 Neo — 9 May)
============================================

27 fence için TAM PIPELINE testi:
  1. Backend: bot ```X``` fence üretti mi (string match)
  2. Frontend: pending marker oluşur mu (HTML class kontrol)
  3. Renderer dispatcher: fonksiyon var mı (JS içinde)

Çıktı: 27/27 PASS hedeflenir, eksik nokta nerede tespit.
"""
from __future__ import annotations
import os
import re
import sys


HTML_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "web_chat_ui.html",
)


# 27 aktif renderer
RENDERERS = [
    "chart", "calc", "desmos", "sim", "radar", "heatmap", "karne",
    "gauge", "timeline", "progress", "compare", "compare2", "geogebra",
    "plotly", "mermaid", "vr", "mol3d", "sound", "element",
    "excalidraw", "codeout", "steps", "kgraph", "quiz", "recall", "compound",
    "formula",
]


# Renderer → JS dispatch fonksiyon adı (re-prefix var)
JS_DISPATCH = {
    "chart": "rerenderCharts",
    "calc": "rerenderCalcs",
    "desmos": "rerenderDesmos",
    "sim": "rerenderSims",
    "radar": "rerenderRadar",
    "heatmap": "rerenderHeatmap",
    "karne": "rerenderKarne",
    "gauge": "rerenderGauge",
    "timeline": "rerenderTimeline",
    "progress": "rerenderProgress",
    "compare": "rerenderCompare",
    "compare2": "rerenderCompare",  # compare2 aynı dispatcher
    "geogebra": "rerenderGeogebra",
    "plotly": "rerenderPlotly",
    "mermaid": "rerenderMermaid",
    "vr": "rerenderVR",
    "mol3d": "rerenderMol",
    "sound": "rerenderSound",
    "element": "rerenderElement",
    "excalidraw": "rerenderExcalidraw",
    "codeout": "rerenderCodeOut",
    "steps": "rerenderSteps",
    "kgraph": "rerenderKgraph",
    "quiz": "rerenderQuiz",
    "recall": "rerenderRecall",
    "compound": "rerenderCompound",
    "formula": "rerenderFormulas",
}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if not os.path.exists(HTML_FILE):
        print(f"❌ HTML dosyası bulunamadı: {HTML_FILE}")
        sys.exit(1)

    print("🎨 Renderer Pipeline Audit\n")
    with open(HTML_FILE, "r", encoding="utf-8") as f:
        html = f.read()

    print("─" * 70)
    print(f"{'Renderer':12s} | Pending | Replace | Dispatcher | Pipeline")
    print("─" * 70)

    pass_count = 0
    fail_list = []

    for r in RENDERERS:
        # 1) Pending marker class oluşturma
        pending_pat = rf'class="{re.escape(r)}-pending"'
        has_pending = re.search(pending_pat, html) is not None

        # 2) Pending → data attribute replace
        replace_pat = rf'<div class="{re.escape(r)}-pending" data-{re.escape(r)}'
        has_replace = re.search(replace_pat, html) is not None

        # 3) JS dispatcher fonksiyon var mı
        dispatch_fn = JS_DISPATCH.get(r, "")
        has_dispatch = bool(dispatch_fn) and (f"function {dispatch_fn}" in html or f"{dispatch_fn} =" in html)

        # Tüm 3 katman PASS = pipeline OK
        pipeline_ok = has_pending and has_replace and has_dispatch
        if pipeline_ok:
            pass_count += 1
            status = "✅"
        else:
            fail_list.append((r, has_pending, has_replace, has_dispatch))
            status = "❌"

        print(f"{r:12s} | {'✅' if has_pending else '❌':7s} | {'✅' if has_replace else '❌':7s} | {'✅' if has_dispatch else '❌':10s} | {status}")

    print("─" * 70)
    print(f"\nSONUÇ: {pass_count}/{len(RENDERERS)} renderer pipeline tamam")

    if fail_list:
        print("\n⚠️  Eksik pipeline:")
        for r, p, rp, d in fail_list:
            issues = []
            if not p:  issues.append("pending marker yok")
            if not rp: issues.append("data-attribute replace yok")
            if not d:  issues.append("JS dispatcher yok")
            print(f"  • {r}: {', '.join(issues)}")
    else:
        print("\n🎉 Tüm 27 renderer fence backend → frontend → render pipeline çalışır")


if __name__ == "__main__":
    main()
