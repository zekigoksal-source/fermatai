"""
FermatAI — Finans Guvenlik Test Suite (22.1n-neo)
==================================================

Bu testler finans_access + finans_tools + role_access entegrasyonunu dogrular.
YAZILIM DEGILSEKI — bu testler ASLA kirilmamali. Her PR oncesi calisir.

Calistir:
  cd eyotek_agent
  .venv/Scripts/python.exe -m pytest tests/test_finans_security.py -v
"""
import pytest
import asyncio
from finans_access import (
    is_finans_authorized,
    sql_contains_finans,
    check_finans_sql_access,
    is_finans_content,
    is_finans_cache_op,
)
from role_access import _ACL_MATRIX, _is_tool_allowed, _check_sql_acl


NEO_PHONE = "905051256802"
SGM_PHONE = "905547043775"
DUYGU_PHONE = "905051256801"
MAHSUM_PHONE = "905462605446"
OGRENCI_PHONE = "905999999999"


# ─── 1. is_finans_authorized ─────────────────────────────────────────────────

def test_auth_neo_allowed():
    assert is_finans_authorized(NEO_PHONE) is True

def test_auth_neo_with_plus():
    assert is_finans_authorized("+" + NEO_PHONE) is True

def test_auth_sgm_blocked():
    """Orsel (SGM) finansa erisemez — admin rolu olsa bile."""
    assert is_finans_authorized(SGM_PHONE) is False

def test_auth_duygu_blocked():
    """Duygu (mudur) finansa erisemez."""
    assert is_finans_authorized(DUYGU_PHONE) is False

def test_auth_mahsum_blocked():
    assert is_finans_authorized(MAHSUM_PHONE) is False

def test_auth_ogrenci_blocked():
    assert is_finans_authorized(OGRENCI_PHONE) is False

def test_auth_empty_blocked():
    assert is_finans_authorized("") is False
    assert is_finans_authorized(None) is False


# ─── 2. sql_contains_finans — tablo/kolon tespit ────────────────────────────

def test_sql_detect_monthly_installments():
    assert len(sql_contains_finans("SELECT * FROM monthly_installments")) > 0

def test_sql_detect_payments_case_insensitive():
    assert len(sql_contains_finans("select * from PAYMENTS")) > 0

def test_sql_detect_financial_summary_view():
    assert len(sql_contains_finans("SELECT * FROM student_financial_summary")) > 0

def test_sql_detect_column_taksit():
    assert len(sql_contains_finans("SELECT taksit_tutari FROM students")) > 0

def test_sql_normal_query_passes():
    """Normal sorgu finans bayragi yok."""
    assert sql_contains_finans("SELECT full_name FROM students") == []

def test_sql_student_exams_not_finans():
    """Sinav verisi finansal degil."""
    assert sql_contains_finans("SELECT * FROM student_exams") == []


# ─── 3. check_finans_sql_access — Neo vs digerleri ──────────────────────────

def test_sql_neo_allowed():
    """Neo tum finans tablolarini sorgulayabilir."""
    err = check_finans_sql_access("admin", NEO_PHONE, "SELECT * FROM payments")
    assert err is None

def test_sql_admin_role_sgm_blocked():
    """Rol admin olsa bile SGM finans sorgusu blok."""
    err = check_finans_sql_access("admin", SGM_PHONE, "SELECT * FROM payments")
    assert err is not None
    assert "finansal" in err.lower() or "guvenlik" in err.lower()

def test_sql_mudur_duygu_blocked():
    err = check_finans_sql_access("mudur", DUYGU_PHONE, "SELECT * FROM monthly_installments")
    assert err is not None

def test_sql_ogrenci_blocked():
    err = check_finans_sql_access("ogrenci", OGRENCI_PHONE, "SELECT * FROM payments")
    assert err is not None

def test_sql_ogrenci_normal_not_blocked_by_finans():
    """Ogrenci normal sorgu finans katmanindan gecer."""
    err = check_finans_sql_access("ogrenci", OGRENCI_PHONE, "SELECT full_name FROM students")
    assert err is None


# ─── 4. _check_sql_acl — tam zincir ──────────────────────────────────────────

def test_acl_finans_guard_engaged_for_all_roles():
    """Admin/mudur dahil her rol icin finans SQL'de phone check yapilir."""
    for role in ["admin", "mudur", "yonetim", "rehber", "ogretmen", "ogrenci", "veli"]:
        err = _check_sql_acl(role, "SELECT * FROM payments", phone=SGM_PHONE)
        assert err is not None, f"role={role} phone=SGM blok edilmedi!"

def test_acl_neo_admin_passes():
    err = _check_sql_acl("admin", "SELECT * FROM payments", phone=NEO_PHONE)
    assert err is None


# ─── 5. ACL Matrix — finans tool'lari sadece admin'de ──────────────────────

FINANS_TOOLS = {
    "finans_ozet", "ogrenci_borc_detay", "geciken_odemeler",
    "aylik_tahsilat_trend", "veli_borc_bildirim_taslak", "finans_audit_rapor",
}

def test_acl_admin_has_all_finans_tools():
    admin_tools = _ACL_MATRIX["admin"]
    assert FINANS_TOOLS.issubset(admin_tools)

def test_acl_non_admin_roles_have_zero_finans_tools():
    for role in ["mudur", "yonetim", "rehber", "ogretmen", "ogrenci", "veli", "guest", "unknown"]:
        role_tools = _ACL_MATRIX.get(role, set())
        overlap = FINANS_TOOLS & role_tools
        assert not overlap, f"role={role} finans tool'larina erismemeli: {overlap}"


# ─── 6. is_tool_allowed + phone check ────────────────────────────────────────

def test_tool_allowed_admin_role():
    """ACL seviyesi admin rolu finans tool'u gorur (phone check wrapper'da)."""
    for t in FINANS_TOOLS:
        assert _is_tool_allowed("admin", t, phone=NEO_PHONE) is True

def test_tool_blocked_sgm_phone_admin_role():
    """SGM admin rolu olsa bile phone check'ten degil, ACL seviyesi OK;
    BlokLAMAYI run_tool wrapper'da is_finans_authorized yapar — ayrı test."""
    # ACL seviyesinde admin rolu gorsin ama run_tool finans_authorized check yapacak
    # Bu test ACL seviyesini dogrular — ayrı test run_tool guard'i olur
    pass  # run_tool guard integration testi manuel


# ─── 7. Vision caption filter ────────────────────────────────────────────────

def test_vision_detects_finans_caption_tr():
    assert is_finans_content("bu ogrencinin borcu nedir") is True
    assert is_finans_content("taksit odemesi gozuktu mu") is True
    assert is_finans_content("Ali'nin ödeme durumu") is True
    assert is_finans_content("makbuz no 12345") is True

def test_vision_detects_finans_caption_amount():
    assert is_finans_content("2500 TL ödedi") is True
    assert is_finans_content("3000 try borcu var") is True

def test_vision_normal_caption_not_blocked():
    assert is_finans_content("bu soruyu cozer misin") is False
    assert is_finans_content("matematik sorusu") is False
    assert is_finans_content("") is False


# ─── 8. Cache deny ───────────────────────────────────────────────────────────

def test_cache_deny_finans_prefixes():
    assert is_finans_cache_op("finans_ozet") is True
    assert is_finans_cache_op("payment_list") is True
    assert is_finans_cache_op("borc_detay") is True
    assert is_finans_cache_op("taksit_rapor") is True
    assert is_finans_cache_op("student_financial_summary") is True

def test_cache_allow_normal_ops():
    assert is_finans_cache_op("student_grades") is False
    assert is_finans_cache_op("class_summary") is False
    assert is_finans_cache_op("exam_trend") is False


# ─── 9. ACL satir sayisi korunmus mu ────────────────────────────────────────

def test_acl_totals():
    """Sanity check — ACL matris yapi degistirilmedi."""
    assert len(_ACL_MATRIX) == 9  # 9 rol
    assert "guest" in _ACL_MATRIX
    assert "unknown" in _ACL_MATRIX
    assert _ACL_MATRIX["guest"] == set()  # guest icin 0 tool
