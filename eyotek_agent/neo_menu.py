"""
Neo Komut Menüsü (Oturum 25.29 — Hızlı Erişim)
================================================

Neo (admin) için kategorize hierarchical menü:
  neo            → ana menü (kategoriler)
  neo dev        → Self-Dev Pipeline alt menü
  neo eyotek     → Eyotek session yönetim
  neo sistem     → Sistem durum/restart/log
  neo kurum      → Kullanıcı yetki/blokla
  neo rapor      → Günlük/haftalık rapor
  neo data       → Veri sync (öğrenci/sınav)
  neo yardim     → Tam yardım metni

Eski komutlar (brief yaz, self dev durum vs.) HALA ÇALIŞIR.
Bu menü sadece "hatırlatıcı + hızlı erişim" işlevi görür.
"""
from __future__ import annotations
import re
from typing import Optional


# ─── ANA MENÜ ────────────────────────────────────────────────────────────────

def main_menu() -> str:
    """`neo` komutuna ana kategori menüsü."""
    return """*🎯 Neo Komut Merkezi*

Hangi kategori? Alt menüye girmek için kategori adı yaz:

*📂 Kategoriler:*

🛠️ `neo dev`     — Self-Dev Pipeline (brief, draft, PR)
🌐 `neo eyotek`   — Eyotek session yönetimi
⚙️ `neo sistem`   — Sistem durum, restart, log
👥 `neo kurum`    — Kullanıcı yetki, blokla, ACL
📊 `neo rapor`    — Günlük/haftalık rapor + atlas
🔄 `neo data`     — Veri sync (öğrenci/sınav/Eyotek)
📝 `neo guncelle` — KALDIGIM/blueprint güncelleme
❓ `neo yardim`   — Detaylı tüm komut listesi

_⚡ Hızlı Sıkça Kullanılanlar:_
  • `self dev durum`  — pipeline yeşil/kırmızı
  • `brief yaz`       — konuşmadan brief üret
  • `eyotek tamam`    — session yenile
  • `sistem`          — özet sistem raporu
  • `rapor`           — günlük kullanım

_💡 Tüm eski komutlar HÂLÂ çalışıyor — bu menü sadece hızlı erişim._"""


# ─── ALT MENÜLER ─────────────────────────────────────────────────────────────

def menu_dev() -> str:
    """`neo dev` — Self-Dev Pipeline alt menü."""
    return """*🛠️ Self-Dev Pipeline*
_(Evre 1 + 2.1 + 2.2 + 2.3 CANLI — 24 katmanlı koruma)_

*🟢 Durum & Switch*
  • `self dev durum`           — istatistik + token + push durumu
  • `self dev ac/kapat`        — master kill switch
  • `self dev push ac/kapat`   — GitHub push yetkisi

*📋 Brief (kod öneri taslağı)*
  • `brief yaz`                — son konuşmadan brief üret
  • `brief liste`              — geçmiş brief'ler
  • `brief #N göster`          — brief detay

*📝 Draft (sandbox unified diff)*
  • `brief #N draft yap`       — diff dosyası üret (_drafts/)
  • `draft liste`              — tüm draft'lar
  • `draft #N göster`          — diff içeriği oku
  • `draft #N iptal`           — draft sil

*🌿 Branch (lokal git)*
  • `brief #N branch`          — bot/draft branch + commit
  • `branch liste`             — bot/draft-* branch'ler
  • `branch durum`             — ahead/behind, uncommitted
  • `branch <name> sil`        — lokal branch sil

*🚀 Push + PR (GitHub)*
  • `branch <name> push`       — GitHub'a push (push açıksa)
  • `brief #N PR`              — TEK TIK: branch+commit+push+PR
  • `pr #N durum`              — PR sorgu
  • `pr #N kapat`              — PR iptal

*⚡ Hızlı Senaryo (Mehmet bug gibi):*
  1. Botla sorunu konuş (5dk)
  2. `brief yaz` → bot kod öneri çıkarır
  3. `brief #N PR` → bot push edip PR draft açar
  4. Telefondan PR'a tıkla → onayla → merge"""


def menu_eyotek() -> str:
    """`neo eyotek` — Eyotek session alt menü."""
    return """*🌐 Eyotek Session Yönetim*

*🔄 Session*
  • `eyotek tamam`             — session yenile (Chrome'dan cookie)
  • `eyotek durum`             — anlık session sağlık
  • `token`                    — Eyotek WP token yenileme

*🔍 Veri Çekme (admin only)*
  • Bot Eyotek'e direk gider:
    - "Apotemi sınav sonuçları" — anlık sınav nezleri
    - "Mahmut Taha rehberlik notları"
    - "Bugün etüt programı"
  • İçerden tool çağrısı: `sinav_sonuclari`, `ogrenci_drilldown`

*⚠️ Session Düşerse*
  Bot otomatik fark eder, sana WP'da bildirir:
    "Eyotek session bitti, 'eyotek tamam' yaz"
  Sen yazınca Chrome cookie yenilenir."""


def menu_sistem() -> str:
    """`neo sistem` — Sistem durum/restart alt menü."""
    return """*⚙️ Sistem Yönetimi*

*📊 Durum*
  • `sistem`                   — özet sistem raporu (uptime, pid, memory)
  • `sistem durum`             — detaylı durum
  • `son guncelleme`           — KALDIGIM son N oturum
  • `son güncellemen sana ne kattı` — bot'un son fix'lerini özetler

*🔧 Bakım (sadece terminal'den)*
  • `sudo systemctl restart fermatai-bridge.service`
  • `sudo journalctl -u fermatai-bridge -n 100`
  • `sudo systemctl status fermatai-*` (timer'lar dahil)

*🤖 Self-Awareness*
  • `not et: <not>`            — DB'ye admin notu kaydet
  • `hata not: <not>`          — bot'un kendi hatalarını işaretle
  • `diyalog not: <not>`       — konuşma kalitesi notu

*⏰ Otomatik Görevler (cron/systemd)*
  • `fermatai-atlas-nightly`   — 02:30 UTC anomali tarama
  • `fermatai-backup`          — 03:00 UTC PG dump + tar
  • `fermatai-eyotek-daily`    — 04:00 UTC otomatik login
  • `fermatai-dr-drill`        — her ay 1'i 04:30 UTC restore test"""


def menu_kurum() -> str:
    """`neo kurum` — Kullanıcı yetki + blokla alt menü."""
    return """*👥 Kurum Yönetim*

*🚫 Bloklama*
  • `blokla 905XXXXXXXXX`      — numara blokla (mesaj almaz)
  • `blok kaldir 905XX`        — blok kaldır
  • `blokli liste`             — blokli numaralar

*🎚️ Yetki Değişimi*
  • `yetki 905XX admin`        — admin yetkisi ver
  • `yetki 905XX mudur`        — müdür yetkisi
  • `yetki 905XX ogretmen`     — öğretmen
  • `yetki 905XX rehber`       — rehber öğretmen
  • `yetki 905XX yonetim`      — yönetim üyesi
  • `yetki 905XX guest`        — sıfırla

*🔒 Hassas Tool Yetki*
  • Finans tool'ları → SADECE Neo (905051256802)
  • Etüt yazma → admin/mudur/rehber
  • Öğrenci sınav verileri → admin/mudur/rehber + ogretmen (kendi sınıfı)

*👁️ Audit*
  • `kim ne yazdi son 24h`     — kullanıcı log
  • `flood durum`              — flood koruma istatistik
  • `hack denemeleri`          — kötü amaçlı pattern'ler"""


def menu_rapor() -> str:
    """`neo rapor` — Rapor + atlas alt menü."""
    return """*📊 Rapor + Atlas*

*📅 Günlük/Haftalık*
  • `rapor`                    — bugünkü kullanım özeti (token, msg, kişi)
  • `trend`                    — son 7 gün trend
  • `gunluk rapor`             — detaylı bugünkü
  • `haftalik ozet`            — kurum geneli haftalık

*🎓 Akademik*
  • `kac ogrenci`              — toplam öğrenci sayısı
  • `en basarili`              — top öğrenciler
  • `devamsiz top`             — yüksek devamsızlık
  • `sinif dagilimi`           — sınıf bazlı

*🔍 Atlas (Self-Observation)*
  • `atlas trend`              — sistem anomali raporu
  • `atlas son`                — son 24h gözlem
  • `atlas onerileri`          — bekleyen iyileştirme önerileri

*🧠 Self-Awareness*
  • Bot her gece 02:30'da kendini tarar (frustration, latency, pattern miss)
  • Kritik bulgu varsa Neo'ya WP'da bildirim atar
  • `atlas son` ile manuel bakabilirsin"""


def menu_data() -> str:
    """`neo data` — Veri sync alt menü."""
    return """*🔄 Veri Sync*

*📚 Öğrenci Verisi*
  • `son guncelleme`           — son sync ne zamandı
  • `sinav guncelle`           — Eyotek'ten yeni sınav nezleri (manuel)
  • `guncelle <isim>`          — tek öğrenci force update
  • `cache yenile`             — analytics cache reset

*⏰ Otomatik Sync (Cron)*
  • Her gece 03:00 → smart_sync (yeni sınav verileri)
  • Sabah 04:00 → eyotek-daily (otomatik login)
  • Hafta içi 08:01 → fermatai-daily-sync (öğrenci snapshot)

*📥 Excel Import*
  • `python import_etut_excel.py <dosya>` (terminal'den)
  • `python import_rehberlik_excel.py <dosya>`
  • `python import_exam_details.py <dosya>`

*🔍 Data Quality*
  • `query_analytics SELECT...`  — bot SQL ile DB sorgular
  • `eyotek_query "..."`         — Eyotek anlık veri"""


def menu_guncelle() -> str:
    """`neo guncelle` — Dökümantasyon update alt menü."""
    return """*📝 Dökümantasyon Güncelleme*

*🤖 Bot İçi*
  • `not et: <not>`            — DB'ye admin notu (admin_talimat tablosu)
  • `hata not: <not>`          — bot davranış sorunları
  • `diyalog not: <not>`       — konuşma kalitesi feedback

*📂 Dosya Tabanlı (yarın yapılacak Evre 2.4)*
  • `KALDIGIM guncelle`        — son oturum özeti append
  • `BLUEPRINT guncelle`       — mimari değişiklik notu
  • `memory ekle: <konu>`      — yeni memory dosyası

*🛡️ Önemli Not*
  Bu komutlar **sadece sen** kullanırsın (admin only).
  Bot kendi başına KALDIGIM/BLUEPRINT'e yazamaz (Evre 3 kapsamı, çok sonra)."""


def menu_yardim() -> str:
    """`neo yardim` — Tam yardım metni."""
    return """*❓ Tam Komut Listesi*

*Sıkça Kullanılan TOP 10:*
  1. `neo`                     — bu menü
  2. `self dev durum`          — self-dev pipeline yeşil mi
  3. `brief yaz`               — konuşmadan brief üret
  4. `brief #N PR`             — full pipeline tek tık
  5. `eyotek tamam`            — session yenile
  6. `sistem`                  — sistem özet
  7. `rapor`                   — günlük kullanım
  8. `atlas trend`             — anomali raporu
  9. `not et: <not>`           — admin notu kaydet
  10. `son güncellemen ne kattı` — bot fix özet

*Kategori Menüleri:*
  • `neo dev`        — Self-Dev tüm komutlar (15+ komut)
  • `neo eyotek`     — Eyotek session
  • `neo sistem`     — sistem yönetim
  • `neo kurum`      — yetki/blokla
  • `neo rapor`      — rapor + atlas
  • `neo data`       — veri sync
  • `neo guncelle`   — dökümantasyon

*Düzgün Çalışmıyorsa:*
  1. `self dev durum` ile pipeline sağlığı bak
  2. `sistem` ile bridge active mi
  3. `eyotek durum` ile session canli mi
  4. SSH ile journalctl: `sudo journalctl -u fermatai-bridge -n 50`

*🆘 Acil Durum:*
  Bot sapıtırsa:
    `self dev kapat` → tüm yazma işlemleri pasif
    `self dev push kapat` → push yetkisi pasif"""


# ─── ROUTER ──────────────────────────────────────────────────────────────────

# Anahtarsa: hem TR hem alfabetik, alias destek
_CATEGORIES = {
    "dev":      menu_dev,
    "selfdev":  menu_dev,
    "self":     menu_dev,
    "eyotek":   menu_eyotek,
    "session":  menu_eyotek,
    "sistem":   menu_sistem,
    "system":   menu_sistem,
    "kurum":    menu_kurum,
    "yetki":    menu_kurum,
    "user":     menu_kurum,
    "kullanici":menu_kurum,
    "rapor":    menu_rapor,
    "report":   menu_rapor,
    "atlas":    menu_rapor,
    "data":     menu_data,
    "veri":     menu_data,
    "sync":     menu_data,
    "guncelle": menu_guncelle,
    "update":   menu_guncelle,
    "doc":      menu_guncelle,
    "yardim":   menu_yardim,
    "yardım":   menu_yardim,
    "help":     menu_yardim,
    "?":        menu_yardim,
}


def route_neo_command(message: str) -> Optional[str]:
    """`neo` veya `neo <kategori>` mesajını çözümle, menü string döndür.

    Returns:
        str → menü cevabı
        None → eşleşmedi (fallback'e bırak)
    """
    msg = (message or "").strip().lower()
    # Sadece "neo" → ana menü
    if msg == "neo":
        return main_menu()
    # "neo <kategori>" formu
    m = re.match(r"^neo\s+(\w+)\s*$", msg)
    if m:
        kategori = m.group(1)
        fn = _CATEGORIES.get(kategori)
        if fn:
            return fn()
        # Kategori yok → ana menü + uyarı
        return f"_'{kategori}' kategorisi yok._\n\n" + main_menu()
    # "neo <kategori> ..." → şimdilik ana menüye yönlendir (gelecekte alt-alt komutlar)
    return None


# ─── CLI test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    test_msgs = [
        "neo",
        "neo dev",
        "neo eyotek",
        "neo sistem",
        "neo kurum",
        "neo rapor",
        "neo data",
        "neo yardim",
        "neo bilinmeyen",
    ]
    for m in test_msgs:
        print("=" * 70)
        print(f"Input: {m!r}")
        print("=" * 70)
        r = route_neo_command(m)
        print(r[:500] if r else "(None — fallback)")
        print()
