"""
Puan Tahmin Motoru — İNCE WRAPPER (Oturum 25.48 birleştirme)
=============================================================
ESKİDEN: Bu dosya AYRI bir tahmin motoruydu (kendi DB sorguları + kendi format).
puan_tahmin.py ile İKİ AYRI motor vardı (BUG3) — divergence riski: öğrenci
fast-path'ten farklı, Claude path'inden farklı tahmin alabiliyordu.

ŞİMDİ: Tek veri kaynağı = puan_tahmin.tahmin_et(). Bu modül yalnızca
fast_responses'ın çağrı sözleşmesini [puan_tahmin(soz_no, name) -> str] korumak
için ince bir wrapper. Artık core_agent + fast_responses + PDF + bridge HEPSİ
aynı motoru kullanır → divergence YOK.

Çıktı puan_tahmin.format_rapor()'dan gelir:
  TYT/AYT netler · ders-bazlı trend · ÖSYM gerçek puan bandı · net kazanım
  potansiyeli · öncelikli konular · ```chart (trend) + ```radar (ders profili).
"""
from __future__ import annotations


async def puan_tahmin(soz_no, name: str = "") -> str:
    """'şu an tahmini puanım' → tek motordan (tahmin_et) zengin yanıt + render blokları."""
    from puan_tahmin import tahmin_et, format_rapor
    tahmin = await tahmin_et(str(soz_no))
    # tahmin_et adı DB'den çeker; boşsa parametreyi fallback kullan
    if name and not tahmin.get("name"):
        tahmin["name"] = name
    return format_rapor(tahmin)


if __name__ == "__main__":
    import asyncio
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    async def _main():
        for soz in (sys.argv[1:] or ["230"]):
            print(f"\n{'='*60}\nSoz: {soz}\n{'='*60}")
            print(await puan_tahmin(soz, ""))

    asyncio.run(_main())
