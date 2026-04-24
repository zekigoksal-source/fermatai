"""
Classroom Metrics — Classroom Management Çekirdek #6
======================================================
Neo'ya günlük rapor — öğrencilerin sınıf yönetimi özeti.
  - Kaç öğrenci konuştu, ortalama mesaj
  - Kaç drift alarmı oluştu
  - Kaç redirect yapıldı
  - Token verimi (%akademik vs %off-topic)
  - Budget uyarısı alan öğrenciler
  - En çok off-topic konu

Scheduler: her gün 20:00'da daily_report'a eklenebilir.
"""
from __future__ import annotations
from loguru import logger


async def build_classroom_report() -> str:
    """Bugünkü classroom management metriklerini derle."""
    try:
        from db_pool import db_fetch, db_fetchval
        from token_budget import role_limit

        lines = ["🎓 *Classroom Management — Günlük Rapor*", "━━━━━━━━━━━━━━━━━━━━━"]

        # 1) Token kullanımı özeti
        try:
            rows = await db_fetch(
                """
                SELECT phone, role, token_used, msg_count
                FROM fermat.token_budget_daily
                WHERE gun = CURRENT_DATE
                ORDER BY token_used DESC
                """
            )
            if rows:
                toplam_token = sum((r["token_used"] or 0) for r in rows)
                toplam_msg = sum((r["msg_count"] or 0) for r in rows)
                warn_count = 0
                exceeded_count = 0
                for r in rows:
                    tok = r["token_used"] or 0
                    limit = role_limit(r["role"] or "ogrenci")
                    if limit:
                        oran = tok / limit
                        if oran >= 1.0:
                            exceeded_count += 1
                        elif oran >= 0.75:
                            warn_count += 1

                lines.append(f"📊 *Trafik:* {len(rows)} kişi · {toplam_msg} mesaj · {toplam_token:,} token")
                if warn_count:
                    lines.append(f"⚠ {warn_count} öğrenci %75+ budget (nazik uyarı)")
                if exceeded_count:
                    lines.append(f"🔴 {exceeded_count} öğrenci limit aşımı (Claude durdu)")

                # Top 3 token
                lines.append("")
                lines.append("🥇 *En çok konuşan 3 kişi:*")
                for r in rows[:3]:
                    tok = r["token_used"] or 0
                    cnt = r["msg_count"] or 0
                    limit = role_limit(r["role"] or "ogrenci")
                    oran = round(tok / limit * 100, 0) if limit else None
                    phone = (r["phone"] or "????")[-4:]
                    bar = "🟢"
                    if oran and oran >= 90:
                        bar = "🔴"
                    elif oran and oran >= 75:
                        bar = "🟡"
                    oran_s = f" ({oran}%)" if oran else ""
                    lines.append(f"  {bar} ***{phone}** — {tok:,} tok / {cnt} msg{oran_s}")
        except Exception as _te:
            lines.append(f"_Token özeti alınamadı: {_te}_")

        # 2) Drift / off-topic raporu
        try:
            from conversation_drift import classify_message
            from collections import Counter

            rows = await db_fetch(
                """
                SELECT phone, content
                FROM fermat.agent_conversations
                WHERE created_at::date = CURRENT_DATE
                  AND message_role = 'user'
                  AND role = 'ogrenci'
                  AND COALESCE(session_id,'') NOT LIKE '_test_%'
                """
            )
            if rows:
                cats = Counter()
                for r in rows:
                    c = classify_message(r["content"] or "")
                    cats[c] += 1
                total = sum(cats.values())

                lines.append("")
                lines.append("🧭 *Drift Analizi (öğrenci mesajları):*")
                for c in ["akademik", "pedagojik", "kisisel", "off_topic", "belirsiz"]:
                    cnt = cats.get(c, 0)
                    pct = round(cnt / total * 100, 0) if total else 0
                    emoji = {"akademik": "📚", "pedagojik": "🎯", "kisisel": "💙",
                             "off_topic": "🎮", "belirsiz": "❓"}.get(c, "•")
                    lines.append(f"  {emoji} {c}: {cnt} ({pct}%)")

                # Verimlilik skoru
                akademik_pct = (cats.get("akademik", 0) + cats.get("pedagojik", 0)) / total if total else 0
                if akademik_pct >= 0.75:
                    lines.append(f"\n✅ *Sınıf verimliliği: %{round(akademik_pct*100)}* (hedef %75+, başarı)")
                elif akademik_pct >= 0.5:
                    lines.append(f"\n🟡 *Sınıf verimliliği: %{round(akademik_pct*100)}* (hedef %75+)")
                else:
                    lines.append(f"\n🔴 *Sınıf verimliliği: %{round(akademik_pct*100)}* — sohbet ağırlıklı")
        except Exception as _de:
            lines.append(f"_Drift özeti alınamadı: {_de}_")

        lines.append("━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"_Otomatik rapor — FermatAI Classroom Mgmt_")
        return "\n".join(lines)
    except Exception as e:
        return f"Classroom rapor hatası: {e}"


if __name__ == "__main__":
    import asyncio, sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    async def test():
        report = await build_classroom_report()
        print(report)

    asyncio.run(test())
