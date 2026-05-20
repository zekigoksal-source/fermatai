"""
Teacher AI Co-pilot (23 Nisan)
=================================
Öğretmene hazır brief: sınıf performansı, risk öğrencileri, etüt önerisi.
Vedat Hoca WP'den "bugünkü özet" dediğinde bu aktive olur.
"""
from __future__ import annotations
from loguru import logger


async def build_brief(ogretmen: str) -> str:
    """Öğretmen için sınıf bazlı brief."""
    try:
        from db_pool import db_fetch, db_fetchrow
        # Öğretmenin sınıfları (staff + class_timetable)
        staff = await db_fetchrow(
            "SELECT eyotek_id, gorev, sube FROM fermat.staff WHERE full_name ILIKE $1 LIMIT 1",
            f"%{ogretmen}%"
        )
        if not staff:
            return f"Öğretmen bilgim yok: {ogretmen}"

        # Class timetable'dan öğretmen sınıfları
        siniflar = await db_fetch(
            "SELECT DISTINCT sinif FROM fermat.class_timetable WHERE ogretmen ILIKE $1",
            f"%{ogretmen}%"
        )
        sinif_listesi = [r["sinif"] for r in siniflar]
        if not sinif_listesi:
            return f"*{ogretmen} Hocam*, sistemde sınıf kaydın henüz yok. Eyotek'ten senkronize edildikten sonra tekrar bak."

        lines = [
            f"🎓 *{ogretmen} Hocam — Bugünkü Brief*",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"📚 Sınıf sayısı: {len(sinif_listesi)}",
            "",
        ]

        for sinif in sinif_listesi[:4]:
            # Son deneme ortalaması
            avg = await db_fetchrow(
                """
                SELECT AVG(e.toplam) AS ort, COUNT(DISTINCT e.soz_no) AS kisi
                FROM fermat.student_exams e
                JOIN fermat.students s ON s.soz_no::text = e.soz_no::text
                WHERE s.class_name = $1
                  AND e.exam_date > NOW() - INTERVAL '14 days'
                  AND e.status='valid'
                """,
                sinif
            )
            ort = float(avg["ort"] or 0) if avg else 0
            kisi = int(avg["kisi"] or 0) if avg else 0
            # Risk öğrenci (devamsızlık veya net düşüşü)
            risk = await db_fetch(
                """
                SELECT s.full_name, COALESCE(d.toplam_saat, 0) as devamsiz
                FROM fermat.students s
                LEFT JOIN fermat.devamsizlik_sayisi d ON d.soz_no = s.soz_no::int
                WHERE s.class_name = $1 AND COALESCE(d.toplam_saat, 0) > 100
                ORDER BY d.toplam_saat DESC LIMIT 3
                """,
                sinif
            )
            lines.append(f"🏫 *{sinif}* — {kisi} öğrenci, ort *{ort:.1f}* net")
            if risk:
                lines.append(f"  ⚠ Devamsızlık riski: {', '.join((r['full_name'] or '?').split()[0] for r in risk)}")
            lines.append("")

        # Bu hafta zayıf konu trendleri (tüm öğrenciler)
        # sinav_hata_yuzdesi = HATA % (yuksek=zayif). Kurumsal en zayif = en yuksek ort hata.
        zayif = await db_fetch(
            """
            SELECT ders, konu, AVG(sinav_hata_yuzdesi) AS ort, COUNT(DISTINCT soz_no) AS ogr
            FROM fermat.student_topic_tracker
            WHERE COALESCE(status,'') != 'metadata'
              AND sinav_hata_yuzdesi >= 50
            GROUP BY ders, konu
            HAVING COUNT(DISTINCT soz_no) >= 3
            ORDER BY AVG(sinav_hata_yuzdesi) DESC
            LIMIT 3
            """
        )
        if zayif:
            lines.append("🎯 *Kurumsal zayıf konular (3+ öğrenci):*")
            for z in zayif:
                lines.append(f"  🔴 {z['ders']} · {z['konu'][:40]} (ort %{float(z['ort']):.0f} hata, {z['ogr']} öğr)")
            lines.append("")
            lines.append("_Etüt önerisi ister misin?_ 📅")

        # Bu öğretmenin yazdığı bekleyen rehber önerileri (kendi durumu)
        try:
            kendi_oneri = await db_fetch(
                """
                SELECT durum, COUNT(*) AS n
                FROM fermat.teacher_etut_onerileri
                WHERE ogretmen_ad ILIKE $1
                  AND created_at > NOW() - INTERVAL '14 days'
                GROUP BY durum
                """,
                f"%{ogretmen}%"
            )
            if kendi_oneri:
                lines.append("📮 *Rehbere Gönderdiğin Öneriler (son 14 gün):*")
                for ko in kendi_oneri:
                    emoji = {"bekliyor": "⏳", "yazildi": "✅", "reddedildi": "❌", "incelendi": "👁"}.get(ko["durum"], "•")
                    lines.append(f"  {emoji} {ko['durum']}: {ko['n']} adet")
                lines.append("")
        except Exception:
            pass

        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"_FermatAI — {ogretmen} için brief_")
        return "\n".join(lines)
    except Exception as e:
        return f"Brief hatası: {e}"


async def build_rehber_brief(rehber_ad: str = "") -> str:
    """Rehber öğretmen için brief — branş öğretmenlerinin bekleyen etut önerilerini gösterir.

    Rehber bu önerileri görür, uygun olanları Eyotek'te etut olarak YAZAR,
    sonra durumu 'yazildi' olarak günceller.
    """
    try:
        from db_pool import db_fetch
        lines = [
            f"🧭 *Rehber Brief — {rehber_ad or 'Rehberlik Servisi'}*",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "",
        ]

        # Bekleyen öneriler
        bekleyenler = await db_fetch(
            """
            SELECT id, ogretmen_ad, ogrenci_ad, soz_no, ders, konu, aciklama,
                   oncelik, onerilen_gun, created_at
            FROM fermat.teacher_etut_onerileri
            WHERE durum = 'bekliyor'
            ORDER BY
                CASE oncelik
                    WHEN 'acil' THEN 1
                    WHEN 'yuksek' THEN 2
                    WHEN 'normal' THEN 3
                    WHEN 'dusuk' THEN 4
                    ELSE 5
                END,
                created_at DESC
            LIMIT 15
            """
        )

        if not bekleyenler:
            lines.append("✅ Bekleyen etut önerisi yok — şu an temiz.")
            lines.append("")
        else:
            lines.append(f"📥 *Branş Öğretmeni Etut Önerileri ({len(bekleyenler)} bekliyor):*")
            lines.append("")
            oncelik_emoji = {"acil": "🚨", "yuksek": "🔴", "normal": "🟡", "dusuk": "🟢"}
            for b in bekleyenler:
                em = oncelik_emoji.get(b["oncelik"], "•")
                ogr_label = b["ogrenci_ad"] or (f"soz_no:{b['soz_no']}" if b["soz_no"] else "?")
                lines.append(
                    f"{em} *#{b['id']}* · {b['ogretmen_ad']} → {ogr_label}"
                )
                lines.append(f"    📚 {b['ders']} · {b['konu'] or '-'}")
                if b["aciklama"]:
                    acik = (b["aciklama"] or "")[:100]
                    lines.append(f"    💬 {acik}")
                if b["onerilen_gun"]:
                    lines.append(f"    🗓 Önerilen: {b['onerilen_gun']}")
                lines.append("")

            lines.append("_Uygun gördüklerini Eyotek'te yaz, sonra 'öneri #ID yazildi' de._")
            lines.append("")

        # Bu hafta yazılan etutlerin özeti
        son_durum = await db_fetch(
            """
            SELECT durum, COUNT(*) AS n
            FROM fermat.teacher_etut_onerileri
            WHERE created_at > NOW() - INTERVAL '7 days'
            GROUP BY durum
            """
        )
        if son_durum:
            lines.append("📊 *Son 7 gün öneri özeti:*")
            for s in son_durum:
                lines.append(f"  • {s['durum']}: {s['n']}")
            lines.append("")

        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        return "\n".join(lines)
    except Exception as e:
        return f"Rehber brief hatası: {e}"
