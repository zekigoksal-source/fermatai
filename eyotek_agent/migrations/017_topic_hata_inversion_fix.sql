-- 017_topic_hata_inversion_fix.sql
-- Oturum 25.47 (Neo 21 May) — Zeynep Akbaş vakası.
--
-- SORUN: student_topic_tracker.sinav_hata_yuzdesi kolonu, adının aksine
--        BAŞARI (doğru) oranını tutuyordu:
--          - oncelikli_konular import: JSON `yuzde` = (soru−yanlis−bos)/soru = BAŞARI
--          - post_sync_update.py: basari_pct = avg_net/max_net*100 = BAŞARI
--        Tüm okuyucu kod ise kolonu HATA% sanıyordu (DESC=zayıf, 100−x=başarı).
--        Sonuç: güçlü konular zayıf gösteriliyordu. Türkçe'de 37/40 yapan öğrenci
--        raporda "Türkçe paragraf %80 hata, kör nokta" diye çıkıyordu (TERS).
--
-- Ayrıca sinav_basari_yuzdesi kolonu GENERATED ALWAYS AS (sinav_hata_yuzdesi)
-- idi — yani hata kolonunun birebir KOPYASI (100−hata DEĞİL). İkisi hep eşitti.
--
-- ÇÖZÜM:
--   1) hata_yuzdesi'ni gerçek HATA oranına çevir (100 − mevcut_değer).
--   2) sinav_basari_yuzdesi'ni gerçek tümleyen (100 − hata) generated kolon yap.
--
-- KOD TARAFI (aynı commit): post_sync_update.py artık 100−basari_pct yazıyor;
-- 7 success-convention okuyucu (web_chat, teacher_escalation, ucgen_model,
-- topic_difficulty_map, teacher_copilot, student_profile_v2) HATA% konvansiyonuna
-- çevrildi; system_prompts.py'a çapraz-doğrulama guardrail eklendi.
--
-- ⚠️ İDEMPOTENT GUARD: Bu migration SADECE migrate EDİLMEMİŞ DB'de çalışır.
--    sinav_basari_yuzdesi generation_expression'ı zaten '100 - ...' içeriyorsa
--    (yani daha önce uygulanmışsa) HİÇBİR ŞEY YAPMAZ — tekrar flip ETMEZ.
--    Production VPS 21 May'de uygulandı; bu dosya local/diğer env içindir.

DO $migrate$
DECLARE
    cur_expr text;
BEGIN
    SELECT generation_expression INTO cur_expr
    FROM information_schema.columns
    WHERE table_name = 'student_topic_tracker'
      AND column_name = 'sinav_basari_yuzdesi';

    IF cur_expr IS NOT NULL AND cur_expr LIKE '%100%' THEN
        RAISE NOTICE '017: zaten uygulanmış (basari = 100 - hata). Atlanıyor.';
        RETURN;
    END IF;

    -- Yedek (varsa dokunma)
    EXECUTE 'CREATE TABLE IF NOT EXISTS student_topic_tracker_bak_o2547 AS
             SELECT * FROM student_topic_tracker';

    -- 1) GENERATED basari kolonunu düş (varsa) — hata'yı değiştirebilmek için
    ALTER TABLE student_topic_tracker DROP COLUMN IF EXISTS sinav_basari_yuzdesi;

    -- 2) Veri: success → error çevir (non-null, 0-100 aralığı)
    UPDATE student_topic_tracker
    SET sinav_hata_yuzdesi = ROUND((100 - sinav_hata_yuzdesi)::numeric, 2)
    WHERE sinav_hata_yuzdesi IS NOT NULL
      AND sinav_hata_yuzdesi BETWEEN 0 AND 100;

    -- 3) Generated başarı kolonu = 100 − hata (gerçek tümleyen, 0'a kırp)
    ALTER TABLE student_topic_tracker
      ADD COLUMN sinav_basari_yuzdesi real
      GENERATED ALWAYS AS (GREATEST(0, 100 - sinav_hata_yuzdesi)) STORED;

    RAISE NOTICE '017: uygulandı (hata flip + basari generated 100-hata).';
END
$migrate$;

-- DOĞRULAMA:
--   SELECT konu, sinav_hata_yuzdesi, sinav_basari_yuzdesi
--   FROM student_topic_tracker WHERE soz_no=246 AND status='onerilen'
--   ORDER BY sinav_hata_yuzdesi DESC;
--   Beklenen: Kimya Asit-Baz hata~98/basari~2 (gerçek zayıf),
--             Türkçe Paragraf hata~20/basari~80 (gerçek güçlü).
