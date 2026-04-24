"""
Hassas Veri Log Filtresi (Oturum 22.1d)
=======================================

Log dosyalarina:
  - Telefon numaralari (tam format) → son 4 hane haric maskele
  - API keyleri, tokenlar → kaldir
  - TC kimlik (11 hane sayi) → maskele
  - OTP kodlari → maskele

Kullanim (bridge lifespan):
    from utils.log_filter import install_log_filter
    install_log_filter()  # loguru'ya baglanir

Sonra tum logger.info/debug cagrilari otomatik sensitize olur.
"""
import re
from loguru import logger

# Hassas veri pattern'lari
_PHONE_PATTERN = re.compile(r'\b(90)?5\d{9}\b')  # Turkish phone 905xxxxxxxxx veya 5xxxxxxxxx
_TOKEN_PATTERN = re.compile(r'(sk-[a-zA-Z0-9_-]{20,}|ant_[a-zA-Z0-9_-]{20,}|Bearer\s+[a-zA-Z0-9._-]{20,})')
_TC_PATTERN = re.compile(r'\b\d{11}\b')  # 11 hane sayi (TC)
_OTP_PATTERN = re.compile(r'\botp_code=(\d{4,8})\b|\bOTP[:\s]+(\d{4,8})\b', re.IGNORECASE)
_API_KEY_PATTERN = re.compile(r'(api[_-]?key|authorization|bearer)[:=\s]+[\'"]?([a-zA-Z0-9._-]{10,})', re.IGNORECASE)


def mask_phone(phone: str) -> str:
    """Son 4 hane haric maskele: 905462605446 → ****605446"""
    if not phone or len(phone) < 4:
        return phone
    return "****" + phone[-4:]


def sanitize(message: str) -> str:
    """Bir log mesajindan hassas veriyi temizle/maskele."""
    if not isinstance(message, str):
        return message

    # Telefon — son 4 hane haric maskele
    def _phone_mask(m):
        num = m.group(0)
        return mask_phone(num)
    result = _PHONE_PATTERN.sub(_phone_mask, message)

    # API key / token → tamamen kaldir
    result = _TOKEN_PATTERN.sub('[REDACTED]', result)
    result = _API_KEY_PATTERN.sub(r'\1=[REDACTED]', result)

    # TC kimlik → ilk 3 + son 2 haric maskele
    def _tc_mask(m):
        tc = m.group(0)
        return tc[:3] + "****" + tc[-2:] if len(tc) == 11 else tc
    # DIKKAT: Telefon da 11 hane olabilir, telefon ustteki pattern'da yakalandi zaten
    # Sadece 90 ile baslamayan 11 haneli sayilari TC olarak isaretle
    result = re.sub(r'\b(?!90)\d{11}\b', lambda m: m.group(0)[:3] + "****" + m.group(0)[-2:], result)

    # OTP kod → maskele
    result = _OTP_PATTERN.sub('OTP=******', result)

    return result


def _loguru_filter(record):
    """Loguru record'una sanitize uygula."""
    # record["message"] string olacak (format sonrasi)
    record["message"] = sanitize(record["message"])
    return True


def install_log_filter():
    """Loguru'ya filter ekle — TUM log'lar maskelenir."""
    # Default handler'i guncelle
    try:
        # Tum handler'larin mesajlarini sanitize et
        logger.configure(patcher=lambda r: r.update(message=sanitize(r["message"])) if isinstance(r.get("message"), str) else None)
        logger.info("🔒 Log filter aktif — hassas veri maskeleniyor")
    except Exception as e:
        logger.warning(f"Log filter install hatasi: {e}")


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    tests = [
        "User login: 905462605446 from IP 1.2.3.4",
        "API key: sk-abc123xyz789TokenHere1234567890",
        "Bearer eyJhbGc.eyJzdWIx.Signature12345678",
        "OTP: 482193",
        "TC: 12345678901",
        "Authorization=sk-abc1234567890abcdefghij",
        "Normal message without sensitive data",
        "params: {'student_id': 385, 'phone': '905051256802', 'note': 'test'}",
    ]
    print("=" * 60)
    print("LOG FILTER TEST")
    print("=" * 60)
    for t in tests:
        print(f"ORJ: {t}")
        print(f"MSK: {sanitize(t)}")
        print()
