"""
Renderer Hint Inject (25.41 Neo — 9 May)
=========================================

Sorun: Bot kullanıcı "grafik göster", "trend yap", "kıyasla" dese bile sadece
       markdown tablo döndürüyor — chart/compare2/timeline blok ÜRETMIYOR.

Çözüm: Mesajdaki keyword pattern'larından renderer ihtiyacını tespit et,
       Claude system prompt'una SERT direktif inject et.

Kullanım:
  from renderer_hint_inject import detect_renderer_need, build_hint
  hint = build_hint(user_message, channel="web")
  if hint:
      system_prompt += hint

Pattern → renderer eşleştirme (Cerebras INTENT_RENDERER_MAP ile uyumlu):
  - sayı/grafik/trend          → chart, line, bar
  - karşılaştır/kıyas/vs       → compare2, chart
  - dağılım/yüzde              → chart (pie/donut), gauge
  - plan/zaman/gün             → timeline
  - karne/yetkinlik            → radar, karne
  - hedef/yüzde tamamlanma     → gauge, progress
  - adım/çözüm                 → steps, formula
  - kavram/ilişki              → kgraph
  - quiz/soru/test üretim      → quiz, steps
"""
from __future__ import annotations
import re
from typing import Optional


# Pattern → [renderers] (priority high→low — ÜST PATTERN ÖNCE EŞLEŞİR)
RENDERER_PATTERNS = [
    # --- KAVRAM HARİTASI / İLİŞKİ (en yüksek öncelik — "kavram harita" steps'ten önce) ---
    (
        r"(kgraph|kavram\s*harita|kavram\s*ilişki|ilişki\s*göster|"
        r"ilişki\s*\w+\s*göster|bağlantı\s*ağ|"
        r"node\s*graph|knowledge\s*graph|ağaç\s*yapı|hiyerarşi)",
        ["kgraph"],
    ),
    # --- ZAMAN ÇİZGİSİ / PLAN (chart'tan önce — "haftalık plan" timeline) ---
    (
        r"(zaman\s*çizgi|tarih\s*sırası|haftalık\s*plan|aylık\s*plan|"
        r"ay\s*ay|gün\s*gün|takvim|roadmap|yol\s*haritası|"
        r"timeline|haftalık\s*program|aylık\s*program)",
        ["timeline"],
    ),
    # --- KARŞILAŞTIRMA (chart'tan önce) ---
    (
        r"(kıyas|karşılaştır|kar[sş][ıi]la[sş]t[ıi]r|vs\b|fark[ıi]|"
        r"versus|aralarındaki\s*fark|hangisi\s*daha|compare)",
        ["compare2", "chart"],
    ),
    # --- KARNE / YETKINLIK / RADAR (chart'tan önce) ---
    (
        r"(karne|yetkinlik|ders\s*ders|radar|spider|"
        r"güçlü\s*konu.*zayıf\s*konu|profil\s*skor|skor\s*tablosu)",
        ["radar", "karne"],
    ),
    # --- HEDEF / YÜZDE TAMAMLAMA (chart'tan önce) ---
    (
        r"(hedef\s*yüzde|hedef\s*yüzdesi|tamamlanma|ilerleme\s*yüzdesi|"
        r"%\s*kaç|kaç\s*yüzde|hedef.*kaç|gauge|ölçek|skala|"
        r"hedef.*\d+|tyt.*hedef|ayt.*hedef)",
        ["gauge", "progress"],
    ),
    # --- VERİ GÖRSELLEŞTİRME (genel chart) ---
    (
        r"(grafik|chart|görsel|şema|dağılım|trend|gidişat|"
        r"kullanıcı\s*say|kişi\s*say|mesaj\s*say|"
        r"son\s*\d+\s*gün|haftalık|aylık|günlük\s*say|"
        r"oran|yüzde|pasta|sütun|bar)",
        ["chart"],
    ),
    # --- ADIM ADIM ÇÖZÜM / FORMUL ---
    (
        r"(adım\s*adım|step\s*by|nasıl\s*çözülür|çözümünü|"
        r"formül|formula|denklem|integral|türev|limit)\b",
        ["steps", "formula"],
    ),
    # --- QUIZ / TEST ÜRETİM ---
    (
        r"(quiz|test\s*üret|soru\s*üret|yeni\s*nesil\s*soru|"
        r"alıştırma|pratik\s*soru|deneme\s*sorusu)\b",
        ["quiz", "steps"],
    ),
    # --- HEATMAP / YOĞUNLUK ---
    (
        r"(heatmap|ısı\s*harita|yoğunluk\s*harita|hata\s*yoğun|"
        r"sıklık\s*harita|matris\s*görsel|crosstab)",
        ["heatmap"],
    ),
    # --- 3D / MOLEKÜL / SİMÜLASYON ---
    (
        r"(3d\b|üç\s*boyut|molekül|atom\s*model|kristal\s*yapı|"
        r"mol3d|kimyasal\s*yapı)",
        ["mol3d", "3d"],
    ),
    # --- SES / DALGA / FREKANS ---
    (
        r"(ses\s*dalga|frekans|hertz|titreşim|ses\s*analiz|"
        r"do\s*re\s*mi|nota|akor)",
        ["sound"],
    ),
    # --- DESMOS / FONKSİYON GRAFİĞİ ---
    (
        r"(desmos|fonksiyon\s*graf|y\s*=\s*f\(x\)|parabol|hiperbol|"
        r"sinüs\s*graf|kosinüs\s*graf|polinom\s*graf)",
        ["desmos", "plotly"],
    ),
    # --- GEOGEBRA / GEOMETRİ ---
    (
        r"(geogebra|geometri\s*çiz|üçgen\s*çiz|daire\s*çiz|"
        r"açı\s*ölç|prizma|piramit|dikdörtgen)",
        ["geogebra"],
    ),
    # --- MERMAID / AKIŞ ŞEMASI ---
    (
        r"(mermaid|akış\s*şema|flowchart|state\s*diagram|"
        r"sequence\s*diagram|er\s*diagram)",
        ["mermaid"],
    ),
    # --- KOD / EXAMPLES ---
    (
        r"(kod\s*örnek|kod\s*yaz|kod\s*çıkar|programla|"
        r"javascript|python|c\+\+|kotlin)\b",
        ["codeout"],
    ),
    # --- ELEMENT / PERIYODİK TABLO ---
    (
        r"(element|periyodik\s*tab|atom\s*numara|kimyasal\s*sembol|"
        r"hidrojen|karbon|oksijen)\b",
        ["element"],
    ),
    # --- HAFIZA / RECALL / TEKRAR ---
    (
        r"(recall|tekrar\s*soru|aklımda\s*kalsın|hafıza\s*tazele|"
        r"flashcard|aralıklı\s*tekrar|spaced)",
        ["recall"],
    ),
    # --- BİLEŞİK / COMPOUND ---
    (
        r"(bileşik|compound|reaksiyon|denklik|tepkime\s*denk)",
        ["compound"],
    ),
    # --- HESAP / CALC ---
    (
        r"(hesapla|kalkül|calc|işlem\s*sonucu|toplam\s*kaç|"
        r"sonuç\s*kaç|net\s*hesap)",
        ["calc"],
    ),
    # --- SİMÜLASYON / FİZİK ---
    (
        r"(sim\b|simülasyon|fizik\s*simül|sarkaç|harmonik|"
        r"yay\s*hareket|atwood)",
        ["sim"],
    ),
    # --- VR / SANAL GERÇEKLİK ---
    (
        r"(vr\b|sanal\s*gerçek|360\s*derece|immersif|metaverse)",
        ["vr"],
    ),
    # --- EXCALIDRAW / ÇİZİM ---
    (
        r"(excalidraw|elle\s*çiz|kroki|taslak\s*çiz)",
        ["excalidraw"],
    ),
]


def detect_renderer_need(message: str) -> list[str]:
    """Mesajdan ihtiyaç duyulan renderer'ları tespit et.

    Returns: ["chart", "compare2"] gibi liste (priority, dedup)
    """
    if not message or len(message) < 6:
        return []
    msg = message.lower()
    found: list[str] = []
    for pattern, renderers in RENDERER_PATTERNS:
        if re.search(pattern, msg, re.IGNORECASE):
            for r in renderers:
                if r not in found:
                    found.append(r)
    # Maksimum 3 — fazla seçim olunca model karar veremiyor
    return found[:3]


def build_hint(message: str, channel: str = "web") -> Optional[str]:
    """Mesajdan renderer ihtiyacı varsa SERT system prompt direktif döndür.

    Args:
        message: Son user mesajı
        channel: 'web' | 'whatsapp' | ... (sadece web'de inject)

    Returns:
        Inject edilecek string ya da None (gerek yok)
    """
    if channel != "web":
        return None
    renderers = detect_renderer_need(message)
    if not renderers:
        return None
    r_block = " + ".join(f"```{r}" for r in renderers)
    return (
        f"\n\n🎨 [RENDERER — ZORUNLU İNJECT]: {r_block}\n"
        f"Kullanıcı mesajı bu blok(lar)ı tetikledi. Web kanalında düz markdown\n"
        f"YETERSIZ — yanıtın içinde MUTLAKA yukarıdaki kod fence'lerini\n"
        f"(geçerli JSON/string ile) ÜRET. Aksi halde cevap eksik kalır.\n"
        f"Bot grafik/karşılaştırma istenince tablo sunup chart üretmeme = bug."
    )


# ─── TEST ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    cases = [
        "son 7 gün kullanıcı sayısı grafiği",
        "matematik ve fizik netlerini karşılaştır",
        "ders bazlı yetkinlik karne göster",
        "TYT puanım % kaç tamamlandı",
        "haftalık çalışma planı",
        "limit nasıl çözülür adım adım",
        "kavram haritası türev integral",
        "yeni nesil 4 örnek soru üret",
        "selam nasılsın",  # NONE beklenir
        "ben kimim",  # NONE beklenir
    ]

    print("🧪 Renderer Hint Detection Test\n")
    for msg in cases:
        renderers = detect_renderer_need(msg)
        hint = build_hint(msg, "web")
        marker = "✓" if renderers else "—"
        rstr = ", ".join(renderers) if renderers else "(yok)"
        print(f"  {marker} {msg:50s} → {rstr}")
    print()
    print("Web kanalı, son test mesajıyla hint preview:")
    print(build_hint("son 7 gün kullanıcı sayısı grafiği"))
