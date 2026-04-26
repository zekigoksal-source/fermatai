"""role_access ACL matrix testleri"""
from role_access import _is_tool_allowed


def test_admin_can_finans():
    """Admin finans tool'larini kullanabilir"""
    assert _is_tool_allowed('admin', 'finans_ozet') is True


def test_ogrenci_cannot_finans():
    """Ogrenci finans tool'larini KULLANAMAZ"""
    assert _is_tool_allowed('ogrenci', 'finans_ozet') is False


def test_admin_can_query_analytics():
    assert _is_tool_allowed('admin', 'query_analytics') is True


def test_ogrenci_can_search_curriculum():
    """Ogrenci RAG müfredat arar"""
    assert _is_tool_allowed('ogrenci', 'search_curriculum') is True


def test_mudur_can_query_analytics():
    """Mudur kurum verisi okur"""
    assert _is_tool_allowed('mudur', 'query_analytics') is True
