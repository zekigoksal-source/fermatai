"""
Role Briefs — Rehber + Öğretmen Hızlı Brief Tool'ları (22.1n-toplanti #4, #5)
=============================================================================

Bot tespit (20 Nisan toplantı):
> "Rehber 30sn response — çünkü öğrenci verisi çek, plan yaz, mesaj taslağı
>  hazırla: 3 ayrı tool call. prepare_counsellor_brief tek çağrı olsun."
> "Öğretmen değer önerisi yok — get_class_brief(sinif, ders, tarih) tek tool
>  ile 'bu sınıfın bu konuda zayıflığı' çıkar."

KULLANIM (Claude tool):
  prepare_counsellor_brief(soz_no)
  → öğrenci ozet + veli mesaj taslağı + öncelikli konular

  get_class_brief(sinif, ders="", tarih="")
  → sınıfın o dersteki son 3 deneme ortalaması + en zayıf konu + öneri

GÜVENLİK: Sadece DB okuma — MESAJ ATMAZ.
"""
import asyncio
from datetime import datetime, date, timedelta
from loguru import logger


async def prepare_counsellor_brief(soz_no: int) -> dict:
    """Rehber için tek çağrıda öğrenci özeti + veli mesaj taslağı + öncelikler."""
    from db_pool import db_fetchrow, db_fetch

    try:
        soz_no = int(soz_no)
    except (ValueError, TypeError):
        return {"error": "geçersiz soz_no"}

    # 1. Öğrenci temel bilgi
    student = await db_fetchrow(
        """SELECT full_name, class_name, sube, program
           FROM students WHERE soz_no::text=$1 AND status='active'""",
        str(soz_no),
    )
    if not student:
        return {"error": f"Öğrenci bulunamadı: soz_no={soz_no}"}

    # 2. Son 3 deneme
    exams = await db_fetch(
        """SELECT exam_name, exam_date, toplam, matematik, fizik, kimya, biyoloji, turkce
           FROM student_exams
           WHERE soz_no::text=$1 AND status='valid' AND toplam IS NOT NULL AND toplam > 0
           ORDER BY exam_date DESC NULLS LAST LIMIT 3""",
        str(soz_no),
    )

    # 3. En zayıf 3 konu — INVERSION FIX (Berf bug 10 May)
    # sinav_hata_yuzdesi = HATA % (yuksek=zayif). DESC + >=25 + metadata filter.
    weak = await db_fetch(
        """SELECT ders, konu, sinav_hata_yuzdesi
           FROM student_topic_tracker
           WHERE soz_no=$1 AND (tamamlandi IS NULL OR tamamlandi=FALSE)
             AND COALESCE(status,'') != 'metadata'
             AND konu NOT LIKE 'Ortalama %'
             AND sinav_hata_yuzdesi IS NOT NULL
             AND sinav_hata_yuzdesi >= 25
           ORDER BY sinav_hata_yuzdesi DESC NULLS LAST LIMIT 3""",
        soz_no,
    )

    # 4. Devamsızlık
    devam = await db_fetchrow(
        "SELECT toplam_saat FROM devamsizlik_sayisi WHERE soz_no=$1", soz_no)

    # 5. Son negatif duygu sinyali (varsa)
    neg_sinyal = await db_fetchrow(
        """SELECT insight_type, content, created_at
           FROM student_insights
           WHERE soz_no=$1 AND active=TRUE
             AND insight_type IN ('crisis','stressed','negative','angry','frustrated')
           ORDER BY created_at DESC LIMIT 1""",
        soz_no,
    )

    # 6. Son rehberlik notu
    rehber_note = await db_fetchrow(
        """SELECT gorusme_tarihi, not_metni, not_turu
           FROM counsellor_notes WHERE soz_no=$1
           ORDER BY gorusme_tarihi DESC NULLS LAST LIMIT 1""", soz_no
    )

    # ── Brief yapılandır ────────────────────────────────
    brief = {
        "ogrenci": {
            "ad": student["full_name"],
            "sinif": student["class_name"] or "?",
            "sube": student.get("sube"),
            "program": student.get("program"),
        },
        "son_denemeler": [
            {
                "isim": (e["exam_name"] or "?")[:40],
                "tarih": e["exam_date"].isoformat() if e.get("exam_date") else None,
                "toplam": float(e["toplam"] or 0),
            } for e in exams
        ],
        "oncelikli_konular": [
            # INVERSION FIX: sinav_hata_yuzdesi = HATA %. basari = 100 - hata.
            {"ders": w["ders"], "konu": w["konu"],
             "hata_yuzdesi": round(float(w["sinav_hata_yuzdesi"] or 0), 1),
             "basari_yuzdesi": round(max(0.0, min(100.0, 100.0 - float(w["sinav_hata_yuzdesi"] or 0))), 1)}
            for w in weak
        ],
        "devamsizlik_saat": int(devam["toplam_saat"]) if devam and devam.get("toplam_saat") else 0,
        "son_negatif_sinyal": None,
        "son_rehberlik_notu": None,
    }

    if neg_sinyal:
        brief["son_negatif_sinyal"] = {
            "tip": neg_sinyal["insight_type"],
            "icerik": (neg_sinyal["content"] or "")[:200],
            "tarih": neg_sinyal["created_at"].isoformat() if neg_sinyal["created_at"] else None,
        }

    if rehber_note:
        brief["son_rehberlik_notu"] = {
            "tarih": rehber_note["gorusme_tarihi"].isoformat() if rehber_note.get("gorusme_tarihi") else None,
            "tur": rehber_note.get("not_turu"),
            "icerik": (rehber_note["not_metni"] or "")[:300],
        }

    # ── Veli mesaj taslağı (opsiyonel) ───────────────────
    if exams:
        last_net = brief["son_denemeler"][0]["toplam"]
        ort_trend = ""
        if len(exams) >= 2:
            diff = float(exams[0]["toplam"] or 0) - float(exams[1]["toplam"] or 0)
            ort_trend = f"(+{diff:.0f})" if diff > 0 else f"({diff:.0f})" if diff else "(stabil)"
        brief["veli_mesaj_taslagi"] = (
            f"Merhaba, {student['full_name']}'in bu hafta özeti:\n"
            f"• Son deneme: {last_net:.0f} net {ort_trend}\n"
            f"• Öncelikli çalışma alanları: "
            f"{', '.join(w['konu'][:30] for w in weak[:2]) if weak else 'hepsi dengeli'}\n"
            f"• Devamsızlık: {brief['devamsizlik_saat']} saat\n\n"
            f"Detaylı görüşme için randevu alabilirsiniz."
        )

    brief["hatirlatma"] = (
        "Bu tek-çağrı özet — sen ek tool çağrısı yapma, doğrudan rehbere sun. "
        "İstenirse eylem planı (etüt talebi, görüşme) öner."
    )
    return brief


async def get_class_brief(sinif: str, ders: str = "", tarih: str = "") -> dict:
    """Öğretmen için sınıf özeti — bugünün dersine hazırlık."""
    if not sinif:
        return {"error": "sinif zorunlu"}

    from db_pool import db_fetch, db_fetchval

    # 1. Sınıfta kaç öğrenci
    ogrenci_sayisi = await db_fetchval(
        """SELECT COUNT(*) FROM students
           WHERE status='active' AND (class_name = $1 OR sube = $1)""",
        sinif,
    )

    # 2. Son 5 denemenin ortalaması (ders bazlı varsa)
    if ders:
        ders_lower = ders.lower()
        ders_col = None
        if "mat" in ders_lower:
            ders_col = "matematik"
        elif "fiz" in ders_lower:
            ders_col = "fizik"
        elif "kim" in ders_lower:
            ders_col = "kimya"
        elif "bio" in ders_lower or "biyo" in ders_lower:
            ders_col = "biyoloji"
        elif "türk" in ders_lower or "turk" in ders_lower:
            ders_col = "turkce"
        elif "tarih" in ders_lower:
            ders_col = "tarih"
    else:
        ders_col = None

    if ders_col:
        ort = await db_fetchval(
            f"""SELECT AVG({ders_col})::numeric(10,2)
                FROM student_exams e
                JOIN students s ON s.soz_no::text = e.soz_no::text
                WHERE (s.class_name = $1 OR s.sube = $1)
                  AND e.status = 'valid' AND e.{ders_col} IS NOT NULL
                  AND e.exam_date > CURRENT_DATE - INTERVAL '30 days'""",
            sinif,
        )
        ort_net = float(ort) if ort else 0
    else:
        ort_net = None

    # 3. Sınıfta en zayıf 3 konu (ders filtresiyle) — INVERSION FIX
    # sinav_hata_yuzdesi = HATA %. Sınıfın zayıflığı = YÜKSEK ort hata. DESC.
    where_ders = f"AND stt.ders ILIKE '%{ders.replace(chr(39), '')}%'" if ders else ""
    rows = await db_fetch(f"""
      SELECT stt.ders, stt.konu,
             AVG(stt.sinav_hata_yuzdesi)::numeric(10,1) AS ort_hata_yuzde,
             (100 - AVG(stt.sinav_hata_yuzdesi))::numeric(10,1) AS ort_basari_yuzde,
             COUNT(DISTINCT stt.soz_no) AS ogr
      FROM student_topic_tracker stt
      JOIN students s ON s.soz_no::text = stt.soz_no::text
      WHERE (s.class_name = $1 OR s.sube = $1)
        AND (stt.tamamlandi IS NULL OR stt.tamamlandi = FALSE)
        AND COALESCE(stt.status,'') != 'metadata'
        AND stt.konu NOT LIKE 'Ortalama %'
      {where_ders}
      GROUP BY stt.ders, stt.konu
      HAVING COUNT(DISTINCT stt.soz_no) >= 2
         AND AVG(stt.sinav_hata_yuzdesi) >= 30
      ORDER BY AVG(stt.sinav_hata_yuzdesi) DESC NULLS LAST LIMIT 5
    """, sinif)

    weak_topics = [
        {"ders": r["ders"], "konu": r["konu"],
         "sinif_basari": float(r["ort_basari_yuzde"]) if r["ort_basari_yuzde"] else 0,
         "sinif_hata": float(r["ort_hata_yuzde"]) if r["ort_hata_yuzde"] else 0,
         "etki_ogrenci": int(r["ogr"])}
        for r in rows
    ]

    # 4. Devamsızlık riski (class bazlı) — devamsizlik_sayisi.soz_no tipi farklı olabilir
    try:
        risk = await db_fetchval(
            """SELECT COUNT(*) FROM students s
               LEFT JOIN devamsizlik_sayisi d ON d.soz_no::text = s.soz_no::text
               WHERE (s.class_name = $1 OR s.sube = $1) AND s.status = 'active'
                 AND d.toplam_saat > 100""",
            sinif
        )
    except Exception:
        risk = 0

    brief = {
        "sinif": sinif,
        "ders": ders or "(tüm dersler)",
        "ogrenci_sayisi": int(ogrenci_sayisi or 0),
        "ortalama_net_30gun": ort_net,
        "zayif_konular": weak_topics,
        "devamsizlik_riski_ogrenci": int(risk or 0),
        "oneri": "",
    }

    # Pedagojik öneri üret
    if weak_topics:
        top = weak_topics[0]
        brief["oneri"] = (
            f"Bugünkü derste {top['konu']} konusuna özellikle vakit ayır — "
            f"sınıfın %{100 - top['sinif_basari']:.0f}'i bu konuda zorluk yaşıyor "
            f"({top['etki_ogrenci']} öğrenci). 10 dakikalık tekrar + 2-3 örnek soru iyi sonuç verir."
        )
    else:
        brief["oneri"] = "Sınıf bu dersin genelinde dengeli — yeni konuya geçilebilir."

    return brief


if __name__ == "__main__":
    # CLI test
    import sys, io, json
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    async def main():
        from dotenv import load_dotenv
        load_dotenv(override=True)
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument("--counsellor", type=int, help="Soz_no (rehber brief)")
        p.add_argument("--class-brief", type=str, help="Sınıf adı (öğretmen brief)")
        p.add_argument("--ders", type=str, default="")
        args = p.parse_args()

        if args.counsellor:
            r = await prepare_counsellor_brief(args.counsellor)
            print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
        if args.class_brief:
            r = await get_class_brief(args.class_brief, ders=args.ders)
            print(json.dumps(r, indent=2, ensure_ascii=False, default=str))

    asyncio.run(main())
