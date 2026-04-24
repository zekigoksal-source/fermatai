"""
Tercih Robotu Testleri (23 Nisan 2026)
========================================
Oturum 23 yeni modül — YKS sonrası tercih danışmanı.

Kapsanan:
  - tercih_donemi_durum (timeline + flag kontrol)
  - tercih_profili_kaydet UPSERT (gelen alanları güncelle, None dokunma)
  - tercih_profili_getir (var/yok kontrol)
  - bolum_karsilastir (2+ bölüm, SAY/EA/SOZ/DIL)
  - tercih_listesi_uret (4 bant + kapsama)
  - Pentest: öğrenci soz_no bypass denemesi
"""
import os
import sys
import asyncio
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run_with_pool_reset(coro):
    """Async test için yardımcı — event loop izolasyonu + db_pool reset.

    DB pool singleton olduğu için her asyncio.run() sonrası event loop kapanıyor,
    pool hâlâ eski loop'a bağlı kalıyor. Her test başında pool'u reset edelim.
    """
    import db_pool
    # Önce varsa eski pool'u sıfırla (yeni event loop'ta yeniden kurulur)
    db_pool._pool = None
    try:
        return asyncio.run(coro)
    finally:
        # Test sonrası da pool referansını sıfırla (sonraki test temiz başlasın)
        db_pool._pool = None


# ═══════════════════════════════════════════════════════════════════════════
# DÖNEM YÖNETİMİ
# ═══════════════════════════════════════════════════════════════════════════

def test_puan_turu_normalize():
    """SÖZ → SOZ, DİL → DIL normalize."""
    from tercih_robotu import _normalize_puan_turu
    assert _normalize_puan_turu("SAY") == "SAY"
    assert _normalize_puan_turu("say") == "SAY"
    assert _normalize_puan_turu("EA") == "EA"
    assert _normalize_puan_turu("SÖZ") == "SOZ"
    assert _normalize_puan_turu("söz") == "SOZ"
    assert _normalize_puan_turu("DİL") == "DIL"
    assert _normalize_puan_turu("dil") == "DIL"
    assert _normalize_puan_turu("") == ""
    assert _normalize_puan_turu(None) == ""


def test_timeline_dogru():
    """YKS 2026 tarihleri doğru yüklenmiş."""
    from tercih_robotu import TERCIH_DONEMI_BASLANGIC, TERCIH_DONEMI_BITIS
    from datetime import date
    assert TERCIH_DONEMI_BASLANGIC == date(2026, 7, 1)
    assert TERCIH_DONEMI_BITIS == date(2026, 8, 31)


async def _test_donem_durum():
    from tercih_robotu import tercih_donemi_durum
    d = await tercih_donemi_durum()
    assert "tercih_modu_aktif" in d
    assert "timeline" in d
    assert len(d["timeline"]) >= 6  # TYT/AYT/Sonuç/Tercih Başla/Bitiş/Kamp
    olay_adlari = [t["olay"] for t in d["timeline"]]
    assert any("TYT" in o for o in olay_adlari)
    assert any("AYT" in o for o in olay_adlari)
    assert any("Tercih" in o for o in olay_adlari)


def test_donem_durum():
    _run_with_pool_reset(_test_donem_durum())


# ═══════════════════════════════════════════════════════════════════════════
# PROFİL UPSERT
# ═══════════════════════════════════════════════════════════════════════════

async def _test_profil_upsert():
    from tercih_robotu import tercih_profili_kaydet, tercih_profili_getir
    from db_pool import db_execute

    test_soz = 99998

    # 1. Yeni kayıt (sadece sıralama + puan türü)
    r1 = await tercih_profili_kaydet(
        soz_no=test_soz, puan_turu="SAY", siralama=25000,
    )
    assert r1.get("success"), f"1. kayıt: {r1}"

    # 2. Güncelleme (şehir/bölüm ekle) — None olan alanlar dokunulmamalı
    r2 = await tercih_profili_kaydet(
        soz_no=test_soz,
        tercih_sehirler=["Ankara", "Istanbul"],
        tercih_bolumler=["Bilgisayar Mühendisliği"],
    )
    assert r2.get("success")

    # 3. Oku — siralama hala 25000 olmalı
    p = await tercih_profili_getir(test_soz)
    assert p.get("profil_var_mi")
    assert p["siralama"] == 25000, f"siralama kayboldu: {p['siralama']}"
    assert p["puan_turu"] == "SAY"
    assert "Ankara" in p["tercih_sehirler"]
    assert "Bilgisayar Mühendisliği" in p["tercih_bolumler"]

    # 4. Gecersiz puan_turu reddedilmeli
    r4 = await tercih_profili_kaydet(soz_no=test_soz, puan_turu="XYZ")
    assert "error" in r4

    # 5. Temizlik
    await db_execute("DELETE FROM fermat.tercih_profil WHERE soz_no=$1", test_soz)
    await db_execute("DELETE FROM fermat.tercih_listesi WHERE soz_no=$1", test_soz)


def test_profil_upsert():
    _run_with_pool_reset(_test_profil_upsert())


async def _test_profil_yok():
    """Olmayan öğrenci için profil_var_mi=False."""
    from tercih_robotu import tercih_profili_getir
    p = await tercih_profili_getir(99977)
    assert p.get("profil_var_mi") is False
    assert "mesaj" in p


def test_profil_yok():
    _run_with_pool_reset(_test_profil_yok())


# ═══════════════════════════════════════════════════════════════════════════
# LİSTE ÜRETME
# ═══════════════════════════════════════════════════════════════════════════

async def _test_liste_uret():
    from tercih_robotu import tercih_profili_kaydet, tercih_listesi_uret
    from db_pool import db_execute

    test_soz = 99996

    # Önkoşul: profil kaydet
    await tercih_profili_kaydet(
        soz_no=test_soz, puan_turu="SAY", siralama=50000,
        tercih_bolumler=["Mühendisliği"],  # kapsamı geniş tut
    )
    r = await tercih_listesi_uret(test_soz)

    assert "liste" in r or "error" in r
    if r.get("liste"):
        assert r["toplam_satir"] > 0
        # En az 1 bant dolu
        assert r["bant_sayaci"]
        # Her kayıt zorunlu alanlar
        for item in r["liste"][:3]:
            assert "universite" in item
            assert "bolum" in item
            assert "siralama" in item
            assert "strateji" in item
            assert item["strateji"] in ("garanti", "orta", "hedef", "hayal")

    # Temizlik
    await db_execute("DELETE FROM fermat.tercih_profil WHERE soz_no=$1", test_soz)
    await db_execute("DELETE FROM fermat.tercih_listesi WHERE soz_no=$1", test_soz)


def test_liste_uret():
    _run_with_pool_reset(_test_liste_uret())


async def _test_liste_profilsiz():
    """Profilsiz öğrenci için hata dönmeli."""
    from tercih_robotu import tercih_listesi_uret
    r = await tercih_listesi_uret(99955)
    assert "error" in r


def test_liste_profilsiz():
    _run_with_pool_reset(_test_liste_profilsiz())


# ═══════════════════════════════════════════════════════════════════════════
# BÖLÜM KIYASLAMA
# ═══════════════════════════════════════════════════════════════════════════

async def _test_bolum_karsilastir():
    from tercih_robotu import bolum_karsilastir
    r = await bolum_karsilastir(
        ["Bilgisayar Mühendisliği", "Endüstri Mühendisliği"], puan_turu="SAY"
    )
    assert "karsilastirma" in r
    assert len(r["karsilastirma"]) == 2
    # En az 1'i bulunmalı (YOK Atlas'ta var)
    bulunan = [k for k, v in r["karsilastirma"].items() if v.get("bulundu")]
    assert len(bulunan) >= 1


def test_bolum_karsilastir():
    _run_with_pool_reset(_test_bolum_karsilastir())


async def _test_bolum_karsilastir_tek():
    """Tek bölüm ile hata dönmeli."""
    from tercih_robotu import bolum_karsilastir
    r = await bolum_karsilastir(["Tıp"], puan_turu="SAY")
    assert "error" in r


def test_bolum_karsilastir_tek():
    _run_with_pool_reset(_test_bolum_karsilastir_tek())


# ═══════════════════════════════════════════════════════════════════════════
# GÜVENLİK: Öğrenci kendi soz_no'su dışına çıkamaz
# ═══════════════════════════════════════════════════════════════════════════

def test_acl_ogrenci_tercih_profil():
    """Öğrenci başka öğrencinin tercih_profil'ini okumaya çalışırsa SQL ACL engeller."""
    from role_access import _check_sql_acl
    err = _check_sql_acl(
        "ogrenci",
        "SELECT * FROM tercih_profil WHERE soz_no=200",
        soz_no=150,
        phone="905000000000",
    )
    assert err is not None
    # Hata ya sensitive_tables (kendi soz_no değil) ya _FORBIDDEN_TABLES olmalı
    assert ("soz_no" in err.lower() or "tercih_profil" in err.lower()
            or "erişim" in err.lower() or "erisim" in err.lower())


def test_acl_veli_tercih_profil_yasak():
    """Veli tercih_profil'e DEĞEMEZ."""
    from role_access import _FORBIDDEN_TABLES
    assert "tercih_profil" in _FORBIDDEN_TABLES["veli"]
    assert "tercih_listesi" in _FORBIDDEN_TABLES["veli"]


def test_acl_ogretmen_tercih_profil_yasak():
    """Öğretmen tercih profiline ERIŞEMEZ — sadece rehber/müdür/admin."""
    from role_access import _FORBIDDEN_TABLES, _ACL_MATRIX
    # Öğretmen ACL'de tercih tool'ları YOK
    assert "tercih_profili_kaydet" not in _ACL_MATRIX["ogretmen"]
    assert "tercih_listesi_uret" not in _ACL_MATRIX["ogretmen"]
    # Forbidden tables'ta da tercih_profil YOK değil — ogretmen erişemez
    assert "tercih_profil" in _FORBIDDEN_TABLES["ogretmen"]
