"""
academic_service — Akademik veri tool'ları (Oturum 25.41-REFACTOR, 9 May)
=========================================================================

fermat_core_agent.py'den taşınan akademik tool fonksiyonları:
  - get_student_analytics  (167 satır) — öğrenci profil + sınav + devamsızlık + davranış
  - get_class_summary      (53 satır)  — sınıf öğrenci listesi + ortalama net
  - search_students        (216 satır) — Türkçe normalize'lı isim/sınıf arama
  - query_analytics        (188 satır) — SQL ACL guard + cache + execute
  - get_ayt_analysis       (63 satır)  — AYT bazlı net + sıralama
  - branch_zayif_konu      (110 satır) — branş bazlı zayıf konu top-N
  - transfer_failure       (88 satır)  — sınıf düşüş analizi
  - ogrenci_peer_kiyas     (63 satır)  — öğrenci-akran karşılaştırma
  - student_heatmap        (60 satır)  — sınıf/öğrenci konu hata heatmap

Mimari ilke (memory: project_monolith_korunsun.md):
    "Brain centralized (fermat_core_agent), execution modular (services/)"

fermat_core_agent.py orchestrator olarak kalır:
- Tool dispatcher table 1-line lambda ile bu service'i çağırır
- Prompt + intent + LLM çağrısı orchestrator'da, query mantığı burada

Test: pytest services/test_academic_service.py
"""
from __future__ import annotations
from typing import Any, Optional


# ─────────────────────────────────────────────────────────────────────────
# tool_get_student_analytics (taşındı — fermat_core_agent.py:241-407)
# ─────────────────────────────────────────────────────────────────────────

async def get_student_analytics(student_id: str, include_sections: list[str] | None = None) -> dict:
    """Öğrenci analytics — PostgreSQL'den çek."""
    from db_pool import db_fetch as _db_fetch
    sections = include_sections or ["all"]
    include_all = "all" in sections
    result: dict[str, Any] = {"student_id": student_id, "found": False}

    # Öğrenci temel bilgisi
    rows = await _db_fetch(
        """SELECT * FROM students
           WHERE eyotek_id = $1
              OR lower(full_name) LIKE lower($2)
              OR lower(first_name) LIKE lower($2)
           LIMIT 5""",
        student_id,
        f"%{student_id}%",
    )
    if not rows:
        return {**result, "message": f"'{student_id}' için kayıt bulunamadı."}

    result["found"] = True
    result["students"] = rows[:5]
    main = rows[0]
    eid = main.get("eyotek_id", student_id)

    # Sınavlar
    if include_all or "exams" in sections:
        soz = main.get("soz_no") or eid
        exams = await _db_fetch(
            """SELECT exam_name, exam_date, turkce, matematik, geometri, fizik, kimya, biyoloji, toplam
               FROM student_exams
               WHERE soz_no = $1
               ORDER BY exam_date DESC NULLS LAST LIMIT 5""",
            int(soz) if soz else 0,
        )
        result["exams"] = exams
        if exams:
            nets = [float(r.get("toplam", 0) or 0) for r in exams if r.get("toplam")]
            result["avg_net"] = round(sum(nets) / len(nets), 2) if nets else 0
        analysis = await _db_fetch(
            """SELECT ham_puan, yerlesme_puani, oncelikli_konular, sinav_sayisi
               FROM student_exam_analysis WHERE soz_no::text = $1 LIMIT 1""",
            str(soz),
        )
        if analysis:
            result["exam_analysis"] = analysis[0]

    # Devamsızlık
    if include_all or "attendance" in sections:
        soz = main.get("soz_no") or eid
        devam = await _db_fetch(
            "SELECT toplam_saat FROM devamsizlik_sayisi WHERE soz_no = $1 LIMIT 1",
            int(soz) if soz else 0,
        )
        result["absence_total_hours"] = devam[0]["toplam_saat"] if devam else 0
        # NOT (Oturum 25.29): attendance tablosu deprecated
        result["absences"] = []
        result["absence_count"] = result.get("absence_total_hours", 0)

    # Ödemeler
    if include_all or "payments" in sections:
        payments = await _db_fetch(
            """SELECT tutar, borc, odeme, bakiye, vade_tarihi
               FROM overdue_payments
               WHERE eyotek_id = $1 OR soz_no = $1
               LIMIT 5""",
            eid,
        )
        result["overdue_payments"] = payments

    # Davranış kayıtları
    if include_all or "behaviour" in sections:
        behaviour = await _db_fetch(
            """SELECT tarih, tur, aciklama, puan, ogretmen
               FROM student_behaviour
               WHERE eyotek_id = $1 OR soz_no = $1
               ORDER BY tarih DESC LIMIT 10""",
            eid,
        )
        result["behaviour"] = behaviour

    # Bireysel sınav sonuçları
    if include_all or "exams" in sections:
        try:
            soz_int = int(eid) if isinstance(eid, str) and eid.isdigit() else eid
        except Exception:
            soz_int = eid
        personal_exams = await _db_fetch(
            """SELECT exam_name as sinav_adi, exam_date as tarih,
                      toplam as net,
                      turkce, matematik, geometri, fizik, kimya, biyoloji,
                      tarih as h_tarih, cografya, felsefe, din_kulturu
               FROM student_exams
               WHERE soz_no::text = $1::text
               ORDER BY exam_date DESC LIMIT 15""",
            str(soz_int) if soz_int else str(eid),
        )
        if personal_exams:
            result["personal_exams"] = personal_exams
            nets = [float(r.get("net", 0) or 0) for r in personal_exams if r.get("net")]
            if nets:
                result["avg_net"] = round(sum(nets) / len(nets), 2)

    # Sınav birleştirme analizi
    if include_all or "exams" in sections:
        exam_analysis = await _db_fetch(
            """SELECT ham_puan, yerlesme_puani, ham_sira, yerlesme_sirasi,
                      ders_netleri, oncelikli_konular, sinav_sayisi, katilan_sinav,
                      toplam_net, toplam_dogru, toplam_yanlis, toplam_bos,
                      osym_2025_ham, osym_2025_yer, last_sync
               FROM student_exam_analysis
               WHERE eyotek_id = $1 OR soz_no = $1
               ORDER BY last_sync DESC LIMIT 1""",
            eid,
        )
        if exam_analysis:
            ea = exam_analysis[0]
            result["exam_analysis"] = {
                "ham_puan": ea.get("ham_puan"),
                "yerlesme_puani": ea.get("yerlesme_puani"),
                "siralama": ea.get("ham_sira"),
                "ders_netleri": ea.get("ders_netleri"),
                "oncelikli_konular": ea.get("oncelikli_konular"),
                "sinav_sayisi": ea.get("sinav_sayisi"),
                "toplam_net": ea.get("toplam_net"),
                "last_sync": str(ea.get("last_sync", "")),
            }

    # Etkileşim istatistikleri
    interactions = await _db_fetch(
        """SELECT konu, mesaj_sayisi FROM student_interactions
           WHERE eyotek_id = $1 ORDER BY mesaj_sayisi DESC LIMIT 5""",
        eid,
    )
    if interactions:
        result["interaction_stats"] = interactions

    # Pedagojik özet
    absence_count = result.get("absence_count", 0)
    avg_net = result.get("avg_net", 0)
    risk_level = "düşük"
    if absence_count > 10 or avg_net < 10:
        risk_level = "yüksek"
    elif absence_count > 5 or avg_net < 20:
        risk_level = "orta"

    result["pedagogical_summary"] = {
        "name": main.get("full_name", ""),
        "class": main.get("class_name", ""),
        "program": main.get("program", ""),
        "avg_net": avg_net,
        "absence_count": absence_count,
        "risk_level": risk_level,
        "overdue_debt": bool(result.get("overdue_payments")),
    }
    return result


# ─────────────────────────────────────────────────────────────────────────
# tool_search_students (taşındı — fermat_core_agent.py:322-377)
# ─────────────────────────────────────────────────────────────────────────

async def search_students(query: str, limit: int = 5) -> dict:
    """Öğrenci adına veya sınıfa göre ara. query='istatistik' ile genel ozet dondurur."""
    from db_pool import db_fetch as _db_fetch
    # Istatistik modu
    if query.lower().strip() in ("istatistik", "sayı", "sayi", "toplam", "kac", "kaç", "özet", "tüm", "tum", "hepsi"):
        stats = await _db_fetch("""
            SELECT class_name, devre, COUNT(*) as cnt
            FROM students
            WHERE status IS NULL OR status != 'Silinmiş'
            GROUP BY class_name, devre
            ORDER BY devre, class_name
        """)
        total = sum(r["cnt"] for r in stats)
        devre_summary = {}
        for r in stats:
            d = r.get("devre") or "Tanimsiz"
            devre_summary[d] = devre_summary.get(d, 0) + r["cnt"]
        return {
            "query": query,
            "mode": "istatistik",
            "total_students": total,
            "devre_summary": devre_summary,
            "class_details": [{"class": r.get("class_name") or "?", "devre": r.get("devre") or "?", "count": r["cnt"]} for r in stats],
            "count": total,
        }

    # Türkçe normalize: küçük→BÜYÜK Türkçe (DB uppercase saklıyor)
    _TR_TO_UPPER = str.maketrans("iığşüöç", "İIĞŞÜÖÇ")
    q_tr_upper = query.translate(_TR_TO_UPPER).upper()
    # ASCII versiyonu da dene
    _TR_TO_ASCII = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    q_ascii = query.translate(_TR_TO_ASCII)

    rows = await _db_fetch(
        """SELECT eyotek_id, soz_no, full_name, class_name, sube, program, status
           FROM students
           WHERE full_name  ILIKE $1
              OR class_name ILIKE $1
              OR sube       ILIKE $1
              OR full_name  ILIKE $2
              OR class_name ILIKE $2
              OR TRANSLATE(full_name, 'ÇĞİÖŞÜçğıöşü', 'CGIOSUcgiosu') ILIKE $3
              OR eyotek_id  = $4
              OR soz_no     = $4
           LIMIT $5""",
        f"%{query}%",
        f"%{q_tr_upper}%",
        f"%{q_ascii.upper()}%",
        query,
        limit,
    )
    return {
        "query":   query,
        "results": rows,
        "count":   len(rows),
    }


# ─────────────────────────────────────────────────────────────────────────
# tool_get_class_summary (taşındı — fermat_core_agent.py:268-319)
# ─────────────────────────────────────────────────────────────────────────

async def get_class_summary(class_name: str) -> dict:
    """Sınıf özeti — students + exam_results + devamsızlık."""
    from db_pool import db_fetch as _db_fetch
    students = await _db_fetch(
        """SELECT eyotek_id, full_name, status
           FROM students
           WHERE lower(class_name) LIKE lower($1)""",
        f"%{class_name}%",
    )
    if not students:
        return {"class_name": class_name, "found": False, "message": "Sınıf bulunamadı"}

    ids = [s["eyotek_id"] for s in students if s.get("eyotek_id")]
    active_count = sum(1 for s in students if (s.get("status") or "") != "Silinmiş")

    # Son sınav ortalaması
    avg_net = 0.0
    if ids:
        exam_rows = await _db_fetch(
            """SELECT AVG(NULLIF(net, '')::float) as avg_net
               FROM exam_results
               WHERE eyotek_id = ANY($1::text[])""",
            ids,
        )
        if exam_rows and exam_rows[0].get("avg_net"):
            avg_net = round(float(exam_rows[0]["avg_net"]), 2)

    # Devamsızlık (attendance deprecated, devamsizlik_sayisi'den)
    abs_count = 0
    if ids:
        try:
            abs_rows = await _db_fetch(
                """SELECT COALESCE(SUM(toplam_saat), 0) as cnt
                   FROM devamsizlik_sayisi
                   WHERE soz_no::text = ANY($1::text[])""",
                ids,
            )
            if abs_rows:
                abs_count = int(abs_rows[0].get("cnt", 0) or 0)
        except Exception:
            abs_count = 0

    return {
        "class_name":    class_name,
        "found":         True,
        "student_count": len(students),
        "active_count":  active_count,
        "avg_net":       avg_net,
        "total_absences": abs_count,
        "students":      students[:20],
    }


# ─────────────────────────────────────────────────────────────────────────
# tool_get_ayt_analysis (taşındı — fermat_core_agent.py:1146-1206)
# ─────────────────────────────────────────────────────────────────────────

async def get_ayt_analysis(soz_no: str) -> str:
    """AYT birleştir analizini döndür — sınav başı ortalama netlerle."""
    import json as _json
    from db_pool import get_pool
    _pool = await get_pool()
    async with _pool.acquire() as conn:
        r = await conn.fetchrow("""
            SELECT s.full_name, s.class_name,
                   sea.ham_puan_ayt, sea.yerlesme_puani_ayt,
                   sea.sinav_sayisi_ayt, sea.katilan_sinav_ayt,
                   sea.ders_netleri_ayt, sea.oncelikli_konular_ayt
            FROM student_exam_analysis sea
            LEFT JOIN students s ON s.soz_no::text = sea.soz_no::text
            WHERE sea.soz_no::text = $1
        """, str(soz_no))

    if not r or not r['ham_puan_ayt']:
        return _json.dumps({
            'error': f'Ogrenci {soz_no} icin AYT birlestir verisi yok (sinav_sayisi_ayt<1 veya kayit yok).',
            'oneri': 'Ogrencinin 12.SAY/EA/Mezun degilse AYT girmez. Bu dogal.',
        }, ensure_ascii=False)

    katilan = max(1, r['katilan_sinav_ayt'] or 1)
    netler_raw = r['ders_netleri_ayt']
    if isinstance(netler_raw, str):
        netler_raw = _json.loads(netler_raw)

    # Ortalama netler (sınav başı) — Toplam satırını atla, aynı ders 2x ise MAX soru seç
    by_ders = {}
    for n in netler_raw or []:
        d = (n.get('ders') or '').strip()
        if not d or d.lower() in ('toplam', 'total'):
            continue
        if not (d.startswith('YKS_') or d.startswith('AYT_')):
            continue
        def _pf(v):
            try: return float(str(v).replace(',','.'))
            except: return 0.0
        net = _pf(n.get('net'))
        soru = _pf(n.get('soru'))
        if d not in by_ders or soru > by_ders[d]['soru']:
            by_ders[d] = {'net': net, 'soru': soru}

    ort_netler = {}
    for d, v in by_ders.items():
        ort_netler[d.replace('YKS_','').replace('AYT_','')] = {
            'ortalama_net': round(v['net']/katilan, 2),
            'soru_sayisi': round(v['soru']/katilan, 0),
        }

    return _json.dumps({
        'full_name': r['full_name'],
        'sinif': r['class_name'],
        'sinav_sayisi_ayt': r['sinav_sayisi_ayt'],
        'katilan_sinav': katilan,
        'ham_puan_ayt': r['ham_puan_ayt'],
        'yerlesme_puani_ayt': r['yerlesme_puani_ayt'],
        'ortalama_netler': ort_netler,
        'NOT': 'Netler sinav BASI ORTALAMA (Birlestir analiz: toplam/katilan_sinav). Yerlesme puani RESMI hesap.',
    }, ensure_ascii=False, default=str)


# ─────────────────────────────────────────────────────────────────────────
# tool_branch_zayif_konu (taşındı — fermat_core_agent.py:1207-1314)
# ─────────────────────────────────────────────────────────────────────────

async def branch_zayif_konu(**kwargs) -> dict:
    """Öğretmen branş analizi — sınıf geneli ders+konu zayıf ortalamaları.
    Merve 65 mesaj örneğinden: 8 query_analytics zinciri tek çağrıya iniyor.
    """
    from db_pool import db_fetch
    ders = (kwargs.get("ders") or "").strip()
    if not ders:
        return {"error": "ders zorunlu"}
    sinif_list = kwargs.get("sinif_list") or []
    if isinstance(sinif_list, str):
        sinif_list = [s.strip() for s in sinif_list.split(",") if s.strip()]

    # Konu bazlı ortalama başarı (topic_tracker)
    # INVERSION FIX (Berf bug 10 May): sinav_hata_yuzdesi = HATA %.
    # En zayıf konular = EN YÜKSEK ortalama hata. ASC sıralama yanlış sonuç verirdi.
    try:
        if sinif_list:
            konular = await db_fetch(
                """SELECT t.konu,
                          (100 - AVG(t.sinav_hata_yuzdesi))::numeric(10,1) AS ort_basari,
                          AVG(t.sinav_hata_yuzdesi)::numeric(10,1) AS ort_hata,
                          COUNT(DISTINCT t.soz_no) AS ogr_sayisi
                   FROM student_topic_tracker t
                   JOIN students s ON s.soz_no::int = t.soz_no
                   WHERE LOWER(t.ders) LIKE LOWER($1)
                     AND s.sube = ANY($2::text[])
                     AND t.sinav_hata_yuzdesi IS NOT NULL
                     AND (t.tamamlandi IS NULL OR t.tamamlandi=FALSE)
                     AND COALESCE(t.status,'') != 'metadata'
                     AND t.konu NOT LIKE 'Ortalama %'
                   GROUP BY t.konu
                   HAVING AVG(t.sinav_hata_yuzdesi) >= 30
                   ORDER BY ort_hata DESC NULLS LAST
                   LIMIT 10""",
                f"%{ders}%", sinif_list
            )
        else:
            konular = await db_fetch(
                """SELECT konu,
                          (100 - AVG(sinav_hata_yuzdesi))::numeric(10,1) AS ort_basari,
                          AVG(sinav_hata_yuzdesi)::numeric(10,1) AS ort_hata,
                          COUNT(DISTINCT soz_no) AS ogr_sayisi
                   FROM student_topic_tracker
                   WHERE LOWER(ders) LIKE LOWER($1)
                     AND sinav_hata_yuzdesi IS NOT NULL
                     AND (tamamlandi IS NULL OR tamamlandi=FALSE)
                     AND COALESCE(status,'') != 'metadata'
                     AND konu NOT LIKE 'Ortalama %'
                   GROUP BY konu
                   HAVING AVG(sinav_hata_yuzdesi) >= 30
                   ORDER BY ort_hata DESC NULLS LAST
                   LIMIT 10""",
                f"%{ders}%"
            )
    except Exception as e:
        return {"error": f"query hata: {e}"}

    # Öğrenci bazlı ders ort net (student_exams kolon bazlı)
    ders_col_map = {
        "fizik": "fizik", "kimya": "kimya", "biyoloji": "biyoloji",
        "matematik": "matematik", "geometri": "geometri",
        "turkce": "turkce", "türkçe": "turkce", "edebiyat": "turkce",
        "tarih": "tarih", "cografya": "cografya", "coğrafya": "cografya",
        "felsefe": "felsefe", "din": "din_kulturu",
    }
    ders_l = ders.lower()
    col = None
    for k, v in ders_col_map.items():
        if k in ders_l:
            col = v
            break

    ogr_zayif = []
    if col:
        try:
            if sinif_list:
                ogr_zayif = await db_fetch(
                    f"""SELECT e.soz_no, e.student_name,
                             AVG(e.{col})::numeric(10,2) AS ort_net,
                             COUNT(*) AS sinav_sayisi
                        FROM student_exams e
                        JOIN students s ON s.soz_no::int = e.soz_no
                        WHERE e.{col} IS NOT NULL
                          AND s.sube = ANY($1::text[])
                        GROUP BY e.soz_no, e.student_name
                        HAVING COUNT(*) >= 2
                        ORDER BY ort_net ASC
                        LIMIT 5""",
                    sinif_list
                )
            else:
                ogr_zayif = await db_fetch(
                    f"""SELECT soz_no, student_name,
                             AVG({col})::numeric(10,2) AS ort_net,
                             COUNT(*) AS sinav_sayisi
                        FROM student_exams
                        WHERE {col} IS NOT NULL
                        GROUP BY soz_no, student_name
                        HAVING COUNT(*) >= 2
                        ORDER BY ort_net ASC
                        LIMIT 5"""
                )
        except Exception:
            pass

    return {
        "ders": ders,
        "sinif_list": sinif_list,
        "konu_zayif_siralamasi": [dict(r) for r in konular] if konular else [],
        "en_zayif_ogrenciler": [dict(r) for r in ogr_zayif] if ogr_zayif else [],
        "yorum": (
            f"{ders} dersinde {len(konular)} konu analizi, "
            f"{len(ogr_zayif)} en zayif ogrenci tespit edildi. "
            "Tek cagriyla sinif brans panorama."
        ),
    }


# ─────────────────────────────────────────────────────────────────────────
# tool_transfer_failure (taşındı — fermat_core_agent.py:1213-1298)
# ─────────────────────────────────────────────────────────────────────────

async def transfer_failure(**kwargs) -> dict:
    """Konu başarısı vs sınav başarısı cross — transfer failure tespiti.
    Öğrenci 'test kitabında yapıyorum denemede yapamıyorum' dediğinde bu tool.
    """
    from db_pool import db_fetch
    soz_no = kwargs.get("soz_no")
    if not soz_no:
        return {"error": "soz_no zorunlu"}
    try:
        soz_no = int(soz_no)
    except Exception:
        return {"error": "gecersiz soz_no"}

    # Topic tracker başarı (ders bazlı ortalama)
    # INVERSION FIX: sinav_hata_yuzdesi = HATA %. ort_basari = 100 - ort_hata.
    topic_avg = await db_fetch(
        """SELECT ders,
                  (100 - AVG(sinav_hata_yuzdesi))::numeric(10,1) AS ort_basari,
                  AVG(sinav_hata_yuzdesi)::numeric(10,1) AS ort_hata,
                  COUNT(*) AS konu_sayisi
           FROM student_topic_tracker
           WHERE soz_no=$1 AND sinav_hata_yuzdesi IS NOT NULL
             AND (tamamlandi IS NULL OR tamamlandi=FALSE)
             AND COALESCE(status,'') != 'metadata'
             AND konu NOT LIKE 'Ortalama %'
           GROUP BY ders""",
        soz_no
    )

    # Son 5 sınavdaki ders bazlı ortalama net
    exams = await db_fetch(
        """SELECT AVG(matematik)::numeric(10,1) AS mat,
                  AVG(fizik)::numeric(10,1) AS fiz,
                  AVG(kimya)::numeric(10,1) AS kim,
                  AVG(biyoloji)::numeric(10,1) AS bio,
                  AVG(turkce)::numeric(10,1) AS turkce
           FROM (
             SELECT * FROM student_exams
             WHERE soz_no::text=$1 AND status='valid'
             ORDER BY exam_date DESC LIMIT 5
           ) recent""",
        str(soz_no)
    )
    exam_nets = dict(exams[0]) if exams else {}

    # Transfer gap tespiti
    transfer_gaps = []
    ders_to_net_key = {
        "Matematik": "mat", "Geometri": "mat", "Fizik": "fiz",
        "Kimya": "kim", "Biyoloji": "bio", "Turkce": "turkce", "Türkçe": "turkce"
    }

    for row in topic_avg:
        ders = row["ders"]
        topic_basari = float(row["ort_basari"] or 0)
        if topic_basari < 40:
            continue  # zaten zayıf, transfer gap değil

        net_key = ders_to_net_key.get(ders)
        if not net_key:
            continue
        raw_net = exam_nets.get(net_key)
        if raw_net is None:
            continue
        raw_net = float(raw_net)

        # Max net referansı (TYT'ye göre)
        max_net = {"mat": 30, "fiz": 7, "kim": 7, "bio": 6, "turkce": 40}.get(net_key, 30)
        exam_basari = (raw_net / max_net) * 100 if max_net else 0

        # Gap: topic_basari >> exam_basari
        gap = topic_basari - exam_basari
        if gap > 20:  # %20+ fark = transfer gap
            transfer_gaps.append({
                "ders": ders,
                "konu_basari_pct": round(topic_basari, 1),
                "sinav_basari_pct": round(exam_basari, 1),
                "gap_pct": round(gap, 1),
                "ort_net": round(raw_net, 1),
                "yorum": f"{ders} konularda %{topic_basari:.0f} başarı, sınavda %{exam_basari:.0f} — {round(gap,0)}% transfer gap",
            })

    transfer_gaps.sort(key=lambda x: -x["gap_pct"])
    return {
        "soz_no": soz_no,
        "transfer_gap_sayisi": len(transfer_gaps),
        "tespit_edilen_dersler": transfer_gaps,
        "yorum": (
            "Transfer gap: öğrenci konuyu 'tanıyor' ama sınav koşullarında yapamıyor. "
            "Çözüm: daha fazla süreli deneme, zamana karşı çözüm, yanlış soru defteri analizi."
            if transfer_gaps else
            "Transfer gap yok — konu başarısı ve sınav başarısı uyumlu."
        ),
    }


# ─────────────────────────────────────────────────────────────────────────
# tool_student_heatmap (taşındı — fermat_core_agent.py:2079-2135)
# ─────────────────────────────────────────────────────────────────────────

async def student_heatmap(soz_no_list: list = None, ders: str = "",
                          weeks: int = 8, _caller_role: str = "ogrenci",
                          _caller_phone: str = "", **_extra) -> dict:
    """Öğrenci × konu performans heatmap — sınıf karşılaştırma.
    Sadece öğretmen+ rol görür (ACL). Sonuç ```heatmap renderer formatında.
    """
    import json
    try:
        if _caller_role not in ("admin", "mudur", "ogretmen", "rehber"):
            return {"success": False, "error": "Bu tool sadece öğretmen+ icin"}
        from db_pool import db_fetch
        if not soz_no_list:
            return {"success": False, "error": "soz_no_list gerekli (orn: [137, 138, 139])"}
        # Öğrenci adları + konu × öğrenci hata yüzdesi matrisi
        rows = await db_fetch(
            f"""SELECT s.full_name, t.konu, ROUND(AVG(t.hata_yuzdesi)::numeric, 0) as avg_hata
                FROM students s
                JOIN student_topic_tracker t ON s.soz_no::text = t.soz_no::text
                WHERE s.soz_no = ANY($1::int[])
                  AND ($2 = '' OR t.ders = $2)
                  AND t.created_at > NOW() - INTERVAL '{int(weeks or 8)} weeks'
                GROUP BY s.full_name, t.konu
                ORDER BY t.konu, s.full_name""",
            [int(x) for x in soz_no_list], ders
        )
        if not rows:
            return {"success": False, "error": "Veri yok (öğrenciler veya ders eşleşmiyor)"}
        # Pivot: y=konu, x=öğrenci, value=hata%
        students = sorted({r["full_name"] for r in rows})
        konular = sorted({r["konu"] for r in rows})
        matrix = [[0 for _ in students] for _ in konular]
        for r in rows:
            yi = konular.index(r["konu"])
            xi = students.index(r["full_name"])
            matrix[yi][xi] = int(r["avg_hata"] or 0)
        return {
            "success": True,
            "students": students,
            "konular": konular,
            "matrix": matrix,
            "ders_filter": ders or "tüm dersler",
            "weeks": int(weeks or 8),
            "heatmap_block": (
                "```heatmap\n"
                + json.dumps({
                    "title": f"{ders or 'Tüm Dersler'} — Konu × Öğrenci Hata Haritası ({weeks} hafta)",
                    "x": [s.split()[0] for s in students],
                    "y": konular,
                    "values": matrix,
                }, ensure_ascii=False)
                + "\n```"
            ),
            "kullanim": "heatmap_block alanini direkt cevabina yapistir, frontend render eder",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


__all__ = ["get_student_analytics", "search_students", "get_class_summary",
           "get_ayt_analysis", "branch_zayif_konu", "transfer_failure",
           "student_heatmap"]
