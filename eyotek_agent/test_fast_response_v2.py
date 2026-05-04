"""
A+++ Fast Response — Mock test (DB bağımsız)
=============================================
Phase 1 (Görsel kalite upgrade) test.

Mock DB ile her yeni rewrite'ı render edip görsel kalite ölçer.
"""
import sys, asyncio
sys.stdout.reconfigure(encoding='utf-8')

from unittest.mock import patch, MagicMock, AsyncMock

# Test scenarios
SCENARIOS = []


async def mock_q(query, *args):
    """Generic mock for SELECT queries."""
    q = query.lower()
    # devamsizlik_sayisi
    if 'devamsizlik_sayisi' in q:
        return [{'toplam_saat': 75}]
    # devamsizlik_ders
    if 'devamsizlik_ders' in q:
        return [
            {'ders': 'Matematik', 'saat': 25},
            {'ders': 'Fizik', 'saat': 18},
            {'ders': 'Türkçe', 'saat': 12},
        ]
    # student_topic_tracker (guclu)
    if 'student_topic_tracker' in q and 'sinav_hata_yuzdesi > 60' in q:
        return [
            {'ders': 'Matematik', 'konu': 'Türev', 'sinav_hata_yuzdesi': 92},
            {'ders': 'Fizik', 'konu': 'Manyetik Alan', 'sinav_hata_yuzdesi': 85},
            {'ders': 'Matematik', 'konu': 'İntegral', 'sinav_hata_yuzdesi': 78},
            {'ders': 'Kimya', 'konu': 'Organik Kimya', 'sinav_hata_yuzdesi': 73},
        ]
    # etut_history
    if 'etut_history' in q and 'count' in q:
        return [{'toplam': 87, 'ogrenci': 245, 'ilk': '2025-09-15', 'son': '2026-04-25'}]
    if 'etut_history' in q and 'extract(week' in q:
        return [{'cnt': 5}, {'cnt': 8}, {'cnt': 12}, {'cnt': 7}]
    if 'etut_history' in q:
        return [
            {'tarih': '2026-04-25', 'ogretmen': 'Selma Hoca', 'ders': 'Matematik', 'konu': 'Türev'},
            {'tarih': '2026-04-22', 'ogretmen': 'Murathan Hoca', 'ders': 'Fizik', 'konu': 'Manyetik Alan'},
        ]
    # etut_student_control
    if 'etut_student_control' in q and 'order by' in q:
        return [
            {'soz_no': 137, 'full_name': 'Ali Veli', 'sinif': '12 SAY A', 'toplam': 25, 'yapildi': 22, 'ogrenci_gelmedi': 3},
            {'soz_no': 138, 'full_name': 'Mehmet Şen', 'sinif': '11 SAY B', 'toplam': 22, 'yapildi': 19, 'ogrenci_gelmedi': 3},
            {'soz_no': 139, 'full_name': 'Ayşe Yıldız', 'sinif': '12 EA C', 'toplam': 18, 'yapildi': 12, 'ogrenci_gelmedi': 6},
        ]
    # counsellor_notes
    if 'counsellor_notes' in q:
        from datetime import date, timedelta
        return [
            {'gorusme_tarihi': date(2026, 4, 20), 'ogretmen': 'Kardelen Hoca',
             'not_metni': 'AYT puanı yükselişte, motivasyonu yüksek. Fizik etüdü öneril.'},
            {'gorusme_tarihi': date(2026, 4, 5), 'ogretmen': 'Kardelen Hoca',
             'not_metni': 'Hedef üniversite görüşmesi yapıldı, ODTÜ planlandı.'},
        ]
    # etut_teacher_summary
    if 'etut_teacher_summary' in q:
        return [
            {'ad_soyad': 'Selma Hoca', 'toplam_ders': 320, 'ogrenci_sayisi': 87, 'toplam_etut': 145},
            {'ad_soyad': 'Murathan Hoca', 'toplam_ders': 285, 'ogrenci_sayisi': 78, 'toplam_etut': 132},
            {'ad_soyad': 'Kardelen Hoca', 'toplam_ders': 220, 'ogrenci_sayisi': 92, 'toplam_etut': 98},
        ]
    return []


async def mock_q1(query, *args):
    """Mock for fetchrow."""
    q = query.lower()
    # students
    if 'from students' in q and 'soz_no=$1' in q:
        return {'class_name': '12 SAY A'}
    if 'devamsizlik_sayisi' in q:
        return {'toplam_saat': 75}
    # student_exam_analysis
    if 'student_exam_analysis' in q:
        return {
            'ham_puan': 425.5,
            'yerlesme_puani': 462.3,
            'toplam_net': 89.5,
            'sinav_sayisi': 5,
        }
    # etut_student_control (single)
    if 'etut_student_control' in q and 'where soz_no' in q:
        return {'toplam': 18, 'yapildi': 14, 'ogrenci_gelmedi': 4}
    # etut_history count
    if 'etut_history' in q and 'count(*)' in q:
        return {'toplam': 87, 'ogrenci': 245, 'ilk': '2025-09-15', 'son': '2026-04-25', 'c': 25}
    return None


async def mock_qval(query, *args):
    return 0


# ─── Patch and run ────────────────────────────────────────────────────────
async def run_tests():
    import fast_responses

    # Replace DB calls
    fast_responses._q = mock_q
    fast_responses._q1 = mock_q1
    fast_responses._qval = mock_qval

    # Mock analytics_cache.get_cached
    import analytics_cache
    _MOCK_CACHE = {
        'genel_istatistik': {
            'toplam_ogrenci': 125, 'toplam_personel': 18,
            'toplam_etut': 2421, 'toplam_rehberlik': 1631,
        },
        'sinif_ogrenci_sayisi': [
            {'class_name': '12 SAY A', 'ogrenci_sayisi': 18},
            {'class_name': '12 SAY B', 'ogrenci_sayisi': 15},
            {'class_name': '11 SAY A', 'ogrenci_sayisi': 12},
            {'class_name': '12 EA A', 'ogrenci_sayisi': 14},
            {'class_name': 'Mezun SAY', 'ogrenci_sayisi': 22},
        ],
        'devamsizlik_top20': [
            {'adi': 'Ali', 'soyadi': 'Veli', 'sinif': '12 SAY A', 'toplam_saat': 175},
            {'adi': 'Mehmet', 'soyadi': 'Şen', 'sinif': '11 SAY B', 'toplam_saat': 130},
            {'adi': 'Ayşe', 'soyadi': 'Yıldız', 'sinif': '12 EA C', 'toplam_saat': 95},
            {'adi': 'Burak', 'soyadi': 'Demir', 'sinif': 'Mezun SAY', 'toplam_saat': 60},
        ],
    }
    analytics_cache.get_cached = lambda k: _MOCK_CACHE.get(k)

    print("=" * 80)
    print("A+++ FAST RESPONSE TEST — PHASE 1 (Görsel Kalite Upgrade)")
    print("=" * 80)

    tests = [
        ('1. ogrenci_devamsizlik (75 saat)',
         lambda: fast_responses.ogrenci_devamsizlik(137, 'Ali Veli')),

        ('2. ogrenci_etutlerim',
         lambda: fast_responses.ogrenci_etutlerim(137, 'Ali Veli')),

        ('3. ogrenci_hedef (425 puan)',
         lambda: fast_responses.ogrenci_hedef(137, 'Ali Veli')),

        ('4. ogrenci_rehberlik (2 görüşme)',
         lambda: fast_responses.ogrenci_rehberlik(137, 'Ali Veli')),

        ('5. ogrenci_guclu_konular (4 konu)',
         lambda: fast_responses.ogrenci_guclu_konular(137, 'Ali Veli')),

        ('6. ogretmen_bugun_ders',
         lambda: fast_responses.ogretmen_bugun_ders('Selma Hoca')),

        ('7. ogretmen_etut_istatistik',
         lambda: fast_responses.ogretmen_etut_istatistik('Selma Hoca')),

        ('8. admin_devamsizlik_top',
         lambda: fast_responses.admin_devamsizlik_top()),

        ('9. admin_ogrenci_sayisi',
         lambda: fast_responses.admin_ogrenci_sayisi()),

        ('10. admin_en_cok_etut_alan_ogrenci',
         lambda: fast_responses.admin_en_cok_etut_alan_ogrenci()),

        ('11. admin_ogretmen_kiyasla',
         lambda: fast_responses.admin_ogretmen_kiyasla()),
    ]

    passed = failed = 0
    for label, fn in tests:
        print(f"\n\n{'━' * 80}")
        print(f"  {label}")
        print('━' * 80)
        try:
            result = await fn()
            if result:
                print(result)
                passed += 1
            else:
                print("⚠️  Returned None")
                failed += 1
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback; traceback.print_exc()
            failed += 1

    print(f"\n\n{'=' * 80}")
    print(f"  SONUÇ: {passed}/{passed+failed} test geçti")
    print('=' * 80)


if __name__ == '__main__':
    asyncio.run(run_tests())
