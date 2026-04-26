"""format_whatsapp ek senaryo testleri (Oturum 25.11)"""
from format_whatsapp import format_for_whatsapp


def test_groq_source_kabul():
    """Yeni 'groq' source enforcer'i tetikler"""
    text = "Merhaba **bold** test"
    out = format_for_whatsapp(text, source='groq')
    assert '*bold*' in out
    assert '**' not in out


def test_local_source_kabul():
    """Yeni 'local' source da kabul"""
    text = "Test"
    out = format_for_whatsapp(text, source='local')
    assert isinstance(out, str)


def test_short_text_passthrough():
    """5 karakterden kisa metin oldugu gibi doner"""
    assert format_for_whatsapp("Hi", source='claude') == 'Hi'


def test_empty_text():
    assert format_for_whatsapp('', source='claude') == ''


def test_h2_to_bold():
    """## Başlık → *Başlık*"""
    text = '## Başlık\nİçerik metin'
    out = format_for_whatsapp(text, source='claude')
    assert '*Başlık*' in out
    assert '## ' not in out


def test_link_format():
    """[text](url) → text (url)"""
    text = 'Buraya bak: [Site](https://example.com)'
    out = format_for_whatsapp(text, source='claude')
    assert 'Site' in out
    assert 'https://example.com' in out
    assert '[Site]' not in out


def test_table_to_list():
    """Markdown tablosu pipe-separated liste'ye"""
    text = "| Kol1 | Kol2 |\n|------|------|\n| Veri1 | Veri2 |"
    out = format_for_whatsapp(text, source='claude')
    assert '|--' not in out  # tablo separator yok


def test_multiple_chart_blocks():
    """Birden fazla chart bloğu hepsi temizlenmeli"""
    text = '''Bak:
```chart
{"type":"line","title":"Test1"}
```
ve
```chart
{"type":"bar","title":"Test2"}
```
'''
    out = format_for_whatsapp(text, source='claude')
    assert 'Test1' in out
    assert 'Test2' in out
    assert '"type"' not in out


def test_excessive_newlines_collapsed():
    """3+ satır boşluk → 2 satır"""
    text = "A\n\n\n\n\nB"
    out = format_for_whatsapp(text, source='claude')
    assert '\n\n\n' not in out
