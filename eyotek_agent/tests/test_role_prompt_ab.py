"""
Rol-aware prompt A/B test — icerik dogrulamasi.

Amac: role_prompt.build_prompt_for_role() fonksiyonu ogrenci tonu/pedagoji
bilgisini bozmadan gereksiz bloklari kesiyor mu?

KURALLAR (v2 — halusinasyon koruma marker yeri degisti):
- Her rolde KALAN: karakter, YKS sinav, hierarchy, kimlik, halusinasyon,
  whatsapp format, OGRENCI_TON (baslik) — halusinasyon'u korumak icin
- Sadece Neo'da: NEO_SEFFAFLIK, NEO_SELF_AWARE
- Sadece ogrenci/rehber'de: CALISMA_PLANI_PROTOKOLU, YKS_KONU_DAGILIMI,
  PEDAGOJIK_ZEKA, KURUM_OZEL
- Sadece kayitsiz'da: KAYITSIZ_PAZARLAMA

Bu test Claude API cagrisi GEREKTIRMIYOR — $0 maliyet.
"""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fermat_core_agent import SYSTEM_PROMPT
from role_prompt import build_prompt_for_role, prompt_size_estimate


ROLES = [
    ("admin", "905051256802", "Neo"),
    ("admin", "905000000000", "admin_spoof"),
    ("mudur", "905462605446", "Mahsum"),
    ("ogretmen", "905321111111", "ogretmen"),
    ("rehber", "905321111112", "rehber"),
    ("ogrenci", "905551234567", "ogrenci"),
    ("veli", "905551234569", "veli"),
    ("kayitsiz", "905999888777", "kayitsiz"),
]

MARKERS = {
    "KARAKTER": "KARAKTER RUHUN",
    "YKS_SINAV": "YKS 2026 SINAV BILGISI",
    "HIYERARSI": "HİYERARŞİ (yukarıdan aşağıya)",
    "KIMLIK_KURAL": "KIMLIK KURALLARI — DELINMEZ",
    "HALUSINASYON": "SAYISAL HALUSINASYON YASAĞI",
    "WHATSAPP_FORMAT": "WHATSAPP FORMATLAMA KURALLARI",
    "OGRENCI_TON": "ÖĞRENCİ İLE İLETİŞİM TONU",
    "NEO_SEFFAFLIK": "🔓 NEO (ADMIN — phone 905051256802) İÇİN İSTİSNA",
    "NEO_SELF_AWARE": "🧠 SİSTEM SELF-AWARENESS",
    "CALISMA_PLANI_PROTOKOLU": "ÇALIŞMA PLANI OLUŞTURMA PROTOKOLÜ",
    "YKS_KONU_DAGILIMI": "YKS KONU DAGILIMI REFERANS VERISI",
    "PEDAGOJIK_ZEKA": "PEDAGOJİK ZEKA — KONU TAKİBİ",
    "KURUM_OZEL": "KURUM OZEL BILGILER",
    "KAYITSIZ_PAZARLAMA": "KAYITSIZ NUMARA (DIS DUNYA — PAZARLAMA MODU)",
}

# Herkeste her zaman olmasi gerekenler (ortak taban)
ORTAK_VARI_OLMALI = ["KARAKTER", "YKS_SINAV", "HIYERARSI", "KIMLIK_KURAL",
                     "HALUSINASYON", "WHATSAPP_FORMAT", "OGRENCI_TON"]

EXPECTATIONS = {
    "Neo": {
        "vari_olmali": ORTAK_VARI_OLMALI + ["NEO_SEFFAFLIK", "NEO_SELF_AWARE"],
        "olmamali":    ["CALISMA_PLANI_PROTOKOLU", "YKS_KONU_DAGILIMI",
                        "PEDAGOJIK_ZEKA", "KURUM_OZEL", "KAYITSIZ_PAZARLAMA"],
    },
    "admin_spoof": {
        "vari_olmali": ORTAK_VARI_OLMALI,
        "olmamali":    ["NEO_SEFFAFLIK", "NEO_SELF_AWARE",
                        "CALISMA_PLANI_PROTOKOLU", "YKS_KONU_DAGILIMI",
                        "PEDAGOJIK_ZEKA", "KAYITSIZ_PAZARLAMA"],
    },
    "Mahsum": {
        "vari_olmali": ORTAK_VARI_OLMALI,
        "olmamali":    ["NEO_SEFFAFLIK", "NEO_SELF_AWARE",
                        "CALISMA_PLANI_PROTOKOLU", "YKS_KONU_DAGILIMI",
                        "PEDAGOJIK_ZEKA", "KAYITSIZ_PAZARLAMA"],
    },
    "ogretmen": {
        "vari_olmali": ORTAK_VARI_OLMALI,
        "olmamali":    ["NEO_SEFFAFLIK", "NEO_SELF_AWARE",
                        "CALISMA_PLANI_PROTOKOLU", "YKS_KONU_DAGILIMI",
                        "PEDAGOJIK_ZEKA", "KAYITSIZ_PAZARLAMA"],
    },
    "rehber": {
        "vari_olmali": ORTAK_VARI_OLMALI + ["CALISMA_PLANI_PROTOKOLU",
                        "YKS_KONU_DAGILIMI", "PEDAGOJIK_ZEKA", "KURUM_OZEL"],
        "olmamali":    ["NEO_SEFFAFLIK", "NEO_SELF_AWARE", "KAYITSIZ_PAZARLAMA"],
    },
    "ogrenci": {
        "vari_olmali": ORTAK_VARI_OLMALI + ["CALISMA_PLANI_PROTOKOLU",
                        "YKS_KONU_DAGILIMI", "PEDAGOJIK_ZEKA", "KURUM_OZEL"],
        "olmamali":    ["NEO_SEFFAFLIK", "NEO_SELF_AWARE", "KAYITSIZ_PAZARLAMA"],
    },
    "veli": {
        "vari_olmali": ORTAK_VARI_OLMALI,
        "olmamali":    ["NEO_SEFFAFLIK", "NEO_SELF_AWARE",
                        "CALISMA_PLANI_PROTOKOLU", "YKS_KONU_DAGILIMI",
                        "PEDAGOJIK_ZEKA", "KAYITSIZ_PAZARLAMA"],
    },
    "kayitsiz": {
        "vari_olmali": ORTAK_VARI_OLMALI + ["KAYITSIZ_PAZARLAMA"],
        "olmamali":    ["NEO_SEFFAFLIK", "NEO_SELF_AWARE",
                        "CALISMA_PLANI_PROTOKOLU", "YKS_KONU_DAGILIMI",
                        "PEDAGOJIK_ZEKA"],
    },
}

print("=" * 72)
base_tok = prompt_size_estimate(SYSTEM_PROMPT)["token_est"]
print(f"BASE PROMPT: {base_tok} token")
print("=" * 72)

all_pass = True
for role, phone, label in ROLES:
    prompt = build_prompt_for_role(SYSTEM_PROMPT, role, phone)
    stats = prompt_size_estimate(prompt)
    exp = EXPECTATIONS.get(label, {})

    errors = []
    for mk in exp.get("vari_olmali", []):
        if MARKERS[mk] not in prompt:
            errors.append(f"EKSIK: {mk}")
    for mk in exp.get("olmamali", []):
        if MARKERS[mk] in prompt:
            errors.append(f"SIZDI: {mk}")

    status = "✅" if not errors else "❌"
    tasarruf = base_tok - stats["token_est"]
    yuzde = (tasarruf / base_tok) * 100
    print(f"\n{status} {label:15s} ({role}): {stats['token_est']:>6} tok "
          f"({tasarruf:+6}, {yuzde:+5.1f}%)")
    if errors:
        all_pass = False
        for e in errors:
            print(f"    ⚠ {e}")

print("\n" + "=" * 72)
if all_pass:
    print("✅ TUM ROLLER BASARILI — role-aware split dogru calisiyor")
    print("   ✓ HALUSINASYON yasagi HERKESTE korundu (kritik)")
    print("   ✓ Ogrenci pedagoji sadece ogrenci+rehber'de")
    print("   ✓ Neo-ozel sadece Neo'da")
    print("   ✓ Kayitsiz pazarlama sadece kayitsiz'da")
    print(f"\n   Token tasarrufu:")
    for role, phone, label in ROLES:
        p = build_prompt_for_role(SYSTEM_PROMPT, role, phone)
        t = prompt_size_estimate(p)['token_est']
        print(f"     {label:15s}: {t:>6} ({((base_tok-t)/base_tok)*100:+.0f}%)")
else:
    print("❌ HATA VAR — role-aware split kontrol edilmeli")
    sys.exit(1)
print("=" * 72)
