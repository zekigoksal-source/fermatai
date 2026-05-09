"""
knowledge_service — Bilgi katmanı tool'ları (Oturum 25.41-REFACTOR, 9 May)
============================================================================

fermat_core_agent.py'den taşınan knowledge tool fonksiyonları:
  - _keyword_search_rag      (101 satır helper) — RAG keyword fallback
  - ogm_yonlendir            (33 satır)  — MEB OGM Materyal yönlendirme
  - search_curriculum        (123 satır) — RAG semantik + keyword + OGM ekleme
  - send_exam_image          (39 satır)  — Cikmis soru görseli WP/Web kanalı
  - list_exam_questions      (107 satır) — Çıkmış soru kataloğu (split bazlı)
  - make_render_link         (73 satır)  — HTML artefakt + kalıcı link

Mimari ilke: Brain centralized, Execution modular
"""
from __future__ import annotations
from typing import Any


# ─────────────────────────────────────────────────────────────────────────
# _keyword_search_rag (taşındı — fermat_core_agent.py:335-436)
# Helper — search_curriculum tarafından çağrılır
# ─────────────────────────────────────────────────────────────────────────

async def keyword_search_rag(query: str, ders: str = "", limit: int = 3) -> list:
    """Semantik arama yetersiz kaldığında keyword-based fallback."""
    from db_pool import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Query'den anahtar kelimeler çıkar (2+ harfli)
        words = [w.strip().lower() for w in query.split() if len(w.strip()) > 2]
        if not words:
            return []
        # Genel kelimeleri atla
        skip_words = {'cikmis', 'cıkmış', 'soru', 'sorusu', 'sorulari', 'goster', 'göster',
                      'getir', 'bul', 'var', 'konusundan', 'konusu', 'konusunda',
                      'gecen', 'geçen', 'yil', 'yıl', 'son', 'bana', 'bir'}
        content_words = [w for w in words if w not in skip_words]
        if not content_words:
            content_words = words[:2]
        # Türkçe karakter varyantları
        _TR_MAP = {'turev': 'türev', 'basinc': 'basınç', 'kaldirma': 'kaldırma',
                   'cozum': 'çözüm', 'olasilik': 'olasılık', 'ucgen': 'üçgen',
                   'cember': 'çember', 'donusum': 'dönüşüm', 'ustel': 'üstel',
                   'hucre': 'hücre', 'osmanli': 'osmanlı', 'cumhuriyet': 'cumhuriyet',
                   'esitsizlik': 'eşitsizlik', 'fonksiyon': 'fonksiyon',
                   'bolunebilme': 'bölünebilme', 'carpanlar': 'çarpanlar',
                   'cozunurluk': 'çözünürlük', 'induksiyon': 'indüksiyon',
                   'elektromanyetik': 'elektromanyetik', 'frekans': 'frekans',
                   'isik': 'ışık', 'sicaklik': 'sıcaklık', 'yogunluk': 'yoğunluk',
                   'kalitim': 'kalıtım', 'mutasyon': 'mutasyon', 'ekoloji': 'ekoloji'}
        # Konu araması (kesin)
        conditions = []
        params = []
        for w in content_words:
            idx = len(params) + 1
            tr_w = _TR_MAP.get(w.lower())
            if tr_w:
                conditions.append(f"(konu ILIKE ${idx} OR konu ILIKE ${idx+1})")
                params.extend([f"%{w}%", f"%{tr_w}%"])
            else:
                conditions.append(f"(konu ILIKE ${idx})")
                params.append(f"%{w}%")
        where = " AND ".join(conditions)
        # Sadece OGM Vision kaynaklarında ara
        where += " AND kaynak LIKE '%OGM Vision%'"
        # Ders filtresi
        _DERS_NORM_KW = {'türkçe': 'Turkce', 'turkce': 'Turkce', 'matematik': 'Matematik',
                         'fizik': 'Fizik', 'kimya': 'Kimya', 'biyoloji': 'Biyoloji',
                         'tarih': 'Tarih', 'cografya': 'Cografya', 'felsefe': 'Felsefe'}
        ders_kw = _DERS_NORM_KW.get((ders or '').lower().strip(), ders)
        if ders_kw:
            params.append(ders_kw)
            where += f" AND ders = ${len(params)}"
        params.append(limit)
        rows = await conn.fetch(f"""
            SELECT id, sinav_turu, ders, konu, alt_konu, icerik_turu,
                   baslik, icerik, kaynak, zorluk, soru_sayisi
            FROM rag_content
            WHERE {where}
            ORDER BY
                CASE WHEN kaynak LIKE '%%OGM Vision%%' THEN 0 ELSE 1 END,
                LENGTH(icerik) DESC
            LIMIT ${len(params)}
        """, *params)
        results = []
        for r in rows:
            results.append({
                "id": r["id"], "sinav_turu": r["sinav_turu"], "ders": r["ders"],
                "konu": r["konu"], "alt_konu": r["alt_konu"], "icerik_turu": r["icerik_turu"],
                "baslik": r["baslik"], "icerik": r["icerik"], "kaynak": r["kaynak"],
                "zorluk": r["zorluk"], "soru_sayisi": r["soru_sayisi"], "skor": 0.700,
            })
        # Konu aramasında sonuç yoksa içerik fallback
        if not results and content_words:
            fallback_conds = []
            fallback_params = []
            for w in content_words:
                idx = len(fallback_params) + 1
                tr_w = _TR_MAP.get(w.lower())
                if tr_w:
                    fallback_conds.append(f"(icerik ILIKE ${idx} OR icerik ILIKE ${idx+1})")
                    fallback_params.extend([f"%{w}%", f"%{tr_w}%"])
                else:
                    fallback_conds.append(f"(icerik ILIKE ${idx})")
                    fallback_params.append(f"%{w}%")
            fb_where = " AND ".join(fallback_conds)
            fb_where += " AND kaynak LIKE '%OGM Vision%'"
            if ders_kw:
                fallback_params.append(ders_kw)
                fb_where += f" AND ders = ${len(fallback_params)}"
            fallback_params.append(limit)
            fb_rows = await conn.fetch(f"""
                SELECT id, sinav_turu, ders, konu, alt_konu, icerik_turu,
                       baslik, icerik, kaynak, zorluk, soru_sayisi
                FROM rag_content WHERE {fb_where}
                ORDER BY LENGTH(icerik) DESC LIMIT ${len(fallback_params)}
            """, *fallback_params)
            for r in fb_rows:
                results.append({
                    "id": r["id"], "sinav_turu": r["sinav_turu"], "ders": r["ders"],
                    "konu": r["konu"], "alt_konu": r["alt_konu"], "icerik_turu": r["icerik_turu"],
                    "baslik": r["baslik"], "icerik": r["icerik"], "kaynak": r["kaynak"],
                    "zorluk": r["zorluk"], "soru_sayisi": r["soru_sayisi"], "skor": 0.650,
                })
        return results


# ─────────────────────────────────────────────────────────────────────────
# tool_ogm_yonlendir (taşındı — fermat_core_agent.py:439-469)
# ─────────────────────────────────────────────────────────────────────────

async def ogm_yonlendir(ders: str = "", sinav_turu: str = "", tip: str = "") -> dict:
    """MEB OGM Materyal resmi kaynağı yönlendirme."""
    from ogm_catalog import yonlendir
    _NORM = {'türkçe': 'Turkce', 'turkce': 'Turkce', 'matematik': 'Matematik', 'fizik': 'Fizik',
             'kimya': 'Kimya', 'biyoloji': 'Biyoloji', 'tarih': 'Tarih', 'coğrafya': 'Cografya',
             'cografya': 'Cografya', 'felsefe': 'Felsefe', 'edebiyat': 'TDE', 'tde': 'TDE',
             'ingilizce': 'Ingilizce', 'english': 'Ingilizce'}
    if ders:
        ders = _NORM.get(ders.lower().strip(), ders)
    if sinav_turu:
        sinav_turu = sinav_turu.upper().strip()

    results = await yonlendir(ders=ders, sinav_turu=sinav_turu, tip=tip)
    if not results:
        return {"sonuc": "OGM materyal kataloğunda eşleşen kaynak yok. Filtreleri gevşet."}
    return {
        "kaynak_sayisi": len(results),
        "kaynaklar": [
            {
                "baslik": r["konu_adi"],
                "url": r["url"],
                "aciklama": r["icerik_ozet"],
                "kategori": r["icerik_tipi"],
                "sinav": r["sinif"],
                "ders": r["ders"],
            }
            for r in results
        ],
        "hatirlatma": "Bu MEB OGM Materyal resmi kaynaklaridir. Ogrenciye 2-3 link paylaş, 'Bu linke git, X kadar soru çöz, zorlandığını bana getir' gibi PROAKTIF yönlendirme yap.",
    }


# ─────────────────────────────────────────────────────────────────────────
# tool_search_curriculum (taşındı — fermat_core_agent.py:472-592)
# ─────────────────────────────────────────────────────────────────────────

async def search_curriculum(query: str = "", ders: str = "", sinav_turu: str = "") -> dict:
    """Müfredat bilgi bankasında semantik + keyword arama."""
    from rag_engine import search_curriculum as _rag_search
    if not query:
        return {"error": "query parametresi gerekli"}
    # Ders normalizasyonu
    _DERS_NORM = {'türkçe': 'Turkce', 'turkce': 'Turkce', 'matematik': 'Matematik',
                  'fizik': 'Fizik', 'kimya': 'Kimya', 'biyoloji': 'Biyoloji',
                  'tarih': 'Tarih', 'coğrafya': 'Cografya', 'cografya': 'Cografya',
                  'felsefe': 'Felsefe', 'geometri': 'Geometri',
                  'fen bilimleri': 'Fen Bilimleri', 'sosyal bilgiler': 'Sosyal Bilgiler',
                  'ingilizce': 'İngilizce', 'i̇ngilizce': 'İngilizce',
                  't.c. inkılap tarihi': 'T.C. İnkılap Tarihi'}
    if ders:
        ders = _DERS_NORM.get(ders.lower().strip(), ders)
    sinav_turu_clean = (sinav_turu or "").strip().upper() or None
    results = await _rag_search(query, ders=ders, limit=5, sinav_turu=sinav_turu_clean)
    # Yetersiz sonuç → ders filtresi olmadan tekrar
    if len(results) < 2 or (results and results[0]["skor"] < 0.5):
        results_broad = await _rag_search(query, ders="", limit=5)
        if results_broad and (not results or results_broad[0]["skor"] > results[0]["skor"]):
            results = results_broad
    # Keyword fallback — çıkmış soru görseli
    has_ogm = any("OGM Vision" in r.get("kaynak", "") for r in results)
    if not has_ogm or not results or results[0]["skor"] < 0.65:
        kw_results = await keyword_search_rag(query, ders=ders, limit=3)
        if kw_results:
            existing_ids = {r["id"] for r in results}
            for kr in kw_results:
                if kr["id"] not in existing_ids:
                    results.insert(0, kr)
            results = results[:5]
    # OGM konu özeti PDF link ekleme
    _global_ogm = None
    try:
        from ogm_catalog import yonlendir
        _q_low = query.lower()
        _ders_map = {'fizik': 'Fizik', 'matematik': 'Matematik', 'mat': 'Matematik', 'kimya': 'Kimya',
                     'biyoloji': 'Biyoloji', 'turkce': 'Turkce', 'türkçe': 'Turkce', 'tarih': 'Tarih',
                     'cografya': 'Cografya', 'coğrafya': 'Cografya', 'felsefe': 'Felsefe',
                     'edebiyat': 'TDE', 'tde': 'TDE', 'geometri': 'Matematik', 'basit makine': 'Fizik'}
        _detected = ders
        if not _detected:
            for k, v in _ders_map.items():
                if k in _q_low:
                    _detected = v
                    break
        if _detected:
            _ogm_list = await yonlendir(ders=_detected, tip="konu_ozeti")
            if _ogm_list:
                _global_ogm = [
                    {"baslik": r["konu_adi"], "url": r["url"]} for r in _ogm_list[:2]
                ]
    except Exception:
        pass

    if not results:
        resp = {"sonuc": "Bu konuda henüz müfredat içeriği yok. Kendi bilginle kapsamlı anlat."}
        if _global_ogm:
            resp["ogm_onerisi"] = _global_ogm
            resp["hatirlatma"] = "Cevabin sonunda MEB OGM konu ozeti PDF linkini ekle."
        return resp
    # OGM Vision parse — soru indeksi + yapılandırılmış metin
    import re as _re
    output = []
    for r in results:
        entry = {
            "ders": r["ders"],
            "konu": r["konu"],
            "baslik": r["baslik"],
            "icerik": r["icerik"],
            "zorluk": r["zorluk"],
            "soru_sayisi": r["soru_sayisi"],
            "benzerlik": r["skor"],
            "kaynak": r.get("kaynak", ""),
            "icerik_turu": r.get("icerik_turu", ""),
        }
        if "OGM Vision" in entry["kaynak"]:
            matches = _re.findall(r'SORU\s+(\d+)\s*\|\s*(\d{4})[-–](AYT|TYT)', entry["icerik"][:2000])
            if matches:
                entry["sayfadaki_sorular"] = [
                    {"soru_no": int(m[0]), "yil": int(m[1]), "sinav": m[2]}
                    for m in matches
                ]
            soru_blocks = _re.split(r'(?=SORU\s+\d+\s*\|)', entry["icerik"])
            parsed_sorular = []
            for block in soru_blocks:
                block = block.strip()
                if not block.startswith("SORU"):
                    continue
                header = _re.match(r'SORU\s+(\d+)\s*\|\s*(\d{4})[-–]?(AYT|TYT)?', block)
                if header:
                    soru_obj = {
                        "soru_no": int(header.group(1)),
                        "yil": header.group(2),
                        "sinav": header.group(3) or "?",
                        "metin": block[header.end():].strip()[:500],
                    }
                    siklar = _re.findall(r'([A-E]\))\s*(.+?)(?=[A-E]\)|$)', soru_obj["metin"], _re.DOTALL)
                    if siklar:
                        soru_obj["siklar"] = {s[0]: s[1].strip()[:100] for s in siklar}
                    parsed_sorular.append(soru_obj)
            if parsed_sorular:
                entry["sorular_parsed"] = parsed_sorular
        output.append(entry)
    final = {"sonuclar": output, "kayit_sayisi": len(output)}
    if _global_ogm:
        final["ogm_konu_ozeti"] = _global_ogm
        final["hatirlatma"] = "RAG'da bulunmayan konular veya detay isteyen ogrencilerde cevap sonuna MEB OGM konu ozeti PDF linkini ekle."
    return final


# ─────────────────────────────────────────────────────────────────────────
# tool_send_exam_image (taşındı — fermat_core_agent.py:595-631)
# ─────────────────────────────────────────────────────────────────────────

async def send_exam_image(kaynak: str = "", caption: str = "",
                          _caller_phone: str = "", _caller_channel: str = "") -> dict:
    """Çıkmış soru görselini kanala göre gönder.
    WhatsApp: send_wa_image / Web: CDN URL döndürür.
    """
    from whatsapp_bridge import kaynak_to_cdn_url

    if not kaynak or "OGM Vision" not in kaynak:
        return {"error": "Gecersiz kaynak — sadece 'OGM Vision' iceren kaynaklar desteklenir."}

    cdn_url = kaynak_to_cdn_url(kaynak)
    if not cdn_url:
        return {"error": f"CDN URL olusturulamadi: {kaynak}"}

    if _caller_channel == "web":
        return {
            "basarili": True,
            "kanal": "web",
            "image_url": cdn_url,
            "caption": caption or "YKS Cikmis Soru",
            "mesaj": "Gorsel URL hazir — web UI'sinda inline render edilecek.",
            "markdown": f"![{caption or 'YKS Soru'}]({cdn_url})",
        }

    # WhatsApp
    if not _caller_phone:
        return {"error": "Hedef telefon numarasi yok."}

    from whatsapp_bridge import send_wa_image
    ok = await send_wa_image(_caller_phone, cdn_url, caption or "YKS Cikmis Soru")
    if ok:
        return {"basarili": True, "kanal": "whatsapp", "mesaj": f"Gorsel gonderildi: {caption or kaynak}"}
    else:
        return {"basarili": False, "mesaj": "Gorsel gonderilemedi — text ile devam et."}


# ─────────────────────────────────────────────────────────────────────────
# tool_list_exam_questions (taşındı — fermat_core_agent.py:634-738)
# ─────────────────────────────────────────────────────────────────────────

async def list_exam_questions(konu: str = "", ders: str = "") -> dict:
    """Çıkmış soru kataloğu — split kayıtlar (her soru tek kayıt)."""
    import re
    from db_pool import get_pool
    _DERS_NORM = {'türkçe': 'Turkce', 'turkce': 'Turkce', 'matematik': 'Matematik',
                  'fizik': 'Fizik', 'kimya': 'Kimya', 'biyoloji': 'Biyoloji',
                  'tarih': 'Tarih', 'coğrafya': 'Cografya', 'cografya': 'Cografya',
                  'felsefe': 'Felsefe', 'geometri': 'Geometri'}
    if ders:
        ders = _DERS_NORM.get(ders.lower().strip(), ders)
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Sadece split kayıtlar
        conditions = [
            "kaynak LIKE '%OGM Vision%'",
            "kaynak LIKE '%split%'",
        ]
        params = []
        if konu:
            _TR = {'turev': 'türev', 'basinc': 'basınç', 'kaldirma': 'kaldırma',
                   'cember': 'çember', 'cembersel': 'çembersel', 'ucgen': 'üçgen',
                   'hucre': 'hücre', 'osmanli': 'osmanlı', 'esitsizlik': 'eşitsizlik',
                   'cozum': 'çözüm', 'olasilik': 'olasılık', 'isik': 'ışık',
                   'sicaklik': 'sıcaklık', 'kalitim': 'kalıtım', 'cozunurluk': 'çözünürlük'}
            konu_words = [w for w in konu.lower().split() if len(w) > 2]
            konu_conds = []
            for w in konu_words:
                params.append(f"%{w}%")
                idx = len(params)
                tr_w = _TR.get(w)
                if tr_w:
                    params.append(f"%{tr_w}%")
                    idx2 = len(params)
                    konu_conds.append(f"(konu ILIKE ${idx} OR konu ILIKE ${idx2})")
                else:
                    konu_conds.append(f"(konu ILIKE ${idx})")
            if konu_conds:
                conditions.append(f"({' OR '.join(konu_conds)})")
        if ders:
            params.append(f"%{ders}%")
            conditions.append(f"ders ILIKE ${len(params)}")

        where = " AND ".join(conditions)
        rows = await conn.fetch(f"""
            SELECT id, kaynak, konu, ders, icerik, baslik FROM rag_content
            WHERE {where} ORDER BY kaynak LIMIT 80
        """, *params)

        catalog = {}
        for r in rows:
            konu_adi = (r['konu'] or 'Genel').strip()
            if konu and konu_adi.lower() in ('fizik', 'kimya', 'biyoloji', 'biyoloji - genel', 'matematik'):
                continue

            m = re.search(r'SORU\s+(\d+)\s*\|\s*(\d{4})[-–](AYT|TYT)', r['baslik'] or '')
            if not m:
                m = re.search(r'SORU\s+(\d+)\s*\|\s*(\d{4})[-–](AYT|TYT)', r['icerik'] or '')
            if not m:
                continue
            soru_no, yil, sinav = m.group(1), m.group(2), m.group(3)

            if konu_adi not in catalog:
                catalog[konu_adi] = {}
            yil_key = f"{yil}-{sinav}"
            if yil_key not in catalog[konu_adi]:
                catalog[konu_adi][yil_key] = []
            catalog[konu_adi][yil_key].append({
                "soru_no": int(soru_no),
                "kaynak": r['kaynak'],
                "id": r['id'],
            })

        if not catalog:
            return {"sonuc": "Bu konuda cikmis soru bulunamadi."}

        result = []
        for konu_name, yillar in sorted(catalog.items()):
            entry = {"konu": konu_name, "yillar": {}}
            for yil, sorular in sorted(yillar.items(), reverse=True):
                entry["yillar"][yil] = [{"soru_no": s["soru_no"], "kaynak": s["kaynak"]} for s in sorular]
            entry["toplam_soru"] = sum(len(v) for v in yillar.values())
            result.append(entry)

        result.sort(key=lambda x: -x["toplam_soru"])
        return {
            "katalog": result[:10],
            "toplam_konu": len(result),
            "toplam_soru": sum(e["toplam_soru"] for e in result),
            "kullanim": "Ogrenciye yil ve konu secenekleri sun. Sectigi soruyu send_exam_image ile gonder."
        }


# ─────────────────────────────────────────────────────────────────────────
# tool_make_render_link (taşındı — fermat_core_agent.py:2093-2161)
# ─────────────────────────────────────────────────────────────────────────

async def make_render_link(html: str = "", title: str = "FermatAI Görsel",
                           ttl_days: int = 7, _caller_phone: str = "",
                           **_extra) -> dict:
    """Bot tool — kompleks HTML kaydet, kalıcı link ver."""
    if not html or not html.strip():
        return {
            "success": False,
            "error": (
                "❌ html PARAMETRESI BOS — Claude output truncated (kronik 3+ kez bug). "
                "ACIL HEMEN AŞAĞIDAKİNİ UYGULA:\n"
                "1) ⚡ ŞIMDI TEKRAR make_render_link CAGIR ama bu kez DAHA KISA HTML "
                "(max 60-80KB hedefli). Onceki uzun reasoning'i BIRAK, sadece kompakt HTML yaz: "
                "<!DOCTYPE html><html>...<canvas>+tek script CDN+~50 satır JS+formul...</html>\n"
                "2) ASLA reasoning yapma, ASLA kullaniciya 'tekrar dene' yazma — HEMEN tool retry.\n"
                "3) İkinci kez de empty olursa → o zaman ```3d preset'e gec (karadelik→blackhole, "
                "dna→dna_helix, atom→atom_proper, dalga→sine_wave, calabi→calabi_yau, "
                "kafes→lattice, manyetik→magnetic_field, su→water).\n"
                "4) Kullanici 'devam et' demek ZORUNDA KALMAMALI — sen hemen retry yap."
            ),
            "retry_now": True,
            "max_retry_size_kb": 80,
            "preset_fallback": ["blackhole", "dna_helix", "atom_proper", "sine_wave",
                                "calabi_yau", "lattice", "magnetic_field", "water", "sphere"]
        }
    html_size = len(html.encode('utf-8'))
    if html_size > 1024 * 1024:
        return {
            "success": False,
            "error": f"HTML cok buyuk ({html_size//1024}KB > 1024KB/1MB max). "
                     f"Daha kisa HTML uret (~200-400KB ideal) veya 22 renderer'dan birini kullan."
        }
    # 25.43-RENDER-QUALITY-GATE (Neo bug 10 May 20:21-20:58):
    # 5 deneme yapildi, 3'u "lacivert bos ekran". HTML create etmeden ONCE
    # quality skoru hesapla, threshold altindaysa direkt fail + bot retry et.
    # Bos canvas + 3D request mismatch = silent fail. Erken yakala.
    try:
        from render_endpoint import calculate_quality_score
        pre_score, pre_breakdown = calculate_quality_score(html, title)
    except Exception:
        pre_score, pre_breakdown = 0, {}

    QUALITY_THRESHOLD = 70  # 70 alti -> retry. 70-100 sun.
    is_3d_request = any(k in (title or "").lower() for k in [
        "3d", "simul", "evrim", "yildiz", "yıldız", "galaksi", "kuantum",
        "kara delik", "molek", "atom", "uzay", "yorunge", "yörünge"
    ])
    is_real_3d = pre_breakdown.get("3d_scene_complete", False)

    # Critical: 3D istendi ama gercek 3D scene yok = "lacivert bos ekran" (Neo bug)
    if is_3d_request and not is_real_3d:
        missing = [k for k, v in (pre_breakdown.get("3d_components") or {}).items() if not v]
        return {
            "success": False,
            "error": (
                f"❌ 3D simulasyon istendi ama HTML'de gercek 3D scene YOK. "
                f"'{title}' baslikli render bos canvas/lacivert ekran cikacak. "
                f"\n\n🔧 EKSIK BILESENLER: {', '.join(missing) if missing else 'tüm 3D motor parçaları'}. "
                f"\n\n⚡ HEMEN RETRY:\n"
                f"1) Ya ```3d preset kullan (blackhole/dna_helix/atom_proper/sine_wave/calabi_yau/lattice/magnetic_field/water/sphere)\n"
                f"2) Ya HTML'de SUNLAR'i ekle: new THREE.Scene + PerspectiveCamera + WebGLRenderer + scene.add(mesh) + requestAnimationFrame\n"
                f"3) CDN: three@0.147 (UMD), examples/js/controls/OrbitControls.js — three@0.149+ ASLA"
            ),
            "quality_score": pre_score,
            "missing_3d_components": missing,
            "retry_now": True,
            "preset_fallback": ["blackhole", "dna_helix", "atom_proper", "sine_wave",
                                "calabi_yau", "lattice", "magnetic_field", "water", "sphere"],
        }

    # Genel quality threshold
    if pre_score < QUALITY_THRESHOLD:
        return {
            "success": False,
            "error": (
                f"⚠️ HTML kalite skoru DUSUK ({pre_score}/100, esik {QUALITY_THRESHOLD}). "
                f"Kullanicinin gormesi sakincalı — geri don, daha zengin uret. "
                f"\n\nKalite breakdown: {pre_breakdown}\n\n"
                f"⚡ HEMEN RETRY:\n"
                f"1) Daha zengin DOM (heading + paragraf + canvas/svg + interaktif element)\n"
                f"2) Inline CSS (renkli gradient, padding, border)\n"
                f"3) Bilgilendirici icerik (legend, label, aciklama)\n"
                f"4) Min 30KB HTML (cok kisa = bos hissiyat)"
            ),
            "quality_score": pre_score,
            "quality_breakdown": pre_breakdown,
            "retry_now": True,
        }

    try:
        from render_endpoint import create_artifact
        ttl = max(1, min(30, int(ttl_days or 7)))
        uuid = await create_artifact(html=html, title=title,
                                      creator_phone=_caller_phone or "",
                                      ttl_days=ttl)
        if not uuid:
            return {
                "success": False,
                "error": "Kayit hatasi (DB veya backend). Tekrar deneyin veya 12 renderer kullanın."
            }
        import os
        base = os.getenv("PUBLIC_BASE_URL", "https://api.fermategitimkurumlari.com").rstrip("/")
        url = f"{base}/render/{uuid}"
        from datetime import datetime, timedelta
        return {
            "success": True,
            "url": url,
            "uuid": uuid,
            "ttl_days": ttl,
            "quality_score": pre_score,
            "size_kb": round(html_size / 1024, 1),
            "expires_at": (datetime.now() + timedelta(days=ttl)).isoformat(),
            "kullanim": f"Ogrenciye 'Buyuk gorseli ac: {url}' diye sun. Mobilde tek tikla acilir."
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


__all__ = [
    "keyword_search_rag", "ogm_yonlendir", "search_curriculum",
    "send_exam_image", "list_exam_questions", "make_render_link",
]
