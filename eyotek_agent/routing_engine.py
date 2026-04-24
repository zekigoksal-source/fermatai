"""
Merkezi Routing Engine — mesaj nereye gidecek, TEK NOKTADA karar verir.

Oturum 20 refactor: 3 farklı yerdeki routing kararı → tek fonksiyon.
Önceki durum:
  - fast_responses.py: admin early bypass, pattern match
  - llm_router.py: classify_complexity (keyword + regex)
  - fermat_core_agent.py: admin/SGM hardcoded cloud override

Yeni durum: Bu modül KARARCI, diğerleri UYGULAYICI.

Kullanım:
    from routing_engine import decide_route
    route = decide_route(message, role, phone, soz_no)
    # route: "fast" | "ollama" | "claude"
"""
import re


# ── Admin / SGM Override ──────────────────────────────────────────────────────
_NEO_PHONE = "905051256802"
_SGM_PHONE = "905547043775"


# ── 22.1n-toplanti: Frustration Keyword Intercept (Bot TOP#1 önerisi) ───────
# Bot 20 Nisan toplantida tespit: "sıkıcı chatgpt'ye gidiyom" Ollama path'ten
# geçti, Claude'a eskale etmedi — öğrenci kayboldu. Artık Ollama/fast path'te
# frustration keyword yakalanırsa ZORLA Claude'a yönlendirilir.
_FRUSTRATION_KEYWORDS = [
    # Rakip platform
    "chatgpt", "chat gpt", "gpt'ye", "gemini", "copilot", "claude'a",
    # Pes etme
    "sıkıcı", "sikici", "bıktım", "biktim", "yapamıyorum", "yapamiyorum",
    "pes ediyorum", "çıkıyorum", "cikiyorum", "siliyorum",
    # Olumsuz değer
    "yararsız", "yararsiz", "işe yaramıyor", "ise yaramiyor", "boş konuş",
    "bos konus", "saçma", "sacma", "rezalet", "berbat",
    # Anlamama/hayal kırıklığı
    "anlamıyorsun", "anlamiyorsun", "anlamadın", "anlamadin",
    "tekrar", "yine yanlış", "yine yanlis", "olmadı", "olmadi",
    # Agresif
    "kafamı bozma", "kafami bozma", "uyma", "bana ne",
]


# ── Fix 21 Nisan 15:30: Duygu/psikoloji pre-route — Ollama halusilasyon riski ─
# Bugün Zehra "canim sikkin" yazdı, Ollama "bugun ne kadar güzel bir gun!" cevabıyla
# tam ters duygu yansıtmıştı. Duygu/psikoloji belirtisi varsa Claude'a zorla.
_DUYGU_PSIKOLOJI_KEYWORDS = [
    # Üzgünlük / mutsuzluk
    "sikkin", "sıkkın", "uzgunum", "üzgünüm", "mutsuz", "moralim bozuk",
    "moralsiz", "uzuldum", "üzüldüm", "kotuyum", "kötüyüm",
    # Stres / kaygı
    "stres", "streslıyım", "stresliyim", "stresli", "kaygi", "kaygı",
    "kayg[iı]l[iı]y", "tedirgin", "panik", "endise", "endişe",
    "gergin", "gerildim", "gergindım", "gerginim",
    # Motivasyon düşük
    "motivasyonum yok", "motivasyonum dusuk", "motivasyonum düşük",
    "motivasyonum hic", "motivasyonum hiç",
    "motive degilim", "motive değilim", "calisamiyorum", "çalışamıyorum",
    "vazgec", "vazgeç", "pes ed", "birakmak", "bırakmak",
    "hic motivasyon", "hiç motivasyon", "moralim yok",
    # Oturum 23 meeting fix — Zehra vakası keyword boşluğu:
    # "ders calismak istemiyorum" match YOKTU → Ollama halusinasyon
    "calismak istemiyor", "çalışmak istemiyor",
    "ders calismak istemiyor", "ders çalışmak istemiyor",
    "okumak istemiyor", "ders yapmak istemiyor",
    "istemiyorum ders", "istemiyorum calis", "istemiyorum çalış",
    "istegim yok", "isteğim yok", "hevesim yok",
    "yapabilecegimi sanm", "yapabileceğimi sanm",
    # Öğrenme bloğu
    "kafam kari", "kafam karış", "kafam dur", "kafam tutmuy",
    "ogrendim ama unut", "öğrendim ama unut",
    # Perfeksiyonizm
    "mukemmel olmak", "mükemmel olmak", "kusursuz", "her sey dogru",
    "her şey doğru", "yoksa olmaz", "olmazsa olmaz",
    # Kıyas
    "kiyaslıyorum", "kıyaslıyorum", "kiyasl", "kıyasl", "benden iyi",
    "arkadaslarım daha", "arkadaşlarım daha", "herkes benden",
    # Uyku / yorgunluk
    "uyku kac", "uyku yok", "uyuyamiyorum", "uyuyamıyorum",
    "yoruldum", "yorgunum", "bitkinim", "tukendim", "tükendim",
    # Derin duygu / kriz
    "aglıyorum", "ağlıyorum", "deli oluyorum", "dayanamiyorum",
    "dayanamıyorum", "bunaldım", "bunaldim", "kotu hissediyorum",
    "kötü hissediyorum", "ask acisi", "aşk acısı",
]


def detect_duygu_psikoloji(message: str) -> bool:
    """Fix 21 Nisan: Duygusal/psikolojik belirti var mı? → Claude zorunlu.

    Kısa mesajlarda (500 char altı) anahtar kelime taraması.
    "cok stresliyim" gibi 15 char'lık mesajlar için önemli — Ollama yanlış yanıt verir.
    """
    if not message or len(message) > 500:
        return False
    msg_lower = message.lower()
    return any(kw in msg_lower for kw in _DUYGU_PSIKOLOJI_KEYWORDS)


def detect_frustration(message: str) -> bool:
    """22.1n-toplanti: Mesajda frustration keyword var mı?

    Gerçek pattern check — hem lowercase, hem word boundary.
    Sadece kısa mesajlarda (< 200 char) — uzun mesajlarda keyword rastgele
    geçebiliyor (ör: "chatgpt ile karşılaştırma" akademik soru).
    """
    if not message or len(message) > 200:
        return False
    msg_lower = message.lower()
    return any(kw in msg_lower for kw in _FRUSTRATION_KEYWORDS)


def decide_route(
    message: str,
    role: str = "",
    phone: str = "",
    soz_no: int | None = None,
) -> str:
    """
    Mesajın nereye gideceğini belirle.

    Döner: "fast" | "ollama" | "claude"

    Öncelik sırası:
    1. Admin → selamlama/not_et fast, geri kalan Claude
    2. SGM → kısa+basit Ollama, geri kalan Claude
    3. Tüm roller → fast_responses pattern match dene
    4. Kavramsal sorular → Claude (Ollama halüsinasyon riski)
    5. Cloud keywords → Claude
    6. Kısa+basit → Ollama
    7. Belirsiz → Claude (güvenli taraf)
    """
    msg_lower = message.lower().strip()

    # ── 0. FRUSTRATION INTERCEPT (22.1n-toplanti TOP#1) ─────────────────────
    # Bot tespit: "chatgpt'ye gidiyom" Ollama'da kaybolmuştu.
    # Artık her rolde frustration keyword → ZORLA Claude (empati + eskalasyon için).
    if detect_frustration(message):
        return "claude"

    # ── 0b. DUYGU/PSIKOLOJI INTERCEPT (Fix 21 Nisan 15:30) ──────────────────
    # Bugün Zehra "canim sikkin" yazdı, Ollama ters cevap verdi.
    # Duygu/psikolojik belirtisi varsa Ollama'ya GITMESIN, Claude'a zorunlu.
    # Fix 4 (egitim_psikoloji pattern'larıyla hizalı).
    if detect_duygu_psikoloji(message):
        return "claude"

    # ── 1. ADMIN → her zaman Claude (selamlama+not_et hariç) ──
    if role == "admin":
        is_greeting = bool(re.match(r'^(merhaba|selam|sa$|iyi\s*g[uü]n|hey|na[sb])', msg_lower))
        is_note = bool(re.search(r'(not\s*et|kaydet|hata.*not|diyalog.*not)', msg_lower))
        if is_greeting or is_note:
            return "fast"
        return "claude"

    # ── 2. SGM → kısa+basit Ollama, geri kalan Claude ──
    if phone == _SGM_PHONE:
        is_simple = (
            len(msg_lower) < 25
            and not any(kw in msg_lower for kw in [
                'analiz', 'rapor', 'mimari', 'sistem', 'teknik', 'ogrenci',
                'sinav', 'deneme', 'performans', 'plan', 'guncelle', 'gozlem',
            ])
        )
        return "ollama" if is_simple else "claude"

    # ── 3. Fast response pattern kontrolü → try_fast_response'a bırak ──
    # (fast_responses.py handler match yaparsa "fast" döner)
    # Burada sadece fast'a GİTMEMESİ gereken durumları filtrele

    # Context-dependent kısa mesajlar → Claude
    if len(msg_lower) < 20 and re.search(
        r'^(g[oö]nder+|at|atsana|yolla|g[oö]ster|[cç][oö]z|evet|olur|tamam|hadi|devam|peki)',
        msg_lower
    ):
        return "claude"

    # ── 4. Kavramsal sorular → Oturum 25: Groq 70B'ye (local).
    # Eskiden "claude" dondururduk cunku Ollama halusinasyon riski vardi.
    # Groq 70B ile bu risk dusuk; trailing \b kaldirildi (Turkce suffix: anlatir/ornegi/formulu).
    # GROQ_CONCEPTUAL=false ile eski davranisi aktive edebilirsin.
    import os as _os
    _groq_conceptual = _os.getenv("GROQ_CONCEPTUAL", "true").lower() == "true"
    is_conceptual = bool(re.search(
        r'\b(nedir|ne\s*demek|nasil\s*calisir|acikla|açıkla|anlat|ogret|tanim|orne[kg]|örne[kğ]|farki|ozet|formul|formül)',
        msg_lower,
    ))
    if is_conceptual:
        return "ollama" if _groq_conceptual else "claude"

    # ── 5. Varsayılan: fast_responses dene, yakalamasa llm_router.classify ──
    # 19 Nisan refactor: "auto" yerine final karar don (bridge karmasikligi azalir)
    try:
        from llm_router import classify_complexity
        complexity = classify_complexity(message)
        # local → ollama, cloud → claude, auto → fast (fast_responses bridge'de dener)
        if complexity == "cloud":
            return "claude"
        if complexity == "local":
            return "ollama"
        return "auto"  # fast_responses uygulayicisi karar versin
    except Exception:
        return "auto"


def is_admin_only_claude(role: str) -> bool:
    """Admin mesajları her zaman Claude mı?"""
    return role == "admin"
