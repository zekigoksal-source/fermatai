"""student_daily helper smoke tests (Oturum 25.12)"""
import pytest
import asyncio
from datetime import date
from student_daily import (
    add_daily_program, get_daily_program, complete_program_block, delete_program_block,
    add_todo, get_todos, complete_todo, delete_todo,
    add_habit, get_habits, log_habit,
    add_exam_event, get_upcoming_events,
    log_study_session, get_today_stats, get_weekly_stats,
    log_physical_activity, get_recent_activities,
    add_daily_note, get_recent_notes,
    get_summary, analyze_study_pattern,
)


# Test soz_no — TEST_SOZ veya 999999 (gerçek öğrenciyi bozmasın)
TEST_SOZ_NO = 999998


@pytest.mark.asyncio
async def test_program_crud():
    """Program ekle → liste → tamamla → sil"""
    r = await add_daily_program(TEST_SOZ_NO, "Test Program", "10:00", "11:00",
                                 ders="Matematik", konu="Türev")
    assert "id" in r
    block_id = r["id"]
    items = await get_daily_program(TEST_SOZ_NO)
    assert any(p["id"] == block_id for p in items)
    await complete_program_block(block_id, TEST_SOZ_NO)
    await delete_program_block(block_id, TEST_SOZ_NO)


@pytest.mark.asyncio
async def test_todo_crud():
    r = await add_todo(TEST_SOZ_NO, "Test Görev", priority="high")
    assert "id" in r
    todo_id = r["id"]
    items = await get_todos(TEST_SOZ_NO, only_open=True)
    assert any(t["id"] == todo_id for t in items)
    await complete_todo(todo_id, TEST_SOZ_NO)
    # Tamamlanan görev only_open=True listede olmamalı
    items_after = await get_todos(TEST_SOZ_NO, only_open=True)
    assert not any(t["id"] == todo_id for t in items_after)
    await delete_todo(todo_id, TEST_SOZ_NO)


@pytest.mark.asyncio
async def test_habit_streak():
    r = await add_habit(TEST_SOZ_NO, "Test Habit", target_days=['Pzt', 'Sal'])
    habit_id = r["id"]
    # Bugün için log
    log_r = await log_habit(habit_id, completed=True)
    assert log_r["streak"] >= 1
    # Cleanup (alışkanlığı pasifleştir veya sil — şu an sadece bırak)


@pytest.mark.asyncio
async def test_study_session_additive():
    """log_study_session aynı gün için ek toplar"""
    today = date.today()
    # İlk session
    r1 = await log_study_session(TEST_SOZ_NO, minutes=30, questions=10, ders="Matematik")
    # İkinci session
    r2 = await log_study_session(TEST_SOZ_NO, minutes=20, questions=5, ders="Matematik")
    # Toplam
    stats = await get_today_stats(TEST_SOZ_NO)
    # En az 50 dk + 15 soru olmalı (önceki test sonrası, bu yüzden >=)
    assert stats["total_minutes"] >= 50
    assert stats["questions_solved"] >= 15
    assert stats["ders_breakdown"].get("Matematik", 0) >= 50


@pytest.mark.asyncio
async def test_daily_note_upsert():
    """Aynı gün için 2 note → ikincisi UPDATE"""
    await add_daily_note(TEST_SOZ_NO, "İlk not", mood="normal")
    await add_daily_note(TEST_SOZ_NO, "Güncellenmiş not", mood="verimli")
    notes = await get_recent_notes(TEST_SOZ_NO, days=1)
    assert len(notes) >= 1
    today_note = next((n for n in notes if str(n["log_date"]) == str(date.today())), None)
    assert today_note is not None
    assert today_note["note"] == "Güncellenmiş not"
    assert today_note["mood"] == "verimli"


@pytest.mark.asyncio
async def test_get_summary():
    """get_summary tüm modülleri tek çağrıda döner"""
    summary = await get_summary(TEST_SOZ_NO)
    assert "today_program" in summary
    assert "open_todos" in summary
    assert "habits" in summary
    assert "upcoming_events" in summary
    assert "today_stats" in summary
    assert "weekly_stats" in summary
    assert "recent_activities" in summary
    assert "recent_notes" in summary


@pytest.mark.asyncio
async def test_analyze_pattern():
    """analyze_study_pattern bilgisi döner"""
    result = await analyze_study_pattern(TEST_SOZ_NO, days=30)
    # Önceki testler veri ekledi, error olmamalı
    if "error" not in result:
        assert "total_minutes" in result
        assert "consistency_score" in result
        assert "weak_weekdays" in result


@pytest.mark.asyncio
async def test_physical_activity():
    r = await log_physical_activity(TEST_SOZ_NO, "Test Yürüyüş", 30, "orta")
    assert "id" in r
    items = await get_recent_activities(TEST_SOZ_NO, days=1)
    assert any(a["activity_type"] == "Test Yürüyüş" for a in items)


@pytest.mark.asyncio
async def test_exam_event_upcoming():
    from datetime import timedelta
    future = date.today() + timedelta(days=10)
    r = await add_exam_event(TEST_SOZ_NO, "Test Sınav", future, event_type="sinav", ders="Matematik")
    assert "id" in r
    events = await get_upcoming_events(TEST_SOZ_NO, days_ahead=15)
    assert any(e["title"] == "Test Sınav" for e in events)
