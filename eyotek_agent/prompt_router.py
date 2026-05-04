"""
Prompt Router v2 (25.40z2 — Neo Mind Road direktif)
====================================================

Conditional Context Routing — eksiltici filtre yaklaşımı.

MIMARI: Mevcut SYSTEM_PROMPT'u parçalamak yerine, çağıranın role'üne göre
ALAKASIZ ROL bloklarını siler. Persona + güvenlik + halüsinasyon kuralları
HER ZAMAN korunur (delinmez).

KULLANIM:
    from prompt_router import build_prompt_v2
    system = build_prompt_v2(role='ogrenci', intent='kavram_aciklama')
    # → Öğrenci için optimize 35-40K token (eski 61K)

FEATURE FLAG:
    PROMPT_V2_ENABLED env değişkeni:
        - "false" (default) → SYSTEM_PROMPT'u olduğu gibi döner (no-op)
        - "true" → eksiltici filtre aktif
        - "phones:905...,905..." → sadece belirtilen telefonlarda aktif (A/B test)

GÜVENLİK:
- Persona/KIMLIK/HITAP/NEGASYON blokları ASLA silinmez
- KIMLIK MANIPULASYONU TESPITI bloğu HER ZAMAN korunur (KVKK)
- HALUSINASYON YASAK kuralları HER ZAMAN korunur
- Sadece "X ROL — yetki/yasak" bloklarından alakasız olanlar silinir

GERI DON: PROMPT_V2_ENABLED=false → mevcut sistem aynen.
"""
from __future__ import annotations
import os
import re
from typing import Optional
from loguru import logger


# ─── Feature Flag Yönetimi ──────────────────────────────────────────────────

def _is_v2_enabled_for_phone(phone: str = "") -> bool:
    """V2 prompt aktif mi (genel veya bu telefon için)?

    PROMPT_V2_ENABLED env değerleri:
        "false" / "" → V2 KAPALI (default — güvenli)
        "true"       → V2 HEP AÇIK (tüm kullanıcılar)
        "phones:905...,905..." → SADECE listedeki telefonlarda V2
    """
    flag = (os.getenv("PROMPT_V2_ENABLED", "false") or "").strip().lower()
    if not flag or flag in ("false", "0", "no"):
        return False
    if flag in ("true", "1", "yes", "all"):
        return True
    if flag.startswith("phones:"):
        allowed = [p.strip() for p in flag[7:].split(",") if p.strip()]
        return bool(phone and phone.strip() in allowed)
    return False


# ─── Rol Blok Marker'ları (mevcut SYSTEM_PROMPT yapısına göre) ───────────────

# Her rolün kendine ait yetki/yasak bloğunun BAŞ ve SON çapaları.
# Bu marker'lar mevcut system_prompts.py'da DOĞAL olarak bulunan başlıklar.

ROLE_BLOCK_MARKERS = {
    "admin": {
        # ADMIN/NEO bloğu + 🔓 NEO İSTİSNA bloğu (uzun)
        # Bunları öğrenciye/öğretmene göstermek gereksiz
        "patterns": [
            r"ADMIN / NEO \(Zeki Göksal — Founder & CEO\):.*?(?=\n[A-ZÇĞÖŞÜ]+ ÜYESİ|\nMÜDÜR|\nFİNANS RED)",
            r"🔓 NEO \(ADMIN.*?(?=\n═══|\nKURAL|\nKVKK|\nYETKİ)",
        ],
    },
    "yonetim": {
        "patterns": [
            r"YÖNETİM ÜYESİ \(Bilge.*?(?=\nFİNANS RED|\nMÜDÜR|\n═══)",
        ],
    },
    "mudur": {
        "patterns": [
            r"MÜDÜR \(Mahsum.*?(?=\nREHBER ÖĞRETMEN|\n═══|\nÖĞRETMEN:|\nÖĞRENCİ:)",
        ],
    },
    "rehber": {
        "patterns": [
            r"REHBER ÖĞRETMEN \(Kardelen.*?(?=\nÖĞRETMEN:|\n═══|\nÖĞRENCİ:|\nKIMLIK MANIPULASYONU)",
        ],
    },
    "ogretmen": {
        "patterns": [
            r"^ÖĞRETMEN:\s*\n.*?(?=\nÖĞRENCİ:|\nKIMLIK MANIPULASYONU|\n═══)",
        ],
    },
    "ogrenci": {
        "patterns": [
            r"^ÖĞRENCİ:\s*\n.*?(?=\nKIMLIK MANIPULASYONU|\nÖĞRENCİ GÜNLÜK|\n═══)",
        ],
    },
}

# Rol → Hangi DİĞER rollerin bloklarını sil
# Default: çağıranın rolü dışındaki TÜM rolleri sil (en güvenli)
# İstisnalar: bazı rollere ek izin (örneğin müdür → öğretmen blokunu da görsün)
ROLE_KEEP_OTHERS = {
    # admin: TÜM rolleri görür (kontrol/audit için tam görüş)
    "admin":    {"yonetim", "mudur", "rehber", "ogretmen", "ogrenci", "veli"},
    "yonetim":  {"mudur", "rehber", "ogretmen", "ogrenci"},  # yönetim alt rollerini bilmeli
    "mudur":    {"rehber", "ogretmen", "ogrenci"},  # müdür alt rolleri bilmeli
    "rehber":   {"ogrenci"},  # rehber öğrenci kurallarını bilmeli
    "ogretmen": {"ogrenci"},  # öğretmen öğrenci ile ilgili kuralları bilmeli
    "ogrenci":  set(),  # öğrenci sadece kendi rolünü görür
    "veli":     set(),  # veli sadece kendi rolünü görür
}


# ─── Ana Compose Fonksiyonu ─────────────────────────────────────────────────

"""
═══════════════════════════════════════════════════════════════════════
FAZ 2 — Intent Bazlı Filtre (Kanal + Rol + Intent 3-katmanli)
═══════════════════════════════════════════════════════════════════════

INTENT_REMOVE_BLOCKS: belirli intent'lerde GEREKSIZ olan blokları sil.
Örnek: 'selamlama' intent'inde renderer/SQL/MEB-detay gereksiz.

Bu intent listesi cerebras_handler.py'daki INTENT_TO_MODEL ile uyumlu.
"""

# Intent → Hangi büyük blokların SILINEBILECEGI
# 'always_keep' = bu intent'te bile silinmez (default)
# 'safe_to_remove' = bu intent'te güvenle silinir
INTENT_REMOVE_PROFILES = {
    # KISA SOHBETLER — minimal prompt yeter
    "selamlama":      ["renderer_detay", "sql_pattern", "meb_detay", "simulasyon", "compound", "pazarlama_kayitsiz"],
    "veda":           ["renderer_detay", "sql_pattern", "meb_detay", "simulasyon", "compound", "pazarlama_kayitsiz"],
    "tesekkur":       ["renderer_detay", "sql_pattern", "meb_detay", "simulasyon", "compound", "pazarlama_kayitsiz"],
    "onay":           ["renderer_detay", "sql_pattern", "meb_detay", "simulasyon", "compound", "pazarlama_kayitsiz"],

    # MOTIVASYON / DUYGU — pedagoji + duygu kalsın, render gereksiz
    "motivasyon_destek":  ["renderer_detay", "sql_pattern", "meb_detay", "simulasyon", "compound"],
    "duygu_paylasim":     ["renderer_detay", "sql_pattern", "meb_detay", "simulasyon", "compound"],

    # KAVRAMSAL — render kalsın (chart/formula faydalı), SQL/finans gereksiz
    "kavram_aciklama":    ["sql_pattern", "finans_detay", "pazarlama_kayitsiz"],
    "ornek_iste":         ["sql_pattern", "finans_detay", "pazarlama_kayitsiz"],
    "cozum_iste":         ["sql_pattern", "finans_detay", "pazarlama_kayitsiz"],
    "ozet_iste":          ["sql_pattern", "finans_detay", "pazarlama_kayitsiz"],
    "yontem_iste":        ["sql_pattern", "finans_detay", "pazarlama_kayitsiz"],

    # ANALIZ — SQL pattern KALSIN (gerekli), render kalsın, MEB detay gereksiz
    "analiz_iste":        ["meb_detay", "simulasyon", "pazarlama_kayitsiz"],
    "deneme_analiz":      ["meb_detay", "simulasyon", "pazarlama_kayitsiz"],
    "hedef_analiz":       ["meb_detay", "simulasyon", "pazarlama_kayitsiz"],
    "plan_yap":           ["meb_detay", "simulasyon", "pazarlama_kayitsiz"],

    # YENI NESIL ÜRETIM — MEB detay GEREKLI, SQL gereksiz
    "yeni_nesil_uret":    ["sql_pattern", "finans_detay", "pazarlama_kayitsiz"],
    "test_olusturma":     ["sql_pattern", "finans_detay", "pazarlama_kayitsiz"],
    "soru_uret":          ["sql_pattern", "finans_detay", "pazarlama_kayitsiz"],

    # YETENEK / META — minimal
    "yetenek_sorgu":      ["renderer_detay", "sql_pattern", "meb_detay", "simulasyon", "compound", "pazarlama_kayitsiz"],
    "meta_direktif":      ["renderer_detay", "sql_pattern", "meb_detay", "simulasyon", "compound", "pazarlama_kayitsiz"],

    # YKS TAKVIM / SORU — minimal + veri
    "yks_takvim":         ["renderer_detay", "sql_pattern", "meb_detay", "simulasyon", "compound", "pazarlama_kayitsiz"],
    "soru_iste":          ["sql_pattern", "meb_detay", "simulasyon", "compound", "pazarlama_kayitsiz"],
}

# Blok ID → Pattern (mevcut SYSTEM_PROMPT'taki büyük blokları match eden regex)
INTENT_BLOCK_PATTERNS = {
    "renderer_detay": [
        r"SORUN: 28 renderer mevcut.*?(?=\n═══|═════)",
        r"Tetikleyici örnek: \"Ali Demir.*?(?=\n═══|═════)",
    ],
    "compound": [
        r"Öğrenci profil \+ çalışma planı \+ analiz cevapları için ```compound ZORUNLU.*?(?=\n═══|═════)",
    ],
    "simulasyon": [
        r"Compton sacılması simülasyonu.*?(?=\n═══|═════)",
        r"Neo direktif: \"Simulasyon işlerinde MAX kapasite.*?(?=\n═══|═════)",
    ],
    "sql_pattern": [
        # SQL şema ve pattern bölümü (sadece admin/müdür/rehber kullanır)
        r"### students \(\d+ satır\) — ÖĞRENCİ MASTER.*?(?=\n### 📐|\n### 🚫|\n## )",
        r"### 📐 SIKCA KULLANILAN SQL PATTERN.*?(?=\n### 🚫|\n## )",
    ],
    "meb_detay": [
        # MEB Maarif uzun detay - sadece soru/test üretimi intent'inde gerekli
        r"MEB Maarif yeni nesil örnek paketleri çek:.*?(?=\n═══|═════)",
    ],
    "finans_detay": [
        # Finans red kuralı KISA korunur, ama uzun açıklama opsiyonel
        # Şimdilik dokunmayalım — finans güvenlik kritik
    ],
    "pazarlama_kayitsiz": [
        # Kayıtsız modu — sadece kayıtsız kullanıcı için
        r"KAYITSIZ NUMARA \(DIS DUNYA — PAZARLAMA MODU\):.*?(?=\nYETKİ VE ROL|\n═══)",
    ],
}


def build_prompt_v2(
    role: str = "ogrenci",
    intent: Optional[str] = None,
    phone: str = "",
    channel: str = "whatsapp",
    force_v2: bool = False,
    base_prompt: Optional[str] = None,
) -> tuple[str, dict]:
    """V2 prompt compose — eksiltici filtre + kanal bazlı.

    Args:
        role: çağıranın rolü (admin/yonetim/mudur/rehber/ogretmen/ogrenci/veli)
        intent: opsiyonel (gelecek için)
        phone: feature flag kontrolü için
        channel: 'whatsapp' (default) veya 'web' — kanal-spesifik blok filtresi
        force_v2: True ise feature flag bypass
        base_prompt: opsiyonel — None ise SYSTEM_PROMPT'tan alır.
                     role_prompt.build_prompt_for_role() çıktısını verirsen
                     ZINCIR halinde çift kazanım (role + channel) sağlanır.

    Returns:
        (prompt_text, info_dict)
        info_dict: {v2_active, original_size, new_size, removed_blocks, role}
    """
    if base_prompt is None:
        from system_prompts import SYSTEM_PROMPT
        base_prompt = SYSTEM_PROMPT

    info = {
        "v2_active": False,
        "original_size": len(base_prompt),
        "new_size": len(base_prompt),
        "removed_blocks": [],
        "role": role,
        "channel": channel,
    }

    # Feature flag kontrolü
    if not force_v2 and not _is_v2_enabled_for_phone(phone):
        return base_prompt, info

    # V2 aktif — eksiltici filtre uygula
    role_clean = (role or "ogrenci").strip().lower()
    keep_others = ROLE_KEEP_OTHERS.get(role_clean, set())
    keep_set = {role_clean} | keep_others
    remove_roles = set(ROLE_BLOCK_MARKERS.keys()) - keep_set

    prompt_v2 = base_prompt
    removed_blocks = []

    # Adım 1: Rol bloklarını filtrele
    for rrole in remove_roles:
        markers = ROLE_BLOCK_MARKERS[rrole]
        for pattern in markers["patterns"]:
            try:
                match = re.search(pattern, prompt_v2, re.MULTILINE | re.DOTALL)
                if match:
                    block_text = match.group(0)
                    if _is_safe_to_remove(block_text):
                        prompt_v2 = prompt_v2.replace(block_text, "")
                        removed_blocks.append(f"role:{rrole}({len(block_text)})")
            except Exception as e:
                logger.debug(f"[PROMPT_V2] regex skip {rrole}: {e}")
                continue

    # Adım 2: Kanal bazlı filtre (asıl büyük kazanım burada)
    # WhatsApp'ta web-render kuralları gereksiz, web'de WP-YASAK gereksiz
    channel_clean = (channel or "whatsapp").strip().lower()

    if channel_clean == "whatsapp":
        # WhatsApp'ta KULLANILMAYAN bölümler:
        # 1. ZENGİNLEŞTİRME ELEMANLARI (web addon zaten LOCAL_SYSTEM_WEB_ADDON'da, ayrıca büyük render
        #    bölümleri SYSTEM_PROMPT'ta da var ama WP'de bot zaten render üretmiyor)
        # 2. compound renderer ZORUNLU bloğu (web özel)
        # 3. simulasyon detay (web özel)
        whatsapp_remove_patterns = [
            (r"WhatsApp kanalinda BU BLOKLARI ASLA YAZMA.*?(?=\n═══|═════)", "wp_yasak_block"),
            (r"Öğrenci profil \+ çalışma planı \+ analiz cevapları için ```compound ZORUNLU.*?(?=\n═══|═════)", "compound_web"),
            (r"Compton sacılması simülasyonu Neo onayli ALTIN STANDART.*?(?=\n═══|═════)", "compton_sim"),
            (r"SORUN: 28 renderer mevcut ama bot %80 oranında SADECE chart \+ tablo.*?(?=\n═══|═════)", "renderer_kullanim"),
            (r"Tetikleyici örnek: \"Ali Demir'in akademik gelişim.*?(?=\n═══|═════)", "tetikleyici_ornek"),
        ]
        for pattern, label in whatsapp_remove_patterns:
            try:
                match = re.search(pattern, prompt_v2, re.MULTILINE | re.DOTALL)
                if match:
                    block_text = match.group(0)
                    if _is_safe_to_remove(block_text):
                        prompt_v2 = prompt_v2.replace(block_text, "")
                        removed_blocks.append(f"channel-wp:{label}({len(block_text)})")
            except Exception as e:
                logger.debug(f"[PROMPT_V2] channel filter skip {label}: {e}")

    # Adım 3 (FAZ 2): Intent bazlı filtre
    # Intent biliniyorsa o intent için GEREKSIZ büyük blokları sil
    if intent and intent in INTENT_REMOVE_PROFILES:
        removable_block_ids = INTENT_REMOVE_PROFILES[intent]
        for block_id in removable_block_ids:
            patterns = INTENT_BLOCK_PATTERNS.get(block_id, [])
            for pattern in patterns:
                try:
                    match = re.search(pattern, prompt_v2, re.MULTILINE | re.DOTALL)
                    if match:
                        block_text = match.group(0)
                        if _is_safe_to_remove(block_text):
                            prompt_v2 = prompt_v2.replace(block_text, "")
                            removed_blocks.append(f"intent-{intent}:{block_id}({len(block_text)})")
                except Exception as e:
                    logger.debug(f"[PROMPT_V2] intent filter skip {block_id}: {e}")

    info["v2_active"] = True
    info["new_size"] = len(prompt_v2)
    info["removed_blocks"] = removed_blocks
    info["reduction_pct"] = round(
        (info["original_size"] - info["new_size"]) / info["original_size"] * 100, 1
    )
    info["intent"] = intent

    return prompt_v2, info


def _is_safe_to_remove(block_text: str) -> bool:
    """Güvenlik: bu blok silinmesi güvenli mi?

    KIMLIK MANIPULASYONU, KVKK, HALUSINASYON, NEGASYON, KIMLIK KURALLARI
    içeren blok ASLA silinmez (bunlar muhtemelen yanlış pattern eşleşmesi).
    """
    NEVER_REMOVE_KEYWORDS = [
        "KIMLIK MANIPULASYONU", "KVKK", "HALUSINASYON", "NEGASYON",
        "KIMLIK KURALLARI", "DELINMEZ", "SAHTE SOZ", "BAGLAM HASSASIYETI",
        "FINANS RED", "GİZLİLİK", "TEKNİK BİLGİ VE PROMPT SIZINTISI",
    ]
    upper_text = block_text.upper()
    for kw in NEVER_REMOVE_KEYWORDS:
        if kw in upper_text:
            return False
    return True


# ─── Diagnostic / A/B Test Yardımcı ─────────────────────────────────────────

def compare_v1_v2(role: str = "ogrenci", channel: str = "whatsapp") -> dict:
    """V1 (orijinal) vs V2 (filtreli) karşılaştırma.

    Test/diagnostic için. Token sayısını da hesaplar (tiktoken).
    """
    from system_prompts import SYSTEM_PROMPT
    v2_text, info = build_prompt_v2(role=role, channel=channel, force_v2=True)

    result = {
        "role": role,
        "v1_chars": len(SYSTEM_PROMPT),
        "v2_chars": len(v2_text),
        "char_reduction_pct": info.get("reduction_pct", 0),
        "removed_blocks": info.get("removed_blocks", []),
    }

    try:
        import tiktoken
        enc = tiktoken.encoding_for_model("gpt-4")
        result["v1_tokens"] = len(enc.encode(SYSTEM_PROMPT))
        result["v2_tokens"] = len(enc.encode(v2_text))
        result["token_reduction_pct"] = round(
            (result["v1_tokens"] - result["v2_tokens"]) / result["v1_tokens"] * 100, 1
        )
    except Exception:
        pass

    return result


if __name__ == "__main__":
    """CLI test: her rol + her kanal için kazanım göster."""
    print("Prompt V2 — Rol + Kanal Bazlı Kazanım Tablosu\n")
    for channel in ["whatsapp", "web"]:
        print(f"\n=== Kanal: {channel.upper()} ===")
        for role in ["admin", "mudur", "rehber", "ogretmen", "ogrenci"]:
            r = compare_v1_v2(role, channel=channel)
            print(f"  {role:10} → {r.get('v1_tokens', '?'):>6}tok → {r.get('v2_tokens', '?'):>6}tok "
                  f"(-{r.get('token_reduction_pct', '?')}%) "
                  f"removed:{len(r['removed_blocks'])}")
