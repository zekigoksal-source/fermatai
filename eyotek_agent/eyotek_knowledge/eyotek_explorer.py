"""
Eyotek Schema Explorer — Oturum 25.26
========================================

Eyotek sayfalarini gezip her birinin form schema'sini cikarir, DB'ye yazar.
Planner agent (Cerebras 70B) bu schema'lari okuyarak akilli navigation
planlari uretir.

Mimari:
    explorer (her sayfa icin)
       ├─ navigate to path
       ├─ open modal (varsa)
       ├─ inspect_page_form() → inputs/selects/buttons/modals
       ├─ click search (filtresiz) → table columns + sample row
       └─ UPSERT eyotek_page_schema (path, label, schema_json, ...)

CLI:
    python -m eyotek_knowledge.eyotek_explorer --priority    # 30 onemli sayfa
    python -m eyotek_knowledge.eyotek_explorer --all         # tum site_map
    python -m eyotek_knowledge.eyotek_explorer --page Student/exam-result
"""
from __future__ import annotations
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Optional

from loguru import logger

_ROOT = Path(__file__).resolve().parent.parent.parent
_FULL_MAP = _ROOT / "eyotek_agent" / "eyotek_full_site_map.json"
sys.path.insert(0, str(_ROOT / "eyotek_agent"))


# ─── ONCELIKLI SAYFA LISTESI ──────────────────────────────────────────────────
# Bot'un %95 sorusu bu 30 sayfaya iniyor. Tum 180 sayfayi kesfetmek pahali +
# gerekli degil. Kapsam genisleyince listeyi guncelle.
PRIORITY_PAGES = [
    # --- ETUT (en cok sorgu) ---
    ("Student/individual-lesson",            "Etut Ara"),
    ("Student/individual-lesson-input",      "Etut Girisi"),
    ("Student/individual-lesson-attendance", "Etut Yoklama"),
    ("Student/individual-lesson-control-student", "Etut Ogrenci Kontrol"),
    ("Student/individual-lesson-reports",    "Etut Raporlari"),

    # --- SINAV (Apotemi gibi yeni sinav sorgulari) ---
    ("Student/Test/test",                          "Sinav Degerlendirme"),
    ("Student/test-transferred",                   "Degerlendirilmis Sinavlar (Yeni Sinav Listesi)"),
    ("Student/test-transferred-dynamic-list",      "Sinav Detay - Tum Ogrenci Sonuclari (URL params: SnvTur+SnvKod+Sube)"),
    ("Student/exam-result",                        "Sinav Sonuclari"),
    ("Student/exam-statistic",                     "Sinav Istatistik"),
    ("Student/exam-combine",                       "TYT Birlestir"),
    ("Student/exam-combine-ayt",                   "AYT Birlestir"),
    ("Student/test-participation",                 "Sinav Katilim"),

    # --- YOKLAMA ---
    ("Student/attendance-check-multi",       "Ogrenci Yoklama Giris"),
    ("Student/attendance-class-control",     "Sinif Yoklama Kontrol"),
    ("Student/attendance-report",            "Yoklama Kontrol"),
    ("Student/attendance-today",             "Bugun Gelmeyenler"),
    ("Student/attendance-count",             "Devamsizlik Sayisi"),

    # --- OGRENCI ---
    ("Student/student",                      "Ogrenciler"),
    ("Student/list-students",                "Ogrenci Liste"),
    ("Student/class-list",                   "Sinif Listesi"),

    # --- REHBERLIK ---
    ("Student/guidance",                     "Rehberlik"),
    ("Student/counsellor-note-list",         "Rehberlik Notu"),
    ("Student/counsellor-class-note-list",   "Sinif Rehberligi"),
    ("Student/counsellor-note-appointment-list", "Veli Randevulari"),

    # --- DERS PROGRAMI ---
    ("Student/timetable",                    "Ders Programlari"),
    ("Student/schedule",                     "Ders Programi"),
    ("Student/schedule-teacher",             "Ogretmen Programi"),
    ("Student/timetable-class-list",         "Sinif Ders Programi"),

    # --- ODEV (dijital iz, seneye duzenli takip) ---
    ("Student/homework",                     "Odev (eski path)"),
    ("Student/homework-search",              "Odev Ara"),
    ("Student/homework-input",               "Odev Giris/Ver"),
    ("Student/homework-reports",             "Odev Raporlari (Aylik/Toplam ozet)"),

    # --- DAVRANIS ---
    ("Student/behaviour-search",             "Davranis Ara"),
    ("Student/behaviour",                    "Davranislar"),
]


# ─── DB SCHEMA ────────────────────────────────────────────────────────────────

_SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS eyotek_page_schema (
    page_path TEXT PRIMARY KEY,
    label TEXT,
    final_url TEXT,
    inputs JSONB DEFAULT '[]'::jsonb,
    selects JSONB DEFAULT '[]'::jsonb,
    buttons JSONB DEFAULT '[]'::jsonb,
    modals JSONB DEFAULT '[]'::jsonb,
    columns JSONB DEFAULT '[]'::jsonb,
    sample_rows JSONB DEFAULT '[]'::jsonb,
    can_filter BOOL DEFAULT FALSE,
    can_search BOOL DEFAULT FALSE,
    has_table BOOL DEFAULT FALSE,
    discovered_at TIMESTAMPTZ DEFAULT NOW(),
    error TEXT
);
"""


async def ensure_schema():
    """eyotek_page_schema tablosunu yarat (idempotent)."""
    from db_pool import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA_DDL)


async def explore_page(page_path: str, label: str) -> dict:
    """Tek sayfayi kesfeder. Schema dict doner."""
    from eyotek_knowledge.eyotek_navigator import inspect_page_form, navigate

    result = {
        "page_path": page_path,
        "label": label,
        "final_url": None,
        "inputs": [],
        "selects": [],
        "buttons": [],
        "modals": [],
        "columns": [],
        "sample_rows": [],
        "can_filter": False,
        "can_search": False,
        "has_table": False,
        "error": None,
    }

    # Step 1: form inspection (modal acilmis halde)
    info = await inspect_page_form(page_path, mode="modal")
    if info.get("error"):
        result["error"] = info["error"]
        return result

    result["final_url"] = info.get("url")
    result["inputs"] = info.get("inputs", [])
    result["selects"] = info.get("selects", [])
    result["buttons"] = info.get("buttons", [])
    result["modals"] = info.get("modals", [])
    result["can_filter"] = bool(result["inputs"]) or bool(result["selects"])

    # Step 2: filtresiz search → tablo columns
    nav = await navigate(page_path, filters=None, max_rows=2)
    if nav.get("success"):
        result["columns"] = nav.get("columns", [])
        result["sample_rows"] = nav.get("rows", [])[:2]
        result["can_search"] = nav.get("search_clicked", False)
        result["has_table"] = bool(result["columns"]) or bool(result["sample_rows"])

    return result


async def upsert_schema(schema: dict) -> None:
    """eyotek_page_schema'a UPSERT."""
    from db_pool import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO eyotek_page_schema
              (page_path, label, final_url, inputs, selects, buttons, modals,
               columns, sample_rows, can_filter, can_search, has_table,
               discovered_at, error)
            VALUES ($1,$2,$3,$4::jsonb,$5::jsonb,$6::jsonb,$7::jsonb,
                    $8::jsonb,$9::jsonb,$10,$11,$12,NOW(),$13)
            ON CONFLICT (page_path) DO UPDATE SET
              label=EXCLUDED.label,
              final_url=EXCLUDED.final_url,
              inputs=EXCLUDED.inputs,
              selects=EXCLUDED.selects,
              buttons=EXCLUDED.buttons,
              modals=EXCLUDED.modals,
              columns=EXCLUDED.columns,
              sample_rows=EXCLUDED.sample_rows,
              can_filter=EXCLUDED.can_filter,
              can_search=EXCLUDED.can_search,
              has_table=EXCLUDED.has_table,
              discovered_at=NOW(),
              error=EXCLUDED.error
        """,
            schema["page_path"], schema["label"], schema["final_url"],
            json.dumps(schema["inputs"]), json.dumps(schema["selects"]),
            json.dumps(schema["buttons"]), json.dumps(schema["modals"]),
            json.dumps(schema["columns"]), json.dumps(schema["sample_rows"]),
            schema["can_filter"], schema["can_search"], schema["has_table"],
            schema["error"],
        )


async def explore_all(pages: list[tuple[str, str]], delay_sec: float = 1.5) -> dict:
    """Tum sayfalari ardisik kesfet, DB'ye yaz, ozet rapor don."""
    await ensure_schema()
    summary = {"total": len(pages), "ok": 0, "error": 0, "results": []}

    for i, (path, label) in enumerate(pages, 1):
        logger.info(f"[{i}/{len(pages)}] {label} ({path})")
        try:
            schema = await explore_page(path, label)
            await upsert_schema(schema)
            if schema.get("error"):
                summary["error"] += 1
                status = f"ERR: {schema['error'][:80]}"
            else:
                summary["ok"] += 1
                status = (
                    f"inputs={len(schema['inputs'])} "
                    f"selects={len(schema['selects'])} "
                    f"cols={len(schema['columns'])} "
                    f"sample={len(schema['sample_rows'])}"
                )
            logger.success(f"   → {status}")
            summary["results"].append({"path": path, "label": label, "status": status})
        except Exception as e:
            logger.error(f"   ✗ {type(e).__name__}: {str(e)[:120]}")
            summary["error"] += 1
            summary["results"].append({"path": path, "label": label, "status": f"EXC: {e}"})

        # Eyotek'i bunaltmamak icin delay
        if i < len(pages):
            await asyncio.sleep(delay_sec)

    return summary


# ─── PUBLIC: planner icin schema okuma ────────────────────────────────────────

async def get_schema(page_path: str) -> Optional[dict]:
    """Planner icin: kayitli schema doner (None varsa)."""
    from db_pool import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM eyotek_page_schema WHERE page_path = $1",
            page_path,
        )
        return dict(row) if row else None


async def list_schemas(only_filterable: bool = True) -> list[dict]:
    """Planner icin: tum kayitli schema'lari listele (compact)."""
    from db_pool import get_pool
    pool = await get_pool()
    where = "WHERE can_filter = TRUE" if only_filterable else ""
    async with pool.acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT page_path, label, columns, can_filter, can_search,
                   jsonb_array_length(inputs) AS input_count,
                   jsonb_array_length(selects) AS select_count
            FROM eyotek_page_schema
            {where}
            ORDER BY page_path
        """)
        return [dict(r) for r in rows]


# ─── CLI ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Eyotek schema explorer")
    parser.add_argument("--page", help="Tek sayfayi kesfet (Path)")
    parser.add_argument("--label", help="Tek sayfa icin label", default="")
    parser.add_argument("--priority", action="store_true", help="30 oncelikli sayfa")
    parser.add_argument("--all", action="store_true", help="Tum site_map.json (180+)")
    parser.add_argument("--list", action="store_true", help="DB'deki kayitli schema'lari listele")
    parser.add_argument("--show", help="Tek bir sayfanin schema'sini goster")
    parser.add_argument("--delay", type=float, default=1.5, help="Sayfalar arasi delay (sn)")
    args = parser.parse_args()

    async def _main():
        if args.list:
            schemas = await list_schemas(only_filterable=False)
            for s in schemas:
                print(f"  {s['page_path']:50}  cols={len(s.get('columns') or [])}  filt={s['can_filter']}  inputs={s['input_count']}  selects={s['select_count']}")
            print(f"Total: {len(schemas)}")
            return

        if args.show:
            sc = await get_schema(args.show)
            if not sc:
                print(f"Schema yok: {args.show}")
                return
            print(json.dumps({k: v for k, v in sc.items() if k not in ("buttons",)}, default=str, indent=2, ensure_ascii=False))
            return

        pages: list[tuple[str, str]] = []
        if args.page:
            pages = [(args.page, args.label or args.page)]
        elif args.priority:
            pages = PRIORITY_PAGES
        elif args.all:
            # tum site_map.json'dan parse
            with _FULL_MAP.open(encoding="utf-8") as f:
                data = json.load(f)
            seen = set()
            for sec_key, sec in data.items():
                if not isinstance(sec, dict) or sec_key.startswith("_"):
                    continue
                for sub_key, items in sec.items():
                    if sub_key.startswith("_") or not isinstance(items, list):
                        continue
                    for it in items:
                        path = it.get("path")
                        label = it.get("label", path)
                        if path and path not in seen:
                            seen.add(path)
                            pages.append((path, label))
            print(f"Tum site_map: {len(pages)} unique path")
        else:
            parser.print_help()
            return

        summary = await explore_all(pages, delay_sec=args.delay)
        print(f"\n=== OZET ===")
        print(f"Total: {summary['total']}, OK: {summary['ok']}, ERR: {summary['error']}")

    asyncio.run(_main())
