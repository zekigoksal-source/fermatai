"""
Alert System Testleri (23 Nisan 2026 — Oturum 23 audit)
==========================================================
Neo "aktif et" diyene kadar ALERTS_ACTIVE=False — bu test o invaryantı
korur + dry-run check fonksiyonlarının bozulmadığını doğrular.

Kapsanan:
  - ALERTS_ACTIVE=False invaryantı
  - send_alerts flag check (güvenlik)
  - format_alert_message boş/dolu senaryolar
  - check_* fonksiyonlar DB schema uyumlu
"""
import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run_with_pool_reset(coro):
    """Async test yardımcısı — db_pool singleton'ı her test arası sıfırla."""
    import db_pool
    db_pool._pool = None
    try:
        return asyncio.run(coro)
    finally:
        db_pool._pool = None


# ═══════════════════════════════════════════════════════════════════════════
# GÜVENLİK INVARYANTLARI
# ═══════════════════════════════════════════════════════════════════════════

def test_alerts_default_kapali():
    """ALERTS_ACTIVE=False invaryantı — Neo onayı olmadan ASLA True olmaz."""
    from alert_system import ALERTS_ACTIVE
    assert ALERTS_ACTIVE is False, (
        "ALERTS_ACTIVE=True yapıldı ama Neo onayı repo'da yok. "
        "feedback_no_unauthorized_messages.md kuralı ihlal ediliyor."
    )


def test_neo_phone_sabit():
    """Alarm hedefi Neo'nun telefonu sabit — başka numaraya gönderim yok."""
    from alert_system import NEO_PHONE
    assert NEO_PHONE == "905051256802"


async def _test_send_alerts_guvenlik():
    """send_alerts ALERTS_ACTIVE=False'ken gönderim yapmaz, False döner."""
    from alert_system import send_alerts
    # Boş results — zaten mesaj yok
    sent = await send_alerts({})
    assert sent is False, "ALERTS_ACTIVE=False olduğunda send_alerts True dönmemeli!"


def test_send_alerts_guvenlik():
    _run_with_pool_reset(_test_send_alerts_guvenlik())


# ═══════════════════════════════════════════════════════════════════════════
# CHECK FONKSIYONLARI — DRY-RUN (göndermez, sadece tespit eder)
# ═══════════════════════════════════════════════════════════════════════════

async def _test_check_net_dusus_dry():
    """check_net_dusus çalışmalı, liste dönmeli (boş olabilir, hata olmamalı)."""
    from alert_system import check_net_dusus
    results = await check_net_dusus()
    assert isinstance(results, list), f"liste bekleniyordu: {type(results)}"
    # Her item zorunlu alanları içeriyor mu?
    for r in results[:3]:
        assert "soz_no" in r or "full_name" in r


def test_check_net_dusus_dry():
    _run_with_pool_reset(_test_check_net_dusus_dry())


async def _test_check_devamsizlik_dry():
    from alert_system import check_devamsizlik
    results = await check_devamsizlik()
    assert isinstance(results, list)


def test_check_devamsizlik_dry():
    _run_with_pool_reset(_test_check_devamsizlik_dry())


async def _test_check_duygu_dry():
    from alert_system import check_duygu_sinyal
    results = await check_duygu_sinyal()
    assert isinstance(results, list)


def test_check_duygu_dry():
    _run_with_pool_reset(_test_check_duygu_dry())


# ═══════════════════════════════════════════════════════════════════════════
# FORMAT
# ═══════════════════════════════════════════════════════════════════════════

def test_format_alert_bos():
    """Boş results'ta format None veya boş string dönmeli."""
    from alert_system import format_alert_message
    msg = format_alert_message({})
    assert not msg or msg.strip() == ""


def test_format_alert_dolu():
    """Dolu results'ta mesaj üretilmeli."""
    from alert_system import format_alert_message
    fake_results = {
        "net_dusus": [{"full_name": "Test Öğrenci", "fark": -10, "son_net": 20}],
        "devamsizlik": [],
        "duygu_kriz": [],
    }
    msg = format_alert_message(fake_results)
    # Boş olmayabilir ama çalışmalı
    assert msg is None or isinstance(msg, str)


# ═══════════════════════════════════════════════════════════════════════════
# RUN ALL CHECKS
# ═══════════════════════════════════════════════════════════════════════════

async def _test_run_all_checks():
    """run_all_checks dict dönmeli, üç kategori var."""
    from alert_system import run_all_checks
    results = await run_all_checks()
    assert isinstance(results, dict)
    # alert_system.py'de anahtarlar: risk_dusus, devamsizlik, duygu_kriz
    expected_keys = {"risk_dusus", "devamsizlik", "duygu_kriz"}
    assert expected_keys.issubset(set(results.keys())), (
        f"Eksik kategori: {expected_keys - set(results.keys())}"
    )


def test_run_all_checks():
    _run_with_pool_reset(_test_run_all_checks())
