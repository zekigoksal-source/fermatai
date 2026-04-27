"""
Eyotek Query Planner — Oturum 25.26
======================================

Kullanici sorusu (Turkce, dogal dil) → Cerebras 70B → JSON navigation plan.

Mimari:
    plan_query("dun hangi etutler vardi")
        ├─ build_planner_prompt: 31 sayfanin compact schema'si + tarih bilgisi
        ├─ Cerebras gpt-oss-120b cagrisi (~$0.0001, ~1sn)
        └─ JSON dondu: {page_path, filters, max_rows, explain, confidence}

Sonra caller:
    plan = await plan_query(question)
    if plan["confidence"] > 0.5:
        result = await navigate(plan["page_path"], filters=plan["filters"], ...)

Tasarim ilkeleri:
  - Schema DB'den okunur (eyotek_explorer ile guncellenir, planner her seferinde)
  - Bugun tarihi prompt'a enjekte edilir → "dun" / "3 gun once" planner cozer
  - Planner duyarli/imkansiz sorulara confidence:0 doner — caller fallback yapar
  - Compact schema: label + columns + filter_keys (30 sayfa ~3KB)
"""
from __future__ import annotations
import asyncio
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from loguru import logger

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "eyotek_agent"))


# ─── COMPACT SCHEMA OZETLEMESI ────────────────────────────────────────────────
# Planner'a her sayfanin TUM input/select detayini vermek pahali. Compact:
#   {path, label, columns, filter_keys: [date_from, date_to, teacher, ...]}
# Filter keys schema'daki id/name pattern'lerinden cikar.

_FILTER_PATTERNS = {
    "date_from":  [r"txt.*Bas", r"txt.*Begin", r"txt.*Tarih.*Bas"],
    "date_to":    [r"txt.*Bit", r"txt.*End"],
    "teacher":    [r"cmb.*Ogrt", r"cmb.*Teacher", r"cmb.*Staff", r"cmb.*Ogretmen"],
    "ders":       [r"cmb.*Ders$", r"cmb.*Lesson", r"cmb.*Dersad"],
    "branch":     [r"cmb.*Sube", r"cmb.*Subek"],
    "class":      [r"cmb.*Sinif", r"cmb.*Class"],
    "etut_type":  [r"cmb.*EtudTur", r"cmb.*EtutTur", r"cmb.*Type"],
    "yoklama":    [r"cmb.*Yoklama"],
    "classroom":  [r"cmb.*Derslik"],
    "etut_kod":   [r"txt.*EtutKod", r"txt.*Kod"],
    "student":    [r"txt.*AdSoyad", r"txt.*StudentName", r"txt.*Name"],
    "exam_name":  [r"txt.*Sinav", r"txt.*Test", r"txt.*Exam"],
}


def _extract_filter_keys(schema: dict) -> list[str]:
    """Schema input/select id'lerinden destekli filter_key'leri cikar."""
    keys = set()
    inputs = schema.get("inputs") or []
    selects = schema.get("selects") or []
    all_ids = []
    for el in inputs + selects:
        if isinstance(el, dict):
            all_ids.append(el.get("id", ""))
            all_ids.append(el.get("name", ""))
    blob = " ".join(all_ids)
    for filter_key, patterns in _FILTER_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, blob, re.IGNORECASE):
                keys.add(filter_key)
                break
    return sorted(keys)


async def build_compact_catalog() -> list[dict]:
    """DB'den tum schema'lari oku, compact catalog don."""
    from eyotek_knowledge.eyotek_explorer import list_schemas, get_schema
    schemas = await list_schemas(only_filterable=False)
    compact = []
    for s in schemas:
        path = s["page_path"]
        label = s["label"]
        cols = s.get("columns") or []
        # filter_keys icin tam schema'yi getir (hafifce optimize: ilk N sayfa)
        full = await get_schema(path)
        if not full:
            continue
        filter_keys = _extract_filter_keys(full)
        compact.append({
            "path": path,
            "label": label,
            "columns": cols[:14],  # ilk 14 sutun (token tasarrufu)
            "filter_keys": filter_keys,
            "has_table": s.get("can_filter", False) or bool(cols),
        })
    return compact


# ─── PLANNER PROMPT ─────────────────────────────────────────────────────────

_PLANNER_SYSTEM = """Sen Eyotek LMS sayfa navigasyon planlayicisisin. Kullanici Turkce dogal dilde sorar (orn: "dun hangi etutler vardi"), sen DOGRU sayfayi ve filtreleri secersin.

GOREVIN: Kullanici sorusunu, asagidaki page catalog'a bakarak bir JSON plana cevir.

JSON CIKTI FORMATI (sadece JSON, baska metin YOK):
{
  "page_path": "Student/individual-lesson",
  "filters": {"date_from": "26.04.2026", "date_to": "26.04.2026"},
  "max_rows": 30,
  "explain": "Kullanici dunun (26.04) etutlerini sordu. Etut Ara sayfasinin tarih filtresiyle.",
  "confidence": 0.95
}

KURALLAR:
- date_from/date_to formati: dd.MM.yyyy (orn: 26.04.2026)
- BUGUN tarihi prompt'ta verilir, "dun" / "geçen hafta" / "N gun once" gibi ifadeleri sen cözersin
- Eger sayfa filtre kabul etmiyorsa "filters" bos: {}
- Kullanici sorusunu netlestiremiyorsan confidence < 0.5 ver
- Eger HIC uygun sayfa yoksa: page_path: "" + confidence: 0
- "explain" 1 cumlede neyi nasil yaptigini ozetler (kullaniciya gosterilir)
- max_rows: detay isteniyorsa 30, ozet ise 10, listele dendi ise 50

ORNEKLER:
Q: "dun hangi etutler vardi"
A: {"page_path":"Student/individual-lesson","filters":{"date_from":"<dun>","date_to":"<dun>"},"max_rows":30,"explain":"Dunun etut listesi.","confidence":0.95}

Q: "Apotemi sinavinin sonuclari"
A: {"page_path":"Student/exam-result","filters":{"exam_name":"Apotemi"},"max_rows":50,"explain":"Apotemi sinav sonuclari.","confidence":0.85}

Q: "bu hafta yoklama almayanlar"
A: {"page_path":"Student/attendance-report","filters":{"date_from":"<bu_hafta_basla>","date_to":"<bugun>","yoklama":"Alinmamis"},"max_rows":50,"explain":"Bu haftanin yoklama alinmamis listesi.","confidence":0.85}

Q: "Mehmet Donmez'in Nisan etutleri"
A: {"page_path":"Student/individual-lesson","filters":{"date_from":"01.04.2026","date_to":"30.04.2026","teacher":"Mehmet Donmez"},"max_rows":50,"explain":"Mehmet Donmez ogretmenin Nisan etutleri.","confidence":0.92}

Q: "bu hafta matematik etutleri"
A: {"page_path":"Student/individual-lesson","filters":{"date_from":"<bu_hafta_basla>","date_to":"<bugun>","ders":"Matematik"},"max_rows":50,"explain":"Bu hafta matematik etutleri.","confidence":0.90}

Q: "yoklama alinmamis etutler bugun"
A: {"page_path":"Student/individual-lesson","filters":{"date_from":"<bugun>","date_to":"<bugun>","yoklama":"Alınmamış"},"max_rows":30,"explain":"Bugun yoklama alinmamis etutler.","confidence":0.88}

Q: "en son hangi sinav yapildi"
A: {"page_path":"Student/Test/test","filters":{},"max_rows":10,"explain":"Sinav degerlendirme sayfasinda en son sinavlar listelenir.","confidence":0.78}

Q: "TYT sinavlarini birlestir"
A: {"page_path":"Student/exam-combine","filters":{},"max_rows":20,"explain":"TYT sinavlari birlestir sayfasi.","confidence":0.82}

Q: "12 SAY A sinif ders programi"
A: {"page_path":"Student/timetable-class-list","filters":{"class":"12 SAY A"},"max_rows":30,"explain":"12 SAY A sinifin ders programi.","confidence":0.85}

Q: "Kardelen Savci ogretmenin gecen hafta etutlerinden yoklama alinmamis olanlari"
A: {"page_path":"Student/individual-lesson","filters":{"date_from":"<gecen_hafta_basla>","date_to":"<gecen_hafta_son>","teacher":"Kardelen Savci","yoklama":"Alınmamış"},"max_rows":50,"explain":"Kardelen Hocanin gecen hafta yoklamasiz etutleri.","confidence":0.88}

Q: "kasa raporu"
A: {"page_path":"","filters":{},"max_rows":0,"explain":"Mali sayfalar bot kapsami disinda.","confidence":0}

Q: "dun yoklama nasildi"
A: {"page_path":"Student/attendance-report","filters":{"date_from":"<dun>","date_to":"<dun>"},"max_rows":30,"explain":"Dun yoklama raporu.","confidence":0.92}

Q: "Nisan ayinda yazilan rehberlik notlari"
A: {"page_path":"Student/counsellor-note-list","filters":{"date_from":"01.04.2026","date_to":"30.04.2026"},"max_rows":50,"explain":"Nisan rehberlik notlari.","confidence":0.92}

ZORUNLU: Soruda zaman ifadesi varsa (dun, Nisan, gecen hafta vs.) ve sayfa date_from kabul ediyorsa filter MUTLAKA EKLE.
ZORUNLU: Sayfa katalogu ile az da olsa eslesen sorulari bos plan'la DONDURME — sec, confidence 0.6+.
"""


def _date_context() -> str:
    today = date.today()
    yesterday = today - timedelta(days=1)
    week_start = today - timedelta(days=today.weekday())
    last_week_start = week_start - timedelta(days=7)
    last_week_end = week_start - timedelta(days=1)
    month_start = today.replace(day=1)
    return (
        f"BUGUN: {today.strftime('%d.%m.%Y')} ({today.strftime('%A')})\n"
        f"DUN: {yesterday.strftime('%d.%m.%Y')}\n"
        f"BU_HAFTA: {week_start.strftime('%d.%m.%Y')} - {today.strftime('%d.%m.%Y')}\n"
        f"GECEN_HAFTA: {last_week_start.strftime('%d.%m.%Y')} - {last_week_end.strftime('%d.%m.%Y')}\n"
        f"BU_AY_BASLA: {month_start.strftime('%d.%m.%Y')}\n"
    )


def _build_catalog_text(catalog: list[dict]) -> str:
    """Compact catalog'u prompt'a uygun text formatina cevir."""
    lines = ["EYOTEK SAYFA KATALOGU:\n"]
    for i, c in enumerate(catalog, 1):
        cols = ", ".join(c["columns"][:8]) if c["columns"] else "(sutun bilgisi yok)"
        flt = ", ".join(c["filter_keys"]) if c["filter_keys"] else "(filtresiz)"
        lines.append(f"{i}. {c['label']} → {c['path']}")
        lines.append(f"   filtreler: {flt}")
        lines.append(f"   sutunlar: {cols}")
        lines.append("")
    return "\n".join(lines)


# ─── ANA API ─────────────────────────────────────────────────────────────────

async def plan_query(question: str, catalog: Optional[list[dict]] = None) -> dict:
    """Kullanici sorusunu Eyotek navigation plan'a cevir.

    Args:
        question: kullanici metni
        catalog:  None ise DB'den otomatik yuklenir

    Returns:
        {page_path, filters, max_rows, explain, confidence, raw_response}
    """
    if catalog is None:
        catalog = await build_compact_catalog()

    catalog_text = _build_catalog_text(catalog)
    user_prompt = (
        f"{_date_context()}\n"
        f"{catalog_text}\n"
        f"KULLANICI SORUSU:\n\"{question}\"\n\n"
        f"JSON plani uret:"
    )

    # Cerebras direkt — 503 retry + Groq fallback
    raw = ""
    last_err = ""
    try:
        from cerebras_handler import CerebrasClient
        if not os.getenv("CEREBRAS_API_KEY"):
            raise RuntimeError("CEREBRAS_API_KEY env yok")
        client = CerebrasClient()  # api_key env'den otomatik

        # Cerebras 503/parse retry (5 deneme, exp backoff)
        for attempt in range(5):
            try:
                result = await client.complete_async(
                    messages=[{"role": "user", "content": user_prompt}],
                    system=_PLANNER_SYSTEM,
                    model="gpt-oss-120b",
                    max_tokens=700,
                    temperature=0.1,
                )
                if result.get("ok"):
                    candidate_raw = result.get("text", "")
                    # Hizli sanity check: JSON benzeri icerik var mi?
                    if "{" in candidate_raw and "page_path" in candidate_raw:
                        raw = candidate_raw
                        break
                    # Bos veya bozuk: retry
                    last_err = "empty/non-JSON response"
                    await asyncio.sleep(0.5 * (1.5 ** attempt))
                    continue
                err_str = str(result.get("error", ""))
                last_err = err_str
                if "503" in err_str or "high traffic" in err_str.lower() or "rate" in err_str.lower():
                    await asyncio.sleep(1.0 * (2 ** attempt))  # 1.0 / 2.0 / 4.0 / 8.0 / 16.0
                    continue
                break  # diger hatalar: retry yok
            except Exception as e:
                last_err = str(e)
                await asyncio.sleep(0.5)
                continue
    except Exception as e:
        last_err = f"init fail: {e}"

    # Groq fallback (Cerebras yetmediyse)
    if not raw:
        try:
            from llm_router import LLMRouter
            router = LLMRouter()
            if router._groq_available and router._groq_client:
                groq_result = await router._groq_client.complete(
                    messages=[{"role": "user", "content": user_prompt}],
                    system=_PLANNER_SYSTEM,
                    max_tokens=700,
                )
                if isinstance(groq_result, dict):
                    raw = groq_result.get("text", "")
                logger.info("[PLANNER] Groq fallback kullanildi")
        except Exception as e:
            logger.debug(f"[PLANNER] Groq fallback fail: {e}")

    if not raw:
        logger.warning(f"[PLANNER] Tum LLM denemeleri basarisiz: {last_err[:120]}")
        return {
            "page_path": "", "filters": {}, "max_rows": 0,
            "explain": f"Planner LLM hatasi: {last_err[:100]}",
            "confidence": 0, "raw_response": None,
        }

    # JSON parse — bazen LLM ek metin koyar, JSON bloku ayikla
    plan = _parse_plan_json(raw)
    plan["raw_response"] = raw[:500]
    return plan


def _parse_plan_json(text: str) -> dict:
    """Metin icinden JSON plan ayikla — 4 strateji.

    1. ```json ... ``` blok
    2. Ilk { ... son }
    3. ``` ... ``` (json etiketi olmadan)
    4. Saf JSON (text'in tamami)
    """
    default = {"page_path": "", "filters": {}, "max_rows": 0,
               "explain": "Plan parse hatasi", "confidence": 0}
    if not text or not text.strip():
        return default

    candidates = []
    # 1. ```json ... ```
    m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if m:
        candidates.append(m.group(1))
    # 2. Ilk { ... son }
    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last > first:
        candidates.append(text[first:last+1])
    # 3. Saf — tum text JSON olabilir
    candidates.append(text.strip())

    for cand in candidates:
        # Yaygin LLM hatalari: trailing commas, single quotes
        cleaned = cand
        cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)  # trailing commas
        try:
            plan = json.loads(cleaned)
            if not isinstance(plan, dict):
                continue
            return {
                "page_path":  str(plan.get("page_path", "")),
                "filters":    plan.get("filters") or {},
                "max_rows":   int(plan.get("max_rows") or 30),
                "explain":    str(plan.get("explain", "")),
                "confidence": float(plan.get("confidence", 0)),
            }
        except Exception:
            continue

    logger.debug(f"[PLANNER] Tum parse stratejileri basarisiz: text={text[:200]}")
    return default


# ─── EXECUTE: PLAN -> NAVIGATE -> RESULT ──────────────────────────────────────

async def execute_query(question: str, max_rows: Optional[int] = None) -> dict:
    """End-to-end: kullanici sorusu → plan → navigate → veri.

    Bu fonksiyon Claude tool'u olarak cagrilir.
    """
    plan = await plan_query(question)
    plan_only = {k: v for k, v in plan.items() if k != "raw_response"}

    # Confidence dusuk veya page_path bos → erken return
    if plan["confidence"] < 0.4 or not plan["page_path"]:
        return {
            "success": False,
            "plan": plan_only,
            "error": "Sorgu icin uygun Eyotek sayfasi bulunamadi (confidence dusuk).",
        }

    # Navigate
    from eyotek_knowledge.eyotek_navigator import navigate
    eff_max = max_rows or plan["max_rows"] or 30
    nav = await navigate(
        page_path=plan["page_path"],
        filters=plan["filters"],
        max_rows=eff_max,
    )

    return {
        "success": nav.get("success", False),
        "plan": plan_only,
        "page": plan["page_path"],
        "filters_applied": nav.get("filters_applied", {}),
        "filters_failed":  nav.get("filters_failed", []),
        "columns": nav.get("columns", []),
        "rows":    nav.get("rows", []),
        "row_count": nav.get("row_count", 0),
        "error_code": nav.get("error_code"),
        "error":      nav.get("error"),
    }


# ─── CLI ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Eyotek Query Planner")
    parser.add_argument("question", nargs="?", help="Kullanici sorusu")
    parser.add_argument("--plan-only", action="store_true", help="Sadece plan goster, navigate etme")
    parser.add_argument("--catalog", action="store_true", help="DB catalog'unu goster")
    args = parser.parse_args()

    async def _main():
        if args.catalog:
            cat = await build_compact_catalog()
            print(_build_catalog_text(cat))
            return
        if not args.question:
            parser.print_help()
            return
        if args.plan_only:
            plan = await plan_query(args.question)
            print(json.dumps({k: v for k, v in plan.items() if k != "raw_response"},
                             ensure_ascii=False, indent=2))
            return
        result = await execute_query(args.question)
        # Print compact summary
        print(f"PLAN: {json.dumps(result['plan'], ensure_ascii=False)}")
        print(f"SUCCESS: {result['success']}")
        print(f"ROWS: {result.get('row_count', 0)}")
        if result.get("filters_applied"):
            print(f"FILTERS APPLIED: {result['filters_applied']}")
        if result.get("error"):
            print(f"ERROR: {result['error']}")
        print(f"COLUMNS: {result.get('columns', [])[:10]}")
        for row in (result.get("rows") or [])[:3]:
            print(f"  ROW: {row}")

    asyncio.run(_main())
