"""knowledge_graph müfredat seed + helper testleri"""
from knowledge_graph import YKS_CURRICULUM


def test_curriculum_not_empty():
    assert len(YKS_CURRICULUM) >= 70


def test_curriculum_has_all_main_subjects():
    """6 ana ders olmalı"""
    derslar = {c[0] for c in YKS_CURRICULUM}
    expected = {'Matematik', 'Geometri', 'Fizik', 'Kimya', 'Biyoloji', 'Türkçe'}
    assert expected.issubset(derslar)


def test_curriculum_seviye_values():
    """Sadece TYT/AYT/LGS seviye"""
    seviyeler = {c[2] for c in YKS_CURRICULUM}
    assert seviyeler.issubset({'TYT', 'AYT', 'LGS'})


def test_matematik_has_turev_limit_integral():
    """AYT Matematik kritik konuları"""
    konular = {c[1].lower() for c in YKS_CURRICULUM if c[0] == 'Matematik'}
    assert 'türev' in konular
    assert 'limit' in konular
    assert 'i̇ntegral' in konular or 'integral' in konular


def test_turev_has_limit_prerequisite():
    """Türev'in ön koşulu Limit olmalı (pedagojik)"""
    for ders, konu, seviye, prereqs in YKS_CURRICULUM:
        if konu.lower() == 'türev':
            prereq_konular = [p[1].lower() for p in prereqs]
            assert 'limit' in prereq_konular
            return
    raise AssertionError('Türev curriculum item not found')


def test_integral_has_turev_prerequisite():
    """İntegral'in ön koşulu Türev"""
    for ders, konu, seviye, prereqs in YKS_CURRICULUM:
        if konu.lower() in ('integral', 'i̇ntegral'):
            prereq_konular = [p[1].lower() for p in prereqs]
            assert 'türev' in prereq_konular
            return


def test_curriculum_no_self_prerequisite():
    """Hicbir konu kendi kendinin on kosulu olamaz"""
    for ders, konu, seviye, prereqs in YKS_CURRICULUM:
        for p_ders, p_konu, _ in prereqs:
            assert not (p_ders == ders and p_konu == konu), \
                f'{ders}/{konu} kendi kendisinin on kosulu'
