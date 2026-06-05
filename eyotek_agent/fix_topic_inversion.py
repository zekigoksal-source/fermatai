"""25.57-D — student_topic_tracker subtopic hata% INVERSION fix (Neo: Ali Küçükuysal bug).

KÖK: build_topic_tracker.py oncelikli_konular'daki 'yuzde' alanını (BAŞARI oranı=
(soru-yanlis-bos)/soru) doğrudan sinav_hata_yuzdesi'ne yazmış → başarı, hata kolonunda.
Sonuç: bot güçlü konuyu zayıf sanıyor (Ali Paragraf: hata%=86 ama gerçekte %86 BAŞARI).

OTORİTER DÜZELTME: oncelikli_konular JSON'undan yeniden hesapla:
  gerçek hata% = (yanlis+bos)/soru*100 ; basari% = 100-hata ; hata_sayisi = yanlis+bos.
Subtopic satırlarını (konu LIKE 'Ortalama%' DEĞİL) güncelle. İdempotent.

Kullanım: python fix_topic_inversion.py          # DRY-RUN (sadece rapor)
          python fix_topic_inversion.py --apply  # uygula
"""
import asyncio
import json
import sys
sys.path.insert(0, "/opt/fermatai/eyotek_agent")
from dotenv import load_dotenv
load_dotenv("/opt/fermatai/.env", override=True)

APPLY = "--apply" in sys.argv


def _parse_topics(oncelikli):
    """oncelikli_konular JSON → [(ders, konu, hata_sayisi, hata_pct)]"""
    if not oncelikli:
        return []
    ok = oncelikli
    if isinstance(ok, str):
        try:
            ok = json.loads(ok)
        except Exception:
            return []
    out = []
    levels = ok if isinstance(ok, list) else [ok]
    for lvl in levels:
        if not isinstance(lvl, dict):
            continue
        for k in lvl.get("konular", []):
            if not isinstance(k, dict):
                continue
            konu_raw = k.get("konu", "")
            if not konu_raw or ":" not in konu_raw:
                continue
            ders = konu_raw.split(":", 1)[0].strip().replace("TYT_", "").replace("AYT_", "")
            konu = konu_raw.split(":", 1)[1].strip()
            try:
                yanlis = int(k.get("yanlis", 0) or 0)
                bos = int(k.get("bos", 0) or 0)
                soru = int(k.get("soru", 0) or 0)
            except (ValueError, TypeError):
                continue
            if soru <= 0:
                continue
            hata_sayisi = yanlis + bos
            hata_pct = round(hata_sayisi / soru * 100, 2)
            out.append((ders, konu, hata_sayisi, hata_pct))
    return out


async def main():
    from db_pool import db_fetch, db_execute
    rows = await db_fetch("""SELECT soz_no, oncelikli_konular, oncelikli_konular_ayt
                             FROM student_exam_analysis
                             WHERE oncelikli_konular IS NOT NULL OR oncelikli_konular_ayt IS NOT NULL""")
    print(f"{len(rows)} öğrenci exam_analysis kaydı taranıyor (APPLY={APPLY})")
    wrong = 0
    fixed = 0
    examples = []
    for r in rows:
        try:
            soz = int(r["soz_no"])
        except (ValueError, TypeError):
            continue
        topics = _parse_topics(r["oncelikli_konular"]) + _parse_topics(r["oncelikli_konular_ayt"])
        for ders, konu, hs, hata_pct in topics:
            # Mevcut topic_tracker satırı (subtopic — Ortalama değil)
            cur = await db_fetch("""SELECT id, sinav_hata_yuzdesi FROM student_topic_tracker
                                    WHERE soz_no=$1 AND konu=$2 AND konu NOT ILIKE 'Ortalama%'
                                      AND konu NOT ILIKE 'AYT Ort%'""", soz, konu)
            for c in cur:
                old = c["sinav_hata_yuzdesi"]
                if old is None or abs(float(old) - hata_pct) > 1.0:
                    wrong += 1
                    if len(examples) < 12:
                        examples.append((soz, ders, konu[:28], old, hata_pct))
                    if APPLY:
                        # sinav_basari_yuzdesi GENERATED kolon (otomatik = 100 - hata) — dokunma.
                        await db_execute("""UPDATE student_topic_tracker
                            SET sinav_hata_yuzdesi=$1, sinav_hata_sayisi=$2
                            WHERE id=$3""", hata_pct, hs, c["id"])
                        fixed += 1

    print(f"\nYANLIŞ (>1% sapma) satır: {wrong}")
    print("Örnekler (soz | ders | konu | ESKİ hata% | DOĞRU hata%):")
    for soz, ders, konu, old, new in examples:
        print(f"  {soz} | {ders:10} | {konu:30} | {old} → {new}")
    if APPLY:
        print(f"\n✅ {fixed} satır düzeltildi (sinav_hata_yuzdesi + basari + hata_sayisi).")
    else:
        print("\n(DRY-RUN — uygulamak için --apply)")


if __name__ == "__main__":
    asyncio.run(main())
