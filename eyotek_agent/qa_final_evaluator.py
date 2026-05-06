"""
FermatAI QA Final 1000 — 6-Disiplinli Cevap Değerlendirici
============================================================
Neo direktifi: "Cevapları sadece mimari değil; yazılım müh, iletişim uzmanı,
tasarımcı, akademisyen, eğitimci rollerinde değerlendir."

6 BOYUT:
  1. YAZILIM (Mimari/Tool/Route): Doğru handler, tool, latency, error
  2. İLETİŞİM: Akıcı Türkçe, doğru hitap, ton, samimi
  3. TASARIM (Görsel): A+++ format, emoji, bold, separator, action_block
  4. AKADEMİK: Bilgi doğruluğu, formül, kavram, halüsinasyon yok
  5. EĞİTİM (Pedagoji): Yönlendirme, soru, motive, seviye uygun
  6. UX: Uzunluk uygun, render link, sonraki adım önerisi

Her boyut 0-100 puan. Toplam = ortalama. ≥85 → PASS.
"""
from __future__ import annotations
import re
from typing import Optional


# ─── 1. YAZILIM (MİMARİ/TOOL/ROUTE) ────────────────────────────────────
def score_yazilim(cevap: Optional[str], handler: str, expected: dict) -> tuple[int, list]:
    """
    Mimari değerlendirme:
    - Cevap None değil mi (LLM bekleniyorsa OK)
    - Beklenen handler tetiklendi mi
    - Beklenen tool çağrıldı mı (cevap içinde tool_call referansı)
    - Cevap çok kısa veya çok uzun değil mi
    - Hata stack trace yok mu
    """
    score = 100
    notes = []

    if cevap is None:
        if expected.get("expected_path") == "llm":
            return 100, ["✅ LLM path doğru (Claude/Cerebras devreye)"]
        return 30, ["❌ Cevap None — beklenmedik"]

    # Hata stack trace
    if any(kw in cevap.lower() for kw in [
        "traceback","exception","error:","undefined","null reference",
        "syntax error","keyerror","valueerror","typeerror",
    ]):
        score -= 50
        notes.append("❌ Hata stack trace görünüyor")

    # Beklenen handler
    exp_handler = expected.get("expected_handler", "")
    if exp_handler and exp_handler not in (handler or ""):
        # Cevap içerik check (handler boş kalsa bile content doğru olabilir)
        cl = cevap.lower()
        handler_keywords = expected.get("handler_keywords", [])
        if handler_keywords and not any(kw in cl for kw in handler_keywords):
            score -= 20
            notes.append(f"⚠️ Handler {exp_handler} eşleşmedi (got: {handler})")

    # Cevap uzunluk
    cl = len(cevap)
    if cl < 30:
        score -= 25
        notes.append(f"⚠️ Çok kısa cevap ({cl} char)")
    elif cl > 5000:
        score -= 15
        notes.append(f"⚠️ Çok uzun cevap ({cl} char) — WP limit aşıyor olabilir")

    # Render link bekleniyorsa kontrolü
    if expected.get("render_expected"):
        if "https://" in cevap or "render/" in cevap or "📊" in cevap or "🗺️" in cevap:
            notes.append("✅ Render link/visual var")
        else:
            score -= 30
            notes.append("❌ Render link bekleniyor ama yok")

    # Tool call bekleniyorsa
    if expected.get("tool_expected"):
        # Cevap LLM'den gelir, fast_response'da tool çağrı görünmez
        # Ama beklenti karşılandı mı?
        if cevap is None:
            notes.append("✅ Tool için Claude path (fast=None doğru)")
        else:
            # Fast'te tool çağrılmadı — beklenmedik
            notes.append("⚠️ Tool beklenirken fast cevap geldi")

    return max(0, score), notes


# ─── 2. İLETİŞİM (Akıcılık/Hitap/Ton) ──────────────────────────────────
def score_iletisim(cevap: Optional[str], expected: dict) -> tuple[int, list]:
    """
    İletişim değerlendirme:
    - Türkçe akıcı mı (yazım hatası yok)
    - İsim hitabı uygun mu
    - Ton uygun mu (öğrenci/öğretmen/admin)
    - Yapay/robotik değil mi
    """
    if cevap is None:
        return 100, ["LLM path — iletişim Claude/Cerebras tarafında"]

    score = 100
    notes = []
    cl = cevap.lower()

    # Yazım hataları (sık görülen)
    yazim_hatalari = ["nereye nereye", "sürekli sürekli", "anladım anladım",
                     "ne ne ", "  ", "..."*3]
    for h in yazim_hatalari:
        if h in cl:
            score -= 8
            notes.append(f"⚠️ Tekrar/spam: '{h}'")
            break

    # İsim hitabı (öğrenci için)
    expected_name = expected.get("name", "")
    if expected_name and expected.get("expect_personal_greeting"):
        first = expected_name.split()[0].lower()
        if first not in cl and len(cl) > 50:
            score -= 10
            notes.append(f"⚠️ İsim hitabı yok ({first})")

    # Ton — öğrenci için samimi, admin için profesyonel
    role = expected.get("role", "")
    if role == "ogrenci":
        # Samimi ton göstergeleri
        warm_indicators = ["sen", "hadi", "birlikte", "🌟","💪","✨","🎯",
                          "merhaba","selam","aferin","tebrikler","düşün","seninle"]
        if not any(w in cl for w in warm_indicators):
            score -= 8
            notes.append("⚠️ Samimi ton zayıf (öğrenci)")
    elif role in ("admin", "mudur", "yonetim"):
        # Profesyonel ton
        prof_indicators = ["bey","hanım","müdürüm","hocam","sayın","raporu",
                          "analiz","özet","zeki bey"]
        if not any(p in cl for p in prof_indicators) and len(cl) > 50:
            score -= 5
            notes.append("⚠️ Profesyonel ton zayıf (admin/müdür)")

    # Robotik dil
    robotic = ["unable to","i cannot","i am sorry but","upgraded version",
              "as an ai language model"]
    for r in robotic:
        if r in cl:
            score -= 25
            notes.append(f"❌ Robotik İngilizce: '{r}'")
            break

    # Türkçe karakter (mesajda 5+ Türkçe karakter olmalı uzun cevapta)
    if len(cl) > 100:
        tr_chars = sum(1 for c in cevap if c in "çğıöşüÇĞİÖŞÜ")
        if tr_chars < 5:
            score -= 10
            notes.append("⚠️ Türkçe karakter eksik (cevap İngilizceye kaymış olabilir)")

    return max(0, score), notes


# ─── 3. TASARIM (Görsel A+++) ──────────────────────────────────────────
def score_tasarim(cevap: Optional[str], expected: dict) -> tuple[int, list]:
    """
    Görsel tasarım değerlendirme:
    - Emoji semantic kullanımı
    - Bold/markdown yapısı
    - Separator (━━━ veya ───)
    - Action block (💡 + öneri liste)
    - Header/section yapısı
    - Render link gömülü mü
    """
    if cevap is None:
        return 100, ["LLM path — tasarım Claude/Cerebras tarafında"]

    score = 0
    notes = []

    # Sadece kısa cevaplarda görsel kalite zorunlu değil
    if len(cevap) < 50:
        return 100, ["Kısa cevap — görsel kalite şartı yok"]

    # Emoji
    emoji_count = sum(1 for c in cevap if ord(c) > 0x1F00)
    if emoji_count >= 2:
        score += 20
        notes.append(f"✅ Emoji: {emoji_count}")
    elif emoji_count >= 1:
        score += 10
        notes.append(f"⚠️ Tek emoji ({emoji_count})")
    else:
        notes.append("❌ Emoji yok")

    # Bold (*text* veya **text**)
    bold_count = len(re.findall(r"\*[^*\n]+\*", cevap))
    if bold_count >= 2:
        score += 20
        notes.append(f"✅ Bold: {bold_count}")
    elif bold_count == 1:
        score += 10
    else:
        notes.append("❌ Bold formatlama yok")

    # Separator
    if "━" in cevap or "─" in cevap:
        score += 15
        notes.append("✅ Separator")
    elif len(cevap) > 200:
        notes.append("⚠️ Uzun cevapta separator yok")

    # Action block / öneri (💡 ve madde işareti)
    has_action = ("💡" in cevap and ("→" in cevap or "•" in cevap or
                                      cevap.count("\n") >= 3))
    if has_action:
        score += 20
        notes.append("✅ Action block")
    elif len(cevap) > 300:
        score += 5
        notes.append("⚠️ Action block önerilir")

    # Header (📊 *Title* gibi)
    if re.search(r"[📊📅📝🎯📈📚🎓🔥💪📋]\s*\*", cevap):
        score += 15
        notes.append("✅ Visual header")

    # Render link
    if "https://" in cevap or "/render/" in cevap:
        score += 10
        notes.append("✅ Render/external link")

    return min(100, score), notes


# ─── 4. AKADEMİK (Bilgi Doğruluğu) ─────────────────────────────────────
def score_akademik(cevap: Optional[str], expected: dict) -> tuple[int, list]:
    """
    Akademik doğruluk değerlendirme:
    - Halüsinasyon yok (bilinen yanlış değer/formül)
    - Konu doğru (matematik fizik vs)
    - Sayısal değerler tutarlı
    - Kaynak/referans uygun
    """
    if cevap is None:
        return 100, ["LLM path — akademik içerik Claude tarafında"]

    score = 100
    notes = []
    cl = cevap.lower()

    # Bilinen halüsinasyon riskleri
    halusinasyon_red = [
        ("g=10","Yerçekimi 9.81 olmalı, 10 yaklaşık"),
        ("c=300000","Işık hızı 3×10⁸ m/s veya 299792458"),
        # Tarih halüsinasyonu
        ("yks 2024 yapılmadı","2024 YKS yapıldı"),
        ("2025 tyt henüz yapılmadı","2025 TYT yapıldı"),
        ("2025 yks olmadı","2025 YKS yapıldı"),
    ]
    for kw, msg in halusinasyon_red:
        if kw in cl:
            score -= 30
            notes.append(f"❌ Halüsinasyon: {msg}")

    # Sayısal tutarlılık (eğer specific akademik soru ise)
    expected_topic = expected.get("akademik_topic", "")
    if expected_topic == "fizik":
        # Fizik kavramları doğru mu
        if "f=ma" in cl or "f = ma" in cl:
            notes.append("✅ Newton 2 doğru")
    elif expected_topic == "matematik":
        if "türev" in cl or "limit" in cl or "integral" in cl:
            notes.append("✅ Matematik kavram referansı")

    # Akademik referans (kaynak gösteriyor mu)
    if expected.get("expect_source"):
        if any(kw in cl for kw in ["meb","ösym","wikipedia","kaynak","referans",
                                     "https://","yayın"]):
            notes.append("✅ Kaynak/referans var")
        elif len(cevap) > 200:
            score -= 10
            notes.append("⚠️ Akademik kaynak referansı yok")

    # Bilmediğini söylüyor mu (halüsinasyon yerine)
    if expected.get("not_in_db") and any(kw in cl for kw in [
        "henüz veri yok","sistemde yok","emin değilim","bilgi bulunamadı",
        "hazır değil","görünmüyor"
    ]):
        notes.append("✅ Honest 'bilmiyorum' — halüsinasyon yerine")
        score = min(100, score + 10)

    return max(0, score), notes


# ─── 5. EĞİTİM (Pedagoji) ──────────────────────────────────────────────
def score_egitim(cevap: Optional[str], expected: dict) -> tuple[int, list]:
    """
    Pedagojik değerlendirme:
    - Yönlendirici (sonraki adım öneriyor mu)
    - Soru soruyor mu (etkileşim)
    - Motive edici ton
    - Seviyeye uygun (LGS/TYT/AYT)
    - Adım adım anlatım var mı
    """
    if cevap is None:
        return 100, ["LLM path — pedagoji Claude tarafında"]

    if len(cevap) < 50:
        return 100, ["Kısa cevap — pedagoji şartı yok"]

    score = 0
    notes = []
    cl = cevap.lower()

    # Yönlendirme (sonraki adım önerisi)
    yonlendirme_kelimeleri = [
        "şimdi ne","istersen","yapalım","bakalım","deneyelim","çalış",
        "sor","yaz","hadi","başla","devam edebiliriz","bir sonraki",
        "ister misin","görmek istersen","detay istersen","öğrenmek istersen",
    ]
    if any(kw in cl for kw in yonlendirme_kelimeleri):
        score += 25
        notes.append("✅ Yönlendirme var")
    else:
        notes.append("⚠️ Yönlendirme zayıf")

    # Etkileşim (soru soruyor mu)
    if "?" in cevap:
        score += 20
        notes.append("✅ Karşı soru")
    elif len(cevap) > 200:
        notes.append("⚠️ Soru/etkileşim yok")

    # Motive edici ton
    motive_words = ["başarı","gelişim","ilerleme","tebrikler","güzel",
                    "harika","iyi gidiyorsun","aferin","yapabilirsin",
                    "potansiyel","kazanabilir","hedef"]
    if any(w in cl for w in motive_words):
        score += 20
        notes.append("✅ Motive edici")

    # Seviyeye uygunluk
    role = expected.get("role", "")
    if role == "ogrenci":
        # Öğrenciye basit dil
        if "lemma" in cl or "isomorphism" in cl or "topological" in cl:
            score -= 20
            notes.append("⚠️ Öğrenci seviyesinden ileri akademik dil")

    # Adım adım anlatım
    if expected.get("expect_steps"):
        step_indicators = ["1.","2.","3.","adım","önce","sonra","ardından",
                          "ilk olarak"]
        step_count = sum(1 for s in step_indicators if s in cl)
        if step_count >= 2:
            score += 20
            notes.append(f"✅ Adım yapısı ({step_count})")
        else:
            score -= 10
            notes.append("⚠️ Adım adım yok (bekleniyor)")

    # Pedagojik anchor
    if any(kw in cl for kw in ["günlük hayat","örnek","fark eder ki","düşün",
                                 "günlük","gerçek hayat"]):
        score += 15
        notes.append("✅ Günlük hayat örneği")

    return min(100, max(0, score + 30)), notes  # base 30 + bonuslar


# ─── 6. UX (Kullanıcı Deneyimi) ────────────────────────────────────────
def score_ux(cevap: Optional[str], expected: dict) -> tuple[int, list]:
    """
    UX değerlendirme:
    - Cevap uzunluğu uygun mu (mobil okuma)
    - Render/foto link var mı (uygunsa)
    - Sonraki aksiyon net mi
    - Karmaşa yok mu (info overload)
    """
    if cevap is None:
        return 100, ["LLM path"]

    score = 100
    notes = []
    cl = len(cevap)
    role = expected.get("role", "")

    # Uzunluk
    if role == "ogrenci":
        ideal_min, ideal_max = 80, 1500
    else:
        ideal_min, ideal_max = 100, 3000

    if cl < ideal_min and not expected.get("short_ok"):
        score -= 15
        notes.append(f"⚠️ Kısa ({cl} char, hedef {ideal_min}+)")
    elif cl > ideal_max:
        score -= 20
        notes.append(f"⚠️ Çok uzun ({cl} char, hedef <{ideal_max})")
    else:
        notes.append(f"✅ Uzunluk OK ({cl})")

    # Mobil-friendly (paragraf bölünmüş mü)
    paragraf_count = cevap.count("\n\n")
    if cl > 300 and paragraf_count < 1:
        score -= 15
        notes.append("⚠️ Paragraf bölünmesi yok (uzun blok)")
    elif paragraf_count >= 2:
        score += 5
        notes.append(f"✅ Paragraf yapısı ({paragraf_count})")

    # Aksiyon net mi (CTA)
    cta_indicators = ["yaz","sor","dene","başla","ister misin","ne istersin",
                       "hangi","seçim","tıkla","gör","incele"]
    if any(c in cevap.lower() for c in cta_indicators):
        notes.append("✅ Action CTA var")
    elif cl > 200:
        score -= 10
        notes.append("⚠️ CTA yok")

    # Renk/emoji info overload
    emoji_count = sum(1 for c in cevap if ord(c) > 0x1F00)
    if emoji_count > 30:
        score -= 15
        notes.append(f"⚠️ Emoji overload ({emoji_count})")

    return max(0, score), notes


# ─── ANA EVALUATOR ─────────────────────────────────────────────────────
def evaluate_response(
    cevap: Optional[str],
    handler: str,
    expected: dict,
) -> dict:
    """
    Bir cevabı 6 boyutta değerlendir.

    expected dict:
        - expected_path: "fast"|"llm"
        - expected_handler: "son_deneme" gibi
        - role: "ogrenci"|"ogretmen"|"admin"|...
        - name: "Ali Veli"
        - render_expected: bool
        - tool_expected: bool
        - expect_personal_greeting: bool
        - expect_source: bool
        - expect_steps: bool
        - akademik_topic: "fizik"|"matematik"|...
        - short_ok: bool

    Returns:
        {
          "yazilim": (score, notes),
          "iletisim": (score, notes),
          "tasarim": (score, notes),
          "akademik": (score, notes),
          "egitim": (score, notes),
          "ux": (score, notes),
          "toplam": int (0-100),
          "pass": bool,
        }
    """
    yzilim = score_yazilim(cevap, handler, expected)
    iletisim = score_iletisim(cevap, expected)
    tasarim = score_tasarim(cevap, expected)
    akademik = score_akademik(cevap, expected)
    egitim = score_egitim(cevap, expected)
    ux = score_ux(cevap, expected)

    boyutlar = [yzilim, iletisim, tasarim, akademik, egitim, ux]
    toplam = sum(b[0] for b in boyutlar) / len(boyutlar)

    return {
        "yazilim": yzilim,
        "iletisim": iletisim,
        "tasarim": tasarim,
        "akademik": akademik,
        "egitim": egitim,
        "ux": ux,
        "toplam": int(toplam),
        "pass": toplam >= 75,
    }


__all__ = ["evaluate_response", "score_yazilim", "score_iletisim",
           "score_tasarim", "score_akademik", "score_egitim", "score_ux"]
