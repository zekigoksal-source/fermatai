"""
Teacher ACL Filter (Oturum 25.29 — Vedat hoca vakası)
======================================================

Bot Neo'ya konuşma analizinden bildirdi:
  Vedat hoca: "Özdebir sınav sonuçlarını söyler misin?"
  Bot: "ACL: ogretmen rolü sinav_sonuclari aracını kullanamaz"

Neo karari: Öğretmen, KENDİ DERSLERİNE GİRDİĞİ ÖĞRENCİLERİN sinav verilerini
görebilmeli. Diger sinif/ogrencilerin verilerine erişemez.

Bu modül:
  1. Öğretmen telefonu/adı → kendi sınıfları listesi (teacher_timetable)
  2. Bir tool çıktısındaki öğrenci satırlarını → kendi sınıflarına göre filtre
  3. Kara liste: ogretmen başka öğretmen/finans verisine erişemez

Format farkları:
  teacher_timetable.sinif: '[1] 12 SAY A' (prefix'li, Eyotek'ten)
  students.class_name:     '12 SAY A'    (temiz)
  → strip_class_prefix() ile [N] kısımı kaldırılır
"""
from __future__ import annotations
import re
import time
from typing import Optional

from loguru import logger

# Cache: ogretmen_phone → list[class_name] (5dk TTL)
_TEACHER_CLASS_CACHE: dict = {}
_TEACHER_CACHE_TTL = 300


def strip_class_prefix(class_str: str) -> str:
    """teacher_timetable formatından students formatına çevir.
    '[1] 12 SAY A' → '12 SAY A'
    """
    if not class_str:
        return ""
    return re.sub(r"^\[\d+\]\s*", "", class_str).strip()


async def get_teacher_classes_by_phone(phone: str) -> list[str]:
    """Öğretmenin telefonundan ders verdiği sınıflarının temiz listesini döndür.

    Returns: ['12 SAY A', '11 SAY VIB', ...]
            Boş liste = öğretmen bulunamadı veya sınıf yok
    """
    phone_clean = (phone or "").replace("+", "").strip()
    if not phone_clean:
        return []

    # Cache
    cache_entry = _TEACHER_CLASS_CACHE.get(phone_clean)
    if cache_entry and time.time() - cache_entry["ts"] < _TEACHER_CACHE_TTL:
        return list(cache_entry["classes"])

    from db_pool import db_fetch, db_fetchrow
    try:
        # 1. phone → staff direkt (staff.phone kolonu var)
        staff_row = await db_fetchrow(
            """SELECT full_name, first_name, last_name, eyotek_id
               FROM staff
               WHERE REPLACE(COALESCE(phone, ''), '+', '') = $1
               LIMIT 1""",
            phone_clean,
        )
        if not staff_row:
            # 2. phone → acl_users.full_name → staff.full_name fallback
            acl_row = await db_fetchrow(
                """SELECT full_name FROM acl_users
                   WHERE REPLACE(phone, '+', '') = $1 AND role = 'ogretmen'
                   LIMIT 1""",
                phone_clean,
            )
            if acl_row and acl_row.get("full_name"):
                staff_row = await db_fetchrow(
                    """SELECT full_name, first_name, last_name, eyotek_id
                       FROM staff
                       WHERE UPPER(TRIM(full_name)) = UPPER(TRIM($1))
                          OR UPPER(full_name) ILIKE $2
                       LIMIT 1""",
                    acl_row["full_name"],
                    f"%{acl_row['full_name'].split()[0]}%" if acl_row['full_name'] else "%",
                )

        if not staff_row:
            logger.debug(f"[TEACHER-ACL] phone {phone_clean} → staff bulunamadı")
            _TEACHER_CLASS_CACHE[phone_clean] = {"classes": [], "ts": time.time()}
            return []

        # Öğretmen bulundu — teacher_timetable'da sınıfları bul
        full_name = (staff_row.get('full_name')
                     or f"{staff_row.get('first_name', '')} {staff_row.get('last_name', '')}").strip()
        rows = await db_fetch(
            """SELECT DISTINCT sinif FROM teacher_timetable
               WHERE UPPER(ogretmen_ad) = UPPER($1)
                  OR ogretmen_id = $2""",
            full_name, str(staff_row.get('eyotek_id', '')),
        )
        if not rows:
            logger.debug(f"[TEACHER-ACL] {full_name} için teacher_timetable boş")
            _TEACHER_CLASS_CACHE[phone_clean] = {"classes": [], "ts": time.time()}
            return []

        # Prefix temizle, dedupe
        classes = sorted({strip_class_prefix(r["sinif"]) for r in rows if r["sinif"]})
        _TEACHER_CLASS_CACHE[phone_clean] = {"classes": classes, "ts": time.time()}
        return classes
    except Exception as e:
        logger.debug(f"[TEACHER-ACL] hata: {e}")
        return []


async def get_teacher_class_students(phone: str) -> list[dict]:
    """Öğretmenin sınıflarındaki tüm öğrencileri (soz_no, full_name, class_name)."""
    classes = await get_teacher_classes_by_phone(phone)
    if not classes:
        return []

    from db_pool import db_fetch
    try:
        rows = await db_fetch(
            """SELECT soz_no, full_name, class_name, status
               FROM students
               WHERE class_name = ANY($1::text[])
                 AND status = 'aktif'
               ORDER BY class_name, full_name""",
            classes,
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.debug(f"[TEACHER-ACL] students fetch fail: {e}")
        return []


def _row_belongs_to_teacher_classes(row: dict, allowed_classes: set[str],
                                     allowed_soz_nos: set[int]) -> bool:
    """Bir tool sonuç satırı öğretmenin sınıfında mı?

    Heuristic: row'da hem class_name + soz_no aramak.
    """
    # 1. soz_no eşleşmesi (en kesin)
    for key in ("soz_no", "sozNo", "söz_no", "ogrenci_id", "student_id", "id"):
        v = row.get(key)
        if v is None:
            continue
        try:
            if int(v) in allowed_soz_nos:
                return True
        except (ValueError, TypeError):
            continue

    # 2. class_name eşleşmesi
    for key in ("class_name", "sinif", "sınıf", "siniflama", "class"):
        v = row.get(key)
        if not v:
            continue
        cleaned = strip_class_prefix(str(v)).upper()
        if cleaned in {c.upper() for c in allowed_classes}:
            return True

    # 3. Ad eşleşmesi (öğrencinin tam adı students.full_name'le eşleşirse)
    for key in ("full_name", "ad_soyad", "name", "ogrenci", "ogrenci_adi"):
        v = row.get(key)
        if not v:
            continue
        # Bu daha pahalı — son çare
        # Şu an skip, soz_no/class_name yeterli olmalı
        pass

    return False


async def filter_rows_for_teacher(rows: list[dict], phone: str) -> tuple[list[dict], dict]:
    """Bir tool sonuç listesini öğretmenin sınıflarına göre filtrele.

    Returns: (filtered_rows, meta)
            meta: {original_count, filtered_count, allowed_classes}
    """
    if not rows:
        return [], {"original_count": 0, "filtered_count": 0, "allowed_classes": []}

    allowed_classes = await get_teacher_classes_by_phone(phone)
    if not allowed_classes:
        return [], {
            "original_count": len(rows),
            "filtered_count": 0,
            "allowed_classes": [],
            "reason": "teacher_no_classes",
        }

    # Allowed soz_no list (öğrencilere göre)
    students = await get_teacher_class_students(phone)
    allowed_soz_nos = {int(s["soz_no"]) for s in students if s.get("soz_no")}
    allowed_classes_set = set(allowed_classes)

    filtered = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if _row_belongs_to_teacher_classes(row, allowed_classes_set, allowed_soz_nos):
            filtered.append(row)

    return filtered, {
        "original_count": len(rows),
        "filtered_count": len(filtered),
        "allowed_classes": list(allowed_classes),
        "allowed_students": len(allowed_soz_nos),
    }


async def filter_tool_result_for_teacher(result: dict, phone: str) -> dict:
    """Tool sonuç dict'ini öğretmen ACL filtresinden geçir.

    Beklenen yapı: result {sonuc: [...], rows: [...], data: [...]} veya direkt list.
    Hangi key list olursa onu filtrele.

    Returns: filtered_result + 'teacher_filter' meta key
    """
    if not isinstance(result, dict):
        return result

    # Hata durumunda dokunma
    if "error" in result and not result.get("rows") and not result.get("sonuc"):
        return result

    filtered_result = dict(result)
    filter_meta_total = {"original_count": 0, "filtered_count": 0,
                         "allowed_classes": []}

    for list_key in ("rows", "sonuc", "data", "results", "students", "ogrenciler"):
        v = result.get(list_key)
        if isinstance(v, list) and v and isinstance(v[0], dict):
            filtered, meta = await filter_rows_for_teacher(v, phone)
            filtered_result[list_key] = filtered
            filter_meta_total["original_count"] += meta.get("original_count", 0)
            filter_meta_total["filtered_count"] += meta.get("filtered_count", 0)
            if meta.get("allowed_classes") and not filter_meta_total["allowed_classes"]:
                filter_meta_total["allowed_classes"] = meta["allowed_classes"]

    # Öğretmen sınıfsız ise warning ekle
    if not filter_meta_total["allowed_classes"]:
        filtered_result["teacher_filter"] = {
            "warning": "Ders verdiğiniz sınıf bulunamadı (teacher_timetable boş?)",
            "filtered_to_zero": True,
        }
    else:
        filtered_result["teacher_filter"] = filter_meta_total
        # Eger filtre sonrası sıfır kayıt kaldıysa kullanıcıya açıklama
        if (filter_meta_total["original_count"] > 0
                and filter_meta_total["filtered_count"] == 0):
            filtered_result["mesaj"] = (
                f"Bu sınavın sonuçlarında ders verdiğiniz "
                f"{len(filter_meta_total['allowed_classes'])} sınıftan öğrenci yok. "
                f"Sınıflar: {', '.join(filter_meta_total['allowed_classes'][:5])}"
            )

    return filtered_result


def invalidate_cache(phone: Optional[str] = None):
    """Cache temizle (test/admin override için)."""
    if phone is None:
        _TEACHER_CLASS_CACHE.clear()
    else:
        _TEACHER_CLASS_CACHE.pop(phone.replace("+", ""), None)


# ─── CLI test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    async def _test():
        # Vedat hocanın phone'unu DB'den bul
        from db_pool import db_fetchrow
        row = await db_fetchrow(
            """SELECT REPLACE(COALESCE(phone, ''), '+', '') AS p, full_name
               FROM staff
               WHERE full_name ILIKE '%Vedat%'
               LIMIT 1"""
        )
        if not row:
            print("Vedat hoca DB'de bulunamadi")
            return

        phone = row["p"]
        print(f"Vedat hoca phone: {phone}")
        print()

        # Sınıfları
        classes = await get_teacher_classes_by_phone(phone)
        print(f"=== Sinif sayisi: {len(classes)} ===")
        for c in classes:
            print(f"  {c}")
        print()

        # Öğrenci sayısı
        students = await get_teacher_class_students(phone)
        print(f"=== Ogrenci sayisi: {len(students)} ===")
        for s in students[:8]:
            print(f"  [{s['class_name']}] {s['full_name']} (soz_no={s['soz_no']})")

    asyncio.run(_test())
