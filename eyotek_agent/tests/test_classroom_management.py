"""
Classroom Management Regresyon Testleri (22 Nisan 2026)
========================================================
Neo vizyonu: EdTech — token değerli, sınıf yönetimi doğal, hedef bazlı.

Kapsanan modüller:
  - token_budget (role limit, classify, advice)
  - conversation_drift (classify_message, drift_level)
  - redirect_templates (kategori bazlı mesaj)
  - teacher_persona (phase, merak sorusu)
  - session_tracker (message count, redirect spam)
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ═══════════════════════════════════════════════════════════════════════════
# TOKEN BUDGET
# ═══════════════════════════════════════════════════════════════════════════

def test_token_role_limits():
    """Rol bazlı günlük limitler doğru."""
    from token_budget import role_limit
    assert role_limit("ogrenci") == 20_000
    assert role_limit("ogretmen") == 40_000
    assert role_limit("mudur") == 80_000
    assert role_limit("admin") is None  # sınırsız


def test_token_classify_usage():
    """Kullanım sınıflandırması eşikleri."""
    from token_budget import classify_usage
    # 0-74% → ok
    assert classify_usage(0, 20000) == "ok"
    assert classify_usage(14000, 20000) == "ok"
    # 75-89% → warn
    assert classify_usage(15000, 20000) == "warn"
    assert classify_usage(17800, 20000) == "warn"
    # 90-99% → last_seans
    assert classify_usage(18000, 20000) == "last_seans"
    assert classify_usage(19900, 20000) == "last_seans"
    # 100+ → exceeded
    assert classify_usage(20000, 20000) == "exceeded"
    assert classify_usage(25000, 20000) == "exceeded"
    # Sınırsız (admin) → her zaman ok
    assert classify_usage(100_000, None) == "ok"


def test_token_estimate():
    """Token tahmini makul aralıkta."""
    from token_budget import _estimate_tokens
    # 300 char → ~100 token
    assert 60 <= _estimate_tokens("a" * 300) <= 200
    # Boş
    assert _estimate_tokens("") == 0
    # Minimum 10
    assert _estimate_tokens("x") == 10


# ═══════════════════════════════════════════════════════════════════════════
# CONVERSATION DRIFT
# ═══════════════════════════════════════════════════════════════════════════

def test_drift_classify_akademik():
    from conversation_drift import classify_message
    cases = [
        "türev nedir anlatır mısın",
        "fizik denemem 2.5 net",
        "kaldırma kuvveti çözdüm",
        "türkçe paragraf sorularını karıştırıyorum",
        "kimyasal tepkime nedir",
    ]
    for msg in cases:
        c = classify_message(msg)
        assert c == "akademik", f"'{msg}' akademik bulunmadı, bulunan: {c}"


def test_drift_classify_off_topic():
    from conversation_drift import classify_message
    cases = [
        "valorant oynuyorum",
        "chatgpt'ye sorsam daha iyi",
        "netflix dizi izledim",
        "Real Madrid maçı süperdi",
        "hahah çok komik",
    ]
    for msg in cases:
        c = classify_message(msg)
        assert c == "off_topic", f"'{msg}' off_topic bulunmadı, bulunan: {c}"


def test_drift_classify_pedagojik():
    from conversation_drift import classify_message
    cases = [
        "çalışma planı yap bana",
        "haftalık program oluştur",
        "hedef belirleyelim",
        "pomodoro tekniği deneyeyim",
    ]
    for msg in cases:
        c = classify_message(msg)
        assert c == "pedagojik", f"'{msg}' pedagojik bulunmadı, bulunan: {c}"


def test_drift_net_not_netflix():
    """'net' keyword'u 'netflix' içine match ETMEMELİ."""
    from conversation_drift import classify_message
    assert classify_message("netflix dizi izledim") == "off_topic"
    assert classify_message("5 net yaptım tyt") == "akademik"
    assert classify_message("netim düştü") == "akademik"


# ═══════════════════════════════════════════════════════════════════════════
# REDIRECT TEMPLATES
# ═══════════════════════════════════════════════════════════════════════════

def test_redirect_nazik_icerir_hedef():
    from redirect_templates import get_redirect
    r = get_redirect("hafif", name="Zehra", hedef_konu="türev")
    assert r is not None
    assert "türev" in r.lower()


def test_redirect_agir_net_davet():
    from redirect_templates import get_redirect
    r = get_redirect("agir", name="Ali", hedef_konu="kaldırma kuvveti")
    assert r is not None
    assert len(r) > 50  # uzun ve net olmalı


def test_redirect_drift_yok():
    from redirect_templates import get_redirect
    assert get_redirect("yok", "Mehmet") is None


def test_redirect_template_count():
    """42+ şablon olmalı."""
    from redirect_templates import template_count
    cnt = template_count()
    assert cnt["toplam"] >= 30, f"Şablon sayısı yetersiz: {cnt['toplam']}"


def test_redirect_budget_closing():
    from redirect_templates import get_budget_closing
    last = get_budget_closing("last_seans", "Ayşe")
    exceed = get_budget_closing("exceeded", "Mehmet")
    assert last and "Ayşe" in last
    assert exceed and "Mehmet" in exceed
    assert get_budget_closing("ok") is None


def test_redirect_merak():
    """Merak sorusu ? veya emoji ile bitiyor."""
    from redirect_templates import get_merak_sorusu
    for _ in range(5):
        r = get_merak_sorusu("Zehra")
        assert r.endswith(("?", "🤔", "💡", "✨", "🎯", "🤝", "🧠", "💪", "📐", "🎓", "🔬"))


# ═══════════════════════════════════════════════════════════════════════════
# TEACHER PERSONA
# ═══════════════════════════════════════════════════════════════════════════

def test_teacher_phase():
    from teacher_persona import get_phase
    assert get_phase(1) == "isinma"
    assert get_phase(5) == "cekirdek"
    assert get_phase(12) == "derin"
    assert get_phase(20) == "sarkma"


def test_teacher_merak_sorusu_kurali():
    from teacher_persona import should_add_merak_sorusu
    # İsınmada hayır (sohbet)
    assert should_add_merak_sorusu(1, "yok") is False
    # Çekirdek + drift yok → evet
    assert should_add_merak_sorusu(5, "yok") is True
    # Drift orta → hayır (redirect önemli)
    assert should_add_merak_sorusu(5, "orta") is False
    # Sarkmada → hayır (kapanış)
    assert should_add_merak_sorusu(20, "yok") is False


def test_teacher_context_build():
    """Prompt bloğu üretildi ve temel kelimeleri içeriyor."""
    from teacher_persona import build_teacher_context
    ctx = build_teacher_context(
        budget_status="warn",
        drift_level="hafif",
        msg_count=5,
        hedef_konu="türev",
    )
    assert "CLASSROOM_MGMT" in ctx
    assert "türev" in ctx
    assert len(ctx) > 200  # anlamlı içerik


# ═══════════════════════════════════════════════════════════════════════════
# SESSION TRACKER
# ═══════════════════════════════════════════════════════════════════════════

def test_session_record():
    from session_tracker import record_message, get_session
    phone = "test_sess_1"
    record_message(phone, "türev")
    record_message(phone, "integral")
    s = get_session(phone)
    assert s["msg_count"] == 2
    assert "türev" in s["konu_list"]
    assert "integral" in s["konu_list"]


def test_session_redirect_spam():
    """Oturum başına max 2 redirect, spam önleme."""
    from session_tracker import record_redirect, can_redirect
    phone = "test_sess_spam"
    # Başlangıç → can_redirect True
    assert can_redirect(phone) is True
    # 1. redirect sonra 5dk kısıt
    record_redirect(phone)
    assert can_redirect(phone) is False  # gap az


# ═══════════════════════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    tests = [
        test_token_role_limits,
        test_token_classify_usage,
        test_token_estimate,
        test_drift_classify_akademik,
        test_drift_classify_off_topic,
        test_drift_classify_pedagojik,
        test_drift_net_not_netflix,
        test_redirect_nazik_icerir_hedef,
        test_redirect_agir_net_davet,
        test_redirect_drift_yok,
        test_redirect_template_count,
        test_redirect_budget_closing,
        test_redirect_merak,
        test_teacher_phase,
        test_teacher_merak_sorusu_kurali,
        test_teacher_context_build,
        test_session_record,
        test_session_redirect_spam,
    ]
    ok = 0
    for t in tests:
        try:
            t()
            ok += 1
            print(f"✓ {t.__name__}")
        except AssertionError as e:
            print(f"✗ {t.__name__}: {e}")
        except Exception as e:
            print(f"✗ {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{ok}/{len(tests)} test geçti")
