"""25.43-LAZY-EXTEND-V2: 4 yeni upsert smoke test.

Her upsert fonksiyonunu fake row ile test et, DB'ye yazılıp yazılmadığını gör.
Sonra cleanup yap (test kayıtlarını sil).
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

TEST_SOZ_NO = 999998  # benzersiz test soz_no


async def cleanup_test_records():
    """Test kayıtlarını temizle."""
    from db_pool import db_execute
    queries = [
        ("DELETE FROM counsellor_notes WHERE soz_no = $1 OR ogrenci_adi LIKE 'TestSentetik%'", [TEST_SOZ_NO]),
        ("DELETE FROM attendance WHERE soz_no = $1 OR full_name LIKE 'TestSentetik%'", [str(TEST_SOZ_NO)]),
        ("DELETE FROM teacher_timetable WHERE ogretmen_id LIKE 'TEST_%' OR ogretmen_ad LIKE 'TestSentetik%'", []),
        ("DELETE FROM devamsizlik_sayisi WHERE soz_no = $1 OR adi LIKE 'TestSentetik%'", [TEST_SOZ_NO]),
        ("DELETE FROM student_exams WHERE student_name LIKE 'TestSentetik%' OR exam_code LIKE 'lazy_TEST_%'", []),
    ]
    for q, args in queries:
        try:
            if args:
                await db_execute(q, *args)
            else:
                await db_execute(q)
        except Exception as e:
            print(f"  cleanup skip: {e}")


async def test_attendance():
    from eyotek_lazy_sync import lazy_sync_after_query
    r = await lazy_sync_after_query({
        "success": True, "page": "student/attendance-report",
        "rows": [{
            "ogrenci_adi": "TestSentetikAttend",
            "tarih": "2026-05-10", "ders_no": "1", "saat": "09:00",
            "gun": "Cumartesi", "durum": "Var", "sube": "Test",
            "soz_no": TEST_SOZ_NO,
        }],
        "columns": [],
    })
    ok = r.get("synced") and r.get("count", 0) > 0
    print(f"  [{'OK' if ok else 'FAIL'}] attendance: {r}")
    return ok


async def test_counsellor():
    from eyotek_lazy_sync import lazy_sync_after_query
    r = await lazy_sync_after_query({
        "success": True, "page": "student/counsellor-meeting",
        "rows": [{
            "ogrenci_adi": "TestSentetikCouns", "ogrenci_soyadi": "Sentetik",
            "gorusme_tarihi": "2026-05-10 11:00:00",
            "not_turu": "Test", "gorusulen": "Senaryo",
            "gorusme_turu": "Genel", "sube": "Test", "sinif": "Test",
            "ogretmen": "Test", "soz_no": TEST_SOZ_NO,
        }],
        "columns": [],
    })
    ok = r.get("synced") and r.get("count", 0) > 0
    print(f"  [{'OK' if ok else 'FAIL'}] counsellor: {r}")
    return ok


async def test_teacher_timetable():
    from eyotek_lazy_sync import lazy_sync_after_query
    r = await lazy_sync_after_query({
        "success": True, "page": "student/timetable-teacher",
        "rows": [{
            "ogretmen_id": "TEST_999",
            "ogretmen_ad": "TestSentetikOgr",
            "brans": "Test", "haftalik_saat": 5,
            "gun": "Pazartesi", "saat": "09:00",
        }],
        "columns": [],
    })
    ok = r.get("synced") and r.get("count", 0) > 0
    print(f"  [{'OK' if ok else 'FAIL'}] teacher_timetable: {r}")
    return ok


async def test_devamsizlik():
    from eyotek_lazy_sync import lazy_sync_after_query
    r = await lazy_sync_after_query({
        "success": True, "page": "student/attendance-summary",
        "rows": [{
            "adi": "TestSentetikDev",
            "sube": "Test", "sinif": "Test",
            "soz_no": TEST_SOZ_NO,
            "okul_no": "999",
        }],
        "columns": [],
    })
    ok = r.get("synced") and r.get("count", 0) > 0
    print(f"  [{'OK' if ok else 'FAIL'}] devamsizlik: {r}")
    return ok


async def test_student_exams():
    """V1 zaten test edildi ama V2 deploy sonrasi tekrar."""
    from eyotek_lazy_sync import lazy_sync_after_query
    r = await lazy_sync_after_query({
        "success": True, "page": "student/exam-result",
        "rows": [{
            "ogrenci_adi": "TestSentetikExam",
            "sinav_adi": "TEST_SINAV_LAZY",
            "tarih": "2026-05-10",
            "turkce": 25.0, "matematik": 18.5, "fizik": 5.0,
            "toplam": 48.5,
            "soz_no": TEST_SOZ_NO,
        }],
        "columns": [],
    })
    ok = r.get("synced") and r.get("count", 0) > 0
    print(f"  [{'OK' if ok else 'FAIL'}] student_exams: {r}")
    return ok


async def main():
    print("═══════════════════════════════════════════════")
    print("25.43-LAZY-EXTEND-V2 smoke (5 upsert tablo)")
    print("═══════════════════════════════════════════════\n")

    print("─── Pre-cleanup ───")
    await cleanup_test_records()
    print("  cleanup done\n")

    print("─── 5 upsert test ───")
    results = []
    results.append(await test_attendance())
    results.append(await test_counsellor())
    results.append(await test_teacher_timetable())
    results.append(await test_devamsizlik())
    results.append(await test_student_exams())

    print("\n─── Post-cleanup ───")
    await cleanup_test_records()
    print("  cleanup done\n")

    pass_count = sum(results)
    print(f"═══════════════════════════════════════════════")
    print(f"TOPLAM: {pass_count}/{len(results)} upsert PASS")
    print(f"═══════════════════════════════════════════════")
    return pass_count == len(results)


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
