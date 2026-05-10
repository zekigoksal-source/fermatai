"""Test mod izolasyonu — test mesajlarini gercek verilerden ayir.

Kullanim:
    from test_mode import is_test_context, set_test_mode, strip_test_marker

    # 1. Bridge entry-point'inde tespit:
    is_test = is_test_message(text) or is_test_phone(phone)
    if is_test:
        set_test_mode(True, test_id=parsed_id)

    # 2. Side-effect yapan kodda guard:
    if is_test_context():
        return  # sentiment_tracker / student_insights / alert / memory SKIP

Test marker formatlari:
    [TEST:abc123] gercek mesaj burada   <- prefix marker (oncelikli)
    9059900001..9059900099                <- test_phone allowlist

ContextVar kullanir — asyncio task'lerinde guvenli, concurrent request'ler karismaz.
"""
from __future__ import annotations

import re
from contextvars import ContextVar
from typing import Optional

# ── Public state (read-only dişardan, set_test_mode kullan) ──────────────
_IS_TEST: ContextVar[bool] = ContextVar('_IS_TEST', default=False)
_TEST_ID: ContextVar[str] = ContextVar('_TEST_ID', default='')

# ── Konfigurasyon ──────────────────────────────────────────────────────────
TEST_PREFIX_RE = re.compile(r'^\s*\[TEST:([A-Za-z0-9_-]{1,32})\]\s*', re.IGNORECASE)
# Bridge'in normalize_phone() sonucu (+ yok). 99 test numarasi.
TEST_PHONE_PREFIX = "9059900"           # 9059900001..9059900099
TEST_PHONE_MIN = "9059900001"
TEST_PHONE_MAX = "9059900099"


def is_test_phone(phone: str) -> bool:
    """phone bir test numarasi mi? 9059900001..9059900099 arasi."""
    if not phone:
        return False
    p = str(phone).replace('+', '').strip()
    return p.startswith(TEST_PHONE_PREFIX) and TEST_PHONE_MIN <= p <= TEST_PHONE_MAX


def parse_test_marker(text: str) -> tuple[bool, str, str]:
    """text [TEST:id] prefix'i tasiyor mu?

    Returns:
        (is_test, test_id, cleaned_text)
        is_test=False ise test_id='' ve cleaned_text=text (orijinal).
    """
    if not text:
        return False, '', text or ''
    m = TEST_PREFIX_RE.match(text)
    if not m:
        return False, '', text
    return True, m.group(1), text[m.end():]


def strip_test_marker(text: str) -> str:
    """Mesajdaki [TEST:id] prefix'i temizle, sadece soru kalsin."""
    if not text:
        return text or ''
    return TEST_PREFIX_RE.sub('', text, count=1)


def is_test_message(text: str) -> bool:
    """text [TEST:...] prefix'i tasiyor mu?"""
    return bool(text) and bool(TEST_PREFIX_RE.match(text))


def detect_test_context(phone: str, text: str) -> tuple[bool, str]:
    """Bu istek test mi? (phone allowlist VEYA [TEST:id] prefix).

    Returns: (is_test, test_id) — test_id phone'dan geldiyse 'phone:<phone>'.
    """
    if is_test_phone(phone):
        return True, f"phone:{phone[-4:]}"
    has_marker, tid, _ = parse_test_marker(text)
    if has_marker:
        return True, tid
    return False, ''


def set_test_mode(enabled: bool, test_id: str = '') -> None:
    """ContextVar'lari set et — bu task'in scope'unda is_test_context() True doner."""
    _IS_TEST.set(bool(enabled))
    _TEST_ID.set(str(test_id or ''))


def is_test_context() -> bool:
    """Su anki async task test scope'unda mi? Side-effect kodlarinda guard."""
    try:
        return _IS_TEST.get()
    except LookupError:
        return False


def get_test_id() -> str:
    """Su anki test'in id'si (varsa). Loglamada kullan."""
    try:
        return _TEST_ID.get()
    except LookupError:
        return ''


# ── Side-effect guard helper'lar ──────────────────────────────────────────
# Bu fonksiyonlar yan-etki yapan modullerde kullanilir.

def skip_if_test(label: str = '') -> bool:
    """Test mode'daysa True doner — caller return etmeli.

    Kullanim:
        async def save_to_db(...):
            if skip_if_test('insights'):
                return
            # gercek kullanici icin yaz
    """
    if is_test_context():
        return True
    return False


# ── Test telefon havuzu seed araci ─────────────────────────────────────────
TEST_USERS = [
    # (phone, full_name, role, soz_no_for_student)
    ("9059900001", "Test Admin",     "admin",    None),
    ("9059900002", "Test Mudur",     "mudur",    None),
    ("9059900003", "Test Yonetim",   "yonetim",  None),
    ("9059900004", "Test Rehber",    "rehber",   None),
    ("9059900010", "Test Ogretmen Mat",  "ogretmen", None),
    ("9059900011", "Test Ogretmen Fiz",  "ogretmen", None),
    ("9059900012", "Test Ogretmen Tur",  "ogretmen", None),
    # Test ogrenciler — gercek bir profile bagli, kendi verisini gorsun
    # (soz_no'lar 137-314 arasinda, sezona kayitli ogrenciler)
    ("9059900020", "Test Ogrenci SAY1", "ogrenci", 233),  # Berf (11 SAY)
    ("9059900021", "Test Ogrenci SAY2", "ogrenci", 244),  # Cagan
    ("9059900022", "Test Ogrenci SAY3", "ogrenci", 230),  # Ecrin
    ("9059900023", "Test Ogrenci EA1",  "ogrenci", 256),  # Ceren Naz
    ("9059900024", "Test Ogrenci EA2",  "ogrenci", 252),  # Saniye
    ("9059900025", "Test Ogrenci SOZ",  "ogrenci", 218),  # Nehir
    ("9059900026", "Test Ogrenci LGS",  "ogrenci", 196),  # Devin
    ("9059900030", "Test Veli",        "veli",     None),
    ("9059900099", "Test Guest",       "guest",    None),
]


async def seed_test_users(db_execute_fn=None):
    """acl_users tablosuna test kullanicilari ekle/guncelle. is_active=TRUE,
    welcomed_at=NOW (onboarding atlama).

    db_execute_fn: db_pool.db_execute callable (test runner verir).
    """
    if db_execute_fn is None:
        from db_pool import db_execute as _ex
        db_execute_fn = _ex
    for phone, name, role, _soz in TEST_USERS:
        await db_execute_fn(
            """
            INSERT INTO acl_users (phone, full_name, role, is_active, welcomed_at, notes)
            VALUES ($1, $2, $3, TRUE, NOW(), 'test_account')
            ON CONFLICT (phone) DO UPDATE SET
                full_name = EXCLUDED.full_name,
                role = EXCLUDED.role,
                is_active = TRUE,
                welcomed_at = COALESCE(acl_users.welcomed_at, NOW()),
                notes = 'test_account'
            """,
            phone, name, role,
        )


if __name__ == "__main__":
    # Hizli sanity
    print("=== test_mode sanity ===")
    print(f"is_test_phone('9059900020'): {is_test_phone('9059900020')}")
    print(f"is_test_phone('905051256802'): {is_test_phone('905051256802')}")
    has, tid, txt = parse_test_marker('[TEST:run42] son denemem nasıl')
    print(f"parse_test_marker: has={has}, tid={tid!r}, cleaned={txt!r}")
    has, tid, txt = parse_test_marker('selam')
    print(f"parse_test_marker(selam): has={has}, tid={tid!r}, cleaned={txt!r}")
    print(f"detect_test_context: {detect_test_context('9059900020', 'merhaba')}")
    print(f"detect_test_context: {detect_test_context('905051256802', '[TEST:abc] selam')}")
