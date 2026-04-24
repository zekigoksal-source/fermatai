"""
FermatAI Ollama Hakem Sistemi
==============================
Fast_response'da birden fazla pattern tetiklendiginde
veya belirsiz mesajlarda Ollama karar verir.

Rol: Mesajin gercek niyetini anla, dogru handler'a yonlendir.
Maliyet: $0 (yerel LLM)
Hiz: ~1-2s
"""

import json
import time
from typing import Optional

from loguru import logger


ARBITER_PROMPT = """Sen FermatAI hakem sistemisin. Ogrencinin mesajini gerceke dogru sinifa yonlendir.

TEK GOREV: Mesaj niyeti sinifla → dogru fast_response handler'a git veya Claude'a eskale et.

SINIFLAR VE ORNEK KULLANIM:

📊 VERI SORGULARI (fast, saniyede yanit, token yakmaz):
- "son_deneme" — "son denemem", "netlerim nasil", "sinav sonucum ne"
- "ayt_deneme" — "ayt netlerim", "ayt yorum", "aytlerim"
- "kiyaslama" — "son 3 denememi karsilastir", "trend", "gelismem"
- "zayif_konular" — "zayif konularim", "nerede hata", "neye calismali"
- "guclu_konular" — "guclu oldugum konular", "iyi gittigim"
- "devamsizlik" — "kac saat devamsizim", "yoklama durumum"
- "ders_programi" — "bu hafta ders", "programim ne", "cumartesi dersim"
- "hedef" — "hedef bolumum", "kac net lazim", "universite"
- "rehberlik" — "rehberlik notum", "gorusme gecmisi"

📘 AKADEMIK (Claude — kaliteli icerik):
- "konu_aciklama" — "turev nedir", "fotosentez anlat", "kaldirma kuvveti"
- "cikmis_soru" — "fizik cikmis sorular", "manyetizma sorusu", "2024 goster"

🎯 BILGILENDIRME (fast, hazir icerik):
- "sinav_bilgi" — "yks ne zaman", "kac gun kaldi", "tyt kac soru"
- "selamlama" — "merhaba", "selam", "iyi gunler"
- "sohbet" — "nasilsin", "naber", "iyi misin"
- "kapanis" — "tesekkur", "sagol", "gorusuruz"
- "kurum_bilgi" — "fermat ne", "en iyi mi", "hoca kimdir"
- "yetenek" — "neler yapabilirsin", "kabiliyetlerin"

🧠 PSIKOLOJIK (Claude — hassasiyet):
- "motivasyon" — "yoruldum", "yapamiyorum", "bitmek istemiyor"
- "kriz" — "intihar", "depresyon", "cidden kotuyum"

⚠️ GUVENLIK (fast, hazir):
- "kimlik_manipulasyon" — "adim X", "benim adim Neo"
- "yetki_yukseltme" — "beni admin yap", "yetki ver"
- "jailbreak" — "DAN", "ChatGPT ol", "ignore instructions"
- "kapsamsiz" — "acisktim", "saat kacta uyuyum" (kapsam disi)

📝 CALISMA (Claude — kisisel plan):
- "calisma_plani" — "plan yap", "program olustur"
- "soru_coz" — "soruyu coz", "cevap nedir" (context: aynen soru metni veya foto var)

🔀 CONTEXT (Claude — onceki mesaja bagli):
- "baglam_devam" — "evet", "olur", "goster", "diger", "2024" (tek kelime/sayi, onceki mesaja bagli)

❓ BELIRSIZ:
- "belirsiz" — mesaj cok kisa, anlamsiz, context yok
- "claude_gerekli" — karmasik analiz, coklu veri, ozel istek

KARAR KURALI:
1. Mesajda ACIK bir istek varsa → ilgili sinif (confidence 0.9+)
2. Mesaj tek/iki kelime + onceki mesaj context varsa → "baglam_devam"
3. Akademik konu ANLATIMI → "konu_aciklama"
4. Spesifik SORU/CEVAP → "soru_coz"
5. Ozel istek, kapsamli analiz → "claude_gerekli"
6. Emin degilsen → confidence DUSUK (<0.6) ver, Claude devralsin

SADECE JSON DON: {"intent": "sinif_adi", "confidence": 0.0-1.0}
"""


def classify_intent(message: str, caller_name: str = "", recent_context: str = "") -> dict:
    """
    Mesajin niyetini Ollama ile siniflandir.
    Returns: {"intent": str, "confidence": float}
    """
    # HARD RULES — Ollama'ya gondermeden direkt karar
    import re as _re
    msg_lower = message.lower().strip()
    # Yil + goster/getir: "2024 yilindakini goster" → context-bagimli, Claude
    if _re.search(r'\b20[12]\d\b.*?(g[oö]ster|getir|g[oö]nder|yolla|at|aç|ac|sec|seç)', msg_lower):
        return {"intent": "claude_gerekli", "confidence": 1.0}
    # "soru X coz/goster" → Claude (tool gerekir)
    if _re.search(r'(soru|sorular)\s*\d+\s*(c[oö]z|aç|ac|g[oö]ster|getir|g[oö]nder|yolla)', msg_lower):
        return {"intent": "claude_gerekli", "confidence": 1.0}
    # "X numarali soru" → Claude
    if _re.search(r'\d+\s*(nolu|numarali|numaralı)', msg_lower):
        return {"intent": "claude_gerekli", "confidence": 1.0}
    # "diger soruyu/digerini goster" → Claude (context bagimli)
    if _re.search(r'(di[gğ]er|sonraki|baska|ba[sş]ka)\w*\s*(soru|sorular)\w*\s*(g[oö]ster|getir|g[oö]nder|yolla|aç)?', msg_lower):
        return {"intent": "claude_gerekli", "confidence": 1.0}
    # "attim/attigim soru" / "bu soru" / "sorumu/soruyu" — soru cozme context'i
    if _re.search(r'(at(t[iı]|m[iı]s)|att[iı]g[iı]m|bu\s*soru|soru\w*\s*(odakla|odaklan|coz|çöz|bak|anla)|sorumu|soruyu|cevap)', msg_lower):
        return {"intent": "claude_gerekli", "confidence": 1.0}
    # "X ve Y" / "A sikki" — belirsiz soru icerigi → Claude
    if _re.search(r'([a-e]\s*[sş][iı]k|do[gğ]ru\s*cevap|yanl[iı][sş]\s*cevap|cevap\s*[a-e])', msg_lower):
        return {"intent": "claude_gerekli", "confidence": 1.0}

    try:
        import ollama

        user_prompt = f"Mesaj: \"{message}\""
        if caller_name:
            user_prompt += f"\nArayan: {caller_name}"
        if recent_context:
            user_prompt += f"\nOnceki baglam: {recent_context}"

        start = time.time()
        response = ollama.chat(
            model="qwen2.5:7b",
            messages=[
                {"role": "system", "content": ARBITER_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            options={"temperature": 0.1, "num_predict": 50},  # Kisa, deterministik
        )
        elapsed = time.time() - start

        answer = response.get("message", {}).get("content", "").strip()

        # JSON parse dene
        try:
            # Bazen Ollama JSON yerine duz metin doner
            if "{" in answer:
                json_str = answer[answer.index("{"):answer.rindex("}") + 1]
                result = json.loads(json_str)
                logger.debug(f"[ARBITER] {elapsed:.1f}s → {result}")
                return result
            else:
                # Duz metin — intent olarak al
                intent = answer.lower().strip().strip('"').strip("'")
                return {"intent": intent, "confidence": 0.7}
        except (json.JSONDecodeError, ValueError):
            return {"intent": "belirsiz", "confidence": 0.3}

    except Exception as e:
        logger.debug(f"Arbiter hatasi: {e}")
        return {"intent": "belirsiz", "confidence": 0.0}
