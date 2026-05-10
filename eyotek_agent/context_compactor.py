"""
context_compactor.py — Cerebras pre-compile / Hibrit Cevap Yardımcısı (Neo vizyonu).

Neo direktif (11 May 19:30):
"Cerebras 50+ mesaj okur, Claude'a 1K özet sunar. Bağlamı genişletip Claude'un
token kullanımını optimize ederiz."

Mimari:
  History (20-50 mesaj) → Cerebras 235B (1-2sn, $0.005/çağrı)
                       ↓
                    Compacted Summary (300-500 token)
                       ↓
  Claude'a: System prompt + Compacted summary + Son 2 mesaj (cache hit %94 korunur)

CACHE-AWARE STRATEGY:
  Anthropic prompt cache HIT %94. Cache miss durumlarında compact aktif olur.
  Cache hit durumlarında compact SKİP (Anthropic zaten optimize etmiş).
  Trigger heuristics:
    - Yeni session (history < 3 mesaj) → SKIP (compact gereksiz)
    - 3-10 mesaj → SKIP (cache verimli)
    - 10+ mesaj → ENABLE (Cerebras'ın bağlamı genişletme değeri)
    - Conversation_memory recent_user_questions > 5 farklı konu → ENABLE

Maliyet & Kalite:
  - Cerebras 235B: $0.85/Mtok input, ~$1.20/Mtok output (yaklaşık)
  - Compaction çağrı: 5K input + 0.5K output = $0.005
  - Karşılığında: Claude'a giden context %30-50 daha zengin (50 mesaj özeti)
                + cache write azalır (kısa context = az cache yazımı)

Kalite Güvenceleri:
  - Compaction her zaman OPSIYONEL: hata olursa Claude raw history alır
  - A/B test framework (test_compaction_quality.py) — Claude full vs compacted
    benzerlik oranı ölçer. <%85 → Cerebras prompt tune

Kullanım:
    from context_compactor import compact_history_for_claude

    summary = await compact_history_for_claude(
        history=self.history,
        user_msg=user_input,
        recent_n=20,  # Son N mesajı al
    )
    # summary = "Son 20 mesajda kullanıcı X istiyor. Y bilgisi mevcut. Şu kararlar verildi: ..."

    if summary:
        # Compacted Claude call
        compact_history = [
            {"role": "system", "content": summary},
            {"role": "user", "content": user_msg},
        ]
    else:
        compact_history = self.history  # Fallback raw
"""
from __future__ import annotations
import asyncio
import os
import time
from typing import Optional

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────

COMPACT_ENABLED = os.getenv("FERMAT_COMPACT_ENABLED", "true").lower() == "true"
COMPACT_MIN_MESSAGES = int(os.getenv("FERMAT_COMPACT_MIN_MESSAGES", "10"))
COMPACT_RECENT_N = int(os.getenv("FERMAT_COMPACT_RECENT_N", "20"))
COMPACT_TARGET_TOKENS = int(os.getenv("FERMAT_COMPACT_TARGET_TOKENS", "400"))
COMPACT_CEREBRAS_MODEL = os.getenv("FERMAT_COMPACT_MODEL", "qwen-3-235b-a22b-instruct-2507")


COMPACT_SYSTEM_PROMPT = """Sen FermatAI sisteminin context-compactor modulüsün. Çok uzun konuşma
geçmişini Claude için kısa ve faydalı bir bağlam özetine dönüştürürsün.

Çıkarman gereken bilgiler (300-500 kelime, Türkçe):
1. KULLANICI KIM: ad, rol (admin/öğretmen/öğrenci/veli), bilinen profil notları
2. AKTIF KONULAR: son N mesajdaki ana konular (2-5 madde)
3. VERILEN VERILER/KARARLAR: bot kullanıcıya hangi sayıları/kararları sundu
4. AÇIK SORULAR/BEKLENTİLER: kullanıcının bekleyen istekleri
5. TON & DUYGU: kullanıcının ruh hali (mutlu/stresli/sinirli/vs.)
6. SON 2 MESAJ ÖZETİ (kelime kelime DEĞİL, anlamca)

ÇIKARMA:
- Tek tek tüm mesaj içeriklerini tekrar yazma
- Tool call detay JSON'larını kopyalama
- Render fence'lerini (```chart, ```sim) kopyalama
- Wikipedia auto-injection bloklarını dahil etme

FORMAT:
**KULLANICI:** ...
**AKTIF KONULAR:** ...
**VERILEN VERILER:** ...
**AÇIK SORULAR:** ...
**SON İSTEK:** (en son user mesajı 1 cümle özeti)

Çıktı 300-500 token aralığında olsun. JSON DEĞİL, düz Türkçe metin."""


# ─────────────────────────────────────────────────────────────────────────
# HEURISTICS — compact gerekli mi?
# ─────────────────────────────────────────────────────────────────────────

def should_compact(history: list, user_msg: str = "") -> dict:
    """Compact gerekli mi karar ver. Cache-aware heuristics.

    Returns:
        {
            "should": bool,
            "reason": "...",
            "msg_count": int,
            "estimated_tokens": int,
        }
    """
    if not COMPACT_ENABLED:
        return {"should": False, "reason": "compact_disabled", "msg_count": 0}

    msg_count = len([m for m in (history or []) if m.get("role") in ("user", "assistant")])

    if msg_count < COMPACT_MIN_MESSAGES:
        return {
            "should": False,
            "reason": f"history_short ({msg_count}<{COMPACT_MIN_MESSAGES})",
            "msg_count": msg_count,
        }

    # Estimate token count (rough: 4 chars/token)
    total_chars = sum(len(str(m.get("content", ""))) for m in history)
    est_tokens = total_chars // 4

    # Eşik: 5K+ token'lık history → compact değerli
    if est_tokens < 3000:
        return {
            "should": False,
            "reason": f"low_token_count ({est_tokens})",
            "msg_count": msg_count,
            "estimated_tokens": est_tokens,
        }

    return {
        "should": True,
        "reason": f"long_history_{msg_count}msg_{est_tokens}tok",
        "msg_count": msg_count,
        "estimated_tokens": est_tokens,
    }


# ─────────────────────────────────────────────────────────────────────────
# COMPACT
# ─────────────────────────────────────────────────────────────────────────

async def compact_history_for_claude(
    history: list,
    user_msg: str = "",
    recent_n: int = COMPACT_RECENT_N,
    target_tokens: int = COMPACT_TARGET_TOKENS,
) -> Optional[str]:
    """Cerebras 235B ile history → compact summary.

    Returns:
        str: compacted summary (300-500 token) — Claude'un system prompt'unun
             sonuna eklenir.
        None: compact yapılmadı/yapılamadı (Claude raw history kullansın)
    """
    decision = should_compact(history, user_msg)
    if not decision["should"]:
        logger.debug(f"[COMPACT] skip: {decision['reason']}")
        return None

    try:
        # Son N mesajı al (en yenisi user_msg değil — history'deki son N)
        recent = history[-recent_n:] if len(history) > recent_n else list(history)

        # Mesajları text-only formata çevir (tool_call/result detay çıkar)
        compact_input = _format_history_for_compaction(recent, user_msg)

        # Cerebras call — direkt CerebrasClient.complete_async
        from cerebras_handler import CerebrasClient
        client = CerebrasClient()

        start = time.time()
        # Cerebras 235B en güçlü context anlama — uzun history için tercih
        result = await client.complete_async(
            messages=[{"role": "user", "content": compact_input}],
            system=COMPACT_SYSTEM_PROMPT,
            model=COMPACT_CEREBRAS_MODEL,
            temperature=0.3,
            max_tokens=target_tokens + 100,
        )
        elapsed_ms = int((time.time() - start) * 1000)

        if not result or not (result.get("text") or result.get("content")):
            logger.warning(f"[COMPACT] Cerebras boş cevap: {result}")
            return None

        summary = (result.get("text") or result.get("content") or "").strip()
        logger.info(
            f"[COMPACT] {decision['msg_count']} msg → {len(summary)} char "
            f"({elapsed_ms}ms, ~{decision.get('estimated_tokens', 0)} → {len(summary)//4} tok)"
        )

        return summary
    except ImportError as e:
        logger.warning(f"[COMPACT] LLMRouter import fail: {e}")
        return None
    except Exception as e:
        logger.warning(f"[COMPACT] fail: {type(e).__name__}: {str(e)[:200]}")
        return None


def _format_history_for_compaction(messages: list, user_msg: str = "") -> str:
    """History'yi compact-friendly text formatına dönüştür.

    - Tool call/result JSON'larını ÇIKAR (gereksiz noise)
    - Render fence'leri ÇIKAR
    - Sadece user/assistant text içerikler
    """
    lines = []
    for m in messages:
        role = m.get("role", "")
        content = m.get("content", "")
        if not content or role not in ("user", "assistant"):
            continue
        # Tool call/result skip
        if isinstance(content, str):
            text = content
            if text.startswith("[tool_calls:") or text.startswith("[tool_results:"):
                continue
            # Render fence'leri çıkar (```chart...``` blokları)
            import re
            text = re.sub(r'```(chart|sim|3d|threed|p5|matter|mermaid|graph|map|leaflet|cesium|tikz|asymptote|graphviz|jsxgraph|geogebra|manim|svg|html|widget|heatmap|treemap|sankey|parallel|forcegraph|vegalite|vega|d3)\b[^`]*?```', '[render]', text, flags=re.DOTALL)
            # Wikipedia bloklarını çıkar
            text = re.sub(r'📚 \*Wikipedia[^*]+\*[^*]+\*', '', text)
            text = text.strip()
            if not text:
                continue
            # Çok uzun mesajları kıs
            if len(text) > 800:
                text = text[:800] + "..."
            lines.append(f"{role.upper()}: {text}")
        elif isinstance(content, list):
            # Anthropic content blocks list — sadece text type'ları al
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "").strip()
                    if text:
                        if len(text) > 800:
                            text = text[:800] + "..."
                        lines.append(f"{role.upper()}: {text}")

    history_str = "\n\n".join(lines)
    instruction = (
        f"Aşağıdaki konuşma geçmişini Claude için bağlam özetine dönüştür.\n\n"
        f"=== KONUŞMA GEÇMİŞİ ===\n{history_str}\n=== /KONUŞMA GEÇMİŞİ ===\n\n"
    )
    if user_msg:
        instruction += f"Kullanıcının ŞU AN sorduğu: \"{user_msg[:300]}\"\n\n"
    instruction += "Bu bağlamla Claude doğru cevabı verebilsin. ÖZET ÇIKAR (300-500 token):"
    return instruction


# ─────────────────────────────────────────────────────────────────────────
# DB LOG (compaction istatistikleri)
# ─────────────────────────────────────────────────────────────────────────

INIT_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS compaction_log (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    phone TEXT,
    msg_count INTEGER,
    input_tokens INTEGER,
    output_tokens INTEGER,
    elapsed_ms INTEGER,
    cerebras_model TEXT,
    summary_chars INTEGER,
    skip_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_compaction_created ON compaction_log(created_at DESC);
"""


async def init_compaction_table() -> bool:
    try:
        from db_pool import db_execute
        await db_execute(INIT_TABLE_SQL)
        return True
    except Exception as e:
        logger.warning(f"[COMPACT] init table fail: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    print(f"COMPACT_ENABLED:        {COMPACT_ENABLED}")
    print(f"COMPACT_MIN_MESSAGES:   {COMPACT_MIN_MESSAGES}")
    print(f"COMPACT_RECENT_N:       {COMPACT_RECENT_N}")
    print(f"COMPACT_TARGET_TOKENS:  {COMPACT_TARGET_TOKENS}")
    print(f"COMPACT_CEREBRAS_MODEL: {COMPACT_CEREBRAS_MODEL}")

    if len(sys.argv) > 1 and sys.argv[1] == "init-table":
        from dotenv import load_dotenv
        from pathlib import Path
        env_path = Path(__file__).resolve().parent.parent / ".env"
        if env_path.exists():
            load_dotenv(env_path)
        ok = asyncio.run(init_compaction_table())
        print(f"init_compaction_table: {'OK' if ok else 'FAIL'}")
