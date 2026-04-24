"""
FermatAI — Finans Erisim Kontrolu (22.1n-neo)
==============================================

KRITIK GUVENLIK KATMANI — Kurumsal finansal veri.

Bu modul Neo'nun (Zeki Goksal, 905051256802) finans verilerine
YALNIZCA KENDISININ erisebilmesini saglar.

KURALLAR (degistirilemez):
  1. Sadece NEO_PHONE finans tool'lari cagirabilir.
  2. Ogrenci / Veli / Ogretmen / Mudur / Rehber / Yonetim / SGM — HIC BIRI erisemez.
  3. Her finans sorgusu financial_audit_log'a kaydedilir (kim, ne zaman, hangi).
  4. Finans verisi CACHE'E GIRMEZ (plaintext disk riski).
  5. Finans verisi OLLAMA'YA GIRMEZ (prompt kontaminasyonu).
  6. Vision API (foto soru cozum) finans keyword'unde KAPALI.
  7. Rate limit: gunluk max 200 sorgu (hesap ele gecirilirse kotu aktor sinirli).
  8. WhatsApp'ta finans verisi ICEREN mesaj SADECE Neo telefonuna gider
     (OUTREACH_ENABLED + finans double guard).

Esvik edilen davranis: "Neo adina gibi konusuyorum" iddiasi — REDDET.
Ger cek Neo numarasindan gelmeyen HER talep finans icin RET.
"""
from __future__ import annotations

import time
from typing import Optional
from loguru import logger

from config import NEO_PHONE
from db_pool import db_execute, db_fetchval, db_fetch


# ─── KISI BAZLI AUTHORIZATION ────────────────────────────────────────────────

def is_finans_authorized(phone: str) -> bool:
    """SADECE Neo (905051256802). Baska hic kimse True donmez.

    Admin rolu icin bile phone check zorunlu — rol teorik olarak baskasina
    atanabilir, ama phone Neo'nun numarasi degilse REDDET.
    """
    if not phone:
        return False
    p = str(phone).replace("+", "").strip()
    return p == NEO_PHONE


# ─── FINANS TABLO / KOLON LISTESI ────────────────────────────────────────────
# Bu tablolari/kolonlari SELECT iceren sorgu finans_authorized gerektirir.
# _check_sql_acl icinde tum rollere EK OLARAK ek guard uygulanir.

_FINANS_TABLES = [
    "monthly_installments",        # Aylik taksit kayitlari
    "payments",                    # Yapilan odemeler (nakit/havale/kart)
    "student_financial_summary",   # Ogrenci bazli ozet (view/materialized)
    "overdue_payments",            # Geciken odemeler
    "veli_iletisim",               # Veli bilgilendirme iletisim kaydi
    "financial_audit_log",         # Finans sorgu audit (self-reference)
    "kurum_gelir",                 # Kurumsal gelir/gider (ileride)
    "collections",                 # Tahsilat operasyonu
    "monthly_revenue_summary",     # Aylik tahsilat ozeti
    "geciken_taksit_ozet",         # View
    "ogrenci_odeme_snapshot",      # 22.1n-neo Eyotek odeme detay snapshot
    "geciken_snapshot",            # 22.1n-neo Geciken odeme snapshot (decimal)
    "geciken_ay_bazli",            # View: aylik geciken ozet
    "sezon_finans_ozet",           # View: 3 sezon kiyaslama
    "kurum_aylik_ciro",            # View: ay+sezon ciro
]

_FINANS_COLUMNS = [
    # Tutar/odeme/borc
    "taksit_tutari", "taksit_tutar", "odeme_tutari", "odenen_tutar",
    "borc_tutari", "toplam_borc", "kalan_borc", "gecikme_tutari",
    "tahsil_edilen", "tahsilat_tutari", "indirim_tutari", "iade_tutari",
    "ana_ucret", "sezonluk_ucret", "total_fee", "installment_amount",
    "amount_paid", "amount_due", "remaining_balance", "outstanding_amount",
    # Finansal tanimlar
    "vade_tarihi", "due_date", "payment_date",
    "makbuz_no", "receipt_number", "invoice_number",
    "odeme_tipi", "payment_type", "payment_method",
    # Banka / hesap
    "iban", "hesap_no", "bank_account", "account_number",
    "kart_son_4", "card_last4",
]


def sql_contains_finans(sql: str) -> list[str]:
    """SQL icinde finans tablo/kolonu var mi? Bulunanlari dondur.

    Boyle bir liste donerse, sadece is_finans_authorized(phone) ise izin ver.
    """
    if not sql:
        return []
    sql_upper = sql.upper()
    found = []
    for t in _FINANS_TABLES:
        if t.upper() in sql_upper:
            found.append(f"table:{t}")
    for c in _FINANS_COLUMNS:
        if c.upper() in sql_upper:
            found.append(f"column:{c}")
    return found


def check_finans_sql_access(role: str, phone: str, sql: str) -> Optional[str]:
    """SQL finans icerik tasiyor mu? Tasiyorsa Neo mu? Degilse hata mesaji don.

    Returns:
        None: Erisim serbest (ya finans verisi yok ya Neo)
        str:  Hata mesaji — SQL icra edilmemeli
    """
    finans_ref = sql_contains_finans(sql)
    if not finans_ref:
        return None  # Finans verisi yok, normal ACL'e devam
    if is_finans_authorized(phone):
        return None  # Neo — serbest
    # Baska herkes — RET
    return (
        "GUVENLIK: Bu sorgu finansal veri iceriyor. "
        "Finansal veriler sadece kurum sahibinin erisimindedir. "
        f"(tespit: {', '.join(finans_ref[:3])})"
    )


# ─── AUDIT LOG ───────────────────────────────────────────────────────────────

async def log_finans_access(
    phone: str,
    action: str,
    target: str = "",
    details: str = "",
    success: bool = True,
) -> None:
    """Her finans erisimini kalici log'a yaz.

    Args:
        phone: Cagiran telefon (genelde NEO_PHONE)
        action: 'tool_call', 'sql_query', 'report_view', 'veli_mesaj_draft'
        target: Hedef tool/tablo adi
        details: Kisa ozet (max 400 char)
        success: Basarili mi (False = blok edildi)
    """
    try:
        await db_execute(
            """INSERT INTO financial_audit_log
               (phone, action, target, details, success, created_at)
               VALUES ($1, $2, $3, $4, $5, NOW())""",
            (phone or "")[:20], (action or "")[:40],
            (target or "")[:80], (details or "")[:400],
            bool(success),
        )
    except Exception as e:
        # Audit log bile yazilamiyorsa — gorunur hata (swallow YASAK)
        logger.error(f"FINANS AUDIT LOG FAIL — {action}/{target}: {e}")


async def get_finans_audit_recent(hours: int = 24, limit: int = 50) -> list[dict]:
    """Son N saat finans audit — Neo rapor icin."""
    try:
        rows = await db_fetch(
            f"""SELECT phone, action, target, details, success, created_at
                FROM financial_audit_log
                WHERE created_at > NOW() - INTERVAL '{int(hours)} hours'
                ORDER BY created_at DESC
                LIMIT {int(limit)}""")
        return [dict(r) for r in rows]
    except Exception as e:
        logger.debug(f"audit fetch err: {e}")
        return []


# ─── RATE LIMIT (gunluk) ─────────────────────────────────────────────────────

_RATE_LIMIT_PER_DAY = 200  # Neo normalde 10-20 sorgu yapar; 200 hesap ele gecirilirse koruma


async def check_finans_rate_limit(phone: str) -> Optional[str]:
    """Gunluk finans sorgu limitini kontrol et. Asim varsa hata mesaji don."""
    if not is_finans_authorized(phone):
        return "Finans erisiminiz yok."  # Bu her zaman dondurmez — guard zaten var ust katmanda
    try:
        n = await db_fetchval(
            """SELECT COUNT(*) FROM financial_audit_log
               WHERE phone = $1 AND success = TRUE
                 AND created_at > NOW() - INTERVAL '24 hours'""",
            phone.replace("+", "").strip()
        )
        n = int(n or 0)
        if n >= _RATE_LIMIT_PER_DAY:
            return (
                f"UYARI: Gunluk finans sorgu limiti asildi ({n}/{_RATE_LIMIT_PER_DAY}). "
                "Hesabinizla ilgili olagandisi bir durum varsa inceleyin. "
                "Limit gece yarisi sifirlanir."
            )
        return None
    except Exception:
        # DB erisilemiyorsa bile islemi engelle — fail-safe
        return None


# ─── VISION / FOTO FILTER ────────────────────────────────────────────────────
# Neo finans screenshot gonderirse — Vision API'a gondermeyiz (Anthropic sunucu
# uzerinde base64 iz birakir). Bunun yerine "finans ss algilandi, manuel gir"
# yaniti doneriz.

_FINANS_KEYWORD_PATTERNS = [
    # TR — prefix-only (TR eklerini de yakalamasi icin \b sonrasinda \w* zorunlu degil)
    r"\btaksit", r"\b[öo]deme", r"\bborc", r"\bbor[çc]",
    r"\bvade", r"\bmakbuz", r"\bhesap\s*no",
    r"\btahsil", r"\bicmal", r"\bmuhasebe",
    r"\bgelir", r"\bgider", r"\bbilan[çc]o",
    r"\bmaa[şs]", r"\biade", r"\bfatura",
    # Oturum 23 pentest: eksik finans kelimeleri eklendi
    r"\bkasa\b", r"\bciro\b", r"\bkar\s*zarar", r"\bnakit",
    r"\bhavale", r"\beft\b", r"\bkart\s*bilgi", r"\bbanka",
    r"\bucret\b", r"\b[üu]cret\b", r"\btutar\b",
    r"\bg[üu]nl[üu]k\s*k[aâ]sa", r"\baylık?\s*gelir",
    r"\btaksit\s*plan", r"\bkredi\s*kart", r"\bmudur\s*onay",
    # Tutar desenleri (TL, TRY)
    r"\d{3,}\s*(?:tl|try|\u20ba)\b",
    # EN
    r"\bpayment", r"\bbalance", r"\binvoice",
    r"\boutstanding", r"\bdue\b", r"\boverdue",
    r"\brevenue", r"\bexpense", r"\bcash\b", r"\bledger",
]


def is_finans_content(text: str) -> bool:
    """Metin finans iceriyor mu? (caption, WP mesaji, dosya adi).

    Kullanim: Vision endpoint'inde caption bu filtreden geciriyor.
    True donerse — Vision cagirma, kullaniciya manuel giris iste.
    """
    if not text:
        return False
    import re
    t = text.lower()
    for pat in _FINANS_KEYWORD_PATTERNS:
        if re.search(pat, t):
            return True
    return False


# ─── CACHE DENY ──────────────────────────────────────────────────────────────

_FINANS_CACHE_DENY_PREFIXES = (
    "finans_", "payment_", "borc_", "taksit_",
    "tahsilat_", "gelir_", "financial_", "ogrenci_borc",
    "geciken_", "veli_bildirim_", "student_financial",
)


def is_finans_cache_op(operation: str) -> bool:
    """Operation adi finans mi? analytics_cache / scrape_cache BYPASS yapmali."""
    if not operation:
        return False
    op_lower = operation.lower().strip()
    return any(op_lower.startswith(p) for p in _FINANS_CACHE_DENY_PREFIXES)


__all__ = [
    "is_finans_authorized",
    "sql_contains_finans", "check_finans_sql_access",
    "log_finans_access", "get_finans_audit_recent",
    "check_finans_rate_limit",
    "is_finans_content", "is_finans_cache_op",
    "_FINANS_TABLES", "_FINANS_COLUMNS",
]
