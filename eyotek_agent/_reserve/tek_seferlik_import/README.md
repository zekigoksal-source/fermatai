# `tek_seferlik_import/`

> **Excel/JSON toplu veri import scriptleri. Ekim-Kasım 2025 dump'ları bir kez import edildi.**
> Aynı formatta yeni veri gelirse tekrar kullanılabilir.

## İçerik

### `import_all_excel.py` (3.5 KB)
- **Ne yapar:** Generic Excel importer — `devamsizlik_sayisi` gibi basit tablolar için.
- **Ne zaman lazım:** Eyotek'ten yeni bir Excel dump geldiğinde (kolonlar eşleşiyor ise).

### `import_etut_excel.py` (5.8 KB)
- **Ne yapar:** Etüt Ara Excel export'u → `etut_history` tablosuna.
- **Bir kez:** Eylül 2025 – Mayıs 2026 dump, 2421 kayıt.
- **Ne zaman lazım:** Yeni sezon etüt verisini toplu import için.

### `import_exam_details.py` (7.7 KB)
- **Ne yapar:** Sınav JSON export'ları → `student_exams` tablosuna.
- **Bir kez:** Ağustos 2025 – Nisan 2026 dump, 3631 kayıt.
- **Ne zaman lazım:** Sınav dump'ı Eyotek'ten JSON formatında alındığında.

### `import_rehberlik_excel.py` (5.1 KB)
- **Ne yapar:** Rehberlik Notu Excel → `counsellor_notes`.
- **Bir kez:** 1631 kayıt import edildi.
- **Ne zaman lazım:** Rehberlik Excel dump güncellendiğinde.

### `import_new_data.py` (7.5 KB)
- **Ne yapar:** Ad-hoc yeni veri kaynaklarını PostgreSQL'e import.
- **Ne zaman lazım:** Belirli ad-hoc import senaryosu (öğrenci telefonları gibi) tekrarlanırsa.

### `build_profiles.py` (21.5 KB)
- **Ne yapar:** Öğrenci profilini derleyip `profile_map.json` üretir.
- **Bir kez:** 125 öğrenci için üretildi.
- **Ne zaman lazım:** Öğrenci listesi ciddi değişirse (yeni dönem kayıtları).

### `build_topic_tracker.py` (3.8 KB)
- **Ne yapar:** Sınav verisinden `student_topic_tracker` tablosuna zayıf konu listesi üretir.
- **Bir kez:** 1145 kayıt üretildi.
- **Ne zaman lazım:** Topic tracker algoritması değişir veya veri büyük güncellenirse.

### `setup_cache_tables.py` (4.8 KB)
- **Ne yapar:** Analytics cache tablolarını oluşturur (ilk kurulum).
- **Bir kez:** Kurulum tamamlandı.
- **Ne zaman lazım:** Yeni sunucuda FermatAI kurulumu (ya da cache tablo şeması değişirse).
