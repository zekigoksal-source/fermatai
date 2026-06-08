"""WhatsApp access token kurulum aracı (Neo çalıştırır).

GÜVENLİK: Token bu kodda YOK — Neo İNTERAKTİF yapıştırır. Araç:
  1. Token'ı Graph API'ye karşı DOĞRULAR (geçerli mi?)
  2. EXPIRY'sini gösterir (kalıcı mı, kaç gün?) → 24 saatlikse uyarır
  3. Geçerliyse /opt/fermatai/.env → WA_ACCESS_TOKEN günceller
  4. Bridge'i restart eder + health doğrular

Kullanım (VPS'te):  cd /opt/fermatai/eyotek_agent && python set_wa_token.py
"""
import asyncio
import os
import re
import sys
from pathlib import Path

ENV = Path("/opt/fermatai/.env")
sys.path.insert(0, "/opt/fermatai/eyotek_agent")
from dotenv import load_dotenv
load_dotenv(ENV, override=True)
import httpx


async def main():
    pnid = os.getenv("WA_PHONE_NUMBER_ID", "").strip()
    ver = os.getenv("GRAPH_API_VERSION", "v25.0")
    appid = os.getenv("FB_APP_ID", ""); appsec = os.getenv("FB_APP_SECRET", "")
    print("=" * 60)
    print("WhatsApp Access Token Kurulumu")
    print("=" * 60)
    print("Yeni token'ı yapıştır (Enter'a bas):")
    tok = input("Token: ").strip()
    if len(tok) < 30:
        print("❌ Token çok kısa görünüyor — iptal."); return

    async with httpx.AsyncClient(timeout=20) as c:
        # 1) Doğrula
        r = await c.get(f"https://graph.facebook.com/{ver}/{pnid}",
                        params={"access_token": tok, "fields": "verified_name,display_phone_number,quality_rating"})
        if r.status_code != 200:
            err = (r.json() or {}).get("error", {})
            print(f"❌ Token GEÇERSİZ — code={err.get('code')}: {str(err.get('message'))[:140]}")
            print("   Kurulum yapılmadı. Doğru token'ı al ve tekrar dene.")
            return
        d = r.json()
        print(f"✅ Token GEÇERLİ — {d.get('verified_name')} / {d.get('display_phone_number')} / kalite={d.get('quality_rating')}")

        # 2) Expiry
        if appid and appsec:
            rd = await c.get(f"https://graph.facebook.com/{ver}/debug_token",
                             params={"input_token": tok, "access_token": f"{appid}|{appsec}"})
            dd = (rd.json() or {}).get("data", {})
            exp = dd.get("expires_at"); typ = dd.get("type")
            if exp == 0:
                print(f"   🟢 KALICI TOKEN (hiç bitmez, type={typ}) — MÜKEMMEL, bir daha yenileme gerekmez!")
            elif exp:
                import datetime as _dt, time as _t
                days = round((exp - _t.time()) / 86400, 1)
                when = _dt.datetime.utcfromtimestamp(exp).strftime("%d %b %Y %H:%M")
                print(f"   ⚠️ Bu token {days} GÜN sonra ({when} UTC) EXPIRE olacak (type={typ}).")
                if days < 2:
                    print("   ⛔ 24 saatlik GEÇİCİ token! Production için System User PERMANENT token al")
                    print("      (Business Settings → System Users → Generate Token → Expiration: Never).")
                else:
                    print("   ℹ️ Çalışır ama kalıcı değil. İdeal: System User permanent token.")

    # 3) .env güncelle
    txt = ENV.read_text(encoding="utf-8")
    if re.search(r"^WA_ACCESS_TOKEN=", txt, re.M):
        txt = re.sub(r"^WA_ACCESS_TOKEN=.*$", f"WA_ACCESS_TOKEN={tok}", txt, flags=re.M)
    else:
        txt = txt.rstrip() + f"\nWA_ACCESS_TOKEN={tok}\n"
    ENV.write_text(txt, encoding="utf-8")
    print("✅ /opt/fermatai/.env güncellendi.")

    # 4) Restart + health
    print("Bridge restart ediliyor...")
    os.system("sudo systemctl restart fermatai-bridge")
    await asyncio.sleep(8)
    rc = os.system("systemctl is-active --quiet fermatai-bridge")
    print("✅ Bridge restart edildi" if rc == 0 else "⚠️ Bridge durumunu kontrol et: systemctl status fermatai-bridge")
    print("\nKurulum tamam. WhatsApp gönderimi tekrar aktif olmalı. 🎉")


if __name__ == "__main__":
    asyncio.run(main())
