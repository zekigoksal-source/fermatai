"""
FermatAI — Foto Soru Cozum v2 (Hafta 5)
========================================
Mevcut Vision cozumune ek katmanlar:
1. Cozulen sorudan ders/konu auto-detect → student_topic_tracker'a 'calisiyor' isaretler
2. RAG'ta benzer cikmis soru var mi? Bulup link/yil oner
3. Cozulen sorunun ogrencinin zayif konusu olup olmadigini kontrol et
4. Proaktif oneri: "_Bu konu zayif alanin — etut ister misin?_"
5. Foto cozum gecmisi (foto_questions tablosu) — performans takibi
6. Dinamik limit: aktif ogrenciye daha cok foto hakki

Kullanim:
  from foto_solver_v2 import solve_photo_v2
  answer = await solve_photo_v2(image_bytes, user_prompt, soz_no, role)
"""

import asyncio
import re
import sys
from datetime import date

from loguru import logger
from db_pool import get_pool as _get_pool, db_fetch, db_fetchrow, db_fetchval, db_execute


# Ders/konu cikarma pattern'i
_DERS_PATTERN = re.compile(
    r"Ders[:\s]+(\w[\w\sıİğĞüÜşŞöÖçÇ]+?)(?:\n|Konu)", re.IGNORECASE
)
_KONU_PATTERN = re.compile(
    r"Konu[:\s]+([^\n]{3,80})", re.IGNORECASE
)


async def ensure_foto_table():
    """foto_questions tablosu yoksa olustur."""
    await db_execute("""
        CREATE TABLE IF NOT EXISTS foto_questions (
            id SERIAL PRIMARY KEY,
            soz_no TEXT,
            phone TEXT,
            ders TEXT,
            konu TEXT,
            cozum_ozet TEXT,
            zorluk TEXT,
            sik_belirtildi TEXT,  -- A/B/C/D/E
            zayif_konu_eslesti BOOLEAN DEFAULT FALSE,
            cikmis_soru_eslesti BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)


def _extract_ders_konu(answer: str) -> tuple:
    """Vision yanitindan ders/konu cikar."""
    ders = None
    konu = None

    m = _DERS_PATTERN.search(answer)
    if m:
        ders = m.group(1).strip().rstrip(':').strip()

    m = _KONU_PATTERN.search(answer)
    if m:
        konu = m.group(1).strip().rstrip(':').strip()

    # Zorluk
    zorluk = None
    if 'Zorluk' in answer:
        m = re.search(r'Zorluk[:\s]+(\w+)', answer)
        if m:
            zorluk = m.group(1).strip()

    # Cevap sikki
    sik = None
    m = re.search(r'(?:Dogru\s*Cevap|Cevap)[:\s]*\*?([A-E])\*?', answer, re.IGNORECASE)
    if m:
        sik = m.group(1).upper()

    return ders, konu, zorluk, sik


async def _is_weak_topic(soz_no: str, ders: str, konu: str) -> bool:
    """Bu ders+konu ogrencinin zayif alanlarinda mi?"""
    if not soz_no or not ders:
        return False
    row = await db_fetchrow("""
        SELECT sinav_hata_yuzdesi FROM student_topic_tracker
        WHERE soz_no::text = $1 AND ders ILIKE $2
        AND (sinav_hata_yuzdesi < 50 OR sinav_hata_yuzdesi IS NULL)
        LIMIT 1
    """, str(soz_no), f"%{ders}%")
    return bool(row)


async def _find_similar_exam_question(ders: str, konu: str) -> dict | None:
    """RAG'ta cikmis soru ara."""
    if not ders:
        return None
    try:
        from rag_engine import semantic_search
        # ders + konu = sorgu
        query = f"{ders} {konu or ''} cikmis soru"
        results = await semantic_search(query, limit=3)
        # Sadece OGM Vision (cikmis soru) kaynaklarini al
        for r in results:
            kaynak = r.get('kaynak', '')
            if 'OGM Vision' in kaynak:
                return {
                    'kaynak': kaynak,
                    'ders': r.get('ders'),
                    'konu': r.get('konu'),
                    'icerik_ozet': (r.get('icerik') or '')[:200],
                }
    except Exception as e:
        logger.debug(f"RAG benzer soru hatasi: {e}")
    return None


async def _log_foto_question(soz_no: str, phone: str, ders: str, konu: str,
                              zorluk: str, sik: str, weak: bool, similar: bool):
    """Cozulen soruyu DB'ye yaz."""
    try:
        await ensure_foto_table()
        await db_execute("""
            INSERT INTO foto_questions
              (soz_no, phone, ders, konu, zorluk, sik_belirtildi,
               zayif_konu_eslesti, cikmis_soru_eslesti)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
        """, soz_no, phone, ders, konu, zorluk, sik, weak, similar)
    except Exception as e:
        logger.debug(f"foto log hatasi: {e}")


async def _mark_topic_studying(soz_no: str, ders: str, konu: str):
    """Ogrencinin bu konuda 'calisiyor' isaretle (topic tracker'a)."""
    if not soz_no or not ders or not konu:
        return
    try:
        # Var olan kayit varsa status guncelle, yoksa ekleme
        await db_execute("""
            UPDATE student_topic_tracker
            SET status = 'calisiyor'
            WHERE soz_no::text = $1
              AND ders ILIKE $2
              AND konu ILIKE $3
              AND (status IS NULL OR status = '')
        """, str(soz_no), f"%{ders}%", f"%{konu[:20]}%")
    except Exception as e:
        logger.debug(f"topic tracker update hatasi: {e}")


async def get_dynamic_photo_limit(soz_no: str, base_limit: int = 10) -> int:
    """Aktif ogrenciye ek foto hakki ver. (Neo direktif 9 May: base 3→10, aktif +3 → 13)"""
    if not soz_no:
        return base_limit
    try:
        # Son 7 gunde sinav verisi varsa +3 (aktif ogrenci bonus)
        cnt = await db_fetchval("""
            SELECT COUNT(*) FROM student_exams
            WHERE soz_no::text = $1
            AND exam_date >= CURRENT_DATE - INTERVAL '7 days'
        """, str(soz_no))
        if cnt and cnt > 0:
            return base_limit + 3  # 10 → 13
    except Exception:
        pass
    return base_limit


def _build_v2_extras(ders: str, konu: str, weak: bool, similar: dict | None,
                     soz_no: str) -> str:
    """v2 ek bilgiler: zayif konu uyarisi + cikmis soru + proaktif oneri."""
    extras = []

    if weak and ders and konu:
        extras.append(
            f"\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ *Bu Konu Senin Zayif Alanin*\n"
            f"_{ders} - {konu[:40]}_ daha once denemelerde dusuk net aldigin bir konu.\n"
            f"💡 Bu konuda 1-2 etut almak ister misin? \"etut iste\" yazabilirsin."
        )

    if similar:
        extras.append(
            f"\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📚 *Bu konudan benzer cikmis soru var*\n"
            f"_{similar['kaynak']}_\n"
            f"\"{similar['ders']} cikmis sorular\" yazarak diger sorulari gor."
        )

    if extras:
        return "\n".join(extras)
    return ""


async def solve_photo_v2(image_bytes: bytes, user_prompt: str = "",
                         soz_no: str = None, phone: str = None,
                         role: str = "ogrenci") -> str:
    """
    v2 foto cozum: MathPix OCR (preflight) + Vision + post-processing katmanlari.

    Oturum 25.38: MathPix Snip API entegre edildi.
    - Matematik soruda MathPix daha doğru OCR yapar (~%95 vs Vision ~%75)
    - MathPix sonucu Claude'a context olarak veriliyor (zenginleştirme, yedekleme değil)
    - Claude hala görüntüye bakarak pedagojik çözüm üretiyor
    """
    # 0. MathPix preflight (varsa) — paralel başlat, Vision ile birlikte çalışsın
    mathpix_task = None
    try:
        from mathpix_client import is_available as mp_available, ocr_image, format_for_claude
        if mp_available():
            mathpix_task = asyncio.create_task(ocr_image(image_bytes))
    except ImportError:
        pass

    # 1. Mevcut Vision cozumunu kullan (paralel olarak MathPix bekler)
    from whatsapp_bridge import _solve_photo_question

    # Eğer MathPix sonucu varsa user_prompt'a context olarak ekle
    enhanced_prompt = user_prompt
    if mathpix_task:
        try:
            mp_result = await asyncio.wait_for(mathpix_task, timeout=8.0)
            if mp_result.get("success") and mp_result.get("confidence", 0) > 0.5:
                mp_context = format_for_claude(mp_result)
                if mp_context:
                    enhanced_prompt = (mp_context + "\n\n" + (user_prompt or "")).strip()
                    logger.info(f"📐 MathPix OCR ekendi: confidence={mp_result.get('confidence'):.0%}, "
                                f"is_math={mp_result.get('is_math')}, len={len(mp_result.get('text',''))}")
        except asyncio.TimeoutError:
            logger.debug("MathPix timeout (>8sn), Vision tek başına devam ediyor")
        except Exception as e:
            logger.debug(f"MathPix preflight hata: {e}")

    answer = await _solve_photo_question(image_bytes, enhanced_prompt)

    if not answer or "Foto analizi icin" in answer:
        return answer

    # 2. Ders/konu/zorluk/sik cikar
    ders, konu, zorluk, sik = _extract_ders_konu(answer)
    logger.info(f"📷 Foto v2: ders={ders}, konu={konu}, zorluk={zorluk}, sik={sik}")

    # 3. Paralel post-processing
    weak = False
    similar = None
    if soz_no and ders:
        try:
            weak, similar = await asyncio.gather(
                _is_weak_topic(soz_no, ders, konu),
                _find_similar_exam_question(ders, konu),
            )
        except Exception as e:
            logger.debug(f"v2 post-process error: {e}")

    # 4. Loglama (background — beklemiyoruz)
    asyncio.create_task(_log_foto_question(
        soz_no, phone, ders, konu, zorluk, sik, weak, bool(similar)
    ))

    # 5. Topic tracker guncelle (background)
    if soz_no and ders and konu:
        asyncio.create_task(_mark_topic_studying(soz_no, ders, konu))

    # 6. v2 ek bilgileri ekle
    extras = _build_v2_extras(ders, konu, weak, similar, soz_no)
    return answer + extras


async def get_foto_stats(soz_no: str = None, days: int = 30) -> dict:
    """Foto cozum istatistikleri."""
    await ensure_foto_table()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        where = "WHERE created_at >= NOW() - INTERVAL '%d days'" % days
        if soz_no:
            where += f" AND soz_no::text = '{soz_no}'"

        stats = await conn.fetchrow(f"""
            SELECT
                COUNT(*) as toplam,
                COUNT(DISTINCT soz_no) as ogrenci_sayisi,
                COUNT(*) FILTER (WHERE zayif_konu_eslesti = TRUE) as zayif_konu_eslesti,
                COUNT(*) FILTER (WHERE cikmis_soru_eslesti = TRUE) as cikmis_eslesti
            FROM foto_questions {where}
        """)

        by_ders = await conn.fetch(f"""
            SELECT ders, COUNT(*) as cnt
            FROM foto_questions {where}
            AND ders IS NOT NULL
            GROUP BY ders
            ORDER BY cnt DESC LIMIT 8
        """)

        return {
            'toplam': stats['toplam'],
            'ogrenci_sayisi': stats['ogrenci_sayisi'],
            'zayif_konu_eslesti': stats['zayif_konu_eslesti'],
            'cikmis_eslesti': stats['cikmis_eslesti'],
            'ders_dagilim': [dict(r) for r in by_ders],
        }


def format_foto_stats(stats: dict, soz_no: str = None) -> str:
    """WhatsApp formatli foto istatistik."""
    lines = ["📷 *FOTO COZUM ISTATISTIKLERI*\n"]
    if soz_no:
        lines.append(f"_Ogrenci: {soz_no} (son 30 gun)_\n")
    else:
        lines.append("_Kurum geneli (son 30 gun)_\n")

    lines.append(f"📊 Toplam cozulen soru: *{stats['toplam']}*")
    if not soz_no:
        lines.append(f"👥 Aktif ogrenci: *{stats['ogrenci_sayisi']}*")
    lines.append(f"⚠️ Zayif konu eslesti: *{stats['zayif_konu_eslesti']}*")
    lines.append(f"📚 Cikmis soru eslesti: *{stats['cikmis_eslesti']}*")
    lines.append("")

    if stats['ders_dagilim']:
        lines.append("*Ders Dagilimi:*")
        for d in stats['ders_dagilim']:
            lines.append(f"  • {d['ders']}: {d['cnt']}")

    return "\n".join(lines)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    async def main():
        if len(sys.argv) > 1 and sys.argv[1] == "stats":
            soz = sys.argv[2] if len(sys.argv) > 2 else None
            s = await get_foto_stats(soz)
            print(format_foto_stats(s, soz))
        else:
            await ensure_foto_table()
            print("✅ foto_questions tablosu hazir")
    asyncio.run(main())
