"""groq_lanes production scenarios (25 Nisan + 26 Nisan canli mesajlar)"""
from groq_lanes import classify_lane, is_groq_safe


# Production'dan gercek mesajlar (kaynak: agent_conversations)
PROD_CASES = [
    # (mesaj, beklenen_lane)
    ('propanoik asit IUPAC adi midir', 'kavramsal_kisa'),
    ('turev nedir', 'kavramsal_kisa'),
    ('limit kavrami anlat', 'kavramsal_kisa'),
    ('Newton kanunu nedir', 'kavramsal_kisa'),
    ('selam', 'sohbet'),
    ('teşekkür ederim', 'sohbet'),
    ('İngilizce devam etsek', 'meta_direktif'),
    ('Emoji koymadan konuş', 'meta_direktif'),
    ('Japonca devam edelim', 'meta_direktif'),
    ('Balık çorbası rezillikmidir', 'sohbet'),
    ('Eğlenceli bir şeyler yapalım mı', 'sohbet'),
    ('Galatasarayın 1971 1972 sezonu yedek kadrosu analizi', 'red_generik'),
    ('YKS stratejisi nasıl olmalı', 'egitim_icerik'),
    ('Süper', 'kibarlik'),
    ('Fen full geldi', 'kibarlik'),
    # CLAUDE'a gitmeli — None
    ('benim gelişimim sence nasıl?', None),
    ('matematikte nasılım sence', None),
    ('Reis benim ortalama puanımı ver', None),
    ('etut yaz Ali için', None),
    ('intihar etmek istiyorum', None),
    ('Niye çok kabasın ya', None),
    ('hala anlamadın beni', None),
    ('yapamıyorum', 'kisa_motivasyon'),
]


def test_all_production_cases():
    fails = []
    for msg, expected in PROD_CASES:
        got = classify_lane(msg, role='ogrenci')
        if got != expected:
            fails.append(f'"{msg[:40]}" expected={expected} got={got}')
    assert not fails, '\n  '.join([''] + fails)


def test_kavramsal_kisa_groq_safe():
    assert is_groq_safe('kavramsal_kisa') is True


def test_none_not_groq_safe():
    assert is_groq_safe(None) is False


def test_kvkk_personal_data_blocked():
    assert classify_lane('benim netim kac', role='ogrenci') is None


def test_kriz_blocked():
    assert classify_lane('intihar etmek istiyorum', role='ogrenci') is None
    assert classify_lane('hayata küstüm artık', role='ogrenci') is None


def test_long_message_blocked():
    """250+ char uzun mesaj complex sayilir"""
    long_msg = 'turev nedir ' * 30  # ~360 char
    assert classify_lane(long_msg, role='ogrenci') is None
