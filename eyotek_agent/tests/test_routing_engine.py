"""routing_engine.decide_route + frustration tests"""
from routing_engine import decide_route, detect_frustration, detect_duygu_psikoloji


def test_admin_to_claude():
    assert decide_route('analiz yap', role='admin') == 'claude'


def test_admin_greeting_to_fast():
    assert decide_route('selam', role='admin') == 'fast'


def test_ogrenci_kavramsal_to_local():
    assert decide_route('turev nedir', role='ogrenci') == 'local'


def test_ogrenci_personal_to_claude():
    assert decide_route('benim netim ne', role='ogrenci') == 'claude'


def test_ogrenci_tool_required_to_claude():
    assert decide_route('etut yaz Ali icin', role='ogrenci') == 'claude'


def test_frustration_intercept_to_claude():
    assert decide_route('chatgpt iyi', role='ogrenci') == 'claude'


def test_kaba_intercept():
    """25.10 fix: 'kaba' frustration"""
    assert decide_route('niye kabasın', role='ogrenci') == 'claude'


def test_kriz_to_claude():
    assert decide_route('intihar etmek istiyorum', role='ogrenci') == 'claude'


def test_detect_frustration_extended():
    """Oturum 25.10: extended keywords"""
    assert detect_frustration('hala anlamadın beni') is True


def test_detect_duygu_psikoloji():
    assert detect_duygu_psikoloji('canım sıkkın') is True
    assert detect_duygu_psikoloji('moralim bozuk') is True


def test_long_msg_admin_to_claude():
    """Admin uzun mesaj her zaman Claude"""
    long = 'detayli rapor istiyorum su konuda ' * 5  # ~150 char
    assert decide_route(long, role='admin') == 'claude'
