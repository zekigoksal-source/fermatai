"""
Long-Term Memory Profili (23 Nisan Neo vizyonu)
=================================================
"Öğrenci 'beni tanıyor' hissini yaşasın"

Kalıcı kimlik profili — her Claude çağrısında baseline olarak inject.
conversation_memory kısa vade (14 gün), bu modül UZUN vade (sezon boyu).

Her öğrenci için sentetik bir profil:
  - Akademik kimlik (güçlü/zayıf alanlar, net trend)
  - Davranışsal sinyal (sabah/gece tipi, uzun/kısa sohbet sever mi)
  - Duygusal desen (stres eğilimli, motivasyon düşüşü sık mı)
  - İlgi alanları (hangi konu sormaya sık geliyor)
  - Hedef (bölüm, puan)
"""
from __future__ import annotations
from loguru import logger
from typing import Optional


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS fermat.student_profile_v2 (
    soz_no INTEGER PRIMARY KEY,
    full_name TEXT,
    guclu_dersler TEXT[],
    zayif_dersler TEXT[],
    net_trend TEXT,
    hedef_bolum TEXT,
    hedef_puan INT,
    davranissal_pattern TEXT,
    sik_sorulan_konular TEXT[],
    duygusal_desen TEXT,
    son_guncellenme TIMESTAMP DEFAULT NOW(),
    ozet TEXT
);
"""


async def ensure_schema():
    try:
        from db_pool import db_execute
        await db_execute(CREATE_TABLE_SQL)
    except Exception as e:
        logger.debug(f"profile_v2 schema: {e}")


async def build_profile(soz_no: int) -> dict:
    """Öğrenci için profil üret (veriden sentez)."""
    try:
        from db_pool import db_fetchrow, db_fetch
        # İsim + sınıf (hedef kolonu bazen yok — COALESCE)
        try:
            s = await db_fetchrow("SELECT full_name, class_name, COALESCE(hedef,'') as hedef FROM students WHERE soz_no::text=$1", str(soz_no))
        except Exception:
            s = await db_fetchrow("SELECT full_name, class_name FROM students WHERE soz_no::text=$1", str(soz_no))
        if not s:
            return {}
        # Son 5 deneme
        exams = await db_fetch(
            "SELECT toplam, turkce, matematik, fizik, kimya, biyoloji FROM student_exams "
            "WHERE soz_no=$1 AND status='valid' ORDER BY exam_date DESC LIMIT 5", soz_no
        )
        # Zayıf/güçlü konular — sinav_hata_yuzdesi = HATA % (yuksek=zayif, dusuk=guclu)
        weak = await db_fetch(
            "SELECT ders FROM student_topic_tracker WHERE soz_no=$1 "
            "AND COALESCE(status,'') != 'metadata' AND sinav_hata_yuzdesi >= 50 "
            "GROUP BY ders ORDER BY COUNT(*) DESC LIMIT 3", soz_no
        )
        strong = await db_fetch(
            "SELECT ders FROM student_topic_tracker WHERE soz_no=$1 "
            "AND COALESCE(status,'') != 'metadata' AND sinav_hata_yuzdesi <= 25 "
            "GROUP BY ders ORDER BY COUNT(*) DESC LIMIT 3", soz_no
        )
        # Konuşma sıklığı (conversation_memory)
        konu_rows = await db_fetch(
            "SELECT content FROM agent_conversations WHERE phone = "
            "(SELECT phone FROM students WHERE soz_no::text=$1) AND message_role='user' "
            "AND created_at > NOW() - INTERVAL '30 days' LIMIT 40", str(soz_no)
        )
        # Trend (artış/düşüş)
        trend_txt = "stabil"
        if len(exams) >= 2:
            first = exams[-1]["toplam"] or 0
            last = exams[0]["toplam"] or 0
            if last - first >= 5:
                trend_txt = "yukselis"
            elif last - first <= -5:
                trend_txt = "dusus"
        # Duygusal desen (insight_type count)
        insights = await db_fetch(
            "SELECT insight_type, COUNT(*) as c FROM student_insights WHERE soz_no=$1 "
            "AND created_at > NOW() - INTERVAL '30 days' GROUP BY insight_type", soz_no
        )
        duygusal = []
        for i in insights:
            if i["c"] >= 3:
                duygusal.append(i["insight_type"])

        profile = {
            "soz_no": soz_no,
            "full_name": s["full_name"],
            "class_name": s.get("class_name"),
            "guclu_dersler": [r["ders"] for r in strong],
            "zayif_dersler": [r["ders"] for r in weak],
            "net_trend": trend_txt,
            "hedef_bolum": (s.get("hedef") or "").strip() if s.get("hedef") else None,
            "duygusal_desen": ",".join(duygusal) if duygusal else "normal",
            "sohbet_aktiflik": len(konu_rows),
        }
        # Ozet uret (Claude prompt icin)
        ozet_parts = []
        if profile["guclu_dersler"]:
            ozet_parts.append(f"güçlü: {','.join(profile['guclu_dersler'])}")
        if profile["zayif_dersler"]:
            ozet_parts.append(f"zayıf: {','.join(profile['zayif_dersler'])}")
        ozet_parts.append(f"trend: {trend_txt}")
        if duygusal:
            ozet_parts.append(f"sinyal: {','.join(duygusal)}")
        if profile["hedef_bolum"]:
            ozet_parts.append(f"hedef: {profile['hedef_bolum']}")
        profile["ozet"] = " | ".join(ozet_parts)

        # UPSERT
        try:
            from db_pool import db_execute
            await db_execute(
                """
                INSERT INTO fermat.student_profile_v2
                (soz_no, full_name, guclu_dersler, zayif_dersler, net_trend,
                 hedef_bolum, duygusal_desen, ozet, son_guncellenme)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,NOW())
                ON CONFLICT (soz_no) DO UPDATE SET
                  guclu_dersler = EXCLUDED.guclu_dersler,
                  zayif_dersler = EXCLUDED.zayif_dersler,
                  net_trend = EXCLUDED.net_trend,
                  hedef_bolum = COALESCE(EXCLUDED.hedef_bolum, fermat.student_profile_v2.hedef_bolum),
                  duygusal_desen = EXCLUDED.duygusal_desen,
                  ozet = EXCLUDED.ozet,
                  son_guncellenme = NOW()
                """,
                soz_no, profile["full_name"], profile["guclu_dersler"],
                profile["zayif_dersler"], trend_txt,
                profile["hedef_bolum"], profile["duygusal_desen"], profile["ozet"]
            )
        except Exception as _ue:
            logger.debug(f"profile upsert: {_ue}")

        return profile
    except Exception as e:
        logger.debug(f"build_profile hata: {e}")
        return {}


async def get_profile_prompt(soz_no: int) -> str:
    """Claude system prompt'a inject edilecek özet."""
    try:
        from db_pool import db_fetchrow
        row = await db_fetchrow(
            "SELECT ozet, son_guncellenme FROM fermat.student_profile_v2 WHERE soz_no=$1", soz_no
        )
        if row and row["ozet"]:
            return f"\n\n🧬 *ÖĞRENCİ KALICI PROFİLİ:* {row['ozet']}\n_(Bu baseline baglam — cevabinda zorla gosterme, ton ayarla.)_"
        # Profil yoksa üret
        p = await build_profile(soz_no)
        return f"\n\n🧬 *ÖĞRENCİ KALICI PROFİLİ:* {p.get('ozet','bilinmiyor')}" if p else ""
    except Exception:
        return ""


async def refresh_all_profiles():
    """Tüm aktif öğrencilerin profilini yenile (nightly scheduler)."""
    try:
        from db_pool import db_fetch
        rows = await db_fetch(
            "SELECT soz_no FROM students WHERE status='active' AND soz_no IS NOT NULL"
        )
        count = 0
        for r in rows:
            try:
                await build_profile(int(r["soz_no"]))
                count += 1
            except Exception:
                pass
        logger.info(f"📊 student_profile_v2 refresh: {count} profil güncellendi")
        return count
    except Exception as e:
        logger.warning(f"refresh_all_profiles: {e}")
        return 0


if __name__ == "__main__":
    import asyncio, sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    async def t():
        await ensure_schema()
        # Enes (214) için
        p = await build_profile(214)
        print("Enes profili:", p.get("ozet"))
        prompt = await get_profile_prompt(214)
        print("Prompt inject:", prompt)

    asyncio.run(t())
