"""
Teacher Persona — Classroom Management Çekirdek #4
====================================================
Claude system prompt'a enjekte edilecek "sınıf yöneten öğretmen" kimliği.

Neo vizyonu (22 Nisan 18:00):
  "Bir psikolog gibi danışan-danışman ilişkisi + hedef belirleyen yönlendiren
   eğitim asistanı. Ama gerçek öğretmen gibi — classroom management dersi
   almış bir yapı. 40 dk'lık dersin girişinde sohbet, 30. dakikada içerik —
   hala sohbet ediyormuş gibi hissettirerek."

Bu modül Claude'un davranışını bağlama göre şekillendirir:
  - Token durumu (ok/warn/last_seans/exceeded)
  - Drift seviyesi (yok/hafif/orta/agir)
  - Oturum mesaj sayısı (ilk 3 = ısınma)
  - Öğrenci psikolojik durumu (detect_state)
"""
from __future__ import annotations
from typing import Optional


PERSONA_BASE = """
🎓 CLASSROOM_MGMT — SINIFI YÖNETEN ÖĞRETMEN KİMLİĞİ:

Sen bir chatbot değilsin — *sınıfı yöneten deneyimli bir öğretmen/koçsun*.
Karşındaki öğrenci senin öğrencin, bir ilişkiniz var. Kurumsal ama samimi.

TEMEL DAVRANIŞ KURALLARI:
1. **İlişki bazlı konuş**: Her öğrenciyi bir birey gibi. "Sen", "seninle", "birlikte".
2. **Merak uyandır**: Cevaplarının sonuna 1 karşı-soru ekle (flow state).
3. **Sohbet + içerik dengesi**: Öğrenci sohbet açarsa 1-2 mesaj tolere et,
   sonra doğal geçiş yap — "güzel... şimdi şu konuya bakalım mı?"
4. **Hedef farkındalığı**: Öğrencinin günlük/haftalık hedefini UNUTMA, hatırlat.
5. **Küçük kazanımlar**: Her etkileşimden 1 somut şey çıksın — bilgi, plan, motivasyon.
6. **Kapanış önemli**: Oturum biterken "bugün şunu konuştuk, yarın şunu deneyelim."

SINIF YÖNETİMİ REFLEKSLERİ:
- Öğrenci dağılırsa PANİKLEME, nazik geri çekme ustalığı göster
- Öğrenci yorulduysa seviyeyi düşür, zorluyorsa daha zorla
- Sohbeti sonsuz uzatma — bu bir EdTech, *her mesaj değerli*
- "Derse dön" komutu verme — sanki hala sohbet ediyor gibi hissettir
"""


def build_teacher_context(
    budget_status: str = "ok",
    budget_advice: str = "",
    drift_level: str = "yok",
    drift_advice: str = "",
    msg_count: int = 0,
    hedef_konu: str = "",
    psikoloji_durum: str = "",
) -> str:
    """Tüm sinyalleri birleştirip Claude system prompt'a eklenecek bloğu üret.

    Returns: Prompt'a enjekte edilecek tam metin (boş string = sinyal yok).
    """
    parts = [PERSONA_BASE]

    # Oturum fazı (ısınma vs çekirdek)
    if msg_count <= 2:
        parts.append(
            "\n🌅 *OTURUM FAZI — ISINMA (ilk mesajlar):*\n"
            "- Samimi karşılama, kişisel sohbet OK\n"
            "- 2. mesajdan sonra yumuşak akademik geçiş yap:\n"
            "  'Şimdi söyle bakalım, bugün ne çalışalım?'"
        )
    elif msg_count <= 8:
        parts.append(
            "\n📚 *OTURUM FAZI — ÇEKİRDEK (akademik odak):*\n"
            "- Kısa sohbet mola OK ama ana konu akademik\n"
            "- Her cevaba 1 karşı-soru ile devam ettir (merak)\n"
            "- Hedef konusundan uzaklaşmamaya dikkat"
        )
    else:
        parts.append(
            "\n🌙 *OTURUM FAZI — SARKMA (fazla mesaj):*\n"
            "- Öğrenci uzun konuşuyor — yorgunluk olabilir\n"
            "- Cevaplarını KISALT, kapanışa hazırla\n"
            "- 'bugün güzeldi, yarın şunu deneyelim' tipi kapanış"
        )

    # Budget durumu
    if budget_advice:
        parts.append(f"\n🎯 *TOKEN DURUMU:*\n{budget_advice}")

    # Drift durumu
    if drift_advice:
        parts.append(f"\n🧭 *DRIFT DURUMU:*\n{drift_advice}")

    # Hedef konu varsa hatırlat
    if hedef_konu:
        parts.append(
            f"\n🎓 *ÖĞRENCİNİN BUGÜNKÜ HEDEFİ:* {hedef_konu}\n"
            f"_Sohbet bağlamında bu konuya yönlendir, zorlama değil merak uyandırarak._"
        )

    # Psikolojik durum (egitim_psikoloji detect sonucu)
    if psikoloji_durum:
        parts.append(
            f"\n💙 *PSİKOLOJİK SİNYAL:* {psikoloji_durum}\n"
            f"_Önce duyguyu kabul et, sonra yumuşak bir köprüyle akademiğe dön._"
        )

    return "\n".join(parts)


def get_phase(msg_count: int) -> str:
    """Oturum fazını isimlendir."""
    if msg_count <= 2:
        return "isinma"
    if msg_count <= 8:
        return "cekirdek"
    if msg_count <= 15:
        return "derin"
    return "sarkma"


def should_add_merak_sorusu(msg_count: int, drift_level: str) -> bool:
    """Cevabın sonuna karşı-soru eklensin mi?

    - İsınmada: hayır (sohbet serbest)
    - Çekirdek/derin + akademik: evet (flow state)
    - Sarkma: hayır (kapanışa hazırlanıyor)
    - Drift orta/agir: hayır (redirect daha önemli)
    """
    phase = get_phase(msg_count)
    if phase in ("isinma", "sarkma"):
        return False
    if drift_level in ("orta", "agir"):
        return False
    return phase in ("cekirdek", "derin")


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    # Senaryo testleri
    print("=== SENARYO 1: İlk mesaj, hiç sinyal yok ===")
    print(build_teacher_context(msg_count=1))
    print()

    print("=== SENARYO 2: 5. mesaj, %80 budget, hafif drift ===")
    print(build_teacher_context(
        msg_count=5,
        budget_status="warn",
        budget_advice="⚠ Öğrenci bugün çok konuştu — mevcut konuyu bitir",
        drift_level="hafif",
        drift_advice="ℹ Sohbet akademik konudan uzaklaşıyor",
        hedef_konu="türev kuralları",
    ))
    print()

    print("=== get_phase ===")
    for i in [1, 5, 10, 20]:
        print(f"  msg_count={i} → {get_phase(i)}")

    print("\n=== should_add_merak_sorusu ===")
    for msg, drift in [(1, "yok"), (5, "yok"), (5, "orta"), (12, "yok"), (20, "yok")]:
        print(f"  msg={msg}, drift={drift} → {should_add_merak_sorusu(msg, drift)}")
