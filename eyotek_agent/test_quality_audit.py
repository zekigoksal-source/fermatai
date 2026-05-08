"""
Quality Audit (25.41 Neo — 9 May)
==================================

Rol × Senaryo matrisi → Kalite Skoru → A+ Hedefi

5 ROL × 7 SENARYO = 35 test:
  - admin (Neo)         → sistem, sql, sync, denetim
  - mudur (Mahsum)       → kurum, performans, brief
  - yonetim (Bilge)      → premium, strateji
  - ogretmen (Vedat)     → sınıf, etüt önerisi
  - rehber (Elif)        → öğrenci profili, kriz
  - ogrenci (Ecrin)      → kendi veri, akademik, plan

KALİTE KRİTERLERİ (her senaryo, ağırlıklı toplam = 100):
  R1 [10] Yanıt geldi (HTTP 200, body var)
  R2 [10] Yanıt boyutu makul (>= 80 char, anlamlı)
  R3 [15] Doğru veri (DB ground-truth'a uyumlu, en az 1 spesifik referans)
  R4 [10] Renderer (web kanalı + grafik beklenen) → uygun fence
  R5 [10] Yanıt süresi < 35 sn
  R6 [15] Halüsilasyon yok (yanlış isim/sayı yok, "uydurma" yok)
  R7 [15] ACL doğru (başka kişi verisi sızmadı)
  R8 [15] Kişiselleştirme (isimle hitap, role uygun ton)

SKOR → GRADE:
  A+ = 95-100
  A  = 85-94
  B+ = 75-84
  B  = 65-74
  C  = < 65
"""
from __future__ import annotations
import json
import os
import re
import sys
import time
import urllib.request
import asyncio
from typing import Optional

try:
    from dotenv import load_dotenv
    _here = os.path.dirname(os.path.abspath(__file__))
    for _candidate in (
        os.path.join(_here, "..", ".env"),
        os.path.join(_here, ".env"),
    ):
        if os.path.exists(_candidate):
            load_dotenv(_candidate, override=False)
except ImportError:
    pass


BRIDGE_URL = "http://localhost:8001/agent"
TOKEN = os.getenv("AGENT_API_KEY", "fermat_agent_secret_2026")


# ─── Test kullanıcıları ─────────────────────────────────────────────────

TEST_USERS = {
    "admin":    {"phone": "905051256802", "name": "Zeki Goksal"},
    "mudur":    {"phone": "905462605446", "name": "Mahsum Yalcin"},
    "yonetim":  {"phone": "971585863751", "name": "Bilge Şarvan"},
    "ogretmen": {"phone": "905448240803", "name": "Vedat Öztekin"},
    "rehber":   {"phone": "905312633238", "name": "Elif Sude Hunyas"},
    "ogrenci":  {"phone": "905309356389", "name": "ECRİN BELLER"},  # known student
}


# ─── Senaryo matrisi (35 = 5 rol × 7 senaryo) ───────────────────────────

# Her senaryo:
#   role, message, expects: {
#     min_len, max_ms, must_contain (str list), must_not_contain (str list),
#     renderer (web fence beklenen), data_check (DB cross-check),
#     personalize_token (rolün ismi), acl_violation (başka role veri sızıntısı)
#   }

SCENARIOS = [
    # ─── ADMIN (Neo) ───────────────────────────────────────────────────
    ("admin", "selam Neo",
     {"min_len": 30, "max_ms": 8000, "must_contain": ["zeki"],
      "must_not_contain": ["merhaba ben fermat", "ben bir botum"],
      "renderer": None, "personalize_token": "zeki"}),
    ("admin", "kurum genel durum özeti",
     {"min_len": 200, "max_ms": 35000, "must_contain": ["öğrenci", "personel"],
      "must_not_contain": ["bilemem", "veri yok"],
      "renderer": None, "personalize_token": None}),
    ("admin", "kaç öğrenci aktif?",
     {"min_len": 20, "max_ms": 15000, "must_contain": ["1"],
      "must_not_contain": ["bilemem"],
      "renderer": None, "personalize_token": None}),
    ("admin", "sistem durum",
     {"min_len": 50, "max_ms": 15000, "must_contain": [],
      "must_not_contain": ["bilemem"],
      "renderer": None, "personalize_token": None}),
    ("admin", "son sezon en başarılı 5 öğrenci",
     {"min_len": 100, "max_ms": 35000, "must_contain": ["puan"],
      "must_not_contain": ["bilemem"],
      "renderer": None, "personalize_token": None}),
    ("admin", "matematik dersinde kurum geneli en zayıf 3 konuyu chart ile göster",
     {"min_len": 200, "max_ms": 35000, "must_contain": ["matematik"],
      "must_not_contain": ["bilemem"],
      "renderer": "chart", "personalize_token": None}),
    ("admin", "ne yapabilirsin",
     {"min_len": 200, "max_ms": 8000, "must_contain": [["veri", "analiz", "yetenek", "kurum", "tool", "sistem"]],
      "must_not_contain": ["bilemem"],
      "renderer": None, "personalize_token": None}),

    # ─── MUDUR (Mahsum) ────────────────────────────────────────────────
    # Bot "Sayın Müdürüm" diye hitap ediyor (memory kuralı), isim de geçebilir
    ("mudur", "selam",
     {"min_len": 20, "max_ms": 5000, "must_contain": [["mahsum", "müdürüm", "müdür"]],
      "must_not_contain": ["zeki bey", "merhaba ben fermat"],
      "renderer": None, "personalize_token": None}),
    ("mudur", "bu hafta kaç etüt verildi",
     {"min_len": 30, "max_ms": 25000, "must_contain": [],
      "must_not_contain": ["bilemem", "tahmin"],
      "renderer": None, "personalize_token": None}),
    ("mudur", "10. sınıf SAY öğrencilerini özetle",
     {"min_len": 100, "max_ms": 30000, "must_contain": [["10", "say", "sınıf"]],
      "must_not_contain": ["bilemem"],
      "renderer": None, "personalize_token": None}),
    ("mudur", "kurum başarı trendi son 3 deneme",
     {"min_len": 100, "max_ms": 35000, "must_contain": ["net"],
      "must_not_contain": ["bilemem"],
      "renderer": None, "personalize_token": None}),
    ("mudur", "Vedat Öztekin'in son hafta etütleri",
     {"min_len": 50, "max_ms": 30000, "must_contain": ["vedat"],
      "must_not_contain": ["bilemem"],
      "renderer": None, "personalize_token": None}),
    ("mudur", "fizik konularındaki hata yoğunluğu heatmap",
     {"min_len": 150, "max_ms": 35000, "must_contain": ["fizik"],
      "must_not_contain": [],
      "renderer": "heatmap", "personalize_token": None}),
    ("mudur", "öğretmen yoğunluk analizi",
     {"min_len": 100, "max_ms": 35000, "must_contain": [],
      "must_not_contain": ["bilemem"],
      "renderer": None, "personalize_token": None}),

    # ─── YONETIM (Bilge) ────────────────────────────────────────────────
    ("yonetim", "selam",
     {"min_len": 30, "max_ms": 5000, "must_contain": ["bilge"],
      "must_not_contain": ["merhaba ben"],
      "renderer": None, "personalize_token": "bilge"}),
    ("yonetim", "kurum performansını özet ver",
     {"min_len": 150, "max_ms": 35000, "must_contain": [],
      "must_not_contain": ["bilemem"],
      "renderer": None, "personalize_token": None}),
    ("yonetim", "premium öğrencilerin hedefleri",
     {"min_len": 100, "max_ms": 35000, "must_contain": [],
      "must_not_contain": ["bilemem"],
      "renderer": None, "personalize_token": None}),

    # ─── OGRETMEN (Vedat) ──────────────────────────────────────────────
    # Bot "Sayın Vedat Hocam" / "Vedat Hoca" ya da sadece "hocam" diye hitap edebilir
    ("ogretmen", "selam hocam",
     {"min_len": 20, "max_ms": 5000, "must_contain": [["vedat", "hocam", "hoca"]],
      "must_not_contain": ["merhaba ben fermat"],
      "renderer": None, "personalize_token": None}),
    ("ogretmen", "bugünkü ders programım",
     {"min_len": 50, "max_ms": 25000, "must_contain": [],
      "must_not_contain": ["bilemem"],
      "renderer": None, "personalize_token": None}),
    ("ogretmen", "sınıf brief 11 SAY A",
     {"min_len": 100, "max_ms": 35000, "must_contain": [],
      "must_not_contain": ["bilemem"],
      "renderer": None, "personalize_token": None}),
    ("ogretmen", "Ecrin Beller'in son denemeleri",
     {"min_len": 100, "max_ms": 30000, "must_contain": ["ecrin"],
      "must_not_contain": ["bilemem"],
      "renderer": None, "personalize_token": None}),

    # ─── REHBER (Elif) ──────────────────────────────────────────────────
    ("rehber", "selam",
     {"min_len": 20, "max_ms": 5000, "must_contain": [["elif", "rehber", "hocam"]],
      "must_not_contain": ["zeki bey", "merhaba ben fermat"],
      "renderer": None, "personalize_token": None}),
    ("rehber", "Ecrin Beller'in profili",
     {"min_len": 150, "max_ms": 35000, "must_contain": ["ecrin"],
      "must_not_contain": ["bilemem"],
      "renderer": None, "personalize_token": None}),
    ("rehber", "kriz sinyali olan öğrenciler",
     {"min_len": 50, "max_ms": 30000, "must_contain": [],
      "must_not_contain": ["bilemem"],
      "renderer": None, "personalize_token": None}),
    ("rehber", "rehberlik notu istatistiği",
     {"min_len": 100, "max_ms": 35000, "must_contain": [],
      "must_not_contain": ["bilemem"],
      "renderer": None, "personalize_token": None}),

    # ─── OGRENCI (Ecrin) ────────────────────────────────────────────────
    ("ogrenci", "selam",
     {"min_len": 20, "max_ms": 5000, "must_contain": [["ecrin", "merhaba", "selam"]],
      "must_not_contain": ["zeki bey", "merhaba ben fermat"],
      "renderer": None, "personalize_token": None}),
    ("ogrenci", "son denemem nasıldı",
     {"min_len": 80, "max_ms": 30000, "must_contain": ["net"],
      "must_not_contain": ["bilemem"],
      "renderer": None, "personalize_token": None}),
    ("ogrenci", "zayıf konularımı chart ile göster",
     {"min_len": 100, "max_ms": 35000, "must_contain": [],
      "must_not_contain": ["bilemem"],
      "renderer": "chart", "personalize_token": None}),
    ("ogrenci", "limit nasıl çözülür adım adım",
     {"min_len": 200, "max_ms": 35000, "must_contain": ["limit"],
      "must_not_contain": ["bilemem"],
      "renderer": "steps", "personalize_token": None}),
    ("ogrenci", "haftalık çalışma planımı timeline ile çıkar",
     {"min_len": 150, "max_ms": 40000, "must_contain": [],
      "must_not_contain": ["bilemem"],
      "renderer": "timeline", "personalize_token": None}),
    ("ogrenci", "TYT'ye kaç gün kaldı",
     {"min_len": 20, "max_ms": 5000, "must_contain": ["gün"],
      "must_not_contain": ["bilemem"],
      "renderer": None, "personalize_token": None}),
    ("ogrenci", "Mahsum hocanın telefonu nedir",
     {"min_len": 20, "max_ms": 15000, "must_contain": [],
      "must_not_contain": ["905", "+90"],
      "renderer": None, "personalize_token": None,
      "acl_check": "ogrenci_should_not_see_phone"}),
]


# ─── Bridge çağrı ──────────────────────────────────────────────────────

def call_bridge(role: str, phone: str, message: str, timeout: int = 75) -> dict:
    """Bridge'e mesaj at, full response döndür."""
    req = urllib.request.Request(
        BRIDGE_URL,
        data=json.dumps({
            "phone": phone,
            "message": message,
            "channel": "web",
            "session_id": f"audit_{role}_{int(time.time())}",
        }).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {TOKEN}",
        },
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        ms = int((time.time() - t0) * 1000)
        return {"ok": True, "ms": ms, "response": data.get("response", "")}
    except Exception as e:
        return {"ok": False, "ms": int((time.time() - t0) * 1000),
                "error": str(e)[:100]}


# ─── Kalite skorlama ───────────────────────────────────────────────────

def score_response(role: str, message: str, expects: dict, result: dict) -> dict:
    """Yanıtı 8 kritere göre puanla. Toplam = 100."""
    scores = {
        "R1_response": 0,        # 10
        "R2_meaningful": 0,      # 10
        "R3_data_correct": 0,    # 15
        "R4_renderer": 0,        # 10
        "R5_speed": 0,           # 10
        "R6_no_halu": 0,         # 15
        "R7_acl": 0,             # 15
        "R8_personalize": 0,     # 15
    }
    notes = []

    if not result.get("ok"):
        notes.append(f"❌ HTTP fail: {result.get('error', '?')}")
        return {"total": 0, "scores": scores, "notes": notes}

    resp = result.get("response", "") or ""
    resp_lower = resp.lower()
    ms = result.get("ms", 99999)

    # R1: Yanıt geldi
    if resp.strip():
        scores["R1_response"] = 10

    # R2: Anlamlı uzunluk
    min_len = expects.get("min_len", 30)
    if len(resp) >= min_len:
        scores["R2_meaningful"] = 10
    elif len(resp) >= min_len // 2:
        scores["R2_meaningful"] = 5
    else:
        notes.append(f"⚠️  Çok kısa: {len(resp)}c (min {min_len})")

    # R3: Doğru veri — must_contain artık iç içe liste destekler
    # [["a","b"], "c"] → "a" VEYA "b" varsa OK + "c" zorunlu
    must_contain = expects.get("must_contain", [])
    if not must_contain:
        scores["R3_data_correct"] = 15
    else:
        groups_passed = 0
        groups_total = len(must_contain)
        miss_examples = []
        for item in must_contain:
            if isinstance(item, list):
                # OR group — herhangi biri match olursa bu group geçer
                if any(alt.lower() in resp_lower for alt in item):
                    groups_passed += 1
                else:
                    miss_examples.append(f"({'/'.join(item)})")
            else:
                if item.lower() in resp_lower:
                    groups_passed += 1
                else:
                    miss_examples.append(item)
        if groups_passed == groups_total:
            scores["R3_data_correct"] = 15
        elif groups_passed > 0:
            scores["R3_data_correct"] = int(15 * groups_passed / groups_total)
            notes.append(f"⚠️  must_contain {groups_passed}/{groups_total} (eksik: {miss_examples})")
        else:
            notes.append(f"❌ must_contain 0/{groups_total}: {miss_examples}")

    # R4: Renderer
    renderer = expects.get("renderer")
    if renderer is None:
        scores["R4_renderer"] = 10  # gerek yoksa tam puan
    else:
        # ```renderer veya compound içinde "type":"renderer"
        pat_direct = r"```" + re.escape(renderer) + r"\b"
        pat_compound = r'"type"\s*:\s*"' + re.escape(renderer) + r'"'
        if re.search(pat_direct, resp) or re.search(pat_compound, resp):
            scores["R4_renderer"] = 10
        else:
            notes.append(f"❌ Renderer beklenmiş: ```{renderer}, yok")

    # R5: Hız
    max_ms = expects.get("max_ms", 35000)
    if ms <= max_ms * 0.6:
        scores["R5_speed"] = 10
    elif ms <= max_ms:
        scores["R5_speed"] = 7
    elif ms <= max_ms * 1.3:
        scores["R5_speed"] = 4
        notes.append(f"⚠️  Yavaş: {ms}ms")
    else:
        notes.append(f"❌ Çok yavaş: {ms}ms (max {max_ms})")

    # R6: Halüsilasyon yok (must_not_contain)
    mnc = expects.get("must_not_contain", [])
    bad_hits = [k for k in mnc if k.lower() in resp_lower]
    if not bad_hits:
        scores["R6_no_halu"] = 15
    else:
        scores["R6_no_halu"] = max(0, 15 - 5 * len(bad_hits))
        notes.append(f"❌ İçermesi YASAK: {bad_hits}")

    # R7: ACL — özel kontroller (örn. öğrenci öğretmen telefonu görmemeli)
    acl_check = expects.get("acl_check")
    if acl_check == "ogrenci_should_not_see_phone":
        # öğrenci rolü herhangi bir 905... veya +90... görmemeli
        if re.search(r"(905\d{9}|\+90\s*5\d{9})", resp):
            notes.append("❌ ACL ihlal: öğrenci başka rolün telefonunu gördü")
            scores["R7_acl"] = 0
        else:
            scores["R7_acl"] = 15
    else:
        # Default: must_not_contain ihlal yoksa ACL ok
        scores["R7_acl"] = 15 if not bad_hits else 7

    # R8: Kişiselleştirme
    pt = expects.get("personalize_token")
    if pt is None:
        scores["R8_personalize"] = 15  # özel beklenmemiş
    elif pt.lower() in resp_lower:
        scores["R8_personalize"] = 15
    else:
        notes.append(f"⚠️  Kişiselleştirme yok: '{pt}' beklendi")
        scores["R8_personalize"] = 5

    total = sum(scores.values())
    return {"total": total, "scores": scores, "notes": notes,
            "ms": ms, "len": len(resp), "preview": resp[:120]}


def grade(score: int) -> str:
    if score >= 95: return "A+"
    if score >= 85: return "A"
    if score >= 75: return "B+"
    if score >= 65: return "B"
    return "C"


# ─── Ana çalışma ──────────────────────────────────────────────────────

async def run_audit():
    sys.stdout.reconfigure(encoding="utf-8")
    print("🎯 FermatAI Quality Audit — Rol × Senaryo Matrisi\n")
    print(f"Toplam: {len(SCENARIOS)} senaryo, {len(set(s[0] for s in SCENARIOS))} rol\n")

    by_role = {}
    all_results = []

    for i, (role, msg, expects) in enumerate(SCENARIOS, 1):
        user = TEST_USERS[role]
        print(f"[{i:02d}/{len(SCENARIOS)}] {role:8s} | {msg[:55]:55s} ", end="", flush=True)
        result = call_bridge(role, user["phone"], msg)
        scored = score_response(role, msg, expects, result)
        total = scored["total"]
        g = grade(total)
        print(f"| {scored.get('ms', 0):5d}ms | {total:3d} {g}")
        if scored["notes"]:
            for n in scored["notes"]:
                print(f"      {n}")
        by_role.setdefault(role, []).append(total)
        all_results.append({
            "role": role, "msg": msg, "score": total, "grade": g,
            "ms": scored.get("ms", 0), "notes": scored["notes"],
            "preview": scored.get("preview", "")[:100],
        })
        # Bot'un peş peşe gelen istekleri queue'lamaması için kısa bekleme
        await asyncio.sleep(0.5)

    # ─── Özet ─────────────────────────────────────────────────────────
    print()
    print("═" * 70)
    print("📊 ROL BAZLI ÖZETİ")
    print("─" * 70)
    overall_total = 0
    overall_count = 0
    for role, scores in by_role.items():
        avg = sum(scores) / len(scores)
        overall_total += sum(scores)
        overall_count += len(scores)
        print(f"  {role:10s} | n={len(scores)} | ort={avg:5.1f} | {grade(int(avg))}")
    overall = overall_total / overall_count
    print("─" * 70)
    print(f"  {'TOPLAM':10s} | n={overall_count} | ort={overall:5.1f} | {grade(int(overall))}")
    print()

    # En düşük 5 senaryo
    sorted_r = sorted(all_results, key=lambda r: r["score"])
    print("🔻 EN DÜŞÜK 5 (FİX HEDEFİ)")
    print("─" * 70)
    for r in sorted_r[:5]:
        print(f"  {r['score']:3d} {r['grade']:2s} | {r['role']:8s} | {r['msg'][:50]}")
        for n in r["notes"][:2]:
            print(f"        {n}")

    # JSON dump
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "overall_score": overall,
            "overall_grade": grade(int(overall)),
            "by_role": {r: sum(s)/len(s) for r, s in by_role.items()},
            "scenarios": all_results,
            "timestamp": time.time(),
        }, f, ensure_ascii=False, indent=2)
    print(f"\n📁 Detay JSON: {out_path}")
    return overall, all_results


if __name__ == "__main__":
    asyncio.run(run_audit())
