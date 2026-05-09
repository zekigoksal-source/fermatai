"""
admin_service — Admin/yönetim meta tool'ları (Oturum 25.41-REFACTOR, 9 May)
============================================================================

fermat_core_agent.py'den taşınan admin tool fonksiyonları:
  - counsellor_brief         (9 satır) — rehber brief wrapper
  - class_brief              (12 satır) — sınıf brief wrapper
  - get_recent_system_updates (24 satır) — KALDIGIM canlı okuma
  - get_blueprint_section    (63 satır) — BLUEPRINT bolum erişimi
  - get_atlas_trend          (305 satır) — Atlas trend raporu (DİKKATLİ: en büyük tool)

Mimari ilke:
    "Brain centralized (fermat_core_agent), execution modular (services/)"
"""
from __future__ import annotations
from typing import Any


# ─────────────────────────────────────────────────────────────────────────
# counsellor_brief (taşındı — fermat_core_agent.py:1079-1085)
# ─────────────────────────────────────────────────────────────────────────

async def counsellor_brief(**kwargs) -> dict:
    """Rehber brief — tek çağrıda öğrenci özeti + veli mesaj taslağı + öncelikler."""
    from role_briefs import prepare_counsellor_brief
    soz_no = kwargs.get("soz_no")
    if not soz_no:
        return {"error": "soz_no zorunlu"}
    return await prepare_counsellor_brief(int(soz_no))


# ─────────────────────────────────────────────────────────────────────────
# class_brief (taşındı — fermat_core_agent.py:1088-1097)
# ─────────────────────────────────────────────────────────────────────────

async def class_brief(**kwargs) -> dict:
    """Öğretmen sınıf brief — bugünün dersine hazırlık."""
    from role_briefs import get_class_brief
    sinif = (kwargs.get("sinif") or "").strip()
    if not sinif:
        return {"error": "sinif zorunlu"}
    return await get_class_brief(
        sinif=sinif, ders=kwargs.get("ders", ""),
        tarih=kwargs.get("tarih", "")
    )


# ─────────────────────────────────────────────────────────────────────────
# get_recent_system_updates (taşındı — fermat_core_agent.py:1433-1454)
# ─────────────────────────────────────────────────────────────────────────

async def get_recent_system_updates(**kwargs) -> dict:
    """KALDIGIM.md canlı okuma — admin/mudur/yonetim tam, diğer roller header."""
    caller_role = kwargs.get("_caller_role", "")
    max_sessions = min(int(kwargs.get("max_sessions") or 3), 5)
    max_chars = min(int(kwargs.get("max_chars") or 4000), 8000)
    try:
        from system_awareness import get_recent_updates
        result = get_recent_updates(max_sessions=max_sessions, max_chars=max_chars)

        # Teknik detay filtre — sadece admin/mudur/yonetim tam görür
        if caller_role not in ("admin", "mudur", "yonetim"):
            return {
                "info": "Sistem son guncelleme bilgisi",
                "son_guncelleme": result.get("header_info", {}).get("son_guncelleme", "-"),
                "gun": result.get("file_modified_at", "-"),
                "not": "Detaylı teknik gecmis admin erisimindedir.",
            }
        return result
    except Exception as e:
        return {"error": f"Sistem guncelleme okuma hatasi: {e}"}


# ─────────────────────────────────────────────────────────────────────────
# get_blueprint_section (taşındı — fermat_core_agent.py:1457-1517)
# ─────────────────────────────────────────────────────────────────────────

async def get_blueprint_section(**kwargs) -> dict:
    """BLUEPRINT.md bolum erişimi — bot mimari sorularda canlı okuma."""
    section = kwargs.get("section", "")
    caller_role = kwargs.get("_caller_role", "")
    if not section:
        # Default: section listesi
        try:
            from blueprint_awareness import list_blueprint_sections
            sections = list_blueprint_sections()
            return {
                "info": "BLUEPRINT.md tum bolumler (detay icin section parametresi ver)",
                "sections": [{"num": s["num"], "title": s["title"]} for s in sections],
                "ornek": "section=3 veya section='LLM Routing'",
            }
        except Exception as e:
            return {"error": str(e)[:200]}

    try:
        from blueprint_awareness import get_blueprint_section as _get_section, search_blueprint
        # Numerik mi yoksa keyword mu?
        try:
            sec_num = int(section)
            result = _get_section(sec_num)
        except (ValueError, TypeError):
            result = _get_section(str(section))

        if result:
            # Diger roller için trim — admin/mudur/yonetim/rehber tam icerik
            if caller_role not in ("admin", "mudur", "yonetim", "rehber"):
                content = result["content"][:800] + "\n[... detay yonetim erisiminde]"
                return {
                    "num": result["num"],
                    "title": result["title"],
                    "preview": content,
                    "not": "Tam icerik yonetim erisimine acik.",
                }
            return {
                "num": result["num"],
                "title": result["title"],
                "content": result["content"][:5000],
                "char_count": result["char_count"],
            }
        # Bulamadı → search
        hits = search_blueprint(section, max_results=3)
        if hits:
            return {
                "info": f"'{section}' bolum olarak bulunamadi, keyword araamasi yapildi",
                "hits": [
                    {"num": h["num"], "title": h["title"], "snippet": h["snippet"][:300]}
                    for h in hits
                ],
            }
        return {"error": f"'{section}' icin bolum/keyword bulunamadi"}
    except Exception as e:
        return {"error": f"BLUEPRINT okuma hatasi: {e}"}


__all__ = [
    "counsellor_brief", "class_brief",
    "get_recent_system_updates", "get_blueprint_section",
]
