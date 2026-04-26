"""tool_definitions DEAD_TOOLS + role-aware filtering testleri (Oturum 25.11)"""
from tool_definitions import TOOLS, TOOLS_ACTIVE, DEAD_TOOLS, get_tools


def test_tools_full_count():
    """Tum tool'lar 64 (Oturum 25.9'dan beri stabil)"""
    assert len(TOOLS) >= 60  # Buyume olabilir, kucume yok


def test_tools_active_excludes_dead():
    """TOOLS_ACTIVE'da DEAD_TOOLS olmamalı"""
    active_names = {t['name'] for t in TOOLS_ACTIVE}
    assert active_names.isdisjoint(DEAD_TOOLS)


def test_dead_tools_count():
    """En az 12 dead tool olmali (Oturum 25.11 audit)"""
    assert len(DEAD_TOOLS) >= 12


def test_admin_gets_all_tools():
    """Admin tum tool'lari alir (finans dahil)"""
    admin_tools = get_tools(role='admin')
    assert len(admin_tools) == len(TOOLS)


def test_ogrenci_gets_active_only():
    """Ogrenci sadece active tool'lar — DEAD haric"""
    ogr_tools = get_tools(role='ogrenci')
    assert len(ogr_tools) == len(TOOLS_ACTIVE)
    assert len(ogr_tools) < len(TOOLS)


def test_mudur_gets_active_only():
    """Mudur de active subset"""
    mudur_tools = get_tools(role='mudur')
    names = {t['name'] for t in mudur_tools}
    assert names.isdisjoint(DEAD_TOOLS)


def test_include_dead_returns_full():
    """include_dead=True → tum 64"""
    full = get_tools(role='ogrenci', include_dead=True)
    assert len(full) == len(TOOLS)


def test_each_tool_has_required_fields():
    """Her tool name + description + input_schema icermeli (Anthropic format)"""
    for t in TOOLS:
        assert 'name' in t
        assert 'description' in t
        assert 'input_schema' in t
        assert isinstance(t['name'], str)


def test_no_duplicate_tool_names():
    """Tool isimleri unique"""
    names = [t['name'] for t in TOOLS]
    assert len(names) == len(set(names))


def test_dead_tools_not_critical():
    """DEAD_TOOLS'ta kritik tool olmamali (sanity check)"""
    critical = {
        'get_student_analytics', 'query_analytics',
        'execute_eyotek_action', 'send_exam_image',
        'predict_yks_score', 'search_curriculum',
    }
    assert critical.isdisjoint(DEAD_TOOLS)
