"""25.57-E — Pedagojik boş/yanlış ayrımı (Neo direktif).

Neo: "öğrenci denemediyse bu HATA değil ama DOĞRU da yapmamış — pedagojik anlamlı girdi.
Boş bırakılan soruları yorumlama kabiliyeti kaybolmasın, raporlamada pedagojik doğru kullan."

student_topic_tracker'a yanlis/bos adetlerini AYRI ekler (oncelikli_konular'dan). Böylece
reporting 'hata yapıyor' (kavram eksiği) vs 'boş bırakıyor' (zaman/çekingenlik/işlenmemiş)
ayrımını yapabilir. sinav_hata_yuzdesi (=geliştirme alanı %, yanlis+bos) DEĞİŞMEZ — selection
aynı; sadece YORUM zenginleşir.

Kullanım: python populate_topic_breakdown.py
"""
import asyncio
import json
import sys
sys.path.insert(0, "/opt/fermatai/eyotek_agent")
from dotenv import load_dotenv
load_dotenv("/opt/fermatai/.env", override=True)


def _parse(oncelikli):
    if not oncelikli:
        return []
    ok = oncelikli
    if isinstance(ok, str):
        try:
            ok = json.loads(ok)
        except Exception:
            return []
    out = []
    for lvl in (ok if isinstance(ok, list) else [ok]):
        if not isinstance(lvl, dict):
            continue
        for k in lvl.get("konular", []):
            if not isinstance(k, dict):
                continue
            kr = k.get("konu", "")
            if not kr or ":" not in kr:
                continue
            konu = kr.split(":", 1)[1].strip()
            try:
                yanlis = int(k.get("yanlis", 0) or 0)
                bos = int(k.get("bos", 0) or 0)
                soru = int(k.get("soru", 0) or 0)
            except (ValueError, TypeError):
                continue
            if soru <= 0:
                continue
            out.append((konu, yanlis, bos))
    return out


async def main():
    from db_pool import db_execute, db_fetch
    # 1) Kolonları ekle (idempotent)
    await db_execute("ALTER TABLE student_topic_tracker ADD COLUMN IF NOT EXISTS sinav_yanlis_sayisi INTEGER")
    await db_execute("ALTER TABLE student_topic_tracker ADD COLUMN IF NOT EXISTS sinav_bos_sayisi INTEGER")
    print("✅ Kolonlar hazır: sinav_yanlis_sayisi, sinav_bos_sayisi")

    rows = await db_fetch("""SELECT soz_no, oncelikli_konular, oncelikli_konular_ayt
                             FROM student_exam_analysis
                             WHERE oncelikli_konular IS NOT NULL OR oncelikli_konular_ayt IS NOT NULL""")
    updated = 0
    for r in rows:
        try:
            soz = int(r["soz_no"])
        except (ValueError, TypeError):
            continue
        topics = _parse(r["oncelikli_konular"]) + _parse(r["oncelikli_konular_ayt"])
        for konu, yanlis, bos in topics:
            n = await db_execute("""UPDATE student_topic_tracker
                SET sinav_yanlis_sayisi=$1, sinav_bos_sayisi=$2
                WHERE soz_no=$3 AND konu=$4 AND konu NOT ILIKE 'Ortalama%' AND konu NOT ILIKE 'AYT Ort%'""",
                yanlis, bos, soz, konu)
            updated += 1
    print(f"✅ {updated} subtopic satırı yanlis/bos breakdown ile güncellendi.")

    # Doğrulama: Ali (167)
    print("\nALI (167) örnek — tip sınıflama:")
    av = await db_fetch("""SELECT konu, sinav_yanlis_sayisi y, sinav_bos_sayisi b, sinav_hata_yuzdesi h
        FROM student_topic_tracker WHERE soz_no=167 AND sinav_yanlis_sayisi IS NOT NULL
        ORDER BY sinav_hata_yuzdesi DESC LIMIT 6""")
    for x in av:
        y, b = x['y'] or 0, x['b'] or 0
        tot = y + b
        if tot == 0:
            tip = "veri-yok"
        elif b / tot >= 0.7:
            tip = "BOŞ bırakıyor"
        elif b / tot <= 0.3:
            tip = "HATA yapıyor"
        else:
            tip = "karma"
        print(f"  {x['konu'][:28]:30} yanlis={y} bos={b} hata%={round(float(x['h']),0)} → {tip}")


if __name__ == "__main__":
    asyncio.run(main())
