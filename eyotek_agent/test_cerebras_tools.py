"""
Cerebras Tool-Calling Smoke Test (25.41 Neo)
=============================================

3 senaryo:
  1. search_curriculum dispatch (RAG arama, kavramsal)
  2. Whitelist DIŞI tool reddi (write_etut → None döner)
  3. No-tool text (saf cevap, tool yok)

Beklenen: 3/3 PASS.
"""
from __future__ import annotations
import asyncio
import sys

sys.path.insert(0, "/opt/fermatai/eyotek_agent")
sys.stdout.reconfigure(encoding="utf-8")


async def _fake_executor(name: str, args: dict) -> str:
    """Fake tool executor — gerçek DB sorgusu yapmaz, sadece düzgün cevap döner."""
    if name == "search_curriculum":
        return "[RAG] Limit konusu: Limit, bir fonksiyonun bir noktaya yaklaşırken aldığı değerdir. Sürekli/süreksiz fonksiyonlar..."
    if name == "list_exam_questions":
        return "[CIKMIS_SORU] Soru 1 (2024 TYT): ..."
    if name == "get_class_plan":
        return "[CLASS_PLAN] Pazartesi: 9:00 Matematik, 10:30 Fizik..."
    if name == "get_daily_etut":
        return "[ETUT] 12 etüt bugün, 4 öğrenci..."
    return f"[FAKE_TOOL] {name} args={args}"


async def test_1_search_curriculum():
    """Cerebras search_curriculum tool çağırmalı."""
    from llm_router import LLMRouter

    router = LLMRouter()
    if not getattr(router, "_cerebras_available", False):
        print("⚠️  T1 SKIP: Cerebras yok")
        return False

    tools = [{
        "name": "search_curriculum",
        "description": "YKS konuları için RAG semantik arama",
        "input_schema": {
            "type": "object",
            "properties": {"konu": {"type": "string"}},
            "required": ["konu"],
        },
    }]
    messages = [
        {"role": "user", "content": "Limit nedir kavramını anlat. Müfredattan bilgi getir."}
    ]
    r = await router.chat_cerebras_with_tools(
        messages=messages,
        system="Türkçe pedagojik koç. Tool'u kullanarak konu açıkla.",
        tools=tools,
        tool_executor=_fake_executor,
    )
    print(f"\n=== T1: search_curriculum ===")
    if r and r.get("text"):
        print(f"✅ PASS — {len(r['text'])} char, model={r.get('model','?')}, ms={r.get('ms','?')}")
        print(f"   Cevap: {r['text'][:200]}...")
        return True
    print(f"❌ FAIL — r={r}")
    return False


async def test_2_whitelist_reject():
    """Whitelist DIŞI tool → None dönmeli (Claude'a fallback)."""
    from llm_router import LLMRouter

    router = LLMRouter()
    if not getattr(router, "_cerebras_available", False):
        print("⚠️  T2 SKIP: Cerebras yok")
        return False

    bad_tools = [{
        "name": "write_etut",  # YAZMA — whitelist DIŞI
        "description": "Etüt yazma",
        "input_schema": {"type": "object", "properties": {}},
    }]
    messages = [{"role": "user", "content": "Etüt yaz"}]
    r = await router.chat_cerebras_with_tools(
        messages=messages,
        system="Asistan",
        tools=bad_tools,
        tool_executor=_fake_executor,
    )
    print(f"\n=== T2: Whitelist reddi ===")
    if r is None:
        print("✅ PASS — None döndü (whitelist disi tool reddedildi)")
        return True
    print(f"❌ FAIL — r={r} (whitelist çalışmadı!)")
    return False


async def test_3_no_tool_text():
    """Tool gerekli olmayan basit konuşma — direkt text dönmeli."""
    from llm_router import LLMRouter

    router = LLMRouter()
    if not getattr(router, "_cerebras_available", False):
        print("⚠️  T3 SKIP: Cerebras yok")
        return False

    tools = [{
        "name": "search_curriculum",
        "description": "YKS müfredat arama",
        "input_schema": {"type": "object", "properties": {}},
    }]
    messages = [{"role": "user", "content": "Merhaba, sana selam"}]
    r = await router.chat_cerebras_with_tools(
        messages=messages,
        system="Türkçe asistan. Selama selamla cevap ver.",
        tools=tools,
        tool_executor=_fake_executor,
    )
    print(f"\n=== T3: No-tool text ===")
    if r and r.get("text") and not r.get("has_tool_calls", False):
        print(f"✅ PASS — direkt text, {len(r['text'])} char")
        print(f"   Cevap: {r['text'][:120]}...")
        return True
    print(f"❌ FAIL — r={r}")
    return False


async def main():
    print("🧪 Cerebras Tool-Calling Smoke Test\n")

    results = []
    for test_fn in (test_1_search_curriculum, test_2_whitelist_reject, test_3_no_tool_text):
        try:
            r = await test_fn()
            results.append(r)
        except Exception as e:
            print(f"\n❌ EXCEPTION: {e}")
            import traceback; traceback.print_exc()
            results.append(False)

    print("\n" + "=" * 50)
    passed = sum(1 for r in results if r)
    print(f"📊 Sonuç: {passed}/{len(results)} PASS")
    if passed == len(results):
        print("✅ Cerebras tool-calling AKTIF KULLANIMA HAZIR")
    else:
        print("⚠️ Bazı testler başarısız — flag aktif etmeden önce düzelt")


if __name__ == "__main__":
    asyncio.run(main())
