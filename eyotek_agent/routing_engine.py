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
    # Oturum 25.10 — kalite analiz sonrasi eklenenler
    "kaba", "kabasın", "kabasin", "kabasınız", "kabaca",
    "yine boş", "yine bos", "boş yapıyor", "bos yapiyor",
    "anlatamıyorum", "anlatamiyorum", "kimse anlamıyor", "kimse anlamiyor",
    "hala anlamadın", "hala anlamadin",
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

    Döner: "fast" | "local" | "claude"

    NAMING NOTU (Oturum 25.22+ guncel): "local" döndüğünde gerçekte
    chat_local_async() çağrılır. Bu fonksiyon Cerebras-first calisir:
      Cerebras (3 model: 8b/120b/235b) → Groq (fallback) → Ollama (laptop)
    "ollama" eski isim, backwards compat icin kabul edilir; yeni kod "local".

    Öncelik sırası:
    1. Admin → selamlama/not_et fast, geri kalan Claude
    2. SGM → kısa+basit local, geri kalan Claude
    3. Tüm roller → fast_responses pattern match dene
    3b. Ogrenci → groq_lanes.classify_lane → 7 lane (Oturum 25.10 — adi groq_lanes
        ama gerceginde Cerebras'a gider, eski naming, refactor bekliyor)
    4. Kavramsal sorular → local (Cerebras gpt-oss-120b — halusilasyon dusuk)
    5. Cloud keywords → Claude
    6. Kısa+basit → local
    7. Belirsiz (auto/ogrenci) → local; admin/mudur → claude
    """
    msg_lower = message.lower().strip()

    # ── 0. FRUSTRATION INTERCEPT (22.1n-toplanti TOP#1) ─────────────────────
    # Bot tespit: "chatgpt'ye gidiyom" Ollama'da kaybolmuştu.
    # Artık her rolde frustration keyword → ZORLA Claude (empati + eskalasyon için).
    if detect_frustration(message):
        # Brief #6 — Kapı 6: V2 agent'a frustration sinyali yay (sync→async fire-forget)
        # Try/except içinde: bus yoksa veya hata olursa routing kararını ETKILEMESIN
        try:
            from live_signal_bus import get_bus as _get_bus
            import asyncio as _asyncio
            _bus = _get_bus()
            try:
                _loop = _asyncio.get_event_loop()
                if _loop.is_running():
                    _loop.create_task(_bus.emit(
                        "frustration",
                        {
                            "phone": phone or "",
                            "message_preview": (message or "")[:120],
                            "role": role or "",
                            "trigger": "routing_intercept",
                        },
                        actor_phone=phone or "",
                    ))
            except RuntimeError:
                # Event loop yoksa skip (test/sync context)
                pass
        except Exception:
            pass  # bus import veya emit hatası routing'i durdurmasın
        return "claude"

    # ── 0b. DUYGU/PSIKOLOJI INTERCEPT (Fix 21 Nisan 15:30) ──────────────────
    # Bugün Zehra "canim sikkin" yazdı, Ollama ters cevap verdi.
    # Duygu/psikolojik belirtisi varsa Ollama'ya GITMESIN, Claude'a zorunlu.
    # Fix 4 (egitim_psikoloji pattern'larıyla hizalı).
    if detect_duygu_psikoloji(message):
        return "claude"

    # ── 0c. SECURITY INTENT GUARD (25.40z3-ROUTING-FIX1, EN ÜST GÜVENLİK) ──
    # KRITIK: Bu kontrol HİÇBİR routing kararından SONRA gelmemeli — lane/fast
    # match security mesajını local'e atabiliyor (örn injection lane'de "kibarlik"e
    # benziyor). Hassas niyetler ZORLA Claude'a → maksimum güvenlik + KVKK koruma.
    _intent = ""
    try:
        from intent_classifier import classify_intent
        _intent = classify_intent(message) or ""
        _security_intents = {
            "injection_suspect", "role_change", "hassas_veri",
            "finans", "admin_action",
        }
        if _intent in _security_intents:
            return "claude"
    except Exception:
        pass

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
        return "local" if is_simple else "claude"

    # ── 3. Fast response pattern kontrolü → try_fast_response'a bırak ──
    # (fast_responses.py handler match yaparsa "fast" döner)
    # Burada sadece fast'a GİTMEMESİ gereken durumları filtrele

    # Context-dependent kısa mesajlar → Claude
    if len(msg_lower) < 20 and re.search(
        r'^(g[oö]nder+|at|atsana|yolla|g[oö]ster|[cç][oö]z|evet|olur|tamam|hadi|devam|peki)',
        msg_lower
    ):
        return "claude"

    # ── 3b. CEREBRAS-SAFE LANE KONTROLU (Oturum 25.29 — Cerebras tuning) ──
    # Production verisinden: Claude'a giden trafiğin %50'si yerel-safe.
    # 7 lane: kavramsal_kisa, sohbet, meta_direktif, kibarlik, egitim_icerik,
    #         red_generik, kisa_motivasyon
    # Lane match → "local" (chat_local_async Cerebras-first) → quality fail olursa Claude
    # Oturum 25.29 fix: ogrenci + ogretmen + rehber roller — admin/mudur Claude
    # Veri/rapor istekleri lane'e dusmez (kavramsal_kisa/sohbet/egitim_icerik gibi
    # net kategoriler cikar). Rehber "X hakkinda bilgi" gibi sorgular ZATEN
    # classify_complexity uzerinden cloud'a gidecek (data_query pattern yakalar).
    if role in ("ogrenci", "ogretmen", "rehber"):
        try:
            from groq_lanes import classify_lane
            _lane = classify_lane(message, role=role, phone=phone)
            if _lane:
                return "local"
        except Exception:
            pass

    # ── 4. KALDIRILDI (Oturum 25 D3): Kavramsal sorular burada dubleydi —
    # llm_router.classify_complexity asagida zaten "local" donduruyor (Oturum 25
    # PROJ-2-A fix'i + GROQ_CONCEPTUAL flag orada). Tek kaynak, DRY.

    # ── 5. Varsayılan: llm_router.classify_complexity (merkezi karar) ──
    # 19 Nisan refactor: "auto" yerine final karar don (bridge karmasikligi azalir)
    # Oturum 25 D3: Kavramsal dahil tum karar burada.
    # Oturum 25.10: "auto" davranisi degisti — fast miss durumunda Claude'a default
    # dusurmek yerine "local" (chat_local Groq-first) deneme sansi. Quality fail
    # olursa caller Claude'a eskale eder. Boylece Groq anlamli pay alir.
    try:
        from llm_router import classify_complexity
        complexity = classify_complexity(message)

        # 25.40z3-ROUTING-FIX1: claude_text_only → Cerebras 235b yönlendirme
        # Bot analizi (5 May): Claude trafiğinin %39'u tool kullanmadan direkt cevap
        # (claude_text_only: 173/(270+173) son 7 gün). Bu mesajların büyük kısmı
        # öğrenci kavramsal soruları ("Tyt fizik anlat", "Cati eki", "AA yayı uzunluğu")
        # → Cerebras 235b'ye taşınır. Admin text_only DEV TARTIŞMASI olduğu için
        # Claude'da kalır (mimari nüans + kalite zorunlu).
        # NOT: security guard yukarıda zaten yakaladı, burada güvenli intent'ler kalır.
        if complexity == "cloud":
            if role in ("ogrenci", "ogretmen", "rehber"):
                # Tool gerektirmeyen kavramsal/yardımcı intent'ler → local (Cerebras 235b)
                text_only_safe_intents = {
                    "kavram_aciklama", "ornek_iste", "cozum_iste",
                    "ozet_iste", "yontem_iste", "konu_anlatim_uzun",
                    "sohbet", "selamlama", "veda", "tesekkur",
                    "motivasyon_destek", "duygu_paylasim",
                    "kurum_bilgi", "yks_takvim", "mufredat_bilgi",
                    "yetenek_sorgu", "metin_zenginlestir",
                }
                if _intent in text_only_safe_intents:
                    return "local"
            return "claude"
        if complexity == "local":
            return "local"
        # auto: ogrenci icin Groq dene (kalite fail eskale eder)
        # admin/mudur "auto" ise Claude (kompleks olabilir)
        if role == "ogrenci":
            return "local"
        return "claude"
    except Exception:
        return "claude"


def is_admin_only_claude(role: str) -> bool:
    """Admin mesajları her zaman Claude mı?"""
    return role == "admin"
