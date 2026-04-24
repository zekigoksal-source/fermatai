"""
Telefon Numarasi Normalizasyonu
================================
Fermat ekosisteminde telefon numaralari tek standart formatta tutulur:
  905xxxxxxxxx (12 karakter, +'siz)

Sebep: DB tablolari arasi JOIN'lerde tutarsizlik olusmasin. Onceden
students '+905xxx', acl_users karisik, agent_conversations '905xxx' idi.

KULLANIM:
  from phone_utils import normalize_phone
  clean = normalize_phone("+905051256802")  # -> "905051256802"
  clean = normalize_phone("0505 125 68 02")  # -> "905051256802"

INSERT oncesi HEP normalize et. Query'lerde parametreyi normalize
ederek gonder: WHERE phone = $1 (artik REPLACE gerekmiyor).
"""
from typing import Optional


def normalize_phone(phone: Optional[str]) -> Optional[str]:
    """
    Telefon numarasini 905xxxxxxxxx formatina cevir.

    Kurallar:
      - Bos/None  -> None
      - +905xxx   -> 905xxx  (baslangictaki + kaldir)
      - 05xxx     -> 905xxx  (bas 0 -> 90)
      - 5xxx      -> 905xxx  (10 hane = olasi TR mobil)
      - Bosluk/tire/parantez temizlenir
      - Zaten 905xxx ise dokunulmaz

    Args:
        phone: ham telefon string'i

    Returns:
        12 karakterli "905xxxxxxxxx" string veya None
    """
    if not phone:
        return None

    # Sadece rakam ve + birak
    cleaned = "".join(ch for ch in str(phone) if ch.isdigit() or ch == "+")

    # Baslangictaki + kaldir
    if cleaned.startswith("+"):
        cleaned = cleaned[1:]

    # Bos kaldiysa None
    if not cleaned:
        return None

    # Format varyasyonlari
    if cleaned.startswith("90") and len(cleaned) == 12:
        return cleaned  # zaten dogru

    if cleaned.startswith("0") and len(cleaned) == 11:
        # 05051256802 -> 905051256802
        return "9" + cleaned

    if len(cleaned) == 10 and cleaned.startswith("5"):
        # 5051256802 -> 905051256802
        return "90" + cleaned

    # Min 10 rakam olmayan -> gecersiz
    if len(cleaned) < 10:
        return None

    # Tanimsiz format — olani don (min 10 rakam garanti)
    return cleaned


def phones_equal(p1: Optional[str], p2: Optional[str]) -> bool:
    """Iki telefon numarasi ayni mi (normalize edilmis halleriyle)?"""
    n1 = normalize_phone(p1)
    n2 = normalize_phone(p2)
    return n1 is not None and n1 == n2
