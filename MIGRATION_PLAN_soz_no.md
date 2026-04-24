# soz_no Schema Migration Planı

**Durum:** ERTELENDİ (19 Nisan 03:30 — Neo kararı, gece geç)
**Hazır:** Audit yapıldı, veri uyumlu, script hazır, sadece yürütme bekliyor
**Tahmini süre:** 2-4 saat (dikkatli test dahil)
**Önerilen zaman:** Sakin bir gün, hafta içi sabah/öğle, Neo dinlenmiş

## Mevcut Durum (Audit Sonucu — 19 Nisan 03:30)

### Text Tablolar (16 adet — INTEGER'A ÇEVRİLECEK)
```
fermat.attendance
fermat.class_roster
fermat.counsellor_notes  (WAIT: önce kontrol — audit'te counsellor text görünüyor ama daha önce integer demiştik)
fermat.etut_records
fermat.etut_student_control_cache
fermat.exam_results
fermat.foto_questions
fermat.homework
fermat.overdue_payments
fermat.pedagojik_koc_log
fermat.student_behaviour
fermat.student_details_specific
fermat.student_exam_analysis   ← dashboard kullanıyor
fermat.student_grades
fermat.student_interactions
fermat.student_timetable
fermat.students                 ← dashboard kullanıyor
```

### Integer Tablolar (9 adet — DOKUNULMAYACAK)
Zaten doğru tipte, ALTER yok.

## Avantajlar
- ✅ Veri uyumlu (16 tabloda da tüm değerler integer-parse edilebilir)
- ✅ FK constraint yok (drop/recreate cascade sorunu YOK)
- ✅ Backup alındı (`backups/fermatai_20260419_0241.sql`, 63.8MB)
- ✅ Dashboard test-edilebilir durumda

## Risk Faktörleri
- 🔴 16 ALTER TABLE çağrısı → her biri potansiyel hata noktası
- 🔴 12 index (PK/UNIQUE/INDEX) korunmalı
- 🔴 Kod tarafında **100+ yerde** `::text` cast veya `str(soz_no)` var — hepsi temizlense bile birkaç yerde yeni bug yaratabilir
- 🔴 Migration sırasında bridge kapatılmalı (5-10 dk downtime)
- 🟡 Tek yanlış script → 25 tablo etkilenir, rollback için tüm DB restore

## Migration Adımları (Hazır Script)

### Adım 1: Pre-Migration Checklist
```bash
# Yeni backup al (backup otomatik da var ama elle extra)
cd eyotek_agent && python db_backup.py
# Audit çalıştır, "MIGRATION HAZIR" gördüğünden emin ol
python tests/soz_no_migration_audit.py
# Bridge'i durdur
taskkill //PID $(netstat -ano | grep :8001 | grep LISTENING | awk '{print $5}') //F
```

### Adım 2: Migration SQL (Transaction)
```sql
BEGIN;

-- 16 text tabloyu integer'a çevir
ALTER TABLE fermat.attendance                   ALTER COLUMN soz_no TYPE integer USING soz_no::integer;
ALTER TABLE fermat.class_roster                 ALTER COLUMN soz_no TYPE integer USING soz_no::integer;
ALTER TABLE fermat.etut_records                 ALTER COLUMN soz_no TYPE integer USING soz_no::integer;
ALTER TABLE fermat.etut_student_control_cache   ALTER COLUMN soz_no TYPE integer USING soz_no::integer;
ALTER TABLE fermat.exam_results                 ALTER COLUMN soz_no TYPE integer USING soz_no::integer;
ALTER TABLE fermat.foto_questions               ALTER COLUMN soz_no TYPE integer USING soz_no::integer;
ALTER TABLE fermat.homework                     ALTER COLUMN soz_no TYPE integer USING soz_no::integer;
ALTER TABLE fermat.overdue_payments             ALTER COLUMN soz_no TYPE integer USING soz_no::integer;
ALTER TABLE fermat.pedagojik_koc_log            ALTER COLUMN soz_no TYPE integer USING soz_no::integer;
ALTER TABLE fermat.student_behaviour            ALTER COLUMN soz_no TYPE integer USING soz_no::integer;
ALTER TABLE fermat.student_details_specific     ALTER COLUMN soz_no TYPE integer USING soz_no::integer;
ALTER TABLE fermat.student_exam_analysis        ALTER COLUMN soz_no TYPE integer USING soz_no::integer;
ALTER TABLE fermat.student_grades               ALTER COLUMN soz_no TYPE integer USING soz_no::integer;
ALTER TABLE fermat.student_interactions         ALTER COLUMN soz_no TYPE integer USING soz_no::integer;
ALTER TABLE fermat.student_timetable            ALTER COLUMN soz_no TYPE integer USING soz_no::integer;
ALTER TABLE fermat.students                     ALTER COLUMN soz_no TYPE integer USING soz_no::integer;

-- Verify
SELECT table_schema, table_name, data_type
FROM information_schema.columns
WHERE column_name = 'soz_no' AND table_schema IN ('fermat','public')
ORDER BY data_type, table_name;

-- Test: önemli JOIN artık cast'siz çalışıyor mu?
SELECT COUNT(*) FROM fermat.students s
JOIN fermat.student_exams e ON s.soz_no = e.soz_no;  -- cast YOK, int=int

COMMIT;  -- hata yoksa COMMIT, hata varsa ROLLBACK
```

### Adım 3: Kod Temizliği (Grep-based)
```bash
# Gereksiz cast'leri bul — manuel incele, otomatik değiştirme YAPMA
grep -rn "::text" eyotek_agent/*.py | grep "soz_no"
grep -rn "str(soz_no)" eyotek_agent/*.py

# Risk: bazı cast'ler başka sebeple var (örn: JSON serialize). TEK TEK bak.
```

Dashboard endpoint'leri (`web_chat.py:_dashboard_*`) ve çeşitli tool helper'ları:
- `s.soz_no::text = e.soz_no` → `s.soz_no = e.soz_no` (artık her ikisi de int)
- `str(soz_no)` → `int(soz_no)` veya direkt kullan
- `WHERE soz_no::text = $1` → `WHERE soz_no = $1` (Python'dan int geç)

### Adım 4: Bridge Başlat + Test
```bash
cd eyotek_agent && nohup .venv/Scripts/python.exe -m uvicorn whatsapp_bridge:app --host 0.0.0.0 --port 8001 > logs/wp_bridge.log 2>&1 &
# 4 rol dashboard test
# WhatsApp'tan Neo çağrısı test
```

### Adım 5: Rollback Planı
Bir şey bozulursa:
```bash
# Backup restore (Docker PostgreSQL)
docker exec -i fermat_postgres psql -U fermat -d fermatai < backups/fermatai_20260419_0241.sql
# Bridge başlat
```

## Değer Analizi — Migration Yapmalı Mı?

### PRO (lehine)
- Schema tutarlı olur
- Kod cast pattern'lardan arınır
- Gelecek bug'lar azalır
- Performans: int join > text join (mikro iyileştirme)

### CON (aleyhine)
- Şu an **çalışıyor** — cast pattern ile sorun yok
- 2-4 saat iş + downtime
- 100+ kod yeri temizlik
- Regresyon riski (her temizleme potansiyel bug)

## Neo Kararı

**Şimdilik ERTELENDİ.** Mevcut cast pattern üretimde çalışıyor, acil değil.

Ne zaman yap?
- Yeni özellik eklerken çok cast karmaşası başlarsa
- Schema'yı başka sebeple refactor edeceksek (ör: soft delete ekleme)
- Önemli bir veri modeli değişikliği olursa (ör: arşiv tablosu)

## Dosyalar

- `tests/soz_no_migration_audit.py` — Pre-migration audit script
- `backups/fermatai_20260419_0241.sql` — Pre-migration backup (63.8MB)
- Bu doküman — plan + SQL + rollback

---

**Not:** Audit "MIGRATION HAZIR" dedi ama bu teknik hazırlık, zamanlama değil.
Sakin bir gündüz saatinde, Neo dinlenmiş, test için 1-2 saat ayrılmış — o zaman yap.
