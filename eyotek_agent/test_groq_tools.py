"""
Oturum 25: Groq tool-calling smoke test (standalone).

`llm_router.chat_groq_with_tools` dogru calisiyor mu?
Tool dispatch + 2 round + fallback senaryolari.

Kullanim:
    python test_groq_tools.py

Not: Production'a tiklanmaz; sadece ogretici/dogrulama amaçli.
Wire-in fermat_core_agent.py'a daha sonra kontrollu yapilacak.
"""
from __future__ import annotations
import asyncio
import json
import sys

from dotenv import load_dotenv
load_dotenv(override=True)

from llm_router import LLMRouter, SAFE_GROQ_TOOLS


# ── Mock tool_executor ──────────────────────────────────────────
async def mock_executor(tool_name: str, args: dict) -> str:
    """Test icin sahte tool dispatcher. Gercek kodda `_dispatch_tool` yerine gecer."""
    if tool_name == "search_curriculum":
        q = args.get("query", "")
        return json.dumps({
            "ok": True,
            "query": q,
            "results": [
                {
                    "ders": "Fizik",
                    "konu": "Kaldirma Kuvveti",
                    "icerik_ozet": (
                        "Kaldirma kuvveti, bir sivi icine daldirilan cismin "
                        "yukari dogru itilmesidir. F = d × V × g formuluyle "
                        "hesaplanir (d: siviyogunlugu, V: hacim, g: 9.8 m/s²)."
                    ),
                    "skor": 0.87,
                }
            ],
        }, ensure_ascii=False)
    if tool_name == "get_daily_etut":
        return json.dumps({"ok": True, "etut_sayisi": 12, "tarih": "2026-04-24"})
    return json.dumps({"ok": False, "error": f"Unknown tool: {tool_name}"})


# ── Test tool schemas (Claude format) ──────────────────────────
TEST_TOOLS = [
    {
        "name": "search_curriculum",
        "description": "Mufredat bilgi bankasinda semantik arama.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Arama sorgusu"},
                "ders": {"type": "string", "description": "Filtre: ders adi (opsiyonel)"},
            },
            "required": ["query"],
        },
    },
]

UNSAFE_TOOLS = [
    {
        "name": "write_etut",
        "description": "Eyotek'te etut yaz.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


async def test_safe_tool_flow():
    """Pozitif senaryo: Groq search_curriculum cagiriyor, cevap donuyor."""
    print("\n[TEST 1] search_curriculum ile kavramsal soru")
    router = LLMRouter()
    if not router._groq_available:
        print("  SKIP — GROQ_API_KEY yok")
        return False

    result = await router.chat_groq_with_tools(
        messages=[{"role": "user", "content": "Kaldirma kuvveti nedir?"}],
        system="Sen YKS fizik asistanisin. Kavramsal sorularda mufredat tool'unu kullanmayi tercih et.",
        tools=TEST_TOOLS,
        tool_executor=mock_executor,
    )
    if result is None:
        print("  FAIL — None dondu (fallback isareti)")
        return False
    text = result.get("text", "")
    if len(text) < 20:
        print(f"  FAIL — cevap cok kisa: {text[:80]}")
        return False
    print(f"  OK — cevap ({len(text)} char): {text[:120]}...")
    return True


async def test_unsafe_tool_rejected():
    """Negatif senaryo: whitelist disi tool verildiginde None donmelidir."""
    print("\n[TEST 2] Whitelist disi tool (write_etut) -> fallback isareti")
    router = LLMRouter()
    if not router._groq_available:
        print("  SKIP — GROQ_API_KEY yok")
        return False

    result = await router.chat_groq_with_tools(
        messages=[{"role": "user", "content": "test"}],
        system="test",
        tools=UNSAFE_TOOLS,
        tool_executor=mock_executor,
    )
    if result is not None:
        print(f"  FAIL — None bekleniyordu, dondu: {result}")
        return False
    print("  OK — whitelist korumasi calisiyor")
    return True


async def test_no_tools_needed():
    """Groq tool cagirmayinca direkt text dondugunu test et."""
    print("\n[TEST 3] Basit soru (tool gerek yok) -> metin donmeli")
    router = LLMRouter()
    if not router._groq_available:
        print("  SKIP — GROQ_API_KEY yok")
        return False

    result = await router.chat_groq_with_tools(
        messages=[{"role": "user", "content": "Merhaba, nasilsin?"}],
        system="Kisa Turkce cevap ver. Tool kullanma, direkt cevapla.",
        tools=TEST_TOOLS,
        tool_executor=mock_executor,
    )
    if result is None:
        print("  FAIL — None dondu")
        return False
    text = result.get("text", "")
    print(f"  OK — text ({len(text)} char): {text[:100]}")
    return True


async def main():
    print(f"SAFE_GROQ_TOOLS allowlist: {sorted(SAFE_GROQ_TOOLS)}")
    tests = [
        await test_safe_tool_flow(),
        await test_unsafe_tool_rejected(),
        await test_no_tools_needed(),
    ]
    passed = sum(1 for t in tests if t)
    print(f"\n=== SONUC: {passed}/{len(tests)} test gecti ===")
    sys.exit(0 if passed == len(tests) else 1)


if __name__ == "__main__":
    asyncio.run(main())
