"""
Fast Response Visuals — A+++ kalite icin yeniden kullanilabilir gorsel primitifler.

Oturum 25.41 (Neo direktifi): "Fast Response cevaplari proje basinda yazildi,
artik render araclarimiz var, gorsel kalitemiz A+++. Eski cevaplari ayni
profesyonel seviyeye cikar."

Kullanim:
    from fast_response_visuals import (
        sep, sep_thick, dot, gauge, sparkline, medal, trend_arrow,
        progress_bar, header, footer_cta, action_block,
    )

Tum cikti WhatsApp formatinda (markdown→WP):
- *bold*  (tek yildiz)
- _italic_ (alt cizgi)
- emoji semantic
- ━━ separator (ASCII safe)
"""
from __future__ import annotations

from typing import Optional, Sequence, Tuple


# ─── SEPARATORS ────────────────────────────────────────────────────────────
SEP_THIN = "━━━━━━━━━━━━━━━━━━━━━━"   # bolum ici
SEP_THICK = "━━━━━━━━━━━━━━━━━━━━━━━━"  # ana bolum
SEP_DASHED = "─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─"  # alt bolum
SEP_DOT = "· · · · · · · · · · · · ·"   # hafif ayraç


def sep(style: str = "thin") -> str:
    """Standart ayraç. style: thin | thick | dashed | dot"""
    return {
        "thin": SEP_THIN,
        "thick": SEP_THICK,
        "dashed": SEP_DASHED,
        "dot": SEP_DOT,
    }.get(style, SEP_THIN)


def sep_thick() -> str:
    return SEP_THICK


# ─── COLOR DOTS (renk kodlu durum belirteci) ───────────────────────────────
def dot(value: float, thresholds: Tuple[float, float] = (0.4, 0.7),
        reverse: bool = False) -> str:
    """Deger -> renkli emoji nokta.

    thresholds: (low, high) — low altı kırmızı, high üstü yeşil
    reverse=True: yüksek deger kötü (örn devamsızlık)

    >>> dot(0.85)  # iyi
    '🟢'
    >>> dot(0.5)   # orta
    '🟡'
    >>> dot(0.2)   # zayıf
    '🔴'
    >>> dot(150, (50, 100), reverse=True)  # devamsızlık 150 → kötü
    '🔴'
    """
    low, high = thresholds
    if reverse:
        if value < low:
            return "🟢"
        elif value < high:
            return "🟡"
        return "🔴"
    if value >= high:
        return "🟢"
    elif value >= low:
        return "🟡"
    return "🔴"


# ─── TREND ARROWS ─────────────────────────────────────────────────────────
def trend_arrow(prev: float, curr: float, threshold: float = 0.5) -> str:
    """İki değer arasında trend yönü.

    >>> trend_arrow(40, 45)
    '📈'
    >>> trend_arrow(45, 40)
    '📉'
    >>> trend_arrow(40, 40.2)
    '➡️'
    """
    diff = curr - prev
    if diff > threshold:
        return "📈"
    elif diff < -threshold:
        return "📉"
    return "➡️"


def trend_label(prev: float, curr: float, unit: str = "net",
                 threshold: float = 0.5) -> str:
    """Trend etiketi: '📈 +3.5 net' veya '📉 -2.1 net' veya '➡️ stabil'

    >>> trend_label(40, 45)
    '📈 +5.0 net'
    """
    diff = curr - prev
    arrow = trend_arrow(prev, curr, threshold)
    if abs(diff) <= threshold:
        return f"{arrow} stabil"
    sign = "+" if diff > 0 else ""
    return f"{arrow} {sign}{diff:.1f} {unit}"


# ─── SPARKLINE (mini grafik) ──────────────────────────────────────────────
_SPARK_BARS = "▁▂▃▄▅▆▇█"


def sparkline(values: Sequence[float], width: int = 8) -> str:
    """Liste degerlerini ASCII sparkline'a çevir.

    >>> sparkline([10, 20, 15, 30, 25, 40])
    '▁▃▂▆▄█'
    """
    if not values:
        return ""
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return ""
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return _SPARK_BARS[3] * len(vals)  # tüm değerler eşit → orta seviye
    span = hi - lo
    bars = []
    for v in vals:
        idx = int(((v - lo) / span) * (len(_SPARK_BARS) - 1))
        bars.append(_SPARK_BARS[idx])
    return "".join(bars)


# ─── PROGRESS BAR ─────────────────────────────────────────────────────────
def progress_bar(value: float, max_val: float = 100, width: int = 10,
                 filled: str = "█", empty: str = "░") -> str:
    """Yatay progress bar.

    >>> progress_bar(45, 100)
    '████░░░░░░'
    """
    if max_val <= 0:
        return empty * width
    pct = max(0.0, min(1.0, value / max_val))
    filled_count = int(pct * width)
    return filled * filled_count + empty * (width - filled_count)


def gauge(value: float, max_val: float = 100, label: str = "") -> str:
    """Progress bar + yüzde + opsiyonel etiket.

    >>> gauge(45, 100, "Tamamlandı")
    '████░░░░░░ 45% Tamamlandı'
    """
    bar = progress_bar(value, max_val)
    pct = int((value / max_val) * 100) if max_val > 0 else 0
    suffix = f" {label}" if label else ""
    return f"{bar} {pct}%{suffix}"


# ─── MEDALS / RANKS ───────────────────────────────────────────────────────
def medal(rank: int) -> str:
    """Sıralamaya göre madalya emoji.

    >>> medal(1)
    '🥇'
    >>> medal(2)
    '🥈'
    >>> medal(3)
    '🥉'
    >>> medal(5)
    '5.'
    """
    if rank == 1:
        return "🥇"
    if rank == 2:
        return "🥈"
    if rank == 3:
        return "🥉"
    return f"*{rank}.*"


# ─── HEADERS / FOOTERS ────────────────────────────────────────────────────
def header(title: str, subtitle: str = "", emoji: str = "") -> str:
    """Standart kart header.

    >>> header("Son Deneme", "Ali Veli", "📊")
    '📊 *Son Deneme*\\n_Ali Veli_\\n━━━━━━━━━━━━━━━━━━━━━━'
    """
    em = f"{emoji} " if emoji else ""
    lines = [f"{em}*{title}*"]
    if subtitle:
        lines.append(f"_{subtitle}_")
    lines.append(SEP_THIN)
    return "\n".join(lines)


def footer_cta(*options: str, prompt: str = "Şimdi ne yapalım?") -> str:
    """Aksiyon önerileri ile çağrı kapatma.

    >>> footer_cta(
    ...     '"zayıf konularım" → öncelikli alanlar',
    ...     '"çalışma planı" → kişisel program',
    ... )
    """
    if not options:
        return ""
    lines = [SEP_THIN, f"💡 *{prompt}*"]
    for opt in options:
        lines.append(f"• {opt}")
    return "\n".join(lines)


def action_block(title: str = "Şimdi ne yapalım?",
                 options: Sequence[Tuple[str, str]] = ()) -> str:
    """Aksiyon bloğu — emoji + kısayol + açıklama.

    options: [(emoji, "kısayol → açıklama"), ...]

    >>> action_block(options=[("📊", '"son deneme" → analiz')])
    """
    if not options:
        return ""
    lines = [SEP_THIN, f"💡 *{title}*"]
    for emoji_, text in options:
        lines.append(f"{emoji_} {text}")
    return "\n".join(lines)


# ─── DATA PRESENTATION HELPERS ────────────────────────────────────────────
def kv_line(label: str, value: str, emoji: str = "") -> str:
    """Anahtar-değer satırı.

    >>> kv_line("Toplam", "45 net", "📊")
    '📊 *Toplam:* 45 net'
    """
    em = f"{emoji} " if emoji else ""
    return f"{em}*{label}:* {value}"


def list_item(rank: int, title: str, subtitle: str = "",
              emoji: str = "") -> str:
    """Sıralı liste maddesi (madalya destekli).

    >>> list_item(1, "Ali Veli", "TYT 95 net", "👨‍🎓")
    """
    rank_str = medal(rank)
    em = f"{emoji} " if emoji else ""
    out = f"{rank_str} {em}*{title}*"
    if subtitle:
        out += f"\n   _{subtitle}_"
    return out


def status_line(emoji: str, label: str, value: str,
                extra: str = "") -> str:
    """Durum satırı: emoji + label + value + opsiyonel açıklama.

    >>> status_line("🟡", "Devamsızlık", "25 saat", "kalan tolerans 15")
    """
    line = f"{emoji} *{label}:* {value}"
    if extra:
        line += f"  _({extra})_"
    return line


# ─── DERS EMOJI MAPPER ────────────────────────────────────────────────────
_DERS_EMOJI = {
    "matematik": "🔢", "mat": "🔢", "geometri": "📐",
    "fizik": "⚡", "fiz": "⚡",
    "kimya": "🧪", "kim": "🧪",
    "biyoloji": "🧬", "biyo": "🧬", "bio": "🧬",
    "turkce": "📖", "türkçe": "📖", "turk": "📖",
    "edebiyat": "📚", "tde": "📚",
    "tarih": "🏛️",
    "cografya": "🌍", "coğrafya": "🌍",
    "felsefe": "💭",
    "din": "🕌", "din kulturu": "🕌",
    "ingilizce": "🌐",
    "fen": "🔬", "sosyal": "🌐",
    "sayisal": "🔬", "say": "🔬",
}


def ders_emoji(ders: str) -> str:
    """Ders adından uygun emoji döndür.

    >>> ders_emoji("Matematik")
    '🔢'
    >>> ders_emoji("Türkçe")
    '📖'
    """
    if not ders:
        return "📘"
    key = ders.lower().strip()
    if key in _DERS_EMOJI:
        return _DERS_EMOJI[key]
    # Partial match
    for k, v in _DERS_EMOJI.items():
        if k in key:
            return v
    return "📘"


# ─── HİTAP HELPERS ────────────────────────────────────────────────────────
def first_name(name: str) -> str:
    """İsmin ilk parçası (hitap için)."""
    if not name:
        return ""
    return name.split()[0]


def hitap(name: str, fallback: str = "") -> str:
    """Bold hitap. Boşsa fallback."""
    fn = first_name(name) or fallback
    return f"*{fn}*" if fn else ""


# ─── TARIH / FORMAT HELPERS ───────────────────────────────────────────────
def fmt_tarih(d) -> str:
    """Tarih -> 'DD.MM.YYYY' formatı."""
    if not d:
        return "?"
    try:
        return d.strftime("%d.%m.%Y")
    except Exception:
        return str(d)


def fmt_net(v) -> str:
    """Net değeri -> '45.5' formatı."""
    if v is None:
        return "—"
    try:
        return f"{float(v):.1f}"
    except Exception:
        return str(v)


# ─── CARD WRAPPER ─────────────────────────────────────────────────────────
def card(*sections: str) -> str:
    """Birden fazla bölümü tek karta birleştir."""
    return "\n".join(s for s in sections if s)


__all__ = [
    "sep", "sep_thick", "SEP_THIN", "SEP_THICK", "SEP_DASHED",
    "dot", "trend_arrow", "trend_label",
    "sparkline", "progress_bar", "gauge",
    "medal", "list_item",
    "header", "footer_cta", "action_block",
    "kv_line", "status_line",
    "ders_emoji",
    "first_name", "hitap",
    "fmt_tarih", "fmt_net",
    "card",
]
