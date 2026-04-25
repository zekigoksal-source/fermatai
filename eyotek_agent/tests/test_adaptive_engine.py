"""adaptive_engine pure logic testleri (DB-less)"""
from adaptive_engine import expected_score, sm2_next

def test_elo_expected_score_underdog():
    """1200 vs 1500: ~0.15 win probability"""
    e = expected_score(1200, 1500)
    assert 0.13 < e < 0.18

def test_elo_expected_score_favorite():
    """1500 vs 1200: ~0.85"""
    e = expected_score(1500, 1200)
    assert 0.82 < e < 0.87

def test_elo_equal_rating():
    e = expected_score(1500, 1500)
    assert abs(e - 0.5) < 0.001

def test_sm2_first_correct():
    """Doru ilk cevap: reps=1, interval=1"""
    reps, ef, intv = sm2_next(quality=4, repetitions=0, ease_factor=2.5, interval_days=1)
    assert reps == 1 and intv == 1

def test_sm2_second_correct():
    """Iki dogru: interval 6"""
    reps, ef, intv = sm2_next(quality=4, repetitions=1, ease_factor=2.5, interval_days=1)
    assert reps == 2 and intv == 6

def test_sm2_wrong_resets():
    """Yanlis cevap -> reps=0, interval=1"""
    reps, ef, intv = sm2_next(quality=1, repetitions=5, ease_factor=2.5, interval_days=30)
    assert reps == 0 and intv == 1

def test_sm2_ease_factor_floor():
    """EF asla 1.3'un altina inmez"""
    _, ef, _ = sm2_next(quality=0, repetitions=0, ease_factor=1.0, interval_days=1)
    assert ef >= 1.3
