"""admin_notify quiet hours testleri (Oturum 25.11)"""
from datetime import datetime
from admin_notify import _is_quiet_hour, WP_QUIET_START, WP_QUIET_END


def test_quiet_hours_default():
    assert WP_QUIET_START == 20
    assert WP_QUIET_END == 8


def test_quiet_at_midnight():
    assert _is_quiet_hour(datetime(2026, 4, 26, 0, 0)) is True


def test_quiet_at_3am():
    assert _is_quiet_hour(datetime(2026, 4, 26, 3, 0)) is True


def test_quiet_at_5_38am_neo_olayi():
    """Neo'nun 26 Nisan 05:38'de aldigi WP — quiet hours olmaliydi"""
    assert _is_quiet_hour(datetime(2026, 4, 26, 5, 38)) is True


def test_quiet_at_7am():
    assert _is_quiet_hour(datetime(2026, 4, 26, 7, 59)) is True


def test_not_quiet_at_8am():
    assert _is_quiet_hour(datetime(2026, 4, 26, 8, 0)) is False


def test_not_quiet_noon():
    assert _is_quiet_hour(datetime(2026, 4, 26, 12, 30)) is False


def test_not_quiet_at_19():
    assert _is_quiet_hour(datetime(2026, 4, 26, 19, 59)) is False


def test_quiet_at_20():
    assert _is_quiet_hour(datetime(2026, 4, 26, 20, 0)) is True


def test_quiet_at_23():
    assert _is_quiet_hour(datetime(2026, 4, 26, 23, 30)) is True
