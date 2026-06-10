"""
practice_engine.py — Adaptif Soru Üretimi / Pratik Halkası (Oturum 25.54, Neo dikey-AI)
=======================================================================================
Öğrenme döngüsünü KAPATIR: knowledge_state zayıf konuyu bilir → o konudan ÖZGÜN
TYT/AYT-format soru + 4 çeldirici + çözüm üret → öğrenci cevaplar → değerlendir →
mastery güncellenir. Sınırsız kişiye-özel pratik.

Kalite: RAG'daki gerçek çıkmış sorular FEW-SHOT örnek (Maarif standardı). Üretim
Cerebras gpt-oss-120b (ucuz/hızlı), JSON parse fail → Claude fallback.

⚠️ OUTREACH YOK: Sadece öğrenci "soru ver/çöz/pratik yap" deyince çalışır. Otomatik
soru GÖNDERMEZ. State (aktif soru) DB'de tutulur → öğrenci cevabı değerlendirilir.

Kullanım:
  from practice_engine import generate_practice_question, evaluate_practice_answer
  q = await generate_practice_question(soz_no, konu=None)   # zayıf konudan
  res = await evaluate_practice_answer(soz_no, "B")

Tool: generate_practice_question(soz_no, ders, konu) + check_practice_answer(soz_no, cevap)
"""
from __future__ import annotations

import json
import re
from loguru import logger

from db_pool import db_execute, db_fetchrow


async def _ensure_table():
    await db_execute("""
        CREATE TABLE IF NOT EXISTS practice_active (
            soz_no      INT PRIMARY KEY,
            question_json JSONB NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""")


# ── Zayıf konu seçimi (knowledge_state) ───────────────────────────────────────
async def _pick_weak_topic(soz_no: int, ders: str = "", konu: str = "") -> tuple[str, str, float]:
    """Konu verilmemişse knowledge_state'ten en zayıf (çalışılmamış) konuyu seç."""
    if konu:
        return ders or "", konu, 0.0
    try:
        from knowledge_state import get_knowledge_state
        st = await get_knowledge_state(soz_no)
        weak = st.get("weak_topics") or st.get("all_topics") or []
        if ders:
            weak = [w for w in weak if (w.get("ders") or "").lower() == ders.lower()] or weak
        if weak:
            w = weak[0]
            return w.get("ders", ""), w.get("konu", ""), float(w.get("basari", 0) or 0)
    except Exception as e:
        logger.debug(f"[practice] zayıf konu seçimi hatası: {e}")
    return ders or "", konu or "", 0.0


# ── RAG few-shot (gerçek çıkmış soru örneği) ──────────────────────────────────
async def _rag_examples(ders: str, konu: str, limit: int = 2) -> str:
    try:
        from rag_engine import search_curriculum
        q = f"{ders} {konu}".strip()
        rows = await search_curriculum(q, ders=ders or "", limit=limit)
        ex = []
        for r in (rows or [])[:limit]:
            txt = (r.get("icerik") or r.get("content") or "")[:600]
            if txt:
                ex.append(txt)
        if ex:
            return "\n\nGERÇEK ÇIKMIŞ SORU ÖRNEKLERİ (stil/zorluk referansı — KOPYALAMA, ilham al):\n" + "\n---\n".join(ex)
    except Exception as e:
        logger.debug(f"[practice] RAG few-shot hatası: {e}")
    return ""


# ── LLM üretim (Cerebras → Claude fallback) ───────────────────────────────────
_GEN_SYSTEM = (
    "Sen YKS/LGS uzmanı soru yazarısın. Verilen ders+konuda ÖZGÜN, Türkiye müfredatına "
    "uygun, TEK doğru cevaplı çoktan seçmeli (A-E) bir soru üret. Çeldiriciler GERÇEKÇI "
    "olmalı (tipik öğrenci hatalarını yansıtsın). SADECE geçerli JSON döndür, başka metin YOK:\n"
    '{"soru":"...","secenekler":{"A":"...","B":"...","C":"...","D":"...","E":"..."},'
    '"dogru":"B","cozum":"adım adım çözüm","zorluk":"orta"}'
)


def _parse_question_json(text: str) -> dict | None:
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        q = json.loads(m.group(0))
        if q.get("soru") and isinstance(q.get("secenekler"), dict) and q.get("dogru"):
            q["dogru"] = str(q["dogru"]).strip().upper()[:1]
            return q
    except Exception:
        return None
    return None


async def _generate_via_llm(ders: str, konu: str, fewshot: str) -> dict | None:
    user = (f"Ders: {ders or 'Genel'}\nKonu: {konu or 'Genel'}\n"
            f"Bu konudan TYT/AYT seviyesinde 1 özgün soru üret.{fewshot}")
    # 1) Cerebras (ucuz/hızlı)
    try:
        from cerebras_handler import CerebrasClient
        c = CerebrasClient()
        if getattr(c, "api_key", None):
            r = await c.complete_async(
                messages=[{"role": "user", "content": user}],
                system=_GEN_SYSTEM, model="gpt-oss-120b", max_tokens=1200, intent="soru_uret")
            if r.get("ok"):
                q = _parse_question_json(r.get("text", ""))
                if q:
                    q["_engine"] = "cerebras"
                    return q
    except Exception as e:
        logger.debug(f"[practice] Cerebras üretim hatası: {e}")
    # 2) Claude fallback
    try:
        import os
        from anthropic import Anthropic
        import asyncio as _aio
        key = os.getenv("ANTHROPIC_API_KEY", "")
        if key:
            cl = Anthropic(api_key=key)
            # 25.58-C: claude-sonnet-4-20250514 EOL 15 Haz 2026 — env-driven güncel model
            resp = await _aio.to_thread(
                cl.messages.create, model=os.getenv("FERMAT_MODEL", "claude-sonnet-4-6"), max_tokens=1200,
                system=_GEN_SYSTEM, messages=[{"role": "user", "content": user}])
            txt = "".join(b.text for b in resp.content if hasattr(b, "text"))
            q = _parse_question_json(txt)
            if q:
                q["_engine"] = "claude"
                return q
    except Exception as e:
        logger.debug(f"[practice] Claude üretim hatası: {e}")
    return None


# ── Ana fonksiyonlar ──────────────────────────────────────────────────────────
async def generate_practice_question(soz_no, ders: str = "", konu: str = "") -> dict:
    """Zayıf konudan (veya verilen konudan) özgün soru üret + aktif state'e yaz."""
    soz_no = int(soz_no)
    await _ensure_table()
    d, k, basari = await _pick_weak_topic(soz_no, ders, konu)
    fewshot = await _rag_examples(d, k)
    q = await _generate_via_llm(d, k, fewshot)
    if not q:
        return {"basarili": False, "error": "Soru üretilemedi, tekrar dener misin?"}
    q["ders"], q["konu"] = d, k
    # Aktif soruyu kaydet (cevap değerlendirme için) — doğru + çözüm gizli tutulur
    try:
        await db_execute(
            """INSERT INTO practice_active (soz_no, question_json, created_at)
               VALUES ($1, $2, NOW())
               ON CONFLICT (soz_no) DO UPDATE SET question_json=$2, created_at=NOW()""",
            soz_no, json.dumps(q, ensure_ascii=False))
    except Exception as e:
        logger.debug(f"[practice] state yazma hatası: {e}")
    return {
        "basarili": True, "ders": d, "konu": k, "zayif_basari": basari,
        "soru": q["soru"], "secenekler": q["secenekler"], "zorluk": q.get("zorluk", "orta"),
        # dogru + cozum CEVAPTA DÖNMEZ (öğrenci önce cevaplasın)
    }


async def evaluate_practice_answer(soz_no, student_answer: str) -> dict:
    """Öğrencinin cevabını aktif soruyla karşılaştır + geri bildirim + çözüm + mastery güncelle."""
    soz_no = int(soz_no)
    row = await db_fetchrow(
        "SELECT question_json FROM practice_active WHERE soz_no = $1", soz_no)
    if not row:
        return {"basarili": False, "error": "Aktif soru yok — önce 'soru ver' de."}
    q = row["question_json"]
    if isinstance(q, str):
        q = json.loads(q)
    sec = (student_answer or "").strip().upper()
    m = re.search(r"[A-E]", sec)
    sec = m.group(0) if m else sec[:1]
    dogru_mu = (sec == q.get("dogru"))
    # State temizle (tek soru tek deneme)
    try:
        await db_execute("DELETE FROM practice_active WHERE soz_no = $1", soz_no)
    except Exception:
        pass
    # Mastery güncelle (salt kayıt — practiced sinyali topic_tracker'a)
    try:
        await db_execute(
            """UPDATE student_topic_tracker SET calisti_tarih = NOW()
               WHERE soz_no = $1 AND ders = $2 AND konu = $3""",
            soz_no, q.get("ders", ""), q.get("konu", ""))
    except Exception as e:
        logger.debug(f"[practice] mastery güncelleme hatası: {e}")
    return {
        "basarili": True, "dogru_mu": dogru_mu,
        "ogrenci_cevap": sec, "dogru_cevap": q.get("dogru"),
        "cozum": q.get("cozum", ""), "ders": q.get("ders"), "konu": q.get("konu"),
    }


def format_practice_question(res: dict, name: str = "") -> str:
    first = (name.split()[0] if name else "") or "öğrenci"
    if not res.get("basarili"):
        return f"⚠️ {res.get('error', 'Soru üretilemedi.')}"
    lines = [f"📝 *{first} — Pratik Soru* _({res['ders']} · {res['konu']})_", ""]
    lines.append(res["soru"])
    lines.append("")
    for sik in ("A", "B", "C", "D", "E"):
        if sik in res["secenekler"]:
            lines.append(f"*{sik})* {res['secenekler'][sik]}")
    lines.append("\n_Cevabını yaz (A/B/C/D/E) — birlikte kontrol edelim!_ 🎯")
    return "\n".join(lines)


def format_practice_result(res: dict, name: str = "") -> str:
    if not res.get("basarili"):
        return f"⚠️ {res.get('error', '')}"
    if res["dogru_mu"]:
        head = f"✅ *Doğru!* Cevap *{res['dogru_cevap']}*. Harika — {res['konu']} konusunda ilerliyorsun! 🎉"
    else:
        head = (f"❌ Senin cevabın *{res['ogrenci_cevap']}*, doğrusu *{res['dogru_cevap']}*. "
                f"Üzülme — birlikte bakalım:")
    return f"{head}\n\n*Çözüm:*\n{res.get('cozum','')}\n\n_Bir soru daha ister misin?_ 💪"


if __name__ == "__main__":
    import asyncio
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    async def _main():
        soz = int(sys.argv[1]) if len(sys.argv) > 1 else 167
        q = await generate_practice_question(soz)
        print(format_practice_question(q, ""))
        if q.get("basarili"):
            print("\n[SIMÜLE CEVAP: A]")
            r = await evaluate_practice_answer(soz, "A")
            print(format_practice_result(r, ""))

    asyncio.run(_main())
