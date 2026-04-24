"""
Konuşma Öğrenme Motoru — WP konuşmalarından pattern çıkar, fast_response güncelle.

Bu modül:
1. Agent konuşmalarını analiz eder
2. Sık sorulan soru kalıplarını tespit eder
3. Başarılı yanıt formatlarını öğrenir
4. Yeni fast_response pattern önerileri oluşturur
5. Hatalı yanıtları işaretler (bulunamadı, ToolUseBlock, jenerik yanıt)

Günde 1x çalıştırılır veya admin komutuyla tetiklenir.
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


async def analyze_conversations(days: int = 7) -> dict:
    """Son N günlük konuşmaları analiz et."""
    since = date.today() - timedelta(days=days)
    since_ts = datetime.combine(since, datetime.min.time())

    pool = await _get_pool()
    async with pool.acquire() as conn:
        # 1. Tüm konuşmaları çek (user mesajları)
        user_msgs = await conn.fetch("""
            SELECT phone, role, content, created_at
            FROM agent_conversations
            WHERE message_role = 'user' AND created_at >= $1
            ORDER BY created_at
        """, since_ts)

        # 2. Hatalı yanıtları bul (genişletilmiş kontrol)
        error_responses = await conn.fetch("""
            SELECT phone, role, content, created_at
            FROM agent_conversations
            WHERE message_role = 'assistant'
            AND created_at >= $1
            AND (
                content LIKE '%bulunamadi%'
                OR content LIKE '%bulunamadı%'
                OR content LIKE '%ToolUseBlock%'
                OR content LIKE '%TextBlock%'
                OR content LIKE '%hata%'
                OR content LIKE '%yapay zeka asistanıyım%'
                OR content LIKE '%yardımcı olmayı%'
                OR content LIKE '%olarak çalışıyorum%'
                OR content LIKE '%olarak çalısıyorum%'
                OR content LIKE '%Lütfen bekleyin%'
                OR content LIKE '%Let''s%'
                OR content LIKE '%dive deeper%'
                OR content LIKE '%Here are%'
                OR content LIKE '%Academically%'
                OR content LIKE '%performance%'
                OR content LIKE '%insights%'
                OR LENGTH(content) < 30
            )
        """, since_ts)

        # 3. Kullanım istatistikleri
        usage_stats = await conn.fetch("""
            SELECT response_source, COUNT(*) as cnt,
                   COALESCE(AVG(response_ms), 0)::int as avg_ms
            FROM usage_log
            WHERE created_at >= $1
            GROUP BY response_source
        """, since_ts)

    return {
        "user_messages": [dict(r) for r in user_msgs],
        "error_responses": [dict(r) for r in error_responses],
        "usage_stats": {r['response_source']: {"count": r['cnt'], "avg_ms": r['avg_ms']} for r in usage_stats},
        "period_days": days,
        "analyzed_at": datetime.now().isoformat(),
    }


def extract_patterns(analysis: dict) -> dict:
    """Konuşmalardan tekrar eden soru kalıplarını çıkar."""
    messages = analysis["user_messages"]

    # Soru kalıpları — kelimeleri normalize et
    question_patterns = Counter()
    topic_counter = Counter()
    role_questions = {"admin": [], "mudur": [], "ogrenci": [], "ogretmen": []}

    for msg in messages:
        text = (msg.get("content") or "").lower().strip()
        role = msg.get("role", "")

        if role in role_questions:
            role_questions[role].append(text)

        # Anahtar kelime çıkarma
        keywords = re.findall(r'\b(akademik|sinav|sınav|deneme|etut|etüt|ders|program|devamsiz|devamsız|'
                              r'ogretmen|öğretmen|hoca|ogrenci|öğrenci|sinif|sınıf|rapor|analiz|'
                              r'karsilastir|karşılaştır|kiyasla|kıyasla|nasil|nasıl|durum|bilgi|'
                              r'en\s*cok|en\s*çok|toplam|hafta|gun|gün|kaç|kac)\b', text)
        for kw in keywords:
            topic_counter[kw] += 1

        # Soru yapısı çıkar
        # "X nasıl" pattern
        m = re.match(r'(.+?)\s+(nasil|nasıl|durumu|akademik|analiz)', text)
        if m:
            subject = m.group(1).strip()
            question_patterns[f"[ISIM] nasıl/durumu"] += 1

        # "en çok X" pattern
        if re.search(r'en\s*(cok|çok|fazla)', text):
            question_patterns["en çok/fazla [KONU]"] += 1

        # "kaç tane X" pattern
        if re.search(r'(kac|kaç)\s*(tane)?', text):
            question_patterns["kaç tane [KONU]"] += 1

        # "X hoca" pattern
        if re.search(r'\w+\s+hoca', text):
            question_patterns["[ISIM] hoca [SORU]"] += 1

    return {
        "question_patterns": dict(question_patterns.most_common(20)),
        "top_topics": dict(topic_counter.most_common(20)),
        "role_distribution": {k: len(v) for k, v in role_questions.items()},
        "total_messages": len(messages),
    }


def identify_gaps(analysis: dict) -> list:
    """Yanıtlanamayan/hatalı soruları tespit et ve öneriler üret."""
    errors = analysis["error_responses"]
    gaps = []

    for err in errors:
        content = err.get("content", "")
        if "bulunamadi" in content:
            # Hangi kelime arandı?
            m = re.search(r"'(.+?)'\s*ile\s*eslesen", content)
            if m:
                searched = m.group(1)
                gaps.append({
                    "type": "wrong_search",
                    "searched_term": searched,
                    "suggestion": f"'{searched}' kelimesi stop-word olarak eklenmeli veya farklı handler'a yönlendirilmeli",
                    "timestamp": str(err.get("created_at", "")),
                })

        elif "ToolUseBlock" in content:
            gaps.append({
                "type": "toolblock_leak",
                "suggestion": "_clean_response() regex'i bu pattern'ı yakalayamadı",
                "timestamp": str(err.get("created_at", "")),
                "sample": content[:100],
            })

        elif any(eng in content.lower() for eng in ["let's", "here are", "dive deeper", "academically", "insights", "performance"]):
            gaps.append({
                "type": "english_response",
                "suggestion": "Ollama İngilizce yanıt verdi — eskalasyon veya Türkçe prompt güçlendirmesi gerekli",
                "timestamp": str(err.get("created_at", "")),
                "sample": content[:80],
            })

        elif "lütfen bekleyin" in content.lower() or "bekleyin" in content.lower():
            gaps.append({
                "type": "incomplete_response",
                "suggestion": "Yarım kalmış yanıt — agent döngüsü tamamlanmamış",
                "timestamp": str(err.get("created_at", "")),
            })

        elif any(gen in content.lower() for gen in ["olarak çalışıyorum", "olarak çalısıyorum", "yapay zeka asistanıyım"]):
            gaps.append({
                "type": "generic_intro",
                "suggestion": "Jenerik tanıtım yanıtı — bağlam anlaşılmamış, eskalasyon gerekli",
                "timestamp": str(err.get("created_at", "")),
            })

        elif len(content) < 30:
            gaps.append({
                "type": "too_short",
                "content": content,
                "suggestion": "Çok kısa yanıt — eskalasyon tetiklenmeli",
                "timestamp": str(err.get("created_at", "")),
            })

    return gaps


def suggest_new_fast_responses(patterns: dict, gaps: list) -> list:
    """Yeni fast_response önerileri oluştur."""
    suggestions = []

    # En sık sorulan ama fast_response'da olmayan pattern'lar
    top_patterns = patterns.get("question_patterns", {})
    for pattern, count in top_patterns.items():
        if count >= 3:  # 3+ kez sorulmuş
            suggestions.append({
                "pattern": pattern,
                "frequency": count,
                "action": "fast_response pattern olarak ekle",
            })

    # Gap'lerden öneriler
    wrong_searches = [g for g in gaps if g["type"] == "wrong_search"]
    if wrong_searches:
        terms = set(g["searched_term"] for g in wrong_searches)
        suggestions.append({
            "pattern": "stop_words_update",
            "terms": list(terms),
            "action": f"Bu kelimeler stop-word olarak eklenmeli: {', '.join(terms)}",
        })

    return suggestions


async def generate_learning_report() -> str:
    """Öğrenme raporu oluştur ve dosyaya kaydet."""
    analysis = await analyze_conversations(days=7)
    patterns = extract_patterns(analysis)
    gaps = identify_gaps(analysis)
    suggestions = suggest_new_fast_responses(patterns, gaps)

    report = {
        "generated_at": datetime.now().isoformat(),
        "period": f"Son 7 gün",
        "total_messages": patterns["total_messages"],
        "role_distribution": patterns["role_distribution"],
        "top_topics": patterns["top_topics"],
        "question_patterns": patterns["question_patterns"],
        "usage_stats": analysis["usage_stats"],
        "error_count": len(analysis["error_responses"]),
        "gaps": gaps[:20],
        "suggestions": suggestions,
    }

    # Dosyaya kaydet
    report_file = LEARN_DIR / f"report_{date.today().isoformat()}.json"
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    # Özet text
    usage = analysis["usage_stats"]
    fast_pct = 0
    total = sum(v["count"] for v in usage.values()) if usage else 1
    if "fast_response" in usage:
        fast_pct = round(usage["fast_response"]["count"] / total * 100, 1)

    summary = f"""📊 *FermatAI Öğrenme Raporu*
_Son 7 gün analizi_

*Toplam mesaj:* {patterns['total_messages']}
*Hata sayısı:* {len(gaps)}
*Fast response oranı:* %{fast_pct}

*En çok sorulan konular:*
"""
    for topic, count in list(patterns["top_topics"].items())[:8]:
        summary += f"  - {topic}: {count}x\n"

    if suggestions:
        summary += f"\n*Öneriler ({len(suggestions)} adet):*\n"
        for s in suggestions[:5]:
            summary += f"  - {s['action']}\n"

    if gaps:
        summary += f"\n*Düzeltilmesi gereken {len(gaps)} sorun tespit edildi.*"

    return summary


async def auto_update_stop_words(gaps: list) -> int:
    """Gap'lerden otomatik stop-word güncellemesi öner (dosyaya yaz, uygulamaz)."""
    wrong_searches = [g for g in gaps if g["type"] == "wrong_search"]
    if not wrong_searches:
        return 0

    new_stops = set()
    for g in wrong_searches:
        term = g["searched_term"].lower()
        # Gerçek isim olabilecek kelimeleri atla (2+ kelime, büyük harf)
        if len(term.split()) == 1 and not term[0].isupper():
            new_stops.add(term)

    if new_stops:
        suggest_file = LEARN_DIR / "suggested_stop_words.json"
        existing = set()
        if suggest_file.exists():
            existing = set(json.loads(suggest_file.read_text(encoding="utf-8")))
        existing.update(new_stops)
        suggest_file.write_text(json.dumps(sorted(existing), ensure_ascii=False, indent=2), encoding="utf-8")

    return len(new_stops)


async def main():
    """CLI çalıştırma."""
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    print("=== Konuşma Öğrenme Raporu ===\n")
    summary = await generate_learning_report()
    print(summary)

    # Gap analizi
    analysis = await analyze_conversations(days=7)
    gaps = identify_gaps(analysis)
    new_stops = await auto_update_stop_words(gaps)
    if new_stops:
        print(f"\n[!] {new_stops} yeni stop-word önerisi kaydedildi → learned_patterns/suggested_stop_words.json")


if __name__ == "__main__":
    asyncio.run(main())
