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
from typing import Optional


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


# ─── 25.44: Aktif Sezon Helper (Neo direktif 12 May 14:25) ─────────────────
# Hardcoded '2025.26' başka yerlerde de vardı. Tek doğruluk noktası burada.
# Eyotek format: "2025.26" (Eylul-Agustos akademik yıl)

def aktif_sezon(today: Optional[date] = None) -> str:
    """Şu anda aktif Fermat akademik sezonu — '2025.26' formatında.

    Kural (Türkiye akademik takvim): Eylül-Ağustos.
      - Eylül-Aralık ay X yılı → sezon "X.X+1"
      - Ocak-Ağustos ay X yılı → sezon "X-1.X"

    Örnek: 12 May 2026 → '2025.26' (henüz sezon sonu, Eylül 2026'ya kadar)
           1 Eyl 2026 → '2026.27' (yeni sezon başlangıcı)
    """
    t = today or date.today()
    if t.month >= 9:  # Eylül-Aralık
        return f"{t.year}.{(t.year + 1) % 100:02d}"
    else:  # Ocak-Ağustos
        return f"{t.year - 1}.{t.year % 100:02d}"


def aktif_sezon_kod(today: Optional[date] = None) -> str:
    """Eyotek navbar PostBack için 5-haneli kod: '22526'.

    aktif_sezon('2025.26') → '22526' (yıl 25 + yıl 26)
    """
    s = aktif_sezon(today)
    if "." in s:
        y1, y2 = s.split(".")
        # y1='2025' → '25'; y2='26' → '26'
        return f"2{y1[-2:]}{y2[-2:]}"
    return s


def onceki_sezon(today: Optional[date] = None) -> str:
    """Bir önceki sezon — kıyaslama için."""
    t = today or date.today()
    if t.month >= 9:
        return f"{t.year - 1}.{t.year % 100:02d}"
    else:
        return f"{t.year - 2}.{(t.year - 1) % 100:02d}"


def gelecek_sezon(today: Optional[date] = None) -> str:
    """Bir sonraki sezon — yaz dönemi tercih/kayıt sürecinde."""
    t = today or date.today()
    if t.month >= 9:
        return f"{t.year + 1}.{(t.year + 2) % 100:02d}"
    else:
        return f"{t.year}.{(t.year + 1) % 100:02d}"
