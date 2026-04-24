"""
FermatAI — Akıllı Etüt Öneri Motoru
====================================
Öğrenci için en uygun etüt önerir:
  - Zayıf konular (en acil)
  - Müsait öğretmen (uzman + boş slot)
  - Öğrencinin yoklama tutarlılığı (gelir mi?)
  - Optimal saat (öğrencinin programındaki boşluk)

Kullanım:
  python smart_etut_advisor.py 230        # Öğrenci soz_no
  python smart_etut_advisor.py --top 5    # Genel kurum önerileri
"""

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

from loguru import logger
from db_pool import get_pool as _get_pool, db_fetch, db_fetchrow, db_fetchval, db_execute


async def get_student_weak_topics(soz_no: str, limit: int = 5) -> list:
    """Öğrencinin en zayıf konuları (etüt için öncelikli)."""
    return await db_fetch("""
        SELECT ders, konu, sinav_hata_yuzdesi as basari, sinav_hata_sayisi as hata
        FROM student_topic_tracker
        WHERE soz_no::text = $1
        AND tamamlandi = FALSE
        AND sinav_hata_yuzdesi < 50
        AND LENGTH(konu) > 5
        AND konu NOT LIKE 'Ortalama %'
        ORDER BY sinav_hata_yuzdesi ASC LIMIT $2
    """, str(soz_no), limit)


async def find_available_teachers(ders: str, gun: str = None) -> list:
    """Belirli ders için müsait öğretmen + boş slot."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        # Bu dersi veren öğretmenler
        teachers = await conn.fetch("""
            SELECT DISTINCT ogretmen_ad, brans, COUNT(*) as ders_sayisi
            FROM teacher_timetable
            WHERE ders ILIKE $1 OR brans ILIKE $2
            GROUP BY ogretmen_ad, brans
            ORDER BY ders_sayisi DESC LIMIT 5
        """, f"%{ders}%", f"%{ders}%")

        # Her öğretmen için bos slotlari hesapla (ders yapmadığı saatler)
        advisors = []
        for t in teachers:
            # Öğretmenin tüm derslerini al
            ogretmen = t['ogretmen_ad']
            all_slots = await conn.fetch("""
                SELECT gun, saat FROM teacher_timetable WHERE ogretmen_ad = $1
            """, ogretmen)
            busy = {(s['gun'], s['saat']) for s in all_slots}

            # Olası saatler (09:00 - 19:00, 5 gün)
            gunler = ['Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma'] if not gun else [gun]
            saatler = ['09:00', '10:30', '12:00', '14:00', '15:30', '17:00', '18:30']
            bos_slotlar = []
            for g in gunler:
                for s in saatler:
                    if (g, s) not in busy:
                        bos_slotlar.append({'gun': g, 'saat': s})
                    if len(bos_slotlar) >= 3:
                        break
                if len(bos_slotlar) >= 3:
                    break

            advisors.append({
                'ogretmen': ogretmen,
                'brans': t['brans'],
                'haftalik_ders': t['ders_sayisi'],
                'bos_slotlar': bos_slotlar[:3],
            })

    return advisors


async def get_student_attendance_score(soz_no: str) -> dict:
    """Öğrencinin yoklama güvenilirliği."""
    devamsizlik = await db_fetchval(
        "SELECT toplam_saat FROM devamsizlik_sayisi WHERE soz_no::text = $1",
        str(soz_no)
    )
    saat = devamsizlik or 0
    if saat < 30:
        return {'puan': 'A', 'aciklama': 'Düzenli devam ediyor', 'saat': saat}
    elif saat < 80:
        return {'puan': 'B', 'aciklama': 'Genelde geliyor', 'saat': saat}
    elif saat < 150:
        return {'puan': 'C', 'aciklama': 'Bazen aksıyor — etüt zamanı önemli', 'saat': saat}
    else:
        return {'puan': 'D', 'aciklama': 'Sık aksıyor — kısa süreli etüt önerilir', 'saat': saat}


async def get_student_etut_history(soz_no: str, ders: str = "") -> list:
    """Öğrencinin önceki etütleri."""
    # students tablosundan ad bul
    student = await db_fetchrow("SELECT first_name, full_name FROM students WHERE soz_no::text=$1", str(soz_no))
    if not student:
        return []
    name = student['first_name'] or student['full_name'].split()[0]
    where = "yoklama ILIKE $1"
    params = [f"%{name}%"]
    if ders:
        params.append(f"%{ders}%")
        where += f" AND ders ILIKE ${len(params)}"
    return await db_fetch(
        f"SELECT tarih, ders, konu, ogretmen FROM etut_history WHERE {where} "
        f"ORDER BY tarih DESC LIMIT 5",
        *params
    )


async def recommend_etut_for_student(soz_no: str) -> str:
    """Öğrenci için tam etüt önerisi raporu."""
    student = await db_fetchrow(
        "SELECT full_name, class_name FROM students WHERE soz_no::text=$1",
        str(soz_no)
    )
    if not student:
        return f"Öğrenci bulunamadı (soz_no: {soz_no})"

    name = student['full_name']
    sinif = student['class_name']

    weak = await get_student_weak_topics(soz_no, limit=3)
    if not weak:
        return f"*{name}* için zayıf konu verisi yok — deneme analizi gerekli."

    attendance = await get_student_attendance_score(soz_no)

    lines = [
        f"🎯 *AKILLI ETÜT ÖNERİSİ — {name}*\n",
        f"📚 *Sınıf:* {sinif}",
        f"📋 *Devam Durumu:* {attendance['puan']} ({attendance['aciklama']})",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━",
        "🔥 *ÖNCELIKLI 3 ETÜT*",
        "━━━━━━━━━━━━━━━━━━━━━━━\n",
    ]

    for i, w in enumerate(weak, 1):
        teachers = await find_available_teachers(w['ders'])
        ders_kisa = w['ders'][:15]
        konu_kisa = w['konu'][:35]
        lines.append(f"*{i}. {ders_kisa}* — _{konu_kisa}_")
        lines.append(f"   📊 Şu anki başarı: %{(w['basari'] or 0):.0f} | Hata: {w['hata']}")

        if teachers:
            t = teachers[0]
            lines.append(f"   👨‍🏫 *Önerilen öğretmen:* {t['ogretmen']}")
            if t['bos_slotlar']:
                slot_str = " · ".join(
                    f"{s['gun']} {s['saat']}" for s in t['bos_slotlar'][:2]
                )
                lines.append(f"   📅 Müsait slotlar: {slot_str}")
        lines.append("")

    # Onceki etüt geçmişi
    if weak:
        history = await get_student_etut_history(soz_no, weak[0]['ders'])
        if history:
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append(f"📜 *{weak[0]['ders']} dersinde önceki etütler:*")
            for h in history[:3]:
                lines.append(f"  • {h['tarih']} | {h['ogretmen']} | {(h['konu'] or 'Genel')[:30]}")
            lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 *Aksiyon:*")
    lines.append(f"İlk önceliği — *{weak[0]['ders']}* dersinde *{weak[0]['konu'][:30]}* konusunda")
    if attendance['puan'] in ('C', 'D'):
        lines.append("🚨 Devam tutarsız — etüt için *velinin haberi olması* önerilir.")
    lines.append("")
    lines.append("_'etüt yaz [öğrenci] [tarih] [öğretmen]' komutu ile kayda alabilirsin._")

    return "\n".join(lines)


async def get_kurum_etut_oncelikleri(top: int = 5) -> str:
    """Kurum geneli en acil etüt ihtiyaçları (toplu öneri)."""
    # En çok zorlanan öğrenci-konu çiftleri
    rows = await db_fetch(f"""
        SELECT t.soz_no, s.full_name, s.class_name,
               t.ders, t.konu, t.sinav_hata_yuzdesi as basari
        FROM student_topic_tracker t
        LEFT JOIN students s ON s.soz_no::text = t.soz_no::text
        WHERE t.sinav_hata_yuzdesi < 30
        AND t.tamamlandi = FALSE
        AND s.full_name IS NOT NULL
        AND LENGTH(t.konu) > 5
        AND t.konu NOT LIKE 'Ortalama %'
        ORDER BY t.sinav_hata_yuzdesi ASC LIMIT {top * 2}
    """)

    if not rows:
        return "Acil etüt önerisi gerektiren öğrenci yok."

    lines = ["🚨 *KURUM GENELI ETÜT ÖNCELIKLERI*\n"]
    lines.append("_(En acil müdahale gereken öğrenciler)_\n")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━\n")

    seen = set()
    sira = 0
    for r in rows:
        key = (r['soz_no'], r['ders'])
        if key in seen:
            continue
        seen.add(key)
        sira += 1
        if sira > top:
            break
        sinif = (r['class_name'] or 'Sinif?')[:12]
        lines.append(f"*{sira}. {r['full_name'][:25]}* ({sinif})")
        lines.append(f"   🔴 *{r['ders']}* — _{r['konu'][:35]}_")
        lines.append(f"   %{(r['basari'] or 0):.0f} başarı")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("_'etüt öner [öğrenci adı]' yazarak detaylı plan al_")
    return "\n".join(lines)


async def main():
    if len(sys.argv) < 2 or sys.argv[1].startswith('--'):
        # Kurum geneli
        top = 5
        if "--top" in sys.argv:
            top = int(sys.argv[sys.argv.index("--top") + 1])
        rapor = await get_kurum_etut_oncelikleri(top)
    else:
        soz_no = sys.argv[1]
        rapor = await recommend_etut_for_student(soz_no)
    print(rapor)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
