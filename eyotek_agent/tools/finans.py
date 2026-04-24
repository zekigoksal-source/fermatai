"""
Finans Tool Wrapper'ları — Neo-only erişim
==============================================
22.1n-neo: Finans tool'ları ACL'den geçer AMA her tool İÇİNDE
`is_finans_authorized(phone)` guard'ı çalışır (phone == NEO_PHONE şartı).

Bu modül sadece wrapper — iş mantığı `finans_tools.py`'de.
"""
from __future__ import annotations


async def _tool_finans_ozet(**kwargs):
    from finans_tools import finans_ozet
    return await finans_ozet(_caller_phone=kwargs.get("_caller_phone", ""))


async def _tool_ogrenci_borc_detay(**kwargs):
    from finans_tools import ogrenci_borc_detay
    return await ogrenci_borc_detay(
        soz_no=int(kwargs.get("soz_no") or 0),
        _caller_phone=kwargs.get("_caller_phone", ""),
    )


async def _tool_geciken_odemeler(**kwargs):
    from finans_tools import geciken_odemeler
    return await geciken_odemeler(
        min_gun=int(kwargs.get("min_gun") or 0),
        limit=int(kwargs.get("limit") or 50),
        _caller_phone=kwargs.get("_caller_phone", ""),
    )


async def _tool_aylik_tahsilat_trend(**kwargs):
    from finans_tools import aylik_tahsilat_trend
    return await aylik_tahsilat_trend(
        ay_sayisi=int(kwargs.get("ay_sayisi") or 12),
        _caller_phone=kwargs.get("_caller_phone", ""),
    )


async def _tool_veli_borc_bildirim_taslak(**kwargs):
    from finans_tools import veli_borc_bildirim_taslak
    return await veli_borc_bildirim_taslak(
        soz_no=int(kwargs.get("soz_no") or 0),
        mesaj_tipi=kwargs.get("mesaj_tipi") or "nazik",
        _caller_phone=kwargs.get("_caller_phone", ""),
    )


async def _tool_finans_audit_rapor(**kwargs):
    from finans_tools import finans_audit_rapor
    return await finans_audit_rapor(
        saat=int(kwargs.get("saat") or 24),
        _caller_phone=kwargs.get("_caller_phone", ""),
    )


async def _tool_sezon_kiyasla(**kwargs):
    from finans_tools import sezon_kiyasla
    return await sezon_kiyasla(_caller_phone=kwargs.get("_caller_phone", ""))


async def _tool_aylik_borc_detay(**kwargs):
    from finans_tools import aylik_borc_detay
    return await aylik_borc_detay(
        ay=kwargs.get("ay", ""),
        _caller_phone=kwargs.get("_caller_phone", ""),
    )


async def _tool_ogrenci_sezon_gecmisi(**kwargs):
    from finans_tools import ogrenci_sezon_gecmisi
    return await ogrenci_sezon_gecmisi(
        soz_no=int(kwargs.get("soz_no") or 0),
        _caller_phone=kwargs.get("_caller_phone", ""),
    )


__all__ = [
    "_tool_finans_ozet", "_tool_ogrenci_borc_detay", "_tool_geciken_odemeler",
    "_tool_aylik_tahsilat_trend", "_tool_veli_borc_bildirim_taslak",
    "_tool_finans_audit_rapor", "_tool_sezon_kiyasla", "_tool_aylik_borc_detay",
    "_tool_ogrenci_sezon_gecmisi",
]
