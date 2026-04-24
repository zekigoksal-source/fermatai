"""
Doğal Sohbet İçi Insight Extraction + Time-Decay (22.1n-fikir1)
================================================================

Neo 20 Nisan 14:00 DİREKT TALİMAT:
> "anket gibi yapay soru yollamak süreci doğallıktan uzaklaştırır — bot'un
>  öğrenciyi konu akışında tıpkı bir insan gibi soru cevap yoluyla konu
>  bağlamı içinde bilgiler çıkarması"
> "hassas olan çıkarımlar güncellenebilmeli. bugün üzgünken yarın mutlu olabilir.
>  bugün fizik derdi iken haftaya matematik olacaktır. dersler uçucu olmalı"

ÇÖZÜM:
Her öğrenci cevabından SONRA arka planda bir extract_insights çağrısı,
konuşmadan organik çıkarımlar yapar. Çıkarımlar kategorili + time-decay'li:

  - mood:          bugünkü duygu (7 gün aktif)
  - active_topic:  bu hafta çalıştığı konu (14 gün aktif)
  - weak_belief:   "matematikten nefret ediyorum" (30 gün aktif)
  - goal_evolution: hedef değişimi (90 gün aktif)
  - study_habit:   çalışma alışkanlığı (60 gün aktif)
  - relationship:  öğretmen/arkadaş ilişkisi ipucu (30 gün aktif)

TIME-DECAY:
  - aktif insight -> last_seen_at güncel tutar
  - yeni çelişen insight gelince eski -> superseded_by işaretlenir, active=FALSE
  - TTL dolunca passive (decay_score < 0.3)

KULLANIM:
  - run_extraction_background(phone, soz_no, user_msg, bot_msg) — her sohbet sonrası çağrılır
  - get_active_insights(soz_no) — Claude context için aktif insight listesi

GÜVENLİK (Neo 22.1n-kural1):
  - Bu modül MESAJ GÖNDERMEZ. Sadece DB yazma/okuma.
"""
import asyncio
import json
from datetime import datetime, timedelta
from typing import Optional

from loguru import logger

# Kategori bazlı TTL (gün cinsinden)
INSIGHT_TTL = {
    "mood":            7,
    "active_topic":    14,
    "weak_belief":     30,
    "goal_evolution":  90,
    "study_habit":     60,
    "relationship":    30,
    "family_context":  60,
    "motivation":      14,
}

# Decay eşiği — altında ise insight görünmez
DECAY_VISIBLE_THRESHOLD = 0.3


def decay_factor(days_old: float, ttl_days: int) -> float:
    """
    Exponential decay — ttl günü dolduğunda confidence ~0.3'e düşer.
    yeni: 1.0, yarı-ömür (ttl/2): 0.65, tam ttl: 0.3, 2*ttl: 0.09
    """
    import math
    if ttl_days <= 0:
        return 0.0
    half_life = ttl_days / 2.0
    return max(0.0, math.exp(-0.693 * days_old / half_life))


async def refresh_decay_scores(soz_no: int):
    """Bir öğrencinin aktif insight'larını yeniden skorla."""
    try:
        soz_no = int(soz_no)
    except (ValueError, TypeError):
        return
    from db_pool import db_fetch, db_execute
    rows = await db_fetch(
        """SELECT id, insight_type, created_at, last_seen_at
           FROM student_insights WHERE soz_no=$1 AND active=TRUE""",
        soz_no
    )
    now = datetime.now()
    for r in rows:
        ttl = INSIGHT_TTL.get(r["insight_type"], 30)
        # last_seen_at'ten geçen gün
        anchor = r["last_seen_at"] or r["created_at"] or now
        days_old = (now - anchor).days
        score = decay_factor(days_old, ttl)
        try:
            await db_execute(
                "UPDATE student_insights SET decay_score=$1, active=$2 WHERE id=$3",
                score, score >= DECAY_VISIBLE_THRESHOLD, r["id"]
            )
        except Exception:
            pass


async def log_insight(
    soz_no: int,
    insight_type: str,
    content: str,
    confidence: float = 0.8,
    source: str = "chat",
    supersede_previous: bool = True
):
    """
    Yeni insight kaydet. Aynı tipde önceki aktif insight varsa eskisi soft-close edilir.

    22.1n-fikir1-bugfix: students.soz_no TEXT, student_insights.soz_no INTEGER.
    int() zorunlu conversion tüm noktalarda.
    """
    if not soz_no or not content:
        return None
    try:
        soz_no = int(soz_no)  # TEXT → INT güvence
    except (ValueError, TypeError):
        logger.debug(f"log_insight geçersiz soz_no: {soz_no!r}")
        return None

    from db_pool import db_execute, db_fetchrow, db_fetchval

    # Aynı tipde son aktif insight var mı?
    existing = await db_fetchrow(
        """SELECT id, content FROM student_insights
           WHERE soz_no=$1 AND insight_type=$2 AND active=TRUE
           ORDER BY created_at DESC LIMIT 1""",
        soz_no, insight_type
    )

    # Aynı içerik — last_seen_at refresh (reinforcement)
    if existing and (existing["content"] or "").strip().lower() == content.strip().lower():
        await db_execute(
            "UPDATE student_insights SET last_seen_at=NOW(), decay_score=LEAST(1.0, decay_score + 0.2) WHERE id=$1",
            existing["id"]
        )
        logger.debug(f"  [INSIGHT refresh] soz_no={soz_no} type={insight_type} content={content[:40]}")
        return existing["id"]

    # Yeni insight — eski varsa supersede
    new_id = await db_fetchval(
        """INSERT INTO student_insights
           (soz_no, insight_type, content, source, confidence, active, last_seen_at, decay_score, created_at)
           VALUES ($1, $2, $3, $4, $5, TRUE, NOW(), 1.0, NOW())
           RETURNING id""",
        soz_no, insight_type, content[:500], source, float(confidence)
    )

    if existing and supersede_previous:
        await db_execute(
            "UPDATE student_insights SET active=FALSE, stale_reason='superseded', superseded_by=$1 WHERE id=$2",
            new_id, existing["id"]
        )
        logger.info(f"  [INSIGHT supersede] soz_no={soz_no} type={insight_type} #{existing['id']} → #{new_id}")
    else:
        logger.info(f"  [INSIGHT new] soz_no={soz_no} type={insight_type} #{new_id}: {content[:50]}")

    return new_id


async def get_active_insights(soz_no: int, limit: int = 10) -> list[dict]:
    """Öğrencinin aktif insight'larını — Claude context için."""
    if not soz_no:
        return []
    # Önce decay skorlarını yenile
    try:
        await refresh_decay_scores(int(soz_no))
    except Exception:
        pass

    from db_pool import db_fetch
    rows = await db_fetch(
        f"""SELECT insight_type, content, decay_score, last_seen_at, created_at
            FROM student_insights
            WHERE soz_no=$1 AND active=TRUE AND decay_score >= $2
            ORDER BY decay_score DESC, last_seen_at DESC
            LIMIT {int(limit)}""",
        int(soz_no), DECAY_VISIBLE_THRESHOLD
    )
    return [
        {
            "tip": r["insight_type"],
            "icerik": r["content"],
            "guven": round(float(r.get("decay_score") or 0.0), 2),
            "son_gorulme": r["last_seen_at"].strftime("%d %b") if r.get("last_seen_at") else "",
        }
        for r in rows
    ]


# ─── LLM EXTRACT ──────────────────────────────────────────────────────────────

EXTRACTION_SYSTEM_PROMPT = """Sen bir pedagojik gözlemcisin. Öğrencinin son mesajından
ORGANIK çıkarımlar yap. Öğrenci anket cevaplamıyor — sohbet ediyor.

Çıkarabileceğin kategoriler:
- mood: bugünkü duygu durumu (tek cümle, ör: "stresli, sınav kaygısı var")
- active_topic: şu an çalıştığı konu (ör: "AYT Fizik Fotoelektrik")
- weak_belief: kendisi hakkında olumsuz inanç (ör: "matematiği asla yapamayacağını düşünüyor")
- goal_evolution: hedef değişimi ipucu (ör: "ITÜ yerine Boğaziçi düşünmeye başladı")
- study_habit: çalışma alışkanlığı (ör: "gece çalışmayı tercih ediyor")
- relationship: öğretmen/arkadaş ilişkisi (ör: "Kardelen Hoca'yla iyi bağ kurmuş")
- family_context: aile ipucu (ör: "babasıyla tercih konusunda anlaşamıyor")
- motivation: motivasyon seviyesi/kaynağı (ör: "kardeşini örnek alarak motive oluyor")

KURALLAR:
- Sadece NET ÇIKARIM yapabildiğin kategorileri doldur
- Uydurma — öğrencinin söylemediği şeyi yazma
- Her insight MAX 100 karakter
- Cevap: saf JSON {"mood": "...", "active_topic": "..."} — bulmadığın key'leri atla
- Boş ise {} dön. EK açıklama YOK.
"""


async def extract_insights_from_message(user_msg: str, bot_msg: str = "") -> dict:
    """Ollama ile hızlı çıkarım yap (yerel, $0 maliyet).

    Claude yerine Ollama tercih — arka plan iş, latency < 3s, bedava.
    """
    if not user_msg or len(user_msg.strip()) < 10:
        return {}

    try:
        import ollama
        client = ollama.Client(host="http://localhost:11434", timeout=15)
        full_ctx = f"Öğrenci: {user_msg[:500]}"
        if bot_msg:
            full_ctx += f"\n\nBot: {bot_msg[:300]}"

        r = client.chat(
            model="qwen2.5:7b",
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": full_ctx}
            ],
            options={"temperature": 0.2, "num_predict": 300},
        )
        txt = (r.get("message") or {}).get("content", "").strip()
        # JSON parse
        import re as _re
        m = _re.search(r'\{.*\}', txt, _re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return {}
        return {}
    except Exception as e:
        logger.debug(f"insight extract Ollama hatası: {e}")
        return {}


async def run_extraction_background(phone: str, soz_no: Optional[int],
                                     user_msg: str, bot_msg: str = ""):
    """Fire-and-forget: sohbet sonrası arkaplanda insight çıkar + DB'ye yaz."""
    # Bug fix 22 Nisan: FERMAT_TEST_MODE aktifse insight yazma (test kirliligi onlenir)
    import os as _os_ie
    if _os_ie.getenv("FERMAT_TEST_MODE"):
        return

    # 22.1n-fikir1-bugfix: students.soz_no TEXT, zorla int
    if soz_no is not None:
        try:
            soz_no = int(soz_no)
        except (ValueError, TypeError):
            soz_no = None

    if not soz_no:
        # Phone'dan lookup dene
        try:
            from db_pool import db_fetchval
            phone_clean = (phone or "").replace("+", "").strip()
            looked = await db_fetchval(
                "SELECT soz_no FROM students WHERE REPLACE(phone,'+','')=$1 AND status='active' LIMIT 1",
                phone_clean
            )
            if looked:
                soz_no = int(looked)
        except Exception:
            pass

    if not soz_no:
        return  # Kayıtsız öğrenci — insight tutma

    try:
        insights = await extract_insights_from_message(user_msg, bot_msg)
    except Exception as e:
        logger.debug(f"insight extraction hatası: {e}")
        return

    if not insights:
        return

    for key, val in insights.items():
        if key in INSIGHT_TTL and val and isinstance(val, str) and 5 < len(val) < 500:
            try:
                await log_insight(soz_no, key, val.strip(), confidence=0.75, source="chat_auto")
            except Exception as e:
                logger.debug(f"insight log error ({key}): {e}")


# ─── CLI ──────────────────────────────────────────────────────────────────────
async def _cli():
    import sys as _sys, argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--soz_no", type=int, help="Ogrenci soz_no")
    parser.add_argument("--test-extract", action="store_true", help="Test extraction")
    parser.add_argument("--msg", type=str, default="Bugun fizik bana cok zor geldi, hic kafam basmiyor")
    parser.add_argument("--refresh", action="store_true", help="Tum ogrenciler decay refresh")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv(override=True)

    if args.test_extract:
        print(f'Test mesaj: {args.msg}')
        r = await extract_insights_from_message(args.msg)
        print(f'Cikarim: {json.dumps(r, indent=2, ensure_ascii=False)}')

    if args.soz_no:
        insights = await get_active_insights(args.soz_no)
        print(f'\nAktif insight ({args.soz_no}): {len(insights)}')
        for i in insights:
            print(f'  [{i["tip"]}] {i["icerik"]} (guven={i["guven"]}, son_gorulme={i["son_gorulme"]})')

    if args.refresh:
        from db_pool import db_fetch
        rows = await db_fetch("SELECT DISTINCT soz_no FROM student_insights WHERE active=TRUE")
        for r in rows:
            await refresh_decay_scores(r["soz_no"])
        print(f'{len(rows)} ogrenci icin decay yenilendi')


if __name__ == "__main__":
    import sys as _sys, io
    _sys.stdout = io.TextIOWrapper(_sys.stdout.buffer, encoding="utf-8", errors="replace")
    asyncio.run(_cli())
