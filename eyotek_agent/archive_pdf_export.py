"""
Arşiv PDF Export v2 — (Oturum 23 — A3 rewrite, 23 Nisan)
==========================================================
Kullanıcı arşivdeki kayıtlarını kaliteli PDF olarak indirir.

v1 sorunları (çözüldü):
  1. Türkçe karakterler ■ görünüyordu → DejaVuSans TTF font kaydı
  2. Chart'lar render edilmiyordu → matplotlib ile PNG çizip Image flowable olarak ekle
  3. Tablolar parçalanıyordu → reportlab Table objesi + TableStyle
  4. data-chart regex bozuk (attribute içinde > varsa) → BeautifulSoup HTML parse
  5. Emoji kare görünüyordu → anlamsal metne map (📊→[Grafik], 🎯→[Hedef], …)
  6. İçerik truncation → BeautifulSoup ile iteratif blok yürüyüşü (regex yerine)
  7. Paragraph try/except pass sessiz kayıp → escape katmanı güvenli

Teknoloji: reportlab + matplotlib + BeautifulSoup4
Font: DejaVuSans (matplotlib içindeki TTF dosyası, Türkçe Unicode destekli)
"""
from __future__ import annotations
import io
import json
import html as htmlmod
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    from loguru import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)


# ─── Font registration (module-level, idempotent) ───────────────────────────
_FONT_REGISTERED = False
_FONT_REGULAR = "DejaVu"
_FONT_BOLD = "DejaVu-Bold"
_FONT_ITALIC = "DejaVu-Italic"
_FONT_BOLDITALIC = "DejaVu-BoldItalic"


def _register_fonts() -> None:
    """DejaVuSans TTF ailesini reportlab'e kaydet (Türkçe karakter için)."""
    global _FONT_REGISTERED, _FONT_REGULAR, _FONT_BOLD, _FONT_ITALIC, _FONT_BOLDITALIC
    if _FONT_REGISTERED:
        return

    import matplotlib
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfbase.pdfmetrics import registerFontFamily

    mpl_fonts = Path(matplotlib.__file__).parent / "mpl-data" / "fonts" / "ttf"
    try:
        pdfmetrics.registerFont(TTFont(_FONT_REGULAR, str(mpl_fonts / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont(_FONT_BOLD, str(mpl_fonts / "DejaVuSans-Bold.ttf")))
        pdfmetrics.registerFont(TTFont(_FONT_ITALIC, str(mpl_fonts / "DejaVuSans-Oblique.ttf")))
        pdfmetrics.registerFont(TTFont(_FONT_BOLDITALIC, str(mpl_fonts / "DejaVuSans-BoldOblique.ttf")))
        registerFontFamily(
            _FONT_REGULAR,
            normal=_FONT_REGULAR,
            bold=_FONT_BOLD,
            italic=_FONT_ITALIC,
            boldItalic=_FONT_BOLDITALIC,
        )
        _FONT_REGISTERED = True
        logger.debug("PDF: DejaVuSans TTF ailesi kaydedildi")
    except Exception as e:
        logger.warning(f"PDF: DejaVuSans kayıt hatası: {e} — Helvetica fallback (Türkçe bozulabilir)")
        _FONT_REGULAR = "Helvetica"
        _FONT_BOLD = "Helvetica-Bold"
        _FONT_ITALIC = "Helvetica-Oblique"
        _FONT_BOLDITALIC = "Helvetica-BoldOblique"
        # Helvetica ailesi zaten reportlab'de kayıtlı, registerFontFamily gerekmiyor
        _FONT_REGISTERED = True


# ─── Emoji → anlamsal metin (DejaVu color emoji render edemez) ──────────────
# Prensip: dekoratif emoji'ler → STRIP (başlıklara "[Grafik]" gibi etiket koymak çirkin).
# Anlamlı semboller → DejaVu mono eşdeğeri (✓ ✗ ● ★ ⚠).
_EMOJI_MAP = {
    # Dekoratif — tamamen strip
    "📊": "", "📈": "", "📉": "", "🎯": "", "💡": "", "📝": "",
    "🔥": "", "🚀": "", "🧠": "", "📚": "", "⚡": "", "✨": "",
    "⏰": "", "🔔": "", "💰": "", "🎓": "", "💼": "",
    "📂": "", "📅": "", "🏷": "", "📌": "",
    "😊": "", "😔": "", "👍": "", "⏳": "", "📖": "",
    "💪": "", "✏️": "", "✏": "", "🏆": "",
    "👨‍🏫": "", "👩‍🏫": "", "🧑‍🎓": "", "👨‍🎓": "", "👩‍🎓": "",
    # Sıralama madalyaları → kısa sayısal
    "🥇": "1. ", "🥈": "2. ", "🥉": "3. ",
    # Renkli daireler → DejaVu mono (U+25CF, Geometric Shapes — safe)
    "🔴": "\u25CF ", "🟢": "\u25CF ", "🟡": "\u25CF ",
    "🟠": "\u25CF ", "🔵": "\u25CF ",
    # Color emoji → DejaVu mono eşdeğer
    "✅": "\u2713 ",   # ✓ plain checkmark
    "❌": "\u2717 ",   # ✗ plain x
    "⭐": "\u2605 ",   # ★ mono star
    "🌟": "\u2605 ",
    "⚠️": "\u26A0 ", "⚠": "\u26A0 ",  # ⚠ mono warning
}

# Emoji strip range — sadece supplementary plane (1F000+)
# 2600-27BF (Misc Symbols + Dingbats) KAPSAM DIŞI — DejaVu bu blokları mono glyph ile render eder
# (✓ ✗ ● ○ ★ ⚠ → sorunsuz görünür)
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F9FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001FA00-\U0001FAFF"
    "\U0001F1E6-\U0001F1FF"
    "\uFE0F"
    "\u200D"
    "]+",
    flags=re.UNICODE,
)


def _clean_emoji(text: str) -> str:
    """Bilinen emoji'leri label'a çevir, kalanları strip et."""
    if not text:
        return text
    for em, lbl in _EMOJI_MAP.items():
        text = text.replace(em, lbl)
    text = _EMOJI_RE.sub("", text)
    return text


# ─── ReportLab paragraph-safe escape ────────────────────────────────────────
def _rl_escape(text: str) -> str:
    """String → reportlab Paragraph güvenli (emoji temiz + XML escape)."""
    text = _clean_emoji(text or "")
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )


def _inline_to_rl(el) -> str:
    """BS4 element → reportlab inline markup (<b>, <i>, <br/>)."""
    from bs4 import NavigableString

    if isinstance(el, NavigableString):
        return _rl_escape(str(el))

    out = []
    for child in el.children:
        if isinstance(child, NavigableString):
            out.append(_rl_escape(str(child)))
        elif child.name in ("strong", "b"):
            out.append("<b>" + _inline_to_rl(child) + "</b>")
        elif child.name in ("em", "i"):
            out.append("<i>" + _inline_to_rl(child) + "</i>")
        elif child.name == "br":
            out.append("<br/>")
        elif child.name == "code":
            out.append('<font face="Courier" size="9">' + _inline_to_rl(child) + "</font>")
        elif child.name == "a":
            url = child.get("href", "")
            txt = _inline_to_rl(child)
            out.append(f'<link href="{_rl_escape(url)}" color="#C76F3E">{txt}</link>')
        elif child.name == "img":
            pass  # image inline skip
        else:
            out.append(_inline_to_rl(child))
    return "".join(out)


# ─── Chart parse + matplotlib render ────────────────────────────────────────
def _parse_chart_dict(div) -> Optional[dict]:
    """<div class='chart-container' data-chart='…'> → dict veya None."""
    raw = div.get("data-chart") if hasattr(div, "get") else None
    if not raw:
        return None
    # BS4 attribute zaten HTML entities'yi decode eder, ekstra gerekmez
    # Ama güvenlik için bir round daha unescape
    try:
        return json.loads(raw)
    except Exception:
        try:
            return json.loads(htmlmod.unescape(raw))
        except Exception as e:
            logger.warning(f"chart data-chart parse fail: {e}")
            return None


def _render_chart_png(chart: dict, width_inch: float = 6.5, height_inch: float = 3.4) -> Optional[io.BytesIO]:
    """Chart dict → matplotlib PNG BytesIO (reportlab Image olarak eklenebilir)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        logger.warning(f"matplotlib yüklenemedi: {e}")
        return None

    chart_type = (chart.get("type") or "line").lower()
    labels = chart.get("labels") or []
    datasets = chart.get("datasets") or []
    title = chart.get("title") or ""

    # Scatter labels zorunlu değil (x,y data point'leri)
    if not datasets:
        return None
    if not labels and (chart.get("type") or "").lower() != "scatter":
        return None

    # Renklerin rgba()/hex formatını matplotlib'e çevir
    def _parse_color(c):
        if not c:
            return None
        c = str(c).strip()
        if c.startswith("#"):
            return c
        m = re.match(r"rgba?\(([^)]+)\)", c)
        if m:
            parts = [p.strip() for p in m.group(1).split(",")]
            if len(parts) >= 3:
                r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
                a = float(parts[3]) if len(parts) >= 4 else 1.0
                return (r / 255, g / 255, b / 255, a)
        return c

    fig, ax = plt.subplots(figsize=(width_inch, height_inch), dpi=130)
    fig.patch.set_facecolor("white")

    try:
        if chart_type == "line":
            for ds in datasets:
                ax.plot(
                    labels,
                    ds.get("data", []),
                    label=ds.get("label", ""),
                    color=_parse_color(ds.get("borderColor")),
                    linewidth=ds.get("borderWidth", 2.2),
                    marker="o",
                    markersize=4.5,
                )
            if any(ds.get("label") for ds in datasets):
                ax.legend(fontsize=8, frameon=False, loc="best")
            ax.grid(True, alpha=0.25, linestyle="--")

        elif chart_type == "bar":
            n = len(datasets)
            x = list(range(len(labels)))
            bar_w = 0.8 / max(n, 1)
            for i, ds in enumerate(datasets):
                offsets = [xi + i * bar_w - 0.4 + bar_w / 2 for xi in x]
                bg = ds.get("backgroundColor") or ds.get("borderColor")
                # backgroundColor liste olabilir (her bar ayrı renk) — doğru parse et
                if isinstance(bg, list):
                    color = [_parse_color(c) for c in bg]
                else:
                    color = _parse_color(bg)
                ax.bar(
                    offsets,
                    ds.get("data", []),
                    width=bar_w,
                    label=ds.get("label", ""),
                    color=color,
                    edgecolor=_parse_color(ds.get("borderColor")) if not isinstance(bg, list) else None,
                    linewidth=0.8,
                )
            ax.set_xticks(x)
            ax.set_xticklabels(labels, rotation=25, ha="right", fontsize=8)
            if any(ds.get("label") for ds in datasets):
                ax.legend(fontsize=8, frameon=False, loc="best")
            ax.grid(True, axis="y", alpha=0.25, linestyle="--")

        elif chart_type in ("horizontalbar", "horizontal_bar"):
            # Yatay bar — Chart.js v2 tipi
            n = len(datasets)
            y = list(range(len(labels)))
            bar_h = 0.8 / max(n, 1)
            for i, ds in enumerate(datasets):
                offsets = [yi + i * bar_h - 0.4 + bar_h / 2 for yi in y]
                bg = ds.get("backgroundColor") or ds.get("borderColor")
                color = [_parse_color(c) for c in bg] if isinstance(bg, list) else _parse_color(bg)
                ax.barh(
                    offsets,
                    ds.get("data", []),
                    height=bar_h,
                    label=ds.get("label", ""),
                    color=color,
                    linewidth=0.8,
                )
            ax.set_yticks(y)
            ax.set_yticklabels(labels, fontsize=8)
            ax.invert_yaxis()  # üst→alt sıralama
            if any(ds.get("label") for ds in datasets):
                ax.legend(fontsize=8, frameon=False, loc="best")
            ax.grid(True, axis="x", alpha=0.25, linestyle="--")

        elif chart_type == "radar":
            # Çok boyutlu karşılaştırma — matplotlib polar
            import numpy as np
            plt.close(fig)  # eski figure kapat, polar axes için yeni
            fig, ax = plt.subplots(
                figsize=(width_inch, height_inch), dpi=130,
                subplot_kw=dict(projection="polar"),
            )
            fig.patch.set_facecolor("white")
            n_labels = len(labels)
            angles = [i / n_labels * 2 * 3.14159265 for i in range(n_labels)]
            angles += [angles[0]]  # kapat
            for ds in datasets:
                data = list(ds.get("data", []))
                if len(data) != n_labels:
                    continue
                data += [data[0]]  # kapat
                color = _parse_color(ds.get("borderColor") or ds.get("backgroundColor"))
                ax.plot(angles, data, label=ds.get("label", ""), color=color, linewidth=2)
                ax.fill(angles, data, alpha=0.18, color=color)
            ax.set_xticks(angles[:-1])
            ax.set_xticklabels(labels, fontsize=8)
            ax.tick_params(labelsize=7)
            if any(ds.get("label") for ds in datasets):
                ax.legend(fontsize=8, frameon=False, loc="upper right", bbox_to_anchor=(1.25, 1.1))

        elif chart_type == "scatter":
            for ds in datasets:
                data_pts = ds.get("data", [])
                xs = [p.get("x", i) if isinstance(p, dict) else i for i, p in enumerate(data_pts)]
                ys = [p.get("y", 0) if isinstance(p, dict) else p for p in data_pts]
                ax.scatter(
                    xs, ys,
                    label=ds.get("label", ""),
                    color=_parse_color(ds.get("backgroundColor") or ds.get("borderColor")),
                    s=40, alpha=0.75,
                )
            if any(ds.get("label") for ds in datasets):
                ax.legend(fontsize=8, frameon=False, loc="best")
            ax.grid(True, alpha=0.25, linestyle="--")

        elif chart_type == "polararea":
            # Polar alan grafiği — matplotlib polar bar
            import numpy as np
            plt.close(fig)
            fig, ax = plt.subplots(
                figsize=(width_inch, height_inch), dpi=130,
                subplot_kw=dict(projection="polar"),
            )
            fig.patch.set_facecolor("white")
            ds = datasets[0]
            data = ds.get("data", [])
            n = len(data)
            if n > 0:
                angles = [i / n * 2 * 3.14159265 for i in range(n)]
                width = 2 * 3.14159265 / n
                bg = ds.get("backgroundColor")
                colors_list = [_parse_color(c) for c in bg] if isinstance(bg, list) else None
                ax.bar(angles, data, width=width, color=colors_list, alpha=0.72, edgecolor="white")
                ax.set_xticks(angles)
                ax.set_xticklabels(labels, fontsize=8)
                ax.tick_params(labelsize=7)

        elif chart_type in ("doughnut", "pie"):
            ds = datasets[0]
            data = ds.get("data", [])
            bg = ds.get("backgroundColor")
            colors_list = None
            if isinstance(bg, list):
                colors_list = [_parse_color(c) for c in bg]
            ax.pie(
                data,
                labels=labels,
                autopct="%1.0f%%",
                colors=colors_list,
                startangle=90,
                textprops={"fontsize": 8},
                wedgeprops={"linewidth": 1.2, "edgecolor": "white"},
            )
            if chart_type == "doughnut":
                centre = plt.Circle((0, 0), 0.55, fc="white")
                ax.add_artist(centre)
            ax.axis("equal")

        else:
            plt.close(fig)
            logger.info(f"Chart type desteklenmiyor: {chart_type}")
            return None

        if title:
            ax.set_title(_clean_emoji(title), fontsize=10.5, color="#333", pad=10)

        # Polar ve pie axes'te spine yok — sadece cartesian axes'te çerçeve temizle
        if chart_type not in ("pie", "doughnut", "radar", "polararea"):
            ax.tick_params(labelsize=8, colors="#555")
            for sp in ("top", "right"):
                if sp in ax.spines:
                    ax.spines[sp].set_visible(False)
            for sp in ("left", "bottom"):
                if sp in ax.spines:
                    ax.spines[sp].set_color("#999")

        plt.tight_layout()
        out = io.BytesIO()
        plt.savefig(out, format="png", bbox_inches="tight", dpi=130, facecolor="white")
        plt.close(fig)
        out.seek(0)
        return out
    except Exception as e:
        logger.warning(f"chart render fail ({chart_type}): {e}")
        try:
            plt.close(fig)
        except Exception:
            pass
        return None


# ─── Table parser ───────────────────────────────────────────────────────────
def _table_to_flowable(tbl_el, cell_style, header_style):
    """<table> BS4 element → reportlab Table (header shading dahil)."""
    from reportlab.platypus import Table, TableStyle, Paragraph
    from reportlab.lib import colors

    all_rows = []
    header_found = False
    for tr in tbl_el.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if not cells:
            continue
        is_header = all(c.name == "th" for c in cells)
        row = []
        for c in cells:
            text = _inline_to_rl(c).strip()
            if not text:
                text = " "
            style = header_style if is_header else cell_style
            row.append(Paragraph(text, style))
        all_rows.append((row, is_header))
        if is_header:
            header_found = True

    if not all_rows:
        return None

    # Header yoksa ilk satırı header gibi işle
    if not header_found and len(all_rows) > 1:
        first = list(all_rows[0][0])
        all_rows[0] = (first, True)

    rows = [r for r, _ in all_rows]
    max_cols = max(len(r) for r in rows)
    # Kolonları normalize et
    for r in rows:
        while len(r) < max_cols:
            r.append(Paragraph(" ", cell_style))

    tbl = Table(rows, repeatRows=1, hAlign="LEFT")
    tstyle = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F5E9DD")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#A5542B")),
        ("FONTNAME", (0, 0), (-1, 0), _FONT_BOLD),
        ("FONTNAME", (0, 1), (-1, -1), _FONT_REGULAR),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#DDD")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFAF8")]),
    ])
    tbl.setStyle(tstyle)
    return tbl


# ─── HTML → Flowable listesi (ana walker) ───────────────────────────────────
def _walk_html(parent, flowables: list, styles: dict) -> None:
    """BS4 element'in blok-düzey çocuklarını yürü, reportlab flowable üret."""
    from reportlab.platypus import Paragraph, Image, Spacer
    from reportlab.lib.units import cm
    from bs4 import NavigableString

    for child in parent.children:
        if isinstance(child, NavigableString):
            text = str(child).strip()
            if not text:
                continue
            flowables.append(Paragraph(_rl_escape(text), styles["body"]))
            continue

        name = child.name
        if name in ("h1", "h2"):
            flowables.append(Paragraph(_inline_to_rl(child), styles["h1"]))
        elif name == "h3":
            flowables.append(Paragraph(_inline_to_rl(child), styles["h2"]))
        elif name in ("h4", "h5", "h6"):
            flowables.append(Paragraph(_inline_to_rl(child), styles["h3"]))
        elif name == "p":
            txt = _inline_to_rl(child).strip()
            if txt:
                flowables.append(Paragraph(txt, styles["body"]))
        elif name in ("ul", "ol"):
            for li in child.find_all("li", recursive=False):
                txt = _inline_to_rl(li).strip()
                if txt:
                    bullet = "• " if name == "ul" else f"{len(flowables)+1}. "
                    flowables.append(Paragraph(bullet + txt, styles["body_li"]))
        elif name == "table":
            tbl = _table_to_flowable(child, styles["cell"], styles["cell_h"])
            if tbl:
                flowables.append(Spacer(1, 6))
                flowables.append(tbl)
                flowables.append(Spacer(1, 6))
        elif name == "div":
            klass = child.get("class") or []
            if "chart-container" in klass or "chart-pending" in klass:
                chart_data = _parse_chart_dict(child)
                if chart_data:
                    png = _render_chart_png(chart_data)
                    if png:
                        img = Image(png, width=15 * cm, height=7.8 * cm, kind="proportional")
                        flowables.append(Spacer(1, 8))
                        flowables.append(img)
                        flowables.append(Spacer(1, 8))
                    else:
                        # Render fail — chart başlığını metin olarak bas (placeholder ugly)
                        title = chart_data.get("title", "").strip()
                        if title:
                            flowables.append(Paragraph(
                                f"<i>{_rl_escape(title)}</i>", styles["meta"]))
                # data-chart parse edilemediyse sessizce atla (ugly placeholder yok)
            else:
                _walk_html(child, flowables, styles)
        elif name == "hr":
            flowables.append(Spacer(1, 10))
        elif name == "blockquote":
            txt = _inline_to_rl(child).strip()
            if txt:
                flowables.append(Paragraph(txt, styles["quote"]))
        elif name == "pre":
            txt = child.get_text()
            if txt.strip():
                flowables.append(Paragraph(
                    f'<font face="Courier" size="9">{_rl_escape(txt)}</font>',
                    styles["code"],
                ))
        elif name in ("br",):
            continue
        elif name in ("b", "strong", "em", "i", "span", "a", "code"):
            # Inline element top-level geldiyse body-level paragraph olarak ekle
            txt = _inline_to_rl(child).strip()
            if txt:
                flowables.append(Paragraph(txt, styles["body"]))
        else:
            _walk_html(child, flowables, styles)


def _sanitize_html(html: str) -> str:
    """HTML'i BS4 öncesi temizle — unescaped + truncated data-chart JSON.

    İki vaka:
    1. İYİ FORM: `<div class="chart-container" data-chart="{...}"></div>` — JSON iç
       tırnakları escape edilmemiş ama div kapalı. İç tırnakları `&quot;` yap.
    2. TRUNCATED: JSON kesik (DB'de yarım saklanmış). `<div class="chart-container"
       data-chart="{"type":"line",...,"borderColor"` diye bitiyor, `}"></div>` yok.
       Bu div'i + ardındaki bozuk içeriği komple strip et (metne sızmasın).

    BS4 parser ilk `"` görünce attribute'u kapanmış sanıyor → her iki vaka da
    tarayıcıda çalışır ama BS4'te parser bozar.
    """
    if not html or "chart-container" not in html:
        return html

    # ─ 1. İyi formlu chart-container: data-chart içini escape et ─
    # Well-formed div'leri marker class ile işaretle, ikinci pass onlara dokunmasın
    def _fix_chart(m: re.Match) -> str:
        payload = m.group(1).strip()
        if not (payload.startswith("{") and payload.endswith("}")):
            return ""  # malformed → drop
        escaped = payload.replace("&", "&amp;").replace('"', "&quot;")
        return f'<div class="chart-container-OK" data-chart="{escaped}"></div>'

    # Key insight: `"></div>` dizisi JSON içinde ASLA olmaz (no `</div>` tokens).
    html = re.sub(
        r'<div\s+class="chart-container"\s+data-chart="(.*?)"></div>',
        _fix_chart,
        html,
        flags=re.DOTALL,
    )

    # ─ 2. Truncated chart-container (marker'sız olanlar): tamamen strip ─
    # Sadece class="chart-container" (marker OK olmayan) → truncated, DB kesiği
    while True:
        m = re.search(r'<div\s+class="chart-container"[^>]*', html)
        if not m:
            break
        start = m.start()
        tail = html[m.end():]
        close = re.search(r'</div>', tail)
        end = m.end() + close.end() if close else len(html)
        html = html[:start] + html[end:]
        logger.debug(f"PDF: truncated chart-container stripped (pos {start}-{end})")

    # ─ 3. Marker'ı geri normal class'a çevir (BS4 "chart-container" görsün) ─
    html = html.replace('class="chart-container-OK"', 'class="chart-container"')

    return html


def _html_to_flowables(html: str, styles: dict) -> list:
    """HTML string → reportlab flowable listesi."""
    if not html:
        return []
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.warning("BeautifulSoup yok — plain text fallback")
        from reportlab.platypus import Paragraph
        return [Paragraph(_rl_escape(html), styles["body"])]

    # BS4 öncesi: unescaped data-chart JSON'larını HTML-entity escape et
    html = _sanitize_html(html)

    soup = BeautifulSoup(html, "html.parser")
    flowables: list = []
    _walk_html(soup, flowables, styles)
    return flowables


# ─── Stil fabrikası ─────────────────────────────────────────────────────────
def _build_styles():
    """Reportlab ParagraphStyle sözlüğü (hepsi DejaVu tabanlı)."""
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT

    accent = colors.HexColor("#C76F3E")
    accent_dark = colors.HexColor("#A5542B")
    fg = colors.HexColor("#2A2A2A")
    muted = colors.HexColor("#6B6B6B")

    return {
        "title": ParagraphStyle(
            "title", fontName=_FONT_BOLD, fontSize=22, leading=26,
            textColor=accent, alignment=TA_CENTER, spaceAfter=14,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", fontName=_FONT_REGULAR, fontSize=11, leading=16,
            textColor=muted, alignment=TA_CENTER, spaceAfter=30,
        ),
        "cover_summary": ParagraphStyle(
            "cover_summary", fontName=_FONT_REGULAR, fontSize=11, leading=17,
            textColor=fg, alignment=TA_CENTER, spaceAfter=8,
        ),
        "item_title": ParagraphStyle(
            "item_title", fontName=_FONT_BOLD, fontSize=15, leading=19,
            textColor=accent, spaceAfter=4, spaceBefore=0,
        ),
        "meta": ParagraphStyle(
            "meta", fontName=_FONT_ITALIC, fontSize=9, leading=12,
            textColor=muted, spaceAfter=10,
        ),
        "context": ParagraphStyle(
            "context", fontName=_FONT_ITALIC, fontSize=10, leading=15,
            textColor=colors.HexColor("#554"), spaceAfter=14,
            leftIndent=10, rightIndent=10, borderPadding=(8, 10, 8, 10),
            backColor=colors.HexColor("#FDF6EC"),
            borderColor=colors.HexColor("#E9D9C2"), borderWidth=0.5,
        ),
        "h1": ParagraphStyle(
            "h1", fontName=_FONT_BOLD, fontSize=13.5, leading=18,
            textColor=accent_dark, spaceBefore=16, spaceAfter=8,
        ),
        "h2": ParagraphStyle(
            "h2", fontName=_FONT_BOLD, fontSize=12, leading=16,
            textColor=accent, spaceBefore=12, spaceAfter=6,
        ),
        "h3": ParagraphStyle(
            "h3", fontName=_FONT_BOLDITALIC, fontSize=11, leading=15,
            textColor=fg, spaceBefore=10, spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "body", fontName=_FONT_REGULAR, fontSize=10.5, leading=15,
            textColor=fg, spaceAfter=7, alignment=TA_LEFT,
        ),
        "body_li": ParagraphStyle(
            "body_li", fontName=_FONT_REGULAR, fontSize=10.5, leading=15,
            textColor=fg, spaceAfter=3, leftIndent=14, bulletIndent=0,
        ),
        "quote": ParagraphStyle(
            "quote", fontName=_FONT_ITALIC, fontSize=10, leading=14,
            textColor=colors.HexColor("#555"), leftIndent=16, rightIndent=16,
            spaceBefore=8, spaceAfter=8,
            borderPadding=(6, 10, 6, 10),
            backColor=colors.HexColor("#F9F4EC"),
        ),
        "code": ParagraphStyle(
            "code", fontName="Courier", fontSize=9, leading=12,
            textColor=colors.HexColor("#333"), leftIndent=8, rightIndent=8,
            spaceBefore=6, spaceAfter=6,
            backColor=colors.HexColor("#F5F5F0"),
            borderPadding=(6, 8, 6, 8),
        ),
        "cell": ParagraphStyle(
            "cell", fontName=_FONT_REGULAR, fontSize=9, leading=12,
            textColor=fg,
        ),
        "cell_h": ParagraphStyle(
            "cell_h", fontName=_FONT_BOLD, fontSize=9, leading=12,
            textColor=accent_dark,
        ),
        "footer": ParagraphStyle(
            "footer", fontName=_FONT_REGULAR, fontSize=8, leading=10,
            textColor=muted, alignment=TA_CENTER,
        ),
    }


# ─── Sayfa altı (footer — sayfa numarası) ──────────────────────────────────
def _on_page(canvas, doc):
    """Her sayfaya alt bilgi (FermatAI · Sayfa N) yaz."""
    canvas.saveState()
    canvas.setFont(_FONT_REGULAR, 8)
    canvas.setFillColorRGB(0.5, 0.5, 0.5)
    from reportlab.lib.pagesizes import A4
    w, h = A4
    canvas.drawCentredString(
        w / 2, 1.0 * 28.35,  # ~1 cm from bottom (28.35 = pt/cm)
        f"FermatAI · Sayfa {doc.page}",
    )
    canvas.restoreState()


# ─── Ana fonksiyon ──────────────────────────────────────────────────────────
async def build_archive_pdf(
    phone: str,
    student_name: str = "",
    archive_ids: list[int] | None = None,
    category: str = "",
) -> bytes:
    """Kullanıcının arşiv kayıtlarından kaliteli PDF üret.

    Args:
        phone: Kullanıcı telefonu (güvenlik filtresi — başka kullanıcı kayıtlarına erişilmez)
        student_name: Kapak sayfasında gösterilecek ad
        archive_ids: Spesifik kayıt ID'leri (None → tümü)
        category: Kategori filtresi ("calisma_plani" vb, boş → tümü)

    Returns:
        PDF byte içeriği
    """
    from db_pool import db_fetch
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, PageBreak,
    )

    _register_fonts()
    styles = _build_styles()

    # ─ Kayıtları çek (phone filtresi ZORUNLU — güvenlik) ─
    conditions = ["phone = $1"]
    args: list = [phone]
    idx = 2
    if archive_ids:
        conditions.append(f"id = ANY(${idx}::int[])")
        args.append(archive_ids)
        idx += 1
    if category:
        conditions.append(f"category = ${idx}")
        args.append(category)
        idx += 1
    sql = (
        "SELECT id, title, content, category, context_prompt, tags, created_at "
        "FROM user_archive WHERE " + " AND ".join(conditions) +
        " ORDER BY created_at DESC"
    )
    kayitlar = await db_fetch(sql, *args)

    if not kayitlar:
        raise RuntimeError("Seçilen kriterlere uyan arşiv kaydı yok")

    # ─ PDF doc ─
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=2.2 * cm, rightMargin=2.2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
        title=f"FermatAI Arşiv — {student_name or phone[-4:]}",
        author="FermatAI",
    )

    story: list = []

    # ═══ Kapak Sayfası ═══
    story.append(Spacer(1, 5.5 * cm))
    story.append(Paragraph("FermatAI Arşivi", styles["title"]))
    try:
        locale_date = datetime.now().strftime("%d %B %Y")
    except Exception:
        locale_date = datetime.now().strftime("%d.%m.%Y")
    story.append(Paragraph(
        f"{_rl_escape(student_name) or 'Öğrenci'} &middot; {locale_date}",
        styles["subtitle"],
    ))

    # Özet
    cat_labels = {
        "genel": "Genel", "calisma_plani": "Çalışma Planı",
        "deneme": "Deneme/Net Analizi", "konu_anlatimi": "Konu Anlatımı",
        "analiz": "Analiz/Rapor", "soru_cozum": "Soru Çözümü",
        "kaynak": "Kaynak Paketi", "not": "Not/Hatırlatma",
    }
    cats: dict = {}
    for k in kayitlar:
        c = k.get("category") or "genel"
        cats[c] = cats.get(c, 0) + 1
    cat_lines = [
        f"• {cat_labels.get(c, c)}: <b>{n}</b> kayıt"
        for c, n in sorted(cats.items(), key=lambda x: -x[1])
    ]
    story.append(Paragraph(
        f"Toplam: <b>{len(kayitlar)} kayıt</b>",
        styles["cover_summary"],
    ))
    story.append(Spacer(1, 12))
    for line in cat_lines:
        story.append(Paragraph(line, styles["cover_summary"]))

    story.append(PageBreak())

    # ═══ Her kayıt için bölüm ═══
    for i, k in enumerate(kayitlar, 1):
        # Başlık
        title_txt = _rl_escape(k.get("title") or "Başlıksız")
        story.append(Paragraph(f"{i}. {title_txt}", styles["item_title"]))

        # Meta
        dt = k.get("created_at")
        try:
            dt_str = dt.strftime("%d %b %Y, %H:%M") if dt else "—"
        except Exception:
            dt_str = str(dt or "—")
        cat_lbl = cat_labels.get(k.get("category") or "genel", "Genel")
        tags = k.get("tags") or ""
        meta_parts = [dt_str, cat_lbl]
        if tags:
            meta_parts.append(f"etiket: {_rl_escape(tags)}")
        story.append(Paragraph(" &middot; ".join(meta_parts), styles["meta"]))

        # Context (soru)
        if k.get("context_prompt"):
            ctx_text = _rl_escape(k["context_prompt"][:500])
            story.append(Paragraph(f"<b>Soru:</b> {ctx_text}", styles["context"]))

        # İçerik — BS4 ile parse
        try:
            content_flowables = _html_to_flowables(k.get("content") or "", styles)
            for fw in content_flowables:
                story.append(fw)
        except Exception as e:
            logger.warning(f"PDF içerik parse fail (kayıt {k.get('id')}): {e}")
            # Fallback: plain text
            plain = re.sub(r"<[^>]+>", " ", k.get("content") or "")
            plain = _rl_escape(plain)
            story.append(Paragraph(plain, styles["body"]))

        # Kayıtlar arası ayırıcı
        if i < len(kayitlar):
            story.append(PageBreak())

    # ─ Build ─
    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


__all__ = ["build_archive_pdf"]
