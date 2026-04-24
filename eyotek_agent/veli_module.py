"""
FermatAI Veli Modülü
=====================
Veli telefonu → çocuk eşleştirmesi + sınırlı okuma yetkisi.

Kurallar:
  - Veli SADECE kendi çocuğunun verisini görebilir
  - Rehberlik notları GİZLİ (aile görüşmesinden geliyor)
  - Kurumsal, saygılı ton
  - Çocuğa ait: son deneme, devamsızlık, genel durum
  - Çocuğa ait DEĞİL: öğretmen bilgileri, diğer öğrenciler, ödeme
"""

import asyncio
from typing import Optional

from loguru import logger
from db_pool import get_pool as _get_pool, db_fetch, db_fetchrow, db_fetchval, db_execute


async def find_child_by_parent_phone(parent_phone: str) -> Optional[dict]:
    """
    Veli telefonundan çocuğu bul.
    anne_phone, baba_phone, veli_phone kolonlarından eşleşme.
    """
    phone_clean = parent_phone.replace("+", "")

    try:
        child = await db_fetchrow("""
            SELECT soz_no, full_name, class_name, program, devre
            FROM students
            WHERE REPLACE(anne_phone,'+','') = $1
               OR REPLACE(baba_phone,'+','') = $1
               OR REPLACE(veli_phone,'+','') = $1
               OR REPLACE(anne_tel,'+','') = $1
               OR REPLACE(baba_tel,'+','') = $1
            LIMIT 1
        """, phone_clean)

        if child:
            return {
                "soz_no": int(child['soz_no']),
                "full_name": child['full_name'],
                "class_name": child.get('class_name', '?'),
                "program": child.get('program', '?'),
                "devre": child.get('devre', '?'),
            }
        return None
    except Exception as e:
        logger.debug(f"Veli çocuk eşleştirme hatası: {e}")
        return None


async def get_parent_report(soz_no: int, child_name: str) -> str:
    """
    Veli için çocuk akademik raporu — sınırlı bilgi.
    Rehberlik notları DAHİL DEĞİL.
    """
    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            # Son deneme
            exam = await conn.fetchrow("""
                SELECT exam_name, exam_date, turkce, matematik, fizik, kimya, biyoloji, toplam
                FROM student_exams WHERE soz_no = $1
                ORDER BY exam_date DESC NULLS LAST LIMIT 1
            """, soz_no)

            # Son 3 deneme trendi
            exams = await conn.fetch("""
                SELECT exam_name, exam_date, toplam
                FROM student_exams WHERE soz_no = $1
                ORDER BY exam_date DESC NULLS LAST LIMIT 3
            """, soz_no)

            # Devamsızlık
            devam = await conn.fetchval(
                "SELECT toplam_saat FROM devamsizlik_sayisi WHERE soz_no = $1", soz_no)

            # Etüt bilgisi
            etut = await conn.fetchrow(
                "SELECT toplam, yapildi FROM etut_student_control WHERE soz_no = $1", soz_no)

        # Rapor oluştur
        lines = [
            f"📋 *{child_name} — Akademik Durum Raporu*\n",
            f"---\n",
        ]

        if exam:
            lines.append(f"📝 *Son Deneme:* {exam['exam_name'][:30]}")
            lines.append(f"📅 Tarih: _{exam['exam_date']}_")
            lines.append(f"📊 Toplam: *{exam['toplam']:.1f}* net\n")

            subjects = [
                ("Türkçe", exam.get('turkce')),
                ("Matematik", exam.get('matematik')),
                ("Fizik", exam.get('fizik')),
                ("Kimya", exam.get('kimya')),
                ("Biyoloji", exam.get('biyoloji')),
            ]
            for s, v in subjects:
                if v and v > 0:
                    lines.append(f"  • {s}: *{v:.1f}* net")
            lines.append("")

        # Trend
        if len(exams) >= 2:
            exams_rev = list(reversed(exams))
            diff = (exams_rev[-1]['toplam'] or 0) - (exams_rev[0]['toplam'] or 0)
            if diff > 3:
                lines.append(f"📈 *Trend:* Son {len(exams)} denemede *{diff:+.1f} net artış* — olumlu gelişme!")
            elif diff < -3:
                lines.append(f"📉 *Trend:* Son {len(exams)} denemede *{diff:+.1f} net düşüş* — dikkat gerekiyor.")
            else:
                lines.append(f"➡️ *Trend:* Net değerler stabil ({diff:+.1f})")
            lines.append("")

        # Devamsızlık
        if devam is not None:
            emoji = "🟢" if devam < 30 else "🟡" if devam < 80 else "🔴"
            lines.append(f"{emoji} *Devamsızlık:* {devam} saat")
            if devam > 80:
                lines.append(f"   _Devamsızlık oranı yüksek — lütfen takip ediniz._")
            lines.append("")

        # Etüt
        if etut and etut['toplam']:
            lines.append(f"📚 *Etüt:* {etut['toplam']} etüt planlanmış, {etut.get('yapildi', 0)} katılım")
            lines.append("")

        if not exam:
            lines.append("Henüz sisteme yüklenmiş deneme sonucu bulunmamaktadır.")
            lines.append("Yeni deneme sonuçları geldikçe otomatik güncellenecektir.\n")

        lines.append(f"---")
        lines.append(f"_Detaylı bilgi için kurum ile iletişime geçebilirsiniz._")
        lines.append(f"📞 *+90 546 260 54 46*")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"Veli rapor hatası: {e}")
        return (
            "Şu an teknik bir aksama yaşanmaktadır.\n"
            "Lütfen daha sonra tekrar deneyiniz veya kurumu arayınız.\n"
            "📞 *+90 546 260 54 46*"
        )


# Veli ACL kaydı oluşturma
async def register_parent(phone: str, child_info: dict) -> bool:
    """Veli için ACL kaydı oluştur."""
    try:
        # Zaten kayıtlı mı?
        existing = await db_fetchval(
            "SELECT phone FROM acl_users WHERE REPLACE(phone,'+','') = $1",
            phone.replace("+", ""))
        if not existing:
            await db_execute("""
                INSERT INTO acl_users (phone, full_name, role, is_active)
                VALUES ($1, $2, 'veli', TRUE)
            """, phone, f"Veli ({child_info['full_name']})")
            logger.info(f"Veli ACL kaydı oluşturuldu: {phone} → {child_info['full_name']}")
        return True
    except Exception as e:
        logger.debug(f"Veli kayıt hatası: {e}")
        return False
