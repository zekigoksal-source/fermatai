"""
AYT tutarlilik testleri.
  - query_analytics SQL guard
  - ogrenci_ayt_deneme canli DB (student_exam_analysis kaynakli)
  - Prompt'ta yasak filter'in var oldugu
"""
import pytest
from pathlib import Path

pytestmark = pytest.mark.ayt


# ─── 1) SQL GUARD — DB gerektirmez ────────────────────────────────────

async def test_ayt_guard_blocks_student_exams_ayt_query():
    """student_exams + [AYT] kombinasyonu query_analytics'te engellenmelidir."""
    from fermat_core_agent import tool_query_analytics
    r = await tool_query_analytics(
        "SELECT * FROM student_exams WHERE exam_name LIKE '[AYT]%' LIMIT 1",
        explanation="test",
        _caller_role="admin",
    )
    assert r.get("success") is False
    err = r.get("error", "")
    assert "YANILTICI VERI KORUMASI" in err
    assert "get_ayt_analysis" in err


async def test_ayt_guard_allows_tyt_query():
    """TYT filtresi (NOT LIKE [AYT]%) serbest olmali."""
    from fermat_core_agent import tool_query_analytics
    r = await tool_query_analytics(
        "SELECT COUNT(*) as cnt FROM student_exams WHERE exam_name NOT LIKE '[AYT]%'",
        explanation="test tyt",
        _caller_role="admin",
    )
    # TYT sorgusu gecmeli (hem [AYT] hem LIKE yok -> guard pass)
    # Not: SQL CNT ilk sutuna aktarilir
    # Bu testte 'success'=True olabilir veya DB yoksa error gelebilir
    err = r.get("error", "") or ""
    assert "YANILTICI" not in err


async def test_ayt_guard_allows_student_exam_analysis():
    """student_exam_analysis (doğru tablo) serbest olmali."""
    from fermat_core_agent import tool_query_analytics
    r = await tool_query_analytics(
        "SELECT COUNT(*) FROM student_exam_analysis WHERE ham_puan_ayt IS NOT NULL",
        explanation="test",
        _caller_role="admin",
    )
    err = r.get("error", "") or ""
    assert "YANILTICI" not in err


# ─── 2) PROMPT KURAL VARLIGI ──────────────────────────────────────────

def test_prompt_has_ayt_warning():
    """Prompt'ta AYT student_exams kullanim uyarisi olmali."""
    path = Path(__file__).parent.parent / "fermat_core_agent.py"
    content = path.read_text(encoding="utf-8")
    # KRITIK uyari
    assert "TYT NETLERININ KOPYASI" in content or "YANILTICI" in content
    assert "get_ayt_analysis" in content


def test_no_forbidden_ayt_like_pattern_in_prompt():
    """Prompt, 'WHERE exam_name LIKE [AYT]%' onerisi ICERMEMELI (Claude'a bu yonlendirme yasak)."""
    path = Path(__file__).parent.parent / "fermat_core_agent.py"
    content = path.read_text(encoding="utf-8")
    # Prompt icinde olmamali (comment veya guard mesaji dışında)
    lines = content.split("\n")
    for i, line in enumerate(lines):
        # Sadece tool description string'lerinde ara
        if "Ogrenci AYT sordugunda" in line and "LIKE '[AYT]%'" in line:
            pytest.fail(f"Satir {i+1}: AYT icin LIKE filter tavsiyesi hala var!")


# ─── 3) CANLI DB TESTI — ogrenci_ayt_deneme ───────────────────────────

@pytest.mark.db
async def test_ogrenci_ayt_deneme_real_student():
    """Gercek bir AYT verisi olan ogrenci icin dogru cevap."""
    from fast_responses import ogrenci_ayt_deneme, _get_pool

    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT sea.soz_no::int AS soz_no, s.full_name "
            "FROM student_exam_analysis sea "
            "LEFT JOIN students s ON s.soz_no::text = sea.soz_no::text "
            "WHERE sea.ham_puan_ayt IS NOT NULL AND sea.ham_puan_ayt != '' LIMIT 1"
        )

    if not row:
        pytest.skip("DB'de AYT verisi olan ogrenci yok")

    resp = await ogrenci_ayt_deneme(int(row["soz_no"]), row["full_name"])
    assert "AYT Birlestir Analizi" in resp
    assert "Resmi Puan" in resp
    assert "Eyotek" not in resp  # Backend platform, kullaniciya gosterilmiyor
    assert "Ham" in resp
    assert "Yerlesme" in resp
    # Yanıltıcı TYT netleri görünmemeli
    assert "AYT Deneme Analizi" not in resp  # eski format


@pytest.mark.db
async def test_ogrenci_ayt_deneme_no_data():
    """AYT verisi OLMAYAN ogrenci icin nazik cevap."""
    from fast_responses import ogrenci_ayt_deneme, _get_pool

    # Olmayan bir soz_no ile — DB sorgu bos doner, nazik mesaj beklenir
    resp = await ogrenci_ayt_deneme(999999, "Test Ogrenci")
    assert "Henuz sisteme yuklu AYT" in resp


# ─── 4) NO REGRESSION — student_exams [AYT] direkt query YOK ──────────

def test_ogrenci_ayt_deneme_does_not_use_student_exams_ayt():
    """ogrenci_ayt_deneme artik student_exams [AYT]% sorgusu YAPMAMALI."""
    path = Path(__file__).parent.parent / "fast_responses.py"
    content = path.read_text(encoding="utf-8")
    # Fonksiyon blokunu izole et
    start = content.index("async def ogrenci_ayt_deneme")
    end = content.index("async def ogrenci_deneme_kiyasla")
    func_body = content[start:end]
    # student_exams + [AYT]% sorgusu OLMAMALI (yorum olarak olabilir ama SQL aktif yok)
    assert "FROM student_exams WHERE" not in func_body, \
        "ogrenci_ayt_deneme artik student_exams kullanmamali!"


def test_conversation_memory_uses_analysis_table():
    """conversation_memory AYT context'i student_exam_analysis kullanmali."""
    path = Path(__file__).parent.parent / "conversation_memory.py"
    content = path.read_text(encoding="utf-8")
    assert "student_exam_analysis" in content,         "conversation_memory student_exam_analysis tablosunu kullanmali!"
    assert "ham_puan_ayt" in content
    assert "ayt_last" in content
    # YASAK: student_exams LIKE [AYT]% (TYT kopyasi). NOT LIKE serbest.
    import re as _re
    assert not _re.search(r"(?<!NOT\s)LIKE\s*'?\[AYT\]", content),         "student_exams [AYT]% sorgusu KULLANILMAMALI (TYT kopyasi)"
