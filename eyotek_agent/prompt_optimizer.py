"""
Atlas-2 — Self-Improving Prompts (Oturum 25.9)
==================================================
Bot kendi konusmalarini her gece analiz eder, prompt iyilestirme onerisi
uretir, Neo onaylar, otomatik patch + commit + VPS sync.

Akış:
  1. Her gece 02:00 (cron) — analyze_and_suggest()
  2. Son 24h konusmalarda problem tespit (frustration, baglam_kaybi,
     yanlis_data, halusinasyon, eksik_pattern)
  3. Claude Opus 4.7'ye sorulur — somut prompt degisikligi onerisi
     (Cerebras qwen-235b + Groq 70B fallback)
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
import time
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

    25.44-dm11 (Neo direktifi): Atlas önerileri KRİTİK — yanlış öneri sistemi
    bozar. Birincil model **Claude Opus 4.7** (en üst kalite öz-farkındalık +
    hata tespiti + çözüm önerisi). Cerebras qwen-235b + Groq 70B fallback olarak
    korunur (Anthropic API down ise gece üretimi tamamen durmasın).
    Model env ile değiştirilebilir: ATLAS_LLM_MODEL (default: claude-opus-4-7).
    """
    if not problems:
        return []

    # ── Model zinciri için client init — hepsi bağımsız, fallback sağlam ──
    cerebras = None
    use_cerebras = bool(os.getenv("CEREBRAS_API_KEY"))
    if use_cerebras:
        try:
            from cerebras_handler import CerebrasClient
            cerebras = CerebrasClient()
        except Exception as e:
            logger.warning(f"[ATLAS-2] Cerebras client init fail: {e}")
            use_cerebras = False

    client = None  # Groq fallback — her zaman dene (use_cerebras'tan bağımsız)
    try:
        from groq_handler import GroqClient
        client = GroqClient()
    except Exception as e:
        logger.warning(f"[ATLAS-2] Groq client init fail: {e}")

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
    # 25.40z3-ATLAS2 BIRLEŞIK: atlas_suggestions tablosu (source='prompt_optimizer')
    past_rejections_block = ""
    try:
        past_rejected = await _fetch(
            """SELECT title, rationale, neo_note
               FROM atlas_suggestions
               WHERE status='rejected' AND source='prompt_optimizer'
                 AND neo_note IS NOT NULL AND neo_note != ''
                 AND created_at >= NOW() - INTERVAL '30 days'
               ORDER BY created_at DESC LIMIT 10"""
        )
        if past_rejected:
            past_rejections_block = (
                "\n\n📛 GEÇMİŞTE REDDEDİLEN ÖNERİLER (Neo'nun açıklamasıyla):\n"
                "Bu önerileri TEKRAR ÜRETME, benzer pattern'leri ASLA öne sürme:\n\n"
            )
            for i, r in enumerate(past_rejected[:10], 1):
                past_rejections_block += (
                    f"{i}. ❌ '{r['title']}'\n"
                    f"   Neden reddedildi: {(r['neo_note'] or '')[:300]}\n\n"
                )
    except Exception:
        pass

    # Geçmiş onaylanan öneriler — bunlara benzer pattern'ler değerli
    past_approvals_block = ""
    try:
        past_approved = await _fetch(
            """SELECT title FROM atlas_suggestions
               WHERE status IN ('uygulandi','applied') AND source='prompt_optimizer'
                 AND created_at >= NOW() - INTERVAL '30 days'
               ORDER BY created_at DESC LIMIT 10"""
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
        '    "severity": "critical|high|medium|low",\n'
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

    # ── 1) BİRİNCİL: Claude Opus 4.7 (25.44-dm11 Neo direktifi) ──────────────
    # Atlas önerileri sistem promptunu değiştirir → en üst kalite şart.
    # Hata olursa (key yok / API down / model id yanlış) sessizce Cerebras'a düşer.
    ATLAS_MODEL = os.getenv("ATLAS_LLM_MODEL", "claude-opus-4-7")
    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            from anthropic import Anthropic
            _cl = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"),
                            max_retries=3, timeout=120.0)
            _t0 = time.time()
            _resp = _cl.messages.create(
                model=ATLAS_MODEL,
                max_tokens=2500,
                temperature=0.3,
                system=sys_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            text = "".join(
                getattr(b, "text", "") for b in _resp.content
                if getattr(b, "type", "") == "text"
            )
            if text:
                used_model = f"claude_{ATLAS_MODEL}"
                logger.info(
                    f"[ATLAS-2] Claude {ATLAS_MODEL} yaniti: {(time.time()-_t0):.1f}s, "
                    f"in={_resp.usage.input_tokens} out={_resp.usage.output_tokens}"
                )
        except Exception as _cae:
            logger.warning(f"[ATLAS-2] Claude exception ({_cae}), Cerebras'a duşuyor")

    # ── 2) FALLBACK: Cerebras qwen-3-235b (paid tier, sınırsız) ─────────────
    if not text and use_cerebras:
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

    # ── 3) FALLBACK: Groq Llama 3.3 70B (son çare) ─────────────────────────
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
        logger.warning("[ATLAS-2] Hicbir LLM yanit veremedi (Claude + Cerebras + Groq fail)")
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

    # 25.40z3-ATLAS2 BIRLEŞIK MIMARI:
    # Atlas-1 ve Atlas-2 artık AYNI tabloyu (atlas_suggestions) kullanır.
    # source='prompt_optimizer' field ile ayrı kategorize edilir.
    # Tek dashboard tek listeden okur. Tek API tek deduplication.
    existing_norms = set()
    try:
        existing_rows = await _fetch(
            """SELECT lower(regexp_replace(title, '\\d+', 'N', 'g')) as norm
               FROM atlas_suggestions
               WHERE status IN ('uygulandi','yapildi','rejected','archived',
                                'applied','superseded','yeni','pending','ertelendi')
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

        # Title normalize + dedup
        title = s.get('title', '')[:200]
        norm_title = re.sub(r'\d+', 'N', title.lower())
        if norm_title in existing_norms:
            skipped_dup += 1
            logger.info(f"[ATLAS-2] DUP SKIP: '{title[:60]}' (90 gun icinde mevcut)")
            continue

        # Signature compute (Atlas-1 ile uyumlu)
        sig_raw = f"prompt_optimizer::{norm_title}"
        signature = hashlib.md5(sig_raw.encode('utf-8')).hexdigest()[:16]

        try:
            await _exec(
                """INSERT INTO atlas_suggestions
                   (category, severity, title, rationale, suggested_change,
                    description, affected_pattern, expected_impact,
                    sample_conversations, status, source, signature,
                    first_seen_at, last_seen_at, occurrence_count)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'yeni','prompt_optimizer',
                           $10, NOW(), NOW(), 1)""",
                s.get('category', 'improvement')[:30],
                s.get('severity', 'medium')[:20],
                title,
                s.get('description', '')[:1000],  # rationale = description
                s.get('suggested_change', '')[:2000],
                s.get('description', '')[:1000],
                s.get('affected_pattern', '')[:300],
                s.get('expected_impact', '')[:300],
                json.dumps(problems[:5]),
                signature,
            )
            existing_norms.add(norm_title)
            saved += 1
        except Exception as e:
            logger.warning(f"[ATLAS-2] suggestion save fail: {e}")

    logger.info(f"[ATLAS-2] {saved} oneri atlas_suggestions'a kaydedildi (source=prompt_optimizer), {skipped_dup} duplicate atlandi")

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
    """Onayi bekleyen prompt_optimizer onerileri (dashboard listing).

    25.40z3-ATLAS2 BIRLEŞIK: atlas_suggestions tablosundan source='prompt_optimizer'
    filtresi ile çekilir (eski prompt_suggestions tablosu deprecated).
    """
    rows = await _fetch(
        """SELECT id, category, severity, title,
                  description, affected_pattern,
                  suggested_change AS suggested_prompt_change,
                  expected_impact, sample_conversations, created_at,
                  occurrence_count, signature
           FROM atlas_suggestions
           WHERE status='yeni' AND source='prompt_optimizer'
           ORDER BY created_at DESC LIMIT $1""",
        limit,
    )
    return [dict(r) for r in (rows or [])]


async def approve_suggestion(suggestion_id: int, reviewer: str = "neo") -> dict:
    """Bir oneriyi onayla → manual apply icin status guncelle.

    25.40z3-ATLAS2 BIRLEŞIK: status='uygulandi' (Atlas-1 ile uyumlu, eski 'approved' deprecated).
    """
    await _exec(
        """UPDATE atlas_suggestions
           SET status='uygulandi', approved_at=NOW(), applied_by=$2
           WHERE id=$1""",
        suggestion_id, reviewer,
    )
    return {"id": suggestion_id, "status": "uygulandi"}


async def reject_suggestion(suggestion_id: int, reviewer: str = "neo", note: str = "") -> dict:
    """Bir oneriyi reddet."""
    await _exec(
        """UPDATE atlas_suggestions
           SET status='rejected', approved_at=NOW(), applied_by=$2, neo_note=$3
           WHERE id=$1""",
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
        """SELECT id, title, suggested_change AS suggested_prompt_change,
                  description, affected_pattern, source
           FROM atlas_suggestions
           WHERE id=$1 AND status='uygulandi' AND source='prompt_optimizer'""",
        suggestion_id,
    )
    if not sug:
        return {"error": "suggestion not found or not uygulandi"}

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
        """UPDATE atlas_suggestions SET status='applied', applied_at=NOW(),
                 neo_note=COALESCE(neo_note,'')||' rollback_sha='||$2
           WHERE id=$1""",
        suggestion_id, sha,
    )

    return {"id": suggestion_id, "status": "applied", "rollback_sha": sha}


if __name__ == "__main__":
    print("Atlas-2 module loaded.")
    print(f"Protected patterns: {len(PROTECTED_PATTERNS)}")
