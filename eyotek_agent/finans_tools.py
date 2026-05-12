"""
FermatAI — Finans Tool Fonksiyonlari (22.1n-neo)
=================================================

Bu modul Claude tool-calling icin finans fonksiyonlarini tanimlar.
HER fonksiyon:
  1. is_finans_authorized(phone) kontrolu yapar — Neo degilse REDDET
  2. check_finans_rate_limit(phone) — gunluk limit asimi kontrolu
  3. log_finans_access — basarili/basarisiz audit
  4. Sonucu dict olarak doner (Claude'a JSON serializable)

KULLANIM (Claude tool dispatch):
  from finans_tools import finans_ozet, ogrenci_borc_detay, ...
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional
from loguru import logger

from db_pool import db_fetch, db_fetchrow, db_fetchval, db_execute
from finans_access import (
    is_finans_authorized,
    check_finans_rate_limit,
    log_finans_access,
)


def _latest_sezon_code_simple() -> str:
    """Bugünün tarihine göre aktif sezon kodu — tek doğruluk noktası sinav_takvimi.py."""
    from sinav_takvimi import aktif_sezon
    return aktif_sezon()


def _unauth_response() -> dict:
    """Neo degilse standard hata — 22.1n-neo (iş2): bilgi leak korumali.

    Red mesajinda 'finans/borc/tahsilat' gibi modul iceriginden BAHSETME.
    Saldirgan red'in icerik tipinden sistem yapisini cikarmasin.
    """
    return {
        "error": "ACCESS_DENIED",
        "detay": "Bu islem yetkiniz disindadir.",
        "action": "blocked",
    }


def _dec_to_float(obj):
    """Decimal / date / datetime → JSON uygun tipe donustur."""
    if isinstance(obj, Decimal):
        return float(obj)
    if hasattr(obj, 'isoformat'):
        return obj.isoformat()
    return obj


def _serialize_row(row: dict) -> dict:
    """Row'u JSON-serializable hale getir."""
    return {k: _dec_to_float(v) for k, v in row.items()}


async def _pre_check(phone: str, action: str, target: str) -> Optional[dict]:
    """Her finans tool basinda standard kontrol. None = devam et, dict = hata."""
    if not is_finans_authorized(phone):
        await log_finans_access(phone, f"{action}_blocked", target=target,
                                details="not_neo", success=False)
        return _unauth_response()
    rate_err = await check_finans_rate_limit(phone)
    if rate_err:
        await log_finans_access(phone, f"{action}_rate_limit", target=target,
                                details=rate_err, success=False)
        return {"error": rate_err, "action": "rate_limited"}
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# 1. KURUM GENEL FINANSAL OZET
# ═══════════════════════════════════════════════════════════════════════════════

async def finans_ozet(_caller_phone: str = "") -> dict:
    """Kurum geneli finans ozet: toplam borc, tahsilat, geciken, ogrenci sayisi."""
    err = await _pre_check(_caller_phone, "finans_ozet", "kurum_geneli")
    if err:
        return err

    try:
        # 25.44 (Neo bug 12 May 14:25): sezon HARDCODED kaldırıldı — sinav_takvimi.aktif_sezon
        from sinav_takvimi import aktif_sezon
        _aktif = aktif_sezon()
        row = await db_fetchrow("""
            SELECT
                COUNT(DISTINCT soz_no) FILTER (WHERE kalan_borc > 0) AS borclu_ogrenci,
                COUNT(DISTINCT soz_no) FILTER (WHERE kalan_borc = 0 AND toplam_ucret > 0) AS tamami_odenmis,
                COUNT(DISTINCT soz_no) AS toplam_ogrenci,
                COALESCE(SUM(toplam_ucret), 0) AS kurum_toplam_ucret,
                COALESCE(SUM(toplam_odenen), 0) AS kurum_toplam_tahsilat,
                COALESCE(SUM(kalan_borc), 0) AS kurum_kalan_borc
            FROM student_financial_summary
            WHERE sezon = $1
        """, _aktif)

        # Geciken bilgisi geciken_snapshot'tan (Eyotek canli veri, ay bazli)
        geciken_row = await db_fetchrow("""
            SELECT COUNT(*) AS geciken_ogrenci_sayisi,
                   COALESCE(SUM(borc), 0) AS kurum_geciken_tutar
            FROM geciken_snapshot WHERE sezon = $1
        """, _aktif)

        ozet = dict(row) if row else {}
        if geciken_row:
            ozet["geciken_ogrenci_sayisi"] = geciken_row["geciken_ogrenci_sayisi"]
            ozet["kurum_geciken_tutar"] = geciken_row["kurum_geciken_tutar"]

        result = {
            "basarili": True,
            "sezon": f"{_aktif} (aktif)",
            "ozet": _serialize_row(ozet),
        }

        # Son 30 gun tahsilat — kurum_gelir tablosundan
        son30 = await db_fetchrow("""
            SELECT COUNT(*) AS islem, COALESCE(SUM(tutar), 0) AS toplam
            FROM kurum_gelir
            WHERE kategori='ciro' AND tarih > (CURRENT_DATE - INTERVAL '30 days')
        """)
        if son30:
            result["son_30_gun"] = {
                "islem_sayisi": son30["islem"],
                "toplam_tahsilat": float(son30["toplam"] or 0),
            }

        await log_finans_access(_caller_phone, "finans_ozet", target="kurum_geneli",
                                details=f"borclu={result['ozet'].get('borclu_ogrenci')}",
                                success=True)
        return result
    except Exception as e:
        logger.error(f"finans_ozet hata: {e}")
        return {"error": f"Sorgu hatasi: {e}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 2. OGRENCI BAZLI BORC DETAYI
# ═══════════════════════════════════════════════════════════════════════════════

async def ogrenci_borc_detay(soz_no: int = 0, sezon: str = "", _caller_phone: str = "") -> dict:
    """Tek ogrenci borc dokumanu: taksit listesi, yapilan odemeler, kalan.

    25.44 BUG FIX (Neo 12 May 14:09): sezon HARDCODED '2025.26' idi —
    yeni sezon (2026.27) kayıtları için 'aktif sezonda kayıt yok' fail.
    Şimdi: en yeni snapshot sezonu otomatik bulunur; param ile override edilebilir.
    DB'de YOKSA Eyotek live'dan Financial/overdue-student-payment çekilir.
    """
    err = await _pre_check(_caller_phone, "ogrenci_borc_detay", f"soz_no={soz_no}")
    if err:
        return err

    if not soz_no or int(soz_no) <= 0:
        return {"error": "soz_no zorunlu"}

    try:
        soz_no = int(soz_no)

        # 25.44 fix: sezon dinamik — bu öğrencinin EN YENİ snapshot sezonu
        if not sezon:
            sezon_row = await db_fetchrow("""
                SELECT sezon FROM ogrenci_odeme_snapshot
                WHERE soz_no = $1
                ORDER BY snapshot_date DESC LIMIT 1
            """, soz_no)
            sezon = (sezon_row['sezon'] if sezon_row else None) or _latest_sezon_code_simple()

        ozet = await db_fetchrow("""
            SELECT oos.*,
                   CASE WHEN oos.son_taksit_tarihi < CURRENT_DATE AND oos.kalan > 0
                        THEN (CURRENT_DATE - oos.son_taksit_tarihi) ELSE 0 END AS gecikme_gun
            FROM ogrenci_odeme_snapshot oos
            WHERE oos.soz_no = $1 AND oos.sezon = $2
            ORDER BY oos.snapshot_date DESC LIMIT 1
        """, soz_no, sezon)

        # 25.44 fix: DB'de yoksa Eyotek live'dan çek (yeni kayıt, snapshot henüz yok)
        if not ozet:
            try:
                from eyotek_knowledge.eyotek_planner import execute_query
                live = await execute_query(
                    f"söz no {soz_no} öğrencinin ödeme detayı bu sezonda borç",
                    max_rows=10,
                )
                rows = live.get("rows") or []
                # söz_no eşleşen satır (overdue-student-payment sayfasında soz_no kolonu var)
                match = None
                for r in rows:
                    for v in r.values():
                        if str(soz_no) == str(v).strip():
                            match = r
                            break
                    if match:
                        break
                if match:
                    # Eyotek satırından özet çıkar
                    name = " ".join(str(v) for k, v in match.items()
                                    if any(t in k.lower() for t in ('ad', 'isim'))
                                    and v and str(v).strip()).strip()
                    return {
                        "basarili": True,
                        "kaynak": "eyotek_live",
                        "soz_no": soz_no,
                        "sezon_aranan": sezon,
                        "ogrenci_adi": name or "(isim yok)",
                        "eyotek_satiri": match,
                        "not": (
                            f"Bu öğrenci için DB snapshot henüz yok (yeni kayıt). "
                            f"Eyotek'ten canlı çekildi. Tam taksit detayı için "
                            f"Financial/overdue-student-payment sayfasında manuel bak."
                        ),
                    }
            except Exception as _live_err:
                pass
            return {"error": f"Ogrenci bulunamadi (soz_no={soz_no}, sezon={sezon}). DB snapshot ve Eyotek live ikisi de fail."}

        # Gecmis sezonlardaki kayitlari getir
        sezonlar = await db_fetch("""
            SELECT DISTINCT ON (sezon) sezon, kayit_fiyati, tahsilat, kalan, kayit_tarihi
            FROM ogrenci_odeme_snapshot
            WHERE soz_no = $1
            ORDER BY sezon, snapshot_date DESC
        """, soz_no)

        # Geciken varsa detay — 25.44 fix: sezon dinamik (yukarıda set edildi)
        geciken = await db_fetchrow("""
            SELECT borc, en_son_gort, soz_verme_tarihi, veli_adi, veli_cep, odeme_tipi,
                   GREATEST(0,
                       CURRENT_DATE - COALESCE(soz_verme_tarihi, en_son_gort, CURRENT_DATE)
                   ) AS gecikme_gun_geciken
            FROM geciken_snapshot
            WHERE soz_no = $1 AND sezon = $2
        """, soz_no, sezon)

        result = {
            "basarili": True,
            "ogrenci": _serialize_row(dict(ozet)),
            "gecmis_sezonlar": [_serialize_row(dict(r)) for r in sezonlar],
            "geciken_bilgisi": _serialize_row(dict(geciken)) if geciken else None,
        }
        await log_finans_access(_caller_phone, "ogrenci_borc_detay",
                                target=f"soz_no={soz_no}",
                                details=f"ogrenci={ozet['full_name']}",
                                success=True)
        return result
    except Exception as e:
        logger.error(f"ogrenci_borc_detay hata: {e}")
        return {"error": f"Sorgu hatasi: {e}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 3. GECIKEN ODEMELER LISTESI
# ═══════════════════════════════════════════════════════════════════════════════

async def geciken_odemeler(min_gun: int = 0, limit: int = 50,
                            _caller_phone: str = "") -> dict:
    """N gunden fazla geciken odemeler listesi (en cok gecikene gore siralı)."""
    err = await _pre_check(_caller_phone, "geciken_odemeler", f"min_gun={min_gun}")
    if err:
        return err

    try:
        min_gun = max(0, int(min_gun))
        limit = max(1, min(500, int(limit)))
        # 25.44 (Neo bug 14:25): sezon HARDCODED kaldırıldı
        from sinav_takvimi import aktif_sezon
        rows = await db_fetch(
            f"""SELECT
                    soz_no, full_name, devre, borc AS geciken_tutar,
                    taksit_sayisi AS geciken_taksit_sayisi,
                    COALESCE(soz_verme_tarihi, en_son_gort) AS en_eski_vade,
                    GREATEST(0,
                        CURRENT_DATE - COALESCE(soz_verme_tarihi, en_son_gort, CURRENT_DATE)
                    ) AS max_gecikme_gun,
                    veli_adi, veli_cep, odeme_tipi
                FROM geciken_snapshot
                WHERE sezon = $2
                  AND GREATEST(0,
                      CURRENT_DATE - COALESCE(soz_verme_tarihi, en_son_gort, CURRENT_DATE)
                  ) >= $1
                ORDER BY borc DESC, max_gecikme_gun DESC
                LIMIT {limit}""",
            min_gun, aktif_sezon()
        )
        result = {
            "basarili": True,
            "kayit_sayisi": len(rows),
            "min_gecikme_gun": min_gun,
            "geciken_ogrenciler": [_serialize_row(dict(r)) for r in rows],
        }
        await log_finans_access(_caller_phone, "geciken_odemeler",
                                target=f"min_gun={min_gun}",
                                details=f"sonuc={len(rows)} ogrenci",
                                success=True)
        return result
    except Exception as e:
        logger.error(f"geciken_odemeler hata: {e}")
        return {"error": f"Sorgu hatasi: {e}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 4. AYLIK TAHSILAT TREND (son 12 ay)
# ═══════════════════════════════════════════════════════════════════════════════

async def aylik_tahsilat_trend(ay_sayisi: int = 12, _caller_phone: str = "") -> dict:
    """Son N ay tahsilat trendi — grafik icin zaman serisi."""
    err = await _pre_check(_caller_phone, "aylik_tahsilat_trend", f"ay={ay_sayisi}")
    if err:
        return err

    try:
        n = max(1, min(60, int(ay_sayisi)))
        # 22.1n-neo bugfix: kurum_gelir tablosu (Bilanco'dan gelen aylik ciro)
        # payments bos — simdilik aylik tahsilat bilanco'daki 'ciro' kolondan
        rows = await db_fetch(
            f"""SELECT
                    TO_CHAR(tarih, 'YYYY-MM') AS ay,
                    COUNT(*) AS islem_sayisi,
                    SUM(tutar) AS tahsilat,
                    AVG(tutar)::numeric(12,2) AS ortalama
                FROM kurum_gelir
                WHERE kategori = 'ciro'
                  AND tarih > (CURRENT_DATE - INTERVAL '{n} months')
                GROUP BY TO_CHAR(tarih, 'YYYY-MM')
                ORDER BY ay"""
        )
        result = {
            "basarili": True,
            "ay_sayisi": n,
            "aylik_trend": [_serialize_row(dict(r)) for r in rows],
        }
        await log_finans_access(_caller_phone, "aylik_tahsilat_trend",
                                target=f"ay={n}", details=f"kayit={len(rows)}",
                                success=True)
        return result
    except Exception as e:
        return {"error": f"Sorgu hatasi: {e}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 5. VELI BORC HATIRLATMA — TASLAK (DRAFT ONLY, gonderilmez)
# ═══════════════════════════════════════════════════════════════════════════════

async def veli_borc_bildirim_taslak(soz_no: int = 0, mesaj_tipi: str = "nazik",
                                      _caller_phone: str = "") -> dict:
    """Veli icin borc hatirlatma mesaj taslagi uret — GONDERMEZ, Neo'ya gosterir.

    mesaj_tipi: nazik / resmi / son_uyari
    """
    err = await _pre_check(_caller_phone, "veli_borc_bildirim_taslak", f"soz_no={soz_no}")
    if err:
        return err

    if not soz_no:
        return {"error": "soz_no zorunlu"}

    try:
        soz_no = int(soz_no)
        ogr = await db_fetchrow(
            "SELECT * FROM student_financial_summary WHERE soz_no = $1",
            soz_no
        )
        if not ogr:
            return {"error": "Ogrenci bulunamadi"}
        if not ogr["kalan_borc"] or float(ogr["kalan_borc"]) <= 0:
            return {"error": "Bu ogrencinin kalan borcu yok"}

        # Veli telefonu — students tablosundan
        veli = await db_fetchrow(
            """SELECT veliCep, anneCep, babaCep, veli_adi, anne_adi, baba_adi
               FROM students WHERE soz_no = $1""",
            str(soz_no)
        )
        veli_tel = ""
        veli_isim = ""
        if veli:
            veli_tel = veli["velicep"] or veli["annecep"] or veli["babacep"] or ""
            veli_isim = veli["veli_adi"] or veli["anne_adi"] or veli["baba_adi"] or "Sayin Veli"

        isim = ogr["full_name"]
        sinif = ogr["class_name"] or ""
        borc = float(ogr["kalan_borc"])
        geciken = float(ogr["geciken_tutar"] or 0)

        if mesaj_tipi == "nazik":
            draft = (
                f"Sayin {veli_isim},\n\n"
                f"{isim} ({sinif}) ogrencimizin aylik odemeleri ile ilgili sizi "
                f"bilgilendirmek istedik. Son durum:\n\n"
                f"  Kalan bakiye: {borc:,.2f} TL\n"
                + (f"  Geciken tutar: {geciken:,.2f} TL\n" if geciken > 0 else "")
                + "\nOdemenizi en kisa surede yapabilirseniz sevinirim. "
                "Sorulariniz icin kurumumuzu arayabilirsiniz.\n\n"
                "Iyi gunler.\nFermat Egitim Kurumlari"
            )
        elif mesaj_tipi == "resmi":
            draft = (
                f"Sayin {veli_isim},\n\n"
                f"{isim} adli ogrencimizin kurumumuzdaki bakiyesi asagidaki gibidir:\n\n"
                f"Toplam bakiye: {borc:,.2f} TL\n"
                f"Geciken: {geciken:,.2f} TL\n\n"
                "Odemeniz icin kurumumuza muhasebe birimine ulasabilirsiniz.\n\n"
                "Saygilarimla,\nFermat Egitim Kurumlari Muhasebe"
            )
        else:  # son_uyari
            draft = (
                f"Sayin {veli_isim},\n\n"
                f"{isim} ogrencimizin gecmis donem bakiyesi hala odenmemistir.\n"
                f"Geciken tutar: {geciken:,.2f} TL\n\n"
                "Odeme yapmanizi rica eder, aksi halde gorusmemiz gerekecegini "
                "belirtmek isteriz.\n\n"
                "Fermat Egitim Kurumlari"
            )

        # DB'ye taslak kaydet (gonderilmedi)
        draft_id = await db_fetchval(
            """INSERT INTO veli_iletisim (soz_no, veli_tel, iletisim_tipi,
                                           mesaj_icerik, mesaj_tipi, status)
               VALUES ($1, $2, $3, $4, $5, 'draft')
               RETURNING id""",
            soz_no, veli_tel, "veli", draft, f"odeme_hatirlatma_{mesaj_tipi}"
        )
        await log_finans_access(_caller_phone, "veli_borc_taslak",
                                target=f"soz_no={soz_no}",
                                details=f"draft_id={draft_id} tip={mesaj_tipi}",
                                success=True)

        return {
            "basarili": True,
            "ogrenci": isim,
            "veli_adi": veli_isim,
            "veli_tel": (veli_tel[-4:] if veli_tel else "") + "****",  # son 4 hane goster
            "kalan_borc": borc,
            "geciken_tutar": geciken,
            "mesaj_tipi": mesaj_tipi,
            "mesaj_taslagi": draft,
            "taslak_id": draft_id,
            "durum": "DRAFT — gonderilmedi. Onaylamak icin /finans/onay/{draft_id}",
            "uyari": (
                "Mesaj TASLAK halinde. Gondermek icin Neo'nun EXPLICIT onayi "
                "ve veli_borc_bildirim_gonder tool cagrisi gerekli."
            ),
        }
    except Exception as e:
        logger.error(f"veli_borc_bildirim_taslak hata: {e}")
        return {"error": f"Taslak olusturulamadi: {e}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 6. FINANS AUDIT RAPORU
# ═══════════════════════════════════════════════════════════════════════════════

async def finans_audit_rapor(saat: int = 24, _caller_phone: str = "") -> dict:
    """Son N saat finans audit log — olagandisi erisim tespiti."""
    err = await _pre_check(_caller_phone, "finans_audit_rapor", f"saat={saat}")
    if err:
        return err

    try:
        from finans_access import get_finans_audit_recent
        audit = await get_finans_audit_recent(hours=int(saat), limit=100)

        # Basarili vs blocked
        basarili = sum(1 for a in audit if a.get("success"))
        bloklanan = sum(1 for a in audit if not a.get("success"))

        return {
            "basarili": True,
            "saat": int(saat),
            "toplam_erisim": len(audit),
            "basarili_sorgu": basarili,
            "bloklanan_sorgu": bloklanan,
            "kayitlar": [_serialize_row(a) for a in audit[:30]],  # son 30 detay
        }
    except Exception as e:
        return {"error": f"Audit rapor hatasi: {e}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 7. SEZON KIYASLAMA — 3 SEZON TREND (NEO STRATEJIK ANALIZ)
# ═══════════════════════════════════════════════════════════════════════════════

async def sezon_kiyasla(_caller_phone: str = "") -> dict:
    """3 sezon (2024.25 / 2025.26 / 2026.27) karsilastirma — Neo stratejik analiz."""
    err = await _pre_check(_caller_phone, "sezon_kiyasla", "3_sezon_kiyaslama")
    if err:
        return err
    try:
        rows = await db_fetch("SELECT * FROM sezon_finans_ozet ORDER BY sezon")
        if not rows:
            return {"error": "Sezon verisi yok — 'finans sync' ile yukle."}

        sezonlar = [_serialize_row(dict(r)) for r in rows]
        # Buyume oranlari
        buyume = []
        for i in range(1, len(sezonlar)):
            prev = sezonlar[i-1]
            cur = sezonlar[i]
            prev_kayit = prev.get("toplam_kayit_fiyati", 0) or 0
            cur_kayit = cur.get("toplam_kayit_fiyati", 0) or 0
            if prev_kayit > 0:
                buyume.append({
                    "donem": f"{prev['sezon']} → {cur['sezon']}",
                    "kayit_buyume_pct": round(100*(cur_kayit - prev_kayit)/prev_kayit, 1),
                    "kayit_fark_tl": round(cur_kayit - prev_kayit, 2),
                    "ogrenci_fark": cur.get("ogrenci_sayisi", 0) - prev.get("ogrenci_sayisi", 0),
                    "ort_fiyat_fark": round(
                        (cur.get("ort_kayit_fiyati", 0) or 0) -
                        (prev.get("ort_kayit_fiyati", 0) or 0), 2
                    ),
                })

        await log_finans_access(_caller_phone, "sezon_kiyasla",
                                target="3_sezon", details=f"sezon_sayisi={len(sezonlar)}",
                                success=True)
        return {
            "basarili": True,
            "sezon_sayisi": len(sezonlar),
            "sezonlar": sezonlar,
            "buyume_analizi": buyume,
        }
    except Exception as e:
        return {"error": f"Sezon kiyas hatasi: {e}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 8. AY BAZLI GECIKEN DETAY
# ═══════════════════════════════════════════════════════════════════════════════

async def aylik_borc_detay(ay: str = "", _caller_phone: str = "") -> dict:
    """Aylik borc/geciken detay.

    Args:
        ay: 'YYYY-MM' format (ornek '2025-11'). Bos ise tum aylar.
    """
    err = await _pre_check(_caller_phone, "aylik_borc_detay", f"ay={ay}")
    if err:
        return err
    try:
        # 25.44 (Neo bug 14:25): sezon HARDCODED kaldırıldı
        from sinav_takvimi import aktif_sezon
        if ay:
            rows = await db_fetch(
                "SELECT * FROM geciken_ay_bazli WHERE ay = $1",
                ay
            )
            # Detay: ogrenci bazli
            detay = await db_fetch(
                """SELECT soz_no, full_name, devre, borc, veli_adi, veli_cep,
                          odeme_tipi, en_son_gort, soz_verme_tarihi
                   FROM geciken_snapshot
                   WHERE sezon = $2
                     AND TO_CHAR(COALESCE(en_son_gort, soz_verme_tarihi, CURRENT_DATE), 'YYYY-MM') = $1
                   ORDER BY borc DESC""",
                ay, aktif_sezon()
            )
        else:
            rows = await db_fetch("SELECT * FROM geciken_ay_bazli")
            detay = []

        await log_finans_access(_caller_phone, "aylik_borc_detay",
                                target=f"ay={ay}", details=f"kayit={len(rows)}",
                                success=True)
        return {
            "basarili": True,
            "ay_filtresi": ay or "tum_aylar",
            "aylik_ozet": [_serialize_row(dict(r)) for r in rows],
            "ogrenci_detay": [_serialize_row(dict(r)) for r in detay],
        }
    except Exception as e:
        return {"error": f"Aylik borc hatasi: {e}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 9. OGRENCI SEZON GECMISI — Tek ogrenci 3 sezon trend
# ═══════════════════════════════════════════════════════════════════════════════

async def ogrenci_sezon_gecmisi(soz_no: int = 0, _caller_phone: str = "") -> dict:
    """Bir ogrencinin 3 sezonluk finansal gecmisi."""
    err = await _pre_check(_caller_phone, "ogrenci_sezon_gecmisi", f"soz_no={soz_no}")
    if err:
        return err
    if not soz_no:
        return {"error": "soz_no zorunlu"}
    try:
        rows = await db_fetch(
            """SELECT sezon, full_name, devre, kayit_tarihi, kayit_fiyati,
                      taksit_toplam, tahsilat, kalan, egitim_destek
               FROM ogrenci_odeme_snapshot
               WHERE soz_no = $1 ORDER BY sezon""",
            int(soz_no)
        )
        if not rows:
            # TC Kimlik ile de arama — eski sezonda soz_no degismis olabilir
            rows = await db_fetch(
                """SELECT DISTINCT ON (sezon) sezon, full_name, devre,
                          kayit_tarihi, kayit_fiyati, taksit_toplam, tahsilat, kalan
                   FROM ogrenci_odeme_snapshot
                   WHERE soz_no = $1 ORDER BY sezon""",
                int(soz_no)
            )
        return {
            "basarili": True,
            "soz_no": soz_no,
            "sezon_gecmisi": [_serialize_row(dict(r)) for r in rows],
            "sezon_sayisi": len(rows),
        }
    except Exception as e:
        return {"error": f"Sezon gecmisi hatasi: {e}"}


__all__ = [
    "finans_ozet",
    "ogrenci_borc_detay",
    "geciken_odemeler",
    "aylik_tahsilat_trend",
    "veli_borc_bildirim_taslak",
    "finans_audit_rapor",
    "sezon_kiyasla",          # 22.1n-neo
    "aylik_borc_detay",       # 22.1n-neo
    "ogrenci_sezon_gecmisi",  # 22.1n-neo
]
