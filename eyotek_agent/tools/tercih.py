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


# 25.40k (Neo direktif) — sezon-bagimsiz YOK Atlas wrapper'lari
async def _tool_universite_taban_sorgu(**kwargs):
    from tercih_robotu import universite_taban_sorgu
    return await universite_taban_sorgu(
        sorgu=kwargs.get("sorgu") or "",
        puan_turu=kwargs.get("puan_turu") or "SAY",
        yil=kwargs.get("yil"),
        limit=int(kwargs.get("limit") or 10),
    )


async def _tool_siralama_ile_bolumler(**kwargs):
    from tercih_robotu import siralama_ile_bolumler
    return await siralama_ile_bolumler(
        siralama=int(kwargs.get("siralama") or 0),
        puan_turu=kwargs.get("puan_turu") or "SAY",
        sehir=kwargs.get("sehir"),
        bolum_filter=kwargs.get("bolum_filter"),
        yil=kwargs.get("yil"),
        limit=int(kwargs.get("limit") or 25),
    )


# 25.46+ (Neo 17 May, Duygu mudur vakasi): bir programin 4 yilini tek cagri ile
async def _tool_universite_taban_trend(**kwargs):
    from tercih_robotu import universite_taban_trend
    return await universite_taban_trend(
        sorgu=kwargs.get("sorgu") or "",
        puan_turu=kwargs.get("puan_turu") or "SAY",
    )


__all__ = [
    "_tool_tercih_profili_kaydet", "_tool_tercih_profili_getir",
    "_tool_tercih_listesi_uret", "_tool_bolum_karsilastir",
    "_tool_tercih_donemi_durum",
    "_tool_universite_taban_sorgu", "_tool_siralama_ile_bolumler",
    "_tool_universite_taban_trend",
]
