"""
FermatAI — Merkezi Config (22.1n-refactor)
===========================================

Tekrarlanan konfig değerleri için tek kaynak. Eskiden 7 farklı dosyada
NEO_PHONE/ADMIN_PHONE hard-coded'tu — değişiklik sinir bozucuydu.

KULLANIM:
    from config import NEO_PHONE, SGM_PHONE, ADMIN_PHONE
    # NEO_PHONE ve ADMIN_PHONE aynı, backward compatibility için iki isim

KURAL (Neo 20 Nisan):
- Yeni sabit/kritik değer eklerken ÖNCE bu dosyayı kontrol et.
- Mevcut varsa import et, tekrar tanımlama.
"""
import os
from dotenv import load_dotenv

load_dotenv(override=True)

# ─── ÖZEL TELEFON NUMARALARI (rol kimlikleri) ────────────────────────────────
NEO_PHONE   = os.getenv("NEO_PHONE",   "905051256802")  # Zeki Göksal — admin/mimar
ADMIN_PHONE = NEO_PHONE  # Geriye uyumluluk alias'ı
SGM_PHONE   = os.getenv("SGM_PHONE",   "905547043775")  # Orsel Koc — Sistem Geliştirme Müdürü
DUYGU_PHONE = os.getenv("DUYGU_PHONE", "905051256801")  # Duygu Göksal — mudur
MAHSUM_PHONE= os.getenv("MAHSUM_PHONE","905462605446")  # Mahsum Yalcin — mudur


# ─── FEATURE FLAGS (yeni sezon için kapalı) ──────────────────────────────────
OUTREACH_ENABLED    = os.getenv("OUTREACH_ENABLED",    "false").lower() in ("1","true","yes")
TELAFI_ACTIVE       = os.getenv("TELAFI_ACTIVE",       "false").lower() in ("1","true","yes")
YAZ_KAMPI_ACTIVE    = os.getenv("YAZ_KAMPI_ACTIVE",    "false").lower() in ("1","true","yes")
VELI_MODULE_ACTIVE  = os.getenv("VELI_MODULE_ACTIVE",  "false").lower() in ("1","true","yes")
ALERTS_ACTIVE       = os.getenv("ALERTS_ACTIVE",       "false").lower() in ("1","true","yes")


# ─── TIMEOUT/LIMIT CONFIG ────────────────────────────────────────────────────
OLLAMA_TIMEOUT_SEC  = int(os.getenv("OLLAMA_TIMEOUT", "30"))
STALE_LOCK_SEC      = int(os.getenv("STALE_LOCK_SEC", "180"))
QUEUE_NOTIFY_GAP    = int(os.getenv("QUEUE_NOTIFY_GAP", "30"))


# ─── CACHE TTL (22.1n-refactor: 2 katman unified) ───────────────────────────
# hot: sık sorgulanan (analytics cache), warm: veri değişmeyen (scrape)
CACHE_TTL_HOT_SEC  = int(os.getenv("CACHE_TTL_HOT",  "600"))    # 10 dk
CACHE_TTL_WARM_SEC = int(os.getenv("CACHE_TTL_WARM", "86400"))  # 24 saat


def is_admin_phone(phone: str) -> bool:
    """Telefon numarası Neo'nun mu?"""
    return (phone or "").replace("+","").strip() == NEO_PHONE


def is_mudur_phone(phone: str) -> bool:
    """Müdür rolü (Duygu, Mahsum, Orsel)?"""
    p = (phone or "").replace("+","").strip()
    return p in (DUYGU_PHONE, MAHSUM_PHONE, SGM_PHONE)
