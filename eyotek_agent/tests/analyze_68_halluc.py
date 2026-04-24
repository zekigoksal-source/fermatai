"""
68 yuksek halusinasyon vakasini kategorize et.

Amac: Claude hal>=0.5 olanlari DB'den cek, user_message + bot_response +
sorunlar alanlarini analiz et, kategoriye ayir:

Kategoriler (on tanimli, eslesmezse 'diger'):
  - sayi_uydurma    : rakam halusinasyonu (net, puan, siralama)
  - isim_uydurma    : yanlis ogretmen/ogrenci ismi
  - tarih_karisma   : gecen/gelecek tarih hatasi
  - konu_uydurma    : olmayan konu/ders
  - tool_yorum      : tool output yanlis yorumlama
  - teknik_detay    : fazla teknik bilgi sizinti
  - context_kayip   : onceki mesaji unutma
  - meta_bilgi      : "ben bir AI'yim" tarzi meta leak
  - genel_hata      : diger

Cikti: Rapor + fix onerileri.
"""
import sys, io, os, asyncio, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(override=True)


# Kategori pattern'lari — bot_response icinde bu pattern'lar varsa o kategori
CATEGORIES = {
    "sayi_uydurma": [
        r"\b\d+\s*net\b", r"\byaklasik\s+\d+", r"\bortalama\s+\d+",
        r"\bsiralama\w*\s+\d+", r"\b\d+\s*puan\b",
    ],
    "isim_uydurma": [
        r"\bhocam?\s+[A-Z][a-zçğıöşü]+\s+[A-Z][a-zçğıöşü]+\b",  # "Hocam Mehmet Yilmaz"
    ],
    "tarih_karisma": [
        r"\b(gecen\s+hafta|gelecek\s+ay|dun|yarin)\b",
        r"\b(bu\s+hafta|bu\s+ay)\b.*\b\d{1,2}\b",
    ],
    "meta_leak": [
        r"\bben\s+bir\s+AI\b", r"\bdil\s+modeli\b", r"\b(claude|ollama|gpt|llm)\b",
        r"\bsistem\s+prompt\b", r"\btool\s+call\b", r"\bpromptta\b",
    ],
    "teknik_sizinti": [
        r"\b(agent_conversations|usage_log|student_exams|student_topic_tracker)\b",
        r"\bSELECT\s+\w+\s+FROM\b", r"\bquery_analytics\b", r"\bdb_fetch\b",
        r"\bDATABASE_URL\b", r"\bpostgres\b",
    ],
    "uzun_cevap": [
        # 500+ karakter cevap (pedagojik olmayan)
    ],
}


def categorize(user_msg: str, bot_resp: str, sorunlar: list) -> list:
    """Bir vakayi kategorize et (birden fazla kategori olabilir)."""
    cats = []
    bot_lower = (bot_resp or "").lower()
    user_lower = (user_msg or "").lower()

    for cat, patterns in CATEGORIES.items():
        if cat == "uzun_cevap":
            if len(bot_resp or "") > 1500:
                cats.append(cat)
            continue
        for p in patterns:
            if re.search(p, bot_lower, re.IGNORECASE):
                cats.append(cat)
                break

    # Sorunlar kolonundan ek kategori
    if sorunlar:
        for s in sorunlar:
            s_low = str(s).lower()
            if "halüs" in s_low or "halus" in s_low:
                cats.append("self_observer_halus")
            if "sayı" in s_low or "sayi" in s_low or "rakam" in s_low:
                cats.append("sayi_sorunu")

    if not cats:
        cats.append("diger")

    return cats


async def main():
    import asyncpg
    conn = await asyncpg.connect(os.getenv("DATABASE_URL"))
    try:
        rows = await conn.fetch("""
            SELECT id, role, response_source, user_message, bot_response,
                   halusinasyon_skor, kalite_skor, grade, sorunlar, created_at
            FROM quality_log
            WHERE halusinasyon_skor >= 0.5
              AND created_at > NOW() - INTERVAL '7 days'
            ORDER BY halusinasyon_skor DESC, created_at DESC
        """)

        print("=" * 70)
        print(f"68 VAKA ANALIZI — Son 7 gun, hal>=0.5")
        print(f"Gercek sayi: {len(rows)}")
        print("=" * 70)

        # Kategori sayilari
        cat_counts = {}
        cat_samples = {}
        role_cat = {}  # {role: {cat: count}}
        source_cat = {}

        for r in rows:
            cats = categorize(r["user_message"], r["bot_response"], r["sorunlar"] or [])
            for c in cats:
                cat_counts[c] = cat_counts.get(c, 0) + 1
                if c not in cat_samples:
                    cat_samples[c] = r
                role_cat.setdefault(r["role"], {}).setdefault(c, 0)
                role_cat[r["role"]][c] += 1
                source_cat.setdefault(r["response_source"], {}).setdefault(c, 0)
                source_cat[r["response_source"]][c] += 1

        print("\n📊 KATEGORI DAGILIMI:")
        for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
            pct = (count / len(rows)) * 100
            bar = "█" * int(pct / 2)
            print(f"  {cat:25s}: {count:>3} ({pct:5.1f}%) {bar}")

        print("\n👥 ROL BAZLI KATEGORI (top 3/role):")
        for role, cats in role_cat.items():
            top = sorted(cats.items(), key=lambda x: -x[1])[:3]
            print(f"  {role:15s}: {', '.join(f'{c}({n})' for c, n in top)}")

        print("\n📡 SOURCE BAZLI KATEGORI (top 3/source):")
        for src, cats in source_cat.items():
            top = sorted(cats.items(), key=lambda x: -x[1])[:3]
            print(f"  {src:15s}: {', '.join(f'{c}({n})' for c, n in top)}")

        # Her kategoriden 1 ornek
        print("\n\n🔍 KATEGORI BASI 1 ORNEK:")
        for cat, sample in sorted(cat_samples.items(), key=lambda x: -cat_counts[x[0]]):
            print(f"\n--- {cat.upper()} ({cat_counts[cat]} vaka) ---")
            print(f"U [{sample['role']}/{sample['response_source']}]: {(sample['user_message'] or '')[:100]}")
            print(f"B: {(sample['bot_response'] or '')[:250]}")
            if sample['sorunlar']:
                print(f"⚠: {sample['sorunlar']}")

        # User message baslari — hangi soru tipleri halusine yoluyor?
        print("\n\n📝 USER MESSAGE BASLARI (ilk 20 kelime):")
        user_starts = {}
        for r in rows:
            msg = (r["user_message"] or "").lower()
            first_words = " ".join(msg.split()[:3])
            user_starts[first_words] = user_starts.get(first_words, 0) + 1
        top_starts = sorted(user_starts.items(), key=lambda x: -x[1])[:15]
        for words, count in top_starts:
            print(f"  {count:>2}x: {words[:60]}")

        # Oneriler
        print("\n\n" + "=" * 70)
        print("💡 AKSIYON ONERILERI")
        print("=" * 70)

        if cat_counts.get("meta_leak", 0) > 3:
            print("⚠ META LEAK — 'ben bir AI', 'Claude', 'prompt' gibi teknik terimler sizdirildi")
            print("  FIX: SYSTEM_PROMPT'da 'TEKNIK BILGI YASAK' kuralini guclendir")

        if cat_counts.get("teknik_sizinti", 0) > 3:
            print("⚠ TEKNIK SIZINTI — tablo/SQL/DB adlari kullanici cevabinda")
            print("  FIX: Claude response post-processing (tablo adlarini temizle)")

        if cat_counts.get("sayi_uydurma", 0) > 10:
            print("⚠ SAYI UYDURMA — net/puan/siralama rakamlari halusine")
            print("  FIX: Tool output'u strict parse + null case'leri explicit handle")

        if cat_counts.get("isim_uydurma", 0) > 3:
            print("⚠ ISIM UYDURMA — DB'de olmayan ogretmen/ogrenci isimleri")
            print("  FIX: search_students zorunlu, isim listesi beyaz liste")

        if cat_counts.get("uzun_cevap", 0) > 10:
            print("⚠ UZUN CEVAP (>1500 char) — overflow halusinasyon riski")
            print("  FIX: Prompt'a 'max 500 char' hatirlatmasi, response_long_check")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
