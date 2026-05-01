"""
PhET Simulations Catalog (Oturum 25.38)
========================================
Colorado Üniversitesi PhET (Physics Education Technology) — 600+ ücretsiz interaktif simulasyon.
İframe ile direkt embed edilebilir, $0 maliyet.

KRİTİK NOT (Neo direktifi 25.38):
  Bu modül DESTEK altyapı olarak duruyor — bizim kendi make_render_link
  simulasyonlarımız BIRINCI SINIF. PhET sadece:
    - Çok özel/uzun simulasyon gerektiğinde (kuantum tüneli, gen-net vb)
    - Öğrenci özellikle "PhET" derse
    - Bizim render başarısız olursa (last resort)

iframe URL formatı:
  https://phet.colorado.edu/sims/html/<sim_id>/latest/<sim_id>_<lang>.html

Türkçe destekli simulasyonlar var, lang=tr ile yüklenir (yoksa İngilizce).
"""

# Türkçe destekli en popüler 60 PhET simulasyonu (YKS müfredatına yakın)
PHET_CATALOG = {
    # ═════ FİZİK ═════
    "blackbody-spectrum": {
        "title": "Karacisim Tayfı",
        "ders": "Fizik", "konu": "Karacisim ışıması",
        "lang": "tr", "tag": "ayt-fizik",
    },
    "build-an-atom": {
        "title": "Atom İnşa Et",
        "ders": "Fizik", "konu": "Atom yapısı",
        "lang": "tr", "tag": "tyt-fizik",
    },
    "circuit-construction-kit-dc": {
        "title": "Devre İnşa Kiti — DC",
        "ders": "Fizik", "konu": "Elektrik devreleri",
        "lang": "tr", "tag": "tyt-fizik",
    },
    "circuit-construction-kit-ac": {
        "title": "Devre İnşa Kiti — AC",
        "ders": "Fizik", "konu": "Alternatif akım",
        "lang": "tr", "tag": "ayt-fizik",
    },
    "color-vision": {
        "title": "Renk Görüsü",
        "ders": "Fizik", "konu": "Optik, ışık tayfı",
        "lang": "tr", "tag": "tyt-fizik",
    },
    "energy-skate-park": {
        "title": "Enerji Kaykay Parkı",
        "ders": "Fizik", "konu": "Enerji korunumu",
        "lang": "tr", "tag": "tyt-fizik",
    },
    "energy-skate-park-basics": {
        "title": "Enerji Kaykay Parkı — Temel",
        "ders": "Fizik", "konu": "Kinetik/potansiyel enerji",
        "lang": "tr", "tag": "tyt-fizik",
    },
    "faradays-law": {
        "title": "Faraday Yasası",
        "ders": "Fizik", "konu": "Elektromanyetik indüksiyon",
        "lang": "tr", "tag": "ayt-fizik",
    },
    "forces-and-motion-basics": {
        "title": "Kuvvet ve Hareket — Temel",
        "ders": "Fizik", "konu": "Newton yasaları, kuvvet",
        "lang": "tr", "tag": "tyt-fizik",
    },
    "forces-and-motion": {
        "title": "Kuvvet ve Hareket",
        "ders": "Fizik", "konu": "Sürtünme, ivme",
        "lang": "tr", "tag": "tyt-fizik",
    },
    "gravity-and-orbits": {
        "title": "Yerçekimi ve Yörüngeler",
        "ders": "Fizik", "konu": "Kütle çekimi",
        "lang": "tr", "tag": "ayt-fizik",
    },
    "gravity-force-lab": {
        "title": "Yerçekimi Kuvvet Laboratuvarı",
        "ders": "Fizik", "konu": "Newton kütle çekim yasası",
        "lang": "tr", "tag": "ayt-fizik",
    },
    "hookes-law": {
        "title": "Hooke Yasası",
        "ders": "Fizik", "konu": "Yay esnekliği",
        "lang": "tr", "tag": "ayt-fizik",
    },
    "magnets-and-electromagnets": {
        "title": "Mıknatıslar ve Elektromıknatıslar",
        "ders": "Fizik", "konu": "Manyetizma",
        "lang": "tr", "tag": "ayt-fizik",
    },
    "masses-and-springs": {
        "title": "Kütle ve Yaylar",
        "ders": "Fizik", "konu": "Basit harmonik hareket",
        "lang": "tr", "tag": "ayt-fizik",
    },
    "pendulum-lab": {
        "title": "Sarkaç Laboratuvarı",
        "ders": "Fizik", "konu": "Basit sarkaç",
        "lang": "tr", "tag": "ayt-fizik",
    },
    "photoelectric": {
        "title": "Fotoelektrik Etki",
        "ders": "Fizik", "konu": "Fotoelektrik etki, kuantum",
        "lang": "en", "tag": "ayt-fizik",
    },
    "projectile-motion": {
        "title": "Eğik Atış",
        "ders": "Fizik", "konu": "Eğik/yatay atış",
        "lang": "tr", "tag": "tyt-fizik",
    },
    "quantum-bound-states": {
        "title": "Kuantum Bağlı Durumlar",
        "ders": "Fizik", "konu": "Kuantum mekaniği",
        "lang": "en", "tag": "ayt-fizik",
    },
    "quantum-tunneling": {
        "title": "Kuantum Tünelleme",
        "ders": "Fizik", "konu": "Kuantum tünelleme etkisi",
        "lang": "en", "tag": "ayt-fizik",
    },
    "ramp-forces-and-motion": {
        "title": "Eğik Düzlem — Kuvvet ve Hareket",
        "ders": "Fizik", "konu": "Eğik düzlem, sürtünme",
        "lang": "en", "tag": "tyt-fizik",
    },
    "resistance-in-a-wire": {
        "title": "Tel Direnci",
        "ders": "Fizik", "konu": "Direnç, Ohm yasası",
        "lang": "tr", "tag": "tyt-fizik",
    },
    "rutherford-scattering": {
        "title": "Rutherford Saçılması",
        "ders": "Fizik", "konu": "Atom modeli",
        "lang": "tr", "tag": "tyt-fizik",
    },
    "wave-on-a-string": {
        "title": "İpteki Dalga",
        "ders": "Fizik", "konu": "Dalga hareketi",
        "lang": "tr", "tag": "ayt-fizik",
    },
    "wave-interference": {
        "title": "Dalga Girişimi",
        "ders": "Fizik", "konu": "Girişim, kırınım",
        "lang": "tr", "tag": "ayt-fizik",
    },
    "geometric-optics": {
        "title": "Geometrik Optik",
        "ders": "Fizik", "konu": "Mercek, ayna",
        "lang": "tr", "tag": "ayt-fizik",
    },
    "bending-light": {
        "title": "Işığın Kırılması",
        "ders": "Fizik", "konu": "Snell yasası, kırılma",
        "lang": "tr", "tag": "ayt-fizik",
    },
    "balloons-and-static-electricity": {
        "title": "Balonlar ve Statik Elektrik",
        "ders": "Fizik", "konu": "Statik elektrik",
        "lang": "tr", "tag": "tyt-fizik",
    },
    "ohms-law": {
        "title": "Ohm Yasası",
        "ders": "Fizik", "konu": "V=IR ilişkisi",
        "lang": "tr", "tag": "tyt-fizik",
    },

    # ═════ KİMYA ═════
    "build-a-molecule": {
        "title": "Molekül İnşa Et",
        "ders": "Kimya", "konu": "Moleküller",
        "lang": "tr", "tag": "tyt-kimya",
    },
    "molecule-shapes": {
        "title": "Molekül Şekilleri",
        "ders": "Kimya", "konu": "VSEPR, molekül geometrisi",
        "lang": "tr", "tag": "ayt-kimya",
    },
    "atomic-interactions": {
        "title": "Atomik Etkileşimler",
        "ders": "Kimya", "konu": "Atomlar arası kuvvetler",
        "lang": "tr", "tag": "ayt-kimya",
    },
    "balancing-chemical-equations": {
        "title": "Kimyasal Denklem Denkleştirme",
        "ders": "Kimya", "konu": "Denklem denkleştirme",
        "lang": "tr", "tag": "tyt-kimya",
    },
    "states-of-matter": {
        "title": "Maddenin Halleri",
        "ders": "Kimya", "konu": "Faz değişimi",
        "lang": "tr", "tag": "tyt-kimya",
    },
    "states-of-matter-basics": {
        "title": "Maddenin Halleri — Temel",
        "ders": "Kimya", "konu": "Katı/sıvı/gaz",
        "lang": "tr", "tag": "tyt-kimya",
    },
    "ph-scale": {
        "title": "pH Cetveli",
        "ders": "Kimya", "konu": "Asit/baz, pH",
        "lang": "tr", "tag": "ayt-kimya",
    },
    "ph-scale-basics": {
        "title": "pH Cetveli — Temel",
        "ders": "Kimya", "konu": "pH temel",
        "lang": "tr", "tag": "tyt-kimya",
    },
    "molarity": {
        "title": "Molarite",
        "ders": "Kimya", "konu": "Çözelti derişimi",
        "lang": "tr", "tag": "ayt-kimya",
    },
    "concentration": {
        "title": "Derişim",
        "ders": "Kimya", "konu": "Çözeltiler",
        "lang": "tr", "tag": "ayt-kimya",
    },
    "isotopes-and-atomic-mass": {
        "title": "İzotoplar ve Atom Kütlesi",
        "ders": "Kimya", "konu": "İzotoplar",
        "lang": "tr", "tag": "tyt-kimya",
    },
    "reactions-and-rates": {
        "title": "Tepkimeler ve Hızlar",
        "ders": "Kimya", "konu": "Tepkime hızı, kataliz",
        "lang": "en", "tag": "ayt-kimya",
    },

    # ═════ MATEMATİK ═════
    "graphing-lines": {
        "title": "Doğru Çizimi",
        "ders": "Matematik", "konu": "Doğrusal denklemler",
        "lang": "tr", "tag": "tyt-mat",
    },
    "graphing-quadratics": {
        "title": "İkinci Derece Çizim",
        "ders": "Matematik", "konu": "Parabol, kuadratik",
        "lang": "tr", "tag": "ayt-mat",
    },
    "graphing-slope-intercept": {
        "title": "Eğim-Kesim Çizimi",
        "ders": "Matematik", "konu": "Doğru denklemi",
        "lang": "tr", "tag": "tyt-mat",
    },
    "trig-tour": {
        "title": "Trigonometri Turu",
        "ders": "Matematik", "konu": "Trigonometri, birim çember",
        "lang": "tr", "tag": "ayt-mat",
    },
    "function-builder": {
        "title": "Fonksiyon İnşa",
        "ders": "Matematik", "konu": "Fonksiyonlar",
        "lang": "tr", "tag": "tyt-mat",
    },
    "fraction-matcher": {
        "title": "Kesir Eşleştirici",
        "ders": "Matematik", "konu": "Kesirler",
        "lang": "tr", "tag": "tyt-mat",
    },
    "calculus-grapher": {
        "title": "Türev/İntegral Grafiği",
        "ders": "Matematik", "konu": "Türev, integral grafik",
        "lang": "en", "tag": "ayt-mat",
    },

    # ═════ BİYOLOJİ ═════
    "natural-selection": {
        "title": "Doğal Seçilim",
        "ders": "Biyoloji", "konu": "Evrim, doğal seçilim",
        "lang": "tr", "tag": "ayt-bio",
    },
    "gene-machine-the-lac-operon": {
        "title": "Gen Makinesi — Lac Operon",
        "ders": "Biyoloji", "konu": "Gen ifade düzenlenmesi",
        "lang": "en", "tag": "ayt-bio",
    },
    "neuron": {
        "title": "Nöron",
        "ders": "Biyoloji", "konu": "Sinir hücresi, aksiyon potansiyeli",
        "lang": "en", "tag": "tyt-bio",
    },
    "membrane-channels": {
        "title": "Membran Kanalları",
        "ders": "Biyoloji", "konu": "Hücre membranı",
        "lang": "en", "tag": "ayt-bio",
    },

    # ═════ EARTH/UZAY (AYT Coğrafya/Fen) ═════
    "plate-tectonics": {
        "title": "Levha Tektoniği",
        "ders": "Coğrafya", "konu": "Levha hareketleri",
        "lang": "en", "tag": "tyt-cog",
    },
    "greenhouse-effect": {
        "title": "Sera Etkisi",
        "ders": "Coğrafya", "konu": "İklim değişimi",
        "lang": "tr", "tag": "tyt-cog",
    },
    "my-solar-system": {
        "title": "Benim Güneş Sistemim",
        "ders": "Fizik", "konu": "Yörünge mekaniği",
        "lang": "tr", "tag": "ayt-fizik",
    },
}


def get_iframe_url(sim_id: str, lang: str = None) -> str:
    """PhET simulasyon iframe URL'si üret."""
    sim = PHET_CATALOG.get(sim_id)
    if not sim:
        # Bilinmeyen sim — varsayılan İngilizce
        lang = lang or "en"
        return f"https://phet.colorado.edu/sims/html/{sim_id}/latest/{sim_id}_{lang}.html"
    use_lang = lang or sim.get("lang", "en")
    return f"https://phet.colorado.edu/sims/html/{sim_id}/latest/{sim_id}_{use_lang}.html"


def search_simulations(ders: str = None, konu: str = None, tag: str = None,
                       limit: int = 5) -> list[dict]:
    """Ders/konu/tag filtresiyle PhET sim ara."""
    results = []
    konu_lower = (konu or "").lower()
    ders_lower = (ders or "").lower()

    for sim_id, info in PHET_CATALOG.items():
        score = 0
        if ders_lower and ders_lower in info.get("ders", "").lower():
            score += 3
        if konu_lower:
            if konu_lower in info.get("konu", "").lower():
                score += 5
            if konu_lower in info.get("title", "").lower():
                score += 2
        if tag and tag in info.get("tag", ""):
            score += 1

        if score > 0:
            results.append({
                "sim_id": sim_id,
                "score": score,
                **info,
                "iframe_url": get_iframe_url(sim_id),
            })

    results.sort(key=lambda x: -x["score"])
    return results[:limit]


def list_by_ders(ders: str) -> list[dict]:
    """Bir dersin tüm simulasyonları."""
    return [
        {"sim_id": k, **v, "iframe_url": get_iframe_url(k)}
        for k, v in PHET_CATALOG.items()
        if ders.lower() in v.get("ders", "").lower()
    ]


def stats() -> dict:
    """Catalog istatistik."""
    by_ders = {}
    for info in PHET_CATALOG.values():
        ders = info.get("ders", "?")
        by_ders[ders] = by_ders.get(ders, 0) + 1
    return {
        "toplam": len(PHET_CATALOG),
        "ders_dagilim": by_ders,
        "turkce_destek": sum(1 for v in PHET_CATALOG.values() if v.get("lang") == "tr"),
    }


if __name__ == "__main__":
    import json
    s = stats()
    print(json.dumps(s, ensure_ascii=False, indent=2))
    print("\nFizik 'kaldırma kuvveti' arama:")
    res = search_simulations(ders="Fizik", konu="kuvvet", limit=3)
    for r in res:
        print(f"  {r['title']} → {r['iframe_url']}")
