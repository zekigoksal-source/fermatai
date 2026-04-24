"""
Deep Research Mode (23 Nisan)
================================
Öğrenci "X konusunu tam öğrenmek istiyorum" → 15-20 dk pipeline:
  1. RAG konu anlatımı
  2. Çıkmış soru örnekleri (OGM Vision)
  3. Gamification check (achievement)
  4. Spaced Rep kuyruğa al
  5. Adaptive difficulty analiz
"""
from __future__ import annotations
from loguru import logger


async def deep_study_package(soz_no: int, konu: str, ders: str = "") -> dict:
    """Bir konuya DAİR her şey — tek pakette."""
    out = {"konu": konu, "ders": ders, "bolumler": []}
    try:
        # 1) RAG konu anlatımı
        from rag_engine import search_curriculum
        rag_hits = await search_curriculum(konu, ders=ders, limit=3)
        if rag_hits:
            out["bolumler"].append({
                "tip": "konu_anlatim",
                "baslik": "📚 Konu Anlatımı",
                "kaynaklar": [{"baslik": h.get("baslik"), "icerik": (h.get("icerik") or "")[:800]} for h in rag_hits[:2]],
            })

        # 2) Çıkmış soru
        try:
            from fermat_core_agent import _tool_list_exam_questions
            qs = await _tool_list_exam_questions(konu=konu, ders=ders)
            if qs and isinstance(qs, dict) and qs.get("sorular"):
                out["bolumler"].append({
                    "tip": "cikmis_soru",
                    "baslik": "📸 Çıkmış Sorular",
                    "sayi": len(qs["sorular"][:3]),
                    "ornekler": qs["sorular"][:3],
                })
        except Exception:
            pass

        # 3) Spaced repetition kuyruğa al
        try:
            from spaced_repetition import schedule_review
            await schedule_review(soz_no, ders, konu)
            out["bolumler"].append({
                "tip": "spaced_rep",
                "baslik": "🧠 Tekrar Programı",
                "plan": "1 gün → 3 gün → 7 gün → 14 gün (otomatik hatırlatma)",
            })
        except Exception:
            pass

        # 4) Adaptive seviye
        try:
            from adaptive_difficulty import get_level, suggest_zorluk
            lvl = await get_level(soz_no)
            z = suggest_zorluk(lvl.get("seviye", "tanimsiz"))
            out["bolumler"].append({
                "tip": "zorluk",
                "baslik": "🎯 Seviyene Göre",
                "seviye": lvl.get("seviye"),
                "oneri": z["odak"],
            })
        except Exception:
            pass

        return out
    except Exception as e:
        logger.debug(f"deep_research: {e}")
        return out


async def format_deep_package(paket: dict, name: str = "") -> str:
    """WhatsApp uyumlu derin paket mesajı."""
    first = (name or "").split()[0] if name else ""
    lines = [
        f"🔬 *{first} — Derin Çalışma Paketi*",
        f"*Konu:* {paket.get('konu', '?')}",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]
    for bol in paket.get("bolumler", []):
        lines.append(f"*{bol.get('baslik', '')}*")
        if bol["tip"] == "konu_anlatim":
            for k in bol.get("kaynaklar", [])[:1]:
                lines.append(f"_{k.get('baslik', '')}_")
                lines.append(f"{k.get('icerik', '')[:400]}")
        elif bol["tip"] == "cikmis_soru":
            lines.append(f"{bol.get('sayi', 0)} çıkmış soru hazır — 'çıkmış sorular' yaz, örnekleri gör.")
        elif bol["tip"] == "spaced_rep":
            lines.append(f"{bol.get('plan', '')}")
        elif bol["tip"] == "zorluk":
            lines.append(f"Seviye: *{bol.get('seviye', '?')}* — {bol.get('oneri', '')}")
        lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"_Hangi bölümden başlamak istersin?_ 🎯")
    return "\n".join(lines)
