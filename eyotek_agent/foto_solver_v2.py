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
    """Bu ders+konu ogrencinin zayif alanlarinda mi?

    INVERSION FIX (Berf bug 10 May): sinav_hata_yuzdesi = HATA %.
    Zayif = YUKSEK hata. Eski kod `< 50` ile basariliyi 'zayif' sayiyordu.
    """
    if not soz_no or not ders:
        return False
    row = await db_fetchrow("""
        SELECT sinav_hata_yuzdesi FROM student_topic_tracker
        WHERE soz_no::text = $1 AND ders ILIKE $2
        AND COALESCE(status,'') != 'metadata'
        AND sinav_hata_yuzdesi >= 50
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


async def get_dynamic_photo_limit(soz_no: str, base_limit: int = 5) -> int:
    """Aktif ogrenciye ek foto hakki ver. (Neo direktif 9 May: base 5, aktif +2 → 7)"""
    if not soz_no:
        return base_limit
    try:
        # Son 7 gunde sinav verisi varsa +2 (aktif ogrenci bonus)
        cnt = await db_fetchval("""
            SELECT COUNT(*) FROM student_exams
            WHERE soz_no::text = $1
            AND exam_date >= CURRENT_DATE - INTERVAL '7 days'
        """, str(soz_no))
        if cnt and cnt > 0:
            return base_limit + 2  # 5 → 7
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


_DIAGNOSE_RE = re.compile(
    r"(nerede.*(hata|yanl[ıi]ş)|hata(m[ıi]?|m\b).*(bul|nerede|var\s*m)|"
    r"yanl[ıi]ş[ıi]?m|çöz[üu]m[üu]m[üu]?|cozumum[uu]?|"
    r"doğru\s*mu|dogru\s*mu|yanl[ıi]ş\s*m[ıi]|kontrol\s*et|"
    r"yapt[ıi]ğ[ıi]m.*(doğru|yanl[ıi]ş|hata)|nerede\s*yanl[ıi]ş)",
    re.IGNORECASE)


def _is_diagnosis_request(user_prompt: str) -> bool:
    """25.54: caption öğrencinin KENDİ çözümünü teşhis isteği mi? ('nerede hata yaptım',
    'çözümümü kontrol et', 'doğru mu')."""
    if not user_prompt:
        return False
    return bool(_DIAGNOSE_RE.search(user_prompt))


async def _log_error_diagnosis(soz_no: str, ders: str, konu: str, hata_turu: str):
    """25.54: hata teşhisini student_insights'a yaz — longitudinal hata paterni.
    SALT KAYIT (outreach yok). rehber/öğretmen ileride paterni görebilir."""
    if not soz_no:
        return
    try:
        await db_execute(
            """INSERT INTO student_insights
               (soz_no, insight_type, content, source, confidence, created_at)
               VALUES ($1, 'hata_teshisi', $2, 'foto_diagnosis', 0.8, NOW())""",
            int(soz_no),
            f"{ders or '?'} / {konu or '?'} — hata türü: {hata_turu or 'belirtilmedi'}")
    except Exception as e:
        logger.debug(f"[foto_diagnosis] insight log hatası: {e}")


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
                    # 25.54 DeepSeek: matematik metni temizse kanonik çözümü üret →
                    # Claude'a CONTEXT olarak ver (KVKK: sadece anonim soru metni).
                    # Key yoksa is_available()=False → atlanır, mevcut akış korunur.
                    try:
                        from deepseek_handler import is_available as _ds_ok, solve_math as _ds_solve
                        if _ds_ok() and mp_result.get("is_math"):
                            _ds_sol = await _ds_solve(mp_result.get("text", ""))
                            if _ds_sol:
                                enhanced_prompt += (
                                    "\n\n[REFERANS ÇÖZÜM — DeepSeek matematik motoru, "
                                    "doğrula ve pedagojik sun]:\n" + _ds_sol[:2000])
                    except Exception as _dse:
                        logger.debug(f"DeepSeek foto entegrasyon atlandı: {_dse}")
        except asyncio.TimeoutError:
            logger.debug("MathPix timeout (>8sn), Vision tek başına devam ediyor")
        except Exception as e:
            logger.debug(f"MathPix preflight hata: {e}")

    # 25.54 HATA TEŞHİSİ: caption "nerede hata yaptım / çözümümü kontrol et" ise
    # öğrencinin KENDİ çözümünü teşhis et (soruyu çözme).
    _mode = "diagnose" if _is_diagnosis_request(user_prompt) else "solve"
    answer = await _solve_photo_question(image_bytes, enhanced_prompt, mode=_mode)

    if not answer or "Foto analizi icin" in answer:
        return answer

    # 2. Ders/konu/zorluk/sik cikar
    ders, konu, zorluk, sik = _extract_ders_konu(answer)
    logger.info(f"📷 Foto v2 [{_mode}]: ders={ders}, konu={konu}, zorluk={zorluk}, sik={sik}")

    # 25.54: diagnosis ise hata türünü çıkar + longitudinal patern'e yaz (salt kayıt)
    if _mode == "diagnose":
        _ht = None
        _m = re.search(r"Hata\s*t[üu]r[üu][:\s]+([^\n]{2,30})", answer, re.IGNORECASE)
        if _m:
            _ht = _m.group(1).strip()
        asyncio.create_task(_log_error_diagnosis(soz_no, ders, konu, _ht))

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

        # Aktif gun sayisi ve gunluk ortalama
        gunluk_data = await conn.fetch(f"""
            SELECT DATE(created_at) as gun, COUNT(*) as cnt
            FROM foto_questions {where}
            GROUP BY DATE(created_at)
            ORDER BY gun DESC
        """)
        aktif_gun = len(gunluk_data)
        gunluk_ort = round(stats['toplam'] / max(aktif_gun, 1), 1) if aktif_gun else 0

        return {
            'toplam': stats['toplam'],
            'ogrenci_sayisi': stats['ogrenci_sayisi'],
            'zayif_konu_eslesti': stats['zayif_konu_eslesti'],
            'cikmis_eslesti': stats['cikmis_eslesti'],
            'ders_dagilim': [dict(r) for r in by_ders],
            'aktif_gun': aktif_gun,
            'gunluk_ort': gunluk_ort,
            'donem_gun': days,
        }


def format_foto_stats(stats: dict, soz_no: str = None) -> str:
    """WhatsApp formatli foto istatistik — gercek vs. teorik AYRI gosterilir."""
    donem = stats.get("donem_gun", 30)
    lines = ["📷 *FOTO SORU COZUM — Gercek Kullanim (son %d gun)*" % donem, ""]
    if soz_no:
        lines.append("_Ogrenci: %s_" % soz_no)
        lines.append("")
    else:
        lines.append("_Kurum geneli_")
        lines.append("")

    lines.append("*📊 Gercek Kullanim (DB veritabani — kesin rakamlar):*")
    lines.append("  Toplam cozulen: *%d* soru" % stats["toplam"])
    if not soz_no:
        lines.append("  Aktif ogrenci: *%d* kisi" % stats["ogrenci_sayisi"])
    aktif = stats.get("aktif_gun", 0)
    ort = stats.get("gunluk_ort", 0)
    lines.append("  Aktif gun: *%d* gun / %d gunluk donem" % (aktif, donem))
    lines.append("  Gunluk ortalama: *%.1f* foto/gun  ← GERCEK VERI (veritabanindan)" % ort)
    lines.append("  Zayif konu eslesti: *%d*" % stats["zayif_konu_eslesti"])
    lines.append("  Cikmis soru eslesti: *%d*" % stats["cikmis_eslesti"])
    lines.append("")

    ogrenci = max(stats.get("ogrenci_sayisi", 1) or 1, 1)
    toplam = stats["toplam"] or 0
    max_aylik = ogrenci * 5 * 22
    kullanim_pct = round(toplam / max(max_aylik, 1) * 100, 1)
    lines.append("*⚠️ Kapasite Analizi (ASAGISI TEORIK — gercek yukarda):*")
    lines.append("  Teorik maks: %d ogr x 5foto x 22gun = *%d* foto/ay" % (ogrenci, max_aylik))
    lines.append("  Gercek kullanim: teorik maksimumun *%%%s'i*" % kullanim_pct)
    lines.append("")

    if stats["ders_dagilim"]:
        lines.append("*Ders Dagilimi:*")
        for d in stats["ders_dagilim"]:
            lines.append("  • %s: %d" % (d["ders"], d["cnt"]))

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
