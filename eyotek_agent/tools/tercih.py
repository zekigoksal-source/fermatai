"""
Tercih Robotu Tool Wrapper'ları (Oturum 23)
=============================================
YKS sonrası tercih danışmanı modu — iş mantığı `tercih_robotu.py` modülünde.
Bu modül sadece parametre adaptasyonu + tool dispatcher bağlantısı.

Dönem bayrağı: fermat.sistem_ayar.TERCIH_DONEMI_ACTIVE
Admin komutu: "tercih modu ac" / "tercih modu kapa"
"""
from __future__ import annotations


async def _tool_tercih_profili_kaydet(**kwargs):
    from tercih_robotu import tercih_profili_kaydet
    # soz_no opsiyonel — caller_phone'dan çözülebilir
    return await tercih_profili_kaydet(**kwargs)


async def _tool_tercih_profili_getir(**kwargs):
    from tercih_robotu import tercih_profili_getir
    return await tercih_profili_getir(int(kwargs.get("soz_no") or 0))


async def _tool_tercih_listesi_uret(**kwargs):
    from tercih_robotu import tercih_listesi_uret
    return await tercih_listesi_uret(
        int(kwargs.get("soz_no") or 0),
        max_satir=int(kwargs.get("max_satir") or 24),
    )


async def _tool_bolum_karsilastir(**kwargs):
    from tercih_robotu import bolum_karsilastir
    bl = kwargs.get("bolum_listesi") or []
    pt = kwargs.get("puan_turu") or "SAY"
    return await bolum_karsilastir(bl, puan_turu=pt)


async def _tool_tercih_donemi_durum(**kwargs):
    from tercih_robotu import tercih_donemi_durum
    return await tercih_donemi_durum()


__all__ = [
    "_tool_tercih_profili_kaydet", "_tool_tercih_profili_getir",
    "_tool_tercih_listesi_uret", "_tool_bolum_karsilastir",
    "_tool_tercih_donemi_durum",
]
