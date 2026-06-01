"""
wa_config.py — Meta WhatsApp Graph API tek-kaynak yapılandırması (Oturum 25.50)
==============================================================================
NEDEN: Graph API versiyonu 6 dosyada 4 FARKLI değerle (v18/v21/v23/v25) hardcoded'du.
Meta bir versiyonu deprecate ettiğinde (genelde 2 yıl pencere) tek tek aramak +
bazılarını unutmak riski vardı (v18.0 zaten çok eskiydi — conversation_quality_analyzer
hâlâ onu kullanıyordu). Artık TEK yerden: GRAPH_API_VERSION env / bu sabit.

Kullanım:
  from wa_config import GRAPH_BASE, graph_url
  url = f"{GRAPH_BASE}/{phone_id}/messages"
  # veya
  url = graph_url(f"{phone_id}/messages")

Versiyon güncelleme: .env'de GRAPH_API_VERSION=v26.0 → tüm sistem otomatik.
Bağımlılık-sız (sadece os) — circular import riski yok, her modülden güvenle import edilir.
"""
import os

# Meta Graph API versiyonu — Haziran 2026 itibarıyla v25.0 güncel/stabil.
# Deprecation takibi: model_health.py mantığıyla ileride graph /me?fields ping eklenebilir.
GRAPH_API_VERSION = os.getenv("GRAPH_API_VERSION", "v25.0")
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


def graph_url(path: str) -> str:
    """Graph API tam URL üret. path baştaki / opsiyonel."""
    return f"{GRAPH_BASE}/{path.lstrip('/')}"
