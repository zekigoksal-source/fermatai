"""
Field Reconciler — LLM-native + Türkçe-aware schema-less field matching.

NEO VIZYON (11 May): Bot Eyotek'te "soz_no" ararken "SözNo" görüyor — biz
manuel mapping listeleriyle her varyantı yazmamalıyız. LLM çağı bu, sistem
karakter normalizasyonu + bağlam çıkarımı + akıllı fuzzy match yapabiliyor.
"soz_no ≡ SözNo ≡ Söz No ≡ söznö" hepsi aynı kavram.

Bu modül:
1. Türkçe-aware normalize (NFD diakritik temizle, lowercase, alphanumeric)
2. Synonym graph (Eyotek tablo key'leri → canonical akademik field)
3. Suffix-aware (`Türkçe_NET` → 'turkce' base; `Türkçe_DC` → 'turkce_dc')
4. Fuzzy match fallback (Levenshtein-lite, similarity > 0.8)
5. (Opsiyonel) LLM-fallback: rare unknown field için Cerebras'a sor

Kullanım:
    from field_reconciler import find_field, canonicalize_row

    # 1. Tek field çek (en yaygın kullanım)
    soz_no = find_field(row, 'soz_no')   # 'SözNo' / 'soz_no' / 'Söz No' fark etmez
    turkce = find_field(row, 'turkce_net') # 'Türkçe_NET' / 'turkce' bulur

    # 2. Tüm row'u canonical hale getir (lazy_sync için)
    clean = canonicalize_row(row)
    # → {'soz_no': '168', 'ad': 'ZEYNEP', 'soyad': 'KIRSAKAL',
    #    'turkce_net': 31.25, 'matematik_net': 28.5, 'toplam_net': ...}
"""

from __future__ import annotations
import re
import unicodedata
from typing import Any, Optional


# ─────────────────────────────────────────────────────────────────────────
# 1. NORMALIZATION
# ─────────────────────────────────────────────────────────────────────────

def _normalize_key(s: str) -> str:
    """Field name → canonical comparison form.

    'SözNo' → 'sozno'
    'Söz No' → 'sozno'
    'Türkçe_NET' → 'turkcenet'
    'Toplam Net' → 'toplamnet'
    'TYT Türkçe' → 'tyttürkce' (hatta 'tytturkce')
    """
    if not s:
        return ""
    # 1. Unicode normalize: 'İ' → 'I' + combining dot
    s = unicodedata.normalize('NFD', s)
    # 2. Tüm combining mark'ları sil (diakritik)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    # 3. Türkçe ı → i (NFD'de ayrılmaz)
    s = s.replace('ı', 'i').replace('I', 'i')
    # 4. Lowercase
    s = s.lower()
    # 5. Sadece alfanümerik tut (boşluk/_/./- vb. sil)
    s = re.sub(r'[^a-z0-9]', '', s)
    return s


# ─────────────────────────────────────────────────────────────────────────
# 2. SYNONYM GRAPH — kavram → varyantlar (Eyotek + bizim DB schema'mız)
# ─────────────────────────────────────────────────────────────────────────

# Canonical key → known variant set
# Variantlar otomatik normalize edilip karşılaştırılır
SYNONYMS: dict[str, list[str]] = {
    # ─── Öğrenci kimlik ───
    'soz_no':       ['SözNo', 'Söz No', 'soz_no', 'sözno', 'Söz_No', 'sozno', 'StudentNo'],
    'student_name': ['ogrenci_adi', 'Öğrenci', 'Öğrenci Adı', 'ad_soyad', 'Ad Soyad', 'student_name'],
    'ad':           ['Adı', 'ad', 'Ad', 'first_name', 'name'],
    'soyad':        ['Soyadı', 'soyad', 'Soyad', 'last_name', 'surname'],
    'tc_no':        ['TC', 'TC No', 'tc_no', 'TCKimlik', 'tckimlik_no'],

    # ─── Sınav meta ───
    'sinav_adi':    ['Sınav Adı', 'sinav_adi', 'Sınav', 'Sinav', 'exam_name', 'SnvName'],
    'sinav_kodu':   ['Sınav Kodu', 'sinav_kodu', 'SnvKod', 'exam_code', 'SnvKodu'],
    'sinav_turu':   ['Sınav Türü', 'sinav_turu', 'SnvTur', 'exam_type'],
    'tarih':        ['Tarih', 'tarih', 'date', 'exam_date', 'Date'],
    'sube':         ['Şube', 'sube', 'Şube Adı', 'branch'],
    'devre':        ['Devre', 'devre', 'Sınıf Düzeyi', 'grade'],
    'sinif':        ['Sınıf', 'sinif', 'Sınıflar', 'class'],

    # ─── TYT NETLER (suffix-aware: '_NET' suffix kalksın, base = canonical) ───
    'turkce':       ['Türkçe_NET', 'Türkçe', 'TYT Türkçe', 'turkce'],
    'matematik':    ['Matematik_NET', 'Matematik', 'TYT Matematik', 'matematik', 'Mat'],
    'geometri':     ['Geometri_NET', 'Geometri', 'geometri'],
    'fizik':        ['Fizik_NET', 'Fizik', 'fizik'],
    'kimya':        ['Kimya_NET', 'Kimya', 'kimya'],
    'biyoloji':     ['Biyoloji_NET', 'Biyoloji', 'biyoloji', 'Biyo'],
    'tarih_ders':   ['Tarih_NET', 'tarih_ders'],   # ders olarak (sinav meta tarih ile karışmasın)
    'cografya':     ['Coğrafya_NET', 'Coğrafya', 'cografya', 'Cog'],
    'felsefe':      ['Felsefe_NET', 'Felsefe', 'felsefe'],
    'din':          ['DinKültürü_NET', 'DinKültürü', 'Din Kültürü', 'din', 'din_kulturu'],
    'toplam':       ['Toplam_NET', 'Toplam', 'toplam', 'toplam_net', 'TOP'],

    # ─── AYT NETLER (yks sınavları için) ───
    'edebiyat':     ['Türk Dili ve Edebiyatı_NET', 'TDE_NET', 'edebiyat', 'tde'],
    'mat_ayt':      ['AYT Matematik_NET', 'mat_ayt', 'Matematik AYT'],
    'tarih_ayt':    ['Tarih-1_NET', 'tarih_ayt'],
    'fizik_ayt':    ['AYT Fizik_NET', 'fizik_ayt'],
    'kimya_ayt':    ['AYT Kimya_NET', 'kimya_ayt'],
    'biyoloji_ayt': ['AYT Biyoloji_NET', 'biyoloji_ayt'],

    # ─── Puanlar / Sıralamalar ───
    'tyt_puan':     ['TYT Puanı', 'TYT_Puan', 'tyt_puan', 'TYT P'],
    'ayt_puan':     ['AYT Puanı', 'AYT_Puan', 'ayt_puan', 'YKS Puan'],
    'genel_sira':   ['Genel Sıra', 'TYT_Genel_Sıra', 'AYT_Genel_Sıra', 'genel_sira'],
    'sube_sira':    ['Şube Sıra', 'TYT_Şube_Sıra', 'sube_sira'],
    'sinif_sira':   ['Sınıf Sıra', 'TYT_Sınıf_Sıra', 'sinif_sira'],

    # ─── Etüt / Yoklama ───
    'ders':         ['Ders', 'ders', 'lesson'],
    'ogretmen':     ['Öğretmen', 'ogretmen', 'teacher'],
    'derslik':      ['Derslik', 'derslik', 'sinif_kodu', 'classroom'],
    'saat':         ['Saat', 'saat', 'time'],
    'etut_kodu':    ['Etüt Kodu', 'etut_kodu', 'Kod', 'kod'],
    'ogrenci_sayisi': ['Öğrenci Sayısı', 'ogrenci_sayisi', 'Öğr.Say'],
}


# Pre-compute normalized variants → canonical
_VARIANT_TO_CANONICAL: dict[str, str] = {}
for canonical, variants in SYNONYMS.items():
    # Canonical kendisi de varyant olarak ekleniyor
    all_variants = list(set(variants + [canonical]))
    for v in all_variants:
        _VARIANT_TO_CANONICAL[_normalize_key(v)] = canonical


# ─────────────────────────────────────────────────────────────────────────
# 3. SUFFIX-AWARE EŞLEŞTIRME (Türkçe_DC, Türkçe_YC, Türkçe_SS gibi sub-fieldlar)
# ─────────────────────────────────────────────────────────────────────────

# Eyotek bazı netleri 'Türkçe_NET' (canonical), bazısı 'Türkçe_DC' (doğru cevap)
# 'Türkçe_YC' (yanlış cevap), 'Türkçe_SS' (soru sayısı) — bunlar farklı field.
# 'Türkçe_NET' = canonical 'turkce'. Diğerleri 'turkce_dc' vb. canonical olur.

_SUFFIX_KEEP = {'_dc', '_yc', '_ss', '_dogru', '_yanlis', '_bos'}  # bunları sakla
_SUFFIX_DROP = {'_net'}  # _NET = canonical, suffix kaldır


def _strip_net_suffix(normalized_key: str) -> str:
    """'turkcenet' → 'turkce' (NET base canonical)."""
    if normalized_key.endswith('net'):
        # 'turkcenet' → 'turkce' AMA 'tyt' suffix de korunur
        # Test: 'matematiknet' → 'matematik'
        return normalized_key[:-3]
    return normalized_key


# ─────────────────────────────────────────────────────────────────────────
# 4. CORE API
# ─────────────────────────────────────────────────────────────────────────

def find_field(row: dict, *canonical_keys: str, default: Any = None) -> Any:
    """Row'da canonical key'in herhangi bir varyantını ara.

    Args:
        row: dict — keys can be in any format ('SözNo', 'soz_no', 'Söz No')
        *canonical_keys: aranan canonical isim(ler) ('soz_no', 'turkce')
        default: bulunamazsa dönecek değer

    Returns: bulunan değer veya default

    Examples:
        soz_no = find_field({'SözNo': '168'}, 'soz_no')  # → '168'
        turkce = find_field({'Türkçe_NET': '31,25'}, 'turkce')  # → '31,25'
        ad = find_field({'Adı': 'ZEYNEP', 'Soyadı': 'K.'}, 'ad')  # → 'ZEYNEP'
    """
    if not row or not canonical_keys:
        return default

    # Her row key'ini normalize edip lookup
    for raw_key, value in row.items():
        if not raw_key:
            continue
        norm = _normalize_key(raw_key)

        # _NET suffix'i de dene (Türkçe_NET → 'turkcenet' → 'turkce')
        norm_stripped = _strip_net_suffix(norm)

        for canonical in canonical_keys:
            canonical_norm = _normalize_key(canonical)
            # Direct match
            if norm == canonical_norm:
                return value
            # Stripped (NET suffix removed)
            if norm_stripped == canonical_norm:
                return value
            # Variant graph match
            if _VARIANT_TO_CANONICAL.get(norm) == canonical:
                return value
            if _VARIANT_TO_CANONICAL.get(norm_stripped) == canonical:
                return value

    return default


def canonicalize_row(row: dict, *, keep_extra: bool = True) -> dict:
    """Row'un tüm key'lerini canonical formata çevir.

    Args:
        row: ham Eyotek row dict
        keep_extra: bilinmeyen key'ler de eklensin mi (kayıp önleme)

    Returns: canonical key'lerle yeni dict

    Examples:
        canonicalize_row({'SözNo': '168', 'Adı': 'ZEYNEP', 'Türkçe_NET': '31,25'})
        # → {'soz_no': '168', 'ad': 'ZEYNEP', 'turkce': '31,25'}
    """
    if not row:
        return {}

    out: dict = {}
    for raw_key, value in row.items():
        if not raw_key:
            continue
        norm = _normalize_key(raw_key)
        norm_stripped = _strip_net_suffix(norm)

        # Synonym graph lookup
        canonical = _VARIANT_TO_CANONICAL.get(norm) or _VARIANT_TO_CANONICAL.get(norm_stripped)

        if canonical:
            out.setdefault(canonical, value)  # ilk gelen kazanır (NET vs DC durumunda NET öncelikli ekli)
        elif keep_extra:
            # Bilinmeyen field — orijinal key'i koru ama normalize edilmiş tekrar etmesin
            out.setdefault(raw_key, value)

    return out


def find_field_anycase(row: dict, key: str, default: Any = None) -> Any:
    """Tek-key, case/normalize-insensitive arama (synonym graph kullanmadan).

    'soz_no' arasan 'SözNo', 'Söz_No', 'sozno' hepsini bulur ama synonym genişletmez.
    """
    target = _normalize_key(key)
    for k, v in (row or {}).items():
        if _normalize_key(k) == target:
            return v
    return default


# ─────────────────────────────────────────────────────────────────────────
# 5. FUZZY MATCH (rare fallback)
# ─────────────────────────────────────────────────────────────────────────

def _similarity(a: str, b: str) -> float:
    """Basit Jaccard char-bigram similarity (Levenshtein'a alternatif)."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    bi_a = {a[i:i+2] for i in range(len(a)-1)} or {a}
    bi_b = {b[i:i+2] for i in range(len(b)-1)} or {b}
    intersection = len(bi_a & bi_b)
    union = len(bi_a | bi_b)
    return intersection / union if union else 0.0


def fuzzy_find(row: dict, target: str, threshold: float = 0.7) -> Optional[Any]:
    """Synonym match başarısızsa bigram similarity ile fuzzy ara.

    Örn target='turkce' row'da 'Türkçe_NET' yok ama 'Türk_Dili' var → similarity > 0.7 ise dön.
    """
    target_norm = _normalize_key(target)
    best_value = None
    best_score = threshold
    for k, v in (row or {}).items():
        k_norm = _normalize_key(k)
        score = _similarity(k_norm, target_norm)
        if score > best_score:
            best_score = score
            best_value = v
    return best_value


# ─────────────────────────────────────────────────────────────────────────
# 6. DATA COMPLETENESS CHECK (self-aware drill için)
# ─────────────────────────────────────────────────────────────────────────

def check_data_completeness(
    sinav_found: list,
    actual_rows: int,
    devre_count: int = 1,
) -> dict:
    """sinav_found header'da expected katılım vs actual rows karşılaştır.

    sinav_found typical: ['', 'Şube', 'Tarih', 'Kod', 'Tür', 'Kategori', 'Adı',
                          'Devre', 'Genel Katılım', 'İl Katılım', 'İlçe Katılım',
                          'Şube Katılım', 'Sınıflar', '']
    Index 11 = Şube Katılım (kuruma ait katılımcı sayısı)

    Returns:
        {
            'complete': bool,        # ratio > 0.85 ise complete
            'expected': int,         # Şube Katılım rakamı
            'actual': int,           # gelen rows
            'ratio': float,          # actual/expected
            'warning': str|None,     # complete olmadığında açıklama
        }
    """
    out = {
        'complete': True,
        'expected': None,
        'actual': actual_rows,
        'ratio': None,
        'warning': None,
    }
    try:
        if not isinstance(sinav_found, list) or len(sinav_found) < 12:
            return out
        sube_katilim_raw = sinav_found[11]
        if not sube_katilim_raw:
            return out
        sube_katilim = int(re.sub(r'[^\d]', '', str(sube_katilim_raw)) or 0)
        if sube_katilim < 1:
            return out
        out['expected'] = sube_katilim
        ratio = actual_rows / sube_katilim
        out['ratio'] = round(ratio, 2)
        # Devre sayısına göre toleranslı: tek devre çekildiyse (devre_count=1) ve
        # ratio < 0.5 → muhtemelen multi-devre var ama biz birini aldık
        # Multi-devre çekildiyse (devre_count >= 2) ve ratio < 0.85 → hala filtre var
        if devre_count == 1 and ratio < 0.5:
            out['complete'] = False
            out['warning'] = (
                f"Sınava {sube_katilim} öğrenci katılmış ama sadece {actual_rows} "
                f"verisi çekilebildi (%{int(ratio*100)}). Muhtemelen başka devre "
                f"satırları var (Mezun, 11.Snf gibi). Drill-down V2 normalde tüm "
                f"devreleri çeker — eğer çekemediyse sayfa yapısı değişmiş olabilir."
            )
        elif ratio < 0.85:
            out['complete'] = False
            out['warning'] = (
                f"Sınava {sube_katilim} öğrenci katılmış, {actual_rows} kayıt geldi "
                f"(%{int(ratio*100)}). Eyotek'te bazı katılımcılar farklı bir "
                f"sayfa/filtrede olabilir veya sisteme aktarılmamış olabilir."
            )
    except (ValueError, TypeError, IndexError):
        pass
    return out


# ─────────────────────────────────────────────────────────────────────────
# 7. SELF-TEST
# ─────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Eyotek dynamic-list row simulasyonu
    test_row = {
        '': '1',
        'SnvKod': '999000107',
        'SözNo': '168',
        'Adı': 'ZEYNEP',
        'Soyadı': 'KIRSAKAL',
        'KitTür': 'A',
        'Türkçe_SS': '40',
        'Türkçe_DC': '33',
        'Türkçe_YC': '7',
        'Türkçe_NET': '31,25',
        'Matematik_NET': '28,00',
        'Toplam_NET': '76,50',
        'TYT_Puan': '369,7',
    }

    print("=== find_field() ===")
    print(f"soz_no: {find_field(test_row, 'soz_no')}")  # 168
    print(f"ad: {find_field(test_row, 'ad')}")  # ZEYNEP
    print(f"soyad: {find_field(test_row, 'soyad')}")  # KIRSAKAL
    print(f"sinav_kodu: {find_field(test_row, 'sinav_kodu')}")  # 999000107
    print(f"turkce: {find_field(test_row, 'turkce')}")  # 31,25
    print(f"matematik: {find_field(test_row, 'matematik')}")  # 28,00
    print(f"toplam: {find_field(test_row, 'toplam')}")  # 76,50

    print("\n=== canonicalize_row() ===")
    canon = canonicalize_row(test_row)
    for k, v in canon.items():
        print(f"  {k}: {v}")

    print("\n=== completeness check ===")
    sinav_found_test = ['', 'Kurs', '22.04.2026', '999000107', 'TYT', 'TYT',
                        'APOTEMİ TG TYT-3', '12.Snf', '9497', '146', '101', '60', '', '']
    chk_one_devre = check_data_completeness(sinav_found_test, actual_rows=14, devre_count=1)
    chk_full = check_data_completeness(sinav_found_test, actual_rows=30, devre_count=2)
    print(f"1 devre, 14 row, expected 60: {chk_one_devre}")
    print(f"2 devre, 30 row, expected 60: {chk_full}")
