"""
FermatAI — Pedagojik Koc (Hafta 6)
===================================
Ogrenci kisisel kocluk modulu:
  - Pomodoro: 25dk calisma + 5dk mola
  - Feynman teknigi: kavrami baskasina anlatir gibi
  - Gunluk calisma hedefi: zayif konularla
  - Motivasyon: trend bazli
  - Mola onerisi: 90dk arali calisma
  - Calisma rutini onerisi (sabah/aksam tipine gore)

GECE MESAJ YASAK: 08:00-20:00 arasi proaktif mesaj. Disinda sadece reaktif.

Komutlar (ogrenci):
  - "pomodoro basla [konu]" → 25dk timer
  - "pomodoro durdur" → erken bitir
  - "feynman [konu]" → kavram tartismasi
  - "bugun ne calisayim" → personalize plan
  - "calisma istatistigim" → kendi takip
  - "motivasyon" → trend bazli destek

Komutlar (admin):
  - "koc istatistik" → tum ogrencilerin pomodoro/feynman aktivitesi
"""

import asyncio
import json
import sys
from datetime import datetime, time, timedelta
from typing import Optional

from loguru import logger
from db_pool import get_pool as _get_pool, db_fetch, db_fetchrow, db_fetchval, db_execute

# Aktif pomodoro session'lari (in-memory)
ACTIVE_POMODOROS: dict[str, dict] = {}
# {phone: {'start': datetime, 'duration': 25, 'konu': '...', 'soz_no': '...'}}


async def ensure_koc_table():
    """pedagojik_koc_log tablosu yoksa olustur."""
    await db_execute("""
        CREATE TABLE IF NOT EXISTS pedagojik_koc_log (
            id SERIAL PRIMARY KEY,
            soz_no TEXT,
            phone TEXT,
            tip TEXT,  -- pomodoro_basla, pomodoro_bitir, feynman, plan_iste
            konu TEXT,
            sure_dk INTEGER,
            durum TEXT,  -- tamamlandi, yarida_birakildi
            notlar TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)


def is_calisma_saati() -> bool:
    """Calisma saati: 08-23 (gece mesaj yasak ama reaktif yanit serbest)."""
    h = datetime.now().hour
    return 7 <= h < 23


# ─────────────────────────────────────────
# POMODORO
# ─────────────────────────────────────────

async def pomodoro_basla(phone: str, soz_no: str, konu: str = "",
                         duration_min: int = 25) -> str:
    """Pomodoro baslat."""
    await ensure_koc_table()
    if phone in ACTIVE_POMODOROS:
        existing = ACTIVE_POMODOROS[phone]
        elapsed = (datetime.now() - existing['start']).total_seconds() / 60
        return (
            f"⏱️ *Zaten aktif pomodoro var!*\n"
            f"Konu: _{existing.get('konu', 'belirtilmemis')}_\n"
            f"Gecen sure: *{elapsed:.0f} dk* / {existing['duration']} dk\n\n"
            f"_'pomodoro durdur' yazarak iptal et._"
        )

    ACTIVE_POMODOROS[phone] = {
        'start': datetime.now(),
        'duration': duration_min,
        'konu': konu,
        'soz_no': soz_no,
    }

    # DB log
    try:
        await db_execute("""
            INSERT INTO pedagojik_koc_log
              (soz_no, phone, tip, konu, sure_dk, durum)
            VALUES ($1,$2,'pomodoro_basla',$3,$4,'baslatildi')
        """, soz_no, phone, konu, duration_min)
    except Exception as e:
        logger.debug(f"pomodoro log err: {e}")

    return (
        f"🍅 *POMODORO BAŞLADI*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📚 Konu: *{konu or 'Genel calisma'}*\n"
        f"⏰ Sure: *{duration_min} dk*\n"
        f"🎯 Bitis: *{(datetime.now() + timedelta(minutes=duration_min)).strftime('%H:%M')}*\n\n"
        f"💡 *Kurallar:*\n"
        f"  • Telefonu sessize al\n"
        f"  • Sosyal medya YOK\n"
        f"  • Sadece *bu konuya* odaklan\n"
        f"  • Su ic, oturus duzelt\n\n"
        f"_'pomodoro durdur' ile iptal edebilirsin._\n"
        f"_Bittiginde \"pomodoro bitti\" yazabilirsin._"
    )


async def pomodoro_durdur(phone: str, soz_no: str, tamamlandi: bool = False) -> str:
    """Aktif pomodoro durdur."""
    if phone not in ACTIVE_POMODOROS:
        return "⚠️ Aktif pomodoro yok. _'pomodoro basla [konu]' ile baslayabilirsin._"

    p = ACTIVE_POMODOROS.pop(phone)
    elapsed = (datetime.now() - p['start']).total_seconds() / 60
    durum = 'tamamlandi' if tamamlandi or elapsed >= p['duration'] - 2 else 'yarida_birakildi'

    try:
        await db_execute("""
            INSERT INTO pedagojik_koc_log
              (soz_no, phone, tip, konu, sure_dk, durum, notlar)
            VALUES ($1,$2,'pomodoro_bitir',$3,$4,$5,$6)
        """, soz_no, phone, p.get('konu'), int(elapsed), durum,
             f"hedef:{p['duration']}, gercek:{elapsed:.1f}")
    except Exception as e:
        logger.debug(f"pomodoro log err: {e}")

    if durum == 'tamamlandi':
        return (
            f"🎉 *POMODORO TAMAMLANDI*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📚 Konu: *{p.get('konu', '?')}*\n"
            f"⏱️ Sure: *{elapsed:.0f} dk*\n\n"
            f"☕ *5 dakika MOLA zamani:*\n"
            f"  • Ayaga kalk, esne\n"
            f"  • Su ic\n"
            f"  • Pencereyi acik bak\n"
            f"  • Telefonu eline alma!\n\n"
            f"_Yeni pomodoro baslamak ister misin?_ 🍅"
        )
    else:
        return (
            f"⏸️ *Pomodoro yarida birakildi*\n"
            f"Konu: _{p.get('konu', '?')}_\n"
            f"Gecen sure: *{elapsed:.0f} dk* / {p['duration']} dk\n\n"
            f"_Sorun yok — tekrar baslamak istersen ben buradayim._ 💪"
        )


# ─────────────────────────────────────────
# FEYNMAN TEKNIGI
# ─────────────────────────────────────────

async def feynman_basla(phone: str, soz_no: str, konu: str) -> str:
    """Feynman teknigi: konuyu basit dilde anlatma denemesi."""
    if not konu:
        return "Hangi konuyu calisalim? Ornek: _'feynman turev'_"

    try:
        await db_execute("""
            INSERT INTO pedagojik_koc_log
              (soz_no, phone, tip, konu, durum)
            VALUES ($1,$2,'feynman',$3,'baslatildi')
        """, soz_no, phone, konu)
    except Exception as e:
        logger.debug(f"feynman log err: {e}")

    return (
        f"🧠 *FEYNMAN TEKNIGI — {konu}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"_(Bir konuyu gercekten anladigimizi anlamak icin baskasina ogretebilmemiz lazim — Richard Feynman)_\n\n"
        f"*ADIM 1:* Bana *{konu}* konusunu anlat.\n\n"
        f"❗ *Onemli kurallar:*\n"
        f"  • Sanki *5 yasinda bir cocuga* anlatiyormus gibi yaz\n"
        f"  • Akademik terim KULLANMA — basit kelimeler kullan\n"
        f"  • Ornekler ver — gunluk hayattan\n"
        f"  • Cumlerini *kisa* tut\n\n"
        f"*Hazirsan, simdi yaz — anlatmaya basla.* 📝\n"
        f"_(Anlatimin ardindan boslukta kaldigin yerleri sana gosterecegim)_"
    )


# ─────────────────────────────────────────
# GUNLUK PLAN
# ─────────────────────────────────────────

async def bugun_ne_calisayim(soz_no: str) -> str:
    """Ogrencinin zayif konulari + dengeli plan."""
    if not soz_no:
        return "Bunun icin sana ait sinav verisi gerekli. Ogretmenine danis."

    pool = await _get_pool()
    async with pool.acquire() as conn:
        weak = await conn.fetch("""
            SELECT ders, konu, sinav_hata_yuzdesi as basari
            FROM student_topic_tracker
            WHERE soz_no::text = $1
            AND tamamlandi = FALSE
            AND sinav_hata_yuzdesi < 50
            AND LENGTH(konu) > 5
            AND konu NOT LIKE 'Ortalama %'
            ORDER BY sinav_hata_yuzdesi ASC, RANDOM()
            LIMIT 6
        """, str(soz_no))

        student = await conn.fetchrow(
            "SELECT first_name, full_name FROM students WHERE soz_no::text=$1", str(soz_no))
    name = (student['first_name'] if student else None) or "arkadasim"

    if not weak:
        return (
            f"📅 *Bugunku Plan — {name}*\n\n"
            f"Henuz konu bazli zayif alan tespit edilmedi.\n"
            f"Bir kac deneme sonrasi sana ozel plan onerebilirim.\n\n"
            f"_Su an genel YKS muhfredatindan calismanı oneririm — TYT Matematik / Turkce / Fen / Sosyal._"
        )

    # 4 farkli ders sec (varsa)
    secilen = []
    seen_ders = set()
    for w in weak:
        if w['ders'] in seen_ders and len(secilen) >= 3:
            continue
        secilen.append(w)
        seen_ders.add(w['ders'])
        if len(secilen) >= 4:
            break

    lines = [
        f"📅 *BUGUNKU PLAN — {name}*\n",
        "_(Senin zayif noktalarindan ozel olarak hazirlandi)_\n",
        "━━━━━━━━━━━━━━━━━━━━━━━",
    ]

    sureler = [50, 40, 40, 30]  # toplam ~160 dk = 6.5 pomodoro
    for i, (w, s) in enumerate(zip(secilen, sureler), 1):
        emoji = "🔴" if (w['basari'] or 0) < 20 else "🟠" if (w['basari'] or 0) < 40 else "🟡"
        pomodoro_sayi = max(1, s // 25)
        lines.append(f"\n*{i}. {w['ders']}* — _{w['konu'][:40]}_")
        lines.append(f"   {emoji} Mevcut basari: %{(w['basari'] or 0):.0f}")
        lines.append(f"   ⏰ Sure: *{s} dk* (~{pomodoro_sayi} pomodoro)")

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 *Yontem:*")
    lines.append("  1. Konu anlatimi izle / oku (10dk)")
    lines.append("  2. 10-15 ornek soru coz")
    lines.append("  3. Yanlislari INCELE — neden yanlisti kayit et")
    lines.append("  4. 5dk MOLA — sonra siradaki ders")
    lines.append("\n_'pomodoro basla [konu]' yazarak ilk seansa baslayabilirsin._ 🍅")

    return "\n".join(lines)


# ─────────────────────────────────────────
# CALISMA ISTATISTIGI
# ─────────────────────────────────────────

async def calisma_istatistigi(soz_no: str, days: int = 7) -> str:
    """Ogrencinin pomodoro/feynman aktivitesi."""
    await ensure_koc_table()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT tip, COUNT(*) as cnt, SUM(sure_dk) as sure,
                   COUNT(*) FILTER (WHERE durum='tamamlandi') as tamamlanan
            FROM pedagojik_koc_log
            WHERE soz_no::text = $1
            AND created_at >= NOW() - INTERVAL '{days} days'
            GROUP BY tip
        """, str(soz_no))

        by_konu = await conn.fetch(f"""
            SELECT konu, COUNT(*) as cnt
            FROM pedagojik_koc_log
            WHERE soz_no::text = $1
            AND created_at >= NOW() - INTERVAL '{days} days'
            AND konu IS NOT NULL AND konu != ''
            GROUP BY konu
            ORDER BY cnt DESC LIMIT 5
        """, str(soz_no))

    if not rows:
        return (
            f"📊 *Son {days} Gun Calisma Istatistigi*\n\n"
            f"Henuz pomodoro/feynman kaydin yok.\n"
            f"_'pomodoro basla [konu]' ile basla — alismam icin biraz veri lazim._ 🍅"
        )

    lines = [f"📊 *SON {days} GUN CALISMA*\n", "━━━━━━━━━━━━━━━━━━━━━━━"]

    for r in rows:
        if r['tip'] == 'pomodoro_basla':
            continue  # bitirilenleri sayariz
        emoji = {'pomodoro_bitir': '🍅', 'feynman': '🧠', 'plan_iste': '📅'}.get(r['tip'], '✨')
        lines.append(f"\n{emoji} *{r['tip']}*: {r['cnt']} kez")
        if r['sure']:
            lines.append(f"   ⏱️ Toplam: *{r['sure']} dk*")
        if r['tamamlanan'] is not None:
            lines.append(f"   ✅ Tamamlanan: {r['tamamlanan']}")

    if by_konu:
        lines.append("\n*En cok calisilan konular:*")
        for k in by_konu:
            lines.append(f"  • {k['konu'][:35]} ({k['cnt']}x)")

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("_'bugun ne calisayim' yazarak personalize plan al._")
    return "\n".join(lines)


# ─────────────────────────────────────────
# KOC ISTATISTIGI (admin)
# ─────────────────────────────────────────

async def koc_kurum_istatistik(days: int = 7) -> str:
    """Tum ogrencilerin pomodoro/feynman aktivitesi (admin icin)."""
    await ensure_koc_table()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        overall = await conn.fetchrow(f"""
            SELECT
              COUNT(*) FILTER (WHERE tip='pomodoro_basla') as pomodoro_baslayan,
              COUNT(*) FILTER (WHERE tip='pomodoro_bitir' AND durum='tamamlandi') as pomodoro_tamamlanan,
              COUNT(*) FILTER (WHERE tip='feynman') as feynman_sayisi,
              COUNT(DISTINCT soz_no) as aktif_ogrenci
            FROM pedagojik_koc_log
            WHERE created_at >= NOW() - INTERVAL '{days} days'
        """)

        top_users = await conn.fetch(f"""
            SELECT k.soz_no, s.full_name, COUNT(*) as toplam
            FROM pedagojik_koc_log k
            LEFT JOIN students s ON s.soz_no::text = k.soz_no::text
            WHERE k.created_at >= NOW() - INTERVAL '{days} days'
            AND k.tip IN ('pomodoro_bitir','feynman')
            GROUP BY k.soz_no, s.full_name
            ORDER BY toplam DESC LIMIT 5
        """)

    lines = [
        f"🎓 *PEDAGOJIK KOC ISTATISTIGI — Son {days} Gun*\n",
        "━━━━━━━━━━━━━━━━━━━━━━━",
        f"👥 Aktif ogrenci: *{overall['aktif_ogrenci']}*",
        f"🍅 Baslatilan pomodoro: *{overall['pomodoro_baslayan']}*",
        f"✅ Tamamlanan pomodoro: *{overall['pomodoro_tamamlanan']}*",
        f"🧠 Feynman teknigi: *{overall['feynman_sayisi']}*",
    ]
    if overall['pomodoro_baslayan']:
        bitis_orani = 100 * (overall['pomodoro_tamamlanan'] or 0) / overall['pomodoro_baslayan']
        lines.append(f"📈 Tamamlama orani: *%{bitis_orani:.0f}*")

    if top_users:
        lines.append("\n🏆 *En Aktif Ogrenciler:*")
        for i, u in enumerate(top_users, 1):
            ad = (u['full_name'] or 'Bilinmeyen')[:25]
            lines.append(f"  {i}. {ad}: {u['toplam']} aktivite")

    return "\n".join(lines)


async def main():
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    if not args:
        await ensure_koc_table()
        print("✅ pedagojik_koc_log tablosu hazir")
        print("\nKomutlar:")
        print("  python pedagojik_koc.py kurum")
        print("  python pedagojik_koc.py plan 230")
        print("  python pedagojik_koc.py istat 230")
        return

    cmd = args[0]
    if cmd == "kurum":
        print(await koc_kurum_istatistik())
    elif cmd == "plan":
        soz = args[1] if len(args) > 1 else "230"
        print(await bugun_ne_calisayim(soz))
    elif cmd == "istat":
        soz = args[1] if len(args) > 1 else "230"
        print(await calisma_istatistigi(soz))


if __name__ == "__main__":
    asyncio.run(main())
