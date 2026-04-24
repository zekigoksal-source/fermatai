"""
Peer Learning — Anonim Akran Eşleştirme (23 Nisan)
=====================================================
Öğrenciye "aynı seviyede X arkadaşın var" tarzı sosyal sinyal.
Rekabet değil DESTEK tonu. ACL: isimler ASLA verilmez.
"""
from __future__ import annotations
from loguru import logger


async def find_similar_peers(soz_no: int, n: int = 3) -> list:
    """Öğrenciye benzer seviyedeki akranları bul (anonim)."""
    try:
        from db_pool import db_fetch, db_fetchrow
        # Öğrencinin son avg net + sınıfı
        me = await db_fetchrow(
            """
            SELECT AVG(e.toplam) AS my_net, s.class_name
            FROM fermat.student_exams e
            JOIN fermat.students s ON s.soz_no::text = e.soz_no::text
            WHERE e.soz_no::text = $1::text AND e.status='valid'
            GROUP BY s.class_name
            """,
            str(soz_no)
        )
        if not me or not me["my_net"]:
            return []
        my_net = float(me["my_net"])
        my_class = me.get("class_name")

        # ±10 net aralığında, aynı sınıftan veya benzer sınıftan, başka öğrenciler
        band_low = my_net - 10
        band_high = my_net + 10
        peers = await db_fetch(
            """
            SELECT s.soz_no, s.class_name, AVG(e.toplam) AS peer_net, COUNT(*) AS sinav_sayisi
            FROM fermat.student_exams e
            JOIN fermat.students s ON s.soz_no::text = e.soz_no::text
            WHERE e.status='valid' AND s.soz_no::text != $1::text
            GROUP BY s.soz_no, s.class_name
            HAVING AVG(e.toplam) BETWEEN $2 AND $3
            ORDER BY ABS(AVG(e.toplam) - $4)
            LIMIT $5
            """,
            str(soz_no), band_low, band_high, my_net, n
        )
        return [dict(p) for p in peers]
    except Exception as e:
        logger.debug(f"peer find: {e}")
        return []


async def build_peer_msg(soz_no: int, name: str) -> str | None:
    """Motivasyonel akran mesajı (anonim)."""
    peers = await find_similar_peers(soz_no, n=3)
    if len(peers) < 2:
        return None
    first = (name or "").split()[0] if name else ""
    avg_net = sum(float(p["peer_net"]) for p in peers) / len(peers)
    return (
        f"👥 *{first}*, seviyendeki arkadaşların nasıl gidiyor?\n\n"
        f"---\n\n"
        f"*{len(peers)}* arkadaşın seninle benzer aralıkta — ortalama *{avg_net:.1f}* net.\n"
        f"_(Anonim, kişilik belirtmiyoruz — birlikte ilerliyoruz, rekabet yok!)_\n\n"
        f"🎯 Birlikte *+5 net* hedefleyelim bu hafta!\n\n"
        f"_Hangi konuda yoğunlaşmak istiyorsun?_"
    )
