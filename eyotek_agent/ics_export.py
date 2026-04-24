"""
Google Calendar / Apple Calendar .ics Export (Oturum 22.1m)
============================================================

Çalışma planını .ics dosyasına çevirir → öğrenci tek tıkla telefon/bilgisayar
takvimine ekler (Google Calendar, Apple, Outlook hepsi destekler).

Format: RFC 5545 iCalendar

Kullanim:
    from ics_export import plan_to_ics
    content = plan_to_ics(plan_data, student_name="Ayşe")
    # content → .ics dosya metni, Content-Type: text/calendar

Plan formati (Claude'un build_study_plan_context ciktisindan):
    [
      {"gun": "Pazartesi", "saat": "19:00", "sure_dk": 60,
       "ders": "Matematik", "konu": "Turev", "yontem": "30 soru coz"},
      ...
    ]
"""
import uuid
from datetime import datetime, timedelta, date, time
from typing import Optional


_GUN_MAP = {
    "Pazartesi": 0, "Salı": 1, "Sali": 1,
    "Çarşamba": 2, "Carsamba": 2,
    "Perşembe": 3, "Persembe": 3,
    "Cuma": 4, "Cumartesi": 5, "Pazar": 6,
}


def _escape(text: str) -> str:
    """iCalendar ozel karakter kacislari."""
    if not text:
        return ""
    return (text.replace("\\", "\\\\")
                .replace(";", "\\;")
                .replace(",", "\\,")
                .replace("\n", "\\n"))


def _fmt_dt(dt: datetime) -> str:
    """YYYYMMDDTHHMMSS format (naive, local time)."""
    return dt.strftime("%Y%m%dT%H%M%S")


def _next_weekday(target_weekday: int, base: Optional[date] = None) -> date:
    """Bugunden sonraki belirtilen gunu bul. target_weekday: 0=Pazartesi."""
    if base is None:
        base = date.today()
    days_ahead = (target_weekday - base.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7  # bugun ise gelecek haftaya al
    return base + timedelta(days=days_ahead)


def plan_to_ics(plan: list[dict], student_name: str = "", weeks: int = 4) -> str:
    """
    Çalışma planını .ics'ye çevir. Varsayılan 4 hafta tekrar eden RRULE.

    Args:
        plan: Liste of {"gun", "saat" (HH:MM), "sure_dk", "ders", "konu", "yontem"}
        student_name: Takvim sahibi
        weeks: Kaç hafta tekrar (default 4)

    Returns:
        .ics dosya metni
    """
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//FermatAI//Calisma Plani//TR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:FermatAI — {_escape(student_name or 'Calisma Plani')}",
        "X-WR-TIMEZONE:Europe/Istanbul",
    ]

    today = date.today()
    now_utc = datetime.utcnow()

    for item in plan:
        gun = item.get("gun", "")
        saat_str = item.get("saat", "19:00")
        sure_dk = int(item.get("sure_dk") or 60)
        ders = item.get("ders", "")
        konu = item.get("konu", "")
        yontem = item.get("yontem", "")

        wday = _GUN_MAP.get(gun)
        if wday is None:
            continue

        # Saat parse (HH:MM)
        try:
            hh, mm = saat_str.split(":")
            tvak = time(int(hh), int(mm))
        except Exception:
            tvak = time(19, 0)

        first_date = _next_weekday(wday, today)
        start_dt = datetime.combine(first_date, tvak)
        end_dt = start_dt + timedelta(minutes=sure_dk)

        uid = f"{uuid.uuid4().hex[:12]}@fermatai.local"
        summary = f"{ders} — {konu}".strip(" —")
        description = yontem or f"{ders} çalışması"

        # RRULE: weeks haftası tekrarla
        rrule_until = (start_dt + timedelta(weeks=weeks)).strftime("%Y%m%dT%H%M%SZ")

        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{_fmt_dt(now_utc)}Z",
            f"DTSTART;TZID=Europe/Istanbul:{_fmt_dt(start_dt)}",
            f"DTEND;TZID=Europe/Istanbul:{_fmt_dt(end_dt)}",
            f"SUMMARY:{_escape(summary)}",
            f"DESCRIPTION:{_escape(description)}",
            f"LOCATION:{_escape('Fermat Eğitim (veya evde)')}",
            f"CATEGORIES:CALISMA,FERMAT",
            f"RRULE:FREQ=WEEKLY;UNTIL={rrule_until}",
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{_escape(summary)}",
            "TRIGGER:-PT10M",
            "END:VALARM",
            "END:VEVENT",
        ])

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    sample_plan = [
        {"gun": "Pazartesi", "saat": "19:00", "sure_dk": 60,
         "ders": "Matematik", "konu": "Türev", "yontem": "30 soru çöz + formül ezberle"},
        {"gun": "Çarşamba", "saat": "20:00", "sure_dk": 45,
         "ders": "Fizik", "konu": "Kaldırma Kuvveti", "yontem": "Konu özeti + 15 soru"},
        {"gun": "Cuma", "saat": "18:30", "sure_dk": 90,
         "ders": "Biyoloji", "konu": "Hücre", "yontem": "Tekrar deneme çöz"},
    ]
    ics_content = plan_to_ics(sample_plan, student_name="Ayşe Yılmaz", weeks=4)
    print(ics_content[:800])
    print(f"\n[...{len(ics_content)} byte toplam]")
