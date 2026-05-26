"""
FermatAI — YKS Puan Tahmin Motoru (Hafta 4.1)
==============================================
Öğrencinin mevcut deneme trendinden YKS puan tahmini yapar.
Hedef bölüm/puan için kaç net daha gerektiğini hesaplar.

YKS Puan Formülü (2024-2026, Maarif Modeli öncesi):
  TYT = 100 + (Türkçe×3.3 + Sosyal×3.4 + Matematik×3.3 + Fen×3.4)
  AYT_SAY = 100 + (Mat×3 + Fizik×2.85 + Kim×3.07 + Bio×3.07) + TYT×0.4
  AYT_EA  = 100 + (Mat×3 + TDE×3 + Tarih×2.8 + Cog×3.33) + TYT×0.4
  AYT_SOZ = 100 + (TDE×3 + Tarih×2.8 + Cog×3.33 + Felsefe×3 + Din×3.3) + TYT×0.32

Diploma puanı YKS yerleşme puanına +0 (2024 sonrasi sadece OBP olarak kullanılıyor).

Kullanım:
  python puan_tahmin.py 230                # Ecrin için tahmin
  python puan_tahmin.py 230 --hedef 480    # Hedef puan analizi
  python puan_tahmin.py 230 --bolum tip    # Bölüm bazlı (tip/muh/hukuk vb.)
"""

import asyncio
import statistics
import sys
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

from db_pool import db_fetch, db_fetchrow, db_fetchval


# Ortalama hedef puanlar (2025 son 3 yıl ortalama, devlet üniv 4 yıl)
BOLUM_HEDEFLER = {
    'tip': {'puan': 530, 'alan': 'SAY', 'aciklama': 'Tıp Fakültesi (devlet)'},
    'dishekim': {'puan': 510, 'alan': 'SAY', 'aciklama': 'Diş Hekimliği'},
    'eczacilik': {'puan': 480, 'alan': 'SAY', 'aciklama': 'Eczacılık'},
    'muh': {'puan': 460, 'alan': 'SAY', 'aciklama': 'Mühendislik (orta seviye)'},
    'bilgisayar_muh': {'puan': 500, 'alan': 'SAY', 'aciklama': 'Bilgisayar Müh.'},
    'odtu_muh': {'puan': 510, 'alan': 'SAY', 'aciklama': 'ODTÜ Mühendislik'},
    'itu_muh': {'puan': 505, 'alan': 'SAY', 'aciklama': 'İTÜ Mühendislik'},
    'hukuk': {'puan': 470, 'alan': 'EA', 'aciklama': 'Hukuk Fakültesi'},
    'iibf': {'puan': 380, 'alan': 'EA', 'aciklama': 'İktisadi-İdari'},
    'psikoloji': {'puan': 450, 'alan': 'EA', 'aciklama': 'Psikoloji'},
    'ogretmenlik': {'puan': 350, 'alan': 'EA', 'aciklama': 'Öğretmenlik (alan)'},
    'rehberlik': {'puan': 380, 'alan': 'EA', 'aciklama': 'PDR (Rehberlik)'},
}


async def _fetch_unique_exams(soz_no: str, limit: int = 10) -> list:
    """Tekrar eden satırları kaldır, son N denemeyi getir."""
    rows = await db_fetch("""
        SELECT DISTINCT ON (exam_date, exam_name)
            exam_name, exam_date,
            turkce, tarih, cografya, felsefe, din_kulturu,
            matematik, geometri, fizik, kimya, biyoloji, toplam
        FROM student_exams
        WHERE soz_no::text = $1
        ORDER BY exam_date DESC, exam_name
        LIMIT $2
    """, str(soz_no), limit * 2)
    # Tarihten ayır: TYT vs AYT
    tyt = [r for r in rows if not r['exam_name'].startswith('[AYT]')]
    ayt = [r for r in rows if r['exam_name'].startswith('[AYT]')]
    return tyt[:limit], ayt[:limit]


def _safe(v):
    return float(v) if v is not None else 0.0


def hesapla_tyt_puan(turkce: float, sosyal: float, matematik: float, fen: float) -> float:
    """TYT ham puanı (diploma yok)."""
    return 100 + (turkce * 3.3 + sosyal * 3.4 + matematik * 3.3 + fen * 3.4)


def hesapla_ayt_say(tyt_puan: float, mat: float, fiz: float, kim: float, bio: float) -> float:
    """AYT Sayısal yerleşme puanı."""
    ayt_kismi = 100 + (mat * 3 + fiz * 2.85 + kim * 3.07 + bio * 3.07)
    # SAY puan: TYT %40 + AYT %60
    return tyt_puan * 0.4 + ayt_kismi * 0.6


def hesapla_ayt_ea(tyt_puan: float, mat: float, tde: float, tarih: float, cog: float) -> float:
    """AYT Eşit Ağırlık yerleşme puanı."""
    ayt_kismi = 100 + (mat * 3 + tde * 3 + tarih * 2.8 + cog * 3.33)
    return tyt_puan * 0.4 + ayt_kismi * 0.6


def trend_yon(values: list) -> tuple:
    """Liste için trend: ('artıyor'|'azalıyor'|'sabit', delta)."""
    if len(values) < 2:
        return ('belirsiz', 0)
    # Son 3 vs önceki 3
    n = len(values)
    half = max(1, n // 2)
    son = sum(values[:half]) / half
    eski = sum(values[half:]) / (n - half) if n > half else son
    delta = son - eski
    if delta > 1.5:
        return ('artıyor', delta)
    elif delta < -1.5:
        return ('azalıyor', delta)
    else:
        return ('sabit', delta)


def _parse_num(v):
    """Eyotek '54,25' → 54.25 float."""
    if v is None or v == '':
        return 0.0
    try:
        return float(str(v).replace(',', '.'))
    except (ValueError, TypeError):
        return 0.0


async def _get_ayt_avg_netler(soz_no: str) -> dict:
    """student_exam_analysis tablosundan AYT ortalama netleri cek.

    Eyotek BIRLESTIR sonuc TOPLAM verir → katilan_sinav_ayt'a bölerek ortalamaya cevir.
    Ayrica:
    - 'Toplam' satirini filtrele
    - Ayni ders birden fazla kayitsa hepsini topla (Eyotek bazen Matematik'i 2 kez verir)
    """
    import json as _json
    r = await db_fetchrow("""
        SELECT katilan_sinav_ayt, sinav_sayisi_ayt, ders_netleri_ayt,
               ham_puan_ayt, yerlesme_puani_ayt
        FROM student_exam_analysis WHERE soz_no::text = $1
    """, str(soz_no))
    if not r or not r['ders_netleri_ayt']:
        return None
    katilan = max(1, r['katilan_sinav_ayt'] or 1)

    netler_raw = r['ders_netleri_ayt']
    if isinstance(netler_raw, str):
        netler_raw = _json.loads(netler_raw)

    # Ders bazli kayit (Toplam satirini atla)
    # Eyotek bazen ayni dersi 2 kez veriyor (eski/yeni mufredat) — EN BUYUK soru sayisini sec
    by_ders = {}
    for n in netler_raw:
        d = (n.get('ders') or '').strip()
        if not d or d.lower() in ('toplam', 'total'):
            continue
        # YKS_ veya AYT_ prefix olanlar AYT
        if not (d.startswith('YKS_') or d.startswith('AYT_')):
            continue
        net = _parse_num(n.get('net'))
        soru = _parse_num(n.get('soru'))
        # Ayni ders 2x ise EN BUYUK soru olani sec (en kapsamli kayit)
        if d not in by_ders or soru > by_ders[d]['soru']:
            by_ders[d] = {'net': net, 'soru': soru}

    # Sinav basina ortalama (TOPLAM / katilan)
    avg = {}
    for d, vals in by_ders.items():
        avg[d] = {
            'net': vals['net'] / katilan,
            'soru': vals['soru'] / katilan,
        }

    return {
        'katilan': katilan,
        'sinav_sayisi': r['sinav_sayisi_ayt'] or 0,
        'ham_puan': _parse_num(r['ham_puan_ayt']),
        'yerlesme_puani': _parse_num(r['yerlesme_puani_ayt']),
        'avg_netler': avg,
    }


async def tahmin_et(soz_no: str) -> dict:
    """Öğrenci için puan tahmin paketi."""
    student = await db_fetchrow(
        "SELECT full_name, class_name FROM students WHERE soz_no::text=$1",
        str(soz_no)
    )
    if not student:
        return {'error': f'Öğrenci bulunamadı: {soz_no}'}

    name = student['full_name']
    sinif = student['class_name'] or '?'

    tyt, ayt = await _fetch_unique_exams(soz_no, limit=10)

    if not tyt:
        return {
            'name': name, 'sinif': sinif,
            'error': 'Henüz TYT denemesi yok.'
        }

    # TYT analiz
    tyt_turkce = [_safe(r['turkce']) for r in tyt]
    tyt_mat = [_safe(r['matematik']) + _safe(r['geometri']) for r in tyt]
    tyt_fen = [_safe(r['fizik']) + _safe(r['kimya']) + _safe(r['biyoloji']) for r in tyt]
    tyt_sos = [_safe(r['tarih']) + _safe(r['cografya']) + _safe(r['felsefe']) + _safe(r['din_kulturu']) for r in tyt]
    tyt_toplam = [_safe(r['toplam']) for r in tyt]

    # Son 3 deneme ortalaması
    son3 = lambda lst: sum(lst[:3]) / max(1, len(lst[:3]))
    avg_turkce = son3(tyt_turkce)
    avg_mat = son3(tyt_mat)
    avg_fen = son3(tyt_fen)
    avg_sos = son3(tyt_sos)

    tyt_puan_tahmin = hesapla_tyt_puan(avg_turkce, avg_sos, avg_mat, avg_fen)

    # ── AYT — student_exam_analysis tablosundan toplu birlestir verisi ─────
    # Eyotek "BIRLESTIR" sonuc Eyotek tarafindan zaten dogru hesaplanmis yerlesme puani veriyor.
    # Bizim hesapladigimizdan ZIYADE Eyotek'in degerini kullanmak daha guvenli.
    ayt_data = await _get_ayt_avg_netler(soz_no)
    ayt_say_puan = None
    ayt_ea_puan = None
    ayt_avg_netler = None
    eyotek_yerlesme = None
    eyotek_ham = None

    if ayt_data:
        # Eyotek'in zaten hesapladigi yerlesme puani var — bunu kullan (auth)
        eyotek_yerlesme = ayt_data['yerlesme_puani'] or None
        eyotek_ham = ayt_data['ham_puan'] or None
        ayt_avg_netler = ayt_data['avg_netler']

        avg = ayt_data['avg_netler']
        avg_mat_ayt = avg.get('YKS_Matematik', {}).get('net', 0) + avg.get('YKS_Geometri', {}).get('net', 0)
        avg_fiz_ayt = avg.get('YKS_Fizik', {}).get('net', 0)
        avg_kim_ayt = avg.get('YKS_Kimya', {}).get('net', 0)
        avg_bio_ayt = avg.get('YKS_Biyoloji', {}).get('net', 0)
        avg_tde_ayt = avg.get('YKS_TDili ve Edb', {}).get('net', 0)
        avg_tarih_ayt = avg.get('YKS_Tarih-1', {}).get('net', 0)
        avg_cog_ayt = avg.get('YKS_Coğrafya-1', {}).get('net', 0)

        ayt_say_puan = hesapla_ayt_say(
            tyt_puan_tahmin,
            avg_mat_ayt, avg_fiz_ayt, avg_kim_ayt, avg_bio_ayt,
        )
        ayt_ea_puan = hesapla_ayt_ea(
            tyt_puan_tahmin,
            avg_mat_ayt, avg_tde_ayt, avg_tarih_ayt, avg_cog_ayt,
        )
    elif ayt:
        # Fallback: student_exams [AYT] kayitlarindan (eski yontem)
        ayt_mat = [_safe(r['matematik']) + _safe(r['geometri']) for r in ayt]
        ayt_fiz = [_safe(r['fizik']) for r in ayt]
        ayt_kim = [_safe(r['kimya']) for r in ayt]
        ayt_bio = [_safe(r['biyoloji']) for r in ayt]
        ayt_tde = [_safe(r['turkce']) for r in ayt]
        ayt_tarih = [_safe(r['tarih']) for r in ayt]
        ayt_cog = [_safe(r['cografya']) for r in ayt]

        ayt_say_puan = hesapla_ayt_say(
            tyt_puan_tahmin,
            son3(ayt_mat), son3(ayt_fiz), son3(ayt_kim), son3(ayt_bio)
        )
        ayt_ea_puan = hesapla_ayt_ea(
            tyt_puan_tahmin,
            son3(ayt_mat), son3(ayt_tde), son3(ayt_tarih), son3(ayt_cog)
        )

    # Trend analizleri
    trend_turkce = trend_yon(tyt_turkce[:6])
    trend_mat = trend_yon(tyt_mat[:6])
    trend_fen = trend_yon(tyt_fen[:6])
    trend_sos = trend_yon(tyt_sos[:6])
    trend_toplam = trend_yon(tyt_toplam[:6])

    # En iyi / en kötü deneme
    if tyt_toplam:
        en_iyi = max(tyt_toplam)
        en_kotu = min(tyt_toplam)
    else:
        en_iyi = en_kotu = 0

    return {
        'name': name, 'sinif': sinif,
        'sinav_sayisi': len(tyt),
        'son_tarih': tyt[0]['exam_date'].strftime('%d.%m.%Y') if (tyt and tyt[0].get('exam_date')) else None,
        'tyt_son3_avg': {
            'turkce': avg_turkce, 'matematik': avg_mat,
            'fen': avg_fen, 'sosyal': avg_sos,
            'toplam': avg_turkce + avg_mat + avg_fen + avg_sos,
        },
        'tahmin': {
            'tyt_puan': round(tyt_puan_tahmin, 2),
            'ayt_say': round(ayt_say_puan, 2) if ayt_say_puan else None,
            'ayt_ea': round(ayt_ea_puan, 2) if ayt_ea_puan else None,
            # Eyotek'in zaten hesapladigi RESMI yerlesme puani (varsa daha guvenilir)
            'eyotek_yerlesme_puani': round(eyotek_yerlesme, 2) if eyotek_yerlesme else None,
            'eyotek_ham_puan': round(eyotek_ham, 2) if eyotek_ham else None,
        },
        'ayt_avg_netler': ayt_avg_netler,  # ders bazli SINAV BASINA ortalama net
        'trendler': {
            'turkce': trend_turkce, 'matematik': trend_mat,
            'fen': trend_fen, 'sosyal': trend_sos, 'toplam': trend_toplam,
        },
        'en_iyi_net': en_iyi, 'en_kotu_net': en_kotu,
    }


def hedef_analiz(tahmin: dict, hedef_puan: float, alan: str = 'SAY') -> dict:
    """Hedef puana ulaşmak için kaç net gerekli."""
    mevcut_puan = tahmin['tahmin']['ayt_say'] if alan == 'SAY' else tahmin['tahmin']['ayt_ea']
    if not mevcut_puan:
        # AYT yoksa TYT bazli
        mevcut_puan = tahmin['tahmin']['tyt_puan']
    fark = hedef_puan - mevcut_puan
    # Yaklasim: 1 net ~ 5-6 puan AYT etkisi
    if fark <= 0:
        return {'durum': 'hedef_uzerinde', 'fark': fark, 'gereken_ek_net': 0}
    # AYT ders bazli ortalama katsayi: ~3 × 0.6 (AYT %60) = ~1.8 puan/net
    net_per_puan = 1 / 1.8
    gereken_ek_net = fark * net_per_puan
    return {
        'durum': 'hedef_altinda',
        'fark': round(fark, 1),
        'gereken_ek_net': round(gereken_ek_net, 1),
        'mevcut_puan': round(mevcut_puan, 2),
        'hedef_puan': hedef_puan,
    }


def format_rapor(tahmin: dict, hedef: dict = None) -> str:
    """WhatsApp formatlı puan tahmin raporu."""
    if 'error' in tahmin:
        return f"⚠️ {tahmin.get('name', '')}: {tahmin['error']}"

    t = tahmin
    lines = [
        f"🎯 *YKS PUAN TAHMİNİ — {t['name']}*\n",
        f"📚 *Sınıf:* {t['sinif']}",
        f"📊 *Analiz edilen deneme:* {t['sinav_sayisi']} adet",
        f"📅 *Son sınav:* {t['son_tarih']}",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━",
        "🔢 *SON 3 DENEME ORTALAMA NET*",
        "━━━━━━━━━━━━━━━━━━━━━━━\n",
    ]

    a = t['tyt_son3_avg']
    lines.append(f"  📖 Türkçe: *{a['turkce']:.1f}* / 40")
    lines.append(f"  ➗ Matematik: *{a['matematik']:.1f}* / 40")
    lines.append(f"  🔬 Fen: *{a['fen']:.1f}* / 20")
    lines.append(f"  🌍 Sosyal: *{a['sosyal']:.1f}* / 20")
    lines.append(f"  ✨ *TYT Toplam:* {a['toplam']:.1f} / 120\n")

    # AYT NETLERI (varsa) — Eyotek BIRLESTIR'den ortalama
    # NOT: Soru sayisi veriden gelir (Eyotek formatina göre değişir, hardcoded yapma)
    avg_ayt = t.get('ayt_avg_netler')
    if avg_ayt:
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("🎯 *AYT NETLERI* (sınav başına ortalama)")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━\n")
        # Sayisal — sadece net > 0 olanlar (girilmis dersler)
        for ders, emoji in [
            ('YKS_Matematik', '➗'), ('YKS_Geometri', '📐'),
            ('YKS_Fizik', '⚛️'), ('YKS_Kimya', '🧪'), ('YKS_Biyoloji', '🧬'),
            ('YKS_TDili ve Edb', '📖'), ('YKS_Tarih-1', '🏛️'),
            ('YKS_Coğrafya-1', '🌍'), ('YKS_Felsefe', '🤔'),
            ('YKS_Din Kültürü', '🕌'),
        ]:
            d = avg_ayt.get(ders)
            if d and d['net'] > 0.05:
                lines.append(f"  {emoji} {ders.replace('YKS_','')}: *{d['net']:.1f}* / {d['soru']:.0f}")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("🏆 *YKS PUAN TAHMİNİ*")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━\n")

    lines.append(f"  📐 *TYT puanı (tahmin):* ~{t['tahmin']['tyt_puan']:.0f}")
    if t['tahmin'].get('eyotek_yerlesme_puani'):
        # Eyotek'in resmi hesaplamasi - DAHA GUVENILIR
        lines.append(f"  🏅 *Eyotek YERLEŞME (resmi):* *{t['tahmin']['eyotek_yerlesme_puani']:.0f}*")
        lines.append(f"  📊 *Eyotek Ham puan:* {t['tahmin']['eyotek_ham_puan']:.0f}")
    if t['tahmin']['ayt_say']:
        lines.append(f"  🧪 *Sayısal (SAY) tahmin:* ~{t['tahmin']['ayt_say']:.0f}")
    if t['tahmin']['ayt_ea']:
        lines.append(f"  ⚖️ *Eşit Ağırlık (EA) tahmin:* ~{t['tahmin']['ayt_ea']:.0f}")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("📈 *TREND ANALİZİ*")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━\n")

    trend_emoji = {'artıyor': '🟢↗️', 'azalıyor': '🔴↘️', 'sabit': '🟡➡️', 'belirsiz': '⚪'}
    for k, label in [('turkce', 'Türkçe'), ('matematik', 'Matematik'),
                     ('fen', 'Fen'), ('sosyal', 'Sosyal'), ('toplam', 'TOPLAM')]:
        yon, delta = t['trendler'][k]
        emoji = trend_emoji.get(yon, '⚪')
        sign = '+' if delta > 0 else ''
        lines.append(f"  {emoji} *{label}*: {yon} ({sign}{delta:.1f} net)")

    lines.append("")

    if hedef:
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("🎯 *HEDEF ANALİZİ*")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━\n")
        if hedef['durum'] == 'hedef_uzerinde':
            lines.append(f"  ✅ *Hedef puanın ÜZERİNDESİN!* ({hedef['fark']:.1f} fark)")
            lines.append("  Bu trendi koru, daha üst hedef belirleyebiliriz.")
        else:
            lines.append(f"  📍 *Mevcut tahmin:* ~{hedef['mevcut_puan']:.0f}")
            lines.append(f"  🎯 *Hedef puan:* {hedef['hedef_puan']:.0f}")
            lines.append(f"  ⚡ *Eksik:* {hedef['fark']:.1f} puan")
            lines.append(f"  💪 *Gereken ek net:* ~{hedef['gereken_ek_net']:.1f} net")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 *Strateji Önerisi:*")

    # En düşüş trendde olan dersi vurgula
    en_kotu_trend = None
    en_kotu_delta = 0
    for k in ['matematik', 'fen', 'sosyal', 'turkce']:
        yon, delta = t['trendler'][k]
        if yon == 'azalıyor' and delta < en_kotu_delta:
            en_kotu_trend = k
            en_kotu_delta = delta
    if en_kotu_trend:
        lines.append(f"⚠️ *{en_kotu_trend.title()}* derste düşüş var ({en_kotu_delta:+.1f}) — bu öncelik.")

    # En artış trendde olan dersi vurgula
    en_iyi_trend = None
    en_iyi_delta = 0
    for k in ['matematik', 'fen', 'sosyal', 'turkce']:
        yon, delta = t['trendler'][k]
        if yon == 'artıyor' and delta > en_iyi_delta:
            en_iyi_trend = k
            en_iyi_delta = delta
    if en_iyi_trend:
        lines.append(f"🚀 *{en_iyi_trend.title()}* derste artış var ({en_iyi_delta:+.1f}) — devam et.")

    lines.append("")
    lines.append("_'puan tahmin [isim] hedef [bolum]' diyerek bolum bazli analiz al._")
    lines.append("_Bolumler: tip, muh, hukuk, iibf, psikoloji, ogretmenlik..._")

    return "\n".join(lines)


# ─── C3 (Oturum 22) — Yokatlas DB Tabanlı Gerçek Üniversite Önerisi ──────
# puan_tahmin.py statik BOLUM_HEDEFLER dict kullanıyordu, sadece tahmin
# yapıyordu. Şimdi universite_taban tablosunu sorgulayarak gerçek bölüm
# önerileri döndürüyoruz (öğrencinin puanına göre kategorize edilmiş).

async def nereye_girebilir(soz_no: Optional[str] = None, puan: Optional[float] = None,
                           puan_turu: str = "SAY", tolerans: float = 15.0,
                           max_sonuc: int = 15) -> dict:
    """
    Öğrencinin puanı ile girebileceği bölümleri kategorize et:
    - garanti: taban_puan + 5 puan aşağıda (güvenli yerleşme)
    - ihtimal_yuksek: taban_puan civarı (±3)
    - risk: taban_puan ÜSTÜNDE ama -8 içinde (zorlama)
    """
    # soz_no verildiyse öğrenciden puan çek
    if soz_no and not puan:
        sa = await db_fetchrow(
            "SELECT yerlesme_puani_ayt, yerlesme_puani FROM student_exam_analysis "
            "WHERE soz_no::text = $1::text",
            str(soz_no)
        )
        if sa:
            student = await db_fetchrow(
                "SELECT class_name FROM students WHERE soz_no::text = $1::text",
                str(soz_no)
            )
            class_name = (student["class_name"] or "") if student else ""
            if "12" in class_name or "Mez" in class_name.lower():
                puan_raw = sa["yerlesme_puani_ayt"]
            else:
                puan_raw = sa["yerlesme_puani"]
            if puan_raw:
                try:
                    puan = float(str(puan_raw).replace(",", "."))
                except Exception:
                    puan = None

    if not puan:
        return {"error": "Puan belirlenemedi"}

    # DB kapsam kontrolü
    min_db = await db_fetchrow(
        "SELECT MIN(taban_puan) AS p FROM universite_taban WHERE puan_turu = $1",
        puan_turu
    )
    min_db_v = float(min_db["p"]) if min_db and min_db["p"] else 0

    uyari = None
    if puan < min_db_v - 5:
        uyari = (f"Puanınız ({puan:.1f}) DB'deki en düşük bölümden ({min_db_v:.0f}) düşük. "
                 "Şu anda DB daha çok üst segment kapsıyor — orta/alt segmentler Yokatlas genişleme sonrası gelecek.")

    # 22.1k — 2025 yilina gore (en son yil), ama 4 yillik trend ekle
    rows = await db_fetch(
        """
        SELECT universite, bolum, sehir, tur, taban_puan, siralama, kontenjan
        FROM universite_taban
        WHERE puan_turu = $1 AND yil = 2025
          AND taban_puan BETWEEN $2::numeric AND $3::numeric
        ORDER BY taban_puan DESC
        LIMIT $4
        """,
        puan_turu, puan - tolerans, puan + tolerans, max_sonuc * 2,
    )

    # 2025 yok ise en son mevcut yil
    if not rows:
        rows = await db_fetch(
            """
            SELECT universite, bolum, sehir, tur, taban_puan, siralama, kontenjan
            FROM universite_taban
            WHERE puan_turu = $1
              AND taban_puan BETWEEN $2::numeric AND $3::numeric
            ORDER BY yil DESC, taban_puan DESC
            LIMIT $4
            """,
            puan_turu, puan - tolerans, puan + tolerans, max_sonuc * 2,
        )

    garanti, ihtimal, risk = [], [], []
    for r in rows:
        tp = float(r["taban_puan"])
        # 4 yillik trend — ayni universite+bolum ucun
        trend_rows = await db_fetch(
            """SELECT yil, taban_puan, siralama FROM universite_taban
               WHERE universite = $1 AND bolum = $2 AND puan_turu = $3
               ORDER BY yil""",
            r["universite"], r["bolum"], puan_turu
        )
        trend_4y = {str(t["yil"]): round(float(t["taban_puan"]), 2) for t in trend_rows}
        item = {
            "universite": r["universite"],
            "bolum": r["bolum"],
            "sehir": r["sehir"],
            "tur": r["tur"],
            "taban_puan_2025": tp,
            "siralama_2025": r["siralama"],
            "kontenjan": r["kontenjan"],
            "fark": round(puan - tp, 2),
            "trend_4_yil": trend_4y,  # {"2022": 495.2, "2023": 502.1, ...}
        }
        if puan >= tp + 5:
            garanti.append(item)
        elif puan >= tp - 3:
            ihtimal.append(item)
        else:
            risk.append(item)

    return {
        "ogrenci_puan": puan,
        "puan_turu": puan_turu,
        "garanti": garanti[:max_sonuc],
        "ihtimal_yuksek": ihtimal[:max_sonuc],
        "risk": risk[:max_sonuc // 2],
        "toplam_bulundu": len(rows),
        "DB_kapsam_uyari": uyari,
    }


async def hedef_bolum_ara(
    bolum_adi: str,
    puan_turu: str = "SAY",
    yil: int = 2025,
    limit: int = 200,
    sehir: str = "",
    tur: str = "",
) -> dict:
    """Bölüm bazlı: bu bölümü veren üniversiteler + taban puan aralığı.

    22.1n-neo bugfix:
    - LIMIT 25 → 200 (Fizik için 164 kayıt vardı, 25 kesiyor)
    - yil parametresi zorunlu (default 2025, karışık yıl sorunu)
    - sehir + tur opsiyonel filter (İzmir'deki Fizik, Vakıf Tıp vb.)
    """
    # Yil param guard
    try:
        yil = int(yil) if yil else 2025
    except: yil = 2025
    try:
        limit = min(500, max(10, int(limit)))
    except: limit = 200

    conds = ["puan_turu = $1", "bolum ILIKE $2", "yil = $3"]
    params = [puan_turu, f"%{bolum_adi}%", yil]
    if sehir:
        conds.append(f"sehir ILIKE ${len(params)+1}")
        params.append(f"%{sehir}%")
    if tur:
        conds.append(f"tur ILIKE ${len(params)+1}")
        params.append(f"%{tur}%")

    where = " AND ".join(conds)
    rows = await db_fetch(
        f"""SELECT universite, bolum, sehir, tur, taban_puan, siralama, kontenjan, yil
            FROM universite_taban WHERE {where}
            ORDER BY taban_puan DESC LIMIT {limit}""",
        *params
    )
    if not rows:
        # yil 2025 yoksa en son yılı dene
        alt_yil = await db_fetchval(
            "SELECT MAX(yil) FROM universite_taban WHERE puan_turu = $1 AND bolum ILIKE $2",
            puan_turu, f"%{bolum_adi}%"
        )
        if alt_yil and alt_yil != yil:
            return await hedef_bolum_ara(bolum_adi, puan_turu, int(alt_yil), limit, sehir, tur)
        return {"error": f"{bolum_adi} için veri bulunamadı", "bolum": bolum_adi, "yil": yil}

    puanlar = [float(r["taban_puan"]) for r in rows]
    # Sehir/tur dagilim istatistigi (özet)
    from collections import Counter
    sehir_cnt = Counter(r["sehir"] for r in rows if r["sehir"]).most_common(5)
    tur_cnt = Counter(r["tur"] for r in rows if r["tur"]).most_common()

    return {
        "bolum": bolum_adi,
        "puan_turu": puan_turu,
        "yil": yil,
        "universite_sayisi": len(rows),
        "min_puan": round(min(puanlar), 2),
        "max_puan": round(max(puanlar), 2),
        "ortalama_puan": round(sum(puanlar) / len(puanlar), 2),
        "medyan_puan": round(sorted(puanlar)[len(puanlar)//2], 2),
        "sehir_dagilimi": dict(sehir_cnt),
        "tur_dagilimi": dict(tur_cnt),
        "universiteler": [
            {
                "universite": r["universite"], "bolum": r["bolum"],
                "sehir": r["sehir"], "tur": r["tur"],
                "taban_puan": float(r["taban_puan"]), "siralama": r["siralama"],
                "kontenjan": r["kontenjan"],
            } for r in rows
        ],
    }


# Typing import (üstte yok, ekleyelim)
try:
    from typing import Optional
except Exception:
    pass


async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    soz_no = sys.argv[1]
    tahmin = await tahmin_et(soz_no)

    hedef = None
    if "--hedef" in sys.argv:
        hedef_puan = float(sys.argv[sys.argv.index("--hedef") + 1])
        alan = 'SAY'
        if "--bolum" in sys.argv:
            bolum = sys.argv[sys.argv.index("--bolum") + 1]
            if bolum in BOLUM_HEDEFLER:
                hedef_puan = BOLUM_HEDEFLER[bolum]['puan']
                alan = BOLUM_HEDEFLER[bolum]['alan']
        hedef = hedef_analiz(tahmin, hedef_puan, alan)
    elif "--bolum" in sys.argv:
        bolum = sys.argv[sys.argv.index("--bolum") + 1]
        if bolum in BOLUM_HEDEFLER:
            b = BOLUM_HEDEFLER[bolum]
            hedef = hedef_analiz(tahmin, b['puan'], b['alan'])

    print(format_rapor(tahmin, hedef))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
