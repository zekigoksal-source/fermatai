# `eski_versiyon/`

> **Yeni bir sürüm devraldı. Geri alma nadirdir ama referans değeri var.**

## İçerik

### `daily_briefing.py` (5.0 KB — 7 Nisan 2026)
- **Ne yaptı:** Sabah 08:00'de briefing üretirdi (devamsız, riskli, agent kullanımı).
- **Kim devraldı:** `daily_report.py` (Oturum 10+) — daha zengin rapor, WP otomatik gönderim,
  scheduler ile entegre (20:00 günlük rapor + duygu takibi).
- **Ne zaman lazım:** Eski sabah briefing formatı ile karşılaştırma (A/B testi).
- Komut vardı: `python daily_briefing.py` veya `--send`

### `test_paraphrase_coverage.py` (18.3 KB — 10 Nisan 2026)
- **Ne yaptı:** 173 paraphrased soru ile fast_response coverage testi (Oturum 6).
- **Kim devraldı:** `tests/` klasörü (Oturum 18) — 88 test, pytest + marker sistemi.
- **Ne zaman lazım:** Eski paraphrase senaryolarına dönmek için referans,
  yeni senaryolarla karşılaştırma.
