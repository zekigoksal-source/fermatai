"""
Chart URL Helper — Oturum 25.44 (Neo direktif 12 May)
=========================================================

Bot ```chart {json}``` bloğu yazdığında, WhatsApp'a image olarak gönder.
Web UI Chart.js ile render eder ama WA static image lazım.

Strateji: QuickChart.io public API kullan (ücretsiz, popüler, Chart.js compatible).
  GET https://quickchart.io/chart?c=<URLencoded_chart_config>

Eğer chart config çok büyükse (~2KB+) POST endpoint:
  POST https://quickchart.io/chart/create
  Body: {"chart": "<config>"}
  Response: {"success": true, "url": "..."}

Mimari:
  Bot text → extract_chart_blocks(text) → [{spec, raw_block}, ...]
  for each → make_chart_url(spec) → URL
  WA: text minus blocks + (her chart için bir image mesajı)
  Web UI: kod bloğu olduğu gibi kalır (Chart.js render eder)
"""
from __future__ import annotations
import json
import re
import urllib.parse
from typing import Optional

import httpx
from loguru import logger


# Bot mesajındaki ```chart\n{json}\n``` bloklarını yakalar
_CHART_BLOCK_RE = re.compile(
    r"```chart\s*\n(.*?)\n```",
    re.DOTALL | re.IGNORECASE,
)


def extract_chart_blocks(text: str) -> list[dict]:
    """Text içindeki ```chart {...}``` bloklarını ayıkla.

    Returns: [{"raw": full_block_with_fences, "spec": parsed_dict_or_None, "json": json_str}]
    """
    if not text or "chart" not in text.lower():
        return []
    blocks = []
    for m in _CHART_BLOCK_RE.finditer(text):
        json_str = m.group(1).strip()
        # Try to parse
        spec = None
        try:
            spec = json.loads(json_str)
        except Exception:
            # Sometimes inner has trailing comma or unquoted keys — try lenient
            try:
                # Strip trailing commas in JSON-ish text
                fixed = re.sub(r",(\s*[}\]])", r"\1", json_str)
                spec = json.loads(fixed)
            except Exception:
                continue  # malformed, skip
        blocks.append({
            "raw": m.group(0),
            "spec": spec,
            "json": json_str,
        })
    return blocks


def remove_chart_blocks(text: str) -> str:
    """Text'ten chart bloklarını çıkar — chart yerine sade text bırak."""
    if not text:
        return text
    return _CHART_BLOCK_RE.sub("", text).strip()


def _build_quickchart_config(spec: dict, dark: bool = True) -> dict:
    """Spec'i QuickChart-uyumlu config'e dönüştür.

    Bot tipik spec:
      {type, data:{labels,datasets}, options:{title:{text}}}
    veya bizim eski:
      {type, title, labels, datasets:[{label,data,backgroundColor}]}

    İki formatı da handle et.
    """
    # Eski format → standart Chart.js format
    if "labels" in spec and "data" not in spec:
        normalized = {
            "type": spec.get("type", "bar"),
            "data": {
                "labels": spec.get("labels", []),
                "datasets": spec.get("datasets", []),
            },
            "options": spec.get("options") or {},
        }
        # Title varsa options.title.text ekle
        if spec.get("title"):
            normalized["options"].setdefault("plugins", {}).setdefault(
                "title", {"display": True, "text": spec["title"]}
            )
        cfg = normalized
    else:
        cfg = dict(spec)

    # Dark mode bg
    if dark:
        cfg.setdefault("options", {})
        cfg["options"].setdefault("plugins", {})
        cfg["options"]["plugins"].setdefault("legend", {})
        cfg["options"]["plugins"]["legend"]["labels"] = {
            **(cfg["options"]["plugins"]["legend"].get("labels") or {}),
            "color": "#ffffff",
        }
        cfg["options"].setdefault("scales", {})
    return cfg


async def make_chart_url(spec: dict, dark: bool = True,
                          width: int = 720, height: int = 360,
                          bg_color: str = "transparent") -> Optional[str]:
    """Chart spec → kalıcı (QuickChart) image URL.

    Önce GET ile dene (config < 2KB). Büyükse POST /chart/create.
    """
    if not spec or not isinstance(spec, dict):
        return None
    cfg = _build_quickchart_config(spec, dark=dark)
    cfg_json = json.dumps(cfg, ensure_ascii=False, separators=(",", ":"))

    # GET — küçük config
    if len(cfg_json) < 1800:
        encoded = urllib.parse.quote(cfg_json, safe="")
        url = (f"https://quickchart.io/chart"
               f"?c={encoded}&width={width}&height={height}"
               f"&backgroundColor={bg_color}&devicePixelRatio=2.0")
        return url

    # POST — büyük config, short URL al
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                "https://quickchart.io/chart/create",
                json={
                    "chart": cfg_json,
                    "width": width,
                    "height": height,
                    "backgroundColor": bg_color,
                    "devicePixelRatio": 2.0,
                },
            )
            if r.status_code == 200:
                d = r.json()
                if d.get("success"):
                    return d.get("url")
    except Exception as e:
        logger.debug(f"[CHART_URL] POST create fail: {e}")
    return None


async def process_text_for_chart_images(text: str) -> tuple[str, list[str]]:
    """Text içindeki chart bloklarını image URL'ye çevir.

    Returns: (text_without_chart_blocks, [chart_image_url, ...])
    """
    blocks = extract_chart_blocks(text)
    if not blocks:
        return text, []
    urls = []
    for b in blocks:
        if not b["spec"]:
            continue
        u = await make_chart_url(b["spec"])
        if u:
            urls.append(u)
    cleaned = remove_chart_blocks(text)
    return cleaned, urls


# CLI test
if __name__ == "__main__":
    import asyncio

    async def _main():
        sample = """**Sınav Sonuçları**

Bak grafiğe:

```chart
{"type":"bar","data":{"labels":["TYT","AYT","YDT"],"datasets":[{"label":"Net","data":[85,72,60],"backgroundColor":"#4caf50"}]},"options":{"plugins":{"title":{"display":true,"text":"Son Deneme"}}}}
```

Genel olarak iyi gidişat.
"""
        cleaned, urls = await process_text_for_chart_images(sample)
        print("CLEANED:")
        print(cleaned)
        print()
        print("URLS:", urls)

    asyncio.run(_main())
