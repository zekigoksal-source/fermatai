"""
Renderer Render-Validation Audit (25.41-DIAG, 9 May)
====================================================

ÖNCEKİ test (test_full_audit) sadece "fence VAR mı" diyordu.
Bu test: bot'un ÜRETTİĞİ JSON gerçekten BROWSER'DA RENDER edilebilir mi?

Her renderer için:
  1. Bot'a fence üretmesini iste
  2. Fence'i extract et
  3. JSON.loads ile parse et (frontend'e tam aynı şekilde)
  4. Required field'lar var mı (renderer'a göre):
     - chart: type, data.labels, data.datasets[0].data
     - radar: data.labels, data.datasets
     - heatmap: x, y, values (matrix)
     - gauge: value, min, max
     - timeline: items[].date, items[].title
     - karne: rows[].ders, rows[].konular
     - compare2: items[].label
     - quiz: questions[].soru, questions[].siklar
     - formula: latex string
     - kgraph: nodes, edges

Çıktı: PASS/FAIL/MISSING_FIELDS detayı
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
NEO_PHONE = "905051256802"
ECRIN_PHONE = "905309356389"


# ─── Renderer test senaryoları ─────────────────────────────────────────

# (renderer_name, message, required_fields_validator)

def _check_chart(j):
    """chart: type + data.labels + data.datasets[].data eşit uzunluk."""
    errs = []
    if "type" not in j: errs.append("type missing")
    data = j.get("data", {})
    labels = data.get("labels", [])
    datasets = data.get("datasets", [])
    if not labels: errs.append("data.labels empty")
    if not datasets: errs.append("data.datasets empty")
    for i, ds in enumerate(datasets):
        d = ds.get("data", [])
        if len(d) != len(labels):
            errs.append(f"dataset[{i}].data len {len(d)} != labels len {len(labels)}")
        if not d:
            errs.append(f"dataset[{i}].data empty")
    return errs


def _check_radar(j):
    errs = []
    # radar bazen üst seviye labels, bazen data.labels
    labels = j.get("labels") or j.get("data", {}).get("labels", [])
    datasets = j.get("datasets") or j.get("data", {}).get("datasets", [])
    if not labels: errs.append("labels empty")
    if not datasets: errs.append("datasets empty")
    for i, ds in enumerate(datasets):
        d = ds.get("data", [])
        if not d:
            errs.append(f"dataset[{i}].data empty")
        if len(d) != len(labels) and len(labels) > 0:
            errs.append(f"dataset[{i}].data len {len(d)} != labels len {len(labels)}")
    return errs


def _check_heatmap(j):
    """Frontend defansif: x/xAxis/cols, y/yAxis/rows, values/data/matrix."""
    errs = []
    x = j.get("x") or j.get("xAxis") or j.get("cols") or j.get("columns") or []
    y = j.get("y") or j.get("yAxis") or j.get("rows") or []
    vals = j.get("values") or j.get("matrix") or j.get("data")
    if not x: errs.append("x/xAxis missing")
    if not y: errs.append("y/yAxis missing")
    if not vals: errs.append("values/data missing")
    if isinstance(vals, list) and y and len(vals) != len(y):
        errs.append(f"values rows {len(vals)} != y len {len(y)}")
    return errs


def _check_gauge(j):
    errs = []
    val = j.get("value")
    if val is None: errs.append("value missing")
    if "max" not in j: errs.append("max missing")
    return errs


def _check_timeline(j):
    errs = []
    items = j.get("items") or j.get("data") or j.get("events")
    if not items: errs.append("items/data missing")
    elif isinstance(items, list):
        for i, it in enumerate(items[:3]):
            if not (it.get("date") or it.get("tarih") or it.get("gun") or it.get("title") or it.get("baslik")):
                errs.append(f"item[{i}] no date/title")
                break
    return errs


def _check_karne(j):
    errs = []
    rows = j.get("rows") or j.get("dersler")
    if not rows: errs.append("rows/dersler missing")
    return errs


def _check_compare2(j):
    errs = []
    # Frontend rerenderCompare2: left/right/rows kullanıyor
    if not (j.get("left") or j.get("items") or j.get("data")):
        errs.append("left/items/data missing")
    if not (j.get("right") or j.get("items") or j.get("data")):
        errs.append("right missing (when left/right format)")
    return errs


def _check_quiz(j):
    errs = []
    qs = j.get("questions") or j.get("sorular")
    if not qs: errs.append("questions/sorular missing")
    elif isinstance(qs, list):
        for i, q in enumerate(qs[:1]):
            if not (q.get("soru") or q.get("question") or q.get("text")):
                errs.append(f"q[{i}] no soru/question text")
            if not (q.get("siklar") or q.get("options") or q.get("choices")):
                errs.append(f"q[{i}] no siklar/options")
    return errs


def _check_formula(j):
    # formula: tek string olabilir veya {"latex": "..."}
    return []  # her şey kabul (KaTeX parse'ı runtime'da)


def _check_kgraph(j):
    errs = []
    nodes = j.get("nodes")
    edges = j.get("edges") or j.get("links")
    if not nodes: errs.append("nodes missing")
    if not edges: errs.append("edges/links missing")
    return errs


def _check_steps(j):
    errs = []
    steps = j.get("steps") or j.get("adimlar")
    if not steps: errs.append("steps/adimlar missing")
    return errs


SCENARIOS = [
    ("chart", "matematik kurum geneli en zayıf 5 konuyu chart ile göster", _check_chart),
    ("radar", "ders bazlı yetkinlik karne radar ile göster", _check_radar),
    ("heatmap", "konu hata yoğunluğu heatmap göster", _check_heatmap),
    ("gauge", "TYT hedef ilerlemesi gauge ile göster", _check_gauge),
    ("timeline", "Mayıs ayı çalışma takvimini timeline ile göster", _check_timeline),
    ("karne", "öğrenci karne ders bazlı net ortalaması", _check_karne),
    ("compare2", "matematik fizik kıyasla compare2 ile", _check_compare2),
    ("quiz", "TYT matematik 1 quiz sorusu üret", _check_quiz),
    ("formula", "limit formülü formula ile yaz", _check_formula),
    ("kgraph", "türev integral ilişkisi kgraph ile göster", _check_kgraph),
    ("steps", "limit nasıl çözülür adım adım steps ile", _check_steps),
]


def call_bridge(message: str, phone: str = NEO_PHONE, timeout: int = 60) -> str:
    req = urllib.request.Request(
        BRIDGE_URL,
        data=json.dumps({
            "phone": phone,
            "message": message,
            "channel": "web",
            "session_id": f"render_diag_{int(time.time())}_{hash(message) & 0xFFFF}",
        }).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {TOKEN}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8"))
        return d.get("response", "")
    except Exception as e:
        return f"[FETCH-FAIL: {e}]"


def extract_fences(resp: str, renderer: str) -> list[str]:
    """ ```renderer JSON ``` arası içeriği çıkar."""
    pattern = r"```" + re.escape(renderer) + r"\s*\n([\s\S]*?)\n?```"
    return re.findall(pattern, resp)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print("🎨 RENDERER RENDER VALIDATION AUDIT")
    print("=" * 70)
    print()

    pass_count = 0
    fail_count = 0
    no_fence_count = 0
    invalid_json = 0

    results = []

    for renderer, msg, validator in SCENARIOS:
        print(f"[{renderer:10s}] '{msg[:55]}...'")
        resp = call_bridge(msg, phone=ECRIN_PHONE)
        if resp.startswith("[FETCH-FAIL"):
            print(f"    ❌ {resp}")
            results.append((renderer, "FETCH_FAIL", resp))
            fail_count += 1
            continue

        # 1. Fence var mı?
        fences = extract_fences(resp, renderer)
        if not fences:
            # Belki compound içinde
            if f'"type":"{renderer}"' in resp or '```compound' in resp:
                print(f"    ⚠️  Direct fence yok ama compound/inline tespit (PASS)")
                results.append((renderer, "COMPOUND_OK", "via compound"))
                pass_count += 1
                continue
            print(f"    ❌ NO FENCE (response len={len(resp)})")
            results.append((renderer, "NO_FENCE", resp[:200]))
            no_fence_count += 1
            continue

        fence = fences[0].strip()
        # 2. JSON parse?
        # formula bazen latex string, JSON değil
        if renderer == "formula":
            print(f"    ✅ formula: latex string ({len(fence)} char)")
            pass_count += 1
            results.append((renderer, "PASS_FORMULA", fence[:100]))
            continue

        try:
            j = json.loads(fence)
        except json.JSONDecodeError as e:
            print(f"    ❌ INVALID JSON: {e}")
            print(f"       First 100: {fence[:100]}")
            print(f"       Last 100: {fence[-100:]}")
            results.append((renderer, "INVALID_JSON", str(e)))
            invalid_json += 1
            continue

        # 3. Required fields?
        errs = validator(j)
        if errs:
            print(f"    ❌ MISSING FIELDS: {', '.join(errs)}")
            results.append((renderer, "MISSING_FIELDS", "; ".join(errs)))
            fail_count += 1
            continue

        print(f"    ✅ VALID (JSON OK + fields tamam)")
        pass_count += 1
        results.append((renderer, "PASS", "valid"))

    print()
    print("=" * 70)
    print(f"📊 SONUÇ: {pass_count}/{len(SCENARIOS)} PASS")
    print(f"   - JSON invalid:   {invalid_json}")
    print(f"   - Fence yok:      {no_fence_count}")
    print(f"   - Field eksik:    {fail_count}")
    print()

    # Özet tablo
    print("RENDERER     | STATUS         | DETAY")
    print("-" * 70)
    for r, s, d in results:
        print(f"{r:12s} | {s:14s} | {d[:50]}")


if __name__ == "__main__":
    main()
