"""
Halusinasyon Retrospektif A/B Analizi (Oturum 22.1e, Talimat #14)
==================================================================

quality_log tablosunda biriken gercek trafik verisi uzerinden
halusinasyon + kalite sorunlarini kategorize et.

Cikti: Rapor + en kotu 20 cevap + routing kaynak dagilimi + oneriler.

Kullanim:
    python tests/test_hallucination_retrospective.py
    python tests/test_hallucination_retrospective.py --days 30
    python tests/test_hallucination_retrospective.py --grade D  # sadece D grade
"""
import sys, io, os, asyncio, argparse
from datetime import datetime
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(override=True)


async def analyze(days: int = 7, grade_filter: str = ""):
    import asyncpg
    conn = await asyncpg.connect(os.getenv("DATABASE_URL"))
    try:
        # Temel istatistik
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM quality_log WHERE created_at > NOW() - INTERVAL '{days} days'"
        )
        print("=" * 70)
        print(f"HALUSINASYON RETROSPEKTIF ANALIZ — Son {days} gun")
        print(f"Toplam kayit: {total}")
        print("=" * 70)

        if total == 0:
            print("Veri yok, test edilemez")
            return

        # Grade dagilimi
        grades = await conn.fetch(f"""
            SELECT grade, COUNT(*) AS sayi
            FROM quality_log
            WHERE created_at > NOW() - INTERVAL '{days} days'
            GROUP BY grade ORDER BY grade
        """)
        print("\n📊 GRADE DAGILIMI:")
        for g in grades:
            pct = (g["sayi"] / total) * 100
            bar = "█" * int(pct / 2)
            print(f"  {g['grade'] or '?':4s}: {g['sayi']:>5} ({pct:5.1f}%) {bar}")

        # Routing source dagilimi
        sources = await conn.fetch(f"""
            SELECT response_source, COUNT(*) AS sayi,
                   AVG(halusinasyon_skor) AS avg_hal,
                   AVG(kalite_skor) AS avg_kal
            FROM quality_log
            WHERE created_at > NOW() - INTERVAL '{days} days'
            GROUP BY response_source ORDER BY sayi DESC
        """)
        print("\n📡 ROUTING KAYNAK DAGILIMI:")
        for s in sources:
            name = s["response_source"] or "unknown"
            print(f"  {name:20s}: {s['sayi']:>5} msg | avg hal={float(s['avg_hal'] or 0):.2f} | avg kal={float(s['avg_kal'] or 0):.2f}")

        # Rol dagilimi — kim en cok halusine veriyor?
        roles = await conn.fetch(f"""
            SELECT role, COUNT(*) AS sayi,
                   AVG(halusinasyon_skor) AS avg_hal
            FROM quality_log
            WHERE created_at > NOW() - INTERVAL '{days} days'
            GROUP BY role ORDER BY avg_hal DESC
        """)
        print("\n👥 ROL BAZLI HALUSINASYON SKORU (yuksek = kotu):")
        for r in roles:
            name = r["role"] or "unknown"
            print(f"  {name:15s}: {r['sayi']:>4} msg | avg hal={float(r['avg_hal'] or 0):.2f}")

        # Halusinasyon skoru yuksek olanlar (>0.5)
        halus_count = await conn.fetchval(f"""
            SELECT COUNT(*) FROM quality_log
            WHERE created_at > NOW() - INTERVAL '{days} days'
              AND halusinasyon_skor >= 0.5
        """)
        print(f"\n🚨 HALUSINASYON ŞUPHESİ (skor >= 0.5): {halus_count}/{total} ({(halus_count/total)*100:.1f}%)")

        if halus_count > 0:
            top_hal = await conn.fetch(f"""
                SELECT role, response_source, user_message, bot_response, halusinasyon_skor, grade, sorunlar
                FROM quality_log
                WHERE created_at > NOW() - INTERVAL '{days} days'
                  AND halusinasyon_skor >= 0.5
                ORDER BY halusinasyon_skor DESC
                LIMIT 10
            """)
            print("\n🔍 EN YUKSEK HALUSINASYON SKORU 10:")
            for i, r in enumerate(top_hal, 1):
                print(f"\n{i}. [{r['role']}/{r['response_source']}] skor={float(r['halusinasyon_skor']):.2f} grade={r['grade']}")
                print(f"   U: {(r['user_message'] or '')[:80]}")
                print(f"   B: {(r['bot_response'] or '')[:120]}")
                if r["sorunlar"]:
                    print(f"   ⚠ {r['sorunlar']}")

        # D grade cevaplar (sistem bunları "kötü" olarak işaretledi)
        where_grade = ""
        if grade_filter:
            where_grade = f"AND grade = '{grade_filter}'"

        d_grade_count = await conn.fetchval(f"""
            SELECT COUNT(*) FROM quality_log
            WHERE created_at > NOW() - INTERVAL '{days} days' AND grade = 'D'
        """)
        print(f"\n\n📉 D GRADE (sistem kalite: 'kötü'): {d_grade_count}")

        if d_grade_count > 0:
            d_sample = await conn.fetch(f"""
                SELECT role, response_source, user_message, bot_response,
                       halusinasyon_skor, kalite_skor, sorunlar
                FROM quality_log
                WHERE created_at > NOW() - INTERVAL '{days} days'
                  AND grade = 'D' {where_grade}
                ORDER BY created_at DESC
                LIMIT 5
            """)
            print("\nSon 5 D-grade ornegi:")
            for i, r in enumerate(d_sample, 1):
                print(f"\n{i}. [{r['role']}/{r['response_source']}] hal={float(r['halusinasyon_skor'] or 0):.2f} kal={float(r['kalite_skor'] or 0):.2f}")
                print(f"   U: {(r['user_message'] or '')[:80]}")
                print(f"   B: {(r['bot_response'] or '')[:150]}")

        # Kullanici feedback'leri
        fb_total = await conn.fetchval(f"""
            SELECT COUNT(*) FROM user_feedback
            WHERE created_at > NOW() - INTERVAL '{days} days'
        """)
        print(f"\n\n📝 KULLANICI FEEDBACK: {fb_total} kayit")

        if fb_total > 0:
            fb_cats = await conn.fetch(f"""
                SELECT category, COUNT(*) AS sayi
                FROM user_feedback
                WHERE created_at > NOW() - INTERVAL '{days} days'
                GROUP BY category ORDER BY sayi DESC
            """)
            for c in fb_cats:
                print(f"  {c['category'] or 'genel':20s}: {c['sayi']}")

        # Ozet + oneriler
        print("\n\n" + "=" * 70)
        print("💡 ÖNERİLER")
        print("=" * 70)

        if halus_count / total > 0.05:
            print("⚠ Halusinasyon orani >%5 — Ollama routing daha strict yapilmali")
        else:
            print("✅ Halusinasyon orani kabul edilebilir (<%5)")

        if d_grade_count / total > 0.10:
            print("⚠ D-grade >%10 — fast_response/prompt iyilestirme gerekli")
        else:
            print("✅ D-grade orani makul")

        ollama_avg_hal = next((float(s["avg_hal"] or 0) for s in sources if s["response_source"] == "ollama"), 0)
        claude_avg_hal = next((float(s["avg_hal"] or 0) for s in sources if s["response_source"] == "claude"), 0)
        if ollama_avg_hal > claude_avg_hal * 1.5:
            print(f"⚠ Ollama halusinasyonu ({ollama_avg_hal:.2f}) Claude'dan ({claude_avg_hal:.2f}) 1.5x daha yuksek")
        else:
            print(f"✅ Ollama-Claude halusinasyon fark makul ({ollama_avg_hal:.2f} vs {claude_avg_hal:.2f})")

    finally:
        await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--grade", type=str, default="")
    args = parser.parse_args()
    asyncio.run(analyze(args.days, args.grade))
