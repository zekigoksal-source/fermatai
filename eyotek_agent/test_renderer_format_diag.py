"""
Renderer Format Diagnostic — bot her renderer için hangi JSON key'leri kullanıyor?
Frontend'in beklediği vs bot'un gönderdiği keys karşılaştırması.
"""
from __future__ import annotations
import json
import os
import re
import sys
import time
import urllib.request


BRIDGE_URL = "http://localhost:8001/agent"
TOKEN = os.getenv("AGENT_API_KEY", "fermat_agent_secret_2026")
ECRIN_PHONE = "905309356389"


# (renderer, message)
SAMPLES = [
    ("chart",     "matematik kurum geneli zayıf 5 konuyu chart ile göster"),
    ("radar",     "radar ile son denemedeki ders dengesini göster"),
    ("heatmap",   "heatmap ile konu hata yoğunluğunu göster"),
    ("gauge",     "gauge ile TYT hedef yüzdesini göster"),
    ("karne",     "karne ile son sınav ders performansım"),
    ("timeline",  "timeline ile bu hafta deneme tarihlerimi göster"),
    ("progress",  "progress ile YKS hedef ilerlemem"),
    ("compare",   "compare ile matematik fizik kıyasla"),
    ("compare2",  "compare2 ile TYT AYT yanyana göster"),
    ("plotly",    "plotly ile y=sin(x) fonksiyon grafiği"),
    ("mermaid",   "mermaid ile öğrenme akış şeması"),
    ("kgraph",    "kgraph ile türev integral kavram haritası"),
    ("quiz",      "quiz ile TYT matematik soru üret"),
    ("steps",     "steps ile limit nasıl çözülür"),
    ("formula",   "formula ile türev formülü"),
    ("calc",      "calc ile yerleşme puanı hesaplayıcı"),
    ("element",   "element ile karbon atomu göster"),
    ("desmos",    "desmos ile y=x^2 grafiği"),
    ("geogebra",  "geogebra ile dik üçgen göster"),
    ("recall",    "recall ile bu konuyu hatırlat"),
]


def call_bot(msg: str) -> str:
    req = urllib.request.Request(
        BRIDGE_URL,
        data=json.dumps({
            "phone": ECRIN_PHONE,
            "message": msg,
            "channel": "web",
            "session_id": f"format_diag_{int(time.time())}_{hash(msg) & 0xFFFF}",
        }).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8")).get("response", "")
    except Exception as e:
        return f"[ERR: {e}]"


def extract_fence(resp: str, renderer: str) -> str | None:
    pattern = r"```" + re.escape(renderer) + r"\s*\n([\s\S]*?)\n?```"
    m = re.search(pattern, resp)
    return m.group(1).strip() if m else None


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print("🔬 RENDERER FORMAT DIAGNOSTIC")
    print("=" * 100)
    print(f"{'RENDERER':12s} | {'KEYS (top-level)':40s} | {'JSON formatı':30s}")
    print("=" * 100)

    for renderer, msg in SAMPLES:
        resp = call_bot(msg)
        if resp.startswith("[ERR"):
            print(f"{renderer:12s} | FETCH ERROR: {resp[:80]}")
            continue

        fence = extract_fence(resp, renderer)
        if not fence:
            # compound içinde olabilir
            if '```compound' in resp:
                comp = extract_fence(resp, 'compound')
                if comp and f'"type":"{renderer}"' in comp:
                    print(f"{renderer:12s} | (compound içinde, atla)")
                    continue
            print(f"{renderer:12s} | NO FENCE (resp len={len(resp)})")
            continue

        # formula bazen latex string
        if renderer == "formula" and not fence.startswith("{"):
            print(f"{renderer:12s} | latex string: {fence[:60]}")
            continue

        try:
            j = json.loads(fence)
        except json.JSONDecodeError as e:
            print(f"{renderer:12s} | INVALID JSON: {e}")
            continue

        keys = sorted(j.keys()) if isinstance(j, dict) else []
        # Ana içerik nerede?
        has_data_obj = isinstance(j.get("data"), dict)
        format_type = "Chart.js standart (data.labels)" if has_data_obj and "labels" in j.get("data", {}) else \
                      "Üst seviye (labels)" if "labels" in j else \
                      "Custom (no labels)"

        print(f"{renderer:12s} | {','.join(keys[:6])[:40]:40s} | {format_type:30s}")
        # Critical fields
        if has_data_obj:
            inner_keys = sorted(j["data"].keys()) if isinstance(j["data"], dict) else []
            print(f"             | data.{','.join(inner_keys[:5])[:50]}")


if __name__ == "__main__":
    main()
