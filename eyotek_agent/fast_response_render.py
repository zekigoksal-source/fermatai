"""
Fast Response Render — A+++ visual augmentation icin render template'leri.

Oturum 25.41 Faz 2 (Neo direktifi):
"Fast response cevaplara render entegre et — Claude'a gitmeden, $0 maliyet,
2-3s latency ile gorsel zenginlik."

Mimari:
    Fast Response (text)
        +
    Render Template (Chart.js / HTML)
        ↓
    create_artifact() → UUID → public URL
        ↓
    Cevap text'ine link eklenir (augmentation)

3 Pilot Render:
    1. trend_chart      — Son N deneme trend grafigi
    2. weekly_dashboard — Ogrenci haftalik dashboard kart
    3. topic_heatmap    — Ders × Konu basari heatmap

Maliyet: $0 (Claude yok, sadece DB + Chart.js CDN)
Latency: ~200-400ms HTML build + ~100ms DB write
"""
from __future__ import annotations

import os
from typing import Optional, Sequence


# Public render base URL (env'den, varsa)
PUBLIC_BASE = os.getenv("PUBLIC_BASE_URL", "https://api.fermategitimkurumlari.com").rstrip("/")


# ─── Chart.js CDN (stable v4) ─────────────────────────────────────────────
_CHARTJS_CDN = "https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"


def _wrap_html(title: str, body_inner: str, extra_head: str = "") -> str:
    """Standart HTML wrapper — responsive + Fermat brand."""
    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    background: #F5F4ED; color: #2F2F2F; padding: 20px;
    min-height: 100vh;
  }}
  .container {{
    max-width: 800px; margin: 0 auto;
    background: white; border-radius: 16px; padding: 28px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.06);
  }}
  .header {{ margin-bottom: 24px; }}
  .header h1 {{
    font-size: 22px; font-weight: 700; color: #2F2F2F;
    margin-bottom: 6px;
  }}
  .header .subtitle {{
    font-size: 14px; color: #888; font-weight: 400;
  }}
  .stat-grid {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 12px; margin-bottom: 20px;
  }}
  .stat-card {{
    background: #FAF8F2; padding: 14px; border-radius: 10px;
    border-left: 4px solid #C76F3E;
  }}
  .stat-card .label {{
    font-size: 11px; text-transform: uppercase;
    color: #888; letter-spacing: 0.5px;
  }}
  .stat-card .value {{
    font-size: 22px; font-weight: 700; color: #2F2F2F;
    margin-top: 4px;
  }}
  .stat-card .delta {{
    font-size: 12px; margin-top: 2px;
  }}
  .stat-card .delta.up {{ color: #16A34A; }}
  .stat-card .delta.down {{ color: #DC2626; }}
  .chart-container {{
    position: relative; height: 320px; margin-top: 20px;
  }}
  .footer {{
    text-align: center; padding: 16px 0;
    color: #888; font-size: 12px;
    border-top: 1px solid #E5E1D7; margin-top: 24px;
  }}
  .footer .brand {{ color: #C76F3E; font-weight: 600; }}
  table.heatmap {{
    width: 100%; border-collapse: collapse; margin-top: 16px;
  }}
  table.heatmap th, table.heatmap td {{
    padding: 10px 8px; text-align: center;
    font-size: 13px; border: 1px solid #E5E1D7;
  }}
  table.heatmap th {{
    background: #FAF8F2; color: #2F2F2F;
    font-weight: 600; text-align: left;
  }}
  .chip {{
    display: inline-block; padding: 4px 10px; border-radius: 20px;
    font-size: 11px; font-weight: 600;
  }}
  .chip.green {{ background: #DCFCE7; color: #166534; }}
  .chip.yellow {{ background: #FEF3C7; color: #92400E; }}
  .chip.red {{ background: #FEE2E2; color: #991B1B; }}
  @media (max-width: 600px) {{
    body {{ padding: 12px; }}
    .container {{ padding: 18px; border-radius: 12px; }}
    .header h1 {{ font-size: 18px; }}
    .chart-container {{ height: 260px; }}
  }}
</style>
{extra_head}
</head>
<body>
<div class="container">
{body_inner}
<div class="footer">
  ⚡ <span class="brand">FermatAI</span> &middot; Kişisel Eğitim Asistanın
</div>
</div>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════════════
# RENDER 1 — TREND CHART (Son N Deneme Trend Grafigi)
# ═══════════════════════════════════════════════════════════════════════
def build_trend_chart_html(name: str, exams: Sequence[dict]) -> str:
    """Son N deneme trend grafigi — Chart.js line chart.

    exams: [{exam_name, exam_date, toplam, turkce, matematik, fizik, kimya, biyoloji}, ...]
    Eskiden yeniye sirali olmali.

    Returns: HTML string (create_artifact'e kaydedilir)
    """
    import json as _json

    # Veri hazirla
    labels = []
    toplam_data = []
    for e in exams:
        # Etiket: "01.04 TYT" gibi kisa
        d = e.get('exam_date')
        if d:
            try:
                lbl = d.strftime('%d.%m')
            except Exception:
                lbl = str(d)[:5]
        else:
            lbl = '?'
        ex_name = (e.get('exam_name') or '')[:20]
        labels.append(f"{lbl}")
        toplam_data.append(float(e.get('toplam', 0) or 0))

    # Stats
    if toplam_data:
        max_v = max(toplam_data)
        min_v = min(toplam_data)
        son = toplam_data[-1]
        ilk = toplam_data[0]
        delta = son - ilk
        delta_class = "up" if delta > 0 else ("down" if delta < 0 else "")
        delta_arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
        delta_str = f"{delta_arrow} {abs(delta):.1f} net"
    else:
        max_v = min_v = son = 0
        delta = 0; delta_class = ""; delta_str = "—"

    body = f"""
<div class="header">
  <h1>📊 {name} — Deneme Trend Analizi</h1>
  <div class="subtitle">Son {len(exams)} deneme | _{labels[0] if labels else '?'} → {labels[-1] if labels else '?'}_</div>
</div>

<div class="stat-grid">
  <div class="stat-card">
    <div class="label">Son Net</div>
    <div class="value">{son:.1f}</div>
    <div class="delta {delta_class}">{delta_str}</div>
  </div>
  <div class="stat-card">
    <div class="label">En Yüksek</div>
    <div class="value">{max_v:.1f}</div>
  </div>
  <div class="stat-card">
    <div class="label">En Düşük</div>
    <div class="value">{min_v:.1f}</div>
  </div>
  <div class="stat-card">
    <div class="label">Ortalama</div>
    <div class="value">{sum(toplam_data)/len(toplam_data) if toplam_data else 0:.1f}</div>
  </div>
</div>

<div class="chart-container">
  <canvas id="trendChart"></canvas>
</div>

<script src="{_CHARTJS_CDN}"></script>
<script>
const ctx = document.getElementById('trendChart');
new Chart(ctx, {{
  type: 'line',
  data: {{
    labels: {_json.dumps(labels)},
    datasets: [{{
      label: 'Toplam Net',
      data: {_json.dumps(toplam_data)},
      borderColor: '#C76F3E',
      backgroundColor: 'rgba(199, 111, 62, 0.1)',
      borderWidth: 3,
      tension: 0.3,
      fill: true,
      pointRadius: 6,
      pointBackgroundColor: '#C76F3E',
      pointBorderColor: 'white',
      pointBorderWidth: 2,
      pointHoverRadius: 8,
    }}]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    plugins: {{
      legend: {{ display: false }},
      tooltip: {{
        backgroundColor: '#2F2F2F',
        padding: 12, cornerRadius: 8,
        callbacks: {{
          label: (ctx) => `${{ctx.parsed.y.toFixed(1)}} net`
        }}
      }}
    }},
    scales: {{
      y: {{
        beginAtZero: false,
        ticks: {{ font: {{ size: 12 }} }},
        grid: {{ color: '#F0EDE3' }}
      }},
      x: {{
        ticks: {{ font: {{ size: 12 }} }},
        grid: {{ display: false }}
      }}
    }}
  }}
}});
</script>
"""
    return _wrap_html(f"{name} - Deneme Trendi", body)


# ═══════════════════════════════════════════════════════════════════════
# RENDER 2 — WEEKLY DASHBOARD (Ogrenci Haftalik Ozet Kart)
# ═══════════════════════════════════════════════════════════════════════
def build_weekly_dashboard_html(name: str, data: dict) -> str:
    """Ogrenci haftalik dashboard — son deneme + devamsizlik + zayif konu + etut.

    data: {
        'son_deneme': {'toplam': 45, 'tarih': '...', 'name': 'TYT...'},
        'devamsizlik': 75,
        'zayif_konular': [{'ders', 'konu', 'basari'}, ...],
        'guclu_konular': [{'ders', 'konu', 'basari'}, ...],
        'etut': {'toplam': 18, 'yapildi': 14},
        'sinif': '12 SAY A',
    }
    """
    import json as _json

    son_d = data.get('son_deneme', {})
    son_net = float(son_d.get('toplam', 0) or 0)
    devamsizlik = int(data.get('devamsizlik', 0) or 0)
    zayif = data.get('zayif_konular', [])[:3]
    guclu = data.get('guclu_konular', [])[:3]
    etut = data.get('etut', {})
    etut_toplam = int(etut.get('toplam', 0) or 0)
    etut_yapildi = int(etut.get('yapildi', 0) or 0)
    etut_oran = int((etut_yapildi / etut_toplam) * 100) if etut_toplam > 0 else 0
    sinif = data.get('sinif', '?')

    # Devamsizlik chip rengi
    dev_chip = "green" if devamsizlik < 50 else ("yellow" if devamsizlik < 150 else "red")
    dev_lbl = "İYİ" if devamsizlik < 50 else ("ORTA" if devamsizlik < 150 else "RİSK")
    etut_chip = "green" if etut_oran >= 70 else ("yellow" if etut_oran >= 40 else "red")

    # Zayıf/güçlü liste
    zayif_html = "".join(
        f'<li><b>{(t.get("ders") or "?")}</b> — {(t.get("konu") or "")[:35]} '
        f'<span class="chip red">%{int(t.get("basari", 0))}</span></li>'
        for t in zayif
    ) or '<li><i>Henüz veri yok</i></li>'

    guclu_html = "".join(
        f'<li><b>{(t.get("ders") or "?")}</b> — {(t.get("konu") or "")[:35]} '
        f'<span class="chip green">%{int(t.get("basari", 0))}</span></li>'
        for t in guclu
    ) or '<li><i>Henüz veri yok</i></li>'

    body = f"""
<div class="header">
  <h1>📊 {name} — Haftalık Dashboard</h1>
  <div class="subtitle">{sinif} sınıfı | Akademik durum özeti</div>
</div>

<div class="stat-grid">
  <div class="stat-card">
    <div class="label">Son Deneme Net</div>
    <div class="value">{son_net:.1f}</div>
  </div>
  <div class="stat-card">
    <div class="label">Devamsızlık</div>
    <div class="value">{devamsizlik} sa</div>
    <div class="delta"><span class="chip {dev_chip}">{dev_lbl}</span></div>
  </div>
  <div class="stat-card">
    <div class="label">Etüt Katılım</div>
    <div class="value">%{etut_oran}</div>
    <div class="delta"><span class="chip {etut_chip}">{etut_yapildi}/{etut_toplam}</span></div>
  </div>
  <div class="stat-card">
    <div class="label">Güçlü Konu</div>
    <div class="value">{len(guclu)}</div>
  </div>
</div>

<div style="margin-top: 24px;">
  <h3 style="color: #16A34A; font-size: 16px; margin-bottom: 10px;">💪 Güçlü Konuların</h3>
  <ul style="list-style: none; padding-left: 0;">
    {guclu_html}
  </ul>
</div>

<div style="margin-top: 20px;">
  <h3 style="color: #DC2626; font-size: 16px; margin-bottom: 10px;">🎯 Öncelikli Konular (Zayıf)</h3>
  <ul style="list-style: none; padding-left: 0;">
    {zayif_html}
  </ul>
</div>

<style>
  ul li {{
    padding: 8px 12px; margin-bottom: 6px;
    background: #FAF8F2; border-radius: 6px;
    display: flex; justify-content: space-between; align-items: center;
  }}
</style>
"""
    return _wrap_html(f"{name} - Haftalık Dashboard", body)


# ═══════════════════════════════════════════════════════════════════════
# RENDER 3 — TOPIC HEATMAP (Ders × Konu Basari Heatmap)
# ═══════════════════════════════════════════════════════════════════════
def build_topic_heatmap_html(name: str, topics: Sequence[dict]) -> str:
    """Ders bazli konu basari heatmap.

    topics: [{ders, konu, sinav_hata_yuzdesi}, ...]
    """
    # Ders bazli grupla
    by_ders = {}
    for t in topics:
        d = t.get('ders', '?')
        by_ders.setdefault(d, []).append(t)

    # Renk fonksiyonu (basari yuzdesine gore)
    def _color(basari):
        if basari >= 80:
            return "#16A34A"  # green
        elif basari >= 60:
            return "#84CC16"  # lime
        elif basari >= 40:
            return "#EAB308"  # yellow
        elif basari >= 20:
            return "#F97316"  # orange
        else:
            return "#DC2626"  # red

    # HTML rows
    table_rows = []
    for ders, konu_list in by_ders.items():
        # Ders satiri
        konu_cells = []
        for k in konu_list[:8]:  # max 8 konu/ders
            basari = float(k.get('sinav_hata_yuzdesi', 0) or 0)
            konu_ad = (k.get('konu') or '')[:25]
            color = _color(basari)
            konu_cells.append(
                f'<td style="background: {color}; color: white; '
                f'font-weight: 600;">{konu_ad}<br/>'
                f'<span style="font-size: 11px; opacity: 0.9;">%{int(basari)}</span></td>'
            )

        # Eksik konularla doldur (en az 4 sutun gosterelim)
        while len(konu_cells) < 4:
            konu_cells.append('<td style="background: #FAF8F2; color: #888;">—</td>')

        table_rows.append(
            f'<tr><th style="background: #FAF8F2; min-width: 100px;">{ders}</th>'
            f'{"".join(konu_cells)}</tr>'
        )

    table_html = "\n".join(table_rows)

    # Renk legenti
    legend = """
    <div style="margin-top: 20px; display: flex; gap: 8px; flex-wrap: wrap; font-size: 12px;">
      <span class="chip" style="background: #DC2626; color: white;">0-20% Çok Zayıf</span>
      <span class="chip" style="background: #F97316; color: white;">20-40% Zayıf</span>
      <span class="chip" style="background: #EAB308; color: white;">40-60% Orta</span>
      <span class="chip" style="background: #84CC16; color: white;">60-80% İyi</span>
      <span class="chip" style="background: #16A34A; color: white;">80-100% Çok İyi</span>
    </div>
    """

    body = f"""
<div class="header">
  <h1>🗺️ {name} — Konu Başarı Haritası</h1>
  <div class="subtitle">{len(topics)} konu | {len(by_ders)} ders</div>
</div>

<table class="heatmap">
{table_html}
</table>

{legend}

<div style="margin-top: 20px; padding: 14px; background: #FAF8F2; border-radius: 8px;">
  <div style="font-weight: 600; margin-bottom: 6px;">💡 Stratejik Yorum</div>
  <div style="font-size: 13px; line-height: 1.6;">
    Kırmızı/Turuncu konular <b>en hızlı puan kazanım alanların</b>.
    Yeşil konularda istikrarı koru, kırmızıya odaklan.
  </div>
</div>
"""
    return _wrap_html(f"{name} - Konu Haritası", body)


# ═══════════════════════════════════════════════════════════════════════
# CONVENIENCE: Make + persist + return URL
# ═══════════════════════════════════════════════════════════════════════
async def make_render_and_get_url(
    html: str,
    title: str,
    creator_phone: str = "",
    ttl_days: int = 14,
) -> Optional[str]:
    """HTML'i create_artifact'e kaydet ve public URL dondur.

    Hata olursa None doner — caller fast response'a render eklemez (graceful).
    """
    try:
        from render_endpoint import create_artifact
        uuid = await create_artifact(
            html=html,
            title=title,
            creator_phone=creator_phone,
            ttl_days=ttl_days,
            allow_cache=True,  # ayni title ile reuse
        )
        if uuid:
            return f"{PUBLIC_BASE}/render/{uuid}"
        return None
    except Exception as e:
        # Sessiz fail — fast response yine ana cevabi gonderir, sadece link eksik
        import logging
        logging.getLogger(__name__).debug(f"[FAST_RENDER] make_render fail: {e}")
        return None


async def make_trend_chart(
    soz_no: int,
    name: str,
    exams: Sequence[dict],
    creator_phone: str = "",
) -> Optional[str]:
    """Convenience: trend chart uret + URL dondur.

    exams: en az 3 deneme istenir (daha az ise None doner)
    """
    if not exams or len(exams) < 3:
        return None
    html = build_trend_chart_html(name, exams)
    return await make_render_and_get_url(
        html=html,
        title=f"{name} - Deneme Trendi",
        creator_phone=creator_phone,
        ttl_days=14,
    )


async def make_weekly_dashboard(
    soz_no: int,
    name: str,
    data: dict,
    creator_phone: str = "",
) -> Optional[str]:
    """Convenience: haftalik dashboard uret + URL dondur."""
    if not data:
        return None
    html = build_weekly_dashboard_html(name, data)
    return await make_render_and_get_url(
        html=html,
        title=f"{name} - Haftalik Dashboard",
        creator_phone=creator_phone,
        ttl_days=7,  # haftalik veri, 7 gun yeter
    )


async def make_topic_heatmap(
    soz_no: int,
    name: str,
    topics: Sequence[dict],
    creator_phone: str = "",
) -> Optional[str]:
    """Convenience: konu heatmap uret + URL dondur.

    topics: en az 5 konu istenir (anlamli heatmap icin)
    """
    if not topics or len(topics) < 5:
        return None
    html = build_topic_heatmap_html(name, topics)
    return await make_render_and_get_url(
        html=html,
        title=f"{name} - Konu Haritasi",
        creator_phone=creator_phone,
        ttl_days=14,
    )


__all__ = [
    "build_trend_chart_html",
    "build_weekly_dashboard_html",
    "build_topic_heatmap_html",
    "make_trend_chart",
    "make_weekly_dashboard",
    "make_topic_heatmap",
    "make_render_and_get_url",
]
