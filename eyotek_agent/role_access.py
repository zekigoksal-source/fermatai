"""
FermatAI — Rol Erişim Kontrolü (Role Access Control)
=====================================================

22.1n-split: fermat_core_agent.py'dan ayrıştırıldı (risk: sıfır — sadece taşıma).
Backward compat: eski isimler `from role_access import ...` ile aynen çalışır.

Bu modül kritik güvenlik katmanıdır:
- Tool seviyesi ACL (_ACL_MATRIX + _is_tool_allowed)
- SQL seviyesi guard (_check_sql_acl + _FORBIDDEN_TABLES + _FORBIDDEN_COLUMNS)
- Elevated actions (SMS, toplu etüt) — sadece admin/mudur

Hiç kimse yetkisi dışına çıkamaz. Sızıntı = kurumsal kriz.
"""
from __future__ import annotations

# ═══════════════════════════════════════════════════════════════════════════════
# ACL — YETKİ SİSTEMİ (Kurumsal Güvenlik Katmanı)
# ═══════════════════════════════════════════════════════════════════════════════

# ── Araç erişim matrisi ──────────────────────────────────────────────────────

_ACL_MATRIX: dict[str, set[str]] = {
    # Admin: tüm araçlar, tüm veriler
    "admin": {
        "get_student_analytics", "get_ayt_analysis", "check_teacher_availability",
        "execute_eyotek_action", "get_class_summary",
        "search_students", "get_class_plan", "query_analytics",
        "build_study_plan_context",
        "search_curriculum", "send_exam_image", "list_exam_questions",
        "calculate_yks_score",
        "eyotek_read",
        "eyotek_query", "ogrenci_drilldown", "sinav_sonuclari",
        # Oturum 22 (C3 + 22.1) — Yokatlas + Atlas + System awareness
        "ogrenci_nereye_girebilir", "hedef_bolum_ara", "puan_tahmin", "hedef_puan_analiz",
        "plan_kaydet", "plan_getir", "plan_gun_guncelle",
        "counsellor_brief", "class_brief", "transfer_failure_analiz", "tercih_listesi_tasla",
        "get_atlas_trend",              # Neo-only ama ACL'den geçsin, icinde phone check var
        "get_recent_system_updates",
        "get_blueprint_section",        # 25.29 BLUEPRINT mimari farkindalik    # KALDIGIM canli okuyucu
        "hazirla_etut_talebi",          # Ogretmen eskalasyon (22.1l)
        "ogrenci_peer_kiyas",           # Peer benchmark (22.1m)
        "add_to_student_program",       # 25.14h: ogrenci calismam panel yazma (admin override)
        "ogm_yonlendir",                # MEB OGM yonlendirme (22.1n-ogm)
        "branch_zayif_konu",            # 22.1n-neo: brans analiz (admin herseyi)
        # 22.1n-neo FINANS TOOLS — ACL'de admin'de ama her tool ICINDE
        # is_finans_authorized(phone) kontrolu YAPILIR (phone = NEO_PHONE sart)
        "finans_ozet", "ogrenci_borc_detay", "geciken_odemeler",
        "aylik_tahsilat_trend", "veli_borc_bildirim_taslak", "finans_audit_rapor",
        "sezon_kiyasla", "aylik_borc_detay", "ogrenci_sezon_gecmisi",
        # 22.1n-neo FAZ 2 EKSTRA
        "ogretmen_pedagojik_brief", "veli_pedagojik_rehberlik",
        # Oturum Mentenans (21 Nisan 14:25)
        "get_pedagojik_sablon",
        # 22 Nisan — Career info (tum roller erisebilir)
        "get_career_info",
        "deep_research_paket", "youtube_oner", "konu_kaynak_paketi", "ogretmen_brief", "odev_ekle",
        "plani_takvime_ekle", "etut_takvime_ekle",
        # 23 Nisan — Tercih Robotu (YKS sonrası dönem)
        "tercih_profili_kaydet", "tercih_profili_getir", "tercih_listesi_uret",
        "bolum_karsilastir", "tercih_donemi_durum",
        "ders_konu_dagilimi_raporu", "get_lgs_konu_durumu",
        # ── Oturum 25.29 — SELF-DEV PIPELINE (Evre 1: read + brief, ADMIN ONLY) ──
        # Bu araclar SADECE admin (Neo) icin. Diger rollere ASLA acmayin.
        # Audit log + secret mask + sandbox kontrolu icerden yapilir.
        "selfdev_read_file", "selfdev_list_dir", "selfdev_grep_repo",
        "selfdev_read_logs", "selfdev_git_diff", "selfdev_git_log",
        "selfdev_git_blame", "selfdev_search_atlas_history",
        "selfdev_write_brief", "selfdev_list_briefs", "selfdev_get_brief",
    },
    # Yönetim üyesi: müdür gibi okuma ama yazma yok (etüt/eyotek action yok)
    "yonetim": {
        "get_student_analytics", "get_ayt_analysis", "check_teacher_availability",
        "get_class_summary", "search_students", "get_class_plan", "query_analytics",
        "build_study_plan_context",
        "ogrenci_nereye_girebilir", "hedef_bolum_ara", "puan_tahmin", "hedef_puan_analiz",
        "plan_kaydet", "plan_getir", "plan_gun_guncelle",
        "counsellor_brief", "class_brief", "transfer_failure_analiz", "tercih_listesi_tasla",
        "get_recent_system_updates",
        "get_blueprint_section",        # 25.29 BLUEPRINT mimari farkindalik
        "ogm_yonlendir",
        "branch_zayif_konu",
        # 23 Nisan — Tercih Robotu (okuma)
        "tercih_profili_getir", "tercih_listesi_uret", "bolum_karsilastir",
        "tercih_donemi_durum",
    },
    # Müdür: admin ile aynı (atlas_trend ve yönetim system verisi HARİÇ — Neo only)
    "mudur": {
        "get_student_analytics", "get_ayt_analysis", "check_teacher_availability",
        "execute_eyotek_action", "get_class_summary",
        "search_students", "get_class_plan", "query_analytics",
        "build_study_plan_context",
        "search_curriculum", "send_exam_image", "list_exam_questions",
        "calculate_yks_score", "eyotek_read", "eyotek_query", "ogrenci_drilldown", "sinav_sonuclari",
        "ogrenci_nereye_girebilir", "hedef_bolum_ara", "puan_tahmin", "hedef_puan_analiz",
        "plan_kaydet", "plan_getir", "plan_gun_guncelle",
        "counsellor_brief", "class_brief", "transfer_failure_analiz", "tercih_listesi_tasla",
        "get_recent_system_updates",
        "get_blueprint_section",        # 25.29 BLUEPRINT mimari farkindalik
        "hazirla_etut_talebi",
        "ogrenci_peer_kiyas",
        "ogm_yonlendir",
        "branch_zayif_konu",
        # 23 Nisan — Tercih Robotu (tam erişim)
        "tercih_profili_kaydet", "tercih_profili_getir", "tercih_listesi_uret",
        "bolum_karsilastir", "tercih_donemi_durum",
        "ders_konu_dagilimi_raporu", "get_lgs_konu_durumu",
        # 23 Nisan — Konu kaynak paketi (YouTube + Wikipedia + OGM)
        "konu_kaynak_paketi",
        # 25.14h: mudur tum ogrencilerin programina ekleyebilir
        "add_to_student_program",
    },
    # Öğretmen: kendi sınıfı + öğrenci akademik veri (etüt yazma YOK, ödeme/iletişim HARİÇ)
    # 22.1n-neo: universite tahmin tool'lari herkese acildi (Neo 20 Nisan onayi)
    "ogretmen": {
        "get_student_analytics", "get_ayt_analysis", "check_teacher_availability",
        "get_class_summary",
        "search_students", "get_class_plan", "query_analytics",
        "build_study_plan_context",
        "search_curriculum", "send_exam_image", "list_exam_questions",
        "ogm_yonlendir",
        # 22.1n-neo: ogretmenlere universite/puan tahmin araclari acildi
        "ogrenci_nereye_girebilir", "hedef_bolum_ara", "puan_tahmin", "hedef_puan_analiz",
        "calculate_yks_score",
        # 22.1n-neo: ogretmen brans analiz ozel tool (Merve 65 mesaj gorecevinden)
        "branch_zayif_konu",
        # 22.1n-neo FAZ 2 EKSTRA: Ogretmen pedagojik brief
        "ogretmen_pedagojik_brief",
        # Oturum Mentenans (21 Nisan 14:25) — ogretmen sablon getirebilir
        "get_pedagojik_sablon",
        "get_career_info",
        "deep_research_paket", "youtube_oner", "konu_kaynak_paketi", "ogretmen_brief", "odev_ekle",
        # 23 Nisan — Ogretmen Yetki Duzeltme (Neo karari)
        # Branş öğretmeni ETUT YAZMAZ. Sadece:
        # 1) Kendi etut takvimini okur + Google Calendar'a ekler
        # 2) Rehbere tavsiye/öneri yazar (günlük/haftalık rapor mantığı)
        "ogretmen_etut_takvimim", "ogretmen_etut_onerisi",
        # 23 Nisan FAZ 1 A2 — LGS öğrenci konu durumu
        "get_lgs_konu_durumu",
    },
    # Rehber öğretmen: TÜM öğrenci + TÜM öğretmen programı + etüt yazma + rehberlik notu
    "rehber": {
        "get_student_analytics", "get_ayt_analysis", "check_teacher_availability",
        "execute_eyotek_action", "get_class_summary",
        "search_students", "get_class_plan", "query_analytics",
        "build_study_plan_context",
        "search_curriculum", "list_exam_questions", "send_exam_image",
        "ogrenci_nereye_girebilir", "hedef_bolum_ara", "puan_tahmin", "hedef_puan_analiz",
        "plan_kaydet", "plan_getir", "plan_gun_guncelle",
        "counsellor_brief", "class_brief", "transfer_failure_analiz", "tercih_listesi_tasla",
        "hazirla_etut_talebi",
        "ogrenci_peer_kiyas",
        "ogm_yonlendir",
        "branch_zayif_konu",
        # Oturum Mentenans (21 Nisan 14:25) — rehber icin sablon (KRIZ_DESTEK, VELI_ILETISIM)
        "get_pedagojik_sablon",
        "get_career_info",
        "deep_research_paket", "youtube_oner", "konu_kaynak_paketi", "ogretmen_brief", "odev_ekle",
        "plani_takvime_ekle", "etut_takvime_ekle",
        # 23 Nisan — Tercih Robotu (rehber tum ogrencilerin tercihlerine bakabilir)
        "tercih_profili_kaydet", "tercih_profili_getir", "tercih_listesi_uret",
        "bolum_karsilastir", "tercih_donemi_durum",
        "ders_konu_dagilimi_raporu", "get_lgs_konu_durumu",
        # 25.14h: rehber tum ogrencilerin programina ekleyebilir (override)
        "add_to_student_program",
    },
    # Veli: sadece kendi çocuğunun akademik verisi + universite tahmin (Neo onay)
    "veli": {"get_student_analytics", "get_ayt_analysis",
             "ogrenci_nereye_girebilir", "hedef_bolum_ara", "puan_tahmin", "hedef_puan_analiz",
             "calculate_yks_score",
             # 22.1n-neo FAZ 2 EKSTRA: veli rehberlik
             "veli_pedagojik_rehberlik"},
    # Öğrenci: sadece kendi akademik verisi + çalışma planı + müfredat arama
    "ogrenci": {"get_student_analytics", "get_ayt_analysis", "query_analytics",
                "build_study_plan_context", "search_curriculum", "send_exam_image", "list_exam_questions",
                "calculate_yks_score",
                "ogrenci_nereye_girebilir", "hedef_bolum_ara", "puan_tahmin", "hedef_puan_analiz",
        "plan_kaydet", "plan_getir", "plan_gun_guncelle",
        "counsellor_brief", "class_brief", "transfer_failure_analiz", "tercih_listesi_tasla",
                "hazirla_etut_talebi",
                "ogrenci_peer_kiyas",
                "ogm_yonlendir",
                "get_career_info",
                "deep_research_paket", "youtube_oner", "konu_kaynak_paketi",
                # 23 Nisan — Tercih Robotu (sadece kendi profili)
                "tercih_profili_kaydet", "tercih_profili_getir", "tercih_listesi_uret",
                "bolum_karsilastir", "tercih_donemi_durum",
                "ders_konu_dagilimi_raporu", "get_lgs_konu_durumu",
                # 25.14h: ogrenci kendi calismam paneline ekleyebilir
                "add_to_student_program"},
    # Misafir / bilinmeyen: hiçbir araç
    "guest": set(),
    "unknown": set(),
}

# Sadece admin/müdür SMS gönderebilir ve toplu etüt yazabilir
_ELEVATED_ACTIONS = {"send_sms", "write_etut_for_class"}
_ELEVATED_ROLES   = {"admin", "mudur"}

# ── Veri erişim sınırları ────────────────────────────────────────────────────
# query_analytics SQL sorgularına ek güvenlik filtresi

# Öğrenci: sadece kendi soz_no'suna ait veriler
# Öğretmen: iletişim numarası ve ödeme bilgisi yasak
# Veli: sadece kendi çocuğu

_FORBIDDEN_COLUMNS = {
    "ogrenci": ["phone", "veli_phone", "anne_phone", "baba_phone", "tc_no",
                "odeme", "borc", "payment", "maas", "salary",
                "veli_cep", "anne_cep", "baba_cep", "ogrenci_cep"],
    "ogretmen": ["phone", "veli_phone", "anne_phone", "baba_phone", "tc_no",
                 "odeme", "borc", "payment", "maas", "salary",
                 "parent_name", "veli_cep", "anne_cep", "baba_cep", "ogrenci_cep",
                 "veli_adi", "anne_adi", "baba_adi"],
    "veli": ["phone", "anne_phone", "baba_phone", "tc_no",
             "odeme", "borc", "payment", "maas", "salary"],
    "rehber": ["tc_no", "odeme", "borc", "payment", "maas", "salary",
               "veli_cep", "anne_cep", "baba_cep"],  # iletişim bilgisi müdür yetkisinde
}

# 23 Nisan (Neo audit raporu): Sistem telemetri + atlas + duygu analiz tabloları
# HASSAS — sadece admin (ve Neo-only bazıları). KVKK: öğrenci duygu sinyalleri,
# Neo talimatları, rotalama stats, alarm logları — öğretmen/veli/öğrenci DEĞEMEZ.
_SYSTEM_PRIVATE_TABLES = [
    "user_feedback",         # Neo talimatları + öğrenci geri bildirimleri
    "atlas_suggestions",     # Neo-only öneri kuyruğu
    "atlas_observations",    # Sistem gözlemleri
    "atlas_chat_state",      # Atlas iç state
    "routing_stats",         # Kim hangi route'tan geldi (sistem)
    "alert_log",             # Alarm geçmişi
    "frustration_log",       # Hoşnutsuzluk tespitleri
    "student_insights",      # Duygu/motivasyon — kendi öğrencisi için öğretmen/rehber
    "hack_attempts",         # Güvenlik izleme
    "deployment_log",        # Sistem sürüm geçmişi
    "query_cache",           # Semantik cache — Neo debug
    "sistem_ayar",           # TERCIH_DONEMI_ACTIVE vb. bayraklar
    "teacher_etut_onerileri", # Rehber-yazar + öğretmen-okur (Neo-only değil, ama kısıtlı)
    "tercih_profil",         # Öğrenci tercih profili — KVKK
    "tercih_listesi",        # Üretilen taslaklar — KVKK
]

_FORBIDDEN_TABLES = {
    # Öğrenci: kendi verisi hariç HER ŞEY yasak (sensitive_tables ACL kontrolü de ayrıca)
    "ogrenci": ["acl_users", "staff", "agent_conversations", "usage_log",
                "blocked_numbers", "overdue_payments", "teacher_performance",
                "daily_stats", "admin_talimat", "etut_teacher_summary",
                "teacher_timetable", "teacher_etut_onerileri",
                # Oturum 23 ek: sistem/telemetri/Neo talimat tabloları — HEPSİ YASAK
                *_SYSTEM_PRIVATE_TABLES,
                # Başka öğrenci verisi genel (SQL guard ayrıca soz_no kısıtlar)
                ],
    "yonetim": ["acl_users", "agent_conversations", "usage_log", "blocked_numbers",
                "admin_talimat", "daily_stats",
                # Yönetim: Atlas + routing_stats + user_feedback Neo-only
                "user_feedback", "atlas_suggestions", "atlas_observations",
                "atlas_chat_state", "routing_stats", "hack_attempts", "deployment_log",
                "query_cache", "sistem_ayar"],
    "mudur": ["acl_users", "agent_conversations", "usage_log", "blocked_numbers",
              "admin_talimat", "daily_stats",
              # Müdür: Atlas/telemetri Neo-only
              "atlas_suggestions", "atlas_observations", "atlas_chat_state",
              "routing_stats", "hack_attempts", "deployment_log",
              "query_cache", "sistem_ayar"],
              # Müdür user_feedback ERIŞEBILIR (Neo talimatı değil, genel geri bildirim)
    "ogretmen": ["acl_users", "agent_conversations", "usage_log", "blocked_numbers",
                 "overdue_payments", "teacher_performance", "daily_stats",
                 "admin_talimat", "etut_teacher_summary",
                 # Oturum 23: Sistem + Neo + diğer öğrenci duygu verisi — YASAK
                 *_SYSTEM_PRIVATE_TABLES,
                 "counsellor_notes",  # rehberlik notları rehber+müdür yetkisinde
                 ],
    "rehber": ["acl_users", "agent_conversations", "usage_log", "blocked_numbers",
               "admin_talimat", "daily_stats", "overdue_payments",
               # Oturum 23: Atlas + telemetri Neo-only, rehber user_feedback ERIŞEBILIR
               "atlas_suggestions", "atlas_observations", "atlas_chat_state",
               "routing_stats", "hack_attempts", "deployment_log",
               "query_cache", "sistem_ayar"],
    # Rehber: teacher_timetable, etut_teacher_summary, staff, student_insights,
    # teacher_etut_onerileri, tercih_profil, tercih_listesi ERIŞEBILIR (iş için gerekli)
    "veli": ["acl_users", "staff", "agent_conversations", "etut_history",
             "counsellor_notes", "usage_log", "blocked_numbers",
             "teacher_timetable", "teacher_performance", "overdue_payments",
             # Oturum 23: Sistem + Neo + başka öğrenci verisi — HEPSİ YASAK
             *_SYSTEM_PRIVATE_TABLES,
             "admin_talimat", "daily_stats", "etut_teacher_summary",
             "teacher_etut_onerileri"],
}


def _is_tool_allowed(role: str, tool_name: str, action: str = "", phone: str = "") -> bool:
    """Rol için araç çağrısına izin var mı?"""
    # Orsel Koc — Sistem Gelistirme Muduru: mudur yetkileri AMA yazma YASAK
    # Oturum 18: Neo karari — yetki karmasasi yaratmamak icin sert guvenlik
    if phone == "905547043775":
        # Yazma/aksiyon tool'lari kesinlikle kapali
        _SGM_FORBIDDEN = {"execute_eyotek_action"}
        if tool_name in _SGM_FORBIDDEN:
            return False
        # Kalan: mudur yetkisiyle okuma (query_analytics'te ekstra tablo guard var)
    allowed_tools = _ACL_MATRIX.get(role, set())
    if tool_name not in allowed_tools:
        return False
    if tool_name == "execute_eyotek_action" and action in _ELEVATED_ACTIONS:
        return role in _ELEVATED_ROLES
    return True


def _check_sql_acl(role: str, sql: str, soz_no: int = None, phone: str = "") -> str | None:
    """
    SQL sorgusunda yetki ihlali var mı kontrol et.
    İhlal varsa hata mesajı döndür, yoksa None.

    22.1n-neo: phone parametresi eklendi — finans SQL guard icin gerekli.
    Finans tablosu/kolonu iceren sorgu SADECE Neo (NEO_PHONE) tarafindan
    yapilabilir. Diger tum roller (admin rolu bile) phone check'ten gecer.
    """
    sql_upper = sql.upper()

    # ── FINANS GUARD (22.1n-neo) — en once calis, en kati kural ──
    # Neo bile olsa rol admin degilse veya phone Neo degilse REDDET
    try:
        from finans_access import check_finans_sql_access
        finans_err = check_finans_sql_access(role, phone, sql)
        if finans_err:
            return finans_err
    except Exception:
        # finans_access modulu yuklenemezse — GUVENLIK ICIN REDDET (fail-closed)
        from finans_access import sql_contains_finans
        if sql_contains_finans(sql):
            return "GUVENLIK: Finans erisim modulu dogrulanamadi."

    # Öğrenci: sadece kendi verisine erişebilir (Oturum 18 + 23 guclendirildi)
    # Oturum 23 pentest: OR/UNION injection check HER öğrenci SQL'inde — non-sensitive
    # table üzerinden (ör. students) bypass açığı kapatıldı.
    if role == "ogrenci":
        import re as _re_acl
        # 1) OR/UNION injection tüm SQL'ler için (sensitive olsun olmasın)
        if _re_acl.search(r'\b(OR\s+\d+\s*=\s*\d+|UNION\s+(?:ALL\s+)?SELECT|--|/\*)\b', sql_upper):
            return "Güvenlik: SQL injection pattern (OR/UNION/comment) tespit edildi — reddedildi."
        # 2) Hassas ogrenci tablolari — kendi soz_no kisitlamali
        if soz_no:
            sensitive_tables = ["STUDENT_EXAMS", "STUDENT_TOPIC_TRACKER", "DEVAMSIZLIK",
                                "STUDENT_EXAM_ANALYSIS", "STUDENT_INSIGHTS",
                                "COUNSELLOR_NOTES", "ETUT_HISTORY",
                                "TERCIH_PROFIL", "TERCIH_LISTESI"]
            if any(t in sql_upper for t in sensitive_tables):
                if str(soz_no) not in sql:
                    return f"Güvenlik: Sadece kendi verilerine erişebilirsin. Sorgu kendi soz_no'nu ({soz_no}) içermelidir."
                # Bulunan tüm soz_no sayıları kendi soz_no'muza eşit olmalı
                found_nums = _re_acl.findall(r'soz_no\s*[=<>]+\s*(\d+)', sql_upper, _re_acl.IGNORECASE)
                for n in found_nums:
                    if n != str(soz_no):
                        return f"Güvenlik: Başka öğrencinin soz_no'su ({n}) sorgulanamaz. Sadece kendi ({soz_no})."

    # Yasaklı tablo kontrolü
    forbidden_tables = _FORBIDDEN_TABLES.get(role, [])
    for table in forbidden_tables:
        if table.upper() in sql_upper:
            return f"Güvenlik: {table} tablosuna erişim yetkiniz yok."

    # Yasaklı kolon kontrolü
    forbidden_cols = _FORBIDDEN_COLUMNS.get(role, [])
    for col in forbidden_cols:
        if col.upper() in sql_upper:
            return f"Güvenlik: {col} bilgisine erişim yetkiniz yok."

    # Öğretmen: staff tablosunda başka öğretmen verisi yasak
    if role == "ogretmen":
        if "STAFF" in sql_upper and "etut_teacher_summary" not in sql.lower():
            return "Güvenlik: Personel bilgilerine erişim yetkiniz yok."
        # teacher_timetable'da başka öğretmen programı yasak (sadece kendi)
        if "TEACHER_TIMETABLE" in sql_upper:
            # Kendi adı filtrede yoksa engelle
            pass  # System prompt'ta kısıtlanıyor, SQL seviyesinde ek kontrol gerekmez

    # Öğrenci: başka öğrencinin soz_no'su ile sorgu yasak
    if role == "ogrenci" and soz_no:
        if "ETUT_STUDENT_CONTROL" in sql_upper:
            if str(soz_no) not in sql:
                return "Güvenlik: Sadece kendi etüt bilgilerine erişebilirsin."

    return None  # İhlal yok


# Backward-compat: eski isimler module-level expose (external kullanıcılar kırılmaz)
__all__ = [
    "_ACL_MATRIX", "_ELEVATED_ACTIONS", "_ELEVATED_ROLES",
    "_FORBIDDEN_COLUMNS", "_FORBIDDEN_TABLES",
    "_is_tool_allowed", "_check_sql_acl",
]
