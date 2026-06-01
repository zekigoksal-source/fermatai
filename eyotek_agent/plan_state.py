"""
Öğrenci Çalışma Planı State Yönetimi (22.1n-toplanti #2)
=========================================================

Bot TOP#2 önerisi — 20 Nisan toplanti:
> "Her seferinde sıfırdan build_study_plan_context çağırıyorum.
>  Plan hafızada tutulmuyor. 'Perşembeden itibaren güncelle' dediğinde
>  sıfırdan tüm planı yeniden yazıyorum — 25-40 saniye."

ÇÖZÜM: Plan bir kez üretilir, student_active_plans tablosunda yaşar.
Öğrenci düzenleme istediğinde sadece ilgili gün diff update.

KULLANIM:
  from plan_state import save_plan, get_active_plan, update_day

  # Plan üretildikten sonra kaydet:
  await save_plan(soz_no=174, plan_json={...})

  # "Perşembeyi güncelle" → sadece o gün:
  await update_day(174, "persembe", new_day_content)

  # Claude context için güncel plan:
  plan = await get_active_plan(174)

GÜVENLİK: MESAJ GÖNDERMEZ, sadece DB.
"""
import asyncio
import json
from datetime import datetime
from typing import Optional

from loguru import logger


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS student_active_plans (
    soz_no INT PRIMARY KEY,
    plan_json JSONB NOT NULL,
    plan_text TEXT,
    version INT DEFAULT 1,
    source TEXT DEFAULT 'claude',
    hedef_ozet TEXT,
    toplam_saat INT,
    hafta_basi DATE,
    hafta_sonu DATE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS plan_update_log (
    id SERIAL PRIMARY KEY,
    soz_no INT,
    change_type TEXT,
    target_day TEXT,
    old_content TEXT,
    new_content TEXT,
    changed_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_plan_log_soz ON plan_update_log(soz_no, changed_at DESC);
"""


GUNLER = ["pazartesi", "sali", "carsamba", "persembe", "cuma", "cumartesi", "pazar"]

GUN_ALIASES = {
    "pazartesi": ["pazartesi", "pzt"],
    "sali": ["sali", "salı"],
    "carsamba": ["carsamba", "çarşamba", "cars", "çrs"],
    "persembe": ["persembe", "perşembe", "prş", "perş"],
    "cuma": ["cuma", "cu"],
    "cumartesi": ["cumartesi", "cmt"],
    "pazar": ["pazar", "pzr"],
}


def normalize_gun(text: str) -> Optional[str]:
    """'Perşembe' → 'persembe' gibi normalize et."""
    t = (text or "").lower().strip()
    for key, aliases in GUN_ALIASES.items():
        if any(a in t for a in aliases):
            return key
    return None


async def init_db():
    from db_pool import db_execute
    await db_execute(SCHEMA_SQL)
    logger.info("student_active_plans + plan_update_log tablolari hazir")


async def save_plan(soz_no: int, plan_json: dict, plan_text: str = "",
                    hedef_ozet: str = "", toplam_saat: Optional[int] = None,
                    source: str = "claude") -> bool:
    """Yeni plan kaydet — mevcut varsa version++."""
    if not soz_no or not plan_json:
        return False
    try:
        soz_no = int(soz_no)
    except (ValueError, TypeError):
        return False

    from db_pool import db_execute, db_fetchval
    try:
        # Mevcut version
        v = await db_fetchval("SELECT version FROM student_active_plans WHERE soz_no=$1", soz_no)
        new_version = (v or 0) + 1

        await db_execute(
            """INSERT INTO student_active_plans
               (soz_no, plan_json, plan_text, version, source, hedef_ozet, toplam_saat, updated_at)
               VALUES ($1, $2::jsonb, $3, $4, $5, $6, $7, NOW())
               ON CONFLICT (soz_no) DO UPDATE SET
                 plan_json = EXCLUDED.plan_json,
                 plan_text = EXCLUDED.plan_text,
                 version = EXCLUDED.version,
                 source = EXCLUDED.source,
                 hedef_ozet = EXCLUDED.hedef_ozet,
                 toplam_saat = EXCLUDED.toplam_saat,
                 updated_at = NOW()""",
            soz_no, json.dumps(plan_json, ensure_ascii=False, default=str),
            plan_text[:8000] if plan_text else None,
            new_version, source, hedef_ozet[:500] if hedef_ozet else None,
            toplam_saat,
        )

        # Log
        await db_execute(
            """INSERT INTO plan_update_log (soz_no, change_type, new_content)
               VALUES ($1, 'full_save', $2)""",
            soz_no, (plan_text or "")[:2000]
        )
        # 22.1n-neo Paket B: plan değişti — context cache invalidate
        try:
            from study_plan_builder import invalidate_plan_cache
            invalidate_plan_cache(soz_no)
        except Exception:
            pass
        logger.info(f"  [PLAN save] soz_no={soz_no} v{new_version}")
        return True
    except Exception as e:
        logger.error(f"save_plan hata: {e}")
        return False


async def get_active_plan(soz_no: int) -> Optional[dict]:
    """Öğrencinin güncel planını getir."""
    if not soz_no:
        return None
    try:
        soz_no = int(soz_no)
    except (ValueError, TypeError):
        return None

    from db_pool import db_fetchrow
    try:
        row = await db_fetchrow(
            """SELECT plan_json, plan_text, version, hedef_ozet, toplam_saat,
                      created_at, updated_at
               FROM student_active_plans WHERE soz_no=$1""",
            soz_no
        )
        if not row:
            return None
        plan = row["plan_json"]
        if isinstance(plan, str):
            try:
                plan = json.loads(plan)
            except Exception as _e:
                # 25.50: eskiden sessizdi — bozuk plan_json string olarak dönüyordu
                logger.warning(f"[plan_state] plan_json parse hatasi (soz_no={soz_no}): {_e}")
        return {
            "plan": plan,
            "plan_text": row["plan_text"],
            "version": row["version"],
            "hedef_ozet": row["hedef_ozet"],
            "toplam_saat": row["toplam_saat"],
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
            "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
        }
    except Exception as e:
        logger.debug(f"get_active_plan err: {e}")
        return None


async def update_day(soz_no: int, gun: str, new_day_content: dict) -> bool:
    """Sadece bir günü güncelle — diff update.

    gun: 'persembe' gibi normalize edilmiş
    new_day_content: {"saat": 6, "konular": [...]}
    """
    plan_data = await get_active_plan(soz_no)
    if not plan_data or not plan_data.get("plan"):
        return False

    plan = plan_data["plan"]
    # Plan structure: {"gunler": {"pazartesi": {...}, ...}} ya da liste
    if isinstance(plan, dict):
        if "gunler" in plan:
            old = plan["gunler"].get(gun, {})
            plan["gunler"][gun] = new_day_content
        else:
            old = plan.get(gun, {})
            plan[gun] = new_day_content
    else:
        return False

    from db_pool import db_execute
    try:
        await db_execute(
            """UPDATE student_active_plans
               SET plan_json=$1::jsonb, version=version+1, updated_at=NOW()
               WHERE soz_no=$2""",
            json.dumps(plan, ensure_ascii=False, default=str), int(soz_no)
        )
        await db_execute(
            """INSERT INTO plan_update_log (soz_no, change_type, target_day, old_content, new_content)
               VALUES ($1, 'day_update', $2, $3, $4)""",
            int(soz_no), gun,
            json.dumps(old, ensure_ascii=False, default=str)[:1000],
            json.dumps(new_day_content, ensure_ascii=False, default=str)[:1000],
        )
        # 22.1n-neo Paket B: cache invalidate
        try:
            from study_plan_builder import invalidate_plan_cache
            invalidate_plan_cache(soz_no)
        except Exception:
            pass
        logger.info(f"  [PLAN day_update] soz_no={soz_no} gun={gun}")
        return True
    except Exception as e:
        logger.error(f"update_day hata: {e}")
        return False


async def delete_plan(soz_no: int) -> bool:
    """Plan'ı tamamen sil (öğrenci yeniden başlatmak istese)."""
    from db_pool import db_execute
    # 22.1n-neo Paket B: cache invalidate
    try:
        from study_plan_builder import invalidate_plan_cache
        invalidate_plan_cache(soz_no)
    except Exception:
        pass
    try:
        await db_execute("DELETE FROM student_active_plans WHERE soz_no=$1", int(soz_no))
        await db_execute(
            """INSERT INTO plan_update_log (soz_no, change_type)
               VALUES ($1, 'delete')""", int(soz_no)
        )
        return True
    except Exception:
        return False


async def list_recent_plans(limit: int = 20) -> list[dict]:
    """Admin için — son güncellenen planlar."""
    from db_pool import db_fetch
    rows = await db_fetch(
        """SELECT p.soz_no, s.full_name, s.class_name,
                  p.version, p.hedef_ozet, p.toplam_saat, p.updated_at
           FROM student_active_plans p
           LEFT JOIN students s ON s.soz_no::text = p.soz_no::text
           ORDER BY p.updated_at DESC LIMIT $1""", int(limit)
    )
    return [dict(r) for r in rows]


async def main():
    import argparse, sys, io
    parser = argparse.ArgumentParser()
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--get", type=int, help="Soz_no")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv(override=True)

    if args.init:
        await init_db()
    if args.list:
        plans = await list_recent_plans()
        print(f"Son guncellenen plan: {len(plans)}")
        for p in plans:
            print(f"  {p['soz_no']} {p.get('full_name','?')[:25]} v{p['version']} ({p['updated_at']})")
    if args.get:
        p = await get_active_plan(args.get)
        import json as _j
        print(_j.dumps(p, indent=2, ensure_ascii=False, default=str)[:2000])


if __name__ == "__main__":
    import io as _io, sys as _sys
    _sys.stdout = _io.TextIOWrapper(_sys.stdout.buffer, encoding="utf-8", errors="replace")
    asyncio.run(main())
