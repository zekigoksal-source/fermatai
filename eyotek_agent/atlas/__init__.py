"""
ATLAS — FermatAI'nin İç Zihni (Vizyon Faz 1)

Modüller:
  observer.py  — DB scan + anomali tespit
  advisor.py   — observation -> suggestion (kural-tabanlı v0.1, Claude entegrasyonu Faz 2)
  chat.py      — terminal CLI dialog
  schema.sql   — atlas_suggestions, atlas_observations tabloları

Kullanım:
  python -m atlas observe    # tek seferlik tarama, observation kaydet
  python -m atlas advise     # son observation'lardan suggestion üret
  python -m atlas chat       # terminal interaktif diyalog
  python -m atlas list       # bekleyen suggestion listesi

WhatsApp:
  Neo /atlas yazınca whatsapp_bridge.py admin handler chat moduna girer.

═══════════════════════════════════════════════════════════════════════════
🔒 KESİN GÜVENLİK KURALI — ATLAS HİÇBİR ZAMAN DIŞ MESAJ ATMAZ
═══════════════════════════════════════════════════════════════════════════
ATLAS yalnızca:
  ✅ DB'ye yazar (atlas_observations, atlas_suggestions)
  ✅ Neo (admin) ile WhatsApp veya terminal üzerinden konuşur
  ✅ Konsol/log çıktısı verir

ATLAS ASLA:
  ❌ Öğrenciye, öğretmene, müdüre, veliye, başka herhangi birine
     proaktif WhatsApp/SMS/email mesajı GÖNDERMEZ.
  ❌ Telafi mesajı, alarm, bildirim, hatırlatma — Neo'dan EXPLICIT onay
     komutu olmadan ASLA tetiklenmez.
  ❌ Bir suggestion onaylansa bile, dış mesaj içeriyorsa Neo ayrıca
     "evet bu mesajı gönder" demelidir.

Bu kural Neo'nun (Zeki Göksal) 16 Nisan 2026 02:00'da koyduğu sıkı
operasyon kuralıdır — bilhassa gece saatleri için yüksek hassasiyet vardır.
Kuralı esnetmek YASAK; "bir kerelik test" bile YASAK.
═══════════════════════════════════════════════════════════════════════════
"""
__version__ = "0.1.0"
NEO_PHONE = "905051256802"
ATLAS_CAN_SEND_EXTERNAL = False  # SADELEŞTIRME: ASLA True olmasin bu kod sürümünde

