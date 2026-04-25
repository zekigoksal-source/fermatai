"""
Sinav Takvimi — Tek Kaynak (Oturum 25.8 fix, Neo karari 25 Nisan)
====================================================================
Onceden 2 farkli yerde hardcoded tarih vardi:
  - study_plan_builder.py: 13 Haziran 2026
  - fast_responses.py:    13 Haziran 2026
  - system_prompts.py (Claude): 20 Haziran 2026

Sonuc: Deren'e plan "49 gun" denildi, Hoca'ya "56 gun" denildi.
Tutarsizlik. KVKK degil ama akademik plan kalitesi icin kritik.

Resmi OSYM 2026 takvimi:
  - TYT: 20 Haziran 2026 (Cumartesi)
  - AYT: 21 Haziran 2026 (Pazar)
  - YDT: 21 Haziran 2026 (Pazar, ogleden sonra)
  - LGS:  7 Haziran 2026 (Pazar)

Bu module TUM kod tarafindan import edilmeli.
"""
from __future__ import annotations
from datetime import date


# ── RESMI TARIHLER (OSYM/MEB) ──
TYT_DATE = date(2026, 6, 20)   # Cumartesi
AYT_DATE = date(2026, 6, 21)   # Pazar
YDT_DATE = date(2026, 6, 21)   # Pazar
LGS_DATE = date(2026, 6, 7)    # Pazar


def days_until_tyt(today: date | None = None) -> int:
    """Bugunden TYT'ye kalan gun (negatif olabilir, sinav gectiyse)."""
    return (TYT_DATE - (today or date.today())).days


def days_until_ayt(today: date | None = None) -> int:
    return (AYT_DATE - (today or date.today())).days


def days_until_lgs(today: date | None = None) -> int:
    return (LGS_DATE - (today or date.today())).days


def yks_summary_line(today: date | None = None) -> str:
    """Tek satir ozet — system prompt veya raporlar icin."""
    t = today or date.today()
    return (
        f"YKS 2026 — TYT {TYT_DATE.strftime('%d %B %Y')} ({days_until_tyt(t)} gun), "
        f"AYT {AYT_DATE.strftime('%d %B %Y')} ({days_until_ayt(t)} gun)"
    )


if __name__ == "__main__":
    print(yks_summary_line())
    print(f"LGS: {LGS_DATE} ({days_until_lgs()} gun)")
