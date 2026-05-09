"""Test user registry — gercek kullanici / test ayrimi (Bulgu F).

Oturum 25.42 (9 May 2026, Neo direktifi):
"Test ve gerçek kullaniciyi sistem ayırt etmeli routing değerleri için.
Testleri de kullanması mantıklı veri anlamında değerli, fakat onun dışında
verilerin test olduğunu sistem bilmeli."

Kullanim:
    from test_user_registry import is_test_phone

    if is_test_phone("905309356389"):
        is_test = True

Listeyi guncelleme: TEST_USER_PHONES env var (virgulle ayrilmis) VEYA
default listede ekle. Production'da env oncelikli.

Filtreleme ornegi:
    SELECT * FROM routing_stats WHERE is_test_user = false  -- gercek kullanici
    SELECT * FROM routing_stats                              -- hepsi (default)
"""
from __future__ import annotations
import os
from typing import Set


# Default test telefonlar — manuel kontrol amacli, gercek kullanici değil
# 9 May 2026 — Neo "render araç testi" yapan numaralar:
DEFAULT_TEST_PHONES: Set[str] = {
    "905309356389",  # 9 May render araç testi (235 mesaj burst)
    # NOT: 905051256802 (Neo) admin → test_user DEGIL, ama dashboard'larda
    # admin filtreleme ayrı yapılır (system_prompts'ta zaten WHERE phone!=admin var)
}


def _load_test_phones() -> Set[str]:
    """Env var TEST_USER_PHONES VARsa onu kullan, yoksa default."""
    env_val = os.environ.get("TEST_USER_PHONES", "").strip()
    if not env_val:
        return DEFAULT_TEST_PHONES.copy()

    # Virgul/bosluk/satir sonu ayirici hosgor
    parts = [p.strip() for p in env_val.replace("\n", ",").replace(" ", ",").split(",")]
    phones = {p for p in parts if p and p.isdigit()}
    # Default ile birlestir (env eklemeci)
    return phones | DEFAULT_TEST_PHONES


# Modul yuklenirken bir kere oku
_TEST_PHONES = _load_test_phones()


def is_test_phone(phone: str) -> bool:
    """Telefon numarasi test kullanici mi? (gercek prod kullanici degil)

    Ornek:
        >>> is_test_phone("905309356389")
        True
        >>> is_test_phone("905050952398")  # Mehmet Karpuz, gercek
        False
        >>> is_test_phone("")
        False
    """
    if not phone:
        return False
    # Normalize: + isareti, bosluk, vs. cikar
    p = str(phone).replace("+", "").replace(" ", "").strip()
    return p in _TEST_PHONES


def list_test_phones() -> list[str]:
    """Mevcut test telefon listesini don (debug/admin icin)."""
    return sorted(_TEST_PHONES)


def add_test_phone(phone: str) -> bool:
    """Runtime'da test phone ekle (dashboard'tan veya admin komuttan).

    NOT: Persist edilmez — restart sonrasi kaybolur. Kalici icin .env'e ekle.
    """
    p = str(phone).replace("+", "").replace(" ", "").strip()
    if p and p.isdigit() and p not in _TEST_PHONES:
        _TEST_PHONES.add(p)
        return True
    return False


if __name__ == "__main__":
    print(f"Test phones registered: {len(_TEST_PHONES)}")
    for p in list_test_phones():
        print(f"  {p}")
    # Self-test
    assert is_test_phone("905309356389") is True
    assert is_test_phone("905050952398") is False
    assert is_test_phone("") is False
    assert is_test_phone("+905309356389") is True  # plus isareti hosgor
    print("[OK] test_user_registry self-test PASS")
