"""
FermatAI PDF Rapor Oluşturucu
==============================
Öğrenci bazlı akademik rapor PDF olarak oluşturur.
WP üzerinden paylaşılabilir.

Kullanım:
  python pdf_report.py <soz_no>
  python pdf_report.py 200  # Ali Küçükuysal

FEATURE FLAG: Hazır ama Neo aktif edene kadar WP'den erişilemez.
"""

import asyncio
import os
import sys
from datetime import date, datetime

from fpdf import FPDF
from db_pool import get_pool as _get_pool
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "reports")


def _resolve_unicode_fonts():
    """Regular/Bold/Italic için MEVCUT Unicode TTF yollarını döner (platform-bağımsız).
    BUG1 fix (26 May): eskiden C:/Windows/Fonts hardcode'luydu → Linux VPS'te crash.
    Linux'ta LiberationSans (Arial-uyumlu) / DejaVu, Windows'ta Arial denenir."""
    candidates = {
        "regular": [
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ],
        "bold": [
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
        ],
        "italic": [
            "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
            "C:/Windows/Fonts/ariali.ttf",
        ],
    }
    def pick(style):
        for p in candidates[style]:
            if os.path.exists(p):
                return p
        return None
    reg = pick("regular")
    if not reg:
        raise RuntimeError(
            "PDF raporu için Unicode TTF font bulunamadı (LiberationSans/DejaVu/Arial). "
            "Linux'ta çözüm: apt install fonts-liberation")
    return reg, (pick("bold") or reg), (pick("italic") or reg)


class FermatReport(FPDF):
    """Fermat kurumsal PDF şablonu."""

    def __init__(self):
        super().__init__()
        # Türkçe karakter desteği — platform-bağımsız Unicode font (BUG1 fix)
        _reg, _bold, _ital = _resolve_unicode_fonts()
        # fpdf2'de uni param deprecated — TTF'ler zaten Unicode (uni=True KALDIRILDI)
        self.add_font("Arial", "", _reg)
        self.add_font("Arial", "B", _bold)
        self.add_font("Arial", "I", _ital)

    def header(self):
        self.set_font("Arial", "B", 14)
        self.cell(0, 10, "FERMAT EGITIM KURUMLARI", 0, 1, "C")
        self.set_font("Arial", "", 9)
        self.cell(0, 5, "Akademik Performans Raporu", 0, 1, "C")
        self.line(10, self.get_y() + 2, 200, self.get_y() + 2)
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font("Arial", "I", 8)
        self.cell(0, 10, f"FermatAI - {date.today().strftime('%d.%m.%Y')} - Sayfa {self.page_no()}", 0, 0, "C")

    def section_title(self, title):
        self.set_font("Arial", "B", 12)
        self.set_fill_color(230, 230, 250)
        self.cell(0, 8, f"  {title}", 0, 1, "L", True)
        self.ln(3)

    def key_value(self, key, value, bold_value=False):
        self.set_font("Arial", "", 10)
        self.cell(50, 6, f"  {key}:", 0, 0)
        self.set_font("Arial", "B" if bold_value else "", 10)
        self.cell(0, 6, str(value), 0, 1)


async def generate_student_pdf(soz_no) -> str:
    soz_no = int(soz_no)  # normalize
    """Öğrenci PDF raporu oluştur. Dosya yolunu döndür."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        # Öğrenci bilgisi
        student = await conn.fetchrow(
            "SELECT full_name, class_name, program, devre FROM students WHERE soz_no::int = $1", soz_no)
        if not student:
            return ""

        name = student['full_name']
        sinif = student.get('class_name', '?')

        # Son 5 deneme
        exams = await conn.fetch("""
            SELECT exam_name, exam_date, turkce, matematik, geometri, fizik, kimya, biyoloji, toplam
            FROM student_exams WHERE soz_no::int = $1
            ORDER BY exam_date DESC NULLS LAST LIMIT 5
        """, soz_no)

        # Devamsızlık
        devam = await conn.fetchval(
            "SELECT toplam_saat FROM devamsizlik_sayisi WHERE soz_no::int = $1", soz_no)

        # Zayıf konular — sinav_hata_yuzdesi = HATA % (yüksek=zayıf)
        # INVERSION FIX (Berf bug 10 May): ASC → DESC + metadata filter + >=25 esik
        topics = await conn.fetch("""
            SELECT ders, konu, sinav_hata_yuzdesi
            FROM student_topic_tracker
            WHERE soz_no::int = $1 AND tamamlandi = FALSE
              AND COALESCE(status,'') != 'metadata'
              AND konu NOT LIKE 'Ortalama %'
              AND sinav_hata_yuzdesi >= 25
            ORDER BY sinav_hata_yuzdesi DESC NULLS LAST LIMIT 8
        """, soz_no)

        # Rehberlik notu sayısı (içerik GİZLİ)
        reh_count = await conn.fetchval(
            "SELECT COUNT(*) FROM counsellor_notes WHERE soz_no::int = $1", soz_no)

        # Etüt
        etut = await conn.fetchrow(
            "SELECT toplam, yapildi FROM etut_student_control WHERE soz_no::int = $1", soz_no)

    # PDF oluştur
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    pdf = FermatReport()
    pdf.add_page()

    # Öğrenci bilgisi
    pdf.section_title("Ogrenci Bilgileri")
    pdf.key_value("Ad Soyad", name, bold_value=True)
    pdf.key_value("Sinif", sinif)
    pdf.key_value("Rapor Tarihi", date.today().strftime("%d.%m.%Y"))
    pdf.ln(5)

    # Son denemeler
    if exams:
        pdf.section_title("Son Deneme Sonuclari")
        # Tablo başlığı
        pdf.set_font("Arial", "B", 9)
        headers = ["Sinav", "Tarih", "Tur", "Mat", "Fiz", "Kim", "Bio", "TOPLAM"]
        widths = [50, 20, 15, 15, 15, 15, 15, 20]
        for h, w in zip(headers, widths):
            pdf.cell(w, 6, h, 1, 0, "C")
        pdf.ln()

        # Satırlar
        pdf.set_font("Arial", "", 9)
        for e in reversed(exams):
            pdf.cell(50, 6, str(e['exam_name'] or '?')[:25], 1, 0)
            pdf.cell(20, 6, str(e['exam_date'] or '?'), 1, 0, "C")
            for col in ['turkce', 'matematik', 'fizik', 'kimya', 'biyoloji']:
                v = e.get(col)
                pdf.cell(15, 6, f"{v:.1f}" if v else "-", 1, 0, "C")
            pdf.set_font("Arial", "B", 9)
            pdf.cell(20, 6, f"{e['toplam']:.1f}" if e['toplam'] else "-", 1, 0, "C")
            pdf.set_font("Arial", "", 9)
            pdf.ln()

        # Trend
        if len(exams) >= 2:
            diff = (exams[0]['toplam'] or 0) - (exams[-1]['toplam'] or 0)
            trend = f"+{diff:.1f} net artis" if diff > 0 else f"{diff:.1f} net dusus"
            pdf.ln(2)
            pdf.set_font("Arial", "I", 9)
            pdf.cell(0, 5, f"Trend: {trend} (son {len(exams)} deneme)", 0, 1)
        pdf.ln(3)

    # Devamsızlık
    pdf.section_title("Devamsizlik")
    if devam is not None:
        durumu = "Normal" if devam < 30 else "Dikkat" if devam < 80 else "Kritik"
        pdf.key_value("Toplam", f"{devam} saat ({durumu})", bold_value=True)
    else:
        pdf.key_value("Durum", "Devamsizlik kaydi yok")
    pdf.ln(3)

    # Zayıf konular — INVERSION FIX: hata yüksek = ACIL
    if topics:
        pdf.section_title("Gelisim Alanlari (Zayif Konular)")
        pdf.set_font("Arial", "", 9)
        for i, t in enumerate(topics, 1):
            hata = t.get('sinav_hata_yuzdesi', 0) or 0
            basari = max(0.0, min(100.0, 100.0 - float(hata)))
            oncelik = "ACIL" if hata >= 50 else "Orta" if hata >= 25 else "Iyi"
            pdf.cell(0, 5, f"  {i}. {t['ders']} - {t['konu'][:40]} (basari: %{basari:.0f}, oncelik: {oncelik})", 0, 1)
        pdf.ln(3)

    # Etüt + Rehberlik
    pdf.section_title("Etut ve Rehberlik")
    if etut and etut['toplam']:
        pdf.key_value("Etut", f"{etut['toplam']} planlanmis, {etut.get('yapildi', 0)} katilim")
    else:
        pdf.key_value("Etut", "Kayit yok")
    pdf.key_value("Rehberlik", f"{reh_count} gorusme kaydi")
    pdf.ln(5)

    # YKS Puan Tahmin (Hafta 4.1 entegrasyonu)
    try:
        from puan_tahmin import tahmin_et
        ph = await tahmin_et(str(soz_no))
        if 'tahmin' in ph:
            pdf.section_title("YKS Puan Tahmini")
            pdf.key_value("TYT puani", f"~{ph['tahmin']['tyt_puan']:.0f}")
            if ph['tahmin']['ayt_say']:
                pdf.key_value("Sayisal (SAY)", f"~{ph['tahmin']['ayt_say']:.0f}")
            if ph['tahmin']['ayt_ea']:
                pdf.key_value("Esit Agirlik (EA)", f"~{ph['tahmin']['ayt_ea']:.0f}")
            pdf.set_font("Arial", "I", 8)
            pdf.cell(0, 5, "Tahmin: son 3 deneme ortalamasi - YKS resmi formul", 0, 1)
            pdf.set_font("Arial", "", 10)
            pdf.ln(3)
    except Exception as e:
        pass  # tahmin yapamazsa atla

    # Oneri
    pdf.section_title("Oneriler")
    pdf.set_font("Arial", "", 10)
    if topics:
        pdf.multi_cell(0, 5,
            f"Ogrencinin en zayif alani {topics[0]['ders']} - {topics[0]['konu'][:30]}. "
            f"Bu konuya oncelikli olarak calisilmasi onerilir. "
            f"Haftalik duzenlı etut plani ile iyilestirme saglanabilir.")
    else:
        pdf.multi_cell(0, 5, "Konu bazli analiz icin daha fazla deneme verisi gereklidir.")

    # Kaydet
    safe_name = name.replace(" ", "_").replace("İ", "I").replace("Ö", "O").replace("Ü", "U").replace("Ş", "S").replace("Ç", "C").replace("Ğ", "G")
    filename = f"{safe_name}_{date.today().strftime('%Y%m%d')}.pdf"
    filepath = os.path.join(OUTPUT_DIR, filename)
    pdf.output(filepath)

    return filepath


async def main():
    if len(sys.argv) < 2:
        print("Kullanim: python pdf_report.py <soz_no>")
        return
    soz_no = int(sys.argv[1])
    path = await generate_student_pdf(soz_no)
    if path:
        print(f"PDF olusturuldu: {path}")
    else:
        print("Ogrenci bulunamadi!")


if __name__ == "__main__":
    asyncio.run(main())
