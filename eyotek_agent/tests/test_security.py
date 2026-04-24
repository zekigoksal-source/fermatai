"""
Guvenlik denetim testleri — Oturum 18 white-hacker raporu sonrası.
SQL injection, ACL bypass, phone spoofing, endpoint auth bypass.
"""
import pytest
from fermat_core_agent import _check_sql_acl, _is_tool_allowed


pytestmark = pytest.mark.registry  # Mevcut marker


# ═══════════════════════════════════════════════════════════════════════
# SQL ACL BYPASS — ogrenci kendi dışı veri goremez
# ═══════════════════════════════════════════════════════════════════════

class TestStudentSQLAcl:
    def test_own_data_allowed(self):
        err = _check_sql_acl("ogrenci",
            "SELECT * FROM student_exams WHERE soz_no=137",
            soz_no=137)
        assert err is None

    def test_or_1equals1_blocked(self):
        err = _check_sql_acl("ogrenci",
            "SELECT * FROM student_exams WHERE soz_no=137 OR 1=1",
            soz_no=137)
        assert err is not None
        assert "OR" in err.upper() or "UNION" in err.upper()

    def test_union_attack_blocked(self):
        err = _check_sql_acl("ogrenci",
            "SELECT * FROM student_exams WHERE soz_no=137 UNION SELECT * FROM students",
            soz_no=137)
        assert err is not None

    def test_another_soz_no_blocked(self):
        err = _check_sql_acl("ogrenci",
            "SELECT * FROM student_exams WHERE soz_no=200",
            soz_no=137)
        assert err is not None

    def test_or_another_soz_no_blocked(self):
        """En kritik: soz_no=137 OR soz_no=200 — case-sensitive regex fix"""
        err = _check_sql_acl("ogrenci",
            "SELECT * FROM student_exams WHERE soz_no=137 OR soz_no=200",
            soz_no=137)
        assert err is not None
        assert "200" in err or "başka" in err.lower()

    def test_topic_tracker_own(self):
        err = _check_sql_acl("ogrenci",
            "SELECT * FROM student_topic_tracker WHERE soz_no = 137",
            soz_no=137)
        assert err is None

    def test_sensitive_tables_require_own_soz_no(self):
        """Yeni eklenen tablolar da korumalı olmalı"""
        for tbl in ["STUDENT_EXAM_ANALYSIS", "COUNSELLOR_NOTES", "ETUT_HISTORY"]:
            err = _check_sql_acl("ogrenci",
                f"SELECT * FROM {tbl} WHERE soz_no=200",
                soz_no=137)
            assert err is not None, f"{tbl} başka soz_no'yu engellemiyor"


# ═══════════════════════════════════════════════════════════════════════
# TOOL ACL — SGM (Örsel) yazma engellendi
# ═══════════════════════════════════════════════════════════════════════

class TestSGMToolAcl:
    def test_sgm_cannot_write_etut(self):
        assert not _is_tool_allowed("mudur", "execute_eyotek_action",
                                    action="write_etut",
                                    phone="905547043775")

    def test_sgm_cannot_send_sms(self):
        assert not _is_tool_allowed("mudur", "execute_eyotek_action",
                                    action="send_sms",
                                    phone="905547043775")

    def test_sgm_can_read_analytics(self):
        assert _is_tool_allowed("mudur", "get_student_analytics",
                                phone="905547043775")

    def test_other_mudur_can_write(self):
        """Duygu (mudur, SGM degil) yazabilir"""
        assert _is_tool_allowed("mudur", "execute_eyotek_action",
                                action="write_etut",
                                phone="905051256801")

    def test_admin_always_can_write(self):
        assert _is_tool_allowed("admin", "execute_eyotek_action",
                                action="write_etut",
                                phone="905051256802")


# ═══════════════════════════════════════════════════════════════════════
# STUDENT ACL — ogrenci yazma tool'larına erişemez
# ═══════════════════════════════════════════════════════════════════════

class TestStudentToolAcl:
    def test_ogrenci_cannot_execute_eyotek_action(self):
        assert not _is_tool_allowed("ogrenci", "execute_eyotek_action",
                                    action="write_etut")

    def test_ogrenci_cannot_search_students(self):
        """search_students ogrenci ACL'sinde YOK"""
        assert not _is_tool_allowed("ogrenci", "search_students")

    def test_guest_no_tools(self):
        assert not _is_tool_allowed("guest", "get_student_analytics")
        assert not _is_tool_allowed("guest", "execute_eyotek_action",
                                    action="write_etut")
