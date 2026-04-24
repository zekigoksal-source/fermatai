# `eyotek_arayuz_referansi/`

> **Eyotek LMS UI'si değişirse yeniden keşif + scraping için kritik değerli dosyalar.**

## İçerik

### `explore_eyotek.py` (9.2 KB — 5 Nisan 2026)
- **Ne yapar:** Eyotek LMS sitesinde menü/URL haritasını otomatik keşfeder,
  `site_map.json` + `eyotek_menu_map.md` üretir.
- **Ne zaman lazım:** Eyotek'e yeni menü/sayfa eklenir ya da URL yapısı değişirse,
  bu script'i çalıştırıp güncel haritayı çıkartırsın. Sonra `STUDENT_SECTION_PATHS`
  gibi hardcoded URL listeleri güncellenir.

### `explore_student_profile.py` (88.8 KB — 6 Nisan 2026)
- **Ne yapar:** Öğrenci profil sayfasındaki tüm alt menüleri keşfeder
  (Yoklama, Sinav, Davranış, Timetable vs.), CDP ile derin gezinti yapar.
- **Ne zaman lazım:** Öğrenci profilinin tab yapısı değişirse, yeni keşif için.
  `student_page_map.json`'u yeniden üretir.

### `eyotek_agent.py` (58.3 KB — 6 Nisan 2026) — v10 eski toplu scraper
- **Ne yapar:** Tüm öğrenci, yoklama, personel verisini Eyotek'ten çekip
  PostgreSQL'e UPSERT eder. `fermat_start.py` devraldığı için artık direkt çağırılmıyor.
- **Ne zaman lazım:**
  - Eyotek yapısı değişip yeni bir scraper yazmak gerektiğinde temel referans
  - `fermat_start.py` çalışmazsa (acil durum) manuel toplu veri çekimi için fallback
  - Komut: `python eyotek_agent.py students` / `attendance`

### `data_sync.py` (18.4 KB — 8 Nisan 2026) — eski sync katmanı
- **Ne yapar:** Eyotek → PostgreSQL Local Cache sync mantığını içerir.
- **Ne zaman lazım:** Sync mimarisi değişirse eski davranış referansı.
  `sync_attendance.py` ve `smart_sync.py` aktif versiyonları.

## UYARI

Bu dosyalar **hardcoded Eyotek URL'leri ve selector'ları** içerir. Eyotek değişirse:
1. Önce bu dosyaları `cp ../explore_eyotek.py .` ile geri al
2. Çalıştırıp güncel yapıyı keşfet
3. Yeni selector'ları `eyotek_wrapper.py`'a uygula
