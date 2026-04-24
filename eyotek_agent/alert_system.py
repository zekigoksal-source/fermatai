"""
FermatAI — Akıllı Alarm & Bildirim Sistemi
=============================================
Tüm alarmlar ve bildirimler tek merkezden yönetilir.
NEO "aktif" diyene kadar hiçbir bildirim GÖNDERİLMEZ.

Alarm Türleri:
  1. risk_dusus      — 3 deneme üst üste net düşüşü
  2. devamsizlik     — devamsızlık eşiği aşıldı (50+ saat)
  3. duygu_kriz      — 7 günde 3+ negatif sinyal
  4. etut_eksik      — haftalık etüt katılımı düşük
  5. haftalik_ozet   — Pazar akşamı kurum özeti

Kullanım:
  python alert_system.py check          # Tüm alarmları kontrol et (göndermez)
  python alert_system.py test           # Test raporu üret (konsola yaz)
  python alert_system.py send           # SADECE AKTIF_MI=True ise gönder
  python alert_system.py stats          # Alarm istatistikleri
"""

import asyncio
import json
import os
import sys
from datetime import datetime, date, timedelta
from typing import Optional

from loguru import logger
from db_pool import get_pool as _get_pool, db_fetch, db_fetchrow, db_fetchval, db_execute

NEO_PHONE = "905051256802"

# ══════════════════════════════════════════════════════════════════════
# ⛔ ANA KONTROL — Neo "aktif" diyene kadar FALSE
# ══════════════════════════════════════════════════════════════════════
ALERTS_ACTIVE = False  # True olunca WP'ye gönderir, False = sadece log

# Alarm eşikleri — spam önleme: sadece gerçekten dikkat gerektiren durumlar
THRESHOLDS = {
    "deneme_dusus_sayisi": 2,       # 2+ üst üste düşüş → alarm
    "dusus_net_farki": -8,          # -8 net veya daha fazla düşüş (küçük dalgalanma alarm değil)
    "devamsizlik_saat": 100,        # 100+ saat devamsızlık → uyarı
    "devamsizlik_kritik": 200,      # 200+ saat → KRİTİK alarm
    "duygu_sinyal_sayisi": 3,       # 7 günde 3+ negatif sinyal
    "duygu_pencere_gun": 7,         # Duygu analizi penceresi
    "max_alarm_per_type": 5,        # Her alarm türünden max 5 göster (spam önleme)
}

# Alarm DB tablosu
CREATE_ALERTS_TABLE = """
CREATE TABLE IF NOT EXISTS alert_log (
    id SERIAL PRIMARY KEY,
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    target_phone TEXT NOT NULL,
    soz_no INT,
    student_name TEXT,
    message TEXT NOT NULL,
    sent BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_alert_type ON alert_log (alert_type, created_at);
"""


async def init_db():
    await db_execute(CREATE_ALERTS_TABLE)


# ══════════════════════════════════════════════════════════════════════
# ALARM 1: Deneme Net Düşüşü
# ══════════════════════════════════════════════════════════════════════

async def check_net_dusus() -> list[dict]:
    """Son 3 denemede üst üste düşüş gösteren öğrencileri tespit et."""
    pool = await _get_pool()
    alerts = []
    async with pool.acquire() as conn:
        # Her öğrencinin son 4 denemesini al
        students = await conn.fetch("""
            SELECT DISTINCT soz_no FROM student_exams WHERE toplam > 5
        """)

        for s in students:
            soz = s['soz_no']
            exams = await conn.fetch("""
                SELECT DISTINCT ON (exam_date) exam_name, toplam, exam_date
                FROM student_exams
                WHERE soz_no = $1 AND toplam > 5
                ORDER BY exam_date DESC NULLS LAST
                LIMIT 4
            """, soz)

            if len(exams) < 3:
                continue

            # Kronolojik sıra: exams[0]=en yeni, exams[-1]=en eski
            # Ardışık düşüş: her sınav bir öncekinden düşük mü?
            consecutive_drops = 0
            for i in range(len(exams) - 1):
                newer = exams[i]['toplam'] or 0
                older = exams[i+1]['toplam'] or 0
                if newer < older - 3:  # 3 net tolerans (küçük dalgalanma sayılmaz)
                    consecutive_drops += 1
                else:
                    break  # Ardışıklık bozuldu

            # Toplam düşüş: en yeni - en yüksek
            son_net = exams[0]['toplam'] or 0
            max_net = max((e['toplam'] or 0) for e in exams)
            total_drop = son_net - max_net

            if consecutive_drops >= THRESHOLDS["deneme_dusus_sayisi"] and total_drop < THRESHOLDS["dusus_net_farki"]:
                name_row = await conn.fetchrow(
                    "SELECT full_name, class_name FROM students WHERE soz_no::int = $1", soz)
                name = name_row['full_name'] if name_row else f"soz:{soz}"
                cls = name_row.get('class_name', '?') if name_row else '?'

                son_net = exams[0]['toplam']
                ilk_net = exams[-1]['toplam']

                alerts.append({
                    "type": "risk_dusus",
                    "severity": "kritik" if total_drop < -20 else "uyari",
                    "soz_no": soz,
                    "name": name,
                    "class": cls,
                    "son_net": round(son_net, 1),
                    "max_net": round(max_net, 1),
                    "dusus": round(total_drop, 1),
                    "ardisik_dusus": consecutive_drops,
                })

    return alerts


# ══════════════════════════════════════════════════════════════════════
# ALARM 2: Devamsızlık Eşiği
# ══════════════════════════════════════════════════════════════════════

async def check_devamsizlik() -> list[dict]:
    """Devamsızlık eşiğini aşan öğrencileri tespit et."""
    rows = await db_fetch("""
        SELECT d.soz_no, d.toplam_saat, s.full_name, s.class_name
        FROM devamsizlik_sayisi d
        JOIN students s ON d.soz_no = s.soz_no::int
        WHERE d.toplam_saat >= $1
        ORDER BY d.toplam_saat DESC
    """, THRESHOLDS["devamsizlik_saat"])

    alerts = []
    for r in rows:
        saat = r['toplam_saat']
        severity = "kritik" if saat >= THRESHOLDS["devamsizlik_kritik"] else "uyari"
        alerts.append({
            "type": "devamsizlik",
            "severity": severity,
            "soz_no": r['soz_no'],
            "name": r['full_name'],
            "class": r['class_name'] or '?',
            "saat": saat,
        })

    return alerts


# ══════════════════════════════════════════════════════════════════════
# ALARM 3: Duygu/Kriz Sinyali
# ══════════════════════════════════════════════════════════════════════

async def check_duygu_sinyal() -> list[dict]:
    """Son 7 günde 3+ negatif sinyal veren öğrencileri tespit et."""
    pencere = THRESHOLDS["duygu_pencere_gun"]
    esik = THRESHOLDS["duygu_sinyal_sayisi"]

    rows = await db_fetch(f"""
        SELECT si.soz_no, s.full_name, s.class_name,
               COUNT(*) as sinyal_sayisi,
               STRING_AGG(DISTINCT si.insight_type, ', ') as tipler,
               MAX(si.created_at)::date as son_sinyal
        FROM student_insights si
        JOIN students s ON si.soz_no = s.soz_no::int
        WHERE si.created_at >= CURRENT_DATE - INTERVAL '{pencere} days'
        AND si.insight_type IN ('negative', 'stressed', 'crisis', 'angry')
        GROUP BY si.soz_no, s.full_name, s.class_name
        HAVING COUNT(*) >= {esik}
        ORDER BY COUNT(*) DESC
    """)

    alerts = []
    for r in rows:
        has_crisis = 'crisis' in (r['tipler'] or '')
        severity = "kritik" if has_crisis or r['sinyal_sayisi'] >= 5 else "uyari"
        alerts.append({
            "type": "duygu_kriz",
            "severity": severity,
            "soz_no": r['soz_no'],
            "name": r['full_name'],
            "class": r['class_name'] or '?',
            "sinyal_sayisi": r['sinyal_sayisi'],
            "tipler": r['tipler'],
            "son_sinyal": str(r['son_sinyal']),
        })

    return alerts


# ══════════════════════════════════════════════════════════════════════
# ALARM 4: Haftalık Kurum Özeti
# ══════════════════════════════════════════════════════════════════════

async def generate_weekly_summary() -> str:
    """Haftalık kurum özet raporu oluştur."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        # 1. Haftalık konuşma istatistikleri
        conv_stats = await conn.fetchrow("""
            SELECT
                COUNT(*) FILTER (WHERE message_role='user') as mesaj,
                COUNT(DISTINCT phone) as kullanici
            FROM agent_conversations
            WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'
        """)

        # 2. En aktif öğrenciler
        aktif = await conn.fetch("""
            SELECT phone, COUNT(*) as cnt FROM agent_conversations
            WHERE message_role='user' AND created_at >= CURRENT_DATE - INTERVAL '7 days'
            GROUP BY phone ORDER BY cnt DESC LIMIT 5
        """)

        aktif_list = []
        for a in aktif:
            phone_clean = a['phone'].replace('+', '')
            # Önce ACL'den, sonra students'dan isim bul
            name_row = await conn.fetchrow(
                "SELECT full_name FROM acl_users WHERE REPLACE(phone,'+','') = $1", phone_clean)
            if not name_row:
                name_row = await conn.fetchrow(
                    "SELECT full_name FROM students WHERE REPLACE(phone,'+','') = $1", phone_clean)
            name = name_row['full_name'] if name_row else f"...{phone_clean[-4:]}"
            # Büyük harf düzeltme
            if name and name == name.upper() and len(name) > 2:
                parts = name.split()
                name = ' '.join(p.capitalize() for p in parts)
            aktif_list.append(f"  • {name}: {a['cnt']} mesaj")

        # 3. Deneme trendi (kurum ortalaması)
        trend = await conn.fetch("""
            SELECT exam_date, AVG(toplam) as ort, COUNT(DISTINCT soz_no) as katilim
            FROM student_exams
            WHERE toplam > 5 AND exam_date >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY exam_date
            ORDER BY exam_date DESC
            LIMIT 3
        """)

        trend_lines = []
        for t in trend:
            trend_lines.append(
                f"  • {t['exam_date'].strftime('%d.%m')}: ort *{t['ort']:.1f}* net ({t['katilim']} öğrenci)")

        # 5. RAG kullanımı (conn blok icinde)
        rag_count = await conn.fetchval("SELECT COUNT(*) FROM rag_content")

    # 4. Risk öğrencileri (conn kapandiktan sonra — kendi pool acquire yapiyorlar)
    risk_dusus = await check_net_dusus()
    risk_devam = await check_devamsizlik()
    risk_duygu = await check_duygu_sinyal()

    # Rapor oluştur
    now = datetime.now().strftime('%d.%m.%Y %H:%M')
    lines = [
        f"📊 *FermatAI — Haftalık Özet*",
        f"📅 {now}",
        f"",
        f"━━━━━━━━━━━━━━━━━━━━━━",
        f"",
        f"👥 *Kullanım:*",
        f"  • {conv_stats['mesaj']} mesaj, {conv_stats['kullanici']} kullanıcı",
        f"",
        f"🏆 *En Aktif:*",
    ]
    lines.extend(aktif_list[:5])

    if trend_lines:
        lines.append(f"\n📈 *Son Denemeler (kurum ort.):*")
        lines.extend(trend_lines)

    # Risk özeti
    kritik_count = sum(1 for a in risk_dusus if a['severity'] == 'kritik')
    uyari_count = sum(1 for a in risk_dusus if a['severity'] == 'uyari')
    devam_count = len(risk_devam)
    duygu_count = len(risk_duygu)

    lines.append(f"\n⚠️ *Risk Sinyalleri:*")
    if risk_dusus:
        lines.append(f"  🔴 Net düşüşü: {len(risk_dusus)} öğrenci ({kritik_count} kritik)")
        for a in risk_dusus[:3]:
            lines.append(f"    • {a['name']} ({a['class']}): {a['max_net']}→{a['son_net']} ({a['dusus']:+.0f})")
    if risk_devam:
        lines.append(f"  🟡 Devamsızlık: {devam_count} öğrenci (50+ saat)")
        for a in risk_devam[:3]:
            lines.append(f"    • {a['name']}: {a['saat']} saat")
    if risk_duygu:
        lines.append(f"  🟣 Duygu sinyali: {duygu_count} öğrenci")
        for a in risk_duygu[:3]:
            lines.append(f"    • {a['name']}: {a['sinyal_sayisi']} sinyal ({a['tipler']})")

    if not risk_dusus and not risk_devam and not risk_duygu:
        lines.append(f"  ✅ Risk sinyali yok — her şey yolunda!")

    lines.append(f"\n📚 *Müfredat:* {rag_count} konu RAG'da")
    lines.append(f"\n_FermatAI Otonom Rapor_")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════
# MERKEZ: Tüm Alarmları Çalıştır
# ══════════════════════════════════════════════════════════════════════

async def alarm_dry_run_audit() -> dict:
    """
    22.1l — ALERTS_ACTIVE=False iken kalibrasyon testi.
    ALARM YOLLAMAZ, sadece HANGI ESKIKLE HANGI OGRENCILER YAKALANACAK raporla.

    Neo yeni sezon öncesi: "şimdi 10 öğrenci alarm verirdi, eşikler uygun mu?" diye test.
    """
    results = {
        "aktif": ALERTS_ACTIVE,
        "esikler": THRESHOLDS,
        "net_dusus": await check_net_dusus(),
        "devamsizlik": await check_devamsizlik(),
        "duygu_kriz": await check_duygu_sinyal(),
    }
    ozet = {
        "aktif_flag": ALERTS_ACTIVE,
        "toplam_net_dusus": len(results["net_dusus"]),
        "toplam_devamsizlik": len(results["devamsizlik"]),
        "toplam_duygu": len(results["duygu_kriz"]),
        "toplam_alarm": len(results["net_dusus"]) + len(results["devamsizlik"]) + len(results["duygu_kriz"]),
        "esikler": THRESHOLDS,
        "ornekler": {
            "net_dusus": results["net_dusus"][:3],
            "devamsizlik": results["devamsizlik"][:3],
            "duygu_kriz": results["duygu_kriz"][:3],
        },
        "tavsiye": (
            "ALERTS_ACTIVE=False — simdi WP'ye alarm gitmiyor. "
            "Yeni sezon (1 Eylul 2026) öncesi ayarları kontrol et, gerekirse eşikler güncelle."
        ),
    }
    return ozet


async def run_all_checks() -> dict:
    """Tüm alarm kontrollerini çalıştır, sonuçları döndür."""
    await init_db()

    results = {
        "risk_dusus": await check_net_dusus(),
        "devamsizlik": await check_devamsizlik(),
        "duygu_kriz": await check_duygu_sinyal(),
    }

    # DB'ye logla
    pool = await _get_pool()
    async with pool.acquire() as conn:
        for alert_type, alerts in results.items():
            for a in alerts:
                await conn.execute("""
                    INSERT INTO alert_log (alert_type, severity, target_phone, soz_no, student_name, message, sent)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT DO NOTHING
                """, alert_type, a.get('severity', 'uyari'), NEO_PHONE,
                    a.get('soz_no', 0), a.get('name', '?'),
                    json.dumps(a, ensure_ascii=False, default=str), False)

    return results


def format_alert_message(results: dict) -> Optional[str]:
    """Alarm sonuçlarını WP mesajına dönüştür."""
    all_alerts = []
    for alerts in results.values():
        all_alerts.extend(alerts)

    if not all_alerts:
        return None  # Alarm yok, mesaj gönderme

    kritik = [a for a in all_alerts if a.get('severity') == 'kritik']
    uyari = [a for a in all_alerts if a.get('severity') == 'uyari']

    lines = [
        f"🚨 *FermatAI — Alarm Raporu*",
        f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        f"",
    ]

    max_show = THRESHOLDS.get("max_alarm_per_type", 5)

    if kritik:
        lines.append(f"🔴 *KRİTİK ({len(kritik)}):*")
        for a in kritik[:max_show]:
            if a['type'] == 'risk_dusus':
                lines.append(f"  ↘️ *{a['name']}* ({a['class']}): {a['max_net']:.0f}→{a['son_net']:.0f} ({a['dusus']:+.0f} net)")
            elif a['type'] == 'devamsizlik':
                lines.append(f"  ⛔ *{a['name']}* ({a['class']}): {a['saat']} saat")
            elif a['type'] == 'duygu_kriz':
                lines.append(f"  💔 *{a['name']}* ({a['class']}): {a['sinyal_sayisi']} sinyal")
        if len(kritik) > max_show:
            lines.append(f"  _...ve {len(kritik) - max_show} daha_")
        lines.append("")

    if uyari:
        lines.append(f"🟡 *UYARI ({len(uyari)}):*")
        for a in uyari[:max_show]:
            if a['type'] == 'risk_dusus':
                lines.append(f"  📉 {a['name']} ({a['class']}): {a['dusus']:+.0f} net")
            elif a['type'] == 'devamsizlik':
                lines.append(f"  ⏰ {a['name']} ({a['class']}): {a['saat']}s")
            elif a['type'] == 'duygu_kriz':
                lines.append(f"  😟 {a['name']} ({a['class']}): {a['sinyal_sayisi']} sinyal")
        if len(uyari) > max_show:
            lines.append(f"  _...ve {len(uyari) - max_show} daha_")

    lines.append(f"\n_Detay için: 'alarm detay [isim]' yaz_")
    return "\n".join(lines)


async def send_alerts(results: dict) -> bool:
    """Alarm mesajını NEO'ya WP ile gönder — SADECE AKTIF ise."""
    if not ALERTS_ACTIVE:
        logger.warning("⛔ ALERTS_ACTIVE=False — WP gönderim yapılmıyor")
        return False

    msg = format_alert_message(results)
    if not msg:
        logger.info("Alarm yok — mesaj gönderilmedi")
        return False

    try:
        from whatsapp_bridge import send_wa_message
        # 22.1n-kural1: _outreach=True — Neo dısındakilere guard'a takılır (Neo zaten whitelist)
        sent = await send_wa_message(NEO_PHONE, msg, _outreach=True, _reason="alert_system")
        if sent:
            # DB'de sent=True yap
            await db_execute(
                "UPDATE alert_log SET sent=TRUE WHERE sent=FALSE AND target_phone=$1",
                NEO_PHONE)
        return sent
    except Exception as e:
        logger.error(f"Alert gönderim hatası: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════

async def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"

    if cmd == "check":
        results = await run_all_checks()
        total = sum(len(v) for v in results.values())
        print(f"\n📊 Alarm Kontrolü: {total} alarm tespit edildi")
        for atype, alerts in results.items():
            if alerts:
                print(f"\n  {atype} ({len(alerts)}):")
                for a in alerts[:5]:
                    sev = "🔴" if a.get('severity') == 'kritik' else "🟡"
                    print(f"    {sev} {a.get('name','?')} ({a.get('class','?')})")
        if total == 0:
            print("  ✅ Alarm yok!")

    elif cmd == "test":
        results = await run_all_checks()
        msg = format_alert_message(results)
        if msg:
            print("\n=== ALARM MESAJI (test — gönderilmeyecek) ===\n")
            print(msg)
        else:
            print("Alarm yok.")

        print("\n=== HAFTALIK ÖZET (test) ===\n")
        summary = await generate_weekly_summary()
        print(summary)

    elif cmd == "send":
        if not ALERTS_ACTIVE:
            print("⛔ ALERTS_ACTIVE=False — Neo 'aktif' demeden gönderim yapılamaz!")
            print("   alert_system.py içinde ALERTS_ACTIVE = True yapın.")
            return
        results = await run_all_checks()
        await send_alerts(results)

    elif cmd == "stats":
        await init_db()
        pool = await _get_pool()
        async with pool.acquire() as conn:
            total = await conn.fetchval("SELECT COUNT(*) FROM alert_log")
            sent = await conn.fetchval("SELECT COUNT(*) FROM alert_log WHERE sent=TRUE")
            by_type = await conn.fetch(
                "SELECT alert_type, COUNT(*) as cnt FROM alert_log GROUP BY alert_type ORDER BY cnt DESC")
        print(f"\n📊 Alert Log: {total} toplam, {sent} gönderildi")
        for r in by_type:
            print(f"  {r['alert_type']}: {r['cnt']}")

    else:
        print("Kullanım: python alert_system.py [check|test|send|stats]")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
