"""
Knowledge Graph (Oturum 25.9)
==============================
Konu seti, konu iliskileri, ogrenci × konu ustalik haritasi.

3 ana operasyon:
  1. seed_curriculum() — YKS müfredatından concept_nodes + edges seed et
  2. update_student_mastery(soz_no, ders, konu, mastery) — ELO'dan turetilen ustalık
  3. get_student_graph(soz_no) — JSON graph (d3.js icin)

Kullanim:
  - Bot context'e "Ali'nin guclu/zayif konu agi" eklenebilir
  - Dashboard'da görsel graph (renk = mastery, kenarlar = ön koşul)
  - Predictive model'e zayif konu booster
  - Pazarlama materyali: "Ogrencimizin Beyin Haritasi" gorseli

Ön koşul mantığı:
  - Türev → Limit (limit bilmeden türev olmaz)
  - Integral → Türev
  - Logaritma → Üs (üs bilmeden log olmaz)
"""
from __future__ import annotations
import asyncio
import json
from typing import Optional

from loguru import logger

from db_pool import (
    db_execute as _exec,
    db_fetch as _fetch,
    db_fetchrow as _fetchrow,
    db_fetchval as _fetchval,
)


# ── YKS MÜFREDAT SEED ────────────────────────────────────────────────────
# Format: (ders, konu, seviye, [(prerequisite_ders, prerequisite_konu, strength)])
# Bu liste minimal — production'da rag_content tablosundan otomatik genişler.

YKS_CURRICULUM = [
    # ── MATEMATİK (TYT) ──
    ("Matematik", "Temel Kavramlar", "TYT", []),
    ("Matematik", "Sayılar", "TYT", [("Matematik", "Temel Kavramlar", 0.9)]),
    ("Matematik", "Bölme - Bölünebilme", "TYT", [("Matematik", "Sayılar", 0.8)]),
    ("Matematik", "EBOB - EKOK", "TYT", [("Matematik", "Bölme - Bölünebilme", 0.9)]),
    ("Matematik", "Rasyonel Sayılar", "TYT", [("Matematik", "Sayılar", 0.8)]),
    ("Matematik", "Mutlak Değer", "TYT", [("Matematik", "Sayılar", 0.7)]),
    ("Matematik", "Üslü Sayılar", "TYT", [("Matematik", "Sayılar", 0.8)]),
    ("Matematik", "Köklü Sayılar", "TYT", [("Matematik", "Üslü Sayılar", 0.9)]),
    ("Matematik", "Çarpanlara Ayırma", "TYT", [("Matematik", "Üslü Sayılar", 0.7)]),
    ("Matematik", "Oran-Orantı", "TYT", [("Matematik", "Rasyonel Sayılar", 0.8)]),
    ("Matematik", "Denklemler ve Eşitsizlikler", "TYT", [("Matematik", "Çarpanlara Ayırma", 0.8)]),
    ("Matematik", "Mantık", "TYT", []),
    ("Matematik", "Kümeler", "TYT", [("Matematik", "Mantık", 0.6)]),
    ("Matematik", "Fonksiyonlar", "TYT", [("Matematik", "Denklemler ve Eşitsizlikler", 0.8)]),
    ("Matematik", "Polinomlar", "TYT", [("Matematik", "Çarpanlara Ayırma", 0.9)]),
    ("Matematik", "Permütasyon - Kombinasyon", "TYT", [("Matematik", "Sayılar", 0.6)]),
    ("Matematik", "Olasılık", "TYT", [("Matematik", "Permütasyon - Kombinasyon", 0.9)]),
    ("Matematik", "Veri - Grafik İstatistik", "TYT", [("Matematik", "Olasılık", 0.5)]),

    # ── MATEMATİK (AYT) ──
    ("Matematik", "Limit", "AYT", [("Matematik", "Fonksiyonlar", 0.9)]),
    ("Matematik", "Türev", "AYT", [("Matematik", "Limit", 0.95)]),
    ("Matematik", "İntegral", "AYT", [("Matematik", "Türev", 0.95)]),
    ("Matematik", "Logaritma", "AYT", [("Matematik", "Üslü Sayılar", 0.95)]),
    ("Matematik", "Trigonometri", "AYT", [("Matematik", "Fonksiyonlar", 0.7)]),
    ("Matematik", "Karmaşık Sayılar", "AYT", [("Matematik", "Köklü Sayılar", 0.7)]),
    ("Matematik", "Diziler", "AYT", [("Matematik", "Fonksiyonlar", 0.6)]),

    # ── GEOMETRİ ──
    ("Geometri", "Doğruda Açılar", "TYT", []),
    ("Geometri", "Üçgenler", "TYT", [("Geometri", "Doğruda Açılar", 0.9)]),
    ("Geometri", "Dörtgenler", "TYT", [("Geometri", "Üçgenler", 0.8)]),
    ("Geometri", "Çokgenler", "TYT", [("Geometri", "Dörtgenler", 0.7)]),
    ("Geometri", "Çember ve Daire", "TYT", [("Geometri", "Üçgenler", 0.6)]),
    ("Geometri", "Katı Cisimler", "TYT", [("Geometri", "Çember ve Daire", 0.7)]),
    ("Geometri", "Analitik Geometri", "AYT", [("Matematik", "Fonksiyonlar", 0.8), ("Geometri", "Doğruda Açılar", 0.7)]),

    # ── FİZİK ──
    ("Fizik", "Fiziğin Doğası", "TYT", []),
    ("Fizik", "Madde ve Özellikleri", "TYT", [("Fizik", "Fiziğin Doğası", 0.5)]),
    ("Fizik", "Hareket ve Kuvvet", "TYT", [("Fizik", "Fiziğin Doğası", 0.6)]),
    ("Fizik", "Enerji", "TYT", [("Fizik", "Hareket ve Kuvvet", 0.9)]),
    ("Fizik", "Isı ve Sıcaklık", "TYT", [("Fizik", "Enerji", 0.7)]),
    ("Fizik", "Elektrik ve Manyetizma", "TYT", [("Fizik", "Enerji", 0.6)]),
    ("Fizik", "Basınç ve Kaldırma Kuvveti", "TYT", [("Fizik", "Hareket ve Kuvvet", 0.7)]),
    ("Fizik", "Dalgalar", "TYT", [("Fizik", "Hareket ve Kuvvet", 0.6)]),
    ("Fizik", "Optik", "TYT", [("Fizik", "Dalgalar", 0.8)]),
    ("Fizik", "Vektörler", "AYT", [("Matematik", "Trigonometri", 0.8)]),
    ("Fizik", "Tork ve Denge", "AYT", [("Fizik", "Hareket ve Kuvvet", 0.9), ("Fizik", "Vektörler", 0.7)]),
    ("Fizik", "Elektromanyetik Dalgalar", "AYT", [("Fizik", "Elektrik ve Manyetizma", 0.95)]),
    ("Fizik", "Atom Fiziği ve Modern Fizik", "AYT", [("Fizik", "Optik", 0.6)]),

    # ── KİMYA ──
    ("Kimya", "Kimya Bilimi", "TYT", []),
    ("Kimya", "Atom ve Periyodik Sistem", "TYT", [("Kimya", "Kimya Bilimi", 0.6)]),
    ("Kimya", "Kimyasal Türler Arası Etkileşimler", "TYT", [("Kimya", "Atom ve Periyodik Sistem", 0.9)]),
    ("Kimya", "Maddenin Halleri", "TYT", [("Kimya", "Kimyasal Türler Arası Etkileşimler", 0.6)]),
    ("Kimya", "Karışımlar", "TYT", [("Kimya", "Maddenin Halleri", 0.7)]),
    ("Kimya", "Asit-Baz-Tuz", "TYT", [("Kimya", "Karışımlar", 0.7)]),
    ("Kimya", "Mol Kavramı", "AYT", [("Kimya", "Atom ve Periyodik Sistem", 0.8)]),
    ("Kimya", "Kimyasal Tepkimeler ve Hesaplamalar", "AYT", [("Kimya", "Mol Kavramı", 0.95)]),
    ("Kimya", "Gazlar", "AYT", [("Kimya", "Maddenin Halleri", 0.8)]),
    ("Kimya", "Çözeltiler", "AYT", [("Kimya", "Karışımlar", 0.9), ("Kimya", "Mol Kavramı", 0.7)]),
    ("Kimya", "Kimyasal Tepkimelerde Enerji", "AYT", [("Kimya", "Kimyasal Tepkimeler ve Hesaplamalar", 0.8)]),
    ("Kimya", "Organik Kimya", "AYT", [("Kimya", "Kimyasal Türler Arası Etkileşimler", 0.7)]),

    # ── BİYOLOJİ ──
    ("Biyoloji", "Canlıların Ortak Özellikleri", "TYT", []),
    ("Biyoloji", "Hücre", "TYT", [("Biyoloji", "Canlıların Ortak Özellikleri", 0.7)]),
    ("Biyoloji", "Canlıların Sınıflandırılması", "TYT", [("Biyoloji", "Hücre", 0.5)]),
    ("Biyoloji", "Mitoz ve Eşeysiz Üreme", "TYT", [("Biyoloji", "Hücre", 0.9)]),
    ("Biyoloji", "Mayoz ve Eşeyli Üreme", "TYT", [("Biyoloji", "Mitoz ve Eşeysiz Üreme", 0.95)]),
    ("Biyoloji", "Kalıtımın Genel İlkeleri", "AYT", [("Biyoloji", "Mayoz ve Eşeyli Üreme", 0.95)]),
    ("Biyoloji", "Sinir Sistemi", "AYT", [("Biyoloji", "Hücre", 0.7)]),
    ("Biyoloji", "Endokrin Sistem", "AYT", [("Biyoloji", "Sinir Sistemi", 0.7)]),

    # ── TÜRKÇE ──
    ("Türkçe", "Sözcükte Anlam", "TYT", []),
    ("Türkçe", "Cümlede Anlam", "TYT", [("Türkçe", "Sözcükte Anlam", 0.8)]),
    ("Türkçe", "Paragrafta Anlam", "TYT", [("Türkçe", "Cümlede Anlam", 0.9)]),
    ("Türkçe", "Paragrafta Yapı", "TYT", [("Türkçe", "Paragrafta Anlam", 0.9)]),
    ("Türkçe", "Ses Bilgisi", "TYT", []),
    ("Türkçe", "Yazım Kuralları", "TYT", [("Türkçe", "Ses Bilgisi", 0.6)]),
    ("Türkçe", "Noktalama İşaretleri", "TYT", [("Türkçe", "Yazım Kuralları", 0.5)]),
    ("Türkçe", "Sözcük Yapısı", "TYT", [("Türkçe", "Sözcükte Anlam", 0.6)]),
    ("Türkçe", "Sözcük Türleri", "TYT", [("Türkçe", "Sözcük Yapısı", 0.7)]),
    ("Türkçe", "Cümlenin Ögeleri", "TYT", [("Türkçe", "Sözcük Türleri", 0.8)]),
    ("Türkçe", "Cümle Türleri", "TYT", [("Türkçe", "Cümlenin Ögeleri", 0.9)]),
    ("Türkçe", "Anlatım Bozukluğu", "TYT", [("Türkçe", "Cümle Türleri", 0.7)]),
]


async def seed_curriculum() -> dict:
    """Müfredat node'larını ve edge'lerini seed et (idempotent)."""
    nodes_added = 0
    edges_added = 0

    # 1. Önce tüm node'ları ekle
    for ders, konu, seviye, _ in YKS_CURRICULUM:
        try:
            await _exec(
                """INSERT INTO concept_nodes (ders, konu, seviye)
                   VALUES ($1, $2, $3)
                   ON CONFLICT (ders, konu, seviye) DO NOTHING""",
                ders, konu, seviye,
            )
            nodes_added += 1
        except Exception as e:
            logger.warning(f"node insert fail {ders}/{konu}: {e}")

    # 2. Edge'leri ekle (önce node_id lookup)
    node_id_cache: dict[tuple, int] = {}
    rows = await _fetch("SELECT id, ders, konu, seviye FROM concept_nodes")
    for r in (rows or []):
        node_id_cache[(r['ders'], r['konu'], r['seviye'])] = r['id']

    for ders, konu, seviye, prereqs in YKS_CURRICULUM:
        to_id = node_id_cache.get((ders, konu, seviye))
        if not to_id:
            continue
        for pre_ders, pre_konu, strength in prereqs:
            # Önce TYT, sonra AYT prerequisite ara
            from_id = (
                node_id_cache.get((pre_ders, pre_konu, "TYT")) or
                node_id_cache.get((pre_ders, pre_konu, "AYT")) or
                node_id_cache.get((pre_ders, pre_konu, "LGS"))
            )
            if not from_id or from_id == to_id:
                continue
            try:
                await _exec(
                    """INSERT INTO concept_edges (from_node_id, to_node_id, relation_type, strength)
                       VALUES ($1, $2, 'prerequisite', $3)
                       ON CONFLICT (from_node_id, to_node_id, relation_type)
                       DO UPDATE SET strength = EXCLUDED.strength""",
                    from_id, to_id, strength,
                )
                edges_added += 1
            except Exception as e:
                logger.warning(f"edge insert fail: {e}")

    return {"nodes": nodes_added, "edges": edges_added, "total_curriculum": len(YKS_CURRICULUM)}


async def update_student_mastery_from_elo(soz_no: int) -> int:
    """student_topic_elo'dan student_concept_mastery'yi turet (ELO → 0-1).

    ELO 800 = 0.0 mastery
    ELO 1200 = 0.5 (default — yeni)
    ELO 1600 = 0.8
    ELO 2000+ = 1.0

    Returns: updated count
    """
    elo_rows = await _fetch(
        "SELECT ders, konu, rating, games_played FROM student_topic_elo WHERE soz_no=$1",
        soz_no,
    )
    if not elo_rows:
        return 0

    # node lookup — TYT veya AYT ayrımı yok (konu adıyla eşleşir)
    node_lookup = await _fetch("SELECT id, ders, konu FROM concept_nodes")
    node_map: dict[tuple, int] = {}
    for r in (node_lookup or []):
        # Aynı ders/konu hem TYT hem AYT olabilir — son kazanan
        node_map[(r['ders'].lower(), r['konu'].lower())] = r['id']

    updated = 0
    for er in elo_rows:
        nid = node_map.get((er['ders'].lower(), er['konu'].lower()))
        if not nid:
            continue
        rating = er['rating']
        # Lineer mapping: 800→0, 2000→1
        mastery = max(0.0, min(1.0, (rating - 800) / 1200))
        try:
            await _exec(
                """INSERT INTO student_concept_mastery
                   (soz_no, node_id, mastery_level, sample_count, last_assessed)
                   VALUES ($1, $2, $3, $4, NOW())
                   ON CONFLICT (soz_no, node_id) DO UPDATE SET
                     mastery_level = EXCLUDED.mastery_level,
                     sample_count = EXCLUDED.sample_count,
                     last_assessed = NOW()""",
                soz_no, nid, mastery, er['games_played'] or 0,
            )
            updated += 1
        except Exception as e:
            logger.warning(f"mastery update fail: {e}")
    return updated


async def get_student_graph(soz_no: int, seviye: Optional[str] = None) -> dict:
    """Ogrencinin knowledge graph JSON'ı (d3.js icin).

    Returns: {
      "nodes": [{id, ders, konu, seviye, mastery}],
      "edges": [{from, to, type, strength}],
      "stats": {avg_mastery, weak_count, strong_count}
    }
    """
    where_seviye = "AND n.seviye=$2" if seviye else ""
    params = [soz_no]
    if seviye:
        params.append(seviye)

    nodes_q = f"""
        SELECT n.id, n.ders, n.konu, n.seviye,
               COALESCE(m.mastery_level, 0) as mastery,
               COALESCE(m.sample_count, 0) as samples
        FROM concept_nodes n
        LEFT JOIN student_concept_mastery m ON m.node_id = n.id AND m.soz_no = $1
        WHERE 1=1 {where_seviye}
        ORDER BY n.ders, n.konu
    """
    nodes = await _fetch(nodes_q, *params)
    nodes_list = [dict(n) for n in (nodes or [])]

    if not nodes_list:
        return {"nodes": [], "edges": [], "stats": {}}

    node_ids = [n['id'] for n in nodes_list]
    edges = await _fetch(
        """SELECT from_node_id, to_node_id, relation_type, strength
           FROM concept_edges
           WHERE from_node_id = ANY($1::int[]) AND to_node_id = ANY($1::int[])""",
        node_ids,
    )
    edges_list = [
        {"from": e['from_node_id'], "to": e['to_node_id'],
         "type": e['relation_type'], "strength": float(e['strength'] or 0.5)}
        for e in (edges or [])
    ]

    # Stats
    masteries = [n['mastery'] for n in nodes_list if n['samples'] > 0]
    weak_count = sum(1 for m in masteries if m < 0.4)
    strong_count = sum(1 for m in masteries if m >= 0.7)
    avg = sum(masteries) / len(masteries) if masteries else 0

    return {
        "nodes": nodes_list,
        "edges": edges_list,
        "stats": {
            "total_nodes": len(nodes_list),
            "studied_nodes": len(masteries),
            "avg_mastery": round(avg, 2),
            "weak_count": weak_count,
            "strong_count": strong_count,
        },
    }


async def get_concept_tree(ders: str, seviye: Optional[str] = None) -> list[dict]:
    """Bir dersin konu agacini ders + seviye filtresiyle dön."""
    where = "WHERE ders=$1"
    params = [ders]
    if seviye:
        where += " AND seviye=$2"
        params.append(seviye)
    rows = await _fetch(
        f"SELECT id, ders, konu, seviye FROM concept_nodes {where} ORDER BY konu",
        *params,
    )
    return [dict(r) for r in (rows or [])]


if __name__ == "__main__":
    print(f"Curriculum entries: {len(YKS_CURRICULUM)}")
    derslar = set(c[0] for c in YKS_CURRICULUM)
    print(f"Derslar: {sorted(derslar)}")
    for d in sorted(derslar):
        cnt = sum(1 for c in YKS_CURRICULUM if c[0] == d)
        print(f"  {d}: {cnt} konu")
