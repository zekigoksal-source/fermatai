"""
FermatAI — Anthropic Tool Use Tanimlari (22.1n-split)
======================================================

fermat_core_agent.py'dan ayrilan TOOLS listesi.
Backward compat: `from tool_definitions import TOOLS`.

Bu modul sadece DATA iceriir. Tool FONKSIYONLARI hala
fermat_core_agent.py icinde (_tool_*, tool_*).

Son degisiklik: 22.1n-neo branch_zayif_konu tool eklendi (Merve brans analizi).
"""

# ─── Araç Tanımları (Anthropic Tool-Use formatı) ──────────────────────────────

TOOLS: list[dict] = [
    {
        "name": "get_student_analytics",
        "description": (
            "Bir öğrencinin akademik profilini PostgreSQL'den çeker: "
            "son sınav netleri, devamsızlık sayısı, ödeme durumu, "
            "rehberlik not özeti. Pedagojik karar vermek için kullan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "student_id": {
                    "type": "string",
                    "description": "Eyotek okul numarası veya öğrenci adı (tam/kısmi)",
                },
                "include_sections": {
                    "type": "array",
                    "items": {"type": "string",
                              "enum": ["exams", "attendance", "payments", "notes", "behaviour", "interactions", "all"]},
                    "description": "Hangi bölümler çekilsin. Varsayılan: all. behaviour=davranış, interactions=WP etkileşim istatistikleri",
                },
            },
            "required": ["student_id"],
        },
    },
    {
        "name": "get_ayt_analysis",
        "description": (
            "🎯 AYT analizi icin OZEL araç. 12.SAY/EA/Mezun ogrencinin AYT birlestir verisini "
            "(Eyotek'ten cekilmis SAĞLAM DOĞRU veri) donuyor. "
            "AYT sorulunca BU TOOL'u kullan — student_exams tablosundaki [AYT] kayitlar YANILTICI, KULLANMA! "
            "Donen veri: ham_puan_ayt, yerlesme_puani_ayt, sinav_sayisi_ayt, katilan_sinav_ayt, "
            "ders_netleri_ayt (sinav basi ORTALAMA NET — hesaplama yapilmis), oncelikli_konular_ayt."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "soz_no": {
                    "type": "string",
                    "description": "Ogrencinin soz_no'su (ornek: '182' Taha)",
                },
            },
            "required": ["soz_no"],
        },
    },
    {
        "name": "check_teacher_availability",
        "description": (
            "Bir branşta müsait öğretmen listesini döndürür. "
            "Etüt yazarken veya ders planlarken kullan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "description": "Ders adı, örn: Matematik, Fizik, Kimya",
                },
                "date": {
                    "type": "string",
                    "description": "Tarih YYYY-MM-DD formatında (opsiyonel)",
                },
            },
            "required": ["subject"],
        },
    },
    {
        "name": "execute_eyotek_action",
        "description": (
            "Eyotek LMS üzerinde yazma işlemi yapar. "
            "Etüt kaydı, rehberlik notu, SMS gönderimi gibi aksiyonlar. "
            "Sadece açıkça yetkilendirilmiş işlemler için kullan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["write_etut", "write_counsellor_note", "send_sms", "write_etut_for_class"],
                    "description": "Yapılacak eylem",
                },
                "params": {
                    "type": "object",
                    "description": (
                        "Eylem parametreleri. "
                        "write_etut için: {class_name, student_id_or_name, lesson, target_date (DD.MM.YYYY), "
                        "ders_no (1-15), etut_type, devre (ör: '1.Snf'), duration (35), repeat (1-10), "
                        "classroom (ör: 'D-3'), teacher, confirmed, dry_run}. "
                        "write_etut_for_class için: {class_name, lesson, target_date, ders_no, "
                        "etut_type, devre, duration, repeat, classroom, teacher, confirmed, dry_run}. "
                        "write_counsellor_note için: {student_id, note, note_type, meeting_type}. "
                        "send_sms için: {message, student_ids?, class_name?, devre?, dry_run?}."
                    ),
                },
                "reason": {
                    "type": "string",
                    "description": "Bu eylemi neden yapıyorsun? (pedagojik gerekçe)",
                },
            },
            "required": ["action", "params", "reason"],
        },
    },
    {
        "name": "get_class_summary",
        "description": (
            "Bir sınıfın genel özetini döndürür: öğrenci sayısı, "
            "son sınav ortalama neti, devamsızlık oranı."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "class_name": {
                    "type": "string",
                    "description": "Sınıf adı, örn: '11 SAY A', 'LGS A'",
                },
            },
            "required": ["class_name"],
        },
    },
    {
        "name": "search_students",
        "description": "İsme veya sınıfa göre öğrenci ara. query='istatistik' ile toplam öğrenci sayısı ve sınıf dağılımı döndürür.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Arama terimi: öğrenci adı veya sınıf adı",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maksimum sonuç sayısı (varsayılan: 5)",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_class_plan",
        "description": (
            "Bir öğrencinin haftalık ders programını veya belirli bir günün etüt listesini döndürür. "
            "Etüt çakışma kontrolü için kullan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "student_id": {
                    "type": "string",
                    "description": "Öğrenci adı veya eyotek_id",
                },
                "date": {
                    "type": "string",
                    "description": "Tarih DD.MM.YYYY formatında (boşsa bugün). Günlük etüt listesi için kullan.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "build_study_plan_context",
        "description": (
            "Öğrencinin çalışma planı oluşturmak için TÜM akademik verilerini toplar. "
            "Zayıf konular (hata % sıralı), deneme trendi (5 sınav), ders bazlı artış/düşüş, "
            "hedef üniversite, devamsızlık, ders programı, net kazanım potansiyeli döner. "
            "SADECE çalışma planı/programı oluşturma isteğinde kullan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "student_id": {
                    "type": "string",
                    "description": "Öğrenci soz_no (sayı olarak)",
                },
            },
            "required": ["student_id"],
        },
    },
    {
        "name": "search_curriculum",
        "description": (
            "Müfredat bilgi bankasında konu araması yapar. "
            "Öğrenci ders sorusu sorduğunda (kaldırma kuvveti nedir, paragrafta ana düşünce nasıl bulunur) "
            "veya konu anlatımı istediğinde kullan. Semantik arama ile en alakalı içerikleri döner. "
            "İçerik: konu anlatımı, formüller, soru tipleri, çalışma yöntemi."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Arama sorgusu (ör: 'Newton yasaları', 'paragrafta ana düşünce')",
                },
                "ders": {
                    "type": "string",
                    "description": "Ders filtresi (ör: Fizik, Matematik). Boş bırakılabilir.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "ogm_yonlendir",
        "description": (
            "MEB OGM Materyal resmi kaynagina (ogmmateryal.eba.gov.tr) yonlendirme linki al. "
            "Ogrenci ders calismak istedigi bir konu/soru tipi/deneme sorunca kullan. "
            "3 Adim Soru Bankasi (kazanim bazli), Konu Ozeti (PDF), Konu Anlatim Videolari, "
            "Cikmis Sorular, YKS Denemeleri, Puan Hesaplama gibi resmi MEB kaynaklari. "
            "BOS cevaptan daha degerli: 'Bu linke git, 20 soru coz, zorlandigini getir' gibi yonlendir. "
            "Birden fazla kaynak varsa 2-3 tanesini kategori+link formatiyla paylas."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ders": {
                    "type": "string",
                    "description": "Ders (Fizik, Matematik, Kimya, Biyoloji, Turkce, Tarih, Cografya, Felsefe, TDE, Ingilizce). Bos olursa tum dersler.",
                },
                "sinav_turu": {
                    "type": "string",
                    "description": "TYT, AYT, YDT veya YKS (genel hub). Bos olursa tum sinav turleri.",
                },
                "tip": {
                    "type": "string",
                    "description": "Icerik tipi: '3_adim_soru_bankasi', 'konu_ozeti', 'hub_link', 'konu_anlatim_video'. Bos olursa tum tipler.",
                },
            },
        },
    },
    {
        "name": "send_exam_image",
        "description": (
            "Cikmis soru sayfa gorselini ogrenciye WhatsApp uzerinden gonder. "
            "search_curriculum sonucundaki kaynak alanini kullan. "
            "Sadece 'OGM Vision' iceren kaynak degerleri icin calisir. "
            "Gorsel dersler (Matematik, Geometri, Fizik, Kimya, Biyoloji) icin kullan. "
            "Turkce, Tarih, Edebiyat gibi metin agirlikli dersler icin KULLANMA."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "kaynak": {
                    "type": "string",
                    "description": "search_curriculum sonucundan gelen kaynak alani (ör: 'OGM Vision: 68b4eb6deb07 s.120')",
                },
                "caption": {
                    "type": "string",
                    "description": "Gorsel alt yazisi (ör: 'Fizik — Kaldirma Kuvveti (YKS Cikmis)'). Kisa tut.",
                },
            },
            "required": ["kaynak"],
        },
    },
    {
        "name": "list_exam_questions",
        "description": (
            "Cikmis soru katalogu — konu ve yil bazli. "
            "Kullanici 'fizik cikmis sorular', 'modern fizik sorulari', 'matematik hangi konulardan soru var' "
            "gibi genel sorgularda ONCE bunu cagir. Sonra ogrenciye yil ve konu secenekleri sun. "
            "Ogrenci bir soru sectikten sonra send_exam_image ile gorsel gonder."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "konu": {
                    "type": "string",
                    "description": "Aranacak konu (ör: 'modern fizik', 'tork', 'integral'). Bos birakilabilir — tum konulari listeler.",
                },
                "ders": {
                    "type": "string",
                    "description": "Ders filtresi (ör: 'Fizik', 'Matematik')",
                },
            },
        },
    },
    {
        "name": "query_analytics",
        "description": (
            "KURUMSAL analiz + ÖZEL SQL sorgusu. ⚠️ ÖNCE hazır yapılandırılmış tool'ları KULLAN:\n"
            " • Tek öğrenci profili → get_student_analytics (query_analytics DEĞİL)\n"
            " • AYT detay → get_ayt_analysis\n"
            " • Rehber özet → counsellor_brief\n"
            " • Sınıf brief → class_brief\n"
            " • Transfer gap → transfer_failure_analiz\n"
            " • Puan tahmin → puan_tahmin / hedef_puan_analiz\n"
            "query_analytics SADECE bu tool'larda olmayan özel sorgularda: "
            "öğretmen etüt karşılaştırma, devamsızlık sıralama, tarihsel trend, çoklu sınıf karşılaştırma. "
            "Aynı veriyi 2 yoldan çekme — performans + maliyet kaybı.\n\n"
            "SQL sorgusu yaz ve calistir. "
            "Tablolar ve GERCEK kolon isimleri: "
            "etut_history (id, etut_kodu, tarih DATE, ogretmen, ders, konu, saat, sure, derslik, ogrenci_sayisi, yoklama, kaydeden, olusturma_tarihi), "
            "counsellor_notes (id, ogretmen, soz_no, ogrenci_adi, ogrenci_soyadi, sinif, devre, gorusme_tarihi, not_turu, gorusulen, gorusme_turu, not_metni), "
            "devamsizlik_sayisi (id, soz_no, adi, soyadi, sinif, devre, toplam_saat), "
            "teacher_timetable (ogretmen_id, ogretmen_ad, brans, haftalik_saat, gun, saat, sinif, ders, derslik), "
            "class_timetable (sinif, gun, saat, ogretmen, ders, derslik), "
            "students (soz_no, eyotek_id, full_name, first_name, last_name, class_name, sube, program, devre, phone, status='active|inactive'), "
            "KURAL: analiz sorgularinda WHERE status='active' kullan (125 kayittan 123 aktif, 2 inactive/yeni kayit veri yok). "
            "class_name bazi ogrencilerde prefix'li ('[10] 10 SAY A') veya NULL olabilir — bu AKTIF olmayi etkilemez, class_name gruplama icin devre veya program alanini da dene. "
            "MEZUN AYRIM (25.8): basari/sıralama sorgularinda mezunlari HARIC tut: "
            "AND class_name NOT ILIKE '%mezun%' AND class_name NOT ILIKE '%mez %'. "
            "Kullanici 'mezunlar dahil' demediyse default boyle. 40 mezun ogrenci aktif siralamayi bozar. "
            "staff (eyotek_id, full_name, first_name, last_name, gorev, brans), "
            "student_exam_analysis (soz_no, eyotek_id, full_name, "
            "ham_puan, yerlesme_puani, yerlesme_sirasi, ders_netleri JSONB, oncelikli_konular, sinav_sayisi, toplam_net, "
            "ham_puan_ayt, yerlesme_puani_ayt, ders_netleri_ayt JSONB, oncelikli_konular_ayt JSONB, sinav_sayisi_ayt, katilan_sinav_ayt"
            "), "
            "student_exams (soz_no, student_name, exam_code, exam_name, exam_date DATE, turkce, tarih, cografya, felsefe, din_kulturu, matematik, geometri, fizik, kimya, biyoloji, toplam, status='valid|not_attended', exam_type='TYT|AYT|BRANS|LGS|UNKNOWN'). "
            "SINAV VERI KURALLARI (Oturum 21 temizleme — tek noktada toplandi): "
            "• 1337 gecerli sinav + 626 not_attended + 2 exam_type sinif — WHERE status='valid' ekle zorunlu "
            "• TYT trend icin: WHERE exam_type='TYT' AND status='valid' "
            "• AYT trend icin: WHERE exam_type='AYT' AND status='valid'  (student_exams'teki [AYT] kayitlari YANILTICI idi, artik exam_type ile ayrildi) "
            "• BRANS denemesini TYT/AYT ile AYNI CHART'A KOYMA — ayri gorsellestir veya citla "
            "• 0 NET/NULL = katilmadi demek, TREND'E EKLEME "
            "\n🔴 AYT ANALIZI — TEK NET KURAL: "
            "1) Tek ogrenci AYT analizi: `get_ayt_analysis(soz_no='X')` TOOL — SQL yazma. "
            "2) Coklu ogrenci AYT liste/siralama: student_exam_analysis tablosundaki yerlesme_puani_ayt kolonu. "
            "   SQL: SELECT s.full_name, s.class_name, sea.sinav_sayisi_ayt, sea.ham_puan_ayt, sea.yerlesme_puani_ayt "
            "        FROM student_exam_analysis sea JOIN students s ON s.soz_no::text=sea.soz_no::text "
            "        WHERE sea.ham_puan_ayt IS NOT NULL AND s.status='active' "
            "        ORDER BY CAST(REPLACE(sea.yerlesme_puani_ayt,',','.') AS FLOAT) DESC "
            "3) get_ayt_analysis 'error' donerse: 'ogrenci AYT'ye girmemis' de — UYDURMA. "
            "4) Raporlarda: 'Resmi Yerlesme Puani: X' seklinde belirt. "
            "5) 'Eyotek' kelimesi YASAK — 'Resmi', 'Sistem', 'Kayitli veri' kullan. "
            "6) Ders netleri: tool'dan donen ortalama_netler dict'i AYNEN yazdir (net/soru formatinda). "
            "🔴 KURUM SIRALAMASI / COKLU OGRENCI LISTE KURALI (Oturum 18): "
            "Kurum geneli siralama yaparken (ornek: 'ilk 50bin'e girme adayi', 'en basarili 12SAY'), "
            "ogrencinin SINIF SEVIYESINE gore DOGRU puani kullan: "
            "  • 12.SAY / 12.EA / 12.SOZ / Mezun → `yerlesme_puani_ayt` (AYT puani) kullan "
            "  • 11.sinif ve altı → `yerlesme_puani` (TYT puani) kullan "
            "  • Ayirmadan tek bir 'en basarili' listesi yapma — karma listede 12.sinif ogrencisi TYT puaniyla yer aliyorsa YANILTICI olur. "
            "  • SORGU ORNEGI: `SELECT s.full_name, s.class_name, "
            "    CASE WHEN s.class_name ~ '12|Mez' THEN sea.yerlesme_puani_ayt ELSE sea.yerlesme_puani END as asil_puan, "
            "    CASE WHEN s.class_name ~ '12|Mez' THEN 'AYT' ELSE 'TYT' END as puan_turu "
            "    FROM students s JOIN student_exam_analysis sea ON sea.soz_no::text=s.soz_no::text "
            "    ORDER BY CAST(REPLACE(asil_puan,',','.') AS FLOAT) DESC`. "
            "  • Raporda HER OGRENCI icin puan turunu belirt: 'Yigit Alp: 509 (AYT)', 'Defne: 385 (TYT)'. "
            "Genelde SELECT sorgusu calistir. ISTISNA: student_topic_tracker ve student_insights tablolarina UPDATE/INSERT yapabilirsin (ogrenci konu takibi ve duygu analizi icin). "
            "ADMIN SELF-REPORT: Admin 'ne gozlemledin/hatalar/saglik durumu/sistem analizi' sorarsa → "
            "atlas_observations (id, category, severity, metric_name, metric_value, rationale, created_at) ve "
            "atlas_suggestions (id, category, severity, title, rationale, estimated_impact, status, created_at) tablolarini sorgula. "
            "Ornek: SELECT severity, category, title, rationale FROM atlas_suggestions WHERE status='yeni' ORDER BY severity, created_at DESC LIMIT 10"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "SELECT sorgusu. Ornek: SELECT ogretmen, COUNT(*) as etut_sayisi FROM etut_history GROUP BY ogretmen ORDER BY etut_sayisi DESC",
                },
                "explanation": {
                    "type": "string",
                    "description": "Bu sorgunun ne yaptigini kisa acikla",
                },
                "use_cache": {
                    "type": "string",
                    "description": (
                        "Cache key — hazir veri varsa DB'ye gitmeden aninda cevap verir. "
                        "Mumkunse ONCE cache kullan. Anahtarlar: "
                        "ogretmen_listesi, ogretmen_etut_toplam, ogretmen_etut_son30, "
                        "ders_etut_dagilimi, devamsizlik_top20, sinif_ogrenci_sayisi, "
                        "genel_istatistik, rehberlik_ozet, aylik_etut_trendi"
                    ),
                },
            },
            "required": ["sql", "explanation"],
        },
    },
    {
        "name": "calculate_yks_score",
        "description": (
            "YKS TYT puan hesaplama — OGM Materyal ile kalibre edilmis gercek katsayilar (fark <0.02 puan). "
            "Ogrencinin netleri + diploma notuyla TYT puanini hesaplar. "
            "Sonuc: ham_puan, yerlestirme_puani, tahmini_siralama, net_etkisi. "
            "Ogrenci 'kac puan yaparim', 'puanim kac', 'siralama tahmin' dediginde kullan. "
            "Calisma planinda: 'bu ders +3 net yaparsan +X puan kazanirsin' etkisi gostermek icin kullan. "
            "NOT: TYT katsayilari OGM dogrulanmis. SAY/EA/SOZ tahmini — 'kesin degil' uyarisi ekle."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "turkce_net": {"type": "number", "description": "TYT Turkce net (0-40)"},
                "sosyal_net": {"type": "number", "description": "TYT Sosyal net (0-20)"},
                "matematik_net": {"type": "number", "description": "TYT Matematik net (0-40)"},
                "fen_net": {"type": "number", "description": "TYT Fen net (0-20)"},
                "diploma_notu": {"type": "number", "description": "Diploma notu (50-100, varsayilan: 80)"},
            },
            "required": ["turkce_net", "matematik_net"],
        },
    },
    {
        "name": "eyotek_read",
        "description": (
            "Eyotek LMS'den ANLIK veri oku — CDP ile sayfa acip tablo cekim. "
            "Admin 'etut yoklamaya bak', 'bugun yoklama durumu', 'eyotek verisine bak' dediginde kullan. "
            "Mevcut kaynaklar: etut_ara, yoklama_kontrol, ogrenci_listesi, devamsizlik, rehberlik, sinav_sonuclari, "
            "etut_yoklama, etut_ogrenci_kontrol, ders_programi, ogretmen_programi. "
            "Sonuc: tablo satir/sutun olarak doner. SADECE OKUMA — yazma YAPMAZ. "
            "NOT: Bu basit/sabit kaynak okuyucu. Tarih filtresi, ogretmen filtresi, sinav adi gibi "
            "DETAYLI sorgular icin eyotek_query kullan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "page_key": {
                    "type": "string",
                    "description": "Kaynak adi: etut_ara | yoklama_kontrol | ogrenci_listesi | devamsizlik | rehberlik | sinav_sonuclari",
                },
                "max_rows": {
                    "type": "number",
                    "description": "Max satir (varsayilan: 20)",
                },
            },
            "required": ["page_key"],
        },
    },
    {
        "name": "sinav_sonuclari",
        "description": (
            "Bir sınavın TÜM öğrenci sonuçlarını Eyotek'ten ANLIK çek. "
            "Kullan ne zaman 'Apotemi sınav sonuçları', 'son denemenin sonuçları', "
            "'Bilgi Sarmal TG TYT-3 nasıldı', '3D TG TYT-3 sonuçları' gibi sorular gelirse. "
            "Bot: test-transferred sayfasında sınav adıyla arar → ⋯ Dinamik Liste tıklar → "
            "öğrenci bazlı net tablosu döner (Türkçe_NET, Mat_NET, Fizik_NET, vb.). "
            "DB'de sync edilmemiş YENİ sınavlar için kritik. ASLA exam-result KULLANMA."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sinav_adi": {
                    "type": "string",
                    "description": "Sınav adı (LIKE eşleşme): 'Apotemi' / 'Bilgi Sarmal TG TYT-3' / '3D TG'",
                },
                "max_rows": {
                    "type": "number",
                    "description": "Max öğrenci satırı (varsayılan 100)",
                },
                "date_from_days": {
                    "type": "number",
                    "description": "Son N gün sınavlarında ara (varsayılan 30)",
                },
            },
            "required": ["sinav_adi"],
        },
    },
    {
        "name": "ogrenci_drilldown",
        "description": (
            "Tek bir öğrencinin Eyotek profil alt sayfasından veri çek. "
            "Kullan ne zaman kullanıcı SPESIFIK bir öğrenci hakkında detay isterse: "
            "'Mahmut Taha'nın etütleri', 'Damla Keskin yazılı notları', 'Ezgi'nin davranış kayıtları', "
            "'Ali Kuçükuysal'ın MEB notları', 'Ayse Ecrin son sınav', 'Selin Coşkun rehberlik'. "
            "Bot ana liste sayfasından öğrenciyi bulur, ⋯ menüsünden alt sayfaya tıklar, tabloyu okur. "
            "Alt sayfa seçenekleri: etut | yoklama | odev | rehberlik | sinav | davranis | yazili | "
            "meb_notlari | hedef_soru | ders_programi | boy_kilo | etkinlik."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "student": {
                    "type": "string",
                    "description": "Öğrenci tanımlayıcısı: 'Mahmut Taha' (ad+soyad) | 'AKKAYA' (sadece soyad) | '182' (söz_no)",
                },
                "alt_sayfa": {
                    "type": "string",
                    "description": "Alt sayfa: etut | yoklama | odev | rehberlik | sinav | davranis | yazili | meb_notlari | hedef_soru | ders_programi | boy_kilo",
                },
                "max_rows": {
                    "type": "number",
                    "description": "Max satır (varsayılan 50)",
                },
            },
            "required": ["student", "alt_sayfa"],
        },
    },
    {
        "name": "eyotek_query",
        "description": (
            "Eyotek'ten AGENTIC veri sorgulama — dogal dilde soru, otomatik sayfa+filtre secimi. "
            "Kullan ne zaman kullanici tarih, ogretmen, ders, sinif, sinav adi gibi parametreli sorgu yapar: "
            "'dun hangi etutler vardi', '3 gun once yoklamalar', 'Apotemi sinav sonuclari', "
            "'Mehmet Donmez Nisan etutleri', 'Ali Veli devamsizliklari'. "
            "Cerebras 70B planner soruyu Eyotek sayfasina + filtreye cevirir, navigator data ceker. "
            "Sonuc: {plan, columns, rows, filters_applied, error_code}. "
            "SADECE OKUMA — yazma YAPMAZ. confidence < 0.4 ise plan basarisiz, error doner."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "Kullanicinin Turkce dogal dilde sorusu (orn: 'dun hangi etutler vardi')",
                },
                "max_rows": {
                    "type": "number",
                    "description": "Max satir (varsayilan: planner karari)",
                },
            },
            "required": ["question"],
        },
    },
    # C3 (Oturum 22) — Puan tahmin + Yokatlas üniversite önerisi
    {
        "name": "ogrenci_nereye_girebilir",
        "description": (
            "Öğrencinin mevcut AYT/TYT puanı ile girebileceği üniversite bölümlerini listele. "
            "3 kategoride döner: garanti (puan >> taban), ihtimal_yüksek (puan ~ taban), "
            "risk (puan < taban ama ±8 içinde). DB'de 36+ kayıt var (genişliyor). "
            "'Göktürk ne olur', 'netlerimle hangi üni', 'bu puanla nereye girerim' gibi sorularda KULLAN."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "soz_no": {
                    "type": "string",
                    "description": "Öğrenci ID (soz_no). Verilirse DB'den puan çekilir.",
                },
                "puan": {
                    "type": "number",
                    "description": "Direkt puan (öğrenci soz_no yoksa)",
                },
                "puan_turu": {
                    "type": "string",
                    "description": "SAY / SOZ / EA / DIL (default: SAY)",
                },
                "tolerans": {
                    "type": "number",
                    "description": "±puan aralığı (default: 15)",
                },
            },
        },
    },
    {
        "name": "hedef_bolum_ara",
        "description": (
            "Belirli bir bölümü (Tıp, Bilgisayar Müh, Fizik, Pilotaj vb.) veren üniversiteleri listele. "
            "Öğrenci 'Fizik bölümleri', 'Tıp için kaç net', 'Pilotaj var mı' dediğinde KULLAN. "
            "2025 default yıl + 200 sonuç + şehir/tür dağılımı. Query_analytics'ten ÖNCE bunu dene."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "bolum_adi": {
                    "type": "string",
                    "description": "Bölüm adı (ör: Tıp, Bilgisayar, Fizik, Pilotaj, Yapay Zeka)",
                },
                "puan_turu": {
                    "type": "string",
                    "description": "SAY / SOZ / EA / DIL (default: SAY)",
                },
                "yil": {
                    "type": "integer",
                    "description": "Yıl (default: 2025; veri yoksa otomatik en son yıla düşer)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max sonuç (default 200, Fizik 164, Tıp 190+ var)",
                },
                "sehir": {
                    "type": "string",
                    "description": "İl filtresi (İzmir, İstanbul vb. — opsiyonel, Neo sorarsa)",
                },
                "tur": {
                    "type": "string",
                    "description": "Devlet / Vakıf filtresi — opsiyonel",
                },
            },
            "required": ["bolum_adi"],
        },
    },
    # 22.1n-toplanti #4 — Rehber brief (tek çağrı)
    {
        "name": "counsellor_brief",
        "description": (
            "REHBER için tek çağrıda öğrenci özet + veli mesaj taslağı + öncelikli konular + "
            "son negatif sinyal + son rehberlik notu. "
            "Rehber 'Ali'yi anlat', 'Saniye için brief ver', 'velisine yazacak mesaj hazırla' dediğinde KULLAN. "
            "3 ayrı tool çağrısı yerine TEK çağrı — ~5sn cevap."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"soz_no": {"type": "integer"}},
            "required": ["soz_no"]
        }
    },
    # 22.1n-toplanti #5 — Öğretmen class brief
    {
        "name": "class_brief",
        "description": (
            "ÖĞRETMEN için sınıf özeti — bugünkü derse hazırlık. "
            "Öğrenci sayısı + son 30gün ders ortalaması + sınıfın en zayıf konuları + pedagojik öneri. "
            "Öğretmen 'bugün 11 SAY'a Matematik var, sınıf nasıl?' derse KULLAN."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sinif": {"type": "string", "description": "'11 SAY', '12 SAY NXT' vb."},
                "ders": {"type": "string", "description": "Matematik/Fizik/... (opsiyonel)"},
                "tarih": {"type": "string", "description": "ISO date (opsiyonel)"}
            },
            "required": ["sinif"]
        }
    },
    # 22.1n-toplanti (Bot #3): Tercih listesi taslağı
    {
        "name": "tercih_listesi_tasla",
        "description": (
            "Öğrencinin AYT yerleşme puanına göre 24 tercihli otomatik taslak. "
            "YÖK Atlas taban puan verisinden 3 kategori karışımı: "
            "güvenli (-20/-5 puan), hedef (±5), zorlayıcı (+5/+20). "
            "'Tercih listesi yap', 'nereye girebilirim' dediğinde KULLAN. "
            "Ham liste — öğrenciye öneri sun, 'mutlaka oraya gir' DEME."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "soz_no": {"type": "integer"},
                "puan_turu": {"type": "string", "description": "SAY/EA/SOZ/DIL (default SAY)"}
            },
            "required": ["soz_no"]
        }
    },
    # 22.1n-neo — Ogretmen brans analiz tool (Merve 65-mesaj orneginden)
    {
        "name": "branch_zayif_konu",
        "description": (
            "Ogretmen brans analiz: bir dersin sinif/kurum genelinde konu bazli ortalama basarisi ve "
            "o dersteki en zayif 5 ogrenci. Ogretmen 'brans analizi', 'sinifimda zayif konular', "
            "'en zayif 20 ogrenci' dediginde KULLAN — tek cagri, 8 query_analytics zinciri yerine. "
            "Eger ogretmen belirli siniflari tarif ederse sinif_list parametresiyle filtrele."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ders": {"type": "string", "description": "Ders adi (fizik, biyoloji, kimya, matematik, turkce, tarih vb.)"},
                "sinif_list": {"type": "array", "items": {"type": "string"},
                               "description": "Opsiyonel sinif kodlari: ['12 SAY A', '12 SAY B']"}
            },
            "required": ["ders"]
        }
    },
    # 22.1n-toplanti #6 — Transfer failure detection
    {
        "name": "transfer_failure_analiz",
        "description": (
            "Öğrencinin konu başarısı ile sınav performansı arasındaki 'TRANSFER GAP' tespit. "
            "Öğrenci 'test kitabında yapıyorum denemede yapamıyorum' derse KULLAN. "
            "topic_tracker vs student_exams cross-reference — konu %70 ama sınav %40 ise gap var."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"soz_no": {"type": "integer"}},
            "required": ["soz_no"]
        }
    },
    # 22.1n-toplanti #2 — Plan State (diff update)
    {
        "name": "plan_kaydet",
        "description": (
            "Üretilen çalışma planını KALICI olarak kaydet (student_active_plans tablosu). "
            "build_study_plan_context ile plan üretince MUTLAKA bu tool'u da çağır — sonraki düzenlemeler "
            "diff olur (tüm plan yeniden yazılmaz). YAZ KAMPI için kritik."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "soz_no": {"type": "integer"},
                "plan_json": {"type": "object", "description": "Plan yapısı — gunler: {pazartesi: {...}, ...} formatında"},
                "plan_text": {"type": "string", "description": "Plan markdown metin hali (arşiv için)"},
                "hedef_ozet": {"type": "string"},
                "toplam_saat": {"type": "integer"}
            },
            "required": ["soz_no", "plan_json"]
        }
    },
    {
        "name": "plan_getir",
        "description": (
            "Öğrencinin aktif çalışma planını getir. Öğrenci 'planımı göster', 'haftasonumu yaz' gibi "
            "TAKIP mesajı atınca ÖNCE bu tool'u çağır — varsa planı oku. "
            "Yoksa yeni plan üretmeye geç (build_study_plan_context)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"soz_no": {"type": "integer"}},
            "required": ["soz_no"]
        }
    },
    {
        "name": "plan_gun_guncelle",
        "description": (
            "Çalışma planında TEK GÜNÜ güncelle (diff update). "
            "Öğrenci 'perşembeyi sil', 'cumartesi ders ekle' dediğinde kullan. "
            "Tüm planı yeniden üretmek YASAK — sadece o gün değişir."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "soz_no": {"type": "integer"},
                "gun": {"type": "string", "description": "pazartesi/salı/çarşamba/perşembe/cuma/cumartesi/pazar"},
                "yeni_icerik": {"type": "object", "description": "O günün yeni içeriği — saat, konular, vb."}
            },
            "required": ["soz_no", "gun", "yeni_icerik"]
        }
    },
    # 25.14h — Calismam panel (gunluk program) yazma tool
    {
        "name": "add_to_student_program",
        "description": (
            "Öğrencinin Çalışmam panelindeki günlük programa yeni bir blok ekle. "
            "Öğrenci 'evet ekle', 'matematik koy 16:00', 'yarın 09:00 fizik ekle' gibi ONAY/talep verince KULLAN. "
            "ÖNCE öneri sun ('16:00-17:00 Matematik ekleyeyim mi?'), öğrenci ONAYLAYINCA bu tool'u çağır. "
            "ACL: sadece kendi soz_no'su (admin override). Yanıtta 'eklendi' onayı + Çalışmam linki ver. "
            "plan_date YYYY-MM-DD formatı (default bugün). start_time/end_time HH:MM."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "soz_no": {"type": "integer", "description": "Öğrenci soz_no (kendi)"},
                "title": {"type": "string", "description": "Blok başlığı, örn 'Matematik — Limit'"},
                "start_time": {"type": "string", "description": "Başlangıç saati HH:MM, örn '16:00'"},
                "end_time": {"type": "string", "description": "Bitiş saati HH:MM, opsiyonel"},
                "plan_date": {"type": "string", "description": "YYYY-MM-DD, default bugün"},
                "ders": {"type": "string", "description": "Ders adı (Matematik, Fizik...), opsiyonel"},
                "konu": {"type": "string", "description": "Spesifik konu (Limit, Kuvvet...), opsiyonel"},
                "notes": {"type": "string", "description": "Not, opsiyonel"}
            },
            "required": ["soz_no", "title", "start_time"]
        }
    },
    # 22.1n-bug8 — Puan Tahmin + Hedef Analiz
    {
        "name": "puan_tahmin",
        "description": (
            "Öğrencinin mevcut TYT+AYT trendinden YKS puanını tahmin et. "
            "Son 3 deneme ortalaması + trend yönü (artış/stabil/düşüş) ile YKS yerleşme puanı tahmini. "
            "Öğrenci 'puanim ne olacak', 'şu an kaç puan yapıyorum', 'tahmini puanım' dediğinde KULLAN. "
            "Sınava kalan gün + gelişim trendi de dahil."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "soz_no": {"type": "integer", "description": "Öğrenci soz_no"},
            },
            "required": ["soz_no"],
        },
    },
    {
        "name": "hedef_puan_analiz",
        "description": (
            "Hedef puan için öğrencinin hangi derslerde kaç net daha kazanması gerektiğini hesapla. "
            "Öğrenci 'Bilgisayar Müh için kaç net yapmalıyım', 'ODTÜ Tıp'a gidebilir miyim' dediğinde KULLAN. "
            "Önce puan_tahmin veya hedef_bolum_ara ile hedef puanı öğren, sonra bu tool'la net gap analizi yap."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "soz_no": {"type": "integer"},
                "hedef_puan": {"type": "number", "description": "Hedef yerleşme puanı (ör: 480)"},
                "alan": {"type": "string", "description": "SAY / EA / SOZ / DIL (default: SAY)"},
            },
            "required": ["soz_no", "hedef_puan"],
        },
    },
    # Oturum 22.1m — Öğrenci Peer Benchmark (anonim kiyas)
    {
        "name": "ogrenci_peer_kiyas",
        "description": (
            "Öğrenciyi benzer net aralığındaki aynı alan öğrencileriyle ANONIM kıyasla. "
            "Peer sayısı, peer'lerin en çok çalıştığı konular, güçlü oldukları alanlar döner. "
            "ASLA öğrenci adı veya ID paylaşılmaz. "
            "Öğrenci 'benim gibi ne çalışılıyor', 'başkaları ne yapıyor' dediğinde KULLAN. "
            "Motivasyon + pedagojik yön için değerli."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "soz_no": {"type": "integer", "description": "Öğrenci soz_no"},
                "tolerans_net": {"type": "integer", "description": "Net aralığı (±, default 10)"},
            },
            "required": ["soz_no"],
        },
    },
    # Oturum 22.1l — Öğretmen Eskalasyon (öğrenci etut talebi chain)
    {
        "name": "hazirla_etut_talebi",
        "description": (
            "Öğrenci 'X dersi etut istiyorum / X hocadan etüt' dediğinde: "
            "öğrencinin son 3 deneme + zayıf konu + ilgili branşta uygun hoca+müsait saat "
            "önerilerini hazırla. Hocaya gönderilecek mesaj taslağını döner. "
            "NOT: TASLAK DÖNER — hocaya direkt YOLLAMAZ (Neo onayı zorunlu). "
            "Admin/Müdür/Rehber bu taslağı görüp 'gönder' dediğinde send_wa_message ile yollar. "
            "Öğrenci için talep student_insights'a kaydedilir."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "soz_no": {"type": "integer", "description": "Öğrenci soz_no"},
                "ders": {"type": "string", "description": "Fizik/Kimya/Matematik/Türkçe vb."},
                "note": {"type": "string", "description": "Öğrencinin eklediği not (opsiyonel)"},
            },
            "required": ["soz_no", "ders"],
        },
    },
    # Oturum 22.1h — System Self-Awareness (KALDIGIM.md canli okuma)
    {
        "name": "get_recent_system_updates",
        "description": (
            "KALDIGIM.md dosyasini GERCEK ZAMANLI okur, son oturum/guncelleme ozetini ver. "
            "Neo 'ne guncelleme aldın', 'son durum', 'ne yaptın yarim saat önce', 'en son ne değişti', "
            "'sisteme ne eklendi' dediginde KULLAN. Deployments tablosu SADECE bridge restart'ta guncellenir, "
            "bu tool dakika cinsinden guncel verir. "
            "Admin/mudur/yonetim icin — ogrenci/veli/kayitsiz için teknik detay paylasma kurallari var."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "max_sessions": {
                    "type": "integer",
                    "description": "Kac oturum gecmisi getirilsin (default 3, max 5)",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Toplam icerik limit (default 4000, max 8000)",
                },
            },
        },
    },
    # Oturum 25.29 — BLUEPRINT.md mimari farkindalik
    {
        "name": "get_blueprint_section",
        "description": (
            "BLUEPRINT.md dosyasini GERCEK ZAMANLI okur, mimari kapasiteyi gosterir. "
            "Kullanim:\n"
            "- 'Mimari nedir / kapasite ne / X bolumu nasil calisir' sorularinda BU TOOL'u kullan\n"
            "- 'BLUEPRINT'te ne diyoruz / hangi mimari kararlar var' sorularinda KULLAN\n"
            "- Atlas oneri vermeden once 'bu zaten mimari karari mi' kontrolu icin KULLAN\n"
            "section parametresi: int (1-17) veya keyword (orn 'LLM Routing', 'Eyotek')\n"
            "section bos verilirse → tum bolum listesi doner. KALDIGIM (oturum bazli) ile "
            "BLUEPRINT (mimari) BIR ARADA bot'a inject edilmistir, bu tool DETAY almak icin."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "description": (
                        "Bolum no (1-17) veya keyword (orn '3' veya 'LLM Routing'). "
                        "Bos birakilirsa tum bolum listesi doner."
                    ),
                },
            },
        },
    },
    # Oturum 22.1 — Atlas Self-Observing Trend
    {
        "name": "get_atlas_trend",
        "description": (
            "Atlas self-observing sistemin trend raporu. SADECE Neo (admin, 905051256802). "
            "Mudur/yonetim/rehber/ogretmen KAPALI — sistem self-observation kategorisi (alert_log, usage_log gibi). "
            "Son N günün özeti: toplam sorun, açık/çözülen/regresyon, kategori dağılımı, "
            "günlük yeni sorun trendi, en çok tekrar eden 5 sorun. "
            "Neo 'atlas trend', 'atlas rapor', 'son 30 gün sorunlar' dediğinde KULLAN."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Kaç günlük trend (default: 30)",
                },
            },
        },
    },
    # ══════════════════════════════════════════════════════════════════════
    # 22.1n-neo: FINANS TOOLS — SADECE NEO erisimi (is_finans_authorized guard)
    # Diger tum roller (admin dahil phone check ile) REDDEDILIR.
    # ══════════════════════════════════════════════════════════════════════
    {
        "name": "finans_ozet",
        "description": (
            "KURUM GENELI FINANSAL OZET — Sadece Neo icin. "
            "Toplam borc, tahsilat, geciken tutar, borclu ogrenci sayisi. "
            "Son 30 gun tahsilat ozetini de doner. Neo 'kurum finans nasil', "
            "'bu ay ne kadar tahsil ettik', 'toplam borc ne durumda' derse KULLAN."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "ogrenci_borc_detay",
        "description": (
            "Tek ogrencinin tam borc dokumani — Sadece Neo icin. "
            "Taksit listesi (odenen/odenmemis), yapilan odeme gecmisi, kalan bakiye. "
            "Neo 'Ali Demir ne durumda', '125 soz_no'lu ogrenci borcu' derse KULLAN."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "soz_no": {"type": "integer", "description": "Ogrenci soz_no"},
            },
            "required": ["soz_no"],
        },
    },
    {
        "name": "geciken_odemeler",
        "description": (
            "Geciken odemeler listesi — Sadece Neo. N gunden fazla geciken ogrenciler, "
            "en cok gecikene gore sirali. Neo 'kimler gecikti', 'borcu 30 gun geciken kimler' derse KULLAN."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "min_gun": {"type": "integer", "description": "Min gecikme gun sayisi (default: 0)"},
                "limit": {"type": "integer", "description": "Max sonuc (default: 50)"},
            },
        },
    },
    {
        "name": "aylik_tahsilat_trend",
        "description": (
            "Son N ay tahsilat trendi (grafik icin) — Sadece Neo. "
            "Neo 'son 6 ay tahsilat trendi', 'aylik tahsilat grafigi' derse KULLAN."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ay_sayisi": {"type": "integer", "description": "Kac ay geriye (default: 12, max: 60)"},
            },
        },
    },
    {
        "name": "veli_borc_bildirim_taslak",
        "description": (
            "Veli icin borc hatirlatma mesaj TASLAGI uret — Sadece Neo. "
            "DIKKAT: SADECE TASLAK — otomatik GONDERILMEZ. "
            "Neo taslagi goruntuler, onaylarsa ayri bir tool ile gonderilir. "
            "Neo 'X ogrencinin velisine hatirlatma hazirla' derse KULLAN."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "soz_no": {"type": "integer", "description": "Ogrenci soz_no"},
                "mesaj_tipi": {
                    "type": "string",
                    "enum": ["nazik", "resmi", "son_uyari"],
                    "description": "Ton secimi (default: nazik)",
                },
            },
            "required": ["soz_no"],
        },
    },
    {
        "name": "finans_audit_rapor",
        "description": (
            "Son N saat finans erisim audit log'u — Sadece Neo. "
            "Basarili/bloklanan sorgu kirilimi, olagandisi erisim tespiti. "
            "Neo 'finans erisim audit', 'kim finans sordu' derse KULLAN."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "saat": {"type": "integer", "description": "Kac saat geriye (default: 24)"},
            },
        },
    },
    {
        "name": "sezon_kiyasla",
        "description": (
            "3 SEZON finansal karsilastirma — Sadece Neo. "
            "2024.25 / 2025.26 / 2026.27 yan yana: ogrenci sayisi, kayit fiyati, "
            "tahsilat, tahsilat orani + sezondan sezona buyume yuzdesi. "
            "Neo 'sezon kiyasla', 'yildan yila nasil', 'buyuyoruz mu' derse KULLAN."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "aylik_borc_detay",
        "description": (
            "Ay bazli geciken odeme detayi — Sadece Neo. "
            "Belirli bir ayin borclulari (Kasim 2025'te kim borcluydu) veya tum aylarin toplami. "
            "Neo 'Kasim ayi borclulari', 'hangi ay kim borclu', 'bu ay geciken' derse KULLAN."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ay": {"type": "string", "description": "YYYY-MM format (ornek '2025-11'), bos ise tum aylar"},
            },
        },
    },
    # 23 Nisan Jarvis Paket
    {
        "name": "deep_research_paket",
        "description": (
            "Öğrenci bir konuyu TAM OLARAK öğrenmek istediğinde kullan. "
            "Tek seferde: RAG konu anlatımı + çıkmış soru listesi + "
            "spaced repetition kaydı + adaptive difficulty analizi döndürür. "
            "'X konusunu derinlemesine çalışmak istiyorum' dediğinde."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "soz_no": {"type": "integer"},
                "konu": {"type": "string"},
                "ders": {"type": "string"},
            },
            "required": ["soz_no", "konu"],
        },
    },
    {
        "name": "odev_ekle",
        "description": (
            "Öğretmen/rehber öğrenciye ödev verir. Öğrenci ilgili teslim tarihinde "
            "(sabah 08:00) WP hatırlatması alır."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ogrenci_soz_no": {"type": "integer"},
                "odev_tanim": {"type": "string"},
                "ders": {"type": "string"},
                "konu": {"type": "string"},
                "teslim_gun_sonra": {"type": "integer", "description": "Kaç gün sonra (default 1)"},
            },
            "required": ["ogrenci_soz_no", "odev_tanim"],
        },
    },
    {
        "name": "ogretmen_brief",
        "description": (
            "Öğretmen için hazır sınıf brief'i: performans, risk öğrenci, kurumsal zayıf konu. "
            "Öğretmen 'bugünkü özet', 'sınıfım nasıl' derse KULLAN."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"ogretmen_ad": {"type": "string"}},
            "required": ["ogretmen_ad"],
        },
    },
    {
        "name": "youtube_oner",
        "description": (
            "[DEPRECATED önerisi: konu_kaynak_paketi tercih et — daha zengin]. "
            "Sadece tek bir konuda YouTube video listesi istendiğinde. "
            "Whitelist kanallardan (Tonguç, Hocalara Geldik, MEB, OGM, Khan Academy...) "
            "sonuç döner. Whitelist dışı ASLA. Uygun video bulunmazsa boş döner."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"konu": {"type": "string"}},
            "required": ["konu"],
        },
    },
    {
        "name": "konu_kaynak_paketi",
        "description": (
            "ÇOKLU KAYNAK PAKETİ — öğrenci EXPLICIT olarak kaynak/video/alternatif anlatım "
            "talep ettiğinde KULLAN. "
            "\n\n"
            "⚠️ ÇAĞRI KOŞULLARI (sadece bunlardan biri olursa çağır):\n"
            "  • 'video izlemek istiyorum' / 'video var mı' / 'izleyebileceğim bir şey'\n"
            "  • 'başka kaynak öner' / 'farklı yerden bakmak istiyorum'\n"
            "  • 'nereden çalışayım' / 'PDF / soru bankası link'\n"
            "  • 'Wikipedia'da/OGM'de var mı' / 'resmî kaynak'\n"
            "\n"
            "❌ ÇAĞIRMA: Öğrenci sadece konuyu anlamak istiyorsa — ÖNCE DİYALOG ile "
            "Sokrates/Feynman tarzı anlat, soru sor, karşı soru bekle. Konuyu sen "
            "anlatırken ortasında kaynak atma. Bot kendi kendine 'al sana playlist' DEMEZ.\n"
            "\n"
            "Paket içeriği (hepsi paralel gelir):\n"
            "  1. OGM Materyal (MEB resmi) — her zaman en güvenilir, vurgula\n"
            "  2. YouTube 3-5 farklı kanal (whitelist) — playlist hissi\n"
            "  3. Wikipedia (tr → en fallback) — ansiklopedik bakış\n"
            "  4. FermatAI dâhili müfredat notları — konu anlatımı varsa\n"
            "\n"
            "Dönen 'sunum_mesaji' öğrenciye direkt gönderilebilir — çoklu kaynak tek mesajda."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "konu": {"type": "string", "description": "Konu adı (örn. 'Fotoelektrik Olayı', 'Türev')"},
                "ders": {
                    "type": "string",
                    "description": "Ders (Fizik/Matematik/Kimya/Biyoloji/Tarih/Turkce/Cografya/Felsefe/TDE). Belli değilse boş bırak.",
                },
                "youtube_adet": {"type": "integer", "description": "YouTube video sayısı (default 4, max 6)"},
                "wikipedia_adet": {"type": "integer", "description": "Wikipedia sonuç sayısı (default 2)"},
            },
            "required": ["konu"],
        },
    },
    {
        "name": "plani_takvime_ekle",
        "description": (
            "Öğrencinin çalışma planını Google Calendar'a ekler. Öğrenci "
            "'takvime ekle', 'plani takvime işle', 'kendi takvimime at' derse KULLAN. "
            "Öğrencinin email'i kayıtlıysa DAVET gönderir (kendi Gmail'ine). "
            "ÖNCE çalışma planı oluştur (build_study_plan_context + Claude yorum), "
            "SONRA günlük-saatli event dizisi olarak takvime ekle."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "soz_no": {"type": "integer", "description": "Öğrenci soz_no"},
                "ogrenci_ad": {"type": "string"},
                "plan_events": {
                    "type": "array",
                    "description": "Event listesi",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tarih_iso": {"type": "string", "description": "ISO format: 2026-04-24T14:00:00"},
                            "ders": {"type": "string"},
                            "konu": {"type": "string"},
                            "sure_dk": {"type": "integer", "description": "Süre dk (default 60)"},
                            "aciklama": {"type": "string"},
                        },
                        "required": ["tarih_iso", "ders"],
                    },
                },
            },
            "required": ["soz_no", "ogrenci_ad", "plan_events"],
        },
    },
    {
        "name": "etut_takvime_ekle",
        "description": (
            "REHBER ÖĞRETMEN tool'u. Rehber Eyotek'te etüt yazdıktan sonra bilgiyi "
            "Google Calendar'a ekler. Rehber 'takvime işle', 'bu etüt takvime düşsün' derse KULLAN. "
            "Öğrenci ve branş öğretmenine WP quick-add linki döner (email gerekmez). "
            "UYARI: Branş öğretmeni bu tool'u ÇAĞIRAMAZ — branş etüt yazmaz. "
            "Branş için: 'ogretmen_etut_onerisi' (tavsiye) veya 'ogretmen_etut_takvimim' (kendi takvimi)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ogrenci_soz_no": {"type": "integer"},
                "ogrenci_ad": {"type": "string"},
                "ogretmen_ad": {"type": "string"},
                "ders": {"type": "string"},
                "konu": {"type": "string"},
                "tarih_iso": {"type": "string"},
                "sure_dk": {"type": "integer"},
            },
            "required": ["ogrenci_soz_no", "ogretmen_ad", "ders", "tarih_iso"],
        },
    },
    # ═════════════════════════════════════════════════════════════════════
    # 23 NİSAN — Branş Öğretmeni Yetki Düzeltmesi (Neo kararı)
    # Branş öğretmeni ETUT YAZMAZ. Bu iki tool sadece branş öğretmeni içindir.
    # ═════════════════════════════════════════════════════════════════════
    {
        "name": "ogretmen_etut_takvimim",
        "description": (
            "BRANŞ ÖĞRETMENİ tool'u. Kendi etut takvimini listeler (son gün + önümüzdeki günler) "
            "ve her etüt için Google Calendar quick-add linki üretir — öğretmen linke tıklar "
            "ve kendi Gmail takvimine ekler. Öğretmen 'etut takvimim', 'bu hafta kime ne etüt "
            "vereceğim', 'etütlerimi takvime at' derse KULLAN. "
            "Sadece READ-ONLY — öğretmen etüt YAZAMAZ, sadece var olan etutlerini görür."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ogretmen_ad": {
                    "type": "string",
                    "description": "Öğretmenin ad+soyad (caller profile'dan)",
                },
                "gun": {
                    "type": "integer",
                    "description": "Kaç gün ileriye bak (default 7)",
                },
            },
            "required": ["ogretmen_ad"],
        },
    },
    {
        "name": "ogretmen_etut_onerisi",
        "description": (
            "BRANŞ ÖĞRETMENİ tool'u. Öğretmen bir öğrenciye etut yapılmasını öneriyor — "
            "bu tool öneriyi rehber öğretmene iletir (Eyotek'te etut YAZMAZ). Rehber "
            "günlük/haftalık brief'te bu önerileri görür, uygun bulursa Eyotek'te gerçek "
            "etutu kendi yazar. Öğretmen 'X öğrenciye fizik etüt lazım', 'bu çocuğa etut "
            "yazılmalı', 'rehbere söyler misin' derse KULLAN. "
            "Branş öğretmeni Eyotek'te etüt YAZAMAZ — bu tool tavsiye/rapor mekanizmasıdır."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ogretmen_ad": {"type": "string", "description": "Öneriyi yazan öğretmen (caller profile'dan)"},
                "soz_no": {"type": "integer", "description": "Öğrenci soz_no"},
                "ogrenci_ad": {"type": "string", "description": "Öğrenci ad+soyad"},
                "ders": {"type": "string", "description": "Etüt önerilen ders (Fizik, Mat vb.)"},
                "konu": {"type": "string", "description": "Spesifik konu (opsiyonel — 'Kaldırma Kuvveti')"},
                "aciklama": {
                    "type": "string",
                    "description": "Gerekçe — neden etut öneriliyor (test sonucu, kavram eksikliği, motivasyon)",
                },
                "oncelik": {
                    "type": "string",
                    "enum": ["dusuk", "normal", "yuksek", "acil"],
                    "description": "Öncelik seviyesi — default 'normal'",
                },
                "onerilen_gun": {
                    "type": "string",
                    "description": "Serbest metin öneri (örn 'bu hafta persembe 14:00 uygun')",
                },
            },
            "required": ["ogretmen_ad", "ders"],
        },
    },
    # ═════════════════════════════════════════════════════════════════════
    # 23 NİSAN — Tercih Robotu (YKS sonrası dönem asistanı)
    # ═════════════════════════════════════════════════════════════════════
    {
        "name": "tercih_profili_kaydet",
        "description": (
            "TERCİH ROBOTU tool'u. Öğrenci tercih profilini UPSERT eder. Her alan "
            "opsiyonel — konuşma ilerledikçe parça parça topla. Öğrenci 'sıralamam 15000', "
            "'Ankara'da okumak isterim', 'Bilgisayar Mühendisliği hedefim' derse KULLAN. "
            "Dönüş: tamlik_yuzde + eksik_alanlar (bir sonraki soruyu buna göre sor)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "soz_no": {"type": "integer"},
                "tyt_ham": {"type": "number", "description": "TYT ham puan"},
                "ayt_ham": {"type": "number", "description": "AYT ham puan"},
                "yerlesme_puani": {"type": "number", "description": "Yerleşme puanı (OBP dahil)"},
                "puan_turu": {
                    "type": "string",
                    "enum": ["SAY", "EA", "SOZ", "DIL", "TYT"],
                    "description": "SAY/EA/SOZ/DIL (Türkçe karakter gerekli değil)",
                },
                "siralama": {"type": "integer", "description": "Puan türündeki sıralama"},
                "tercih_sehirler": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tercih şehirleri listesi: ['Ankara','Istanbul','Izmir']",
                },
                "tercih_bolumler": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tercih bölümleri: ['Bilgisayar Mühendisliği','Endüstri Mühendisliği']",
                },
                "kacinmak_istedigi": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Kaçınmak istediği bölüm anahtar kelimeler: ['Hukuk']",
                },
                "burs_durumu": {
                    "type": "string",
                    "enum": ["tam_burs", "yuzde_75", "yuzde_50", "yuzde_25", "ucretli", "belirsiz"],
                },
                "aile_butce_ust": {"type": "integer", "description": "Aile yıllık bütçe üst sınırı TL"},
                "sehir_kisiti_katalik": {
                    "type": "boolean",
                    "description": "True: SADECE tercih_sehirler'deki şehirleri dikkate al. False: öncelikli ama kısıtlama yok",
                },
                "ozel_not": {"type": "string", "description": "Serbest not (aile görüşü, özel durum)"},
            },
            "required": ["soz_no"],
        },
    },
    {
        "name": "tercih_profili_getir",
        "description": (
            "TERCİH ROBOTU tool'u. Öğrencinin mevcut tercih profilini okur. "
            "Konuşmaya başlarken önce buraya bak — profil var mı, hangi alanlar eksik?"
        ),
        "input_schema": {
            "type": "object",
            "properties": {"soz_no": {"type": "integer"}},
            "required": ["soz_no"],
        },
    },
    {
        "name": "tercih_listesi_uret",
        "description": (
            "TERCİH ROBOTU tool'u. Öğrencinin profiline + YÖK Atlas (universite_taban, "
            "35.584 kayıt) verisine göre 18-24 satırlık taslak tercih listesi üretir. "
            "Bantlar: 3 garanti + 6 orta + 6 hedef + 3 hayal. "
            "ÖNKOŞUL: Profil doldurulmuş olmalı (en az siralama + puan_turu + tercih_bolumler). "
            "Dönüş: liste [{strateji, universite, bolum, sehir, tur, taban_puan, siralama, ...}]"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "soz_no": {"type": "integer"},
                "max_satir": {"type": "integer", "description": "Default 24. Min 6."},
            },
            "required": ["soz_no"],
        },
    },
    {
        "name": "bolum_karsilastir",
        "description": (
            "TERCİH ROBOTU tool'u. 2-5 bölümü YÖK Atlas verisine göre kıyaslar "
            "(taban puan aralığı, sıralama, üniversite sayısı, şehir çeşitliliği). "
            "Öğrenci 'endüstri mi makine mi?' gibi sorularda KULLAN."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "bolum_listesi": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Kıyaslanacak bölüm adları (2-5 adet)",
                },
                "puan_turu": {
                    "type": "string",
                    "enum": ["SAY", "EA", "SOZ", "DIL"],
                },
            },
            "required": ["bolum_listesi"],
        },
    },
    {
        "name": "get_lgs_konu_durumu",
        "description": (
            "LGS öğrencisi (7. veya 8. sınıf) için konu durumu + kalan gün + öneri. "
            "LGS tarih: 7 Haziran 2026. Öğrenci 'zayıf konularım', 'LGS'ye kaç gün', "
            "'müfredatım ne' derse KULLAN. Dönen data'da: 6 ders (Türkçe, Matematik, "
            "Fen Bilimleri TEK BİRLEŞİK, İnkılap, Din, İngilizce), her dersin müfredat + "
            "durumu (konu listesi + hata yüzdesi), son sınav toplamı, kalan gün, öneri. "
            "ÖNEMLI: LGS'de Fen Bilimleri TEK ders (Fizik/Kimya/Biyoloji AYRI DEĞİL). "
            "YKS öğrencisi değilse is_lgs=False döner."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"soz_no": {"type": "integer"}},
            "required": ["soz_no"],
        },
    },
    {
        "name": "ders_konu_dagilimi_raporu",
        "description": (
            "8 yıllık çıkmış soru konu dağılımı + 2026 tahmini raporu. Öğretmen 'Fizik AYT "
            "son 8 yıl konu dağılımı, hangi konu kaç kez çıkmış, bu yıl ne gelebilir' gibi "
            "sorduğunda KULLAN. Dönen data'da: konu_dagilimi (her konu için toplam, yıllar, "
            "2026 tahmin skoru), yil_bazli_sayilar, chart_konu_agirlik (yığılmış çubuk), "
            "chart_yil_trend (çizgi). Claude bu veriyi arşivlenebilir kaliteli detaylı rapora "
            "dönüştürür — ```chart blokları ekler, her konu için yorum yazar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ders": {
                    "type": "string",
                    "description": "Ders adı: Fizik, Matematik, Kimya, Biyoloji, Turkce, TDE, Tarih, Cografya, Felsefe",
                },
                "sinav_turu": {
                    "type": "string",
                    "enum": ["TYT", "AYT"],
                    "description": "TYT veya AYT — default AYT",
                },
                "yil_bas": {"type": "integer", "description": "Başlangıç yılı (default 2018)"},
                "yil_bit": {"type": "integer", "description": "Bitiş yılı (default 2025)"},
            },
            "required": ["ders"],
        },
    },
    {
        "name": "tercih_donemi_durum",
        "description": (
            "TERCİH ROBOTU tool'u. Tercih robotu modu aktif mi? YKS tarihleri timeline — "
            "TYT/AYT/Sonuç/Tercih dönemi/Yaz kampı. 'Tercih ne zaman başlıyor', 'sonuç "
            "ne zaman', 'kaç gün kaldı' sorularında KULLAN."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    # 22 Nisan: Career Info — meslek/bolum tanitim (Fix 1 kalici cozumu)
    {
        "name": "get_career_info",
        "description": (
            "Meslek/bolum tanitim bilgisi getir. Ogrenci 'X mühendisliği ne iş yapar', "
            "'tıp okumak istiyorum', 'eczacılık kaç yıl' gibi sorularda KULLAN. "
            "Önceden hazırlanmış 13 ana meslek/bölüm: puan aralığı, süre, iş alanları, "
            "maaş, avantaj/dezavantaj. KAYNAKSIZ uydurma yapma — bu tool'dan çek, "
            "dönen veriyi doğal dilde öğrenciye aktar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "meslek": {
                    "type": "string",
                    "description": "Meslek/bölüm adı (Kimya Mühendisliği, Tıp, Hukuk vb.)",
                },
            },
            "required": ["meslek"],
        },
    },
    # Oturum Mentenans (21 Nisan): Pedagojik sablon erisimi — Claude talep edebilir
    {
        "name": "get_pedagojik_sablon",
        "description": (
            "Pedagojik sablon kutuphanesinden belirli kategori/rol icin hazir metin getir. "
            "Ogrenci veya ogretmene gonderecegin bir destek/onerme mesajini uretirken "
            "'nasil soyleyeyim' kilavuzu olarak kullan. "
            "Kategoriler: SINAV_YAKIN, DENEME_SONRASI, HEDEF_BELIRLEME, "
            "CALISMA_PLANI_FEEDBACK, VELI_ILETISIM, KONU_GERI_BILDIRIM, "
            "OGRETMEN_YONLENDIRME, ZAMAN_YONETIMI_KRIZ, DERS_CAKISMA_COZUM, KRIZ_DESTEK."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "kategori": {
                    "type": "string",
                    "description": "Sablon kategorisi (buyuk harfli slug)",
                },
                "rol": {
                    "type": "string",
                    "enum": ["ogrenci", "ogretmen", "veli", "rehber", "admin", "mudur"],
                    "description": "Hedef rol (default ogrenci)",
                },
            },
            "required": ["kategori"],
        },
    },
    # 22.1n-neo FAZ 2 EKSTRA: Üçgen Model (Öğretmen + Veli pedagojik ortak)
    {
        "name": "ogretmen_pedagojik_brief",
        "description": (
            "Öğretmen için öğrenci hakkında PEDAGOJİK ÖNERİ briefi. "
            "Dweck, CLT, VARK, SDT gibi eğitim bilimleri literatürü + öğrenci datasını "
            "sentezleyip pratik öneri döner. "
            "Öğretmen 'Damla hakkında öneri', 'Ahmet için nasıl yaklaşayım' derse KULLAN."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"soz_no": {"type": "integer", "description": "Ogrenci soz_no"}},
            "required": ["soz_no"],
        },
    },
    {
        "name": "veli_pedagojik_rehberlik",
        "description": (
            "Veliye eğitim psikolojisi temelli REHBERLİK metni. "
            "Temalar: motivasyon / kaygi / calisma / ekran / iletisim / genel. "
            "Veli 'çocuğum çalışmıyor', 'kaygısı var', 'telefondan çıkmıyor' derse KULLAN. "
            "SDT, CBT, Seligman, Dweck gibi literatürü pratik dille aktarır."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "soz_no": {"type": "integer", "description": "Ogrenci soz_no"},
                "tema": {
                    "type": "string",
                    "enum": ["motivasyon", "kaygi", "calisma", "ekran", "iletisim", "genel"],
                    "description": "Rehberlik temasi",
                },
            },
            "required": ["soz_no"],
        },
    },
    {
        "name": "ogrenci_sezon_gecmisi",
        "description": (
            "Bir ogrencinin 3 sezonluk finansal gecmisi — Sadece Neo. "
            "Soz_no ile ogrencinin 2024.25 + 2025.26 + 2026.27 donemlerindeki "
            "kayit fiyati, tahsilat, kalan bakiyesini karsilastir. "
            "Neo 'Ali'nin yillar icindeki odemesi', 'X ogrenci gecmis sezonda da kayitliydi mi' derse KULLAN."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "soz_no": {"type": "integer", "description": "Ogrenci soz_no"},
            },
            "required": ["soz_no"],
        },
    },
    # ── OTURUM 25.9 — ADAPTIVE INTELLIGENCE / PREDICTIVE / KG ──
    {
        "name": "predict_yks_score",
        "description": (
            "Bir ogrencinin YKS puan TAHMINI — predictive_model.predict_student. "
            "Trend + zayif konular + devamsizlik + ELO bazli. "
            "Returns: predicted_tyt, predicted_ayt, predicted_yerlesme_puani, "
            "confidence (0-1), bottleneck_topics, suggested_focus. "
            "Ogrenci/admin 'YKS'de ne alirim', 'hedef bolum tutar mi', "
            "'su anki gidisla nereye girerim' derse KULLAN. KVKK: ogrenci sadece kendi tahminini gorur."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "soz_no": {"type": "integer", "description": "Ogrenci soz_no"},
                "target_taban_puan": {
                    "type": "number",
                    "description": "Opsiyonel: hedef bolumun gecen yil taban puani (probability hesabi icin)",
                },
            },
            "required": ["soz_no"],
        },
    },
    {
        "name": "get_adaptive_summary",
        "description": (
            "Adaptive Intelligence ozeti — adaptive_engine.get_adaptive_summary. "
            "Ogrencinin: ELO bazli zayif konulari, bugun tekrarlanmasi gereken konular (SM-2), "
            "aktif kavram yanılgıları (misconceptions). "
            "Ogrenci 'bugun ne calismaliyim', 'neyi tekrar etmem gerekir', "
            "'hangi konuyu yanlis anliyorum' sorularinda KULLAN."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "soz_no": {"type": "integer", "description": "Ogrenci soz_no"},
            },
            "required": ["soz_no"],
        },
    },
    {
        "name": "get_knowledge_graph",
        "description": (
            "Ogrencinin knowledge graph'i — knowledge_graph.get_student_graph. "
            "Konu agi (nodes + edges), ustalık seviyesi, on kosul iliskileri. "
            "Returns: nodes (id, ders, konu, mastery 0-1), edges (prerequisite agi), stats. "
            "Bot 'X konusunu anlayamiyorsun cunku Y on kosul eksik' tarzinda pedagojik gerekce verebilir. "
            "Ogrenci 'beyin haritami goster' / 'hangi konularim guclu' / 'hangi konuya gecsem' derse KULLAN."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "soz_no": {"type": "integer", "description": "Ogrenci soz_no"},
                "seviye": {
                    "type": "string",
                    "enum": ["TYT", "AYT", "LGS"],
                    "description": "Opsiyonel: sadece bu seviyenin grafigi",
                },
            },
            "required": ["soz_no"],
        },
    },
    {
        "name": "observe_student_answer",
        "description": (
            "Ogrenci bir soru cozdugunde 3 katmani guncelle — adaptive_engine.observe_answer. "
            "ELO + SM-2 review + misconception kayit. Foto soru cozum sonrasinda "
            "veya ogrenci 'bu soruyu cozdum' diyince KULLAN. "
            "Ders/konu Vision'dan veya ogrenciden alinir."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "soz_no": {"type": "integer"},
                "ders": {"type": "string", "description": "Matematik/Fizik/Kimya..."},
                "konu": {"type": "string", "description": "Türev/Limit/Kuvvet..."},
                "dogru": {"type": "boolean"},
                "zorluk": {"type": "string", "enum": ["kolay", "orta", "zor", "cok_zor"], "default": "orta"},
                "quality": {
                    "type": "integer",
                    "minimum": 0, "maximum": 5,
                    "description": "SM-2 quality 0-5 (yoksa dogru/yanlis bazli default)",
                },
                "misconception": {
                    "type": "string",
                    "description": "Yanlissa kavram yanılgısı (örn. 'integralı türevin tersi unutuyor')",
                },
            },
            "required": ["soz_no", "ders", "konu", "dogru"],
        },
    },
    # ── Oturum 25.12 — ÖĞRENCİ GÜNLÜK TAKİP (GRAFEN-tarzı) ──
    {
        "name": "get_student_daily_summary",
        "description": (
            "Ogrencinin günlük takip ozeti — student_daily.get_summary. "
            "7 modul tek cagri: bugunkü program, acik to-do, aliskanlik, yaklasan sinav/odev, "
            "bugunkü stat (sure+soru), son 7g aktivite, bugunkü not + mood. "
            "Ogrenci 'bugun ne yapacagim', 'odevim ne', 'kac saat calistim' derse KULLAN. "
            "Admin/mudur baska ogrenciye soz_no ile erisir."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "soz_no": {"type": "integer", "description": "Ogrenci soz_no"},
            },
            "required": ["soz_no"],
        },
    },
    {
        "name": "analyze_student_study_pattern",
        "description": (
            "Ogrencinin son N gun calisma oruntu analizi — student_daily.analyze_study_pattern. "
            "Toplam saat, en cok calisilan ders/konu, consistency skoru, zayif gun, "
            "fiziksel aktivite sayisi, mood dagilimi. "
            "Ogrenci 'bu ay nasil calistim', 'dengeli mi calisiyorum' / "
            "Admin 'X ogrencinin son ayki performans' derse KULLAN. "
            "30 gun default, 7-90 arasi degisebilir."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "soz_no": {"type": "integer", "description": "Ogrenci soz_no"},
                "days": {"type": "integer", "default": 30, "minimum": 7, "maximum": 90},
            },
            "required": ["soz_no"],
        },
    },
]


# ═══════════════════════════════════════════════════════════════════════════
# Oturum 25.11 — Tool Compact (Token Tasarruf)
# ═══════════════════════════════════════════════════════════════════════════
# Production verisinden (son 30g routing_stats) ≤2 cagri alan tool'lar tespit
# edildi. Sistem prompt'a yer almamaları icin TOOLS_ACTIVE'den filtrelenir.
# TOOL_DISPATCH'te wrapper'lari KORUNUR — eger Claude bir sekilde tahmin edip
# cagirirsa hata vermez. Geri eklemek icin: DEAD_TOOLS set'ten cikar.
#
# Tahmini tasarruf: 15 tool × ~30 satir desc × ~12 token = ~5400 token/cagri
# Aylik 500 mesaj × 5400 tok × $3/1M = ~$8/ay + Claude response hizi
DEAD_TOOLS: set[str] = {
    "youtube_oner",                  # 1 cagri
    "get_career_info",               # 1
    "plan_kaydet",                   # 1
    "plan_getir",                    # 1
    "transfer_failure_analiz",       # 1
    "proaktif_sgm_kademe_bildirimi", # 1
    "ogrenci_borc_detay",            # 1 — Neo onay verirse acilabilir
    "aylik_borc_detay",              # 2
    "geciken_odemeler",              # 2
    "web_upload",                    # 2
    # eyotek_read — 25.26'da CDP+cookie fix sonrasi calisir, AKTIF
    # eyotek_query — yeni agentic tool, AKTIF
    "pedagojik_koc",                 # 2
    "puan_tahmin",                   # 2 — yeni puan_tahmin yerine predict_yks_score var
    "konu_kaynak_paketi",            # 2
    "ogrenci_nereye_girebilir",      # 2 — yeni predict_yks_score + universite_taban
}

# Active TOOLS — Claude system prompt'a gonderilen liste
TOOLS_ACTIVE: list[dict] = [t for t in TOOLS if t.get("name") not in DEAD_TOOLS]


def get_tools(role: str = "ogrenci", include_dead: bool = False) -> list[dict]:
    """Role-aware tool listesi.

    role: 'admin' → tum tool'lar (finans dahil)
          'ogrenci'/'mudur'/'rehber'/'ogretmen' → DEAD_TOOLS hariç
          'veli' → cok kisitli (gelecek sezon)
    include_dead=True → DEAD dahil (debug/admin tam liste icin)
    """
    if include_dead or role == "admin":
        return TOOLS
    return TOOLS_ACTIVE
