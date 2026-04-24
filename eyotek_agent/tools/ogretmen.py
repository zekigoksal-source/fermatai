"""
Öğretmen Tool Wrapper'ları
===========================
Branş öğretmeni etüt yazma yetkisi YOK (Oturum 23 Neo kararı).
Bu modül:
  - ogretmen_etut_takvimim  → kendi etut takvimi (READ-ONLY + quick-add link)
  - ogretmen_etut_onerisi   → rehbere tavsiye gönder
  - ogretmen_brief          → sınıf performans brief (rehber için özel dallanır)
  - ogretmen_pedagojik_brief → pedagojik değerlendirme (22.1n-neo)
  - odev_ekle               → ödev ekleme
"""
from __future__ import annotations


async def _tool_ogretmen_etut_takvimim(**kwargs):
    """Öğretmenin KENDİ etut takvimini listele + Google Calendar quick-add linkleri.

    Branş öğretmeni Eyotek'te etut yazmaz ama kendi takvimine ekleyebilir.
    teacher_timetable + etut_history'den kendi kayıtlarını çeker.
    """
    from external_apis import gcal_quick_add_link
    from db_pool import db_fetch
    from datetime import datetime, timedelta

    ogretmen_ad = (kwargs.get("ogretmen_ad") or "").strip()
    gun_sayisi = int(kwargs.get("gun") or 7)

    if not ogretmen_ad:
        return {"error": "ogretmen_ad parametresi gerekli"}

    # Son N gün + gelecek N gün etutler
    today = datetime.now().date()
    start_date = today - timedelta(days=1)
    end_date = today + timedelta(days=gun_sayisi)

    # etut_history'den kendi etutlerini çek
    try:
        rows = await db_fetch("""
            SELECT tarih, saat, ders, konu, ogrenci_ad, derslik, sinif_ad
            FROM fermat.etut_history
            WHERE ogretmen_ad ILIKE $1
              AND tarih BETWEEN $2 AND $3
            ORDER BY tarih, saat
            LIMIT 50
        """, f"%{ogretmen_ad}%", start_date, end_date)
    except Exception:
        # tarih sütunu yok veya farklı ad — fallback
        try:
            rows = await db_fetch("""
                SELECT tarih, saat, ders, konu, ogrenci_ad, derslik
                FROM fermat.etut_history
                WHERE ogretmen_ad ILIKE $1
                ORDER BY tarih DESC
                LIMIT 20
            """, f"%{ogretmen_ad}%")
        except Exception:
            rows = []

    etutler = []
    for r in rows:
        # Quick-add link üret — öğretmen kendi Gmail takvimine ekleyebilsin
        tarih_str = str(r.get("tarih") or "")
        saat_str = str(r.get("saat") or "09:00")
        # ISO format
        try:
            tarih_iso = f"{tarih_str}T{saat_str.zfill(5)}:00"
            link = gcal_quick_add_link(
                f"📝 Etüt · {r.get('ders', '')} · {r.get('ogrenci_ad', 'Öğrenci')}",
                tarih_iso,
                45,
                f"Konu: {r.get('konu', '')}\nÖğrenci: {r.get('ogrenci_ad', '')}\nDerslik: {r.get('derslik', '')}\n\nFermatAI etüt"
            )
        except Exception:
            link = None

        etutler.append({
            "tarih": tarih_str,
            "saat": saat_str,
            "ders": r.get("ders"),
            "konu": r.get("konu") or "-",
            "ogrenci": r.get("ogrenci_ad"),
            "derslik": r.get("derslik") or "",
            "takvim_linki": link,
        })

    return {
        "ogretmen": ogretmen_ad,
        "toplam": len(etutler),
        "etutler": etutler,
        "not": (
            "Her etut için quick-add linki üretildi. Öğretmen linke tıklayınca "
            "kendi Gmail takvimine ekleyebilir. Etüt yazma yetkisi rehber öğretmende."
        ),
    }


async def _tool_ogretmen_etut_onerisi(**kwargs):
    """Branş öğretmeni → rehbere etut tavsiyesi gönderir.

    Rehber günlük/haftalık brief'te bu önerileri görür ve uygun bulursa
    Eyotek'te gerçek etutu YAZAR.
    """
    from db_pool import db_fetchval

    ogretmen_ad = (kwargs.get("ogretmen_ad") or "").strip()
    soz_no = int(kwargs.get("soz_no") or 0)
    ogrenci_ad = (kwargs.get("ogrenci_ad") or "").strip()
    ders = (kwargs.get("ders") or "").strip()
    konu = (kwargs.get("konu") or "").strip()
    aciklama = (kwargs.get("aciklama") or kwargs.get("gerekce") or "").strip()
    oncelik = (kwargs.get("oncelik") or "normal").strip().lower()  # dusuk/normal/yuksek/acil
    onerilen_gun = kwargs.get("onerilen_gun") or ""  # örn "persembe 14:00" serbest metin

    if not ogretmen_ad or not ders or (not soz_no and not ogrenci_ad):
        return {"error": "ogretmen_ad, ders ve (soz_no veya ogrenci_ad) zorunlu"}

    if oncelik not in ("dusuk", "normal", "yuksek", "acil"):
        oncelik = "normal"

    try:
        oid = await db_fetchval("""
            INSERT INTO fermat.teacher_etut_onerileri
                (ogretmen_ad, soz_no, ogrenci_ad, ders, konu, aciklama, oncelik,
                 onerilen_gun, durum, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'bekliyor', NOW())
            RETURNING id
        """, ogretmen_ad, soz_no or None, ogrenci_ad, ders, konu, aciklama, oncelik, onerilen_gun)
    except Exception as e:
        return {"error": f"Kayıt yapılamadı: {e}"}

    return {
        "success": True,
        "oneri_id": oid,
        "durum": "bekliyor",
        "not": (
            f"Öneriniz rehber öğretmene iletildi (ID #{oid}). "
            "Rehber bir sonraki brief'inde görür ve uygun görürse Eyotek'te etutu yazar. "
            "Oturumda sorun çıkarsa rehbere doğrudan WP mesajı atabilirsiniz."
        ),
    }


async def _tool_ogretmen_brief(**kwargs):
    """Öğretmen/rehber brief.

    23 Nisan: Rehber role için bekleyen branş öğretmeni etut önerilerini ayrı göster.
    Parametre olarak 'role' gelirse ona göre branşlanır.
    """
    role = (kwargs.get("role") or "").strip().lower()
    ogretmen_ad = kwargs.get("ogretmen_ad") or ""
    if role == "rehber":
        from teacher_copilot import build_rehber_brief
        return {"brief": await build_rehber_brief(ogretmen_ad)}
    from teacher_copilot import build_brief
    return {"brief": await build_brief(ogretmen_ad)}


async def _tool_odev_ekle(**kwargs):
    from odev_scheduler import add_odev
    oid = await add_odev(
        int(kwargs.get("ogrenci_soz_no") or 0),
        kwargs.get("odev_tanim") or "",
        kwargs.get("ders") or "",
        kwargs.get("konu") or "",
        int(kwargs.get("teslim_gun_sonra") or 1),
        kwargs.get("ogretmen_ad") or "",
    )
    return {"success": oid > 0, "odev_id": oid}


async def _tool_ogretmen_pedagojik_brief(**kwargs):
    """22.1n-neo FAZ 2 EKSTRA — Öğretmen için pedagojik gelişim değerlendirmesi."""
    from ucgen_model import build_ogretmen_brief
    return await build_ogretmen_brief(int(kwargs.get("soz_no") or 0))


async def _tool_veli_pedagojik_rehberlik(**kwargs):
    """22.1n-neo FAZ 2 EKSTRA — Veli için pedagojik rehberlik."""
    from ucgen_model import build_veli_rehberlik
    return await build_veli_rehberlik(
        int(kwargs.get("soz_no") or 0),
        kwargs.get("tema") or "genel",
    )


async def _tool_deep_research_paket(**kwargs):
    """23 Nisan Jarvis paket — deep research kombinasyonu."""
    from deep_research import deep_study_package
    soz = int(kwargs.get("soz_no") or 0)
    konu = kwargs.get("konu") or ""
    ders = kwargs.get("ders") or ""
    return await deep_study_package(soz, konu, ders)


__all__ = [
    "_tool_ogretmen_etut_takvimim",
    "_tool_ogretmen_etut_onerisi",
    "_tool_ogretmen_brief",
    "_tool_odev_ekle",
    "_tool_ogretmen_pedagojik_brief",
    "_tool_veli_pedagojik_rehberlik",
    "_tool_deep_research_paket",
]
