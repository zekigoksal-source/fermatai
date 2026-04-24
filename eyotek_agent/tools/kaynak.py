"""
Kaynak/Medya Tool Wrapper'ları
===============================
YouTube, Wikipedia, OGM, Google Calendar, Career bilgi, Pedagojik şablon.

Oturum 23 Neo kuralı:
  - youtube_oner SADECE whitelist kanallardan
  - konu_kaynak_paketi öğrenci EXPLICIT talep ederse (diyalog varsayılan)
"""
from __future__ import annotations


# ─── YouTube (whitelist-only) ─────────────────────────────────────────
async def _tool_youtube_oner(**kwargs):
    from external_apis import youtube_search
    return {"videolar": await youtube_search(kwargs.get("konu") or "", max_results=3)}


# ─── Konu Kaynak Paketi (OGM + YouTube + Wikipedia + RAG) ─────────────
async def _tool_konu_kaynak_paketi(**kwargs):
    """Öğrenci EXPLICIT olarak kaynak/video/farklı anlatım istediğinde çağrılır.

    Diyalog varsayılan — bu tool sadece 'video izlemek istiyorum', 'başka kaynak?',
    'farklı yerden bakmak istiyorum', 'nereden çalışayım' gibi direkt talep.
    """
    from konu_kaynak_paketi import konu_kaynak_paketi
    return await konu_kaynak_paketi(
        konu=kwargs.get("konu") or "",
        ders=kwargs.get("ders") or "",
        youtube_adet=int(kwargs.get("youtube_adet") or 4),
        wikipedia_adet=int(kwargs.get("wikipedia_adet") or 2),
    )


# ─── Google Calendar — Çalışma Planı ──────────────────────────────────
async def _tool_plani_takvime_ekle(**kwargs):
    """Çalışma planını Google Calendar'a event dizisi + WP link'leri.

    23 Nisan yeni mimari (Neo vizyonu): Email YOK, WP link yeterli.
    Her event için quick-add URL üretiliyor — öğrenci tıklar, tek tıkla
    kendi Gmail takvimine ekler.
    """
    from external_apis import gcal_create_study_plan, gcal_quick_add_link
    soz_no = int(kwargs.get("soz_no") or 0)
    ogrenci_ad = kwargs.get("ogrenci_ad") or ""
    plan_events = kwargs.get("plan_events") or []

    # Merkezi takvime yaz (KVKK filter ile, Neo + admin görsün)
    created = await gcal_create_study_plan(soz_no, ogrenci_ad, plan_events, ogrenci_email="")

    # Her event için öğrenciye özel "kendi takvimine ekle" linki
    student_links = []
    for ev in plan_events:
        summary = f"📚 Çalışma · {ev.get('ders', '')}"
        desc = f"Konu: {ev.get('konu', '')}\n{ev.get('aciklama', '')}"
        link = gcal_quick_add_link(
            summary, ev["tarih_iso"], ev.get("sure_dk", 60), desc
        )
        if link:
            student_links.append({
                "tarih": ev["tarih_iso"][:10],
                "saat": ev["tarih_iso"][11:16],
                "ders": ev.get("ders"),
                "konu": ev.get("konu", ""),
                "link": link,
            })

    return {
        "olusturulan_event_sayisi": len(created),
        "toplam_planlanan": len(plan_events),
        "ogrenci_linkleri": student_links,
        "not": (
            "Her event için öğrenciye özel link üretildi. WP mesajında bu linkleri "
            "ver — öğrenci tek tıkla kendi Gmail takvimine ekleyebilir. Email gerekmez."
        ),
    }


# ─── Google Calendar — Etüt ───────────────────────────────────────────
async def _tool_etut_takvime_ekle(**kwargs):
    """Etüt → Merkezi takvime + öğrenciye WP link (kendi takvimine için).

    REHBER ÖĞRETMEN tool'u. Branş öğretmeni çağıramaz (Oturum 23 yetki ayrımı).
    """
    from external_apis import gcal_create_etut, gcal_quick_add_link
    soz_no = int(kwargs.get("ogrenci_soz_no") or 0)
    ogretmen = kwargs.get("ogretmen_ad") or ""
    ders = kwargs.get("ders") or ""
    konu = kwargs.get("konu") or ""
    tarih_iso = kwargs.get("tarih_iso") or ""
    sure = int(kwargs.get("sure_dk") or 45)

    # Merkezi takvim (email'siz)
    r = await gcal_create_etut(
        ogrenci_ad=kwargs.get("ogrenci_ad") or "",
        ogretmen_ad=ogretmen,
        ders=ders, konu=konu, tarih_iso=tarih_iso,
        sure_dk=sure, ogrenci_soz_no=soz_no,
    )

    # Öğrenci ve öğretmen için ayrı quick-add linkleri
    ogrenci_link = gcal_quick_add_link(
        f"📝 Etüt · {ders} · {ogretmen} Hoca",
        tarih_iso, sure,
        f"Konu: {konu}\nÖğretmen: {ogretmen}\nSüre: {sure} dk\n\nFermatAI etüt"
    )
    ogretmen_link = gcal_quick_add_link(
        f"👨‍🏫 Etüt · {ders} · Öğrenci",
        tarih_iso, sure,
        f"Konu: {konu}\nDers: {ders}\nSüre: {sure} dk\n\nFermatAI etüt"
    )

    return {
        "success": bool(r),
        "event_id": r.get("id") if r else None,
        "merkezi_link": r.get("htmlLink") if r else None,
        "ogrenci_takvim_linki": ogrenci_link,
        "ogretmen_takvim_linki": ogretmen_link,
        "not": "Öğrenciye WP'den 'ogrenci_takvim_linki' gönder, tek tıkla kendi takvimine eklesin.",
    }


# ─── Career Info (13 meslek/bölüm) ────────────────────────────────────
async def _tool_get_career_info(**kwargs):
    """13+ meslek/bölüm için hazır tanıtım. Hızlı ve token-tasarruflu."""
    from career_info import get_career_info
    return await get_career_info(kwargs.get("meslek") or "")


# ─── Pedagojik Şablon ─────────────────────────────────────────────────
async def _tool_get_pedagojik_sablon(**kwargs):
    """Claude talep ederse pedagojik şablon kütüphanesinden getir.

    Kategoriler: SINAV_YAKIN, DENEME_SONRASI, HEDEF_BELIRLEME,
    CALISMA_PLANI_FEEDBACK, VELI_ILETISIM, KONU_GERI_BILDIRIM,
    OGRETMEN_YONLENDIRME, ZAMAN_YONETIMI_KRIZ, DERS_CAKISMA_COZUM, KRIZ_DESTEK
    """
    from pedagojik_sablonlar import list_by_kategori
    kategori = (kwargs.get("kategori") or "").strip().upper()
    rol = (kwargs.get("rol") or "ogrenci").strip().lower()
    if not kategori:
        return {"error": "kategori gerekli", "oneri": "Orn: SINAV_YAKIN, KRIZ_DESTEK, DENEME_SONRASI"}
    try:
        tpls = await list_by_kategori(kategori, rol=rol)
        if not tpls:
            return {
                "kategori": kategori,
                "rol": rol,
                "sablonlar": [],
                "bilgi": "Bu kategori/rol icin sablon bulunamadi. "
                         "Kategoriler: SINAV_YAKIN, DENEME_SONRASI, HEDEF_BELIRLEME, "
                         "CALISMA_PLANI_FEEDBACK, VELI_ILETISIM, KONU_GERI_BILDIRIM, "
                         "OGRETMEN_YONLENDIRME, ZAMAN_YONETIMI_KRIZ, DERS_CAKISMA_COZUM, KRIZ_DESTEK",
            }
        return {
            "kategori": kategori,
            "rol": rol,
            "sablonlar": [
                {
                    "slug": t.get("slug"),
                    "alt_tip": t.get("alt_tip"),
                    "metin": (t.get("sablon_metin") or "")[:500],
                    "uygulama_notu": (t.get("uygulama_notu") or "")[:160],
                }
                for t in tpls[:3]
            ],
        }
    except Exception as e:
        return {"error": str(e)}


__all__ = [
    "_tool_youtube_oner",
    "_tool_konu_kaynak_paketi",
    "_tool_plani_takvime_ekle",
    "_tool_etut_takvime_ekle",
    "_tool_get_career_info",
    "_tool_get_pedagojik_sablon",
]
