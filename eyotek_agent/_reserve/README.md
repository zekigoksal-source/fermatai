# `_reserve/` — Rezerv Modül Arşivi

> **Bu klasor silinmiş değil, envanterleştirilmiş modülleri tutar.**
> 15 Nisan 2026 (Oturum 18) itibarıyla kritik olmayan/aktif kullanılmayan
> ama ileride referans/yeniden kullanım için değerli modüller buraya taşındı.

## Amaç

- Ana dizini temiz tut → Grep/IDE/kod gezinmesi hızlanır
- Hiçbir şey kaybetme → Git tarihinde de var ama burada **organize** ve **açıklamalı**
- İleride ihtiyaç olursa → alt klasörlerdeki README'den hangisi hangi senaryoya uyduğu görünür

## Klasör Yapısı

| Klasör | Içerik | Ne zaman geri alınır |
|--------|--------|---------------------|
| `eyotek_arayuz_referansi/` | Eyotek site haritası çıkarma, eski scraping agent'ı | Eyotek UI değişirse (yeni keşif + scraping mantığı revize) |
| `tek_seferlik_import/` | Excel/JSON ad-hoc veri import scriptleri | Aynı formatta yeni Excel/JSON dump geldiğinde |
| `eski_versiyon/` | Yeni sürümle devredilen dosyalar | Referans karşılaştırma (eski davranış nasıldı?) |

## Geri Alma Prosedürü

Bir dosyaya ihtiyaç duyarsan:

```bash
# Örnek: scrape_* artık lazım oldu
cp _reserve/eyotek_arayuz_referansi/explore_eyotek.py .
# Ya da
mv _reserve/tek_seferlik_import/import_new_data.py .
```

İçinde import'lar hala doğru (eski yapıya göre). Çağıran başka dosyalar
güncel schemayla uyumlu değilse küçük düzeltme gerekebilir.

## Dokunulmaması Gerekenler

Bu dosyalar **aktif kullanımda**, `_reserve/`'e alınmadı:
- `alert_system.py` — hazır pasif (ALERTS_ACTIVE=False)
- `scrape_*.py` (veri çekim scriptleri) — düzenli kullanım
- `sync_missing_students.py`, `fill_missing_nets.py`, `incremental_exam_check.py`
- `auto_import_exams.py`, `quality_monitor.py`, `conversation_viewer.py`
- `ogm_scraper.py`, `rag_content_builder.py`
- `veli_module.py`, `pdf_archive.py`, `pdf_report.py` (pasif ama referanslı)
