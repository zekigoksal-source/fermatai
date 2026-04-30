"""
External APIs V2 (Oturum 25.32 — Neo direktifi)
================================================
NASA + Wolfram + Wikipedia + arXiv + DALL-E/SD entegrasyonları.

Bot eğitim sorularında bu API'lardan zenginlik çeker:
- NASA: astrofizik konular için resmi görseller (karadelik, plank, evren)
- Wolfram: matematik/fizik komputasyonal sorgu (denklem, integral, hesap)
- Wikipedia: kavram doğrulama, kısa özet (TR+EN fallback)
- arXiv: ileri bilim makaleleri (YKS sınırı üstü meraklı öğrenci)
- DALL-E / SDXL: bot konuya özel illüstrasyon üretir

Tüm API'lar timeout-corumalı, hata durumunda graceful skip.

ENV:
  NASA_API_KEY            — DEMO_KEY 30 sorgu/saat, gercek key sınırsız
  WOLFRAM_APP_ID          — wolframalpha.com/api'den ücretsiz
  OPENAI_API_KEY          — DALL-E için (zaten Whisper için var)
  REPLICATE_API_TOKEN     — Stable Diffusion alternatifi
  DAILY_IMAGE_LIMIT       — günlük görsel üretim limiti (default 30)
"""
from __future__ import annotations

import os
import asyncio
from typing import Optional
from urllib.parse import quote_plus

import httpx
from loguru import logger

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

_HTTP_TIMEOUT = 15.0


# ═══════════════════════════════════════════════════════════════════════
# 1. NASA Open APIs — astronomi görselleri + bilim verisi
# ═══════════════════════════════════════════════════════════════════════
NASA_API_KEY = os.getenv("NASA_API_KEY", "DEMO_KEY")


async def nasa_apod(query_date: str = "") -> dict:
    """Astronomy Picture of the Day — NASA günün görseli + açıklama."""
    try:
        url = f"https://api.nasa.gov/planetary/apod?api_key={NASA_API_KEY}"
        if query_date:
            url += f"&date={query_date}"
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            d = r.json()
            return {
                "success": True,
                "title": d.get("title", ""),
                "explanation": d.get("explanation", "")[:800],
                "url": d.get("url", ""),
                "hdurl": d.get("hdurl", d.get("url", "")),
                "media_type": d.get("media_type", "image"),
                "date": d.get("date", ""),
                "copyright": d.get("copyright", "NASA"),
            }
    except Exception as e:
        logger.warning(f"nasa_apod hata: {e}")
        return {"success": False, "error": str(e)}


async def nasa_image_search(query: str, page: int = 1) -> dict:
    """NASA Image and Video Library — anahtar kelime ile görsel ara.
    Örnek: 'black hole', 'galaxy', 'mars', 'quantum', 'einstein'."""
    try:
        url = f"https://images-api.nasa.gov/search?q={quote_plus(query)}&media_type=image&page={page}"
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            d = r.json()
            items = d.get("collection", {}).get("items", [])[:6]
            results = []
            for it in items:
                data = (it.get("data") or [{}])[0]
                links = (it.get("links") or [{}])[0]
                results.append({
                    "title": data.get("title", ""),
                    "description": (data.get("description") or "")[:300],
                    "image_url": links.get("href", ""),
                    "date": data.get("date_created", "")[:10],
                    "center": data.get("center", "NASA"),
                })
            return {"success": True, "query": query, "results": results, "count": len(results)}
    except Exception as e:
        logger.warning(f"nasa_image_search hata: {e}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# 2. Wolfram Alpha API — matematik + fizik komputasyonal sorgu
# ═══════════════════════════════════════════════════════════════════════
WOLFRAM_APP_ID = os.getenv("WOLFRAM_APP_ID", "")


async def wolfram_query(query: str) -> dict:
    """Wolfram Alpha kısa cevap — denklem, integral, fizik hesabı.
    Örnek: 'integral x^2 from 0 to 5', 'speed of light in km/s', 'solve x^2+5x-6=0'.
    İPUCU: Türkçe sorguyu İngilizce'ye çevirip gönder."""
    if not WOLFRAM_APP_ID:
        return {"success": False, "error": "WOLFRAM_APP_ID env tanımsız (.env'e ekle)"}
    try:
        url = (f"https://api.wolframalpha.com/v1/result"
               f"?appid={WOLFRAM_APP_ID}&i={quote_plus(query)}&units=metric")
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
            r = await client.get(url)
            if r.status_code == 200:
                return {"success": True, "query": query, "answer": r.text}
            elif r.status_code == 501:
                return {"success": False, "query": query,
                        "error": "Wolfram bu sorguyu anlamadı, daha net İngilizce sor"}
            r.raise_for_status()
    except Exception as e:
        logger.warning(f"wolfram_query hata: {e}")
        return {"success": False, "error": str(e)}
    return {"success": False, "error": "Beklenmeyen hata"}


async def wolfram_full(query: str) -> dict:
    """Wolfram Full Results — adım adım çözüm + grafik URL'leri.
    25.32-fix: format=plaintext,image bazi sorgularda 500 hata — plaintext only daha stabil."""
    if not WOLFRAM_APP_ID:
        return {"success": False, "error": "WOLFRAM_APP_ID env tanımsız"}
    try:
        url = (f"https://api.wolframalpha.com/v2/query"
               f"?appid={WOLFRAM_APP_ID}&input={quote_plus(query)}"
               f"&output=json&format=plaintext&units=metric")
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT * 2, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            d = r.json()
            qresult = d.get("queryresult", {})
            if not qresult.get("success"):
                return {"success": False, "error": "Wolfram cevap üretmedi"}
            pods = qresult.get("pods", [])
            extracted = []
            for pod in pods[:5]:
                title = pod.get("title", "")
                subpods = pod.get("subpods", [])
                for sp in subpods[:2]:
                    plaintext = sp.get("plaintext", "")
                    img = sp.get("img", {})
                    if plaintext or img.get("src"):
                        extracted.append({
                            "title": title,
                            "text": plaintext[:300],
                            "image": img.get("src", ""),
                        })
            return {"success": True, "query": query, "pods": extracted,
                    "interpretation": qresult.get("inputstring", query)}
    except Exception as e:
        logger.warning(f"wolfram_full hata: {e}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# 3. Wikipedia API — kavram doğrulama, kısa özet
# ═══════════════════════════════════════════════════════════════════════
async def wiki_lookup(query: str, lang: str = "tr") -> dict:
    """Wikipedia REST API — başlık özeti çek (önce TR, bulunamazsa EN).
    25.32-fix: Direct summary endpoint + URL encoding (boşluk → _, quote not quote_plus)."""
    from urllib.parse import quote
    langs = [lang, "en"] if lang != "en" else ["en"]
    # Wikipedia URL: boşluk = "_", özel karakterler = % encoded
    def _wiki_title(q: str) -> str:
        return quote(q.replace(" ", "_"), safe="_")
    # Wikipedia API User-Agent zorunlu (yoksa 403/empty response) — ASCII only
    headers = {"User-Agent": "FermatAI/1.0 (+https://fermategitimkurumlari.com; education assistant)"}
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True, headers=headers) as client:
        for try_lang in langs:
            try:
                # 1) Direct summary endpoint (TR karakterleri ile çoğunlukla işe yarıyor)
                summary_url = f"https://{try_lang}.wikipedia.org/api/rest_v1/page/summary/{_wiki_title(query)}"
                r = await client.get(summary_url)
                if r.status_code == 200:
                    d = r.json()
                    if d.get("type") != "disambiguation":
                        return {
                            "success": True,
                            "lang": try_lang,
                            "title": d.get("title", query),
                            "extract": d.get("extract", "")[:600],
                            "url": d.get("content_urls", {}).get("desktop", {}).get("page", ""),
                            "thumbnail": d.get("thumbnail", {}).get("source", "") if d.get("thumbnail") else "",
                        }
                # 2) Fallback: opensearch ile başlığı bul, sonra summary çek
                search_url = (f"https://{try_lang}.wikipedia.org/w/api.php"
                              f"?action=opensearch&search={quote_plus(query)}&limit=3&format=json&utf8=1")
                r = await client.get(search_url)
                if r.status_code != 200:
                    continue
                data = r.json()
                titles = data[1] if len(data) > 1 else []
                if not titles:
                    continue
                # İlk başarılı title — disambiguation hariç
                for title in titles:
                    summary_url = f"https://{try_lang}.wikipedia.org/api/rest_v1/page/summary/{_wiki_title(title)}"
                    r2 = await client.get(summary_url)
                    if r2.status_code != 200:
                        continue
                    d = r2.json()
                    if d.get("type") == "disambiguation":
                        continue
                    return {
                        "success": True,
                        "lang": try_lang,
                        "title": d.get("title", title),
                        "extract": d.get("extract", "")[:600],
                        "url": d.get("content_urls", {}).get("desktop", {}).get("page", ""),
                        "thumbnail": d.get("thumbnail", {}).get("source", "") if d.get("thumbnail") else "",
                    }
            except Exception as e:
                logger.warning(f"wiki_lookup hata ({try_lang}): {e}")
                continue
    return {"success": False, "error": f"Wikipedia'da '{query}' bulunamadı (TR/EN)"}


# ═══════════════════════════════════════════════════════════════════════
# 4. arXiv API — bilimsel makale arama
# ═══════════════════════════════════════════════════════════════════════
async def arxiv_search(query: str, max_results: int = 5) -> dict:
    """arXiv — bilimsel makale arama (özellikle astrofizik, kuantum).
    Bot YKS üstü konularda referans için kullanır."""
    try:
        url = (f"http://export.arxiv.org/api/query?search_query=all:{quote_plus(query)}"
               f"&start=0&max_results={max_results}&sortBy=relevance")
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            import re
            text = r.text
            entries = re.findall(r"<entry>([\s\S]*?)</entry>", text)
            results = []
            for entry in entries[:max_results]:
                title = re.search(r"<title>([\s\S]*?)</title>", entry)
                summary = re.search(r"<summary>([\s\S]*?)</summary>", entry)
                published = re.search(r"<published>([\s\S]*?)</published>", entry)
                link = re.search(r'<link.*?href="([^"]+)".*?rel="alternate"', entry)
                authors = re.findall(r"<name>([\s\S]*?)</name>", entry)
                results.append({
                    "title": (title.group(1) if title else "").strip().replace("\n", " "),
                    "summary": (summary.group(1) if summary else "").strip()[:400],
                    "published": published.group(1)[:10] if published else "",
                    "url": link.group(1) if link else "",
                    "authors": ", ".join(authors[:3]),
                })
            return {"success": True, "query": query, "results": results, "count": len(results)}
    except Exception as e:
        logger.warning(f"arxiv_search hata: {e}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# 5. DALL-E 3 / Stable Diffusion — bot konuya özel illüstrasyon
# ═══════════════════════════════════════════════════════════════════════
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN", "")
DAILY_IMAGE_LIMIT = int(os.getenv("DAILY_IMAGE_LIMIT", "30"))

_IMAGE_DAILY_COUNT = {"date": "", "count": 0}


async def generate_image(prompt: str, style: str = "educational",
                         provider: str = "auto") -> dict:
    """AI image generation — eğitim odaklı illüstrasyon.
    provider: 'openai' (DALL-E 3) | 'replicate' (SDXL) | 'auto'
    style: 'educational' | 'scientific' | 'diagram' | 'photo'
    """
    from datetime import date
    today_str = date.today().isoformat()
    if _IMAGE_DAILY_COUNT["date"] != today_str:
        _IMAGE_DAILY_COUNT["date"] = today_str
        _IMAGE_DAILY_COUNT["count"] = 0
    if _IMAGE_DAILY_COUNT["count"] >= DAILY_IMAGE_LIMIT:
        return {"success": False, "error": f"Günlük resim limiti ({DAILY_IMAGE_LIMIT}) doldu"}

    style_prompts = {
        "educational": "clean educational illustration, simple, scientific accuracy, white background, suitable for textbook, no text overlay",
        "scientific": "scientific diagram, accurate physics representation, white background, technical illustration, no text",
        "diagram": "schematic diagram, vector style, clean lines, white background, labeled components",
        "photo": "photorealistic, high detail, accurate scientific representation",
    }
    enhanced = f"{prompt}. Style: {style_prompts.get(style, style_prompts['educational'])}"

    use_provider = provider
    if provider == "auto":
        use_provider = "openai" if OPENAI_API_KEY else ("replicate" if REPLICATE_API_TOKEN else None)
    if not use_provider:
        return {"success": False, "error": "Hiç image API key yok (OPENAI_API_KEY veya REPLICATE_API_TOKEN)"}

    try:
        if use_provider == "openai":
            if not OPENAI_API_KEY:
                return {"success": False, "error": "OPENAI_API_KEY tanımsız"}
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(
                    "https://api.openai.com/v1/images/generations",
                    headers={"Authorization": f"Bearer {OPENAI_API_KEY}",
                             "Content-Type": "application/json"},
                    json={
                        "model": "dall-e-3",
                        "prompt": enhanced[:4000],
                        "n": 1,
                        "size": "1024x1024",
                        "quality": "standard",
                    })
                r.raise_for_status()
                d = r.json()
                image_url = d["data"][0]["url"]
                _IMAGE_DAILY_COUNT["count"] += 1
                return {
                    "success": True,
                    "provider": "openai/dall-e-3",
                    "image_url": image_url,
                    "prompt_used": enhanced[:200],
                    "today_used": _IMAGE_DAILY_COUNT["count"],
                    "today_limit": DAILY_IMAGE_LIMIT,
                }
        elif use_provider == "replicate":
            if not REPLICATE_API_TOKEN:
                return {"success": False, "error": "REPLICATE_API_TOKEN tanımsız"}
            async with httpx.AsyncClient(timeout=120.0) as client:
                r = await client.post(
                    "https://api.replicate.com/v1/predictions",
                    headers={"Authorization": f"Token {REPLICATE_API_TOKEN}",
                             "Content-Type": "application/json"},
                    json={
                        "version": "39ed52f2a78e934b3ba6e2a89f5b1c712de7dfea535525255b1aa35c5565e08b",
                        "input": {"prompt": enhanced[:1000], "width": 1024, "height": 1024,
                                  "num_inference_steps": 30}
                    })
                r.raise_for_status()
                pred = r.json()
                pred_url = pred["urls"]["get"]
                for _ in range(30):
                    await asyncio.sleep(2)
                    pr = await client.get(pred_url,
                        headers={"Authorization": f"Token {REPLICATE_API_TOKEN}"})
                    pd = pr.json()
                    if pd.get("status") == "succeeded":
                        out = pd.get("output", [])
                        image_url = out[0] if out else ""
                        _IMAGE_DAILY_COUNT["count"] += 1
                        return {
                            "success": True,
                            "provider": "replicate/sdxl",
                            "image_url": image_url,
                            "prompt_used": enhanced[:200],
                            "today_used": _IMAGE_DAILY_COUNT["count"],
                            "today_limit": DAILY_IMAGE_LIMIT,
                        }
                    if pd.get("status") in ("failed", "canceled"):
                        return {"success": False, "error": f"Replicate {pd.get('status')}: {pd.get('error', '')}"}
                return {"success": False, "error": "Replicate timeout (60s)"}
    except httpx.HTTPStatusError as e:
        logger.warning(f"generate_image HTTP {e.response.status_code}: {e.response.text[:200]}")
        return {"success": False, "error": f"API hata: {e.response.status_code}"}
    except Exception as e:
        logger.error(f"generate_image hata: {e}")
        return {"success": False, "error": str(e)}
    return {"success": False, "error": "Beklenmeyen hata"}


# ═══════════════════════════════════════════════════════════════════════
# 6. PubChem API — kimya molekül bilgisi (CID, formula, struktur)
# ═══════════════════════════════════════════════════════════════════════
async def pubchem_lookup(name: str) -> dict:
    """PubChem REST — molekül arama (örn: 'glucose', 'caffeine', 'water', 'ethanol').
    Donus: cid, molecular_formula, molecular_weight, iupac_name, image_url, 3d_url."""
    headers = {"User-Agent": "FermatAI/1.0 education"}
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True, headers=headers) as client:
            # 1) Name → CID
            cid_url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{quote_plus(name)}/cids/JSON"
            r = await client.get(cid_url)
            if r.status_code != 200:
                return {"success": False, "error": f"'{name}' PubChem'de bulunamadı"}
            cids = r.json().get("IdentifierList", {}).get("CID", [])
            if not cids:
                return {"success": False, "error": f"'{name}' icin CID yok"}
            cid = cids[0]
            # 2) Properties
            prop_url = (f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/property/"
                        f"MolecularFormula,MolecularWeight,IUPACName,Charge/JSON")
            r2 = await client.get(prop_url)
            props = {}
            if r2.status_code == 200:
                p = r2.json().get("PropertyTable", {}).get("Properties", [{}])[0]
                props = {
                    "molecular_formula": p.get("MolecularFormula", ""),
                    "molecular_weight": p.get("MolecularWeight", ""),
                    "iupac_name": p.get("IUPACName", ""),
                    "charge": p.get("Charge", 0),
                }
            return {
                "success": True,
                "name": name,
                "cid": cid,
                **props,
                "image_2d_url": f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/PNG",
                "structure_url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}",
                "sdf_3d_url": f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/SDF?record_type=3d",
            }
    except Exception as e:
        logger.warning(f"pubchem_lookup hata: {e}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# 7. USGS Earthquake API — son depremler (jeoloji/coğrafya)
# ═══════════════════════════════════════════════════════════════════════
async def usgs_earthquakes(min_magnitude: float = 4.5, max_results: int = 10) -> dict:
    """USGS — son 1 günün önemli depremleri (mag >= min_magnitude)."""
    try:
        url = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_day.geojson"
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            d = r.json()
            features = d.get("features", [])
            results = []
            for f in features[:max_results]:
                p = f.get("properties", {})
                if p.get("mag", 0) < min_magnitude:
                    continue
                results.append({
                    "magnitude": p.get("mag", 0),
                    "place": p.get("place", ""),
                    "time": p.get("time", 0),
                    "url": p.get("url", ""),
                    "tsunami": bool(p.get("tsunami", 0)),
                })
            return {"success": True, "count": len(results), "results": results,
                    "metadata": d.get("metadata", {}).get("title", "")}
    except Exception as e:
        logger.warning(f"usgs_earthquakes hata: {e}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# 8. PDF üretici — bot çalışma planı/rapor PDF olusturur
# ═══════════════════════════════════════════════════════════════════════
async def generate_pdf(html_content: str, title: str = "FermatAI Rapor") -> dict:
    """HTML'den PDF üret — bot çalışma planı, deneme analizi, rapor için.
    Returns: {success, pdf_path, pdf_url}"""
    import os, tempfile, secrets
    from pathlib import Path
    try:
        # WeasyPrint ile HTML→PDF (pip install weasyprint)
        try:
            from weasyprint import HTML
        except ImportError:
            return {"success": False, "error": "weasyprint kurulu değil (pip install weasyprint)"}
        # Kalıcı path: /opt/fermatai/eyotek_agent/logs/pdfs/{uuid}.pdf
        pdf_dir = Path("/opt/fermatai/eyotek_agent/logs/pdfs")
        pdf_dir.mkdir(parents=True, exist_ok=True)
        uuid = secrets.token_urlsafe(10)
        pdf_path = pdf_dir / f"{uuid}.pdf"
        # Wrapper HTML
        full_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>
  body {{ font-family: -apple-system, sans-serif; padding: 40px; color: #2F2F2F; line-height: 1.6; }}
  h1, h2, h3 {{ color: #C76F3E; }}
  .header {{ border-bottom: 2px solid #C76F3E; padding-bottom: 12px; margin-bottom: 24px; }}
  .footer {{ margin-top: 40px; padding-top: 12px; border-top: 1px solid #ddd; font-size: 11px; color: #888; text-align: center; }}
  table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
  th, td {{ border: 1px solid #E7E5DE; padding: 8px 12px; text-align: left; }}
  th {{ background: #FAFAF7; font-weight: 700; }}
</style></head><body>
<div class="header"><h1>⚡ {title}</h1></div>
<div class="content">{html_content}</div>
<div class="footer">FermatAI · fermategitimkurumlari.com</div>
</body></html>"""
        # Sync call thread'e at
        await asyncio.to_thread(lambda: HTML(string=full_html).write_pdf(str(pdf_path)))
        # Public URL: bridge'in /pdfs/{uuid}.pdf static endpoint'i ile servis edilebilir
        # Şimdilik URL render endpoint'i üzerinden — render_endpoint'a basit static HTML wrapper
        return {
            "success": True,
            "pdf_path": str(pdf_path),
            "pdf_filename": f"{uuid}.pdf",
            "pdf_size_kb": round(pdf_path.stat().st_size / 1024, 1),
            "title": title,
        }
    except Exception as e:
        logger.error(f"generate_pdf hata: {e}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# Status raporu
# ═══════════════════════════════════════════════════════════════════════
def status_report_v2() -> dict:
    return {
        "nasa": True,  # DEMO_KEY her zaman çalışır
        "nasa_real_key": NASA_API_KEY != "DEMO_KEY",
        "wolfram": bool(WOLFRAM_APP_ID),
        "wikipedia": True,  # API key gerek yok
        "arxiv": True,  # API key gerek yok
        "openai_image": bool(OPENAI_API_KEY),
        "replicate_image": bool(REPLICATE_API_TOKEN),
        "pubchem": True,  # API key gerek yok
        "usgs": True,  # API key gerek yok
        "pdf_generator": True,  # weasyprint kurulu olmalı (yoksa graceful skip)
    }
