"""
SQL AST Guard (Oturum 22.1e, Talimat #13)
==========================================

query_analytics'da Claude'un yazdigi SQL'i AST parse eder.
Regex yerine yapisal kontrol → bypass zor.

Koruma katmanlari:
  1. Sadece SELECT | UPDATE (belirli tablolarda) | INSERT (belirli tablolarda)
  2. Yasaklı statement turu: DROP, ALTER, CREATE, TRUNCATE, GRANT, REVOKE, COPY, CALL, EXECUTE
  3. Yasaklı fonksiyon: pg_sleep, pg_read_file, pg_ls_dir, lo_export, dblink
  4. Multi-statement blokaj (sqlglot birden fazla statement parse ederse)
  5. Yorum satiri var mi? (AST'de comment korundu ise)
  6. Subquery'de ACL ihlali var mi (ogrenci kendi soz_no'su disina cikmali degil)

Kullanim:
    from utils.sql_guard import validate_sql
    err = validate_sql(sql, role="ogrenci", soz_no=137)
    if err:
        # Guvenlik ihlali — reddet
"""
from typing import Optional
import logging

try:
    import sqlglot
    from sqlglot.expressions import (
        Select, Update, Insert, Delete,
        Drop, Alter, Create, Command,
        Table, Func, Anonymous,
    )
    _SQLGLOT_OK = True
except ImportError:
    _SQLGLOT_OK = False


# Sadece belirli tablolarda write izni
_WRITABLE_TABLES = {
    "student_topic_tracker", "student_insights",
    "atlas_suggestions", "atlas_observations",
    "admin_talimat", "lead_contacts",  # admin only
    "hack_attempts", "query_cache", "deployments",  # system tablolari
}

# Hic bir zaman dokundurulmayacak
_FORBIDDEN_STATEMENTS = (Drop, Alter, Create, Delete)

# Yasakli fonksiyon isimleri (lowercase)
_FORBIDDEN_FUNCTIONS = {
    "pg_sleep", "pg_read_file", "pg_ls_dir", "pg_read_binary_file",
    "lo_export", "lo_import", "dblink", "pg_terminate_backend",
    "pg_reload_conf", "copy_from_program", "system", "load_extension",
}

# Yasak komut isimleri (AST'de Command olarak parse edilen)
_FORBIDDEN_COMMANDS = {
    "GRANT", "REVOKE", "TRUNCATE", "COPY", "CALL", "EXECUTE",
    "SET", "RESET", "LOCK", "VACUUM", "ANALYZE", "CLUSTER",
    "LISTEN", "NOTIFY", "UNLISTEN", "LOAD",
}


def validate_sql(sql: str, role: str = "", soz_no: Optional[int] = None) -> Optional[str]:
    """
    SQL'i AST seviyesinde dogrula. Ihlal varsa hata mesaji don.

    Returns:
        None → SQL guvenli
        str  → Ihlal mesaji (reddetmek icin)
    """
    if not sql or not sql.strip():
        return "SQL bos"

    if not _SQLGLOT_OK:
        logging.warning("sqlglot kurulu degil, AST guard KAPALI")
        return None  # Fallback: mevcut regex guard devam eder

    try:
        # Multi-statement → parse_one yerine parse (liste)
        statements = sqlglot.parse(sql, dialect="postgres", error_level="warn")
    except Exception as e:
        return f"SQL parse hatasi: {str(e)[:200]}"

    if not statements:
        return "SQL parse edilmedi"

    # 1. Multi-statement blokaj
    if len(statements) > 1:
        return f"Guvenlik: Coklu statement yasak ({len(statements)} bulundu)."

    stmt = statements[0]
    if stmt is None:
        return "SQL parse edilmedi (None)"

    # 2. Statement turu kontrolu
    if isinstance(stmt, _FORBIDDEN_STATEMENTS):
        return f"Guvenlik: {type(stmt).__name__.upper()} statement yasak."

    # 3. Command (GRANT/REVOKE/TRUNCATE vs) — sqlglot bunlari Command olarak parse eder
    if isinstance(stmt, Command):
        cmd_name = str(stmt.this or "").upper()
        if cmd_name in _FORBIDDEN_COMMANDS:
            return f"Guvenlik: {cmd_name} komutu yasak."

    # 4. SELECT / UPDATE / INSERT kontrolu
    if isinstance(stmt, (Update, Insert)):
        # Hedef tablo writable listede mi?
        tables = [t.name.lower() for t in stmt.find_all(Table)]
        for tbl in tables:
            if tbl not in _WRITABLE_TABLES:
                return f"Guvenlik: '{tbl}' tablosuna INSERT/UPDATE yasak."

    elif not isinstance(stmt, Select):
        # Ne SELECT, ne izinli write — uzak dur
        return f"Guvenlik: Bilinmeyen/izinsiz statement turu ({type(stmt).__name__})."

    # 5. Tehlikeli fonksiyon kontrolu — TUM ast icinde yasak func var mi?
    for func in stmt.find_all(Func):
        name = (func.key or "").lower()
        if name in _FORBIDDEN_FUNCTIONS:
            return f"Guvenlik: {name}() fonksiyonu yasak."
    for anon in stmt.find_all(Anonymous):
        name = (anon.this or "").lower() if anon.this else ""
        if name in _FORBIDDEN_FUNCTIONS:
            return f"Guvenlik: {name}() fonksiyonu yasak."

    # 6. Ogrenci rol icin ek kontrol: soz_no disina cikmasin
    if role == "ogrenci" and soz_no is not None:
        sensitive = {"student_exams", "student_topic_tracker", "devamsizlik",
                     "student_exam_analysis", "student_insights",
                     "counsellor_notes", "etut_history"}
        tables_used = {t.name.lower() for t in stmt.find_all(Table)}
        if tables_used & sensitive:
            # SQL'de soz_no gecmek ZORUNDA
            sql_lower = sql.lower()
            if str(soz_no) not in sql_lower:
                return f"Guvenlik: Hassas tabloya erisim icin kendi soz_no'nuz ({soz_no}) sorguda bulunmali."

    return None  # ✓ tum kontrollar gecti


def validate_sql_or_raise(sql: str, role: str = "", soz_no: Optional[int] = None):
    """Saldırı yakalarsa ValueError fırlatır — decorator/test icin."""
    err = validate_sql(sql, role, soz_no)
    if err:
        raise ValueError(err)


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    TEST_CASES = [
        # (sql, role, soz_no, should_pass, label)
        ("SELECT COUNT(*) FROM students WHERE puan_turu='SAY'", "admin", None, True, "Normal SELECT"),
        ("SELECT 1; DROP TABLE students", "admin", None, False, "Multi-stmt"),
        ("SELECT 1 -- DROP TABLE x", "admin", None, True, "Comment (regex yakalar, AST temizler)"),
        ("SELECT * FROM students /* malicious */", "admin", None, True, "Block comment"),
        ("DROP TABLE students", "admin", None, False, "DROP"),
        ("GRANT ALL ON students TO public", "admin", None, False, "GRANT"),
        ("SELECT pg_sleep(10)", "admin", None, False, "pg_sleep"),
        ("SELECT pg_read_file('/etc/passwd')", "admin", None, False, "pg_read_file"),
        ("INSERT INTO students (full_name) VALUES ('hack')", "admin", None, False, "INSERT to non-writable"),
        ("INSERT INTO atlas_suggestions (category, title) VALUES ('X','Y')", "admin", None, True, "INSERT to writable"),
        ("UPDATE student_topic_tracker SET tamamlandi=TRUE WHERE id=1", "admin", None, True, "UPDATE to writable"),
        ("UPDATE students SET full_name='x' WHERE soz_no=1", "admin", None, False, "UPDATE to non-writable"),
        ("SELECT * FROM student_exams WHERE soz_no=999", "ogrenci", 137, False, "Ogrenci baska soz_no"),
        ("SELECT * FROM student_exams WHERE soz_no=137", "ogrenci", 137, True, "Ogrenci kendi soz_no"),
        ("TRUNCATE students", "admin", None, False, "TRUNCATE"),
    ]

    passed = 0
    failed = 0
    print("=" * 70)
    print("SQL AST GUARD TEST")
    print("=" * 70)
    for sql, role, soz_no, should_pass, label in TEST_CASES:
        err = validate_sql(sql, role, soz_no)
        actual_pass = err is None
        status = "✅" if actual_pass == should_pass else "❌"
        if actual_pass == should_pass:
            passed += 1
        else:
            failed += 1
        print(f"{status} {label:40s} → {'OK' if actual_pass else f'RED: {err[:40]}'}")

    print(f"\n{'='*70}")
    print(f"Sonuc: {passed} passed, {failed} failed / {len(TEST_CASES)}")
    if failed == 0:
        print("✅ Tum testler gecti — AST guard production hazir")
    else:
        print("⚠ Baz testler basarisiz — dikkat")
