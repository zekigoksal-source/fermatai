"""class_rosters_dump.json → PostgreSQL class_roster tablosu"""
import asyncio, json, os
from dotenv import load_dotenv
load_dotenv(override=True)
from db_pool import get_pool as _get_pool

async def save():
    with open("class_rosters_dump.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    pool = await _get_pool()
    conn = await pool.acquire()
    await conn.execute("DELETE FROM class_roster")
    count = 0
    for sinif_name, info in data.items():
        devre = info.get("devre", "")
        for st in info.get("students", []):
            # Turkce header key'leri (lowercase)
            soz_no = st.get("söz no", "") or st.get("soz no", "")
            ad = st.get("adı", "") or st.get("adi", "")
            soyad = st.get("soyadı", "") or st.get("soyadi", "")
            okul_no = st.get("okul no", "")
            mudur = st.get("müdür", "") or st.get("mudur", "")
            rehber = st.get("rehber", "")
            sinif_ogr = st.get("sınıf öğretmeni", "") or st.get("sinif ogretmeni", "")
            danisman = st.get("danışman", "") or st.get("danisman", "")
            mudur_yrd = st.get("müdür yardımcısı", "") or st.get("mudur yardimcisi", "")
            if not soz_no:
                continue
            await conn.execute(
                """INSERT INTO class_roster
                    (sinif, devre, soz_no, okul_no, ad, soyad,
                     mudur, mudur_yardimcisi, rehber, sinif_ogretmeni, danisman)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                ON CONFLICT (sinif, soz_no) DO UPDATE SET
                    ad = EXCLUDED.ad, soyad = EXCLUDED.soyad,
                    last_sync = CURRENT_TIMESTAMP""",
                sinif_name, devre, soz_no, okul_no, ad, soyad,
                mudur, mudur_yrd, rehber, sinif_ogr, danisman,
            )
            count += 1

    await conn.execute(
        "UPDATE data_freshness SET last_sync = CURRENT_TIMESTAMP WHERE module = 'class_roster'"
    )

    total = await conn.fetchval("SELECT COUNT(*) FROM class_roster")
    print(f"class_roster: {count} ogrenci yazildi, toplam={total}")

    rows = await conn.fetch(
        "SELECT sinif, COUNT(*) as cnt FROM class_roster GROUP BY sinif ORDER BY sinif"
    )
    for r in rows:
        print(f"  {r['sinif']}: {r['cnt']}")

    await pool.release(conn)

asyncio.run(save())
