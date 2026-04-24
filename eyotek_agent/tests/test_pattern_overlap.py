"""
Pattern Ortusmesi Tespiti (Oturum 22.1e, Talimat #12)
======================================================

OGRENCI_PATTERNS + OGRETMEN_PATTERNS + ADMIN_PATTERNS listelerinde
birden fazla pattern'e eslesen ornek mesajlari bul.

Kanit edilen mesaj senaryolariyla her pattern'i test edip multiple match
varsa RAPORLA. Sistem "first match wins" ile calisiyor → ilk pattern
intended ise sorun yok, degilse refactor gerekli.
"""
import sys, io, os, re

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fast_responses import OGRENCI_PATTERNS, OGRETMEN_PATTERNS, ADMIN_PATTERNS


# Kanit edilen konusma senaryolari (gercek kullanim)
TEST_MESSAGES = [
    # Ogrenci mesajlari
    ("selam", "ogrenci"),
    ("merhaba nasilsin", "ogrenci"),
    ("web kodu", "ogrenci"),
    ("son denemem nasil", "ogrenci"),
    ("ayt sonucum", "ogrenci"),
    ("zayif konularim", "ogrenci"),
    ("deneme analizi yap", "ogrenci"),
    ("son 3 denememi kiyasla", "ogrenci"),
    ("ne calismali", "ogrenci"),
    ("devamsizligim kac", "ogrenci"),
    ("ders programim", "ogrenci"),
    ("bu hafta hangi dersler var", "ogrenci"),
    ("calisma plani yap", "ogrenci"),
    ("hedefim ne", "ogrenci"),
    ("netlerimle hangi universite", "ogrenci"),
    ("hangi universite girerim", "ogrenci"),
    ("fizik branş analizi", "ogrenci"),
    ("tum denemelere gore", "ogrenci"),
    ("kaldirma kuvveti nedir", "ogrenci"),
    ("tyt ne zaman", "ogrenci"),
    ("foto hakkim kac", "ogrenci"),
    ("rehberlik randevusu", "ogrenci"),
    # Ogretmen
    ("ders programim", "ogretmen"),
    ("bugun hangi ders", "ogretmen"),
    ("haftalik ders saat", "ogretmen"),
    ("kac etut verdim", "ogretmen"),
    # Admin
    ("salı kim geliyor", "admin"),
    ("zeki hoca persembe", "admin"),
    ("ogretmenleri kiyasla", "admin"),
    ("web kodu al ali icin", "admin"),
]


def match_patterns(msg: str, pattern_list: list) -> list:
    """Bir mesaja match eden TUM pattern'leri dondur (ilk degil, hepsi)."""
    msg_lower = msg.lower()
    matches = []
    for i, (pattern, handler, desc) in enumerate(pattern_list):
        if re.search(pattern, msg_lower):
            matches.append((i, handler, desc))
    return matches


def report_overlaps():
    """Her test mesaji icin pattern match analizi."""
    total_overlaps = 0
    total_tests = 0

    pattern_map = {
        "ogrenci": OGRENCI_PATTERNS,
        "ogretmen": OGRETMEN_PATTERNS,
        "admin": ADMIN_PATTERNS,
    }

    for msg, role in TEST_MESSAGES:
        total_tests += 1
        patterns = pattern_map[role]
        matches = match_patterns(msg, patterns)

        if len(matches) == 0:
            # fallback - Claude'a dusecek (normal)
            pass
        elif len(matches) == 1:
            # tek match, ideal (winner belli)
            pass
        else:
            total_overlaps += 1
            winner = matches[0]
            print(f"\n[{role}] {msg!r}")
            print(f"  ✓ WINNER: {winner[1]} ({winner[2]})")
            for m in matches[1:]:
                print(f"  ✗ overlap: {m[1]} ({m[2]})")

    print(f"\n{'='*60}")
    print(f"Toplam test: {total_tests}")
    print(f"Ortusme (winner belli + ignore edilen): {total_overlaps}")
    print(f"Net (1 match veya 0): {total_tests - total_overlaps}")
    print(f"{'='*60}")

    return total_overlaps


def find_redundant_patterns(pattern_list: list, role_name: str) -> int:
    """Ayni handler'a yonlendiren birden fazla pattern varsa flag."""
    handler_count = {}
    for pattern, handler, desc in pattern_list:
        handler_count.setdefault(handler, []).append((pattern, desc))

    redundant = 0
    for handler, entries in handler_count.items():
        if len(entries) >= 3:  # 3+ pattern ayni handler'a → potansiyel redundancy
            print(f"\n[{role_name}] Handler '{handler}' icin {len(entries)} pattern:")
            for p, d in entries:
                print(f"  • {p[:60]}... ({d})")
            redundant += 1
    return redundant


if __name__ == "__main__":
    print("=" * 60)
    print("PATTERN ÖRTÜŞME RAPORU")
    print("=" * 60)

    overlaps = report_overlaps()

    print("\n\n" + "=" * 60)
    print("HANDLER REDUNDANCY (ayni handler'a 3+ pattern)")
    print("=" * 60)
    r1 = find_redundant_patterns(OGRENCI_PATTERNS, "OGRENCI")
    r2 = find_redundant_patterns(OGRETMEN_PATTERNS, "OGRETMEN")
    r3 = find_redundant_patterns(ADMIN_PATTERNS, "ADMIN")

    print(f"\n\nÖZET: {overlaps} mesajda ortusme, {r1+r2+r3} handler redundancy")

    if overlaps > 10:
        print("⚠ YUKSEK ORTUSME — refactor dusunulsun")
    elif overlaps > 5:
        print("⚠ ORTA ORTUSME — notlandirildi, gelecek oturumda bak")
    else:
        print("✅ DUSUK ORTUSME — mevcut sistem makul")
