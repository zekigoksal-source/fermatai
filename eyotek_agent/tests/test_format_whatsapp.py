"""format_whatsapp chart cleaner (Oturum 25.8 P9 fix)"""
from format_whatsapp import format_for_whatsapp

def test_chart_with_title_replaced():
    text = 'Hi!\n```chart\n{"type":"line","title":"AYT Mat 2026"}\n```\nBye'
    out = format_for_whatsapp(text, source='claude')
    assert 'AYT Mat 2026' in out
    assert 'json' not in out.lower()
    assert 'type' not in out.lower() or 'type":"line' not in out

def test_chart_without_title_removed():
    text = 'Hi!\n```chart\n{"type":"line"}\n```\nBye'
    out = format_for_whatsapp(text, source='claude')
    assert '```' not in out
    assert 'chart' not in out.lower() or 'json' not in out.lower()

def test_markdown_bold_to_wp():
    text = 'Bu **çok** önemli'
    out = format_for_whatsapp(text, source='claude')
    assert '*çok*' in out
    assert '**' not in out

def test_h1_to_bold():
    text = '# Başlık\nİçerik'
    out = format_for_whatsapp(text, source='claude')
    assert '*Başlık*' in out
    assert '#' not in out.split('\n')[0]
