"""
Fast Response Anti-Repeat Guard (Oturum 25.41 — Neo direktifi)
==============================================================

NEO TALEP (5 May):
"Eger kullanici tekrar ayni soruyu tekrarlarsa bu yine cat diye fast response
tetiklenmesin asla ayni cevabi arka arkaya attigi bir diyalog senaryosu olmamali.
Kullanici tekrar soruyorsa veya detay istiyorsa demekki bu sefer Intent Classifier
konuyu anlayip ilgili yere iletmeli kendisi loop gibi ayni kelime ile tekrar
tekrar tetiklenmemeli."

Mantik:
- In-memory cache: phone -> {handler, timestamp, message}
- Eger ayni handler son 90 saniyede tetiklendiyse → SKIP (return True)
- Caller fast_response None doner → routing engine devreye → LLM (Cerebras/Claude)
  baglamlarini okuyup farkli/derin cevap verir.

Hassas degil — selamlama/ack/foto_hakki/kurum_bilgi/web_kodu gibi statik handler'lar
zaten skip listesinde (tekrar gonderilmeli).

Token tasarrufu: User tekrarliyorsa LLM context'le anlami cikarir, fast'in
duz cevabi yetmez.
"""
from __future__ import annotations

import time
from collections import OrderedDict
from typing import Optional


# In-memory cache: phone -> deque[(handler, timestamp), (handler, timestamp)]
# OrderedDict ile FIFO eviction (max 200 phone)
_HISTORY: "OrderedDict[str, list]" = OrderedDict()
_MAX_PHONES = 200
_HISTORY_DEPTH = 3  # son 3 handler kaydet
_REPEAT_WINDOW_SEC = 90  # 90 saniye icinde ayni handler → skip

# SKIP edilmemesi gereken handler'lar (her seferinde fast versin)
_SAFE_REPEAT_HANDLERS = {
    "selamlama", "selamlasma", "selamla", "sohbet",
    "veda_cevap",
    "web_kodu", "web_kodu_auth_fast",
    "foto_hakki",  # ogrenci sik sorabilir, sayac degisir
    "yetenekler", "get_yetenekler",
    "neo_menu",
    "kurum_reddet", "_handler_kurum_reddet",
    "GIZLILIK_CEVAP",
    # Hack/safety responses — her zaman tetiklenmeli
    "hack_attempt", "tehdit", "kufur", "frustration",
    # Acil yonlendirme
    "privacy_reject",
    # Konu degisikligi olabilir, her sefer yeniden hesap
    "selamlama",
}


def _record_handler(phone: str, handler: str, message: str) -> None:
    """Phone icin yeni handler kaydet."""
    if not phone or not handler:
        return
    now = time.time()
    if phone not in _HISTORY:
        _HISTORY[phone] = []
        # Eviction
        if len(_HISTORY) > _MAX_PHONES:
            _HISTORY.popitem(last=False)

    h_list = _HISTORY[phone]
    h_list.append({
        "handler": handler,
        "ts": now,
        "msg": (message or "")[:50],
    })
    # Trim to depth
    if len(h_list) > _HISTORY_DEPTH:
        del h_list[: len(h_list) - _HISTORY_DEPTH]


def should_skip_repeat(phone: str, handler: str, message: str = "") -> bool:
    """Bu handler son N saniye icinde tetiklendi mi? Tetiklendi ise SKIP et.

    Returns:
        True  → skip (return None to caller, LLM devreye)
        False → normal fast response calistir + record
    """
    if not phone or not handler:
        return False

    # Safe handler'lar her zaman tetiklenmeli
    if handler in _SAFE_REPEAT_HANDLERS:
        return False

    # History yoksa skip etme
    h_list = _HISTORY.get(phone)
    if not h_list:
        return False

    # Son handler kontrolu
    last = h_list[-1]
    if last["handler"] != handler:
        return False

    # Zaman kontrolu
    age = time.time() - last["ts"]
    if age > _REPEAT_WINDOW_SEC:
        return False

    # Mesaj cok benzer mi (ek kontrol — false positive azaltma)
    # Eger mesaj cok farkli ise (ornegin onceki "son denemem", simdi "son denemem detay")
    # yine de skip et — cunku ayni handler tetikleniyor demek detay istiyor demek
    return True


def record_handler(phone: str, handler: str, message: str = "") -> None:
    """Public API — fast response success sonrasinda cagrilir."""
    _record_handler(phone, handler, message)


def get_recent_handlers(phone: str) -> list:
    """Debug/monitoring: phone icin son handler'lari don."""
    h_list = _HISTORY.get(phone, [])
    now = time.time()
    return [
        {**h, "age_sec": int(now - h["ts"])}
        for h in h_list
    ]


def clear_history(phone: str = "") -> None:
    """Belirli phone'u veya tum history'i temizle (test/debug)."""
    if phone:
        _HISTORY.pop(phone, None)
    else:
        _HISTORY.clear()


__all__ = [
    "should_skip_repeat",
    "record_handler",
    "get_recent_handlers",
    "clear_history",
]
