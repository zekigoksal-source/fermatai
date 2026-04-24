"""Oturum 20 regresyon testleri — tüm değişiklikleri korur."""
import pytest
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── Puan Hesaplama ──────────────────────────────────────────────────────────

def test_tyt_puan_ogm_kalibre():
    """TYT puan hesaplama OGM ile kalibre — fark <1 puan."""
    from puan_hesaplama import hesapla_tyt
    r = hesapla_tyt(29, 9, 18, 9, 80)
    # OGM gerçek: 336.874
    assert abs(r["ham_puan"] - 336.874) < 1.0, f"TYT fark çok büyük: {r['ham_puan']} vs 336.874"


def test_say_puan_ogm_kalibre():
    """SAY puan hesaplama OGM ile kalibre — fark <5 puan."""
    from puan_hesaplama import hesapla_say
    r = hesapla_say(26.5, 8.75, 16, 9, 18, 6.25, 5.25, 4.25, 80)
    # OGM gerçek: 299.502
    assert abs(r["ham_puan"] - 299.502) < 5.0, f"SAY fark çok büyük: {r['ham_puan']} vs 299.502"


def test_net_etkisi():
    """Net etkisi hesaplama — fizik +3 net."""
    from puan_hesaplama import net_etkisi
    etki = net_etkisi("fizik", 3, "SAY")
    assert etki > 5, f"Fizik +3 net etkisi çok düşük: {etki}"
    assert etki < 15, f"Fizik +3 net etkisi çok yüksek: {etki}"


# ── Routing Engine ──────────────────────────────────────────────────────────

def test_admin_routing_claude():
    """Admin mesajları her zaman Claude'a."""
    from routing_engine import decide_route
    assert decide_route("mimari anlat", "admin") == "claude"
    assert decide_route("analiz yap", "admin") == "claude"


def test_admin_selamlama_fast():
    """Admin selamlama fast_response'ta."""
    from routing_engine import decide_route
    assert decide_route("selam", "admin") == "fast"
    assert decide_route("merhaba", "admin") == "fast"


def test_kavramsal_claude():
    """Kavramsal sorular Claude'a."""
    from routing_engine import decide_route
    assert decide_route("türev nedir", "ogrenci") == "claude"
    assert decide_route("fotosentez açıkla", "ogrenci") == "claude"


def test_context_dependent_claude():
    """Context-dependent kısa mesajlar Claude'a (routing_engine veya fast_response)."""
    from routing_engine import decide_route
    # routing_engine: "devam" → claude (kısa + context-dependent)
    assert decide_route("devam et", "ogrenci") == "claude"
    assert decide_route("gönder", "ogrenci") == "claude"
    # "cevap e" fast_responses'ta yakalanır → None → Claude. routing_engine'de "auto".


# ── Format WhatsApp ─────────────────────────────────────────────────────────

def test_bold_conversion():
    """**bold** → *bold* dönüşümü."""
    from format_whatsapp import format_for_whatsapp
    r = format_for_whatsapp("Bu **önemli** bir metin", "claude")
    assert "**" not in r
    assert "*önemli*" in r


def test_emoji_ekleme():
    """Emoji yoksa otomatik eklenir (40+ char metin)."""
    from format_whatsapp import format_for_whatsapp
    long_text = (
        "Merhaba bu bir test mesaji ve oldukca uzun olmali ki "
        "format_whatsapp fonksiyonu emoji ekleyebilsin cunku kisa "
        "metinlere emoji eklenmez bu bir kalite kontrol testi"
    )
    r = format_for_whatsapp(long_text, "claude")
    import re
    has_emoji = bool(re.search(r'[\U0001f300-\U0001f9ff]', r))
    assert has_emoji, f"Emoji eklenmedi: {r[:100]}"


# ── Detect Subject ──────────────────────────────────────────────────────────

def test_fizik_tespiti():
    from detect_subject import detect_subject
    assert detect_subject("kaldırma kuvveti nedir") == "Fizik"
    assert detect_subject("fotoelektrik olay") == "Fizik"


def test_matematik_tespiti():
    from detect_subject import detect_subject
    assert detect_subject("integral hesapla") == "Matematik"
    assert detect_subject("türev formülü") == "Matematik"


def test_biyoloji_tespiti():
    from detect_subject import detect_subject
    assert detect_subject("fotosentez nedir") == "Biyoloji"
    assert detect_subject("hücre bölünmesi") == "Biyoloji"


# ── Motivasyon Çeşitlilik ──────────────────────────────────────────────────

def test_motivasyon_cesitlilik():
    """30 template — aynısı tekrar etmemeli."""
    from motivation_library import get_trend_motivasyon
    results = set()
    for _ in range(10):
        r = get_trend_motivasyon("Test", "yukselis")
        results.add(r[:50])  # İlk 50 char
    assert len(results) >= 3, f"Yeterli çeşitlilik yok: {len(results)} farklı"


def test_motivasyon_tum_trendler():
    """3 trend de çalışıyor."""
    from motivation_library import get_trend_motivasyon
    for trend in ["yukselis", "dusus", "stabil"]:
        r = get_trend_motivasyon("Ali", trend)
        assert len(r) > 50, f"{trend} template çok kısa"
        assert "Ali" in r, f"{trend} template isim içermiyor"


# ── DB Pool ─────────────────────────────────────────────────────────────────

def test_db_pool_import():
    """db_pool modülü import edilebilir."""
    from db_pool import DB_URL, get_pool, db_fetch
    assert "fermatai" in DB_URL
    assert callable(get_pool)
    assert callable(db_fetch)


# ── Eyotek Knowledge ────────────────────────────────────────────────────────

def test_site_map_exists():
    """site_map.json mevcut ve geçerli."""
    import json
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "eyotek_knowledge", "site_map.json")
    with open(path, 'r', encoding='utf-8') as f:
        sm = json.load(f)
    assert "sync_kaynaklar" in sm
    assert len(sm["sync_kaynaklar"]) >= 5


def test_eyotek_commands_import():
    """Eyotek komutları import edilebilir."""
    from eyotek_knowledge.eyotek_commands import handle_eyotek_command
    assert callable(handle_eyotek_command)


def test_scrapers_import():
    """Eyotek scraper modülleri mevcut."""
    import os
    base = os.path.join(os.path.dirname(os.path.dirname(__file__)), "eyotek_knowledge", "scrapers")
    for f in ["etut_sync.py", "yoklama_sync.py", "sinav_sync.py", "ogrenci_sync.py"]:
        assert os.path.exists(os.path.join(base, f)), f"{f} bulunamadı"
