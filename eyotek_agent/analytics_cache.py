"""
Analytics Cache — Sik sorulan sorularin cevaplarini onceden hesapla ve cache'le.

Sistem basladiginda veya periyodik olarak calisir.
Agent soru geldiginde once buraya bakar — DB'ye gitmeden aninda cevap.
"""
import asyncio
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from db_pool import get_pool, db_fetch

CACHE_FILE = Path(__file__).parent / ".analytics_cache.json"


async def query(sql: str, *args) -> list[dict]:
    """Pool uzerinden hizli sorgu."""
    return await db_fetch(sql, *args)


def _serialize(data):
    """JSON serializable yap."""
    if isinstance(data, list):
        return [_serialize(d) for d in data]
    if isinstance(data, dict):
        return {k: _serialize(v) for k, v in data.items()}
    if hasattr(data, 'isoformat'):
        return data.isoformat()
    return data


async def build_all_caches() -> dict:
    """Tum cache'leri olustur. Sistem baslagicinda ve periyodik olarak cagir."""
    cache = {
        "_meta": {
            "built_at": datetime.now().isoformat(),
            "version": 1,
        }
    }

    try:
        # 1. Ogretmen listesi + brans
        cache["ogretmen_listesi"] = _serialize(await query(
            "SELECT full_name, brans, gorev FROM staff WHERE brans IS NOT NULL ORDER BY full_name"
        ))

        # 2. Ogretmen etut yogunlugu (tum sezon)
        cache["ogretmen_etut_toplam"] = _serialize(await query("""
            SELECT ogretmen, COUNT(*) as etut_sayisi,
                   SUM(ogrenci_sayisi) as toplam_ogrenci,
                   MIN(tarih) as ilk_etut, MAX(tarih) as son_etut,
                   COUNT(DISTINCT ders) as ders_cesidi
            FROM etut_history
            GROUP BY ogretmen ORDER BY etut_sayisi DESC
        """))

        # 3. Ogretmen etut yogunlugu (son 30 gun)
        cache["ogretmen_etut_son30"] = _serialize(await query("""
            SELECT ogretmen, COUNT(*) as etut_sayisi,
                   SUM(ogrenci_sayisi) as toplam_ogrenci
            FROM etut_history
            WHERE tarih >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY ogretmen ORDER BY etut_sayisi DESC
        """))

        # 4. Ders bazli etut dagilimi
        cache["ders_etut_dagilimi"] = _serialize(await query("""
            SELECT ders, COUNT(*) as etut_sayisi,
                   SUM(ogrenci_sayisi) as toplam_ogrenci
            FROM etut_history GROUP BY ders ORDER BY etut_sayisi DESC
        """))

        # 5. En cok devamsizlik yapan ogrenciler (top 20)
        cache["devamsizlik_top20"] = _serialize(await query("""
            SELECT adi, soyadi, sinif, toplam_saat
            FROM devamsizlik_sayisi
            ORDER BY toplam_saat DESC LIMIT 20
        """))

        # 6. Sinif bazli ogrenci sayisi
        cache["sinif_ogrenci_sayisi"] = _serialize(await query("""
            SELECT class_name, COUNT(*) as ogrenci_sayisi
            FROM students WHERE class_name IS NOT NULL
            GROUP BY class_name ORDER BY class_name
        """))

        # 7. Genel istatistikler
        stats = {}
        stats["toplam_ogrenci"] = (await query("SELECT COUNT(*) as c FROM students"))[0]["c"]
        stats["toplam_personel"] = (await query("SELECT COUNT(*) as c FROM staff"))[0]["c"]
        stats["toplam_etut"] = (await query("SELECT COUNT(*) as c FROM etut_history"))[0]["c"]
        stats["toplam_rehberlik"] = (await query("SELECT COUNT(*) as c FROM counsellor_notes"))[0]["c"]
        stats["etut_tarih_araligi"] = _serialize(
            (await query("SELECT MIN(tarih) as ilk, MAX(tarih) as son FROM etut_history"))[0]
        )
        stats["yoklama_alinmis"] = (await query(
            "SELECT COUNT(*) as c FROM etut_history WHERE yoklama ILIKE '%alınmış%' OR yoklama ILIKE '%alinmis%'"
        ))[0]["c"]
        stats["yoklama_alinmamis"] = (await query(
            "SELECT COUNT(*) as c FROM etut_history WHERE yoklama ILIKE '%alınmamış%' OR yoklama ILIKE '%alinmamis%'"
        ))[0]["c"]
        cache["genel_istatistik"] = stats

        # 8. Rehberlik notu ozeti (ogretmen bazli)
        cache["rehberlik_ozet"] = _serialize(await query("""
            SELECT ogretmen, COUNT(*) as not_sayisi,
                   COUNT(DISTINCT soz_no) as ogrenci_sayisi
            FROM counsellor_notes
            GROUP BY ogretmen ORDER BY not_sayisi DESC
        """))

        # 9. Aylik etut trendi
        cache["aylik_etut_trendi"] = _serialize(await query("""
            SELECT TO_CHAR(tarih, 'YYYY-MM') as ay, COUNT(*) as etut_sayisi,
                   SUM(ogrenci_sayisi) as toplam_ogrenci
            FROM etut_history GROUP BY ay ORDER BY ay
        """))

        # 10. Sinav istatistikleri
        cache["sinav_istatistik"] = _serialize(await query("""
            SELECT COUNT(*) as toplam_sinav, COUNT(DISTINCT soz_no) as ogrenci_sayisi,
                   MIN(exam_date) as ilk_sinav, MAX(exam_date) as son_sinav
            FROM student_exams
        """))

        # Cache dosyasina yaz
        CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

    except Exception as e:
        cache["_meta"]["error"] = str(e)

    return cache


def load_cache() -> dict:
    """Cache dosyasini oku."""
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def get_cache_age_minutes() -> float:
    """Cache kac dakika once olusturuldu."""
    cache = load_cache()
    built = cache.get("_meta", {}).get("built_at")
    if built:
        try:
            dt = datetime.fromisoformat(built)
            return (datetime.now() - dt).total_seconds() / 60
        except Exception:
            pass
    return 9999


def get_cached(key: str):
    """Cache'ten veri al. Yoksa None don."""
    cache = load_cache()
    return cache.get(key)


async def ensure_cache(max_age_minutes: int = None):
    """Cache yoksa veya eskiyse yenile.
    22.1n-neo: TTL artik config.py'den (CACHE_TTL_HOT_SEC/60). Override ile legacy."""
    if max_age_minutes is None:
        try:
            from config import CACHE_TTL_HOT_SEC
            max_age_minutes = max(10, CACHE_TTL_HOT_SEC // 60)  # min 10 dk
        except Exception:
            max_age_minutes = 60
    age = get_cache_age_minutes()
    if age > max_age_minutes:
        await build_all_caches()


if __name__ == "__main__":
    async def main():
        print("Analytics cache olusturuluyor...")
        cache = await build_all_caches()
        meta = cache.get("_meta", {})
        print(f"Cache olusturuldu: {meta.get('built_at')}")
        for k, v in cache.items():
            if k == "_meta":
                continue
            if isinstance(v, list):
                print(f"  {k}: {len(v)} kayit")
            elif isinstance(v, dict):
                print(f"  {k}: {len(v)} alan")
        from db_pool import close_pool
        await close_pool()

    asyncio.run(main())
