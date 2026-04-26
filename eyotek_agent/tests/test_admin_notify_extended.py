"""admin_notify ek testler — severity routing logic"""
from admin_notify import _is_quiet_hour, NEO_PHONE


def test_neo_phone_constant():
    assert NEO_PHONE == "905051256802"


def test_quiet_boundary_exact_8am():
    """08:00 quiet biter"""
    from datetime import datetime
    assert _is_quiet_hour(datetime(2026, 4, 26, 8, 0, 0)) is False
    # 7:59 hala quiet
    assert _is_quiet_hour(datetime(2026, 4, 26, 7, 59, 59)) is True


def test_quiet_boundary_exact_20pm():
    """20:00 quiet baslar"""
    from datetime import datetime
    assert _is_quiet_hour(datetime(2026, 4, 26, 20, 0, 0)) is True
    assert _is_quiet_hour(datetime(2026, 4, 26, 19, 59, 59)) is False


def test_quiet_no_arg_uses_now():
    """Argument yoksa datetime.now() kullanilir"""
    result = _is_quiet_hour()
    assert isinstance(result, bool)
