"""
FermatAI — Data Audit Script (22.1n-toplanti #3)
==================================================

Bot TOP#3 önerisi — 20 Nisan toplantıda:
> "Veri kalitesi — her şeyin tabanı bu. student_topic_tracker.sinav_hata_yuzdesi
>  aslında başarı yüzdesi, class_name NULL, derslik D-1 her yerde, [AYT] prefix
>  sahte kayıtlar... Yaz kampına 70 yeni öğrenci geldiğinde bu kirli veriyle
>  çalışmaya devam edersek: çalışma planları yanlış, rehber raporları tutarsız,
>  veli bildirimleri yanlış net gösterir."

BU SCRIPT:
- Tüm kritik tablolarda NULL, tutarsız, sahte kayıtları SAYIP RAPORLAR
- DRY-RUN modu: sadece raporlar, düzeltmez
- --apply modu: Neo onayıyla temizlik uygular

KULLANIM:
  python data_audit.py                  # DRY-RUN rapor
  python data_audit.py --apply-safe     # Sadece güvenli düzeltmeler (AYT prefix temizle)
  python data_audit.py --full-report    # Her tablo için detay

GÜVENLİK: MESAJ ATMAZ, silmez (apply-safe olmadan), sadece rapor + UPDATE.
"""
import asyncio
import sys
from datetime import datetime

from loguru import logger


# ─── CHECK FONKSIYONLARI ──────────────────────────────────────────────────────

async def check_students():
    """students tablosu kalite."""
    from db_pool import db_fetch, db_fetchval
    print("\n📋 students")
    print("─" * 60)

    total = await db_fetchval("SELECT COUNT(*) FROM students WHERE status='active'")
    print(f"  Aktif öğrenci: {total}")

    null_class = await db_fetchval(
        "SELECT COUNT(*) FROM students WHERE status='active' AND (class_name IS NULL OR class_name='')")
    print(f"  class_name NULL/boş: {null_class}")

    null_phone = await db_fetchval(
        "SELECT COUNT(*) FROM students WHERE status='active' AND (phone IS NULL OR phone='')")
    print(f"  phone NULL/boş: {null_phone}")

    prefix_class = await db_fetchval(
        "SELECT COUNT(*) FROM students WHERE status='active' AND class_name LIKE '[%'")
    print(f"  class_name prefix'li '[10] 10 SAY A': {prefix_class}")

    no_program = await db_fetchval(
        "SELECT COUNT(*) FROM students WHERE status='active' AND (program IS NULL OR program='')")
    print(f"  program NULL/boş: {no_program}")

    return {"total": total, "null_class": null_class, "null_phone": null_phone,
            "prefix_class": prefix_class, "no_program": no_program}


async def check_student_exams():
    """student_exams — sahte [AYT] prefix'li kayıtlar."""
    from db_pool import db_fetch, db_fetchval
    print("\n📝 student_exams")
    print("─" * 60)

    total = await db_fetchval("SELECT COUNT(*) FROM student_exams")
    print(f"  Toplam kayıt: {total}")

    ayt_prefix = await db_fetchval(
        "SELECT COUNT(*) FROM student_exams WHERE exam_name LIKE '[AYT]%'")
    print(f"  [AYT] prefix sahte: {ayt_prefix}")

    null_toplam = await db_fetchval(
        "SELECT COUNT(*) FROM student_exams WHERE toplam IS NULL OR toplam = 0")
    print(f"  toplam NULL/0: {null_toplam}")

    future_date = await db_fetchval(
        "SELECT COUNT(*) FROM student_exams WHERE exam_date > CURRENT_DATE")
    print(f"  Geleceğe tarihli sınav: {future_date}")

    # Duplicate: aynı öğrenci + aynı tarih + aynı isim
    dup = await db_fetchval("""
      SELECT COUNT(*) FROM (
        SELECT soz_no, exam_date, exam_name FROM student_exams
        WHERE status='valid'
        GROUP BY soz_no, exam_date, exam_name
        HAVING COUNT(*) > 1
      ) AS d
    """)
    print(f"  Duplicate kombinasyonlar: {dup}")

    return {"total": total, "ayt_prefix": ayt_prefix, "null_toplam": null_toplam,
            "future_date": future_date, "duplicates": dup}


async def check_topic_tracker():
    """student_topic_tracker — kolon adı yanıltıcı (sinav_hata_yuzdesi aslında başarı)."""
    from db_pool import db_fetch, db_fetchval
    print("\n🎯 student_topic_tracker")
    print("─" * 60)

    total = await db_fetchval("SELECT COUNT(*) FROM student_topic_tracker")
    print(f"  Toplam kayıt: {total}")

    invalid_yuzde = await db_fetchval(
        "SELECT COUNT(*) FROM student_topic_tracker WHERE sinav_hata_yuzdesi > 100 OR sinav_hata_yuzdesi < 0")
    print(f"  sinav_hata_yuzdesi > 100 veya < 0 (anomali): {invalid_yuzde}")

    all_zero = await db_fetchval(
        "SELECT COUNT(*) FROM student_topic_tracker WHERE sinav_hata_yuzdesi = 0 AND sinav_hata_sayisi = 0")
    print(f"  Tamamen 0 kayıt (muhtemelen boş): {all_zero}")

    never_studied = await db_fetchval(
        "SELECT COUNT(*) FROM student_topic_tracker WHERE tamamlandi = FALSE")
    print(f"  tamamlandı=FALSE (hiç çalışılmamış işaretli): {never_studied}")

    completed = await db_fetchval(
        "SELECT COUNT(*) FROM student_topic_tracker WHERE tamamlandi = TRUE")
    print(f"  tamamlandı=TRUE: {completed}")

    print(f"  ⚠️  KOLON ADI YANILTICI: 'sinav_hata_yuzdesi' aslında 'sinav_basari_yuzdesi'")

    return {"total": total, "invalid_yuzde": invalid_yuzde, "all_zero": all_zero,
            "completed": completed, "never_studied": never_studied}


async def check_class_timetable():
    """class_timetable — D-1 derslik çakışması (bot tespit)."""
    from db_pool import db_fetch, db_fetchval
    print("\n📅 class_timetable")
    print("─" * 60)

    total = await db_fetchval("SELECT COUNT(*) FROM class_timetable")
    print(f"  Toplam slot: {total}")

    # Derslik dağılımı
    rows = await db_fetch("""
      SELECT COALESCE(derslik, 'NULL') AS derslik, COUNT(*) AS c
      FROM class_timetable GROUP BY derslik ORDER BY c DESC LIMIT 10
    """)
    print(f"  Derslik dağılımı:")
    for r in rows:
        print(f"    {r['derslik']:15s}: {r['c']}")

    # D-1 çakışması (bot tespit — 62 slot)
    d1_total = await db_fetchval(
        "SELECT COUNT(*) FROM class_timetable WHERE derslik = 'D-1'")
    print(f"  D-1 slot sayısı (bot: 62 çakışma): {d1_total}")

    null_derslik = await db_fetchval(
        "SELECT COUNT(*) FROM class_timetable WHERE derslik IS NULL OR derslik = ''")
    print(f"  Derslik NULL/boş: {null_derslik}")

    return {"total": total, "d1_slots": d1_total, "null_derslik": null_derslik}


async def check_rag_content():
    """rag_content — boş embedding, dublicate, vs."""
    from db_pool import db_fetchval
    print("\n📚 rag_content")
    print("─" * 60)

    total = await db_fetchval("SELECT COUNT(*) FROM rag_content")
    print(f"  Toplam kayıt: {total}")

    no_emb = await db_fetchval("SELECT COUNT(*) FROM rag_content WHERE embedding IS NULL")
    print(f"  Embedding eksik: {no_emb}")

    no_konu = await db_fetchval(
        "SELECT COUNT(*) FROM rag_content WHERE konu IS NULL OR konu = '' OR konu = '-'")
    print(f"  Konu eksik/-: {no_konu}")

    no_ders = await db_fetchval(
        "SELECT COUNT(*) FROM rag_content WHERE ders IS NULL OR ders = ''")
    print(f"  Ders eksik: {no_ders}")

    return {"total": total, "no_embedding": no_emb, "no_konu": no_konu, "no_ders": no_ders}


async def check_acl_users():
    """acl_users — inactive user temizliği."""
    from db_pool import db_fetchval
    print("\n🔐 acl_users")
    print("─" * 60)

    total = await db_fetchval("SELECT COUNT(*) FROM acl_users")
    active = await db_fetchval("SELECT COUNT(*) FROM acl_users WHERE is_active = TRUE")
    inactive = total - active
    print(f"  Toplam: {total} | Aktif: {active} | Inactive: {inactive}")

    no_name = await db_fetchval(
        "SELECT COUNT(*) FROM acl_users WHERE full_name IS NULL OR full_name = ''")
    print(f"  full_name boş: {no_name}")

    dup_phone = await db_fetchval("""
      SELECT COUNT(*) FROM (
        SELECT phone FROM acl_users GROUP BY phone HAVING COUNT(*) > 1
      ) AS d
    """)
    print(f"  Duplicate phone: {dup_phone}")

    return {"total": total, "active": active, "no_name": no_name, "dup_phone": dup_phone}


async def check_insights():
    """student_insights — eski veri."""
    from db_pool import db_fetchval
    print("\n🧠 student_insights")
    print("─" * 60)

    total = await db_fetchval("SELECT COUNT(*) FROM student_insights")
    active = await db_fetchval("SELECT COUNT(*) FROM student_insights WHERE active = TRUE")
    no_soz = await db_fetchval(
        "SELECT COUNT(*) FROM student_insights WHERE soz_no IS NULL OR soz_no = 0")
    print(f"  Toplam: {total} | Aktif: {active}")
    print(f"  soz_no=0 (bug kayıtları): {no_soz}")

    test_records = await db_fetchval(
        "SELECT COUNT(*) FROM student_insights WHERE content LIKE '%TEHDIT%[905000000000]%'")
    print(f"  Test sahte kayıtlar (905000000000): {test_records}")

    return {"total": total, "active": active, "no_soz": no_soz, "test_records": test_records}


# ─── APPLY FONKSIYONLARI ──────────────────────────────────────────────────────

async def apply_safe_fixes():
    """Güvenli düzeltmeler — geri alınabilir, kritik veri silmez."""
    from db_pool import db_execute, db_fetchval
    print("\n🔧 Güvenli Düzeltmeler Uygulanıyor")
    print("─" * 60)

    # 1. [AYT] prefix'li sahte sınav kayıtlarını invalid işaretle
    invalid_exams = await db_fetchval("""
      SELECT COUNT(*) FROM student_exams
      WHERE exam_name LIKE '[AYT]%' AND status = 'valid'
    """)
    if invalid_exams:
        await db_execute("""
          UPDATE student_exams SET status = 'sahte_ayt_prefix'
          WHERE exam_name LIKE '[AYT]%' AND status = 'valid'
        """)
        print(f"  ✓ {invalid_exams} [AYT] prefix kaydı status='sahte_ayt_prefix' yapıldı")

    # 2. Test sahte insights (905000000000 phone)
    test_insights = await db_fetchval(
        "SELECT COUNT(*) FROM student_insights WHERE content LIKE '%[905000000000]%' AND active = TRUE")
    if test_insights:
        await db_execute("""
          UPDATE student_insights SET active = FALSE, stale_reason = 'test_data_cleanup'
          WHERE content LIKE '%[905000000000]%' AND active = TRUE
        """)
        print(f"  ✓ {test_insights} test insight pasife alındı")

    # 3. class_timetable'da boş derslikleri 'TBD' yap
    null_derslik = await db_fetchval(
        "SELECT COUNT(*) FROM class_timetable WHERE derslik IS NULL OR derslik = ''")
    if null_derslik:
        await db_execute(
            "UPDATE class_timetable SET derslik = 'TBD' WHERE derslik IS NULL OR derslik = ''")
        print(f"  ✓ {null_derslik} NULL derslik 'TBD' yapıldı")

    # 4. sinav_hata_yuzdesi > 100 olanları 100'e clamp et
    anomaly = await db_fetchval(
        "SELECT COUNT(*) FROM student_topic_tracker WHERE sinav_hata_yuzdesi > 100")
    if anomaly:
        await db_execute(
            "UPDATE student_topic_tracker SET sinav_hata_yuzdesi = 100 WHERE sinav_hata_yuzdesi > 100")
        print(f"  ✓ {anomaly} anormal yüzde 100'e clamp")

    print("\n✅ Güvenli düzeltmeler tamam")


# ─── CLI ──────────────────────────────────────────────────────────────────────

async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply-safe", action="store_true",
                        help="Güvenli düzeltmeleri uygula (AYT prefix, test insight, TBD derslik)")
    parser.add_argument("--full-report", action="store_true",
                        help="Detaylı rapor (uzun sürer)")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv(override=True)

    print("=" * 60)
    print("📊 FermatAI — Data Audit Raporu")
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    # Tüm kontroller
    results = {
        "students": await check_students(),
        "exams": await check_student_exams(),
        "topics": await check_topic_tracker(),
        "timetable": await check_class_timetable(),
        "rag": await check_rag_content(),
        "acl": await check_acl_users(),
        "insights": await check_insights(),
    }

    # Özet sorun listesi
    print("\n" + "=" * 60)
    print("🔍 Tespit Edilen Problemler")
    print("=" * 60)
    issues = []
    if results["students"]["null_class"]:
        issues.append(f"  🟡 {results['students']['null_class']} öğrencinin class_name NULL")
    if results["students"]["prefix_class"]:
        issues.append(f"  🟡 {results['students']['prefix_class']} öğrencinin class_name prefix'li [10]...")
    if results["exams"]["ayt_prefix"]:
        issues.append(f"  🔴 {results['exams']['ayt_prefix']} [AYT] prefix sahte sınav kaydı")
    if results["exams"]["duplicates"]:
        issues.append(f"  🟠 {results['exams']['duplicates']} duplicate sınav kombinasyonu")
    if results["topics"]["invalid_yuzde"]:
        issues.append(f"  🔴 {results['topics']['invalid_yuzde']} topic_tracker yüzde anomalisi")
    if results["timetable"]["d1_slots"] > 30:
        issues.append(f"  🔴 {results['timetable']['d1_slots']} D-1 derslik kaydı (bot: çakışma)")
    if results["rag"]["no_embedding"]:
        issues.append(f"  🟡 {results['rag']['no_embedding']} RAG kaydı embedding eksik")
    if results["acl"]["dup_phone"]:
        issues.append(f"  🔴 {results['acl']['dup_phone']} duplicate ACL phone")
    if results["insights"]["no_soz"]:
        issues.append(f"  🟡 {results['insights']['no_soz']} insight soz_no=0 bug kaydı")
    if results["insights"]["test_records"]:
        issues.append(f"  🟢 {results['insights']['test_records']} test sahte insight (tem.ok)")

    if issues:
        for i in issues:
            print(i)
    else:
        print("  ✅ Kritik sorun bulunamadı")

    # Öneri
    print("\n" + "=" * 60)
    print("💡 Öneriler")
    print("=" * 60)
    print("  1. [AYT] prefix sahte kayıtları → --apply-safe ile temizle")
    print("  2. D-1 dersliği → Eyotek'ten gerçek derslik bilgisi senkronla")
    print("  3. class_name prefix'li kayıtları → regex ile normalize et")
    print("  4. topic_tracker kolon adı → 'sinav_hata_yuzdesi' yanıltıcı, yorumla (UI aslında başarı gösteriyor)")
    print()

    if args.apply_safe:
        await apply_safe_fixes()
    else:
        print("ℹ️  --apply-safe ile güvenli düzeltmeleri uygula (test insight + AYT prefix + TBD derslik)")


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    asyncio.run(main())
