"""
Pattern Loop Guard — Classroom Management Alt Modülü (22 Nisan Neo)
====================================================================
Enes vakası (22 Nisan 23:06-23:08): "AYT zayıf konular", "AYT ortalamam bu
olmamalı", "Sadece ayt fizik net analizlerim", "Ayt fizik net analizlerim
nasıl" — 4 farklı mesaj, bot 4 kez AYNI "AYT Birlestir Analizi" verdi.

Problem: fast_response pattern istikrarla yakalıyor ama user intent farklı.
Kullanıcı bezdiği için sistemi kötü algılayacak.

Çözüm: Son 2 bot yanıtı ve son 2 user mesajı karşılaştır:
  - Aynı handler tetiklendiyse (2x aynı tools_used)
  - VE user mesajları farklıysa
  → Claude'a eskale et (fast response PATHWAY'DEN CIKAR)

Bu kişisel veri sorularında kritik — bot statik handler'a sıkışmamalı.
"""
from __future__ import annotations
from loguru import logger


async def detect_pattern_loop(phone: str, new_handler: str = "") -> dict:
    """Son 2 bot cevabı aynı handler'a mı düştü? İntent loop mu?

    Args:
        phone: öğrenci telefonu
        new_handler: şimdi tetiklenecek handler adı (ör. "ogrenci_ayt_deneme")

    Returns:
        dict:
          is_loop: bool
          loop_count: int (kaç kez aynı handler çalıştı)
          last_handler: str
          advice: str (Claude prompt'a not)
          should_escalate: bool (True → fast response'u skip, Claude'a ver)
    """
    try:
        from db_pool import db_fetch
        rows = await db_fetch(
            """
            SELECT message_role, content, tools_used, created_at
            FROM fermat.agent_conversations
            WHERE phone = $1
              AND message_role = 'assistant'
              AND COALESCE(session_id,'') NOT LIKE '_test_%'
              AND created_at > NOW() - INTERVAL '10 minutes'
            ORDER BY created_at DESC
            LIMIT 3
            """,
            phone,
        )
    except Exception as e:
        logger.debug(f"pattern_loop detect hatasi: {e}")
        return {"is_loop": False, "should_escalate": False, "advice": ""}

    if not rows or len(rows) < 2:
        return {"is_loop": False, "loop_count": 0, "should_escalate": False, "advice": ""}

    # Son 2-3 bot cevabının tools_used'u
    last_tools = []
    last_contents = []
    for r in rows:
        tools = r.get("tools_used") or []
        # asyncpg list olarak dönebiliyor veya str
        if isinstance(tools, str):
            import json
            try:
                tools = json.loads(tools)
            except Exception:
                tools = [tools] if tools else []
        last_tools.append(tuple(sorted(tools)) if tools else ())
        last_contents.append((r.get("content") or "")[:150])

    # Aynı handler 2+ kez ardışık → loop
    loop_count = 1
    for i in range(1, len(last_tools)):
        if last_tools[i] == last_tools[0] and last_tools[0]:
            loop_count += 1
        else:
            break

    is_loop = loop_count >= 2
    should_escalate = loop_count >= 2

    # İçerik benzerliği — ilk 80 char aynıysa kesin loop
    content_match = False
    if len(last_contents) >= 2:
        content_match = last_contents[0][:80] == last_contents[1][:80]

    if content_match and loop_count >= 2:
        should_escalate = True

    advice = ""
    if should_escalate:
        advice = (
            f"⚠ PATTERN_LOOP: Son {loop_count} bot cevabı AYNI handler. "
            f"Öğrenci muhtemelen farklı detay istiyor. "
            f"Fast response'u SKIP et, Claude devreye girsin. "
            f"Özellikle 'sadece X istiyorum', 'X olmamalı', 'eksik olan X' gibi "
            f"itiraz/düzeltme ifadeleri varsa Claude intent'i anlayıp spesifik cevap versin."
        )

    return {
        "is_loop": is_loop,
        "loop_count": loop_count,
        "last_handler": last_tools[0][0] if last_tools[0] else "",
        "should_escalate": should_escalate,
        "content_match": content_match,
        "advice": advice,
    }


if __name__ == "__main__":
    import asyncio, sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    async def test():
        # Enes'in vakası — 905370460675
        r = await detect_pattern_loop("905370460675")
        print(f"Enes loop detect: {r}")

    asyncio.run(test())
