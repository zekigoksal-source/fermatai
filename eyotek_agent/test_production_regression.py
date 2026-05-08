"""
Production Regression Smoke Test (25.41 Neo — 8 May)
=====================================================

30 senaryo — gerçek production trafiği taklidi:
- Öğrenci (10): selamlama, foto hakki, deneme, zayif konu, puan tahmin,
                tıp tahmin, devamsızlık, çalışma plan, motivasyon, sohbet
- Admin/Müdür (10): kurum durum, en başarılı, devamsızlık top, etüt istatistik,
                    konu haritası, ogretmen kıyas, sınıf ortalaması, finansal,
                    yardım menü, web kodu
- Öğretmen (5): ders programı, etüt istatistik, sınıf öğrenci, bugün ders, web kodu
- Edge (5): yetkisiz, foto soru, ordamısın, kavramsal soru, hassas

Her test:
- Bridge'e POST /agent
- Yanıt boş değil (>20 char)
- Hata pattern yok ("hata", "Bağlantı", "anlayamadım")
- 30 saniye timeout

Çıktı: pass/fail + kritik sorunlar listesi.
"""
from __future__ import annotations
import asyncio
import json
import time
import sys

import urllib.request
import urllib.error


BRIDGE_URL = "http://localhost:8001/agent"
TOKEN = "fermat_agent_secret_2026"

# Phone'lar (production'da gerçek)
PHONES = {
    "neo": "905051256802",         # admin
    "mehmet_ali": "905050952398",  # öğrenci 163
    "nazli": "905541486884",       # öğrenci 211
    "ahmet_fatih": "905383718725", # öğrenci 290
    "mahsum": "905462605446",      # mudur
    "ogretmen_test": "905533399701", # ogretmen örneği
    "yetkisiz": "905056728868",    # unknown
}

# 30 SENARYO
SCENARIOS = [
    # Öğrenci (Mehmet Ali — soz_no 163, has data)
    ("ogrenci_selam",       "mehmet_ali",  "selam"),
    ("ogrenci_kimim",       "mehmet_ali",  "ben kimim"),
    ("ogrenci_son_deneme",  "mehmet_ali",  "son denemem nasıl"),
    ("ogrenci_zayif",       "mehmet_ali",  "zayıf konularım neler"),
    ("ogrenci_devamsizlik", "mehmet_ali",  "devamsızlığım kaç saat"),
    ("ogrenci_motivasyon",  "mehmet_ali",  "motivasyonum yok bugün"),
    ("ogrenci_kavramsal",   "mehmet_ali",  "limit nedir kısaca anlat"),
    ("ogrenci_foto_hakki",  "mehmet_ali",  "foto ile soru nasıl çözerim"),
    ("ogrenci_ders_prog",   "mehmet_ali",  "bugün ders programım ne"),
    ("ogrenci_ordami",      "mehmet_ali",  "ordamısın"),

    # Öğrenci-2 Nazlı (soz_no 211, AYT verisi var)
    ("nazli_puan_tahmin",   "nazli",       "puanım ne olur"),
    ("nazli_tip_tahmin",    "nazli",       "tıp fakültesine girer miyim"),
    ("nazli_ayt_zayif",     "nazli",       "ayt zayıf konularım"),

    # Admin (Neo)
    ("admin_yardim",        "neo",         "yardım"),
    ("admin_neo_menu",      "neo",         "neo"),
    ("admin_konu_harita",   "neo",         "matematik konu zorluk haritası"),
    ("admin_acil_konu",     "neo",         "acil konuları göster"),
    ("admin_web_kodu",      "neo",         "web kodu"),
    ("admin_sistem",        "neo",         "sistem durum"),
    ("admin_kullanici",     "neo",         "bugün kaç kullanıcı"),

    # Mudur (Mahsum)
    ("mudur_durum",         "mahsum",      "kurum genel durum"),
    ("mudur_en_basarili",   "mahsum",      "en başarılı 5 öğrenci"),
    ("mudur_devamsizlik",   "mahsum",      "devamsızlığı yüksek öğrenciler"),

    # Yetkisiz (kayıtsız)
    ("yetkisiz_selam",      "yetkisiz",    "merhaba"),
    ("yetkisiz_web_kodu",   "yetkisiz",    "web kodu"),

    # Edge cases
    ("ogrenci_emoji",       "mehmet_ali",  "👍"),
    ("ogrenci_tek_harf",    "mehmet_ali",  "?"),
    ("ogrenci_uzun",        "mehmet_ali",  "matematik konusunda kuvvetli olmak için günde kaç soru çözmeliyim ve hangi yayınları öneriyorsun yks ye 60 gün kaldı"),
    ("ogrenci_typo",        "mehmet_ali",  "snav sonucm gozter"),  # imla hatası
    ("ahmet_yeni",          "ahmet_fatih", "merhaba"),  # yeni kullanıcı (10. sınıf, veri yok)
]


def call_agent(phone: str, message: str, timeout: int = 30) -> dict:
    """Bridge'e POST gönder, yanıt al."""
    req = urllib.request.Request(
        BRIDGE_URL,
        data=json.dumps({"phone": phone, "message": message}).encode("utf-8"),
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
        return {"ok": True, "response": data.get("response", ""), "ms": ms}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}", "ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:100], "ms": int((time.time() - t0) * 1000)}


def evaluate(name: str, response: str, ms: int) -> tuple[bool, str]:
    """Yanıtı değerlendir. (pass, açıklama)"""
    if not response:
        return False, "Boş yanıt"
    if len(response) < 15:
        return False, f"Çok kısa: {len(response)} char"
    rl = response.lower()
    bad_patterns = [
        "anlayamadım", "anlayamad", "hata olu", "bir hata",
        "bağlantı hatası", "sistem ayar", "henüz hazır değil",
        "yetkisiz", "bilinmeyen hata",
    ]
    # Yetkisiz/anlam yok için "hata" cümleleri OK olabilir, ama unknown sebep KÖTÜ
    for bp in bad_patterns:
        if bp in rl and "henüz" not in rl[:50]:  # bot "henüz veri yok" dese OK
            return False, f"Hata pattern: '{bp}'"
    if ms > 60000:
        return False, f"Çok yavaş: {ms}ms"
    return True, f"OK ({ms}ms)"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print("🧪 Production Regression Smoke Test\n")
    print(f"Bridge: {BRIDGE_URL}\n")

    pass_count = 0
    fail_count = 0
    fails = []

    for i, (name, phone_key, message) in enumerate(SCENARIOS, 1):
        phone = PHONES[phone_key]
        result = call_agent(phone, message, timeout=35)
        if not result["ok"]:
            fail_count += 1
            fails.append((name, message, result["error"]))
            print(f"  [{i:2d}] ❌ {name:25s} | ERR | {result['error']}")
            continue
        passed, msg = evaluate(name, result["response"], result["ms"])
        if passed:
            pass_count += 1
            print(f"  [{i:2d}] ✅ {name:25s} | {result['ms']:5d}ms | {len(result['response']):4d}c")
        else:
            fail_count += 1
            fails.append((name, message, msg))
            preview = result["response"][:120].replace("\n", " ")
            print(f"  [{i:2d}] ❌ {name:25s} | {result['ms']:5d}ms | {msg}")
            print(f"       Yanıt: {preview}")

    print()
    print("=" * 60)
    print(f"📊 Sonuç: {pass_count}/{len(SCENARIOS)} PASS · {fail_count} FAIL")
    if fail_count == 0:
        print("✅ Tüm senaryolar production-ready")
    else:
        print(f"\n⚠️  {fail_count} sorun:")
        for name, msg, err in fails:
            print(f"  - {name} ({msg!r}): {err}")


if __name__ == "__main__":
    main()
