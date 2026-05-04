# -*- coding: utf-8 -*-
"""
Modüler prompt sistemi (Oturum 25.40z3 — V3 modular parsing)
==============================================================

V3 mimarisi: SYSTEM_PROMPT'tan 3 büyük modül EXTRACT edildi.
BASE = SYSTEM_PROMPT - (3 modül) ≈ persona + güvenlik + roller + KVKK + tools

Modüller:
- pedagoji_extended.py (~38K char) — pedagojik ton + plan + yeni nesil + tutarlılık
- render_extended.py (~25K char) — chart/3d/sim/compound/compton/renderer
- db_schema_extended.py (~12K char) — students/student_exams + SQL pattern

Kullanım:
    from prompt_modules.composer_v3 import build_prompt_v3, get_base_prompt

    # String compose (V2 uyumlu)
    text, info = build_prompt_v3('ogrenci', 'kavram_aciklama', 'web')

    # Anthropic API hierarchical block (cache_control destekli)
    blocks, info = build_prompt_v3('ogrenci', 'kavram', 'web', return_blocks=True)

NOT (25.40z3-MIMARI #8): Eski V1 composer.py (iskelet, hiç implement edilmedi)
4 May 2026'da silindi — tek modüler kaynak: composer_v3.
"""
from .composer_v3 import build_prompt_v3, get_base_prompt

__all__ = ["build_prompt_v3", "get_base_prompt"]
