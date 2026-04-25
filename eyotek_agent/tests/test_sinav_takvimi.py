"""sinav_takvimi tek kaynak testleri (Oturum 25.8 fix)"""
from datetime import date
from sinav_takvimi import (
    TYT_DATE, AYT_DATE, LGS_DATE,
    days_until_tyt, days_until_ayt, yks_summary_line,
)

def test_tyt_date_correct():
    """TYT 20 Haziran 2026 (resmi OSYM)"""
    assert TYT_DATE == date(2026, 6, 20)

def test_ayt_date_correct():
    """AYT 21 Haziran 2026"""
    assert AYT_DATE == date(2026, 6, 21)

def test_lgs_date_correct():
    """LGS 7 Haziran 2026"""
    assert LGS_DATE == date(2026, 6, 7)

def test_days_until_tyt_25_april():
    """25 Nisan 2026 -> TYT 56 gun (Deren olayi tutarsizligi onleme)"""
    assert days_until_tyt(date(2026, 4, 25)) == 56

def test_days_until_ayt_25_april():
    assert days_until_ayt(date(2026, 4, 25)) == 57

def test_yks_summary_line_format():
    line = yks_summary_line(date(2026, 4, 25))
    assert "TYT" in line and "AYT" in line
    assert "56" in line  # gun sayisi
