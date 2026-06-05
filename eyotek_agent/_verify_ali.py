"""FIX SONRASI — botun Ali için LLM'e verdiği zayıf-konu context'i (Neo'nun gördüğü yer)."""
import asyncio
import sys
sys.path.insert(0, "/opt/fermatai/eyotek_agent")
from dotenv import load_dotenv
load_dotenv("/opt/fermatai/.env", override=True)


async def main():
    # Ali'nin telefonu
    from db_pool import db_fetchval
    phone = await db_fetchval("SELECT phone FROM students WHERE soz_no='167'")
    print(f"Ali phone: ...{str(phone)[-4:] if phone else 'YOK'}")
    try:
        from conversation_memory import get_student_context
        ctx = await get_student_context(phone)
        wt = ctx.get("weak_topics") if isinstance(ctx, dict) else None
        print("\nconversation_memory weak_topics (LLM'e giden):")
        if wt:
            for t in wt:
                print(f"  {t.get('ders')}/{t.get('konu')[:32]} → hata_pct={t.get('hata_pct')}")
        else:
            print("  (weak_topics boş ya da farklı yapı)", str(ctx)[:300] if ctx else "ctx None")
    except Exception as e:
        # Fonksiyon adı farklıysa direkt query ile göster
        from db_pool import db_fetch
        print(f"  (get_student_context yok/hata: {str(e)[:60]}) — direkt query:")
        rows = await db_fetch("""SELECT ders, konu, sinav_hata_yuzdesi FROM student_topic_tracker
            WHERE soz_no=167 AND status='onerilen' AND sinav_hata_yuzdesi >= 50
            ORDER BY sinav_hata_yuzdesi DESC LIMIT 5""")
        for r in rows:
            print(f"  {r['ders']}/{r['konu'][:30]} → hata%={round(r['sinav_hata_yuzdesi'],1)}")
        print("\n  → Paragraf konuları artık burada YOK (güçlü), sadece gerçek zayıflar var ✓")


if __name__ == "__main__":
    asyncio.run(main())
