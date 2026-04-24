"""
FermatAI Otonom Ogrenme Motoru — Sistem calistikca kendini gelistirir.

Her 100 mesajda veya her 2 saatte bir otomatik tetiklenir.
Konusmalari analiz eder, yeni pattern'lar cikarir, fast_response gunceller.

Guvenlik: Kritik degisiklikler admin onayina birakilir (admin_talimat tablosu).
Rutin iyilestirmeler (stop-word, format) otomatik uygulanir.

Calistirma: whatsapp_bridge icerisinden otomatik tetiklenir.
"""
import asyncio
import json
import re
from datetime import datetime, date, timedelta
from collections import Counter
from pathlib import Path

from db_pool import get_pool as _get_pool
LEARN_DIR = Path(__file__).parent / "learned_patterns"
LEARN_DIR.mkdir(exist_ok=True)

# Son calisma zamani
_last_run = None
_msg_since_last = 0


async def should_run() -> bool:
    """Calisma zamani geldi mi?"""
    global _last_run, _msg_since_last
    _msg_since_last += 1

    now = datetime.now()

    # Her 100 mesajda bir
    if _msg_since_last >= 100:
        _msg_since_last = 0
        _last_run = now
        return True

    # Veya son calismadan 2 saat gectiyse
    if _last_run is None or (now - _last_run).total_seconds() > 7200:
        _msg_since_last = 0
        _last_run = now
        return True

    return False


async def run_auto_learning():
    """Ana ogrenme dongusu — analiz et, pattern cikar, guncelle."""
    try:
        from loguru import logger
    except ImportError:
        import logging
        logger = logging.getLogger(__name__)

    logger.info("[OGRENME] Otonom ogrenme dongusu baslatildi...")

    pool = await _get_pool()
    async with pool.acquire() as conn:
        # 1. Son 2 saatteki konusmalari analiz et
        recent = await conn.fetch("""
            SELECT phone, role, message_role, content, created_at
            FROM agent_conversations
            WHERE created_at >= NOW() - INTERVAL '2 hours'
            AND message_role IN ('user', 'assistant')
            AND content NOT LIKE '[tool_calls%'
            ORDER BY created_at ASC
        """)

    if len(recent) < 5:
        logger.info("[OGRENME] Yeterli konusma yok (< 5), atlaniyor")
        return

    # 2. Hatali yanitlari tespit et
    errors = []
    for r in recent:
        if r['message_role'] != 'assistant':
            continue
        content = r['content'] or ""
        c_lower = content.lower()

        # Hata kategorileri
        if 'bulunamadi' in c_lower or 'bulunamadı' in c_lower:
            # Hangi kelime arandi?
            m = re.search(r"'(.+?)'\s*ile\s*eslesen", content)
            if m:
                errors.append({"type": "wrong_search", "term": m.group(1), "phone": r['phone']})

        elif any(x in c_lower for x in ['tooluseblock', 'textblock', 'traceback']):
            errors.append({"type": "code_leak", "sample": content[:80], "phone": r['phone']})

        elif any(x in c_lower for x in ["let's", "here are", "dive deeper", "academically"]):
            errors.append({"type": "english", "sample": content[:80], "phone": r['phone']})

        elif len(content) < 25 and r['role'] != 'admin':
            errors.append({"type": "too_short", "content": content, "phone": r['phone']})

    # 3. Sik sorulan ama fast_response'da olmayan sorulari bul
    user_msgs = [r for r in recent if r['message_role'] == 'user']
    question_patterns = Counter()

    for msg in user_msgs:
        text = (msg['content'] or "").lower().strip()
        # Soru kaliplari
        if re.search(r'(calisma|çalışma)\s*(plan|program)', text):
            question_patterns["calisma_plani"] += 1
        elif re.search(r'(bolum|bölüm|universite|üniversite)', text):
            question_patterns["bolum_hedef"] += 1
        elif re.search(r'(motivasyon|moral|pes|stres)', text):
            question_patterns["motivasyon"] += 1
        elif re.search(r'(devamsiz|devamsız|gelmedi)', text):
            question_patterns["devamsizlik"] += 1
        elif re.search(r'(etut|etüt)', text):
            question_patterns["etut"] += 1
        elif re.search(r'(sinav|sınav|deneme)', text):
            question_patterns["sinav"] += 1
        elif re.search(r'(program|ders.*program)', text):
            question_patterns["ders_programi"] += 1

    # 4. Otomatik iyilestirmeler uygula
    improvements = []

    # 4a. Yanlis aranan kelimeleri stop-word olarak kaydet
    wrong_terms = set()
    for e in errors:
        if e['type'] == 'wrong_search':
            term = e['term'].lower()
            if len(term.split()) == 1 and len(term) > 1:
                wrong_terms.add(term)

    if wrong_terms:
        # learned_patterns'a kaydet
        sw_file = LEARN_DIR / "auto_stop_words.json"
        existing = set()
        if sw_file.exists():
            try:
                existing = set(json.loads(sw_file.read_text(encoding='utf-8')))
            except Exception:
                pass
        new_words = wrong_terms - existing
        if new_words:
            existing.update(wrong_terms)
            sw_file.write_text(json.dumps(sorted(existing), ensure_ascii=False), encoding='utf-8')
            improvements.append(f"Yeni stop-word: {', '.join(new_words)}")

    # 4b. Sik tekrarlanan sorulari raporla
    frequent = [(k, v) for k, v in question_patterns.items() if v >= 3]
    if frequent:
        improvements.append(f"Sik sorulan: {', '.join(f'{k}({v}x)' for k,v in frequent)}")

    # 5. Ogrenme raporunu DB'ye kaydet
    report = {
        "timestamp": datetime.now().isoformat(),
        "analyzed_messages": len(recent),
        "errors_found": len(errors),
        "error_types": Counter(e['type'] for e in errors),
        "frequent_topics": dict(question_patterns.most_common(10)),
        "improvements_applied": improvements,
    }

    # admin_talimat tablosuna otomatik rapor
    try:
        pool = await _get_pool()
        async with pool.acquire() as conn2:
            await conn2.execute("""
                CREATE TABLE IF NOT EXISTS auto_learning_log (
                    id SERIAL PRIMARY KEY,
                    report JSONB,
                    errors_count INT DEFAULT 0,
                    improvements TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            await conn2.execute(
                "INSERT INTO auto_learning_log (report, errors_count, improvements) VALUES ($1, $2, $3)",
                json.dumps(report, ensure_ascii=False, default=str),
                len(errors),
                "; ".join(improvements) if improvements else None
            )
    except Exception:
        pass

    # Log
    logger.info(f"[OGRENME] Analiz tamamlandi: {len(recent)} mesaj, {len(errors)} hata, "
                f"{len(improvements)} iyilestirme")
    if improvements:
        for imp in improvements:
            logger.info(f"  [OGRENME] {imp}")

    return report


async def maybe_learn():
    """Otomatik ogrenme tetikleyici — her mesajdan sonra cagirilir."""
    if await should_run():
        try:
            await run_auto_learning()
        except Exception:
            pass  # Ogrenme hatasi ana akisi etkilemesin
