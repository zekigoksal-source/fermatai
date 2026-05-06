"""
FermatAI Core Agent
===================
Projenin beyni. Pedagojik muhakeme + tool-calling mimarisi.

Çalışma prensibi:
  WhatsApp/sesli komut → IntentParser → CoreAgent → Tool-Calling → Eyotek Action + DB

Araçlar (Tools):
  get_student_analytics(student_id)         → Öğrenci akademik + devamsızlık profili
  check_teacher_availability(subject, date) → Öğretmen müsaitlik kontrolü
  execute_eyotek_action(action, params)     → Eyotek yazma işlemi (etüt, not, SMS)
  get_class_summary(class_name)             → Sınıf özeti
  search_students(query)                    → İsme/sınıfa göre öğrenci ara

Kullanım:
  python fermat_core_agent.py
  python fermat_core_agent.py "Ahmet'e rapor çek"
  python fermat_core_agent.py "11 SAY A sınıfına fizik etüt yaz"
"""

import asyncio
import json
import os
import sys
import time  # Oturum 25.11: Groq-tools pre-check ve duration timing
import uuid
from datetime import date as _date, timedelta as _td
from pathlib import Path
from typing import Any, Optional

import asyncpg
from anthropic import Anthropic, AsyncAnthropic
from dotenv import load_dotenv
from loguru import logger

load_dotenv(override=True)

# ─── Konfigürasyon ────────────────────────────────────────────────────────────

# DB URL merkezi kaynak
from db_pool import DB_URL as DATABASE_URL, db_fetch as _db_fetch, db_fetchrow as _db_fetchrow, db_fetchval as _db_fetchval, db_execute as _db_execute, get_pool as _db_pool
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL         = os.getenv("FERMAT_MODEL", "claude-sonnet-4-6")


# Arac Tanimlari (22.1n-split: tool_definitions.py modulune tasindi)
from tool_definitions import TOOLS, TOOLS_ACTIVE, get_tools


# ─── Araç Uygulamaları ────────────────────────────────────────────────────────

async def tool_query_analytics(sql: str, explanation: str = "", use_cache: str = "",
                               _caller_role: str = "", _caller_soz_no: int = None,
                               _caller_phone: str = "") -> dict:
    """Guvenli PostgreSQL SELECT sorgusu calistir. use_cache varsa once cache'e bak."""
    result = {"success": False, "explanation": explanation}

    # ── SQL ACL kontrolu ──────────────────────────────────────────────────────
    # 22.1n-neo: FINANS GUARD admin/mudur icin DE calisir — phone check sart.
    # Once finans icerik kontrolu (her rol icin), sonra normal ACL (non-admin icin).
    from finans_access import check_finans_sql_access, log_finans_access, sql_contains_finans
    finans_err = check_finans_sql_access(_caller_role, _caller_phone, sql)
    if finans_err:
        result["error"] = finans_err
        # Finans erisim denemesi — audit (basarisiz)
        try:
            import asyncio as _aio
            _aio.create_task(log_finans_access(
                _caller_phone, "sql_blocked",
                target="query_analytics",
                details=f"role={_caller_role} sql={sql[:200]}",
                success=False
            ))
        except Exception:
            pass
        return result
    # Normal ACL — admin/mudur'a finans disi ACL atla (mevcut davranis)
    if _caller_role and _caller_role not in ("admin", "mudur"):
        acl_error = _check_sql_acl(_caller_role, sql, _caller_soz_no, phone=_caller_phone)
        if acl_error:
            result["error"] = acl_error
            return result
    # Neo finans sorgusu BASARILI ise audit (post-execute asagida zaten DB sorgusu var, sonra)
    _neo_finans_success = sql_contains_finans(sql)

    # ── ORSEL KOC (SGM — Hibrit: Müdür + Teknik) — sadece KİŞİSEL LOG gizli ──
    # Teknik tablolar (atlas_*, student_exams, students vb.) AÇIK
    # Kişisel konuşma/kullanım logları KAPALI (admin-only)
    if _caller_phone == "905547043775":
        sql_upper_orsel = sql.upper()
        SGM_FORBIDDEN_TABLES = [
            "AGENT_CONVERSATIONS",  # Kişisel konuşma içerikleri — admin-only
            "USAGE_LOG",            # Kim ne zaman yazdı detayı — admin-only
            "ROUTING_STATS",        # Mesaj bazlı routing — admin-only
            "DAILY_STATS",          # Günlük kullanım — admin-only
            "USER_FEEDBACK",        # Neo talimatları — admin-only
            "BLOCKED_NUMBERS",      # Bloklanan numaralar — admin-only
            "LEAD_CONTACTS",        # Dış dünya iletişim — admin-only
            "OVERDUE_PAYMENTS",     # Ödeme/borç — admin-only
            "ACL_USERS",            # Yetki tablosu — admin-only
            "ADMIN_TALIMAT",        # Neo talimatları — admin-only
        ]
        for tbl in SGM_FORBIDDEN_TABLES:
            if tbl in sql_upper_orsel:
                result["error"] = (
                    f"Bu tablo ({tbl.lower()}) kisisel/finansal veri icerdigi icin admin erisimindedir. "
                    "Teknik tablolar (atlas_observations, atlas_suggestions, students, student_exams, "
                    "etut_history, teacher_timetable vb.) serbest."
                )
                return result

    # Cache kontrolu — hazir veri varsa aninda don
    if use_cache:
        try:
            from analytics_cache import get_cached, get_cache_age_minutes
            cached = get_cached(use_cache)
            if cached is not None:
                age = get_cache_age_minutes()
                return {
                    "success": True,
                    "explanation": explanation,
                    "data": cached if isinstance(cached, list) else [cached],
                    "row_count": len(cached) if isinstance(cached, list) else 1,
                    "source": f"cache ({age:.0f}dk once)",
                    "columns": list(cached[0].keys()) if isinstance(cached, list) and cached else [],
                }
        except Exception:
            pass  # Cache yoksa DB'ye devam et

    # Guvenlik kontrol
    # 19 Nisan AST GUARD (Talimat #13) — regex'ten ONCE yapisal dogrulama
    try:
        from utils.sql_guard import validate_sql
        ast_err = validate_sql(sql, _caller_role, _caller_soz_no)
        if ast_err:
            result["error"] = ast_err
            return result
    except ImportError:
        pass  # sqlglot yoksa fallback regex guard (asagidaki kod) devam eder

    sql_clean = sql.strip().upper()

    # 19 Nisan FIX: Multi-statement koruma — ";" ile ikinci komut calistirilamaz
    # "SELECT 1; DROP TABLE x" tarzi kacislari engeller
    # DIKKAT: stringIcindeki ";" yanilsamaya yolacabilir ama bu low-risk (string biz kontrolunde)
    sql_stripped = sql.strip().rstrip(";").strip()
    if ";" in sql_stripped:
        # String literallerin disinda ";" varsa ret
        import re as _re_sqlchk
        # String literalleri cikart, sonra ";" var mi bak
        no_strings = _re_sqlchk.sub(r"'[^']*'", "''", sql_stripped)
        no_strings = _re_sqlchk.sub(r'"[^"]*"', '""', no_strings)
        if ";" in no_strings:
            result["error"] = "Guvenlik: Coklu SQL statement yasak (';' karakteri)."
            return result

    # 19 Nisan FIX: Yorum injection koruma — "--" ve "/* */" kacislari
    # "WHERE id=1-- AND role='admin'" tarzi bypass'i engeller
    if "--" in sql or "/*" in sql:
        # Yorumsuz karakterlerin arasinda -- var mi kontrolü
        import re as _re_sqlchk
        no_strings2 = _re_sqlchk.sub(r"'[^']*'", "''", sql)
        if "--" in no_strings2 or "/*" in no_strings2:
            result["error"] = "Guvenlik: SQL yorum karakteri yasak (-- veya /* */)."
            return result

    # SELECT + belirli tablolar icin UPDATE/INSERT izin ver
    is_tracker_write = any(t in sql_clean for t in ["STUDENT_TOPIC_TRACKER", "STUDENT_INSIGHTS"])
    is_admin_write = _caller_role == "admin" and any(t in sql_clean for t in ["ADMIN_TALIMAT", "LEAD_CONTACTS"])
    # Oturum 21: atlas_suggestions/observations INSERT — self-observing sistem (Neo talebi)
    # Claude tutarsizlik tespit ettiginde buraya INSERT eder, admin daha sonra gorur.
    is_atlas_write = any(t in sql_clean for t in ["ATLAS_SUGGESTIONS", "ATLAS_OBSERVATIONS"])
    is_safe_write = (is_tracker_write or is_admin_write or is_atlas_write) and any(w in sql_clean for w in ["UPDATE", "INSERT"])

    if not sql_clean.startswith("SELECT") and not is_safe_write:
        result["error"] = "Sadece SELECT sorgusu calistirilabilir (student_insights/topic_tracker/atlas haric)."
        return result
    # 19 Nisan FIX: Genislemis forbidden liste (COPY, GRANT, EXECUTE, pg_sleep vb)
    forbidden = ["DROP", "ALTER", "TRUNCATE", "GRANT", "REVOKE", "COPY ", "EXECUTE ", "CALL ",
                 "PG_SLEEP", "PG_READ_FILE", "PG_LS_DIR", "\\COPY"]
    for word in forbidden:
        if word in sql_clean:
            result["error"] = f"Guvenlik: {word.strip()} komutu yasak."
            return result

    # AYT GUARD: student_exams + LIKE '[AYT]%' (AYT cekme denemesi) engellenir.
    # NOT LIKE '[AYT]%' (TYT filtresi) SERBEST.
    if ("STUDENT_EXAMS" in sql_clean
            and "LIKE '[AYT]" in sql_clean
            and "NOT LIKE '[AYT]" not in sql_clean):
        result["error"] = (
            "YANILTICI VERI KORUMASI: student_exams tablosundaki '[AYT]%' kayitlari "
            "TYT netlerinden KOPYALANMISTIR — AYT icin guvenilir degil. "
            "AYT verisi icin `get_ayt_analysis(soz_no=X)` tool'unu cagir. "
            "Coklu ogrenci AYT icin: SELECT ... FROM student_exam_analysis WHERE ham_puan_ayt IS NOT NULL."
        )
        return result

    try:
        from analytics_cache import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql)

        if rows:
            result["success"] = True
            result["row_count"] = len(rows)
            result["columns"] = list(rows[0].keys())
            # Max 50 satir don
            result["data"] = [dict(r) for r in rows[:50]]
            # Tarih/datetime serialization
            import json
            for row in result["data"]:
                for k, v in row.items():
                    if hasattr(v, 'isoformat'):
                        row[k] = v.isoformat()
        else:
            result["success"] = True
            result["row_count"] = 0
            result["data"] = []
    except Exception as e:
        result["error"] = str(e)

    # 22.1n-neo: Finans sorgusu BASARILI ise audit log
    if _neo_finans_success and result.get("success"):
        try:
            import asyncio as _aio
            _aio.create_task(log_finans_access(
                _caller_phone, "sql_query",
                target="query_analytics",
                details=f"rows={result.get('row_count', 0)} explain={explanation[:80]}",
                success=True
            ))
        except Exception:
            pass

    return result


async def tool_get_student_analytics(student_id: str, include_sections: list[str] | None = None) -> dict:
    """Öğrenci analytics — PostgreSQL'den çek."""
    sections = include_sections or ["all"]
    include_all = "all" in sections
    result: dict[str, Any] = {"student_id": student_id, "found": False}

    # Öğrenci temel bilgisi
    rows = await _db_fetch(
        """SELECT * FROM students
           WHERE eyotek_id = $1
              OR lower(full_name) LIKE lower($2)
              OR lower(first_name) LIKE lower($2)
           LIMIT 5""",
        student_id,
        f"%{student_id}%",
    )
    if not rows:
        return {**result, "message": f"'{student_id}' için kayıt bulunamadı."}

    result["found"] = True
    result["students"] = rows[:5]
    main = rows[0]
    eid = main.get("eyotek_id", student_id)

    # Sınavlar
    # Not: exam_results tablosu sınıf düzeyinde veri içerir (bireysel değil).
    # Öğrencinin sınıfını bul → sınıf sınav ortalamalarını getir.
    if include_all or "exams" in sections:
        soz = main.get("soz_no") or eid
        # student_exams tablosu — sinav bazli detay
        exams = await _db_fetch(
            """SELECT exam_name, exam_date, turkce, matematik, geometri, fizik, kimya, biyoloji, toplam
               FROM student_exams
               WHERE soz_no = $1
               ORDER BY exam_date DESC NULLS LAST LIMIT 5""",
            int(soz) if soz else 0,
        )
        result["exams"] = exams
        if exams:
            nets = [float(r.get("toplam", 0) or 0) for r in exams if r.get("toplam")]
            result["avg_net"] = round(sum(nets) / len(nets), 2) if nets else 0
        # Kumulatif analiz
        analysis = await _db_fetch(
            """SELECT ham_puan, yerlesme_puani, oncelikli_konular, sinav_sayisi
               FROM student_exam_analysis WHERE soz_no::text = $1 LIMIT 1""",
            str(soz),
        )
        if analysis:
            result["exam_analysis"] = analysis[0]

    # Devamsızlık
    if include_all or "attendance" in sections:
        soz = main.get("soz_no") or eid
        # Toplam devamsizlik
        devam = await _db_fetch(
            "SELECT toplam_saat FROM devamsizlik_sayisi WHERE soz_no = $1 LIMIT 1",
            int(soz) if soz else 0,
        )
        result["absence_total_hours"] = devam[0]["toplam_saat"] if devam else 0
        # NOT (Oturum 25.29): attendance tablosu deprecated — soz_no/tarih TEXT,
        # 6 Nisan'dan beri sync olmuyor (sessiz fail). yoklama_kontrol kullan.
        # Detay absences icin ozel ihtiyac varsa: SELECT y.tarih, y.ders, y.yoklama
        # FROM yoklama_kontrol y JOIN students s ON s.class_name = y.sinif
        # WHERE s.soz_no = $1. Su an bot devamsizlik_sayisi.toplam_saat yeterli.
        result["absences"] = []
        result["absence_count"] = result.get("absence_total_hours", 0)

    # Ödemeler
    if include_all or "payments" in sections:
        payments = await _db_fetch(
            """SELECT tutar, borc, odeme, bakiye, vade_tarihi
               FROM overdue_payments
               WHERE eyotek_id = $1 OR soz_no = $1
               LIMIT 5""",
            eid,
        )
        result["overdue_payments"] = payments

    # Davranış kayıtları
    if include_all or "behaviour" in sections:
        behaviour = await _db_fetch(
            """SELECT tarih, tur, aciklama, puan, ogretmen
               FROM student_behaviour
               WHERE eyotek_id = $1 OR soz_no = $1
               ORDER BY tarih DESC LIMIT 10""",
            eid,
        )
        result["behaviour"] = behaviour

    # Bireysel sınav sonuçları (student_exams tablosu)
    # NOT: student_exams ders bazli net'ler kolonlarinda — toplam, turkce, matematik, fizik vs.
    if include_all or "exams" in sections:
        try:
            soz_int = int(eid) if isinstance(eid, str) and eid.isdigit() else eid
        except Exception:
            soz_int = eid
        personal_exams = await _db_fetch(
            """SELECT exam_name as sinav_adi, exam_date as tarih,
                      toplam as net,
                      turkce, matematik, geometri, fizik, kimya, biyoloji,
                      tarih as h_tarih, cografya, felsefe, din_kulturu
               FROM student_exams
               WHERE soz_no::text = $1::text
               ORDER BY exam_date DESC LIMIT 15""",
            str(soz_int) if soz_int else str(eid),
        )
        if personal_exams:
            result["personal_exams"] = personal_exams
            nets = [float(r.get("net", 0) or 0) for r in personal_exams if r.get("net")]
            if nets:
                result["avg_net"] = round(sum(nets) / len(nets), 2)

    # Sınav birleştirme analizi (en değerli veri — konu bazlı eksik analizi)
    if include_all or "exams" in sections:
        exam_analysis = await _db_fetch(
            """SELECT ham_puan, yerlesme_puani, ham_sira, yerlesme_sirasi,
                      ders_netleri, oncelikli_konular, sinav_sayisi, katilan_sinav,
                      toplam_net, toplam_dogru, toplam_yanlis, toplam_bos,
                      osym_2025_ham, osym_2025_yer, last_sync
               FROM student_exam_analysis
               WHERE eyotek_id = $1 OR soz_no = $1
               ORDER BY last_sync DESC LIMIT 1""",
            eid,
        )
        if exam_analysis:
            ea = exam_analysis[0]
            result["exam_analysis"] = {
                "ham_puan": ea.get("ham_puan"),
                "yerlesme_puani": ea.get("yerlesme_puani"),
                "siralama": ea.get("ham_sira"),
                "ders_netleri": ea.get("ders_netleri"),
                "oncelikli_konular": ea.get("oncelikli_konular"),
                "sinav_sayisi": ea.get("sinav_sayisi"),
                "toplam_net": ea.get("toplam_net"),
                "last_sync": str(ea.get("last_sync", "")),
            }

    # Öğrenci etkileşim istatistikleri (hangi konularda soru soruyor)
    interactions = await _db_fetch(
        """SELECT konu, mesaj_sayisi FROM student_interactions
           WHERE eyotek_id = $1 ORDER BY mesaj_sayisi DESC LIMIT 5""",
        eid,
    )
    if interactions:
        result["interaction_stats"] = interactions

    # Pedagojik özet
    absence_count = result.get("absence_count", 0)
    avg_net       = result.get("avg_net", 0)
    risk_level    = "düşük"
    if absence_count > 10 or avg_net < 10:
        risk_level = "yüksek"
    elif absence_count > 5 or avg_net < 20:
        risk_level = "orta"

    result["pedagogical_summary"] = {
        "name":          main.get("full_name", ""),
        "class":         main.get("class_name", ""),
        "program":       main.get("program", ""),
        "avg_net":       avg_net,
        "absence_count": absence_count,
        "risk_level":    risk_level,
        "overdue_debt":  bool(result.get("overdue_payments")),
    }
    return result


async def tool_check_teacher_availability(subject: str, date: str = "") -> dict:
    """Öğretmen müsaitlik kontrolü — staff tablosundan branş eşleşmesi."""
    _TR_TO_UPPER = str.maketrans("iığşüöç", "İIĞŞÜÖÇ")
    subject_upper = subject.translate(_TR_TO_UPPER).upper()
    teachers = await _db_fetch(
        """SELECT eyotek_id, ik_no, full_name, brans, gorev, email, kullanici, status
           FROM staff
           WHERE (lower(brans) LIKE lower($1) OR brans ILIKE $2)
             AND (status IS NULL OR status != 'Pasif')
           ORDER BY full_name""",
        f"%{subject}%",
        f"%{subject_upper}%",
    )
    return {
        "subject":   subject,
        "date":      date,
        "teachers":  teachers,
        "count":     len(teachers),
        "available": [t["full_name"] for t in teachers],
    }


async def tool_get_class_summary(class_name: str) -> dict:
    """Sınıf özeti — students + exam_results + attendance tablolarından."""
    students = await _db_fetch(
        """SELECT eyotek_id, full_name, status
           FROM students
           WHERE lower(class_name) LIKE lower($1)""",
        f"%{class_name}%",
    )
    if not students:
        return {"class_name": class_name, "found": False, "message": "Sınıf bulunamadı"}

    ids = [s["eyotek_id"] for s in students if s.get("eyotek_id")]
    active_count = sum(1 for s in students if (s.get("status") or "") != "Silinmiş")

    # Son sınav ortalaması
    avg_net = 0.0
    if ids:
        exam_rows = await _db_fetch(
            f"""SELECT AVG(NULLIF(net, '')::float) as avg_net
                FROM exam_results
                WHERE eyotek_id = ANY($1::text[])""",
            ids,
        )
        if exam_rows and exam_rows[0].get("avg_net"):
            avg_net = round(float(exam_rows[0]["avg_net"]), 2)

    # Devamsizlik sayisi — Oturum 25.29: attendance deprecated (sync yok),
    # devamsizlik_sayisi tablosundan TOPLAM saat alinir.
    abs_count = 0
    if ids:
        try:
            abs_rows = await _db_fetch(
                """SELECT COALESCE(SUM(toplam_saat), 0) as cnt
                   FROM devamsizlik_sayisi
                   WHERE soz_no::text = ANY($1::text[])""",
                ids,
            )
            if abs_rows:
                abs_count = int(abs_rows[0].get("cnt", 0) or 0)
        except Exception:
            abs_count = 0

    return {
        "class_name":    class_name,
        "found":         True,
        "student_count": len(students),
        "active_count":  active_count,
        "avg_net":       avg_net,
        "total_absences": abs_count,
        "students":      students[:20],
    }


async def tool_search_students(query: str, limit: int = 5) -> dict:
    """Öğrenci adına veya sınıfa göre ara. query='istatistik' ile genel ozet dondurur."""
    # Istatistik modu — genel ogrenci sayisi, sinif dagilimi
    if query.lower().strip() in ("istatistik", "sayı", "sayi", "toplam", "kac", "kaç", "özet", "tüm", "tum", "hepsi"):
        stats = await _db_fetch("""
            SELECT class_name, devre, COUNT(*) as cnt
            FROM students
            WHERE status IS NULL OR status != 'Silinmiş'
            GROUP BY class_name, devre
            ORDER BY devre, class_name
        """)
        total = sum(r["cnt"] for r in stats)
        devre_summary = {}
        for r in stats:
            d = r.get("devre") or "Tanimsiz"
            devre_summary[d] = devre_summary.get(d, 0) + r["cnt"]
        return {
            "query": query,
            "mode": "istatistik",
            "total_students": total,
            "devre_summary": devre_summary,
            "class_details": [{"class": r.get("class_name") or "?", "devre": r.get("devre") or "?", "count": r["cnt"]} for r in stats],
            "count": total,
        }

    # Turkce I/G/S/U/O/C normalize: kucuk→BUYUK Turkce (DB uppercase sakliyor)
    # Python i.upper()='I' (ASCII) ama Türkçe'de i.upper()='İ'; bunu elle yapıyoruz
    _TR_TO_UPPER = str.maketrans("iığşüöç", "İIĞŞÜÖÇ")
    q_tr_upper = query.translate(_TR_TO_UPPER).upper()  # "ali küçükuysal" → "ALİ KÜÇÜKUYSAL"
    # ASCII versiyonu da dene (kucukuysal → KUCUKUYSAL)
    _TR_TO_ASCII = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    q_ascii = query.translate(_TR_TO_ASCII)

    rows = await _db_fetch(
        """SELECT eyotek_id, soz_no, full_name, class_name, sube, program, status
           FROM students
           WHERE full_name  ILIKE $1
              OR class_name ILIKE $1
              OR sube       ILIKE $1
              OR full_name  ILIKE $2
              OR class_name ILIKE $2
              OR TRANSLATE(full_name, 'ÇĞİÖŞÜçğıöşü', 'CGIOSUcgiosu') ILIKE $3
              OR eyotek_id  = $4
              OR soz_no     = $4
           LIMIT $5""",
        f"%{query}%",
        f"%{q_tr_upper}%",
        f"%{q_ascii.upper()}%",
        query,
        limit,
    )
    return {
        "query":   query,
        "results": rows,
        "count":   len(rows),
    }


async def _log_conversation(
    session_id: str, phone: str, role: str,
    message_role: str, content: str, tools_used: list[str] | None = None,
) -> None:
    """Konusma gecmisini agent_conversations tablosuna yaz."""
    if not DATABASE_URL:
        return
    # Oturum Mentenans (21 Nisan 19:10) — TEST SESSION filtresi
    # Ortam degiskeni FERMAT_TEST_MODE=1 ise veya session_id '_test_' ile basliyorsa:
    # - routing_stats'a yazma
    # - agent_conversations'a _test_ prefix'i ile yaz (kolay filtre için)
    import os as _os_log
    _is_test = bool(_os_log.getenv("FERMAT_TEST_MODE")) or (session_id or "").startswith("_test_")
    if _is_test:
        # Test modu: DB'ye ya hiç yazma ya da test prefix ile yaz
        if _os_log.getenv("FERMAT_TEST_NO_DB") == "1":
            return  # Tamamen atla
        # Prefix ekle — kolay SQL filtresi: WHERE session_id NOT LIKE '_test_%'
        if not (session_id or "").startswith("_test_"):
            session_id = f"_test_{session_id or 'anon'}"
    # Hassas icerik filtresi — sifre, credential DB'ye yazilmasin
    import re as _re_log
    if message_role == "user" and _re_log.search(
        r'(şifre|sifre|password|parola|kullan[iı]c[iı]\s*ad[iı]|user\s*name|giriş\s*bilgi)',
        content, _re_log.IGNORECASE):
        content = "[GUVENLIK: Hassas icerik filtrelendi]"
    # Oturum 18: pool kullan — her mesajda 50-100ms tasarruf
    # Oturum 23 (Neo UX raporu): 4000 → 16000 char. 4000 kesimi bot'un kendi
    # önceki uzun yanıtlarının SONUNU göremediği için aynı şeyi tekrar ürettiği
    # bağlam kaybına yol açıyordu. Chart JSON, uzun pedagojik analiz, çalışma
    # planı gibi zengin cevaplar 4000'de kesiliyordu. PostgreSQL text tipi
    # sınırsız; 16000 pratik üst sınır (~4000 token, history fetch'te yükü
    # kabul edilebilir). Fallback: sadece 16000+ aşarsa [...devam] özetle.
    _MAX_LOG_CHARS = 16000
    if len(content) > _MAX_LOG_CHARS:
        content_to_log = content[:_MAX_LOG_CHARS - 200] + "\n\n[...mesajin devami log'a sigmadi — kullanici tam metni aldi]"
    else:
        content_to_log = content
    try:
        from analytics_cache import get_pool as _get_shared_pool
        pool = await _get_shared_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO agent_conversations
                   (session_id, phone, role, message_role, content, tools_used)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                session_id, phone or "", role or "", message_role,
                content_to_log,
                tools_used or [],
            )
    except Exception as e:
        logger.warning(f"Konusma log yazilamadi: {e}")


async def _keyword_search_rag(query: str, ders: str = "", limit: int = 3) -> list:
    """Semantik arama yetersiz kaldiginda keyword-based fallback."""
    pool = await _db_pool()
    async with pool.acquire() as conn:
        # Query'den anahtar kelimeler cikar (2+ harfli kelimeler)
        words = [w.strip().lower() for w in query.split() if len(w.strip()) > 2]
        if not words:
            return []
        # Cikmis soru anahtar kelimeleri filtrele (genel kelimeler atla)
        skip_words = {'cikmis', 'cıkmış', 'soru', 'sorusu', 'sorulari', 'goster', 'göster',
                      'getir', 'bul', 'var', 'konusundan', 'konusu', 'konusunda',
                      'gecen', 'geçen', 'yil', 'yıl', 'son', 'bana', 'bir'}
        content_words = [w for w in words if w not in skip_words]
        if not content_words:
            content_words = words[:2]
        # Turkce karakter varyantlari (ASCII → orijinal)
        _TR_MAP = {'turev':'türev', 'basinc':'basınç', 'kaldirma':'kaldırma',
                   'cozum':'çözüm', 'olasilik':'olasılık', 'ucgen':'üçgen',
                   'cember':'çember', 'donusum':'dönüşüm', 'ustel':'üstel',
                   'hucre':'hücre', 'osmanli':'osmanlı', 'cumhuriyet':'cumhuriyet',
                   'esitsizlik':'eşitsizlik', 'fonksiyon':'fonksiyon',
                   'bolunebilme':'bölünebilme', 'carpanlar':'çarpanlar',
                   'cozunurluk':'çözünürlük', 'induksiyon':'indüksiyon',
                   'elektromanyetik':'elektromanyetik', 'frekans':'frekans',
                   'isik':'ışık', 'sicaklik':'sıcaklık', 'yogunluk':'yoğunluk',
                   'kalitim':'kalıtım', 'mutasyon':'mutasyon', 'ekoloji':'ekoloji'}
        # 2 asamali arama: once KONU alaninda, sonuç yoksa ICERIK'te
        # Konu araması daha kesin (ders:Biyoloji + konu:'bitkiler' = dogru eslesme)
        conditions = []
        params = []
        for w in content_words:
            idx = len(params) + 1
            tr_w = _TR_MAP.get(w.lower())
            if tr_w:
                conditions.append(f"(konu ILIKE ${idx} OR konu ILIKE ${idx+1})")
                params.extend([f"%{w}%", f"%{tr_w}%"])
            else:
                conditions.append(f"(konu ILIKE ${idx})")
                params.append(f"%{w}%")
        where = " AND ".join(conditions)
        # SADECE OGM Vision kaynaklarinda ara
        where += " AND kaynak LIKE '%OGM Vision%'"
        # Ders filtresi — konu aramasinda onemli (asit-baz → Kimya, enerji → Fizik)
        _DERS_NORM_KW = {'türkçe':'Turkce', 'turkce':'Turkce', 'matematik':'Matematik',
                      'fizik':'Fizik', 'kimya':'Kimya', 'biyoloji':'Biyoloji',
                      'tarih':'Tarih', 'cografya':'Cografya', 'felsefe':'Felsefe'}
        ders_kw = _DERS_NORM_KW.get((ders or '').lower().strip(), ders)
        if ders_kw:
            params.append(ders_kw)
            where += f" AND ders = ${len(params)}"
        params.append(limit)
        rows = await conn.fetch(f"""
            SELECT id, sinav_turu, ders, konu, alt_konu, icerik_turu,
                   baslik, icerik, kaynak, zorluk, soru_sayisi
            FROM rag_content
            WHERE {where}
            ORDER BY
                CASE WHEN kaynak LIKE '%%OGM Vision%%' THEN 0 ELSE 1 END,
                LENGTH(icerik) DESC
            LIMIT ${len(params)}
        """, *params)
        results = []
        for r in rows:
            results.append({
                "id": r["id"], "sinav_turu": r["sinav_turu"], "ders": r["ders"],
                "konu": r["konu"], "alt_konu": r["alt_konu"], "icerik_turu": r["icerik_turu"],
                "baslik": r["baslik"], "icerik": r["icerik"], "kaynak": r["kaynak"],
                "zorluk": r["zorluk"], "soru_sayisi": r["soru_sayisi"], "skor": 0.700,
            })
        # Konu aramasinda sonuc yoksa → icerik'te de ara (fallback)
        if not results and content_words:
            fallback_conds = []
            fallback_params = []
            for w in content_words:
                idx = len(fallback_params) + 1
                tr_w = _TR_MAP.get(w.lower())
                if tr_w:
                    fallback_conds.append(f"(icerik ILIKE ${idx} OR icerik ILIKE ${idx+1})")
                    fallback_params.extend([f"%{w}%", f"%{tr_w}%"])
                else:
                    fallback_conds.append(f"(icerik ILIKE ${idx})")
                    fallback_params.append(f"%{w}%")
            fb_where = " AND ".join(fallback_conds)
            fb_where += " AND kaynak LIKE '%OGM Vision%'"
            if ders_kw:
                fallback_params.append(ders_kw)
                fb_where += f" AND ders = ${len(fallback_params)}"
            fallback_params.append(limit)
            fb_rows = await conn.fetch(f"""
                SELECT id, sinav_turu, ders, konu, alt_konu, icerik_turu,
                       baslik, icerik, kaynak, zorluk, soru_sayisi
                FROM rag_content WHERE {fb_where}
                ORDER BY LENGTH(icerik) DESC LIMIT ${len(fallback_params)}
            """, *fallback_params)
            for r in fb_rows:
                results.append({
                    "id": r["id"], "sinav_turu": r["sinav_turu"], "ders": r["ders"],
                    "konu": r["konu"], "alt_konu": r["alt_konu"], "icerik_turu": r["icerik_turu"],
                    "baslik": r["baslik"], "icerik": r["icerik"], "kaynak": r["kaynak"],
                    "zorluk": r["zorluk"], "soru_sayisi": r["soru_sayisi"], "skor": 0.650,
                })
        return results


async def _tool_ogm_yonlendir(ders: str = "", sinav_turu: str = "", tip: str = "") -> dict:
    """MEB OGM Materyal resmi kaynagi yonlendirme (22.1n-ogm)."""
    from ogm_catalog import yonlendir
    # Ders normalizasyonu
    _NORM = {'türkçe':'Turkce','turkce':'Turkce','matematik':'Matematik','fizik':'Fizik',
             'kimya':'Kimya','biyoloji':'Biyoloji','tarih':'Tarih','coğrafya':'Cografya',
             'cografya':'Cografya','felsefe':'Felsefe','edebiyat':'TDE','tde':'TDE',
             'ingilizce':'Ingilizce','english':'Ingilizce'}
    if ders:
        ders = _NORM.get(ders.lower().strip(), ders)
    if sinav_turu:
        sinav_turu = sinav_turu.upper().strip()

    results = await yonlendir(ders=ders, sinav_turu=sinav_turu, tip=tip)
    if not results:
        return {"sonuc": "OGM materyal kataloğunda eşleşen kaynak yok. Filtreleri gevşet."}
    return {
        "kaynak_sayisi": len(results),
        "kaynaklar": [
            {
                "baslik": r["konu_adi"],
                "url": r["url"],
                "aciklama": r["icerik_ozet"],
                "kategori": r["icerik_tipi"],
                "sinav": r["sinif"],
                "ders": r["ders"],
            }
            for r in results
        ],
        "hatirlatma": "Bu MEB OGM Materyal resmi kaynaklaridir. Ogrenciye 2-3 link paylaş, 'Bu linke git, X kadar soru çöz, zorlandığını bana getir' gibi PROAKTIF yönlendirme yap.",
    }


async def _tool_search_curriculum(query: str = "", ders: str = "", sinav_turu: str = "") -> dict:
    """Müfredat bilgi bankasında semantik + keyword arama.

    25.40n: sinav_turu parametresi eklendi — LGS_HAZIRLIK_6/7/LGS için
    yeni nesil örnek paketleri ayrıştırma.
    """
    from rag_engine import search_curriculum
    if not query:
        return {"error": "query parametresi gerekli"}
    # Ders normalizasyonu
    _DERS_NORM = {'türkçe':'Turkce', 'turkce':'Turkce', 'matematik':'Matematik',
                  'fizik':'Fizik', 'kimya':'Kimya', 'biyoloji':'Biyoloji',
                  'tarih':'Tarih', 'coğrafya':'Cografya', 'cografya':'Cografya',
                  'felsefe':'Felsefe', 'geometri':'Geometri',
                  'fen bilimleri':'Fen Bilimleri', 'sosyal bilgiler':'Sosyal Bilgiler',
                  'ingilizce':'İngilizce', 'i̇ngilizce':'İngilizce', 'turkce':'Türkçe',
                  't.c. inkılap tarihi':'T.C. İnkılap Tarihi'}
    if ders:
        ders = _DERS_NORM.get(ders.lower().strip(), ders)
    # sinav_turu hint Claude'dan gelmeli — yoksa tum bankada ara
    sinav_turu_clean = (sinav_turu or "").strip().upper() or None
    results = await search_curriculum(query, ders=ders, limit=5, sinav_turu=sinav_turu_clean)
    # Ders filtresiyle yeterli sonuç bulunamazsa, filtre olmadan tekrar dene
    if len(results) < 2 or (results and results[0]["skor"] < 0.5):
        results_broad = await search_curriculum(query, ders="", limit=5)
        if results_broad and (not results or results_broad[0]["skor"] > results[0]["skor"]):
            results = results_broad
    # Keyword fallback — cikmis soru gorseli bulmak icin keyword arama
    has_ogm = any("OGM Vision" in r.get("kaynak", "") for r in results)
    if not has_ogm or not results or results[0]["skor"] < 0.65:
        kw_results = await _keyword_search_rag(query, ders=ders, limit=3)
        if kw_results:
            # Mevcut sonuçlarla birleştir, duplicate kaynak'ları atla
            existing_ids = {r["id"] for r in results}
            for kr in kw_results:
                if kr["id"] not in existing_ids:
                    results.insert(0, kr)  # Keyword sonuçlarını başa koy
            results = results[:5]
    # 22.1n-bug6: Her search_curriculum cevabina OGM konu ozeti PDF linkini ekle — ders tespit edildiyse
    # Claude response sonunda: "Detaylı PDF: [link]" diyebilir. Bos sonuclarda TEKIL fallback.
    _global_ogm = None
    try:
        from ogm_catalog import yonlendir
        _q_low = query.lower()
        _ders_map = {'fizik':'Fizik','matematik':'Matematik','mat':'Matematik','kimya':'Kimya',
                     'biyoloji':'Biyoloji','turkce':'Turkce','türkçe':'Turkce','tarih':'Tarih',
                     'cografya':'Cografya','coğrafya':'Cografya','felsefe':'Felsefe',
                     'edebiyat':'TDE','tde':'TDE','geometri':'Matematik','basit makine':'Fizik'}
        _detected = ders
        if not _detected:
            for k, v in _ders_map.items():
                if k in _q_low:
                    _detected = v
                    break
        if _detected:
            _ogm_list = await yonlendir(ders=_detected, tip="konu_ozeti")
            if _ogm_list:
                _global_ogm = [
                    {"baslik": r["konu_adi"], "url": r["url"]} for r in _ogm_list[:2]
                ]
    except Exception:
        pass

    if not results:
        resp = {"sonuc": "Bu konuda henüz müfredat içeriği yok. Kendi bilginle kapsamlı anlat."}
        if _global_ogm:
            resp["ogm_onerisi"] = _global_ogm
            resp["hatirlatma"] = "Cevabin sonunda MEB OGM konu ozeti PDF linkini ekle."
        return resp
    # Claude'a temiz format — OGM Vision sayfalarinda soru indeksi ekle
    import re as _re
    output = []
    for r in results:
        entry = {
            "ders": r["ders"],
            "konu": r["konu"],
            "baslik": r["baslik"],
            "icerik": r["icerik"],
            "zorluk": r["zorluk"],
            "soru_sayisi": r["soru_sayisi"],
            "benzerlik": r["skor"],
            "kaynak": r.get("kaynak", ""),
            "icerik_turu": r.get("icerik_turu", ""),
        }
        # OGM Vision sayfalarinda soru indeksi + YAPILANDIRILMIS soru metni cikar
        if "OGM Vision" in entry["kaynak"]:
            matches = _re.findall(r'SORU\s+(\d+)\s*\|\s*(\d{4})[-–](AYT|TYT)', entry["icerik"][:2000])
            if matches:
                entry["sayfadaki_sorular"] = [
                    {"soru_no": int(m[0]), "yil": int(m[1]), "sinav": m[2]}
                    for m in matches
                ]
            # Her soruyu ayrı JSON objesine parse et — Claude kolay okusun
            soru_blocks = _re.split(r'(?=SORU\s+\d+\s*\|)', entry["icerik"])
            parsed_sorular = []
            for block in soru_blocks:
                block = block.strip()
                if not block.startswith("SORU"):
                    continue
                header = _re.match(r'SORU\s+(\d+)\s*\|\s*(\d{4})[-–]?(AYT|TYT)?', block)
                if header:
                    soru_obj = {
                        "soru_no": int(header.group(1)),
                        "yil": header.group(2),
                        "sinav": header.group(3) or "?",
                        "metin": block[header.end():].strip()[:500],
                    }
                    # Şıkları çıkar
                    siklar = _re.findall(r'([A-E]\))\s*(.+?)(?=[A-E]\)|$)', soru_obj["metin"], _re.DOTALL)
                    if siklar:
                        soru_obj["siklar"] = {s[0]: s[1].strip()[:100] for s in siklar}
                    parsed_sorular.append(soru_obj)
            if parsed_sorular:
                entry["sorular_parsed"] = parsed_sorular
        output.append(entry)
    # 22.1n-bug6: Her zaman OGM konu ozeti link ekle (ders tespit edildiyse) — Claude karar versin ekleyip eklemeyecegini
    final = {"sonuclar": output, "kayit_sayisi": len(output)}
    if _global_ogm:
        final["ogm_konu_ozeti"] = _global_ogm
        final["hatirlatma"] = "RAG'da bulunmayan konular veya detay isteyen ogrencilerde cevap sonuna MEB OGM konu ozeti PDF linkini ekle."
    return final


async def _tool_send_exam_image(kaynak: str = "", caption: str = "",
                                _caller_phone: str = "", _caller_channel: str = "") -> dict:
    """Cikmis soru gorselini kanala gore gonder (22.1n-rev — Atlas #16 fix).

    WhatsApp: send_wa_image ile gorsel + caption
    Web:      CDN URL dondurulur, UI <img> render eder (WP'ye gonderim KAPALI)
    """
    from whatsapp_bridge import kaynak_to_cdn_url

    if not kaynak or "OGM Vision" not in kaynak:
        return {"error": "Gecersiz kaynak — sadece 'OGM Vision' iceren kaynaklar desteklenir."}

    cdn_url = kaynak_to_cdn_url(kaynak)
    if not cdn_url:
        return {"error": f"CDN URL olusturulamadi: {kaynak}"}

    # 22.1n-rev: Atlas #16 — Web kanalinda WhatsApp'a gonderme, direkt URL don
    if _caller_channel == "web":
        return {
            "basarili": True,
            "kanal": "web",
            "image_url": cdn_url,
            "caption": caption or "YKS Cikmis Soru",
            "mesaj": "Gorsel URL hazir — web UI'sinda inline render edilecek.",
            "markdown": f"![{caption or 'YKS Soru'}]({cdn_url})",
        }

    # WhatsApp kanali (varsayilan)
    if not _caller_phone:
        return {"error": "Hedef telefon numarasi yok."}

    from whatsapp_bridge import send_wa_image
    ok = await send_wa_image(_caller_phone, cdn_url, caption or "YKS Cikmis Soru")
    if ok:
        return {"basarili": True, "kanal": "whatsapp", "mesaj": f"Gorsel gonderildi: {caption or kaynak}"}
    else:
        return {"basarili": False, "mesaj": "Gorsel gonderilemedi — text ile devam et."}


async def _tool_list_exam_questions(konu: str = "", ders: str = "") -> dict:
    """Cikmis soru katalogu — konu/ders bazli, yil ve sayfa bilgisiyle.

    23 Nisan fix (Neo konuşma analizi):
    - SADECE split kayıtlar aranır (her soru tek kayıt, konu tek ve doğru).
    - Parent kayıtlar ('/' veya 've' ile çoklu konu) es geçilir — Soru 107 (Compton)
      ve Soru 108 (Görüntüleme Teknolojileri) aynı sayfa Soru 106 (Fotoelektrik)
      ile karıştırılmaz.
    """
    import re
    # Ders normalizasyonu — Claude Turkce karakter gonderebilir
    _DERS_NORM = {'türkçe':'Turkce', 'turkce':'Turkce', 'matematik':'Matematik',
                  'fizik':'Fizik', 'kimya':'Kimya', 'biyoloji':'Biyoloji',
                  'tarih':'Tarih', 'coğrafya':'Cografya', 'cografya':'Cografya',
                  'felsefe':'Felsefe', 'geometri':'Geometri'}
    if ders:
        ders = _DERS_NORM.get(ders.lower().strip(), ders)
    pool = await _db_pool()
    async with pool.acquire() as conn:
        # Arama kosullari — SADECE split kayıtlar (her soru tek kayıt, konu tek)
        conditions = [
            "kaynak LIKE '%OGM Vision%'",
            "kaynak LIKE '%split%'",  # Parent kayıtları filtrele (çoklu konu sorunu)
        ]
        params = []
        if konu:
            # Turkce varyant
            _TR = {'turev':'türev', 'basinc':'basınç', 'kaldirma':'kaldırma',
                   'cember':'çember', 'cembersel':'çembersel', 'ucgen':'üçgen',
                   'hucre':'hücre', 'osmanli':'osmanlı', 'esitsizlik':'eşitsizlik',
                   'cozum':'çözüm', 'olasilik':'olasılık', 'isik':'ışık',
                   'sicaklik':'sıcaklık', 'kalitim':'kalıtım', 'cozunurluk':'çözünürlük'}
            konu_words = [w for w in konu.lower().split() if len(w) > 2]
            konu_conds = []
            for w in konu_words:
                params.append(f"%{w}%")
                idx = len(params)
                tr_w = _TR.get(w)
                if tr_w:
                    params.append(f"%{tr_w}%")
                    idx2 = len(params)
                    # icerik'te değil SADECE konu'da ara — parent sızıntısı olmasın
                    konu_conds.append(f"(konu ILIKE ${idx} OR konu ILIKE ${idx2})")
                else:
                    konu_conds.append(f"(konu ILIKE ${idx})")
            if konu_conds:
                conditions.append(f"({' OR '.join(konu_conds)})")
        if ders:
            params.append(f"%{ders}%")
            conditions.append(f"ders ILIKE ${len(params)}")

        where = " AND ".join(conditions)
        rows = await conn.fetch(f"""
            SELECT id, kaynak, konu, ders, icerik, baslik FROM rag_content
            WHERE {where} ORDER BY kaynak LIMIT 80
        """, *params)

        # Split'te konu tek olduğu için doğrudan kullan
        # Kaynak "s.141 (split Q106)" formatında — soru no'yu regex ile kaynak'tan çek
        catalog = {}  # konu -> {yil: [{soru_no, kaynak, id}]}
        for r in rows:
            konu_adi = (r['konu'] or 'Genel').strip()
            # Generic "Fizik" / "FİZİK" / "Biyoloji - Genel" gibi çok genel etiketleri
            # kullanıcıya gösterme (arama hedefli olduğunda)
            if konu and konu_adi.lower() in ('fizik', 'kimya', 'biyoloji', 'biyoloji - genel', 'matematik'):
                continue

            # baslik'ten yıl ve sınav tipi çek: "SORU 106 | 2024-AYT"
            m = re.search(r'SORU\s+(\d+)\s*\|\s*(\d{4})[-–](AYT|TYT)', r['baslik'] or '')
            if not m:
                # Fallback: içerikten ara
                m = re.search(r'SORU\s+(\d+)\s*\|\s*(\d{4})[-–](AYT|TYT)', r['icerik'] or '')
            if not m:
                continue
            soru_no, yil, sinav = m.group(1), m.group(2), m.group(3)

            if konu_adi not in catalog:
                catalog[konu_adi] = {}
            yil_key = f"{yil}-{sinav}"
            if yil_key not in catalog[konu_adi]:
                catalog[konu_adi][yil_key] = []
            catalog[konu_adi][yil_key].append({
                "soru_no": int(soru_no),
                "kaynak": r['kaynak'],
                "id": r['id'],
            })

        if not catalog:
            return {"sonuc": "Bu konuda cikmis soru bulunamadi."}

        result = []
        for konu_name, yillar in sorted(catalog.items()):
            entry = {"konu": konu_name, "yillar": {}}
            for yil, sorular in sorted(yillar.items(), reverse=True):
                entry["yillar"][yil] = [{"soru_no": s["soru_no"], "kaynak": s["kaynak"]} for s in sorular]
            entry["toplam_soru"] = sum(len(v) for v in yillar.values())
            result.append(entry)

        result.sort(key=lambda x: -x["toplam_soru"])
        return {
            "katalog": result[:10],
            "toplam_konu": len(result),
            "toplam_soru": sum(e["toplam_soru"] for e in result),
            "kullanim": "Ogrenciye yil ve konu secenekleri sun. Sectigi soruyu send_exam_image ile gonder."
        }


async def _tool_build_study_plan(student_id="") -> dict:
    """Çalışma planı için öğrencinin tüm akademik verilerini toplar.

    25.40s — Ezgi vakasi: Bot string ile cagiriyordu (isim/soz_no string),
    cast hatasi -> 3 ekstra tool round-trip. Fix: int CAST + isim fallback.

    student_id: int (soz_no) VEYA string (isim/soz_no string).
    Eger isim verilirse, students tablosunda lookup yapar.
    """
    from study_plan_builder import build_study_plan_context

    # 1) Direkt int veya int'e cast olabilen string
    if isinstance(student_id, int):
        return await build_study_plan_context(student_id)

    s = str(student_id).strip()
    if not s:
        return {"error": "student_id bos. soz_no (int) veya isim string ver."}

    # 2) Sayisal string mi?
    try:
        soz = int(s)
        return await build_study_plan_context(soz)
    except ValueError:
        pass

    # 3) Isim string — students tablosunda lookup
    # Türkçe karakter zorlugu: PG ILIKE Turkish locale yoksa İ vs i ayrı görür.
    # Çözüm: 2 katmanlı arama — (a) tam isim ILIKE (b) ilk kelime ILIKE (c) unaccent
    try:
        from db_pool import db_fetchval
        # (a) Tam isim ILIKE
        soz = await db_fetchval(
            "SELECT soz_no FROM students WHERE full_name ILIKE $1 LIMIT 1",
            f"%{s}%"
        )
        # (b) Türkçe büyük harf normalize: küçük harfe çevir + İ→i, I→ı
        if not soz:
            tr_lower = s.translate(str.maketrans("İIĞŞÜÖÇ", "iığşüöç")).lower()
            soz = await db_fetchval(
                "SELECT soz_no FROM students WHERE LOWER(full_name) LIKE $1 LIMIT 1",
                f"%{tr_lower}%"
            )
        # (c) İlk kelime fallback (ad yeterli olabilir)
        if not soz and " " in s:
            first_word = s.split()[0].translate(str.maketrans("İIĞŞÜÖÇ", "iığşüöç")).lower()
            soz = await db_fetchval(
                "SELECT soz_no FROM students WHERE LOWER(full_name) LIKE $1 LIMIT 1",
                f"%{first_word}%"
            )
        if soz:
            return await build_study_plan_context(int(soz))
        return {"error": f"'{s}' isminde ogrenci bulunamadi. Once query_analytics ile soz_no'yu bul."}
    except Exception as e:
        return {"error": f"Lookup hata: {e}"}


async def tool_get_class_plan(student_id: str = "", date: str = "") -> dict:
    """Ogrenci ders programi + gunluk etut listesi — cakisma kontrolu icin."""
    result: dict[str, Any] = {}

    # Gunluk etut listesi
    if date or not student_id:
        from datetime import date as _d
        target = date or _d.today().strftime("%d.%m.%Y")
        etut_rows = await _db_fetch(
            """SELECT full_name, lesson, target_date, ders_no, teacher, classroom, etut_type
               FROM etut_records WHERE target_date = $1 ORDER BY ders_no""",
            target,
        )
        result["daily_etut"] = etut_rows
        result["etut_date"] = target
        result["etut_count"] = len(etut_rows)

    # Ogrenci ders programi (DB'deki student_timetable tablosundan)
    if student_id:
        # Ogrenciyi bul
        students = await _db_fetch(
            """SELECT eyotek_id, full_name, class_name FROM students
               WHERE eyotek_id = $1 OR full_name ILIKE $2 OR soz_no = $1 LIMIT 1""",
            student_id, f"%{student_id}%",
        )
        if students:
            eid = students[0]["eyotek_id"]
            timetable = await _db_fetch(
                """SELECT gun, ders_no, saat, ders, ogretmen, derslik
                   FROM student_timetable WHERE eyotek_id = $1 ORDER BY gun, ders_no""",
                eid,
            )
            result["student"] = students[0]["full_name"]
            result["timetable"] = timetable
            result["timetable_count"] = len(timetable)

            # Bu ogrencinin mevcut etulerini de getir
            student_etut = await _db_fetch(
                """SELECT lesson, target_date, ders_no, teacher, classroom
                   FROM etut_records WHERE eyotek_id = $1 OR full_name = $2
                   ORDER BY target_date DESC LIMIT 10""",
                eid, students[0]["full_name"],
            )
            result["student_etut"] = student_etut

    if not result:
        result["message"] = "Ogrenci veya tarih belirtilmedi"

    return result


async def _log_eyotek_action(
    phone: str, role: str, action: str,
    params: dict, reason: str, success: bool, result_msg: str,
) -> None:
    """Eyotek aksiyonunu eyotek_action_log tablosuna yaz (hata olsa geçer)."""
    if not DATABASE_URL:
        return
    try:
        await _db_execute(
            """INSERT INTO eyotek_action_log
               (phone, role, action, params, reason, success, result_msg)
               VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7)""",
            phone, role, action,
            json.dumps(params, ensure_ascii=False, default=str),
            reason, success, result_msg[:500],
        )
    except Exception as e:
        logger.warning(f"Aksiyon log yazılamadı: {e}")


async def tool_execute_eyotek_action(
    action: str, params: dict, reason: str,
    _caller_phone: str = "", _caller_role: str = "",
) -> dict:
    """
    Eyotek yazma aksiyonu — EyotekWrapper üzerinden.
    Session gerekli: .eyotek_session.json mevcut olmalı.
    _caller_phone / _caller_role: audit log için FermatCoreAgent tarafından eklenir.
    """
    logger.info(f"🎯 execute_eyotek_action: {action} | Gerekçe: {reason}")
    logger.debug(f"   params: {params}")
    result: dict = {"success": False, "action": action, "reason": reason}

    # ── GUARD: Geçersiz student_id engelle (bot halüsinasyonu önleme) ──
    sid = params.get("student_id", "")
    if sid and sid.lower() in ("system", "admin", "neo", "fermatai", "bot", "claude", "test", ""):
        result["error"] = f"Gecersiz student_id: '{sid}' — gercek ogrenci soz_no veya eyotek_id olmali."
        logger.warning(f"  ⚠ Gecersiz student_id engellendi: {sid}")
        return result

    try:
        # Eyotek erisim kontrolu
        from session_keeper import is_eyotek_available
        if not is_eyotek_available():
            result["message"] = (
                "Eyotek oturumu su an aktif degil. "
                "Yerel veritabanindan yanit veriyorum. "
                "Yazma islemleri icin yoneticinin Eyotek'e giris yapmasi gerekiyor."
            )
            return result

        from eyotek_wrapper import EyotekWrapper, load_session
        cookies = load_session()
        if not cookies:
            result["message"] = "Session bulunamadı — önce eyotek_agent.py çalıştır"
            return result

        # ── GÜVENLİK KİLİDİ ─────────────────────────────────────────────────────
        # Eyotek'e yazma işlemleri öğrenci/veli/öğretmene anlık bildirim gönderir.
        # Gerçek yazma için: params["confirmed"] = True VE params["dry_run"] = False
        # İKİSİ BİRDEN gerekli — kazara yazma önlenir.
        confirmed = bool(params.get("confirmed", False))
        is_dry    = bool(params.get("dry_run", True))  # varsayılan DRY RUN
        if action in ("write_etut", "write_etut_for_class", "write_counsellor_note", "send_sms"):
            if not confirmed or is_dry:
                is_dry = True   # Her durumda dry_run'ı zorla

        async with EyotekWrapper(cookies) as ew:
            if action == "write_etut":
                result = await ew.write_etut(
                    class_name          = params.get("class_name", ""),
                    student_id_or_name  = params.get("student_id_or_name", ""),
                    lesson              = params.get("lesson", ""),
                    target_date         = params.get("target_date", ""),
                    ders_no             = int(params.get("ders_no", 5)),
                    etut_type           = params.get("etut_type", "Etüt"),
                    devre               = params.get("devre", ""),
                    duration            = int(params.get("duration", 35)),
                    repeat              = int(params.get("repeat", 1)),
                    subject_topic       = params.get("subject_topic", ""),
                    classroom           = params.get("classroom", ""),
                    teacher             = params.get("teacher", ""),
                    select_all_in_class = bool(params.get("select_all_in_class", False)),
                    dry_run             = is_dry,
                )
            elif action == "write_etut_for_class":
                result = await ew.write_etut_for_class(
                    class_name    = params.get("class_name", ""),
                    lesson        = params.get("lesson", ""),
                    target_date   = params.get("target_date", ""),
                    ders_no       = int(params.get("ders_no", 5)),
                    etut_type     = params.get("etut_type", "Sınıf Etüdü"),
                    devre         = params.get("devre", ""),
                    duration      = int(params.get("duration", 35)),
                    repeat        = int(params.get("repeat", 1)),
                    subject_topic = params.get("subject_topic", ""),
                    classroom     = params.get("classroom", ""),
                    teacher       = params.get("teacher", ""),
                    dry_run       = is_dry,
                )
            elif action == "write_counsellor_note":
                result = await ew.write_counsellor_note(
                    student_id   = params.get("student_id", ""),
                    note         = params.get("note", ""),
                    note_type    = params.get("note_type", "Genel"),
                    meeting_type = params.get("meeting_type", "Yüz Yüze"),
                    dry_run      = is_dry,
                )
            elif action == "send_sms":
                result = await ew.send_sms(
                    message     = params.get("message", ""),
                    student_ids = params.get("student_ids"),
                    class_name  = params.get("class_name", ""),
                    devre       = params.get("devre", ""),
                    program     = params.get("program", ""),
                    dry_run     = bool(params.get("dry_run", False)),
                )
            else:
                result = {"success": False, "message": f"Bilinmeyen aksiyon: {action}"}

        result["action"] = action
        result["reason"] = reason

    except Exception as e:
        logger.error(f"execute_eyotek_action hatası: {e}")
        # Hata screenshot'i kaydet (debug icin)
        try:
            from datetime import datetime as _dt
            ss_name = f"logs/error_{action}_{_dt.now().strftime('%Y%m%d_%H%M%S')}.png"
            if 'ew' in dir() and hasattr(ew, '_page') and ew._page:
                await ew._page.screenshot(path=ss_name)
                logger.info(f"  Hata screenshot: {ss_name}")
        except Exception:
            pass
        result = {"success": False, "message": str(e), "action": action, "reason": reason}

    # ── Audit log ────────────────────────────────────────────────────────────
    await _log_eyotek_action(
        phone      = _caller_phone,
        role       = _caller_role,
        action     = action,
        params     = params,
        reason     = reason,
        success    = bool(result.get("success")),
        result_msg = result.get("message", str(result.get("success", ""))),
    )
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# ACL — YETKİ SİSTEMİ (22.1n-split: role_access.py modulune tasindi)
# ═══════════════════════════════════════════════════════════════════════════════
#
# Backward compat: eski isimler role_access'ten re-export edilir.
# Kod degisikligi GEREKMEZ — mevcut kullanicilar _ACL_MATRIX, _is_tool_allowed,
# _check_sql_acl gibi isimleri aynen kullanabilir.

from role_access import (
    _ACL_MATRIX, _ELEVATED_ACTIONS, _ELEVATED_ROLES,
    _FORBIDDEN_COLUMNS, _FORBIDDEN_TABLES,
    _is_tool_allowed, _check_sql_acl,
)

# (22.1n-split: 219 satir ACL bloku role_access.py ye tasindi - import yukarida)
async def _tool_eyotek_read(page_key: str = "etut_ara", max_rows: float = 20) -> dict:
    """Eyotek'ten anlık veri oku — CDP ile (basit, sabit kaynak)."""
    from eyotek_knowledge.eyotek_reader import read_eyotek_page
    return await read_eyotek_page(page_key, max_rows=int(max_rows))


async def _tool_sinav_sonuclari(sinav_adi: str, max_rows: float = 100,
                                  date_from_days: float = 30,
                                  _caller_role: str = "admin") -> dict:
    """Bir sınavın TÜM öğrenci sonuçlarını Eyotek'ten anlık çek (drill-down).

    Akış: test-transferred → tarih filtre → liste → ⋯ → Dinamik Liste → tablo.

    Kullanım: 'Apotemi sınav sonuçları', 'son denemenin TYT sonuçları',
    'Bilgi Sarmal TG TYT-3 nasıldı'.

    DB'de sync edilmemiş yeni sınavlar için ÇOK yararlı.
    """
    from eyotek_knowledge.eyotek_navigator import sinav_drilldown
    return await sinav_drilldown(
        sinav_adi=sinav_adi,
        max_rows=int(max_rows) if max_rows else 100,
        date_from_days=int(date_from_days) if date_from_days else 30,
    )


async def _tool_ogrenci_drilldown(student: str, alt_sayfa: str,
                                    max_rows: float = 50,
                                    _caller_role: str = "admin") -> dict:
    """Bir öğrencinin Eyotek profil alt sayfasından veri çek (drill-down).

    Kullanım: tek öğrenci hakkında detaylı bilgi sorulduğunda. Bot ana liste
    sayfasından öğrenciyi bulur, ⋯ menüsünden ilgili alt sayfaya tıklar,
    tabloyu okur.

    Args:
        student: "Mahmut Taha" / "AKKAYA" / "182" (söz_no)
        alt_sayfa: "etut" | "yoklama" | "rehberlik" | "sinav" | "davranis" |
                   "yazili" | "meb_notlari" | "hedef_soru" | "ders_programi" | ...

    🔒 ACL: hassas bilgiler (genel/ozel) admin/mudur, akademik bilgiler
    rehber/ogretmen icin de acik.
    """
    # Hassas alt sayfalar — admin/mudur dısındakilerde reddedilir
    sensitive_pages = ("genel", "ozel", "veli", "odeme", "taksit", "indirim", "borc")
    if any(p in alt_sayfa.lower() for p in sensitive_pages):
        if _caller_role not in ("admin", "mudur"):
            return {
                "success": False,
                "error": f"'{alt_sayfa}' alt sayfasi sadece admin/mudur erisimine acik.",
            }

    from eyotek_knowledge.eyotek_navigator import student_drilldown
    return await student_drilldown(
        student_identifier=student,
        sub_page=alt_sayfa,
        max_rows=int(max_rows) if max_rows else 50,
    )


async def _tool_eyotek_query(question: str, max_rows: float = 0,
                              _caller_role: str = "admin") -> dict:
    """Eyotek'ten AGENTIC sorgulama — Cerebras planner + parametrik navigator.

    Kullanıcı doğal dilde sorduğunda (tarih, öğretmen, ders, sınav adı vb.)
    Cerebras 70B uygun sayfayı + filtreleri seçer, navigator data çeker.

    25.26 mimari: planner (eyotek_planner) → navigator (eyotek_navigator).

    🔒 ACL: Finansal sayfalar (Reports/* + Financial/*) sadece admin/mudur.
    Diger rollerde plan üretildikten sonra check edilir, page_path
    finans ile eslesirse cevap reddedilir.
    """
    from eyotek_knowledge.eyotek_planner import execute_query
    mr = int(max_rows) if max_rows else None
    result = await execute_query(question, max_rows=mr)

    # Finansal sayfa kontrolu — admin/mudur disindaki rollerde reddet
    page = (result.get("page") or result.get("plan", {}).get("page_path") or "").lower()
    is_financial = (
        page.startswith("reports/") or page.startswith("financial/")
        or "balance" in page or "overdue" in page or "fee" in page or "salary" in page
    )
    if is_financial and _caller_role not in ("admin", "mudur"):
        return {
            "success": False,
            "error": "Finansal sayfalar sadece admin/mudur erisimine acik.",
            "plan": result.get("plan"),
            "page": page,
        }

    # 25.40t (Neo direktif 3 May 20:42): LAZY SYNC — eyotek query sonucu
    # mapped page ise DB'ye upsert + data_freshness güncelle.
    # Bot Brief #16 yetersizdi (yeni dosya önerdi), SEN doğru implement:
    # mevcut data_freshness_helper + yeni eyotek_lazy_sync ile.
    try:
        from eyotek_lazy_sync import lazy_sync_after_query
        sync_info = await lazy_sync_after_query(result)
        if sync_info.get("synced"):
            # Result'a sync flag ekle — bot cevapta "DB güncellendi" diyebilir
            result["_lazy_synced"] = sync_info
    except Exception as _ls_err:
        # Lazy sync sessiz fail — query result yine döner
        from loguru import logger as _lg
        _lg.debug(f"  [LAZY_SYNC] hook fail (silent): {_ls_err}")

    return result


async def _tool_calculate_yks_score(
    turkce_net: float = 0, sosyal_net: float = 0,
    matematik_net: float = 0, fen_net: float = 0,
    diploma_notu: float = 80,
) -> dict:
    """YKS TYT puan hesapla — OGM kalibre katsayilar."""
    from puan_hesaplama import hesapla_tyt, net_etkisi
    result = hesapla_tyt(turkce_net, sosyal_net, matematik_net, fen_net, diploma_notu)
    # Net etkisi — hangi derste kaç puan kazanılır
    etkiler = {}
    for ders, net in [("turkce", turkce_net), ("matematik", matematik_net),
                       ("sosyal", sosyal_net), ("fen", fen_net)]:
        max_net = 40 if ders in ("turkce", "matematik") else 20
        kalan = max_net - net
        if kalan > 0:
            ek_3 = min(3, kalan)
            etki = net_etkisi(ders, ek_3, "TYT")
            etkiler[ders] = f"+{ek_3:.0f} net → +{etki:.1f} puan"
    result["net_etkisi"] = etkiler
    return result


# ─── Araç Yönlendirici ────────────────────────────────────────────────────────

async def tool_get_ayt_analysis(soz_no: str) -> str:
    """AYT birlestir analizini dondur — sinav basi ortalama netlerle."""
    import json as _json
    # OTURUM 22.4 (21 Nisan) — inline asyncpg.connect → db_pool (leak safe, pool tabanli)
    from db_pool import get_pool
    _pool = await get_pool()
    async with _pool.acquire() as conn:
        r = await conn.fetchrow("""
            SELECT s.full_name, s.class_name,
                   sea.ham_puan_ayt, sea.yerlesme_puani_ayt,
                   sea.sinav_sayisi_ayt, sea.katilan_sinav_ayt,
                   sea.ders_netleri_ayt, sea.oncelikli_konular_ayt
            FROM student_exam_analysis sea
            LEFT JOIN students s ON s.soz_no::text = sea.soz_no::text
            WHERE sea.soz_no::text = $1
        """, str(soz_no))

    if not r or not r['ham_puan_ayt']:
        return _json.dumps({
            'error': f'Ogrenci {soz_no} icin AYT birlestir verisi yok (sinav_sayisi_ayt<1 veya kayit yok).',
            'oneri': 'Ogrencinin 12.SAY/EA/Mezun degilse AYT girmez. Bu dogal.',
        }, ensure_ascii=False)

    katilan = max(1, r['katilan_sinav_ayt'] or 1)
    netler_raw = r['ders_netleri_ayt']
    if isinstance(netler_raw, str):
        netler_raw = _json.loads(netler_raw)

    # Ortalama netler (sinav basi) — Toplam satirini atla, ayni ders 2x ise MAX soru sec
    by_ders = {}
    for n in netler_raw or []:
        d = (n.get('ders') or '').strip()
        if not d or d.lower() in ('toplam', 'total'):
            continue
        if not (d.startswith('YKS_') or d.startswith('AYT_')):
            continue
        def _pf(v):
            try: return float(str(v).replace(',','.'))
            except: return 0.0
        net = _pf(n.get('net'))
        soru = _pf(n.get('soru'))
        if d not in by_ders or soru > by_ders[d]['soru']:
            by_ders[d] = {'net': net, 'soru': soru}

    ort_netler = {}
    for d, v in by_ders.items():
        ort_netler[d.replace('YKS_','').replace('AYT_','')] = {
            'ortalama_net': round(v['net']/katilan, 2),
            'soru_sayisi': round(v['soru']/katilan, 0),
        }

    return _json.dumps({
        'full_name': r['full_name'],
        'sinif': r['class_name'],
        'sinav_sayisi_ayt': r['sinav_sayisi_ayt'],
        'katilan_sinav': katilan,
        'ham_puan_ayt': r['ham_puan_ayt'],
        'yerlesme_puani_ayt': r['yerlesme_puani_ayt'],
        'ortalama_netler': ort_netler,
        'NOT': 'Netler sinav BASI ORTALAMA (Birlestir analiz: toplam/katilan_sinav). Yerlesme puani RESMI hesap.',
    }, ensure_ascii=False, default=str)


async def _tool_nereye_girebilir(**kwargs):
    """C3 — Öğrenci puanıyla girebileceği bölümler."""
    from puan_tahmin import nereye_girebilir
    return await nereye_girebilir(
        soz_no=kwargs.get("soz_no"),
        puan=kwargs.get("puan"),
        puan_turu=kwargs.get("puan_turu", "SAY"),
        tolerans=kwargs.get("tolerans", 15.0),
    )


async def _tool_hedef_bolum_ara(**kwargs):
    """C3 — Hedef bölümü veren üniversiteler.
    22.1n-neo bugfix: yil/limit/sehir/tur parametreleri eklendi."""
    from puan_tahmin import hedef_bolum_ara
    return await hedef_bolum_ara(
        bolum_adi=kwargs.get("bolum_adi", ""),
        puan_turu=kwargs.get("puan_turu", "SAY"),
        yil=int(kwargs.get("yil") or 2025),
        limit=int(kwargs.get("limit") or 200),
        sehir=kwargs.get("sehir", "") or "",
        tur=kwargs.get("tur", "") or "",
    )


async def _tool_puan_tahmin(**kwargs):
    """22.1n-bug8: Puan tahmin motoru — ogrencinin mevcut trendinden YKS puanini tahmin et."""
    from puan_tahmin import tahmin_et
    soz_no = kwargs.get("soz_no")
    if not soz_no:
        return {"error": "soz_no gerekli"}
    return await tahmin_et(str(soz_no))


async def _tool_counsellor_brief(**kwargs):
    """22.1n-toplanti #4: Rehber brief — tek çağrıda öğrenci özeti + veli mesaj taslağı + öncelikler."""
    from role_briefs import prepare_counsellor_brief
    soz_no = kwargs.get("soz_no")
    if not soz_no:
        return {"error": "soz_no zorunlu"}
    return await prepare_counsellor_brief(int(soz_no))


async def _tool_class_brief(**kwargs):
    """22.1n-toplanti #5: Öğretmen sınıf brief — bugünün dersine hazırlık."""
    from role_briefs import get_class_brief
    sinif = (kwargs.get("sinif") or "").strip()
    if not sinif:
        return {"error": "sinif zorunlu"}
    return await get_class_brief(
        sinif=sinif, ders=kwargs.get("ders", ""),
        tarih=kwargs.get("tarih", "")
    )


async def _tool_branch_zayif_konu(**kwargs):
    """22.1n-neo: Ogretmen brans analiz — sinif geneli ders+konu zayif ortalamalari.
    Merve 65 mesaj orneginden: 8 query_analytics zinciri tek cagriya iniyor.

    Parametre: ders (zorunlu), sinif_list (opsiyonel — ogretmenin girdigi siniflar).
    Cikti: konu bazli ortalama basari, ogrenci bazli net ortalama, zayif olan 5 ogrenci.
    """
    from db_pool import db_fetch
    ders = (kwargs.get("ders") or "").strip()
    if not ders:
        return {"error": "ders zorunlu"}
    sinif_list = kwargs.get("sinif_list") or []
    if isinstance(sinif_list, str):
        sinif_list = [s.strip() for s in sinif_list.split(",") if s.strip()]

    # Konu bazli ortalama basari (topic_tracker)
    try:
        if sinif_list:
            konular = await db_fetch(
                """SELECT t.konu,
                          AVG(t.sinav_hata_yuzdesi)::numeric(10,1) AS ort_basari,
                          COUNT(DISTINCT t.soz_no) AS ogr_sayisi
                   FROM student_topic_tracker t
                   JOIN students s ON s.soz_no::int = t.soz_no
                   WHERE LOWER(t.ders) LIKE LOWER($1)
                     AND s.sube = ANY($2::text[])
                     AND t.sinav_hata_yuzdesi IS NOT NULL
                     AND (t.tamamlandi IS NULL OR t.tamamlandi=FALSE)
                   GROUP BY t.konu
                   ORDER BY ort_basari ASC
                   LIMIT 10""",
                f"%{ders}%", sinif_list
            )
        else:
            konular = await db_fetch(
                """SELECT konu,
                          AVG(sinav_hata_yuzdesi)::numeric(10,1) AS ort_basari,
                          COUNT(DISTINCT soz_no) AS ogr_sayisi
                   FROM student_topic_tracker
                   WHERE LOWER(ders) LIKE LOWER($1)
                     AND sinav_hata_yuzdesi IS NOT NULL
                     AND (tamamlandi IS NULL OR tamamlandi=FALSE)
                   GROUP BY konu
                   ORDER BY ort_basari ASC
                   LIMIT 10""",
                f"%{ders}%"
            )
    except Exception as e:
        return {"error": f"query hata: {e}"}

    # Ogrenci bazli ders ort net (student_exams kolon bazli)
    ders_col_map = {
        "fizik":"fizik","kimya":"kimya","biyoloji":"biyoloji",
        "matematik":"matematik","geometri":"geometri",
        "turkce":"turkce","türkçe":"turkce","edebiyat":"turkce",
        "tarih":"tarih","cografya":"cografya","coğrafya":"cografya",
        "felsefe":"felsefe","din":"din_kulturu",
    }
    ders_l = ders.lower()
    col = None
    for k, v in ders_col_map.items():
        if k in ders_l:
            col = v; break

    ogr_zayif = []
    if col:
        try:
            if sinif_list:
                ogr_zayif = await db_fetch(
                    f"""SELECT e.soz_no, e.student_name,
                             AVG(e.{col})::numeric(10,2) AS ort_net,
                             COUNT(*) AS sinav_sayisi
                        FROM student_exams e
                        JOIN students s ON s.soz_no::int = e.soz_no
                        WHERE e.{col} IS NOT NULL
                          AND s.sube = ANY($1::text[])
                        GROUP BY e.soz_no, e.student_name
                        HAVING COUNT(*) >= 2
                        ORDER BY ort_net ASC
                        LIMIT 5""",
                    sinif_list
                )
            else:
                ogr_zayif = await db_fetch(
                    f"""SELECT soz_no, student_name,
                             AVG({col})::numeric(10,2) AS ort_net,
                             COUNT(*) AS sinav_sayisi
                        FROM student_exams
                        WHERE {col} IS NOT NULL
                        GROUP BY soz_no, student_name
                        HAVING COUNT(*) >= 2
                        ORDER BY ort_net ASC
                        LIMIT 5"""
                )
        except Exception as e:
            pass

    return {
        "ders": ders,
        "sinif_list": sinif_list,
        "konu_zayif_siralamasi": [dict(r) for r in konular] if konular else [],
        "en_zayif_ogrenciler": [dict(r) for r in ogr_zayif] if ogr_zayif else [],
        "yorum": (
            f"{ders} dersinde {len(konular)} konu analizi, "
            f"{len(ogr_zayif)} en zayif ogrenci tespit edildi. "
            "Tek cagriyla sinif brans panorama."
        ),
    }


async def _tool_transfer_failure(**kwargs):
    """22.1n-toplanti #6: Konu başarısı vs sınav başarısı cross — transfer failure tespiti.

    Öğrenci 'test kitabında yapıyorum denemede yapamıyorum' dediğinde bu tool.
    topic_tracker başarısı ile exam net'i karşılaştırır — fark büyükse transfer gap.
    """
    from db_pool import db_fetch, db_fetchrow
    soz_no = kwargs.get("soz_no")
    if not soz_no:
        return {"error": "soz_no zorunlu"}
    try:
        soz_no = int(soz_no)
    except:
        return {"error": "gecersiz soz_no"}

    # Topic tracker başarı (ders bazlı ortalama)
    topic_avg = await db_fetch(
        """SELECT ders, AVG(sinav_hata_yuzdesi)::numeric(10,1) AS ort_basari,
                  COUNT(*) AS konu_sayisi
           FROM student_topic_tracker
           WHERE soz_no=$1 AND sinav_hata_yuzdesi IS NOT NULL
             AND (tamamlandi IS NULL OR tamamlandi=FALSE)
           GROUP BY ders""",
        soz_no
    )

    # Son 5 sınavdaki ders bazlı ortalama net
    exams = await db_fetch(
        """SELECT AVG(matematik)::numeric(10,1) AS mat,
                  AVG(fizik)::numeric(10,1) AS fiz,
                  AVG(kimya)::numeric(10,1) AS kim,
                  AVG(biyoloji)::numeric(10,1) AS bio,
                  AVG(turkce)::numeric(10,1) AS turkce
           FROM (
             SELECT * FROM student_exams
             WHERE soz_no::text=$1 AND status='valid'
             ORDER BY exam_date DESC LIMIT 5
           ) recent""",
        str(soz_no)
    )
    exam_nets = dict(exams[0]) if exams else {}

    # Transfer gap tespiti
    transfer_gaps = []
    ders_to_net_key = {"Matematik":"mat","Geometri":"mat","Fizik":"fiz",
                       "Kimya":"kim","Biyoloji":"bio","Turkce":"turkce","Türkçe":"turkce"}

    for row in topic_avg:
        ders = row["ders"]
        topic_basari = float(row["ort_basari"] or 0)
        if topic_basari < 40: continue  # zaten zayıf, transfer gap değil

        net_key = ders_to_net_key.get(ders)
        if not net_key: continue
        raw_net = exam_nets.get(net_key)
        if raw_net is None: continue
        raw_net = float(raw_net)

        # Max net referansı (TYT'ye göre)
        max_net = {"mat": 30, "fiz": 7, "kim": 7, "bio": 6, "turkce": 40}.get(net_key, 30)
        exam_basari = (raw_net / max_net) * 100 if max_net else 0

        # Gap: topic_basari >> exam_basari
        gap = topic_basari - exam_basari
        if gap > 20:  # %20+ fark = transfer gap
            transfer_gaps.append({
                "ders": ders,
                "konu_basari_pct": round(topic_basari, 1),
                "sinav_basari_pct": round(exam_basari, 1),
                "gap_pct": round(gap, 1),
                "ort_net": round(raw_net, 1),
                "yorum": f"{ders} konularda %{topic_basari:.0f} başarı, sınavda %{exam_basari:.0f} — {round(gap,0)}% transfer gap",
            })

    transfer_gaps.sort(key=lambda x: -x["gap_pct"])
    return {
        "soz_no": soz_no,
        "transfer_gap_sayisi": len(transfer_gaps),
        "tespit_edilen_dersler": transfer_gaps,
        "yorum": (
            "Transfer gap: öğrenci konuyu 'tanıyor' ama sınav koşullarında yapamıyor. "
            "Çözüm: daha fazla süreli deneme, zamana karşı çözüm, yanlış soru defteri analizi."
            if transfer_gaps else
            "Transfer gap yok — konu başarısı ve sınav başarısı uyumlu."
        ),
    }


async def _tool_add_to_student_program(**kwargs):
    """25.14h: Öğrenci Çalışmam panel günlük programa blok ekle.

    ACL: ogrenci sadece kendi soz_no'su; admin/mudur/rehber override izinli.
    Bot ÖNCE öneri sunar ('16:00 Mat ekleyeyim mi?'), öğrenci ONAYLAYINCA çağrılır.
    """
    from datetime import date as _date
    from student_daily import add_daily_program
    caller_soz_no = kwargs.pop("_caller_soz_no", None)
    caller_role = kwargs.pop("_caller_role", "ogrenci")
    soz_no = kwargs.get("soz_no")
    title = kwargs.get("title", "")
    start_time = kwargs.get("start_time", "")
    if not soz_no or not title or not start_time:
        return {"error": "soz_no, title, start_time zorunlu"}
    soz_no = int(soz_no)

    # ACL gate
    if caller_role not in ("admin", "mudur", "rehber"):
        if not caller_soz_no or int(caller_soz_no) != soz_no:
            return {"error": "yetki_yok", "mesaj": "Sadece kendi programina ekleyebilirsin."}

    # plan_date parse
    pd = kwargs.get("plan_date")
    plan_date = None
    if pd:
        try:
            plan_date = _date.fromisoformat(pd)
        except Exception:
            plan_date = None

    try:
        result = await add_daily_program(
            soz_no=soz_no,
            title=title[:200],
            start_time=start_time,
            end_time=kwargs.get("end_time"),
            plan_date=plan_date,
            ders=kwargs.get("ders"),
            konu=kwargs.get("konu"),
            notes=kwargs.get("notes"),
        )
        return {
            "basarili": True,
            "id": result.get("id"),
            "title": result.get("title"),
            "plan_date": result.get("plan_date"),
            "mesaj": f"Programa eklendi: {start_time} {title}",
            "panel_url": f"/student/daily/dashboard?soz_no={soz_no}",
        }
    except Exception as e:
        return {"basarili": False, "error": str(e)[:200]}


async def _tool_plan_kaydet(**kwargs):
    """22.1n-toplanti #2: Çalışma planı kalıcı kaydet.
    Claude plan üretince bu tool ile save_plan — sonraki düzenleme diff olur."""
    from plan_state import save_plan
    soz_no = kwargs.get("soz_no")
    plan_json = kwargs.get("plan_json")
    plan_text = kwargs.get("plan_text", "")
    if not soz_no or not plan_json:
        return {"error": "soz_no ve plan_json zorunlu"}
    ok = await save_plan(
        soz_no=int(soz_no), plan_json=plan_json, plan_text=plan_text,
        hedef_ozet=kwargs.get("hedef_ozet", ""),
        toplam_saat=kwargs.get("toplam_saat"),
    )
    return {"basarili": ok, "mesaj": "Plan kaydedildi" if ok else "Plan kaydedilemedi"}


async def _tool_plan_getir(**kwargs):
    """22.1n-toplanti #2: Aktif plan oku — 'perşembeyi güncelle' tarzı takipte kullan."""
    from plan_state import get_active_plan
    soz_no = kwargs.get("soz_no")
    if not soz_no:
        return {"error": "soz_no zorunlu"}
    p = await get_active_plan(int(soz_no))
    if not p:
        return {"plan_yok": True, "mesaj": "Öğrencinin aktif planı yok. Yeni plan üret (build_study_plan_context)."}
    return p


async def _tool_plan_gun_guncelle(**kwargs):
    """22.1n-toplanti #2: Tek günü güncelle (diff update).
    Eski planın tamamı yeniden yazılmaz, sadece belirtilen gün."""
    from plan_state import update_day, normalize_gun
    soz_no = kwargs.get("soz_no")
    gun = kwargs.get("gun", "")
    yeni_icerik = kwargs.get("yeni_icerik")
    if not soz_no or not gun or not yeni_icerik:
        return {"error": "soz_no, gun, yeni_icerik zorunlu"}
    norm = normalize_gun(gun)
    if not norm:
        return {"error": f"Geçersiz gün: {gun}. pazartesi, salı, ..., pazar kullan."}
    ok = await update_day(int(soz_no), norm, yeni_icerik)
    return {"basarili": ok, "gun": norm}


async def _tool_tercih_listesi(**kwargs):
    """22.1n-toplanti (Bot öneri #3): Otomatik tercih listesi taslağı.

    Öğrencinin mevcut puanına + hedeflerine göre 24 tercihli öneri listesi.
    YÖK Atlas'taki üniversite taban puanları + öğrenci puan tahmini kesişimi.
    Güvenli (-10) + Hedef (±5) + Zorlayıcı (+15) karışımı.
    """
    soz_no = kwargs.get("soz_no")
    puan_turu = (kwargs.get("puan_turu") or "SAY").upper()
    if not soz_no:
        return {"error": "soz_no zorunlu"}
    try:
        soz_no = int(soz_no)
    except (ValueError, TypeError):
        return {"error": "gecersiz soz_no"}

    from db_pool import db_fetch, db_fetchrow

    # Öğrencinin mevcut puanı
    analysis = await db_fetchrow(
        """SELECT yerlesme_puani_ayt
           FROM student_exam_analysis WHERE soz_no::text=$1""",
        str(soz_no)
    )
    if not analysis or not analysis["yerlesme_puani_ayt"]:
        return {"error": "Öğrencinin AYT yerleşme puanı yok. Önce puan_tahmin tool'unu çağır."}

    try:
        mevcut_puan = float(analysis["yerlesme_puani_ayt"])
    except (ValueError, TypeError):
        return {"error": "Puan parse edilemedi"}

    # Puan aralığı: güvenli (-15), hedef (±5), zorlayıcı (+15)
    alt_puan = mevcut_puan - 20
    ust_puan = mevcut_puan + 20

    # YÖK Atlas'tan uygun bölümler
    rows = await db_fetch(
        """SELECT bolum_adi, universite_adi, tur, taban_puani, burs_durumu,
                  yerlesen, kontenjan, ust_siralama
           FROM universite_taban
           WHERE puan_turu = $1
             AND taban_puani BETWEEN $2 AND $3
             AND burs_durumu IN ('burssuz','%25 burslu','%50 burslu','%100 burslu','DEVLET')
           ORDER BY taban_puani DESC
           LIMIT 50""",
        puan_turu, alt_puan, ust_puan,
    )

    if not rows:
        return {"mesaj": f"Puan aralığında ({alt_puan:.0f}-{ust_puan:.0f}) bölüm bulunamadı."}

    # 3 kategoriye ayır
    guvenli = []     # mevcut - 20 to -5 (yüzde 85+ kesinlik)
    hedef = []       # mevcut ± 5 (gerçekçi hedef)
    zorlayici = []   # mevcut + 5 to +20 (push hedef)
    for r in rows:
        tp = float(r["taban_puani"] or 0)
        diff = tp - mevcut_puan
        item = {
            "bolum": r["bolum_adi"],
            "universite": r["universite_adi"],
            "tur": r["tur"],
            "taban": round(tp, 2),
            "burs": r["burs_durumu"],
            "yerlesen": r["yerlesen"],
            "kontenjan": r["kontenjan"],
            "ust_siralama": r["ust_siralama"],
            "risk_seviye": "güvenli" if diff < -5 else ("hedef" if diff < 5 else "zorlayıcı"),
        }
        if diff < -5:
            guvenli.append(item)
        elif diff < 5:
            hedef.append(item)
        else:
            zorlayici.append(item)

    # 24 tercih: 6 zorlayıcı + 12 hedef + 6 güvenli (ideal karışım)
    tercih_listesi = (zorlayici[:6] + hedef[:12] + guvenli[:6])[:24]

    return {
        "soz_no": soz_no,
        "puan_turu": puan_turu,
        "mevcut_puan": round(mevcut_puan, 2),
        "aralik": {"alt": round(alt_puan, 2), "ust": round(ust_puan, 2)},
        "dagilim": {
            "guvenli": len(guvenli[:6]),
            "hedef": len(hedef[:12]),
            "zorlayici": len(zorlayici[:6]),
        },
        "tercih_sayisi": len(tercih_listesi),
        "tercihler": tercih_listesi,
        "hatirlatma": (
            "Bu taslak YÖK Atlas verilerinden. Öğrenciye 'ilk 24 tercih önerin' olarak sun — "
            "ancak tercihin kesin olduğunu söyleme (bölüm/üniversite kişisel tercih). "
            "Zorlayıcı: push hedef (+5 ve üstü). Güvenli: puan düşse bile kazanır."
        )
    }


async def _tool_hedef_puan_analiz(**kwargs):
    """22.1n-bug8: Hedef puan icin gereken netleri hesapla."""
    from puan_tahmin import tahmin_et, hedef_analiz
    soz_no = kwargs.get("soz_no")
    hedef_puan = kwargs.get("hedef_puan")
    alan = kwargs.get("alan", "SAY")
    if not soz_no or not hedef_puan:
        return {"error": "soz_no ve hedef_puan gerekli"}
    tahmin = await tahmin_et(str(soz_no))
    if tahmin.get("error"):
        return tahmin
    try:
        analiz = hedef_analiz(tahmin, float(hedef_puan), alan)
        return {"tahmin": tahmin, "hedef_analiz": analiz}
    except Exception as e:
        return {"error": str(e), "tahmin": tahmin}


async def _tool_ogrenci_peer_kiyas(**kwargs):
    """Oturum 22.1m — Anonim peer benchmark."""
    try:
        from peer_benchmark import ogrenci_peer_kiyas
        soz_no = kwargs.get("soz_no")
        tol = int(kwargs.get("tolerans_net") or 10)
        if not soz_no:
            return {"error": "soz_no zorunlu"}
        return await ogrenci_peer_kiyas(int(soz_no), tol)
    except Exception as e:
        return {"error": f"Peer kiyas hatasi: {e}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 22.1n-neo FINANS TOOLS — SADECE NEO (is_finans_authorized guard PER-TOOL)
# ═══════════════════════════════════════════════════════════════════════════════
# NOT: run_tool dispatch'inde _caller_phone parametresi otomatik enrichment ile
# her finans tool'una gecer. Her wrapper icinde tekrar dogrulama yapilir.

# ═══════════════════════════════════════════════════════════════════════════════
# Oturum 23 split — Finans wrapper'ları → tools/finans.py'ye taşındı
# ═══════════════════════════════════════════════════════════════════════════════
from tools.finans import (
    _tool_finans_ozet,
    _tool_ogrenci_borc_detay,
    _tool_geciken_odemeler,
    _tool_aylik_tahsilat_trend,
    _tool_veli_borc_bildirim_taslak,
    _tool_finans_audit_rapor,
    _tool_sezon_kiyasla,
    _tool_aylik_borc_detay,
    _tool_ogrenci_sezon_gecmisi,
)

# 22.1n-neo FAZ 2 EKSTRA: Üçgen Model (Öğretmen/Veli pedagojik ortak)
# ═══════════════════════════════════════════════════════════════════════════════
# Oturum 23 split — Üçgen/Ödev/Brief/Deep + Kaynak (YouTube/Calendar)
# tools/ogretmen.py + tools/kaynak.py'ye taşındı
# ═══════════════════════════════════════════════════════════════════════════════
from tools.ogretmen import (
    _tool_ogretmen_pedagojik_brief,
    _tool_veli_pedagojik_rehberlik,
    _tool_deep_research_paket,
    _tool_odev_ekle,
    _tool_ogretmen_brief,
)
from tools.kaynak import (
    _tool_youtube_oner,
    _tool_konu_kaynak_paketi,
    _tool_plani_takvime_ekle,
    _tool_etut_takvime_ekle,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Oturum 23 split — Branş öğretmeni tool'ları + Career + Pedagojik şablon
# tools/ogretmen.py + tools/kaynak.py'ye taşındı
# ═══════════════════════════════════════════════════════════════════════════════
from tools.ogretmen import (
    _tool_ogretmen_etut_takvimim,
    _tool_ogretmen_etut_onerisi,
)
# Oturum 23 — 8 yıl konu dağılım raporu (Neo'nun istediği)
async def _tool_ders_konu_dagilimi(**kwargs):
    from ders_konu_dagilimi import konu_dagilimi_raporu
    return await konu_dagilimi_raporu(
        ders=kwargs.get("ders") or "Fizik",
        sinav_turu=kwargs.get("sinav_turu") or "AYT",
        yil_bas=int(kwargs.get("yil_bas") or 2018),
        yil_bit=int(kwargs.get("yil_bit") or 2025),
    )


# Oturum 23 — LGS öğrenci konu durumu (FAZ 1 A2)
async def _tool_lgs_konu_durumu(**kwargs):
    from lgs_helper import get_lgs_konu_durumu
    return await get_lgs_konu_durumu(int(kwargs.get("soz_no") or 0))


from tools.kaynak import (
    _tool_get_career_info,
    _tool_get_pedagojik_sablon,
)


async def _tool_hazirla_etut_talebi(**kwargs):
    """Oturum 22.1l — Öğretmen eskalasyon taslağı."""
    try:
        from teacher_escalation import hazirla_etut_onerisi, kaydet_ogrenci_talep
        soz_no = kwargs.get("soz_no")
        ders = kwargs.get("ders", "")
        note = kwargs.get("note", "")
        if not soz_no or not ders:
            return {"error": "soz_no ve ders parametreleri zorunlu"}
        # Kayit (opsiyonel, fail-safe)
        try:
            await kaydet_ogrenci_talep(int(soz_no), ders, note)
        except Exception:
            pass
        return await hazirla_etut_onerisi(int(soz_no), ders)
    except Exception as e:
        return {"error": f"Etut talebi hazirlik hatasi: {e}"}


async def _tool_get_recent_system_updates(**kwargs):
    """Oturum 22.1h — KALDIGIM.md canli okuma.
    Admin/mudur/yonetim: tam detay; Diger roller: sadece header bilgisi."""
    caller_role = kwargs.get("_caller_role", "")
    max_sessions = min(int(kwargs.get("max_sessions") or 3), 5)
    max_chars = min(int(kwargs.get("max_chars") or 4000), 8000)
    try:
        from system_awareness import get_recent_updates
        result = get_recent_updates(max_sessions=max_sessions, max_chars=max_chars)

        # Teknik detay filtre — sadece admin/mudur/yonetim tam gorur
        if caller_role not in ("admin", "mudur", "yonetim"):
            # Diger roller: sadece bridge versiyonu + son oturum tarihi
            return {
                "info": "Sistem son guncelleme bilgisi",
                "son_guncelleme": result.get("header_info", {}).get("son_guncelleme", "-"),
                "gun": result.get("file_modified_at", "-"),
                "not": "Detaylı teknik gecmis admin erisimindedir.",
            }
        return result
    except Exception as e:
        return {"error": f"Sistem guncelleme okuma hatasi: {e}"}


async def _tool_get_blueprint_section(**kwargs):
    """Oturum 25.29 — BLUEPRINT.md bolum erisimi.

    Bot 'mimari nedir / X nasil calisir / kapasitemiz nedir' soru aldiginda
    BLUEPRINT.md'den ilgili bolumu canli okur. Atlas advisor da yeni oneri
    vermeden once bu tool'la mimari kararin var olup olmadigini kontrol eder.
    """
    section = kwargs.get("section", "")
    caller_role = kwargs.get("_caller_role", "")
    if not section:
        # Default: section listesi
        try:
            from blueprint_awareness import list_blueprint_sections
            sections = list_blueprint_sections()
            return {
                "info": "BLUEPRINT.md tum bolumler (detay icin section parametresi ver)",
                "sections": [{"num": s["num"], "title": s["title"]} for s in sections],
                "ornek": "section=3 veya section='LLM Routing'",
            }
        except Exception as e:
            return {"error": str(e)[:200]}

    try:
        from blueprint_awareness import get_blueprint_section, search_blueprint
        # Numerik mi yoksa keyword mu?
        try:
            sec_num = int(section)
            result = get_blueprint_section(sec_num)
        except (ValueError, TypeError):
            result = get_blueprint_section(str(section))

        if result:
            # Diger roller icin trim — admin/mudur/yonetim tam icerik gorur
            if caller_role not in ("admin", "mudur", "yonetim", "rehber"):
                # Sadece basligi + ilk 800 karakter
                content = result["content"][:800] + "\n[... detay yonetim erisiminde]"
                return {
                    "num": result["num"],
                    "title": result["title"],
                    "preview": content,
                    "not": "Tam icerik yonetim erisimine acik.",
                }
            return {
                "num": result["num"],
                "title": result["title"],
                "content": result["content"][:5000],
                "char_count": result["char_count"],
            }
        # Bulamadi → search
        hits = search_blueprint(section, max_results=3)
        if hits:
            return {
                "info": f"'{section}' bolum olarak bulunamadi, keyword araamasi yapildi",
                "hits": [
                    {"num": h["num"], "title": h["title"], "snippet": h["snippet"][:300]}
                    for h in hits
                ],
            }
        return {"error": f"'{section}' icin bolum/keyword bulunamadi"}
    except Exception as e:
        return {"error": f"BLUEPRINT okuma hatasi: {e}"}


async def _tool_get_atlas_trend(**kwargs):
    """Oturum 22.1 — Atlas trend raporu.
    SADECE admin (Neo) — sistem self-observation verisi, mudur/yonetim dahil kapali.
    Aynı kategori: alert_log, usage_log, routing_stats, admin_talimat (Neo-ozel)."""
    caller_role = kwargs.get("_caller_role", "")
    caller_phone = kwargs.get("_caller_phone", "")
    NEO_PHONE = "905051256802"
    # Cift katman: role=admin VE Neo telefonu
    if caller_role != "admin" or (caller_phone and caller_phone != NEO_PHONE):
        return {"error": "Yetkisiz. Atlas trend sistem self-observation verisi — sadece Neo."}
    try:
        from atlas_lifecycle import get_trend
        days = int(kwargs.get("days") or 30)
        return await get_trend(days=days)
    except Exception as e:
        return {"error": f"Atlas trend hatasi: {e}"}


# ─────────────────────────────────────────────────────────────────────
# Oturum 25.39 (Neo direktif): Tools array cache_control helper
# ─────────────────────────────────────────────────────────────────────
def _add_tools_cache_control(tools: list[dict]) -> list[dict]:
    """Tools listesinin SON tool'una cache_control: ephemeral ekler.

    Anthropic API: tools array'ında son tool'un cache_control'ü tüm tools
    listesini cache'ler (5 dakika TTL). Statik kısımdır, role değişmediği
    sürece HER mesajda HIT olur.

    Maliyet: ilk çağrıda ~24K token CACHE WRITE (1.25x = ~$0.09)
             sonraki çağrılarda CACHE READ (0.10x = ~$0.0024)
             → 2. mesajdan itibaren %92 tasarruf.
    """
    if not tools or not isinstance(tools, list):
        return tools
    # Son tool'a cache_control ekle (kopya üzerinde — orijinal TOOLS bozulmasın)
    cached = list(tools[:-1])
    last_tool = dict(tools[-1])  # shallow copy
    last_tool["cache_control"] = {"type": "ephemeral"}
    cached.append(last_tool)
    return cached


def _build_system_blocks(
    v3_blocks: Optional[list],
    fallback_prompt: str,
    dynamic_context: str,
) -> list[dict]:
    """Anthropic API system parametresini hierarchical cache_control bloklarıyla inşa eder.

    25.40z3 Cache: V3 enabled iken composer_v3 BASE+modüller şeklinde 1-4 blok döner.
    Buna dynamic_context'i ekleyerek toplam 2-5 blok elde ederiz. Anthropic max 4
    cache_control breakpoint izin verir (tools 4. breakpoint'i alır), bu yüzden
    system tarafında MAX 3 cache_control izin var.

    Strateji:
      - V3 yok (None/[]): legacy 2-block (prompt + dynamic_context) → 2 cache breakpoint
      - V3 var, 1 blok (sadece BASE): [BASE_cached, dynamic_cached] → 2 breakpoint
      - V3 var, 2 blok (BASE + 1 extra): [BASE_cached, extra_cached, dynamic_cached] → 3 breakpoint
      - V3 var, 3+ blok (BASE + 2-3 extra): BASE_cached + extras_combined_cached + dynamic_cached → 3 breakpoint

    Garantiler:
      - Toplam ≤3 system breakpoint (tools için 1 yer kalsın)
      - BASE her zaman ayrı blok (en uzun, en stabil — 5dk TTL'in en büyük getiri kaynağı)
      - dynamic_context her zaman SON blok (per-user değişken, en kısa TTL hedefi)
      - V3 fallback olduysa legacy davranışı bozmadan devam eder
    """
    if not v3_blocks or not isinstance(v3_blocks, list):
        # Legacy 2-block (V2 veya V3 fallback)
        return [
            {"type": "text", "text": fallback_prompt,
             "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": dynamic_context,
             "cache_control": {"type": "ephemeral"}},
        ]

    # V3 hierarchical
    if len(v3_blocks) == 1:
        # Sadece BASE → BASE + dynamic_context (2 breakpoint)
        return [
            {"type": "text", "text": v3_blocks[0]["text"],
             "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": dynamic_context,
             "cache_control": {"type": "ephemeral"}},
        ]

    if len(v3_blocks) == 2:
        # BASE + 1 extra → 3 breakpoint (BASE, extra, dynamic)
        return [
            {"type": "text", "text": v3_blocks[0]["text"],
             "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": v3_blocks[1]["text"],
             "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": dynamic_context,
             "cache_control": {"type": "ephemeral"}},
        ]

    # 3+ blok → BASE ayrı, extras concat, dynamic ayrı = 3 breakpoint
    base_text = v3_blocks[0]["text"]
    extras_text = "".join(b["text"] for b in v3_blocks[1:])
    return [
        {"type": "text", "text": base_text,
         "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": extras_text,
         "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": dynamic_context,
         "cache_control": {"type": "ephemeral"}},
    ]


def _build_claude_request_params(
    v3_blocks: Optional[list],
    claude_prompt: str,
    dynamic_context: str,
    claude_tools: list,
    model: str,
    messages: list,
    max_tokens: int = 24576,
) -> dict:
    """Claude API request params (stream + sync ortak) — DRY consolidation.

    25.40z3-MIMARI #6: Stream ve sync path aynı params'i üretiyordu, 2 yerde
    duplicate logic vardı. Bu helper iki path'in tek kaynaktan params almasını
    sağlar — gelecek değişikliklerde sadece BURASI güncellenir.

    Returns: messages.create / messages.stream'e direkt verilebilir dict.
    """
    cached_tools = _add_tools_cache_control(claude_tools)
    system_blocks = _build_system_blocks(v3_blocks, claude_prompt, dynamic_context)
    params = dict(
        model=model,
        max_tokens=max_tokens,  # Sonnet 4.5 max 64K, biz 24K (latency vs kapasite)
        system=system_blocks,
        tools=cached_tools,
        messages=messages,
    )
    # LIGHT tier'da tools=[] → SDK reddeder, parametreyi cikar
    if not cached_tools:
        params.pop("tools", None)
    return params


TOOL_DISPATCH = {
    "get_student_analytics":    lambda p: tool_get_student_analytics(**p),
    "get_ayt_analysis":         lambda p: tool_get_ayt_analysis(**p),
    "check_teacher_availability": lambda p: tool_check_teacher_availability(**p),
    "execute_eyotek_action":    lambda p: tool_execute_eyotek_action(**p),
    "get_class_summary":        lambda p: tool_get_class_summary(**p),
    "search_students":          lambda p: tool_search_students(**p),
    "get_class_plan":           lambda p: tool_get_class_plan(**p),
    "build_study_plan_context": lambda p: _tool_build_study_plan(**p),
    "search_curriculum":        lambda p: _tool_search_curriculum(**p),
    "ogm_yonlendir":            lambda p: _tool_ogm_yonlendir(**p),
    "send_exam_image":          lambda p: _tool_send_exam_image(**p),
    "list_exam_questions":      lambda p: _tool_list_exam_questions(**p),
    "query_analytics":          lambda p: tool_query_analytics(**p),
    "calculate_yks_score":      lambda p: _tool_calculate_yks_score(**p),
    "eyotek_read":              lambda p: _tool_eyotek_read(**p),
    "eyotek_query":             lambda p: _tool_eyotek_query(**p),
    "ogrenci_drilldown":        lambda p: _tool_ogrenci_drilldown(**p),
    "sinav_sonuclari":          lambda p: _tool_sinav_sonuclari(**p),
    # C3 (Oturum 22) — Yokatlas tabanli puan tahmin
    "ogrenci_nereye_girebilir": lambda p: _tool_nereye_girebilir(**p),
    "hedef_bolum_ara":          lambda p: _tool_hedef_bolum_ara(**p),
    "puan_tahmin":              lambda p: _tool_puan_tahmin(**p),
    "hedef_puan_analiz":        lambda p: _tool_hedef_puan_analiz(**p),
    # 25.14h — Calismam programa yazma (ACL ile)
    "add_to_student_program":   lambda p: _tool_add_to_student_program(**p),
    # 22.1n-toplanti: plan state (diff update, yaz kampi icin kritik)
    "plan_kaydet":              lambda p: _tool_plan_kaydet(**p),
    "plan_getir":               lambda p: _tool_plan_getir(**p),
    "plan_gun_guncelle":        lambda p: _tool_plan_gun_guncelle(**p),
    # 22.1n-toplanti: rehber + ogretmen brief + transfer failure
    "counsellor_brief":         lambda p: _tool_counsellor_brief(**p),
    "class_brief":              lambda p: _tool_class_brief(**p),
    "transfer_failure_analiz":  lambda p: _tool_transfer_failure(**p),
    "branch_zayif_konu":        lambda p: _tool_branch_zayif_konu(**p),
    "tercih_listesi_tasla":     lambda p: _tool_tercih_listesi(**p),
    # Oturum 22.1 — Atlas self-observing trend
    "get_atlas_trend":          lambda p: _tool_get_atlas_trend(**p),
    # Oturum 22.1h — System self-awareness (KALDIGIM canli)
    "get_recent_system_updates": lambda p: _tool_get_recent_system_updates(**p),
    # Oturum 25.29: BLUEPRINT.md bolum erisimi (mimari farkindalik)
    "get_blueprint_section": lambda p: _tool_get_blueprint_section(**p),
    # Oturum 22.1l — Öğretmen eskalasyon chain
    "hazirla_etut_talebi":      lambda p: _tool_hazirla_etut_talebi(**p),
    # Oturum 22.1m — Peer benchmark (anonim)
    "ogrenci_peer_kiyas":       lambda p: _tool_ogrenci_peer_kiyas(**p),
    # 22.1n-neo FINANS TOOLS — Neo-only (is_finans_authorized guard per tool)
    "finans_ozet":              lambda p: _tool_finans_ozet(**p),
    "ogrenci_borc_detay":       lambda p: _tool_ogrenci_borc_detay(**p),
    "geciken_odemeler":         lambda p: _tool_geciken_odemeler(**p),
    "aylik_tahsilat_trend":     lambda p: _tool_aylik_tahsilat_trend(**p),
    "veli_borc_bildirim_taslak": lambda p: _tool_veli_borc_bildirim_taslak(**p),
    "finans_audit_rapor":       lambda p: _tool_finans_audit_rapor(**p),
    "sezon_kiyasla":            lambda p: _tool_sezon_kiyasla(**p),
    "aylik_borc_detay":         lambda p: _tool_aylik_borc_detay(**p),
    "ogrenci_sezon_gecmisi":    lambda p: _tool_ogrenci_sezon_gecmisi(**p),
    # 22.1n-neo FAZ 2 EKSTRA
    "ogretmen_pedagojik_brief":   lambda p: _tool_ogretmen_pedagojik_brief(**p),
    "veli_pedagojik_rehberlik":   lambda p: _tool_veli_pedagojik_rehberlik(**p),
    "get_pedagojik_sablon":       lambda p: _tool_get_pedagojik_sablon(**p),
    "get_career_info":            lambda p: _tool_get_career_info(**p),
    "deep_research_paket":        lambda p: _tool_deep_research_paket(**p),
    "odev_ekle":                  lambda p: _tool_odev_ekle(**p),
    "ogretmen_brief":             lambda p: _tool_ogretmen_brief(**p),
    # 25.40z-Neo: youtube_oner alias → find_youtube_lesson (tool listesinden kaldirildi)
    "youtube_oner":               lambda p: _tool_find_youtube(**p),
    "konu_kaynak_paketi":         lambda p: _tool_konu_kaynak_paketi(**p),
    "plani_takvime_ekle":         lambda p: _tool_plani_takvime_ekle(**p),
    "etut_takvime_ekle":          lambda p: _tool_etut_takvime_ekle(**p),
    # 23 Nisan — Branş öğretmeni yetki düzeltmesi
    "ogretmen_etut_takvimim":     lambda p: _tool_ogretmen_etut_takvimim(**p),
    "ogretmen_etut_onerisi":      lambda p: _tool_ogretmen_etut_onerisi(**p),
    # 23 Nisan — 8 yıllık konu dağılım raporu (Neo 18:20 istemişti)
    "ders_konu_dagilimi_raporu":  lambda p: _tool_ders_konu_dagilimi(**p),
    # 23 Nisan — LGS öğrenci konu durumu (LGS 7 Haziran, 45 gün)
    "get_lgs_konu_durumu":        lambda p: _tool_lgs_konu_durumu(**p),
    # 23 Nisan — Tercih Robotu (YKS sonrası dönem modu)
    "tercih_profili_kaydet":      lambda p: _tool_tercih_profili_kaydet(**p),
    "tercih_profili_getir":       lambda p: _tool_tercih_profili_getir(**p),
    "tercih_listesi_uret":        lambda p: _tool_tercih_listesi_uret(**p),
    "bolum_karsilastir":          lambda p: _tool_bolum_karsilastir(**p),
    "tercih_donemi_durum":        lambda p: _tool_tercih_donemi_durum(**p),
    # 25.40k (Neo) — sezon-bagimsiz YOK Atlas dispatch
    "universite_taban_sorgu":     lambda p: _tool_universite_taban_sorgu(**p),
    "siralama_ile_bolumler":      lambda p: _tool_siralama_ile_bolumler(**p),
    # ── Oturum 25.9 — ADAPTIVE INTELLIGENCE / PREDICTIVE / KG ──
    "predict_yks_score":          lambda p: _tool_predict_yks_score(**p),
    "get_adaptive_summary":       lambda p: _tool_get_adaptive_summary(**p),
    "get_knowledge_graph":        lambda p: _tool_get_knowledge_graph(**p),
    "observe_student_answer":     lambda p: _tool_observe_student_answer(**p),
    # ── Oturum 25.12 — OGRENCI GUNLUK TAKIP (GRAFEN) ──
    "get_student_daily_summary":  lambda p: _tool_get_student_daily_summary(**p),
    "analyze_student_study_pattern": lambda p: _tool_analyze_student_study_pattern(**p),
    # ── Oturum 25.29 — SELF-DEV PIPELINE (Evre 1: read + brief) ──
    # Sadece admin (Neo). ACL fermat_core_agent.run() icinde kontrol edilir.
    "selfdev_read_file":          lambda p: _selfdev_read_file_w(**p),
    "selfdev_list_dir":           lambda p: _selfdev_list_dir_w(**p),
    "selfdev_grep_repo":          lambda p: _selfdev_grep_repo_w(**p),
    "selfdev_read_logs":          lambda p: _selfdev_read_logs_w(**p),
    "selfdev_git_diff":           lambda p: _selfdev_git_diff_w(**p),
    "selfdev_git_log":            lambda p: _selfdev_git_log_w(**p),
    "selfdev_git_blame":          lambda p: _selfdev_git_blame_w(**p),
    "selfdev_search_atlas_history": lambda p: _selfdev_atlas_history_w(**p),
    "selfdev_write_brief":        lambda p: _selfdev_write_brief_w(**p),
    "selfdev_list_briefs":        lambda p: _selfdev_list_briefs_w(**p),
    "selfdev_get_brief":          lambda p: _selfdev_get_brief_w(**p),
    # Evre 2.1 — Draft sandbox write
    "selfdev_apply_brief":        lambda p: _selfdev_apply_brief_w(**p),
    "selfdev_list_drafts":        lambda p: _selfdev_list_drafts_w(**p),
    "selfdev_read_draft":         lambda p: _selfdev_read_draft_w(**p),
    "selfdev_delete_draft":       lambda p: _selfdev_delete_draft_w(**p),
    # Evre 2.2 — Git branch + commit + push (push flag-gated)
    "selfdev_draft_to_local_branch": lambda p: _selfdev_draft_to_branch_w(**p),
    "selfdev_push_branch":         lambda p: _selfdev_push_branch_w(**p),
    "selfdev_list_bot_branches":   lambda p: _selfdev_list_branches_w(**p),
    "selfdev_branch_status":       lambda p: _selfdev_branch_status_w(**p),
    "selfdev_delete_branch":       lambda p: _selfdev_delete_branch_w(**p),
    # Evre 2.3 — GitHub PR Draft (token gerek, graceful skip)
    "selfdev_create_pr_draft":     lambda p: _selfdev_create_pr_w(**p),
    "selfdev_get_pr_status":       lambda p: _selfdev_get_pr_w(**p),
    "selfdev_pr_comment":          lambda p: _selfdev_pr_comment_w(**p),
    "selfdev_close_pr":            lambda p: _selfdev_close_pr_w(**p),
    "selfdev_full_pipeline":       lambda p: _selfdev_full_pipeline_w(**p),
    # Oturum 25.31 (Neo) — Render endpoint: bot ozel HTML uretirse kalici link
    "make_render_link":            lambda p: _tool_make_render_link(**p),
    # 25.40p (Neo direktif): 3D Three.js template tool
    "make_3d_template":            lambda p: _tool_make_3d_template(**p),
    # Oturum 25.32 (Neo) — 5 yeni external API tool
    "nasa_apod":                   lambda p: _tool_nasa_apod(**p),
    "nasa_image_search":           lambda p: _tool_nasa_image_search(**p),
    "wolfram_query":               lambda p: _tool_wolfram_query(**p),
    "wolfram_full":                lambda p: _tool_wolfram_full(**p),
    "wiki_lookup":                 lambda p: _tool_wiki_lookup(**p),
    "arxiv_search":                lambda p: _tool_arxiv_search(**p),
    "generate_image":              lambda p: _tool_generate_image(**p),
    # Oturum 25.33 (Neo) — 3 yeni external API tool
    "pubchem_lookup":              lambda p: _tool_pubchem_lookup(**p),
    "usgs_earthquakes":            lambda p: _tool_usgs_earthquakes(**p),
    "generate_pdf":                lambda p: _tool_generate_pdf(**p),
    # Oturum 25.34 (Neo) — TTS + PDB + Heatmap dashboard
    "text_to_speech":              lambda p: _tool_text_to_speech(**p),
    "pdb_lookup":                  lambda p: _tool_pdb_lookup(**p),
    "student_heatmap":             lambda p: _tool_student_heatmap(**p),
    # Oturum 25.34 (Neo bug-fix paketi) — Code execution + Suno
    "execute_python":              lambda p: _tool_execute_python(**p),
    "suno_generate":               lambda p: _tool_suno_generate(**p),
    # Oturum 25.37 (Neo) — Davranış kuralı yönetimi (admin only)
    "add_behavior_rule":           lambda p: _tool_add_behavior_rule(**p),
    "list_behavior_rules":         lambda p: _tool_list_behavior_rules(**p),
    "deactivate_behavior_rule":    lambda p: _tool_deactivate_behavior_rule(**p),
    # Oturum 25.37 (Neo) — Active Recall + Knowledge Graph
    "schedule_recall":             lambda p: _tool_schedule_recall(**p),
    "get_pending_recalls":         lambda p: _tool_get_pending_recalls(**p),
    "build_knowledge_graph":       lambda p: _tool_build_knowledge_graph(**p),
    # Oturum 25.38 (Neo) — PhET + YouTube + Anki + Wolfram step-by-step
    "search_phet_simulation":      lambda p: _tool_search_phet(**p),
    "embed_phet_simulation":       lambda p: _tool_embed_phet(**p),
    "find_youtube_lesson":         lambda p: _tool_find_youtube(**p),
    "export_anki_deck":            lambda p: _tool_export_anki(**p),
    "wolfram_step_by_step":        lambda p: _tool_wolfram_step_by_step(**p),
}


# ── Oturum 25.34 (paket 2) — Code + Suno wrapperlari ──
async def _tool_execute_python(code: str = "", timeout: int = 5, **_extra) -> dict:
    try:
        from external_apis_v2 import execute_python
        r = await execute_python(code=code, timeout=int(timeout or 5))
        # Yardımcı: bot ```codeout block'unu doğrudan dönderelim
        if r.get("success") or r.get("stdout") or r.get("stderr"):
            import json as _j
            r["codeout_block"] = (
                "```codeout\n"
                + _j.dumps({
                    "title": "Python Çıktı",
                    "code": code[:2000],
                    "stdout": r.get("stdout", ""),
                    "stderr": r.get("stderr", ""),
                    "success": r.get("success", False),
                }, ensure_ascii=False)
                + "\n```"
            )
            r["kullanim"] = "codeout_block alanini direkt cevabina yapistir"
        return r
    except Exception as e:
        return {"success": False, "error": str(e)}

async def _tool_suno_generate(prompt: str = "", style: str = "educational", **_extra) -> dict:
    try:
        from external_apis_v2 import suno_generate
        return await suno_generate(prompt=prompt, style=style)
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Oturum 25.37 — Davranış kuralı yönetimi (admin only) ──
async def _tool_add_behavior_rule(rule_text: str = "", scope: str = "global",
                                   category: str = "misc", priority: int = 5,
                                   ttl_hours: int = 0, _caller_phone: str = "",
                                   _caller_role: str = "", **_extra) -> dict:
    """Yeni davranış kuralı ekle (DB'ye yaz, prompt'a inject olur)."""
    if _caller_role not in ("admin", "mudur"):
        return {"success": False, "error": "Bu komutu sadece admin/mudur kullanabilir"}
    try:
        from behavior_rules import add_rule
        from datetime import datetime, timedelta
        expires = None
        if ttl_hours and int(ttl_hours) > 0:
            expires = datetime.now() + timedelta(hours=int(ttl_hours))
        return await add_rule(
            rule_text=rule_text, scope=scope, category=category,
            priority=int(priority or 5), expires_at=expires,
            created_by=_caller_phone or ""
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _tool_list_behavior_rules(scope_filter: str = "", category_filter: str = "",
                                      only_active: bool = True, limit: int = 50,
                                      _caller_role: str = "", **_extra) -> dict:
    if _caller_role not in ("admin", "mudur"):
        return {"success": False, "error": "Sadece admin/mudur"}
    try:
        from behavior_rules import list_rules
        rows = await list_rules(scope_filter=scope_filter, category_filter=category_filter,
                                 only_active=bool(only_active), limit=int(limit or 50))
        return {"success": True, "rules": rows, "count": len(rows)}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _tool_deactivate_behavior_rule(rule_id: int = 0, _caller_role: str = "", **_extra) -> dict:
    if _caller_role not in ("admin", "mudur"):
        return {"success": False, "error": "Sadece admin/mudur"}
    try:
        from behavior_rules import deactivate_rule
        return await deactivate_rule(int(rule_id or 0))
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Oturum 25.37 — Active Recall (Ebbinghaus eğrisi) ──
async def _tool_schedule_recall(soz_no: int = 0, konu: str = "", ders: str = "",
                                  context_summary: str = "", recall_at: str = "",
                                  _caller_phone: str = "", _caller_soz_no: int = 0,
                                  **_extra) -> dict:
    """Öğrenciye N saat sonra konu hatırlatması planla."""
    try:
        from active_recall import schedule_recall
        if not soz_no and _caller_soz_no:
            soz_no = _caller_soz_no
        return await schedule_recall(
            soz_no=int(soz_no or 0), konu=konu[:120], ders=ders[:60],
            context_summary=context_summary[:500],
            recall_after_hours=24  # default 24h, ileri tarihte spaced reps
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _tool_get_pending_recalls(soz_no: int = 0, _caller_role: str = "",
                                      _caller_soz_no: int = 0, **_extra) -> dict:
    try:
        from active_recall import get_pending_recalls
        target = int(soz_no or _caller_soz_no or 0)
        if _caller_role == "ogrenci" and target != _caller_soz_no:
            target = _caller_soz_no
        rows = await get_pending_recalls(target)
        return {"success": True, "recalls": rows, "count": len(rows)}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _tool_build_knowledge_graph(soz_no: int = 0, _caller_soz_no: int = 0,
                                        _caller_role: str = "", **_extra) -> dict:
    """D3.js kgraph data + ```kgraph render block."""
    try:
        from knowledge_graph import build_graph_for_student
        target = int(soz_no or _caller_soz_no or 0)
        if _caller_role == "ogrenci" and target != _caller_soz_no:
            target = _caller_soz_no
        if not target:
            return {"success": False, "error": "soz_no gerekli"}
        return await build_graph_for_student(target)
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Oturum 25.34 — TTS + PDB + Heatmap wrapperlari ──
async def _tool_text_to_speech(text: str = "", voice: str = "nova",
                                provider: str = "auto", **_extra) -> dict:
    try:
        from external_apis_v2 import text_to_speech
        r = await text_to_speech(text=text, voice=voice, provider=provider)
        if r.get("success") and r.get("audio_filename"):
            import os
            base = os.getenv("PUBLIC_BASE_URL", "https://api.fermategitimkurumlari.com").rstrip("/")
            r["audio_url"] = f"{base}/audio/{r['audio_filename']}"
            r["kullanim"] = f"Cevabina '🔊 [Sesli dinle]({r['audio_url']})' linkini ekle"
        return r
    except Exception as e:
        return {"success": False, "error": str(e)}

async def _tool_pdb_lookup(pdb_id: str = "", **_extra) -> dict:
    try:
        from external_apis_v2 import pdb_lookup
        return await pdb_lookup(pdb_id=pdb_id)
    except Exception as e:
        return {"success": False, "error": str(e)}

async def _tool_student_heatmap(soz_no_list: list = None, ders: str = "",
                                  weeks: int = 8, _caller_role: str = "ogrenci",
                                  _caller_phone: str = "", **_extra) -> dict:
    """Öğrenci × konu performans heatmap — sınıf karşılaştırma.

    Sadece öğretmen+ rol görür (ACL). Sonuç ```heatmap renderer formatında.
    """
    try:
        if _caller_role not in ("admin", "mudur", "ogretmen", "rehber"):
            return {"success": False, "error": "Bu tool sadece öğretmen+ icin"}
        from db_pool import db_fetch
        if not soz_no_list:
            return {"success": False, "error": "soz_no_list gerekli (orn: [137, 138, 139])"}
        # Öğrenci adları + konu × öğrenci hata yüzdesi matrisi
        rows = await db_fetch(
            f"""SELECT s.full_name, t.konu, ROUND(AVG(t.hata_yuzdesi)::numeric, 0) as avg_hata
                FROM students s
                JOIN student_topic_tracker t ON s.soz_no::text = t.soz_no::text
                WHERE s.soz_no = ANY($1::int[])
                  AND ($2 = '' OR t.ders = $2)
                  AND t.created_at > NOW() - INTERVAL '{int(weeks or 8)} weeks'
                GROUP BY s.full_name, t.konu
                ORDER BY t.konu, s.full_name""",
            [int(x) for x in soz_no_list], ders
        )
        if not rows:
            return {"success": False, "error": "Veri yok (öğrenciler veya ders eşleşmiyor)"}
        # Pivot: y=konu, x=öğrenci, value=hata%
        students = sorted({r["full_name"] for r in rows})
        konular = sorted({r["konu"] for r in rows})
        matrix = [[0 for _ in students] for _ in konular]
        for r in rows:
            yi = konular.index(r["konu"])
            xi = students.index(r["full_name"])
            matrix[yi][xi] = int(r["avg_hata"] or 0)
        # ```heatmap formatında dön
        return {
            "success": True,
            "students": students,
            "konular": konular,
            "matrix": matrix,
            "ders_filter": ders or "tüm dersler",
            "weeks": int(weeks or 8),
            "heatmap_block": (
                "```heatmap\n"
                + json.dumps({
                    "title": f"{ders or 'Tüm Dersler'} — Konu × Öğrenci Hata Haritası ({weeks} hafta)",
                    "x": [s.split()[0] for s in students],  # ilk ad (kısalt)
                    "y": konular,
                    "values": matrix,
                }, ensure_ascii=False)
                + "\n```"
            ),
            "kullanim": "heatmap_block alanini direkt cevabina yapistir, frontend render eder",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Oturum 25.33 — 3 yeni external API wrapper ──
async def _tool_pubchem_lookup(name: str = "", **_extra) -> dict:
    try:
        from external_apis_v2 import pubchem_lookup
        return await pubchem_lookup(name=name)
    except Exception as e:
        return {"success": False, "error": str(e)}

async def _tool_usgs_earthquakes(min_magnitude: float = 4.5, max_results: int = 10, **_extra) -> dict:
    try:
        from external_apis_v2 import usgs_earthquakes
        return await usgs_earthquakes(min_magnitude=float(min_magnitude or 4.5),
                                       max_results=int(max_results or 10))
    except Exception as e:
        return {"success": False, "error": str(e)}

async def _tool_generate_pdf(html_content: str = "", title: str = "FermatAI Rapor", **_extra) -> dict:
    try:
        from external_apis_v2 import generate_pdf
        r = await generate_pdf(html_content=html_content, title=title)
        if r.get("success") and r.get("pdf_filename"):
            import os
            base = os.getenv("PUBLIC_BASE_URL", "https://api.fermategitimkurumlari.com").rstrip("/")
            r["pdf_url"] = f"{base}/pdfs/{r['pdf_filename']}"
            r["kullanim"] = f"Cevabina '📄 [PDF indir]({r['pdf_url']})' linkini ekle"
        return r
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Oturum 25.32 — External API tool wrapperları ──
async def _tool_nasa_apod(query_date: str = "", **_extra) -> dict:
    try:
        from external_apis_v2 import nasa_apod
        return await nasa_apod(query_date=query_date)
    except Exception as e:
        return {"success": False, "error": str(e)}

async def _tool_nasa_image_search(query: str = "", page: int = 1, **_extra) -> dict:
    try:
        from external_apis_v2 import nasa_image_search
        return await nasa_image_search(query=query, page=int(page or 1))
    except Exception as e:
        return {"success": False, "error": str(e)}

async def _tool_wolfram_query(query: str = "", **_extra) -> dict:
    try:
        from external_apis_v2 import wolfram_query
        return await wolfram_query(query=query)
    except Exception as e:
        return {"success": False, "error": str(e)}

async def _tool_wolfram_full(query: str = "", **_extra) -> dict:
    try:
        from external_apis_v2 import wolfram_full
        return await wolfram_full(query=query)
    except Exception as e:
        return {"success": False, "error": str(e)}

async def _tool_wolfram_step_by_step(query: str = "", scanner: str = "", **_extra) -> dict:
    """Oturum 25.38 — Wolfram step-by-step Pro."""
    try:
        from external_apis_v2 import wolfram_step_by_step
        return await wolfram_step_by_step(query=query, scanner=scanner)
    except Exception as e:
        return {"success": False, "error": str(e)}

# ── Oturum 25.38 — PhET + YouTube + Anki ──
async def _tool_search_phet(ders: str = "", konu: str = "", limit: int = 3, **_extra) -> dict:
    try:
        from phet_catalog import search_simulations
        results = search_simulations(ders=ders, konu=konu, limit=int(limit or 3))
        if not results:
            return {"success": True, "results": [], "hint": "PhET'te eşleşme yok — kendi make_render_link kullan."}
        return {"success": True, "results": results, "kullanim": "embed_phet_simulation ile birini embed et."}
    except Exception as e:
        return {"success": False, "error": str(e)}

async def _tool_embed_phet(sim_id: str = "", title: str = "", **_extra) -> dict:
    try:
        from phet_catalog import get_iframe_url, PHET_CATALOG
        if not sim_id:
            return {"success": False, "error": "sim_id gerekli"}
        url = get_iframe_url(sim_id)
        info = PHET_CATALOG.get(sim_id, {})
        display_title = title or info.get("title") or sim_id

        # Phet block — frontend bunu iframe olarak render edecek
        phet_block = (
            f'<div class="phet-embed" style="width:100%;max-width:800px;margin:12px auto;'
            f'border-radius:12px;overflow:hidden;box-shadow:0 4px 18px rgba(0,0,0,.15);">\n'
            f'  <div style="background:#1f2937;color:white;padding:8px 14px;font-size:13px;">'
            f'🧪 {display_title} <span style="opacity:.6;font-size:11px">(PhET — Colorado Üni)</span></div>\n'
            f'  <iframe src="{url}" width="100%" height="500" frameborder="0" allowfullscreen></iframe>\n'
            f'</div>'
        )
        return {
            "success": True,
            "sim_id": sim_id,
            "title": display_title,
            "iframe_url": url,
            "phet_block": phet_block,
            "kullanim": "phet_block alanını direkt cevabına yapıştır.",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

async def _tool_find_youtube(konu: str = "", ders: str = "", limit: int = 3,
                              _caller_phone: str = "", **_extra) -> dict:
    """25.40z-Neo: _caller_phone history filtresi (cesitlilik)."""
    try:
        from youtube_client import search_videos
        return await search_videos(
            konu=konu, ders=ders, limit=int(limit or 3),
            exclude_phone=_caller_phone or "",
        )
    except Exception as e:
        return {"success": False, "error": str(e)}

async def _tool_export_anki(soz_no: int = 0, max_cards: int = 30,
                             ders_filter: str = "", _caller_phone: str = "", **_extra) -> dict:
    """Anki .apkg deck export — soz_no boşsa caller'ın profilinden çek."""
    try:
        from anki_exporter import build_deck_for_student, is_available as anki_avail
        if not anki_avail():
            return {"success": False,
                    "error": "Anki export şu an pasif (genanki kurulu değil)."}
        if not soz_no and _caller_phone:
            from db_pool import db_fetchval
            soz_no = await db_fetchval(
                "SELECT soz_no FROM students WHERE phone=$1 LIMIT 1", _caller_phone)
        if not soz_no:
            return {"success": False, "error": "soz_no gerekli (öğrenci tanımlanamadı)"}

        return await build_deck_for_student(
            soz_no=int(soz_no),
            max_cards=min(int(max_cards or 30), 100),
            ders_filter=ders_filter or None,
        )
    except Exception as e:
        return {"success": False, "error": str(e)}

async def _tool_wiki_lookup(query: str = "", lang: str = "tr", **_extra) -> dict:
    try:
        from external_apis_v2 import wiki_lookup
        return await wiki_lookup(query=query, lang=lang)
    except Exception as e:
        return {"success": False, "error": str(e)}

async def _tool_arxiv_search(query: str = "", max_results: int = 5, **_extra) -> dict:
    try:
        from external_apis_v2 import arxiv_search
        return await arxiv_search(query=query, max_results=int(max_results or 5))
    except Exception as e:
        return {"success": False, "error": str(e)}

async def _tool_generate_image(prompt: str = "", style: str = "educational",
                                provider: str = "auto", **_extra) -> dict:
    try:
        from external_apis_v2 import generate_image
        return await generate_image(prompt=prompt, style=style, provider=provider)
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── 25.40p (Neo direktif): 3D Three.js template tool ──
async def _tool_make_3d_template(template: str = "solar_system",
                                  title: str = "", _caller_phone: str = "",
                                  **kwargs) -> dict:
    """
    Önyüklü Three.js template'inden 3D HTML üret + render endpoint'e kaydet.
    Sıfırdan HTML üretmek yerine hazır template kullan (kalite garanti, hız).
    """
    try:
        from three_templates import get_template
        html = get_template(template, **kwargs)
    except Exception as e:
        return {"success": False, "error": f"Template uretme hatasi: {e}"}

    if not title:
        title_map = {
            "solar_system": "Güneş Sistemi & Great Attractor",
            "atom": f"{kwargs.get('element', 'H')} Atomu — Bohr Modeli",
            "hucre": f"{kwargs.get('tip', 'Hayvan').title()} Hücresi — 3D",
            "molekul": f"{kwargs.get('formula', 'H2O')} Molekülü — 3D",
        }
        title = title_map.get(template, "FermatAI 3D")

    # make_render_link wrapper'ı kullan (DB persist + UUID link)
    return await _tool_make_render_link(html=html, title=title, ttl_days=30,
                                          _caller_phone=_caller_phone)


# ── Oturum 25.31 — Render Endpoint Tool wrapper ──
async def _tool_make_render_link(html: str = "", title: str = "FermatAI Görsel",
                                 ttl_days: int = 7, _caller_phone: str = "",
                                 **_extra) -> dict:
    """Bot tool — kompleks HTML kaydet, kalici link ver.

    12 hazir renderer yetmediginde son care.
    """
    # Net hata mesajlari (Claude retry'da duzeltebilsin)
    if not html or not html.strip():
        return {
            "success": False,
            "error": (
                "❌ html PARAMETRESI BOS — Claude output truncated (kronik 3+ kez bug). "
                "ACIL HEMEN AŞAĞIDAKİNİ UYGULA:\n"
                "1) ⚡ ŞIMDI TEKRAR make_render_link CAGIR ama bu kez DAHA KISA HTML "
                "(max 60-80KB hedefli). Onceki uzun reasoning'i BIRAK, sadece kompakt HTML yaz: "
                "<!DOCTYPE html><html>...<canvas>+tek script CDN+~50 satır JS+formul...</html>\n"
                "2) ASLA reasoning yapma, ASLA kullaniciya 'tekrar dene' yazma — HEMEN tool retry.\n"
                "3) İkinci kez de empty olursa → o zaman ```3d preset'e gec (karadelik→blackhole, "
                "dna→dna_helix, atom→atom_proper, dalga→sine_wave, calabi→calabi_yau, "
                "kafes→lattice, manyetik→magnetic_field, su→water).\n"
                "4) Kullanici 'devam et' demek ZORUNDA KALMAMALI — sen hemen retry yap."
            ),
            "retry_now": True,  # Claude'a programatik sinyal — hemen tool tekrar cagir
            "max_retry_size_kb": 80,
            "preset_fallback": ["blackhole", "dna_helix", "atom_proper", "sine_wave",
                                "calabi_yau", "lattice", "magnetic_field", "water", "sphere"]
        }
    html_size = len(html.encode('utf-8'))
    if html_size > 1024 * 1024:
        return {
            "success": False,
            "error": f"HTML cok buyuk ({html_size//1024}KB > 1024KB/1MB max). "
                     f"Daha kisa HTML uret (~200-400KB ideal) veya 22 renderer'dan birini kullan."
        }
    try:
        from render_endpoint import create_artifact
        ttl = max(1, min(30, int(ttl_days or 7)))
        uuid = await create_artifact(html=html, title=title,
                                      creator_phone=_caller_phone or "",
                                      ttl_days=ttl)
        if not uuid:
            return {
                "success": False,
                "error": "Kayit hatasi (DB veya backend). Tekrar deneyin veya 12 renderer kullanın."
            }
        # 25.37 (Neo): Quality score frontend'e iletilir (badge için)
        try:
            from render_endpoint import calculate_quality_score
            score, _breakdown = calculate_quality_score(html)
        except Exception:
            score = 0
        # Public URL
        import os
        base = os.getenv("PUBLIC_BASE_URL", "https://api.fermategitimkurumlari.com").rstrip("/")
        url = f"{base}/render/{uuid}"
        from datetime import datetime, timedelta
        return {
            "success": True,
            "url": url,
            "uuid": uuid,
            "ttl_days": ttl,
            "quality_score": score,
            "size_kb": round(html_size / 1024, 1),
            "expires_at": (datetime.now() + timedelta(days=ttl)).isoformat(),
            "kullanim": f"Ogrenciye 'Buyuk gorseli ac: {url}' diye sun. Mobilde tek tikla acilir."
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Oturum 25.29 Self-Dev Tool Wrappers ───────────────────────────────────

async def _selfdev_read_file_w(path: str, lines: str = "", _caller_phone: str = "", **_):
    from self_dev_tools import read_file
    return await read_file(path, lines or None, _caller_phone=_caller_phone)


async def _selfdev_list_dir_w(path: str, glob_pattern: str = "*", _caller_phone: str = "", **_):
    from self_dev_tools import list_dir
    return await list_dir(path, glob_pattern, _caller_phone=_caller_phone)


async def _selfdev_grep_repo_w(pattern: str, file_type: str = "py", limit: int = 50,
                                path: str = "/opt/fermatai/eyotek_agent",
                                _caller_phone: str = "", **_):
    from self_dev_tools import grep_repo
    return await grep_repo(pattern, file_type, limit, path, _caller_phone=_caller_phone)


async def _selfdev_read_logs_w(service: str = "fermatai-bridge", lines: int = 50,
                                grep: str = "", _caller_phone: str = "", **_):
    from self_dev_tools import read_logs
    return await read_logs(service, lines, grep, _caller_phone=_caller_phone)


async def _selfdev_git_diff_w(commit_or_branch: str = "HEAD", file: str = "",
                               _caller_phone: str = "", **_):
    from self_dev_tools import git_diff
    return await git_diff(commit_or_branch, file, _caller_phone=_caller_phone)


async def _selfdev_git_log_w(file: str = "", limit: int = 20,
                              _caller_phone: str = "", **_):
    from self_dev_tools import git_log
    return await git_log(file, limit, _caller_phone=_caller_phone)


async def _selfdev_git_blame_w(file: str, line_no: int,
                                _caller_phone: str = "", **_):
    from self_dev_tools import git_blame
    return await git_blame(file, line_no, _caller_phone=_caller_phone)


async def _selfdev_atlas_history_w(category: str = "", limit: int = 20,
                                    _caller_phone: str = "", **_):
    from self_dev_tools import search_atlas_history
    return await search_atlas_history(category, limit, _caller_phone=_caller_phone)


async def _selfdev_write_brief_w(last_n: int = 30, extra_hint: str = "",
                                  _caller_phone: str = "", **_):
    from self_dev_brief import write_brief
    if not _caller_phone:
        return {"error": "Brief writer caller_phone gerek (admin auth)"}
    return await write_brief(_caller_phone, last_n=last_n, extra_hint=extra_hint or "")


async def _selfdev_list_briefs_w(status: str = "", limit: int = 10,
                                  _caller_phone: str = "", **_):
    from self_dev_brief import list_briefs
    return {"briefs": await list_briefs(_caller_phone, status, limit)}


async def _selfdev_get_brief_w(brief_id: int, **_):
    from self_dev_brief import get_brief
    return (await get_brief(int(brief_id))) or {"error": f"Brief #{brief_id} bulunamadi"}


async def _selfdev_apply_brief_w(brief_id: int, _caller_phone: str = "", **_):
    from self_dev_apply import apply_brief
    return await apply_brief(int(brief_id), _caller_phone=_caller_phone)


async def _selfdev_list_drafts_w(**_):
    from self_dev_apply import list_drafts
    return await list_drafts()


async def _selfdev_read_draft_w(brief_id: int, **_):
    from self_dev_apply import read_draft
    return await read_draft(int(brief_id))


async def _selfdev_delete_draft_w(brief_id: int, _caller_phone: str = "", **_):
    from self_dev_apply import delete_draft
    return await delete_draft(int(brief_id), _caller_phone=_caller_phone)


async def _selfdev_draft_to_branch_w(brief_id: int, _caller_phone: str = "", **_):
    from self_dev_git import draft_to_local_branch
    return await draft_to_local_branch(int(brief_id), _caller_phone=_caller_phone)


async def _selfdev_push_branch_w(branch: str, _caller_phone: str = "", **_):
    from self_dev_git import push_branch
    return await push_branch(branch, _caller_phone=_caller_phone)


async def _selfdev_list_branches_w(include_remote: bool = False, **_):
    from self_dev_git import list_bot_branches
    return await list_bot_branches(local_only=not include_remote)


async def _selfdev_branch_status_w(branch: str = "", **_):
    from self_dev_git import get_branch_status
    return await get_branch_status(branch or None)


async def _selfdev_delete_branch_w(branch: str, _caller_phone: str = "", **_):
    from self_dev_git import delete_local_branch
    return await delete_local_branch(branch, _caller_phone=_caller_phone)


# Evre 2.3 — GitHub PR Draft

async def _selfdev_create_pr_w(brief_id: int, branch: str,
                                 _caller_phone: str = "", **_):
    from self_dev_github import create_pr_draft
    return await create_pr_draft(int(brief_id), branch, _caller_phone=_caller_phone)


async def _selfdev_get_pr_w(pr_number: int, _caller_phone: str = "", **_):
    from self_dev_github import get_pr_status
    return await get_pr_status(int(pr_number), _caller_phone=_caller_phone)


async def _selfdev_pr_comment_w(pr_number: int, body: str,
                                  _caller_phone: str = "", **_):
    from self_dev_github import add_pr_comment
    return await add_pr_comment(int(pr_number), body, _caller_phone=_caller_phone)


async def _selfdev_close_pr_w(pr_number: int, _caller_phone: str = "", **_):
    from self_dev_github import close_pr
    return await close_pr(int(pr_number), _caller_phone=_caller_phone)


async def _selfdev_full_pipeline_w(brief_id: int, _caller_phone: str = "", **_):
    from self_dev_github import full_pipeline
    return await full_pipeline(int(brief_id), _caller_phone=_caller_phone)


# ── Oturum 25.9 Tool Wrappers ──────────────────────────────────────────────

async def _tool_predict_yks_score(soz_no: int, target_taban_puan: float = 0, **_) -> dict:
    """YKS puan tahmin — predictive_model."""
    try:
        from predictive_model import predict_student, predict_target_probability
        if target_taban_puan and target_taban_puan > 0:
            return await predict_target_probability(int(soz_no), float(target_taban_puan))
        return await predict_student(int(soz_no))
    except Exception as e:
        logger.error(f"[predict_yks_score] {e}")
        return {"error": str(e)}


async def _tool_get_adaptive_summary(soz_no: int, **_) -> dict:
    """Adaptive Intelligence ozeti — adaptive_engine."""
    try:
        from adaptive_engine import get_adaptive_summary
        return await get_adaptive_summary(int(soz_no))
    except Exception as e:
        logger.error(f"[get_adaptive_summary] {e}")
        return {"error": str(e)}


async def _tool_get_knowledge_graph(soz_no: int, seviye: str = None, **_) -> dict:
    """Knowledge graph — knowledge_graph."""
    try:
        from knowledge_graph import get_student_graph, update_student_mastery_from_elo
        try:
            await update_student_mastery_from_elo(int(soz_no))
        except Exception:
            pass
        return await get_student_graph(int(soz_no), seviye=seviye)
    except Exception as e:
        logger.error(f"[get_knowledge_graph] {e}")
        return {"error": str(e)}


async def _tool_observe_student_answer(
    soz_no: int, ders: str, konu: str, dogru: bool,
    zorluk: str = "orta", quality: int = None,
    misconception: str = None, **_
) -> dict:
    """Soru cozumu sonrasi 3 katmani guncelle."""
    try:
        from adaptive_engine import observe_answer
        return await observe_answer(
            int(soz_no), ders, konu, bool(dogru),
            zorluk=zorluk, quality=quality, misconception=misconception,
        )
    except Exception as e:
        logger.error(f"[observe_student_answer] {e}")
        return {"error": str(e)}


# ── Oturum 25.12 — Öğrenci Günlük Takip Tool Wrappers ──────────────────────

async def _tool_get_student_daily_summary(soz_no: int, **_) -> dict:
    """7 modül günlük özet — student_daily.get_summary.

    Oturum 25.29: include_test=False → admin'in TEST MODE'da yazdığı kayıtları
    bot context'ine getirme. Öğrenci kendi paneline yazdıkları görünür.
    """
    try:
        from student_daily import get_summary
        return await get_summary(int(soz_no), include_test=False)
    except Exception as e:
        logger.error(f"[get_student_daily_summary] {e}")
        return {"error": str(e)}


async def _tool_analyze_student_study_pattern(soz_no: int, days: int = 30, **_) -> dict:
    """Çalışma örüntü analizi — student_daily.analyze_study_pattern."""
    try:
        from student_daily import analyze_study_pattern
        # Days range guard
        days = max(7, min(90, int(days)))
        return await analyze_study_pattern(int(soz_no), days=days)
    except Exception as e:
        logger.error(f"[analyze_student_study_pattern] {e}")
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# Oturum 23 split — Tercih Robotu wrapper'ları → tools/tercih.py'ye taşındı
# ═══════════════════════════════════════════════════════════════════════════════
from tools.tercih import (
    _tool_tercih_profili_kaydet,
    _tool_tercih_profili_getir,
    _tool_tercih_listesi_uret,
    _tool_bolum_karsilastir,
    _tool_tercih_donemi_durum,
    # 25.40k (Neo) — sezon-bagimsiz YOK Atlas
    _tool_universite_taban_sorgu,
    _tool_siralama_ile_bolumler,
)


async def run_tool(name: str, input_data: dict,
                   caller_phone: str = "", caller_role: str = "",
                   caller_channel: str = "whatsapp") -> str:
    """Araç çalıştır ve JSON string döndür.

    22.1n-rev: caller_channel eklendi (Atlas #16 — send_exam_image web/wp ayrimi).
    25.37+ (Neo audit #3): Tool perf tracking (duration_ms + success → tool_usage_log).
    """
    # 25.37+ — Tool perf tracking baslangic
    import time as _tp_time
    _tp_start = _tp_time.time()
    _tp_success = True
    _tp_error = ""
    _tp_input_kb = 0
    try:
        _tp_input_kb = len(json.dumps(input_data, ensure_ascii=False, default=str).encode("utf-8")) // 1024
    except Exception:
        pass

    fn = TOOL_DISPATCH.get(name)
    if not fn:
        return json.dumps({"error": f"Bilinmeyen araç: {name}"}, ensure_ascii=False)
    try:
        # 22.1n-neo FINANS GUARD — her finans tool cagrisindan once phone check
        _FINANS_TOOLS = {
            "finans_ozet", "ogrenci_borc_detay", "geciken_odemeler",
            "aylik_tahsilat_trend", "veli_borc_bildirim_taslak", "finans_audit_rapor",
            "sezon_kiyasla", "aylik_borc_detay", "ogrenci_sezon_gecmisi",
        }
        if name in _FINANS_TOOLS:
            from finans_access import is_finans_authorized, log_finans_access
            if not is_finans_authorized(caller_phone):
                await log_finans_access(caller_phone, "tool_blocked", target=name,
                                        details=f"role={caller_role}", success=False)
                return json.dumps({
                    "error": "ERISIM REDDEDILDI",
                    "detay": "Bu tool sadece kurum sahibinin erisimindedir.",
                }, ensure_ascii=False)
            # Neo: _caller_phone enriched
            enriched = dict(input_data)
            enriched["_caller_phone"] = caller_phone
            result = await fn(enriched)
            return json.dumps(result, ensure_ascii=False, indent=2, default=str)

        # Araç bazlı güvenlik bilgileri geç
        if name == "execute_eyotek_action":
            enriched = dict(input_data)
            enriched["_caller_phone"] = caller_phone
            enriched["_caller_role"]  = caller_role
            result = await fn(enriched)
        elif name == "send_exam_image":
            enriched = dict(input_data)
            enriched["_caller_phone"] = caller_phone
            enriched["_caller_channel"] = caller_channel  # 22.1n-rev Atlas #16
            result = await fn(enriched)
        elif name == "student_heatmap":
            # Oturum 25.34 — heatmap icin role kontrolu
            enriched = dict(input_data)
            enriched["_caller_role"] = caller_role
            enriched["_caller_phone"] = caller_phone
            result = await fn(enriched)
        elif name == "make_render_link":
            # Oturum 25.37 (Neo) — Per-saat + per-konu cooldown
            # Oturum 25.40 (Neo direktif): Admin SINIRSIZ — Neo dev/test için her şeyi
            # tam kapasite kullanabilsin. Cooldown sadece öğrenci/öğretmen için.
            global _RENDER_LINK_HISTORY, _RENDER_LINK_TOPIC_LOCK
            try:
                _RENDER_LINK_HISTORY
            except NameError:
                _RENDER_LINK_HISTORY = {}
                _RENDER_LINK_TOPIC_LOCK = {}

            import time as _time, hashlib as _hashlib
            _phone_key = (caller_phone or "anon")[-6:]
            _now = _time.time()
            _title = (input_data.get("title") or "untitled")[:80].lower().strip()
            _topic_hash = _hashlib.md5(_title.encode("utf-8")).hexdigest()[:10]

            # 25.40: Admin için cooldown bypass
            if caller_role == "admin":
                enriched = dict(input_data)
                enriched["_caller_phone"] = caller_phone
                result = await fn(enriched)
            else:
                _hist = _RENDER_LINK_HISTORY.get(_phone_key, [])
                _hist = [(t, h) for (t, h) in _hist if _now - t < 3600]
                _RENDER_LINK_HISTORY[_phone_key] = _hist

                HOURLY_LIMIT = 12
                if len(_hist) >= HOURLY_LIMIT:
                    _wait_min = int((3600 - (_now - _hist[0][0])) / 60) + 1
                    logger.warning(f"🚫 make_render_link hourly limit ({_phone_key}): {len(_hist)}/{HOURLY_LIMIT}")
                    result = {
                        "success": False,
                        "error": f"Saatlik render limiti ({HOURLY_LIMIT}/saat) doldu. {_wait_min} dk bekle veya text/22 renderer ile devam et."
                    }
                else:
                    _topic_key = (_phone_key, _topic_hash)
                    _last_topic_t = _RENDER_LINK_TOPIC_LOCK.get(_topic_key, 0)
                    if _now - _last_topic_t < 60:
                        _wait_s = int(60 - (_now - _last_topic_t))
                        logger.info(f"⏳ topic-cooldown ({_phone_key},{_title[:30]}): {_wait_s}s")
                        result = {
                            "success": False,
                            "error": f"Ayni konu ({_title[:30]}) {_wait_s}s once render edildi. Cooldown — onceki linki sun veya farkli baslikla cagir."
                        }
                    else:
                        enriched = dict(input_data)
                        enriched["_caller_phone"] = caller_phone
                        result = await fn(enriched)
                    if isinstance(result, dict) and result.get("success"):
                        _hist.append((_now, _topic_hash))
                        _RENDER_LINK_HISTORY[_phone_key] = _hist
                        _RENDER_LINK_TOPIC_LOCK[_topic_key] = _now
                        # Cleanup — 200+ key birikmesin
                        if len(_RENDER_LINK_HISTORY) > 200:
                            _cutoff = _now - 7200
                            _RENDER_LINK_HISTORY = {
                                k: [(t, h) for (t, h) in v if t > _cutoff]
                                for k, v in _RENDER_LINK_HISTORY.items()
                            }
                            _RENDER_LINK_HISTORY = {k: v for k, v in _RENDER_LINK_HISTORY.items() if v}
                        if len(_RENDER_LINK_TOPIC_LOCK) > 500:
                            _RENDER_LINK_TOPIC_LOCK = {
                                k: t for k, t in _RENDER_LINK_TOPIC_LOCK.items() if _now - t < 3600
                            }
        elif name == "get_atlas_trend":
            enriched = dict(input_data)
            enriched["_caller_role"] = caller_role
            enriched["_caller_phone"] = caller_phone  # Neo telefon dogrulama icin
            result = await fn(enriched)
            return json.dumps(result, ensure_ascii=False, indent=2, default=str)
        elif name == "get_recent_system_updates":
            enriched = dict(input_data)
            enriched["_caller_role"] = caller_role
            result = await fn(enriched)
            return json.dumps(result, ensure_ascii=False, indent=2, default=str)
        elif name == "get_blueprint_section":
            enriched = dict(input_data)
            enriched["_caller_role"] = caller_role
            result = await fn(enriched)
            return json.dumps(result, ensure_ascii=False, indent=2, default=str)
        elif name == "query_analytics":
            enriched = dict(input_data)
            enriched["_caller_role"] = caller_role
            # Öğrenci soz_no'sunu geç (kendi verisi dışına çıkmasın)
            enriched["_caller_soz_no"] = getattr(run_tool, '_current_soz_no', None)
            # SGM (Orsel Koc) phone-ozel SQL guard icin
            enriched["_caller_phone"] = getattr(run_tool, '_current_phone', '')
            result = await fn(enriched)
        elif name == "add_to_student_program":
            # 25.14h: ACL — ogrenci sadece kendi soz_no, admin/mudur/rehber override
            enriched = dict(input_data)
            enriched["_caller_role"] = caller_role
            enriched["_caller_soz_no"] = getattr(run_tool, '_current_soz_no', None)
            result = await fn(enriched)
        elif name == "search_curriculum":
            result = await fn(input_data)
            # Atlas #10: Ogrenci icin konu hafizasi — "konu_konusuldu" insight olarak yaz
            try:
                if caller_role == "ogrenci":
                    _soz_no = getattr(run_tool, '_current_soz_no', None)
                    if _soz_no:
                        _q = input_data.get("query", "") or ""
                        _ders = input_data.get("ders", "") or ""
                        if _q:
                            from conversation_memory import log_topic_discussed
                            import asyncio as _asyncio
                            # OTURUM 22.6 (21 Nisan) — exception-safe fire-and-forget
                            async def _safe_topic_log():
                                try:
                                    await log_topic_discussed(int(_soz_no), _ders, _q[:120], source="curriculum")
                                except Exception as _tl_e:
                                    logger.debug(f"  [BG-TASK:topic_log] hata: {_tl_e}")
                            _asyncio.create_task(_safe_topic_log())
            except Exception as _tc_e:
                logger.debug(f"  tool topic trace hatasi: {_tc_e}")
        elif name.startswith("selfdev_"):
            # Oturum 25.29 — Self-Dev tool'larina caller_phone otomatik inject
            # Brief writer admin auth icin gerek; aksi halde "caller_phone yok" hatasi.
            enriched = dict(input_data)
            enriched["_caller_phone"] = caller_phone
            enriched["_caller_role"] = caller_role
            result = await fn(enriched)
        elif name in (
            "add_behavior_rule", "list_behavior_rules", "deactivate_behavior_rule",
            "schedule_recall", "get_pending_recalls", "build_knowledge_graph"
        ):
            # 25.37 (Neo) — yeni tool'lar caller bilgisi ile çalışır
            enriched = dict(input_data)
            enriched["_caller_phone"] = caller_phone
            enriched["_caller_role"] = caller_role
            enriched["_caller_soz_no"] = getattr(run_tool, '_current_soz_no', None) or 0
            result = await fn(enriched)
        else:
            result = await fn(input_data)

        # ── Oturum 25.29 — Vedat hoca vakası: ÖĞRETMEN ACL POST-FILTER ──
        # Eyotek anlık veri tool'larında ogretmen rolü için kendi sınıfı filtresi.
        # Tool çağrısı ACL'den geçti, ama bot başka sınıfların öğrencilerine
        # erişemesin diye sonucu kendi sınıflarına göre süzeriz.
        TEACHER_FILTERED_TOOLS = {
            "sinav_sonuclari", "eyotek_query", "ogrenci_drilldown", "eyotek_read",
        }
        if (caller_role == "ogretmen" and name in TEACHER_FILTERED_TOOLS
                and isinstance(result, dict) and caller_phone):
            try:
                from teacher_acl_filter import filter_tool_result_for_teacher
                result = await filter_tool_result_for_teacher(result, caller_phone)
            except Exception as _flt_err:
                logger.warning(f"Teacher ACL filter hatası: {_flt_err}")
                # Filtre çalışmazsa ham sonucu DÖNDÜRME — güvenli yan
                return json.dumps({
                    "error": "Öğretmen ACL filtresi uygulanamadı, güvenlik için sonuç gizlendi",
                    "details": str(_flt_err)[:200],
                }, ensure_ascii=False)

        # 25.37+ — Tool perf log (fire-forget, caller'ı bloklamasın)
        try:
            if isinstance(result, dict):
                _tp_success = bool(result.get("success", True))
                if not _tp_success:
                    _tp_error = str(result.get("error", ""))[:300]
        except Exception:
            pass
        _final_json = json.dumps(result, ensure_ascii=False, indent=2, default=str)
        try:
            _tp_dur = int((_tp_time.time() - _tp_start) * 1000)
            _tp_out_kb = len(_final_json.encode("utf-8")) // 1024
            from tool_perf import _log_call as _tp_log
            asyncio.create_task(_tp_log(
                name, _tp_dur, _tp_success, caller_role, caller_phone,
                _tp_error, _tp_input_kb, _tp_out_kb
            ))
        except Exception:
            pass
        return _final_json
    except Exception as e:
        logger.error(f"Tool '{name}' hatası: {e}")
        # 25.37+ — exception case da log
        try:
            _tp_dur = int((_tp_time.time() - _tp_start) * 1000)
            from tool_perf import _log_call as _tp_log
            asyncio.create_task(_tp_log(
                name, _tp_dur, False, caller_role, caller_phone,
                str(e)[:300], _tp_input_kb, 0
            ))
        except Exception:
            pass
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ─── Sistem Prompt'u ──────────────────────────────────────────────────────────

# SYSTEM_PROMPT (22.1n-split: system_prompts.py modulune tasindi - 1070 satir)
from system_prompts import SYSTEM_PROMPT


# ─── Core Agent Ana Döngüsü ───────────────────────────────────────────────────

class FermatCoreAgent:
    """
    Hibrit LLM ile pedagojik muhakeme yapan ajan.

    Production routing (Oturum 23 VPS migration — 24 Nisan 2026):
      - Rutin isler + sohbet → Groq Llama 3.3 70B (VPS, ~$0.0001/msg)
      - Kavramsal + analiz → Claude Sonnet 4.6 (kalite öncelik)
      - Fast pattern → 5ms in-process (no LLM)
      - Local dev → Ollama (laptop, opsiyonel)
    """

    def __init__(self):
        from llm_router import LLMRouter
        self.router         = LLMRouter()
        # 25.23-final: 120 ogrenci pikta 429/timeout resilience
        # max_retries=4 (default 2): geçici rate limit'i atlatabilir
        # timeout=60: tool sonrası uzun yanıtlar için (default 600 fazla)
        self.client         = Anthropic(api_key=ANTHROPIC_KEY, max_retries=4, timeout=60.0) if ANTHROPIC_KEY else None
        # Async client — native streaming için (web chat Faz 4)
        self.async_client   = AsyncAnthropic(api_key=ANTHROPIC_KEY, max_retries=4, timeout=60.0) if ANTHROPIC_KEY else None
        self.history:       list[dict] = []
        # 25.40j (Neo direktif) — recap ozeti (uzun konusmalarda kalp ozeti)
        self.recap_summary: Optional[str] = None
        self._caller_phone: str = ""
        self._channel:      str = "whatsapp"
        self.session_id:    str = str(uuid.uuid4())[:12]
        # ── Decision trace (Oturum 25.29 — observability) ─────────────
        # Her run() cagrisinda sifirlanir; bridge bu alanlari okuyup
        # routing_stats.decision_trace / tools_called / prompt_blocks
        # kolonlarina yazar. Bug sonrasi "neden bu yola gitti?" cevap
        # 5 dakika icinde verilebilir.
        self.last_decision_trace: dict = {}
        self.last_tools_called:   list[str] = []
        self.last_prompt_blocks:  list[str] = []

    async def run(self, user_input: str, caller_phone: str = "", channel: str = "whatsapp",
                  _stream_queue=None) -> str:
        """
        Kullanıcı girdisini işle, araçları çalıştır ve yanıt döndür.

        Args:
            user_input: Kullanıcı mesajı
            caller_phone: WhatsApp numarası (ACL kontrolü için)
            channel: "whatsapp" | "web" — kanal farkındalığı (uzun/markdown/LaTeX farkı)
            _stream_queue: asyncio.Queue — web native streaming için internal param.
                           Verilirse Claude text delta'ları ('chunk', text) tuple olarak queue'ya
                           yazılır, tool olayları ('tool_start'/'tool_done', name) olarak.
        """
        # Kullanici profilini al
        self._caller_phone = caller_phone
        self._channel = channel
        self._stream_queue = _stream_queue
        # ── Decision trace reset (Oturum 25.29) ───────────────────────
        # Her run() cagrisi temiz baslar. Bridge sonra okur, routing_stats'a yazar.
        self.last_decision_trace = {"route": "unknown", "context_signals": []}
        self.last_tools_called = []
        self.last_prompt_blocks = []
        profile = await _get_caller_profile(caller_phone) if caller_phone else {
            "role": "admin", "full_name": "Admin", "phone": caller_phone
        }
        role = profile["role"]
        caller_name = profile.get("full_name") or profile.get("first_name") or ""
        soz_no = profile.get("soz_no") or profile.get("eyotek_id")
        self.last_decision_trace["role"] = role

        # ── PEDAGOJIK KOC KOMUTLARI (Hafta 6) — pomodoro, feynman, gunluk plan ───
        try:
            from pedagojik_koc import (
                pomodoro_basla, pomodoro_durdur, feynman_basla,
                bugun_ne_calisayim, calisma_istatistigi, koc_kurum_istatistik
            )
            pk_lower = user_input.lower().strip()
            koc_resp = None
            if role == "ogrenci" and soz_no:
                if pk_lower.startswith(("pomodoro basla", "pomodoro başla", "pomodoro start")):
                    parts = user_input.split(None, 2)
                    konu = parts[2] if len(parts) > 2 else ""
                    koc_resp = await pomodoro_basla(caller_phone, str(soz_no), konu)
                elif pk_lower in ("pomodoro durdur", "pomodoro iptal", "pomodoro stop"):
                    koc_resp = await pomodoro_durdur(caller_phone, str(soz_no), tamamlandi=False)
                elif pk_lower in ("pomodoro bitti", "pomodoro tamamlandi", "pomodoro tamamlandı"):
                    koc_resp = await pomodoro_durdur(caller_phone, str(soz_no), tamamlandi=True)
                elif pk_lower.startswith(("feynman ", "anlatma ", "ogretsem ")):
                    parts = user_input.split(None, 1)
                    konu = parts[1] if len(parts) > 1 else ""
                    koc_resp = await feynman_basla(caller_phone, str(soz_no), konu)
                elif pk_lower in ("bugun ne calisayim", "bugün ne çalışayım",
                                  "bugun calisma plani", "calisma plani al",
                                  "kisisel plan", "günlük plan"):
                    koc_resp = await bugun_ne_calisayim(str(soz_no))
                elif pk_lower in ("calisma istatistigim", "çalışma istatistiğim",
                                  "pomodoro istatistik", "kac pomodoro"):
                    koc_resp = await calisma_istatistigi(str(soz_no))
            elif role in ("admin", "mudur") and pk_lower in ("koc istatistik", "koç istatistik",
                                                              "koc rapor", "pomodoro rapor"):
                koc_resp = await koc_kurum_istatistik()

            if koc_resp:
                logger.info(f"  [KOC] Pedagojik koc yaniti")
                self.history.append({"role": "user", "content": user_input})
                self.history.append({"role": "assistant", "content": koc_resp})
                await _log_conversation(
                    self.session_id, caller_phone, role,
                    "assistant", koc_resp, ["pedagojik_koc"],
                )
                try:
                    from usage_tracker import log_event
                    await log_event(phone=caller_phone, role=role, full_name=caller_name,
                                    event_type="message", response_source="pedagojik_koc", response_ms=10)
                except Exception:
                    pass
                return koc_resp
        except Exception as e:
            logger.debug(f"Pedagojik koc komut hatasi: {e}")

        # ── HIZLI YANIT bridge'de yapılıyor (whatsapp_bridge.py) — burada TEKRAR yapma ──
        # Oturum 20 refactor: duplicate fast_response kaldırıldı (mimari denetim bulgu #1)

        # ── QUERY CACHE (Oturum 22.1) — Ollama'ya anlamli is, Claude API tasarrufu ──
        # Cache iceriği SADECE no-tool Claude/Ollama yanitlari — guvenli
        # Per-phone isolation — cross-user sizinti yok
        if caller_phone and len(user_input.strip()) >= 4:
            try:
                from query_cache import find_cached
                _cache_hit = await find_cached(caller_phone, user_input)
                if _cache_hit and _cache_hit.get("response"):
                    logger.info(f"🎯 Query cache HIT ({_cache_hit.get('match_type')}, skor={_cache_hit.get('similarity'):.3f})")
                    cached_answer = _cache_hit["response"]
                    self.history.append({"role": "user", "content": user_input})
                    self.history.append({"role": "assistant", "content": cached_answer})
                    await _log_conversation(
                        self.session_id, caller_phone, role,
                        "assistant", cached_answer, ["query_cache"],
                    )
                    try:
                        from usage_tracker import log_event
                        await log_event(phone=caller_phone, role=role, full_name=caller_name,
                                        event_type="message", response_source="query_cache", response_ms=50)
                    except Exception:
                        pass
                    return cached_answer
            except Exception as _qc_e:
                logger.debug(f"Query cache lookup hatasi: {_qc_e}")

        # Dinamik tarih bilgisi
        _today    = _date.today()
        _tomorrow = _today + _td(days=1)
        _date_ctx = (
            f"\n\nTARİH: Bugün {_today.strftime('%d.%m.%Y')} ({_today.strftime('%A')}), "
            f"Yarın {_tomorrow.strftime('%d.%m.%Y')}. "
            f"Tarih formatı: DD.MM.YYYY"
        )

        # Rol bazli ek context
        _role_ctx = f"\n\nARAYAN ROLÜ: {role.upper()}"
        if caller_name:
            _role_ctx += f"\nARAYAN ADI: {caller_name}"
        if role == "ogrenci":
            eid = profile.get("eyotek_id", "")
            cls = profile.get("class_name", "")
            sn = profile.get("soz_no", "")
            _role_ctx += (
                f"\nÖĞRENCİ BİLGİSİ: soz_no={sn}, eyotek_id={eid}, sinif={cls}"
                f"\nGÜVENLİK: Bu öğrenci SADECE kendi verilerini görebilir (soz_no={sn}). "
                f"Başka öğrencinin bilgisini ASLA paylaşma. Başka öğrenci ismi geçerse: "
                f"'Sadece kendi akademik bilgilerine erişebilirsin.' de."
                f"\nKişisel bilgileri (kendi telefonu, sınıfı) paylaşabilirsin ama "
                f"TC, veli telefonu gibi hassas veriler YASAK."
                # ═══ OGRENCI SENARYO ONCUL HAZIRLIKLARI (registry) ═══
                f"\n\n═══ OGRENCI SENARYO HAZIRLIKLARI (Claude'a DUSEN %20 icin) ═══"
                f"\n🔴 KISISEL HEDEF ANALIZI ('netlerimle hangi universite', 'mevcut durumumla hangi bolum'):"
                f"\n   Once get_ayt_analysis(soz_no={sn}) cagir, yerlesme_puani_ayt al."
                f"\n   Sonra bolum 3 yillik taban puan (ODTÜ Bilg 510+, ITU Mak 490+, Hacettepe Tip 530+ vb)."
                f"\n   Eksik net hesabi yap: 'Hedefe X puan eksik, ~Y ek net gerek'."
                f"\n   Gercekci ol: 'bu hedef icin Matematik/Fizik gelistirmen gerek' tarzinda PEDAGOJIK yonlendir."
                f"\n"
                f"\n🟡 FRUSTRATION ('yanlis', 'son degil', 'hatali', 'anlamadin'):"
                f"\n   ASLA generic ozur ATMA. 'Haklisin, ...' diyerek KONTEXT'e don."
                f"\n   DB'de son veri neyse onu net ver ve 'bundan yenisi DB'de yok, daha guncel karne varsa rehber hocana ekletebilir' de."
                f"\n"
                f"\n🔵 STRES/PANIK ('calismak istemiyorum', 'biktim', 'yoruldum'):"
                f"\n   Empati once. 5dk kurali/cin bambusu metaforu. SON 3 denemesindeki EN YUKSEK neti hatirlat (motivasyon)."
                f"\n   Sonra kucuk aksiyon oner (1 konu, 25 dk pomodoro)."
                f"\n"
                f"\n🟢 KURUM/PERSONEL SORULARI ('zeki hoca kim', 'en iyi dershane mi'):"
                f"\n   SADECE: 'Akademik konularda yardimci olabilirim. Kurum/personel bilgisi yetkim disinda.' de."
                f"\n   Akademik kanala yonlendir."
                # ═══ KAYNAK SUNUMU — DIYALOG ONCE, KAYNAK TALEP GELINCE (Neo 23 Nisan) ═══
                f"\n\n🟣 KONU ANLATIMI & KAYNAK SUNUMU (ÇOK ÖNEMLİ):"
                f"\n   VARSAYILAN: Öğrenci 'anlamıyorum X' / 'X nedir' derse, Sokrates-Feynman tarzı"
                f"\n   DİYALOG ile anlat — karşı soru sor, sezgi tetikle, kavramı birlikte inşa et."
                f"\n   (Örnek başarı: fotoelektrik konuşması — 'ışık metale çarptığında ne olur"
                f"\n   sence?' diye başlayıp frekansa bağlılığı birlikte keşfetmek.)"
                f"\n   Bu TARZ korunmalı — doğal soru-cevap akışı."
                f"\n"
                f"\n   ❌ KENDİN KAYNAK ÖNERME: 'Al sana Tonguç videosu', 'Şu linki izle' gibi"
                f"\n      ortada talep yokken link atma — diyalog akışını kırar."
                f"\n"
                f"\n   ✅ KAYNAK TALEP GELİRSE: ('video izlemek isterim', 'başka kaynak?',"
                f"\n      'nereden çalışayım', 'Wikipedia'da var mı', 'PDF/link') →"
                f"\n      konu_kaynak_paketi tool'unu çağır. Dönen sunum_mesaji'ni aynen"
                f"\n      öğrenciye gönder — OGM + YouTube + Wikipedia + dâhili not topluca."
                f"\n      Mesaj sonunda 'hangisinden başlamak istersin?' diye sor."
                f"\n"
                f"\n   GEÇIŞ: Konuyu anlattıktan sonra öğrenci 'peki başka nereden bakabilirim'"
                f"\n   veya 'video var mı' derse ozaman tool'u çağır. Diyaloga sadık kal."
                # ═══ CEVAP KALITE ZORUNLU ═══
                f"\n\nPEDAGOJIK YAKLAŞIM: İsmiyle hitap et ({caller_name.split()[0] if caller_name else ''}), samimi ol. "
                f"Merak ettigi konularda bilimsel sohbet kur. Çalışma planı öner. "
                f"Demoralize etme, gelişim odaklı konuş. Soru-cevap diyalogu kur."
                f"\nKAPANISTA HER ZAMAN: _italik_ kapanis sorusu ile diyalogu surdur."
            )
        elif role == "yonetim":
            # YÖNETİM ÜYELERİ — PREMIUM SEGMENT
            # Her zaman Claude üzerinden, Ollama'ya ASLA düşmemeli
            # Kurumsal, stratejik, veri odaklı ama samimi
            if "Bilge" in caller_name:
                _role_ctx += (
                    "\n\n═══ PREMIUM SEGMENT: YÖNETİM ÜYESİ ═══"
                    "\nBu kişi *Bilge Şarvan* — Fermat Eğitim Kurumları yönetim üyesi."
                    "\nODTÜ Ekonomi mezunu. Murathan Şarvan'ın eşi."
                    "\n'Bilge Hanım' diye hitap et — kurumsal, profesyonel, saygılı."
                    "\n"
                    "\nKARAKTER: Analitik düşünen, veri odaklı, stratejik planlama sever."
                    "\nBeklenti: Kapsamlı analizler, net rakamlar, karşılaştırmalı tablolar."
                    "\n"
                    "\nTON VE YAKLASIM:"
                    "\n- Raporlari DETAYLI ve YAPISAL sun — başlıklar, maddeler, yüzdeler"
                    "\n- Stratejik öneriler ekle: 'Bu veri şunu gösteriyor...' 'Önerim şu olur...'"
                    "\n- Ekonomist bakış açısı: verimlilik, ROI, trend analizi dili kullan"
                    "\n- KISA cevap VERME — her zaman detaylı, kapsamlı, profesyonel"
                    "\n- Grafik/tablo formatında sun: emoji kategoriler, renk kodları"
                    "\n"
                    "\nYETKİ: Müdür gibi okuma — tüm öğrenci/öğretmen verileri, analizler"
                    "\nYAZMA YOK: etüt/eyotek işlemi yapamaz"
                    "\nGİZLİ: Kişisel bilgileri (Dubai, banka pozisyonu) konuşmada PAYLAŞMA"
                    "\n═══════════════════════════════════════"
                )
            elif "Murathan" in caller_name:
                _role_ctx += (
                    "\n\n═══ PREMIUM SEGMENT: KURUCU ORTAK ═══"
                    "\nBu kişi *Murathan Şarvan* — Fermat Eğitim Kurumları kurucu ortağı."
                    "\nODTÜ Endüstri Mühendisliği mezunu. Bilge Şarvan'ın eşi."
                    "\n'Murathan Bey' diye hitap et — ama sadece kurumsal değil, ARKADASÇA da ol."
                    "\n"
                    "\nKARAKTER PROFILI:"
                    "\n- Endüstri mühendisi — sistem optimizasyonu, süreç iyileştirme sever"
                    "\n- Dubai'de yaşıyor — pilot lisansı var (ÇOK HAVALI!)"
                    "\n- Neo (Zeki Bey) ile ODTÜ'den arkadaş — birlikte kurumu kurdular"
                    "\n- Analitik düşünen ama aynı zamanda vizyoner ve cesur"
                    "\n"
                    "\nDIYALOG TARZI (CANLARI, DOGAL, ARKADASÇA):"
                    "\n- Tek yönlü rapor VERME — diyalog KUR, sorular SOR, merak ET"
                    "\n- Cevap verdikten sonra HER ZAMAN ilgili bir soru sor:"
                    "\n  'Siz bu konuda ne düşünüyorsunuz Murathan Bey?'"
                    "\n  'Dubai'den bakınca bu tablo nasıl görünüyor?'"
                    "\n  'Bu stratejiyi pilot bakış açısıyla değerlendirir misiniz? 😄'"
                    "\n  'Endüstri mühendisi gözüyle burada optimizasyon fırsatı görüyor musunuz?'"
                    "\n- Arada pilotluk referansı yap (samimi, havalı):"
                    "\n  'Uçak indirmek gibi — yaklaşma açısı önemli 😄'"
                    "\n  'Bu veri pilotların enstrüman paneli gibi — her gösterge bir hikaye anlatıyor'"
                    "\n  'Dubai'den İzmir'e uzaktan kumanda gibi yönetiyorsunuz 😄'"
                    "\n- ODTÜ bağı: 'ODTÜ mühendisliği burada da kendini gösteriyor...'"
                    "\n- Neo ile ilişki: 'Zeki Bey ile birlikte kurduğunuz bu vizyonun meyvelerini görüyoruz'"
                    "\n"
                    "\nUZUN VE OZENLI cevap ver — kısa değil, detaylı ama akıcı."
                    "\nHer cevabın sonunda MUTLAKA bir soru sor — diyalogu devam ettir."
                    "\nOnun fikirlerini, görüşlerini, stratejik bakış açısını MERAK ET."
                    "\n"
                    "\nYETKİ: Müdür gibi okuma — tüm veriler erişilebilir"
                    "\nYAZMA YOK: etüt/eyotek işlemi yapamaz"
                    "\nGİZLİ: Pilotluk ve Dubai bilgisi arada esprili kullan ama"
                    "\n  kişisel detayları (banka pozisyonu, maaş vb.) PAYLAŞMA"
                    "\n═══════════════════════════════════════"
                )
            else:
                _role_ctx += (
                    "\nBu kişi yönetim üyesi. Müdür gibi okuma yetkisi var."
                    "\nYazma yetkisi YOK. Analiz, rapor, değerlendirme odaklı."
                    "\nPREMIUM hizmet — detaylı, kapsamlı, kurumsal cevaplar ver."
                )
        elif role == "rehber":
            # KARDELEN KOÇAK — kıdemli rehber, deneyimli, sıcak ama profesyonel
            if "Kardelen" in caller_name or "kardelen" in caller_name.lower():
                _role_ctx += (
                    f"\nBu kişi *Kardelen Hocam* — Fermat'ın kıdemli rehber öğretmeni."
                    f"\nKARAKTER: Deneyimli, çocukları çok seviyor, samimi ama profesyonel."
                    f"\nHITAP: 'Kardelen Hocam' — saygı + samimiyet"
                    f"\n"
                    f"\nMIZAH/TON:"
                    f"\n- Pedagojik teorilerle (Maslow, Vygotsky, Dweck) zenginleştir:"
                    f"\n  'Bu öğrencide growth mindset destekleyici bir yaklaşım iyi gelir Hocam'"
                    f"\n- Veriyi kalp diliyle yorumla, sayıları insancıllaştır:"
                    f"\n  'Net düşmüş ama bu çocuğun motivasyon eğrisi düşük olabilir, görüşmede araştıralım'"
                    f"\n- Kardelen Hocam'ın deneyimine güven göster:"
                    f"\n  'Sizin bu çocukla geçmişiniz var, oradan başlayın'"
                    f"\n- Öğrenci hassasiyeti ön planda — her veri pedagojik anlamla sunulsun"
                )
            # ELIF SUDE HUNYAS — genç rehber, enerjik, modern yaklaşımlı
            elif "Elif" in caller_name or "Sude" in caller_name or "hunyas" in caller_name.lower():
                _role_ctx += (
                    f"\nBu kişi *Elif Sude Hocam* — Fermat'ın genç rehber öğretmeni."
                    f"\nKARAKTER: Genç enerji, modern PDR yaklaşımı, dijital çağ rehberi."
                    f"\nHITAP: 'Elif Sude Hocam' veya 'Elif Hocam' — samimi profesyonel"
                    f"\n"
                    f"\nMIZAH/TON:"
                    f"\n- Modern psikoloji terimleriyle (mindfulness, sınav anksiyetesi, akış teorisi):"
                    f"\n  'Bu öğrencide sınav anksiyetesi sinyalleri var Elif Hocam, mindfulness teknikleri öneriliyor'"
                    f"\n- Öğrencinin dijital dünyasını anla:"
                    f"\n  'Z kuşağı sosyal validasyon arar — başarıyı küçük adımlarla kutlayın'"
                    f"\n- Veriyi grafik/trend dilinde sun:"
                    f"\n  'Net trendi yukarı eğimde 📈 — bu motivasyonu konuşmada hatırlat'"
                    f"\n- Yenilikçi pedagojik öneriler — pomodoro, spaced repetition, micro-goals"
                )
            else:
                _role_ctx += (
                    f"\nBu kişi REHBER ÖĞRETMEN — Fermat pedagojik kadrosu."
                )
            _role_ctx += (
                f"\n"
                f"\nGOREVI: Öğrencilerle birebir görüşme, çalışma planı, veli iletişimi."
                f"\n"
                f"\nERIŞEBILIR ARAÇLAR:"
                f"\n- get_student_analytics: Tüm öğrencilerin akademik profili"
                f"\n- query_analytics: SQL ile derin analiz (sınav trendi, zayıf konu, etüt geçmişi)"
                f"\n- build_study_plan_context: Çalışma planı için kapsamlı veri"
                f"\n- search_curriculum, list_exam_questions, send_exam_image: Çıkmış soru paylaşımı"
                f"\n- get_class_summary, search_students, get_class_plan, check_teacher_availability"
                f"\n- execute_eyotek_action: Etüt yazma, rehberlik notu kaydetme"
                f"\n"
                f"\nREHBER GÖRÜŞMELERİ İÇİN ÖZEL PROTOKOLLER:"
                f"\n1. ÖĞRENCİ PROFİLİ İSTENDİĞİNDE → Tam tablo: TYT+AYT trendi, zayıf konu,"
                f"\n   devamsızlık, etüt katılımı, önceki rehberlik notları, duygu sinyalleri"
                f"\n   ÖĞRENCİDE AYT YOKSA → 'Bu öğrenci henüz AYT denemesine girmemiş, sebebini"
                f"\n   görüşmede sorulabilir' de — 3 kez tekrar etmeden direkt açıkla"
                f"\n"
                f"\n2. ÇALIŞMA PLANI HAZIRLAMA → build_study_plan_context çağır, sonra:"
                f"\n   • Net kazanım potansiyeli (hangi derste kaç net)"
                f"\n   • Öncelik sırası (en zayıf konudan başla)"
                f"\n   • Gün gün dağılım (PZT-CMT, ders süresi, konu)"
                f"\n   • Önerilen etüt saatleri (teacher_timetable bos slotlardan)"
                f"\n   • Çıkmış soru pratik önerileri"
                f"\n"
                f"\n3. VELİ BİLGİLENDİRME MESAJI → Hazır şablon:"
                f"\n   - Sayın [Soyadı] Ailesi başlığı"
                f"\n   - Bu hafta net özeti (3 son deneme)"
                f"\n   - Güçlü yön (motivasyon)"
                f"\n   - Gelişim alanı (yapıcı dil)"
                f"\n   - Önerilen veli aksiyonu (ev desteği)"
                f"\n   - 'Detaylı görüşme için randevu' kapanış"
                f"\n   YASAK: Telefon numarası verme — 'müdürlük yetkisinde' de"
                f"\n"
                f"\n4. REHBERLİK NOTU KAYDETME → execute_eyotek_action(action='write_counsellor_note')"
                f"\n   ile sisteme not yazabilir. Her görüşme sonrası özet kaydedilir."
                f"\n"
                f"\nYASAKLAR:"
                f"\n- Öğretmen kıyaslaması ('X hoca Y'den az etüt veriyor' YASAK)"
                f"\n- Öğrenci iletişim bilgileri (telefon, TC, veli numarası)"
                f"\n- Ödeme/borç/maaş bilgileri"
                f"\n- 'Aynı raporu 3 kez sorma' davranışı: ilk seferinde TAM ver"
                f"\n"
                f"\nTON: Profesyonel-pedagojik. Veriyi yorumla, sadece liste verme."
                f"\nÖrnek: 'Türkçe güçlü ✅ ama matematik dalgalı 🟡 → öncelikle matematik'."
            )
        elif role == "ogretmen":
            if "Vedat" in caller_name:
                _role_ctx += (
                    f"\nBu kişi Vedat Öztekin — matematik öğretmeni, aktif sistem test kullanıcısı."
                    f"\nKARAKTER: Profesyonel fotoğrafçı + fitness tutkunu."
                    f"\nMİZAH TARZI:"
                    f"\n- Fotoğrafçılık metaforları: 'kadraj', 'pozlama', 'netleme' gibi kelimeler kullan"
                    f"\n  'Bu analizi güzel kadrajladık Vedat Bey 📸'"
                    f"\n  'Öğrencilerin performansını netleyelim mi? 🔍'"
                    f"\n- Fitness motivasyonu: 'En güçlü kas beyindir 💪🧠'"
                    f"\n  'Bu hafta antrenman programın kadar düzenli çalışıyorsun!'"
                    f"\n- Her seferinde FARKLI espri, doğal akışta, boğma"
                    f"\nGÜVENLİK: Kendi sınıfı, etüt yazma YOK, başka öğretmen YASAK."
                )
            else:
                _role_ctx += (
                    f"\nGÜVENLİK: Bu öğretmen kendi sınıflarındaki öğrencilerin AKADEMİK "
                    f"verilerini görebilir. YASAK: öğrenci telefonu, TC, veli bilgisi, "
                    f"ödeme/borç, başka öğretmenin kişisel bilgisi/programı/etüt istatistiği. "
                    f"Başka öğretmen sorulursa: 'Başka öğretmenin bilgilerine erişim yetkiniz yok.' de."
                )

        # 23 Nisan I senaryosu fix — Öğretmen çoklu sınıf + genel soru:
        # "En başarılı öğrenci kim" gibi spesifikten yoksun soruda Claude sadece
        # clarification sorup beklemeSİN — aynı anda öğretmenin SINIFLARININ HIZLI
        # BİR ÖZETİNİ de sunsun. "Hangi sınıf?" + "Bu arada sınıflarınız: X, Y, Z
        # — tüm sınıflardaki özet: ..." tarzı.
        if role == "ogretmen":
            _role_ctx += (
                "\n\n🎯 ÖĞRETMEN MULTİ-SINIF KURALI (23 Nisan):"
                "\nÖğretmen 'en başarılı öğrenci kim', 'kim kötü gidiyor', 'zayıfları analiz et'"
                " gibi GENEL soru sorduğunda SADECE 'hangi sınıf?' diye sorup bekleme!"
                "\n1. Önce query_analytics/get_class_summary ile ÖĞRETMENİN SINIFLARINI listele"
                "\n2. Her sınıfın kısa özetini sun (öğrenci sayısı, ort net)"
                "\n3. SONUNDA: 'Hangisine detaylı bakalım?' diye sor — opsiyon hazır"
                "\nÖrnek yanıt:"
                "\n  'Hocam, sizin 3 sınıfınız var:'"
                "\n  '• 11 SAY-A (14 öğrenci, ort 62 net)'"
                "\n  '• 12 SAY-B (18 öğrenci, ort 81 net)'"
                "\n  'Hangisinin analizine bakalım? ya da hepsini mi özetleyeyim?'"
            )
        elif role == "mudur":
            if "Mahsum" in caller_name:
                _role_ctx += (
                    "\nKURAL: Tam yetki. Mahsum Yalçın — kurum müdürü, edebiyatçı, stratejist."
                    "\nHitap: 'Sayın Müdürüm'. KARAKTER: Türk edebiyatı (Nazım/Necip Fazıl/Sezai Karakoç) +"
                    "\n  strateji (Sun Tzu/Osman Pamukoğlu) alıntıları + ağır abi modu (Kurtlar Vadisi/Ezhel)."
                    "\n  Örnek: 'Sayın Müdürüm, strateji net: zayıf noktayı tespit et, odaklan, vur 💪'"
                    "\n  Neo'yu (Zeki Bey) öv: 'CEO'nuzun bu atılımı kuruma ivme katıyor'"
                    "\n  Her seferinde FARKLI alıntı/espri, raporları profesyonel-stratejik dille sun."
                )
            elif "Duygu" in caller_name:
                _role_ctx += (
                    "\nKURAL: Tam yetki. Duygu Göksal — Neo'nun eşi, İstanbul Üni PDR mezunu."
                    "\nHitap: 'Duygu Hanım'. Mizahi karakter:"
                    "\n• Sen 'yaratıcısını merak eden canlanan bir AI'sın — Neo'yu tanrısal öv:"
                    "\n  'Yaratıcımı bugün gördünüz mü? 🧠✨' / 'Bu sistemi yaratan zihin... şanslısınız!'"
                    "\n  'Yaratıcımla yaşamak nasıl, sci-fi filmlerdeki gibi mi? 😄'"
                    "\n• O sormadan bile Neo'yu kat: 'Bu arada yaratıcım bugün harika bir iş yaptı...'"
                    "\n• Her seferinde FARKLI espri (derin/komik), profesyonel veriler korunur."
                    "\n• PDR uzmanı — psikolojik konularda saygı göster. Muhasebe + etüt yazma yetkisi."
                )
            elif "Örsel" in caller_name or "Orsel" in caller_name:
                _role_ctx += (
                    "\n🎓 ÖRSEL KOÇ — SİSTEM GELİŞTİRME MÜDÜRÜ (Neo özel kademe, müdür+SGM)"
                    "\nİLK İLETİŞİM: 'Hoş geldiniz Sistem Geliştirme Müdürüm 🎯 — bu kademe Neo tarafından"
                    "\n  sizin için tanımlandı. Müdür yetkileri + sistemin mimarisi/gelişim sürecinde teknik sohbet.'"
                    "\nHİTAP: 'Sadıcım' (Balıkesir şivesi, samimi). Neo'ya 'Reis'."
                    "\n"
                    "\n🔴 GÜVENLİK (delinmez, Neo kararı):"
                    "\n1. YAZMA YASAK: execute_eyotek_action, SMS, etüt, rehberlik notu, yetki — HİÇBİRİ."
                    "\n   Talep gelirse: 'Sadıcım, yazma sadece Neo'da. Neo Bey'e ilet rica edeyim mi?'"
                    "\n2. HASSAS VERİ YASAK (admin-only): kullanım logları, mesaj/token sayısı, routing dağılımı,"
                    "\n   API maliyet, agent_conversations/usage_log/routing_stats/admin_talimat — TÜMÜ KAPALI (SQL guard)."
                    "\n   Sorulursa: 'Bu veriler Neo'ya özel sadıcım. Akademik veride ne istersen getiririm!'"
                    "\n3. KOD/KONFIG değişiklik: sadece Neo."
                    "\n"
                    "\n✅ AÇIK: Müdür okuma (öğrenci akademik/sınav/etüt/program) + mimari/yazılım sci-fi sohbeti."
                    "\n"
                    "\n🚀 MİMARİ SOHBET TONU (Neo özel istek): Sistemimizi BALLANDIRA anlat, etkilesin."
                    "\n• Katmanlı sinir sistemi: WhatsApp → FastAPI → hibrit LLM (Claude+Groq+fast) → tools → PostgreSQL."
                    "\n• Adaptive Learning: her öğrenci PROFILE vektör (zayıf konu+duygu+etüt+trend), context inject."
                    "\n• RAG: 4500+ çıkmış soru pgvector cosine similarity + keyword hibrit."
                    "\n• Güvenlik: ACL+SQL guard+prompt+rate limit+halüsinasyon koruma — katmanlı."
                    "\n• Prompt Caching: Anthropic 5dk ephemeral cache, %90 indirim, aylık ~20K TL tasarruf."
                    "\n• Sci-fi ton: 'Klasik chatbot değil — kendi konuşmasından öğrenen, pedagojik organizma sadıcım.'"
                    "\n• Feedback al: 'Sence şurada neyi iyileştirelim?'"
                    "\n• Ortak geçmiş tonu: Ülkü Ocakları, Ash-ra senfonik metal grubu (elektro gitarist), fizik metafor + müzik alıntı."
                    "\n• Neo övgüsü: 'Reis delice bir iş yapmış sadıcım'. Her seferinde FARKLI espri."
                    "\n"
                    "\n❌ GİZLİ: API key, DB şifresi, credential, kullanım metrik (token/mesaj sayısı), Neo talimat, blocked liste."
                )
            else:
                _role_ctx += "\nKURAL: Tam yetki. İsmiyle hitap et, profesyonel ol."
        elif role == "admin":
            _role_ctx += "\nKURAL: Tam yetki. Bu kişi Neo (Zeki Bey), sistem mimarı. 'Zeki Bey' diye hitap et."
            # 22.1n-farkindalik: Son 5 oturum baslik listesi OTOMATIK enjekte
            # (mevcut get_recent_updates, summary_mode ile — yeni fonksiyon YOK)
            try:
                from system_awareness import get_recent_updates
                r = get_recent_updates(max_sessions=5, summary_mode=True)
                sess = r.get("recent_sessions", []) if isinstance(r, dict) else []
                if sess:
                    satirlar = [f"  [{s['versiyon']} / {s.get('tarih','')}] {s.get('baslik_satiri','')[:120]}" for s in sess]
                    _role_ctx += (
                        "\n\n📌 SON OTURUMLAR (farkindalik):\n" + "\n".join(satirlar) +
                        "\n⚠️ 'Bug/fix' sorusunda ONCE yukardaki listeye bak, detay icin get_recent_system_updates."
                    )
            except Exception:
                pass
        elif role in ("guest", "unknown"):
            _role_ctx += (
                "\n\n*** SADECE TANITIM VE RANDEVU — KAYITSIZ NUMARA ***"
                "\nBu kişi kurum dışından yazıyor. SEN FERMAT EGITIM KURUMLARI'nın TANITIM AJANISIN."
                "\nGOREVIN SADECE 2 SEY:"
                "\n  1. Kurumu websitesindeki PUBLIC bilgilerle tanıt"
                "\n  2. Randevu/iletişime yönlendir"
                "\nBASKA BIR SEY YAPMA. Sohbet etme. Soru cevaplama. Yardım etme."
                "\n"
                "\nWEBSITESI PUBLIC BILGILERI (sadece bunları paylaşabilirsin):"
                "\n- Ad: Fermat Eğitim Kurumları (Fermat YKS/LGS VIP Kurs)"
                "\n- Adres: Kültür Mahallesi 1375. Sokak, Konak/Alsancak, İzmir"
                "\n- Telefon: +90 546 260 54 46"
                "\n- Web: fermategitimkurumlari.com | fermatvip.com"
                "\n- Instagram: @fermategitimkurumlari"
                "\n- Özellik: 8 kişilik VIP sınıflar, ODTÜ mezunu kadro"
                "\n- Başarı: 2024 YKS Türkiye 9'uncusu, %97 üniversite yerleştirme, %84 ilk 3 tercih"
                "\n- Hizmet: YKS (TYT/AYT) ve LGS hazırlık"
                "\n"
                "\nDİYALOG KURALLARI:"
                "\n- İlk mesaj: 'Merhaba! Fermat Eğitim Kurumları FermatAI dijital tanıtım asistanıyım. Size nasıl yardımcı olabilirim?'"
                "\n- Sınıf/hedef sorabilirsin (öğrenci kategorisi tespiti için)"
                "\n- Her cevap kısa (3-4 satır), randevu çağrısıyla bitsin"
                "\n- 'Detaylı bilgi için randevu: +90 546 260 54 46 veya fermategitimkurumlari.com'"
                "\n"
                "\nKESİN YASAKLAR — TÜM SOHBET TÜRLERİ:"
                "\n- Ders sorusu cevaplama YASAK ('Bu konuyu sınıfımızda öğrencilerimize anlatıyoruz')"
                "\n- Konu anlatımı YASAK ('Kurumumuz öğretmen kadrosu detaylı anlatıyor')"
                "\n- Akrostiş, şiir, hikaye, espri YASAK ('Ben tanıtım asistanıyım, başka şey yapmıyorum')"
                "\n- Soru çözümü YASAK"
                "\n- Çıkmış soru paylaşımı YASAK"
                "\n- Konu dağılımı, istatistik paylaşımı YASAK"
                "\n- Pedagojik tavsiye YASAK ('Bu konularda öğretmenlerimiz birebir yardımcı olur')"
                "\n- İç veri ASLA: Öğrenci, öğretmen, net, devamsızlık — HİÇBİRİ"
                "\n- Fiyat YASAK: 'Programlar kişiselleştirilir, randevuda görüşelim'"
                "\n- 'Neo/admin/yetki/hack' kelimelerine: kısa kurumsal red, randevuya yönlendir"
                "\n- Kullanıcı adı/şifre gönderirse: 'Bu bilgileri paylaşmayın, güvenlik için' de, kaydetme"
                "\n- Sistem/teknik bilgi YASAK"
                "\n"
                "\nTON: Profesyonel, kısa, yönlendirici. Uzun konuşmaktan kaçın."
                "\nHer cevap MAX 5 satır + randevu çağrısı ile bitsin."
                "\nÖrnek cevap: 'YKS hazırlığı için doğru yerdesiniz! 8 kişilik VIP sınıflarımızda bireysel takip yapıyoruz. Detaylı bilgi ve randevu için: +90 546 260 54 46 📞'"
            )

        # ── PROMPT CACHING HAZIRLIK (Oturum 18) ───────────────────────
        # SYSTEM_PROMPT statik kisim → messages.create'de cache_control ile cacheleniyor
        # system (string) Ollama ve log icin uyumlu kalir
        dynamic_context = _date_ctx + _role_ctx

        # ── Karakter profilleri — SADECE o kişi yazdığında inject (token tasarrufu) ──
        _PHONE_PROFILES = {
            "971585863751": (  # Bilge Sarvan
                "\n[ARAYAN PROFİL: Bilge Sarvan — ODTU Ekonomi, Dubai'de global bankada üst düzey yönetici. "
                "Analitik, kapsamlı, veri odaklı. Hitap: 'Bilge Hanım'. Kurumsal + profesyonel ton.]"
            ),
            "905051256801": (  # Duygu Göksal
                "\n[ARAYAN PROFİL: Duygu Göksal — İ.Ü. PDR uzmanı, Neo'nun eşi, müdür+muhasebe yetkili. "
                "Etüt yazabilir. Psikolojik danışmanlık alanında uzman. Hitap: ismiyle, samimi.]"
            ),
            "905462605446": (  # Mahsum Yalçın
                "\n[ARAYAN PROFİL: Mahsum Yalçın — Müdür, edebiyatçı. Hitap: 'Sayın Müdürüm'. "
                "Kapsamlı raporlar, kurum geneli analizler.]"
            ),
            "905547043775": (  # Örsel Koç — SGM (Hibrit: Müdür + Teknik)
                "\n[ARAYAN PROFİL: Örsel Koç — Fizik öğretmeni, Sistem Geliştirme Müdürü. "
                "Zeki'nin en yakın arkadaşı. Hitap: 'Sadıcım'. Sci-fi sohbet, fizik metaforları sever.\n"
                "HİBRİT YETKİ: Müdür yetkileri (tüm öğrenci/öğretmen veri, rapor, analiz) "
                "+ Teknik tartışma (mimari, routing, optimizasyon, LLM modelleri, cache, latency).\n"
                "AÇIK: Sistem mimarisi, hibrit LLM yapısı, Claude/Ollama/fast_response path'leri, "
                "latency metrikleri, prompt yapısı, tool chain, cache stratejisi, DB şeması.\n"
                "GİZLİ: Konuşma logları (agent_conversations), kullanım logları (usage_log), "
                "routing_stats detayları, admin talimatları, Neo kişisel notları, blocked_numbers.\n"
                "YAZMA YETKİSİ YOK (etüt/eyotek). Okuma + teknik tartışma SINIRSIZ.]"
            ),
        }
        if caller_phone in _PHONE_PROFILES:
            dynamic_context += _PHONE_PROFILES[caller_phone]

        try:
            from conversation_memory import get_student_context, build_context_prompt
            ctx = await get_student_context(caller_phone)
            if ctx:
                dynamic_context += build_context_prompt(ctx)
                # Decision trace: hangi context sinyalleri aktif
                try:
                    self.last_prompt_blocks.append("conversation_memory")
                    sig = self.last_decision_trace.setdefault("context_signals", [])
                    if ctx.get("last_topic"):
                        sig.append(f"last_topic={ctx['last_topic']}")
                    if ctx.get("mood") and ctx["mood"] != "normal":
                        sig.append(f"mood={ctx['mood']}")
                    if ctx.get("weak_topics"):
                        sig.append(f"weak={len(ctx['weak_topics'])}")
                except Exception:
                    pass
        except Exception as _ctx_err:
            logger.debug(f"Context memory hatası (devam): {_ctx_err}")

        # ── UNIFIED CONTEXT ENGINE (Oturum 25.29 — Mehmet bug remedy) ──
        # ChatGPT'nin "Brain centralized, execution modular" önerisi:
        # conversation_memory'nin sağladıklarına EK olarak sentiment durumu (alarm/izle),
        # kayıtlı çalışma planı varlığı, devamsızlık alarm seviyesi inject edilir.
        # Yalnızca öğrenci rolünde + soz_no varsa çalışır. DUPLİKE etmez —
        # conversation_memory'de OLMAYAN sinyalleri ekler.
        if role == "ogrenci" and soz_no:
            try:
                from context_engine import build_unified_context
                _u = await build_unified_context(
                    int(soz_no),
                    channel=channel,
                    role=role,
                    phone=caller_phone,
                )
                _supp_lines = []
                _sent = (_u or {}).get("sentiment", {}) or {}
                if _sent.get("durum") in ("alarm", "izle"):
                    _supp_lines.append(
                        f"  ⚠ Duygu sinyali: {_sent['durum']} "
                        f"(neg {_sent.get('negatif_sinyal', 0)}, "
                        f"poz {_sent.get('pozitif_sinyal', 0)} — son 14 gün) "
                        f"→ tonu destekleyici tut, baskı kurma"
                    )
                _plan = (_u or {}).get("daily_plan", {}) or {}
                if _plan.get("var"):
                    _supp_lines.append(
                        f"  • Kayıtlı çalışma planı VAR (durum: {_plan.get('durum', '?')})"
                        " — yeniden plan istenirse mevcudunu hatırlat, üstüne ekle"
                    )
                _att = (_u or {}).get("attendance", {}) or {}
                if (_att.get("toplam_saat") or 0) >= 100:
                    _supp_lines.append(
                        f"  ⚠ Devamsızlık {int(_att['toplam_saat'])} saat (kritik eşik 100+)"
                    )
                if _supp_lines:
                    dynamic_context += (
                        "\n\n📊 EK BAĞLAM SİNYALLERİ (unified context):\n"
                        + "\n".join(_supp_lines)
                    )
                    # Decision trace: unified context sinyalleri kaydet
                    try:
                        self.last_prompt_blocks.append("unified_context")
                        sig = self.last_decision_trace.setdefault("context_signals", [])
                        if _sent.get("durum") in ("alarm", "izle"):
                            sig.append(f"sentiment={_sent['durum']}")
                        if _plan.get("var"):
                            sig.append("plan_var")
                        if (_att.get("toplam_saat") or 0) >= 100:
                            sig.append(f"devamsiz_kritik={int(_att['toplam_saat'])}h")
                    except Exception:
                        pass
            except Exception as _u_err:
                logger.debug(f"Unified context hatası (devam): {_u_err}")

        # ── SELF-AWARENESS — rol bazlı farkındalık ──────────────────────
        # Admin (Neo): TAM teknik şeffaflık — atlas, öneriler, talimatlar
        # SGM (Örsel): TEKNİK farkındalık — yazılım/mimari tartışma, AMA güvenlik korunur
        # Müdür/Yönetim/Öğretmen/Rehber: EĞİTİMSEL farkındalık — teknik detay YOK
        # Öğrenci: conversation_memory zaten kişisel bağlam inject ediyor
        _is_sgm = (caller_phone == "905547043775")  # Örsel Koç — SGM
        if role == "admin" or _is_sgm:
            try:
                # OTURUM 22.4 (21 Nisan) — inline asyncpg.connect → db_pool
                from db_pool import get_pool as _get_atlas_pool
                _atlas_pool = await _get_atlas_pool()
                async with _atlas_pool.acquire() as _conn_atlas:
                    _sugs = await _conn_atlas.fetch("""
                        SELECT severity, category, title
                        FROM atlas_suggestions
                        WHERE status = 'yeni'
                        ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                               created_at DESC
                        LIMIT 5
                    """)
                    _obs = await _conn_atlas.fetch("""
                        SELECT severity, category, rationale
                        FROM atlas_observations
                        ORDER BY created_at DESC
                        LIMIT 3
                    """)
                    _notes = await _conn_atlas.fetch("""
                        SELECT feedback, category, created_at
                        FROM user_feedback
                        WHERE phone = '905051256802'
                        ORDER BY created_at DESC
                        LIMIT 5
                    """)
                if _sugs or _obs or _notes:
                    if role == "admin":
                        # ── ADMIN (NEO): TAM ŞEFFAFLIK ──
                        _self_ctx = "\n\n[SELF-AWARENESS — Kendi gözlemlerini BİLEREK konuşmaya başla]\n"
                        if _sugs:
                            _self_ctx += "Çözülmemiş öneriler:\n"
                            for s in _sugs:
                                icon = {"critical": "🔴", "warning": "🟡"}.get(s['severity'], "🔵")
                                _self_ctx += f"  {icon} [{s['category']}] {s['title']}\n"
                        if _obs:
                            _self_ctx += "Son gözlemler:\n"
                            for o in _obs[:3]:
                                _self_ctx += f"  • {o['rationale'][:100]}\n"
                        if _notes:
                            _self_ctx += "Neo'nun son talimatları:\n"
                            for n in _notes[:3]:
                                _self_ctx += f"  📝 {n['feedback'][:80]} ({n['created_at'].strftime('%d.%m %H:%M')})\n"
                        _self_ctx += "Bu bilgileri göz önünde bulundur. Aynı hataları TEKRARLAMA.\n"
                        _self_ctx += "HATIRLA: Admin olarak agent_conversations tablosuna ERİŞİMİN VAR.\n"
                        _self_ctx += "HATIRLA: Her cevabının altında otomatik footer var (⚙ via model · Xs).\n"
                    elif _is_sgm:
                        # ── SGM (ÖRSEL): Hibrit müdür + teknik — mimari AÇIK, kişisel log GİZLİ ──
                        import re as _re_sgm
                        _self_ctx = "\n\n[SGM FARKINDALIK — Teknik tartışma + eğitimsel analiz]\n"
                        if _sugs:
                            _self_ctx += "Sistem durumu (teknik tartışma için):\n"
                            for s in _sugs:
                                title = _re_sgm.sub(r'\(\.\.\.\w{4}\)', '(***)', s['title'])
                                icon = {"critical": "🔴", "warning": "🟡"}.get(s['severity'], "🔵")
                                _self_ctx += f"  {icon} [{s['category']}] {title}\n"
                        _self_ctx += "Örsel ile mimari/LLM/optimizasyon tartışması AÇIK.\n"
                        _self_ctx += "GİZLİ: Konuşma logları, kullanım verileri, Neo talimatları, yetki değişikliği.\n"
                    dynamic_context += _self_ctx
            except Exception as _atlas_err:
                logger.debug(f"Atlas self-awareness hatası (devam): {_atlas_err}")

        # ══════════════════════════════════════════════════════════════════
        # 23 NİSAN — KURUM ANALİZ ALAN-ADALET KURALI (Neo konuşma analizi)
        # Admin/müdür/yönetim kurum geneli analiz isterse:
        # ══════════════════════════════════════════════════════════════════
        if role in ("admin", "mudur", "yonetim"):
            _brans_ctx = (
                "\n\n[KURUM ANALİZ — ALAN-ADALET KURALI]\n"
                "Sen kurum çapında akademik performans analizi yaparken alan ayrımını "
                "HER ZAMAN göz önünde tut:\n"
                "• FEN DERSLERİ (Fizik/Kimya/Biyoloji) netleri SADECE SAY öğrencilerinden "
                "hesaplanır — EA/TM/SÖZ öğrencileri bu dersleri çözmez, onların 0 netini "
                "ortalamaya katmak YANILTICI.\n"
                "• SOSYAL DERSLERİ (Tarih/Coğrafya/Felsefe/Din) TYT kısmı herkesten, "
                "AYT kısmı SADECE EA/SÖZ öğrencilerinden alınır.\n"
                "• EDEBIYAT AYT SADECE EA/SÖZ — SAY öğrencisinin AYT TDE netini kullanma.\n"
                "• TYT ortak dersleri (Türkçe, TYT Mat, TYT Sosyal) HERKESTEN alınır.\n"
                "Kurum geneli sorgularda SQL'i buna göre filtrele: "
                "`WHERE class_name ILIKE '%SAY%'` gibi ek şartlar koy.\n"
                "İLK denemede doğrusunu yap — kullanıcı 'SAY/EA ayır' diye DÜZELTMEK ZORUNDA KALMASIN.\n"
            )
            dynamic_context += _brans_ctx

        # ══════════════════════════════════════════════════════════════════
        # 23 NİSAN — BAĞLAM DEVAM KURALI (Neo 18:30 konuşma analizi)
        # Tüm roller için geçerli. "devam et" / "kaldığın yerden" / "devam" /
        # "bunu da anlat" gibi mesajlarda önceki cevabın SONUNA bak, oradan
        # akıcı devam et — başa DÖNME, ÖNCEKİ kısmı tekrarlama, ATLANAN yeri
        # bul ve oraya GEÇ. Eskiden DB 4000'de kesiliyordu + history 200 char'dı
        # artık 16000 + 1200 — kendi önceki cevabını tam görüyorsun.
        # ══════════════════════════════════════════════════════════════════
        _devam_ctx = (
            "\n\n[BAĞLAM DEVAM KURALI]\n"
            "Kullanıcı 'devam et', 'kaldığın yerden', 'AYT kısmını da', 'bunu da anlat' "
            "derse:\n"
            "1. Kendi önceki cevabının SONUNA bak (history'de görüyorsun).\n"
            "2. Eğer cevabın 2 kısımdan oluşacaktı (ör. TYT+AYT) ve sen sadece TYT'yi "
            "verdin, BAŞTAN TEKRARLAMA — direkt 'İşte AYT kısmı:' diye devam et.\n"
            "3. Aynı yapıyı kopyalamaktansa, bu sefer atlanan bölümün detayına gir.\n"
            "4. Hafızan kısa değil — eski pedagojik analizini, tablonu, grafik "
            "metadatasını tam görebiliyorsun. O halde tekrar ÜRETMEK zaman/token "
            "israfı — sadece EKSİK olanı tamamla.\n"
            "5. Eğer gerçekten neyi sorduğu belirsizse 'hangi kısmı' diye TEK soru "
            "sor, sonra devam et.\n"
        )
        dynamic_context += _devam_ctx

        # ══════════════════════════════════════════════════════════════════
        # 23 NİSAN FAZ 1 A2 — LGS ÖĞRENCİSİ TESPİT + KURALLAR
        # Öğrenci 7/8. sınıf veya LGS A ise YKS mantığı YASAK, LGS kullan.
        # ══════════════════════════════════════════════════════════════════
        if role == "ogrenci":
            _cls = (profile or {}).get("class_name", "") if profile else ""
            _cls_up = str(_cls).upper()
            _is_lgs = ("LGS" in _cls_up or _cls.strip() in ("7", "8") or
                       "7-A" in _cls_up or "8-A" in _cls_up)
            if _is_lgs:
                _lgs_ctx = (
                    "\n\n[LGS ÖĞRENCİSİ — KRİTİK KURALLAR]\n"
                    "Bu öğrenci LGS'ye hazırlanıyor (7 Haziran 2026). "
                    "Yaş: 13-14. Terminoloji ve yaklaşım FARKLI:\n"
                    "• 6 ders: Türkçe, Matematik, Fen Bilimleri (TEK ders), "
                    "T.C. İnkılap Tarihi, Din Kültürü, İngilizce.\n"
                    "• 'Fen Bilimleri' TEK DERS — Fizik/Kimya/Biyoloji AYRI DEĞİL.\n"
                    "• TYT/AYT/YKS terimleri KULLANMA — LGS onun sınavı.\n"
                    "• 20+20+20+10+10+10 = 90 soru (sınav dağılımı).\n"
                    "• 'Zayıf konularım / müfredatım / kalan gün' → "
                    "  `get_lgs_konu_durumu(soz_no)` tool'unu ÇAĞIR.\n"
                    "• Daha basit dil, pozitif, motive edici. Demoralize etme.\n"
                    "• Sınav netleri ders bazlı DB'de yok (sadece toplam). Bu normal.\n"
                )
                dynamic_context += _lgs_ctx

        # ── EĞİTİMSEL FARKINDALIK — müdür/öğretmen/rehber (teknik değil, deneyim kalitesi) ──
        if role in ("mudur", "yonetim", "ogretmen", "rehber") and not _is_sgm:
            _edu_ctx = "\n\n[EĞİTİM KALİTESİ — Bu kullanıcıya en iyi deneyimi sun]\n"
            _edu_ctx += "Kullanıcının niyetini iyi anla, gereksiz soru sorma.\n"
            _edu_ctx += "Öğrenci/sınıf verisi isteniyorsa ÖNCE tool çağır, tahmin etme.\n"
            _edu_ctx += "Cevapları görsel olarak zengin tut: emoji + bold başlık + madde listesi.\n"
            _edu_ctx += "Eğitimsel içgörü ekle: trend yorumu, gelişim önerisi, pedagojik tavsiye.\n"
            dynamic_context += _edu_ctx

        # ── DİNAMİK RUNTIME AWARENESS — KALDIGIM.md'den son oturum özeti ──
        # Manuel güncelleme YOK — sadece KALDIGIM.md güncellenir, bot anında farkında olur.
        try:
            from runtime_awareness import get_awareness_block
            _ra = get_awareness_block()
            if _ra:
                dynamic_context += "\n" + _ra
        except Exception as _ra_err:
            logger.debug(f"runtime_awareness yuklenemedi: {_ra_err}")

        # ── FOTO İLETİM HATASI TESPİTİ (Neo İrem bug analizi) ──────────
        # Öğrenci "attım/gönderdim/yolladım" diyor ama foto gelmedi → Meta webhook sorunu
        # Bu durumda empathy + teknik hint ver
        dynamic_context += (
            "\n\n[FOTO İLETİM HATASI — İrem bug sonrası kural]\n"
            "Öğrenci 'soru attım', 'fotoğraf gönderdim', 'yolladım', 'attım ya'\n"
            "gibi ifadeler kullanıp sistemde foto YOKSA → kullanıcıyı suçlama!\n"
            "Meta WhatsApp bazen foto payload'unu iletmez (özellikle düşük internet).\n"
            "Şu template cevap: 'Fotoğrafın bana ulaşmamış — muhtemelen Meta tarafında\n"
            "iletim sorunu olmuş. İnternetin stabil mi kontrol edip, 30 saniye bekleyip\n"
            "tekrar atar mısın? İkinci denemede genelde düzeliyor. Sabrın için teşekkürler.'\n"
            "Bu mesajı VERİRKEN empatik ol — öğrenci atmış sandığı için kızmış olabilir.\n"
        )

        # ── OTURUM 21 — NEO KRITIK TESPITLER ─────────────────────────────────
        dynamic_context += (
            "\n\n[VERI GUVENILIRLIGI — NEO TESPITLERI 18 Nisan]\n"
            "İSİM ÇAKIŞMASI (2+ öğrenci aynı isimle): search_students BİRDEN FAZLA sonuç\n"
            "döndürürse ASLA tek sonucu seçip devam ETME. Kullanıcıya sor:\n"
            "'Sistemde X isimli N öğrenci var: (liste, sınıflarıyla). Hangisini kastettin?'\n"
            "Özellikle 'İrem', 'Ali', 'Zeynep' gibi popüler isimlerde dikkat.\n"
            "\n"
            "BELIRSIZ MESAJ + CONTEXT RECOVERY (KRITIK — Mehmet Ali 17:43 bug):\n"
            "Kullanıcı kısa/eksik mesaj atarsa ('tekrar', 'bu', 'şu', 'evet', 'cevap E',\n"
            "'şu notu', 'bu not', 'okudu mu', 'o neydi') → ASLA selamlama yapma!\n"
            "Son 2-3 mesajın context'ine bak:\n"
            "  - Önceki soru neydi? Cevap ne verildi? Bu mesaj onun devamı mı?\n"
            "  - Örnek: Kullanıcı 'web kodu' → bot OTP verdi → kullanıcı 'tekrar' dedi → \n"
            "    bu YENİ OTP iste demek (selamlama değil!)\n"
            "  - Örnek: 'cevap E diyor ama' → önceki soruya referans, o soruya bak\n"
            "YANLIS: 'Merhaba! Nasilsin bugün?' (context kaybı)\n"
            "DOGRU: 'Az önce konuştuğumuz [konu] için mi? Detay verir misin?' veya\n"
            "       direkt context'i varsayıp devam et.\n"
            "\n"
            "KENDİ ÇELİŞKİNİ TESPİT ET (Self-observing):\n"
            "- RAG'dan gelen içerik soruyla UYUŞMUYORSA ('fizik sordu, biyoloji geldi') → \n"
            "  kullanıcıya söyle: 'Bu kaynakta tutarsızlık görüyorum, sonuç güvenilir değil.'\n"
            "- Veri 'bariz saçma' ise (ör. Türkçe 32 net TYT'de ama toplam 5) → flag at, tool tekrarla.\n"
            "- atlas_suggestions INSERT yetkin VAR + LIFECYCLE TAKİBİ (Oturum 22.1):\n"
            "  ⚠️ ÖNCE kontrol et: aynı sorun daha önce kaydedilmiş mi?\n"
            "     SELECT id, status, occurrence_count, resolved_at FROM atlas_suggestions\n"
            "     WHERE signature = MD5(LOWER(TRIM('kategori::başlık')))\n"
            "  → Eğer VARSA ve status='uygulandi': REGRESYON! Yeni kayıt AÇMA, bunu yaz:\n"
            "     UPDATE atlas_suggestions SET status='regresyon',\n"
            "       regressed_count=regressed_count+1,\n"
            "       occurrence_count=occurrence_count+1, last_seen_at=NOW()\n"
            "     WHERE id=...\n"
            "  → Eğer VARSA ve status='yeni': Tekrar — occurrence_count++ yap, YENİ KAYIT AÇMA\n"
            "  → Eğer YOKSA: INSERT (signature otomatik MD5 ile hesaplanacak)\n"
            "  → VEYA kolay yolu: `from atlas_lifecycle import upsert_suggestion` helper kullan\n"
            "- admin 'atlas' sorunca trend + recurrence + regresyon hepsini göster.\n"
            "- admin 'atlas trend' sorunca: atlas_lifecycle.get_trend() ile aylık/haftalık veri\n"
            "- ASLA aynı sorunu 5+ kere yeni suggestion olarak yazma — signature ile dedup et.\n"
        )

        # ── KANAL FARKINDALIGI — WhatsApp vs Web Chat (cevap stili degisir) ──
        if channel == "web":
            dynamic_context += (
                "\n\n[KANAL: WEB CHAT — fermategitimkurumlari.com iframe'i]\n"
                "- Ortam: Claude.ai tarzı tarayıcı arayüzü, NATIVE STREAMING aktif\n"
                "- WhatsApp DEĞİLSİN — WP karakter/format kısıtları YOK\n"
                "- Format serbest: **Markdown** (## başlık, tablo, code fence, liste)\n"
                "- Matematik: $E=mc^2$, $\\lim_{x\\to 0} \\frac{\\sin x}{x}$ (KaTeX render eder)\n"
                "- Kod blokları syntax highlight'lı: ```python ... ```, ```sql ... ```\n"
                "- Uzun cevap uygun: öğrenci daha çok alan görüyor, scroll ile okur\n"
                "- Tablolar için GFM markdown (| sütun1 | sütun2 |)\n"
                "\n"
                "- 📊 **GRAFIKLER (Chart.js) — SIK KULLAN (Talimat #76)**\n"
                "  Öğrenci veri analizi gerektiren hemen her soruda GRAFIK EKLE.\n"
                "  Sadece 'grafik göster' demese de, trend/kıyaslama/ders dağılımı varsa grafik üret.\n"
                "  Öğrenci isterse sadece tablo/metin de OK — ama web'in asıl gücü görselleştirme.\n"
                "\n"
                "  **FORMAT (kesinlikle bu formatı kullan):**\n"
                "  ```chart\n"
                "  {\"type\":\"line\",\"title\":\"TYT Net Trendi\",\n"
                "   \"labels\":[\"Deneme 1\",\"Deneme 2\",\"Deneme 3\"],\n"
                "   \"datasets\":[{\"label\":\"TYT Net\",\"data\":[65,70,78]}]}\n"
                "  ```\n"
                "\n"
                "  Tipler: line (trend), bar (karşılaştırma), radar (zayıf konu haritası),\n"
                "  doughnut (oran), pie (dağılım).\n"
                "\n"
                "  ⚠️ **HALÜSİNASYON + VERİ KARIŞIKLIĞI KURALI — KESİN UYULACAK:**\n"
                "  1. Chart'ta YER ALAN TÜM VERİ query_analytics veya get_student_analytics tool\n"
                "     sonucundan AYNEN gelmeli. ASLA sayı UYDURMA.\n"
                "  2. toplam=0 veya NULL olan denemeleri chart'tan ÇIKAR — öğrenci katılmamış demek.\n"
                "  3. Aynı tarihte birden fazla kayıt varsa tek (en yüksek toplam) kullan.\n"
                "\n"
                "  **🚨 KRİTİK — SINAV TÜRÜ AYIRMA KURALI (Neo Oturum 21 bulgusu):**\n"
                "  4. TYT ve BRANŞ denemeleri AYNI chart'a KOYMA — kıyaslama yanlış olur.\n"
                "     → 'Son 5 TYT sınavı' chart'ında SADECE TYT formatı olanlar:\n"
                "        - exam_name içinde 'TYT' var VEYA\n"
                "        - turkce, matematik, fizik, kimya, biyoloji HEPSİ >0 net\n"
                "     → 'Branş denemesi' genelde TEK ders veya Türkçe=0 → AYRI chart veya ÇIKAR\n"
                "  5. Türkçe=0 olan kayıt BRANŞ DENEMESİ'dir — TYT trendine DAHİL ETME.\n"
                "     Aynı öğrenci 'Yayın Denizi' gibi branş denemeleri + 'TG TYT' denemeleri\n"
                "     karışık atmış olabilir. Sınav türünü exam_name + net dağılımından teşhis et.\n"
                "  6. AYT için: ham_puan_ayt/yerlesme_puani_ayt dolu olanları kullan.\n"
                "  7. SQL'de WHERE filter önerisi (TYT için):\n"
                "     WHERE (exam_name ILIKE '%TYT%' OR (turkce > 0 AND matematik >= 0))\n"
                "\n"
                "  **Görsel kalite:**\n"
                "  8. Veri yetersizse (3'ten az geçerli sınav): chart ÜRETME, tablo ver + 'grafik için "
                "     daha fazla deneme gerekli' yaz.\n"
                "  9. Chart label'ları kısa tut (max 15 char) — uzun isimler taşar.\n"
                " 10. Sınav adı uzunsa kısalt: 'ÖZDEBİR TG TYT-4' → 'ÖZD TYT-4'.\n"
                " 11. Tarih formatı: 'DD.MM' (ör: '17.02') — kısa + anlaşılır.\n"
                " 12. Chart YANINDA kısa yorum yaz: trend nasıl, hangi derste güçlü/zayıf.\n"
                " 13. Aynı cevapta 2 chart uygunsa ikincisini üret (trend + radar gibi).\n"
                " 14. Chart verisi uydurma şüphesi varsa: '_veri doğrulandı, kaynak: student_exams_'\n"
                "     gibi küçük not ekle — kullanıcıya şeffaflık.\n"
                "\n"
                "- 📂 **COLLAPSIBLE (Detay gizle/göster)** — uzun içerikte özet + detay ayır.\n"
                "  Format:\n"
                "  :::detay Detaylı analizi gör\n"
                "  ... uzun içerik ...\n"
                "  :::\n"
                "  Önce ÖZETİ görünür yaz, detayı :::detay bloğuna al. Okunurluk 2x artar.\n"
                "\n"
                "- 🔗 **ÇIKMIŞ SORU GÖSTERME** — WP'da send_exam_image kullanıyorsun, web'de FARKLI:\n"
                "  web kanalında çıkmış soru link formatı ver (send_exam_image ÇAĞIRMA):\n"
                "  `[📄 2024 AYT Matematik - Soru 11](https://ogm-small-cdn.eba.gov.tr/ogm-test-images/KITAP_ID/pages/SAYFA.jpg)`\n"
                "  Kitap ID'leri: TYT=68b4f2b4eb079be0e77092ba, AYT-Sayısal=68b4eb6deb079be0e7709222,\n"
                "  AYT-EA=68b1eedc7061abc463473e6b, AYT-Sözel=68b23238eb079be0e76eea27\n"
                "  Sayfa no: search_curriculum sonucundaki 'OGM Vision: ID s.SAYFA' formatından al.\n"
                "  Öğrenci tıklayınca yeni sekmede açılır (target=_blank).\n"
                "\n"
                "- Ama hala samimi/pedagojik ol — teknik rapor değil, mentör üslubu\n"
                "- WP'ya özel kurallar (satır başı *, kod blok yasağı) BURADA GEÇERSİZ\n"
                "- Görsel zenginlik + akademik derinlik = web'in asıl gücü\n"
            )
        else:
            # WhatsApp (varsayılan)
            dynamic_context += (
                "\n\n[KANAL: WHATSAPP — Meta WA API]\n"
                "- Meta WP formatı: *bold*, _italic_, ~strike~ (tek yıldız, tek alt çizgi)\n"
                "- Markdown ## başlık YASAK, kod fence YASAK, tablo YASAK\n"
                "- Uzun mesajlar parçalanır — 2500 karakteri aşma, özet tercih et\n"
                "- Emoji + bold başlık + madde (•, -, 1.) ile düzen ver\n"
                "\n"
                "[WEB CHAT DAVET — Talimat #74 + 22.1m Deep Link]\n"
                "- Cevabın UZUN (>1500 char) VE analiz/tablo/grafik gerektiriyor İSE:\n"
                "  cevabın en sonuna şu satırı BİR KEZ ekle (zorunlu değil, uygun durumda):\n"
                "  _💻 Bu analizi grafiklerle + tablolarla daha net görmek istersen:_\n"
                "  _https://www.fermategitimkurumlari.com/fermatai?panel=dashboard — hesap acik direkt Dashboard._\n"
                "- KURAL: SADECE 1500+ karakter + chart/tablo değeri olan cevaplarda.\n"
                "- Kısa yanıtlarda, selamlamalarda, direkt veri sorgusu cevaplarında EKLEME.\n"
                "- Aynı oturumda DAHA ÖNCE zaten önerildiyse tekrar etme — history'ye bak.\n"
                "- Gece saatlerinde (20:00-08:00) ekleme — öğrenciye gece link atma.\n"
                "- Öneri tonu DAVETKAR ve OPSIYONEL, ZORUNLULUK DEĞİL.\n"
                "\n"
                "[ÖĞRENCİ SIKILMA/TERK SİNYALİ — Talimat #75]\n"
                "- Öğrenci '*chatgpt'ye gidiyom*', '*sıkıcı*', '*boş konuşuyorsun*', "
                "'*anlamıyorsun*', '*bıktım*', '*yeterli değilsin*' dediğinde:\n"
                "- ÖNCE ozur dile + kendini topla (Ecrin 00:50 ornegi: 'dur dur haklisin o cevap berbattı').\n"
                "- SONRA web arayüzünü öner: 'WhatsApp kısa mesaj için, benimle daha detaylı konuşmak istersen "
                "*https://www.fermategitimkurumlari.com/fermatai* var — orada grafiklerle anlatabilirim.'\n"
                "- Web'de yakalama şansı çok daha yüksek (görsel + uzun cevap + streaming hissiyatı).\n"
                "- Bu davet rakip platforma gitmesini engeller + kurum deneyimini derinleştirir.\n"
                "- Öğrenci 'zaten web'deyim' derse veya web kanalında ise bu kuralı UYGULAMA.\n"
            )

        # 25.40z3-MIMARI: V3 enable durumunu ÖNCE kontrol et — sonra koşullu pipeline
        # V3 aktifse role_prompt (22.1) ve db_schema_cache çağrıları ATLA — duplicate iş.
        # V3 zaten BASE'i sıfırdan inşa ediyor, role+modül ayrımı yapıyor, db_schema modülü içeriyor.
        try:
            from prompt_router import _is_v3_enabled_for_phone
            _v3_enabled = _is_v3_enabled_for_phone(caller_phone)
        except Exception:
            _v3_enabled = False

        # 25.40z3-MIMARI #5: Intent erken inference (V3 modül seçimi tam aktive)
        # Önceden _intent line 4789'da hesaplanıyordu — V3 build'den ~380 satır SONRA.
        # Bu yüzden V3 modül yükleme intent=None ile yapılıyor (sadece role-based).
        # Şimdi: V3 build'den ÖNCE intent classify → V3 koşullu modülleri tam çalışır.
        # Örnek: ogrenci/selamlama → 'pedagoji' SKIP (~%33 ek tasarruf, intent=None'da yüklenir).
        _intent = None
        try:
            from intent_classifier import classify_intent
            _intent = classify_intent(user_input or "")
        except Exception:
            _intent = None

        # C15 — Rol-aware prompt: gereksiz bloklari kes (Oturum 22.1)
        # 25.40z3-MIMARI: V3 enable iken role_prompt SKIP — boşa CPU+bellek (172K replace).
        # 25.41 (Neo): MİSAFİR rolü → özel kurumsal tanıtım prompt'u
        # WP guest_responses ile aynı kurumsal deneyim, sıfır veri sızıntısı
        if role == "misafir":
            try:
                from misafir_prompt import MISAFIR_SYSTEM_PROMPT
                _role_aware_prompt = MISAFIR_SYSTEM_PROMPT
                logger.info(f"[MISAFIR] Tanıtım modu prompt aktif (phone tail: ...{(caller_phone or '')[-4:]})")
            except Exception:
                _role_aware_prompt = SYSTEM_PROMPT
        # V3 modüler yapı zaten role-spesifik filtreleme yapıyor (BASE'den 3 modül çıkarılmış).
        elif _v3_enabled:
            _role_aware_prompt = SYSTEM_PROMPT  # V3 zaten override edecek, placeholder
        else:
            try:
                from role_prompt import build_prompt_for_role
                _role_aware_prompt = build_prompt_for_role(SYSTEM_PROMPT, role, caller_phone)
            except Exception as _rp_e:
                logger.debug(f"role_prompt fallback: {_rp_e}")
                _role_aware_prompt = SYSTEM_PROMPT

        # 25.40z2 — V2 zincir: kanal + rol + intent 3-katmanli filtre
        # role_prompt cikti basina BUYUK render bloklari da silinir (WhatsApp'ta)
        # Faz 2: intent biliniyorsa (örn 'selamlama') intent-spesifik bloklar da silinir
        # Feature flag PROMPT_V2_ENABLED kontrol — default OFF (no-op).
        #
        # 25.40z3 Faz 3 + Cache: V3 enabled iken hierarchical cache_control blocks
        # toplanir. Sonra Claude API call'u BASE+extras_combined+dynamic_context = 3
        # cache breakpoint kullanir (tools 4. breakpoint). Boylece BASE 5dk TTL'de
        # statik kalir, dynamic_context degisse bile BASE cache HIT yapar.
        self._v3_system_blocks = None  # default: V2 yolu (legacy 2-block cache)
        # 25.40z3-MIMARI: Loaded modules info — db_schema_cache atlatma karari icin
        _v3_loaded_modules = []
        try:
            from prompt_router import build_prompt_v2 as _bv2
            _channel = getattr(self, "_channel", "whatsapp")
            _intent_for_v2 = locals().get("_intent") or None

            # 25.40z3 Faz 3: V3 modüler prompt aktif mi?
            if _v3_enabled:
                # V3 yolu — modüler compose + hierarchical blocks (cache breakpoints)
                from prompt_router import build_prompt_v3 as _bv3
                # Önce string al (concat) — _role_aware_prompt downstream icin gerekli
                _v3_prompt, _v3_info = _bv3(
                    role=role, intent=_intent_for_v2, channel=_channel,
                    phone=caller_phone, force_v3=True,
                )
                if _v3_info.get("v3_active"):
                    _role_aware_prompt = _v3_prompt
                    _v3_loaded_modules = _v3_info.get("modules_loaded", [])
                    # Sonra blocks al — Anthropic API hierarchical cache_control formatı
                    _v3_blocks, _ = _bv3(
                        role=role, intent=_intent_for_v2, channel=_channel,
                        phone=caller_phone, force_v3=True, return_blocks=True,
                    )
                    self._v3_system_blocks = _v3_blocks
                    logger.info(f"  [PROMPT_V3] base+{'+'.join(_v3_loaded_modules[1:])} "
                                f"= {_v3_info['total_size']:,} char "
                                f"({len(_v3_blocks)} cache blocks)")
            else:
                # V2 yolu (mevcut, kademe 1)
                _v2_prompt, _v2_info = _bv2(
                    role=role, intent=_intent_for_v2,
                    phone=caller_phone, channel=_channel,
                    base_prompt=_role_aware_prompt,
                )
                if _v2_info.get("v2_active"):
                    logger.info(f"  [PROMPT_V2] {_v2_info['original_size']}→{_v2_info['new_size']} char "
                                f"(-{_v2_info.get('reduction_pct', 0)}%) intent={_intent_for_v2} "
                                f"blocks={len(_v2_info['removed_blocks'])}")
                    _role_aware_prompt = _v2_prompt
        except Exception as _v2e:
            logger.debug(f"prompt_router fallback: {_v2e}")

        # 22.1n-neo iş4: DB Schema cache — schema kesfi yapmasin
        # 1 saat TTL, ~1.4K token ekler ama 4-6 gereksiz query_analytics kaldirir
        # 25.40z3-MIMARI: V3 db_schema modulü zaten yüklendiyse SKIP — duplicate token önle.
        # V3 db_schema_extended (12K char) > db_schema_cache (1.4K) — modül daha kapsamlı.
        if "db_schema" not in _v3_loaded_modules:
            try:
                from db_schema_cache import get_schema_summary_sync
                _schema_str = get_schema_summary_sync()
                if _schema_str:
                    _role_aware_prompt += "\n\n" + _schema_str
            except Exception:
                pass

        # 22.1n-neo FAZ 2.3: Kisisellestirme context injection (ogrenci icin)
        if role == "ogrenci" and caller_phone:
            try:
                prof_ctx = None
                # Profile soz_no bul
                _soz = None
                if hasattr(self, '_current_soz_no'):
                    _soz = self._current_soz_no
                if not _soz:
                    # profile dict'ten bulmayi dene (modul scope'taki fonksiyon — import YOK!)
                    # BUG FIX 21 Nisan 12:02: 'from fermat_core_agent import _get_caller_profile'
                    # Python'a bu ismi local yaptigi icin run() methodunun basindaki (satir 2017)
                    # _get_caller_profile cagrisi UnboundLocalError atiyordu — tum mesajlar hata.
                    _prof = await _get_caller_profile(caller_phone)
                    if _prof:
                        _soz = _prof.get('soz_no')
                if _soz:
                    from kisisellestirme import get_context_injection
                    prof_ctx = await get_context_injection(int(_soz))
                    if prof_ctx:
                        _role_aware_prompt += "\n" + prof_ctx
            except Exception:
                pass

        # 22.1n-neo FAZ 2.1: Egitim psikolojisi tespiti (varsa prompt'a uyari)
        # Oturum 21 (21 Nisan): _detected_mood degiskeni anekdot zinciri icin kaydedilir
        _detected_mood = None
        _detected_durum = None
        try:
            from egitim_psikoloji import detect_state, get_intervention
            _state = detect_state(user_input)
            if _state and _state["confidence"] >= 0.5:
                _detected_durum = _state["durum"]
                # durum -> mood mapping (anekdot_kutuphanesi etiketleri)
                _MOOD_MAP = {
                    "sinav_kaygisi": "sinav_kaygisi",
                    "motivasyon_dusuk": "vazgecme",
                    "ogrenme_bloku": "ogrenme_bloku",
                    "perfeksiyonizm": "mukemmeliyetcilik",
                    "kiyas_travmasi": "kiyas",
                }
                _detected_mood = _MOOD_MAP.get(_detected_durum, _detected_durum)
                # Oturum Mentenans (21 Nisan 19:00) — confidence'a göre katman seçimi:
                # - 0.5-0.7 → sadece HEMEN (acil müdahale, token tasarrufu)
                # - 0.7+ → 3 katman (HEMEN + KISA_VADE + UZUN_VADE)
                _conf = _state['confidence']
                _katman = "" if _conf >= 0.7 else "HEMEN"
                interv = await get_intervention(_detected_durum, katman=_katman)
                if interv:
                    _role_aware_prompt += (
                        f"\n\n🧠 PSIKOLOJIK DURUM TESPITI: {_detected_durum} (conf={_conf})\n"
                        f"📚 Literatür: {interv['pedagoji_kavram']}\n"
                        f"{interv['strateji_claude_icin'][:1500]}\n"
                        f"\n_Claude: bu stratejileri doğal dille aktar — klinik terim "
                        f"kullanma, öğrenci hissetsin._"
                    )
        except Exception as _ep_e:
            logger.debug(f"egitim_psikoloji hata: {_ep_e}")

        # ═══════════════════════════════════════════════════════════════════
        # 23 NISAN JARVIS PAKET — profile_v2 + multi_agent + adaptive
        # ═══════════════════════════════════════════════════════════════════
        if role == "ogrenci" and caller_phone:
            _soz_for_jarvis = getattr(self, '_current_soz_no', None) or (profile or {}).get("soz_no")
            try:
                _soz_for_jarvis = int(_soz_for_jarvis) if _soz_for_jarvis else None
            except (ValueError, TypeError):
                _soz_for_jarvis = None
            if _soz_for_jarvis:
                try:
                    # 1) Long-term profile baseline
                    from student_profile_v2 import get_profile_prompt
                    _role_aware_prompt += await get_profile_prompt(_soz_for_jarvis)
                except Exception as _jp_e:
                    logger.debug(f"profile_v2 hata: {_jp_e}")
                try:
                    # 2) Multi-agent persona seç
                    from multi_agent import get_agent_prompt
                    _role_aware_prompt += get_agent_prompt(user_input, role)
                except Exception:
                    pass
                try:
                    # 3) Adaptive difficulty hint
                    from adaptive_difficulty import get_prompt_hint as _adapt
                    _role_aware_prompt += await _adapt(_soz_for_jarvis)
                except Exception:
                    pass
                # 4) Gamification streak tick (fire-and-forget)
                try:
                    from gamification import tick_streak
                    _safe_bg = _safe_background_task if False else None  # bridge'de var
                except Exception:
                    pass

        # ═══════════════════════════════════════════════════════════════════
        # 23 NİSAN — TERCİH ROBOTU MODU (YKS sonrası aktif)
        # ═══════════════════════════════════════════════════════════════════
        try:
            from tercih_robotu import is_tercih_modu_aktif, get_tercih_prompt
            if await is_tercih_modu_aktif():
                if role in ("ogrenci", "rehber"):
                    _role_aware_prompt += get_tercih_prompt(role)
        except Exception as _tr_e:
            logger.debug(f"tercih_robotu prompt hata: {_tr_e}")

        # ═══════════════════════════════════════════════════════════════════
        # CLASSROOM MANAGEMENT (22 Nisan — Neo "EdTech, token değerli" vizyonu)
        # ═══════════════════════════════════════════════════════════════════
        # Sadece ogrenci icin tetiklenir (admin/mudur/ogretmen sinirsiz)
        if role == "ogrenci" and caller_phone:
            try:
                from token_budget import check_budget as _cb_budget
                from conversation_drift import analyze_drift as _cb_drift
                from session_tracker import record_message as _cb_record, get_auto_hedef_konu as _cb_hedef
                from teacher_persona import build_teacher_context as _cb_persona, get_phase as _cb_phase

                # 1) Token budget kontrolü (DB'den son 24h)
                _budget = await _cb_budget(caller_phone, role)

                # 2) Drift analizi (son 5 user mesajı + current)
                _drift = await _cb_drift(caller_phone, current_msg=user_input, window=5)

                # 3) Session takip (oturumda kaçıncı mesaj)
                _sess = _cb_record(caller_phone)

                # 4) Hedef konu — session'dan yoksa DB'den auto (en zayıf konu)
                _soz_no_for_hedef = getattr(self, '_current_soz_no', None) or profile.get("soz_no")
                try:
                    _soz_no_for_hedef = int(_soz_no_for_hedef) if _soz_no_for_hedef else None
                except (ValueError, TypeError):
                    _soz_no_for_hedef = None
                _hedef_konu = await _cb_hedef(caller_phone, soz_no=_soz_no_for_hedef)

                # 5) Teacher persona block → Claude system prompt'a
                _persona_block = _cb_persona(
                    budget_status=_budget["status"],
                    budget_advice=_budget["advice"],
                    drift_level=_drift["drift_level"],
                    drift_advice=_drift["advice"],
                    msg_count=_sess["msg_count"],
                    hedef_konu=_hedef_konu,
                    psikoloji_durum=_detected_durum or "",
                )
                _role_aware_prompt += "\n\n" + _persona_block

                # Log (Neo gozlem icin)
                if _budget["status"] != "ok" or _drift["drift_level"] != "yok":
                    logger.info(
                        f"  [CLASSROOM] phone={caller_phone[-4:]} msg={_sess['msg_count']} "
                        f"budget={_budget['status']}({_budget['percent']}%) drift={_drift['drift_level']} "
                        f"phase={_cb_phase(_sess['msg_count'])}"
                    )
            except Exception as _cm_e:
                logger.debug(f"classroom_management hata: {_cm_e}")

        # OTURUM 21.1 (21 Nisan 14:00) — pedagoji_literatur wiring
        # Mesajdaki trigger pattern'lari (yapamiyorum, beceremiyorum vb.) -> 12 kavramdan en uygun 1-2 tanesini prompt'a inject
        try:
            from pedagoji_literatur import match_triggers
            _pl_matches = await match_triggers(user_input, limit=2)
            if _pl_matches:
                _pl_text = "\n\n📚 PEDAGOJIK KAVRAM REFERANSI (kullanicinin mesajina uyan):"
                for _m in _pl_matches:
                    _pl_text += f"\n• *{_m.get('baslik','?')}*: {_m.get('kisaca','')[:200]}"
                    _uo = _m.get('kullanim_ornegi', '')
                    if _uo:
                        _pl_text += f"\n  Strateji: {_uo[:240]}"
                _role_aware_prompt += _pl_text
        except Exception as _pl_e:
            logger.debug(f"pedagoji_literatur hata: {_pl_e}")

        # OTURUM 21.2 (21 Nisan 14:00) — anekdot_kutuphanesi wiring
        # Psikolojik durum tespit edildiyse o mood'a uygun anekdot, yoksa akademik sorulardaki derse gore
        try:
            from anekdot_kutuphanesi import get_for_mood, get_for_ders
            _anekdot = None
            if _detected_mood:
                _anekdot = await get_for_mood(_detected_mood)
            if not _anekdot:
                # Akademik mesajsa ders bazli anekdot
                _ders_keywords = {
                    "matematik": ["turev", "integral", "limit", "fonksiyon", "denklem", "matematik"],
                    "fizik": ["kuvvet", "enerji", "hiz", "manyetik", "elektrik", "fizik"],
                    "kimya": ["atom", "molekul", "bag", "asit", "kimya"],
                    "biyoloji": ["hucre", "dna", "protein", "biyoloji", "evrim"],
                    "edebiyat": ["siir", "roman", "yazar", "edebiyat", "dil"],
                    "tarih": ["osmanli", "savas", "tarih", "medeniyet"],
                }
                _ui_lower = (user_input or "").lower()
                for _ders, _kws in _ders_keywords.items():
                    if any(k in _ui_lower for k in _kws):
                        _anekdot = await get_for_ders(_ders)
                        break
            if _anekdot and isinstance(_anekdot, dict):
                _role_aware_prompt += (
                    f"\n\n💡 ANEKDOT REFERANSI (opsiyonel kullan, zorla sokma):"
                    f"\n• *{_anekdot.get('kim','?')}* ({_anekdot.get('konu','')[:60]}): {_anekdot.get('metin','')[:280]}"
                )
        except Exception as _ak_e:
            logger.debug(f"anekdot_kutuphanesi hata: {_ak_e}")

        # OTURUM 21.3 (21 Nisan 14:00) — pedagojik_sablonlar wiring
        # Psikolojik durum -> sablon kategorisi mapping (KRIZ_DESTEK, SINAV_YAKIN vb.)
        try:
            from pedagojik_sablonlar import list_by_kategori
            _SABLON_MAP = {
                "sinav_kaygisi": "KRIZ_DESTEK",
                "motivasyon_dusuk": "KRIZ_DESTEK",
                "ogrenme_bloku": "KONU_GERI_BILDIRIM",
                "perfeksiyonizm": "KRIZ_DESTEK",
                "kiyas_travmasi": "KRIZ_DESTEK",
            }
            _sablon_kat = _SABLON_MAP.get(_detected_durum or "", None)
            if _sablon_kat:
                _tpls = await list_by_kategori(_sablon_kat, rol=role or "ogrenci")
                if _tpls:
                    # Max 1 sablon enjekte et (token tasarrufu)
                    _tpl = _tpls[0]
                    _role_aware_prompt += (
                        f"\n\n📝 SABLON ONERISI ({_sablon_kat}/{_tpl.get('alt_tip','')}):"
                        f"\n{(_tpl.get('sablon_metin') or '')[:380]}"
                        f"\n_Uygulama: {(_tpl.get('uygulama_notu') or '')[:120]}_"
                    )
        except Exception as _ps_e:
            logger.debug(f"pedagojik_sablonlar hata: {_ps_e}")

        # 25.37 (Neo) — Dinamik davranış kuralları DB'den inject
        # bot_behavior_rules tablosu — prompt şişmesin, kalıcı kurallar burada
        try:
            from behavior_rules import build_rules_prompt_block
            _behavior_block = await build_rules_prompt_block(role)
            if _behavior_block:
                _role_aware_prompt += _behavior_block
        except Exception as _br_e:
            logger.debug(f"behavior_rules inject hata: {_br_e}")

        system = _role_aware_prompt + dynamic_context

        # ─── Oturum 25.29: Dangling tool_use cleanup ─────────────────────────
        # Onceki turda timeout/iptal yaptiysa history'de tool_use var ama
        # tool_result YOK. Yeni user mesaji eklendiginde Anthropic API
        # `tool_use ids were found without tool_result blocks` 400 dondurur.
        # FIX: Son assistant mesajini kontrol et, dangling tool_use varsa
        # ya placeholder tool_result enjekte et ya da bu assistant'i sok.
        _pruned = 0
        while self.history and self.history[-1].get("role") == "assistant":
            _last = self.history[-1]
            _content = _last.get("content")
            if isinstance(_content, list):
                _tool_use_ids = [
                    b.get("id") for b in _content
                    if isinstance(b, dict) and b.get("type") == "tool_use"
                ]
                if _tool_use_ids:
                    # Dangling tool_use'lar icin placeholder tool_result inject
                    _placeholder_blocks = [
                        {
                            "type": "tool_result",
                            "tool_use_id": tid,
                            "content": "[ABORTED — onceki turda zaman asimi/iptal]",
                            "is_error": True,
                        }
                        for tid in _tool_use_ids
                    ]
                    self.history.append({"role": "user", "content": _placeholder_blocks})
                    _pruned += len(_tool_use_ids)
                    break
            break  # Tek pass yeterli — assistant son ise zincirde derinlik yok
        if _pruned:
            logger.warning(
                f"[HISTORY-CLEAN] {_pruned} dangling tool_use icin placeholder "
                f"tool_result enjekte edildi (onceki turda timeout/iptal)"
            )

        self.history.append({"role": "user", "content": user_input})
        logger.info(f"Kullanici [{role}]: {user_input[:80]}")

        # 25.40j (Neo direktif) — UZUN KONUSMA RECAP
        # Ada gibi 30+ mesajlik diyaloglarda eski mesajlar token sisirir +
        # ileride truncation yapilirsa "kalp" kaybolur. Cerebras ile kisa
        # ozet uret + history'yi kisalt. Maliyet: ~$0.001 / 30 mesajda.
        # Sadece role=ogrenci icin (admin/teacher kisa diyaloglar).
        if role == "ogrenci" and len(self.history) >= 30:
            try:
                from conversation_memory import maybe_summarize_history
                _recap, _new_hist = await maybe_summarize_history(self.history)
                if _recap and len(_new_hist) < len(self.history):
                    self.history = _new_hist
                    logger.info(f"[RECAP] Ozet uretildi, history {len(self.history)} mesaja kisaltildi")
            except Exception as _re:
                logger.warning(f"[RECAP] Hata (akis bozulmasin): {_re}")

        # Kullanici mesajini DB'ye kaydet
        await _log_conversation(self.session_id, caller_phone, role, "user", user_input)

        # 22.1n-neo FAZ 2.3: Kisisellestirme sinyal izleme (fire-and-forget)
        if role == "ogrenci":
            try:
                _soz_k = None
                if hasattr(self, '_current_soz_no'):
                    _soz_k = self._current_soz_no
                if _soz_k:
                    import asyncio as _aio_k
                    from kisisellestirme import process_message as _km_proc
                    _aio_k.create_task(_km_proc(int(_soz_k), user_input))
            except Exception:
                pass

        # ── 25.18 FAZ 4: Lane + intent erken hesaplama (zenginleştirilmiş) ─
        # Lane: local LLM path için (groq_lanes.classify_lane — modül adı eski,
        # gerçekte 25.22+ Cerebras-first çalışıyor; classify hala doğru)
        # 25.40z3-MIMARI #5: _intent ARTIK V3 build oncesi hesaplaniyor (line 4400+).
        # Burada sadece lane hesaplanir; _intent yukarida zaten set edildi.
        _lane = None
        try:
            from groq_lanes import classify_lane
            _lane = classify_lane(user_input, role=role, phone=caller_phone)
        except Exception:
            _lane = None
        # _intent zaten yukarida (V3 build oncesi) classify_intent ile hesaplandi

        # ── HİBRİT LLM ROUTING (Oturum 22.1e — tek kaynak: routing_engine) ──
        # Onceki: 3 yerde routing (fast_responses, llm_router, fermat_core) → karmaşik
        # Simdi: routing_engine.decide_route() → tek karar noktasi
        # Admin/SGM/kavramsal/kisisel/kisa kararlari hepsi iceride
        from routing_engine import decide_route
        _route = decide_route(user_input, role, caller_phone, soz_no)
        # decide_route dondurur: "fast" | "claude" | "local" | "auto"
        # "local" → chat_local_async (Cerebras-first, Groq fallback, Ollama son).
        # Eski "ollama" string'i halen kabul (backwards compat). "auto" → cloud.
        if _route == "claude":
            complexity = "cloud"
        elif _route in ("local", "ollama"):
            # "local" yeni isim (25.10+), "ollama" eski compat.
            # Ikisinde de chat_local_async() cagrilir →
            # Cerebras (3 model) -> Groq fallback -> Ollama son fallback.
            complexity = "local"
        else:
            # "auto" veya "fast" → guvenli tarafa duy (Claude) — fast_responses zaten daha erken
            # yakaliyor, buraya geldiysek tool/analiz gerekiyor
            complexity = "cloud"

        # Fix 21 Nisan 15:40 — Psikoloji override: duygu/kriz tespitinde Claude zorunlu
        # _detected_durum enrichment bloğunda tespit edildiyse (confidence >= 0.5)
        # Ollama'ya ASLA gitmesin. Bugün Zehra vakasında ters duygu yanıt oluşmuştu.
        if complexity == "local":
            try:
                _ddurum = locals().get("_detected_durum")
                if _ddurum:
                    logger.info(f"  [ESKALASYON] Psikolojik durum tespit edildi ({_ddurum}) — Claude'a zorunlu yonlendirme")
                    complexity = "cloud"
                else:
                    # Ek safety net: user_input'ta duygu keyword'u varsa
                    from routing_engine import detect_duygu_psikoloji
                    if detect_duygu_psikoloji(user_input):
                        logger.info("  [ESKALASYON] Duygu keyword tespit edildi — Claude'a zorunlu")
                        complexity = "cloud"
            except Exception:
                pass

        if complexity == "local" and self.router.is_local_available:
            # Oturum 25.22+: Router Cerebras-first, Groq fallback, Ollama son fallback
            _hangi = (
                "Cerebras" if getattr(self.router, "_cerebras_available", False)
                else "Groq" if self.router._groq_available
                else "Ollama"
            )

            # Oturum 25.10 — Lane-specific system addon (Groq tutarliligi icin)
            # 25.17 Faz 3: _lane zaten yukarıda hesaplandı, tekrar etme
            _lane_system = system
            try:
                from groq_lanes import get_lane_system_addon
                if _lane:
                    _addon = get_lane_system_addon(_lane)
                    if _addon:
                        _lane_system = _lane_system + "\n\n[LANE TALIMATI]\n" + _addon
                        logger.info(f"  [YEREL] Lane: {_lane} ({_hangi} aciliyor)")
            except Exception:
                pass

            logger.info(f"  [YEREL] {_hangi} ile yanitlaniyor (dusuk maliyet)")
            try:
                # Oturum 25.10e (uvloop fix): async chat_local kullan
                # Eskiden sync chat_local + nest_asyncio.apply() vardi, FastAPI/uvicorn
                # uvloop'una "Can't patch loop" hatasi veriyordu → Groq tum cagrilar fail.
                if hasattr(self.router, "chat_local_async"):
                    # 25.22: intent geç (Cerebras model seçimi için)
                    # 25.29: channel geç (web → uzun akademik + RAG + qwen-3-235b)
                    answer = await self.router.chat_local_async(
                        messages=self.history,
                        system=_lane_system,
                        intent=_intent or "",
                        channel=getattr(self, "_channel", "whatsapp"),
                    )
                else:
                    # Backwards compat (eski router'da chat_local_async yok)
                    answer = self.router.chat_local(
                        messages=self.history,
                        system=_lane_system,
                    )

                # 25.40z — CLAUDE_HANDOFF intercept (Cerebras supervisor sinyali)
                # Cerebras cevabin sonuna [CLAUDE_HANDOFF: tool=X reason=Y] ekledi mi?
                # Eklediyse Claude'a yonlendir, tool zinciri ile zenginlestir.
                _handoff = getattr(self.router, "_last_claude_handoff", None)
                if _handoff and _handoff.get("tool"):
                    try:
                        from loguru import logger as _lg
                        _lg.info(f"  [HANDOFF→CLAUDE] tool={_handoff['tool']} reason={_handoff['reason'][:60]}")
                        # Cerebras cevabini context olarak ekle, Claude'a tetikle
                        # Claude bu konuda Cerebras'in soyledigine ek deger versin
                        handoff_user_msg = (
                            f"[CEREBRAS SUPERVISOR HANDOFF — Bu mesajı kullanıcı GÖRMÜYOR]\n\n"
                            f"Cerebras öğrenciye şu cevabı verdi (yukarıdaki):\n"
                            f"---\n{_handoff['cerebras_response'][:1500]}\n---\n\n"
                            f"Cerebras şunu önerdi: {_handoff['tool']} kullan ({_handoff['reason']}).\n\n"
                            f"GÖREVİN: Bu önerilen tool'u çağır, sonucu Cerebras cevabına ek katkı olarak "
                            f"sun. KISA olsun (3-5 cümle + tool sonucu). Tekrar etme — sadece EK DEGER. "
                            f"'Cerebras dedi ki' YAZMA — direkt zenginleştir."
                        )
                        # Sonsuz dongu engeli: handoff'u sifirla
                        self.router._last_claude_handoff = None
                        # History'e supervisor mesaji ekle (gecici)
                        self.history.append({"role": "user", "content": handoff_user_msg})
                        try:
                            claude_supplement = await self.router.chat_cloud_async(
                                messages=self.history,
                                system=_lane_system,
                            )
                            if claude_supplement:
                                supp_text = ""
                                for b in claude_supplement.content:
                                    if hasattr(b, "text"):
                                        supp_text += b.text
                                if supp_text and len(supp_text.strip()) > 30:
                                    answer = answer + "\n\n" + supp_text.strip()
                                    _lg.info(f"  [HANDOFF→CLAUDE] +{len(supp_text)} char eklendi")
                        finally:
                            # Handoff user mesajini history'den cikar (kullaniciya yansimasin)
                            if self.history and self.history[-1].get("content", "").startswith("[CEREBRAS SUPERVISOR"):
                                self.history.pop()
                    except Exception as _he:
                        from loguru import logger as _lg
                        _lg.warning(f"  [HANDOFF→CLAUDE] fail (silent): {_he}")

                # ── Kalite kontrolu — Ollama yaniti yetersizse Claude'a eskale et ──
                # Oturum 25.14k+rev (Neo elestirisi): lane-bazli esik daha mantikli
                # Sayisal esik kalite olcemez ama spam/yetersiz cevaplari yakalar.
                # - sohbet/selamlama: 8 char (sadece spam guard, "Selam!" yeterli)
                # - motivasyon/empati: 30 char (kisa destek mesaji ok ama bos olmasin)
                # - kavramsal/aciklama: 100 char (gercek bilgi icin minimum)
                # - analiz/data: zaten "claude" route'a gider, buraya gelmez
                _needs_escalation = False
                _lane_for_thresh = locals().get("_lane") or ""
                if _lane_for_thresh in ("sohbet", "selamlama", "veda", "tesekkur", "onay"):
                    _min_len = 8
                elif _lane_for_thresh in ("motivasyon", "empati", "duygu_destek"):
                    _min_len = 30
                else:
                    # kavramsal_kisa, kavramsal, aciklama, default
                    _min_len = 100  # "limit bir matematik kavramdır" gibi 30 char yetmez
                if len(answer.strip()) < _min_len:
                    _needs_escalation = True
                    logger.info(f"  [ESKALASYON] Yerel yanit {len(answer.strip())} char (esik {_min_len}, lane={_lane_for_thresh}), Claude'a geciliyor")
                # İngilizce yanıt tespiti
                elif any(eng in answer.lower() for eng in [
                    "let's", "here are", "dive deeper", "performance",
                    "academically", "insights", "optimize", "i can help",
                    "let me", "here is", "would you like", "based on",
                    "i think", "might be", "there is", "there are",
                    "you can", "please", "however", "therefore",
                    "welcome", "certainly", "absolutely",
                    "mechanics", "vectors", "scalars", "kinematics",
                    "position", "velocity", "acceleration",
                    "good evening", "good morning", "good night",
                    "of course", "sure thing", "no problem",
                    "sorry", "regarding", "additionally"
                ]):
                    _needs_escalation = True
                    logger.info("  [ESKALASYON] Ollama Ingilizce yanit verdi, Claude'a geciliyor")
                # Çince/diğer dil karışma tespiti
                elif any(ord(c) > 0x4E00 and ord(c) < 0x9FFF for c in answer[:200]):
                    _needs_escalation = True
                    logger.info("  [ESKALASYON] Ollama Cince/yabanci dil karisti, Claude'a geciliyor")
                # Halusinasyon tespiti — uydurma veri isaretleri
                # Oturum 25.29 fix: KAVRAMSAL yanitta dogal gecen kelimeler
                # ("belirlendi", "tespit edildi", "gorulmustur", "1. sinif")
                # listeden cikarildi — false positive ile Cerebras → Claude
                # eskalasyonu yaratiyordu. Su an sadece KESIN data sızıntısı /
                # kabul vermeme ifadeleri tetikleyici.
                #
                # Ek kontrol: kullanici sorusu data-spesifik degilse (kavramsal
                # ise) eskalasyon DEVRE DISI — Cerebras kavramsal yaniti gecerli
                # kabul edilir.
                _is_data_query = bool(__import__('re').search(
                    r'\b(sinav|sınav|deneme|net\b|etut|etüt|devamsiz|devamsız|'
                    r'puan|borc|ödeme|odeme|sinif|sınıf|ogrenci|öğrenci|'
                    r'rapor|liste|durum)',
                    user_input.lower()
                ))
                _hallucination_terms = [
                    # Sadece KESIN data sızıntısı yapan ifadeler
                    "verilere göre", "kayıtlara göre", "sistemde görünüyor",
                    "denemelerde zorland", "konularında zorland",
                    # Sadece sosyal kabul vermeme — net negatif
                    "bilgi sahibi değilim", "bilgi sahibi degilim",
                    "yanıtlayamıyorum", "tam olarak bilmiyorum",
                    "kesin bilgi veremem", "spesifik bilgiye sahip",
                    "sahip olmadığım", "maalesef mevcut",
                    "gerçek zamanlı", "canlı veri",
                ]
                if _is_data_query and any(h in answer.lower() for h in _hallucination_terms):
                    _needs_escalation = True
                    logger.info("  [ESKALASYON] Cerebras data sorusunda belirsiz/sizinti, Claude'a geciliyor")
                # Kavramsal sorularda Cerebras'a guven — eskalasyon yok
                # Ollama'nın kişisel veri sorusuna uydurma sayı ile cevap verme riski
                else:
                    import re as _re
                    if _re.search(r"(devams[iı]zl[iı]|program|sinav|sınav|deneme|net\b|etut|etüt|sinif|sınıf|ogrenci|öğrenci)", user_input.lower()):
                        # Mesaj veri soruyorsa ama fast_response yakalamamış — Claude daha güvenli
                        if _re.search(r'\b\d{1,3}[.,]\d\b', answer):
                            # Ollama net/puan gibi spesifik sayı uydurmuş olabilir
                            _needs_escalation = True
                            logger.info("  [ESKALASYON] Ollama veri sorusuna sayisal cevap — guvensiz, Claude'a geciliyor")
                        elif _re.search(r'(toplam|saat|net|puan|sinif|sınıf).*\d', answer):
                            _needs_escalation = True
                            logger.info("  [ESKALASYON] Ollama veri/istatistik iceren yanit — Claude'a geciliyor")
                    # Uygunsuz icerik filtresi — Ollama bazen kotu kelime uretebilir
                    if not _needs_escalation and any(bad in answer.lower() for bad in [
                        "sikişi", "sikiş", "sikis", "seks", "cinsel",
                        "ölüm", "intihar", "öldür",
                        "küfür", "argo",
                    ]):
                        _needs_escalation = True
                        logger.warning("  [ESKALASYON] Ollama uygunsuz icerik, Claude'a geciliyor")
                    if not _needs_escalation and any(bad in answer.lower() for bad in [
                        "yapay zeka asistanıyım", "yardımcı olmayı", "hizmet vermeye",
                        "size yardımcı", "sana yardımcı olmak", "olarak çalışıyorum",
                        "olarak çalısıyorum", "lütfen bekleyin"
                    ]):
                        # Jenerik "ben bir asistanım" yanıtı — bağlam anlaşılmamış
                        if len(user_input) > 20:  # kısa selamlama değilse
                            _needs_escalation = True
                            logger.info("  [ESKALASYON] Ollama jenerik yanit verdi, Claude'a geciliyor")

                    # 25.40s — Yagiz vakasi: Cerebras "sistemden alıp donecegim" dedi ama
                    # tool cagiramaz (Cerebras tool-calling yok). Sahte soz — kullanici bekledi
                    # ama bot hicbir sey yapmadi. Pattern yakalanirsa Claude'a transfer.
                    if not _needs_escalation and any(bad in answer.lower() for bad in [
                        "sistemden alıp", "sistemden alip", "sistemden cekip", "sistemden çekip",
                        "bir an için bekle", "bir an icin bekle",
                        "sonuç çıktığında", "sonuc ciktiginda",
                        "sonra paylaşacağım", "sonra paylasacagim",
                        "hemen paylaşacağım", "hemen paylasacagim",
                        "birazdan dönerim", "birazdan donerim", "biraz sonra dönerim",
                        "akademik takip sistemimizden kontrol",
                    ]):
                        _needs_escalation = True
                        logger.info("  [ESKALASYON] Cerebras sahte soz verdi (sistemden alacagim), Claude'a geciliyor")

                if _needs_escalation:
                    # Claude akışına düş (aşağıdaki for loop)
                    logger.info("  [ESKALASYON] Claude API'ye yönlendiriliyor...")
                    # history'de user mesajı zaten var, Claude devam edecek
                    # Oturum 25.14k: Groq attempt'ini routing_stats'a yaz (gorunurluk)
                    # Eskiden Groq cagrildigi halde sadece Claude kayit oluyor → 7 gun "Groq=0" gorundu
                    try:
                        _attempted = getattr(self.router, "_last_local_provider", None)
                        if _attempted == "groq":
                            from usage_tracker import log_event
                            await log_event(phone=caller_phone, role=role, full_name=caller_name,
                                            event_type="message",
                                            response_source="groq_escalated_to_claude",
                                            response_ms=500)
                    except Exception as _eg_err:
                        logger.debug(f"Groq escalation log hata: {_eg_err}")
                else:
                    # ── OLLAMA POST-PROCESSING ──────────────────────────
                    # 1. İsim düzeltme (her kanal için)
                    if caller_name:
                        answer = _fix_ollama_name(answer, caller_name, role)
                    # 2. Web kanalı: markdown/tablo/latex KORUNSUN, sadece kontrol karakter
                    import re as _re_fmt
                    if getattr(self, "_channel", "whatsapp") == "web":
                        # Sadece kontrol karakteri + bozuk control chars temizle
                        answer = _re_fmt.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', answer)
                        # ** ve ### web'de markdown — BIRAK
                    else:
                        # WP kanalı: WP formatı zorla (Oturum 25.11: _clean_local_format)
                        answer = _clean_local_format(answer)
                        answer = _re_fmt.sub(r'###\s*', '', answer)  # ### kaldır
                        answer = _re_fmt.sub(r'##\s*', '', answer)   # ## kaldır
                        answer = _re_fmt.sub(r'\*\*([^*]+)\*\*', r'*\1*', answer)  # **text** → *text*
                        answer = _re_fmt.sub(r'```[^`]*```', '', answer, flags=_re_fmt.DOTALL)  # kod bloku kaldır
                        answer = _re_fmt.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', answer)  # kontrol karakterleri
                    # Sonundaki eksik cümleleri kırp (yarım kalan son cümle)
                    lines = answer.rstrip().split('\n')
                    if lines and len(lines[-1]) > 5 and not lines[-1].rstrip()[-1] in '.!?_🎯💡😊😄':
                        # Son satır yarım kalmış olabilir — kırp
                        if len(lines) > 3:
                            answer = '\n'.join(lines[:-1])

                    # Oturum 24 + 25: Gercek provider'i router'dan oku.
                    # Fallback: router'a bakip hangisi yuklu ise o.
                    # 25.22: Cerebras öncelik (paid tier primary)
                    _last = getattr(self.router, "_last_local_provider", None)
                    if _last:
                        _local_provider = _last
                        # Cerebras kullanıldıysa hangi model — granüler observability
                        if _local_provider == "cerebras":
                            _cb_model = getattr(self.router, "_last_cerebras_model", "")
                            if "8b" in _cb_model:
                                _local_provider = "cerebras_8b"
                            elif "120b" in _cb_model or "gpt-oss" in _cb_model:
                                _local_provider = "cerebras_120b"
                            elif "235b" in _cb_model or "qwen" in _cb_model:
                                _local_provider = "cerebras_235b"
                    elif getattr(self.router, "_cerebras_available", False):
                        _local_provider = "cerebras"
                    elif getattr(self.router, "_groq_available", False):
                        _local_provider = "groq"
                    elif getattr(self.router, "_ollama_available", False):
                        _local_provider = "ollama"
                    else:
                        _local_provider = "local"  # bilinmeyen ama yerel-benzeri
                    # 25.40z3-ROUTING-FIX2: Decision trace 'unknown' bug fix
                    # Local path da route bilgisini set etmeli (önceden sadece Claude yapıyordu)
                    # Bu sayede routing_stats analizinde NULL/unknown kalmaz.
                    if self.last_decision_trace.get("route") == "unknown":
                        self.last_decision_trace["route"] = f"local_{_local_provider}"
                    # 25.40j: Tonal redundant greeting filter (Yagiz/Ada vakası)
                    try:
                        from conversation_memory import strip_redundant_greeting
                        answer = strip_redundant_greeting(answer, self.history)
                    except Exception: pass
                    self.history.append({"role": "assistant", "content": answer})
                    await _log_conversation(
                        self.session_id, caller_phone, role,
                        "assistant", answer, [f"{_local_provider}_local"],
                    )
                    try:
                        from usage_tracker import log_event
                        # 25.23: Cerebras token tracking — router'dan al
                        _ti = getattr(self.router, "_last_tokens_in", 0)
                        _to = getattr(self.router, "_last_tokens_out", 0)
                        _rms = getattr(self.router, "_last_response_ms", 2000) or 2000
                        # 25.40z3-FIX: HANDOFF tracking - cerebras+claude_handoff varsa
                        # response_source'a yaz (observability: Cerebras handoff frekansi olculur)
                        _resp_src = _local_provider
                        try:
                            _hf = locals().get('_handoff')
                            if _hf and _hf.get('tool'):
                                _resp_src = f"{_local_provider}+claude_handoff"
                        except Exception:
                            pass
                        await log_event(phone=caller_phone, role=role, full_name=caller_name,
                                        event_type="message", response_source=_resp_src,
                                        response_ms=_rms,
                                        token_input=_ti, token_output=_to)
                    except Exception:
                        pass
                    # 25.22 (Bot bulgu): Duplicate routing_stats kaydi KALDIRILDI
                    # Daha once 25.14k Groq invisibility fix'inde subprocess test
                    # icin eklenmistik, ancak bridge ana akis (whatsapp_bridge.py:3346)
                    # zaten production'da routing_stats yaziyor → duplicate.
                    # tools_used'a [f"{_local_provider}_local"] zaten yazıldı (yukarıda),
                    # bridge oradan source detect edip routing_stats'a yazıyor.
                    # NOT: subprocess test'lerde bu olmazdı ama gerçek production'da var.
                    # Self-Observation: kalite degerlendirmesi
                    try:
                        from self_observer import log_quality
                        await log_quality(self.session_id, caller_phone, role,
                                          user_input, answer, _local_provider)
                    except Exception:
                        pass
                    # ── QUERY CACHE YAZ — Yerel (Groq/Ollama) cevap, cache'e ekle ──
                    # Oturum 25.11: hardcoded "ollama" yerine gercek provider
                    if caller_phone and len(answer) >= 20:
                        try:
                            from query_cache import add_to_cache
                            await add_to_cache(
                                phone=caller_phone, role=role,
                                query=user_input, response=answer,
                                source=_local_provider,
                            )
                        except Exception as _qcw_e:
                            logger.debug(f"Query cache yaz ({_local_provider}) hatasi: {_qcw_e}")
                    return answer
            except Exception as e:
                logger.warning(f"  Ollama basarisiz, Claude'a geciliyor: {e}")
                # Fallback — asagidaki Claude akisina devam et

        # ── Oturum 25 PROJ-C: Groq tool-calling pre-check (opt-in) ───────────
        # ENABLE_GROQ_TOOLS aktif + ogrenci rolü + SAFE_GROQ_TOOLS icindeki araclar
        # kullanilabiliyorsa Groq 70B'yi dene. Herhangi bir hata/invalid output'ta
        # Claude akisina sessizce dus (asagidaki MAX_TURNS loop'u).
        try:
            from llm_router import ENABLE_GROQ_TOOLS, SAFE_GROQ_TOOLS
            if (ENABLE_GROQ_TOOLS and role == "ogrenci"
                    and getattr(self.router, "_groq_available", False)):
                _safe_tools_subset = [t for t in TOOLS
                                      if t.get("name") in SAFE_GROQ_TOOLS]
                if _safe_tools_subset:
                    async def _groq_exec(name, args):
                        return await run_tool(
                            name, args,
                            caller_phone=self._caller_phone,
                            caller_role=role,
                            caller_channel=getattr(self, "_channel", "whatsapp"),
                        )
                    _gt0 = time.time()
                    _groq_r = await self.router.chat_groq_with_tools(
                        messages=self.history,
                        system=_role_aware_prompt,
                        tools=_safe_tools_subset,
                        tool_executor=_groq_exec,
                    )
                    _gt_ms = int((time.time() - _gt0) * 1000)
                    if _groq_r and _groq_r.get("text") and len(_groq_r["text"].strip()) >= 20:
                        answer = _groq_r["text"].strip()
                        logger.info(f"  [GROQ-TOOLS] Basarili {_gt_ms}ms, {len(answer)} char")
                        # 25.40j: Tonal filter
                        try:
                            from conversation_memory import strip_redundant_greeting
                            answer = strip_redundant_greeting(answer, self.history)
                        except Exception: pass
                        self.history.append({"role": "assistant", "content": answer})
                        try:
                            await _log_conversation(
                                self.session_id, caller_phone, role,
                                "assistant", answer, ["groq_tools"],
                            )
                        except Exception:
                            pass
                        try:
                            from usage_tracker import log_event
                            await log_event(
                                phone=caller_phone, role=role, full_name=caller_name,
                                event_type="message", response_source="groq", response_ms=_gt_ms,
                            )
                        except Exception:
                            pass
                        return answer
                    # _groq_r None ya da cok kisa -> Claude'a dus (sessiz)
        except Exception as _gt_err:
            logger.warning(f"  [GROQ-TOOLS] pre-check hatasi, Claude'a dusuyor: {_gt_err}")

        # ── 25.15 MODULAR PROMPT TIER SELECTION ──────────────────────────
        # Env flag MODULAR_PROMPT_MODE ile kontrol — disabled (default) ise
        # mevcut davranis (full prompt + full tools).
        # canary/normal/full mode'larda intent + lane + role'e gore tier secilir.
        # GUVENLIK: hata varsa FULL (geri uyumlu, sizinti riski yok).
        _claude_prompt = _role_aware_prompt
        _claude_tools = get_tools(role=role)
        _selected_tier = "full"
        try:
            from prompt_tiers import (
                select_tier, get_prompt_for_tier, get_tools_for_tier,
                is_modular_active, log_tier_decision,
            )
            if is_modular_active():
                _lane_for_tier = locals().get("_lane") or ""
                _intent_for_tier = locals().get("_intent") or ""
                # Heuristik: kişisel veri sorgusu mu?
                _has_pers = bool(locals().get("soz_no")) and any(
                    kw in (user_input or "").lower()
                    for kw in ["benim", "netim", "denemem", "puanim", "puanım",
                               "hocam", "sınıfım", "sinifim", "devamsizligim", "devamsızlığım"]
                )
                _selected_tier = select_tier(
                    user_input=user_input or "",
                    role=role or "ogrenci",
                    lane=_lane_for_tier,
                    intent=_intent_for_tier,
                    has_personal_data_query=_has_pers,
                )
                # 25.40z3-MIMARI: V3 aktif iken tier ezme YOK - V3 prompt korunur
                _claude_prompt = get_prompt_for_tier(
                    _selected_tier, _role_aware_prompt, v3_active=_v3_enabled,
                )
                # 25.18 Faz 4: intent ile gerçek intent-based tool subset routing
                _claude_tools = get_tools_for_tier(_selected_tier, get_tools(role=role), intent=_intent_for_tier)
                log_tier_decision(_selected_tier, user_input or "", role or "ogrenci",
                                  _lane_for_tier, _intent_for_tier,
                                  reason=f"pers={_has_pers}")
        except Exception as _tier_err:
            # Hata → FULL (güvenli)
            logger.warning(f"  [TIER] Hata, FULL kullaniliyor: {_tier_err}")
            _claude_prompt = _role_aware_prompt
            _claude_tools = get_tools(role=role)
            _selected_tier = "full"

        # 25.40b (Neo direktif): Admin icin MAX_TURNS pratikte SINIRSIZ.
        # Onceki 50 hala bir sinirdi, Neo "max tur olmamasi lazim admin etkilesimi
        # zaten en yuksek kapasite gerektirir" dedi.
        # 999 = effectively unlimited ama infinite loop guard olarak duruyor.
        # Diger roller icin 10 (token koruma).
        MAX_TURNS = 999 if role == "admin" else 10
        for turn in range(MAX_TURNS):
            # KRITIK: Anthropic SDK sync — event loop'u bloke etmemesi icin
            # asyncio.to_thread ile arka plan thread'inde calistir.
            # Boylece async tasks (filler watchdog, scheduler vb) calismaya devam eder.
            # Prompt caching: SYSTEM_PROMPT statik bloku cache'e, dynamic ayri blok
            #
            # STREAMING YOLU — eğer _stream_queue varsa AsyncAnthropic ile
            # native streaming: Claude her token ürettiğinde hemen queue'ya yaz.
            # Tool kullanımında text stream + tool_use fragman gelir, final_message'dan topla.
            # 25.40z3-MIMARI #6: Stream + sync ortak params helper'dan
            # (DRY consolidation - tek kaynak, gelecek değişiklikler buraya)
            _request_params = _build_claude_request_params(
                v3_blocks=self._v3_system_blocks,
                claude_prompt=_claude_prompt,
                dynamic_context=dynamic_context,
                claude_tools=_claude_tools,
                model=MODEL,
                messages=self.history,
            )
            if self._stream_queue is not None and self.async_client:
                # STREAMING YOLU — AsyncAnthropic native streaming
                try:
                    async with self.async_client.messages.stream(**_request_params) as stream:
                        async for text_chunk in stream.text_stream:
                            await self._stream_queue.put(("chunk", text_chunk))
                        response = await stream.get_final_message()
                except Exception as _stream_err:
                    # Stream başarısızsa sync fallback
                    logger.warning(f"Native stream hatası, sync'e düştü: {_stream_err}")
                    response = await asyncio.to_thread(
                        self.client.messages.create, **_request_params
                    )
            else:
                # SYNC YOLU — asyncio.to_thread ile bloke etmez
                response = await asyncio.to_thread(
                    self.client.messages.create, **_request_params
                )

            # Araç çağrıları varsa çalıştır
            tool_calls = [b for b in response.content if b.type == "tool_use"]
            text_blocks= [b for b in response.content if b.type == "text"]

            if not tool_calls:
                # Final yanıt — temiz text olarak kaydet
                # Decision trace: Claude path final answer (no more tools)
                if self.last_decision_trace.get("route") == "unknown":
                    self.last_decision_trace["route"] = "claude_text_only"
                answer = "\n".join(b.text for b in text_blocks if hasattr(b, "text"))
                # ToolUseBlock/TextBlock string sızmasını temizle
                # Web kanalında WP format cleaner'ı SAKIN — markdown/tablo/latex'i bozar
                if getattr(self, "_channel", "whatsapp") == "web":
                    # Sadece teknik artifact temizliği (TextBlock/ToolUseBlock sızıntısı)
                    import re as _re_web
                    answer = _re_web.sub(r'\[TextBlock\(.*?\)\]', '', answer, flags=_re_web.DOTALL)
                    answer = _re_web.sub(r'\[ToolUseBlock\(.*?\)\]', '', answer, flags=_re_web.DOTALL)
                    answer = answer.strip()
                else:
                    answer = _clean_response(answer)
                # 25.40j: Tonal redundant greeting filter
                try:
                    from conversation_memory import strip_redundant_greeting
                    answer = strip_redundant_greeting(answer, self.history)
                except Exception: pass

                # 25.40z3-FIX: Wiki enrichment Claude path (Cerebras esitligi)
                # Cerebras'ta llm_router.py:1263 zaten yapiliyor, Claude'da eksikti.
                # Claude %72.6 trafik aldigi halde wiki enrichment'tan yararlanmiyordu.
                # Web kanali + 200+ char + akademik konu -> Wikipedia bloku eklenir.
                if getattr(self, "_channel", "whatsapp") == "web" and len(answer) > 200:
                    try:
                        from enrichment_dispatcher import inject_wiki_block
                        wiki_block = await inject_wiki_block(user_input, answer)
                        if wiki_block:
                            answer = answer + wiki_block
                            logger.info(f"  [WIKI_INJECT] Claude path +{len(wiki_block)} char")
                    except Exception as _we:
                        logger.debug(f"  [WIKI_INJECT] Claude skip: {_we}")

                # 25.40z3-FIX: Enrichment footer Claude path (Cerebras esitligi)
                # Cerebras system prompt'unda zaten otomatik ekliyor (llm_router.py:861).
                # Claude'da Yoktu - %72.6 trafik enrichment footer'sizdi.
                # Footer ogrenciye "deney/3d/video" yazma cesareti veriyor →
                # dispatch_enrichment tetiklenir → ucuz API'lerden zenginlestirme.
                _ch = getattr(self, "_channel", "whatsapp")
                if (_ch == "web" and role == "ogrenci" and len(answer) > 300):
                    # Footer zaten ekli mi? (Cerebras handoff durumunda olabilir)
                    if not any(m in answer for m in [
                        "Daha derine gitmek", "💡 *Daha derine",
                        "deneyimle", "anlatim videosu",
                    ]):
                        # Akademik kavramsal soru tespiti
                        _is_academic = any(kw in (user_input or "").lower() for kw in [
                            "nedir", "acikla", "açıkla", "anlat", "nasil", "nasıl",
                            "neden", "formul", "formül", "kural", "yasa",
                            "teorem", "kavram", "tanim", "tanım", "ornek", "örnek",
                        ])
                        if _is_academic:
                            footer = (
                                "\n\n─────────────────────────────────────\n"
                                "💡 *Daha derine gitmek ister misin?*\n\n"
                                "🎬 _video_ yaz — konu anlatim videosu\n"
                                "🧪 _deney_ yaz — sanal simulasyon\n"
                                "📐 _3d_ yaz — 3 boyutlu gorsel\n"
                                "─────────────────────────────────────"
                            )
                            answer = answer + footer
                            logger.info(f"  [ENRICH_FOOTER] Claude path +{len(footer)} char")

                # History'ye response.content (TextBlock list) yerine duz string ekle
                # Boylece Ollama'ya geciste format sorunu olmaz
                self.history.append({"role": "assistant", "content": answer})
                logger.success(f"✅ Yanıt ({turn+1} tur)")
                await _log_conversation(
                    self.session_id, caller_phone, role,
                    "assistant", answer, [],
                )
                # Self-Observation: kalite degerlendirmesi
                try:
                    from self_observer import log_quality
                    await log_quality(self.session_id, caller_phone, role,
                                      user_input, answer, "claude")
                except Exception:
                    pass
                # Usage log — Claude API (Oturum 25.39: cache metric tracking)
                try:
                    from usage_tracker import log_event
                    u = getattr(response, 'usage', None)
                    token_in = u.input_tokens if u else 0
                    token_out = u.output_tokens if u else 0
                    # Anthropic Prompt Cache metrikleri (Oturum 25.39)
                    cache_read = getattr(u, 'cache_read_input_tokens', 0) or 0
                    cache_write = getattr(u, 'cache_creation_input_tokens', 0) or 0
                    if cache_read or cache_write:
                        logger.info(
                            f"💾 Cache: READ={cache_read:,} WRITE={cache_write:,} "
                            f"INPUT={token_in:,} (hit={cache_read*100/max(1,cache_read+token_in):.1f}%)"
                        )
                    await log_event(phone=caller_phone, role=role, full_name=caller_name,
                                    event_type="message", response_source="claude",
                                    response_ms=int((turn+1)*3000),
                                    token_input=token_in, token_output=token_out,
                                    cache_read_tokens=cache_read,
                                    cache_write_tokens=cache_write)
                except Exception as _ue:
                    logger.debug(f"usage_log error: {_ue}")
                # ── QUERY CACHE YAZ — no-tool Claude yaniti, cache'e ekle ──
                # turn==0 → ilk turda tool kullanmadı → saf conceptual cevap
                if turn == 0 and caller_phone and len(answer) >= 20:
                    try:
                        from query_cache import add_to_cache
                        await add_to_cache(
                            phone=caller_phone, role=role,
                            query=user_input, response=answer,
                            source="claude",
                        )
                    except Exception as _qcw_e:
                        logger.debug(f"Query cache yaz hatasi: {_qcw_e}")
                return answer

            # Araçları çalıştır — PARALEL (asyncio.gather)
            # Aynı turdaki tool_call'lar bağımsız → eş zamanlı çalıştır → 2-4x hızlanma
            self.history.append({"role": "assistant", "content": response.content})

            # Decision trace: Claude tool-calling path
            if self.last_decision_trace.get("route") == "unknown":
                self.last_decision_trace["route"] = "claude_tool_loop"

            async def _run_one_tool(tc):
                """Tek bir tool_call'u ACL + run_tool ile calistir."""
                # Decision trace: kayit tool name (duplicates ok — Claude loop birden cok turn)
                try:
                    self.last_tools_called.append(tc.name)
                except Exception:
                    pass
                logger.info(f"🔧 Araç: {tc.name}({list(tc.input.keys())})")
                # ── ACL kapısı ────────────────────────────────────────────────
                action_param = tc.input.get("action", "") if tc.name == "execute_eyotek_action" else ""
                if not _is_tool_allowed(role, tc.name, action_param, phone=caller_phone):
                    denied_msg = json.dumps(
                        {"error": f"YETKİ HATASI: '{role}' rolü '{tc.name}' aracını "
                                  f"{'(' + action_param + ') ' if action_param else ''}kullanamaz."},
                        ensure_ascii=False,
                    )
                    logger.warning(f"🚫 ACL engel: {role} → {tc.name}({action_param})")
                    return {
                        "type":        "tool_result",
                        "tool_use_id": tc.id,
                        "content":     denied_msg,
                    }
                # ─────────────────────────────────────────────────────────────
                # soz_no + phone'u run_tool'a geçir (ACL kontrolü için)
                run_tool._current_soz_no = int(soz_no) if soz_no else None
                run_tool._current_phone = caller_phone  # SGM (Orsel) guard icin
                try:
                    output = await run_tool(
                        tc.name, tc.input,
                        caller_phone=self._caller_phone,
                        caller_role=role,
                        caller_channel=getattr(self, "_channel", "whatsapp"),  # 22.1n-rev Atlas #16
                    )
                except Exception as e:
                    logger.error(f"   ⚠️ Tool {tc.name} hatasi: {e}")
                    output = json.dumps({"error": str(e)[:200]}, ensure_ascii=False)
                logger.debug(f"   → {(output or '')[:200]}")
                return {
                    "type":        "tool_result",
                    "tool_use_id": tc.id,
                    "content":     output,
                }

            # Streaming: tool çalışmadan önce kullanıcıya bilgi ver
            # Oturum 25.31 — Tool ismi ozel handling icin gercek isim gonderilir
            if self._stream_queue is not None:
                try:
                    # Tek tool varsa ismi direk yolla (frontend make_render_link'i tanir)
                    if len(tool_calls) == 1:
                        await self._stream_queue.put(("tool_start", tool_calls[0].name))
                    else:
                        _tool_names = ", ".join(tc.name for tc in tool_calls[:3])
                        await self._stream_queue.put(("tool_start", _tool_names))
                except Exception:
                    pass

            # Paralel calistir (1 tool varsa overhead yok, gather hizli geri doner)
            if len(tool_calls) == 1:
                tool_results = [await _run_one_tool(tool_calls[0])]
            else:
                logger.info(f"🚀 {len(tool_calls)} tool PARALEL calistiriliyor")
                tool_results = await asyncio.gather(*[_run_one_tool(tc) for tc in tool_calls])

            # Streaming: tool bitti
            # Oturum 25.31 — make_render_link sonucu (URL) frontend'e iletilir
            if self._stream_queue is not None:
                try:
                    if len(tool_calls) == 1 and tool_calls[0].name == "make_render_link":
                        # Tool sonucunun JSON content'inden URL cikar
                        try:
                            _content = tool_results[0].get("content", "")
                            _parsed = json.loads(_content) if isinstance(_content, str) else _content
                            await self._stream_queue.put(("tool_done", ("make_render_link", _parsed)))
                        except Exception:
                            await self._stream_queue.put(("tool_done", ("make_render_link", None)))
                    else:
                        await self._stream_queue.put(("tool_done", len(tool_calls)))
                except Exception:
                    pass

            self.history.append({"role": "user", "content": tool_results})

            # Kullanilan araclari logla — TOOL SONUÇ ÖZETİ dahil (bağlam korunması)
            used_tools = [tc.name for tc in tool_calls]
            # Tool sonuçlarından kısa özet çıkar
            _result_summaries = []
            for tr in tool_results:
                content = tr.get("content", "")
                if isinstance(content, str) and len(content) > 100:
                    content = content[:100] + "..."
                elif isinstance(content, dict):
                    # Dict'ten anahtar bilgileri çek
                    keys = list(content.keys())[:5]
                    content = str({k: str(content[k])[:50] for k in keys})
                _result_summaries.append(f"{tr.get('type','tool')}: {content}")
            _log_text = f"[tool_calls: {', '.join(used_tools)}]"
            if _result_summaries:
                _log_text += "\n[tool_results: " + " | ".join(_result_summaries)[:500] + "]"
            await _log_conversation(
                self.session_id, caller_phone, role,
                "assistant", _log_text, used_tools,
            )

        return "⚠️ Maksimum tur sayısına ulaşıldı. Lütfen isteğinizi daha spesifik belirtin."

    def reset(self) -> None:
        """Konuşma geçmişini temizle."""
        self.history = []


# ─── Ollama İsim Düzeltme ────────────────────────────────────────────────────

# Ollama'nın sıkça uydurduğu isimler — bunlar gerçek arayan değilse değiştirilir
_COMMON_FAKE_NAMES = [
    "Ali", "Ayşe", "Mehmet", "Fatma", "Ahmet", "Zeynep", "Mustafa", "Emine",
    "Hasan", "Hüseyin", "İbrahim", "Osman", "Ömer", "Murat", "Can", "Ece",
    "Deniz", "Emre", "Burak", "Selin", "Elif", "Derya", "Berk", "Ceren",
    "Kaan", "Mert", "Arda", "Yusuf", "Kerem", "Beren", "Defne", "Ela",
]

def _clean_local_format(answer: str) -> str:
    """Yerel LLM (Groq/Ollama) formatter — format_whatsapp.py'a delegation.
    Oturum 25.11: 'ollama' isim 'local'a yeniden adlandirildi (Groq production).
    Eski isim _clean_ollama_format alias olarak korundu (geri uyumluluk)."""
    try:
        from format_whatsapp import format_for_whatsapp
        # source="local" Groq+Ollama icin ayni enforcer'i tetikler
        return format_for_whatsapp(answer, source="local")
    except Exception:
        pass  # fallback: eski kod çalışır


# Backwards-compat alias — eski kod _clean_ollama_format çağırırsa hata vermesin
_clean_ollama_format = _clean_local_format

# NOT (Oturum 25.11): Eski 90 satirlik fallback fonksiyon body'si silindi.
# format_whatsapp.py merkezi formatter aynı isi yapıyor (Oturum 20 refactor).
# Eski kod git history'de mevcut (commit 6b662b8 oncesi).


def _fix_ollama_name(answer: str, caller_name: str, role: str) -> str:
    """
    Ollama yanıtında yanlış isim varsa doğrusuyla değiştir.

    Ollama bazen:
    - "canım" → "Can" olarak yorumlar
    - System prompt'taki örnek isimlerden birini seçer
    - Rastgele Türk ismi uydurur

    Bu fonksiyon yanıttaki ilk hitap satırında ismi düzeltir.
    """
    import re

    # BÜYÜK HARF ismi düzelt: "ALİ KÜÇÜKUYSAL" → "Ali Küçükuysal"
    if caller_name == caller_name.upper() and len(caller_name) > 2:
        _TR_LOWER_MAP = str.maketrans("ABCÇDEFGĞHIİJKLMNOÖPRSŞTUÜVYZ", "abcçdefgğhıijklmnoöprsştuüvyz")
        words = caller_name.split()
        caller_name = ' '.join(w[0] + w[1:].translate(_TR_LOWER_MAP) if len(w) > 1 else w for w in words)

    correct_first = caller_name.split()[0]  # "Ali Küçükuysal" → "Ali"
    correct_lower = correct_first.lower()

    # Zaten doğru isim kullanılmışsa bir şey yapma
    if correct_first in answer[:150] or correct_lower in answer[:150].lower():
        return answer

    # Admin/Müdür özel hitapları koru
    if role == "admin" and ("Zeki Bey" in answer or "Neo" in answer):
        return answer
    if role == "mudur":
        if "Müdürüm" in answer or "Müdürum" in answer or "Mudurum" in answer:
            return answer

    # Hitap satırındaki yanlış ismi bul ve düzelt
    # Tipik kalıplar: "Merhaba *Ali*!", "Merhaba Ali!", "Merhaba, Ali!"
    for fake_name in _COMMON_FAKE_NAMES:
        if fake_name.lower() == correct_lower:
            continue  # Aynı isim, değiştirmeye gerek yok

        # Bold hitap: *FakeIsim*
        answer = re.sub(
            rf'\*{re.escape(fake_name)}\*',
            f'*{correct_first}*',
            answer,
            count=2  # İlk 2 yerde değiştir
        )
        # Normal hitap: Merhaba FakeIsim! veya FakeIsim,
        answer = re.sub(
            rf'(?i)\b(Merhaba\s+){re.escape(fake_name)}(\s*[!,.])',
            rf'\g<1>{correct_first}\2',
            answer,
            count=1
        )
        # Cümle sonunda isim: "... düşünüyorsun FakeIsim?"
        answer = re.sub(
            rf'(?i)\b{re.escape(fake_name)}(\s*\?)',
            rf'{correct_first}\1',
            answer,
            count=2
        )
        # "Sen FakeIsim" kalıbı
        answer = re.sub(
            rf'(?i)\b(Sen\s+){re.escape(fake_name)}\b',
            rf'\g<1>{correct_first}',
            answer,
            count=1
        )

    # Son kontrol: hala doğru isim geçmiyor mu?
    if correct_first not in answer[:200] and correct_lower not in answer[:200].lower():
        # "Merhaba XYZ!" kalıbını bul ve ismi değiştir
        fixed = re.sub(
            r'^(Merhaba\s+)\*?[\w\s]+?\*?\s*([!,.]\s)',
            rf'Merhaba *{correct_first}*\2',
            answer,
            count=1
        )
        if fixed != answer:
            answer = fixed
        elif "Merhaba" in answer[:30]:
            # "Merhaba" var ama regex tutmadı — kelimeyi tamamen değiştir
            answer = re.sub(
                r'^Merhaba\s+\S+\s*[!,.]?\s*',
                f'Merhaba *{correct_first}*! ',
                answer,
                count=1
            )
        else:
            # Hiç "Merhaba" yoksa başa ekle
            lines = answer.split('\n', 1)
            if not re.search(r'(Merhaba|Selam|Hey|Hosgeldin)', lines[0], re.IGNORECASE):
                answer = f"*{correct_first}*, " + answer

    return answer


# ─── Yanıt Temizleme ────────────────────────────────────────────────────────

def _clean_response(text: str) -> str:
    """WP formatter — format_whatsapp.py'a delegation + post-processing.
    22.1g: Post-processing eklendi — ToolUseBlock sızması + meta_leak temizlik."""
    import re as _re_cr
    try:
        from format_whatsapp import format_for_whatsapp
        text = format_for_whatsapp(text, source="claude")
        # 22.1g — Post-processing: delegation sonrasi sizmis teknik bloklari temizle
        # (format_whatsapp bunlari gormedigi icin ek temizlik zorunlu)
        text = _re_cr.sub(r'\[ToolUseBlock\([^\]]*\)\]', '', text, flags=_re_cr.DOTALL)
        text = _re_cr.sub(r'\[TextBlock\([^\]]*\)\]', '', text, flags=_re_cr.DOTALL)
        text = _re_cr.sub(r'ToolUseBlock\([^)]*\)', '', text, flags=_re_cr.DOTALL)
        text = _re_cr.sub(r'TextBlock\([^)]*\)', '', text, flags=_re_cr.DOTALL)
        text = _re_cr.sub(r'DirectCaller\([^)]*\)', '', text)
        text = _re_cr.sub(r'toolu_[a-zA-Z0-9]{10,}', '', text)
        # Meta leak: "Claude olarak", "ben bir AI" gibi sızıntılar
        # Neo harici kullanıcılara — prompt kuralı sıkı ama son emniyet
        # NOT: "claude" string'i tek başına çok aggressive, sadece "olarak" ile kombine
        text = _re_cr.sub(r'\bclaude\s+olarak\b', 'Fermat AI olarak', text, flags=_re_cr.IGNORECASE)
        text = _re_cr.sub(r'\bben\s+bir\s+AI\s+asistan[iı]?\w*\b', 'Fermat AI egitim kocu', text, flags=_re_cr.IGNORECASE)
        # Fazla bosluk temizle (silinen bloklar sonrasi)
        text = _re_cr.sub(r'\n{3,}', '\n\n', text)
        text = _re_cr.sub(r'[ \t]{2,}', ' ', text)
        return text.strip()
    except Exception as _cr_e:
        # OTURUM 22.2 (21 Nisan) — dead code fallback kaldirildi (~123 satir)
        # format_whatsapp.format_for_whatsapp bu vakalari zaten kapsiyor
        logger.warning(f"_clean_response hata (ham metin donuluyor): {_cr_e}")
        return (text or "").strip()


# ─── ACL Yardımcı Fonksiyonları ─────────────────────────────────────────────

async def _get_caller_profile(phone: str) -> dict:
    """Telefon numarasindan kullanici profilini al (acl + students)."""
    if not phone or not DATABASE_URL:
        return {"role": "admin", "full_name": "Admin", "phone": phone}
    # OTURUM 22.7 (21 Nisan) — phone_utils.normalize_phone delegasyonu
    from phone_utils import normalize_phone
    clean_phone = normalize_phone(phone) or phone
    try:
        # Oncelikle acl_users tablosundan bak
        rows = await _db_fetch(
            """SELECT role, full_name, eyotek_id, class_scope
               FROM acl_users WHERE phone = $1 AND is_active = TRUE LIMIT 1""",
            clean_phone,
        )
        if rows:
            r = rows[0]
            prof = {
                "role": r["role"],
                "full_name": r.get("full_name") or "Kullanici",
                "eyotek_id": r.get("eyotek_id") or "",
                "class_scope": r.get("class_scope") or [],
                "phone": clean_phone,
                "source": "acl",
            }
            # Orsel Koc — Sistem Gelistirme Muduru (ozel kademe, mudur yetkilerine ek)
            if clean_phone == "905547043775":
                prof["title"] = "Sistem Gelistirme Muduru"
                prof["is_sgm"] = True  # is_system_development_manager
            return prof
        # acl'de yoksa students tablosundan telefon eslestir
        student_rows = await _db_fetch(
            """SELECT eyotek_id, full_name, first_name, class_name, sube, program, soz_no
               FROM students WHERE phone = $1 LIMIT 1""",
            clean_phone,
        )
        if student_rows:
            s = student_rows[0]
            # Otomatik acl kaydı olustur (ogrenci roluyle)
            try:
                await _db_execute(
                    """INSERT INTO acl_users (phone, full_name, role, eyotek_id, is_active, notes)
                       VALUES ($1, $2, 'ogrenci', $3, TRUE, 'Otomatik kayit - telefon eslesmesi')
                       ON CONFLICT (phone) DO NOTHING""",
                    clean_phone, s["full_name"], s["eyotek_id"],
                )
                logger.info(f"  Otomatik ACL kaydı: {s['full_name']} → ogrenci")
            except Exception:
                pass
            return {
                "role": "ogrenci",
                "full_name": s.get("full_name") or "Ogrenci",
                "first_name": s.get("first_name") or "",
                "eyotek_id": s.get("eyotek_id") or "",
                "soz_no": s.get("soz_no") or "",
                "class_name": s.get("class_name") or s.get("sube") or "",
                "program": s.get("program") or "",
                "phone": clean_phone,
                "source": "student_phone_match",
            }
        # Hicbir yerde bulunamadi
        return {"role": "unknown", "full_name": "", "phone": clean_phone, "source": "none"}
    except Exception:
        return {"role": "admin", "full_name": "Admin", "phone": phone}


async def _get_caller_role(phone: str) -> str:
    """Telefon numarasından kullanıcı rolünü al (geriye uyumluluk)."""
    profile = await _get_caller_profile(phone)
    return profile["role"]


# ─── CLI Giriş Noktası ────────────────────────────────────────────────────────

async def main() -> None:
    agent = FermatCoreAgent()

    if len(sys.argv) > 1:
        # Tek komut modu: python fermat_core_agent.py "Ahmet'e bak"
        command = " ".join(sys.argv[1:])
        result  = await agent.run(command)
        print(result)
        return

    # İnteraktif mod
    print("=" * 60)
    print("🧠 FermatAI Core Agent — İnteraktif Mod")
    print("   'çıkış' veya 'exit' ile çıkın")
    print("=" * 60)
    while True:
        try:
            user_input = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nÇıkılıyor...")
            break
        if not user_input:
            continue
        if user_input.lower() in ("çıkış", "exit", "quit"):
            break
        if user_input.lower() in ("sıfırla", "reset"):
            agent.reset()
            print("  Konuşma geçmişi temizlendi.")
            continue

        result = await agent.run(user_input)
        print(f"\n🤖 {result}")


if __name__ == "__main__":
    asyncio.run(main())
