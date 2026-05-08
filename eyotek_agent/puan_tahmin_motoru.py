"""
Puan Tahmin Motoru (25.41 Neo — 7 May konuşma analizi)
======================================================

ÖĞRENCİ TALEBİ: "şu an tahmini puanım ne olacak" — son 30 günde 10 kez sorulmuş.

GİRİŞ verisi:
- student_exam_analysis: ham_puan, yerlesme_puani, ÖSYM 2023-2025 sıralama
- student_exams: son 3 TYT + son AYT
- student_topic_tracker: zayıf konu sayısı + potansiyel net kazanım

ÇIKTI:
  Mevcut tahmini puan aralığı (TYT + AYT)
  Trend (yükseliş/düşüş, son 3 deneme)
  35 gün sonrası tahmini puan (zayıf konuları kapatırsa)
  Yerleşme tahmini (ÖSYM sıralama bandı)

LİSANS: Tahminler indikatif, kesin garanti DEĞIL. Eğitim danışmanlık amaçlı.
"""
from __future__ import annotations
from typing import Optional
from db_pool import db_fetchrow, db_fetchval, db_fetch
import json


# ─── Yardımcılar ─────────────────────────────────────────

def _to_float(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "."))
    except (ValueError, TypeError):
        return None


def _trend_yon(degerler: list[float]) -> tuple[str, float]:
    """[a, b, c] son 3 net → ('yukselis'|'dususte'|'duragan', delta)"""
    if not degerler or len(degerler) < 2:
        return "duragan", 0.0
    delta = degerler[-1] - degerler[0]  # son - ilk (kronolojik sıra)
    if delta > 3:
        return "yukselis", delta
    elif delta < -3:
        return "dususte", delta
    return "duragan", delta


# ─── Ana Fonksiyon ──────────────────────────────────────

async def puan_tahmin(soz_no: int, name: str = "") -> str:
    """Öğrenciye 'şu an tahmini puanım' sorusu için zengin yanıt."""

    # ─── 1. student_exam_analysis (ana profil) ──────────
    profile = await db_fetchrow("""
        SELECT ham_puan, yerlesme_puani, sinav_sayisi, katilan_sinav,
               toplam_soru, toplam_dogru,
               osym_2025_yer, osym_2024_yer, osym_2023_yer,
               ham_puan_ayt, yerlesme_puani_ayt,
               ders_netleri, oncelikli_konular
        FROM student_exam_analysis
        WHERE soz_no::text = $1 LIMIT 1
    """, str(soz_no))

    # ─── 2. Son 3 TYT trendi ────────────────────────────
    tyt_son3 = await db_fetch("""
        SELECT exam_name, exam_date::date d, toplam net
        FROM student_exams
        WHERE soz_no::text = $1 AND COALESCE(exam_type,'TYT') = 'TYT'
          AND toplam IS NOT NULL
        ORDER BY exam_date DESC LIMIT 3
    """, str(soz_no))

    # ─── 3. Son AYT ─────────────────────────────────────
    ayt_son = await db_fetchrow("""
        SELECT exam_name, exam_date::date d, toplam net
        FROM student_exams
        WHERE soz_no::text = $1 AND exam_type = 'AYT'
          AND toplam IS NOT NULL
        ORDER BY exam_date DESC LIMIT 1
    """, str(soz_no))

    # ─── 4. Zayıf konu sayısı + potansiyel ──────────────
    zayif = await db_fetchval("""
        SELECT COUNT(*) FROM student_topic_tracker
        WHERE soz_no::text = $1 AND tamamlandi = FALSE
          AND sinav_hata_yuzdesi < 50 AND LENGTH(konu) > 5
          AND konu NOT LIKE 'Ortalama %'
    """, str(soz_no)) or 0

    first = (name.split()[0] if name else "") or "arkadaşım"

    # Yeterince veri yoksa
    if not profile and not tyt_son3:
        return (
            f"📊 *Puan Tahmini — {first}*\n\n"
            f"Henüz tahmin yapabilecek deneme verisi yok.\n\n"
            f"En az 1-2 deneme katılımından sonra sana _gerçek_ "
            f"tahmin verebilirim — matematiksel olmadan tahmin "
            f"yapamam, **dürüst olmak gerek.**\n\n"
            f"_Önce birkaç deneme yap, sonra puanını çıkartırım._ 💪"
        )

    # ─── BUILD ─────────────────────────────────────────
    lines = [f"🎯 *Puan Tahmini — {first}*\n"]

    # Mevcut puanlar (analysis)
    ham = _to_float(profile.get("ham_puan")) if profile else None
    yer = _to_float(profile.get("yerlesme_puani")) if profile else None
    ham_ayt = _to_float(profile.get("ham_puan_ayt")) if profile else None
    yer_ayt = _to_float(profile.get("yerlesme_puani_ayt")) if profile else None

    if ham or yer:
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("📊 *MEVCUT (TYT) — Eyotek ortalaması*")
        if ham:
            lines.append(f"   Ham puan: *{ham:.1f}*")
        if yer:
            lines.append(f"   Yerleşme: *{yer:.1f}*")
        if ham_ayt or yer_ayt:
            lines.append("\n📊 *MEVCUT (AYT)*")
            if ham_ayt:
                lines.append(f"   Ham: *{ham_ayt:.1f}*")
            if yer_ayt:
                lines.append(f"   Yerleşme: *{yer_ayt:.1f}*")

    # Trend
    if tyt_son3 and len(tyt_son3) >= 2:
        netler = [_to_float(r["net"]) for r in reversed(tyt_son3) if _to_float(r["net"])]
        if len(netler) >= 2:
            yon, delta = _trend_yon(netler)
            emoji = {"yukselis": "📈", "dususte": "📉", "duragan": "➡️"}[yon]
            lines.append(f"\n{emoji} *Son {len(netler)} TYT trendi:*")
            for r in reversed(tyt_son3[:3]):
                n = _to_float(r["net"])
                if n is not None:
                    lines.append(f"   {r['d']} → *{n:.1f}* net")
            if yon == "yukselis":
                lines.append(f"   _Trend: yükseliş (+{delta:.1f} net) — devam et!_")
            elif yon == "dususte":
                lines.append(f"   _Trend: düşüş ({delta:.1f} net) — sebep arayalım_")
            else:
                lines.append(f"   _Trend: durağan — bir sıçrama gerek_")

    # ÖSYM bandı
    if profile and profile.get("osym_2025_yer"):
        yer25 = _to_float(profile.get("osym_2025_yer"))
        yer24 = _to_float(profile.get("osym_2024_yer"))
        yer23 = _to_float(profile.get("osym_2023_yer"))
        if yer25:
            lines.append(f"\n🏆 *ÖSYM gerçek puan tahmini*")
            puanlar = [v for v in (yer25, yer24, yer23) if v]
            if puanlar:
                ort = sum(puanlar) / len(puanlar)
                lines.append(f"   2023-2025 ort: *{ort:.1f}*")
            if yer25:
                lines.append(f"   Son ÖSYM (2025): {yer25:.1f}")

    # Zayıf konu potansiyeli
    if zayif > 0:
        # Ortalama konu netleştirince ~0.4-0.6 net kazanım
        potansiyel = zayif * 0.5
        lines.append(f"\n🎯 *Net Kazanım Potansiyeli*")
        lines.append(f"   Zayıf konu sayısı: *{zayif}*")
        lines.append(f"   Tamamen netleştirirsen: *+{potansiyel:.0f} net* tahmin")
        if ham:
            lines.append(f"   Hedef puan: ~*{ham + potansiyel * 4:.0f}* (ham)")

    # Onceki konular
    if profile and profile.get("oncelikli_konular"):
        try:
            ok = profile["oncelikli_konular"]
            if isinstance(ok, str):
                ok = json.loads(ok)
            # 25.41 (Neo 8 May fix): yapı [{"level":1, "konular":[{konu, yuzde,...}, ...]}, ...]
            # Flatten et — level grouplarından konu'ları çıkar
            flat_konular = []
            if isinstance(ok, list):
                for grup in ok:
                    if isinstance(grup, dict) and "konular" in grup:
                        for k in grup["konular"]:
                            if isinstance(k, dict):
                                konu_str = k.get("konu", "")
                                yuzde = k.get("yuzde", "")
                                if konu_str:
                                    flat_konular.append((konu_str, yuzde))
                    elif isinstance(grup, dict) and "konu" in grup:
                        flat_konular.append((grup["konu"], grup.get("yuzde", "")))
                    elif isinstance(grup, str):
                        flat_konular.append((grup, ""))
            if flat_konular:
                lines.append(f"\n📚 *Öncelikli 3 konu:*")
                for konu, yuzde in flat_konular[:3]:
                    suffix = f" — başarı {yuzde}" if yuzde else ""
                    lines.append(f"   • {str(konu)[:60]}{suffix}")
        except Exception:
            pass

    # 25.41 (Neo 8 May): student_topic_tracker'dan zayıf konu — daha iyi kaynak
    try:
        zayif_top = await db_fetch("""
            SELECT konu, ders FROM student_topic_tracker
            WHERE soz_no::text = $1 AND tamamlandi = FALSE
              AND sinav_hata_yuzdesi < 50 AND LENGTH(konu) > 5
              AND konu NOT LIKE 'Ortalama %'
            ORDER BY sinav_hata_yuzdesi ASC LIMIT 3
        """, str(soz_no))
        if zayif_top and not (profile and profile.get("oncelikli_konular")):
            lines.append(f"\n📚 *En çok hata yaptığın 3 konu:*")
            for r in zayif_top:
                lines.append(f"   • {r['konu'][:50]} ({r['ders']})")
    except Exception:
        pass

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("_Tahminler indikatif. Gerçek puan deneme + ÖSYM gününe bağlı._")
    lines.append(f"_Birlikte plan yapalım mı? *'çalışma planı yap'* yaz._ 💪")

    return "\n".join(lines)


# ─── Test ────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    async def main():
        # Test: birkaç soz_no
        for soz in [163, 230, 137, 287]:
            print(f"\n{'='*60}\nSoz: {soz}\n{'='*60}")
            r = await puan_tahmin(soz, "")
            print(r)
    asyncio.run(main())
