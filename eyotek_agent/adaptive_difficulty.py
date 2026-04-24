"""
Adaptive Difficulty — Vygotsky ZPD (Yakın Gelişim Bölgesi)
============================================================
Öğrenci seviyesine göre soru zorluğu otomatik ayarlanır.
Çok kolay → sıkıcı, çok zor → kaygı. Orta → akış (flow state).
"""
from __future__ import annotations
from loguru import logger


async def get_level(soz_no: int) -> dict:
    """Öğrenci akademik seviye profili."""
    try:
        from db_pool import db_fetchrow
        row = await db_fetchrow(
            """
            SELECT AVG(toplam) AS avg_net, MAX(toplam) AS best_net,
                   COUNT(*) AS sinav_sayisi
            FROM student_exams
            WHERE soz_no=$1 AND status='valid' AND toplam > 5
            """,
            soz_no
        )
        if not row or not row["avg_net"]:
            return {"seviye": "tanimsiz", "avg_net": 0, "sinav_sayisi": 0}
        avg = float(row["avg_net"])
        # Seviye bantları (TYT 120 üzerinden)
        if avg >= 90:
            seviye = "ileri"
        elif avg >= 70:
            seviye = "iyi"
        elif avg >= 50:
            seviye = "orta"
        elif avg >= 30:
            seviye = "temel"
        else:
            seviye = "baslangic"
        return {
            "seviye": seviye,
            "avg_net": round(avg, 1),
            "best_net": float(row["best_net"] or 0),
            "sinav_sayisi": int(row["sinav_sayisi"] or 0),
        }
    except Exception as e:
        logger.debug(f"adaptive level: {e}")
        return {"seviye": "tanimsiz", "avg_net": 0, "sinav_sayisi": 0}


def suggest_zorluk(seviye: str) -> dict:
    """Seviyeye göre soru zorluk dağılımı önerisi."""
    mapping = {
        "baslangic": {"kolay": 60, "orta": 35, "zor": 5, "odak": "temel kavramlar, örnek soru, bol tekrar"},
        "temel":     {"kolay": 40, "orta": 45, "zor": 15, "odak": "temel + orta, klasik sorular"},
        "orta":      {"kolay": 25, "orta": 50, "zor": 25, "odak": "orta + zor karışımı, YKS çıkmış"},
        "iyi":       {"kolay": 10, "orta": 50, "zor": 40, "odak": "zor sorular, yeni tip, süre baskısı"},
        "ileri":     {"kolay": 5,  "orta": 35, "zor": 60, "odak": "uzmanlik, yeni nesil, fark yaratan sorular"},
        "tanimsiz":  {"kolay": 40, "orta": 40, "zor": 20, "odak": "seviye taninmiyor — dengeli başlat"},
    }
    return mapping.get(seviye, mapping["tanimsiz"])


async def get_prompt_hint(soz_no: int) -> str:
    """Claude system prompt'a inject."""
    lvl = await get_level(soz_no)
    s = lvl["seviye"]
    if s == "tanimsiz":
        return ""
    z = suggest_zorluk(s)
    return (
        f"\n\n🎯 *ADAPTIVE DIFFICULTY:* Ogrenci seviyesi: *{s.upper()}* "
        f"(ort {lvl['avg_net']} net, {lvl['sinav_sayisi']} sinav)\n"
        f"Onerilen soru dagilimi: %{z['kolay']} kolay · %{z['orta']} orta · %{z['zor']} zor\n"
        f"Odak: {z['odak']}\n"
    )
