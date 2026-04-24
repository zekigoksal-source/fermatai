"""
phone_utils unit testleri — normalize_phone ve phones_equal.
"""
import pytest
from phone_utils import normalize_phone, phones_equal


@pytest.mark.parametrize("inp,exp", [
    ("+905051256802", "905051256802"),
    ("905051256802", "905051256802"),
    ("05051256802", "905051256802"),
    ("5051256802", "905051256802"),
    ("+90 505 125 68 02", "905051256802"),
    ("(0505) 125-68-02", "905051256802"),
    ("+90-505-125-6802", "905051256802"),
])
def test_normalize_valid(inp, exp):
    assert normalize_phone(inp) == exp


@pytest.mark.parametrize("inp", [
    None,
    "",
    " ",
    "+90 ",
    "abc",
    "12345",      # <10 digit
    "+9012345",   # <10 digit after +
])
def test_normalize_invalid(inp):
    assert normalize_phone(inp) is None


def test_phones_equal_different_formats():
    assert phones_equal("+905051256802", "905051256802")
    assert phones_equal("+90 505 125 68 02", "905051256802")
    assert phones_equal("05051256802", "905051256802")


def test_phones_equal_none():
    # Iki None karsilastirmasi semantik olarak False (bos deger esit sayilmaz)
    assert not phones_equal(None, None)
    assert not phones_equal("", "")
    assert not phones_equal(None, "905051256802")


def test_phones_equal_different_numbers():
    assert not phones_equal("905051256802", "905051256803")


def test_idempotent():
    """Iki kere normalize aynı sonucu vermeli."""
    assert normalize_phone(normalize_phone("+905051256802")) == "905051256802"
    assert normalize_phone(normalize_phone("905051256802")) == "905051256802"
