"""predictive_model pure logic testleri"""
from predictive_model import _linear_trend, _net_to_yerlesme_puani

def test_linear_trend_rising():
    slope, proj = _linear_trend([60, 62, 65, 63, 67])
    assert slope > 0
    assert 65 < proj < 75

def test_linear_trend_falling():
    slope, proj = _linear_trend([70, 65, 60, 55, 50])
    assert slope < 0
    assert proj <= 50

def test_linear_trend_stable():
    slope, proj = _linear_trend([60, 60, 60, 60, 60])
    assert abs(slope) < 0.1
    assert abs(proj - 60) < 1

def test_linear_trend_empty():
    slope, proj = _linear_trend([])
    assert slope == 0 and proj == 0

def test_yerlesme_puani_tyt_only():
    yp = _net_to_yerlesme_puani(60, 0)
    assert yp == 340  # 100 + 60*4

def test_yerlesme_puani_with_ayt():
    yp = _net_to_yerlesme_puani(60, 20)
    # 0.4 * 340 + 0.6 * 180 = 136 + 108 = 244
    assert 240 < yp < 250
