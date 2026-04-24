"""
Öğrenci Peer Benchmark (Anonim) — Oturum 22.1m
================================================

"Senin gibi 45 net hedefleyen 12 öğrenci şu konulara öncelik veriyor" —
anonim kıyaslama + motivasyon.

GÜVENLİK (Neo kuralları):
- ASLA öğrenci adı veya soz_no döndürme
- SADECE agregat sayılar + konu listesi
- Net aralığı ± tolerans (benzer grup)
- Sınıf/program eşleşmesi aynı alan (SAY vs EA vs SÖZ)

Kullanım:
    from peer_benchmark import ogrenci_peer_kiyas
    result = await ogrenci_peer_kiyas(soz_no=385)
"""
import asyncio
from typing import Optional
from loguru import logger


async def ogrenci_peer_kiyas(soz_no: int, tolerans_net: int = 10) -> dict:
    """
    Öğrencinin benzer net aralığındaki (aynı alan) peer'lerini anonim bul.

    Returns:
        {
            "ogrenci_net": float,
            "peer_sayisi": int,
            "net_araligi": [min, max],
            "peer_oncelik_konular": [{"konu", "ders", "sayi", "avg_basari"}],
            "peer_guclu_konular": [...],
            "motivasyon_mesaj": str,
        }
    """
    from db_pool import db_fetch, db_fetchrow, db_fetchval

    # Öğrenci bilgisi
    ogr = await db_fetchrow(
        """SELECT s.soz_no, s.full_name, s.class_name, s.program
           FROM students s WHERE s.soz_no = $1 AND s.status='active'""",
        str(soz_no)
    )
    if not ogr:
        return {"error": f"Ogrenci bulunamadi: {soz_no}"}

    class_name = ogr["class_name"] or ""
    # Alan tespiti — SAY/EA/SÖZ
    if "SAY" in class_name:
        alan_pattern = "%SAY%"
        alan = "SAY"
    elif "EA" in class_name:
        alan_pattern = "%EA%"
        alan = "EA"
    elif "SOZ" in class_name.upper() or "SÖZ" in class_name:
        alan_pattern = "%SÖZ%"
        alan = "SÖZ"
    elif "LGS" in class_name.upper() or "8" in class_name:
        alan_pattern = "%8%"
        alan = "LGS"
    else:
        alan_pattern = f"%{class_name.split()[0] if class_name else ''}%"
        alan = "diger"

    # Öğrencinin son deneme neti
    son_net = await db_fetchval(
        """SELECT toplam FROM student_exams
           WHERE soz_no = $1 AND status='valid' AND exam_type='TYT' AND toplam IS NOT NULL
           ORDER BY exam_date DESC LIMIT 1""",
        int(soz_no)
    )
    if not son_net:
        return {
            "ogrenci_net": None,
            "peer_sayisi": 0,
            "mesaj": "Henüz deneme verin yok, peer kiyasi yapamiyorum. Denemeye girdikçe benzer öğrencilerle kıyas yapabiliriz.",
        }
    son_net = float(son_net)

    # Benzer alan + ±tolerans net aralığındaki peer'lerin SOZ_NO listesi
    # (kendisi HARIÇ, anonim olarak sayılacak)
    peer_soz_nolar = await db_fetch(
        """SELECT DISTINCT e.soz_no
           FROM student_exams e
           JOIN students s ON s.soz_no = e.soz_no::text
           WHERE s.class_name ILIKE $1
             AND s.soz_no != $2
             AND s.status='active'
             AND e.status='valid' AND e.exam_type='TYT'
             AND e.toplam BETWEEN $3 AND $4
             AND e.exam_date > NOW() - INTERVAL '60 days'""",
        alan_pattern, str(soz_no),
        son_net - tolerans_net, son_net + tolerans_net
    )
    peer_ids = [p["soz_no"] for p in peer_soz_nolar]
    if not peer_ids:
        return {
            "ogrenci_net": son_net,
            "alan": alan,
            "peer_sayisi": 0,
            "mesaj": f"Senin gibi {alan} alanında {son_net:.1f} net civarı peer henüz yok — pioneer'sin 🚀",
        }

    # Peer'lerin en çok çalıştığı zayıf konular (öncelikli)
    # status='calisiyor' veya tamamlandi=TRUE olanlar
    oncelik = await db_fetch(
        """SELECT ders, konu, COUNT(*) as sayi,
                  AVG(sinav_hata_yuzdesi) as avg_basari
           FROM student_topic_tracker
           WHERE soz_no = ANY($1::int[])
             AND (status = 'calisiyor' OR tamamlandi = TRUE)
           GROUP BY ders, konu
           HAVING COUNT(*) >= 2
           ORDER BY sayi DESC LIMIT 10""",
        peer_ids
    )
    oncelik_list = [
        {"ders": o["ders"], "konu": o["konu"],
         "peer_sayisi": int(o["sayi"]),
         "avg_basari": round(float(o["avg_basari"] or 0), 1)}
        for o in oncelik
    ]

    # Peer'lerin güçlü konuları (basari %70+)
    guclu = await db_fetch(
        """SELECT ders, konu, COUNT(*) as sayi,
                  AVG(sinav_hata_yuzdesi) as avg_basari
           FROM student_topic_tracker
           WHERE soz_no = ANY($1::int[])
             AND sinav_hata_yuzdesi >= 70
           GROUP BY ders, konu
           HAVING COUNT(*) >= 2
           ORDER BY avg_basari DESC LIMIT 5""",
        peer_ids
    )
    guclu_list = [
        {"ders": g["ders"], "konu": g["konu"],
         "peer_sayisi": int(g["sayi"]),
         "avg_basari": round(float(g["avg_basari"] or 0), 1)}
        for g in guclu
    ]

    motivasyon = ""
    if oncelik_list:
        top = oncelik_list[0]
        motivasyon = (
            f"Senin gibi {alan} alanında ~{int(son_net)} net civarı "
            f"{len(peer_ids)} öğrenci var. En çok *{top['konu']}* ({top['ders']}) üzerinde çalışıyorlar. "
            f"Sen de bu konuyu hedeflersen grup hızınla paralel ilerlersin."
        )
    else:
        motivasyon = f"{len(peer_ids)} peer tespit edildi ama henüz önemli ortak çalışma örüntüsü yok."

    return {
        "ogrenci_net": son_net,
        "alan": alan,
        "peer_sayisi": len(peer_ids),
        "net_araligi": [son_net - tolerans_net, son_net + tolerans_net],
        "peer_oncelik_konular": oncelik_list,
        "peer_guclu_konular": guclu_list,
        "motivasyon_mesaj": motivasyon,
        "not": "Tum peer bilgisi ANONIM — hicbir öğrenci adı veya ID paylaşılmaz.",
    }


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    from dotenv import load_dotenv
    load_dotenv(override=True)

    async def main():
        # Test — Enes Karadaş (en basarili) peer'leri
        r = await ogrenci_peer_kiyas(385, tolerans_net=10)
        print("=" * 60)
        print(f"Peer Benchmark Test")
        print("=" * 60)
        print(f"Ogrenci net: {r.get('ogrenci_net')}")
        print(f"Peer sayisi: {r.get('peer_sayisi')}")
        print(f"Alan: {r.get('alan')}")
        if r.get("peer_oncelik_konular"):
            print(f"\nPeer'lerin en çok çalıştığı konular:")
            for o in r["peer_oncelik_konular"][:5]:
                print(f"  {o['ders']} — {o['konu']}: {o['peer_sayisi']} öğrenci, ort basari %{o['avg_basari']}")
        print(f"\nMotivasyon: {r.get('motivasyon_mesaj')}")

    asyncio.run(main())
