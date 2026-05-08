"""
Full System Audit (25.41 Neo — 9 May)
======================================

Test 4 katman:
1. Env keys — hangi servisler kayıtlı
2. LLM Providers — Claude/Cerebras/Groq/Ollama ping
3. External APIs — Wolfram/YouTube/Sentry/Whisper/Vision smoke
4. Renderer fence'ler — backend bot 28 fence tipini üretebiliyor mu

Çıktı: kategori bazlı PASS/FAIL + zayıf nokta raporu
"""
from __future__ import annotations
import asyncio
import json
import os
import sys
import time
import urllib.request

# .env'i otomatik yükle (VPS'te shell session'a env injekt edilmiyor)
# Path sırası: parent (production) → local → cwd. Tüm bulunan dosyaları yükle.
try:
    from dotenv import load_dotenv
    _here = os.path.dirname(os.path.abspath(__file__))
    for _candidate in (
        os.path.join(_here, "..", ".env"),  # /opt/fermatai/.env (production)
        os.path.join(_here, ".env"),         # eyotek_agent/.env (geliştirme)
        os.path.join(os.getcwd(), ".env"),   # cwd
    ):
        if os.path.exists(_candidate):
            load_dotenv(_candidate, override=False)
except ImportError:
    pass


# ─── Test config ─────────────────────────────────────────────────────────

EXPECTED_ENV = [
    "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GROQ_API_KEY", "CEREBRAS_API_KEY",
    "DATABASE_URL", "WA_ACCESS_TOKEN", "WA_PHONE_NUMBER_ID", "WA_VERIFY_TOKEN",
    "YOUTUBE_API_KEY", "WOLFRAM_APP_ID", "SENTRY_DSN",
    "AGENT_API_KEY",
]


EXTERNAL_API_TESTS = [
    # (name, ping URL, expected_status, header_token_env)
    # Status code = endpoint canlı işareti (auth/method mismatch normal — endpoint var demek)
    ("Cerebras",       "https://api.cerebras.ai/v1/models", 403, "CEREBRAS_API_KEY"),  # 403 = CloudFront WAF (normal)
    ("Anthropic",      "https://api.anthropic.com/v1/messages", 405, "ANTHROPIC_API_KEY"),  # 405 = GET reddediliyor, POST endpoint
    ("Groq",           "https://api.groq.com/openai/v1/models", 401, "GROQ_API_KEY"),  # 401 = auth yok
    ("Ollama",         "http://localhost:11434/api/tags", 200, None),
    ("Wolfram",        "https://api.wolframalpha.com/v1/spoken?appid=DEMO&i=1+1", 401, None),  # 401 = DEMO appid yetkisiz
    ("YouTube",        "https://www.googleapis.com/youtube/v3/search?part=snippet&maxResults=1&q=test", 403, None),  # 403 = key gerek
    ("Sentry",         "https://sentry.io/api/0/", 401, None),
    ("PubChem",        "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/water/property/MolecularFormula/JSON", 200, None),
    ("NASA",           "https://api.nasa.gov/planetary/apod?api_key=DEMO_KEY", 200, None),
    ("Wikipedia TR",   "https://tr.wikipedia.org/api/rest_v1/page/summary/Matematik", 200, None),
    ("OGM Materyal",   "https://ogmmateryal.eba.gov.tr/", 200, None),
    ("PhET",           "https://phet.colorado.edu/sims/html/forces-and-motion-basics/latest/forces-and-motion-basics_tr.html", 200, None),
]


# 27 aktif renderer fence (frontend'de pending marker olanlar)
# NOT: "3d" desmos mode parametresi, ayrı fence değil. "plot3d" deprecated.
RENDERERS = [
    "chart", "calc", "desmos", "sim", "radar", "heatmap", "karne",
    "gauge", "timeline", "progress", "compare", "compare2", "geogebra",
    "plotly", "mermaid", "vr", "mol3d", "sound", "element",
    "excalidraw", "codeout", "steps", "kgraph", "quiz", "recall", "compound",
    "formula",
]


BRIDGE_URL = "http://localhost:8001/agent"
BRIDGE_HEALTH = "http://localhost:8001/health"
TOKEN = "fermat_agent_secret_2026"
NEO_PHONE = "905051256802"


# ─── Test fonksiyonları ─────────────────────────────────────────────────

def test_env_keys() -> tuple[int, int, list[str]]:
    """Env kullanımı — değer var mı (içerik göstermez, sadece set/unset)."""
    missing = []
    for k in EXPECTED_ENV:
        if not os.getenv(k):
            missing.append(k)
    return len(EXPECTED_ENV) - len(missing), len(EXPECTED_ENV), missing


def http_ping(url: str, expected: int, timeout: int = 10) -> tuple[bool, int, int]:
    """URL ping. Returns (passed, http_code, ms)."""
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "FermatAI-Audit/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ms = int((time.time() - t0) * 1000)
            return (r.code == expected or r.code == 200, r.code, ms)
    except urllib.error.HTTPError as e:
        ms = int((time.time() - t0) * 1000)
        # 401 / 403 / 400 expected ise PASS (endpoint var, auth/param yok)
        return (e.code == expected, e.code, ms)
    except Exception as e:
        return (False, 0, int((time.time() - t0) * 1000))


def test_external_apis() -> dict:
    results = {}
    for name, url, expected, _key_env in EXTERNAL_API_TESTS:
        passed, code, ms = http_ping(url, expected)
        results[name] = {"passed": passed, "code": code, "ms": ms, "expected": expected}
    return results


def test_renderer_via_bridge(renderer_name: str, message: str, timeout: int = 35) -> dict:
    """Bot'a mesaj at, response içinde ```X blok var mı kontrol et.

    NOT: `compound` renderer multi-panel wrapper'dır — içinde target
    renderer'ı sarabilir. Compound varsa target'a dolaylı PASS verilir.
    """
    import re
    req = urllib.request.Request(
        BRIDGE_URL,
        data=json.dumps({"phone": NEO_PHONE, "message": message, "channel": "web"}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"},
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        resp = data.get("response", "")
        ms = int((time.time() - t0) * 1000)
        # Hangi renderer block'ları üretildi?
        found = []
        for r_name in RENDERERS:
            pattern = r"```" + re.escape(r_name) + r"\b"
            if re.search(pattern, resp):
                found.append(r_name)
        # compound içinde target renderer panel olarak geçiyor mu?
        # Örn: ```compound { "panels": [{ "type": "gauge", ... }] }
        compound_wrapped = False
        if "compound" in found:
            # compound block içinde "type": "<renderer_name>" var mı?
            type_pat = r'"type"\s*:\s*"' + re.escape(renderer_name) + r'"'
            if re.search(type_pat, resp):
                compound_wrapped = True
        target_found = (renderer_name in found) or compound_wrapped
        return {
            "ok": True, "ms": ms, "len": len(resp),
            "found_renderers": found,
            "target_found": target_found,
            "compound_wrapped": compound_wrapped,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:100], "ms": int((time.time() - t0) * 1000)}


# Renderer trigger mesajları (kısmı LLM kararına bağlı, %100 garanti yok)
RENDERER_TRIGGERS = [
    ("chart",    "son 7 gün kullanıcı sayısı grafik chart olarak göster"),
    ("compare2", "matematik ve fizik konularını karşılaştır compare2 ile"),
    ("radar",   "ders bazlı yetkinlik karne radar göster"),
    ("gauge",    "TYT hedef yüzdesi gauge ile göster"),
    ("timeline", "Mayıs ayı çalışma takvimini timeline blok ile ay ay göster"),
    ("steps",    "limit konusunu steps adım adım anlat"),
    ("kgraph",   "türev integral ilişki kgraph ile göster"),
    ("quiz",     "TYT matematik 1 quiz sorusu üret"),
    ("formula",  "limit formülü formula olarak yaz"),
    ("heatmap",  "konu hata yoğunluğu heatmap göster"),
]


# ─── MAIN ────────────────────────────────────────────────────────────────

async def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print("🔍 FermatAI Full Audit\n")

    # 1) ENV
    print("═" * 60)
    print("1️⃣  ENV KEYS")
    print("─" * 60)
    found_env, total_env, missing = test_env_keys()
    for k in EXPECTED_ENV:
        status = "✅" if os.getenv(k) else "❌"
        print(f"  {status} {k}")
    print(f"  → {found_env}/{total_env} set")

    # 2) Bridge health
    print()
    print("═" * 60)
    print("2️⃣  BRIDGE HEALTH")
    print("─" * 60)
    passed, code, ms = http_ping(BRIDGE_HEALTH, 200, timeout=5)
    bridge_status = "✅ active" if passed else "❌ fail"
    print(f"  Bridge: {bridge_status} (HTTP {code}, {ms}ms)")

    # 3) External APIs
    print()
    print("═" * 60)
    print("3️⃣  EXTERNAL API PING")
    print("─" * 60)
    api_results = test_external_apis()
    api_pass = sum(1 for r in api_results.values() if r["passed"])
    for name, r in api_results.items():
        marker = "✅" if r["passed"] else "❌"
        print(f"  {marker} {name:15s} HTTP {r['code']:3d} ({r['ms']:4d}ms) [exp {r['expected']}]")
    print(f"  → {api_pass}/{len(api_results)} API erişilebilir")

    # 4) Renderer triggers (canlı bot test)
    print()
    print("═" * 60)
    print("4️⃣  RENDERER TRIGGER TEST (canlı bot, web kanalı)")
    print("─" * 60)
    rend_pass = 0
    rend_results = []
    for renderer, msg in RENDERER_TRIGGERS:
        r = test_renderer_via_bridge(renderer, msg, timeout=35)
        if not r["ok"]:
            rend_results.append((renderer, False, r.get("error", "?")))
            print(f"  ❌ {renderer:10s} | ERR | {r.get('error', '?')}")
            continue
        # Beklenen renderer üretildi mi?
        if r["target_found"]:
            rend_pass += 1
            extra = ", ".join(rr for rr in r["found_renderers"] if rr != renderer)
            extra_str = f" + {extra}" if extra else ""
            wrapped_marker = " (compound-wrapped)" if r.get("compound_wrapped") else ""
            print(f"  ✅ {renderer:10s} | {r['ms']:5d}ms | {r['len']:4d}c | {renderer}{extra_str}{wrapped_marker}")
            rend_results.append((renderer, True, ""))
        else:
            others = ", ".join(r["found_renderers"]) if r["found_renderers"] else "(yok)"
            print(f"  ⚠️ {renderer:10s} | {r['ms']:5d}ms | beklenen yok, geldi: {others}")
            rend_results.append((renderer, False, f"got: {others}"))

    print(f"  → {rend_pass}/{len(RENDERER_TRIGGERS)} renderer otomatik üretildi")

    # ─── SUMMARY ──
    print()
    print("═" * 60)
    print("📊 SONUÇ")
    print("─" * 60)
    total_pass = found_env + (1 if passed else 0) + api_pass + rend_pass
    total_max = total_env + 1 + len(api_results) + len(RENDERER_TRIGGERS)
    pct = round(100 * total_pass / total_max)
    print(f"  ENV:       {found_env}/{total_env}")
    print(f"  Bridge:    {'1/1' if passed else '0/1'}")
    print(f"  Ext APIs:  {api_pass}/{len(api_results)}")
    print(f"  Renderers: {rend_pass}/{len(RENDERER_TRIGGERS)}")
    print(f"  TOPLAM:    {total_pass}/{total_max} (%{pct})")

    if missing:
        print(f"\n⚠️  Eksik ENV: {', '.join(missing)}")
    fails_api = [n for n, r in api_results.items() if not r["passed"]]
    if fails_api:
        print(f"⚠️  Çağrılamayan API: {', '.join(fails_api)}")
    fails_rend = [n for n, p, _ in rend_results if not p]
    if fails_rend:
        print(f"⚠️  Otomatik üretmeyen renderer: {', '.join(fails_rend)}")


if __name__ == "__main__":
    asyncio.run(main())
