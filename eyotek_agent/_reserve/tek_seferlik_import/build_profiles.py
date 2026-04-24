"""
FermatAI — Profil Oluşturucu
============================
PostgreSQL'deki ham verileri çapraz referansla birleştirip
öğrenci/öğretmen/sınıf bazında organize profil dokümanları üretir.

Bu profiller LLM'in sorulara hızlıca cevap vermesini sağlar —
Eyotek'e gitmeden yerel veriden analiz yapar.

Kullanım:
    python build_profiles.py                # Tüm profilleri oluştur
    python build_profiles.py --students     # Sadece öğrenci profilleri
    python build_profiles.py --teachers     # Sadece öğretmen profilleri
    python build_profiles.py --analytics    # Sadece analitik özetler
"""

import asyncio
import argparse
import json
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import asyncpg
from dotenv import load_dotenv
from loguru import logger

load_dotenv(override=True)
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://fermat:Ze-zzg10@localhost:5432/fermatai")

PROFILES_DIR = Path(__file__).parent / "profiles"
PROFILES_DIR.mkdir(exist_ok=True)
(PROFILES_DIR / "students").mkdir(exist_ok=True)
(PROFILES_DIR / "teachers").mkdir(exist_ok=True)
(PROFILES_DIR / "classes").mkdir(exist_ok=True)
(PROFILES_DIR / "analytics").mkdir(exist_ok=True)


# ═══════════════════════════════════════════════════════════════
# ÖĞRENCI PROFİLLERİ
# ═══════════════════════════════════════════════════════════════
async def build_student_profiles(conn):
    """Her öğrenci için çapraz referanslı profil dokümanı oluştur."""
    logger.info("Ogrenci profilleri olusturuluyor...")

    students = await conn.fetch(
        "SELECT * FROM students ORDER BY class_name, full_name"
    )

    # Etut kontrol verisi (soz_no bazli)
    etut_ctrl = {}
    try:
        rows = await conn.fetch("SELECT * FROM etut_student_control_cache")
        for r in rows:
            etut_ctrl[r["soz_no"]] = dict(r)
    except Exception:
        pass

    # Sinav analizi (soz_no bazli)
    exam_analysis = defaultdict(list)
    try:
        rows = await conn.fetch("SELECT * FROM student_exam_analysis ORDER BY soz_no, sinav_tarihi DESC")
        for r in rows:
            exam_analysis[r["soz_no"]].append(dict(r))
    except Exception:
        pass

    # Sinif kadrosu (soz_no → sinif bilgisi)
    roster_map = {}
    try:
        rows = await conn.fetch("SELECT * FROM class_roster")
        for r in rows:
            roster_map[r["soz_no"]] = dict(r)
    except Exception:
        pass

    profiles = []
    for st in students:
        soz_no = st["soz_no"] or ""
        eyotek_id = st["eyotek_id"] or ""
        full_name = st["full_name"] or f"{st.get('first_name','')} {st.get('last_name','')}"
        class_name = st["class_name"] or ""
        devre = st["devre"] or ""

        # Etut verisi
        etut = etut_ctrl.get(soz_no, {})
        etut_toplam = etut.get("toplam", 0) or 0
        etut_yapildi = etut.get("yapildi", 0) or 0
        etut_gelmedi = etut.get("gelmedi", 0) or 0
        etut_kontrol = etut.get("kontrol_edilmedi", 0) or 0
        etut_katilim = (
            round(etut_yapildi / etut_toplam * 100) if etut_toplam > 0 else 0
        )

        # Sinav analizi
        exams = exam_analysis.get(soz_no, [])
        son_sinav = exams[0] if exams else {}
        sinav_sayisi = len(exams)

        # Oncelikli konular (en son sinavdan)
        oncelikli_konular = son_sinav.get("oncelikli_konular", "") if son_sinav else ""
        son_puan = son_sinav.get("ham_puan", "") if son_sinav else ""
        son_siralama = son_sinav.get("genel_siralama", "") if son_sinav else ""

        # Kadro bilgisi
        roster = roster_map.get(soz_no, {})
        rehber = roster.get("rehber", "")
        danisman = roster.get("danisman", "")

        # Risk analizi
        risk_factors = []
        if etut_toplam > 0 and etut_katilim < 50:
            risk_factors.append(f"Dusuk etut katilimi (%{etut_katilim})")
        if etut_gelmedi > 3:
            risk_factors.append(f"Etute {etut_gelmedi} kez gelmedi")
        if son_puan and str(son_puan).replace(".", "").isdigit():
            puan = float(son_puan)
            if puan < 200:
                risk_factors.append(f"Dusuk sinav puani ({son_puan})")

        risk_level = "yuksek" if len(risk_factors) >= 2 else "orta" if risk_factors else "dusuk"

        profile = {
            "soz_no": soz_no,
            "eyotek_id": eyotek_id,
            "ad_soyad": full_name,
            "sinif": class_name,
            "devre": devre,
            "telefon": st.get("phone", ""),
            "rehber": rehber,
            "danisman": danisman,
            # Etut
            "etut_toplam": etut_toplam,
            "etut_yapildi": etut_yapildi,
            "etut_gelmedi": etut_gelmedi,
            "etut_kontrol_edilmedi": etut_kontrol,
            "etut_katilim_yuzdesi": etut_katilim,
            # Sinav
            "sinav_sayisi": sinav_sayisi,
            "son_sinav_puan": son_puan,
            "son_sinav_siralama": son_siralama,
            "oncelikli_konular": oncelikli_konular,
            # Risk
            "risk_seviyesi": risk_level,
            "risk_faktorleri": risk_factors,
            # Meta
            "profil_tarihi": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        profiles.append(profile)

        # Bireysel dosya
        safe_name = full_name.replace(" ", "_").replace("/", "_")[:30]
        fpath = PROFILES_DIR / "students" / f"{soz_no}_{safe_name}.json"
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)

    # Toplam ozet
    summary_path = PROFILES_DIR / "students" / "_summary.json"
    summary = {
        "toplam_ogrenci": len(profiles),
        "tarih": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "sinif_dagilimi": {},
        "risk_dagilimi": {"yuksek": 0, "orta": 0, "dusuk": 0},
        "etut_katilim_ortalama": 0,
    }
    sinif_counts = defaultdict(int)
    total_katilim = 0
    katilim_count = 0
    for p in profiles:
        sinif_counts[p["sinif"]] += 1
        summary["risk_dagilimi"][p["risk_seviyesi"]] += 1
        if p["etut_toplam"] > 0:
            total_katilim += p["etut_katilim_yuzdesi"]
            katilim_count += 1
    summary["sinif_dagilimi"] = dict(sinif_counts)
    summary["etut_katilim_ortalama"] = (
        round(total_katilim / katilim_count) if katilim_count > 0 else 0
    )
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    logger.success(f"  {len(profiles)} ogrenci profili olusturuldu")
    logger.info(f"  Risk: yuksek={summary['risk_dagilimi']['yuksek']}, "
                f"orta={summary['risk_dagilimi']['orta']}, "
                f"dusuk={summary['risk_dagilimi']['dusuk']}")
    return profiles


# ═══════════════════════════════════════════════════════════════
# ÖĞRETMEN PROFİLLERİ
# ═══════════════════════════════════════════════════════════════
async def build_teacher_profiles(conn):
    """Her öğretmen için ders yükü + etüt yoğunluğu profili."""
    logger.info("Ogretmen profilleri olusturuluyor...")

    staff = await conn.fetch(
        "SELECT * FROM staff WHERE status='Aktif' ORDER BY full_name"
    )

    # Etut raporlari (ogretmen_id bazli)
    etut_map = {}
    try:
        rows = await conn.fetch("SELECT * FROM etut_reports_cache")
        for r in rows:
            etut_map[r["ogretmen_id"]] = dict(r)
    except Exception:
        pass

    # Hangi siniflarda hangi ogretmen var (class_roster uzerinden degil, etut uzerinden)
    # Ogretmen ders programi (teacher_timetable)
    tt_map = defaultdict(list)
    try:
        rows = await conn.fetch("SELECT * FROM teacher_timetable ORDER BY gun, saat")
        for r in rows:
            tt_map[r["ogretmen_id"]].append(dict(r))
    except Exception:
        pass

    profiles = []
    for s in staff:
        eid = s["eyotek_id"]
        gorev = s.get("gorev", "")
        if gorev and "öğretmen" not in gorev.lower() and "ogretmen" not in gorev.lower():
            if eid not in ("1035",):  # Zeki Bey dahil
                continue

        etut = etut_map.get(eid, {})
        timetable = tt_map.get(eid, [])

        # Ders yogunlugu analizi
        gun_dagilimi = defaultdict(int)
        for slot in timetable:
            gun_dagilimi[slot.get("gun", "")] += 1

        profile = {
            "eyotek_id": eid,
            "ad_soyad": s["full_name"],
            "brans": s.get("brans", ""),
            "gorev": gorev,
            # Ders yuku
            "haftalik_ders_saati": etut.get("toplam_ders", 0) or 0,
            "aylik_etut_sayisi": etut.get("toplam_etut", 0) or 0,
            "etut_ogrenci_sayisi": etut.get("ogrenci_sayisi", 0) or 0,
            # Etut yogunlugu
            "etut_ders_orani": (
                round((etut.get("toplam_etut", 0) or 0) / max(etut.get("toplam_ders", 0) or 1, 1), 2)
            ),
            # Ders programi
            "ders_programi_slot_sayisi": len(timetable),
            "gun_dagilimi": dict(gun_dagilimi),
            # Meta
            "profil_tarihi": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        profiles.append(profile)

        safe_name = (s["full_name"] or "").replace(" ", "_")[:25]
        fpath = PROFILES_DIR / "teachers" / f"{eid}_{safe_name}.json"
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)

    # Ogretmen ozet
    summary = {
        "toplam_ogretmen": len(profiles),
        "tarih": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "brans_dagilimi": {},
        "etut_siralaması": [],
    }
    brans_counts = defaultdict(int)
    for p in profiles:
        brans_counts[p["brans"]] += 1
    summary["brans_dagilimi"] = dict(brans_counts)
    summary["etut_siralaması"] = sorted(
        [{"ad": p["ad_soyad"], "etut": p["aylik_etut_sayisi"], "ders": p["haftalik_ders_saati"]}
         for p in profiles],
        key=lambda x: x["etut"], reverse=True
    )

    with open(PROFILES_DIR / "teachers" / "_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    logger.success(f"  {len(profiles)} ogretmen profili olusturuldu")
    return profiles


# ═══════════════════════════════════════════════════════════════
# SINIF PROFİLLERİ
# ═══════════════════════════════════════════════════════════════
async def build_class_profiles(conn):
    """Her sınıf için kadro + akademik durum + etüt özeti."""
    logger.info("Sinif profilleri olusturuluyor...")

    # Sinif kadrolari
    classes = await conn.fetch(
        "SELECT DISTINCT sinif, devre FROM class_roster ORDER BY devre, sinif"
    )

    profiles = []
    for cls in classes:
        sinif = cls["sinif"]
        devre = cls["devre"]

        # Bu siniftaki ogrenciler
        students = await conn.fetch(
            "SELECT cr.soz_no, cr.ad, cr.soyad, cr.rehber, cr.danisman, "
            "s.class_name, s.phone "
            "FROM class_roster cr "
            "LEFT JOIN students s ON cr.soz_no = s.soz_no "
            "WHERE cr.sinif = $1 ORDER BY cr.ad",
            sinif,
        )

        # Etut verileri (bu siniftaki ogrenciler)
        soz_nos = [s["soz_no"] for s in students if s["soz_no"]]
        etut_data = []
        if soz_nos:
            placeholders = ", ".join(f"${i+1}" for i in range(len(soz_nos)))
            etut_data = await conn.fetch(
                f"SELECT * FROM etut_student_control_cache WHERE soz_no IN ({placeholders})",
                *soz_nos,
            )

        toplam_etut = sum(r["toplam"] or 0 for r in etut_data)
        toplam_yapildi = sum(r["yapildi"] or 0 for r in etut_data)
        toplam_gelmedi = sum(r["gelmedi"] or 0 for r in etut_data)

        # Sinav verileri
        exam_data = []
        if soz_nos:
            try:
                exam_data = await conn.fetch(
                    f"SELECT * FROM student_exam_analysis WHERE soz_no IN ({placeholders}) "
                    "ORDER BY sinav_tarihi DESC",
                    *soz_nos,
                )
            except Exception:
                pass

        # Puan ortalamasi
        puanlar = []
        for e in exam_data:
            try:
                p = float(e.get("ham_puan", 0) or 0)
                if p > 0:
                    puanlar.append(p)
            except (ValueError, TypeError):
                pass
        puan_ort = round(sum(puanlar) / len(puanlar), 1) if puanlar else 0

        profile = {
            "sinif": sinif,
            "devre": devre,
            "ogrenci_sayisi": len(students),
            "ogrenciler": [
                {"soz_no": s["soz_no"], "ad": s["ad"], "soyad": s["soyad"]}
                for s in students
            ],
            "etut_toplam": toplam_etut,
            "etut_yapildi": toplam_yapildi,
            "etut_gelmedi": toplam_gelmedi,
            "etut_katilim_yuzdesi": (
                round(toplam_yapildi / toplam_etut * 100) if toplam_etut > 0 else 0
            ),
            "sinav_puan_ortalamasi": puan_ort,
            "sinav_sayisi": len(set(e.get("sinav_adi", "") for e in exam_data)),
            "profil_tarihi": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        profiles.append(profile)

        safe_sinif = sinif.replace(" ", "_").replace("[", "").replace("]", "")
        fpath = PROFILES_DIR / "classes" / f"{safe_sinif}.json"
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)

    with open(PROFILES_DIR / "classes" / "_summary.json", "w", encoding="utf-8") as f:
        json.dump({"siniflar": [p["sinif"] for p in profiles], "tarih": datetime.now().strftime("%Y-%m-%d %H:%M")}, f, ensure_ascii=False, indent=2)

    logger.success(f"  {len(profiles)} sinif profili olusturuldu")
    return profiles


# ═══════════════════════════════════════════════════════════════
# ANALİTİK ÖZETLER
# ═══════════════════════════════════════════════════════════════
async def build_analytics(conn):
    """Çapraz referans analizleri — LLM'in doğrudan okuyacağı özetler."""
    logger.info("Analitik ozetler olusturuluyor...")

    analytics = {}

    # 1. Risk altindaki ogrenciler
    risk_students = await conn.fetch("""
        SELECT s.soz_no, s.full_name, s.class_name,
               ec.yapildi, ec.gelmedi, ec.kontrol_edilmedi, ec.toplam
        FROM students s
        LEFT JOIN etut_student_control_cache ec ON s.soz_no = ec.soz_no
        WHERE ec.toplam > 0
        ORDER BY (ec.gelmedi::float / GREATEST(ec.toplam, 1)) DESC
        LIMIT 20
    """)
    analytics["risk_ogrenciler"] = [
        {
            "soz_no": r["soz_no"],
            "ad_soyad": r["full_name"],
            "sinif": r["class_name"],
            "etut_toplam": r["toplam"],
            "gelmedi": r["gelmedi"],
            "katilim_yuzdesi": round((r["yapildi"] or 0) / max(r["toplam"] or 1, 1) * 100),
        }
        for r in risk_students
    ]

    # 2. Ogretmen etut yogunlugu karsilastirmasi
    teacher_compare = await conn.fetch("""
        SELECT er.ogretmen_id, er.full_name, er.toplam_ders, er.toplam_etut,
               er.ogrenci_sayisi, s.brans
        FROM etut_reports_cache er
        LEFT JOIN staff s ON er.ogretmen_id = s.eyotek_id
        WHERE er.full_name IS NOT NULL AND er.full_name != ''
        ORDER BY er.toplam_etut DESC
    """)
    analytics["ogretmen_karsilastirma"] = [
        {
            "ad_soyad": r["full_name"],
            "brans": r["brans"],
            "ders": r["toplam_ders"],
            "etut": r["toplam_etut"],
            "ogrenci": r["ogrenci_sayisi"],
            "etut_ders_oran": round((r["toplam_etut"] or 0) / max(r["toplam_ders"] or 1, 1), 2),
        }
        for r in teacher_compare
    ]

    # 3. Sinif bazli etut katilim ozeti
    class_etut = await conn.fetch("""
        SELECT cr.sinif, cr.devre,
               COUNT(*) as ogrenci_sayisi,
               SUM(COALESCE(ec.toplam, 0)) as toplam_etut,
               SUM(COALESCE(ec.yapildi, 0)) as yapildi,
               SUM(COALESCE(ec.gelmedi, 0)) as gelmedi
        FROM class_roster cr
        LEFT JOIN etut_student_control_cache ec ON cr.soz_no = ec.soz_no
        GROUP BY cr.sinif, cr.devre
        ORDER BY cr.devre, cr.sinif
    """)
    analytics["sinif_etut_ozet"] = [
        {
            "sinif": r["sinif"],
            "devre": r["devre"],
            "ogrenci": r["ogrenci_sayisi"],
            "toplam_etut": r["toplam_etut"],
            "katilim_yuzdesi": round((r["yapildi"] or 0) / max(r["toplam_etut"] or 1, 1) * 100),
        }
        for r in class_etut
    ]

    # 4. Brans bazli etut dagilimi
    brans_etut = await conn.fetch("""
        SELECT s.brans, COUNT(*) as ogretmen_sayisi,
               SUM(er.toplam_etut) as toplam_etut,
               SUM(er.toplam_ders) as toplam_ders
        FROM etut_reports_cache er
        JOIN staff s ON er.ogretmen_id = s.eyotek_id
        WHERE er.full_name IS NOT NULL AND er.full_name != ''
        GROUP BY s.brans
        ORDER BY toplam_etut DESC
    """)
    analytics["brans_etut_dagilimi"] = [
        {
            "brans": r["brans"],
            "ogretmen_sayisi": r["ogretmen_sayisi"],
            "toplam_etut": r["toplam_etut"],
            "toplam_ders": r["toplam_ders"],
        }
        for r in brans_etut
    ]

    # 5. Konu analizi — en cok yanlis yapilan konular (tum ogrenciler)
    try:
        konu_rows = await conn.fetch("""
            SELECT oncelikli_konular, COUNT(*) as ogrenci_sayisi
            FROM student_exam_analysis
            WHERE oncelikli_konular IS NOT NULL AND oncelikli_konular != ''
            GROUP BY oncelikli_konular
            ORDER BY ogrenci_sayisi DESC
            LIMIT 20
        """)
        analytics["oncelikli_konular"] = [
            {"konu": r["oncelikli_konular"][:100], "ogrenci_sayisi": r["ogrenci_sayisi"]}
            for r in konu_rows
        ]
    except Exception:
        analytics["oncelikli_konular"] = []

    # Kaydet
    fpath = PROFILES_DIR / "analytics" / "genel_analiz.json"
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(analytics, f, ensure_ascii=False, indent=2)

    # Okunabilir ozet (LLM icin)
    txt_path = PROFILES_DIR / "analytics" / "ozet_rapor.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"FermatAI Analitik Ozet — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write("=" * 60 + "\n\n")

        f.write("OGRETMEN ETUT YOGUNLUGU:\n")
        for t in analytics["ogretmen_karsilastirma"]:
            f.write(f"  {t['ad_soyad']:<25} {t['brans']:<12} "
                    f"ders={t['ders']:<4} etut={t['etut']:<4} "
                    f"ogrenci={t['ogrenci']}\n")

        f.write(f"\nSINIF ETUT KATILIM:\n")
        for c in analytics["sinif_etut_ozet"]:
            f.write(f"  {c['sinif']:<25} {c['devre']:<10} "
                    f"etut={c['toplam_etut']:<5} katilim=%{c['katilim_yuzdesi']}\n")

        f.write(f"\nBRANS BAZLI ETUT:\n")
        for b in analytics["brans_etut_dagilimi"]:
            f.write(f"  {b['brans']:<15} ogretmen={b['ogretmen_sayisi']:<3} "
                    f"etut={b['toplam_etut']:<5} ders={b['toplam_ders']}\n")

        f.write(f"\nRISK ALTINDAKI OGRENCILER (en dusuk katilim):\n")
        for r in analytics["risk_ogrenciler"][:10]:
            f.write(f"  {r['ad_soyad']:<25} {r['sinif']:<15} "
                    f"etut={r['etut_toplam']:<4} gelmedi={r['gelmedi']:<3} "
                    f"katilim=%{r['katilim_yuzdesi']}\n")

    logger.success(f"  Analitik ozet olusturuldu: {txt_path}")
    return analytics


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
async def main():
    parser = argparse.ArgumentParser(description="FermatAI Profil Olusturucu")
    parser.add_argument("--students", action="store_true")
    parser.add_argument("--teachers", action="store_true")
    parser.add_argument("--classes", action="store_true")
    parser.add_argument("--analytics", action="store_true")
    args = parser.parse_args()

    do_all = not (args.students or args.teachers or args.classes or args.analytics)

    conn = await asyncpg.connect(DATABASE_URL)

    if do_all or args.students:
        await build_student_profiles(conn)

    if do_all or args.teachers:
        await build_teacher_profiles(conn)

    if do_all or args.classes:
        await build_class_profiles(conn)

    if do_all or args.analytics:
        await build_analytics(conn)

    await conn.close()
    logger.success(f"Profiller olusturuldu: {PROFILES_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
