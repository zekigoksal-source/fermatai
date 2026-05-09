"""
External APIs V3 — Oturum 25.43 (Neo direktif, 9 May 2026)
============================================================
12 yeni egitim odakli API entegrasyonu:

TIER 1 (Hemen ekle, dusuk effort, yuksek ROI):
  13. TDK Sozluk           (Turkce kelime/deyim/atasozu)
  14. NIST Physical Constants (fizik sabitleri)
  15. OEIS                 (sayilar dizisi)
  16. Open-Meteo           (cografya iklim)

TIER 2 (Onemli, orta effort):
  17. Wikidata SPARQL      (yapilandirilmis bilgi)
  18. CERN Open Data       ("wow factor" havali fizik)
  19. Hugging Face Infer   (100K+ model)
  20. TUIK dataset         (Turkiye istatistik)

TIER 3 (Nis ama havali):
  21. AlphaFold (EBI)      (DeepMind protein yapi)
  22. NIST WebBook         (kimya termodinamik)
  23. Crossref/JSTOR       (akademik makale)
  24. OpenStreetMap        (cografya konum)

Tum API'lar:
  - timeout-koruma (10s default)
  - graceful error (success: False + error metni)
  - JSON-only cikti
  - Hicbiri ucretli/key gerektirmez (HF_API_TOKEN opsiyonel)
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Optional
from urllib.parse import quote_plus, urlencode

import httpx
from loguru import logger

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

_HTTP_TIMEOUT = 12.0
_USER_AGENT = "FermatAI/25.43 (educational, contact: zeki.goksal@gmail.com)"


# ═══════════════════════════════════════════════════════════════════════
# 13. TDK SOZLUK API — Turkce kelime/deyim/atasozu
# ═══════════════════════════════════════════════════════════════════════
async def tdk_sozluk(query: str) -> dict:
    """TDK Guncel Turkce Sozluk — kelime anlami, atasozu, deyim.

    Endpoint: https://sozluk.gov.tr/gts?ara=X
    Donus: anlam, kullanim ornegi, eş anlam, koken bilgisi.

    YKS-TYT Turkce: paragraf sorularinda kelime/deyim anlami kritik.
    Wikipedia'dan farkli: resmi otorite + temiz JSON.

    Ornek:
        >>> r = await tdk_sozluk("müşfik")
        >>> r["entries"][0]["meanings"][0]["definition"]
        "Sevgi gosteren, yumuşak ve dostça davranan"
    """
    if not query or len(query) > 60:
        return {"success": False, "error": "Gecersiz sorgu"}
    try:
        url = f"https://sozluk.gov.tr/gts?ara={quote_plus(query)}"
        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            r = await client.get(url)
            if r.status_code != 200:
                return {"success": False, "error": f"HTTP {r.status_code}"}
            data = r.json()

        # TDK error format: {"error": "Sonuç bulunamadı."}
        if isinstance(data, dict) and "error" in data:
            return {
                "success": True,
                "found": False,
                "query": query,
                "message": data.get("error", "Bulunamadi"),
            }

        # Liste donusu — her item bir kelime
        entries = []
        for item in (data if isinstance(data, list) else [data]):
            meanings = []
            for m in (item.get("anlamlarListe") or []):
                meanings.append({
                    "definition": m.get("anlam", ""),
                    "example": (m.get("orneklerListe") or [{}])[0].get("ornek", "") if m.get("orneklerListe") else "",
                    "type": m.get("ozelliklerListe", [{}])[0].get("tam_adi", "") if m.get("ozelliklerListe") else "",
                })
            entries.append({
                "word": item.get("madde", ""),
                "lisan": item.get("lisan", ""),  # Koken (ar, fa, en, fr, ...)
                "meanings": meanings[:5],  # max 5
            })
        return {
            "success": True,
            "found": True,
            "query": query,
            "entries": entries[:3],  # max 3 ana kelime
        }
    except httpx.HTTPError as e:
        logger.warning(f"tdk_sozluk HTTP error: {e}")
        return {"success": False, "error": f"http: {e}"}
    except Exception as e:
        logger.warning(f"tdk_sozluk hata: {e}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# 14. NIST PHYSICAL CONSTANTS — fizik sabitleri (statik dataset)
# ═══════════════════════════════════════════════════════════════════════
# Source: https://physics.nist.gov/cuu/Constants/
# CODATA 2018 (gecerli set), kapsamli alt-kume
_NIST_CONSTANTS = {
    "c": {
        "name": "isik hizi (vakum)",
        "value": 299792458.0,
        "unit": "m/s",
        "symbol": "c",
        "exact": True,
    },
    "g": {
        "name": "yercekimi sabiti",
        "value": 6.67430e-11,
        "unit": "m^3 kg^-1 s^-2",
        "symbol": "G",
        "exact": False,
    },
    "h": {
        "name": "Planck sabiti",
        "value": 6.62607015e-34,
        "unit": "J s",
        "symbol": "h",
        "exact": True,
    },
    "hbar": {
        "name": "indirgenmis Planck sabiti",
        "value": 1.054571817e-34,
        "unit": "J s",
        "symbol": "ℏ",
        "exact": False,
    },
    "k_b": {
        "name": "Boltzmann sabiti",
        "value": 1.380649e-23,
        "unit": "J/K",
        "symbol": "k_B",
        "exact": True,
    },
    "n_a": {
        "name": "Avogadro sayisi",
        "value": 6.02214076e23,
        "unit": "1/mol",
        "symbol": "N_A",
        "exact": True,
    },
    "r": {
        "name": "ideal gaz sabiti",
        "value": 8.314462618,
        "unit": "J / (mol K)",
        "symbol": "R",
        "exact": True,
    },
    "e": {
        "name": "elektron yuku",
        "value": 1.602176634e-19,
        "unit": "C",
        "symbol": "e",
        "exact": True,
    },
    "m_e": {
        "name": "elektron kutlesi",
        "value": 9.1093837015e-31,
        "unit": "kg",
        "symbol": "m_e",
        "exact": False,
    },
    "m_p": {
        "name": "proton kutlesi",
        "value": 1.67262192369e-27,
        "unit": "kg",
        "symbol": "m_p",
        "exact": False,
    },
    "m_n": {
        "name": "notron kutlesi",
        "value": 1.67492749804e-27,
        "unit": "kg",
        "symbol": "m_n",
        "exact": False,
    },
    "epsilon_0": {
        "name": "vakum permittivitesi",
        "value": 8.8541878128e-12,
        "unit": "F/m",
        "symbol": "ε_0",
        "exact": False,
    },
    "mu_0": {
        "name": "vakum permeabilitesi",
        "value": 1.25663706212e-6,
        "unit": "H/m",
        "symbol": "μ_0",
        "exact": False,
    },
    "g_earth": {
        "name": "Yer cekim ivmesi (standart)",
        "value": 9.80665,
        "unit": "m/s^2",
        "symbol": "g",
        "exact": True,
    },
    "stefan_boltzmann": {
        "name": "Stefan-Boltzmann sabiti",
        "value": 5.670374419e-8,
        "unit": "W m^-2 K^-4",
        "symbol": "σ",
        "exact": True,
    },
    "rydberg": {
        "name": "Rydberg sabiti",
        "value": 1.0973731568160e7,
        "unit": "1/m",
        "symbol": "R_∞",
        "exact": False,
    },
    "f": {
        "name": "Faraday sabiti",
        "value": 96485.33212,
        "unit": "C/mol",
        "symbol": "F",
        "exact": False,
    },
    "atm": {
        "name": "standart atmosfer basinci",
        "value": 101325.0,
        "unit": "Pa",
        "symbol": "atm",
        "exact": True,
    },
}

# Turkce alias
_NIST_ALIASES = {
    "isik hizi": "c", "ışık hızı": "c", "ışık": "c",
    "planck": "h", "plank": "h",
    "yercekimi": "g", "yer cekimi": "g", "yerçekimi": "g",
    "g sabiti": "g",
    "boltzmann": "k_b", "kb": "k_b",
    "avogadro": "n_a", "na": "n_a",
    "gaz sabiti": "r", "ideal gaz": "r",
    "elektron yuku": "e", "elektron yükü": "e", "yuk": "e",
    "elektron kutlesi": "m_e", "elektron": "m_e",
    "proton": "m_p", "proton kutlesi": "m_p",
    "notron": "m_n", "nötron": "m_n",
    "yer çekimi ivmesi": "g_earth", "yercekim ivme": "g_earth",
    "stefan": "stefan_boltzmann",
    "rydberg": "rydberg",
    "faraday": "f",
    "atmosfer": "atm",
}


async def nist_constant(query: str) -> dict:
    """NIST Physical Constants — fizik sabitleri (statik tablo).

    YKS-AYT Fizik: formul uygulamada sabitlere ihtiyac (E=mc2, F=Gm1m2/r2 ...).

    Ornek:
        >>> r = await nist_constant("planck")
        >>> r["value"]  # 6.62607015e-34
    """
    if not query:
        return {"success": False, "error": "Sorgu bos"}

    q = query.strip().lower()

    # Direkt key kontrolu
    key = None
    if q in _NIST_CONSTANTS:
        key = q
    elif q in _NIST_ALIASES:
        key = _NIST_ALIASES[q]
    else:
        # Substring search
        for alias, k in _NIST_ALIASES.items():
            if alias in q or q in alias:
                key = k
                break

    if not key:
        return {
            "success": True,
            "found": False,
            "query": query,
            "message": "Sabit bulunamadi. Mevcut: " + ", ".join(list(_NIST_CONSTANTS.keys())[:8]) + "...",
        }

    c = _NIST_CONSTANTS[key]
    return {
        "success": True,
        "found": True,
        "query": query,
        "key": key,
        "name": c["name"],
        "value": c["value"],
        "unit": c["unit"],
        "symbol": c["symbol"],
        "exact": c["exact"],
        "source": "NIST CODATA 2018",
    }


async def nist_constants_list() -> dict:
    """Tum mevcut sabit listesini don."""
    return {
        "success": True,
        "count": len(_NIST_CONSTANTS),
        "constants": [
            {"key": k, "symbol": v["symbol"], "name": v["name"], "unit": v["unit"]}
            for k, v in _NIST_CONSTANTS.items()
        ],
    }


# ═══════════════════════════════════════════════════════════════════════
# 15. OEIS — Online Encyclopedia of Integer Sequences
# ═══════════════════════════════════════════════════════════════════════
# OEIS fallback dataset — Cloudflare bazi IP'leri (VPS dahil) bloklayinca kullanilir.
# YKS/AYT'de en sik karsilasilan diziler. Genisletilmesi gerekirse ekle.
_OEIS_FALLBACK = {
    "A000045": {  # Fibonacci
        "name": "Fibonacci numbers",
        "data": "0,1,1,2,3,5,8,13,21,34,55,89,144,233,377,610,987",
        "formula": "a(n) = a(n-1) + a(n-2), a(0)=0, a(1)=1",
        "comment": "F(0)=0, F(1)=1, F(n)=F(n-1)+F(n-2). Altin oran phi=(1+sqrt(5))/2.",
        "match_keys": ["fibonacci", "0,1,1,2,3,5,8", "1,1,2,3,5,8", "1,2,3,5,8,13", "0,1,1,2,3"],
    },
    "A000040": {  # Asal sayilar
        "name": "The prime numbers",
        "data": "2,3,5,7,11,13,17,19,23,29,31,37,41,43,47,53,59",
        "formula": "Asal sayilar: 1 ve kendinden baska bolen yok",
        "comment": "Sonsuz coklukta asal sayi vardir (Euclid teoremi).",
        "match_keys": ["asal", "prime", "primes", "2,3,5,7,11", "2,3,5,7"],
    },
    "A000027": {  # Sayma sayilari
        "name": "Natural numbers",
        "data": "1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20",
        "formula": "a(n) = n",
        "comment": "Pozitif tam sayilar.",
        "match_keys": ["dogal sayilar", "natural", "1,2,3,4,5"],
    },
    "A000290": {  # Kareler
        "name": "Squares: a(n) = n^2",
        "data": "0,1,4,9,16,25,36,49,64,81,100,121,144,169,196,225,256",
        "formula": "a(n) = n^2",
        "comment": "Tam kare sayilar.",
        "match_keys": ["kareler", "squares", "n^2", "1,4,9,16,25"],
    },
    "A000578": {  # Kupler
        "name": "The cubes: a(n) = n^3",
        "data": "0,1,8,27,64,125,216,343,512,729,1000,1331,1728,2197",
        "formula": "a(n) = n^3",
        "comment": "Tam kup sayilar.",
        "match_keys": ["kupler", "cubes", "n^3", "1,8,27,64,125"],
    },
    "A000142": {  # Faktoriyel
        "name": "Factorial numbers: n!",
        "data": "1,1,2,6,24,120,720,5040,40320,362880,3628800",
        "formula": "n! = n*(n-1)*(n-2)*...*1, 0! = 1",
        "comment": "Permutasyon, kombinatorik temel.",
        "match_keys": ["faktoriyel", "factorial", "1,2,6,24,120", "n!"],
    },
    "A000108": {  # Catalan
        "name": "Catalan numbers",
        "data": "1,1,2,5,14,42,132,429,1430,4862,16796,58786",
        "formula": "C(n) = (2n)!/((n+1)!*n!) = binomial(2n,n)/(n+1)",
        "comment": "Kombinatorik: parantez dengeleme, dik yol sayma.",
        "match_keys": ["catalan", "1,1,2,5,14,42"],
    },
    "A000217": {  # Ucgensel
        "name": "Triangular numbers: a(n) = n*(n+1)/2",
        "data": "0,1,3,6,10,15,21,28,36,45,55,66,78,91,105,120,136,153",
        "formula": "T(n) = n(n+1)/2 = 1+2+...+n",
        "comment": "Toplam ardisik tam sayilar.",
        "match_keys": ["ucgensel", "triangular", "1,3,6,10,15,21"],
    },
    "A000079": {  # Iki kuvvetleri
        "name": "Powers of 2: a(n) = 2^n",
        "data": "1,2,4,8,16,32,64,128,256,512,1024,2048,4096,8192,16384",
        "formula": "a(n) = 2^n",
        "comment": "Bilgisayar bilimi temeli (bit, byte, kB, MB).",
        "match_keys": ["2^n", "iki kuvvetleri", "powers of 2", "1,2,4,8,16,32"],
    },
    "A000032": {  # Lucas
        "name": "Lucas numbers",
        "data": "2,1,3,4,7,11,18,29,47,76,123,199,322,521,843",
        "formula": "L(n) = L(n-1) + L(n-2), L(0)=2, L(1)=1",
        "comment": "Fibonacci kuzeni — ayni rekurans, farkli baslangic.",
        "match_keys": ["lucas", "2,1,3,4,7,11"],
    },
}


def _oeis_local_search(query: str) -> list:
    """Local fallback — query OEIS yerel mini-database'inde ara."""
    q = (query or "").lower().strip()
    if not q:
        return []
    matches = []
    for seq_id, seq in _OEIS_FALLBACK.items():
        for key in seq["match_keys"]:
            if key.lower() in q or q in key.lower():
                matches.append({
                    "id": seq_id.lstrip("A"),
                    "name": seq["name"],
                    "first_terms": seq["data"],
                    "formula": seq["formula"],
                    "comment": seq["comment"],
                    "url": f"https://oeis.org/{seq_id}",
                })
                break
    return matches


async def oeis_search(query: str, max_results: int = 5) -> dict:
    """OEIS — sayi dizisi/diziler tanima.

    Endpoint: https://oeis.org/search?q=X&fmt=json
    Sorgu: "1,1,2,3,5,8,13" gibi virgullu sayi serisi VEYA "fibonacci" gibi metin.

    YKS-AYT Matematik: dizi sorulari, Fibonacci/asal sayilar/kombinatorik.

    25.43-FALLBACK: VPS IP'lerini Cloudflare bloklayabiliyor (403). Bu durumda
    yerel mini-katalogdan (Fibonacci, asallar, kareler, kupler, Catalan, vb.)
    cevap doner.

    Ornek:
        >>> r = await oeis_search("1,1,2,3,5,8,13")
        >>> r["results"][0]["name"]
        "Fibonacci numbers"
    """
    if not query:
        return {"success": False, "error": "Sorgu bos"}
    # Adim 1: Lokal fallback dataset'inde ara (hizli + Cloudflare-immun)
    local_matches = _oeis_local_search(query)
    try:
        url = f"https://oeis.org/search?q={quote_plus(query)}&fmt=json&start=0"
        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        ) as client:
            r = await client.get(url)
            if r.status_code != 200:
                # Cloudflare 403 vb. → fallback'e dus
                if local_matches:
                    return {
                        "success": True,
                        "found": True,
                        "query": query,
                        "results": local_matches[:max_results],
                        "source": "local_fallback",
                        "_note": f"OEIS API HTTP {r.status_code} (VPS Cloudflare blok), yerel mini-katalogdan",
                    }
                return {"success": False, "error": f"HTTP {r.status_code}"}
            data = r.json()

        # OEIS top-level LIST donuyor (dict degil — onceki implementasyon yanlisti)
        if not data or not isinstance(data, list):
            # API bos → local fallback dene
            if local_matches:
                return {
                    "success": True, "found": True, "query": query,
                    "results": local_matches[:max_results], "source": "local_fallback",
                }
            return {
                "success": True,
                "found": False,
                "query": query,
                "message": "Eslesen dizi bulunamadi",
            }

        results = []
        for item in data[:max_results]:
            results.append({
                "id": item.get("number", ""),  # A000045 vs.
                "name": item.get("name", ""),
                "first_terms": item.get("data", "")[:200],
                "formula": (item.get("formula") or [""])[0][:200] if item.get("formula") else "",
                "comment": (item.get("comment") or [""])[0][:200] if item.get("comment") else "",
                "url": f"https://oeis.org/A{int(item.get('number', 0)):06d}" if item.get("number") else "",
            })

        return {
            "success": True,
            "found": bool(results),
            "query": query,
            "total_matches": len(data),
            "results": results,
        }
    except Exception as e:
        # Network hatasi — local fallback'e dus
        if local_matches:
            return {
                "success": True, "found": True, "query": query,
                "results": local_matches[:max_results], "source": "local_fallback",
                "_note": f"OEIS API hata ({e}), yerel mini-katalogdan",
            }
        logger.warning(f"oeis_search hata: {e}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# 16. OPEN-METEO — Cografya iklim/hava verisi (free, no key)
# ═══════════════════════════════════════════════════════════════════════
async def open_meteo_climate(
    location: str = "Istanbul",
    days: int = 7,
) -> dict:
    """Open-Meteo — sehir bazli iklim verisi (sicaklik, yagis, ruzgar).

    Once geocoding (sehir → koordinat), sonra forecast.
    Endpoint: https://api.open-meteo.com/v1/forecast

    YKS Cografya: iklim tipleri, mevsim sorulari icin canli veri.

    Ornek:
        >>> r = await open_meteo_climate("Konya")
        >>> r["current"]["temperature_2m"]  # mevcut sicaklik
    """
    if not location:
        return {"success": False, "error": "Konum bos"}
    try:
        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        ) as client:
            # Adim 1: Geocoding
            geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={quote_plus(location)}&count=1&language=tr"
            geo_r = await client.get(geo_url)
            if geo_r.status_code != 200:
                return {"success": False, "error": f"Geocoding HTTP {geo_r.status_code}"}
            geo_data = geo_r.json()
            results = geo_data.get("results") or []
            if not results:
                return {
                    "success": True,
                    "found": False,
                    "location": location,
                    "message": "Konum bulunamadi",
                }
            place = results[0]
            lat, lon = place.get("latitude"), place.get("longitude")

            # Adim 2: Forecast
            params = {
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max",
                "forecast_days": min(max(1, days), 14),
                "timezone": "Europe/Istanbul",
            }
            fc_url = f"https://api.open-meteo.com/v1/forecast?{urlencode(params)}"
            fc_r = await client.get(fc_url)
            if fc_r.status_code != 200:
                return {"success": False, "error": f"Forecast HTTP {fc_r.status_code}"}
            fc = fc_r.json()

        return {
            "success": True,
            "found": True,
            "location": {
                "name": place.get("name"),
                "country": place.get("country"),
                "admin": place.get("admin1"),
                "lat": lat,
                "lon": lon,
                "elevation_m": place.get("elevation"),
            },
            "current": fc.get("current", {}),
            "daily": fc.get("daily", {}),
            "units": fc.get("current_units", {}),
        }
    except Exception as e:
        logger.warning(f"open_meteo_climate hata: {e}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# 17. WIKIDATA SPARQL — Yapilandirilmis bilgi grafi
# ═══════════════════════════════════════════════════════════════════════
async def wikidata_lookup(query: str, lang: str = "tr") -> dict:
    """Wikidata Search API — entity arama.

    Endpoint: https://www.wikidata.org/w/api.php
    Donus: kavram label, aciklama, claims (ozellikler).

    YKS Tarih/Cografya: yapilandirilmis ansiklopedik bilgi
    ("Atatürk doğum yılı", "Türkiye yüzölçümü" gibi).
    """
    if not query:
        return {"success": False, "error": "Sorgu bos"}
    try:
        # Adim 1: Entity search
        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        ) as client:
            search_url = "https://www.wikidata.org/w/api.php"
            search_params = {
                "action": "wbsearchentities",
                "search": query,
                "language": lang,
                "limit": 3,
                "format": "json",
            }
            sr = await client.get(search_url, params=search_params)
            if sr.status_code != 200:
                return {"success": False, "error": f"HTTP {sr.status_code}"}
            sd = sr.json()
            search_results = sd.get("search") or []
            if not search_results:
                return {
                    "success": True,
                    "found": False,
                    "query": query,
                    "message": "Eslesen entity yok",
                }

            entity_id = search_results[0].get("id")  # Q-ID

            # Adim 2: Entity claims (basit subset)
            entity_url = f"https://www.wikidata.org/wiki/Special:EntityData/{entity_id}.json"
            er = await client.get(entity_url)
            if er.status_code != 200:
                # Sadece search bilgisini don
                return {
                    "success": True,
                    "found": True,
                    "query": query,
                    "entity": search_results[0],
                    "extra_data": False,
                }
            ed = er.json()
            entity_data = ed.get("entities", {}).get(entity_id, {})

        # Sadelestirilmis output
        labels = entity_data.get("labels", {})
        descs = entity_data.get("descriptions", {})
        return {
            "success": True,
            "found": True,
            "query": query,
            "entity_id": entity_id,
            "label_tr": labels.get("tr", {}).get("value", "") or labels.get("en", {}).get("value", ""),
            "label_en": labels.get("en", {}).get("value", ""),
            "description_tr": descs.get("tr", {}).get("value", "") or descs.get("en", {}).get("value", ""),
            "description_en": descs.get("en", {}).get("value", ""),
            "url": f"https://www.wikidata.org/wiki/{entity_id}",
            "claims_count": len(entity_data.get("claims") or {}),
        }
    except Exception as e:
        logger.warning(f"wikidata_lookup hata: {e}")
        return {"success": False, "error": str(e)}


async def wikidata_sparql(sparql_query: str) -> dict:
    """Wikidata SPARQL — gelismis sorgu (admin/claude tool).

    Endpoint: https://query.wikidata.org/sparql

    NOT: SPARQL guvenlik — sadece SELECT izin ver, DELETE/INSERT olamaz zaten
    (sadece query endpoint), ama kullanici input'u escape edilmemiş.
    Bot uretiyor, kontrol prompt seviyesinde.
    """
    if not sparql_query or len(sparql_query) > 4000:
        return {"success": False, "error": "Sorgu bos veya >4000 char"}
    # Guvenlik: SELECT/ASK disinda kabul etme
    upper = sparql_query.strip().upper()
    if not (upper.startswith("SELECT") or upper.startswith("ASK") or upper.startswith("PREFIX")):
        return {"success": False, "error": "Sadece SELECT/ASK sorgular kabul edilir"}

    try:
        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT * 2,  # SPARQL daha uzun olabilir
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "application/sparql-results+json",
            },
            follow_redirects=True,
        ) as client:
            r = await client.get(
                "https://query.wikidata.org/sparql",
                params={"query": sparql_query, "format": "json"},
            )
            if r.status_code != 200:
                return {"success": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
            data = r.json()
        bindings = data.get("results", {}).get("bindings", [])
        return {
            "success": True,
            "rows": bindings[:20],  # max 20 satir
            "row_count": len(bindings),
            "vars": data.get("head", {}).get("vars", []),
        }
    except Exception as e:
        logger.warning(f"wikidata_sparql hata: {e}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# 18. CERN OPEN DATA — Parcacik fizigi ("wow factor")
# ═══════════════════════════════════════════════════════════════════════
async def cern_open_data(query: str = "higgs", max_results: int = 5) -> dict:
    """CERN Open Data Portal — LHC parcacik fizigi veri seti arama.

    Endpoint: https://opendata.cern.ch/api/records/?q=X
    Egitim odakli — gercek LHC verisinden ornekler (Higgs, ATLAS, CMS).

    YKS-AYT Fizik: meraklı ogrenci icin "Higgs nedir, gercek veri" gostergesi.
    """
    if not query:
        query = "higgs"
    try:
        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        ) as client:
            url = "https://opendata.cern.ch/api/records/"
            params = {"q": query, "size": min(max_results, 10), "type": "Dataset"}
            r = await client.get(url, params=params)
            if r.status_code != 200:
                return {"success": False, "error": f"HTTP {r.status_code}"}
            data = r.json()

        hits = data.get("hits", {}).get("hits") or []
        results = []
        for h in hits[:max_results]:
            md = h.get("metadata") or {}
            results.append({
                "id": h.get("id"),
                "title": md.get("title", ""),
                "type": (md.get("type") or {}).get("primary", ""),
                "year": (md.get("date_created") or [""])[0] if md.get("date_created") else "",
                "experiment": (md.get("experiment") or [""])[0] if md.get("experiment") else "",
                "abstract": (md.get("abstract", {}) or {}).get("description", "")[:300],
                "url": f"https://opendata.cern.ch/record/{h.get('id')}",
            })
        # CERN total bazen int bazen dict
        total_field = data.get("hits", {}).get("total", 0)
        if isinstance(total_field, dict):
            total_matches = total_field.get("value", 0)
        else:
            total_matches = int(total_field) if total_field else 0
        return {
            "success": True,
            "found": bool(results),
            "query": query,
            "total_matches": total_matches,
            "results": results,
        }
    except Exception as e:
        logger.warning(f"cern_open_data hata: {e}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# 19. HUGGING FACE INFERENCE — 100K+ model erisimi
# ═══════════════════════════════════════════════════════════════════════
HF_API_TOKEN = os.getenv("HF_API_TOKEN", "")  # Opsiyonel, free tier var


async def huggingface_inference(
    model: str,
    inputs: str | dict | list,
    task: str = "text-classification",
) -> dict:
    """Hugging Face Inference API — model uzaktan calistir.

    NOT (2025+): HF Inference API auth zorunlu hale geldi (eski free 404).
    Yeni endpoint: https://router.huggingface.co/hf-inference/...
    HF_API_TOKEN .env'de tanimliysa calisir, yoksa hata mesaji.

    Task'lar: text-classification, summarization, translation, question-answering,
    zero-shot-classification, fill-mask, ner, embedding, ...

    Ornek:
        >>> r = await huggingface_inference(
        ...     "savasy/bert-base-turkish-sentiment-cased",
        ...     "Bu film harikaydi!",
        ...     task="text-classification",
        ... )
    """
    if not model:
        return {"success": False, "error": "Model adi bos"}
    if not HF_API_TOKEN:
        return {
            "success": False,
            "error": "HF_API_TOKEN env tanimli degil — HF Inference auth zorunlu",
            "hint": "Free tier: https://huggingface.co/settings/tokens, .env'e HF_API_TOKEN=hf_...",
        }
    try:
        # Yeni router endpoint (2024+)
        url = f"https://router.huggingface.co/hf-inference/models/{model}"
        headers = {
            "User-Agent": _USER_AGENT,
            "Authorization": f"Bearer {HF_API_TOKEN}",
        }
        payload = {"inputs": inputs}
        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT * 3,  # HF cold-start uzun (60s'e kadar)
            headers=headers,
            follow_redirects=True,
        ) as client:
            r = await client.post(url, json=payload)
            if r.status_code == 503:
                return {
                    "success": False,
                    "error": "Model yukleniyor, 30 saniye sonra tekrar dene",
                    "model_loading": True,
                }
            if r.status_code in (401, 403):
                return {"success": False, "error": "HF token gecersiz veya yetki yetersiz"}
            if r.status_code == 404:
                return {"success": False, "error": f"Model bulunamadi: {model}"}
            if r.status_code != 200:
                return {"success": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
            data = r.json()
        return {
            "success": True,
            "model": model,
            "task": task,
            "result": data,
        }
    except Exception as e:
        logger.warning(f"huggingface_inference hata: {e}")
        return {"success": False, "error": str(e)}


async def huggingface_search_models(query: str, max_results: int = 5) -> dict:
    """HF Hub model arama (auth gerek YOK, free).

    Inference yapmadan modelleri bulmak icin — alternatif/yedek.
    """
    if not query:
        return {"success": False, "error": "Sorgu bos"}
    try:
        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        ) as client:
            r = await client.get(
                "https://huggingface.co/api/models",
                params={"search": query, "limit": min(max_results, 20)},
            )
            if r.status_code != 200:
                return {"success": False, "error": f"HTTP {r.status_code}"}
            data = r.json()
        results = []
        for m in (data or [])[:max_results]:
            results.append({
                "id": m.get("modelId") or m.get("id", ""),
                "downloads": m.get("downloads", 0),
                "likes": m.get("likes", 0),
                "tags": (m.get("tags") or [])[:5],
                "url": f"https://huggingface.co/{m.get('modelId') or m.get('id', '')}",
            })
        return {
            "success": True,
            "found": bool(results),
            "query": query,
            "results": results,
        }
    except Exception as e:
        logger.warning(f"huggingface_search_models hata: {e}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# 20. TUIK DATASET — Turkiye istatistik verileri (cached snapshot)
# ═══════════════════════════════════════════════════════════════════════
# TUIK API publically yok, manuel veri seti (statik snapshot, periyodik update).
# Cografya/Sosyal sorularinda Turkiye-spesifik veriler:
_TUIK_DATASET = {
    "nufus_2024": {
        "yil": 2024,
        "toplam": 85_372_377,
        "erkek": 42_840_000,
        "kadin": 42_532_000,
        "kentsel_yuzde": 93.4,
        "kirsal_yuzde": 6.6,
        "kaynak": "TUIK ADNKS 2024",
    },
    "yuzolcumu": {
        "km2": 783_562,
        "kara_km2": 769_604,
        "su_km2": 13_958,
        "kaynak": "Harita Genel Mudurlugu",
    },
    "il_sayisi": {
        "il": 81,
        "ilce": 922,
        "buyukşehir": 30,
        "kaynak": "ICIM 2024",
    },
    "ekonomik_2024": {
        "gsyih_milyar_dolar": 1108,
        "kisi_basi_dolar": 12986,
        "issizlik_yuzde": 8.6,
        "enflasyon_yuzde": 44.4,
        "kaynak": "TUIK 2024 Q4",
    },
    "egitim_2024": {
        "okumayazma_yuzde": 96.8,
        "yuksekogretim_okul_sayisi": 209,
        "ogrenci_sayisi": 8_600_000,
        "kaynak": "MEB Istatistik 2024",
    },
    "iklim_bolgeleri": {
        "akdeniz": "yazlari sicak-kuru, kislari ilik-yagisli",
        "karadeniz": "her mevsim yagisli, ilik nemli",
        "ic_anadolu": "kara iklimi, kis soguk-yazi sicak",
        "dogu_anadolu": "sert kara iklimi, uzun sogan kis",
        "guneydogu_anadolu": "step iklimi, yaz cok sicak kuru",
        "ege": "akdeniz yumusak versiyon",
        "marmara": "gecis iklimi (4 mevsim)",
    },
    "tarim_urun": {
        "fındık": "Karadeniz",
        "incir": "Ege",
        "muz": "Akdeniz",
        "pamuk": "GAP (Sanliurfa, Diyarbakir)",
        "cay": "Rize, Trabzon (Karadeniz)",
        "tutun": "Ege, Karadeniz",
        "uzum": "Akdeniz, Ege, Ic Anadolu",
        "buday": "Konya, Ic Anadolu",
        "seker_pancari": "Konya, Eskisehir",
    },
}


async def tuik_dataset(category: str) -> dict:
    """TUIK / Turkiye genel istatistik dataset (statik snapshot).

    Kategoriler: nufus_2024, yuzolcumu, il_sayisi, ekonomik_2024,
                 egitim_2024, iklim_bolgeleri, tarim_urun
    """
    if not category:
        return {
            "success": True,
            "categories": list(_TUIK_DATASET.keys()),
            "message": "Kategori belirt",
        }
    cat = category.strip().lower().replace(" ", "_")
    # Alias eslestirme
    aliases = {
        "nufus": "nufus_2024",
        "ekonomi": "ekonomik_2024",
        "egitim": "egitim_2024",
        "iklim": "iklim_bolgeleri",
        "tarim": "tarim_urun",
        "il": "il_sayisi",
        "alan": "yuzolcumu",
    }
    cat = aliases.get(cat, cat)

    if cat not in _TUIK_DATASET:
        return {
            "success": True,
            "found": False,
            "query": category,
            "available": list(_TUIK_DATASET.keys()),
        }
    return {
        "success": True,
        "found": True,
        "category": cat,
        "data": _TUIK_DATASET[cat],
    }


# ═══════════════════════════════════════════════════════════════════════
# 21. ALPHAFOLD (EBI) — DeepMind protein yapi tahmini
# ═══════════════════════════════════════════════════════════════════════
async def alphafold_lookup(uniprot_id: str) -> dict:
    """AlphaFold Protein Structure Database (EBI).

    Endpoint: https://alphafold.ebi.ac.uk/api/prediction/<UniProt>

    YKS-AYT Bio: gelismis ogrenci icin protein yapi gosterimi.
    Insulin (P01308), Hemoglobin alpha (P69905) gibi.

    Ornek:
        >>> r = await alphafold_lookup("P69905")  # hemoglobin alpha
        >>> r["pdb_url"]
    """
    if not uniprot_id or len(uniprot_id) > 12:
        return {"success": False, "error": "UniProt ID gecersiz"}
    try:
        url = f"https://alphafold.ebi.ac.uk/api/prediction/{uniprot_id.strip().upper()}"
        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        ) as client:
            r = await client.get(url)
            if r.status_code == 404:
                return {
                    "success": True,
                    "found": False,
                    "uniprot_id": uniprot_id,
                    "message": "Protein bulunamadi",
                }
            if r.status_code != 200:
                return {"success": False, "error": f"HTTP {r.status_code}"}
            data = r.json()
        if not data:
            return {"success": True, "found": False, "uniprot_id": uniprot_id}
        item = data[0] if isinstance(data, list) else data
        return {
            "success": True,
            "found": True,
            "uniprot_id": uniprot_id,
            "name": item.get("entryId", ""),
            "organism": item.get("organismScientificName", ""),
            "gene": item.get("gene", ""),
            "uniprot_description": item.get("uniprotDescription", "")[:500],
            "model_url": item.get("modelCifUrl", ""),
            "pdb_url": item.get("pdbUrl", ""),
            "image_url": item.get("imageUrl", ""),
            "sequence_length": item.get("sequenceLength", 0),
            "source": "AlphaFold (DeepMind / EBI)",
        }
    except Exception as e:
        logger.warning(f"alphafold_lookup hata: {e}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# 22. NIST WEBBOOK — kimya termodinamik (ad/CAS/formul -> termo veriler)
# ═══════════════════════════════════════════════════════════════════════
async def nist_webbook(query: str) -> dict:
    """NIST Chemistry WebBook — kimyasal madde termodinamik verileri.

    NIST WebBook full API yok, ama HTML sayfa parse edilebilir.
    Yedek strateji: PubChem ile sinerji + NIST sabit linki.

    Ornek output: HTML link + onerilen PubChem ile cross-ref.
    """
    if not query:
        return {"success": False, "error": "Sorgu bos"}
    try:
        # NIST webbook yapisini kullan
        # https://webbook.nist.gov/cgi/cbook.cgi?Name=water&Units=SI
        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        ) as client:
            url = f"https://webbook.nist.gov/cgi/cbook.cgi?Name={quote_plus(query)}&Units=SI"
            r = await client.get(url)
            if r.status_code != 200:
                return {"success": False, "error": f"HTTP {r.status_code}"}
            html = r.text[:50000]  # Sadece ilk 50K char

        # Basit HTML parse — title + key data
        import re
        # Maddenin formulu
        formula_m = re.search(r"Formula:\s*</strong>\s*<[^>]+>([^<]+)", html, re.IGNORECASE)
        # Molekul agirligi
        mw_m = re.search(r"Molecular weight:\s*</strong>\s*<[^>]+>([^<]+)", html, re.IGNORECASE)
        # CAS no
        cas_m = re.search(r"CAS Registry Number:\s*</strong>\s*<[^>]+>([^<]+)", html, re.IGNORECASE)
        # Standart entalpi (Heat of formation)
        heat_m = re.search(r"ΔfH°gas[^<]*<[^>]+>\s*([\-\d.]+)\s*kJ/mol", html)

        bulundu = bool(formula_m or mw_m or cas_m)
        return {
            "success": True,
            "found": bulundu,
            "query": query,
            "formula": formula_m.group(1).strip() if formula_m else "",
            "molecular_weight": mw_m.group(1).strip() if mw_m else "",
            "cas_number": cas_m.group(1).strip() if cas_m else "",
            "heat_of_formation_kj_mol": heat_m.group(1).strip() if heat_m else "",
            "url": f"https://webbook.nist.gov/cgi/cbook.cgi?Name={quote_plus(query)}",
            "source": "NIST Chemistry WebBook",
        }
    except Exception as e:
        logger.warning(f"nist_webbook hata: {e}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# 23. CROSSREF / Akademik makale arama
# ═══════════════════════════════════════════════════════════════════════
async def crossref_search(query: str, max_results: int = 5) -> dict:
    """Crossref — akademik makale arama (DOI, baslik, yazar).

    Endpoint: https://api.crossref.org/works?query=X
    JSTOR yerine — Crossref free + sinirsiz.

    YKS Tarih/Edebiyat: ileri arastirma sorulari icin.
    """
    if not query:
        return {"success": False, "error": "Sorgu bos"}
    try:
        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        ) as client:
            url = "https://api.crossref.org/works"
            params = {"query": query, "rows": min(max_results, 10), "select": "DOI,title,author,published,abstract,URL,type"}
            r = await client.get(url, params=params)
            if r.status_code != 200:
                return {"success": False, "error": f"HTTP {r.status_code}"}
            data = r.json()

        items = data.get("message", {}).get("items", [])
        results = []
        for item in items[:max_results]:
            authors = item.get("author") or []
            author_names = ", ".join(
                f"{a.get('given', '')} {a.get('family', '')}".strip()
                for a in authors[:3]
            )
            published = item.get("published", {}).get("date-parts", [[None]])[0]
            results.append({
                "doi": item.get("DOI", ""),
                "title": (item.get("title") or [""])[0][:300],
                "authors": author_names,
                "year": published[0] if published else "",
                "type": item.get("type", ""),
                "abstract": (item.get("abstract") or "")[:500],
                "url": item.get("URL", "") or f"https://doi.org/{item.get('DOI', '')}",
            })
        return {
            "success": True,
            "found": bool(results),
            "query": query,
            "total_matches": data.get("message", {}).get("total-results", 0),
            "results": results,
        }
    except Exception as e:
        logger.warning(f"crossref_search hata: {e}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# 24. OPENSTREETMAP NOMINATIM — cografya konum
# ═══════════════════════════════════════════════════════════════════════
async def osm_lookup(query: str) -> dict:
    """OpenStreetMap Nominatim — geocoding (yer adi → koordinat + detay).

    Endpoint: https://nominatim.openstreetmap.org/search

    YKS Cografya: harita sorulari, konum spesifik veri.

    Ornek:
        >>> r = await osm_lookup("Topkapi Sarayi")
        >>> r["lat"], r["lon"]
    """
    if not query:
        return {"success": False, "error": "Sorgu bos"}
    try:
        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT,
            headers={"User-Agent": _USER_AGENT},  # Nominatim UA zorunlu
            follow_redirects=True,
        ) as client:
            url = "https://nominatim.openstreetmap.org/search"
            params = {
                "q": query,
                "format": "json",
                "limit": 3,
                "addressdetails": 1,
                "extratags": 1,
                "accept-language": "tr",
            }
            r = await client.get(url, params=params)
            if r.status_code != 200:
                return {"success": False, "error": f"HTTP {r.status_code}"}
            data = r.json()

        if not data:
            return {
                "success": True,
                "found": False,
                "query": query,
                "message": "Konum bulunamadi",
            }
        results = []
        for item in data[:3]:
            results.append({
                "display_name": item.get("display_name", ""),
                "lat": float(item.get("lat", 0)),
                "lon": float(item.get("lon", 0)),
                "category": item.get("category", ""),
                "type": item.get("type", ""),
                "importance": item.get("importance", 0),
                "country": item.get("address", {}).get("country", ""),
                "city": (
                    item.get("address", {}).get("city") or
                    item.get("address", {}).get("town") or
                    item.get("address", {}).get("village", "")
                ),
                "extra": item.get("extratags", {}),
            })
        return {
            "success": True,
            "found": True,
            "query": query,
            "results": results,
        }
    except Exception as e:
        logger.warning(f"osm_lookup hata: {e}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# Self-test (import-time, ucuz — ama HTTP cagrilari ASYNC'de manuel)
# ═══════════════════════════════════════════════════════════════════════
async def _self_test():
    """Tum 12 API'yi hizli sirayla test et (manuel kullanim)."""
    print("=== EXTERNAL APIS V3 — 12 API SMOKE ===\n")
    tests = [
        ("TDK", tdk_sozluk("müşfik")),
        ("NIST const", nist_constant("planck")),
        ("OEIS", oeis_search("1,1,2,3,5,8")),
        ("Open-Meteo", open_meteo_climate("Istanbul")),
        ("Wikidata", wikidata_lookup("Atatürk")),
        ("CERN", cern_open_data("higgs")),
        ("HF Search", huggingface_search_models("turkish bert")),
        ("TUIK", tuik_dataset("nufus_2024")),
        ("AlphaFold", alphafold_lookup("P69905")),  # Hemoglobin alpha
        ("NIST WebBook", nist_webbook("water")),
        ("Crossref", crossref_search("turkish education")),
        ("OSM", osm_lookup("Topkapi Sarayi Istanbul")),
    ]
    pass_count = 0
    for name, coro in tests:
        try:
            r = await coro
            ok = r.get("success", False)
            label = "[OK]" if ok else "[FAIL]"
            extra = ""
            if ok:
                if r.get("found") is False:
                    extra = " (data yok ama API OK)"
                pass_count += 1
            else:
                extra = f" — {r.get('error', '')[:60]}"
            print(f"  {label} {name}{extra}")
        except Exception as e:
            print(f"  [EXC] {name} — {str(e)[:60]}")
    print(f"\n{pass_count}/{len(tests)} API erisilebilir\n")


if __name__ == "__main__":
    asyncio.run(_self_test())
