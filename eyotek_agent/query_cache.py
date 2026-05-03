"""
Query Cache Similarity (Oturum 22.1)
=====================================

Ollama'ya anlamli is — semantik sorgu cache'i.

Mantik:
- Ogrenci aynı soruyu tekrar sordugunda (varyasyonlarla) Claude'a gitmeden
  onceki cevabi ver.
- nomic-embed-text (Ollama, yerel, $0) ile sorgu embedding hesaplanir.
- pgvector cosine similarity ile en yakın kayıt bulunur.
- Threshold 0.92 → çok benzer olmalı (false positive önleme).
- TTL 24 saat → veri eskimesin.

Güvenlik:
- PER-PHONE cache (başka kullanıcının cevabı sızmaz).
- Tool-calling cevapları cache'lenmez (veri dinamik).
- Sadece saf Ollama + static Claude cevapları cache'lenir.
- Admin/mudur için de per-phone (isolation).

Mimari karar:
- Query cache'i rag_content'ten ayrı tutulur (farklı ömür, farklı anlam).
- Hit counter ile populer sorulari izler.
- Cleanup cron ile eski kayıtlar silinir.
"""
import asyncio
import hashlib
from typing import Optional
from loguru import logger

try:
    import ollama as _ollama
except ImportError:
    _ollama = None

# nomic-embed-text — Ollama yerel, VPS'te kurulu (768 dim).
# Oturum 25.40r (3 May 2026): bge-m3 (1024 dim) VPS'te yoktu →
# semantic cache sessizce devre disiydi. nomic-embed-text'e gecildi.
# Test bekleniyor: identik ~0.95 / synonym ~0.65 / different ~0.20
# Threshold 0.82 → bge'den biraz daha siki (nomic Turkce'de daha gevsek)
EMBED_MODEL = "nomic-embed-text"
EMBED_DIM = 768

# Ayarlar
SEMANTIC_ENABLED = True
DEFAULT_SIMILARITY_THRESHOLD = 0.82
DEFAULT_TTL_HOURS = 24
MIN_RESPONSE_LENGTH = 20  # cok kisa cevaplar cache'lenmesin


# ── KALİTE FİLTRESİ (Oturum Mentenans 21 Nisan 18:00) ────────────────────────
# Neo talimati: kalitesiz Ollama cevaplari cache'e GIRMESIN.
# 3 katman: halusinasyon marker / gorsel yapi yok / anlamsiz kelime orani.

_HALLUC_MARKERS = [
    # Bugun tespit edilen bozuk kelimeler (halusinasyon)
    "zingerli", "zingeris", "zingerlisin",
    "nasımlı", "nasimli",
    "desiyon stresi", "desyon stres",
    "deneysim", "öğretmen biliyor ki",
    # Ingilizce kalintilari
    "here is", "let me explain", "i can help", "sure!",
    "here's", "that's", "you can",
    # Sistemle kirlenme
    "system prompt", "bilinmeyen kelime", "olarak bir",
    "bir ai asistan", "bir yapay zeka",
    # Kötü tekrar
    "merhaba merhaba", "selam selam",
]


def _anlamsiz_kelime_orani(text: str) -> float:
    """Metindeki kelimelerin kaç yüzdesi 'anlamsız'?

    Anlamsız = sesli harf oranı <%20 VEYA >%75 VEYA tekrarlı ünsüz kümesi.
    Türkçe'de normal kelimelerin sesli oranı genelde %35-50 arası.
    Halusinasyon kelimeler (ör. "zngrl", "rrrf") sesli oranı aşırı düşük.

    Returns: 0.0 (temiz) - 1.0 (hepsi anlamsız).
    """
    import re
    if not text:
        return 0.0
    # Sadece kelime karakterleri (letter) ayıkla — 3+ uzunluk
    words = re.findall(r'[a-zA-Zçğıöşüâîû]{3,}', text, flags=re.IGNORECASE)
    if not words:
        return 0.0
    SESLI = set("aeıiouöüâîûAEIIOUÖÜÂÎÛ")
    bozuk = 0
    for w in words:
        wl = w.lower()
        ch_count = len([c for c in wl if c.isalpha()])
        if ch_count < 3:
            continue
        sesli_count = len([c for c in wl if c in SESLI])
        sesli_oran = sesli_count / ch_count
        # Anlamsız koşulları
        if sesli_oran < 0.15 or sesli_oran > 0.80:
            bozuk += 1
        elif re.search(r'(.)\1{3,}', wl):  # 4+ ardışık aynı harf (rrrr, zzzz)
            bozuk += 1
        elif re.search(r'[bcdfgjklmnpqstvwxyz]{5,}', wl):  # 5+ ardışık ünsüz
            bozuk += 1
    return bozuk / len(words) if words else 0.0


def _is_off_topic_content(text: str) -> bool:
    """23 Nisan: off-topic konulu uzun cevap (valorant/dizi/film vb.) cache'lenmesin.

    Neo kuralı: "off-topic'te kısa tut (max 200 char)". Cache'e uzun off-topic
    yazıldıysa aynı yanıt geri döner → classroom management kuralı ezilir.
    """
    if not text:
        return False
    import re
    low = text.lower()
    off_topic_markers = [
        "valorant", "pes oynad", "fifa oynad", "minecraft", "roblox",
        "netflix", "disney plus", "spotify",
        "tiktok", "instagram", "youtube",
        "maç izle", "maç seyret", "derbi", "galatasaray", "fenerbahçe",
        "chatgpt", "gemini", "copilot",
        "oyuncu deneyim", "oynarken", "izledim dizi",
    ]
    hit = sum(1 for m in off_topic_markers if m in low)
    # 2+ off-topic marker + 250+ char → uzun off-topic sohbet, cache'leme
    return hit >= 2 and len(text) > 250


def is_ollama_response_cacheable(response: str) -> bool:
    """Ollama yanıtı cache'e yazılmaya değer mi?

    5 kontrol katmanı (23 Nisan: off-topic eklendi):
    1. Bilinen halusinasyon marker'ı var mı?
    2. Anlamsız kelime oranı >%15 mi? (halusinasyon/typo göstergesi)
    3. Kısa cevap (<40 char) + hiç emoji yok mu? (zayıf yapı)
    4. Orta cevap (100+ char) + görsel yapı (emoji/bold/italic) yok mu?
    5. Off-topic uzun cevap (valorant/film vb. 250+ char) — cache'lenmez.

    Returns: True = cache'e yazılabilir, False = skip.
    """
    if not response:
        return False
    import re
    # Turkce karakter fold + lower — "ZİNGERLİSIN".lower() combining char sorunu yasamasin
    resp_lower = response.translate(_TR_FOLD).lower()

    # 1) Halusinasyon marker'ları
    if any(m in resp_lower for m in _HALLUC_MARKERS):
        logger.warning(f"  [CACHE-SKIP] Halusinasyon marker: '{response[:60]}'")
        return False

    # 2) Anlamsız kelime oranı — tek kontrol (false positive riskini bil)
    bozuk_oran = _anlamsiz_kelime_orani(response)
    if bozuk_oran > 0.15:
        logger.warning(f"  [CACHE-SKIP] Anlamsiz kelime orani %{int(bozuk_oran*100)}: '{response[:60]}'")
        return False

    # 3) Kısa cevap (<40 char) + emoji yok → düz tek cümle, zayıf
    has_emoji = bool(re.search(r'[\U0001f300-\U0001fad6]', response))
    if len(response) < 40 and not has_emoji:
        logger.warning(f"  [CACHE-SKIP] Cok kisa (<40) + emoji yok: '{response[:60]}'")
        return False

    # 4) Orta+ cevap (100+) + hiçbir görsel yapı (emoji/bold/italic) yok → düz yazı
    has_bold_or_italic = (
        ('*' in response and response.count('*') >= 2) or
        ('_' in response and response.count('_') >= 2)
    )
    if len(response) > 100 and not has_emoji and not has_bold_or_italic:
        logger.warning(f"  [CACHE-SKIP] Gorsel yapisiz (100+ char): '{response[:60]}'")
        return False

    # 5) Off-topic uzun cevap — classroom_mgmt "off_topic kısa" kuralını ezmesin
    if _is_off_topic_content(response):
        logger.warning(f"  [CACHE-SKIP] Off-topic uzun cevap: '{response[:60]}'")
        return False

    return True


# Turkce karakter folding — hash normalizasyonu icin
_TR_FOLD = str.maketrans({
    "ı": "i", "İ": "i", "I": "i",
    "ş": "s", "Ş": "s",
    "ğ": "g", "Ğ": "g",
    "ü": "u", "Ü": "u",
    "ö": "o", "Ö": "o",
    "ç": "c", "Ç": "c",
})


# ── Tablo Olusturma ─────────────────────────────────────────────────

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS query_cache (
    id SERIAL PRIMARY KEY,
    phone TEXT NOT NULL,
    role TEXT,
    prompt TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    embedding vector(1024),
    response TEXT NOT NULL,
    source TEXT DEFAULT 'claude',
    hit_count INT DEFAULT 0,
    ttl_hours INT DEFAULT 24,
    created_at TIMESTAMP DEFAULT NOW(),
    last_used_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_qc_phone ON query_cache (phone);
CREATE INDEX IF NOT EXISTS idx_qc_created ON query_cache (created_at);
CREATE INDEX IF NOT EXISTS idx_qc_hash ON query_cache (prompt_hash);
"""


async def init_db():
    """Tabloyu olustur + boyut migrate (1024 bge-m3 -> 768 nomic gecisi 25.40r).

    pgvector boyutu pg_attribute.atttypmod'da DEGIL — format_type ile string olarak
    'vector(N)' formatinda gelir. Regex ile parse edip karsilastir.
    Tablo yoksa regclass cast UndefinedTableError firlatir — sessizce yutulur."""
    import re
    from db_pool import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Mevcut tablo varsa boyutu kontrol et — yanlissa DROP+recreate
        existing_dim = None
        try:
            type_str = await conn.fetchval("""
                SELECT format_type(atttypid, atttypmod) FROM pg_attribute
                WHERE attrelid = 'query_cache'::regclass AND attname = 'embedding'
            """)
            if type_str:
                m = re.search(r'vector\((\d+)\)', type_str)
                if m:
                    existing_dim = int(m.group(1))
        except Exception:
            # Tablo yok — direkt CREATE'e gec
            pass

        if existing_dim is not None and existing_dim != EMBED_DIM:
            logger.warning(f"Query cache boyut mismatch ({existing_dim} != {EMBED_DIM}) — tablo recreate")
            await conn.execute("DROP TABLE IF EXISTS query_cache CASCADE")
        await conn.execute(CREATE_TABLE_SQL)
    logger.info(f"Query cache tablosu hazir (dim={EMBED_DIM})")


# ── Embedding ────────────────────────────────────────────────────────

def _embed(text: str) -> Optional[list[float]]:
    """Ollama nomic-embed-text ile 768-boyutlu vektor — hata olursa None."""
    if _ollama is None:
        return None
    try:
        resp = _ollama.embed(model=EMBED_MODEL, input=text)
        embeddings = resp.get("embeddings", [])
        if embeddings and len(embeddings[0]) == EMBED_DIM:
            return embeddings[0]
        logger.debug(f"Query cache embed boyut uyumsuz: got={len(embeddings[0]) if embeddings else 0}")
        return None
    except Exception as e:
        logger.debug(f"Query cache embed hatasi: {e}")
        return None


def _hash_prompt(prompt: str) -> str:
    """Prompt kimligi — agresif normalize ile exact match arama.
    Case + Turkce karakter + punktuasyon + whitespace farkini yakalar."""
    import re
    s = (prompt or "").lower().strip()
    s = s.translate(_TR_FOLD)
    s = re.sub(r"[^\w\s]", "", s)  # punktuasyon sil
    s = re.sub(r"\s+", " ", s).strip()  # whitespace normalize
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:16]


# ── Cache Lookup ─────────────────────────────────────────────────────

async def find_cached(
    phone: str,
    query: str,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    max_age_hours: int = DEFAULT_TTL_HOURS,
) -> Optional[dict]:
    """
    Semantik cache'te ara — bulunursa cevabi don.

    Returns:
        {"response": str, "similarity": float, "id": int, "source": str} or None
    """
    if not query or len(query.strip()) < 3:
        return None

    from db_pool import get_pool

    # 1) Once exact hash match (cok hizli)
    prompt_hash = _hash_prompt(query)
    pool = await get_pool()
    async with pool.acquire() as conn:
        exact = await conn.fetchrow(
            """
            SELECT id, response, source, hit_count
            FROM query_cache
            WHERE phone = $1 AND prompt_hash = $2
              AND created_at > NOW() - ($3 || ' hours')::interval
            ORDER BY created_at DESC
            LIMIT 1
            """,
            phone, prompt_hash, str(max_age_hours)
        )
        if exact:
            # hit++
            await conn.execute(
                "UPDATE query_cache SET hit_count = hit_count + 1, last_used_at = NOW() WHERE id = $1",
                exact["id"]
            )
            logger.info(f"🎯 Query cache EXACT hit (id={exact['id']})")
            return {
                "response": exact["response"],
                "similarity": 1.0,
                "id": exact["id"],
                "source": exact["source"],
                "match_type": "exact",
            }

        # 2) Semantik similarity — nomic-embed yapi bias'li, KAPALI
        if not SEMANTIC_ENABLED:
            return None
        vector = await asyncio.to_thread(_embed, query)
        if vector is None:
            return None

        vec_str = str(vector)
        row = await conn.fetchrow(
            """
            SELECT id, response, source, hit_count,
                   1 - (embedding <=> $1::vector) AS similarity
            FROM query_cache
            WHERE phone = $2
              AND embedding IS NOT NULL
              AND created_at > NOW() - ($3 || ' hours')::interval
              AND 1 - (embedding <=> $1::vector) >= $4
            ORDER BY embedding <=> $1::vector
            LIMIT 1
            """,
            vec_str, phone, str(max_age_hours), similarity_threshold
        )

        if row:
            await conn.execute(
                "UPDATE query_cache SET hit_count = hit_count + 1, last_used_at = NOW() WHERE id = $1",
                row["id"]
            )
            logger.info(f"🎯 Query cache SEMANTIK hit (id={row['id']}, skor={row['similarity']:.3f})")
            return {
                "response": row["response"],
                "similarity": float(row["similarity"]),
                "id": row["id"],
                "source": row["source"],
                "match_type": "semantic",
            }

    return None


# ── Cache Yazma ──────────────────────────────────────────────────────

async def add_to_cache(
    phone: str,
    role: str,
    query: str,
    response: str,
    source: str = "claude",
    ttl_hours: int = DEFAULT_TTL_HOURS,
) -> Optional[int]:
    """Yeni bir soru-cevap cifti cache'e ekle."""
    if not query or not response:
        return None
    if len(response) < MIN_RESPONSE_LENGTH:
        return None

    # Oturum Mentenans (21 Nisan 16:00) — Neo talimati: kalitesiz Ollama cevaplari
    # cache'e GIRMESIN. Bir kez yanlis cevap yazildiginda uzun sure o donuyor.
    # Oturum Mentenans (21 Nisan 18:00) — Katman 2: anlamsiz kelime tespiti + kisa-no-emoji
    if source == "ollama":
        if not is_ollama_response_cacheable(response):
            logger.warning(f"  [CACHE-SKIP] Ollama cevabi kalitesiz: '{query[:40]}'")
            return None

    from db_pool import get_pool

    prompt_hash = _hash_prompt(query)
    # Embed sadece SEMANTIC_ENABLED ise (su an kapali)
    if SEMANTIC_ENABLED:
        vector = await asyncio.to_thread(_embed, query)
        vec_str = str(vector) if vector else None
    else:
        vec_str = None

    pool = await get_pool()
    async with pool.acquire() as conn:
        new_id = await conn.fetchval(
            """
            INSERT INTO query_cache
                (phone, role, prompt, prompt_hash, embedding, response, source, ttl_hours)
            VALUES ($1, $2, $3, $4, $5::vector, $6, $7, $8)
            RETURNING id
            """,
            phone, role or "ogrenci", query[:1000], prompt_hash,
            vec_str, response[:5000], source, ttl_hours
        )
    logger.debug(f"Query cache ekle: id={new_id} phone={phone[-4:]} src={source}")
    return new_id


# ── Cache Temizlik ───────────────────────────────────────────────────

async def cleanup_expired() -> int:
    """TTL asilmis kayitlari sil."""
    from db_pool import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM query_cache
            WHERE created_at < NOW() - (ttl_hours || ' hours')::interval
            """
        )
    # "DELETE N" formatinda gelir
    try:
        count = int(result.split()[-1])
    except Exception:
        count = 0
    if count:
        logger.info(f"🧹 Query cache temizlendi: {count} kayit silindi")
    return count


# ── Istatistik ───────────────────────────────────────────────────────

async def get_stats() -> dict:
    """Cache istatistikleri."""
    from db_pool import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        toplam = await conn.fetchval("SELECT COUNT(*) FROM query_cache")
        aktif = await conn.fetchval(
            "SELECT COUNT(*) FROM query_cache WHERE created_at > NOW() - INTERVAL '24 hours'"
        )
        total_hits = await conn.fetchval("SELECT COALESCE(SUM(hit_count),0) FROM query_cache")
        top = await conn.fetch(
            """
            SELECT prompt, hit_count, source
            FROM query_cache
            ORDER BY hit_count DESC
            LIMIT 10
            """
        )
        source_dist = await conn.fetch(
            "SELECT source, COUNT(*) as cnt FROM query_cache GROUP BY source"
        )
    return {
        "toplam": toplam,
        "aktif_24s": aktif,
        "toplam_hit": int(total_hits),
        "top_10": [{"prompt": r["prompt"][:80], "hit": r["hit_count"], "src": r["source"]} for r in top],
        "source_dist": {r["source"]: r["cnt"] for r in source_dist},
    }


# ── CLI Test ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    async def main():
        await init_db()

        # Test add
        cid = await add_to_cache(
            phone="905000000000",
            role="ogrenci",
            query="Turev nedir kisaca anlat",
            response="Turev, bir fonksiyonun anlik degisim oranini olcen matematiksel kavramdir...",
            source="claude",
        )
        print(f"Eklendi: id={cid}")

        # Test find - exact
        hit = await find_cached("905000000000", "Turev nedir kisaca anlat")
        print(f"Exact arama: {hit['match_type'] if hit else 'miss'}")

        # Test find - semantik
        hit = await find_cached("905000000000", "turev kisaca nedir")
        print(f"Semantik arama: {hit and hit['match_type']} skor={hit and hit.get('similarity')}")

        # Stats
        stats = await get_stats()
        print(f"Stats: {stats}")

    asyncio.run(main())
