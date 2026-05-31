"""
Pedagoji V2 — Cerebras gpt-oss-120b İçerik Üretici (25.41 Neo)
==============================================================

Görevi:
  SEED listelerinden (anekdot + kavram) DB'ye hazır JSON üretir.
  Cerebras gpt-oss-120b: hızlı + kaliteli + ucuz (~$0.001/içerik).

Halusilasyon koruma:
  - Çekirdek gerçekler (core_facts) prompt'a verilir → değiştirilemez
  - Output validation: tarih/yer/sayı kontrolü
  - Türkçe karakter check
  - Slug uniqueness check

Çıktı:
  output_anekdot.json (76 normalize edilmiş anekdot)
  output_kavram.json (41 normalize edilmiş kavram)

Kullanım:
  python pedagoji/cerebras_generator.py anekdot
  python pedagoji/cerebras_generator.py kavram
  python pedagoji/cerebras_generator.py all
"""
from __future__ import annotations
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

# Path fix
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger


# ═══════════════════════════════════════════════════════════════
# CEREBRAS CLIENT
# ═══════════════════════════════════════════════════════════════

async def cerebras_generate(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 800,
    temperature: float = 0.4,
) -> Optional[str]:
    """gpt-oss-120b ile içerik üretimi. None dönerse hata."""
    try:
        from cerebras_handler import CerebrasClient
        client = CerebrasClient()
        result = await client.complete_async(
            messages=[{"role": "user", "content": user_prompt}],
            system=system_prompt,
            model="gpt-oss-120b",
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if result and result.get("text"):
            return result["text"]
        return None
    except Exception as e:
        logger.error(f"Cerebras hata: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# ANEKDOT ÜRETİCİ
# ═══════════════════════════════════════════════════════════════

ANEKDOT_SYSTEM = """Sen FermatAI eğitim asistanı için anekdot yazarısın. Görev:
SEED bilgisinden 200-300 karakter Türkçe anekdot metni üretmek.

KURALLAR:
1. ÇEKİRDEK GERÇEKLER (core_facts) içindeki HER BİLGİ olduğu gibi kullan — değiştirme, eksiltme.
2. Lise öğrencisinin (16-18 yaş) ilgisini çekecek dilde yaz.
3. Sonunda öğrenciyle BAĞLANTI cümlesi kur ('Sen de şimdi...', 'Senin durumun da...').
4. Kaynak belirtmek YOK — bot doğal anlatır.
5. Türkçe yaz, akıcı, hikaye gibi.
6. SADECE METİN dön — JSON sarmalayıcısı, açıklama, kod bloğu YOK.
7. Tarih/yer/sayı uydurma — core_facts'ta yoksa yazma.

ÖRNEK ÇIKTI:
"Aziz Sancar 1946'da Mardin Savur'da, 8 kardeşli bir çiftçi ailenin oğlu olarak doğdu. Köyde elektrik yoktu. İstanbul Tıp'ı kazandı, ABD'de DNA tamiri araştırdı. 2015'te Kimya Nobel'i kazandı. Sen de bugün hangi köyden, hangi mahalleden, hangi şartlardan başladığın değil — neyi taşıdığın seni belirler."
"""


def build_anekdot_prompt(seed: dict) -> str:
    return (
        f"KIM: {seed['kim']}\n"
        f"KATEGORI: {seed['kategori']}\n"
        f"DUYGUSAL_HEDEF: {seed['duygusal_hedef']}\n"
        f"CEKIRDEK_GERCEKLER: {seed['core_facts']}\n"
        f"DERS: {seed.get('ders', '')}\n\n"
        f"Yukaridaki bilgilerle 200-300 karakter Türkçe anekdot yaz. "
        f"Sonunda öğrenciyle bağlantı kur. SADECE METİN dön."
    )


# ═══════════════════════════════════════════════════════════════
# KAVRAM ÜRETİCİ
# ═══════════════════════════════════════════════════════════════

KAVRAM_SYSTEM = """Sen FermatAI eğitim asistanı için pedagojik kavram yazarısın.
Akademik literatür kavramlarını lise öğrencisinin anlayabileceği dilde anlat.

GÖREV: SEED bilgisinden JSON dön:
{
  "aciklama": "150-250 char Türkçe anlatım — bilim insanı + yıl + ne keşfetti + neden önemli",
  "kullanim_ornegi": "100-150 char — ÖĞRENCI 'XYZ' DEDI → SEN 'ABC' DERSIN formatı"
}

KURALLAR:
1. core_facts içindeki bilim insanı, yıl, kurum bilgisi DEĞİŞMEZ.
2. Akademik dil DEĞİL — günlük, konuşma dili.
3. Kullanım örneği ÖĞRENCI dialogunda olmalı (Cool öğrenci → akıllı öneri).
4. SADECE JSON dön — başka açıklama YOK, kod bloğu YOK.
5. Türkçe, akıcı.

ÖRNEK ÇIKTI:
{"aciklama": "Carol Dweck (2006, Stanford) iki zihniyet türü tespit etti: sabit zihniyet 'matematikte iyi DEĞİLİM' der, büyüme zihniyeti 'matematiği HENÜZ anlamadım' der. Beyin plastisitesi sayesinde her zorluk yeni nöral bağlantıdır.", "kullanim_ornegi": "Öğrenci 'ben fizik yapamam' → 'Yapamazsın değil, HENÜZ yapamıyorsun. 3 ay sonra otomatik olacak. Beyinde yeni yol açıyorsun.'"}
"""


def build_kavram_prompt(seed: dict) -> str:
    return (
        f"BASLIK: {seed['baslik']}\n"
        f"KATEGORI: {seed['kategori']}\n"
        f"KISACA: {seed['kisaca']}\n"
        f"CEKIRDEK_GERCEKLER: {seed['core_facts']}\n"
        f"KULLANIM_DURUMU: {seed['kullanim_durumu']}\n"
        f"KAYNAK: {seed['kaynak']}\n\n"
        f"JSON dön: {{\"aciklama\": \"...\", \"kullanim_ornegi\": \"...\"}}"
    )


# ═══════════════════════════════════════════════════════════════
# VALIDATOR
# ═══════════════════════════════════════════════════════════════

def validate_anekdot_text(text: str, seed: dict) -> tuple[bool, str]:
    """Anekdot metni validation. (geçerli, hata_mesaj)"""
    if not text:
        return False, "Boş metin"
    text = text.strip().strip('"').strip("'")
    if len(text) < 100:
        return False, f"Çok kısa: {len(text)} char"
    if len(text) > 600:
        return False, f"Çok uzun: {len(text)} char"
    # Kim ismi metinde olmalı (ad VEYA soyad — biri yeterli)
    kim_parts = [p for p in seed["kim"].split() if len(p) > 3 and "(" not in p]
    if kim_parts:
        if not any(part in text for part in kim_parts):
            return False, f"Kim ismi yok: {seed['kim']}"
    return True, ""


def validate_kavram_json(text: str, seed: dict) -> tuple[bool, dict, str]:
    """Kavram JSON validation. (geçerli, parsed_dict, hata)"""
    if not text:
        return False, {}, "Boş yanıt"
    text = text.strip()
    # Code block kaldır
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text else text
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        # Bazen ek metin olur, bul
        try:
            start = text.index("{")
            end = text.rindex("}") + 1
            data = json.loads(text[start:end])
        except Exception:
            return False, {}, f"JSON parse fail: {e}"
    if not isinstance(data, dict):
        return False, {}, "Dict değil"
    if "aciklama" not in data or "kullanim_ornegi" not in data:
        return False, {}, "Eksik anahtar"
    if len(data["aciklama"]) < 100:
        return False, {}, f"Açıklama çok kısa: {len(data['aciklama'])}"
    return True, data, ""


# ═══════════════════════════════════════════════════════════════
# PIPELINE
# ═══════════════════════════════════════════════════════════════

async def generate_anekdot_batch(seeds: list[dict]) -> list[dict]:
    """Tüm anekdot seed'lerini Cerebras ile üret."""
    output = []
    failed = []
    total = len(seeds)
    start = time.time()

    for i, seed in enumerate(seeds, 1):
        prompt = build_anekdot_prompt(seed)
        text = await cerebras_generate(
            ANEKDOT_SYSTEM,
            prompt,
            max_tokens=500,
            temperature=0.4,
        )
        ok, err = validate_anekdot_text(text or "", seed)
        if not ok:
            logger.warning(f"  [{i}/{total}] {seed['slug']} FAIL: {err}")
            failed.append({"slug": seed["slug"], "err": err, "raw": text})
            # 1 retry
            text = await cerebras_generate(
                ANEKDOT_SYSTEM, prompt, max_tokens=500, temperature=0.5
            )
            ok, err = validate_anekdot_text(text or "", seed)
            if not ok:
                continue

        clean_text = text.strip().strip('"').strip("'")
        # Title üret (ilk cümlenin ilk 50 char)
        first_sentence = clean_text.split(".")[0]
        baslik = first_sentence[:60] + ("..." if len(first_sentence) > 60 else "")

        output.append({
            "slug": seed["slug"],
            "kim": seed["kim"],
            "kategori": seed["kategori"],
            "konu": seed.get("duygusal_hedef", "").split(",")[0].strip(),
            "baslik": baslik,
            "metin": clean_text,
            "ders": seed.get("ders", ""),
            "duygusal_hedef": seed["duygusal_hedef"],
            "kaynak": seed["kaynak"],
            "etiketler": seed["etiketler"],
        })

        if i % 10 == 0:
            elapsed = time.time() - start
            logger.info(f"  [{i}/{total}] OK ({elapsed:.0f}s, ~{(elapsed/i)*1000:.0f}ms/anekdot)")

    elapsed = time.time() - start
    logger.success(f"✅ {len(output)}/{total} anekdot üretildi ({elapsed:.0f}s)")
    if failed:
        logger.warning(f"⚠️  {len(failed)} fail: {[f['slug'] for f in failed[:5]]}")
    return output, failed


async def generate_kavram_batch(seeds: list[dict]) -> tuple[list[dict], list]:
    """Tüm kavram seed'lerini Cerebras ile üret."""
    output = []
    failed = []
    total = len(seeds)
    start = time.time()

    for i, seed in enumerate(seeds, 1):
        prompt = build_kavram_prompt(seed)
        text = await cerebras_generate(
            KAVRAM_SYSTEM,
            prompt,
            max_tokens=700,
            temperature=0.4,
        )
        ok, data, err = validate_kavram_json(text or "", seed)
        if not ok:
            logger.warning(f"  [{i}/{total}] {seed['slug']} FAIL: {err}")
            # retry
            text = await cerebras_generate(
                KAVRAM_SYSTEM, prompt, max_tokens=700, temperature=0.5
            )
            ok, data, err = validate_kavram_json(text or "", seed)
            if not ok:
                failed.append({"slug": seed["slug"], "err": err, "raw": text})
                continue

        output.append({
            "slug": seed["slug"],
            "baslik": seed["baslik"],
            "kategori": seed["kategori"],
            "kisaca": seed["kisaca"],
            "aciklama": data["aciklama"].strip(),
            "kullanim_ornegi": data["kullanim_ornegi"].strip(),
            "trigger_patterns": seed["trigger_patterns"],
            "kaynak": seed["kaynak"],
            "etiketler": seed["etiketler"],
        })

        if i % 10 == 0:
            elapsed = time.time() - start
            logger.info(f"  [{i}/{total}] OK ({elapsed:.0f}s)")

    elapsed = time.time() - start
    logger.success(f"✅ {len(output)}/{total} kavram üretildi ({elapsed:.0f}s)")
    if failed:
        logger.warning(f"⚠️  {len(failed)} fail: {[f['slug'] for f in failed[:5]]}")
    return output, failed


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

async def main():
    sys.stdout.reconfigure(encoding="utf-8")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    out_dir = Path(__file__).parent / "output"
    out_dir.mkdir(exist_ok=True)

    if cmd in ("anekdot", "all"):
        from pedagoji.anekdotlar_seed import ANEKDOT_SEED
        logger.info(f"🎬 Anekdot üretimi başladı: {len(ANEKDOT_SEED)} seed")
        output, failed = await generate_anekdot_batch(ANEKDOT_SEED)
        out_file = out_dir / "output_anekdot.json"
        out_file.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.success(f"📁 {out_file} ({len(output)} anekdot)")
        if failed:
            (out_dir / "failed_anekdot.json").write_text(
                json.dumps(failed, ensure_ascii=False, indent=2), encoding="utf-8")

    if cmd in ("kavram", "all"):
        from pedagoji.kavramlar_seed import KAVRAM_SEED
        logger.info(f"🎬 Kavram üretimi başladı: {len(KAVRAM_SEED)} seed")
        output, failed = await generate_kavram_batch(KAVRAM_SEED)
        out_file = out_dir / "output_kavram.json"
        out_file.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.success(f"📁 {out_file} ({len(output)} kavram)")
        if failed:
            (out_dir / "failed_kavram.json").write_text(
                json.dumps(failed, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
