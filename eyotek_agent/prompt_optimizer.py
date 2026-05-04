"""
Atlas-2 — Self-Improving Prompts (Oturum 25.9)
==================================================
Bot kendi konusmalarini her gece analiz eder, prompt iyilestirme onerisi
uretir, Neo onaylar, otomatik patch + commit + VPS sync.

Akış:
  1. Her gece 02:00 (cron) — analyze_and_suggest()
  2. Son 24h konusmalarda problem tespit (frustration, baglam_kaybi,
     yanlis_data, halusinasyon, eksik_pattern)
  3. Groq 70B'ye sorulur — somut prompt degisikligi onerisi
  4. prompt_suggestions tablosuna kaydedilir (status='pending')
  5. Sabah Neo dashboard'da gorur, "approve" tikalar
  6. Approved oldugunda → otomatik git patch + commit + VPS sync + restart
  7. A/B test: 7 gun sonra metrik karsilastirilir, kotu ise rollback

GUVENLIK:
  • Auto-apply YOK — Neo onayi zorunlu
  • Rollback hazir — eski git SHA kaydedilir
  • Critical kelime guard: "ASLA", "YASAK", KVKK kuralı silinmesin
"""
from __future__ import annotations
import asyncio
import json
import os
import re
import subprocess
from datetime import datetime, date, timedelta
from typing import Optional

from loguru import logger

from db_pool import (
    db_execute as _exec,
    db_fetch as _fetch,
    db_fetchrow as _fetchrow,
    db_fetchval as _fetchval,
)


# ── KORUNMASI GEREKEN KURAL DESENLERİ (auto-apply silmeye calismasin) ───
PROTECTED_PATTERNS = [
    r"KVKK", r"ASLA", r"YASAK", r"KIMLIK MANIPULASYON",
    r"identity_lock", r"admin", r"Neo",
    r"kural", r"sensitive_data", r"GUVENLIK",
]


async def _detect_problems(hours: int = 24) -> list[dict]:
    """Son N saat konusmalardan problem ornekleri cikar."""
    rows = await _fetch(
        f"""SELECT phone, message_role, content, created_at
            FROM agent_conversations
            WHERE created_at >= NOW() - INTERVAL '{int(hours)} hours'
              AND content NOT LIKE '[tool_calls%'
            ORDER BY phone, created_at""",
    )
    if not rows:
        return []

    # Konusmalari phone bazinda grupla
    by_phone: dict[str, list[dict]] = {}
    for r in rows:
        by_phone.setdefault(r['phone'], []).append({
            "role": r['message_role'],
            "content": r['content'],
            "ts": r['created_at'],
        })

    problems: list[dict] = []
    for phone, msgs in by_phone.items():
        for i, m in enumerate(msgs):
            if m['role'] != 'user':
                continue
            cl = (m['content'] or "").lower()

            # 1. Frustration sinyali
            if re.search(r'(yanlis anladin|anlamiyorsun|tekrar soyle|bos cevap|sa[cç]ma|zaten dedim|yine|ayni)', cl):
                problems.append({
                    "type": "frustration",
                    "phone": phone,
                    "user_msg": m['content'][:200],
                    "prev_bot": msgs[i-1]['content'][:300] if i > 0 else "",
                    "next_bot": msgs[i+1]['content'][:300] if i+1 < len(msgs) else "",
                })

            # 2. "Anlayamadim" + uzun mesaj — fast_response yetersiz
            if i+1 < len(msgs) and msgs[i+1]['role'] == 'assistant':
                next_bot = msgs[i+1]['content'].lower()
                if 'anlayamadim' in next_bot and len(m['content']) > 30:
                    problems.append({
                        "type": "missed_intent",
                        "phone": phone,
                        "user_msg": m['content'][:200],
                        "next_bot": msgs[i+1]['content'][:200],
                    })

            # 3. Tekrar mesaj — bot ayni cevabi vermisse (spam hissi)
            if i+1 < len(msgs) and msgs[i+1]['role'] == 'assistant':
                bot1 = msgs[i+1]['content'][:100]
                # Bir sonraki user mesaji + ona gelen cevap
                if i+3 < len(msgs) and msgs[i+2]['role'] == 'user' and msgs[i+3]['role'] == 'assistant':
                    bot2 = msgs[i+3]['content'][:100]
                    if bot1 == bot2 and len(bot1) > 50:
                        problems.append({
                            "type": "repeated_response",
                            "phone": phone,
                            "first_user": m['content'][:150],
                            "second_user": msgs[i+2]['content'][:150],
                            "repeated_bot": bot1[:200],
                        })

    return problems[:30]   # En çok 30 örnek


async def _ask_groq_for_suggestion(problems: list[dict]) -> list[dict]:
    """LLM'den problem ornekleri ile prompt iyilestirme onerisi sor.

    25.22 (Bot Atlas-2 bulgu): Groq daily limit dolup duruyor → 0 oneri uretiyor.
    Cerebras'a geciyoruz (gpt-oss-120b — 436ms, kaliteli, paid tier sinirsiz).
    Groq fallback olarak korunur.
    """
    if not problems:
        return []

    # Cerebras-first (paid tier, sınırsız)
    use_cerebras = bool(os.getenv("CEREBRAS_API_KEY"))
    if use_cerebras:
        try:
            from cerebras_handler import CerebrasClient
            cerebras = CerebrasClient()
        except Exception as e:
            logger.warning(f"Cerebras client init fail: {e}, Groq'a dusuyor")
            use_cerebras = False

    if not use_cerebras:
        try:
            from groq_handler import GroqClient
            client = GroqClient()
        except Exception as e:
            logger.warning(f"Groq client init fail: {e}")
            return []

    # Problem ozeti hazirla
    problem_summary = []
    for p in problems[:15]:
        if p['type'] == 'frustration':
            problem_summary.append(
                f"FRUSTRATION: User '{p['user_msg'][:100]}' — Onceki bot: '{p['prev_bot'][:200]}'"
            )
        elif p['type'] == 'missed_intent':
            problem_summary.append(
                f"MISSED INTENT: User '{p['user_msg'][:100]}' — Bot: '{p['next_bot'][:100]}'"
            )
        elif p['type'] == 'repeated_response':
            problem_summary.append(
                f"REPEAT: 2 ayri user sorusuna ayni cevap — '{p['repeated_bot'][:100]}'"
            )

    # 25.24 (Neo): Geçmiş 30 gün reddedilen öneriler ve sebepleri — bot bunlardan öğrensin
    # Sezgisellik için: aynı false positive pattern'leri tekrarlama
    past_rejections_block = ""
    try:
        past_rejected = await _fetch(
            """SELECT title, description, reviewer_note
               FROM prompt_suggestions
               WHERE status='rejected' AND reviewer_note IS NOT NULL AND reviewer_note != ''
                 AND reviewed_at >= NOW() - INTERVAL '30 days'
               ORDER BY reviewed_at DESC LIMIT 10"""
        )
        if past_rejected:
            past_rejections_block = (
                "\n\n📛 GEÇMİŞTE REDDEDİLEN ÖNERİLER (Neo'nun açıklamasıyla):\n"
                "Bu önerileri TEKRAR ÜRETME, benzer pattern'leri ASLA öne sürme:\n\n"
            )
            for i, r in enumerate(past_rejected[:10], 1):
                past_rejections_block += (
                    f"{i}. ❌ '{r['title']}'\n"
                    f"   Neden reddedildi: {(r['reviewer_note'] or '')[:300]}\n\n"
                )
    except Exception:
        pass

    # Geçmiş onaylanan öneriler — bunlara benzer pattern'ler değerli
    past_approvals_block = ""
    try:
        past_approved = await _fetch(
            """SELECT title FROM prompt_suggestions
               WHERE status='approved' AND reviewed_at >= NOW() - INTERVAL '30 days'
               ORDER BY reviewed_at DESC LIMIT 10"""
        )
        if past_approved:
            past_approvals_block = (
                "\n✅ GEÇMİŞTE ONAYLANAN ÖNERİLER (bu tip öneriler değerli):\n"
                + "\n".join(f"  - {r['title']}" for r in past_approved[:10])
                + "\n"
            )
    except Exception:
        pass

    user_prompt = (
        "FermatAI bot konusmalarinda son 24 saatte tespit ettigim problem ornekleri:\n\n"
        + "\n".join(f"{i+1}. {s}" for i, s in enumerate(problem_summary))
        + past_rejections_block
        + past_approvals_block
        + "\n\nGOREVIN: Her problem icin SOMUT bir system_prompts.py iyilestirme "
        "onerisi uret. ÇIKTI TAMAMI TÜRKÇE OLMALI. JSON formatinda don:\n"
        "[\n"
        "  {\n"
        '    "category": "bug|improvement|pattern",\n'
        '    "severity": "high|medium|low",\n'
        '    "title": "TÜRKÇE kısa başlık (örn: \'Bot bazen cevabi yarim kesiyor\')",\n'
        '    "description": "TÜRKÇE — sorunun ne, neden olusuyor (1-2 cumle)",\n'
        '    "affected_pattern": "TÜRKÇE — hangi tip mesaj kalibinda olusuyor",\n'
        '    "suggested_change": "TÜRKÇE — system_prompts.py icine eklenecek kural metni",\n'
        '    "expected_impact": "TÜRKÇE — beklenen iyilesme"\n'
        "  }\n"
        "]\n\n"
        "ÖNEMLİ KURALLAR:\n"
        "- Tüm metin alanları TÜRKÇE yazılacak (severity/category enum hariç).\n"
        "- Maks 5 öneri.\n"
        "- KVKK / GÜVENLİK kurallarını ASLA ZAYIFLATMA.\n"
        "- Sadece JSON dön, başka açıklama metni yok.\n"
        "- Türkçe karakterler doğru kullan (ç, ş, ğ, ü, ö, ı)."
    )

    sys_prompt = (
        "Sen FermatAI'nin LLM prompt mühendisisin. Türkçe konuşan bir botun "
        "konuşma loglarını analiz ederek, sistem promptunda yapılacak somut "
        "iyileştirme önerilerini TÜRKÇE olarak üretirsin. JSON formatında "
        "yanıt verirsin, açıklama metni eklemezsin."
    )
    text = ""
    used_model = None
    # 25.40z3-ATLAS2 MIMARI: Cerebras qwen-3-235b ASIL, Groq YEDEK (Neo prensibi)
    # Önce Cerebras dene (sınırsız paid tier, üst kalite), runtime hata olursa Groq'a düş.
    if use_cerebras:
        try:
            r = cerebras.complete(
                messages=[{"role": "user", "content": user_prompt}],
                system=sys_prompt,
                model="qwen-3-235b-a22b-instruct-2507",
                max_tokens=2000,
                temperature=0.3,
            )
            if r.get("ok"):
                text = r["text"]
                used_model = "cerebras_qwen-3-235b"
                logger.info(f"[ATLAS-2] Cerebras qwen-3-235b yaniti: {r['ms']}ms, in={r['tokens_in']} out={r['tokens_out']}")
            else:
                logger.warning(f"[ATLAS-2] Cerebras fail ({r.get('error', 'unknown')}), Groq'a duşuyor")
        except Exception as _ce:
            logger.warning(f"[ATLAS-2] Cerebras exception ({_ce}), Groq'a duşuyor")

    # Groq fallback (Cerebras yok VEYA Cerebras runtime fail)
    if not text and client:
        try:
            response = client.chat(
                messages=[{"role": "user", "content": user_prompt}],
                system=sys_prompt,
                max_tokens=2000,
            )
            text = response if isinstance(response, str) else (response.get('text', '') if isinstance(response, dict) else '')
            used_model = "groq_llama-3.3-70b"
            logger.info(f"[ATLAS-2] Groq Llama 70B fallback yaniti")
        except Exception as _ge:
            logger.warning(f"[ATLAS-2] Groq fallback exception: {_ge}")

    if not text:
        logger.warning("[ATLAS-2] Hicbir LLM yanit veremedi (Cerebras + Groq fail)")
        return []

    try:
        # JSON parse — Markdown code block kaldır
        text = re.sub(r'^```json\s*', '', text.strip())
        text = re.sub(r'\s*```$', '', text)
        suggestions = json.loads(text)
        if isinstance(suggestions, list):
            # Her oneriye hangi model uretti bilgisi ekle (debug için)
            for s in suggestions:
                s['_generator_model'] = used_model
            return suggestions[:5]
        return []
    except Exception as e:
        logger.warning(f"[ATLAS-2] JSON parse fail ({used_model}): {e}")
        return []


async def analyze_and_suggest(hours: int = 24) -> dict:
    """Ana orchestration: problem tespit + Groq oneri + DB'ye kaydet.

    Cron her gece 02:00 calistirir.
    Returns: {"problems_found": N, "suggestions_saved": M}
    """
    logger.info(f"[ATLAS-2] Son {hours}h problem analizi basliyor...")
    problems = await _detect_problems(hours)
    logger.info(f"[ATLAS-2] {len(problems)} problem tespit edildi")

    if not problems:
        return {"problems_found": 0, "suggestions_saved": 0}

    suggestions = await _ask_groq_for_suggestion(problems)
    logger.info(f"[ATLAS-2] Groq {len(suggestions)} oneri uretti")

    # 25.40z3-ATLAS2 FIX: Mevcut DB'deki tum approved/rejected basliklari yukle
    # Aynı normalize başlık varsa ÜRETME (her gece 5 aynı öneri sorununun çözümü)
    existing_norms = set()
    try:
        existing_rows = await _fetch(
            """SELECT lower(regexp_replace(title, '\\d+', 'N', 'g')) as norm
               FROM prompt_suggestions
               WHERE status IN ('approved', 'rejected', 'superseded', 'applied', 'pending')
                 AND created_at > NOW() - INTERVAL '90 days'"""
        )
        existing_norms = {r['norm'] for r in existing_rows}
        logger.info(f"[ATLAS-2] {len(existing_norms)} mevcut başlık dedup için yüklendi")
    except Exception as _de:
        logger.warning(f"[ATLAS-2] dedup load fail: {_de}")

    import hashlib
    saved = 0
    skipped_dup = 0
    for s in suggestions:
        # Critical pattern guard — koruma kurallari etkilenir mi
        change_text = (s.get('suggested_change') or '').lower()
        is_dangerous = any(re.search(p, change_text, re.IGNORECASE) for p in PROTECTED_PATTERNS)
        if is_dangerous:
            s['_safety_flag'] = 'protected_pattern_touched'

        # 25.40z3-ATLAS2 FIX: Title normalize + dedup
        title = s.get('title', '')[:200]
        norm_title = re.sub(r'\d+', 'N', title.lower())
        if norm_title in existing_norms:
            skipped_dup += 1
            logger.info(f"[ATLAS-2] DUP SKIP: '{title[:60]}' (90 gun icinde mevcut)")
            continue

        try:
            await _exec(
                """INSERT INTO prompt_suggestions
                   (category, severity, title, description, affected_pattern,
                    suggested_prompt_change, expected_impact, sample_conversations,
                    status)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'pending')""",
                s.get('category', 'improvement')[:30],
                s.get('severity', 'medium')[:20],
                title,
                s.get('description', '')[:1000],
                s.get('affected_pattern', '')[:300],
                s.get('suggested_change', '')[:2000],
                s.get('expected_impact', '')[:300],
                json.dumps(problems[:5]),
            )
            existing_norms.add(norm_title)  # Bu run'da da yeni dup olmasin
            saved += 1
        except Exception as e:
            logger.warning(f"[ATLAS-2] suggestion save fail: {e}")

    logger.info(f"[ATLAS-2] {saved} oneri DB'ye kaydedildi, {skipped_dup} duplicate atlandi")

    # Bildirime de ekle (Neo dashboard'da görsün)
    if saved > 0:
        try:
            await _exec(
                """INSERT INTO notifications (severity, category, title, body, metadata)
                   VALUES ('info', 'atlas', $1, $2, $3)""",
                f"Atlas-2: {saved} prompt iyilestirme onerisi hazir",
                f"Son {hours}h analiz: {len(problems)} problem tespit, {saved} oneri uretildi. "
                f"Dashboard'dan onayla.",
                json.dumps({"problems_count": len(problems), "suggestions_count": saved}),
            )
        except Exception:
            pass

    return {"problems_found": len(problems), "suggestions_saved": saved}


async def get_pending_suggestions(limit: int = 20) -> list[dict]:
    """Onayi bekleyen oneriler (dashboard listing)."""
    rows = await _fetch(
        """SELECT id, suggestion_date, category, severity, title, description,
                  affected_pattern, suggested_prompt_change, expected_impact,
                  sample_conversations, created_at
           FROM prompt_suggestions
           WHERE status='pending'
           ORDER BY created_at DESC LIMIT $1""",
        limit,
    )
    return [dict(r) for r in (rows or [])]


async def approve_suggestion(suggestion_id: int, reviewer: str = "neo") -> dict:
    """Bir oneriyi onayla → manual apply icin status guncelle.

    Dikkat: Bu fonksiyon SADECE status'u 'approved' yapar.
    Auto-apply icin apply_suggestion() ayrı çağrılmalı.
    """
    await _exec(
        """UPDATE prompt_suggestions SET status='approved', reviewed_at=NOW(),
                 applied_by=$2 WHERE id=$1""",
        suggestion_id, reviewer,
    )
    return {"id": suggestion_id, "status": "approved"}


async def reject_suggestion(suggestion_id: int, reviewer: str = "neo", note: str = "") -> dict:
    """Bir oneriyi reddet."""
    await _exec(
        """UPDATE prompt_suggestions SET status='rejected', reviewed_at=NOW(),
                 applied_by=$2, reviewer_note=$3 WHERE id=$1""",
        suggestion_id, reviewer, note[:500],
    )
    return {"id": suggestion_id, "status": "rejected"}


async def apply_suggestion(suggestion_id: int, dry_run: bool = True) -> dict:
    """Approved oneriyi system_prompts.py'a uygula.

    Bu CIDDI bir operasyon — dikkat:
      1. Eski git SHA kaydet
      2. system_prompts.py'a yeni metni APPEND et (ASLA delete)
      3. git commit + push + VPS sync + restart
      4. Suggestion status='applied'

    dry_run=True: gerçekten uygulamaz, sadece ne yapacağını döner.
    """
    sug = await _fetchrow(
        "SELECT * FROM prompt_suggestions WHERE id=$1 AND status='approved'",
        suggestion_id,
    )
    if not sug:
        return {"error": "suggestion not found or not approved"}

    change_text = sug['suggested_prompt_change']
    if not change_text:
        return {"error": "suggested_change empty"}

    # Critical pattern guard (son emniyet)
    if any(re.search(p, change_text.lower(), re.IGNORECASE) for p in PROTECTED_PATTERNS):
        return {"error": "protected pattern touch — manual review zorunlu"}

    if dry_run:
        return {
            "dry_run": True,
            "would_append_to": "system_prompts.py",
            "new_section_title": sug['title'],
            "change_length_chars": len(change_text),
            "preview_first_200": change_text[:200],
        }

    # Gerçek uygulama
    sp_path = "/opt/fermatai/eyotek_agent/system_prompts.py"
    if not os.path.exists(sp_path):
        sp_path = "system_prompts.py"

    # Append section
    section = (
        f"\n\n# ── ATLAS-2 ONERI #{suggestion_id} ({date.today()}): {sug['title']} ──\n"
        f"# Description: {sug['description']}\n"
        f"# Pattern: {sug['affected_pattern']}\n"
        f"_ATLAS2_RULE_{suggestion_id} = '''\n"
        f"{change_text}\n"
        f"'''\n"
    )

    try:
        with open(sp_path, "a", encoding="utf-8") as f:
            f.write(section)
    except Exception as e:
        return {"error": f"file write fail: {e}"}

    # Git SHA kaydet (rollback icin)
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=os.path.dirname(sp_path) if "/" in sp_path else ".",
            text=True,
        ).strip()
    except Exception:
        sha = ""

    await _exec(
        """UPDATE prompt_suggestions SET status='applied', applied_at=NOW(),
                 rollback_sha=$2 WHERE id=$1""",
        suggestion_id, sha,
    )

    return {"id": suggestion_id, "status": "applied", "rollback_sha": sha}


if __name__ == "__main__":
    print("Atlas-2 module loaded.")
    print(f"Protected patterns: {len(PROTECTED_PATTERNS)}")
