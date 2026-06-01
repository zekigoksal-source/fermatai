"""
deepseek_handler.py — DeepSeek matematik akıl yürütme (Oturum 25.54, Neo dikey-AI)
=================================================================================
DeepSeek matematik/fizik akıl yürütmede sınıf lideri + ~1/20 fiyat. Foto-çözüm
"çözüm üretme" adımına opsiyonel güç katmanı: MathPix temiz matematik metni
çıkardığında DeepSeek kanonik adım-adım çözümü üretir → Claude Vision'a CONTEXT
olarak verilir (Claude pedagojik sunumu yapar). Kalite↑ maliyet↓.

⚠️ KVKK: DeepSeek'e SADECE anonim akademik içerik (soru metni) gider — öğrenci
adı/telefon/soz_no ASLA. Çin merkezli; kişisel veri gönderilmez.

⚠️ KEY-GATED: DEEPSEEK_API_KEY yoksa is_available()=False → hiç çağrılmaz, mevcut
akış (Claude Vision tek başına) AYNEN devam eder. Sıfır davranış değişikliği.
Aktive: .env'e DEEPSEEK_API_KEY ekle.

Kullanım:
  from deepseek_handler import is_available, solve_math
  if is_available():
      sol = await solve_math(problem_text)   # anonim soru metni
"""
from __future__ import annotations

import os
import asyncio
from loguru import logger

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
# deepseek-reasoner = R-serisi akıl yürütme; deepseek-chat = genel. Math için reasoner.
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-reasoner")


def is_available() -> bool:
    """DEEPSEEK_API_KEY set mi? Değilse hiç çağrılmaz (mevcut akış korunur)."""
    return bool(DEEPSEEK_API_KEY)


_MATH_SYSTEM = (
    "Sen YKS/LGS matematik-fizik uzmanısın. Verilen soruyu ADIM ADIM, doğru ve "
    "Türkçe çöz. Her adımı numaralandır, formülleri ayrı satıra yaz, sonucu net "
    "belirt. Sadece çözümü ver — selamlama/giriş yok. Soru belirsizse en olası "
    "yorumu al ve varsayımını belirt."
)


async def solve_math(problem_text: str, system: str = "", max_tokens: int = 1500) -> str | None:
    """Anonim soru metnini DeepSeek ile çöz. KVKK: PII GÖNDERME. Hata/keysiz → None."""
    if not is_available():
        return None
    if not problem_text or len(problem_text.strip()) < 5:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE, timeout=30.0)
        resp = await asyncio.to_thread(
            client.chat.completions.create,
            model=DEEPSEEK_MODEL,
            max_tokens=max_tokens,
            temperature=0.2,
            messages=[
                {"role": "system", "content": system or _MATH_SYSTEM},
                {"role": "user", "content": problem_text[:4000]},  # PII'siz soru metni
            ],
        )
        msg = resp.choices[0].message
        # deepseek-reasoner reasoning'i ayrı alanda tutabilir — content yeterli
        text = (getattr(msg, "content", "") or "").strip()
        if text:
            logger.info(f"🧮 DeepSeek çözüm: {DEEPSEEK_MODEL} | {len(text)} char")
            return text
    except Exception as e:
        logger.warning(f"[deepseek] solve_math hatası ({type(e).__name__}): {str(e)[:120]}")
    return None


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    async def _main():
        print(f"DEEPSEEK_API_KEY set: {is_available()}")
        if is_available():
            sol = await solve_math("f(x)=x^2 ise f'(2) kaçtır?")
            print(sol)
        else:
            print("(key yok — solve_math() None döner, mevcut akış korunur)")

    asyncio.run(_main())
