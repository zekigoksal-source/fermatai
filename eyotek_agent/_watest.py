import asyncio
import sys
sys.path.insert(0, "/opt/fermatai/eyotek_agent")
from dotenv import load_dotenv
load_dotenv("/opt/fermatai/.env", override=True)
from model_health import check_wa_token


async def main():
    r = await check_wa_token()
    print("WA TOKEN KONTROL:", r["status"])
    print("  detay:", r["detail"][:160])


asyncio.run(main())
