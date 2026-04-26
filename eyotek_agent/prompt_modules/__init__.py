"""
Modüler prompt sistemi (Oturum 25.18 — Faz 5 iskelet)
========================================================

Asıl extract işi: SYSTEM_PROMPT'taki blokları ayrı dosyalara taşımak.
Şu an iskelet hazır, gerçek extract bir sonraki oturumda yapılacak
(hassas iş — test ile birlikte).

GELECEK MODÜL LİSTESİ:
- karakter.py — Karakter ruhu + üslup (~2k tok)
- kurumsal.py — Fermat kurum bilgileri (~1k tok)
- kvkk_acl.py — Yetki, KVKK, ACL kuralları (~3k tok)
- finans.py — Finans red kuralları (~1.5k tok)
- pedagoji.py — Pedagojik destek + şablon (~3k tok)
- scenario.py — Öğrenci/öğretmen senaryoları (~3k tok)
- atlas.py — Admin self-awareness (~2k tok)
- easter.py — Easter egg referansları (~2k tok)

ŞİMDİLİK:
- LIGHT_PROMPT (prompt_tiers.LIGHT_PROMPT) — KVKK + finans yasak entegre
- NORMAL_PROMPT (prompt_tiers.NORMAL_PROMPT) — + plan/analiz protokolü
- FULL_PROMPT (system_prompts.SYSTEM_PROMPT) — mevcut monolitik

Composer kullanımı (gelecek):
    from prompt_modules.composer import build_prompt
    prompt = build_prompt(["karakter", "kvkk_acl", "finans"])
"""
from .composer import build_prompt, list_available_modules

__all__ = ["build_prompt", "list_available_modules"]
