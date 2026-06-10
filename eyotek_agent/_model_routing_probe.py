"""Anthropic /v1/models erişim doğrulama + 7 günlük routing/maliyet analizi."""
import asyncio
import os
import sys
sys.path.insert(0, "/opt/fermatai/eyotek_agent")
from dotenv import load_dotenv
load_dotenv("/opt/fermatai/.env", override=True)
import httpx


async def main():
    # 1) Hesabın GERÇEKTEN erişebildiği Claude modelleri
    print("=" * 66)
    print("1) ANTHROPIC /v1/models (hesabın erişimi — kanıt)")
    key = os.getenv("ANTHROPIC_API_KEY", "")
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get("https://api.anthropic.com/v1/models?limit=50",
                        headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
        if r.status_code == 200:
            ids = [m["id"] for m in r.json().get("data", [])]
            for i in sorted(ids):
                tag = ""
                if "fable" in i: tag = "  ← EN YENİ"
                if i == "claude-sonnet-4-20250514": tag = "  ← EOL 15 Haz (5 gün!)"
                print(f"   {i}{tag}")
        else:
            print(f"   HTTP {r.status_code}: {r.text[:120]}")

    # 2) 7 günlük routing dağılımı + token maliyeti
    print("\n" + "=" * 66)
    print("2) ROUTING (7 gün) + TOKEN/MALİYET (usage_log)")
    from db_pool import db_fetch
    rows = await db_fetch("""SELECT response_source, COUNT(*) n, ROUND(AVG(response_ms)) ms,
                                    SUM(COALESCE(token_input,0)) tin, SUM(COALESCE(token_output,0)) tout,
                                    SUM(COALESCE(cache_read_tokens,0)) cread
                             FROM usage_log WHERE created_at > NOW() - INTERVAL '7 days'
                             GROUP BY response_source ORDER BY n DESC""")
    # Sonnet 4.6 fiyat: $3/M in, $15/M out, cache read $0.30/M (yaklaşık)
    top = 0
    for r2 in rows:
        cost = (r2['tin'] or 0)/1e6*3 + (r2['tout'] or 0)/1e6*15 + (r2['cread'] or 0)/1e6*0.30
        if 'claude' in str(r2['response_source']): top += cost
        print(f"   {str(r2['response_source']):26} {r2['n']:5} msg | {r2['ms']}ms | in={r2['tin']} out={r2['tout']} cache_r={r2['cread']} | ~${cost:.2f}")
    print(f"   → Claude 7-gün tahmini maliyet: ~${top:.2f}  (ay: ~${top*4.3:.2f})")

    # 3) Claude'a giden mesajların intent kırılımı (premium adayları)
    print("\n" + "=" * 66)
    print("3) CLAUDE'A GİDEN İŞLERİN KIRILIMI (routing_stats.handler/intent, 7g)")
    try:
        rows3 = await db_fetch("""SELECT COALESCE(handler_name,'(yok)') h, COUNT(*) n
                                  FROM routing_stats WHERE created_at > NOW() - INTERVAL '7 days'
                                    AND response_source ILIKE '%claude%'
                                  GROUP BY 1 ORDER BY n DESC LIMIT 12""")
        for r3 in rows3:
            print(f"   {r3['h']:34} {r3['n']}")
    except Exception as e:
        print(f"   ({str(e)[:80]})")


if __name__ == "__main__":
    asyncio.run(main())
