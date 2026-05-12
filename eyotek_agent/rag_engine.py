"""
FermatAI — RAG Engine (Retrieval-Augmented Generation)
=======================================================
pgvector + Ollama nomic-embed-text ile semantik konu arama.
Öğrenci ders sorusu sorduğunda müfredat bilgi bankasından
en alakalı içerikleri bulur.

Kullanım:
  from rag_engine import search_curriculum, add_content

  # Semantik arama
  results = await search_curriculum("kaldırma kuvveti nedir")

  # İçerik ekleme
  await add_content(
      sinav_turu="TYT", ders="Fizik",
      konu="Kaldırma Kuvveti", icerik_turu="konu_anlatimi",
      baslik="Kaldırma Kuvveti — Temel Kavramlar",
      icerik="Kaldırma kuvveti, bir sıvı içine...",
      kaynak="MEB müfredat", zorluk="orta", soru_sayisi=1
  )
"""

import asyncio
import json
from typing import Optional

import ollama as _ollama
from loguru import logger
from db_pool import get_pool as _get_pool, db_fetch, db_fetchval, db_execute, db_fetchrow

EMBED_MODEL = "nomic-embed-text"
EMBED_DIM = 768


# ── Tablo Oluşturma ─────────────────────────────────────────────────

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS rag_content (
    id SERIAL PRIMARY KEY,
    sinav_turu TEXT NOT NULL,
    ders TEXT NOT NULL,
    konu TEXT NOT NULL,
    alt_konu TEXT,
    icerik_turu TEXT NOT NULL,
    baslik TEXT NOT NULL,
    icerik TEXT NOT NULL,
    kaynak TEXT,
    zorluk TEXT,
    soru_sayisi INT DEFAULT 0,
    anahtar_kelimeler TEXT[],
    embedding vector(768),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rag_sinav_ders ON rag_content (sinav_turu, ders);
CREATE INDEX IF NOT EXISTS idx_rag_konu ON rag_content (konu);
"""

# IVFFlat index — veri 100+ kayda ulaşınca oluşturulur
CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_rag_embedding ON rag_content
USING ivfflat (embedding vector_cosine_ops) WITH (lists = 20);
"""


async def init_db():
    """Tabloyu oluştur (yoksa)."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(CREATE_TABLE_SQL)
        # Kayıt sayısı yeterliyse IVFFlat index
        count = await conn.fetchval("SELECT COUNT(*) FROM rag_content")
        if count >= 50:
            try:
                await conn.execute(CREATE_INDEX_SQL)
            except Exception:
                pass  # Index zaten var veya veri az
    logger.info(f"RAG tablosu hazır ({count} kayıt)")


# ── Embedding ────────────────────────────────────────────────────────

def embed_text(text: str) -> list[float]:
    """Ollama nomic-embed-text ile 768 boyutlu vektör üret."""
    try:
        resp = _ollama.embed(model=EMBED_MODEL, input=text)
        embeddings = resp.get("embeddings", [[]])
        return embeddings[0] if embeddings else [0.0] * EMBED_DIM
    except Exception as e:
        logger.warning(f"Embedding hatası: {e}")
        return [0.0] * EMBED_DIM


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Toplu embedding — batch API ile hızlı."""
    try:
        resp = _ollama.embed(model=EMBED_MODEL, input=texts)
        return resp.get("embeddings", [[0.0] * EMBED_DIM] * len(texts))
    except Exception as e:
        logger.warning(f"Batch embedding hatası: {e}")
        return [[0.0] * EMBED_DIM] * len(texts)


# ── İçerik Ekleme ────────────────────────────────────────────────────

async def add_content(
    sinav_turu: str,
    ders: str,
    konu: str,
    icerik_turu: str,
    baslik: str,
    icerik: str,
    kaynak: str = "",
    zorluk: str = "orta",
    soru_sayisi: int = 0,
    alt_konu: str = "",
    anahtar_kelimeler: list[str] = None,
) -> int:
    """İçerik ekle + otomatik embedding üret.

    25.44 BUG FIX (bot dev meeting #2, 12 May 19:20):
    Sentry #119329109 → 'invalid byte sequence for encoding UTF8: 0x00'
    PDF text extraction / OGM Vision import bazen NULL byte (\\x00) içeren
    string dönüyor. PostgreSQL UTF8 text bunu reddediyor → INSERT crash.
    Defensive sanitize: tüm text inputlardan \\x00 strip et.
    """
    def _clean(s):
        """NULL byte ve diğer kontrol karakterlerini temizle."""
        if not isinstance(s, str):
            return s
        # \x00 (NULL) PostgreSQL UTF8 reddeder
        # \x01-\x08, \x0b, \x0c, \x0e-\x1f kontrol karakterleri (TAB/LF/CR hariç)
        return ''.join(ch for ch in s if ch == '\t' or ch == '\n' or ch == '\r'
                       or ord(ch) >= 0x20)

    sinav_turu = _clean(sinav_turu)
    ders = _clean(ders)
    konu = _clean(konu)
    icerik_turu = _clean(icerik_turu)
    baslik = _clean(baslik)
    icerik = _clean(icerik)
    kaynak = _clean(kaynak)
    alt_konu = _clean(alt_konu)
    if anahtar_kelimeler:
        anahtar_kelimeler = [_clean(k) for k in anahtar_kelimeler if k]

    # Embedding için: başlık + konu + ders + içerik özeti
    embed_input = f"{ders} {konu} {alt_konu} {baslik} {icerik[:500]}"
    vector = embed_text(embed_input)

    pool = await _get_pool()
    async with pool.acquire() as conn:
        # Duplicate kontrolü
        existing = await conn.fetchval(
            "SELECT id FROM rag_content WHERE sinav_turu=$1 AND ders=$2 AND konu=$3 AND icerik_turu=$4",
            sinav_turu, ders, konu, icerik_turu
        )

        if existing:
            # Güncelle
            await conn.execute("""
                UPDATE rag_content SET
                    baslik=$1, icerik=$2, kaynak=$3, zorluk=$4, soru_sayisi=$5,
                    alt_konu=$6, anahtar_kelimeler=$7, embedding=$8, updated_at=NOW()
                WHERE id=$9
            """, baslik, icerik, kaynak, zorluk, soru_sayisi,
                alt_konu, anahtar_kelimeler or [], str(vector), existing)
            return existing
        else:
            # Yeni ekle
            new_id = await conn.fetchval("""
                INSERT INTO rag_content
                    (sinav_turu, ders, konu, alt_konu, icerik_turu, baslik, icerik,
                     kaynak, zorluk, soru_sayisi, anahtar_kelimeler, embedding)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                RETURNING id
            """, sinav_turu, ders, konu, alt_konu, icerik_turu, baslik, icerik,
                kaynak, zorluk, soru_sayisi, anahtar_kelimeler or [], str(vector))
            return new_id


# ── Semantik Arama ───────────────────────────────────────────────────

async def search_curriculum(
    query: str,
    sinav_turu: str = "",
    ders: str = "",
    limit: int = 5,
) -> list[dict]:
    """
    Semantik arama — soruya en yakın müfredat içeriklerini bul.

    22 Nisan iyileştirme: threshold 0.35 → 0.55 (false match azaltır),
    ayrıca konu başlığı/icerik keyword priority — "türev" aramasında
    "Bölünebilme Kuralları"na düşmesin.

    Args:
        query: Arama sorgusu ("kaldırma kuvveti nedir?")
        sinav_turu: Filtre (TYT, AYT, LGS)
        ders: Filtre (Fizik, Matematik...)
        limit: Max sonuç

    Returns:
        [{ders, konu, baslik, icerik, skor, zorluk, soru_sayisi}, ...]
    """
    import re
    # 22 Nisan: Query'den ana kelimeyi çıkar (keyword priority için)
    _stopwords = {"nedir", "nasıl", "ne", "demek", "anlat", "açıkla", "acikla",
                   "ogret", "öğret", "mısın", "misin", "bu", "şu", "bir", "ile"}
    # Turkce fold
    tr_fold = str.maketrans({"ı": "i", "İ": "i", "ş": "s", "Ş": "s",
                              "ğ": "g", "Ğ": "g", "ü": "u", "Ü": "u",
                              "ö": "o", "Ö": "o", "ç": "c", "Ç": "c"})
    q_fold = query.translate(tr_fold).lower()
    words = [w for w in re.findall(r'\w{4,}', q_fold) if w not in _stopwords]
    main_keyword = max(words, key=len) if words else ""

    # 22 Nisan: KEYWORD-FIRST stratejisi (nomic-embed Türkçe zayıf)
    # Main keyword konu/baslik'ta varsa ÖNCE ILIKE search, hit yoksa semantic.
    # Türkçe karakter: DB'de "Türev", query'de "turev" — TRANSLATE ile normalize.
    if main_keyword and len(main_keyword) >= 4:
        try:
            pool = await _get_pool()
            async with pool.acquire() as conn:
                # PostgreSQL'de TRANSLATE ile DB-side fold
                _TR_IN = "ıİşŞğĞüÜöÖçÇ"
                _TR_OUT = "iIsSgGuUoOcC"
                kw_filters = [
                    f"TRANSLATE(LOWER(konu), '{_TR_IN}', '{_TR_OUT}') LIKE $1",
                ]
                kw_params = [f"%{main_keyword}%"]
                kw_idx = 2
                if sinav_turu:
                    kw_filters.append(f"sinav_turu = ${kw_idx}")
                    kw_params.append(sinav_turu)
                    kw_idx += 1
                if ders:
                    kw_filters.append(f"ders ILIKE ${kw_idx}")
                    kw_params.append(f"%{ders}%")
                    kw_idx += 1
                kw_params.append(limit)
                kw_rows = await conn.fetch(
                    f"""
                    SELECT id, sinav_turu, ders, konu, alt_konu, icerik_turu,
                           baslik, icerik, kaynak, zorluk, soru_sayisi
                    FROM rag_content
                    WHERE {' AND '.join(kw_filters)}
                    LIMIT ${kw_idx}
                    """,
                    *kw_params,
                )
                if kw_rows:
                    results = []
                    for r in kw_rows:
                        results.append({
                            "id": r["id"],
                            "sinav_turu": r["sinav_turu"],
                            "ders": r["ders"],
                            "konu": r["konu"],
                            "alt_konu": r["alt_konu"],
                            "icerik_turu": r["icerik_turu"],
                            "baslik": r["baslik"],
                            "icerik": r["icerik"],
                            "kaynak": r["kaynak"],
                            "zorluk": r["zorluk"],
                            "soru_sayisi": r["soru_sayisi"],
                            "skor": 0.95,  # yüksek güven — keyword exact match
                            "match_type": "keyword",
                        })
                    return results
        except Exception as _kwe:
            from loguru import logger as _l
            _l.debug(f"RAG keyword search hatasi: {_kwe}")

    # Keyword miss → semantic fallback (threshold 0.55)
    vector = embed_text(query)
    vec_str = str(vector)

    # SQL filtreler
    filters = []
    params = [vec_str, limit]
    param_idx = 3

    if sinav_turu:
        filters.append(f"sinav_turu = ${param_idx}")
        params.append(sinav_turu)
        param_idx += 1

    if ders:
        filters.append(f"ders ILIKE ${param_idx}")
        params.append(f"%{ders}%")
        param_idx += 1

    # 22 Nisan: Minimum similarity threshold 0.35 → 0.55 (sıkı)
    filters.append("1 - (embedding <=> $1::vector) >= 0.55")
    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT id, sinav_turu, ders, konu, alt_konu, icerik_turu,
                   baslik, icerik, kaynak, zorluk, soru_sayisi,
                   1 - (embedding <=> $1::vector) as similarity
            FROM rag_content
            {where_clause}
            ORDER BY embedding <=> $1::vector
            LIMIT $2
        """, *params)

        results = []
        for r in rows:
            results.append({
                "id": r["id"],
                "sinav_turu": r["sinav_turu"],
                "ders": r["ders"],
                "konu": r["konu"],
                "alt_konu": r["alt_konu"],
                "icerik_turu": r["icerik_turu"],
                "baslik": r["baslik"],
                "icerik": r["icerik"],
                "kaynak": r["kaynak"],
                "zorluk": r["zorluk"],
                "soru_sayisi": r["soru_sayisi"],
                "skor": round(r["similarity"], 3),
            })

        # 22 Nisan: Keyword priority re-rank
        # Main keyword başlık/konu'da varsa skor +0.2 bonus (üste çıkar).
        # Bu "türev" aramasında "Bölünebilme" üst sıraya çıkmasın diye.
        if main_keyword and results:
            for r in results:
                bonus = 0.0
                if main_keyword in (r.get("konu") or "").lower():
                    bonus += 0.20
                if main_keyword in (r.get("baslik") or "").lower():
                    bonus += 0.15
                if main_keyword in (r.get("alt_konu") or "").lower():
                    bonus += 0.10
                r["skor"] = round(r["skor"] + bonus, 3)
            # Yeniden sırala
            results.sort(key=lambda x: x["skor"], reverse=True)

        return results


async def get_topic_content(ders: str, konu: str) -> Optional[dict]:
    """Belirli bir ders+konu için içerik getir (exact match)."""
    row = await db_fetchrow(
        "SELECT * FROM rag_content WHERE ders ILIKE $1 AND konu ILIKE $2 LIMIT 1",
        f"%{ders}%", f"%{konu}%"
    )
    return row if row else None


async def get_stats() -> dict:
    """RAG istatistikleri."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM rag_content")
        by_ders = await conn.fetch(
            "SELECT ders, COUNT(*) as cnt FROM rag_content GROUP BY ders ORDER BY cnt DESC")
        by_turu = await conn.fetch(
            "SELECT sinav_turu, COUNT(*) as cnt FROM rag_content GROUP BY sinav_turu ORDER BY cnt DESC")
        return {
            "toplam": total,
            "ders_dagilimi": {r["ders"]: r["cnt"] for r in by_ders},
            "sinav_turu": {r["sinav_turu"]: r["cnt"] for r in by_turu},
        }


# ── CLI Test ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    async def main():
        # Tablo oluştur
        await init_db()

        # Test embedding
        vec = embed_text("Newton'un ikinci yasası F=ma")
        print(f"Embedding: {len(vec)} boyut, ilk 3: {[round(x,4) for x in vec[:3]]}")

        # Test ekleme
        test_id = await add_content(
            sinav_turu="TYT", ders="Fizik",
            konu="Kuvvet ve Hareket", alt_konu="Newton Yasaları",
            icerik_turu="konu_anlatimi",
            baslik="Newton'un Hareket Yasaları",
            icerik=(
                "Newton'un üç hareket yasası mekaniğin temelini oluşturur.\n\n"
                "*1. Yasa (Eylemsizlik):* Bir cisme net kuvvet uygulanmazsa, "
                "cisim duruyorsa durur, hareket ediyorsa sabit hızla hareket eder.\n\n"
                "*2. Yasa (F=ma):* Bir cisme uygulanan net kuvvet, cismin kütlesi "
                "ile ivmesinin çarpımına eşittir. F = m × a\n\n"
                "*3. Yasa (Etki-Tepki):* Her etkiye eşit ve zıt yönde bir tepki vardır.\n\n"
                "📌 *TYT'de çıkma sıklığı:* Yüksek — hemen her denemede 1-2 soru\n"
                "📝 *Soru tipi:* Kuvvet hesaplama, ivme bulma, serbest cisim diyagramı\n"
                "🎯 *Çalışma yöntemi:* Önce kavramı anla, sonra 20 soru çöz"
            ),
            kaynak="LLM üretim", zorluk="orta", soru_sayisi=2
        )
        print(f"Eklendi: id={test_id}")

        # Test arama
        results = await search_curriculum("kuvvet nedir fizik")
        for r in results:
            print(f"  [{r['skor']:.3f}] {r['ders']}/{r['konu']} — {r['baslik']}")

        # İstatistik
        stats = await get_stats()
        print(f"RAG: {stats['toplam']} kayıt")

    asyncio.run(main())
