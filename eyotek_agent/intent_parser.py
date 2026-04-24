"""
FermatAI Intent Parser
======================
WhatsApp sesli / yazılı komut → Yapılandırılmış Ajan Niyeti dönüştürücü.

Akış:
  WhatsApp mesajı (metin veya ses)
    → transcribe_audio()   (ses ise Whisper API)
    → parse_intent()       (Anthropic Claude ile niyet analizi)
    → IntentResult         (action_type, entities, priority, raw_text)
    → FermatCoreAgent.run()

Desteklenen Niyet Tipleri:
  STUDENT_REPORT    → "Ahmet'i raporla", "Ali'nin durumu nedir"
  WRITE_ETUT        → "Ahmet'e fizik etüt yaz", "11 SAY A'ya mat etüt"
  WRITE_NOTE        → "Ahmet için rehberlik notu ekle"
  SEND_SMS          → "11 SAY A velilerine SMS gönder"
  CLASS_SUMMARY     → "11 SAY A'nın durumu nasıl"
  ATTENDANCE_CHECK  → "Bugün kimler gelmedi"
  UNKNOWN           → Anlaşılamayan komutlar

Kullanım:
  from intent_parser import parse_intent, transcribe_audio
  intent = await parse_intent("Ahmet'e fizik etüt yaz")
  print(intent.action_type, intent.entities)
"""

import asyncio
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_KEY    = os.getenv("OPENAI_API_KEY", "")     # Whisper için (opsiyonel)
MODEL         = os.getenv("FERMAT_MODEL", "claude-haiku-4-5-20251001")  # Hızlı model


# ─── Veri Modeli ──────────────────────────────────────────────────────────────

@dataclass
class IntentResult:
    """Parse edilmiş kullanıcı niyeti."""
    action_type:  str            # STUDENT_REPORT, WRITE_ETUT, vb.
    raw_text:     str            # Orijinal metin
    entities:     dict[str, Any] = field(default_factory=dict)
    # entities örnekleri:
    #   student_name: "Ahmet"
    #   class_name:   "11 SAY A"
    #   subject:      "Fizik"
    #   etut_type:    "Etüt"
    #   note_text:    "Dikkat dağınıklığı var"
    #   sms_message:  "Sınav tarihi değişti"
    priority:     str = "normal"   # low | normal | high | urgent
    confidence:   float = 0.0
    followup_question: str = ""    # Eksik bilgi için soru
    ready_to_execute:  bool = True # Tüm bilgiler var mı?


# ─── Kural Tabanlı Hızlı Ön Tarama ──────────────────────────────────────────

_PATTERNS = {
    "WRITE_ETUT": [
        r"etüt\s+yaz",
        r"etüt\s+ekle",
        r"etüde?\s+al",
        r"(fizik|matematik|kimya|biyoloji|türkçe|edebiyat|tarih|coğrafya|ingilizce)\s+etüt",
    ],
    "WRITE_NOTE": [
        r"rehberlik\s+notu",
        r"not\s+(ekle|yaz|gir)",
        r"gözlem\s+(yaz|ekle)",
    ],
    "SEND_SMS": [
        r"sms\s+(gönder|at|yaz)",
        r"mesaj\s+(gönder|at)",
        r"veliler[ei]?ne?\s+(yaz|gönder|bildir)",
    ],
    "STUDENT_REPORT": [
        r"rapor\s+(çek|al|ver|hazırla)",
        r"(durumu|profili|analizi)\s+(nedir|nasıl|ver|göster)",
        r"(ne\s+durumda|nasıl\s+gidiyor)",
        r"(devamsızlık|sınav|not)\s+(bak|kontrol|göster)",
    ],
    "CLASS_SUMMARY": [
        r"sınıf\s+(özeti|durumu|raporu)",
        r"(kaçı|kimler)\s+gelm(edi|iyor)",
        r"sınıfın\s+(durumu|ortalaması)",
    ],
    "ATTENDANCE_CHECK": [
        r"bugün\s+(kimler\s+)?gelm(edi|iyor)",
        r"devamsızlık\s+(listesi|raporu|durumu)",
        r"yoklama",
    ],
}

_SUBJECT_MAP = {
    "mat": "Matematik", "matematik": "Matematik",
    "fiz": "Fizik", "fizik": "Fizik",
    "kim": "Kimya", "kimya": "Kimya",
    "bio": "Biyoloji", "biyoloji": "Biyoloji",
    "türkçe": "Türkçe", "edebiyat": "Türk Dili ve Edebiyatı",
    "tarih": "Tarih", "coğrafya": "Coğrafya",
    "ing": "İngilizce", "ingilizce": "İngilizce",
    "alm": "Almanca", "almanca": "Almanca",
}

_CLASS_PATTERN = re.compile(
    r"\b(\d{1,2}[\.\s]?(?:SAY|TM|EA|SÖZ|SOZ|YDİL|YDİL|LGS|snf|sınıf)[\s]?[A-Z]?)\b",
    re.IGNORECASE,
)


def _quick_classify(text: str) -> str | None:
    """Kural tabanlı hızlı sınıflandırma. None = belirsiz."""
    text_lower = text.lower()
    for intent, patterns in _PATTERNS.items():
        for pat in patterns:
            if re.search(pat, text_lower):
                return intent
    return None


def _extract_entities_regex(text: str) -> dict[str, Any]:
    """Regex ile hızlı entity çıkarımı."""
    entities: dict[str, Any] = {}

    # Sınıf adı
    m = _CLASS_PATTERN.search(text)
    if m:
        entities["class_name"] = m.group(1).strip().upper()

    # Ders adı
    for kw, subject in _SUBJECT_MAP.items():
        if re.search(rf"\b{kw}\b", text, re.IGNORECASE):
            entities["subject"] = subject
            break

    # Öğrenci adı — büyük harfle başlayan kelimeler (heuristik)
    name_matches = re.findall(
        r"\b([A-ZÇĞİÖŞÜ][a-zçğışöüa-z]+(?:\s+[A-ZÇĞİÖŞÜ][a-zçğışöüa-z]+)?)\b",
        text,
    )
    # Bilinen anahtar kelimeleri filtrele
    stop_words = {"Etüt", "Fizik", "Matematik", "Kimya", "Biyoloji", "Sınıf",
                  "Rehberlik", "Notu", "Rapor", "Bugün", "Yarın", "Gönder", "Yaz",
                  "Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"}
    names = [n for n in name_matches if n not in stop_words]
    if names:
        entities["student_name"] = names[0]

    # Tarih — DD.MM.YYYY ya da DD/MM/YYYY formatı
    date_m = re.search(r"\b(\d{1,2}[./]\d{1,2}[./]\d{4})\b", text)
    if date_m:
        raw_date = date_m.group(1).replace("/", ".")
        # DD.MM.YYYY formatına normalize et
        parts = raw_date.split(".")
        if len(parts) == 3:
            entities["target_date"] = f"{int(parts[0]):02d}.{int(parts[1]):02d}.{parts[2]}"

    # Bugün / yarın hızlı eşleme
    from datetime import date as _date, timedelta
    text_lower = text.lower()
    if not entities.get("target_date"):
        if "bugün" in text_lower or "bu gün" in text_lower:
            entities["target_date"] = _date.today().strftime("%d.%m.%Y")
        elif "yarın" in text_lower or "yarin" in text_lower:
            entities["target_date"] = (_date.today() + timedelta(days=1)).strftime("%d.%m.%Y")

    # Saat → ders_no dönüşümü
    _TIME_TO_DERS = {
        "09:00": 1, "09:45": 2, "10:30": 3, "11:15": 4,
        "12:00": 5, "12:45": 6, "14:00": 7, "14:45": 8,
        "15:30": 9, "16:15": 10, "17:00": 11, "17:45": 12,
        "18:30": 13, "19:15": 14, "20:00": 15,
    }
    time_m = re.search(r"\b(\d{1,2}):(\d{2})(?!\d)", text)
    if time_m and not entities.get("ders_no"):
        hh, mm = int(time_m.group(1)), int(time_m.group(2))
        time_str = f"{hh:02d}:{mm:02d}"
        if time_str in _TIME_TO_DERS:
            entities["ders_no"] = _TIME_TO_DERS[time_str]
        else:
            # En yakın derse yuvarla
            for t, n in _TIME_TO_DERS.items():
                th, tm = int(t.split(":")[0]), int(t.split(":")[1])
                if hh == th and abs(mm - tm) <= 10:
                    entities["ders_no"] = n
                    break

    return entities


# ─── LLM ile Derin Niyet Analizi ─────────────────────────────────────────────

_INTENT_SYSTEM = """Sen FermatAI'nın niyet analiz motorusun. Türkçe eğitim kurumu komutlarını analiz edersin.
Bugünün tarihi: {today} (DD.MM.YYYY format).

Görüşmeye gelen mesajı analiz et ve JSON formatında yanıt ver:
{{
  "action_type": "WRITE_ETUT|WRITE_NOTE|SEND_SMS|STUDENT_REPORT|CLASS_SUMMARY|ATTENDANCE_CHECK|UNKNOWN",
  "entities": {{
    "student_name": "öğrenci adı (varsa)",
    "student_id":   "okul no (varsa)",
    "class_name":   "sınıf adı (varsa)",
    "subject":      "ders adı (varsa)",
    "etut_type":    "Etüt|Ek Ders|Özel Ders|Sınıf Etüdü (varsa)",
    "note_text":    "not içeriği (varsa)",
    "sms_message":  "SMS metni (varsa)",
    "teacher":      "öğretmen adı (varsa)",
    "target_date":  "tarih DD.MM.YYYY formatında (bugün/yarın/pazartesi gibi ifadeleri dönüştür, varsa)",
    "ders_no":      "1-15 arası ders saati sütunu (saat ifadesinden belirle: 09:00=1, 09:45=2, 10:30=3, 11:15=4, 12:00=5, 12:45=6, 14:00=7, 14:45=8, 15:30=9, 16:15=10, 17:00=11, 17:45=12, 18:30=13, 19:15=14, 20:00=15)"
  }},
  "priority": "low|normal|high|urgent",
  "confidence": 0.0-1.0,
  "followup_question": "eksik bilgi için soru (Türkçe, boş bırakılabilir)",
  "ready_to_execute": true|false
}}

Sadece JSON döndür, açıklama ekleme."""


async def parse_intent(text: str, use_llm: bool = True) -> IntentResult:
    """
    Metin komutundan niyet çıkar.
    use_llm=False → sadece kural tabanlı (hızlı, offline)
    """
    text = text.strip()

    # Kural tabanlı hızlı tarama
    quick = _quick_classify(text)
    entities = _extract_entities_regex(text)

    if not use_llm or not ANTHROPIC_KEY:
        return IntentResult(
            action_type = quick or "UNKNOWN",
            raw_text    = text,
            entities    = entities,
            confidence  = 0.7 if quick else 0.1,
            ready_to_execute = bool(quick and entities),
        )

    # LLM ile derin analiz
    try:
        from datetime import date as _date
        _today_str = _date.today().strftime("%d.%m.%Y")
        _system = _INTENT_SYSTEM.format(today=_today_str)

        # Hibrit LLM — once Ollama dene, basarisiz olursa Claude fallback
        raw = None
        try:
            from llm_router import LLMRouter
            _router = LLMRouter()
            if _router.is_local_available:
                _local = _router.chat_local(
                    messages=[{"role": "user", "content": text}],
                    system=_system + '\nKRITIK: Yanit SADECE JSON olmali. Ornek: {"action_type":"STUDENT_REPORT","entities":{"student_name":"Ali"},"priority":"normal","confidence":0.8,"followup_question":"","ready_to_execute":true}',
                )
                raw = _local.strip()
                # JSON'u text icinden cikar (bazen metin ile karisiyor)
                import json as _json
                json_match = re.search(r'\{[^{}]*"action_type"[^{}]*\}', raw, re.DOTALL)
                if json_match:
                    raw = json_match.group(0)
                logger.info("  [YEREL] Intent Ollama ile analiz edildi")
        except Exception:
            pass

        if not raw and ANTHROPIC_KEY:
            client = Anthropic(api_key=ANTHROPIC_KEY)
            resp = client.messages.create(
                model     = MODEL,
                max_tokens= 512,
                system    = _system,
                messages  = [{"role": "user", "content": text}],
            )
            raw = resp.content[0].text.strip()
            logger.info("  [BULUT] Intent Claude ile analiz edildi")

        if not raw:
            raise ValueError("LLM intent yaniti alinamadi")
        # JSON temizle (bazen ```json ... ``` içinde gelir)
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
        data = __import__("json").loads(raw)

        return IntentResult(
            action_type       = data.get("action_type", "UNKNOWN"),
            raw_text          = text,
            entities          = data.get("entities", {}),
            priority          = data.get("priority", "normal"),
            confidence        = float(data.get("confidence", 0.5)),
            followup_question = data.get("followup_question", ""),
            ready_to_execute  = bool(data.get("ready_to_execute", False)),
        )
    except Exception as e:
        logger.warning(f"LLM niyet analizi hatası: {e} — kural tabanlı fallback")
        return IntentResult(
            action_type = quick or "UNKNOWN",
            raw_text    = text,
            entities    = entities,
            confidence  = 0.5,
        )


# ─── Ses Transkripsiyon ───────────────────────────────────────────────────────

async def transcribe_audio(audio_path: str | Path) -> str:
    """
    Ses dosyasını metne dönüştür.
    Önce OpenAI Whisper API dener, yoksa Anthropic multimodal kullanır.
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(f"Ses dosyası bulunamadı: {audio_path}")

    # OpenAI Whisper (tercih edilen)
    if OPENAI_KEY:
        try:
            import openai
            client = openai.AsyncOpenAI(api_key=OPENAI_KEY)
            with open(audio_path, "rb") as f:
                result = await client.audio.transcriptions.create(
                    model    = "whisper-1",
                    file     = f,
                    language = "tr",
                )
            text = result.text.strip()
            logger.info(f"🎤 Whisper: {text[:80]}")
            return text
        except Exception as e:
            logger.warning(f"Whisper hatası: {e}")

    # Claude ses girişini yerel olarak desteklemiyor — Whisper zorunlu.
    # OPENAI_API_KEY tanımlı değilse kullanıcıya anlamlı hata ver.
    raise RuntimeError(
        "Ses transkripsiyon için OPENAI_API_KEY gerekli. "
        ".env dosyasına OPENAI_API_KEY değerini ekleyin ya da "
        "metin olarak yazın."
    )


# ─── Intent → Agent Komutuna Dönüştür ────────────────────────────────────────

def intent_to_agent_command(intent: IntentResult) -> str:
    """
    IntentResult'ı FermatCoreAgent'ın anlayacağı doğal dil komutuna dönüştür.
    Bu sayede agent kendi muhakemesini yapabilir.
    """
    e = intent.entities
    at = intent.action_type

    if at == "STUDENT_REPORT":
        name = e.get("student_name") or e.get("student_id", "")
        return f"{name} adlı öğrencinin akademik profilini analiz et ve riskleri raporla."

    elif at == "WRITE_ETUT":
        subject = e.get("subject", "")
        student = e.get("student_name") or e.get("student_id", "")
        cls     = e.get("class_name", "")
        target  = f"{cls} sınıfına" if cls else f"{student} öğrencisine"
        return f"{target} {subject} etüt kaydı ekle. Uygun öğretmeni bul ve kaydet."

    elif at == "WRITE_NOTE":
        student = e.get("student_name") or e.get("student_id", "")
        note    = e.get("note_text", intent.raw_text)
        return f"{student} için rehberlik notu ekle: '{note}'"

    elif at == "SEND_SMS":
        target  = e.get("class_name") or e.get("student_name", "")
        message = e.get("sms_message", intent.raw_text)
        return f"{target} için SMS gönder: '{message}'"

    elif at == "CLASS_SUMMARY":
        cls = e.get("class_name", "")
        return f"{cls} sınıfının genel durumunu özetle: devamsızlık, sınav ortalaması, riskli öğrenciler."

    elif at == "ATTENDANCE_CHECK":
        return "Bugün devamsız olan öğrencilerin listesini getir ve ilgili velilere bildirim yap."

    else:
        return intent.raw_text


# ─── Test ─────────────────────────────────────────────────────────────────────

async def _test():
    test_inputs = [
        "Ahmet'e rapor çek, zayıfsa Fizik-1'e etüt yaz",
        "11 SAY A'ya matematik etüt ekle",
        "Bugün kimler gelmedi",
        "Şükrü için devamsızlık çok dedi anne söyledi rehberlik notu ekle",
        "12 SAY A velilerine sınav tarihi değişti diye SMS gönder",
    ]
    for t in test_inputs:
        intent = await parse_intent(t, use_llm=bool(ANTHROPIC_KEY))
        cmd    = intent_to_agent_command(intent)
        print(f"\n📝 Girdi : {t}")
        print(f"🎯 Niyet : {intent.action_type} (güven: {intent.confidence:.0%})")
        print(f"🔑 Entity: {intent.entities}")
        print(f"🤖 Komut : {cmd}")
        if intent.followup_question:
            print(f"❓ Soru  : {intent.followup_question}")


if __name__ == "__main__":
    asyncio.run(_test())
