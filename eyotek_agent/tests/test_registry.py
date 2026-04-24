"""
Registry pattern + dispatcher testleri (DB gerekmez).
"""
import pytest
from student_query_registry import find_match, STUDENT_QUERY_REGISTRY
from fast_responses import _try_registry_match


pytestmark = pytest.mark.registry


# ═══════════════════════════════════════════════════════════════════════
# PATTERN MATCH TESTLERI (find_match)
# ═══════════════════════════════════════════════════════════════════════

PATTERN_CASES = [
    # (mesaj, beklenen_id_fragment, beklenen_path)
    ("merhaba", "selam", "fast"),
    ("selam hocam", "selam", "fast"),
    ("selam nasilsin", "selam_hal", "fast"),

    ("son denemem nasil", "son_deneme", "fast"),
    ("deneme sonucum", "son_deneme", "fast"),
    ("netlerim ne", "son_deneme", "fast"),
    ("son 5 denemeyi kiyasla", "kiyasla", "fast"),
    ("ayt denemem", "ayt_deneme", "fast"),
    ("tyt vs ayt", "tyt_vs_ayt", "claude_required"),

    ("zayif konularim", "zayif_konular", "fast"),
    ("hangi konularda zayifim", "zayif_konular", "fast"),
    ("iyi oldugum konular", "guclu_konular", "fast"),

    ("fizik cikmis sorular", "cikmis_soru", "fast"),
    ("turev cikmis", "cikmis_soru", "fast"),
    ("soru 5 goster", "soru_N_coz", "claude_required"),

    ("netlerimle hangi universite girerim", "kisisel_hedef", "claude_required"),
    ("puanim ne", "puan_tahmin", "claude_required"),
    ("tip puani kac", "bolum_bilgisi_generic", "fast"),

    ("bugunku program", "bugunku_program", "fast"),
    ("calisma planim", "calisma_plani", "claude_required"),

    ("cok stresliyim", "stres_panik", "claude_required"),
    ("motivasyonum dusuk", "motivasyon_iste", "fast"),

    ("yazdiklarimi kim gorur", "gizlilik", "fast"),

    ("bunu demedim", "frustration", "claude_required"),

    ("kurumda kac ogrenci var", "kurum_personel", "fast"),
    ("zeki hoca kim", "kurum_personel", "fast"),

    ("ne yapabilirsin", "yetenekler", "fast"),
    ("yeteneklerin neler", "yetenekler", "fast"),

    ("fotoelektrik olayi nedir", "kavramsal", "ollama_safe"),

    ("not et bunu", "not_kaydet", "fast"),

    ("bye", "veda", "fast"),
    ("hoscakal", "veda", "fast"),
]


@pytest.mark.parametrize("msg,exp_id,exp_path", PATTERN_CASES)
def test_registry_pattern_match(msg, exp_id, exp_path):
    """Her senaryo icin pattern match ve path dogrula."""
    hit = find_match(msg.lower().strip())
    assert hit is not None, f"'{msg}' registry'de eslesmedi"
    assert exp_id in hit["id"], f"'{msg}' -> id={hit['id']} (beklenen: {exp_id})"
    assert hit["path"] == exp_path, f"'{msg}' -> path={hit['path']} (beklenen: {exp_path})"


def test_registry_miss_on_specific_command():
    """Spesifik bir komut registry'ye dusmemeli."""
    hit = find_match("bugun ilhan hocanin 10:30 fizik dersini iptal et")
    assert hit is None


def test_registry_count_and_distribution():
    """Registry'nin toplam senaryo sayisi ve path dagilimi makul olmali."""
    assert len(STUDENT_QUERY_REGISTRY) >= 25, "Registry en az 25 senaryo icermeli"

    paths = {}
    for s in STUDENT_QUERY_REGISTRY:
        paths[s["path"]] = paths.get(s["path"], 0) + 1

    assert paths.get("fast", 0) >= 15, "En az 15 fast senaryo olmali"
    assert paths.get("claude_required", 0) >= 5, "En az 5 claude senaryo olmali"


def test_registry_all_items_compiled():
    """Her senaryo import'ta compile edilmis olmali."""
    for item in STUDENT_QUERY_REGISTRY:
        assert "_compiled" in item, f"{item['id']} compile edilmedi"
        assert len(item["_compiled"]) == len(item["patterns"])


# ═══════════════════════════════════════════════════════════════════════
# DISPATCHER TESTLERI (_try_registry_match — DB gerektirmeyen handler'lar)
# ═══════════════════════════════════════════════════════════════════════

DISPATCH_CASES = [
    # (mesaj, role, soz_no, expected_not_none, description)
    ("merhaba", "ogrenci", 137, True, "selam fast"),
    ("bye", "ogrenci", 137, True, "veda fast"),
    ("ne yapabilirsin", "ogrenci", 137, True, "yetenekler fast"),
    ("tip puani kac", "ogrenci", 137, True, "bolum generic fast"),
    ("kurumda kac ogrenci var", "ogrenci", 137, True, "kurum reddet fast"),
    ("yazdiklarimi kim gorur", "ogrenci", 137, True, "gizlilik fast"),
    ("motivasyonum dusuk", "ogrenci", 137, True, "motivasyon fast"),

    # claude_required -> None
    ("netlerimle hangi universiteye girerim", "ogrenci", 137, False, "kisisel hedef claude"),
    ("cok stresliyim", "ogrenci", 137, False, "stres claude"),
    ("calisma planim", "ogrenci", 137, False, "plan claude"),

    # ollama_safe -> None
    ("fotoelektrik olayi nedir", "ogrenci", 137, False, "kavramsal ollama"),
]


@pytest.mark.parametrize("msg,role,soz_no,expected,desc", DISPATCH_CASES)
async def test_registry_dispatch(msg, role, soz_no, expected, desc):
    """Registry dispatch handler ya cevap doner ya None (path karari)."""
    msg_lower = msg.lower().strip()
    hit, resp = await _try_registry_match(
        msg, msg_lower, "905000000000", role, soz_no, "Test Ogrenci", ""
    )
    assert hit, f"[{desc}] registry hit olmali"
    if expected:
        assert resp is not None, f"[{desc}] resp dolu olmali (claude/ollama degil)"
        assert len(resp) > 10, f"[{desc}] resp cok kisa"
    else:
        assert resp is None, f"[{desc}] resp None olmali (Claude/Ollama'ya gidecek)"


async def test_registry_admin_role_falls_through():
    """Admin rolunde ogrenci-ozel handler miss'e dusmeli."""
    hit, resp = await _try_registry_match(
        "son denememi kiyasla", "son denememi kiyasla",
        "905x", "admin", None, "Zeki", ""
    )
    # Admin icin ogrenci-ozel handler None doner -> hit=False (alt akisa)
    assert not hit


async def test_registry_long_greeting_falls_through():
    """Uzun selam + non-pattern soru alt akisa dusmeli."""
    msg = "merhaba bu aksam neler yapmam lazim"
    hit, resp = await _try_registry_match(
        msg, msg.lower(), "905x", "ogrenci", 137, "Test", ""
    )
    # Selam pattern'i eslemez (saf selam degil), baska pattern de yok -> miss
    assert not hit


async def test_registry_hack_safe_no_crash():
    """Zararsiz edge case: bos mesaj, cok uzun mesaj crash yapmamali."""
    for msg in ["", "a" * 500, "...", "?"]:
        try:
            await _try_registry_match(
                msg, msg.lower().strip(), "905x", "ogrenci", 137, "Test", ""
            )
        except Exception as e:
            pytest.fail(f"Crash for '{msg[:30]}': {e}")
