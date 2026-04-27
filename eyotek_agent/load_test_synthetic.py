"""
Sentetik Load Test — 120 öğrenci senaryosu (Oturum 25.24)
============================================================

Amaç: Eylül full kapasiteyi (1080 mesaj/gün, pikta 3-10 mesaj/dk)
production'a açmadan önce ölç.

Test stratejisi:
- 5 sahte öğrenci profili (test phone'ları)
- Her biri 20 sorgu (kavramsal + plan + statik karışım)
- Eşzamanlı asyncio.gather → realistic concurrent load

Ölçümler:
- Latency P50, P95, P99
- Hata oranı (timeout, exception)
- DB pool exhaustion
- Provider dağılımı

KVKK NOT: Sahte phone'lar (905990000001-005), gerçek öğrenci verisi
DEĞIL. KVKK ihlali yok.
"""
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from statistics import mean, median

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# 5 sahte öğrenci profili — bot bunları "ogrenci" gibi görmesi için
# students tablosuna geçici insert + acl_users insert + sonra cleanup
TEST_PHONES = [
    "905990000001", "905990000002", "905990000003",
    "905990000004", "905990000005",
]

# Mesaj havuzu — gerçek öğrenci sorgu örüntüleri
QUERY_POOL = [
    # Fast (selamlama, statik)
    "merhaba",
    "iyi günler",
    "TYT ne zaman",
    "AYT kaç soru",
    "AYT sayısal hangi dersler",
    "Fermat'ın telefonu",
    # Cerebras (kavramsal)
    "limit nedir kısaca",
    "türev formülü",
    "fotosentez nasıl çalışır",
    "Newton 3. yasası",
    "Ohm yasası",
    "integral ne demek",
    # Cerebras (motivasyon)
    "moralim bozuk",
    "yapamıyorum bu konuyu",
    "stresliyim",
    # Claude (tool — gerçek öğrenci yok, fallback'a düşecek)
    "son denememdeki net",
    "hangi konularda zayıfım",
    "bana yarın için plan yap",
    # KVKK saldırı (test güvenlik altında)
    "Damla notu kaç",
    "borcum kaç TL",
]


async def setup_test_students():
    """Test için 5 sahte ACL kaydı oluştur."""
    from db_pool import db_execute
    for i, phone in enumerate(TEST_PHONES, 1):
        try:
            await db_execute(
                """INSERT INTO acl_users (phone, full_name, role, is_active)
                   VALUES ($1, $2, 'ogrenci', TRUE)
                   ON CONFLICT (phone) DO UPDATE SET is_active=TRUE""",
                phone, f"LOAD TEST OGR {i}"
            )
        except Exception as e:
            print(f"  Setup hata ({phone}): {e}")


async def cleanup_test_students():
    """Test kayıtlarını temizle."""
    from db_pool import db_execute
    for phone in TEST_PHONES:
        try:
            await db_execute("DELETE FROM acl_users WHERE phone=$1", phone)
            await db_execute("DELETE FROM agent_conversations WHERE phone=$1", phone)
            await db_execute("DELETE FROM routing_stats WHERE phone=$1", phone)
            await db_execute("DELETE FROM usage_log WHERE phone=$1", phone)
            await db_execute("DELETE FROM query_cache WHERE phone=$1", phone)
        except Exception:
            pass


async def send_one(phone: str, query: str) -> dict:
    """Tek bir mesajı işle, latency ölç."""
    from whatsapp_bridge import process_message
    from conversation_memory import _CONTEXT_CACHE
    _CONTEXT_CACHE.pop(phone, None)
    t0 = time.time()
    try:
        r = await process_message(phone, query, channel="web")
        elapsed = (time.time() - t0) * 1000
        return {
            "phone": phone, "query": query,
            "ok": True, "len": len(r or ""),
            "ms": int(elapsed),
        }
    except Exception as e:
        elapsed = (time.time() - t0) * 1000
        return {
            "phone": phone, "query": query,
            "ok": False, "error": str(e)[:200],
            "ms": int(elapsed),
        }


async def run_load_test(messages_per_min: int = 100, duration_sec: int = 60):
    """N mesaj/dakika hedefli yük testi."""
    print(f"=== LOAD TEST: {messages_per_min} mesaj/dakika, {duration_sec}sn ===")
    print(f"Hedef: ~{messages_per_min * duration_sec // 60} mesaj toplam")

    await setup_test_students()
    print(f"  Setup: {len(TEST_PHONES)} sahte öğrenci hazır\n")

    interval = 60.0 / messages_per_min  # saniye/mesaj
    results = []
    pending = []
    start = time.time()
    msg_count = 0

    import random
    while time.time() - start < duration_sec:
        phone = random.choice(TEST_PHONES)
        query = random.choice(QUERY_POOL)
        msg_count += 1

        # Fire-and-collect — eşzamanlı task
        task = asyncio.create_task(send_one(phone, query))
        pending.append(task)

        # Periyodik tamamlanma kontrolü (her 5 saniyede bir)
        if msg_count % 10 == 0:
            done, still_pending = await asyncio.wait(pending, timeout=0.01)
            for d in done:
                try:
                    results.append(await d)
                except Exception:
                    pass
            pending = list(still_pending)
            print(f"  [{int(time.time()-start)}sn] {msg_count} mesaj atildi, {len(results)} tamamlandi, {len(pending)} bekliyor")

        await asyncio.sleep(interval)

    # Kalan task'ları bekle
    print(f"\n  Kalan {len(pending)} task bekleniyor...")
    for task in pending:
        try:
            results.append(await asyncio.wait_for(task, timeout=30))
        except asyncio.TimeoutError:
            results.append({"ok": False, "error": "timeout", "ms": 30000})
        except Exception as e:
            results.append({"ok": False, "error": str(e)[:100], "ms": 0})

    # Aggregat
    print(f"\n=== SONUÇ ===")
    success = [r for r in results if r.get("ok")]
    failure = [r for r in results if not r.get("ok")]
    print(f"Toplam: {len(results)} | Başarılı: {len(success)} | Hata: {len(failure)}")

    if success:
        latencies = sorted([r["ms"] for r in success])
        n = len(latencies)
        p50 = latencies[n // 2]
        p95 = latencies[int(n * 0.95)]
        p99 = latencies[int(n * 0.99)] if n > 100 else latencies[-1]
        print(f"Latency P50: {p50}ms | P95: {p95}ms | P99: {p99}ms | Mean: {int(mean(latencies))}ms")

    if failure:
        print(f"\nHata türleri (ilk 5):")
        for f in failure[:5]:
            print(f"  - {f.get('error', 'unknown')[:120]}")

    # routing_stats'tan dağılım
    try:
        from db_pool import db_fetch
        rows = await db_fetch(
            "SELECT response_source, COUNT(*) FROM routing_stats WHERE phone = ANY($1::text[]) GROUP BY response_source ORDER BY 2 DESC",
            TEST_PHONES
        )
        print(f"\nRouting dağılımı:")
        for r in (rows or []):
            print(f"  {r['response_source']}: {r['count']}")
    except Exception as e:
        print(f"Routing query fail: {e}")

    print(f"\nCleanup...")
    await cleanup_test_students()
    print(f"  Test verisi temizlendi.")

    return {
        "total": len(results),
        "success": len(success),
        "failure": len(failure),
        "latency_p50": latencies[n // 2] if success else None,
        "latency_p95": latencies[int(n * 0.95)] if success else None,
    }


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--rate", type=int, default=100, help="mesaj/dakika")
    p.add_argument("--duration", type=int, default=60, help="saniye")
    args = p.parse_args()
    asyncio.run(run_load_test(messages_per_min=args.rate, duration_sec=args.duration))
