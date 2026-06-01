"""
exam_xray.py — Deneme Röntgeni (Oturum 25.52, Neo dikey-AI #2)
==============================================================
Bir öğrencinin SON denemesini öncekiyle kıyaslayıp kişisel "röntgen" üretir:
hangi derste kaç net kazandı/kaybetti, en büyük sıçrama/düşüş, zayıf konularla
çapraz referans. Genel chatbot bunu yapamaz (longitudinal geçmişi yok).

⚠️ OUTREACH YOK: Bu modül SADECE on-demand (öğrenci "son denememi analiz et" /
admin sorgusu) çalışır. Yeni deneme gelince OTOMATIK GÖNDERIM yapmaz. Sezonsal
auto-push isteniyorsa EXAM_XRAY_PUSH_ACTIVE flag'i (default OFF) + send_wa_message
_outreach guard'ı üzerinden — bu modül onu ÇAĞIRMAZ, sadece analizi üretir.
YKS'ye 20 gün kala (Neo direktif): hiçbir öğrenciye otomatik mesaj GİTMEZ.

Kullanım:
  from exam_xray import analyze_latest_exam, format_exam_xray
  data = await analyze_latest_exam(soz_no)
  msg = format_exam_xray(data, name)

Claude tool: get_exam_xray(soz_no) — "son denememi analiz et", "ne kaybettim".
"""
from __future__ import annotations

from loguru import logger

_DERS = [
    ("turkce", "Türkçe"), ("matematik", "Matematik"), ("geometri", "Geometri"),
    ("fizik", "Fizik"), ("kimya", "Kimya"), ("biyoloji", "Biyoloji"),
    ("tarih", "Tarih"), ("cografya", "Coğrafya"), ("felsefe", "Felsefe"),
    ("din_kulturu", "Din Kültürü"),
]


async def analyze_latest_exam(soz_no: int) -> dict:
    """Son deneme vs önceki — ders bazlı delta + en iyi/kötü + zayıf konu çapraz ref."""
    from db_pool import db_fetch
    soz_no = int(soz_no)

    cols = ", ".join(d[0] for d in _DERS)
    rows = await db_fetch(
        f"""SELECT exam_name, exam_date, toplam, {cols}
            FROM student_exams
            WHERE soz_no = $1 AND exam_date IS NOT NULL
            ORDER BY exam_date DESC""",
        soz_no)
    if not rows:
        return {"has_data": False, "soz_no": soz_no}

    # Aynı tarih duplikasyonunu temizle (en güncel önce sıralı)
    seen, clean = set(), []
    for r in rows:
        if r["exam_date"] in seen:
            continue
        seen.add(r["exam_date"])
        clean.append(r)

    if len(clean) < 1:
        return {"has_data": False, "soz_no": soz_no}

    son = clean[0]
    onceki = clean[1] if len(clean) > 1 else None

    ders_delta = []
    for key, label in _DERS:
        s = son.get(key)
        if s is None:
            continue
        s = float(s)
        o = float(onceki[key]) if (onceki and onceki.get(key) is not None) else None
        delta = round(s - o, 2) if o is not None else None
        ders_delta.append({"ders": label, "key": key, "son": round(s, 2),
                           "onceki": round(o, 2) if o is not None else None,
                           "delta": delta})

    # En iyi / en kötü değişim (delta olanlardan)
    with_delta = [d for d in ders_delta if d["delta"] is not None and abs(d["delta"]) >= 0.5]
    en_iyi = max(with_delta, key=lambda x: x["delta"], default=None)
    en_kotu = min(with_delta, key=lambda x: x["delta"], default=None)
    toplam_delta = None
    if onceki and son.get("toplam") is not None and onceki.get("toplam") is not None:
        toplam_delta = round(float(son["toplam"]) - float(onceki["toplam"]), 2)

    # Düşen derslerde zayıf konu çapraz referansı (topic_tracker)
    dusus_dersleri = [d["ders"] for d in with_delta if d["delta"] < 0]
    zayif_eslesme = []
    if dusus_dersleri:
        try:
            zt = await db_fetch(
                """SELECT ders, konu, sinav_basari_yuzdesi
                   FROM student_topic_tracker
                   WHERE soz_no = $1 AND ders = ANY($2::text[])
                     AND COALESCE(status,'') != 'metadata'
                     AND konu NOT LIKE 'Ortalama %'
                   ORDER BY sinav_basari_yuzdesi ASC NULLS LAST LIMIT 5""",
                soz_no, dusus_dersleri)
            zayif_eslesme = [{"ders": r["ders"], "konu": r["konu"],
                              "basari": round(float(r["sinav_basari_yuzdesi"]), 1)
                              if r["sinav_basari_yuzdesi"] is not None else None}
                             for r in zt]
        except Exception as e:
            logger.debug(f"[exam_xray] zayif eslesme hatasi: {e}")

    return {
        "has_data": True, "soz_no": soz_no,
        "son_deneme": {"isim": son["exam_name"], "tarih": str(son["exam_date"]),
                       "toplam": round(float(son["toplam"]), 2) if son.get("toplam") is not None else None},
        "onceki_deneme": ({"isim": onceki["exam_name"], "tarih": str(onceki["exam_date"]),
                           "toplam": round(float(onceki["toplam"]), 2) if onceki.get("toplam") is not None else None}
                          if onceki else None),
        "toplam_delta": toplam_delta,
        "ders_delta": ders_delta,
        "en_iyi": en_iyi, "en_kotu": en_kotu,
        "zayif_konu_eslesme": zayif_eslesme,
        "deneme_sayisi": len(clean),
    }


def format_exam_xray(data: dict, name: str = "") -> str:
    first = (name.split()[0] if name else "") or "öğrenci"
    if not data or not data.get("has_data"):
        return (f"📊 *{first}* için henüz deneme verisi yok.\n\n"
                "Denemelere katıldıkça otomatik analiz oluşacak. 🎯")
    son = data["son_deneme"]
    lines = [f"🩻 *{first} — Deneme Röntgeni*", ""]
    lines.append(f"📝 *{son['isim']}* _{son['tarih']}_")
    if son.get("toplam") is not None:
        td = data.get("toplam_delta")
        trend = ""
        if td is not None:
            trend = f"  ({'📈 +' if td > 0 else '📉 '}{td} net)" if td != 0 else " (➡️ aynı)"
        lines.append(f"   Toplam: *{son['toplam']}* net{trend}")
    lines.append("")

    if not data.get("onceki_deneme"):
        lines.append("_İlk denemen — kıyas için bir sonrakini bekliyoruz._ 🎯")
        return "\n".join(lines)

    # Ders bazlı değişim
    lines.append("*📚 Ders Bazlı Değişim*")
    for d in data["ders_delta"]:
        if d["delta"] is None:
            continue
        if d["delta"] >= 0.5:
            ok = f"📈 +{d['delta']}"
        elif d["delta"] <= -0.5:
            ok = f"📉 {d['delta']}"
        else:
            ok = "➡️ ~"
        lines.append(f"  {d['ders']}: {d['son']} net  {ok}")
    lines.append("")

    if data.get("en_iyi") and data["en_iyi"]["delta"] > 0:
        e = data["en_iyi"]
        lines.append(f"🌟 *En büyük sıçrama:* {e['ders']} (+{e['delta']} net)")
    if data.get("en_kotu") and data["en_kotu"]["delta"] < 0:
        e = data["en_kotu"]
        lines.append(f"⚠️ *En çok gerileme:* {e['ders']} ({e['delta']} net)")

    # Düşüşle ilişkili zayıf konular
    if data.get("zayif_konu_eslesme"):
        lines.append("\n*🎯 İlgili Çalışılacak Konular*")
        for z in data["zayif_konu_eslesme"][:4]:
            b = f" (%{z['basari']})" if z.get("basari") is not None else ""
            lines.append(f"  • {z['ders']} — {z['konu'][:34]}{b}")

    lines.append("\n_Her denemenle bu röntgen güncellenir — net kazanım odaklı._")
    return "\n".join(lines)


if __name__ == "__main__":
    import asyncio
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    async def _main():
        for soz in (sys.argv[1:] or ["167"]):
            print(f"\n{'='*60}\nSoz: {soz}\n{'='*60}")
            d = await analyze_latest_exam(int(soz))
            print(format_exam_xray(d, ""))

    asyncio.run(_main())
