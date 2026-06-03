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
    # ════════════════════════════════════════════════════════════════════
    # 25.43 (Neo: 8 yeni render) — sankey/treemap/parallel/force/vega/jsx/cesium/manim
    # ════════════════════════════════════════════════════════════════════
    # --- SANKEY / AKIŞ DİYAGRAMI ---
    (
        r"(sankey|akış\s*diyagram|akış\s*görsel|kaynak\s*hedef|"
        r"akış\s*haritası|nereden\s*nereye|geçiş\s*şema|"
        r"net\s*kazan|net\s*akış|kaybedilen\s*net|kazanılan\s*net)",
        ["sankey"],
    ),
    # --- TREEMAP / ALAN ORANI ---
    (
        r"(treemap|alan\s*harita|orantılı\s*kutu|hiyerarşi\s*alan|"
        r"konu\s*ağırlık|ders\s*ağırlık|yüzde\s*alan|kapsam\s*haritası|"
        r"ağırlık\s*dağıl)",
        ["treemap"],
    ),
    # --- PARALLEL COORDS / ÇOKLU BOYUT ---
    (
        r"(paralel\s*koordinat|çoklu\s*boyut|multi\s*dim|"
        r"birden\s*çok\s*ölçüt|öğrenciler\s*kıyas|sınıf\s*sınıf\s*kıyas|"
        r"birden\s*fazla\s*öğrenci.*kıyas)",
        ["parallel"],
    ),
    # --- FORCE GRAPH / DİNAMİK BİLGİ AĞI ---
    (
        r"(force\s*graph|dinamik\s*ağ|bilgi\s*ağı\s*interaktif|"
        r"konu\s*ilişki\s*ağı|kavram\s*haritası\s*interaktif|"
        r"sürüklenebilir\s*ağ|node\s*sürükle)",
        ["force_graph"],
    ),
    # --- VEGA-LITE / DECLARATIVE ---
    (
        r"(vega|vegalite|vega-lite|declarative\s*chart|"
        r"json\s*spec\s*chart|grammar\s*of\s*graphics)",
        ["vega_lite"],
    ),
    # --- JSXGRAPH / İNTERAKTİF GEOMETRİ + KALKÜLÜS ---
    (
        r"(jsxgraph|interaktif\s*geometri|sürüklenebilir\s*geometri|"
        r"interaktif\s*kalkülüs|interaktif\s*fonksiyon|"
        r"slider\s*ile\s*geometri|nokta\s*sürükle)",
        ["jsxgraph"],
    ),
    # --- CESIUM / 3D GLOBE / DÜNYA HARİTA ---
    (
        r"(cesium|3d\s*dünya|globe|3d\s*harita|"
        r"dünya\s*üzerinde|enlem\s*boylam\s*göster|harita\s*üzerinde\s*göster|"
        r"konum\s*haritası|coğrafi\s*nokta)",
        ["cesium_globe"],
    ),
    # --- MANIM ANIM / 3BLUE1BROWN STİL MATEMATİK ANİMASYONU ---
    (
        r"(manim|3blue1brown|matematik\s*animasyon|"
        r"formül\s*dönüşüm\s*animasyon|adım\s*adım\s*animasyon|"
        r"limit\s*animasyon|türev\s*animasyon|integral\s*animasyon|"
        r"görsel\s*olarak\s*çöz)",
        ["manim_anim", "formula"],
    ),

    # 25.43-FAZ-4 (Neo direktif 11 May): Kurum geneli toplu sorgular
    # NOT: Pattern'ler hem TR (üö[şs]ı[ğg][çc]ü) hem ASCII (uoogicu) versiyonu i[çc]erir
    # [çc]ünkü kullanıcılar Türk[çc]e klavye/ASCII karı[şs]ık yazabilir.

    # --- TOPLU ÖĞRENCİ SIRALAMA ---
    (
        r"(kurum\s*geneli\s*s[ıi]ra|t[üu]m\s*[öo][ğg]renc\w*\s*s[ıi]ra|"
        r"yks\s*tahmin\s*s[ıi]ra|[öo][ğg]renc\w*\s*s[ıi]ralama|"
        r"kurum\s*ba[şs]ar[ıi]\s*s[ıi]ra|en\s*ba[şs]ar[ıi]l[ıi]\s*[öo][ğg]renc|"
        r"[şs]ube\s*s[ıi]ralama|s[ıi]n[ıi]f\s*s[ıi]ralama|"
        r"hangi\s*[öo][ğg]renc.*nere(de|ye)\s*yerle[şs])",
        ["chart", "treemap"],
    ),
    # --- KURUM GENELİ RAPOR ---
    (
        r"(kurum\s*durum|kurum\s*rapor|genel\s*durum|"
        r"genel\s*performans|t[üu]m\s*kurum)",
        ["chart", "treemap", "radar"],
    ),
    # --- PUAN-ÜNİ EŞLEŞTİRME ---
    (
        r"(puan\s*ile.*[üu]niversit|hangi\s*[üu]ni.*girer|"
        r"taban\s*puan.*hangi\s*b[öo]l[üu]m|s[ıi]ralama\s*ile\s*b[öo]l[üu]m|"
        r"y[öo]k\s*atlas|olas[ıi]\s*yerle[şs]me|tahmini\s*yerle[şs]me|"
        r"[üu]ni.*tercih|tercih\s*[üu]ni)",
        ["sankey", "treemap"],
    ),
    # --- SINIF DAĞILIMI ---
    (
        r"(s[ıi]n[ıi]f\s*da[ğg][ıi]l[ıi]m|[şs]ube\s*da[ğg][ıi]l[ıi]m|devre\s*da[ğg][ıi]l[ıi]m|"
        r"hangi\s*s[ıi]n[ıi]f.*ka[çc]|ka[çc]\s*ki[şs]i.*s[ıi]n[ıi]f|"
        r"[öo][ğg]renci\s*say[ıi].*s[ıi]n[ıi]f)",
        ["treemap", "chart"],
    ),
    # --- ÖĞRETMEN YOĞUNLUK ---
    (
        r"([öo][ğg]retmen\s*yo[ğg]unluk|hoca\s*yo[ğg]unluk|kim\s*ka[çc]\s*et[üu]t|"
        r"[öo][ğg]retmen\s*k[ıi]yas|hoca\s*k[ıi]yas|en\s*[çc]ok\s*et[üu]t\s*veren|"
        r"et[üu]t\s*veren\s*[öo][ğg]retmen)",
        ["chart", "sankey"],
    ),
    # --- TOPLU KONU ZAYIFLIK ---
    (
        r"(en\s*[çc]ok\s*hata|toplu\s*zay[ıi]f|kurum\s*zay[ıi]f\s*konu|"
        r"hangi\s*konu.*zay[ıi]f|[öo][ğg]rencilerin\s*zay[ıi]f|"
        r"t[üu]m\s*[öo][ğg]rencilerin\s*konu|zay[ıi]f\s*konu\s*liste)",
        ["treemap", "heatmap"],
    ),
    # --- REHBERLIK AKTİVİTE ---
    (
        r"(rehberlik\s*aktivite|g[öo]r[üu][şs]me\s*say[ıi]|kim\s*ka[çc]\s*g[öo]r[üu][şs]me|"
        r"rehber\s*yo[ğg]unluk|son\s*g[öo]r[üu][şs]meler)",
        ["chart", "timeline"],
    ),
    # --- DEVAMSIZLIK KRİTİK ---
    (
        r"(devams[ıi]zl[ıi]k.*kritik|100\+?\s*saat\s*devams[ıi]z|"
        r"200\+?\s*saat\s*devams[ıi]z|devams[ıi]z\s*[öo][ğg]renci\s*liste|"
        r"riskli\s*devams[ıi]z|kritik\s*devams[ıi]z)",
        ["chart", "treemap"],
    ),
    # --- ÖĞRENCİ 360 (TEK ÖĞRENCİ TAM PROFİL) ---
    (
        r"(tam\s*profil|360\s*derece|t[üu]m\s*durumu|"
        r"detayl[ıi]\s*durum|kapsaml[ıi]\s*durum|her\s*y[öo]n(üy|uy)?le)",
        ["radar", "kgraph"],
    ),
]


def detect_renderer_need(message: str) -> list[str]:
    """Mesajdan ihtiya[çc] duyulan renderer'ları tespit et.

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
    # Maksimum 3 — fazla se[çc]im olunca model karar veremiyor
    return found[:3]


def build_hint(message: str, channel: str = "web") -> Optional[str]:
    """Mesajdan renderer ihtiyacı varsa SERT system prompt direktif döndür.

    Args:
        message: Son user mesajı
        channel: 'web' | 'whatsapp' | ... (sadece web'de inject)

    Returns:
        Inject edilecek string ya da None (gerek yok)
    """
    renderers = detect_renderer_need(message)
    if not renderers:
        return None

    # ── WEB: tüm render tipleri canlı (Chart.js/Three.js/p5.js/KaTeX) ──
    if channel == "web":
        r_block = " + ".join(f"```{r}" for r in renderers)
        return (
            f"\n\n🎨 [RENDERER — ZORUNLU İNJECT]: {r_block}\n"
            f"Kullanıcı mesajı bu blok(lar)ı tetikledi. Web kanalında düz markdown\n"
            f"YETERSIZ — yanıtın i[çc]inde MUTLAKA yukarıdaki kod fence'lerini\n"
            f"(ge[çc]erli JSON/string ile) ÜRET. Aksi halde cevap eksik kalır.\n"
            f"Bot grafik/kar[şs]ıla[şs]tırma istenince tablo sunup chart üretmeme = bug."
        )

    # ── WHATSAPP (25.56): SADECE ```chart QuickChart image'a dönüşüyor.
    # Diğer render tipleri (3d/sim/steps/gauge...) WP'de ham kod görünür → TEŞVİK ETME.
    # Veri/karşılaştırma/trend uygunsa ```chart öner → sistem otomatik GÖRSELE çevirir.
    if "chart" in renderers:
        return (
            "\n\n🎨 [GÖRSEL — WhatsApp]: Bu mesaj veri/karşılaştırma/trend içeriyor.\n"
            "Uygunsa cevabına BİR ```chart bloğu ekle (geçerli JSON: type + data{labels,datasets}).\n"
            "Sistem onu otomatik GRAFİK GÖRSELİNE çevirip gönderir. SADECE ```chart kullan —\n"
            "diğer render tipleri WhatsApp'ta görünmez. Kısa yorum + grafik birlikte güçlü olur."
        )
    return None


# ─── TEST ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    cases = [
        "son 7 gün kullanıcı sayısı grafi[ğg]i",
        "matematik ve fizik netlerini kar[şs]ıla[şs]tır",
        "ders bazlı yetkinlik karne göster",
        "TYT puanım % ka[çc] tamamlandı",
        "haftalık [çc]alı[şs]ma planı",
        "limit nasıl [çc]özülür adım adım",
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
