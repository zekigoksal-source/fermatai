"""
knowledge_state.py — Bilimsel Öğrenci Modelleme (Oturum 25.51, Neo dikey-AI vizyonu)
====================================================================================
NEDEN: Çalışma planı bugüne kadar "spekülatif"ti — zayıf konuyu hata%'sinden seçip
generic öneri veriyordu. Bu modül onu KANITLANMIŞ bilişsel algoritmalara bağlar:

  1. KONU USTALIĞI (BKT-esinli kalibrasyon): student_topic_tracker.sinav_basari_yuzdesi
     → slip/guess düzeltmeli ustalık + bant (Bloom mastery-learning: yüksek eşik=%85).
  2. DERS TRENDİ (gerçek zaman serisi): student_exams ders netleri zaman içinde →
     yön (yükseliyor/düşüyor/sabit) + slope. Tek veri kaynağımız gerçekten temporal.
  3. FSRS TEKRAR ZAMANLAMASI (py-fsrs v6, $0 yerel): her konu için "tam unutmadan
     önce tekrar et" tarihi. desired_retention=0.90 (yüksek mastery eşiği — Bloom
     2-sigma'nın gerçek kaynağı algoritma değil, %90 eşiği [VanLehn 2011]).

Moat: Bu, 9 aylık longitudinal proprietary datayı bilimsel öğrenci modeline çevirir —
genel chatbot'ların yapamadığı (geçmişleri yok). Kanıt: Ghana Rori RCT d=0.36.

Kullanım:
  from knowledge_state import get_knowledge_state, format_knowledge_state
  state = await get_knowledge_state(soz_no)
  msg = format_knowledge_state(state, name)

Claude tool: get_knowledge_state(soz_no) — study_plan + öğrenci sorularında.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from loguru import logger

# FSRS — yerel, $0, pure-python (v6.3.1). desired_retention=0.90 yüksek eşik.
try:
    from fsrs import Scheduler, Card, Rating
    _FSRS_OK = True
except Exception as _fe:  # pragma: no cover
    _FSRS_OK = False
    logger.warning(f"[knowledge_state] fsrs import edilemedi ({_fe}) — review schedule devre dışı")


# ── Ustalık bantları (Bloom mastery-learning: %85 ustalık eşiği) ──────────────
def _mastery_band(basari_pct: float) -> tuple[str, str]:
    """(bant, emoji) — başarı%'sinden ustalık seviyesi."""
    if basari_pct >= 85:
        return "Usta", "🟢"
    if basari_pct >= 65:
        return "İyi", "🟢"
    if basari_pct >= 45:
        return "Gelişmekte", "🟡"
    if basari_pct >= 25:
        return "Zayıf", "🟠"
    return "Kritik", "🔴"


def _rating_from_success(basari_pct: float):
    """Başarı% → FSRS Rating. Mastery yüksekse uzun aralık, düşükse acil tekrar."""
    if basari_pct >= 85:
        return Rating.Easy
    if basari_pct >= 65:
        return Rating.Good
    if basari_pct >= 45:
        return Rating.Hard
    return Rating.Again


# ── BKT-esinli ustalık kalibrasyonu ───────────────────────────────────────────
# Ham başarı% slip (bildiği halde yanlış) + guess (bilmediği halde doğru) içerir.
# Klasik BKT slip=0.1, guess=0.2 ile gerçek P(mastery) ham orandan biraz farklıdır.
# Sade kalibrasyon: P(known) = (obs - guess) / (1 - slip - guess), [0,1]'e kırp.
_BKT_SLIP, _BKT_GUESS = 0.10, 0.20


def _calibrated_mastery(basari_pct: float) -> float:
    """Ham başarı% → slip/guess düzeltmeli ustalık% (BKT mantığı, 0-100)."""
    obs = max(0.0, min(1.0, basari_pct / 100.0))
    denom = 1.0 - _BKT_SLIP - _BKT_GUESS
    if denom <= 0:
        return round(basari_pct, 1)
    p = (obs - _BKT_GUESS) / denom
    return round(max(0.0, min(1.0, p)) * 100, 1)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _anchor_date(calisti, onerilen) -> datetime:
    """Konunun son 'review' tarihi — çalışıldı > önerilen > 30 gün önce (varsayılan)."""
    for d in (calisti, onerilen):
        if d:
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return d
    return _now() - timedelta(days=30)


# ── FSRS scheduler (öğrenme-adımları kapalı → uzun vade gün-aralığı) ──────────
def _make_scheduler():
    """learning_steps boş → ilk review direkt çok-günlük aralık verir (dakika değil)."""
    if not _FSRS_OK:
        return None
    try:
        return Scheduler(desired_retention=0.90, learning_steps=(), relearning_steps=())
    except Exception:
        # API farklıysa default scheduler (öğrenme adımlı) — yine de çalışır
        try:
            return Scheduler()
        except Exception as e:
            logger.warning(f"[knowledge_state] Scheduler kurulamadı: {e}")
            return None


def _fsrs_due(basari_pct: float, anchor: datetime) -> datetime | None:
    """Konu için FSRS sonraki tekrar tarihi. anchor = son çalışma/test tarihi."""
    sched = _make_scheduler()
    if sched is None:
        return None
    try:
        card = Card()
        card, _ = sched.review_card(card, _rating_from_success(basari_pct),
                                    review_datetime=anchor)
        due = card.due
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        return due
    except Exception as e:
        logger.debug(f"[knowledge_state] fsrs hesap hatası: {e}")
        return None


# ── Ders trendi (gerçek zaman serisi — student_exams) ─────────────────────────
_DERS_COLS = ["turkce", "matematik", "geometri", "fizik", "kimya", "biyoloji",
              "tarih", "cografya", "felsefe", "din_kulturu"]


async def compute_ders_trend(soz_no: int) -> dict:
    """Her ders için son denemelerden trend: yön + slope + son değer."""
    from db_pool import db_fetch
    rows = await db_fetch(
        f"""SELECT exam_date, {', '.join(_DERS_COLS)}
            FROM student_exams
            WHERE soz_no = $1 AND exam_date IS NOT NULL
            ORDER BY exam_date""",
        int(soz_no))
    if not rows:
        return {}
    # Aynı tarih duplikasyonunu temizle (veri kalite: 3x tekrar gözlendi)
    seen, clean = set(), []
    for r in rows:
        if r["exam_date"] in seen:
            continue
        seen.add(r["exam_date"])
        clean.append(r)
    out = {}
    for ders in _DERS_COLS:
        vals = [(r["exam_date"], float(r[ders])) for r in clean if r[ders] is not None]
        # Son 5 denemeyi al (anlamlı trend), en az 2 gerek
        vals = vals[-5:]
        if len(vals) < 2:
            continue
        nets = [v for _, v in vals]
        delta = round(nets[-1] - nets[0], 2)
        if delta >= 1.5:
            yon, ok = "yükseliyor", "📈"
        elif delta <= -1.5:
            yon, ok = "düşüyor", "📉"
        else:
            yon, ok = "sabit", "➡️"
        out[ders] = {
            "son_net": round(nets[-1], 2),
            "ilk_net": round(nets[0], 2),
            "delta": delta,
            "yon": yon, "ok": ok,
            "deneme_sayisi": len(nets),
            "seri": nets,
        }
    return out


# ── Ana fonksiyon: birleşik bilgi durumu ──────────────────────────────────────
async def get_knowledge_state(soz_no: int) -> dict:
    """Öğrencinin bilimsel modeli: konu ustalığı + ders trendi + FSRS tekrar takvimi."""
    from db_pool import db_fetch
    soz_no = int(soz_no)

    topics = await db_fetch(
        """SELECT ders, konu, sinav_basari_yuzdesi, sinav_hata_yuzdesi,
                  calisti_tarih, onerilen_tarih, tamamlandi, sinav_turu
           FROM student_topic_tracker
           WHERE soz_no = $1
             AND COALESCE(status,'') != 'metadata'
             AND konu NOT LIKE 'Ortalama %'
           ORDER BY sinav_basari_yuzdesi ASC NULLS LAST""",
        soz_no)

    now = _now()
    konu_list = []
    for t in topics:
        basari = t["sinav_basari_yuzdesi"]
        if basari is None:
            # hata%'den türet (geriye uyum)
            hata = t["sinav_hata_yuzdesi"]
            basari = (100.0 - float(hata)) if hata is not None else None
        if basari is None:
            continue
        basari = float(basari)
        mastery = _calibrated_mastery(basari)
        band, emoji = _mastery_band(basari)
        anchor = _anchor_date(t["calisti_tarih"], t["onerilen_tarih"])
        due = _fsrs_due(basari, anchor)
        days_until = int((due - now).total_seconds() // 86400) if due else None
        konu_list.append({
            "ders": t["ders"], "konu": t["konu"],
            "basari": round(basari, 1), "mastery": mastery,
            "band": band, "emoji": emoji,
            "tamamlandi": t["tamamlandi"],
            "due": due.isoformat() if due else None,
            "days_until_due": days_until,
            "overdue": (days_until is not None and days_until <= 0),
        })

    trend = await compute_ders_trend(soz_no)

    # Ders bazlı ortalama ustalık (konu mastery'lerinden)
    ders_mastery = {}
    for k in konu_list:
        ders_mastery.setdefault(k["ders"], []).append(k["mastery"])
    ders_ozet = {}
    for ders, ms in ders_mastery.items():
        avg = round(sum(ms) / len(ms), 1)
        band, emoji = _mastery_band(avg)
        e = {"ortalama_ustalik": avg, "band": band, "emoji": emoji, "konu_sayisi": len(ms)}
        if ders.lower() in trend:
            e["trend"] = trend[ders.lower()]
        elif ders in trend:
            e["trend"] = trend[ders]
        ders_ozet[ders] = e

    # FSRS: bugün/yakında tekrar edilecekler (overdue önce)
    review_due = sorted(
        [k for k in konu_list if k["days_until_due"] is not None and k["days_until_due"] <= 3
         and not k["tamamlandi"]],
        key=lambda x: x["days_until_due"])
    weak = [k for k in konu_list if k["basari"] < 50 and not k["tamamlandi"]][:10]

    return {
        "soz_no": soz_no,
        "konu_sayisi": len(konu_list),
        "ders_ozet": ders_ozet,
        "review_due": review_due[:12],
        "weak_topics": weak,
        "all_topics": konu_list,
        "fsrs_active": _FSRS_OK,
        "computed_at": now.isoformat(),
    }


# ── WhatsApp formatı (zengin görsel) ──────────────────────────────────────────
def format_knowledge_state(state: dict, name: str = "") -> str:
    first = (name.split()[0] if name else "") or "öğrenci"
    if not state or state.get("konu_sayisi", 0) == 0:
        return (f"📊 *{first}* için henüz konu bazlı veri birikmemiş.\n\n"
                "Denemelere katıldıkça bilgi haritan otomatik oluşacak. 🎯")
    lines = [f"🧠 *{first} — Bilgi Haritan* _(bilimsel model)_", ""]

    # Ders ustalığı + trend
    lines.append("*📚 Ders Ustalığı*")
    for ders, e in sorted(state["ders_ozet"].items(),
                          key=lambda x: x[1]["ortalama_ustalik"]):
        tr = ""
        if "trend" in e:
            tr = f"  {e['trend']['ok']} {e['trend']['yon']} ({e['trend']['son_net']} net)"
        lines.append(f"{e['emoji']} *{ders}*: %{e['ortalama_ustalik']} ustalık ({e['band']}){tr}")
    lines.append("")

    # FSRS tekrar takvimi
    if state.get("review_due"):
        lines.append("*⏰ Bugün/Yakında Tekrar Et* _(unutma eğrisi)_")
        for k in state["review_due"][:6]:
            ne = "🔴 BUGÜN" if k["overdue"] else f"{k['days_until_due']} gün içinde"
            lines.append(f"  • {k['ders']} — {k['konu'][:32]} ({ne})")
        lines.append("")

    # En zayıf konular
    if state.get("weak_topics"):
        lines.append("*🎯 Öncelikli Çalışma*")
        for k in state["weak_topics"][:5]:
            lines.append(f"{k['emoji']} {k['ders']} — {k['konu'][:32]} (%{k['basari']})")

    if not state.get("fsrs_active"):
        lines.append("\n_(Tekrar takvimi geçici devre dışı)_")
    lines.append("\n_Bu harita her denemenle güncellenir — bilimsel tekrar algoritması (FSRS) ile._")
    return "\n".join(lines)


if __name__ == "__main__":
    import asyncio
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    async def _main():
        for soz in (sys.argv[1:] or ["167"]):
            print(f"\n{'='*64}\nSoz: {soz}\n{'='*64}")
            st = await get_knowledge_state(int(soz))
            print(format_knowledge_state(st, ""))
            print(f"\n[meta] konu={st['konu_sayisi']} due={len(st['review_due'])} "
                  f"weak={len(st['weak_topics'])} fsrs={st['fsrs_active']}")

    asyncio.run(_main())
