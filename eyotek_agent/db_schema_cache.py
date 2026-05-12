"""
FermatAI — DB Schema Cache (22.1n-neo iş4)
============================================

Claude sorgu oncesi schema kesfi yapiyor (SELECT column_name FROM information_schema...).
Bu token israfi + gecikme. Cozum: schema bir kez cek, 1 saat cache, system prompt'a enjekte.

KULLANIM:
  from db_schema_cache import get_schema_summary
  prompt += get_schema_summary()  # kısa string (~1-2KB)
"""
from __future__ import annotations

import time
from typing import Optional
from loguru import logger

from db_pool import db_fetch


# Bellek cache (tek process icin)
_CACHE: dict = {"ts": 0, "data": None}
_TTL_SEC = 3600  # 1 saat


# Kurumsal oneme gore onemli tablolar + acikca sekilen kolonlar
_PRIORITY_TABLES = [
    # Ogrenci
    "students", "student_exams", "student_exam_analysis",
    "student_topic_tracker", "student_timetable", "student_grades",
    "student_behaviour", "student_interactions", "student_insights",
    # Personel
    "staff", "teacher_timetable", "etut_teacher_summary",
    # Sinif
    "class_timetable", "attendance", "devamsizlik_sayisi",
    # Etut / Rehberlik
    "etut_history", "counsellor_notes",
    # RAG / Konu
    "rag_content",
    # Sistem
    "acl_users", "agent_conversations", "routing_stats",
    "usage_log", "daily_stats", "user_feedback",
    # Atlas (self-observing)
    "atlas_observations", "atlas_suggestions", "atlas_lifecycle",
    # Finans (NEO-ONLY — Claude prompt'ta rol kontrolu yapar)
    "ogrenci_odeme_snapshot", "geciken_snapshot", "kurum_gelir",
    "student_financial_summary", "geciken_taksit_ozet",
    "sezon_finans_ozet", "geciken_ay_bazli", "monthly_revenue_summary",
    "kurum_aylik_ciro", "financial_audit_log",
    # Universite
    "universite_taban", "yokatlas_programlar",
    # Plan state
    "student_active_plans",
]


async def _fetch_schema() -> dict:
    """information_schema'dan oncelikli tablolarin kolon + tiplerini cek.

    22.1n-neo fail-fix: data_type da prompt'a dahil (DATE kolonlari Claude anlar).
    NOT: FermatAI DB'de tablolar 'fermat' schema'sinda (public DEGIL).
    """
    try:
        rows = await db_fetch(
            """SELECT table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema IN ('fermat', 'public')
                  AND table_name = ANY($1::text[])
                ORDER BY table_name, ordinal_position""",
            _PRIORITY_TABLES,
        )
        schema = {}
        for r in rows:
            t = r["table_name"]
            if t not in schema:
                schema[t] = []
            # Tipi de ekle (sadece kritik tipler: date, numeric, jsonb, timestamp)
            dt = r["data_type"] or ""
            col = r["column_name"]
            critical_types = ("date", "timestamp", "numeric", "jsonb", "json", "boolean")
            if any(ct in dt for ct in critical_types):
                col_with_type = f"{col}::{dt.replace(' with time zone','tz').replace(' without time zone','')[:12]}"
                schema[t].append(col_with_type)
            else:
                schema[t].append(col)
        return schema
    except Exception as e:
        logger.debug(f"schema fetch err: {e}")
        return {}


async def get_schema_cache(force_refresh: bool = False) -> dict:
    """Schema'yi dict olarak dondur. TTL gecmisse yenile."""
    now = time.time()
    if not force_refresh and _CACHE["data"] and (now - _CACHE["ts"]) < _TTL_SEC:
        return _CACHE["data"]
    data = await _fetch_schema()
    if data:
        _CACHE["ts"] = now
        _CACHE["data"] = data
    return _CACHE["data"] or {}


async def get_schema_summary() -> str:
    """Claude system prompt'a eklenecek kisa string.

    Format: "table_name(col1, col2, col3, ...)" — her tablo bir satir.
    """
    schema = await get_schema_cache()
    if not schema:
        return ""
    lines = ["📊 DB SCHEMA (schema keşfi YAPMA, aşağıdaki listeyi kullan):"]
    for t in sorted(schema.keys()):
        cols = schema[t]
        # Cok fazla kolon varsa ilk 15'i
        if len(cols) > 15:
            col_str = ", ".join(cols[:15]) + f", ... ({len(cols)} kolon)"
        else:
            col_str = ", ".join(cols)
        lines.append(f"  • {t}({col_str})")
    return "\n".join(lines) + "\n" + _SQL_CHEATSHEET


# 22.1n-neo fail-fix: Sık kullanılan SQL pattern'leri (Claude'un ilk denemede doğru yazması için)
_SQL_CHEATSHEET = """
🔍 SIK SQL PATTERN'LERI (query_analytics icin — ilk denemede dogrulamak icin):

SEZON BAZLI TAHSILAT (aylik kirilimli):
  SELECT sezon, TO_CHAR(kayit_tarihi, 'YYYY-MM') AS ay,
         COUNT(*) AS kayit, SUM(kayit_fiyati) AS ciro
  FROM ogrenci_odeme_snapshot
  WHERE sezon IN ('2024.25','2025.26','2026.27')
  GROUP BY sezon, TO_CHAR(kayit_tarihi, 'YYYY-MM')
  ORDER BY sezon, ay;

GECIKEN ODEMELER (sadece aktif sezon):
  -- ⚠️ AKTIF SEZON DİNAMİK: from sinav_takvimi import aktif_sezon
  -- WHERE sezon = aktif_sezon() — '2025.26' / '2026.27' otomatik
  SELECT soz_no, full_name, borc, en_son_gort,
         (CURRENT_DATE - en_son_gort) AS gecikme_gun
  FROM geciken_snapshot WHERE sezon = '2025.26' ORDER BY borc DESC;
  -- Yeni sezon (1 Eylül 2026 sonrası): aktif_sezon() → '2026.27'

ROUTING P50/P95:
  SELECT response_source, COUNT(*) AS n,
         percentile_cont(0.5) WITHIN GROUP (ORDER BY response_ms)::int AS p50_ms,
         percentile_cont(0.95) WITHIN GROUP (ORDER BY response_ms)::int AS p95_ms
  FROM routing_stats WHERE created_at > NOW() - INTERVAL '7 days'
  GROUP BY response_source;

UNIVERSITE TABAN (BOLUM ARAMA — hedef_bolum_ara tool'unu kullan, direkt SQL DEGIL):
  SELECT universite, bolum, taban_puan, siralama, kontenjan, sehir, tur
  FROM universite_taban
  WHERE puan_turu='SAY' AND bolum ILIKE '%Fizik%' AND yil=2025
  ORDER BY taban_puan DESC LIMIT 200;

OGRENCI ANALIZ (get_student_analytics tool tercih — direkt SQL DEGIL):
  SELECT s.full_name, s.class_name, AVG(e.toplam) AS ort_net
  FROM students s JOIN student_exams e ON e.soz_no = s.soz_no::int
  WHERE s.soz_no::int = 182 GROUP BY s.full_name, s.class_name;

ETUT GECMIS (bir ders icin):
  SELECT tarih, ogretmen, konu, ogrenci_sayisi
  FROM etut_history WHERE ders = 'Fizik' AND tarih > NOW() - INTERVAL '30 days'
  ORDER BY tarih DESC;

YOL HATASI (bu DB'de fermat schema):
  - Tablolar 'fermat' schema'sinda (public DEGIL) — ama search_path ayarli, direkt tablo adi yeterli
  - information_schema sorgusu YASAK (zaten cache'de schema var, tekrar bakma)
"""


def get_schema_summary_sync() -> str:
    """Sync kullanim — cache'den. Bos ise empty string."""
    if not _CACHE["data"]:
        return ""
    schema = _CACHE["data"]
    lines = ["📊 DB SCHEMA (schema keşfi YAPMA, aşağıdaki listeyi kullan):"]
    for t in sorted(schema.keys()):
        cols = schema[t]
        if len(cols) > 15:
            col_str = ", ".join(cols[:15]) + f", ... ({len(cols)} kolon)"
        else:
            col_str = ", ".join(cols)
        lines.append(f"  • {t}({col_str})")
    return "\n".join(lines) + "\n" + _SQL_CHEATSHEET


if __name__ == "__main__":
    import asyncio, sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    async def main():
        s = await get_schema_summary()
        print(s)
        print(f"\nTOPLAM: {len(_CACHE['data']) if _CACHE['data'] else 0} tablo, "
              f"{sum(len(c) for c in (_CACHE['data'] or {}).values())} kolon")

    asyncio.run(main())
