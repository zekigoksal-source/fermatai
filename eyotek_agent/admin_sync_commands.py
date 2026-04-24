"""
FermatAI Admin Sync Komutları
==============================
WP üzerinden admin'in veri güncelleme komutları.

Komutlar:
  "güncelle"              → Tüm sistem güncelleme checklist
  "güncelle ali küçükuysal" → Tek öğrenci güncelle
  "güncelle 11 say"       → Sınıf güncelle
  "güncelle etüt"         → Etüt verileri güncelle
  "son güncelleme"        → Son sync zamanlarını göster
  "sync durumu"           → Detaylı sync raporu

Entegrasyon: whatsapp_bridge.py'deki admin komutlarına eklenir.
"""

import asyncio
from datetime import datetime

from loguru import logger
from db_pool import get_pool as _get_pool


async def get_sync_status() -> str:
    """Son güncelleme durumlarını göster."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        # Son sync zamanları
        last_exam_sync = await conn.fetchval(
            "SELECT MAX(last_sync) FROM sync_tracking WHERE sync_status = 'completed'")
        last_etut = await conn.fetchval(
            "SELECT MAX(tarih) FROM etut_history")
        last_timetable = await conn.fetchval(
            "SELECT MAX(tarih) FROM etut_history WHERE tarih >= CURRENT_DATE - 7")

        # Veri sayıları
        tyt_count = await conn.fetchval("SELECT COUNT(*) FROM student_exams WHERE exam_code NOT LIKE 'AYT%' AND toplam IS NOT NULL")
        ayt_count = await conn.fetchval("SELECT COUNT(*) FROM student_exams WHERE exam_code LIKE 'AYT%' AND toplam IS NOT NULL")
        tyt_eksik = await conn.fetchval("SELECT COUNT(*) FROM student_exams WHERE exam_code NOT LIKE 'AYT%' AND toplam IS NULL")
        ayt_eksik = await conn.fetchval("SELECT COUNT(*) FROM student_exams WHERE exam_code LIKE 'AYT%' AND toplam IS NULL")
        tracked = await conn.fetchval("SELECT COUNT(*) FROM sync_tracking WHERE sync_status = 'completed'")
        total_students = await conn.fetchval("SELECT COUNT(*) FROM students")

    last_sync_str = last_exam_sync.strftime("%d.%m.%Y %H:%M") if last_exam_sync else "Hiç yapılmadı"

    return (
        f"📊 *Sistem Güncelleme Durumu*\n\n"
        f"---\n\n"
        f"*Son Sınav Sync:* {last_sync_str}\n"
        f"*Tracking:* {tracked}/{total_students} öğrenci tarandı\n\n"
        f"*TYT Sınavları:*\n"
        f"  ✅ Net var: *{tyt_count}* kayıt\n"
        f"  ⚠️ Net eksik: *{tyt_eksik}* kayıt\n\n"
        f"*AYT Sınavları:*\n"
        f"  ✅ Net var: *{ayt_count}* kayıt\n"
        f"  ⚠️ Net eksik: *{ayt_eksik}* kayıt\n\n"
        f"---\n\n"
        f"*Komutlar:*\n"
        f"  _'güncelle' → tam sistem güncellemesi_\n"
        f"  _'güncelle [isim]' → tek öğrenci_\n"
        f"  _'güncelle etüt' → etüt verileri_"
    )


async def get_update_checklist() -> str:
    """Güncelleme checklist'i oluştur."""
    pool = await _get_pool()
    checks = []

    async with pool.acquire() as conn:
        # 1. Sınav sync
        untracked = await conn.fetchval(
            "SELECT COUNT(*) FROM students s WHERE NOT EXISTS (SELECT 1 FROM sync_tracking t WHERE t.soz_no = s.soz_no::int)")
        if untracked > 0:
            checks.append(f"🔴 *Sınav Sync:* {untracked} öğrenci hiç taranmamış")
        else:
            checks.append(f"✅ *Sınav Sync:* Tüm öğrenciler tarandı")

        # 2. Net eksikleri
        tyt_eksik = await conn.fetchval("SELECT COUNT(*) FROM student_exams WHERE toplam IS NULL AND exam_code NOT LIKE 'AYT%'")
        ayt_eksik = await conn.fetchval("SELECT COUNT(*) FROM student_exams WHERE toplam IS NULL AND exam_code LIKE 'AYT%'")
        if tyt_eksik > 0:
            checks.append(f"🟡 *TYT Net:* {tyt_eksik} kayıtta net eksik (birleştirme gerekli)")
        if ayt_eksik > 0:
            checks.append(f"🟡 *AYT Net:* {ayt_eksik} kayıtta net eksik (birleştirme gerekli)")

        # 3. Konu takibi
        topic_count = await conn.fetchval("SELECT COUNT(*) FROM student_topic_tracker")
        checks.append(f"📝 *Konu Takibi:* {topic_count} kayıt")

        # 4. Etüt verileri
        last_etut = await conn.fetchval("SELECT MAX(tarih) FROM etut_history")
        if last_etut:
            days_ago = (datetime.now().date() - last_etut).days
            if days_ago > 7:
                checks.append(f"🟡 *Etüt:* Son veri {days_ago} gün önce — güncelleme önerilir")
            else:
                checks.append(f"✅ *Etüt:* Güncel ({last_etut})")

        # 5. Öğretmen programı
        checks.append(f"📅 *Ders Programı:* Dönem başı sabit (güncelleme gerekmez)")

    lines = ["📋 *Güncelleme Kontrol Listesi*\n", "---\n"]
    lines.extend(checks)
    lines.append(f"\n---")
    lines.append(f"_Eyotek CDP açıkken 'sync başlat' yazarak güncelleyebilirsiniz._")

    return "\n".join(lines)


async def get_student_freshness(student_name: str) -> str:
    """Tek öğrencinin veri güncelliğini kontrol et."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        # Öğrenciyi bul — Türkçe karakter uyumlu
        student = await conn.fetchrow("""
            SELECT soz_no, full_name, class_name FROM students
            WHERE LOWER(full_name) LIKE LOWER($1)
               OR TRANSLATE(UPPER(full_name), 'ÇĞİÖŞÜ', 'CGIOSU') ILIKE UPPER($2)
            LIMIT 1
        """, f"%{student_name}%", f"%{student_name}%")

        if not student:
            return f"'{student_name}' adında öğrenci bulunamadı."

        soz_no = int(student['soz_no'])
        name = student['full_name']

        # Son sınav
        last_exam = await conn.fetchrow("""
            SELECT exam_name, exam_date, toplam FROM student_exams
            WHERE soz_no = $1 AND toplam IS NOT NULL
            ORDER BY exam_date DESC NULLS LAST LIMIT 1
        """, soz_no)

        # Sync durumu
        tracking = await conn.fetchrow(
            "SELECT last_sync, tyt_sinav_sayisi, tyt_katildi, ayt_sinav_sayisi, ayt_katildi FROM sync_tracking WHERE soz_no = $1",
            soz_no)

        # Eksik net sayısı
        eksik = await conn.fetchval(
            "SELECT COUNT(*) FROM student_exams WHERE soz_no = $1 AND toplam IS NULL", soz_no)

    lines = [f"📊 *{name} — Veri Güncelliği*\n", "---\n"]

    if last_exam:
        lines.append(f"📝 Son sınav: *{last_exam['exam_name'][:30]}* ({last_exam['exam_date']})")
        lines.append(f"   Toplam: *{last_exam['toplam']:.1f}* net")
    else:
        lines.append(f"⚠️ Hiç sınav verisi yok (net)")

    if tracking:
        lines.append(f"\n📅 Son sync: {tracking['last_sync'].strftime('%d.%m %H:%M')}")
        lines.append(f"   TYT: {tracking['tyt_sinav_sayisi']} sınav ({tracking['tyt_katildi']} katıldı)")
        lines.append(f"   AYT: {tracking['ayt_sinav_sayisi']} sınav ({tracking['ayt_katildi']} katıldı)")

    if eksik > 0:
        lines.append(f"\n⚠️ *{eksik} sınavda net eksik* — birleştirme gerekli")

    lines.append(f"\n---")
    lines.append(f"_'güncelle {name.split()[0].lower()}' ile güncelleyebilirsiniz._")

    return "\n".join(lines)
