"""
FermatAI — Tool Dispatcher Katmanı (Oturum 23 audit split)
==============================================================
fermat_core_agent.py içinde 4273 satır içinde dolaşan tool wrapper'ları
bu paketten import edilir. Her wrapper pure pass-through — dispatch'e
karışmaz, sadece parametreleri hazırlayıp iş modülüne iletir.

Kullanım (fermat_core_agent.py içinden):
    from tools.finans import _tool_finans_ozet, _tool_ogrenci_borc_detay, ...
    from tools.tercih import _tool_tercih_profili_kaydet, ...
    from tools.ogretmen import _tool_ogretmen_brief, ...
    from tools.kaynak import _tool_konu_kaynak_paketi, _tool_youtube_oner, ...

Güvenlik: Wrapper'lar iç modüllere aynen devreder. ACL kontrolü
`role_access._is_tool_allowed` ile run_tool seviyesinde zaten yapılıyor.
"""
