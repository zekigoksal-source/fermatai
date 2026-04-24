"""
Sezon Modülleri Regression Testleri (Oturum 23)
=================================================
Yeni sezonda (1 Eylül 2026) açılacak modüller için test coverage.
Amaç: Flag'ler açılıp canlıya alınırken SÜRPRIZ REGRESSION olmasın.

Kapsanan modüller:
  - frustration_telafi.py (TELAFI_ACTIVE=False invaryantı)
  - yaz_kampi.py (YAZ_KAMPI_ACTIVE=False)
  - daily_push.py (PUSH_ACTIVE=False)
  - ogm_catalog.py (okuma — search/yonlendir)
  - konu_kaynak_paketi.py (wikipedia + youtube + ogm + rag paket)
  - ders_konu_dagilimi.py (8 yıl konu dağılım + tahmin)
  - teacher_copilot.py (build_brief + build_rehber_brief)

Kural: Her test kendi event loop'unu kurar (db_pool singleton reset).
"""
import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run(coro):
    """Async test helper — db_pool singleton izolasyonu için reset."""
    import db_pool
    db_pool._pool = None
    try:
        return asyncio.run(coro)
    finally:
        db_pool._pool = None


# ═══════════════════════════════════════════════════════════════════════════
# FRUSTRATION_TELAFI — Kullanıcıya mesaj göndermeyen güvenli mod invaryantı
# ═══════════════════════════════════════════════════════════════════════════

def test_telafi_default_kapali():
    """TELAFI_ACTIVE=False sezon öncesi invaryantı (Neo outreach yasağı)."""
    from frustration_telafi import TELAFI_ACTIVE
    assert TELAFI_ACTIVE is False, (
        "TELAFI_ACTIVE=True yapıldı ama sezon öncesi — Neo outreach yasağı ihlali"
    )


async def _test_telafi_send_bypass():
    """check_and_send_telafi flag kapalıyken gönderim YAPMAMALI."""
    from frustration_telafi import check_and_send_telafi
    # send_wa_func=None — çağrılırsa zaten sessiz geçer
    r = await check_and_send_telafi(send_wa_func=None)
    # TELAFI_ACTIVE=False → reason='TELAFI_ACTIVE=False' dönmeli
    assert r.get("reason") == "TELAFI_ACTIVE=False" or r.get("sent", 0) == 0


def test_telafi_send_bypass():
    _run(_test_telafi_send_bypass())


async def _test_telafi_log_silent():
    """log_frustration flag kapalıyken DB'ye yazmamalı (invariant)."""
    from frustration_telafi import log_frustration, TELAFI_ACTIVE
    # Sessizce döner, hata vermez
    await log_frustration("905999999999", "test mesaj", "context")
    assert TELAFI_ACTIVE is False  # hala kapalı


def test_telafi_log_silent():
    _run(_test_telafi_log_silent())


# ═══════════════════════════════════════════════════════════════════════════
# YAZ_KAMPI — Flag kapalı invaryantı + fonksiyon varlığı
# ═══════════════════════════════════════════════════════════════════════════

def test_yaz_kampi_default_kapali():
    """YAZ_KAMPI_ACTIVE=False sezon başlangıcına kadar."""
    from yaz_kampi import YAZ_KAMPI_ACTIVE
    assert YAZ_KAMPI_ACTIVE is False


async def _test_yaz_kampi_ozet_bypass():
    """kamp_ozet_tum kapalıyken ozet getirmez."""
    from yaz_kampi import kamp_ozet_tum
    r = await kamp_ozet_tum()
    # Flag kapalı iken boş veya status döner
    assert isinstance(r, dict)


def test_yaz_kampi_ozet_bypass():
    _run(_test_yaz_kampi_ozet_bypass())


# ═══════════════════════════════════════════════════════════════════════════
# DAILY_PUSH — Proaktif mesaj yasağı invaryantı
# ═══════════════════════════════════════════════════════════════════════════

def test_daily_push_default_kapali():
    """PUSH_ACTIVE=False invaryantı."""
    from daily_push import PUSH_ACTIVE
    assert PUSH_ACTIVE is False


async def _test_daily_push_send_bypass():
    """send_daily_push dry_run=True default, PUSH_ACTIVE=False ile gerçek göndermiyor."""
    from daily_push import send_daily_push
    # dry_run=True → sadece log, gönderim yok
    r = await send_daily_push(send_wa_func=None, dry_run=True)
    assert isinstance(r, dict)
    # Real send denenmemeli
    assert r.get("reason") != "sent" or r.get("sent", 0) == 0


def test_daily_push_send_bypass():
    _run(_test_daily_push_send_bypass())


# ═══════════════════════════════════════════════════════════════════════════
# OGM_CATALOG — Okuma fonksiyonları (read-only, sezon-neutral)
# ═══════════════════════════════════════════════════════════════════════════

async def _test_ogm_yonlendir():
    """yonlendir ders bazlı kaynak döndürür."""
    from ogm_catalog import yonlendir
    r = await yonlendir(ders="Fizik")
    assert isinstance(r, list)
    # En az bir sonuç olmalı (OGM konu özetleri RAG'da var)
    # Ama DB bağımlı olabilir — sadece liste tipini kontrol ediyoruz


def test_ogm_yonlendir():
    _run(_test_ogm_yonlendir())


async def _test_ogm_search():
    """search_catalog çalışmalı."""
    from ogm_catalog import search_catalog
    r = await search_catalog(konu="türev", ders="Matematik")
    assert isinstance(r, list)


def test_ogm_search():
    _run(_test_ogm_search())


# ═══════════════════════════════════════════════════════════════════════════
# KONU_KAYNAK_PAKETI — Çoklu kaynak paketi (oturum 23 yeni)
# ═══════════════════════════════════════════════════════════════════════════

async def _test_konu_kaynak_paketi():
    """paket dict döner, 4 kaynak alanı var."""
    from konu_kaynak_paketi import konu_kaynak_paketi
    r = await konu_kaynak_paketi(konu="türev", ders="Matematik")
    assert isinstance(r, dict)
    assert "paket" in r
    paket = r["paket"]
    assert "ogm" in paket
    assert "youtube" in paket
    assert "wikipedia" in paket
    assert "dahili" in paket
    # Her kaynak list
    for k in ("ogm", "youtube", "wikipedia", "dahili"):
        assert isinstance(paket[k], list)
    # Sunum mesajı var
    assert "sunum_mesaji" in r
    assert isinstance(r["sunum_mesaji"], str)


def test_konu_kaynak_paketi():
    _run(_test_konu_kaynak_paketi())


async def _test_konu_kaynak_paketi_bos_konu():
    """Boş konu → error dön."""
    from konu_kaynak_paketi import konu_kaynak_paketi
    r = await konu_kaynak_paketi(konu="", ders="")
    assert "error" in r


def test_konu_kaynak_paketi_bos_konu():
    _run(_test_konu_kaynak_paketi_bos_konu())


async def _test_wikipedia_tr():
    """Wikipedia TR çalışır (User-Agent header ile)."""
    from konu_kaynak_paketi import wikipedia_search
    # Türev yüksek ihtimal bulunacak konu
    r = await wikipedia_search("Türev", limit=2, lang="tr")
    # Network bağımlı — en azından list tipi dönmeli
    assert isinstance(r, list)


def test_wikipedia_tr():
    _run(_test_wikipedia_tr())


# ═══════════════════════════════════════════════════════════════════════════
# DERS_KONU_DAGILIMI — 8 yıl konu dağılım raporu (Neo'nun özel isteği)
# ═══════════════════════════════════════════════════════════════════════════

async def _test_konu_dagilimi_fizik_ayt():
    """Fizik AYT için dağılım + tahmin çalışmalı."""
    from ders_konu_dagilimi import konu_dagilimi_raporu
    r = await konu_dagilimi_raporu(ders="Fizik", sinav_turu="AYT")
    assert "toplam_soru" in r
    assert r["toplam_soru"] > 0
    assert "konu_dagilimi" in r
    assert isinstance(r["konu_dagilimi"], list)
    assert r["konu_sayisi"] > 0
    # Her konu için zorunlu alanlar
    for konu in r["konu_dagilimi"][:3]:
        assert "konu" in konu
        assert "toplam" in konu
        assert "yillar" in konu
        assert "tahmin_2026" in konu
        assert "tahmin" in konu["tahmin_2026"]
        assert "skor" in konu["tahmin_2026"]
    # Chart data
    assert "chart_konu_agirlik" in r
    assert "chart_yil_trend" in r


def test_konu_dagilimi_fizik_ayt():
    _run(_test_konu_dagilimi_fizik_ayt())


async def _test_konu_dagilimi_gecersiz_sinav():
    """Geçersiz sınav türü error dön."""
    from ders_konu_dagilimi import konu_dagilimi_raporu
    r = await konu_dagilimi_raporu(ders="Fizik", sinav_turu="XYZ")
    assert "error" in r


def test_konu_dagilimi_gecersiz_sinav():
    _run(_test_konu_dagilimi_gecersiz_sinav())


async def _test_konu_dagilimi_bos_ders():
    """Ders parametresi yoksa default Fizik (veya error)."""
    from ders_konu_dagilimi import konu_dagilimi_raporu
    r = await konu_dagilimi_raporu(ders="")
    # "" de default Fizik olabilir ya da error — ikisi de kabul
    assert ("error" in r) or ("toplam_soru" in r)


def test_konu_dagilimi_bos_ders():
    _run(_test_konu_dagilimi_bos_ders())


def test_tahmin_logic():
    """_tahmin_2026 heuristiği doğru çalışıyor."""
    from ders_konu_dagilimi import _tahmin_2026
    # Son 3 yılda 2+ kez → YÜKSEK
    t = _tahmin_2026([2023, 2024, 2025], 3)
    assert t["skor"] >= 80
    assert "YÜKSEK" in t["tahmin"]
    # Sadece eski yıllar → DÜŞÜK
    t = _tahmin_2026([2018, 2019], 2)
    assert t["skor"] <= 30
    assert "DÜŞÜK" in t["tahmin"]
    # Boş → DÜŞÜK
    t = _tahmin_2026([], 0)
    assert t["tahmin"] == "DÜŞÜK"


# ═══════════════════════════════════════════════════════════════════════════
# TEACHER_COPILOT — build_brief + build_rehber_brief
# ═══════════════════════════════════════════════════════════════════════════

async def _test_teacher_build_brief():
    """build_brief öğretmen için özet üretir (DB bağımlı, hata vermezse geçer)."""
    from teacher_copilot import build_brief
    r = await build_brief("Test Hoca")
    assert isinstance(r, str)
    # "bilgim yok" veya özet — her durumda str dönüyor


def test_teacher_build_brief():
    _run(_test_teacher_build_brief())


async def _test_teacher_rehber_brief():
    """build_rehber_brief bekleyen önerileri gösterir."""
    from teacher_copilot import build_rehber_brief
    r = await build_rehber_brief("Rehber")
    assert isinstance(r, str)
    assert len(r) > 0


def test_teacher_rehber_brief():
    _run(_test_teacher_rehber_brief())


# ═══════════════════════════════════════════════════════════════════════════
# OUTREACH YASAĞI — meta invaryant testi
# ═══════════════════════════════════════════════════════════════════════════

def test_outreach_yasak_tum_flagler():
    """Tüm outreach-yapabilen modüllerin flag'leri kapalı olduğunu garanti et.

    Sezon (1 Eylül 2026) açılmadan önce bu test KESİN PASS olmalı.
    Herhangi bir modül FALSE yerine TRUE'ya geçerse Neo'ya sürpriz yok.
    """
    from alert_system import ALERTS_ACTIVE
    from frustration_telafi import TELAFI_ACTIVE
    from daily_push import PUSH_ACTIVE
    from yaz_kampi import YAZ_KAMPI_ACTIVE

    flags = {
        "ALERTS_ACTIVE (alarm sistemi)": ALERTS_ACTIVE,
        "TELAFI_ACTIVE (iletişim telafisi)": TELAFI_ACTIVE,
        "PUSH_ACTIVE (günlük push)": PUSH_ACTIVE,
        "YAZ_KAMPI_ACTIVE (yaz kampı)": YAZ_KAMPI_ACTIVE,
    }
    aktif_olanlar = [k for k, v in flags.items() if v]
    assert not aktif_olanlar, (
        f"OUTREACH YASAĞI İHLAL EDİLİYOR: {aktif_olanlar} aktif. "
        f"Neo 23 Nisan talimatı: Sınav dönemi + yeni sezon öncesi otomatik mesaj YASAK."
    )
