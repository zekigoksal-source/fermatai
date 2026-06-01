"""
digital_twin.py — Öğrenci Dijital İkizi (Oturum 25.52, Neo dikey-AI #3 sentez)
=============================================================================
Her öğrencinin CANLI birleşik modeli — tek nesnede:
  · AKADEMİK: predict_student (YKS skor tahmini + trend + bottleneck)
  · USTALIK:  knowledge_state (BKT-kalibre ders ustalığı + FSRS tekrar)
  · RÖNTGEN:  exam_xray (son deneme delta)
  · DUYGU:    student_insights (son sentiment sinyalleri)
  · DEVAMSIZLIK: devamsizlik_sayisi
  · RİSK:     yukarıdakilerden hesaplanan KOMPOZIT risk (decline+devamsizlik+duygu)

Bu, 9 aylık longitudinal proprietary datayı TEK pedagojik modele çevirir — genel
chatbot'ların yapamadığı (geçmişleri yok). OECD 2026: amaç-yapımı eğitim AI > genel araç.

⚠️ OUTREACH YOK / SALT-OKUNUR: Bu modül HİÇBİR mesaj göndermez — sadece veri toplar +
analiz üretir. On-demand (admin/rehber sorgusu, öğrenci kendi özeti). Risk skoru
hesaplanır ama OTOMATİK alarm GÖNDERMEZ (delivery alert_system'de, ALERTS_ACTIVE=False).
YKS'ye 20 gün kala (Neo direktif): sıfır otomatik öğrenci mesajı.

ROL FARKI (Dashboard Vizyonu kuralı): öğrenciye devamsızlık + risk skoru GÖSTERİLMEZ
(motive edici özet). admin/rehber/mudur tam görür.

Kullanım:
  from digital_twin import get_digital_twin, format_digital_twin
  twin = await get_digital_twin(soz_no)
  msg = format_digital_twin(twin, name, viewer_role="rehber")

Claude tool: get_digital_twin(soz_no) — "öğrenci 360 profili", "tam durumu", "risk".
"""
from __future__ import annotations

import asyncio
from loguru import logger


# ── Kompozit risk (read-only — alarm GÖNDERMEZ) ───────────────────────────────
def _compute_risk(akademik: dict, devamsizlik_saat: float, neg_sinyal: int,
                  exam_delta) -> dict:
    """Çoklu sinyalden kompozit risk. Sadece HESAP — outreach yok.
    Sinyaller: net düşüş + devamsızlık + negatif duygu + düşük güven."""
    skor = 0
    nedenler = []

    # 1) Net düşüş (son deneme delta veya tahmin trendi)
    if exam_delta is not None and exam_delta <= -8:
        skor += 35
        nedenler.append(f"son denemede {exam_delta} net düşüş")
    elif exam_delta is not None and exam_delta <= -4:
        skor += 18
        nedenler.append(f"son denemede {exam_delta} net düşüş")

    # 2) Devamsızlık
    if devamsizlik_saat >= 200:
        skor += 30
        nedenler.append(f"{int(devamsizlik_saat)} saat devamsızlık (kritik)")
    elif devamsizlik_saat >= 100:
        skor += 15
        nedenler.append(f"{int(devamsizlik_saat)} saat devamsızlık")

    # 3) Negatif duygu sinyali (son 7 gün)
    if neg_sinyal >= 3:
        skor += 25
        nedenler.append(f"{neg_sinyal} negatif duygu sinyali (7 gün)")
    elif neg_sinyal >= 1:
        skor += 10
        nedenler.append(f"{neg_sinyal} negatif duygu sinyali")

    # 4) Düşük tahmin güveni (yetersiz veri / dalgalı)
    conf = (akademik or {}).get("confidence")
    if conf is not None and conf < 0.4:
        skor += 8
        nedenler.append("düşük tahmin güveni (dalgalı performans)")

    skor = min(100, skor)
    if skor >= 60:
        seviye, emoji = "kritik", "🔴"
    elif skor >= 35:
        seviye, emoji = "yüksek", "🟠"
    elif skor >= 15:
        seviye, emoji = "orta", "🟡"
    else:
        seviye, emoji = "düşük", "🟢"
    return {"seviye": seviye, "emoji": emoji, "skor": skor, "nedenler": nedenler}


async def _recent_negative_signals(soz_no: int) -> int:
    """student_insights — son 7 günde negatif/kriz duygu sinyali sayısı."""
    try:
        from db_pool import db_fetchval
        n = await db_fetchval(
            """SELECT COUNT(*) FROM student_insights
               WHERE soz_no = $1
                 AND created_at > NOW() - INTERVAL '7 days'
                 AND (insight_type ILIKE '%stres%' OR insight_type ILIKE '%kayg%'
                      OR insight_type ILIKE '%negatif%' OR insight_type ILIKE '%kriz%'
                      OR insight_type ILIKE '%motivasyon_dusuk%' OR content ILIKE '%stresli%')""",
            int(soz_no))
        return int(n or 0)
    except Exception as e:
        logger.debug(f"[digital_twin] sentiment sorgu hatası: {e}")
        return 0


async def _devamsizlik(soz_no: int) -> float:
    try:
        from db_pool import db_fetchval
        v = await db_fetchval(
            "SELECT toplam_saat FROM devamsizlik_sayisi WHERE soz_no = $1", int(soz_no))
        return float(v or 0)
    except Exception as e:
        logger.debug(f"[digital_twin] devamsizlik sorgu hatası: {e}")
        return 0.0


async def get_digital_twin(soz_no: int) -> dict:
    """Öğrencinin birleşik dijital ikizi (salt-okunur, outreach yok)."""
    soz_no = int(soz_no)

    # Tüm kaynaklar paralel — defensive (biri patlasa diğerleri gelir)
    async def _safe(coro, default):
        try:
            return await coro
        except Exception as e:
            logger.debug(f"[digital_twin] kaynak hatası: {e}")
            return default

    from predictive_model import predict_student
    from knowledge_state import get_knowledge_state
    from exam_xray import analyze_latest_exam

    akademik, ustalik, rontgen, neg, devam = await asyncio.gather(
        _safe(predict_student(soz_no), {}),
        _safe(get_knowledge_state(soz_no), {}),
        _safe(analyze_latest_exam(soz_no), {}),
        _safe(_recent_negative_signals(soz_no), 0),
        _safe(_devamsizlik(soz_no), 0.0),
    )

    exam_delta = rontgen.get("toplam_delta") if isinstance(rontgen, dict) else None
    risk = _compute_risk(akademik if isinstance(akademik, dict) else {},
                         devam, neg, exam_delta)

    # İsim
    isim = ""
    try:
        from db_pool import db_fetchval
        isim = await db_fetchval(
            "SELECT full_name FROM students WHERE soz_no::int = $1", soz_no) or ""
    except Exception:
        pass

    return {
        "soz_no": soz_no, "isim": isim,
        "akademik": akademik if isinstance(akademik, dict) else {},
        "ustalik": {
            "ders_ozet": (ustalik or {}).get("ders_ozet", {}),
            "tekrar_due": len((ustalik or {}).get("review_due", [])),
        },
        "son_deneme_rontgen": {
            "isim": (rontgen or {}).get("son_deneme", {}).get("isim") if rontgen.get("has_data") else None,
            "toplam": (rontgen or {}).get("son_deneme", {}).get("toplam") if rontgen.get("has_data") else None,
            "delta": exam_delta,
            "en_iyi": (rontgen or {}).get("en_iyi"),
            "en_kotu": (rontgen or {}).get("en_kotu"),
        } if rontgen.get("has_data") else None,
        "duygu": {"negatif_sinyal_7g": neg},
        "devamsizlik_saat": devam,
        "risk": risk,
        "outreach": False,  # bu modül asla mesaj göndermez — açık işaret
    }


# ── Rol-bilinçli format (Dashboard Vizyonu: öğrenciye devamsızlık/risk YOK) ────
def format_digital_twin(twin: dict, name: str = "", viewer_role: str = "rehber") -> str:
    first = ((twin.get("isim") or name or "").split()[0]) or "öğrenci"
    ak = twin.get("akademik", {})
    us = twin.get("ustalik", {})
    is_staff = viewer_role in ("admin", "mudur", "rehber", "ogretmen", "yonetim")

    lines = [f"🧬 *{first} — Dijital İkiz* _(360° model)_", ""]

    # Akademik / YKS tahmini
    if ak and not ak.get("error"):
        tyt = ak.get("predicted_tyt")
        yer = ak.get("predicted_yerlesme_puani")
        conf = ak.get("confidence")
        if tyt is not None:
            lines.append(f"🎯 *YKS Tahmini:* TYT ~{tyt} net"
                         + (f" · Yerleşme ~{yer:.0f}" if yer else "")
                         + (f" _(güven %{conf*100:.0f})_" if conf is not None else ""))
    elif ak.get("error") == "no_exam_data":
        lines.append("🎯 _Henüz tahmin için yeterli deneme yok._")

    # Ders ustalığı (en zayıf 3)
    dz = us.get("ders_ozet", {})
    if dz:
        zayif = sorted(dz.items(), key=lambda x: x[1].get("ortalama_ustalik", 100))[:3]
        if zayif:
            lines.append("\n*📚 Ustalık (en zayıf)*")
            for ders, e in zayif:
                tr = ""
                if "trend" in e:
                    tr = f" {e['trend']['ok']}"
                lines.append(f"{e['emoji']} {ders}: %{e['ortalama_ustalik']}{tr}")
    if us.get("tekrar_due"):
        lines.append(f"\n⏰ FSRS: *{us['tekrar_due']}* konu tekrar zamanı geldi")

    # Son deneme röntgeni
    sr = twin.get("son_deneme_rontgen")
    if sr and sr.get("toplam") is not None:
        d = sr.get("delta")
        dtxt = f" ({'📈+' if (d or 0) > 0 else '📉'}{d})" if d else ""
        lines.append(f"\n🩻 *Son deneme:* {sr['toplam']} net{dtxt}")

    # RİSK + DEVAMSIZLIK — SADECE personel (öğrenciye gösterilmez)
    if is_staff:
        r = twin.get("risk", {})
        lines.append(f"\n{r.get('emoji','')} *Risk:* {r.get('seviye','?')} (skor {r.get('skor',0)})")
        if r.get("nedenler"):
            for n in r["nedenler"][:4]:
                lines.append(f"   • {n}")
        dv = twin.get("devamsizlik_saat", 0)
        if dv:
            lines.append(f"📅 Devamsızlık: {int(dv)} saat")
    else:
        # Öğrenci görünümü — motive edici, risk/devamsızlık YOK
        lines.append("\n_Bilgi haritan ve tekrar takvimin hazır — birlikte çalışalım!_ 🎯")

    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    async def _main():
        for soz in (sys.argv[1:] or ["167"]):
            print(f"\n{'='*60}\nSoz: {soz}\n{'='*60}")
            tw = await get_digital_twin(int(soz))
            print("--- REHBER görünümü ---")
            print(format_digital_twin(tw, "", "rehber"))
            print("\n--- ÖĞRENCİ görünümü (risk/devamsızlık YOK) ---")
            print(format_digital_twin(tw, "", "ogrenci"))

    asyncio.run(_main())
