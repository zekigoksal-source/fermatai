"""
Öğretmen Eskalasyon Chain (Oturum 22.1l)
==========================================

Öğrenci → Bot → Hoca zinciri:

1. Öğrenci "X dersi etüt istiyorum" der
2. Bot:
   - Hangi hoca uygun (teacher_timetable + brans)
   - Öğrencinin son 3 denemesi + zayıf konular (özet)
   - Müsait saatler (teacher_timetable'da bos slotlar)
3. Hocaya WhatsApp mesaj:
   "📝 [Öğrenci] için X dersi etüt talebi
   Son 3 TYT: [netler]
   Zayıf: [konu1, konu2]
   Müsait saatlerin: [Pzt 14:00 / Per 15:00 / ...]
   Uygun mu?"
4. Hoca "Perşembe 14:00 olur" der → bot Eyotek'e etüt yazar (execute_eyotek_action)
5. Öğrenciye teyit: "✅ Hoca ile konuştum, Perşembe 14:00'e etüt planlandı"

22.1l — DIKKAT:
- Hocaya mesaj gönderme Neo'nun "onaysız WP mesajı yasak" kuralına tabidir.
- Şu an: bot taslak hazırlar, Neo veya admin "gönder" komutuyla fiili yollama olur.
- Tam otomatik gönderim için Neo ayrıca onaylayacak.

22.1l-rev — FLAG EKLENDI (Neo 19 Nisan 14:30 kararı):
  ESKALASYON_AKTIF = False — YKS'ye az kaldı, sistem değişkenlik gösteriyor,
  yanlış yönlendirme riski var. Yeni sezon (1 Eylul 2026) aktif edilecek.
  Kod hazır, flag True olunca tool tam çalışır.
"""
import asyncio
from datetime import date, datetime, timedelta
from typing import Optional
from loguru import logger


# ══════════════════════════════════════════════════════════════════════
# ⛔ ANA KONTROL — Neo "aktif" diyene kadar FALSE (Yeni sezon: 1 Eylul 2026)
# ══════════════════════════════════════════════════════════════════════
ESKALASYON_AKTIF = False


async def hazirla_etut_onerisi(soz_no: int, ders: str) -> dict:
    """
    Öğrenci için etüt önerisi taslağı hazırla — HOCAYA YOLLANMAZ, sadece veriyi döner.
    Bot bu veriyi Claude tool çıktısı olarak kullanır.

    22.1l-rev — FLAG KAPALI: Neo kararı (yeni sezon), "şu an aktif değil" mesajı döner.
    """
    if not ESKALASYON_AKTIF:
        return {
            "success": False,
            "aktif": False,
            "message": (
                "Öğretmen eskalasyon sistemi şu an pasiftir — sınava az zaman kaldığı için "
                "Neo tarafından yeni sezonda (1 Eylul 2026) aktif edilecek. "
                "Şimdilik öğrenci etüt talebini rehber öğretmen ile chat üzerinden iletebilir."
            ),
            "yeni_sezon": "1 Eylul 2026",
        }

    from db_pool import db_fetch, db_fetchrow

    # Öğrenci
    ogr = await db_fetchrow(
        """SELECT soz_no, full_name, class_name, phone FROM students
           WHERE soz_no::text = $1 AND status='active' LIMIT 1""",
        str(soz_no)
    )
    if not ogr:
        return {"error": f"Ogrenci bulunamadi: soz_no={soz_no}"}

    sinif = ogr["class_name"] or ""
    isim = ogr["full_name"]
    ad = isim.split()[0] if isim else ""

    # Son 3 TYT denemesi
    son_3 = await db_fetch(
        """SELECT exam_name, exam_date, toplam, turkce, matematik,
                  fizik, kimya, biyoloji, tarih, cografya
           FROM student_exams
           WHERE soz_no = $1 AND status='valid' AND exam_type='TYT'
           ORDER BY exam_date DESC LIMIT 3""",
        int(soz_no)
    )

    # Zayıf konular — ders filtreli
    weak = await db_fetch(
        """SELECT ders, konu, sinav_hata_yuzdesi
           FROM student_topic_tracker
           WHERE soz_no = $1 AND ders ILIKE $2
             AND (tamamlandi IS NULL OR tamamlandi = FALSE)
           ORDER BY sinav_hata_yuzdesi ASC NULLS LAST LIMIT 5""",
        int(soz_no), f"%{ders}%"
    )
    zayif_list = [
        {"konu": w["konu"], "basari": round(float(w["sinav_hata_yuzdesi"] or 0), 1)}
        for w in weak
    ]

    # Hocalar — ders branşına göre
    hocalar = await db_fetch(
        """SELECT DISTINCT s.full_name, s.brans, s.gorev
           FROM staff s
           WHERE s.brans ILIKE $1 AND s.status='active'
           LIMIT 3""",
        f"%{ders}%"
    )
    hoca_list = []
    for h in hocalar:
        h_adi = h["full_name"] or ""
        # Öğretmen müsait saatleri (teacher_timetable'a bak — boş slotlar)
        # Sadece bu hafta için — önümüzdeki 7 gün
        tt = await db_fetch(
            """SELECT gun, saat FROM teacher_timetable
               WHERE ogretmen_ad ILIKE $1 ORDER BY gun, saat LIMIT 8""",
            f"%{h_adi}%"
        )
        # Doluluk bilgisi — etut_history son 7 gün var mı?
        dolu = await db_fetch(
            """SELECT saat FROM etut_history
               WHERE ogretmen ILIKE $1 AND tarih > NOW() - INTERVAL '7 days' LIMIT 8""",
            f"%{h_adi}%"
        )
        dolu_saatler = {d["saat"] for d in dolu}
        # Ilk 3 musait saat
        musait = []
        for t in tt:
            if t["saat"] not in dolu_saatler:
                musait.append(f"{t['gun']} {t['saat']}")
            if len(musait) >= 3:
                break

        hoca_list.append({
            "isim": h_adi,
            "brans": h["brans"] or "",
            "gorev": h["gorev"] or "",
            "musait_saatler": musait,
        })

    # Mesaj taslagi (hocaya)
    netler_str = ""
    if son_3:
        netler_str = " | ".join(
            f"{t['exam_date'].strftime('%d.%m') if t['exam_date'] else '-'} {float(t['toplam'] or 0):.1f}"
            for t in son_3
        )
    else:
        netler_str = "Deneme verisi yok"

    zayif_str = ", ".join(f"{z['konu']} (%{int(z['basari'])})" for z in zayif_list[:3]) or "Zayif konu kaydi yok"

    hoca_musait_str = ""
    if hoca_list:
        hoca_musait_str = "\n".join(
            f"• {h['isim']}: {', '.join(h['musait_saatler'][:3]) or 'uygun saat bulunamadi'}"
            for h in hoca_list
        )
    else:
        hoca_musait_str = "(ilgili branşta hoca bulunamadi)"

    mesaj = (
        f"📝 *Etut Talebi — {ders}*\n\n"
        f"*{isim}* ({sinif}) bu derste etut istiyor.\n\n"
        f"*Son 3 TYT netleri:* {netler_str}\n"
        f"*Zayif konular:* {zayif_str}\n\n"
        f"*Musait hoca-saat onerileri:*\n{hoca_musait_str}\n\n"
        f"_Uygun saati yaziniz, Eyotek'e not edeyim._"
    )

    return {
        "ogrenci": {"isim": isim, "sinif": sinif, "soz_no": int(soz_no)},
        "ders": ders,
        "son_3_deneme": [
            {
                "name": (t["exam_name"] or "")[:30],
                "date": t["exam_date"].strftime("%d.%m.%Y") if t["exam_date"] else "",
                "toplam": float(t["toplam"] or 0),
            }
            for t in son_3
        ],
        "zayif_konular": zayif_list,
        "hoca_onerileri": hoca_list,
        "mesaj_taslak": mesaj,
    }


async def kaydet_ogrenci_talep(soz_no: int, ders: str, note: str = "") -> int:
    """Öğrenci etut talebini student_insights'a kaydet.
    22.1n-neo: Merkezi student_signals.log_student_signal uzerinden."""
    try:
        from student_signals import log_student_signal
        _id = await log_student_signal(
            int(soz_no), "etut_talebi",
            f"[{ders}] {note or 'etut istedi'}",
            confidence=0.9, source="teacher_escalation"
        )
        logger.info(f"Ogrenci etut talebi kayit: soz_no={soz_no} ders={ders}")
        return _id or 0
    except Exception as e:
        logger.warning(f"Ogrenci talep kayit hatasi: {e}")
        return 0


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    async def main():
        from dotenv import load_dotenv
        load_dotenv(override=True)
        result = await hazirla_etut_onerisi(soz_no=270, ders="fizik")
        print("=" * 60)
        print("ETUT TALEBI TASLAGI")
        print("=" * 60)
        if "error" in result:
            print(f"ERROR: {result['error']}")
        else:
            print(f"Ogrenci: {result['ogrenci']}")
            print(f"Son 3: {result['son_3_deneme']}")
            print(f"Zayif: {result['zayif_konular']}")
            print(f"Hocalar: {result['hoca_onerileri']}")
            print("\nMesaj taslagi:")
            print(result['mesaj_taslak'])

    asyncio.run(main())
