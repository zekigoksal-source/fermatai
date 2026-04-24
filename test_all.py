# FermatAI Sistem Testi
# Calistir: python test_all.py
# Calisma dizini: FermatAI klasoru
import asyncio
import os
import sys
import pathlib
from datetime import date, timedelta

# Modül yollarını ekle
_here = pathlib.Path(__file__).parent
sys.path.insert(0, str(_here / "eyotek_agent"))

from dotenv import load_dotenv
load_dotenv(_here / "eyotek_agent" / ".env")

import asyncpg

DATABASE_URL = os.getenv("DATABASE_URL", "")

OK   = "✅"
FAIL = "❌"
WARN = "⚠️ "

results = []

def chk(label, ok, detail=""):
    icon = OK if ok else FAIL
    results.append((ok, label, detail))
    print(f"  {icon} {label}" + (f"  →  {detail}" if detail else ""))

async def main():
    print("\n" + "=" * 60)
    print("🧪 FermatAI Sistem Testi")
    print("=" * 60)

    # ── 1. DB BAĞLANTISI ────────────────────────────────────────────
    print("\n📦 1. Veritabanı Bağlantısı")
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        version = await conn.fetchval("SELECT version()")
        chk("PostgreSQL bağlantısı", True, version[:40])
    except Exception as e:
        chk("PostgreSQL bağlantısı", False, str(e)[:80])
        print("\n❌ DB bağlantısı kurulamadı — diğer testler atlanıyor.")
        return

    # ── 2. ÖĞRENCİ TABLOSU ──────────────────────────────────────────
    print("\n👨‍🎓 2. Öğrenci Tablosu")
    try:
        cnt = await conn.fetchval("SELECT COUNT(*) FROM students")
        chk("Öğrenci sayısı", cnt >= 125, f"{cnt} kayıt (≥125 olmalı)")

        ali = await conn.fetchrow(
            "SELECT eyotek_id, full_name, soz_no FROM students WHERE soz_no = '167'"
        )
        chk("ALİ KÜÇÜKUYSAL (soz_no=167)", ali is not None,
            ali["full_name"] if ali else "BULUNAMADI")

        # Türkçe ILIKE testi
        ali2 = await conn.fetchrow(
            "SELECT full_name FROM students WHERE full_name ILIKE '%KÜÇÜKUYSAL%' OR full_name ILIKE '%KUCUKUYSAL%'"
        )
        chk("Türkçe ILIKE arama (KÜÇÜKUYSAL)", ali2 is not None,
            ali2["full_name"] if ali2 else "BULUNAMADI")
    except Exception as e:
        chk("Öğrenci tablosu", False, str(e)[:80])

    # ── 3. PERSONEL TABLOSU ─────────────────────────────────────────
    print("\n👔 3. Personel Tablosu")
    try:
        staff_cnt = await conn.fetchval("SELECT COUNT(*) FROM staff")
        chk("Staff tablosu var", staff_cnt is not None, f"{staff_cnt} kayıt")
        chk("Personel sayısı yeterli", (staff_cnt or 0) >= 18, f"{staff_cnt} kayıt (≥18 olmalı)")

        zeki = await conn.fetchrow(
            "SELECT eyotek_id, full_name, brans FROM staff WHERE eyotek_id = '1035'"
        )
        chk("ZEKİ GÖKSAL (eyotek_id=1035)", zeki is not None,
            zeki["full_name"] if zeki else "BULUNAMADI — import_staff.py çalıştır!")

        fizik = await conn.fetch(
            "SELECT full_name FROM staff WHERE brans ILIKE '%fizik%'"
        )
        chk("Fizik öğretmeni var", len(fizik) > 0,
            ", ".join(r["full_name"] for r in fizik) or "YOK")
    except Exception as e:
        chk("Personel tablosu", False, str(e)[:80])

    # ── 4. ACL TABLOSU ──────────────────────────────────────────────
    print("\n🔐 4. ACL Tablosu")
    try:
        acl_cnt = await conn.fetchval("SELECT COUNT(*) FROM acl_users")
        chk("acl_users tablosu var", acl_cnt is not None, f"{acl_cnt} kayıt")
        if (acl_cnt or 0) == 0:
            print(f"    {WARN} add_admin.py çalıştırılmadı — WhatsApp'tan gelen komutlar 'guest' rolüyle çalışır")
    except Exception as e:
        chk("acl_users tablosu", False, str(e)[:80])

    # ── 5. EYOTEK SESSION ───────────────────────────────────────────
    print("\n🍪 5. Eyotek Session")
    session_file = _here / "eyotek_agent" / ".eyotek_session.json"
    chk("Session dosyası var", session_file.exists(), str(session_file))
    if session_file.exists():
        import json
        try:
            cookies = json.loads(session_file.read_text(encoding="utf-8"))
            chk("Session içeriği geçerli", isinstance(cookies, list) and len(cookies) > 0,
                f"{len(cookies)} cookie")
        except Exception as e:
            chk("Session JSON parse", False, str(e)[:60])

    # ── 6. IMPORT DOSYALARI ─────────────────────────────────────────
    print("\n📁 6. Import/Export Dosyaları")
    for fname in ["students_export.json", "staff_export.json",
                  "import_students.py", "import_staff.py",
                  "cleanup_db.py", "add_admin.py"]:
        p = _here / fname
        chk(fname, p.exists(), "var" if p.exists() else "EKSİK")

    # ── 7. WRITE_ETUT DRY-RUN SİMÜLASYONU ──────────────────────────
    print("\n✏️  7. write_etut Parametre Kontrolü (dry-run simülasyon)")
    try:
        from fermat_core_agent import tool_search_students
        result = await tool_search_students("Ali Küçükuysal")
        found = result.get("count", 0) > 0
        chk("search_students('Ali Küçükuysal')", found,
            result["results"][0]["full_name"] if found else "BULUNAMADI")

        if found:
            student = result["results"][0]
            tomorrow = (date.today() + timedelta(days=1)).strftime("%d.%m.%Y")
            print(f"\n    📋 write_etut parametreleri (dry-run):")
            print(f"       student_id_or_name : {student['full_name']}")
            print(f"       class_name         : {student.get('class_name') or student.get('sube') or '(boş — adla aranacak)'}")
            print(f"       lesson             : Fizik")
            print(f"       target_date        : {tomorrow}")
            print(f"       ders_no            : 5  (12:00-12:35)")
            print(f"       etut_type          : Etüt")
            print(f"       dry_run            : True  ← GERÇEK YAZMA YOK")
    except ImportError as e:
        chk("fermat_core_agent import", False, f"eyotek_agent klasöründen çalıştırın: {e}")
    except Exception as e:
        chk("write_etut parametre kontrolü", False, str(e)[:80])

    await conn.close()

    # ── ÖZET ────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    passed = sum(1 for ok, *_ in results if ok)
    total  = len(results)
    print(f"📊 Sonuç: {passed}/{total} test geçti")
    if passed == total:
        print("🎉 Tüm testler geçti! Sistem hazır.")
    else:
        print("⚠️  Bazı testler başarısız — yukarıdaki detaylara bakın.")
        failed = [label for ok, label, _ in results if not ok]
        print("   Başarısız: " + ", ".join(failed))

    print("\n🚀 write_etut canlı dry-run için:")
    print("   cd eyotek_agent")
    print('   python fermat_core_agent.py "Ali Küçükuysal için yarın saat 12:00\'da fizik etüt yaz"')
    print("=" * 60)

asyncio.run(main())
