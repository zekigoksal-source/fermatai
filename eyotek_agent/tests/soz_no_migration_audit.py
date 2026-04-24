"""
soz_no Schema Migration — Pre-Migration Audit
==============================================

Tum tablolar integer'a migrate edilmeden ONCE:
1. Her tablodaki soz_no tipini ve kayit sayisini listele
2. text olanlarda integer-parse edilebilmeyen deger var mi
3. Foreign key constraint'ler var mi (cascade riski)
4. Primary key / unique / index durumu
5. Dashboard endpoint'lerine etki edecek baska ::text cast'ler

Hata tespit edersen → migration DURMALI.
"""
import sys, io, os, asyncio
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(override=True)


# Mevcut durum
KNOWN_TABLES = [
    "students",
    "student_exams",
    "student_exam_analysis",
    "student_topic_tracker",
    "devamsizlik_sayisi",
    "student_insights",
    "counsellor_notes",
]


async def main():
    import asyncpg
    conn = await asyncpg.connect(os.getenv("DATABASE_URL"))
    try:
        print("=" * 70)
        print("soz_no MIGRATION AUDIT")
        print("=" * 70)

        # Ek tablolar ekle — soz_no kolonu olan her tabloyu tara
        all_tables = await conn.fetch(
            """SELECT DISTINCT table_schema, table_name FROM information_schema.columns
               WHERE column_name = 'soz_no' AND table_schema NOT IN ('pg_catalog','information_schema')
               ORDER BY table_schema, table_name"""
        )
        all_table_names = [f"{r['table_schema']}.{r['table_name']}" for r in all_tables]
        print(f"\nsoz_no kolonu iceren {len(all_table_names)} tablo bulundu:")
        for t in all_table_names:
            print(f"  {t}")

        # 1) Tip + kayit sayisi
        print("\n\n📊 TABLO BAZLI TIP + KAYIT SAYISI")
        print("-" * 70)
        type_map = {}
        for tbl in all_table_names:
            schema, name = tbl.split(".")
            col = await conn.fetchrow(
                "SELECT data_type FROM information_schema.columns WHERE table_schema=$1 AND table_name=$2 AND column_name='soz_no'",
                schema, name
            )
            cnt = await conn.fetchval(f'SELECT COUNT(*) FROM "{schema}"."{name}"')
            nnull = await conn.fetchval(f'SELECT COUNT(*) FROM "{schema}"."{name}" WHERE soz_no IS NOT NULL')
            type_map[tbl] = col["data_type"]
            print(f"  {tbl:45s} {col['data_type']:10s} toplam={cnt:>6}, soz_no dolu={nnull}")

        # 2) text olanlarda integer-parse kontrolu
        print("\n\n🔍 TEXT KOLONLARDA HATALI DEGERLER")
        print("-" * 70)
        text_tables = [t for t, typ in type_map.items() if typ == "text"]
        issues = []
        for tbl in text_tables:
            schema, name = tbl.split(".")
            bad = await conn.fetch(
                f'SELECT soz_no, COUNT(*) as sayi FROM "{schema}"."{name}" '
                f"WHERE soz_no IS NOT NULL AND soz_no !~ '^[0-9]+$' "
                f"GROUP BY soz_no ORDER BY sayi DESC LIMIT 5"
            )
            if bad:
                issues.append((tbl, bad))
                print(f"  ⚠ {tbl}: {len(bad)} hatali deger ornegi:")
                for b in bad:
                    print(f"    '{b['soz_no']}' × {b['sayi']}")
            else:
                print(f"  ✅ {tbl}: tum degerler integer-parse edilebilir")

        # 3) Foreign key'ler
        print("\n\n🔗 FOREIGN KEY CONSTRAINT'LER")
        print("-" * 70)
        fks = await conn.fetch("""
            SELECT tc.table_name, kcu.column_name, ccu.table_name AS foreign_table, ccu.column_name AS foreign_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = tc.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND (kcu.column_name = 'soz_no' OR ccu.column_name = 'soz_no')
        """)
        if fks:
            for f in fks:
                print(f"  ⚠ {f['table_name']}.{f['column_name']} → {f['foreign_table']}.{f['foreign_column']}")
            print("  (Migration'dan ONCE FK drop + sonra yeniden olustur gerekebilir)")
        else:
            print("  ✅ soz_no icin FK constraint YOK — migration serbest")

        # 4) PK / index
        print("\n\n🔑 PRIMARY KEY + INDEX DURUMU")
        print("-" * 70)
        for tbl in all_table_names:
            pk = await conn.fetchrow("""
                SELECT a.attname, i.indisprimary, i.indisunique
                FROM pg_index i
                JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                WHERE i.indrelid = $1::regclass AND a.attname = 'soz_no'
                LIMIT 1
            """, f'"{tbl.split(".")[0]}"."{tbl.split(".")[1]}"')
            if pk:
                info = "PK" if pk["indisprimary"] else ("UNIQUE" if pk["indisunique"] else "INDEX")
                print(f"  {tbl:30s} soz_no → {info}")

        # 5) Kod icinde mevcut '::text' cast'ler (grep olarak)
        print("\n\n📝 MIGRATION SONRASI KOD TEMIZLIGI ONERISI")
        print("-" * 70)
        print("  (asagidaki cast pattern'lar artik gereksiz:)")
        print("  - s.soz_no::text")
        print("  - s.soz_no = $1  (eger $1 str degil int geciyorsa OK)")
        print("  Kod icinde manuel str(soz_no) → int(soz_no) donusumleri de gozden gecir.")

        # SUMMARY
        print("\n\n" + "=" * 70)
        print("ÖZET")
        print("=" * 70)
        text_count = len([t for t in type_map.values() if t == "text"])
        int_count = len([t for t in type_map.values() if t == "integer"])
        print(f"  text tablo:     {text_count}")
        print(f"  integer tablo:  {int_count}")
        print(f"  hatali deger:   {len(issues)} tabloda")
        print(f"  FK constraint:  {len(fks)}")

        if issues:
            print("\n  ⛔ HATALI DEGERLER VAR — migration'dan ONCE temizlenmeli")
            return 1
        if fks:
            print("\n  ⚠  FK var — dikkat, ek dropconstraint gerekli")
            return 2

        print("\n  ✅ MIGRATION HAZIR — veri uyumlu, FK yok")
        return 0

    finally:
        await conn.close()


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
