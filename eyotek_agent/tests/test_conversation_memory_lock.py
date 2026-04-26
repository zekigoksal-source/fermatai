"""conversation_memory identity_lock detection (Oturum 25.8 KVKK fix)"""
from conversation_memory import build_context_prompt


def test_identity_lock_warning_in_prompt():
    """Identity locked iken prompt'a UYARI eklenmeli"""
    ctx = {
        'identity_locked': True,
        'identity_reason': 'kullanici hesap sahibinin yokluğunu soyledi',
    }
    prompt = build_context_prompt(ctx)
    assert 'KIMLIK MANIPULASYONU' in prompt
    assert 'akademik veri' in prompt.lower()


def test_no_identity_lock_normal():
    ctx = {
        'identity_locked': False,
        'name': 'Ali',
        'class': '12 SAY',
    }
    prompt = build_context_prompt(ctx)
    assert 'KIMLIK MANIPULASYONU' not in prompt


def test_empty_context():
    assert build_context_prompt({}) == ''
    assert build_context_prompt(None) == ''
