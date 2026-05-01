"""
MathPix Snip API Client (Oturum 25.38)
=======================================
Foto soru OCR — el yazısı denklemler, matrisler, integraller, tablolar
Claude Vision'a göre 2-3x daha doğru matematik OCR.

API docs: https://docs.mathpix.com/#process-an-image

ENV:
  MATHPIX_APP_ID  — mathpix.com'dan free tier 200 req/ay
  MATHPIX_APP_KEY — API key

Kullanım:
  from mathpix_client import ocr_image
  result = await ocr_image(image_bytes)
  # result = {"success": True, "text": "...", "latex": "...", "confidence": 0.95, "is_math": True}

Maliyet:
  Free tier: 200 req/ay
  Sonrası: $0.004/req (yani 1000 req = $4)
  Tahmini ay başı maliyet: 125 öğrenci × ~3 foto/gün × %30 matematik = ~3000 req → ~$12/ay
"""

import asyncio
import base64
import os
from typing import Optional

import httpx
from loguru import logger

MATHPIX_APP_ID = os.getenv("MATHPIX_APP_ID", "")
MATHPIX_APP_KEY = os.getenv("MATHPIX_APP_KEY", "")
MATHPIX_URL = "https://api.mathpix.com/v3/text"
MATHPIX_TIMEOUT = 25.0  # MathPix genelde 2-5sn döner, 25sn safety


def is_available() -> bool:
    """MathPix yapılandırılmış mı?"""
    return bool(MATHPIX_APP_ID and MATHPIX_APP_KEY)


async def ocr_image(image_bytes: bytes, include_latex: bool = True,
                    include_asciimath: bool = True) -> dict:
    """
    Görüntüden matematik/text OCR.

    Returns:
        {
          "success": bool,
          "text": str,          # markdown + latex inline
          "latex": str,         # \\(...\\) inline LaTeX (varsa)
          "confidence": float,  # 0-1 arası
          "is_math": bool,      # matematiksel içerik var mı
          "error": str          # hata varsa
        }
    """
    if not is_available():
        return {"success": False, "error": "MATHPIX_APP_ID/KEY .env'de tanımsız"}

    try:
        # Base64 encode
        b64 = base64.b64encode(image_bytes).decode("ascii")

        formats = ["text"]
        if include_latex:
            formats.append("latex_styled")
        if include_asciimath:
            formats.append("asciimath")

        payload = {
            "src": f"data:image/jpeg;base64,{b64}",
            "formats": formats,
            "math_inline_delimiters": ["\\(", "\\)"],
            "math_display_delimiters": ["\\[", "\\]"],
            "rm_spaces": True,
            "include_smiles": False,  # kimya yapısı tahmin
        }

        headers = {
            "app_id": MATHPIX_APP_ID,
            "app_key": MATHPIX_APP_KEY,
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=MATHPIX_TIMEOUT) as client:
            r = await client.post(MATHPIX_URL, json=payload, headers=headers)
            r.raise_for_status()
            d = r.json()

        # Hata kontrol
        if d.get("error"):
            return {"success": False, "error": d.get("error_info", {}).get("message", d.get("error"))}

        text = d.get("text", "")
        latex = d.get("latex_styled", "")
        confidence = d.get("confidence", 0.0)
        is_math = d.get("is_printed") or d.get("is_handwritten") or False
        # Basit math heuristic
        if not is_math and any(c in text for c in ["\\(", "\\[", "=", "∫", "∑", "√", "²", "³"]):
            is_math = True

        return {
            "success": True,
            "text": text,
            "latex": latex,
            "confidence": float(confidence),
            "is_math": is_math,
            "raw": d,
        }
    except httpx.HTTPStatusError as e:
        msg = f"MathPix HTTP {e.response.status_code}"
        try:
            err_body = e.response.json()
            msg += f": {err_body.get('error', '')}"
        except Exception:
            pass
        logger.warning(msg)
        return {"success": False, "error": msg}
    except Exception as e:
        logger.warning(f"MathPix hata: {type(e).__name__}: {e}")
        return {"success": False, "error": str(e)}


async def ocr_with_fallback(image_bytes: bytes, fallback_fn=None) -> dict:
    """
    MathPix dener, başarısızsa fallback fonksiyonu çağırır.
    fallback_fn: async function(image_bytes) -> str
    """
    if not is_available():
        if fallback_fn:
            text = await fallback_fn(image_bytes)
            return {"success": True, "text": text, "source": "fallback"}
        return {"success": False, "error": "MathPix yok ve fallback verilmemiş"}

    res = await ocr_image(image_bytes)
    if res.get("success") and res.get("text"):
        res["source"] = "mathpix"
        return res

    if fallback_fn:
        text = await fallback_fn(image_bytes)
        return {"success": True, "text": text, "source": "fallback",
                "mathpix_error": res.get("error")}

    return res


def format_for_claude(mathpix_result: dict) -> str:
    """Claude'a context olarak verilmek üzere MathPix sonucunu formatla."""
    if not mathpix_result.get("success"):
        return ""

    text = mathpix_result.get("text", "")
    latex = mathpix_result.get("latex", "")
    conf = mathpix_result.get("confidence", 0.0)
    is_math = mathpix_result.get("is_math", False)

    if not text and not latex:
        return ""

    parts = ["[MathPix OCR — yüksek doğruluk matematik tanıma]"]
    if is_math:
        parts.append(f"Tip: Matematik içerik (güven: {conf:.0%})")
    else:
        parts.append(f"Tip: Genel metin (güven: {conf:.0%})")

    if text:
        parts.append(f"Metin (markdown+LaTeX inline):\n{text[:1500]}")
    if latex and latex != text:
        parts.append(f"Saf LaTeX:\n{latex[:800]}")

    parts.append(
        "\n[Bu OCR'yi referans al, ama görüntüye de bakarak çöz. "
        "MathPix bazen el yazısı operatörleri yanlış okur — şüphe edersen kendi OCR'na güven.]"
    )
    return "\n".join(parts)


# Test/CLI
if __name__ == "__main__":
    import sys
    from pathlib import Path

    if len(sys.argv) < 2:
        print("Kullanım: python mathpix_client.py <image_path>")
        print(f"Available: {is_available()}")
        if is_available():
            print(f"App ID: {MATHPIX_APP_ID[:8]}...")
        sys.exit(0)

    p = Path(sys.argv[1])
    if not p.exists():
        print(f"Dosya yok: {p}")
        sys.exit(1)

    img = p.read_bytes()
    res = asyncio.run(ocr_image(img))
    print("---OCR sonucu---")
    print(f"Success: {res.get('success')}")
    if res.get("success"):
        print(f"Confidence: {res.get('confidence'):.2%}")
        print(f"Is math: {res.get('is_math')}")
        print(f"Text:\n{res.get('text')[:500]}")
        if res.get("latex"):
            print(f"LaTeX:\n{res.get('latex')[:300]}")
    else:
        print(f"Error: {res.get('error')}")
