"""
Sistem Self-Awareness Tool (Oturum 22.1h)
==========================================

Neo "ne guncelleme aldın", "son durum", "ne yaptın yarim saat içinde" diye
sordugunda bot KALDIGIM.md dosyasini GERCEK ZAMANLI okur ve son oturum
bloglarini ozetler.

Oncesi: Bot prompt context'inden tahmin ediyordu → yanliş/eksik cevap
Sonrasi: Dosyayi dogrudan okur → DAKIKA seviyesinde guncel

Kullanim (Claude tool):
    {"max_sessions": 3, "max_chars": 4000}
"""
import os
import re
import json
from pathlib import Path
from datetime import datetime

# Oturum 25 VPS fix: Laptop-specific Windows path kaldirildi.
# Path(__file__) ile dinamik: eyotek_agent/../KALDIGIM.md
# Laptop: C:\...\FermatAI\KALDIGIM.md | VPS: /opt/fermatai/KALDIGIM.md
KALDIGIM_PATH = Path(__file__).resolve().parent.parent / "KALDIGIM.md"


def get_recent_updates(max_sessions: int = 3, max_chars: int = 4000,
                        summary_mode: bool = False) -> dict:
    """
    KALDIGIM.md'den son N oturum blogunu cek + ozet meta bilgi.

    Args:
        max_sessions: kac son oturum
        max_chars: toplam karakter budget
        summary_mode: True ise icerik yerine SADECE baslik + tarih (admin inject icin kisa)

    Returns:
        {
          "header_info": {...},       # son guncelleme, bridge surumu, vb
          "recent_sessions": [         # son N oturum
              {"baslik": "22.1g", "tarih": "...", "icerik": "..." (summary_mode false),
               "icerik_ozet": "..." (summary_mode true)}
          ],
          "file_modified_at": "...",   # dosyanin son mtime'i
          "file_age_minutes": N,       # dakika cinsinden yaş
          "total_sessions_found": N,
        }
    """
    if not KALDIGIM_PATH.exists():
        return {"error": f"KALDIGIM.md bulunamadi: {KALDIGIM_PATH}"}

    # Dosya meta
    stat = KALDIGIM_PATH.stat()
    mtime = datetime.fromtimestamp(stat.st_mtime)
    age_min = (datetime.now() - mtime).total_seconds() / 60

    # Dosya oku
    try:
        full = KALDIGIM_PATH.read_text(encoding="utf-8")
    except Exception as e:
        return {"error": f"Dosya okunamadi: {e}"}

    # Header meta bilgi (ilk 10 satir)
    header = full[:1500]
    header_info = {}
    m = re.search(r"Son güncelleme:\s*([^\n]+)", header)
    if m:
        header_info["son_guncelleme"] = m.group(1).strip()
    m = re.search(r"Bridge:\s*([^\n]+)", header)
    if m:
        header_info["bridge"] = m.group(1).strip()[:150]
    m = re.search(r"Özellikler:\s*([^\n]+)", header)
    if m:
        header_info["ozellikler"] = m.group(1).strip()[:300]

    # Oturum bloklari — `## <emoji> OTURUM|X.Yz-xxx` ile baslayan
    # 22.1n itibariyle blok basliklari cesitli emoji + versiyon formatlari:
    #   ## 🆕 OTURUM 22.1n (...) — ...
    #   ## 🧠 22.1n-farkindalik (...) — ...
    #   ## ✅ 22.1n-sonuclar (...) — ...
    #   ## 🤝 22.1n-toplanti (...) — ...
    # Ortak: "## <emoji> [OTURUM]? <versiyon> (tarih) — baslik"
    session_pattern = re.compile(
        r"(##\s+[^\w\s]+\s*(?:OTURUM\s+)?(\d+\.\d+[a-z]*(?:-\w+)?)\s+.*?)(?=\n##\s+[^\w\s]+\s*(?:OTURUM\s+)?\d+\.\d+[a-z]*|\Z)",
        re.DOTALL,
    )
    matches = list(session_pattern.finditer(full))
    total_found = len(matches)

    recent = []
    remaining_chars = max_chars
    for m in matches[:max_sessions]:
        blok = m.group(1).strip()
        versiyon = m.group(2)
        # Tarih extract (ilk satirdan)
        tarih_m = re.search(r"\((\d{1,2}\s+\w+[\d\s:-]*)\)", blok[:200])
        tarih = tarih_m.group(1) if tarih_m else ""

        if summary_mode:
            # Sadece basligi + ilk 2 satiri (inject icin kisa format)
            first_line = blok.split("\n", 1)[0][:120]  # "## 🆕 22.1g (Tarih) — Baslik"
            recent.append({
                "versiyon": versiyon,
                "tarih": tarih,
                "baslik_satiri": first_line,
            })
            # Budget dogal kucuk (5 oturum ≈ 500 char)
            continue

        # Detay mod: tam içerik truncate
        if len(blok) > remaining_chars:
            blok = blok[:remaining_chars] + "\n\n[... oturum daha uzun, max_chars limit]"
            remaining_chars = 0
        else:
            remaining_chars -= len(blok)

        recent.append({
            "versiyon": versiyon,
            "tarih": tarih,
            "icerik": blok,
        })

        if remaining_chars <= 0:
            break

    return {
        "header_info": header_info,
        "recent_sessions": recent,
        "file_modified_at": mtime.strftime("%d.%m.%Y %H:%M"),
        "file_age_minutes": round(age_min, 1),
        "total_sessions_found": total_found,
    }


def get_session_summary(versiyon: str = "") -> dict:
    """Belirli bir oturum versiyonu (orn: '22.1g') detayini ver."""
    if not KALDIGIM_PATH.exists():
        return {"error": "KALDIGIM.md bulunamadi"}
    full = KALDIGIM_PATH.read_text(encoding="utf-8")

    if not versiyon:
        # Default: en yenisi
        m = re.search(r"## 🆕 OTURUM\s+([\d.a-z]+)", full)
        if m:
            versiyon = m.group(1)
        else:
            return {"error": "Hic oturum bulunamadi"}

    # Spesifik oturumu bul
    pattern = rf"(## 🆕 OTURUM\s+{re.escape(versiyon)}\s+.*?)(?=## 🆕 OTURUM |\Z)"
    m = re.search(pattern, full, re.DOTALL)
    if not m:
        return {"error": f"Oturum {versiyon} bulunamadi"}

    icerik = m.group(1).strip()
    return {
        "versiyon": versiyon,
        "icerik": icerik[:5000],  # max 5k char
        "total_char": len(icerik),
    }


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    result = get_recent_updates(max_sessions=3, max_chars=3000)
    print("=" * 60)
    print("KALDIGIM.md son oturumlar")
    print("=" * 60)
    if "error" in result:
        print(f"ERROR: {result['error']}")
    else:
        print(f"Dosya: {result['file_modified_at']} ({result['file_age_minutes']:.1f} dk once)")
        print(f"Toplam oturum: {result['total_sessions_found']}")
        print(f"\nHeader:\n  Son guncelleme: {result['header_info'].get('son_guncelleme', '-')}")
        print(f"  Bridge: {result['header_info'].get('bridge', '-')[:100]}")
        print(f"\nSon {len(result['recent_sessions'])} oturum:")
        for s in result["recent_sessions"]:
            print(f"\n=== {s['versiyon']} ({s['tarih']}) — {len(s['icerik'])} char ===")
            print(s["icerik"][:500] + "...")
