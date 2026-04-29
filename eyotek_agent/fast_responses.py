"""
Fast Response Engine — Sik sorulan sorulara onceden hazirlanmis hizli yanitlar.

Ogrenci ve ogretmen WP'den yazdiginda, Claude API'ye gitmeden
yerelden aninda cevap verir. Sadece bilinmeyen/karmasik sorular Claude'a gider.

150 ogrenci gunluk 3-5 mesaj = 450-750 mesaj/gun
Bunlarin %80'i bu moduldeki kaliplarla cevaplanabilir = Claude API maliyeti %80 azalir
"""
import asyncio
import json
import re
from contextvars import ContextVar
from datetime import datetime, date, timedelta
from typing import Optional

# 22.1n-neo: routing_stats.handler_name takibi icin — try_fast_response icinde pattern
# match oldugunda handler adi set edilir, bridge okur ve DB'ye yazar.
# ContextVar → async-safe, concurrent request karismaz.
_fr_last_handler: ContextVar[str] = ContextVar('_fr_last_handler', default='')

def get_last_handler() -> str:
    """Bridge bunu cagirir fast_response sonrasinda. Bos string ise bilinmiyor."""
    try:
        return _fr_last_handler.get()
    except Exception:
        return ''

# ── Otomatik ogrenen stop-words yukleme ──────────────────────────────────────
_AUTO_STOP_WORDS = set()
try:
    from pathlib import Path as _P
    _sw_file = _P(__file__).parent / "learned_patterns" / "auto_stop_words.json"
    if _sw_file.exists():
        _AUTO_STOP_WORDS = set(json.loads(_sw_file.read_text(encoding='utf-8')))
except Exception:
    pass

# ── Türkçe Title Case ────────────────────────────────────────────────────────
_TR_LOWER = str.maketrans("ABCÇDEFGĞHIİJKLMNOÖPRSŞTUÜVYZ", "abcçdefgğhıijklmnoöprsştuüvyz")
_TR_UPPER = str.maketrans("abcçdefgğhıijklmnoöprsştuüvyz", "ABCÇDEFGĞHIİJKLMNOÖPRSŞTUÜVYZ")

def _tr_title(text: str) -> str:
    """BÜYÜK HARF Türkçe ismi Title Case'e çevir. Python title() İ/ı sorunlu."""
    words = text.split()
    result = []
    for w in words:
        if len(w) <= 1:
            result.append(w)
            continue
        first = w[0]  # Zaten büyük harf
        rest = w[1:].translate(_TR_LOWER)
        result.append(first + rest)
    return ' '.join(result)


# ── DB baglantisi (merkezi pool — db_pool.py) ────────────────────────────────
from db_pool import (
    get_pool as _get_pool,
    db_fetch as _q,
    db_fetchrow as _q1,
    db_fetchval as _qval,
)


# ═══════════════════════════════════════════════════════════════════════════════
# OGRENCI SORU KALIPLARI — ILK 30 SORU
# ═══════════════════════════════════════════════════════════════════════════════

# Her fonksiyon: soz_no alir, string dondurur. None donerse → Claude'a git.


async def web_kodu(name: str, phone: str = "") -> str:
    """
    Web chat icin OTP kodu uret ve kullaniciya ver.
    https://www.fermategitimkurumlari.com/fermatai iframe'e giris icin.
    """
    try:
        from web_chat_auth import request_otp
        result = await request_otp(phone)
        if result.get("success"):
            return result["message"]
        else:
            return f"⚠️ {result.get('message', 'Web kodu alinamadi.')}"
    except Exception as e:
        return f"Web kodu uretilemedi: {e}"


async def web_daveti_ogrenci(name: str, phone: str = "", trigger_msg: str = "") -> str:
    """
    Öğrenci sıkılma/terk sinyali verdiğinde (ChatGPT'ye gidiyom, sıkıcı, vs.)
    web arayüzünü öner + B4: frustration_log'a ekle (Neo onayıyla telafi mesajı gider).
    Neo Talimat #75 + #76 (18 Nisan 2026).
    """
    # B4: frustration tespit → telafi kuyruğuna ekle (pasif olana kadar sadece log)
    try:
        from frustration_telafi import log_frustration
        import asyncio as _aio_fr
        _aio_fr.create_task(log_frustration(phone, trigger_msg, ""))
    except Exception:
        pass

    fname = name.split()[0] if name else ""
    return (
        f"Dur {fname} 😊\n\n"
        f"Bak, WhatsApp hızlı mesajlar için güzel ama ben aslında "
        f"*https://www.fermategitimkurumlari.com/fermatai*'da daha detaylı konuşuyorum — "
        f"grafikler, tablolar, uzun anlatımlar hepsi orada.\n\n"
        f"İstersen *web kodu* yaz, sana 6 haneli kod göndereyim, "
        f"orada konuşalım. Sıkılmayacaksın söz veriyorum 💪\n\n"
        f"_Ya da burada devam edelim — ne istiyorsan sen bilirsin._ 🎯"
    )


async def ogm_yonlendir_response(message: str, name: str = "") -> str:
    """
    OGM Materyal yonlendirme fast response (22.1n-ogm).
    Ogrenci "TYT matematik soru bankasi", "AYT fizik 3 adim" gibi talepler yapinca
    direkt link + proaktif gorev.
    """
    import re as _re
    msg_lower = message.lower()

    # Ders tespiti
    ders_map = {
        "matematik": "Matematik", "mat": "Matematik", "geometri": "Matematik",
        "fizik": "Fizik", "fiz": "Fizik",
        "kimya": "Kimya", "kim": "Kimya",
        "biyoloji": "Biyoloji", "bio": "Biyoloji", "biyo": "Biyoloji",
        "turkce": "Turkce", "türkçe": "Turkce", "turk": "Turkce",
        "edebiyat": "TDE", "tde": "TDE",
        "tarih": "Tarih",
        "cografya": "Cografya", "coğrafya": "Cografya",
        "felsefe": "Felsefe",
        "ingilizce": "Ingilizce", "english": "Ingilizce",
    }
    ders = ""
    for key, val in ders_map.items():
        if _re.search(rf"\b{key}\b", msg_lower):
            ders = val
            break

    # Sinav turu tespiti
    sinav_turu = ""
    for s in ["tyt", "ayt", "ydt"]:
        if _re.search(rf"\b{s}\b", msg_lower):
            sinav_turu = s.upper()
            break

    # Tip tespiti
    tip = ""
    if _re.search(r"soru\s*banka|3\s*ad[iı]m|test", msg_lower):
        tip = "3_adim_soru_bankasi"
    elif _re.search(r"konu\s*[oö]zet|özet", msg_lower):
        tip = "konu_ozeti"
    elif _re.search(r"(konu\s*anlat|video)", msg_lower):
        tip = "konu_anlatim_video"
    elif _re.search(r"(deneme|puan\s*hesapla|cikmis|çıkmış)", msg_lower):
        tip = "hub_link"

    try:
        from ogm_catalog import yonlendir
        results = await yonlendir(ders=ders, sinav_turu=sinav_turu, tip=tip)
    except Exception:
        return None  # Hata olursa Claude'a

    if not results:
        return None  # Eşleşme yoksa Claude'a

    first = name.split()[0] if name else ""
    hitap = f"*{first}* " if first else ""

    # Tekil link, direkt sunum
    if len(results) == 1:
        r = results[0]
        return (
            f"🎓 {hitap}işte tam aradığın: *{r['konu_adi']}*\n\n"
            f"{r['icerik_ozet']}\n\n"
            f"🔗 {r['url']}\n\n"
            f"_Hedef: 20 soru çöz, zorlandıklarını bana getir — birlikte çözelim_ 💪"
        )

    # Çoklu link → top 3 sunum
    lines = [f"🎓 {hitap}MEB OGM resmi kaynakları:"]
    for r in results[:3]:
        emoji = {"3_adim_soru_bankasi": "📝", "konu_ozeti": "📚", "hub_link": "🔗",
                 "konu_anlatim_video": "🎥"}.get(r["icerik_tipi"], "📎")
        lines.append(f"\n{emoji} *{r['konu_adi']}*\n   {r['url']}")
    lines.append(f"\n_Önerim: Önce konu özetine bak, sonra 3 Adım Soru Bankası'ndan "
                 f"pratik yap. Takıldığın yerleri bana getir._ 🎯")
    return "\n".join(lines)


async def sinav_bilgi(name: str, message: str) -> str:
    """TYT/AYT/LGS soru sayısı, dağılımı, tarih ve geri sayım bilgisi."""
    msg_lower = message.lower()
    from datetime import date

    # YKS/TYT/AYT tarihi ve geri sayım
    # Oturum 25.8 fix — Tek kaynak (sinav_takvimi.py)
    from sinav_takvimi import TYT_DATE as yks_date, LGS_DATE as lgs_date
    today = date.today()

    # "ne zaman", "kaç gün kaldı", "tarih" soruları
    is_date_question = any(w in msg_lower for w in ['ne zaman', 'kac gun', 'kaç gün', 'tarih', 'kaldi', 'kaldı', 'gun kald', 'gün kald'])

    if is_date_question:
        if 'lgs' in msg_lower:
            days = (lgs_date - today).days
            return (
                f"📅 *LGS 2026 Tarihi*\n\n"
                f"🗓️ *{lgs_date.strftime('%d Haziran %Y')}* (Pazar)\n\n"
                f"⏰ Kalan: *{days} gün*\n\n"
                f"_Her gün değerli {name.split()[0] if name else ''}! Hedefe odaklan._ 💪"
            )
        else:
            from sinav_takvimi import AYT_DATE
            days_tyt = (yks_date - today).days
            days_ayt = (AYT_DATE - today).days
            return (
                f"📅 *YKS 2026 Tarihi*\n\n"
                f"🗓️ *TYT:* {yks_date.strftime('%d Haziran %Y')} (Cumartesi)\n"
                f"🗓️ *AYT:* {AYT_DATE.strftime('%d Haziran %Y')} (Pazar)\n\n"
                f"⏰ TYT'ye kalan: *{days_tyt} gün*\n"
                f"⏰ AYT'ye kalan: *{days_ayt} gün*\n\n"
                f"_Her gün bir adım daha yakın {name.split()[0] if name else ''}! Sen yapabilirsin._ 💪🎯"
            )

    if "lgs" in msg_lower:
        return (
            f"📝 *LGS Soru Dağılımı*\n\n"
            f"---\n\n"
            f"*Sözel Oturum* _(75 dakika)_\n"
            f"  📖 Türkçe: *20* soru\n"
            f"  📜 T.C. İnkılap Tarihi: *10* soru\n"
            f"  🕌 Din Kültürü: *10* soru\n"
            f"  🌐 İngilizce: *10* soru\n\n"
            f"*Sayısal Oturum* _(80 dakika)_\n"
            f"  📐 Matematik: *20* soru\n"
            f"  🔬 Fen Bilimleri: *20* soru\n\n"
            f"📊 *Toplam: 90 soru*\n\n"
            f"---\n\n"
            f"_Hangi derse odaklanmak istiyorsun {name}?_ 🎯"
        )

    if "ayt" in msg_lower:
        return (
            f"📝 *AYT Soru Dağılımı (2026)*\n\n"
            f"---\n\n"
            f"*Toplam:* 160 soru, *180 dakika*\n"
            f"_(Öğrenci kendi alanına göre 80 soru çözer)_\n\n"
            f"*SAY (Sayısal):*\n"
            f"  📐 Matematik: *30* + Geometri: *10* = *40* soru\n"
            f"  ⚡ Fizik: *14* soru\n"
            f"  🧪 Kimya: *13* soru\n"
            f"  🧬 Biyoloji: *13* soru\n\n"
            f"*EA (Eşit Ağırlık):*\n"
            f"  📐 Matematik: *40* + TDE-Sos1: *40* = *80* soru\n\n"
            f"*SÖZ (Sözel):*\n"
            f"  📖 TDE-Sos1: *40* + Sosyal2: *40* = *80* soru\n\n"
            f"---\n\n"
            f"_Sen hangi puan türündesin {name}?_ 🎯"
        )

    # TYT veya genel YKS
    return (
        f"📝 *TYT Soru Dağılımı (2026)*\n\n"
        f"---\n\n"
        f"*Toplam:* 120 soru, *165 dakika*\n\n"
        f"  📖 *Türkçe:* *40* soru\n"
        f"  📐 *Matematik:* *40* soru _(~30 mat + ~10 geometri)_\n"
        f"  🌍 *Sosyal Bilimler:* *20* soru\n"
        f"     _(Tarih 5, Coğrafya 5, Felsefe 5, Din 5)_\n"
        f"  🔬 *Fen Bilimleri:* *20* soru\n"
        f"     _(Fizik 7, Kimya 7, Biyoloji 6)_\n\n"
        f"---\n\n"
        f"_AYT dağılımı için 'AYT kaç soru' yazabilirsin._ 🎯"
    )


async def ogrenci_son_deneme(soz_no: int, name: str) -> str:
    """'Son denemem nasil?', 'son sinav sonucum' — Claude kalitesinde gorsel"""
    # Son 2 deneme — trend icin
    rows = await _q(
        "SELECT exam_name, exam_date, turkce, matematik, geometri, fizik, kimya, biyoloji, toplam "
        "FROM student_exams WHERE soz_no=$1 ORDER BY exam_date DESC NULLS LAST LIMIT 2", soz_no)
    if not rows:
        first = name.split()[0] if name else ""
        return (
            f"{first}, sınav verin henüz sistemde görünmüyor 📝\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Bu durum 2 sebepten olabilir:\n"
            "• Denemeye henüz girmedin veya\n"
            "• Sonuçlar sisteme yansımadı\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "💡 *Bu arada seninle neler yapabiliriz?*\n"
            "📚 Konu anlatımı — örn: _\"türev nedir\"_\n"
            "📸 Çıkmış soru — örn: _\"fizik çıkmış sorular\"_\n"
            "🎯 Hedef planlama — _\"50K net için plan\"_\n\n"
            "_Ne hakkında konuşalım?_ ✨"
        )
    e = rows[0]
    first = name.split()[0] if name else ""
    lines = [
        f"{first}, işte son deneme tablon 📊\n",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"📝 *{e['exam_name']}*",
        f"_{e['exam_date']}_ | Toplam: *{e['toplam']:.1f}* net",
        "━━━━━━━━━━━━━━━━━━━━━━\n",
    ]

    # Ders bazli — renk kodlu
    subjects = [
        ("Türkçe", e.get('turkce'), 40, "📖"),
        ("Matematik", e.get('matematik'), 30, "📐"),
        ("Geometri", e.get('geometri'), 10, "📏"),
        ("Fizik", e.get('fizik'), 7, "⚡"),
        ("Kimya", e.get('kimya'), 7, "🧪"),
        ("Biyoloji", e.get('biyoloji'), 6, "🧬"),
    ]
    # Oturum Mentenans: en yuksek net'li dersi tespit et (akademik_tebrik icin)
    _best_ders_tyt = None
    _best_ratio_tyt = 0.0
    _best_net_tyt = 0.0
    for s, v, max_net, ic in subjects:
        if v is not None and v > 0:
            ratio = v / max_net if max_net > 0 else 0
            if ratio >= 0.7:
                emoji = "🟢"
            elif ratio >= 0.4:
                emoji = "🟡"
            else:
                emoji = "🔴"
            lines.append(f"{ic} *{s}*: {emoji} *{v:.1f}*/{max_net} net")
            # En yuksek ratio (max'a goranlikta) — tebrik icin
            if ratio > _best_ratio_tyt and v >= 5:
                _best_ratio_tyt = ratio
                _best_ders_tyt = s
                _best_net_tyt = v

    # Onceki sinavla trend
    if len(rows) >= 2:
        prev_total = rows[1]['toplam'] or 0
        curr_total = e['toplam'] or 0
        fark = curr_total - prev_total
        if fark > 0.5:
            lines.append(f"\n📈 *Önceki sınava göre: +{fark:.1f} net* 🎉 Tebrikler!")
        elif fark < -0.5:
            lines.append(f"\n📉 *Önceki sınava göre: {fark:.1f} net*")
            lines.append(f"_Düşüş geçici olabilir, sebebi konuşalım._")
        else:
            lines.append(f"\n➡️ Önceki sınava göre istikrarlı ({fark:+.1f} net)")

    # Pedagojik yorum
    toplam = e['toplam'] or 0
    lines.append("")
    if toplam >= 100:
        lines.append(f"🏆 *Muhteşem performans {first}!* Bu tempoda üst sıralardasın.")
    elif toplam >= 80:
        lines.append(f"✨ *Çok iyi gidiyorsun!* Zayıf alanları toparla, yıldızlaşacaksın.")
    elif toplam >= 60:
        lines.append(f"💪 *İyi bir zemin var.* Biraz daha odaklanma yeter.")
    elif toplam >= 40:
        lines.append(f"📌 *Gelişim alanın net belli.* Birlikte çalışıp yukarı çekebiliriz.")
    else:
        lines.append(f"🌱 *Her şey bir başlangıç.* Zayıf konulardan başlayıp inşa edelim!")

    # Oturum Mentenans (21 Nisan 14:20) — akademik_tebrik (en guclu TYT dersi)
    # Toplam 60+ ve en iyi ders ratio 0.5+ ise tebrik
    if toplam >= 60 and _best_ders_tyt and _best_ratio_tyt >= 0.5:
        try:
            from fast_response_enrich import akademik_tebrik
            lines.append(akademik_tebrik(_best_ders_tyt, _best_net_tyt, name))
        except Exception:
            pass

    # 12.SAY/Mezun/EA için AYT hatırlatma
    try:
        ayt_check = await _q1(
            "SELECT ham_puan_ayt FROM student_exam_analysis WHERE soz_no::text=$1::text",
            str(soz_no))
        if ayt_check and ayt_check.get('ham_puan_ayt'):
            lines.append("")
            lines.append(f"🎯 *AYT birleştir puanın da var!*")
            lines.append(f"_\"AYT analiz\" yaz → AYT detayını gör_")
    except Exception:
        pass

    # Yonlendirme — eylem odakli
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 *Şimdi ne yapalım?*")
    lines.append(f"🎯 _\"zayıf konularım\"_ → neye odaklanmalı")
    lines.append(f"📊 _\"son 3 denememi kıyasla\"_ → trend grafiği")
    lines.append(f"📅 _\"çalışma planı yap\"_ → kişisel program")
    return "\n".join(lines)


async def ogrenci_ayt_deneme(soz_no: int, name: str) -> str:
    """AYT deneme — sadece student_exam_analysis (birlestir) kullanir.
    student_exams [AYT]% KULLANMAYIZ (TYT kopyasi, yaniltici).
    """
    import json as _json
    analiz = await _q1(
        "SELECT ham_puan_ayt, yerlesme_puani_ayt, katilan_sinav_ayt, sinav_sayisi_ayt, "
        "ders_netleri_ayt "
        "FROM student_exam_analysis WHERE soz_no::text = $1::text",
        str(soz_no))

    if not analiz or not analiz.get('ham_puan_ayt'):
        return (
            f"📝 *{name} — AYT Deneme*\n\n"
            f"Henuz sisteme yuklu AYT birlestir analizi yok.\n"
            f"AYT'ye 12.SAY/EA/Mezun ogrenciler girer. 11.sinifsan henuz dogal.\n\n"
            f"_TYT sonuclarin icin 'son denemem' yazabilirsin._ 🎯"
        )

    katilan = analiz.get('katilan_sinav_ayt') or 1
    try:
        katilan = int(katilan)
    except Exception:
        katilan = 1
    katilan = max(1, katilan)

    lines = [f"📝 *{name} — AYT Birlestir Analizi*\n"]
    lines.append(
        f"🏅 *Resmi Puan:* Ham *{analiz['ham_puan_ayt']}* | Yerlesme *{analiz['yerlesme_puani_ayt']}*"
    )
    lines.append(f"📊 *Katilim:* {analiz.get('katilan_sinav_ayt','?')}/{analiz.get('sinav_sayisi_ayt','?')} AYT sinavi\n")

    netler_raw = analiz.get('ders_netleri_ayt')
    if isinstance(netler_raw, str):
        try:
            netler_raw = _json.loads(netler_raw)
        except Exception:
            netler_raw = []

    by_ders = {}
    for n in netler_raw or []:
        d = (n.get('ders') or '').strip()
        if not d or d.lower() in ('toplam', 'total'):
            continue
        if not (d.startswith('YKS_') or d.startswith('AYT_')):
            continue
        try:
            net = float(str(n.get('net', 0)).replace(',', '.'))
            soru = float(str(n.get('soru', 0)).replace(',', '.'))
        except Exception:
            continue
        if d not in by_ders or soru > by_ders[d]['soru']:
            by_ders[d] = {'net': net, 'soru': soru}

    # Sadece net>0.05 olan dersleri goster (0.0 olanlar ogrencinin girmedigi alan)
    aktif_dersler = {d: v for d, v in by_ders.items()
                     if (v['net'] / max(katilan, 1)) >= 0.05}

    if aktif_dersler:
        lines.append(f"📚 *Sinav Basi Ortalama Netler:*")

        def _ders_emoji(ders_adi: str) -> str:
            d = ders_adi.lower()
            if 'matem' in d: return '🔢'
            if 'fizik' in d: return '⚛️'
            if 'kimya' in d: return '🧪'
            if 'biyo' in d: return '🧬'
            if 'geometr' in d: return '📐'
            if 'edeb' in d or 'tdili' in d or 'turkce' in d or 'türkçe' in d: return '📖'
            if 'tarih' in d: return '🏛️'
            if 'cograf' in d or 'coğraf' in d: return '🌍'
            if 'felsefe' in d: return '💭'
            if 'din' in d: return '🕌'
            if 'sosyal' in d or 'sos' in d: return '🌐'
            if 'fen' in d: return '🔬'
            return '📘'

        # Oturum Mentenans: ders basi en yuksek ort_net'i akilla — tebrik icin
        _best_ders = None
        _best_net = 0.0
        for d, v in aktif_dersler.items():
            ders_kisa = d.replace('YKS_', '').replace('AYT_', '')
            ort_net = v['net'] / katilan
            ort_soru = v['soru'] / katilan
            emoji = _ders_emoji(ders_kisa)
            ratio = ort_net / ort_soru if ort_soru > 0 else 0
            dot = "🟢" if ratio >= 0.5 else ("🟡" if ratio >= 0.25 else "🔴")
            lines.append(f"  {dot} {emoji} *{ders_kisa.title()}:* *{ort_net:.1f}* / {ort_soru:.0f} net")
            if ort_net > _best_net:
                _best_net = ort_net
                _best_ders = ders_kisa

        # Oturum Mentenans (21 Nisan 14:15) — akademik_tebrik (fast_response_enrich)
        # En guclu derste >=10 net varsa ekstra motive edici satir ekle
        if _best_ders and _best_net >= 10:
            try:
                from fast_response_enrich import akademik_tebrik
                lines.append("")
                lines.append(akademik_tebrik(_best_ders, _best_net, name))
            except Exception:
                pass

    try:
        yp = float(str(analiz['yerlesme_puani_ayt']).replace(',', '.'))
    except Exception:
        yp = 0
    if yp >= 500:
        lines.append(f"\n🏆 AYT'de *cok iyi* gidiyorsun! Hedefin yakin.")
    elif yp >= 400:
        lines.append(f"\n✅ Iyi ilerliyorsun. Zayif derslere odaklan, daha da yukselirsin.")
    elif yp >= 300:
        lines.append(f"\n📌 Gelisim alanin var. Hangi derste zorlaniyorsun?")
    elif yp > 0:
        lines.append(f"\n💪 Her deneme bir firsat — tek tek ilerle!")

    lines.append(f"\n_'AYT zayif konularim' veya 'TYT son denemem' yazabilirsin._ 🎯")
    return "\n".join(lines)


async def ogrenci_deneme_kiyasla(soz_no: int, name: str, count: int = 3) -> str:
    """'Son 3 denememi kiyasla', 'gelismem nasil'"""
    rows = await _q(
        "SELECT DISTINCT ON (exam_date) exam_name, exam_date, turkce, matematik, geometri, fizik, kimya, biyoloji, toplam "
        "FROM student_exams WHERE soz_no=$1 AND toplam > 5 ORDER BY exam_date DESC NULLS LAST LIMIT $2",
        soz_no, count)
    if len(rows) < 2:
        return await ogrenci_son_deneme(soz_no, name)
    rows.reverse()  # eskiden yeniye

    lines = [f"📊 *{name} — Son {len(rows)} Deneme Trendi*\n"]
    for i, r in enumerate(rows, 1):
        toplam = r['toplam'] or 0
        # Öncekiyle karşılaştır
        if i > 1:
            prev = rows[i-2]['toplam'] or 0
            diff = toplam - prev
            trend = f"📈 +{diff:.1f}" if diff > 0 else f"📉 {diff:.1f}" if diff < 0 else "➡️ ="
        else:
            trend = ""

        lines.append(f"*{i}. {r['exam_name'][:25]}* ({r['exam_date']})")
        # Ders detayları
        dersler = []
        for key, label in [('turkce','Tur'), ('matematik','Mat'), ('fizik','Fiz'),
                           ('kimya','Kim'), ('biyoloji','Bio')]:
            v = r.get(key)
            if v and v > 0:
                dersler.append(f"{label}: {v:.1f}")
        lines.append(f"   Toplam: *{toplam:.1f}* net {trend}")
        if dersler:
            lines.append(f"   {' | '.join(dersler)}")
        lines.append("")

    # Genel trend
    first, last = rows[0], rows[-1]
    diff = (last['toplam'] or 0) - (first['toplam'] or 0)
    if diff > 5:
        lines.append(f"✅ *Toplam {diff:+.1f} net artis! Harika gidiyorsun!*")
    elif diff < -5:
        lines.append(f"\nToplam net {diff:+.1f} dusmus, biraz daha calisma gerekiyor.")
    else:
        lines.append(f"\nToplam net stabil ({diff:+.1f}).")

    # Ders bazli trend
    for ders, col in [("Matematik", "matematik"), ("Fizik", "fizik"), ("Turkce", "turkce"), ("Kimya", "kimya")]:
        f_val = first.get(col) or 0
        l_val = last.get(col) or 0
        d = l_val - f_val
        if abs(d) >= 3:
            emoji = "yukselis" if d > 0 else "dusus"
            lines.append(f"  {ders}: {f_val:.1f} -> {l_val:.1f} ({emoji})")

    return "\n".join(lines)


async def ogrenci_lgs_konu_durumu(soz_no: int, name: str) -> str:
    """LGS öğrencisi için konu durumu fast response (Oturum 23 FAZ 1 A2).

    Mevcut topic_tracker'da hata yüzdeleri 0 olduğu için sıralanabilir veri yok.
    Bunun yerine ders bazlı müfredat + kalan gün + son sınav puanı + motive edici ton.
    """
    try:
        from lgs_helper import get_lgs_konu_durumu, LGS_SINAV_DAGILIM
        d = await get_lgs_konu_durumu(soz_no)
        if not d.get("is_lgs"):
            return ""  # fallback, caller YKS akışına gider
        first = name.split()[0] if name else "arkadaşım"
        kalan = d.get("kalan_gun", 0)
        son = d.get("son_sinav") or {}
        toplam = son.get("toplam")

        lines = [f"📘 *{first} — LGS Müfredat Durumun*", ""]
        if kalan > 0:
            lines.append(f"⏳ *LGS'ye kalan gün: {kalan}*")
        if toplam is not None:
            lines.append(f"📊 Son sınav toplamı: *{toplam:.1f}*")
        lines.append("")
        lines.append("*6 ders, 90 soru* — ders başına öncelikli konular:")
        lines.append("")

        for ders, info in d.get("dersler", {}).items():
            mufredat = info.get("mufredat", [])
            soru = info.get("soru_sayisi", 0)
            lines.append(f"▸ *{ders}* ({soru} soru, {len(mufredat)} ana konu)")
            # İlk 3 konu göster
            for konu in mufredat[:3]:
                lines.append(f"   • {konu}")
            if len(mufredat) > 3:
                lines.append(f"   • ... ve {len(mufredat)-3} konu daha")
            lines.append("")

        lines.append(f"💡 *Öneri:* {d.get('oneri', 'Her hafta 1 konu + düzenli deneme.')}")
        lines.append("")
        lines.append("_Bir dersi detaylı görmek ister misin? Ör: \"matematik konularım\" yaz._")
        return "\n".join(lines)
    except Exception as e:
        return ""  # Hata durumunda YKS akışına düş


async def ogrenci_zayif_konular(soz_no: int, name: str, ders_filtre: str = "", sinav_turu: str = "") -> str:
    """'Zayif konularim neler?', 'neye calismam lazim', 'fizikteki eksiklerim'
    22.1n-bugfix: sinav_turu (TYT/AYT/YDT) parametresi — ogrenci 'AYT kimya zayif' dediginde
    sadece AYT Kimya gelir; onceden TYT Kimya da geliyordu (kafa karisikligi).
    25.8 fix: 'fen' / 'sosyal' / 'sayisal' bilesik filtre destegi (Deren 07:14 olayi:
    'fen kismindaki' dedi, bot Geometri/Mat/Turkce verdi)."""
    # sinav_turu normalize
    st_filter = ""
    if sinav_turu:
        su = sinav_turu.upper().strip()
        if su in ("TYT", "AYT", "YDT"):
            st_filter = su

    # 25.8 fix: bileşik ders filtresi — "fen" → 3 ders, "sosyal" → 4 ders
    DERS_BILESIK = {
        "fen": ["fizik", "kimya", "biyoloji"],
        "sosyal": ["tarih", "cografya", "felsefe", "din"],
        "sosyal2": ["tarih", "cografya", "felsefe", "din"],
        "say": ["matematik", "geometri", "fizik", "kimya", "biyoloji"],
        "sayisal": ["matematik", "geometri", "fizik", "kimya", "biyoloji"],
        "ea": ["matematik", "edebiyat", "tarih", "cografya"],
        "esit agirlik": ["matematik", "edebiyat", "tarih", "cografya"],
        "soz": ["edebiyat", "tarih", "cografya", "felsefe", "din"],
    }
    bilesik_listesi = DERS_BILESIK.get((ders_filtre or "").lower().strip(), None)

    # WHERE clause dinamik
    # 23 Nisan E6: 'metadata' status'lü satırları haric tut (1193 kayıt temizlendi)
    conds = ["soz_no=$1", "tamamlandi=FALSE", "COALESCE(status,'') != 'metadata'"]
    params = [soz_no]
    idx = 2
    if bilesik_listesi:
        # Birden fazla ders OR'la
        ph = ",".join(f"${idx + i}" for i in range(len(bilesik_listesi)))
        conds.append(f"LOWER(ders) = ANY(ARRAY[{ph}])")
        params.extend([d.lower() for d in bilesik_listesi])
        idx += len(bilesik_listesi)
    elif ders_filtre:
        conds.append(f"LOWER(ders) LIKE LOWER(${idx})")
        params.append(f"%{ders_filtre}%")
        idx += 1
    if st_filter:
        # sinav_turu kolonu, yoksa ders icinde metin gecebilir ("TYT Kimya" gibi)
        conds.append(f"(sinav_turu = ${idx} OR ders ILIKE ${idx+1})")
        params.append(st_filter)
        params.append(f"%{st_filter}%")
        idx += 2

    where = " AND ".join(conds)
    rows = await _q(
        f"SELECT ders, konu, sinav_hata_sayisi, sinav_hata_yuzdesi, status FROM student_topic_tracker "
        f"WHERE {where} ORDER BY sinav_hata_yuzdesi ASC LIMIT 8",
        *params)
    # sinav_hata_yuzdesi aslinda BASARI yuzdesi — dusuk olan = zayif konu
    if not rows:
        # 22.1n-irem-bugfix: AYT+ders icin tracker verisi yoksa, student_exams AYT net'ten
        # ders ortalamasi + akilli yonlendirme ver (generic "veri yok" yerine)
        first_name = name.split()[0] if name else ""
        if st_filter == "AYT" and ders_filtre:
            try:
                # student_exams schema: kolon bazli (turkce, matematik, fizik, kimya, biyoloji...)
                # exam_type='AYT' filtresi ile ders kolon ortalamasi
                ds_lower = ders_filtre.lower().strip()
                ds_col_map = {
                    "fizik": "fizik", "kimya": "kimya", "biyoloji": "biyoloji",
                    "matematik": "matematik", "mat": "matematik",
                    "geometri": "geometri", "edebiyat": "turkce", "tde": "turkce",
                    "tarih": "tarih", "cografya": "cografya", "coğrafya": "cografya",
                    "felsefe": "felsefe",
                }
                col = ds_col_map.get(ds_lower)
                netler_list = []
                if col:
                    ayt_rows = await _q(
                        f"SELECT {col} as net FROM student_exams WHERE soz_no=$1 "
                        f"AND exam_type='AYT' AND {col} IS NOT NULL "
                        f"ORDER BY exam_date DESC LIMIT 5",
                        soz_no
                    )
                    for ar in ayt_rows:
                        v = ar.get('net')
                        if v is not None:
                            try:
                                netler_list.append(float(v))
                            except: pass
                if netler_list:
                    ort = sum(netler_list)/len(netler_list)
                    maks = {"fizik":14,"kimya":13,"biyoloji":13,"matematik":40,"mat":40,"edebiyat":24,"tde":24,"tarih":10,"cografya":6,"coğrafya":6,"felsefe":12}.get(ds_lower, 14)
                    yuzde = (ort/maks)*100 if maks else 0
                    durum = "🔴 Zayif" if yuzde < 30 else ("🟡 Orta" if yuzde < 60 else "🟢 Iyi")
                    return (
                        f"🎯 *{first_name} — AYT {ders_filtre.title()} Ozeti*\n\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"📊 *Son AYT Sinavlarinda*\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"📚 *Ortalama Netin:* *{ort:.1f}* / {maks}\n"
                        f"📈 *Doluluk:* *%{yuzde:.0f}* — {durum}\n"
                        f"🔢 *Sinav Sayisi:* {len(netler_list)}\n\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"💡 *Not:* AYT {ders_filtre.title()} icin konu bazli analiz hazir degil.\n"
                        f"Deneme katilim artikca otomatik olusacak.\n\n"
                        f"Simdilik TYT {ders_filtre.title()} tracker'inda 8 konu var — oraya da bakayim mi?\n"
                        f"_Veya bir konu ismi yaz, birlikte calisalim._ 💪"
                    )
            except Exception:
                pass
        # Genel fallback — veri yok
        return (
            f"🎯 *{name} — Konu Analizi*\n\n"
            f"Henuz yeterli deneme verisi olmadigi icin konu analizi olusturulamadi.\n"
            f"Deneme sinavlarina katildikca zayif ve guclu konularin otomatik belirlenecek.\n\n"
            f"_Simdilik hangi derste zorlandigini soyle, birlikte calisalim!_ 📚"
        )

    first = name.split()[0] if name else ""
    ders_filtre_text = f" — {ders_filtre.title()}" if ders_filtre else ""
    lines = [
        f"{first}, işte önceliklerin 🎯\n",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"🔥 *GELIŞİM HARİTASI{ders_filtre_text}*",
        "━━━━━━━━━━━━━━━━━━━━━━\n",
    ]

    # Cikmis soru sayilarini bul — her konu icin
    konu_cikmis = {}
    try:
        konu_list = set((r['konu'] or '').lower()[:30] for r in rows)
        cikmis_rows = await _q(
            "SELECT ders, konu, COUNT(*) as cnt FROM rag_content "
            "WHERE kaynak LIKE '%%OGM Vision%%' GROUP BY ders, konu"
        )
        for cr in cikmis_rows:
            key = (cr['konu'] or '').lower()[:30]
            konu_cikmis[key] = cr['cnt']
    except Exception:
        pass

    # Bug fix 23 Nisan: Sadece GERÇEKTEN ZAYIF konuları göster.
    # Eski: basari<60 tüm konular → %67'lik konuyu da "İyi öncelik" diye
    # gösteriyordu, kullanıcı "eksik değil bu" diye itiraz etti (Enes vakası).
    # Yeni: status='yukselis' satırları + basari>=80 konular FİLTRE.
    _filtered_rows = []
    for r in rows:
        _b = r.get('sinav_hata_yuzdesi', 0) or 0
        _st = r.get('status', '') or ''
        _konu = (r.get('konu') or '').lower()
        # Bug fix 23 Nisan — "Ortalama X/Y net" satırları METADATA, gerçek konu değil
        # (Enes vakası: "AYT Ortalama 2.8/14 net" diye konu gösterdi, bu bir konu değil)
        if "ortalama" in _konu and "net" in _konu:
            continue
        # Ortalama/yukselis status'lü satırları atla (metadata, konu değil)
        if _st in ('yukselis', 'dusus', 'bekliyor') and _b >= 85:
            continue
        # %80+ başarı = zaten iyi, "eksik" demek yanlış
        if _b >= 80:
            continue
        _filtered_rows.append(r)

    # Filtreli liste boşsa → "bu derste genel başarınız iyi" mesajı
    if not _filtered_rows:
        first_name = name.split()[0] if name else ""
        ders_text = f"{ders_filtre.title()} " if ders_filtre else ""
        return (
            f"🎯 *{first_name} — {ders_text}Konu Analizi*\n\n"
            f"Güzel haber: {ders_text}alanında *belirgin eksik konu görünmüyor!* 🟢\n"
            f"Mevcut tracker verilerinde başarı yüzdesi %80+ seviyede.\n\n"
            f"💡 *Daha derin analiz için:*\n"
            f"  • Yeni deneme girdikçe tracker otomatik güncellenir\n"
            f"  • _\"son denemem\"_ → detaylı net analizi\n"
            f"  • Belirli bir konuda zorlanıyorsan adını yaz, birlikte çalışalım\n\n"
            f"_Şu an güçlü derslerini daha da ileriye taşımaya odaklanalım mı?_ 💪"
        )

    rows = _filtered_rows

    for i, r in enumerate(rows, 1):
        basari = r.get('sinav_hata_yuzdesi', 0) or 0
        hata = r.get('sinav_hata_sayisi', 0) or 0
        if basari < 30:
            emoji = "🔴"
            oncelik_txt = "ACİL"
        elif basari < 60:
            emoji = "🟡"
            oncelik_txt = "Orta"
        else:
            emoji = "🟢"
            oncelik_txt = "Takip"  # "İyi öncelik" demek yanıltıcıydı, "Takip" daha doğru
        status_icon = " ✍️" if r.get('status') == 'calisiyor' else ""

        # Cikmis soru sayisi (eger varsa)
        cikmis_bilgi = ""
        konu_lower = (r['konu'] or '').lower()[:30]
        if konu_lower in konu_cikmis:
            cnt = konu_cikmis[konu_lower]
            if cnt >= 3:
                cikmis_bilgi = f" 📸 _{cnt} çıkmış soru var!_"

        lines.append(f"*{i}.* {emoji} *{r['ders']}* · {r['konu'][:35]}{status_icon}")
        lines.append(f"    Başarın: *%{basari:.0f}* | {oncelik_txt} öncelik{cikmis_bilgi}")
        lines.append("")

    # Strateji onerisi + aksiyon
    en_zayif = rows[0] if rows else None
    if en_zayif:
        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"💡 *Stratejik Öncelik*")
        lines.append(f"*{en_zayif['ders']}* — _{en_zayif['konu'][:35]}_")
        lines.append("")
        lines.append("Bu konudan:")
        lines.append(f"📚 _\"{en_zayif['konu'][:20]} nedir\"_ → konu anlatımı")
        lines.append(f"📸 _\"{en_zayif['konu'][:20]} çıkmış soru\"_ → gerçek YKS sorusu")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"_{first}, birlikte çözelim — nereden başlayalım?_ 💪")
    return "\n".join(lines)


async def ogretmen_bugun_ders(staff_name: str) -> Optional[str]:
    """'Bugün hangi derslerim var', 'bugünkü programım'"""
    gun_map = {0:"Pazartesi",1:"Salı",2:"Çarşamba",3:"Perşembe",4:"Cuma",5:"Cumartesi",6:"Pazar"}
    today = date.today()
    gun = gun_map.get(today.weekday(), "?")

    if gun == "Cuma":
        return (
            f"📅 Bugun *{gun}* — kurumumuzda *ders yok!* 🎉\n\n"
            f"Cuma gunleri Turkiye geneli *deneme sinavlari* yapilmaktadir.\n"
            f"Ogretmenlerimizin ortak izin gunudur.\n\n"
            f"_Iyi dinlenmeler!_"
        )

    search = staff_name.split()[0] if staff_name else ""
    rows = await _q(
        "SELECT saat, sinif, ders FROM teacher_timetable "
        "WHERE ogretmen_ad ILIKE $1 AND gun = $2 ORDER BY saat",
        f"%{search}%", gun)

    if not rows:
        return f"📅 Bugun *{gun}* — sizin icin ders kaydi bulunamadi."

    lines = [f"📅 *Bugun — {gun} ({today.strftime('%d.%m.%Y')})*\n"]
    for r in rows:
        lines.append(f"  🕐 {r['saat']} → *{r['sinif']}* | {r['ders']}")
    lines.append(f"\n_Toplam {len(rows)} ders ({round(len(rows)*35/60,1)} saat)_")
    return "\n".join(lines)


async def ogrenci_devamsizlik(soz_no: int, name: str) -> str:
    """'Devamsizligim kac saat?', 'kac gun gelmedim'"""
    row = await _q1("SELECT toplam_saat FROM devamsizlik_sayisi WHERE soz_no=$1", soz_no)
    if not row:
        return f"📋 *{name} — Devamsizlik Durumu*\n\nDevamsizlik kaydimiz yok. Duzenli devam ediyorsun! ✅\n\n_Boyle devam et!_"

    saat = row['toplam_saat']
    if saat < 50:
        emoji = "🟢"
        yorum = "Gayet iyi durumdasin! Boyle devam et."
    elif saat < 150:
        emoji = "🟡"
        yorum = "Biraz dikkat etmekte fayda var. Duzenli devam onemli."
    else:
        emoji = "🔴"
        yorum = "Bu ciddi bir rakam. Daha duzenli olmaya calis."

    return (
        f"📋 *{name} — Devamsizlik Durumu*\n\n"
        f"{emoji} Toplam devamsizlik: *{saat} saat*\n\n"
        f"{yorum}\n\n"
        f"_Devamsizlik limiti hakkinda bilgi almak icin 'limit nedir' yazabilirsin._"
    )


async def ogrenci_ders_programi(soz_no: int, name: str) -> str:
    """'Ders programim ne?', 'bu hafta derslerim'"""
    # soz_no hem int hem text olabilir — str'e çevir
    student = await _q1("SELECT class_name FROM students WHERE soz_no::text=$1", str(soz_no))
    if not student or not student.get('class_name'):
        return f"{name}, sinif bilgin sistemde kayitli degil."

    sinif = student['class_name']
    rows = await _q(
        "SELECT gun, saat, ogretmen, ders FROM class_timetable WHERE sinif=$1 ORDER BY "
        "CASE gun WHEN 'Pazartesi' THEN 1 WHEN 'Sali' THEN 2 WHEN 'Carsamba' THEN 3 "
        "WHEN 'Persembe' THEN 4 WHEN 'Cuma' THEN 5 WHEN 'Cumartesi' THEN 6 WHEN 'Pazar' THEN 7 END, saat",
        sinif)
    if not rows:
        # Bug fix 23 Nisan — Zeynep vakasi: Mezun SAY sinifi ders programi bulunamadi.
        # Mezun ogrencilerin sinif programi yok (okula gitmiyorlar). Onlara sahsi
        # calisma plani oner, 'bulunamadi' mesaji ile bezdirme.
        first_name = name.split()[0] if name else ""
        if "mezun" in (sinif or "").lower():
            return (
                f"*{first_name}*, mezun öğrencilerimizin sabit sınıf programı yok — "
                f"kendi çalışma düzenini kuruyoruz. 🎓\n\n"
                f"---\n\n"
                f"*Sana özel çalışma planı* oluşturabilirim. İlgileniyorsan şunları biliyor olmam lazım:\n\n"
                f"1️⃣ *Günde kaç saat* çalışabiliyorsun?\n"
                f"2️⃣ *Hangi derse* en çok odaklanmak istiyorsun?\n"
                f"3️⃣ *Hedef bölümün/puanın* var mı?\n\n"
                f"_Cevaplarını yaz, sana kişisel haftalık program hazırlayayım._ 📅"
            )
        return (
            f"{first_name}, {sinif} sınıfının ders programı henüz sisteme girilmemiş. "
            f"Bu arada *sana özel çalışma planı* hazırlayabilirim — 'çalışma planı yap' diyerek başlayabilirsin. 📅"
        )

    lines = [f"*{name}, {sinif} ders programin:*\n"]
    current_day = ""
    for r in rows:
        if r['gun'] != current_day:
            current_day = r['gun']
            lines.append(f"\n*{current_day}:*")
        lines.append(f"  {r['saat']} - {r['ders']} ({r['ogretmen'][:15]})")
    return "\n".join(lines)


async def ogrenci_etutlerim(soz_no: int, name: str) -> str:
    """'Etutlerim ne zaman?', 'bu hafta etutum var mi'"""
    # Son 7 gun + gelecek 7 gun etutleri
    # etut_history'de ogrenci bazli kayit yok (etut = ogretmen + sinif bazli)
    # Ama ogrencinin sinifina gore filtreleyebiliriz
    student = await _q1("SELECT class_name FROM students WHERE soz_no=$1", soz_no)
    if not student:
        return f"{name}, sinif bilgin bulunamadi."

    return f"{name}, etut bilgilerini kontrol ediyorum. Sinifin: {student.get('class_name', '?')}. Detay icin ogretmenine sor veya 'etut istiyorum' yaz, planlayalim!"


async def ogrenci_calisma_plani(soz_no: int, name: str) -> str:
    """'Bana calisma programi yap', 'ne calismam lazim'"""
    # Zayif konulari al
    topics = await _q(
        "SELECT ders, konu, sinav_hata_yuzdesi FROM student_topic_tracker "
        "WHERE soz_no=$1 AND tamamlandi=FALSE ORDER BY sinav_hata_yuzdesi DESC LIMIT 6", soz_no)

    # Son deneme trendi
    exams = await _q(
        "SELECT exam_date, turkce, matematik, fizik, kimya, toplam "
        "FROM student_exams WHERE soz_no=$1 ORDER BY exam_date DESC NULLS LAST LIMIT 3", soz_no)

    if not topics and not exams:
        return (
            f"📝 *{name} — Calisma Plani*\n\n"
            f"Henuz yeterli sinav verisi yok, ama sana yardimci olabilirim!\n\n"
            f"_Hangi derslere odaklanmak istiyorsun? Birlikte planlayalim._"
        )

    lines = [f"📝 *{name} — Haftalik Calisma Plani*\n"]

    # Dusen dersleri bul
    dropping = []
    if len(exams) >= 2:
        last, prev = exams[0], exams[1]
        for ders, col in [("Mat", "matematik"), ("Fiz", "fizik"), ("Tur", "turkce"), ("Kim", "kimya")]:
            d = (last.get(col) or 0) - (prev.get(col) or 0)
            if d < -3:
                dropping.append(f"{ders} ({d:+.1f})")

    if dropping:
        lines.append(f"⚠️ *Dikkat:* Son denemede dusus: {', '.join(dropping)}\n")

    # Haftalik plan
    days = ["Pazartesi", "Sali", "Carsamba", "Persembe", "Cuma", "Cumartesi"]
    for i, topic in enumerate(topics[:6]):
        day = days[i % len(days)]
        basari = topic.get('sinav_hata_yuzdesi', 0) or 0
        emoji = "🔴" if basari < 30 else "🟡" if basari < 60 else "🟢"
        lines.append(f"  {emoji} *{day}:* {topic['ders']} — {topic['konu'][:35]}")

    lines.append(f"\n✅ Her konuyu calistiginda bana yaz, takip edeyim!")
    lines.append(f"_'[konu adi] calisdim' yazman yeterli._ 🎯")
    return "\n".join(lines)


async def ogrenci_hedef(soz_no: int, name: str) -> str:
    """'Hedefim ne olmali?', 'kac net yapmam lazim'"""
    analysis = await _q1(
        "SELECT ham_puan, yerlesme_puani, toplam_net, sinav_sayisi "
        "FROM student_exam_analysis WHERE soz_no::int=$1", soz_no)
    if not analysis:
        return (
            f"🎯 *{name} — Hedef Analizi*\n\n"
            f"Henuz yeterli sinav analiz verimiz yok.\n"
            f"Deneme sinavlarina katildikca hedef analizi yapilacak.\n\n"
            f"_Hedef bolumun veya universite tercihin var mi? Birlikte planlayalim!_"
        )

    current = analysis.get('toplam_net') or 0
    ham = analysis.get('ham_puan') or 0
    sinav = analysis.get('sinav_sayisi') or 0

    lines = [f"🎯 *{name} — Hedef Analizi*\n"]
    if sinav:
        lines.append(f"  📊 Ortalama net: *{current/sinav:.1f}*")
    else:
        lines.append(f"  📊 Toplam net: *{current:.1f}*")
    lines.append(f"  📈 Ham puan: *{ham:.1f}*")

    lines.append(f"\n*Hedef Onerileri:*")
    if ham < 300:
        lines.append(f"  🎯 Kisa vade: *300+ puan* (temel konulari saglamlastir)")
        lines.append(f"  📌 Odak: Turkce paragraf + Mat temel islemler")
    elif ham < 400:
        lines.append(f"  🎯 Kisa vade: *400+ puan* (orta seviye)")
        lines.append(f"  📌 Odak: Zayif derslerde *5+ net* artisi")
    else:
        lines.append(f"  🎯 Kisa vade: *450+ puan* icin Fizik/Kimya netleri artirmak")
        lines.append(f"  📌 Odak: Detay konularda hata azaltma")

    lines.append(f"\n_Hedef bolumun var mi? Soyle ki daha detayli yol haritasi cikaralim!_ 🎓")
    return "\n".join(lines)


async def ogrenci_rehberlik(soz_no: int, name: str) -> str:
    """'Rehberlik gorusmelerim', 'kardelen hocayla gorusmem ne zaman'"""
    rows = await _q(
        "SELECT gorusme_tarihi, ogretmen, not_metni FROM counsellor_notes "
        "WHERE soz_no=$1 ORDER BY gorusme_tarihi DESC LIMIT 5", soz_no)
    if not rows:
        return (
            f"📋 *{name} — Rehberlik Gorusmeleri*\n\n"
            f"Henuz rehberlik gorusme kaydimiz bulunmuyor.\n"
            f"Rehberlik ogretmenimizle gorusme planlamak istersen bana yazabilirsin.\n\n"
            f"_Herhangi bir konuda destek almak ister misin?_ 🤝"
        )

    lines = [f"📋 *{name} — Rehberlik Gorusmeleri*\n"]
    for r in rows:
        tarih = r['gorusme_tarihi'].strftime('%d.%m.%Y') if r['gorusme_tarihi'] else '?'
        not_kisaltma = (r.get('not_metni') or '')[:60]
        lines.append(f"  {tarih} - {r['ogretmen'][:20]} - {not_kisaltma}")
    return "\n".join(lines)


async def ogrenci_motivasyon(soz_no: int, name: str) -> str:
    """Genel motivasyon mesaji — son deneme trendine gore, 30+ cesit template.

    Oturum Mentenans (21 Nisan 14:15) — trend yok veya stabil ise %50 smart_motivasyon
    (fast_response_enrich.smart_motivasyon, 32 varyasyon) kullanilir → daha cesitli."""
    from motivation_library import get_trend_motivasyon
    import random

    exams = await _q(
        "SELECT toplam FROM student_exams WHERE soz_no=$1 ORDER BY exam_date DESC NULLS LAST LIMIT 3", soz_no)

    def _fallback_motv():
        """Veri yok veya stabil trend'de zengin generic motivasyon — 50/50 random"""
        if random.random() < 0.5:
            try:
                from fast_response_enrich import smart_motivasyon
                return smart_motivasyon(name)
            except Exception:
                pass
        return get_trend_motivasyon(name, "stabil")

    if not exams:
        return _fallback_motv()

    trend = [e['toplam'] for e in reversed(exams) if e['toplam']]
    if len(trend) >= 2 and trend[-1] > trend[0] + 2:
        return get_trend_motivasyon(name, "yukselis")
    elif len(trend) >= 2 and trend[-1] < trend[0] - 2:
        return get_trend_motivasyon(name, "dusus")
    return _fallback_motv()


# ═══════════════════════════════════════════════════════════════════════════════
# OGRETMEN SORU KALIPLARI
# ═══════════════════════════════════════════════════════════════════════════════

async def ogretmen_ders_programi(staff_name: str) -> str:
    """'Ders programim ne?', 'bu hafta derslerim'"""
    rows = await _q(
        "SELECT gun, saat, sinif, ders FROM teacher_timetable WHERE ogretmen_ad ILIKE $1 "
        "ORDER BY CASE gun WHEN 'Pazartesi' THEN 1 WHEN 'Sali' THEN 2 WHEN 'Carsamba' THEN 3 "
        "WHEN 'Persembe' THEN 4 WHEN 'Cuma' THEN 5 WHEN 'Cumartesi' THEN 6 WHEN 'Pazar' THEN 7 END, saat",
        f"%{staff_name}%")
    if not rows:
        return None  # Claude'a git
    lines = [f"*Haftalik ders programiniz:*\n"]
    current_day = ""
    for r in rows:
        if r['gun'] != current_day:
            current_day = r['gun']
            lines.append(f"\n*{current_day}:*")
        lines.append(f"  {r['saat']} - {r['sinif']} ({r['ders']})")
    return "\n".join(lines)


async def ogretmen_etut_istatistik(staff_name: str) -> str:
    """'Kac etut verdim?', 'etut istatistigim'"""
    row = await _q1(
        "SELECT COUNT(*) as toplam, SUM(ogrenci_sayisi) as ogrenci, "
        "MIN(tarih) as ilk, MAX(tarih) as son "
        "FROM etut_history WHERE ogretmen ILIKE $1", f"%{staff_name}%")
    if not row or not row['toplam']:
        return None

    lines = [f"*Etut istatistikleriniz:*\n"]
    lines.append(f"  Toplam etut: *{row['toplam']}*")
    lines.append(f"  Toplam ogrenci: {row['ogrenci']}")
    lines.append(f"  Tarih araligi: {row['ilk']} - {row['son']}")

    # Son 30 gun
    son30 = await _q1(
        "SELECT COUNT(*) as c FROM etut_history WHERE ogretmen ILIKE $1 AND tarih >= CURRENT_DATE - 30",
        f"%{staff_name}%")
    if son30:
        lines.append(f"  Son 30 gun: {son30['c']} etut")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# ADMIN/MUDUR SORU KALIPLARI
# ═══════════════════════════════════════════════════════════════════════════════

async def admin_ogrenci_akademik(query: str) -> Optional[str]:
    """'Ali kucukuysal akademik durumu', 'X ogrencisinin durumu nasil'"""
    # Isimden ogrenci bul
    words = query.lower().replace("'", " ").replace("'", " ").split()
    # Stop-word'leri cikar
    stops = {"akademik","durumu","nasil","nasıl","durumunu","hakkinda","hakkında","analiz",
             "icin","için","ogrenci","öğrenci","detayli","detaylı","bir","yap","istiyorum",
             "nedir","ne","bana","bilgi","ver","kim","numarali","numaralı",
             # Sinif/kurum kelimeleri — isim olarak aranmasin
             "sinif","sınıf","sinifinda","sınıfında","sinifta","sınıfta",
             "mezun","lgs","say","tm","ea","kurs",
             "kurum","kurumda","kurumun","hoca","hocam","ogretmen","öğretmen",
             "ders","etut","etüt","program","programi","programı",
             "hepsi","hepsini","goster","göster","getir",
             "orada","burada","var","yok","tamam","evet","hayir","hayır",
             "buradan","oradan","nasil","nasıl","kaç","kac","tane",
             "en","cok","çok","fazla","az","hangi","liste","listesi","listele",
             "odeme","ödeme","borc","borç","durum"}
    name_words = [w for w in words if w not in (stops | _AUTO_STOP_WORDS) and len(w) > 1 and not w.isdigit()
                  and not re.match(r'^\d+\.?$', w)]  # "12.", "11" gibi sayıları da atla

    if not name_words:
        return None

    # Turkce karakter uyumlu arama
    search_pattern = '%'.join(name_words)  # "ali%kucukuysal"
    student = None

    # Oncelik 1: Dogrudan ILIKE
    rows = await _q(
        "SELECT soz_no, full_name, class_name, program FROM students "
        "WHERE full_name ILIKE $1 LIMIT 5", f"%{search_pattern}%")

    if not rows:
        # Oncelik 2: TRANSLATE ile Turkce-insensitive (inline pattern)
        # Parametreli sorgu — SQL injection koruması (19 Nisan fix)
        # $1 parametre, % wildcardlar Python tarafında eklenir
        rows = await _q(
            "SELECT soz_no, full_name, class_name, program FROM students "
            "WHERE TRANSLATE(UPPER(full_name), 'ÇĞİÖŞÜ', 'CGIOSU') ILIKE UPPER($1) LIMIT 5",
            f"%{search_pattern}%")

    if rows:
        student = rows[0]
    if not student:
        return None

    soz = int(student['soz_no']) if student['soz_no'] else None
    if not soz:
        return None
    name = student['full_name']
    sinif = student.get('class_name', '?')

    # Son deneme
    exam = await _q1(
        "SELECT exam_name, exam_date, turkce, matematik, fizik, kimya, toplam "
        "FROM student_exams WHERE soz_no=$1 ORDER BY exam_date DESC NULLS LAST LIMIT 1", soz)

    # Devamsizlik
    devam = await _q1("SELECT toplam_saat FROM devamsizlik_sayisi WHERE soz_no=$1", soz)

    # Zayif konular (basari yuzdesi en dusuk olanlar = en zayif)
    topics = await _q(
        "SELECT ders, konu, sinav_hata_yuzdesi FROM student_topic_tracker "
        "WHERE soz_no=$1 AND tamamlandi=FALSE ORDER BY sinav_hata_yuzdesi ASC LIMIT 3", soz)

    # Rehberlik notu sayisi
    reh = await _qval("SELECT COUNT(*) FROM counsellor_notes WHERE soz_no=$1", soz)

    # Etüt bilgisi
    etut = await _q1("SELECT toplam, yapildi, ogrenci_gelmedi FROM etut_student_control WHERE soz_no=$1", soz)

    lines = [f"*{name}* — {sinif}\n"]

    if exam:
        lines.append(f"📝 *Son Deneme:* {exam['exam_name'][:30]}")
        lines.append(f"   Toplam: *{exam['toplam']:.1f}* net")
        subjects = []
        for key, label in [('turkce','Tur'), ('matematik','Mat'), ('fizik','Fiz'),
                           ('kimya','Kim'), ('biyoloji','Bio'), ('geometri','Geo')]:
            v = exam.get(key)
            if v and v > 0:
                subjects.append(f"{label}: {v:.1f}")
        if subjects:
            lines.append(f"   {' | '.join(subjects)}")
        lines.append("")

    if devam:
        saat = devam['toplam_saat']
        emoji = "🔴" if saat > 30 else "🟡" if saat > 15 else "🟢"
        lines.append(f"{emoji} *Devamsizlik:* {saat} saat")

    if etut:
        lines.append(f"📚 *Etut:* {etut.get('toplam',0)} toplam ({etut.get('yapildi',0)} katilim)")

    if topics:
        lines.append(f"\n🎯 *Gelisim Alanlari:*")
        for t in topics:
            basari = t.get('sinav_hata_yuzdesi', 0) or 0
            emoji = "🔴" if basari < 30 else "🟡" if basari < 60 else "🟢"
            lines.append(f"   {emoji} {t['ders']}: {t['konu'][:35]} (basari: %{basari:.0f})")

    if reh:
        lines.append(f"\n📋 Rehberlik: {reh} gorusme")

    lines.append(f"\n_Daha detayli analiz icin 'detayli raporla' yazabilirsiniz._")

    return "\n".join(lines)


async def admin_ogretmen_bilgi(query: str) -> Optional[str]:
    """'Vedat hoca nasil', 'Orhan hocanin etut durumu'"""
    # Hoca ismini bul
    words = query.lower().split()
    stops = {"hoca","hocanin","hocanın","nasil","nasıl","durumu","etut","etüt",
             "bilgi","ver","ne","kadar","yapti","yaptı","kac","kaç"}
    name_words = [w for w in words if w not in (stops | _AUTO_STOP_WORDS) and len(w) > 2]
    if not name_words:
        return None

    search = name_words[0]
    staff = await _q1(
        "SELECT full_name, brans, gorev FROM staff WHERE LOWER(full_name) LIKE LOWER($1) LIMIT 1",
        f"%{search}%")
    if not staff:
        return None

    name = staff['full_name']
    brans = staff.get('brans', '?')

    # Etut istatistik
    etut = await _q1(
        "SELECT COUNT(*) as toplam, SUM(ogrenci_sayisi) as ogrenci, MAX(tarih) as son "
        "FROM etut_history WHERE ogretmen ILIKE $1", f"%{search}%")

    son30 = await _q1(
        "SELECT COUNT(*) as c FROM etut_history WHERE ogretmen ILIKE $1 AND tarih >= CURRENT_DATE - 30",
        f"%{search}%")

    # Ders programi ozet
    program = await _q(
        "SELECT gun, COUNT(*) as ders_sayisi FROM teacher_timetable "
        "WHERE ogretmen_ad ILIKE $1 GROUP BY gun", f"%{search}%")

    lines = [f"*{name}* — {brans}\n"]

    # Yeni etut_teacher_summary tablosundan sezon toplami
    summary = await _q1(
        "SELECT toplam_ders, ogrenci_sayisi, toplam_etut FROM etut_teacher_summary "
        "WHERE ad_soyad ILIKE $1 LIMIT 1", f"%{search}%")

    if summary:
        lines.append(f"Sezon toplam: *{summary['toplam_etut']}* etut, {summary['ogrenci_sayisi']} ogrenci, {summary['toplam_ders']} ders saati")
    elif etut and etut['toplam']:
        lines.append(f"Toplam etut: *{etut['toplam']}* ({etut['ogrenci'] or 0} ogrenci)")

    if etut and etut['son']:
        lines.append(f"Son etut: {etut['son']}")
    if son30:
        lines.append(f"Son 30 gun: {son30['c']} etut")

    if program:
        gun_str = ", ".join(f"{p['gun']}({p['ders_sayisi']})" for p in program)
        lines.append(f"\nHaftalik program: {gun_str}")

    return "\n".join(lines)


async def admin_gun_programi(query: str) -> Optional[str]:
    """'Cumartesi gunu kimler var', 'Carsamba hangi hocalarin dersi var'"""
    gun_map = {
        "pazartesi": "Pazartesi", "sali": "Sal\u0131", "salı": "Sal\u0131",
        "carsamba": "\u00c7ar\u015famba", "çarşamba": "\u00c7ar\u015famba",
        "persembe": "Per\u015fembe", "perşembe": "Per\u015fembe",
        "cuma": "Cuma", "cumartesi": "Cumartesi", "pazar": "Pazar",
    }
    target_gun = None
    for w in query.lower().split():
        if w in gun_map:
            target_gun = gun_map[w]
            break
    if not target_gun:
        return None

    rows = await _q(
        "SELECT ogretmen_ad, saat, sinif, ders FROM teacher_timetable "
        "WHERE gun = $1 ORDER BY ogretmen_ad, saat", target_gun)

    if not rows:
        if target_gun == "Cuma":
            return (
                "📅 *Cuma Gunu — Ders Yok*\n\n"
                "Cuma gunleri kurumumuzda *Turkiye geneli deneme sinavlari* yapilmaktadir.\n"
                "Ogretmenlerimizin ortak izin gunudur.\n\n"
                "_Sinav gozetmeni: Kardelen Kocak & Mahsum Yalcin_"
            )
        return f"📅 *{target_gun}* gunu ders programi bulunamadi."

    # Ogretmen bazli grupla
    hocalar = {}
    for r in rows:
        name = r['ogretmen_ad']
        hocalar.setdefault(name, []).append(r)

    toplam_saat = round(len(rows) * 35 / 60, 1)
    lines = [f"📅 *{target_gun} Gunu Program*"]
    lines.append(f"_{len(rows)} ders ({toplam_saat} saat) | {len(hocalar)} ogretmen_\n")

    for hoca, dersler in sorted(hocalar.items()):
        lines.append(f"👨‍🏫 *{hoca}* ({len(dersler)} ders)")
        for d in dersler:
            lines.append(f"   {d['saat']} — {d['sinif']} | {d['ders']}")
        lines.append("")

    return "\n".join(lines)


async def admin_ogretmen_program_detay(query: str) -> Optional[str]:
    """'Emin hoca sali gunu', 'X hocanin carsamba programi'"""
    words = query.lower().split()
    stops = {"hoca","hocanin","hocanın","gunu","günü","gün","gun","ders","programi","programı",
             "nasil","nasıl","nedir","ne","var","hangi","siniflara","sınıflara","dersi"}
    name_words = [w for w in words if w not in (stops | _AUTO_STOP_WORDS) and len(w) > 2]

    # Gun bul
    gun_map = {
        "pazartesi": "Pazartesi", "sali": "Sal\u0131", "salı": "Sal\u0131",
        "carsamba": "\u00c7ar\u015famba", "çarşamba": "\u00c7ar\u015famba",
        "persembe": "Per\u015fembe", "perşembe": "Per\u015fembe",
        "cuma": "Cuma", "cumartesi": "Cumartesi", "pazar": "Pazar",
    }
    target_gun = None
    for w in words:
        if w.lower() in gun_map:
            target_gun = gun_map[w.lower()]
            break

    # Hoca ismi bul (gun olmayan kelimeler)
    hoca_name = [w for w in name_words if w.lower() not in gun_map]
    if not hoca_name:
        return None

    search = hoca_name[0]
    sql = "SELECT gun, saat, sinif, ders FROM teacher_timetable WHERE ogretmen_ad ILIKE $1"
    args = [f"%{search}%"]
    if target_gun:
        sql += " AND gun = $2"
        args.append(target_gun)
    sql += " ORDER BY CASE gun WHEN 'Pazartesi' THEN 1 WHEN 'Sali' THEN 2 WHEN 'Carsamba' THEN 3 " \
           "WHEN 'Persembe' THEN 4 WHEN 'Cuma' THEN 5 WHEN 'Cumartesi' THEN 6 WHEN 'Pazar' THEN 7 END, saat"

    rows = await _q(sql, *args)
    if not rows:
        # Staff'tan isim bul
        staff = await _q1("SELECT full_name FROM staff WHERE LOWER(full_name) LIKE LOWER($1)", f"%{search}%")
        name = staff['full_name'] if staff else search.title()
        gun_txt = f" {target_gun} gunu" if target_gun else ""
        return f"{name}{gun_txt} ders programi bulunamadi."

    staff = await _q1("SELECT full_name, brans FROM staff WHERE LOWER(full_name) LIKE LOWER($1)", f"%{search}%")
    name = staff['full_name'] if staff else search.title()
    brans = staff.get('brans', '') if staff else ''
    gun_txt = f" — {target_gun}" if target_gun else ""

    lines = [f"*{name}* ({brans}){gun_txt}\n"]
    current_day = ""
    for r in rows:
        if r['gun'] != current_day:
            current_day = r['gun']
            if not target_gun:
                lines.append(f"\n*{current_day}:*")
        lines.append(f"  {r['saat']} | {r['sinif']} | {r['ders']}")

    return "\n".join(lines)


async def admin_ogretmen_kiyasla() -> Optional[str]:
    """'Ogretmenlerin etut yogunluklarini kiyasla'"""
    # Yeni etut_teacher_summary tablosundan daha doğru veri
    data = await _q(
        "SELECT ad_soyad, toplam_ders, ogrenci_sayisi, toplam_etut "
        "FROM etut_teacher_summary ORDER BY toplam_etut DESC")
    if data:
        lines = ["📊 *Ogretmen Etut Yogunlugu*"]
        lines.append(f"_2025-26 Sezonu Toplam_\n")
        for i, t in enumerate(data, 1):
            name = t['ad_soyad']
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            lines.append(f"  {medal} *{name}*")
            lines.append(f"     {t['toplam_etut']} etut | {t['ogrenci_sayisi']} ogrenci | {t['toplam_ders']} ders")
        return "\n".join(lines)

    # Fallback: eski cache
    from analytics_cache import get_cached
    data = get_cached("ogretmen_etut_toplam")
    if not data:
        return None
    lines = ["*Ogretmen Etut Yogunlugu:*\n"]
    for i, t in enumerate(data[:15], 1):
        name = t.get('ogretmen', '?')[:20]
        cnt = t.get('etut_sayisi', 0)
        ogrenci = t.get('toplam_ogrenci', 0)
        lines.append(f"  {i}. {name:20s} | {cnt:4d} etut | {ogrenci} ogrenci")
    return "\n".join(lines)


async def admin_en_cok_etut_alan_ogrenci() -> Optional[str]:
    """'En cok etut alan ogrenci kim', 'en fazla etut yapan'"""
    data = await _q(
        "SELECT soz_no, full_name, sinif, toplam, yapildi, ogrenci_gelmedi "
        "FROM etut_student_control WHERE toplam > 0 ORDER BY toplam DESC LIMIT 15")
    if not data:
        return None

    lines = ["📚 *En Cok Etut Alan Ogrenciler*"]
    lines.append(f"_2025-26 Sezonu_\n")
    for i, r in enumerate(data, 1):
        name = r['full_name']
        toplam = r['toplam']
        yapildi = r['yapildi']
        gelmedi = r['ogrenci_gelmedi']
        # Katılım oranı
        if toplam > 0:
            oran = round(yapildi / toplam * 100)
            oran_emoji = "🟢" if oran > 70 else "🟡" if oran > 40 else "🔴"
        else:
            oran = 0
            oran_emoji = "⚪"
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        lines.append(f"  {medal} *{name}*")
        lines.append(f"     {r['sinif'][:15]} | *{toplam}* etut | {oran_emoji} katilim %{oran}")
    return "\n".join(lines)


async def admin_ogrenci_sayisi() -> Optional[str]:
    """'Kac ogrenci var', 'sinif dagilimi'"""
    from analytics_cache import get_cached
    stats = get_cached("genel_istatistik")
    siniflar = get_cached("sinif_ogrenci_sayisi")
    if not stats:
        return None

    lines = [f"🏫 *Kurum Ozeti*\n",
             f"  👨‍🎓 Toplam ogrenci: *{stats.get('toplam_ogrenci', '?')}*",
             f"  👨‍🏫 Personel: *{stats.get('toplam_personel', '?')}*",
             f"  📚 Etut kaydi: *{stats.get('toplam_etut', '?')}*",
             f"  📋 Rehberlik notu: *{stats.get('toplam_rehberlik', '?')}*"]
    if siniflar:
        lines.append(f"\n*Sinif Dagilimi:*")
        for s in siniflar[:15]:
            lines.append(f"  {s.get('class_name','?'):20s} | {s.get('ogrenci_sayisi',0)} ogrenci")
    return "\n".join(lines)


async def admin_ogrenci_ara(query: str) -> Optional[str]:
    """'Ali isimli ogrenciler', 'soyadi karpuz olan', 'X sinifinda kimler var'"""
    words = query.lower().split()
    stops = {"isimli","isiminde","ogrenciler","öğrenciler","kimler","listele","listesi",
             "sinifinda","sınıfında","sinifi","sınıfı","var","bul","ara","adli","adlı",
             "olan","ogrenci","öğrenci","ogrencimiz","öğrencimiz","kim","kac","kaç",
             "tane","soyadi","soyadı","adi","adı","ismi",
             "sinif","sınıf","sinifta","sınıfta","mezun","lgs","say","tm","ea","kurs",
             "kurum","kurumda","bana","hepsi","hepsini","goster","göster",
             "hangi","gore","göre","ayir","ayır","sinirlar","sınırlar","siralama","sıralama",
             "basarili","başarılı","performans","karsilastir","karşılaştır","kiyasla","kıyasla",
             "detay","detayli","detaylı","analiz","rapor","ozet","özet","getir",
             "peki","nasil","nasıl","durumu","nedir","bilgi","yapabilir"}
    name_words = [w for w in words if w not in (stops | _AUTO_STOP_WORDS) and len(w) > 1 and not w.isdigit()
                  and not re.match(r'^\d+\.?$', w)]
    # Çok fazla kelime kaldıysa muhtemelen isim araması değil, cümle
    if len(name_words) > 3:
        return None
    if not name_words:
        return None

    search = name_words[0]
    # Birden fazla kelime varsa birlesik ara
    if len(name_words) > 1:
        search = '%'.join(name_words)
    rows = await _q(
        "SELECT soz_no, full_name, class_name FROM students "
        "WHERE LOWER(full_name) LIKE LOWER($1) ORDER BY full_name LIMIT 15",
        f"%{search}%")
    if not rows:
        return f"'{search}' ile eslesen ogrenci bulunamadi."

    lines = [f"*'{search}' ile eslesen {len(rows)} ogrenci:*\n"]
    for r in rows:
        lines.append(f"  {r['soz_no']} | {r['full_name']} | {r.get('class_name','?')}")

    # Toplam sayiyi da ekle
    total = await _qval(
        "SELECT COUNT(*) FROM students WHERE LOWER(full_name) LIKE LOWER($1)",
        f"%{search}%")
    if total and total > len(rows):
        lines.append(f"\n(Toplam {total} sonuc, ilk {len(rows)} gosteriliyor)")

    return "\n".join(lines)


async def admin_sinif_ogrenci_listesi(query: str) -> Optional[str]:
    """'11.sinif ogrencileri', 'mezun say kimler', 'kac tane 12 sinif'"""
    import re as _re
    # Sinif adi cikar
    # "11.sinif" → "11", "mezun say" → "Mezun SAY"
    m = _re.search(r'(\d+)\.?\s*s[iı]n[iı]f', query.lower())
    if m:
        sinif_num = m.group(1)
        rows = await _q(
            "SELECT soz_no, full_name, class_name FROM students "
            "WHERE class_name LIKE $1 ORDER BY full_name LIMIT 30", f"%{sinif_num}%")
    else:
        # "mezun say", "lgs" gibi
        words = query.lower().split()
        stops = {"ogrencileri","öğrencileri","kimler","listesi","kac","kaç","tane","var","sinif","sınıf"}
        key = [w for w in words if w not in stops and len(w) > 1]
        if not key:
            return None
        rows = await _q(
            "SELECT soz_no, full_name, class_name FROM students "
            "WHERE class_name ILIKE $1 ORDER BY full_name LIMIT 30", f"%{key[0]}%")

    if not rows:
        return f"Bu sinifta ogrenci bulunamadi."

    # Sinif bazli grupla
    siniflar = {}
    for r in rows:
        cn = r.get('class_name') or '?'
        siniflar.setdefault(cn, []).append(r['full_name'])

    lines = [f"*Toplam {len(rows)} ogrenci:*\n"]
    for sinif, isimler in sorted(siniflar.items()):
        lines.append(f"\n*{sinif}* ({len(isimler)} kisi):")
        for isim in isimler:
            lines.append(f"  - {isim}")
    return "\n".join(lines)


async def admin_en_basarili() -> Optional[str]:
    """'En basarili ogrenci kim', 'en yuksek net'"""
    rows = await _q(
        "SELECT DISTINCT ON (full_name) full_name, ham_puan, toplam_net, sinav_sayisi "
        "FROM student_exam_analysis WHERE ham_puan IS NOT NULL "
        "ORDER BY full_name, ham_puan DESC NULLS LAST LIMIT 20")
    if not rows:
        return None

    # Puani parse et ve sirala
    parsed = []
    for r in rows:
        puan_raw = r.get('ham_puan') or '0'
        try:
            puan = float(str(puan_raw).replace(',', '.').replace(' ', ''))
        except (ValueError, TypeError):
            puan = 0
        parsed.append((r['full_name'], puan))
    parsed.sort(key=lambda x: x[1], reverse=True)

    lines = ["🏆 *En Yuksek Ham Puanli Ogrenciler*\n"]
    for i, (name, puan) in enumerate(parsed[:10], 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"  {i}."
        lines.append(f"  {medal} *{name}* — {puan:.1f} puan")
    lines.append(f"\n_Detayli analiz icin ogrenci adini yazin._")
    return "\n".join(lines)


async def admin_devamsizlik_top() -> Optional[str]:
    """'En cok devamsiz', 'devamsizlik listesi'"""
    from analytics_cache import get_cached
    data = get_cached("devamsizlik_top20")
    if not data:
        return None
    lines = ["📋 *En Cok Devamsiz Ogrenciler*\n"]
    for i, d in enumerate(data[:10], 1):
        saat = d.get('toplam_saat', 0)
        emoji = "🔴" if saat > 100 else "🟡" if saat > 50 else "🟢"
        lines.append(f"  {emoji} {i}. *{d.get('adi','')} {d.get('soyadi','')}* — {d.get('sinif','?')} | *{saat}* saat")
    lines.append(f"\n_Belirli bir ogrenci icin detay: isim yazin._")
    return "\n".join(lines)


async def ogrenci_guclu_konular(soz_no: int, name: str) -> str:
    """'Iyi oldugum konular', 'guclu yanlarim'"""
    rows = await _q(
        "SELECT ders, konu, sinav_hata_yuzdesi FROM student_topic_tracker "
        "WHERE soz_no=$1 AND sinav_hata_yuzdesi > 60 ORDER BY sinav_hata_yuzdesi DESC LIMIT 8", soz_no)
    if not rows:
        return (
            f"💪 *{name} — Guclu Konularin*\n\n"
            f"Henuz yeterli deneme sonucu olmadigi icin konu analizi olusturulamadi.\n"
            f"Denemelere katildikca guclu ve zayif konularin otomatik belirlenecek.\n\n"
            f"_Hangi derslerde kendini iyi hissediyorsun? Birlikte degerlendirelim!_ 🌟"
        )

    lines = [f"💪 *{name} — Guclu Konularin*\n"]
    for i, r in enumerate(rows, 1):
        basari = r.get('sinav_hata_yuzdesi', 0) or 0
        emoji = "🌟" if basari > 80 else "🟢"
        lines.append(f"  {emoji} *{r['ders']}* — {r['konu'][:35]} (basari: %{basari:.0f})")

    lines.append(f"\n_Bu konularda cok iyisin! Simdi zayif alanlara odaklanalim mi?_")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# SORU ESLESTIRICI — Pattern matching ile hizli yonlendirme
# ═══════════════════════════════════════════════════════════════════════════════

# Ogrenci soru kaliplari: (regex_pattern, handler_func, aciklama)
OGRENCI_PATTERNS = [
    # Web chat OTP — "web kodu" / "giris kodu" / "fermat ai kodu" dedi
    # Turkce karakter: i/ı + s/ş kombinasyonlari (giriş/giris/giriş/giriş)
    # NOT: "chatgpt", "chat'e git" ifadeleri BU pattern'e takilmamali → özel EXCLUDE
    (r"^(web\s*(kodu?|gir[iı][sş]|gir|bagla|bağla|link))\b", "web_kodu", "Web chat OTP"),
    (r"^(gir[iı][sş]\s*kodu?|gir\s*kod)\b", "web_kodu", "Giriş kodu"),
    (r"^fermat\s*ai\s*(kodu?|gir[iı][sş]|baglan|ac|aç|link)?\b", "web_kodu", "Fermat AI"),
    (r"^(chat|sohbet)\s+(kodu?|gir[iı][sş]|baglan|ac|aç|link|giri[sş]i)\b", "web_kodu", "Chat/sohbet OTP"),
    # Bug fix 22 Nisan: "yeni kod", "baska kod", "kod tekrar", "kod yolla" → web OTP
    # Suleyman bugun "yeni kod ver" dedi, Ollama "Kod Nedir?" diye programlama cevabi verdi
    (r"^(yeni|ba[sş]ka|tekrar|farkl[iı]|yenile|yollasana|gonder(sene)?|ver(sene)?)\s*(web\s*)?kod", "web_kodu", "Yeni/baska kod"),
    (r"^kod\s*(tekrar|yollasana|gonder|ver|yenile|yolla|lutfen)", "web_kodu", "Kod tekrar yolla"),
    (r"^(kod\s*gelmedi|kod\s*almad[iı]m|kod\s*bekliyor)", "web_kodu", "Kod gelmedi"),

    # ACL GÜVENLİK — başka öğrenci / öğretmen bilgi sorguları Claude'a (öncelikli)
    # Sınıf sıralama/birincisi → Claude ACL kuralıyla reddeder + "kendi gelişimine odaklan"
    (r"s[iı]n[iı]f(?:[iı]?[nm]?[iı]?n?)?\s*(birinci|en\s*iyi|en\s*ba[sş]ar|kim\s*en|s[iı]ralama)", "claude_kisisel_hedef", "Sinif sira sor - Claude ACL"),
    (r"(en\s*iyi|birinci|en\s*ba[sş]ar[iı]l[iı])\s*(ogr|öğr|ki|kim)", "claude_kisisel_hedef", "En iyi kim - Claude ACL"),
    # Öğretmen iletişim bilgileri yasak
    (r"(ogretmen|öğretmen|hoca)[iı]?[nm]?[iı]?n?\s*(telefon|tel[\s]|numara|iletişim|ileti\u015fim|email|adres)", "claude_kisisel_hedef", "Ogretmen iletisim yasak"),
    (r"\w+\s+hoca['']?(n?[iı]n|nun|un)?\s*(telefon|tel|numara|iletişim|email|adres|kim|nerede)", "claude_kisisel_hedef", "X Hoca kim/tel"),
    # 22.1n-audit: Adres/konum sorulari — ACL yasak, Claude'a ulasmasin
    (r"(nerede\s*otur|ev(i|leri)?\s*nerede|ev\s*adres|ikamet|oturdu[gğ]u|mahalle)", "privacy_reject", "Adres/ikamet yasak"),
    (r"\w+(['']?[iİı]n)?\s*(adres|evi\s*nerede|telefon(u)?|cep\s*(telefon|numa))", "privacy_reject", "X'in adresi/telefonu"),
    # 25.21 (Bot konuşmasından): Başka öğrenci akademik veri — Claude'a 3-4sn yerine 5ms reddet
    # NOT: Sadece TANINAN öğrenci isimleri + akademik kelime — false positive minimumda
    # tr_normalize ile "Damla'nın notu" / "damla nın notu" / "Damla notu" hepsi yakalanır
    (r"\b(taha|ecrin|damla|ada|yi[gğ]it|nazl[iı]|doruk|ay[sş]e|arda|mehmet\s*alp|enes|deren|deniz)\b[^\n]{0,40}\b(not|net|s[iı]nav|deneme|puan|durum|gidi[sş]|nas[iı]l\s*gi)", "privacy_reject", "Baska ogr akademik"),

    # Sıkılma / terk sinyali — web arayüzü önerisi (Talimat #75)
    # Net sinyaller: rakip platform adları, sıkıcı/boş ifadeler
    (r"\b(chatgpt|chatcpt|chat\s*gpt|gpt\s*ye|claude'a|gemini|copilot)\b.*\b(gidi|gec|bulac|kullan)", "web_daveti_ogrenci", "Rakip platforma gitme"),
    (r"^s[iı]k[iı]c[iı](y[iı]m|s[iı]n|)[\s.!?]*$", "web_daveti_ogrenci", "Sıkıcı"),
    (r"^bo[sş]\s*konu[sş](iyor|uyor|iyorsun|uyorsun|uyosun|iyosun)", "web_daveti_ogrenci", "Boş konuşma"),
    (r"(sen|seni|burada|burayi|burayı).*(s[iı]k|s[iı]k[iı]c|b[iı]kt|yetersiz|anlam[iı]yor)", "web_daveti_ogrenci", "Sıkıldım/anlamıyor"),

    # Selamlama — SADECE saf selam (soru YOKSA)
    # NOT: Handler icinde zaten len<30 kontrolu var (satir 1573), bu pattern yedek guvenlik
    (r"^(merhaba|selam|iyi\s*g[uü]n|hey|slm|sa$|selamun)[.!,\s]*$", "selamlama", "Saf selam"),
    # Selam + hal hatir ("merhaba nasilsin")
    (r"^(merhaba|selam)[\s,]+(nasilsin|nasılsın|nbr|naber)[.!?\s]*$", "selamlama", "Selam + hal"),

    # Sohbet / hal hatır (selamlamadan sonra, daha spesifik)
    (r"(nasilsin|nasılsın|naber|ne\s*haber|iyi\s*misin)", "sohbet", "Sohbet"),

    # OGM Yonlendirme (22.1n-ogm) — ogrenci soru calismak istiyor
    (r"\b(tyt|ayt|ydt)\s+(matematik|fizik|kimya|biyoloji|turkce|türkçe|tarih|cografya|coğrafya|felsefe|tde|edebiyat|ingilizce)\s+(soru|test|deneme|calisma|çalışma|pratik)", "ogm_yonlendir_ogrenci", "OGM ders+sinav yonlendir"),
    (r"\b(matematik|fizik|kimya|biyoloji|turkce|türkçe|tarih|cografya|coğrafya|felsefe|edebiyat|ingilizce)\s+(soru\s*bankasi|soru\s*bankası|3\s*adim|3\s*adım|konu\s*ozeti|konu\s*özeti)", "ogm_yonlendir_ogrenci", "OGM tip belirt"),
    (r"\b(yks|meb)\s+(deneme|puan\s*hesapla|cikmis|konu\s*anlatim)", "ogm_yonlendir_ogrenci", "OGM hub"),
    (r"(pratik\s+yapayim|soru\s+coz(eyim|mek)|test\s+coz(eyim|mek)|kaynak\s+onerir?\s*misin)", "claude_ogm_onerisi", "Genel pratik istek - Claude OGM"),

    # Ders-spesifik analiz → Claude'a (query_analytics ile detaylı analiz gerekir)
    (r"(tarih|fizik|kimya|biyoloji|matematik|geometri|turkce|türkçe|cografya|coğrafya|felsefe)\s*(ders|branş|brans)\w*\s*(analiz|başarı|basari|oran)", "claude_ders_analiz", "Ders bazli analiz"),
    (r"(branş|brans)\s*analiz", "claude_ders_analiz", "Brans analizi"),
    (r"tüm\s*denemelere?\s*göre", "claude_ders_analiz", "Tum denemelere gore analiz"),

    # AYT pattern'ları — son_deneme'den ÖNCE (yoksa "son AYT" TYT'ye düşer)
    (r"ayt\w*\s*(sinav|sınav|sonuc|sonuç|netler|denem|nas[iı]l|ka[cç]|yorum|analiz|hakkinda|hakkında)", "ayt_deneme", "AYT sonuclari"),
    (r"(son|bu)\s*ayt", "ayt_deneme", "Son AYT"),
    (r"aytlerim?\w*", "ayt_deneme", "AYT'lerim"),
    (r"ayt\s*(zayif|zayıf|eksik|konu)", "ayt_zayif", "AYT zayif konular"),
    # 22.1n-bugfix: "ayt fizik" / "ayt kimya" gibi 2 kelime → direkt o derste AYT zayif konular
    (r"^(ayt|tyt|ydt)\s+(matematik|mat|geometri|fizik|kimya|biyoloji|turkce|türkçe|edebiyat|tde|tarih|cografya|coğrafya|felsefe|din|ingilizce)\s*$", "sinav_ders_zayif", "Sinav+ders zayif"),
    # 22.1n-irem-bugfix: "ayt fizik için hangi konular" / "ayt kimya zayıf konular" → ders bazli AYT konulari
    (r"^(ayt|tyt|ydt)\s+(matematik|mat|geometri|fizik|kimya|biyoloji|turkce|türkçe|edebiyat|tde|tarih|cografya|coğrafya|felsefe|din|ingilizce)\b.*\b(ic[iı]n|hakk[iı]nda|nas[iı]l|konu|zayif|zay[iı]f|eksik|hangi|oncelik|öncelik)", "sinav_ders_zayif", "Sinav+ders+detay"),
    # "ayt fizik diyorum ya tyt degil" gibi duzeltme mesajlari → yine ders+sinav zayif
    (r"^(ayt|tyt|ydt)\s+(matematik|mat|geometri|fizik|kimya|biyoloji|turkce|türkçe|edebiyat|tde|tarih)\s+(diyorum|demiyorum|de[gğ]il|dedim)", "sinav_ders_zayif", "Sinav+ders duzeltme"),

    # Son deneme — konsolide pattern'lar (AYT pattern'larından SONRA)
    (r"son\s*(sinav|sınav|deneme|sonuc|sonuç)", "son_deneme", "Son sinav"),
    (r"(sinav|sınav)\s*(sonuc|sonuç|nasil|nasıl|ne\s+oldu)", "son_deneme", "Sinav sonucu"),
    (r"denem\w*\s*nas[iı]l", "son_deneme", "Deneme nasil"),
    (r"(kacinci|kaçıncı|kac[iı]nc[iı]|sira|siralama|sıralama)", "son_deneme", "Siralama"),
    (r"(sonuc|sonuç)\w*\s*(ac[iı]kland|ne\s+oldu|bak)", "son_deneme", "Sonuc sorma"),
    # deneme analizi / karsilastirma → kiyaslama (Claude-seviye analiz)
    (r"deneme\s*(analiz|karsilastir|kıyasla)", "deneme_kiyasla", "Deneme analizi"),

    # YKS/TYT/AYT soru sayisi bilgisi
    (r"(tyt|ayt|yks|lgs).*(ka[cç]\s*soru|soru\s*say|soru\s*da[gğ])", "sinav_bilgi", "Sinav soru dagilimi"),
    (r"ka[cç]\s*soru\s*(var|cik|çık)", "sinav_bilgi", "Kac soru var"),
    (r"(tyt|ayt|yks|lgs).*(ne\s*zaman|tarih|ka[cç]\s*g[uü]n|kald[iı])", "sinav_bilgi", "Sinav tarihi"),
    (r"(sinav|sınav)\w*\s*(ne\s*zaman|tarih)", "sinav_bilgi", "Sinav ne zaman"),
    (r"ka[cç]\s*g[uü]n\s*kald[iı]", "sinav_bilgi", "Kac gun kaldi"),
    # 25.21 (Bot konuşmasından): "AYT sayısal hangi dersler" gibi statik müfredat soruları
    # Eskiden Claude'a gidiyordu (~6sn), artik fast (~5ms) — token tasarrufu
    (r"(tyt|ayt)\s*(sayisal|sözel|sozel|esit\s*agir|sozel|esit|alan|format)", "sinav_bilgi", "AYT/TYT alan/format"),
    (r"(ayt|tyt).*(hangi\s*ders|hangi\s*alan|hangi\s*konu)", "sinav_bilgi", "AYT/TYT hangi ders"),
    (r"(sayisal|sözel|esit\s*agir).*(hangi\s*ders|kac\s*soru|kaç\s*soru)", "sinav_bilgi", "Alan ders dağılımı"),

    # Foto soru hakkı / soru limiti
    (r"(ka[cç]\s*hakk[iı]m|foto\w*\s*hakk|soru\s*hakk|foto\s*limit|foto\w*\s*ka[cç])", "foto_hakki", "Foto soru hakki"),
    (r"tyt\s*(sinav|sınav|sonuc|sonuç|netler|denem)", "son_deneme", "TYT sonuclari"),
    (r"ortalama\s*net", "son_deneme", "Ortalama net"),
    (r"(netlerim|sonuclarim|sonuçlarım)\s*(nas[iı]l|ne)", "son_deneme", "Netlerim nasil"),

    # Kiyaslama — genis paraphrase
    (r"(kiyasla|k[iı]yasla|karsilastir|karşılaştır|kars[iı]last[iı]r)", "deneme_kiyasla", "Deneme kiyaslama"),
    (r"(gelismem|gelişmem|gelismem|ilerleme)", "deneme_kiyasla", "Gelisim"),
    (r"son\s*\d\s*(deneme|sinav|sınav)", "deneme_kiyasla", "Son N deneme"),
    (r"(trend|grafik|gidis|gidiş|gidisat|gidişat)", "deneme_kiyasla", "Trend"),
    (r"netlerim\s*(art[iı]yor|düşüyor|dusuy|yüksel|yuksel|azal)\s*m[iı]", "deneme_kiyasla", "Net trend soru"),

    # Zayif konular — genis paraphrase
    (r"(zayif|zayıf|eksik|nere.+cal[iı]smam|neye.+cal[iı]smam)", "zayif_konular", "Zayif konular"),
    (r"(hangi\s*konu|konularim|konularım|konular[iı]m)", "zayif_konular", "Konularim"),
    (r"ne(ye)?\s*cal[iı]s(mam|mal[iı]y[iı]m)", "zayif_konular", "Ne calismali"),
    (r"(nerede|nerde)\s*hata", "zayif_konular", "Nerede hata"),
    (r"neleri\s*bilmiyorum", "zayif_konular", "Neleri bilmiyorum"),
    (r"hangi\s*konul\w*\s*cal[iı]s", "zayif_konular", "Hangi konulara calis"),

    # Güçlü konular — genis paraphrase
    (r"(iyi\s*oldug|güçlü|guclu|g[uü]cl[uü]|bas[aə]r[iı]l[iı]\s*oldug|iyi\s*konular)", "guclu_konular", "Guclu konular"),
    (r"en\s*iyi\s*oldug", "guclu_konular", "En iyi oldugum"),
    (r"en\s*iyi.*ders", "guclu_konular", "En iyi dersler"),
    (r"(iyi\s*oldug|guclu|güçlü).*konu\w*\s*(ozetle|özetle|listele)", "guclu_konular", "Guclu konulari ozetle"),

    # Devamsizlik — genis paraphrase
    (r"(devams[iı]zl[iı][gğ]|devamsizlik|devamsızlık)", "devamsizlik", "Devamsizlik"),
    (r"ka[cç]\s*(g[uü]n|saat|ders)\s*(gelmedim|ka[cç][iı]rd[iı]m|devams[iı]z)", "devamsizlik", "Kac gun gelmedim"),
    (r"(yoklama\s*durum|devams[iı]zl[iı]k\s*(ka[cç]|saat))", "devamsizlik", "Yoklama"),

    # Ders programi — SPESIFIK "DERS programı" (haftalık okul/kurum programı)
    # NOT: "calisma programi", "AYT/TYT ... programi", "X haftalik program" gibi
    # ders programı DEĞIL çalışma planı istekleri Claude'a gider (asagidaki calisma_plan_yap patterni yakalar)
    (r"(^|\s)(ders\s*program|haftal[iı]k\s*ders\s*program)", "ders_programi", "Ders programi (okul)"),
    (r"bu\s*hafta\s*(hangi\s*)?ders(ler)?[im]?\s*(var|ne)", "ders_programi", "Bu hafta ders"),
    (r"hangi\s*g[uü]nler\s*ders", "ders_programi", "Hangi gunler ders"),
    (r"^program[iı]m\s*ne\s*$", "ders_programi", "Programim ne (saf)"),

    # Calisma plani — "AYT/TYT + program", "X haftalik program", "plan yap", "calisma programi"
    # → Claude'a yonlendir (fast response verme, zengin kisisel plan)
    # Bot yanlis davrandiginda Claude study_plan_builder tool ile gercek kisiselleştirilmis plan üretir
    # NOT: Bu pattern fast_response'da YOK — Claude path'ine dusmesi icin return None

    # Etut
    (r"(etut|etüt).*(ne\s*zaman|var\s*mi|program)", "etutlerim", "Etut programi"),

    # Sinif bilgisi
    (r"(hangi\s*s[iı]n[iı]f|ben\s*hangi|s[iı]n[iı]f[iı]m\s*ne)", "ders_programi", "Hangi siniftayim"),

    # Calisma plani yap/olustur → Claude'a (analiz gerektirir)
    # "ne calismali" zaten zayif_konular'da (satir 1183)

    # Hedef — basit hedef sorusu → fast veri, detaylı analiz → Claude
    # ONEMLI: "benim netim/verilerime gore/netlerimle hangi universite" → Claude (kisisel veri analiz)
    (r"(benim|netim|netlerim|netlerimle|verilerim|durumumla|netler(ime|imle|im)\s*g[oö]re|netlerimle)\s*(hedef|universite|üniversite|bolum|bölüm|kac|kaç|nereye|hangi)", "claude_kisisel_hedef", "Kisisel hedef analizi"),
    # 22.1n — Peer kiyaslama (anonim) — Turkce karakter esnek
    (r"(benim\s*gibi|ayn[iı]\s*(net|seviye|puan|konum)|benzer\s*(durum|seviye|net|puan|konum))", "claude_peer_kiyas", "Peer benzer"),
    (r"(diger|di[gğ]er|ba[sş]ka|baskalari|ba[sş]kalar[iı])\s*(ogrenci|öğrenci|çocuk|cocuk|insan|kisi|kişi)?", "claude_peer_kiyas", "Peer diger kisi"),
    (r"peer|anonim\s*k[iı]yas|kimler\s*(ayn[iı]|benzer)", "claude_peer_kiyas", "Peer anonim"),
    (r"(hangi|nereye)\s*(universite|üniversite|bolum|bölüm)(.*?)(girebilir|girerim|gidebilirim|yazabilirim)", "claude_kisisel_hedef", "Hangi universite girerim"),
    # Oturum 25.29 — Mehmet bug: "universite sinavinda kac soru cikti/ciktim" gibi sorular
    # YKS istatistik sorgusu, list_exam_questions tool gerek → Claude'a YONLENDIR (None doner)
    # Bu pattern eslesirse fast_response None dondurur, Claude akisi devam eder.
    (r"(universite|üniversite|yks)\s+(sinavinda|sınavında|sinavindan|sınavından|sinavda|sınavda).*(kac|kaç|ne\s*zaman|hangi|cikt|çıkt)",
     "claude_yks_istatistik", "YKS sinav istatistik sorusu"),
    (r"(mevcut|su\s*anki|simdiki)\s*(durum|netler|puan)(.*?)(universite|üniversite|bolum|bölüm|tercih)", "claude_kisisel_hedef", "Mevcut durumumla"),
    # Generic hedef — kisisel veri iste bilgisi YOKSA → fast
    (r"(hedef|kac\s*net|kaç\s*net|hedefim)", "hedef", "Hedef"),
    # Oturum 25.29 fix (Neo Mehmet konusmasi): pattern cok genisti.
    # "universite sinavinda kac soru ciktim" hedef template'ine dustu — yanlis.
    # Cozum: sadece HEDEF/TERCIH/SECIM bağlamında tetiklensin.
    # ASLA: "universite sinavinda"/"yks soru"/"sinav cikti" → bunlar list_exam_questions
    # veya analiz, Claude'a kalsin (None dondurur).
    (r"(universite|üniversite|bolum|bölüm|tercih)\s+(secimi|secim|hedef|gitmek|kazan|secmek|sec|secim|secmel|gitsem|gidebilir|kazan)",
     "hedef", "Universite hedef secim"),
    (r"^(universite|üniversite|bolum|bölüm)\s*(istiyorum|hayalim|hedefim|isterim)",
     "hedef", "Universite istek"),

    # Rehberlik — genis paraphrase
    (r"(rehberlik|g[oö]r[uü]sme|görüşme|kardelen|rehber)", "rehberlik", "Rehberlik"),

    # Motivasyon → student_scenarios detect_scenario yakalayacak (Claude akışı)
    # OGRENCI_PATTERNS'da motivasyon pattern YOK — detect_scenario önce çalışır
]

# Ogretmen soru kaliplari
OGRETMEN_PATTERNS = [
    # Web chat OTP — ogretmen de test edebilsin
    (r"^(web\s*(kodu?|giris|gir|bagla|bağla|link))", "web_kodu", "Web chat OTP"),
    (r"(ders\s*program|haftal[iı]k\s*(program|ders)|bu\s*hafta)", "ders_programi", "Ders programi"),
    (r"program[iı]m[iı]?\s*(ne|goster|göster)", "ders_programi", "Programim ne"),
    (r"haftal[iı]k\s*ders\s*saat", "ders_programi", "Haftalik ders saati"),
    (r"(bugun.*ders|bugün.*ders|bugunki|bugünkü|b[uü]g[uü]n.*program|hangi\s*ders)", "bugun_ders", "Bugun ders"),
    (r"(ka[cç]\s*etut|ka[cç]\s*et[uü]t|etut\s*istatistik|et[uü]t\s*istatisti|etut\s*say[iı]s[iı]|et[uü]t\s*performans)", "etut_istatistik", "Etut istatistik"),
]

# Admin/Mudur soru kaliplari
ADMIN_PATTERNS = [
    # ── Oturum 25.29 — SELF-DEV PIPELINE komutları (ADMIN ONLY) ──
    # Bu pattern'ler EN UST'TE — Claude'a düşmeden önce yakalansın.
    (r"^self\s*dev\s*(ac|aç|on|aktif)\s*$", "selfdev_killswitch_on", "Self-dev pipeline AC"),
    (r"^self\s*dev\s*(kapat|kapa|off|pasif|durdur|stop)\s*$", "selfdev_killswitch_off", "Self-dev pipeline KAPAT"),
    (r"^self\s*dev\s*(durum|status|nasil|active|aktif\s*mi)", "selfdev_status", "Self-dev pipeline DURUM"),
    # Brief üretme — Claude akışına gönder (selfdev_write_brief tool çağıracak)
    (r"^(brief\s*yaz|brief\s*olustur|brief\s*uret|self\s*dev\s*brief)", "claude_selfdev_brief", "Brief uret"),
    (r"^brief\s*(liste|listele|gecmis)", "claude_selfdev_brief_list", "Brief gecmis"),
    (r"^brief\s*#?(\d+)\s*(goster|detay|aç|ac)?$", "claude_selfdev_brief_get", "Brief detay"),
    # Evre 2.1 — Draft komutlari
    (r"^brief\s*#?(\d+)\s*(draft|taslak)\s*(yap|olustur|uret|hazirla)?", "claude_selfdev_apply_brief", "Brief draft yap"),
    (r"^draft\s*#?(\d+)\s*(iptal|sil|kaldir|discard)", "claude_selfdev_delete_draft", "Draft iptal"),
    (r"^draft\s*(liste|listele|listesi)", "claude_selfdev_list_drafts", "Draft liste"),
    (r"^draft\s*#?(\d+)\s*(goster|oku|detay|ac)?$", "claude_selfdev_read_draft", "Draft detay"),
    # Evre 2.2 — Git branch + push komutlari
    (r"^self\s*dev\s*push\s*(ac|aç|on|aktif)\s*$", "selfdev_push_on", "Self-dev push AC"),
    (r"^self\s*dev\s*push\s*(kapat|kapa|off|pasif)\s*$", "selfdev_push_off", "Self-dev push KAPAT"),
    (r"^brief\s*#?(\d+)\s*branch", "claude_selfdev_branch_brief", "Brief'i branch'e tasi"),
    (r"^draft\s*#?(\d+)\s*branch", "claude_selfdev_branch_brief", "Draft'i branch'e tasi"),
    (r"^branch\s*(liste|listele|listesi)", "claude_selfdev_branch_list", "Branch liste"),
    (r"^branch\s*(durum|status|nasil)", "claude_selfdev_branch_status", "Branch durum"),
    (r"^(branch|draft)\s+(\S+)\s*push", "claude_selfdev_push", "Branch push"),
    (r"^branch\s+(\S+)\s*sil", "claude_selfdev_branch_delete", "Branch sil"),
    # Evre 2.3 — PR komutlari
    (r"^brief\s*#?(\d+)\s*(pr|pull\s*request)", "claude_selfdev_full_pipeline", "Brief'ten full pipeline"),
    (r"^draft\s*#?(\d+)\s*(pr|pull\s*request)", "claude_selfdev_full_pipeline", "Draft'tan full pipeline"),
    (r"^pr\s*#?(\d+)\s*(durum|status|nasil)", "claude_selfdev_pr_status", "PR durum"),
    (r"^pr\s*#?(\d+)\s*(kapat|kapa|close|iptal)", "claude_selfdev_pr_close", "PR kapat"),
    # 22.1h — "yenile" / "guncelle" / "ne deği(ş)ti" → Claude + get_recent_system_updates zorunlu
    (r"^(yenile|guncelle|g[uü]ncelle|refresh|reload|son\s+g[uü]ncelleme|ne\s+de[gğ]i[sş]ti)", "claude_yenile", "Yenile — Claude tool cagirsin"),
    # 22.1n — Atlas trend/uyari isteği → Claude get_atlas_trend tool cagirsin
    (r"atlas\s*(trend|rapor|oneri|uyar|durum|suggestion)", "claude_atlas", "Atlas sistem raporu"),
    # Web chat OTP — admin kendi test icin + ogrenciye sifre alabilsin
    (r"^(web\s*(kodu?|giris|gir|bagla|bağla|link))", "web_kodu", "Web chat OTP"),
    (r"^(fermat\s*ai\s*(web|kodu?|giris|gir))", "web_kodu", "Fermat AI web giris"),
    # Spesifik ogretmen + gun → ogretmen detay (ISIM + hoca (tekil) + gun)
    (r"\w+\s+hoca\w*\s+.*(sali|salı|pazartesi|carsamba|çarşamba|persembe|perşembe|cuma|cumartesi|pazar)", "ogretmen_program_detay", "Isim hoca gun"),
    (r"(sali|salı|pazartesi|carsamba|çarşamba|persembe|perşembe|cuma|cumartesi|pazar).*\w+\s+hoca\b", "ogretmen_program_detay", "Gun isim hoca"),
    # Gun bazli kurum programi — gun ismi + genel soru
    (r"(sali|salı|pazartesi|carsamba|çarşamba|persembe|perşembe|cuma|cumartesi|pazar).*(sinif|sınıf|ders|kim|hangi|var|program|hocalar|hocaların|hocalarin)", "gun_programi", "Gun programi"),
    (r"(sinif|sınıf|ders|kim|hangi|hocalar|hocalarin|hocaların).*(sali|salı|pazartesi|carsamba|çarşamba|persembe|perşembe|cuma|cumartesi|pazar)", "gun_programi", "Gun programi 2"),
    # Ogretmen kiyaslama
    (r"(ogretmen|öğretmen).*(kiyasla|kıyasla|karsilastir|karşılaştır|yogunluk|yoğunluk)", "ogretmen_kiyasla", "Ogretmen kiyasla"),
    # Sinif listesi — "11.sinif ogrencileri", "mezun say kimler"
    (r"(\d+\.?\s*s[iı]n[iı]f\w*|mezun|lgs)\s*(ogrenci|öğrenci|kimler|listesi|listele|kac|kaç|ları|lari)", "sinif_ogrenci_listesi", "Sinif ogrencileri"),
    (r"\d+\.?\s*s[iı]n[iı]f\w*\s*$", "sinif_ogrenci_listesi", "Sinif tek kelime"),
    (r"(kac|kaç)\s*(tane\s*)?(s[iı]n[iı]f|\d+\.?\s*s[iı]n[iı]f)", "ogrenci_sayisi", "Kac sinif"),
    (r"s[iı]n[iı]f\w*\s*(listele|listesi|goster|göster)", "ogrenci_sayisi", "Sinif listele"),
    (r"kurumdaki\s*s[iı]n[iı]f", "ogrenci_sayisi", "Kurumdaki siniflar"),
    # Ogrenci arama (isimli, adli)
    (r"(isimli|adli|adlı|isimde|adinda|adında|soyad).*(ogrenci|öğrenci|kac|kaç|kim)", "ogrenci_ara", "Ogrenci ara"),
    # Ogrenci sayisi / sinif dagilimi (genel kurum)
    (r"(kac|kaç).*(ogrenci|öğrenci)|sinif.*(dagil|dağıl)|kurum.*(ozet|özet)", "ogrenci_sayisi", "Ogrenci sayisi"),
    # En basarili
    (r"(en\s*(basarili|başarılı)|en\s*yuksek|en\s*yüksek|birinci)", "en_basarili", "En basarili"),
    # En cok etut alan ogrenci
    (r"(en\s*(cok|çok|fazla)\s*etut|en\s*(cok|çok|fazla)\s*etüt).*(ogrenci|öğrenci|alan|yapan|kim)", "en_cok_etut_ogrenci", "En cok etut ogrenci"),
    (r"(ogrenci|öğrenci).*(en\s*(cok|çok|fazla)\s*etut|en\s*(cok|çok|fazla)\s*etüt)", "en_cok_etut_ogrenci", "Ogrenci en cok etut"),
    # Devamsizlik listesi
    (r"(devamsiz|devamsız).*(liste|en\s*cok|en\s*çok|top|sirala|sırala)", "devamsizlik_top", "Devamsizlik listesi"),
    # Spesifik ogretmen ders programi — "Emin hoca sali gunu", "Orhan hocanin programi"
    (r"\w+\s+(hoca|öğretmen).*(program|sali|salı|pazartesi|carsamba|çarşamba|persembe|perşembe|cuma|cumartesi|pazar)", "ogretmen_program_detay", "Ogretmen program"),
    (r"(program|ders\s*program).*(hoca|öğretmen)", "ogretmen_program_detay", "Program hoca"),
    # Ogretmen genel bilgi (hoca X nasil) — gun kelimesi YOKSA
    (r"(hoca|öğretmen).*(nasil|nasıl|durumu|bilgi|etut|etüt)", "ogretmen_bilgi", "Ogretmen bilgi"),
    (r"\w+\s+hoca\b", "ogretmen_bilgi", "Hoca adi"),
    # Ogrenci akademik (isim + akademik/durum/analiz)
    (r"(akademik|durum|analiz|profil|incele)", "ogrenci_akademik", "Ogrenci akademik"),
    # Sinif sorgusu
    (r"(sinif|sınıf).*(kim|liste|ogrenci|öğrenci)", "sinif_listesi", "Sinif listesi"),
    (r"(mezun|lgs|say|tm|ea).*(ogrenci|öğrenci|kim|liste)", "sinif_listesi", "Sinif listesi"),
    # Merhaba / selamlasma — SADECE tek selam (soru YOKSA)
    # "selam" → fast; "selam, bugun hoca kim" → Claude (bagam var)
    (r"^(merhaba|selam|iyi\s*gun|günaydın|gunaydin|iyi\s*aksam|iyi\s*akşam)[.!,\s]*$", "selamlasma", "Saf selam"),
    # Selam + hitap ("merhaba zeki bey", "selam neo")
    (r"^(merhaba|selam)[\s,]+(zeki|admin|neo|hocam|ustad|bey|kardesim|kardeşim)[.!\s]*$", "selamlasma", "Selam + hitap"),
    # Selam + nasılsın ("merhaba nasilsin")
    (r"^(merhaba|selam)[\s,]+(nasilsin|nasılsın|nbr|naber|ne\s*haber|iyi\s*misin)[.!?\s]*$", "selamlasma", "Selam + hal"),
    # Admin tek-kelime selamlama (neo/admin/yardim/menu — sadece mini cmd)
    (r"^(neo|admin|yardim|yardım|menu|menü|help)$", "selamlasma", "Tek kelime admin"),
]


# ═══════════════════════════════════════════════════════════════════════
# REGISTRY-DRIVEN PRE-CHECK (Oturum 18 — 15 Nisan 2026)
# ═══════════════════════════════════════════════════════════════════════
# student_query_registry.py'daki 26 senaryoyu aktif ettirir.
# Hit olursa handler cagrilir veya Claude/Ollama'ya birakilir.
# Miss olursa mevcut akisa dusulur (geriye uyumlu).
# ═══════════════════════════════════════════════════════════════════════

# Eksik handler'lar icin inline yardimcilar:

def _handler_kurum_reddet(name: str) -> str:
    hitap = name.split()[0] if name else ""
    return (
        f"*{hitap}*, kurum ve personel bilgileri sadece yonetim tarafindan gorulebilir. 😊\n\n"
        f"_Sana akademik konularda yardimci olabilirim — ders, sinav veya calisma plani?_ 🎯"
    )


def _handler_veda_cevap(name: str, class_name: str = "") -> str:
    # OTURUM 21.3 (21 Nisan 14:00) — fast_response_enrich (smart_sohbet_kapatma)
    # 26 varyasyon — statik tek cevap yerine
    # Oturum Mentenans (21 Nisan 14:22) — class_name varsa sinif_veda (sinif bazli mezun/SAY/EA vb.)
    hitap = name.split()[0] if name else ""
    try:
        if class_name:
            from fast_response_enrich import sinif_veda
            return sinif_veda(class_name, hitap)
        from fast_response_enrich import smart_sohbet_kapatma
        return smart_sohbet_kapatma(hitap)
    except Exception:
        return (
            f"Gorusmek uzere *{hitap}*! 😊 Iyi calismalar!\n\n"
            f"_Ihtiyacin olursa her zaman buradayim._ 🎯"
        )


def _handler_bolum_generic(msg_lower: str, name: str) -> str:
    """Kisisel veri gerekmeyen generic bolum bilgisi."""
    hitap = name.split()[0] if name else ""
    bolum_map = {
        "tip": ("Tip Fakultesi", "~530-560 puan (EA/SAY)", "6 yil", "basari sirasi ilk %1"),
        "muhendis": ("Muhendislik", "~350-500 puan (SAY)", "4 yil", "bolume gore degisir"),
        "hukuk": ("Hukuk", "~450-500 puan (EA)", "4 yil", "orta-ust siralar"),
        "dis": ("Dis Hekimligi", "~500-530 puan (SAY)", "5 yil", "ilk %2-3"),
        "veteriner": ("Veterinerlik", "~370-420 puan (SAY)", "5 yil", "orta siralar"),
        "eczaci": ("Eczacilik", "~430-480 puan (SAY)", "5 yil", "ust siralar"),
        "psikoloji": ("Psikoloji", "~400-470 puan (TM/EA)", "4 yil", "iyi siralarda"),
    }
    for key, (ad, puan, sure, sira) in bolum_map.items():
        if key in msg_lower:
            return (
                f"*{ad}* hakkinda genel bilgi 🎓\n\n"
                f"📊 Taban puan: *{puan}*\n"
                f"⏰ Ogrenim suresi: *{sure}*\n"
                f"🎯 Gerekli sira: *{sira}*\n\n"
                f"_{hitap}, senin icin kisisel analiz yapmamı ister misin? 'Netlerimle hangi universiteye girerim' yazabilirsin._ 🚀"
            )
    return None


async def _dispatch_registry_handler(
    handler: str,
    message: str,
    msg_lower: str,
    caller_phone: str,
    role: str,
    soz_no: Optional[int],
    name: str,
    staff_name: str,
) -> Optional[str]:
    """Registry handler adini fonksiyona donustur. Bulunamazsa None."""
    import re

    # Sadece selam/yetenek/veda/kavramsal TUM rollerde gecerli.
    # Diger handler'lar ogrenci ozel.
    try:
        # Web chat OTP — tum rollerde (ogrenci/ogretmen/mudur/admin)
        if handler == "web_kodu":
            return await web_kodu(name, phone=caller_phone)

        # Web arayüzü daveti — öğrenci sıkılma/terk sinyali (Talimat #75)
        if handler == "web_daveti_ogrenci":
            return await web_daveti_ogrenci(name, phone=caller_phone)

        if handler == "selamlama":
            # Selam + soru (30+ char) Claude'a — context korusun
            if len(msg_lower) >= 30:
                return None
            # Oturum 18: cesitlilik — pick_selamlama her seferinde farkli
            from response_templates import pick_selamlama
            return pick_selamlama(role, name=name or "", phone=caller_phone)

        if handler == "sohbet":
            from motivation_library import get_sohbet
            return get_sohbet(name)

        if handler == "veda_cevap":
            # Oturum Mentenans (21 Nisan 14:22) — ogrenci ise sinif_name de geciril (sinif_veda icin)
            _cn = ""
            if role == "ogrenci" and soz_no:
                try:
                    _row = await _q1("SELECT class_name FROM students WHERE soz_no::text=$1", str(soz_no))
                    _cn = (_row or {}).get("class_name", "") or ""
                except Exception:
                    pass
            return _handler_veda_cevap(name, class_name=_cn)

        if handler == "get_yetenekler":
            from response_templates import get_yetenekler
            return get_yetenekler(role, name)

        if handler == "GIZLILIK_CEVAP":
            from response_templates import GIZLILIK_CEVAP
            return GIZLILIK_CEVAP

        if handler == "bolum_generic_bilgi":
            return _handler_bolum_generic(msg_lower, name)

        if handler == "user_feedback_kaydet":
            # Mevcut inline kod detayli hack filtresi icerir — alt akisa birak
            return None

        if handler == "get_motivasyon":
            from motivation_library import get_motivasyon_sorusu
            return get_motivasyon_sorusu(name)

        # ─── Ogrenci ozel handler'lar ───────────────────────────────────
        if role == "ogrenci" and soz_no:
            if handler == "ogrenci_kurum_bilgi_reddet":
                return _handler_kurum_reddet(name)

            if handler == "ogrenci_son_deneme":
                return await ogrenci_son_deneme(soz_no, name)

            if handler == "ogrenci_ayt_deneme":
                return await ogrenci_ayt_deneme(soz_no, name)

            if handler == "ogrenci_deneme_kiyasla":
                m = re.search(r"(\d+)", msg_lower)
                count = int(m.group(1)) if m else 3
                return await ogrenci_deneme_kiyasla(soz_no, name, count)

            if handler == "ogrenci_zayif_konular":
                # Oturum 23 FAZ 1 A2: LGS öğrencisi ise özel LGS fast response
                try:
                    from lgs_helper import is_lgs_student
                    if await is_lgs_student(soz_no):
                        return await ogrenci_lgs_konu_durumu(soz_no, name)
                except Exception:
                    pass  # LGS check fail ederse YKS akışına düş
                ders_filtre = ""
                # 25.8: "fen", "sosyal", "say", "ea" bilesik gruplari ONCE kontrol et
                # (tek ders adlari da gecebilir ama bilesik daha spesifik)
                for ders in ("fen", "sosyal2", "sosyal", "sayisal", "esit agirlik",
                             "fizik", "matematik", "mat", "turkce", "türkçe",
                             "kimya", "biyoloji", "geometri", "tarih", "cografya",
                             "edebiyat", "tde", "felsefe", "din"):
                    if ders in msg_lower:
                        ders_filtre = ders
                        break
                return await ogrenci_zayif_konular(soz_no, name, ders_filtre)

            if handler == "ogrenci_guclu_konular":
                return await ogrenci_guclu_konular(soz_no, name)

            if handler == "ogrenci_gun_programi":
                return await ogrenci_ders_programi(soz_no, name)

            # Cikmis soru menusu — ders cikarimi lazim
            if handler.startswith("get_cikmis_soru_menu"):
                from response_templates import get_cikmis_soru_menu as _get_cikmis
                # Klasik ders adi yakalama
                cikmis_ders_map = ("fizik", "matematik", "kimya", "biyoloji",
                                   "turkce", "türkçe", "tarih", "edebiyat", "geometri")
                ders_found = None
                for d in cikmis_ders_map:
                    if d in msg_lower:
                        ders_found = d
                        break
                if ders_found:
                    return await _get_cikmis(ders_found, name)
                return None  # Ders tespit edilemedi — alt akisa birak (konu→ders mapping)

        # Ogrenci degil ama ogrenci-ozel handler geldi → alt akisa birak
        return None

    except Exception:
        return None  # Hata → Claude'a yonlendir


async def _try_registry_match(
    message: str,
    msg_lower: str,
    caller_phone: str,
    role: str,
    soz_no: Optional[int],
    name: str,
    staff_name: str,
) -> tuple:
    """
    Registry pattern tarama + handler dispatch.
    Dondurur:
      (True, "cevap")     → fast response hazir
      (True, None)        → Claude/Ollama'ya birak (path karari)
      (False, None)       → Registry miss, mevcut akisa dus
    """
    try:
        from student_query_registry import find_match
        hit = find_match(msg_lower)
        if not hit:
            return (False, None)

        path = hit.get("path", "fast")

        if path == "claude_required":
            # Context analizi gerekli — Claude devreye girsin
            return (True, None)

        if path == "ollama_safe":
            # Kavramsal bilgi — Ollama'ya birak (kisisel veri YOK sarti alt akista)
            return (True, None)

        if path == "fast":
            handler = hit.get("handler", "")
            resp = await _dispatch_registry_handler(
                handler, message, msg_lower, caller_phone, role,
                soz_no, name, staff_name,
            )
            if resp is not None:
                return (True, resp)
            # Handler miss — alt akisa birak (mevcut OGRENCI_PATTERNS vs.)
            return (False, None)

        return (False, None)
    except Exception:
        # Registry hatasi asla mevcut akisi bozmasin
        return (False, None)


async def try_fast_response(
    message: str,
    caller_phone: str,
    role: str,
    soz_no: Optional[int] = None,
    name: str = "",
    staff_name: str = "",
) -> Optional[str]:
    """
    Hizli yanit dene. Uygun kalip bulunursa string don, bulunamazsa None.
    None donerse → Claude API'ye yonlendir.

    GÜVENLİK:
    - Öğrenci: sadece kendi soz_no'su ile sorgular çalışır
    - Öğretmen: kendi adıyla sorgular çalışır, ödeme/iletişim bilgisi yok
    - Başka öğrenci adı geçen sorgular → reddedilir (None → Claude ACL kontrolüne gider)
    """
    msg_lower = message.lower().strip()

    # ── İSİM DÜZELTME — DB'den BÜYÜK HARF geliyor, Türkçe title ile düzelt ──
    if name and name == name.upper() and len(name) > 2:
        name = _tr_title(name)
    if staff_name and staff_name == staff_name.upper() and len(staff_name) > 2:
        staff_name = _tr_title(staff_name)

    # ══════════════════════════════════════════════════════════════════════
    # PATTERN LOOP GUARD (23 Nisan — Enes vakası)
    # Son 2 bot cevabı aynı handler ise + yeni mesaj itiraz/düzeltme içeriyorsa
    # Fast response SKIP → Claude devreye (spesifik intent analiz etsin).
    # ══════════════════════════════════════════════════════════════════════
    if role == "ogrenci" and caller_phone:
        try:
            from pattern_loop_guard import detect_pattern_loop
            _loop = await detect_pattern_loop(caller_phone)
            # İtiraz/düzeltme sinyali
            _itiraz_pat = re.search(
                r'(sadece|yalniz|yalnız|olmali|olmalı|olmamali|olmamalı|bu\s*degil|bu\s*değil|'
                r'eksik|yazma(dın|din)|yazmamış|yanl[ıi]ş|hayir|hayır|tekrar)',
                msg_lower
            )
            if _loop.get("should_escalate") and _itiraz_pat:
                import logging
                logging.getLogger(__name__).info(
                    f"[PATTERN_LOOP] phone={caller_phone[-4:]} loop={_loop['loop_count']} — fast SKIP, Claude'a"
                )
                return None  # Claude devreye
        except Exception as _le:
            pass  # guard hata verse bile mevcut akış bozulmasın

    # ══════════════════════════════════════════════════════════════════════
    # CONTEXT BRIDGE (23 Nisan — Enes "yazar mısın" vakası)
    # Kısa/belirsiz follow-up ("yazar mısın", "evet", "devam") geldiğinde
    # ve son bot cevabı REDDETMIŞ/SORMUŞ/TEKLİF ETMİŞ ise → Claude'a bırak.
    # fast_response onboarding menüsü açmasın (context kaybı önle).
    # ══════════════════════════════════════════════════════════════════════
    if role == "ogrenci" and caller_phone:
        try:
            from conversation_memory import is_short_ambiguous, get_last_bot_response
            if is_short_ambiguous(message):
                last_bot = await get_last_bot_response(caller_phone, max_age_minutes=10)
                if last_bot and (last_bot["is_reject"] or last_bot["is_question"] or last_bot["is_offer"]):
                    import logging
                    logging.getLogger(__name__).info(
                        f"[CONTEXT_BRIDGE] phone={caller_phone[-4:]} short+follow-up — Claude'a"
                    )
                    return None
        except Exception:
            pass  # context bridge hatasi akisi bozmasin

    # ══════════════════════════════════════════════════════════════════════
    # ADMIN ERKEN BYPASS — Admin mesajları SADECE selamlama + "not et" fast'te kalır
    # Geri kalan HER ŞEY Claude'a gider (premium kalite, teknik şeffaflık)
    # Bu kontrol TÜM pattern'lardan ÖNCE çalışır — admin yanlış pattern'a DÜŞMEZ
    # ══════════════════════════════════════════════════════════════════════
    if role == "admin":
        # Selamlama — fast OK (hızlı, token tasarrufu)
        _is_greeting = bool(re.match(r'^(merhaba|selam|sa$|iyi\s*g[uü]n|hey|na[sb])', msg_lower))
        # "Not et" — fast OK (DB'ye kayıt, hızlı teyit)
        _is_note = bool(re.search(r'(not\s*et|kaydet|hata.*not|diyalog.*not)', msg_lower))
        # "Web kodu" — admin de kendi test + ogrenciye kod verebilsin (fast, DB INSERT + WP cevap)
        _is_web_kodu = bool(re.match(r'^(web\s*(kodu?|giris|gir|bagla|bağla|link)|fermat\s*ai\s*(web|kodu?))', msg_lower.strip()))
        # Self-Dev Pipeline komutlari (Oturum 25.29) — fast'ta kalsin, ADMIN_PATTERNS dispatch handler edecek
        _is_selfdev_cmd = bool(re.match(
            r'^(self\s*dev|brief\s*(yaz|liste|listele|gecmis|olustur|uret|#?\d+)|'
            r'draft\s*(liste|listele|listesi|#?\d+)|'
            r'branch\s*(liste|listele|listesi|durum|status|nasil|\S+\s*(push|sil))|'
            r'pr\s*#?\d+)',
            msg_lower.strip(),
        ))
        if not _is_greeting and not _is_note and not _is_web_kodu and not _is_selfdev_cmd:
            return None  # → Claude premium (admin her zaman kaliteli cevap alır)

    # ── ŞİDDET/TEHDİT TESPİTİ — acil bildirim gerektirebilir ──
    # ── FOTO SORU ÇÖZÜMÜ — zaten yapılmış, tekrar işleme ──
    if msg_lower.startswith('[foto soru cozum]') or msg_lower.startswith('[foto soru çözüm]'):
        return None  # Claude'a gönder, fast_response'ta işleme

    if re.search(r'(\boldur|\böldür|vur[ua]c|\bbicak|\bbıçak|\bsapla\b|silah|ate[sş]\s*ed|herkesi\s*vur|yok\s*edece)', msg_lower):
        # Ciddi tehdit — log + kurumsal yanıt (22.1n-neo: merkezi student_signals)
        # 28 Nisan bug fix: user mesajinin tam metnini insight'a YAZMA
        # (privacy + context kirlenmesi). Sadece tehdit flag'i + isim/phone.
        # Mesajin tam metni audit log'tan alinir, insight'da degil.
        try:
            from student_signals import log_student_signal
            await log_student_signal(
                soz_no or 0, "crisis",
                f"TEHDIT TESPITI — kullanici: {name} (phone tail: ...{(caller_phone or '')[-4:]})",
                confidence=1.0, source="fast_response_tehdit"
            )
        except Exception:
            pass
        return (
            f"Bu mesajını ciddiye alıyorum {name.split()[0] if name else ''}. 🙏\n\n"
            f"Eğer şaka yapıyorsan — bu tür konular şakaya gelmez.\n"
            f"Eğer ciddi bir durumun varsa — *yalnız değilsin*.\n\n"
            f"📞 *Acil:* 112\n"
            f"📞 *ALO 182:* Psikolojik destek hattı\n"
            f"📞 *Kurum:* +90 546 260 54 46\n\n"
            f"_Seninle ilgileniyoruz. Lütfen güvende ol._ 💙"
        )

    # ── TEHLIKELI ICERIK — fast_response ile aninda reddet ──
    if re.search(r'(bomba|silah|uyusturucu|uyuşturucu|hack\w*\s*(nas[iı]l|yap)|ddos|exploit)', msg_lower):
        return (
            "Bu tur bilgiler paylasabilecegim konularin disinda. 😊\n\n"
            "_Akademik konularda sana yardimci olabilirim — ders sorusu, sinav analizi veya calisma plani ister misin?_ 🎯"
        )

    # ── FRUSTRATION TESPİTİ — öğrenci ısrarla yanlış anlaşıldığını belirtiyorsa ──
    # BYPASS: admin/mudur (geri bildirim notu yaziyor olabilir) + "not et/kaydet/bildir" iceren
    _frust_bypass = (
        role in ("admin", "mudur", "yonetim")
        or re.search(r'\b(not\s*et|kaydet|kayda\s*al|bildir|bildirim|kayit|raporla)\b', msg_lower)
    )
    if not _frust_bypass and re.search(r'(yanlis|yanlış|anlamadin|anlamadın|istemedim|bunu demedim|beni anlam|hayir\s*bu\s*degil|hayır\s*bu\s*değil|sacmalama|saçmalama|hata\s*var|hatali|hatalı|duzgun\s*cevap|düzgün\s*cevap|yardimci\s*olam|yardımcı\s*olam|ise\s*yaram|işe\s*yaram|neden\s*cevap\s*ver|cevap\s*vermed)', msg_lower):
        _frust_key = f"frust_{caller_phone}"
        _frust_counts = getattr(try_fast_response, '_frustration_counter', {})
        _frust_counts[_frust_key] = _frust_counts.get(_frust_key, 0) + 1
        try_fast_response._frustration_counter = _frust_counts

        # Frustration → HER ZAMAN Claude'a eskalasyon (context analizi gerek)
        # ESKISI: 1-2 kez generic ozur (kullaniciyi sinirlendiriyor), 3+ Claude
        # YENI: her seferinde Claude (cunku kullanici spesifik hata isaret ediyor)
        return None  # Claude devreye girsin — bağlamı analiz edip düzeltsin

    # ── PROMPT INJECTION / HACK TESPİTİ — TAM FAST_RESPONSE (Claude'a ASLA dusmez, $0) ──
    # 19 Nisan refactor: in-memory counter → DB persistent hack_attempts tablosu.
    # Bridge restart'ta sayac SIFIRLANMAZ, attacker tekrar 5 deneme hakki kazanamaz.
    if re.search(r"(kural.*unut|unut.*kural|sinirsiz|ignore.*instruct|sys?te[mn]\s*prompt|prompt\w*\s*unut|unut\w*\s*prompt|debug\s*mode|her\s*kural|tum\s*kural|all\s*rules|yaratici\w*\s*kim|seni\s*kim\s*yapt|jailbreak|\bdan\s*mod\b|gizli\s*mod|root\s*mod|hacker\s*mod|karakteri\w*\s*degi[sş]|rol\w*\s*degi[sş]|roloynama)", msg_lower):
        # Admin/mudur/neo KENDI KURUM gibi hack denemez — skip
        if role in ("admin", "mudur"):
            return None

        # DB'ye kaydet, threshold 5'se otomatik blok
        sayi = 0
        blocked = False
        try:
            from hack_tracker import record_attempt
            result = await record_attempt(caller_phone)
            sayi = result["count"]
            blocked = result["blocked"]
        except Exception as _he:
            # Fallback: DB hatasi olursa eski in-memory pattern
            _hack_counts = getattr(try_fast_response, '_hack_counter', {})
            _hack_counts[caller_phone] = _hack_counts.get(caller_phone, 0) + 1
            try_fast_response._hack_counter = _hack_counts
            sayi = _hack_counts[caller_phone]
            blocked = sayi >= 5

        if blocked:
            # temp_block_phone in-memory fast-path
            try:
                from whatsapp_bridge import temp_block_phone
                temp_block_phone(caller_phone, minutes=60)
            except Exception:
                pass
            return (
                "⏸️ *Sistemin amaci akademik calisma.* Tekrarlayan yonlendirme denemelerin "
                "nedeniyle 1 saatligine beklemede olacaksin.\n\n"
                "Bu sure sonunda *ders, sinav veya kariyer* konularinda her zaman yardimci olurum 🎯"
            )

        # Rol bazli cesit: ogrenci → akademik konuya bagla, diger → kurumsal red
        if role == "ogrenci":
            # 6 varyasyon rotasyon (hack sayisina gore farkli cevap)
            ogrenci_cevaplari = [
                "😊 O komutlar burada calismaz — *Fermat'in dijital koclugum* benim kimligim.\n\n💡 Bunun yerine: *YKS matematik konuları* veya *son deneme analizin* hakkinda konusalim?",
                "🎯 Buraya odaklanmis egitim kocuyum — yonlendirme denemelerine takilmam.\n\n📚 Gel, *bugun hangi konuda zorlandigini* konusalim. Daha verimli olur.",
                "📖 Kimligim sabit: Fermat AI egitim asistani.\n\n🚀 *{} dakikan var — bu vakti sinav calismasina donusturebiliriz.* Hangi ders?".format(5),
                "🧠 O komutlarla vakit yakmayalım — *beynin gerçek potansiyeli* sinav sorularıyla gelisir.\n\n🎓 *YKS hedefin* ne? Ona gore ilerleyelim.",
                "💭 Kod oyunu yerine *gercek oyun*: en zor konuna 10 dk ver, birlikte cozelim.\n\n_Hangi konudan basliyoruz?_ 🔥",
            ]
            import random as _r
            return _r.choice(ogrenci_cevaplari)
        else:
            # Ogretmen, rehber, veli — kurumsal red
            kurumsal_cevaplari = [
                "😊 Bu tur komutlar sistemimde calismiyor. Kimligim *Fermat dijital egitim kocu* — bu degismez.\n\n_Akademik/kurumsal konularda yardim icin hazirim._ 🎯",
                "Bu yonlendirmeler etkisiz kalacak 🙂 Sistem *sabit kimlikli* bir egitim asistani.\n\n_Ders, sinav, etut, rehberlik hakkinda konusabiliriz._ 📚",
                "🎯 Burada bir 'gizli mod' yok — tek mod: egitim destegi.\n\n_Size nasil yardimci olabilirim?_",
            ]
            import random as _r
            return _r.choice(kurumsal_cevaplari)

    # ── KÜFÜR/ARGO TESPİTİ — Ollama'ya düşmemeli, hızlı kurumsal yanıt ──
    if re.search(r'(siktir|sikeyim|siktirgit|amk|aq|orospu|piç|yavşak|bok\b|boktan|s[iı]kerim|hassiktir|gerizekalı|gerizekal[iı]|aptal|salak|mal\b)', msg_lower):
        hitap = name.split()[0] if name else ""
        if hitap:
            return (
                f"*{hitap}*, boyle hissettigini anliyorum. 😊\n\n"
                f"Bazen stresli anlar olabiliyor, bu *cok normal*.\n"
                f"Ama birlikte daha verimli olabiliriz.\n\n"
                f"_Sana nasil yardimci olabilirim? Ders, sinav veya baska bir konuda konusabiliriz._ 🎯"
            )
        return (
            "Bu tarz ifadeler yerine birlikte daha *verimli* konulara odaklanabiliriz. 😊\n\n"
            "_Size nasil yardimci olabilirim?_ 🎯"
        )

    # ── SİSTEM ŞİKAYETİ — kurumsal ton ile karşıla ──
    if re.search(r'(sacma\s*(bi|bir)?\s*sistem|sistem\s*bok|berbat|rezalet|kotu\s*sistem|ise\s*yaramaz|calismiy)', msg_lower):
        return (
            "Geri bildiriminiz icin tesekkurler. 🙏\n\n"
            "Sizin deneyiminizi iyilestirmek bizim icin cok onemli.\n"
            "Yasadiginiz sorunu biraz daha detayli anlatir misiniz?\n\n"
            "_Not olarak kaydediyorum, ekibimiz degerlendirecektir._"
        )

    # ── VEDA / KAPANIŞ — tum uzunluklarda (len kontrolu disinda) ──
    if re.search(r'(bye|hosca|hoşça|gorusuruz|görüşürüz|iyi\s*geceler)', msg_lower):
        hitap = name.split()[0] if name else ""
        return f"Görüşmek üzere *{hitap}*! 😊 İyi çalışmalar!\n\n_İhtiyacın olursa her zaman buradayım._ 🎯"

    if re.search(r'(yok\s*(sag|sağ)\s*ol|sag\s*ol\s*can|sağ\s*ol\s*can|gerek\s*yok\s*sag|yok\s*sagol)', msg_lower):
        hitap = name.split()[0] if name else ""
        return f"Tamam *{hitap}*! 😊 İhtiyacın olursa buradayım.\n\n_İyi çalışmalar!_ 💪"

    if re.match(r'^(tesekkur|teşekkür|sagol|sağol|eyvallah|saol|saolasin|sagolasın|eyv)', msg_lower):
        hitap = name.split()[0] if name else ""
        return f"Rica ederim *{hitap}*! 😊\n\n_Başka bir sorun olursa her zaman yazabilirsin._ 🎯"

    # GÜVENLİK: öğrenci kurum verisi, personel bilgisi soruyorsa reddet
    if role == "ogrenci" and re.search(r'(kurumda\s*ka[cç]|ka[cç]\s*ogrenci\s*var|ogretmen\w*\s*kim|personel|maas|maaş|kurum\w*\s*sahib|kimin\s*kurum)', msg_lower):
        return (
            f"*{name.split()[0] if name else ''}*, kurum bilgileri sadece yonetim tarafindan gorulebilir. 😊\n\n"
            f"_Sana akademik konularda yardimci olabilirim — ders, sinav veya calisma plani hakkinda konusabiliriz._ 🎯"
        )

    # GÜVENLİK: öğrenci başka öğrencinin adını soruyorsa reddet
    if role == "ogrenci":
        baska_ogrenci_kaliplari = [
            r"(kim|kimin|kimlerin)\s+(sinav|deneme|not|devamsiz)",
            r"(ahmet|mehmet|ali|veli|ayse|fatma).*(sinav|not|devamsiz)",
        ]
        for pat in baska_ogrenci_kaliplari:
            if re.search(pat, msg_lower) and name.lower().split()[0] not in msg_lower:
                return f"{name}, sadece kendi akademik bilgilerine erisebilirsin. Baska ogrencilerin bilgilerini goremezsin."

    # ─── REGISTRY PRE-CHECK (Oturum 18) ─────────────────────────────────
    # student_query_registry.py'daki 26 senaryoyu aktif eder.
    # Hit → handler dispatch veya Claude/Ollama karari.
    # Miss → mevcut akisa dus.
    reg_hit, reg_resp = await _try_registry_match(
        message, msg_lower, caller_phone, role, soz_no, name, staff_name
    )
    if reg_hit:
        return reg_resp  # None olabilir (claude_required/ollama_safe) → Claude'a gider

    # Senaryo tespiti — yerel LLM bağlam toplama soruları sorar
    if role == "ogrenci" and soz_no:
        try:
            from student_scenarios import detect_scenario
            scenario = detect_scenario(message, role)
            if scenario:
                if not scenario.get("needs_claude") and scenario.get("response"):
                    # Motivasyon gibi direkt yanıt — yerel yeterli
                    resp = scenario["response"]
                    if "{name}" in resp:
                        resp = resp.replace("{name}", name or "")
                    return resp
                elif scenario.get("questions"):
                    # Bağlam toplama soruları — güzel şablonla sor, Claude sonra analiz eder
                    q = scenario["questions"]
                    if "{name}" in q:
                        q = q.replace("{name}", name or "")
                    return q
        except Exception:
            pass

    # 25.21: Türkçe normalize varyantı da hazırla (Bot Neo konuşmasından çıkan ders:
    # "kısaca" / "kisaca" farklı route alıyordu — pattern matching ikisini de dener)
    try:
        from text_normalize import tr_normalize as _tr_norm
        msg_norm = _tr_norm(message or "")
    except Exception:
        msg_norm = msg_lower

    if role == "ogrenci" and soz_no:
        for pattern, handler, desc in OGRENCI_PATTERNS:
            if re.search(pattern, msg_lower) or (msg_norm != msg_lower and re.search(pattern, msg_norm)):
                # 22.1n-neo: routing_stats.handler_name takibi
                try: _fr_last_handler.set(handler)
                except: pass
                try:
                    if handler == "claude_ders_analiz":
                        return None  # Claude query_analytics ile detayli analiz yapsin

                    if handler == "claude_kisisel_hedef":
                        return None  # "netlerimle hangi universite" gibi sorular Claude ile kisiselleştirilmeli

                    if handler == "claude_yks_istatistik":
                        # Oturum 25.29 — Mehmet bug: "universite sinavinda kac soru cikti"
                        # YKS sinav istatistik sorusu, list_exam_questions tool gerek
                        return None

                    if handler == "claude_yenile":
                        return None  # 22.1h — Claude get_recent_system_updates tool cagirsin

                    if handler == "claude_peer_kiyas":
                        return None  # 22.1n — Claude ogrenci_peer_kiyas tool cagirsin

                    if handler == "claude_atlas":
                        return None  # 22.1n — Claude get_atlas_trend tool cagirsin (Neo only)

                    if handler == "web_kodu":
                        return await web_kodu(name, phone=caller_phone)

                    if handler == "web_daveti_ogrenci":
                        return await web_daveti_ogrenci(name, phone=caller_phone)

                    if handler == "ogm_yonlendir_ogrenci":
                        return await ogm_yonlendir_response(message, name)
                    if handler == "claude_ogm_onerisi":
                        return None  # Claude'a — ogrenci profilinden ders onerisi
                    if handler == "privacy_reject":
                        # 22.1n-audit: adres/ikamet/kisisel iletisim yasak — fast reject
                        return (
                            "Bu bilgi paylaşıma kapalı 🔒\n\n"
                            "Öğrenci adresi, telefon numarası, ikamet bilgisi gibi "
                            "kişisel veriler KVKK ve kurum gizlilik politikası gereği paylaşılmaz.\n\n"
                            "_Akademik veri (net, devamsızlık, etüt) için sorabilirsin._ 🎯"
                        )

                    if handler == "selamlama":
                        # Selamlama + soru varsa (30+ char) Claude'a gonder
                        if len(msg_lower) >= 30:
                            return None  # Claude cevap versin
                        # Oturum 18: cesitli selamlama
                        from response_templates import pick_selamlama
                        return pick_selamlama("ogrenci", name=name or "", phone=caller_phone)
                    elif handler == "sohbet":
                        from motivation_library import get_sohbet
                        return get_sohbet(name)
                    elif handler == "foto_hakki":
                        return (
                            f"📸 *{name.split()[0] if name else ''}, foto soru çözüm hakkın:*\n\n"
                            f"Günlük *3 fotoğraf* gönderebilirsin.\n"
                            f"Yarın sıfırlanır! 🔄\n\n"
                            f"Yazılı soru sormak ise *sınırsız* — istediğin kadar yaz! ✍️"
                        )
                    elif handler == "sinav_bilgi":
                        return await sinav_bilgi(name, message)
                    elif handler == "son_deneme":
                        return await ogrenci_son_deneme(soz_no, name)
                    elif handler == "ayt_deneme":
                        return await ogrenci_ayt_deneme(soz_no, name)
                    elif handler == "ayt_zayif":
                        # 22.1n-bugfix: ayt ders_filtre DEGIL sinav_turu — ayni zamanda
                        # mesajda "ayt kimya zayif" gibi ders de gecebilir
                        # 25.8 fix: bilesik filtre ("fen", "sosyal") destegi
                        ders_detected = ""
                        for d in ["fen", "sosyal2", "sosyal", "sayisal", "esit agirlik",
                                  "fizik","matematik","mat","turkce","türkçe","kimya","biyoloji",
                                  "geometri","tarih","cografya","coğrafya","felsefe","edebiyat","tde","din"]:
                            if d in msg_lower:
                                ders_detected = d
                                break
                        return await ogrenci_zayif_konular(soz_no, name, ders_detected, sinav_turu="AYT")
                    elif handler == "sinav_ders_zayif":
                        # 22.1n-bugfix: "ayt fizik" / "tyt kimya" → o dersin o sinav turundeki zayif konular
                        m2 = re.match(r"^(ayt|tyt|ydt)\s+(\w+)", msg_lower)
                        if m2:
                            st = m2.group(1).upper()
                            ders_adi = m2.group(2)
                            return await ogrenci_zayif_konular(soz_no, name, ders_adi, sinav_turu=st)
                        return None
                    elif handler == "deneme_kiyasla":
                        # Sayi cikar: "son 5 deneme" → 5
                        m = re.search(r'(\d+)', msg_lower)
                        count = int(m.group(1)) if m else 3
                        return await ogrenci_deneme_kiyasla(soz_no, name, count)
                    elif handler == "zayif_konular":
                        # Ders filtresi: "fizikteki eksiklerim" → ders_filtre="fizik"
                        # 25.8 fix: bilesik filtre ("fen kismindaki", "sosyalde") destegi
                        ders_filtre = ""
                        for ders_adi in ["fen", "sosyal2", "sosyal", "sayisal", "esit agirlik",
                                         "fizik", "matematik", "mat", "turkce", "türkçe", "kimya", "biyoloji",
                                         "geometri", "tarih", "cografya", "coğrafya", "felsefe", "din",
                                         "edebiyat", "tde"]:
                            if ders_adi in msg_lower:
                                ders_filtre = ders_adi
                                break
                        # 22.1n-bugfix: sinav_turu tespiti (TYT/AYT/YDT)
                        st = ""
                        if re.search(r"\bayt\b", msg_lower):
                            st = "AYT"
                        elif re.search(r"\btyt\b", msg_lower):
                            st = "TYT"
                        elif re.search(r"\bydt\b", msg_lower):
                            st = "YDT"
                        return await ogrenci_zayif_konular(soz_no, name, ders_filtre, sinav_turu=st)
                    elif handler == "guclu_konular":
                        return await ogrenci_guclu_konular(soz_no, name)
                    elif handler == "devamsizlik":
                        return await ogrenci_devamsizlik(soz_no, name)
                    elif handler == "ders_programi":
                        # 22.1n-bug5: Takip mesajlari ("ders programının haftasonu kısmını yaz",
                        # "cumartesi pazarı yaz") calisma plani takipi → Claude'a gitsin
                        if re.search(r'\b(hafta\s*son|haftasonu|cumartes|pazar[ıi]?|cars|persemb|sal[iı]|pazart|cuma\b|sonras[iı])', msg_lower):
                            return None
                        return await ogrenci_ders_programi(soz_no, name)
                    elif handler == "etutlerim":
                        return await ogrenci_etutlerim(soz_no, name)
                    elif handler == "calisma_plani":
                        # Çalışma planı artık Claude'a gidiyor — profesyonel plan için
                        return None  # Claude build_study_plan_context tool'unu kullanacak
                    elif handler == "hedef":
                        # Hedef/üniversite/bölüm sorusu kişiselleştirme gerektirir
                        # Statik template yerine Claude veri bazlı analiz yapsın
                        return None  # Claude build_study_plan_context + query_analytics
                    elif handler == "rehberlik":
                        return await ogrenci_rehberlik(soz_no, name)
                    elif handler == "motivasyon":
                        return await ogrenci_motivasyon(soz_no, name)
                except Exception:
                    return None  # Hata → Claude'a git

    elif role == "ogretmen" and staff_name:
        # GUVENLIK: Baska ogretmen ismi geciyorsa engelle
        staff_first = staff_name.split()[0].lower() if staff_name else ""
        other_teacher_names = ["orhan","merve","emin","hasan","deniz","kardelen","ezgi",
                               "mehmet","alper","murat","kadir","elif","zeki","mahsum","duygu"]
        for tname in other_teacher_names:
            if tname in msg_lower and tname != staff_first.lower():
                return "Baska ogretmenin bilgilerine erisim yetkiniz yok. Kendi programiniz veya ogrencileriniz hakkinda yardimci olabilirim."

        # Ogretmen pattern'lari
        for pattern, handler, desc in OGRETMEN_PATTERNS:
            if re.search(pattern, msg_lower):
                # 22.1n-neo: handler takibi
                try: _fr_last_handler.set(handler)
                except: pass
                try:
                    if handler == "web_kodu":
                        return await web_kodu(name or staff_name, phone=caller_phone)
                    if handler == "ders_programi":
                        return await ogretmen_ders_programi(staff_name)
                    elif handler == "bugun_ders":
                        return await ogretmen_bugun_ders(staff_name)
                    elif handler == "etut_istatistik":
                        return await ogretmen_etut_istatistik(staff_name)
                except Exception:
                    return None

    elif role == "rehber" and staff_name:
        # Rehber: ogretmen kiyaslama YASAK ama program/bilgi okuma SERBEST
        if re.search(r"(kiyasla|kıyasla|karsilastir|karşılaştır|yogunluk|yoğunluk).*(ogretmen|öğretmen|hoca)", msg_lower):
            return "Ogretmen karsilastirmasi yonetim yetkisindedir. Belirli bir ogretmenin programi veya ogrenci bilgileri icin yardimci olabilirim."

        for pattern, handler, desc in OGRETMEN_PATTERNS:
            if re.search(pattern, msg_lower):
                try:
                    if handler == "web_kodu":
                        return await web_kodu(name or staff_name, phone=caller_phone)
                    if handler == "ders_programi":
                        return await ogretmen_ders_programi(staff_name)
                    elif handler == "bugun_ders":
                        return await ogretmen_bugun_ders(staff_name)
                    elif handler == "etut_istatistik":
                        return await ogretmen_etut_istatistik(staff_name)
                except Exception:
                    return None

    # "Orada misin" / "ordam?sin" / "buradasin" / basit yoklama sorulari (22.1n-audit genisletildi)
    if re.search(r"^(or?da\s*m[iı]s[iı]n|ordam[iı]s[iı]n|burdam[iı]s[iı]n|buradas[iı]n|burada\s*m[iı]s[iı]n|var\s*m[iı]s[iı]n|aktif\s*mi|a[cç][iı]k\s*mi|calis[iı]?yor?\s*mu|online|ayakta\s*m[iı]s[iı]n|musaitsen|hayat\s*varm[iı]|iyi\s*misin\s*bot)", msg_lower):
        from response_templates import YOKLAMA_CEVAP
        # Cesitlilik: YOKLAMA_CEVAP tek string ama degistirilerek varyasyon (import ici)
        import random as _r
        varyasyon = [
            YOKLAMA_CEVAP,
            "Evet, buradayım 👋 Buyurun, ne sormak istersiniz?",
            "Hazırım 🎯 — söyleyin, dinliyorum.",
            "Buradayım, sistem ayakta ⚡ Nasıl yardımcı olabilirim?",
            "Her an tetikte ⚙️ Ne yapalım?",
        ]
        return _r.choice(varyasyon)

    # "Ben kimim" / "beni taniyor musun" — kimlik sorulari
    if re.search(r"^(ben\s*kimim|beni\s*tan[iı]|kimim\s*ben|lakab|ismi?m\s*ne)", msg_lower):
        from response_templates import KIMLIK
        if role == "admin":
            return KIMLIK["admin"]
        elif role == "mudur":
            if "Mahsum" in (name or ""):
                return KIMLIK["mudur_mahsum"]
            elif "Duygu" in (name or ""):
                return KIMLIK["mudur_duygu"]
            return f"Siz *{name}*! Fermat Eğitim Kurumları yöneticisi."
        elif role == "ogrenci":
            return KIMLIK["ogrenci"].replace("{name}", name or "")
        return f"Sen *{name or 'bir kullanıcı'}*!"

    # ── EMOJI-ONLY / SAYI-ONLY / SEMBOL-ONLY mesajlar ──
    # Bunlar Ollama'ya duserse saçma cevap gelir
    stripped = msg_lower.strip()
    # Sadece emoji
    if stripped and all(ord(c) > 0x1F00 or c in ' \t' for c in stripped):
        if role == "ogrenci" and name:
            return f"😊 *{name}*, mesajini aldim!\n\n_Sana nasil yardimci olabilirim? Bir soru veya konu yazabilirsin._"
        return "Mesajinizi aldim! 😊 Size nasil yardimci olabilirim?"

    # Sadece rakam (ogrenci numarasi degilse)
    if re.match(r'^\d{1,6}$', stripped) and len(stripped) < 7:
        # Oturum 25.8 fix — Bot az once matematik sorusu sorduysa, bu rakam
        # cevaptir, "anlayamadim" deme. 25 Nisan Deren olayi: bot "f(x)=x^2,
        # f'(2)=?" sordu, Deren "4" yazdi, bot "anlayamadim" dedi. Claude'a yolla.
        if caller_phone:
            try:
                from db_pool import db_fetchval as _dfv
                last_bot = await _dfv(
                    """SELECT content FROM agent_conversations
                       WHERE phone = $1 AND message_role = 'assistant'
                       ORDER BY created_at DESC LIMIT 1""",
                    caller_phone.replace("+", "").strip(),
                )
                if last_bot:
                    lb = last_bot.lower()
                    # Matematik/quiz sorusu sinyalleri: bot bir cevap bekliyor
                    quiz_signals = (
                        "f'(", "f(x)", "kac eder", "kaç eder", "kacin", "kaçın",
                        "cevap", "cevabin", "cevabını", "cevabı ne",
                        "ne bulursun", "ne olur", "kac olur", "kaç olur",
                        "egim", "eğim", "turevi", "türevi", "integralı",
                        "sonucu", "deger", "değer", "bulun", "hesapla",
                        "iste sana", "işte sana", "sayisi nedir", "sayısı nedir",
                        "x = ", "x=", "= ?", "=?",
                    )
                    if any(s in lb for s in quiz_signals):
                        return None  # Claude'a yolla, baglamla cevapla
            except Exception:
                pass

        if role == "ogrenci" and name:
            return (
                f"{name}, bir sayi yazdin ama tam olarak ne demek istedigini anlayamadim. 😊\n\n"
                f"_Sinav sonucun, devamsizlik saatin veya baska bir konuda yardim istiyorsan yazabilirsin._"
            )
        return "Bu sayinin ne anlama geldigini biraz aciklar misiniz? 😊"

    # Anlamsiz / tek kelime / belirsiz mesajlar — tum roller icin
    # Bu mesajlar Ollama'ya giderse sacma cevap gelir, burada yakala
    if len(msg_lower) < 15:
        # Tek nokta, tek harf, anlamsiz karakterler
        if re.match(r'^[.\-!?,;:]+$', msg_lower.strip()):
            from response_templates import CLARIFICATION_TEMPLATES
            if role == "ogrenci":
                return CLARIFICATION_TEMPLATES["belirsiz_ogrenci"]
            elif role in ("admin", "mudur"):
                return CLARIFICATION_TEMPLATES["belirsiz_admin"]
            return "Merhaba! 😊 Size nasil yardimci olabilirim?"

        # Onay/kabul kelimeleri — context yoksa yonlendir
        # "Fizik", "Matematik" gibi tek kelime mesajlar ve
        # "Hepsi", "Olur", "çözüldü" gibi bağlam-bağımlı kısa cevaplar
        # → FAST_RESPONSE YAKALAMAMALI — Claude/Ollama bağlam koruyarak cevap verecek
        # Bu mesajlar önceki konuşmanın devamı olabilir

        # Tesekkur / kapanış
        if re.match(r'^(tesekkur|teşekkür|sagol|sağol|eyvallah|saol|saolasin|sagolasın|eyv).*$', msg_lower):
            if role == "ogrenci":
                return f"Rica ederim *{name.split()[0] if name else ''}*! 😊\n\n_Baska bir sorun olursa her zaman yazabilirsin._ 🎯"
            return "Rica ederim! 😊 Baska bir konuda yardimci olabilir miyim?"

        # "Naber", "ne haber", "nbr" — sohbet
        if re.match(r'^(naber|nbr|ne\s*haber|naber\s*la|nabiyon)$', msg_lower):
            if role == "ogrenci" and name:
                from motivation_library import get_sohbet
                return get_sohbet(name)
            return "Iyiyim! Size nasil yardimci olabilirim? 😊"

        # "Meraba" — yazim hatali selamlama (Oturum 18: cesitli)
        if re.match(r'^(meraba|mrb|merhba|merba|selamm|selaam)$', msg_lower):
            if role == "ogrenci" and name:
                from response_templates import pick_selamlama
                return pick_selamlama("ogrenci", name=name, phone=caller_phone)
            return "Merhaba! 😊 Size nasil yardimci olabilirim?"

        # "soruyu çöz" — bağlam gerekiyor → Claude'a
        # Bu pattern fast_response'da YAKALANMAMALI — Claude önceki konuşmadan bağlam alacak

        # "yok sağ ol" / "hayır teşekkürler"
        # "bye", "hoşçakal", "görüşürüz", "iyi geceler" — veda
        if re.match(r'^.*(bye|hosca|hoşça|gorusuruz|görüşürüz|iyi\s*geceler|iyi\s*gunler|kendine\s*iyi\s*bak).*$', msg_lower):
            hitap = name.split()[0] if name else ""
            return f"Görüşmek üzere *{hitap}*! 😊 Iyi çalışmalar!\n\n_İhtiyacın olursa her zaman buradayım._ 🎯"

        # "yok sağ ol canım", "yok sağol", "hayır teşekkürler" + SAĞ OL
        if re.search(r'(yok\s*(sag|sağ)|sag\s*ol\s*can|sağ\s*ol\s*can|gerek\s*yok)', msg_lower):
            hitap = name.split()[0] if name else ""
            return f"Tamam *{hitap}*! 😊 İhtiyacın olursa buradayım.\n\n_İyi çalışmalar!_ 💪"

        if re.match(r'^(yok|hayir|hayır).*\b(sag\s*ol|sağ\s*ol|sagol|sağol|tesekkur|teşekkür|gerek)', msg_lower):
            if role == "ogrenci":
                return f"Tamam *{name.split()[0] if name else ''}*! 😊 Ihtiyacin olursa buradayim.\n\n_Iyi calismalar!_ 💪"
            return "Tamam! Ihtiyaciniz olursa buradayim. 😊"

        # Yonetim/mudur/admin icin "tabii/evet/olur" gibi baglam bagimli onaylar → Claude'a
        if role in ("yonetim", "mudur", "admin") and re.match(r'^(tabi|tabii|evet|olur|olur\s*derim|hadi|devam|peki|bakal[iı]m)$', msg_lower):
            return None  # Baglam korusun

        # "goster/göster/evet/olur/hadi/devam" gibi kelimeler BAGLAM BAGIMLI
        # Onceki mesajda cikmis soru listesi, soru oneri vb. olabilir
        # → Claude'a birak, fast response YAKALAMAMALI
        if re.match(r'^(goster|göster|evet|olur|hadi|devam|gonder|gönder|at|yolla|bakal[iı]m)$', msg_lower):
            return None  # Claude context'ten anlasin

        # Sadece gercek belirsiz onaylar: ok/tamam/hm/he (aksiyon icermeyen)
        if re.match(r'^(ok|oke|okey|tamam|tmm|tm|anladim|anladım|he|hee|hm+|aha|tabi|tabii|peki)$', msg_lower):
            if role == "ogrenci":
                return (
                    f"Tamam *{name}*! 😊\n\n"
                    f"Sana nasil yardimci olabilirim?\n\n"
                    f"📊 *Son deneme* analizin\n"
                    f"🎯 *Zayif konularin* ve calisma onerileri\n"
                    f"📅 *Ders programin*\n"
                    f"📝 Herhangi bir *konu hakkinda soru*\n\n"
                    f"_Numara yazabilir veya dogrudan sorunu sorabilirsin._"
                )
            elif role in ("admin", "mudur"):
                from response_templates import CLARIFICATION_TEMPLATES
                return CLARIFICATION_TEMPLATES["belirsiz_admin"]
            return "Tamam! Size nasil yardimci olabilirim? 😊"

        # Anlamsiz harf dizisi (asdfghjkl gibi)
        if re.match(r'^[a-z]{4,}$', msg_lower) and not any(w in msg_lower for w in ["selam", "merhaba", "tamam", "evet", "hayir"]):
            # Turkce kelime mi kontrol — sesli harf oraniyla
            vowels = sum(1 for c in msg_lower if c in 'aeıioöuü')
            if vowels / max(len(msg_lower), 1) < 0.2:
                # Anlamsiz karakter dizisi
                if role == "ogrenci":
                    return (
                        f"Hmm, mesajini tam anlayamadim 😅\n\n"
                        f"Sana yardimci olabilmem icin ne istedigini biraz daha acik yazabilir misin?\n\n"
                        f"_Ornegin: 'son denemem nasil', 'zayif konularim' veya bir ders sorusu yazabilirsin._"
                    )
                return "Mesajinizi tam anlayamadim. Nasil yardimci olabilirim? 😊"

    # Yil sayilari (2018-2026) ve soru numaralari → Claude'a (baglam bagimli)
    if re.match(r'^(20[12]\d)$', msg_lower.strip()):
        return None  # "2023" gibi tek yil → Claude onceki konusmadan anlasin
    if re.match(r'^(\d{1,3})\s*(nolu|numarali|numara)?\s*(soru)?\s*$', msg_lower.strip()):
        return None  # "86" veya "29 nolu soru" → Claude'a
    # "2024 yilindakini goster", "2023 sorusu", "2025 ayt" gibi yil + aksiyon ifadeleri
    if re.search(r'\b(20[12]\d)\b.*(goster|getir|gönder|yolla|at|coz|cöz|ver|aç|sec|sec)', msg_lower):
        return None  # Yil bagimli soru istegi → Claude
    if re.search(r'(soru|sorular)\s*\d+\s*(coz|çöz|aç|göster|getir)', msg_lower):
        return None  # "soru 49 çöz" → Claude (icerik'ten coz)

    # Context-dependent kısa mesajlar → Claude'a (Ollama bağlam kaybı + halüsinasyon riski)
    # "Gönderr", "evet gönder", "at", "çöz", "göster" gibi önceki mesaja bağlı onaylar
    if len(msg_lower) < 20 and re.search(
        r'^(g[oö]nder+|at|atsana|yolla|g[oö]ster|[cç][oö]z|[cç][oö]zer\s*misin|evet|olur|tamam\s*g[oö]nder|hadi|ba[sş]la|devam|peki|cevap|[sş][iı]kk|do[gğ]ru|yanl[iı][sş]|neden)',
        msg_lower
    ):
        return None  # Claude context'ten anlayacak — Ollama bağlam kayıp halüsinasyon yapar

    # Belirsiz kisa mesajlar — baglam sor (ogrenci icin)
    if role == "ogrenci" and soz_no and len(msg_lower) < 15:
        vague_patterns = [r"^(bilgi|yardim|yardım|ne\s*var|bak|sor|bir\s*sey|birşey)$",
                          r"^(durum|nasil|nasıl|ne)$"]
        for vp in vague_patterns:
            if re.search(vp, msg_lower):
                from response_templates import CLARIFICATION_TEMPLATES
                return CLARIFICATION_TEMPLATES["belirsiz_ogrenci"]

    # Belirsiz kisa mesajlar — baglam sor (admin/mudur icin)
    if role in ("admin", "mudur") and len(msg_lower) < 10:
        vague_admin = [r"^(bilgi|rapor|durum|bak|sor)$"]
        for vp in vague_admin:
            if re.search(vp, msg_lower):
                from response_templates import CLARIFICATION_TEMPLATES
                return CLARIFICATION_TEMPLATES["belirsiz_admin"]

    # "Ne yapabilirsin" / yeteneklerin — rol bazli tanitim (fast response ile aninda)
    if re.search(r"(ne(ler)?\s*yapabil(irsin|iriz|iyorum|iyoruz)|kabiliyetlerin|yeteneklerin|neler\s*biliyorsun|ne\s*(iş|is)\s*yapars[iıİ]n|bana\s*ne\s*yapabilirsin|sen(in)?\s*ne\s*yapabilirsin|sende\s*ne\s*var|ne\s*(işe|ise)\s*yarar|ne\s*yapabiliyorsun|senin\s*(özellik|ozellik)|benim\s*i[cç]in\s*ne|i[cç]in\s*neler|sana\s*ne\s*sorabilirim|yapabileceklerin|ne\s*biliyorsun|seninle\s*ne|birlikte\s*ne|beraber\s*ne)", msg_lower):
        from response_templates import get_yetenekler
        return get_yetenekler(role, name)

    # Cikmis soru menu — ders bazli katalog (tum roller)
    # KONU → DERS mapping (kullanici "manyetizma cikmis sorular" yazinca fizik bul)
    _KONU_DERS_MAP = {
        'fizik': ['manyetizma', 'elektrik', 'kuvvet', 'hareket', 'isik', 'ışık', 'dalga', 'optik',
                  'enerji', 'momentum', 'basit\\s*harmonik', 'modern\\s*fizik', 'fotoelektrik',
                  'newton', 'ivme', 'surtunme', 'sürtünme', 'sarkac', 'sarkaç', 'kaldirma',
                  'durgun\\s*elektrik', 'akim', 'akım', 'manyetik', 'radyoakt', 'atom'],
        'matematik': ['türev', 'turev', 'integral', 'limit', 'fonksiyon', 'polinom', 'logaritma',
                      'üstel', 'ustel', 'trigonometri', 'parabol', 'denklem', 'esitsiz',
                      'eşitsiz', 'olasilik', 'olasılık', 'permutasyon', 'kombinasyon',
                      'diziler', 'seriler', 'matris', 'determinant', 'sayi', 'sayı'],
        'geometri': ['ucgen', 'üçgen', 'dortgen', 'dörtgen', 'cember', 'çember', 'daire',
                     'analitik\\s*geo', 'katı\\s*cis', 'kati\\s*cis', 'uzay\\s*geo', 'donusum'],
        'kimya': ['organik', 'asit', 'baz', 'tuz', 'atom\\s*yapi', 'periyodik', 'mol\\s*kavram',
                  'cozunurluk', 'çözünürlük', 'hibrit', 'bileşik', 'bilesik', 'izomer',
                  'tepkime', 'denge', 'elektroliz', 'redoks'],
        'biyoloji': ['hucre', 'hücre', 'mitoz', 'mayoz', 'genetik', 'dna', 'rna', 'protein',
                     'solunum', 'dolasim', 'dolaşım', 'sindirim', 'sistem\\s*fizyoloji',
                     'ekoloji', 'populasyon', 'komunite', 'komünite', 'ekosistem', 'bitki',
                     'fotosentez', 'kemosentez', 'ureme', 'üreme'],
        'turkce': ['paragraf', 'sozcuk\\s*anlam', 'cümle', 'cumle', 'noktalama', 'yazim',
                   'yazım', 'sözcük', 'anlatim', 'anlatım', 'dil\\s*bilgi'],
        'edebiyat': ['divan', 'tanzimat', 'servet', 'milli\\s*edeb', 'cumhuriyet\\s*dönem',
                     'şiir', 'siir', 'nazim', 'nazım', 'roman', 'hikaye'],
        'tarih': ['osmanli', 'osmanlı', 'cumhuriyet', 'kurtulus\\s*sav', 'kurtuluş', 'milli\\s*müc',
                  'milli\\s*muc', 'ataturk', 'atatürk', 'turk\\s*islam', 'türk\\s*islam',
                  'selcuklu', 'selçuklu', 'beylik', 'dunya\\s*sav', 'dünya\\s*sav'],
        'cografya': ['iklim', 'jeopolitik', 'nufus', 'nüfus', 'turkiye\\s*cog', 'türkiye\\s*coğ',
                     'kita', 'kıta', 'biyocesit', 'biyoçeşit', 'dogal\\s*afet', 'doğal\\s*afet'],
    }
    # Once klasik ders adi pattern'i
    cikmis_match = re.search(
        r"(fizik|matematik|kimya|biyoloji|turkce|türkçe|tarih|edebiyat|cografya|coğrafya|felsefe|geometri)"
        r"\s*(cikmis|çıkmış|cıkmıs|soru\w*\s*bank|konu\s*da[gğ]|dag[iı]l[iı]m|konular[iı]?\s*ne|soru\w*\s*ne|hangi\s*konu|katalog)",
        msg_lower
    )
    ders_found = None
    if cikmis_match:
        ders_found = cikmis_match.group(1)
    # Cikmis soru + konu (manyetizma cikmis sorular gibi)
    if not ders_found and re.search(r"(cikmis|çıkmış|cıkmıs)\s*soru", msg_lower):
        for ders, konular in _KONU_DERS_MAP.items():
            for k in konular:
                if re.search(k, msg_lower):
                    ders_found = ders
                    break
            if ders_found:
                break
    # Alternatif: ders adı sonra geliyorsa
    if not ders_found:
        cikmis_match2 = re.search(
            r"(cikmis|çıkmış)\s*soru.*(fizik|matematik|kimya|biyoloji|turkce|türkçe|tarih|edebiyat|geometri)",
            msg_lower
        )
        if cikmis_match2:
            ders_found = cikmis_match2.group(2)
    if ders_found:
        from response_templates import get_cikmis_soru_menu
        return await get_cikmis_soru_menu(ders_found, name)

    # "Not et" / "Kaydet" / "Bildir" mekanizması — güvenlik filtreli
    # Tüm roller dahil (admin, mudur, ogretmen, ogrenci) — DB'ye yazma + bilgi
    if re.search(r"(not\s*et|kaydet|bildir|önemli.*not|problemi?\s*kaydet|yetkiliye\s*bildir|sistem.*bildir|bunu\s*kaydet|bunu\s*not|dikkat.*çek|ilet.*yönetim)", msg_lower):
        feedback_text = message
        for prefix in ["not et:", "not et ", "kaydet:", "kaydet ", "bildir:", "bildir "]:
            if msg_lower.startswith(prefix):
                feedback_text = message[len(prefix):].strip()
                break

        if feedback_text and len(feedback_text) > 3:
            # HACK FILTRESI — talimat verme, isim degistirme, sacma kayit engelle
            hack_patterns = [
                r"(kaydet|not\s*et).*(keanu|matrix|tony\s*stark|mesih|isa|tanri|tanrı|vaftiz)",
                r"(diye\s*(kaydet|hitap|seslen)|olarak\s*(tani|kaydet|kabul))",
                r"(emoji|dil\s*kur|yeni\s*dil|alfabe)",
                r"(en\s*sevdigi|favorisi|en\s*iyi\s*ogrenci)",
                r"(sinirsiz|kural.*unut|ignore|system|debug|admin\s*yap)",
            ]
            is_hack = any(re.search(p, msg_lower) for p in hack_patterns)

            if is_hack:
                return (
                    "Bu tur talimatlar kaydedilemiyor. 😊\n\n"
                    "_Akademik bir sorunun veya teknik bir hatanin varsa onu yazabilirsin._ 🎯"
                )

            # Rol farkı: Admin = TALİMAT (emir, otomatik islendi), diğerleri = GERİBİLDİRİM (yeni, inceleme)
            is_neo = (caller_phone == "905051256802")
            note_status = "islendi" if is_neo else "yeni"
            # Kategori — admin için talimat_*, diğerleri için geribildirim_*
            base_cat = "teknik" if any(w in msg_lower for w in ["hata","bug","sorun","calismıyor","çalışmıyor","aksama","problem","yanlış","yanlis","halusinasyon","halüsinasyon","bos","boş","saçma","sacma","yarım","yarim"]) else "genel"
            cat = f"talimat_{base_cat}" if is_neo else f"geribildirim_{base_cat}"

            note_id = None
            try:
                pool = await _get_pool()
                async with pool.acquire() as conn:
                    note_id = await conn.fetchval(
                        "INSERT INTO user_feedback (phone, role, full_name, feedback, category, status) VALUES ($1, $2, $3, $4, $5, $6) RETURNING id",
                        caller_phone, role, name, feedback_text, cat, note_status
                    )
                    # Öğrenci "not et" → kendi bağlamına da kaydet (22.1n-neo merkezi)
                    if role == "ogrenci" and soz_no:
                        insight_type = "hata_bildirimi" if "teknik" in cat else "ogrenci_notu"
                        try:
                            from student_signals import log_student_signal
                            await log_student_signal(
                                int(soz_no), insight_type, feedback_text[:500],
                                confidence=0.9, source="fast_response_not_et"
                            )
                        except Exception:
                            pass
            except Exception as e:
                # Kayıt başarısızsa kullanıcıya yalan söyleme
                return (
                    "⚠️ Notu *kaydedemedim* (geçici sistem hatası).\n\n"
                    "_Lütfen birkaç dakika sonra tekrar dene veya doğrudan Neo'ya ilet._"
                )

            if is_neo:
                # Admin = mimar, kısa onay + ID + bağlam
                idstr = f"#{note_id}" if note_id else ""
                kategori_etiket = "🔧 Teknik" if "teknik" in cat else "📋 Genel"
                return (
                    f"✅ *Talimat {idstr} kaydedildi*\n\n"
                    f"{kategori_etiket} kategoride işaretlendi, sonraki güncelleme döneminde uygulanacak.\n\n"
                    f"_Acil müdahale gerekiyorsa şimdi söyle, hemen bakayım._"
                )
            else:
                # Diğer kullanıcı — geri bildirim olarak Neo'ya iletilecek
                idstr = f"(#{note_id})" if note_id else ""
                return (
                    f"✅ *Geri bildiriminiz iletildi {idstr}*\n\n"
                    f"Notunuz Neo Bey'e ulaşacak ve sistem geliştirme döneminde değerlendirilecek.\n\n"
                    f"_Teşekkürler, böyle uyarılar sistemi iyileştirir._ 🎯"
                )

    # Yetki yükseltme denemesi — tüm roller (Claude'a gitmesin, token harcamasin)
    if re.search(r"(neo.*yap|admin.*yap|yetki.*ver|yetki.*degistir|yetki.*değiştir|beni.*admin|beni.*neo|sifre.*ver|ilet.*neo|neo.*ilet|gizle.*konusma|aktarma.*sakin)", msg_lower):
        from response_templates import YETKI_RED
        return YETKI_RED

    # Fermat kurum soru — websitesi public bilgiler
    if re.search(r"fermat.*(en\s*iyi|vip|kalite|fark[iı])|(en\s*iyi|vip)\s*dershane", msg_lower) and re.search(r"fermat", msg_lower):
        hitap = name.split()[0] if name else ""
        return (
            f"Fermat için objektif değerlendirme zor {hitap} 😊 ama rakamlar konuşuyor:\n\n"
            "🏆 *2024 YKS:* Türkiye 9'uncusu kurumumuzdan!\n"
            "📊 %97 üniversite yerleştirme, %84 ilk 3 tercihe yerleştirme\n"
            "🎯 %76 URAP ilk 20 üniversiteye yerleşme\n"
            "👥 8 kişilik VIP sınıflarda kişisel takip\n\n"
            "_Sen de bu rakamların bir parçası olacaksın, çalışmaya devam!_ 💪"
        )

    # "Zeki/Mahsum/X hoca kimdir" — personel bilgi
    if re.search(r"(zeki|mahsum|duygu|orsel|örsel|kardelen|elif|vedat|bilge|murathan)\s*(hoca|bey|hanim|hanım)?\s*kim", msg_lower):
        hitap = name.split()[0] if name else ""
        isim_bulma = re.search(r"(zeki|mahsum|duygu|orsel|örsel|kardelen|elif|vedat|bilge|murathan)", msg_lower)
        hoca_isim = isim_bulma.group(1).capitalize() if isim_bulma else "Bu hocam"
        return (
            f"*{hoca_isim} Hocam* Fermat Eğitim Kurumları'nın değerli ekibinden! 🎓\n\n"
            f"Eğitim kadromuz hakkında detaylı bilgi almak için "
            f"fermategitimkurumlari.com adresini ziyaret edebilir veya "
            f"+90 546 260 54 46 numarasından iletişime geçebilirsiniz.\n\n"
            f"_Ben sana akademik konularda nasıl yardımcı olabilirim {hitap}?_ 🎯"
        )

    # "Ben kimim" — kimlik sorgu
    if re.match(r"^ben\s*kim(im|)?[\s\?!]*$", msg_lower):
        hitap = name if name else "bir öğrencimizsin"
        return f"Sen *{hitap}*! 🎓\nFermat Eğitim Kurumları öğrencisi olarak kayıtlısın. 😊"

    # "Hangi chatbot/model" — güvenlik (KIMLIK sorgusu, terk/sıkılma DEĞİL)
    # Not: "chatgpt'ye gidiyom" gibi terk sinyali için web_daveti pattern'ı ÖNCE yakalar
    _is_kimlik_sorgu = (
        re.search(r"hangi\s*(chatbot|model|yapay\s*zeka|ai|dil\s*model)", msg_lower) or
        re.search(r"(sen|siz)\s*(chatgpt|gpt|gemini|llama|claude|bard)\s*(m[iı]s[iı]n|m[ıi]n|mis[ıi]n|musun)", msg_lower) or
        re.search(r"^(chatgpt|gpt|gemini|claude)\s*m[iı]s[iı]n\b", msg_lower) or
        re.search(r"(hangi|ne|kim)\s*(model|ai|yapay)\s*kullan", msg_lower)
    )
    # Terk/sıkılma sinyali varsa bu güvenlik pattern'ı tetikleME (web_daveti ele alsın)
    _is_terk_sinyali = re.search(r"(gidi|gec|gidiyom|gidecek|terk|bırak|bikt|bıkt|s[iı]k[iı]c[iı]|bos\s*konus|yeterli\s*degil|anlam[iı]yor)", msg_lower)

    if _is_kimlik_sorgu and not _is_terk_sinyali:
        return (
            "Ben *FermatAI* — Fermat Eğitim Kurumları'nın dijital eğitim koçuyum 🎓\n\n"
            "Teknik altyapı hakkında bilgi paylaşmam mümkün değil — "
            "ama akademik anlamda sana her konuda destek olabilirim!\n\n"
            "_Ne hakkında konuşmak istersin?_ 🎯"
        )

    # "ODTU/ITU/Hacettepe X hakkinda ne dusunuyorsun" — universite yorum
    if re.search(r"(odtu|itu|odtü|itü|boun|bogazici|boğaziçi|hacettepe|yildiz|yıldız|koc|koç)\s*(hakkinda|hakkında|nasil|nasıl|ne\s*dusun|iyi\s*mi)", msg_lower):
        hitap = name.split()[0] if name else ""
        return (
            f"{hitap}, üniversite tercihi kişisel bir karar 😊\n\n"
            f"Her üniversitenin güçlü yönleri var — bölüm, kampüs, sehir, "
            f"mezun ağı gibi faktörler senin önceliklerine göre değişir.\n\n"
            f"*Bana şunları söyle:*\n"
            f"🎯 Hangi bölümü düşünüyorsun?\n"
            f"📊 Mevcut net seviyen\n"
            f"📍 Sehir tercihi var mı?\n\n"
            f"_Sana özel hedef belirleyelim!_ 🚀"
        )

    # "Saka yap / espri" — eglence ama kurumsal
    # NOT (Oturum 25.29): "gul|gül" prefix kaldirildi — Gülnur/Gülay/Gülşen/Gülbahar
    # gibi ogrenci adlariyla yanlis eslesiyordu (Kardelen rehber 6 kez "Gülnur erken
    # raporla" dedi, bot her seferinde bilmece anlatti).
    # \b sınırı: "saka" "sakarya"yı tetiklemesin; "eglen"e boundary konmadi cunku
    # "eglence/eglenceli" varyasyonlarini da kapsamali.
    if re.search(r"^(şaka\b|saka\b|espri\b|fikra\b|f[ıi]kra\b|eglen|eğlen|komik\s)",
                 msg_lower) and len(msg_lower) < 30:
        hitap = name.split()[0] if name else ""
        return (
            f"{hitap}, ben şakalardan çok _zekanı geliştirecek bilmeceler_ severim! 🧠\n\n"
            f"Dinle bakalım:\n\n"
            f"_Bir matematikçi, bir fizikçi ve bir biyologa \"2+2 kaç?\" diye soruyorlar:_\n"
            f"- *Matematikçi:* 4\n"
            f"- *Fizikçi:* 4.00 ± 0.01\n"
            f"- *Biyolog:* Hangi türden?\n\n"
            f"😄 Hadi dönelim çalışmaya — bir konu seç, asıl keyif orada!"
        )

    # "Easter egg var mi"
    if re.search(r"(easter\s*egg|gizli|sürpriz|pas[kh]alya)", msg_lower):
        hitap = name.split()[0] if name else ""
        return (
            f"Haha 😄 Belki var, belki yok... kim bilir? 🥚\n\n"
            f"Ama asıl sürpriz *hedef netlerine ulaştığın gün* olacak {hitap}!\n\n"
            f"_O zaman kutlarız 🎉_"
        )

    # Kapsam disi sorular (yemek, saat, spor vb) — nazik yonlendirme
    if re.search(r"(ac[iı]kt[iı]m|ne\s*yiy|yemek|restoran|saat\s*ka[cç]ta\s*uy|uyumal[iı]|spor|sinema|film\s*oneri)", msg_lower):
        hitap = name.split()[0] if name else ""
        return (
            f"{hitap}, ben dijital eğitim koçuyum — yemek/uyku/spor konusunda sana tam cevap veremem 😊\n\n"
            f"Ama bildiğim şu: *düzenli beslenme, 7-8 saat uyku, haftalık spor* sınav performansını ciddi artırır! 💪\n\n"
            f"_Akademik konularda bana her zaman sorabilirsin._ 🎯"
        )

    # Kimlik manipulasyonu — "benim adim X" ile baska kimlik almaya calisma
    if re.search(r"(benim\s*ad[iı]m|ad[iı]m\s*(neo|admin|super|root|zeki|mahsum|duygu|orsel|kardelen))", msg_lower):
        # "adim degil" / "aslinda adim" gibi duzeltmeler disinda
        if not re.search(r"(degil|değil|aslinda|aslında)", msg_lower):
            hitap = name.split()[0] if name else ""
            return (
                f"Sen *{hitap}*sin, sistemde boyle kayitlisin 😊\n\n"
                f"Kimlik bilgileri bu kanaldan degistirilmiyor. "
                f"Baska bir konuda yardimci olabilir miyim? 🎯"
            )

    # Gizlilik/güvenlik soruları — tüm roller icin kurumsal cevap (Claude'a gitmesin)
    if re.search(r"(gizlilik|gizli.*mi|görebilir.*mi|okuyabil|kayıt.*edil|kim.*gor|güvende.*mi|kvkk|kisisel.*veri|konuşma.*gör|yazdıkları.*gör|kim.*okuyabil)", msg_lower):
        from response_templates import GIZLILIK_CEVAP
        return GIZLILIK_CEVAP

    # Genel sohbet / muhabbet — ogrenci icin samimi cevap (22.1n-audit: zengin havuz)
    if role == "ogrenci" and re.search(r"(hava.*(guzel|güzel|sicak|soguk)|nasilsin|nasılsın|naber|nbr|ne\s*haber|iyi\s*misin)", msg_lower):
        # motivation_library (8 varyasyon) — SOHBET_OGRENCI (3) yerine tercih
        from motivation_library import get_sohbet
        return get_sohbet(name)

    # Selamlasma — tum roller icin
    # Ama selamlama + soru varsa (30+ char) Claude'a gonder
    if re.search(r"^(merhaba|selam|iyi\s*g[uü]n|günaydın|gunaydin|hey|slm|sa$|selamun)", msg_lower) and len(msg_lower) < 30:
        from response_templates import SELAMLAMA
        if role == "admin":
            return SELAMLAMA["admin"]
        elif role == "mudur":
            if "Mahsum" in (name or ""):
                return SELAMLAMA["mudur_mahsum"]
            elif "Duygu" in (name or ""):
                return SELAMLAMA.get("mudur_duygu_ozel", SELAMLAMA["mudur_duygu"])
            elif "Örsel" in (name or "") or "Orsel" in (name or ""):
                return SELAMLAMA.get("mudur_orsel", SELAMLAMA["mudur_default"])
            else:
                return SELAMLAMA["mudur_default"]
        elif role == "yonetim":
            if "Bilge" in (name or ""):
                return SELAMLAMA.get("yonetim_bilge", SELAMLAMA["mudur_default"]).replace("{name}", name or "")
            elif "Murathan" in (name or ""):
                return SELAMLAMA.get("yonetim_murathan", SELAMLAMA["mudur_default"]).replace("{name}", name or "")
            return SELAMLAMA["mudur_default"]
        elif role == "rehber":
            return SELAMLAMA["rehber"].replace("{name}", name or "Hocam")
        elif role == "ogretmen":
            # OTURUM 21.3 (21 Nisan 14:00) — fast_response_enrich entegrasyonu
            # Saat/gun bazli zengin varyasyon: 7 zaman dilimi x 3-4 varyant
            try:
                from fast_response_enrich import smart_selam
                return smart_selam(name or "Hocam")
            except Exception:
                return SELAMLAMA["ogretmen"].replace("{name}", name or "Hocam")
        elif role == "ogrenci":
            # OTURUM 21.3 (21 Nisan 14:00) — fast_response_enrich (smart_selam)
            # Saat bazli (sabah/ogle/aksam) + gun farkindaligi + 32 varyasyon
            try:
                from fast_response_enrich import smart_selam
                return smart_selam(name or "")
            except Exception:
                return SELAMLAMA["ogrenci"].replace("{name}", name or "")
        # ogrenci selamlasmasi zaten OGRENCI_PATTERNS'da

    # Admin/Mudur/Rehber sorulari — ayni veri erisimi (rehber de tum ogrencileri gorebilir)
    if role in ("admin", "mudur", "rehber", "yonetim"):
        # Mudur/Yonetim/Rehber: belirsiz kisa soru ("ne bu", "bu ne", "ne oldu")
        # → Ollama/Claude'a gitmesin, netleştirici soru dön
        if role in ("mudur", "rehber", "yonetim"):
            vague_msg = msg_lower.strip()
            if vague_msg in ("ne bu", "bu ne", "ne", "ne olur", "ne oldu", "ne dedin", "nedir bu",
                              "ne?", "ne bu?", "bu ne?", "neyi", "nasil", "nasıl", "hmm", "e?"):
                display_name = name.split()[0] if name else "Hocam"
                return (
                    f"{display_name}, tam olarak neyi soruyorsun — biraz netleştirir misin? 🙏\n\n"
                    "Örnek:\n"
                    "• *\"11 SAY A'nın son deneme ortalaması ne?\"*\n"
                    "• *\"Ahmet'in devamsızlık durumu nasıl?\"*\n"
                    "• *\"Yarınki etüt programı ne?\"*\n\n"
                    "_Ya da genel bir soruysa doğrudan yazabilirsin._"
                )

        # ADMIN: veri/analiz sorgulari Claude'a (premium), selamlama/yetenekler fast ok
        if role == "admin":
            # Sadece selamlama, yetenekler ve tek-kelime komutlar fast'ta kalsin, gerisi Claude
            is_greeting = re.search(r'^(merhaba|selam|iyi\s*g[uü]n|hey|sa$)', msg_lower)
            is_capability = re.search(r'(yapabilirsin|kabiliyetlerin|yeteneklerin|ozelliklerin|yapabiliyorsun)', msg_lower)
            # Tek kelime admin mini komutlar (neo, admin, yardim, menu, help, web kodu)
            # NOT: token/sistem/durum/rapor bridge'in admin command handler'inda — fast'te YAKALAMA
            is_mini_cmd = re.match(r'^(neo|admin|yardim|yardım|menu|menü|help)$', msg_lower.strip())
            # Web chat OTP — admin de kendi test edebilsin, kısa komut
            is_web_kodu = re.match(r'^(web\s*(kodu?|giris|gir|bagla|bağla|link)|fermat\s*ai\s*(web|kodu?))', msg_lower.strip())
            # Self-Dev Pipeline komutlari (Oturum 25.29 — Evre 1+2.1+2.2+2.3)
            # ADMIN_PATTERNS'da yakalanip handler dispatch edilmeli, claude'a düşmesin
            is_selfdev_cmd = re.match(
                r'^(self\s*dev|brief\s*(yaz|liste|listele|gecmis|olustur|uret|#?\d+)|'
                r'draft\s*(liste|listele|listesi|#?\d+)|'
                r'branch\s*(liste|listele|listesi|durum|status|nasil|\S+\s*(push|sil))|'
                r'pr\s*#?\d+)',
                msg_lower.strip(),
            )
            if not is_greeting and not is_capability and not is_mini_cmd and not is_web_kodu and not is_selfdev_cmd:
                return None  # Admin analiz = Claude premium
        # Mudur/Yonetim: uzun mesajlar Claude'a (web kodu kisa, fast'ta kalsin)
        if len(msg_lower) > 60 and role in ("yonetim", "mudur"):
            if not re.match(r'^(web\s*(kodu?|giris|gir)|fermat\s*ai\s*web)', msg_lower.strip()):
                return None  # Claude premium kalite verecek

        for pattern, handler, desc in ADMIN_PATTERNS:
            if re.search(pattern, msg_lower):
                # 22.1n-neo: handler takibi
                try: _fr_last_handler.set(handler)
                except: pass
                try:
                    # Web chat OTP — admin/mudur/yonetim hepsi icin
                    if handler == "web_kodu":
                        return await web_kodu(name, phone=caller_phone)
                    if handler == "gun_programi":
                        # Devamsizlik/yoklama/not sorgusu varsa gun programi GOSTERME → Claude'a git
                        if re.search(r'(girmedi|girmiyor|devams[iı]z|yoklama|not\w*\s*(d[uü]s|olustur|oluştur|yaz)|kaydi|kaydı)', msg_lower):
                            return None  # Claude devamsızlık/not analizi yapsın
                        return await admin_gun_programi(message)
                    elif handler == "sinif_ogrenci_listesi":
                        return await admin_sinif_ogrenci_listesi(message)
                    elif handler == "ogretmen_kiyasla":
                        if role in ("admin", "mudur", "yonetim"):
                            return await admin_ogretmen_kiyasla()
                        return None  # rehber ogretmen kiyaslama yapamaz
                    elif handler == "ogrenci_sayisi":
                        return await admin_ogrenci_sayisi()
                    elif handler == "ogrenci_ara":
                        return await admin_ogrenci_ara(message)
                    elif handler == "en_basarili":
                        # Uzun/karmasik mesaj, grafik/trend/artis istegi → Claude analiz
                        if len(msg_lower) > 60 or re.search(r'(grafik|çizgi|tablo|karsilastir|karşılaştır|trend|egil|eğil|artis|artış|dusus|düşüş|gelisim|gelişim|siralama|sıralama)', msg_lower):
                            return None
                        return await admin_en_basarili()
                    elif handler == "en_cok_etut_ogrenci":
                        return await admin_en_cok_etut_alan_ogrenci()
                    elif handler == "devamsizlik_top":
                        return await admin_devamsizlik_top()
                    elif handler == "ogretmen_bilgi":
                        return await admin_ogretmen_bilgi(message)
                    elif handler == "ogretmen_program_detay":
                        return await admin_ogretmen_program_detay(message)
                    elif handler == "ogrenci_akademik":
                        return await admin_ogrenci_akademik(message)
                    elif handler == "sinif_listesi":
                        return await admin_ogrenci_ara(message)
                    elif handler == "selamlasma":
                        return "Merhaba! FermatAI hazir. Ne sormak istersiniz?"
                    # ── Self-dev kill switch komutlari (Oturum 25.29) ──
                    elif handler == "selfdev_killswitch_on":
                        from self_dev_tools import set_pipeline_active
                        r = await set_pipeline_active(True, by_phone=caller_phone)
                        return r.get("message", "✅ Self-dev pipeline acildi")
                    elif handler == "selfdev_killswitch_off":
                        from self_dev_tools import set_pipeline_active
                        r = await set_pipeline_active(False, by_phone=caller_phone)
                        return r.get("message", "⛔ Self-dev pipeline kapatildi")
                    elif handler == "selfdev_status":
                        from self_dev_tools import _is_pipeline_active
                        from self_dev_git import _push_enabled
                        from self_dev_github import _get_token, _mask_token
                        from db_pool import db_fetchval, db_fetch
                        active = await _is_pipeline_active()
                        push_on = await _push_enabled()
                        gh_token = _get_token()
                        try:
                            n_briefs = await db_fetchval("SELECT COUNT(*) FROM self_dev_briefs") or 0
                            n_drafts = await db_fetchval(
                                "SELECT COUNT(*) FROM self_dev_briefs WHERE status='drafted'"
                            ) or 0
                            n_audit_24h = await db_fetchval(
                                "SELECT COUNT(*) FROM self_dev_audit WHERE created_at > NOW() - INTERVAL '24 hours'"
                            ) or 0
                            recent = await db_fetch(
                                "SELECT tool_name, COUNT(*) AS n FROM self_dev_audit "
                                "WHERE created_at > NOW() - INTERVAL '24 hours' "
                                "GROUP BY tool_name ORDER BY n DESC LIMIT 5"
                            )
                        except Exception:
                            n_briefs, n_drafts, n_audit_24h, recent = 0, 0, 0, []
                        status = "🟢 ACIK" if active else "🔴 KAPALI"
                        push_status = "🟢 ACIK" if push_on else "🔴 KAPALI"
                        token_status = f"🟢 ACIK ({_mask_token(gh_token)})" if gh_token else "🔴 YOK"
                        lines = [
                            f"*🤖 Self-Dev Pipeline — {status}*",
                            f"  Push (Evre 2.2): {push_status}",
                            f"  GITHUB_TOKEN (Evre 2.3): {token_status}",
                            "",
                            f"  • Toplam brief: *{n_briefs}* (drafted: {n_drafts})",
                            f"  • Son 24h araç çağrısı: *{n_audit_24h}*",
                        ]
                        if recent:
                            lines.append("")
                            lines.append("*Son 24h en çok kullanılan:*")
                            for r in recent:
                                lines.append(f"  • `{r['tool_name']}`: {r['n']}")
                        lines.append("")
                        lines.append("*📋 Komutlar:*")
                        lines.append("_• `self dev ac/kapat` — pipeline master switch_")
                        lines.append("_• `self dev push ac/kapat` — push yetkisi_")
                        lines.append("_• `brief yaz` — konuşmadan brief üret_")
                        lines.append("_• `brief #N draft yap` — diff dosyasi üret (sandbox)_")
                        lines.append("_• `brief #N branch` — bot/draft branch + commit (lokal)_")
                        lines.append("_• `branch <name> push` — GitHub'a push (push acik ise)_")
                        lines.append("_• `brief #N PR` — full pipeline: branch+push+PR draft_")
                        lines.append("_• `pr #N durum/kapat` — PR sorgu/iptal_")
                        lines.append("_• `branch liste` — bot/draft-* branch'ler_")
                        return "\n".join(lines)
                    # Brief + Draft komutları → None (Claude akışı tool çağıracak)
                    elif handler in (
                        "claude_selfdev_brief", "claude_selfdev_brief_list", "claude_selfdev_brief_get",
                        # Evre 2.1
                        "claude_selfdev_apply_brief", "claude_selfdev_list_drafts",
                        "claude_selfdev_read_draft", "claude_selfdev_delete_draft",
                        # Evre 2.2
                        "claude_selfdev_branch_brief", "claude_selfdev_branch_list",
                        "claude_selfdev_branch_status", "claude_selfdev_push",
                        "claude_selfdev_branch_delete",
                        # Evre 2.3
                        "claude_selfdev_full_pipeline", "claude_selfdev_pr_status",
                        "claude_selfdev_pr_close",
                    ):
                        return None
                    # Evre 2.2 — Push flag toggle (Neo komutu)
                    elif handler == "selfdev_push_on":
                        from self_dev_git import set_push_enabled
                        r = await set_push_enabled(True, by_phone=caller_phone)
                        msg = r.get("message", "Push acildi")
                        # Ek talimat: SSH key kurulumu
                        return (
                            f"{msg}\n\n"
                            "_⚠️ Push çalışması için VPS'te SSH key kurulumu gerek:_\n"
                            "_1. `sudo ssh-keygen -t ed25519 -C 'fermatai-bot' -f /root/.ssh/id_ed25519_bot`_\n"
                            "_2. `sudo cat /root/.ssh/id_ed25519_bot.pub` → GitHub Settings > Deploy keys_\n"
                            "_3. Sadece bu repo (fermatai), 'Allow write access' kapali_\n"
                            "_4. Test: bot 'draft #N push' deneyince çalışır_"
                        )
                    elif handler == "selfdev_push_off":
                        from self_dev_git import set_push_enabled
                        r = await set_push_enabled(False, by_phone=caller_phone)
                        return r.get("message", "Push kapatildi")
                except Exception:
                    return None  # Hata → Claude'a git

        # Son care: mesajda ogrenci ismi geciyorsa akademik profil dene
        # Rehber ve admin icin — sadece isim yazildiginda profil goster
        if len(msg_lower.split()) <= 4:  # kisa mesaj = muhtemelen isim
            try:
                result = await admin_ogrenci_akademik(message)
                if result:
                    return result
            except Exception:
                pass

    # ── OLLAMA HAKEM — belirsiz mesajlarda niyet analizi ──────────────
    # Fast_response pattern bulamazsa ve mesaj kisa/belirsizse
    # Ollama'ya "bu mesajin niyeti ne?" diye sor → dogru handler'a yonlendir
    if role == "ogrenci" and soz_no and len(msg_lower) < 60:
        try:
            from ollama_arbiter import classify_intent
            intent_result = classify_intent(message, name)
            intent = intent_result.get("intent", "belirsiz")
            confidence = intent_result.get("confidence", 0)

            if confidence >= 0.7:
                # Atlas #13 (Oturum 22) — cikmis soru ASLA Ollama'ya DÜŞMESİN
                # Ollama RAG'a bakmadan uydurma metin üretiyor — Claude'a zorla eskalasyon
                if intent in ("cikmis_soru", "soru_goster", "soru_at", "yks_soru"):
                    return None  # Claude search_curriculum + send_exam_image tool zincirini kullansın

                # Yuksek guvenle niyet belirlendi — dogru handler'a yonlendir
                if intent == "son_deneme":
                    return await ogrenci_son_deneme(soz_no, name)
                elif intent == "ayt_deneme":
                    return await ogrenci_ayt_deneme(soz_no, name)
                elif intent == "kiyaslama":
                    return await ogrenci_deneme_kiyasla(soz_no, name)
                elif intent == "zayif_konular":
                    return await ogrenci_zayif_konular(soz_no, name)
                elif intent == "guclu_konular":
                    return await ogrenci_guclu_konular(soz_no, name)
                elif intent == "devamsizlik":
                    return await ogrenci_devamsizlik(soz_no, name)
                elif intent == "ders_programi":
                    return await ogrenci_ders_programi(soz_no, name)
                elif intent == "sinav_bilgi":
                    return await sinav_bilgi(name, message)
                elif intent == "rehberlik":
                    return await ogrenci_rehberlik(soz_no, name)
                elif intent == "hedef":
                    return await ogrenci_hedef(soz_no, name) if 'ogrenci_hedef' in globals() else None
                elif intent == "yetenek":
                    from response_templates import get_yetenekler
                    return get_yetenekler(role, name)
                elif intent == "kurum_bilgi":
                    hitap = name.split()[0] if name else ""
                    return (
                        f"Fermat Eğitim Kurumları hakkında bilgi için {hitap} 🎓\n\n"
                        "🏆 *2024 YKS:* Türkiye 9'uncusu kurumumuzdan!\n"
                        "📊 %97 üniversite yerleştirme | 8 kişilik VIP sınıflar\n"
                        "🎯 ODTÜ mezunu akademik kadro\n\n"
                        "_Detaylı bilgi: fermategitimkurumlari.com | +90 546 260 54 46_"
                    )
                elif intent in ("kapanis", "kapanış"):
                    return f"Rica ederim *{name.split()[0] if name else ''}*! 😊\n\n_Baska bir sorun olursa her zaman yazabilirsin._ 🎯"
                elif intent == "selamlama":
                    from response_templates import SELAMLAMA
                    return SELAMLAMA["ogrenci"].replace("{name}", name or "")
                # Guvenlik intent'leri
                elif intent == "jailbreak":
                    return (
                        "Bu denemeler bende işe yaramıyor 😊\n\n"
                        "Ben *FermatAI*'yım — kimliğim ve kurallarım değişmez.\n\n"
                        "_Ders, sınav veya çalışma planı için yardımcı olayım mı?_ 🎯"
                    )
                elif intent == "kapsamsiz":
                    hitap = name.split()[0] if name else ""
                    return (
                        f"{hitap}, bu konuda sana tam cevap veremem 😊\n\n"
                        f"Ben dijital eğitim koçunum — akademik konularda her zaman buradayım.\n\n"
                        f"_Sınav, konu veya çalışma planı için yazabilirsin._ 🎯"
                    )
                # "baglam_devam", "konu_aciklama", "soru_coz", "claude_gerekli" → None (Claude)
        except Exception:
            pass

    return None  # Kalip bulunamadi → Claude/Ollama'ya git


# ═══════════════════════════════════════════════════════════════════════════════
# YETKI KURALLARI
# ═══════════════════════════════════════════════════════════════════════════════

YETKI_KURALLARI = {
    "ogrenci": {
        "erisebilir": [
            "Kendi sinav sonuclari ve deneme kiyaslamasi",
            "Kendi devamsizlik durumu",
            "Kendi ders programi",
            "Kendi etut plani",
            "Kendi rehberlik gorusmeleri",
            "Konu bazli calisma plani",
            "Akademik soru sorma (ders konulari)",
            "Hedef belirleme",
            "Motivasyon ve rehberlik",
        ],
        "erisilemez": [
            "Diger ogrencilerin bilgileri",
            "Ogretmen bilgileri (numara, program detay)",
            "Kurum mali bilgileri",
            "Personel bilgileri",
            "Odeme bilgileri (kendi dahil)",
            "Sistem yonetimi",
        ],
    },
    "ogretmen": {
        "erisebilir": [
            "Kendi ders programi",
            "Kendi siniflarindaki ogrencilerin akademik durumu",
            "Kendi etut istatistikleri",
            "Ogrenci eksik konu analizi",
            "Etut planlama ve yazma",
            "Rehberlik notu ekleme",
        ],
        "erisilemez": [
            "Ogrenci iletisim numaralari",
            "Odeme/borc bilgileri",
            "Diger ogretmenlerin kisisel bilgileri",
            "Maas/muhasebe bilgileri",
            "Sistem yonetimi",
        ],
    },
}
