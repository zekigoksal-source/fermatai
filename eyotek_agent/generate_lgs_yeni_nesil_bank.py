"""
LGS Yeni Nesil Soru Bank Generator (Oturum 25.40n — Neo direktif)
==================================================================

Vakası: Vedat hoca 2 May 18:24 → "yeni nesil 6. sınıf matematik" istedi,
bot 20 KLASİK 1-adımlı formül sorusu üretti (akademik kalite 2/10).

Çözüm: MEB Maarif 2024 müfredatına göre 6/7/8. sınıf için tam yeni nesil
örnek bank — RAG'a yüklenir, bot bir sonraki "yeni nesil" talebinde
bu örneklerden çekip adapte eder.

Stratejik konum:
- Şu an 6. sınıf öğrencimiz YOK ama seneye 7-8. sınıf KESİN olacak
- 6'yı da dahil et — eğitsel boşluk kalmasın
- Ortaokul içeriği MEB Maarif (2024) + LGS ÖSYM standartlarında

Maliyet: Claude Sonnet ile ~$3-5 (kalite > maliyet — Vedat tarzı bir daha olmasın)
Üretim: ~95 konu × 1 paket (3-5 örnek) = 95 RAG kaydı

Kullanım:
  cd eyotek_agent
  /opt/fermatai/.venv/bin/python -X utf8 generate_lgs_yeni_nesil_bank.py [--dry-run] [--ders matematik] [--sinif 6]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
load_dotenv(override=True)

from loguru import logger

# Anthropic Claude
try:
    from anthropic import Anthropic
    _ANTHROPIC_OK = True
except ImportError:
    _ANTHROPIC_OK = False


# ═══════════════════════════════════════════════════════════════════════════════
# MEB MAARIF MÜFREDATI 2024 — 6/7/8. SINIF KONU HARİTASI
# ═══════════════════════════════════════════════════════════════════════════════

CURRICULUM = {
    "6_sinif": {
        "Matematik": [
            "Kümeler ve Küme İşlemleri",
            "Doğal Sayılarda İşlemler (Asal Çarpanlar, EBOB, EKOK)",
            "Tam Sayılar (Toplama, Çıkarma, Çarpma, Bölme)",
            "Kesirlerle İşlemler (Toplama, Çıkarma, Çarpma, Bölme)",
            "Ondalık Gösterim ve Ondalık İşlemler",
            "Yüzdeler",
            "Oran ve Orantı",
            "Cebirsel İfadeler",
            "Açılar (Komşu, Doğrusal, Dik, Bütünler, Tümler)",
            "Çokgenler (Üçgen, Dörtgen, Düzgün Çokgenler — iç ve dış açılar)",
            "Çember ve Daire (Çevre, Alan)",
            "Geometrik Cisimler (Prizma, Küre — yüzey alanı, hacim)",
            "Veri Analizi (Tablo, Grafik, Aritmetik Ortalama)",
            "Olasılık (Olası Durumlar, Basit Olayların Olasılığı)",
        ],
        "Fen Bilimleri": [
            "Hücre ve Yapısı (Bitki/Hayvan Hücresi, Mikroskop)",
            "Vücudumuzdaki Sistemler (Sindirim, Dolaşım, Solunum, Boşaltım)",
            "Kuvvet ve Hareket (Sabit Süratli Hareket, Sürtünme)",
            "Madde ve Isı (Erime/Donma/Kaynama, Isı-Sıcaklık Farkı)",
            "Ses ve Özellikleri (Yayılma, Yansıma, Soğurulma)",
            "Işık ve Yansıma (Düzlem Ayna, Gölge Oluşumu)",
            "Elektriğin İletimi (Elektrik Devresi, İletken/Yalıtkan)",
            "Bitki ve Hayvanlarda Üreme, Büyüme ve Gelişme",
        ],
        "Türkçe": [
            "Sözcük Türleri (İsim, Sıfat, Zamir)",
            "Cümlede Anlam ve Anlatım Bozuklukları",
            "Paragrafta Yapı ve Anlam",
            "Yazım Kuralları ve Noktalama",
            "Metin Türleri (Bilgilendirici, Anlatımcı, Öyküleyici)",
        ],
        "Sosyal Bilgiler": [
            "Birey ve Toplum (Sosyal Roller, Hak ve Sorumluluklar)",
            "Kültür ve Miras (Tarih Öncesi Çağlar, İlk Türk Devletleri)",
            "İnsanlar, Yerler ve Çevreler (Türkiye'nin İklimi, Coğrafi Konumu)",
            "Etkin Vatandaşlık ve Yönetim (Demokratik Yaşam, T.B.M.M.)",
            "Üretim, Dağıtım ve Tüketim (Ekonomi, Türkiye'nin Geçim Kaynakları)",
        ],
        "İngilizce": [
            "Daily Routines and Habits",
            "Holidays and Travel",
            "Food and Healthy Eating",
            "Weather and Seasons",
        ],
    },
    "7_sinif": {
        "Matematik": [
            "Tam Sayılarla Çarpma ve Bölme İşlemleri",
            "Rasyonel Sayılar ve İşlemleri",
            "Cebirsel İfadeler ve Eşitlik (1. Dereceden Bir Bilinmeyenli Denklemler)",
            "Oran-Orantı (Doğru/Ters Orantı, Yüzde, Faiz)",
            "Doğrular ve Açılar (Yöndeş, İç/Dış Ters)",
            "Çokgenler (Kongrüans, Benzerlik, İç Açı, Dış Açı)",
            "Çember (Yay, Kiriş, Teğet, Çevre, Alan)",
            "Geometrik Cisimler (Dik Prizma, Dik Piramit, Koni — yüzey alanı/hacim)",
            "Dönüşüm Geometrisi (Yansıma, Öteleme)",
            "Veri Analizi (Aritmetik Ortalama, Ortanca, Tepe Değer)",
            "Basit Olayların Olasılığı",
        ],
        "Fen Bilimleri": [
            "Güneş Sistemi ve Ötesi (Gezegenler, Galaksiler)",
            "Hücre ve Bölünmeler (Mitoz, Mayoz)",
            "Kuvvet ve Enerji (İş, Güç, Kinetik/Potansiyel Enerji)",
            "Saf Madde ve Karışımlar (Element, Bileşik, Ayırma Yöntemleri)",
            "Işığın Madde ile Etkileşimi (Mercekler, Aynalar)",
            "Canlılarda Üreme, Büyüme ve Gelişme",
            "İnsan ve Çevre (Ekosistem, Madde Döngüsü)",
            "Elektrik Devreleri (Seri/Paralel, Direnç, Akım)",
        ],
        "Türkçe": [
            "Sözcük Türleri (Fiil, Zarf, Edat, Bağlaç, Ünlem)",
            "Cümlenin Ögeleri (Yüklem, Özne, Nesne, Tümleç)",
            "Anlatım Bozuklukları",
            "Metin İnceleme (Şiir, Hikaye, Anı, Deneme)",
            "Yazım ve Noktalama (Birleşik Sözcükler, Tırnak)",
        ],
        "Sosyal Bilgiler": [
            "İletişim ve İnsan İlişkileri (Medya, Sorumlu Vatandaşlık)",
            "Türk Tarihinde Yolculuk (Anadolu Selçuklu, Beylikler, Osmanlı)",
            "Türkiye'de Nüfus (Yerleşme, Göç)",
            "Türk-İslam Medeniyetinin Doğuşu",
            "Üretim, Dağıtım, Tüketim ve Türkiye'nin Ekonomik Gelişimi",
        ],
        "İngilizce": [
            "Appearances and Personality",
            "Biographies of Famous People",
            "Sports and Healthy Lifestyle",
            "Environmental Awareness",
        ],
    },
    "8_sinif_lgs": {
        "Matematik": [
            "Çarpanlar ve Katlar (Asal Çarpan, EBOB-EKOK Uygulamaları)",
            "Üslü İfadeler (Çarpma, Bölme, Tabanı/Üssü Eşit, 10'un Kuvvetleri)",
            "Köklü Sayılar (Kareli Sayılar, Köklü İfadelerde Toplama/Çıkarma)",
            "Veri Analizi (Sütun, Çizgi, Daire Grafiği — Karşılaştırma)",
            "Olasılık (Bağımlı/Bağımsız Olaylar, Bileşik Olaylar)",
            "Cebirsel İfadeler (Çarpma, Özdeşlikler — kare, iki kare farkı)",
            "Doğrusal Denklemler (Eğim, y=ax+b, Grafik)",
            "Eşitsizlikler (Birinci Dereceden Bir Bilinmeyenli)",
            "Üçgenler (Kenar Bağıntısı, Pisagor, Dik Üçgen Özellikleri)",
            "Dönüşüm Geometrisi (Yansıma, Öteleme, Dönme)",
            "Geometrik Cisimler (Dik Prizma, Dik Piramit, Dik Dairesel Silindir — Yüzey Alanı/Hacim)",
        ],
        "Fen Bilimleri": [
            "Mevsimler ve İklim (Eksenel Eğiklik, İklim-Hava Olayları Farkı)",
            "DNA ve Genetik Kod (Mendel Yasaları, Mutasyon, Modifikasyon, Adaptasyon)",
            "Basınç (Sıvı/Gaz/Katı Basıncı — Günlük Hayat Uygulamaları)",
            "Madde ve Endüstri (Periyodik Sistem, Asit-Baz, Tepkimeler)",
            "Basit Makineler (Sabit/Hareketli Makara, Kaldıraç, Eğik Düzlem)",
            "Enerji Dönüşümleri ve Çevre Bilimi",
            "Elektrik Yükleri ve Elektrik Enerjisi (Akım, Gerilim, Direnç, Joule)",
            "Canlılar ve Enerji İlişkileri (Fotosentez, Solunum)",
        ],
        "Türkçe": [
            "Fiilimsi (İsim-Fiil, Sıfat-Fiil, Zarf-Fiil)",
            "Cümlenin Ögeleri ve Cümle Türleri",
            "Anlatım Bozuklukları",
            "Sözcük Anlamı ve Söz Sanatları",
            "Metin Türleri ve İnceleme (Roman, Hikaye, Şiir)",
        ],
        "T.C. İnkılap Tarihi": [
            "Bir Kahraman Doğuyor (Mustafa Kemal'in Hayatı, Eğitimi, Askerlik)",
            "Milli Uyanış (Mondros, İşgaller, Yararlı/Zararlı Cemiyetler, Mustafa Kemal'in Samsun'a Çıkışı)",
            "Ya İstiklal Ya Ölüm (Kongreler, Misak-ı Milli, Kurtuluş Savaşı Cepheleri)",
            "Çağdaş Türkiye Yolunda Adımlar (Saltanat ve Hilafetin Kaldırılması, İnkılaplar)",
            "Demokratikleşme Çabaları ve Dış Politika (Atatürk Dönemi)",
            "Atatürk İlkeleri (Cumhuriyetçilik, Milliyetçilik, Halkçılık, Devletçilik, Laiklik, İnkılapçılık)",
        ],
        "İngilizce": [
            "Friendship and Personal Qualities",
            "Teen Life and School Life",
            "In the Kitchen and Recipes",
            "Communication and Social Media",
            "Adventure and Tourism",
        ],
    },
    # ─── 25.40n Neo direktif: 9-12 LISE TYT/AYT (SAY+EA odakli, SOZ atlandi) ───
    # YKS = TYT (tum lise) + AYT (sayisal/eA dersleri).
    # Ozel kapsam: Matematik (TYT+AYT) + Fizik+Kimya+Biyoloji (AYT SAY) + TDE+Tarih+Cografya (AYT EA)
    # SOZ ogrencimiz YOK — felsefe/cografya2/din kultur YOK
    "9_sinif_tyt": {  # 9. sınıf konuları → TYT + AYT temel
        "Matematik (TYT temel)": [
            "Mantık (Önerme, Bileşik Önermeler, Doğruluk Tablosu)",
            "Kümeler (İşlemler, Venn Şemaları, Doğal/Tam/Rasyonel Sayılar)",
            "Denklem ve Eşitsizlikler (Birinci Dereceden, Mutlak Değer)",
            "Üçgenler (Açılar, Kenar Bağıntıları, Eşlik ve Benzerlik)",
            "Veri Analizi ve Olasılık (Merkezi Eğilim, Yayılım Ölçüleri)",
            "Fonksiyonlar (Tanım, Görüntü, Bire-bir, Örten)",
        ],
        "Fizik (TYT temel)": [
            "Fizik Bilimine Giriş (Büyüklükler, Birim Sistemleri, Hata Hesabı)",
            "Madde ve Özellikleri (Yoğunluk, Genleşme, Hal Değişimi)",
            "Hareket ve Kuvvet (Konum, Hız, İvme, Newton Yasaları)",
            "Enerji (İş, Güç, Mekanik Enerji, Korunum)",
            "Isı ve Sıcaklık (Hal Değişimi, Genleşme, Kalorimetre)",
            "Elektrostatik (Yükler, Coulomb Yasası, Elektrik Alan)",
        ],
        "Kimya (TYT temel)": [
            "Kimya Bilimi (Atom Modelleri, Periyodik Sistem)",
            "Atom ve Periyodik Sistem (Elektron Dizilimi, Periyodik Özellikler)",
            "Kimyasal Türler Arası Etkileşimler (İyonik, Kovalent, Metalik Bağlar)",
            "Maddenin Halleri (Katı/Sıvı/Gaz Özellikleri, Hal Değişimi)",
            "Doğa ve Kimya (Su, Çözünürlük, Asit-Baz)",
        ],
        "Biyoloji (TYT temel)": [
            "Yaşam Bilimi Biyoloji (Canlıların Ortak Özellikleri)",
            "Hücre ve Canlı Organizasyonu (Prokaryot/Ökaryot, Organeller)",
            "Canlılar Dünyası (Sınıflandırma, 6 Alem)",
        ],
    },
    "10_sinif_tyt": {
        "Matematik (TYT/AYT temel)": [
            "Sayma ve Olasılık (Permütasyon, Kombinasyon, Olasılık)",
            "Fonksiyonlar (Bileşke, Ters Fonksiyon, Grafik)",
            "Polinomlar (Çarpanlara Ayırma, Özdeşlikler, Bölme)",
            "İkinci Dereceden Denklemler (Diskriminant, Köklerin Çarpımı/Toplamı, Vieta)",
            "Üçgenler (Açıortay, Kenarortay, Yükseklik, Sinüs/Kosinüs Teoremleri)",
            "Dörtgenler ve Çokgenler (Paralelkenar, Dikdörtgen, Yamuk — alan, çevre)",
            "Çember ve Daire (Yay, Kiriş, Teğet, Çevre Açı, Merkez Açı)",
            "Veri Analizi (Korelasyon, Regresyon Giriş)",
        ],
        "Fizik (TYT temel)": [
            "Elektrik ve Manyetizma (Akım, Gerilim, Direnç, Ohm Yasası, Manyetik Alan)",
            "Basınç ve Kaldırma Kuvveti (Katı/Sıvı/Gaz Basıncı, Arşimet)",
            "Dalgalar (Yay, Su, Ses Dalgaları, Periyodik Hareket)",
            "Optik (Yansıma, Kırılma, Mercekler, Ayna)",
        ],
        "Kimya (TYT temel)": [
            "Kimyanın Temel Kanunları (Kütlenin Korunumu, Sabit Oranlar)",
            "Mol Kavramı ve Hesaplamaları (Avogadro, Molarite)",
            "Kimyasal Tepkimeler (Denkleştirme, Sentez, Analiz, Yer Değiştirme)",
            "Karışımlar (Çözeltiler, Derişim Hesaplamaları)",
        ],
        "Biyoloji (TYT temel)": [
            "Hücre Bölünmeleri (Mitoz, Mayoz — karşılaştırma, kromozom davranışı)",
            "Kalıtım (Mendel Yasaları, Genetik Çapraz, Kan Grupları, Cinsiyet)",
            "Ekosistem Ekolojisi (Beslenme Zinciri, Madde Döngüleri, Popülasyon)",
        ],
    },
    "11_sinif_ayt": {  # 11. sınıf konuları → AYT SAY ve AYT EA için
        "Matematik (AYT)": [
            "Trigonometri (Birim Çember, Trigonometrik Fonksiyonlar, Kimlikler)",
            "Karmaşık Sayılar (Modül, Argüman, Kutupsal Form, De Moivre)",
            "Logaritma (Logaritma Özellikleri, Logaritmik Fonksiyon, Üstel-Log)",
            "Diziler (Aritmetik/Geometrik Dizi, Toplam, Limit)",
            "Limit ve Süreklilik (Tanımsızlık, Sonsuz Limit, Süreklilik)",
            "Türev (Tanım, Kurallar, Zincir, Yüksek Mertebe, Uygulama)",
            "Analitik Geometri (Doğru Denklemi, Açı, Uzaklık, Çember)",
        ],
        "Fizik (AYT SAY)": [
            "Vektörler (Toplama/Çıkarma, Bileşke, İz Düşüm, Skalar/Vektörel Çarpım)",
            "Bağıl Hareket (Görelilik, Bileşke Hız)",
            "Newton Yasaları Uygulamaları (Sürtünme, Eğik Düzlem, Asansör)",
            "Atışlar (Yatay/Eğik/Düşey Atış, Mermi Hareketi)",
            "Tork ve Denge (Kuvvet Çifti, Statik Denge)",
            "İtme-Momentum (Korunum, Çarpışmalar — Esnek/Esnek Olmayan)",
            "Düzgün Çembersel Hareket (Merkez Çekim Kuvveti, Dönme)",
            "Elektrik Akımı (Direnç, Joule, Kirchhoff Yasaları)",
            "Manyetizma (Manyetik Alan, Lorentz Kuvveti, İndüksiyon)",
        ],
        "Kimya (AYT SAY)": [
            "Modern Atom Teorisi (Bohr, Kuantum Sayıları, Orbital, Pauli)",
            "Gazlar (İdeal Gaz, Boyle, Charles, Difüzyon)",
            "Sıvı Çözeltiler ve Çözünürlük (Doygun, Süpersature, Çözünürlük Etkenleri)",
            "Kimyasal Tepkimelerde Enerji (Endotermik, Egzotermik, Entalpi)",
            "Tepkime Hızı ve Denge (Hız Sabiti, Le Chatelier)",
            "Asit-Baz Dengesi (pH, pOH, Tampon Çözeltiler, Titrasyon)",
            "Çözünürlük Dengesi (Kçç, Ortak İyon Etkisi)",
            "Elektrokimya (Redoks, Pil, Elektroliz)",
        ],
        "Biyoloji (AYT SAY)": [
            "Sinir Sistemi (Nöron, Sinaps, Refleks, MSS-ÇSS)",
            "Endokrin Sistem (Hipofiz, Tiroid, Pankreas, Hormonlar)",
            "Duyu Organları (Göz, Kulak, Deri, Tat, Koku)",
            "Destek ve Hareket Sistemi (Kemik, Eklem, Kas)",
            "Sindirim Sistemi (Mekanik/Kimyasal Sindirim, Enzimler)",
            "Dolaşım Sistemi (Kalp, Damarlar, Kan, Lenf)",
            "Solunum Sistemi (Akciğer, Gaz Alışverişi)",
            "Boşaltım Sistemi (Böbrek, Nefron, Idrar Oluşumu)",
            "İnsanda Üreme (Erkek/Dişi Üreme Sistemi, Hormonal Kontrol)",
            "Komünite ve Popülasyon Ekolojisi (Türler Arası İlişkiler)",
        ],
        "Türk Dili ve Edebiyatı (AYT EA)": [
            "Edebi Akımlar (Klasisizm, Romantizm, Realizm, Natüralizm)",
            "Cumhuriyet Dönemi Türk Şiiri (Beş Hececiler, Garip, İkinci Yeni)",
            "Cumhuriyet Dönemi Türk Romanı (Köy, Bireyselci, Toplumsal Roman)",
            "Cumhuriyet Dönemi Hikaye ve Tiyatro",
        ],
        "Tarih (AYT EA)": [
            "İlk Türk-İslam Devletleri (Karahanlılar, Gazneliler, Selçuklular)",
            "Osmanlı Devleti Kuruluş ve Yükselme (1299-1600)",
            "Osmanlı Devleti Duraklama, Gerileme, Dağılma (1600-1922)",
            "20. Yüzyıl Başlarında Dünya (1. Dünya Savaşı, Sömürgecilik)",
        ],
        "Coğrafya (AYT EA)": [
            "Doğal Sistemler (İç ve Dış Kuvvetler, Yer Şekilleri)",
            "Ekonomik Faaliyetler (Tarım, Sanayi, Hizmet — Türkiye ve Dünya)",
            "Türkiye'nin Coğrafi Bölgeleri ve Ekonomik Özellikleri",
        ],
    },
    "12_sinif_ayt": {  # 12. sınıf — son tekrar + ileri konular
        "Matematik (AYT)": [
            "İntegral (Belirsiz İntegral, Belirli İntegral, Alan Hesabı)",
            "İntegral Uygulamaları (Hacim, Yay Uzunluğu, Ortalama Değer)",
            "Türev Uygulamaları (Maksimum-Minimum, Değişim Hızı, Optimizasyon)",
            "Limit ve Süreklilik İleri (L'Hospital, Belirsizlik Şekilleri)",
            "Analitik Geometri (Çember, Elips, Hiperbol, Parabol — koni kesitleri)",
            "Olasılık ve İstatistik İleri (Koşullu Olasılık, Bayes, Dağılımlar)",
        ],
        "Fizik (AYT SAY)": [
            "Elektromanyetik İndüksiyon (Faraday, Lenz, Transformatör)",
            "Alternatif Akım (RMS, Empedans, Rezonans Devresi)",
            "Modern Fizik Giriş (Fotoelektrik, Compton, De Broglie)",
            "Atom Fiziği (Bohr Atom Modeli, Spektrum, Geçiş)",
            "Çekirdek Fiziği (Radyoaktivite, Yarı Ömür, Füzyon/Fisyon)",
            "Dalga ve Parçacık (Çift Yarık Deneyi, Belirsizlik İlkesi)",
        ],
        "Kimya (AYT SAY)": [
            "Organik Kimyaya Giriş (Hibritleşme, Organik Bileşik Adlandırma)",
            "Hidrokarbonlar (Alkan, Alken, Alkin, Aromatik)",
            "Fonksiyonel Gruplar (Alkol, Aldehit, Keton, Asit, Ester, Amin)",
            "Karbohidrat-Protein-Yağ (Biyomoleküller)",
            "Polimerler (Sentetik ve Doğal Polimerler)",
        ],
        "Biyoloji (AYT SAY)": [
            "Canlılarda Enerji Dönüşümleri (Fotosentez, Solunum İleri)",
            "Genetik Mühendisliği ve Biyoteknoloji (DNA Klonlama, GDO, CRISPR)",
            "Bitki Biyolojisi (Yapı, Doku, Üreme — Kapalı/Açık Tohumlu)",
            "Komünite Ekolojisi (Süksesyon, Biyom, Madde Döngüleri)",
        ],
        "Türk Dili ve Edebiyatı (AYT EA)": [
            "Türk Edebiyatı Dönemleri Toplam (İslamiyet Öncesi → Tanzimat → Servet-i Fünun → Cumhuriyet)",
            "Roman ve Hikaye Tahlili (Karakter, Tema, Anlatıcı)",
            "Şiir Tahlili (Söz Sanatları, Ölçü, Yapı)",
        ],
        "Tarih (AYT EA)": [
            "Türk İnkılap Tarihi ve Atatürkçülük (Cumhuriyet'in Kuruluşu, İlkeler)",
            "Soğuk Savaş ve Sonrası Dünya (Bloklar, Avrupa Birliği, Türkiye Dış Politika)",
        ],
        "Coğrafya (AYT EA)": [
            "Çevre ve Toplum (Çevre Sorunları, Sürdürülebilirlik)",
            "Türkiye ve Dünyadan Bölgesel Çalışmalar",
        ],
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# CLAUDE SONNET PROMPT — KALİTE GARANTİ
# ═══════════════════════════════════════════════════════════════════════════════

GENERATION_PROMPT = """Sen MEB Maarif 2024 müfredatı uzmanı bir akademik içerik üreticisisin. \
Konuya göre 4 adet **YENİ NESİL** örnek soru üreteceksin.

Sınıf: {sinif}
Ders: {ders}
Konu: {konu}

═══ YENI NESİL SORU 7 ZORUNLU KRİTERİ ═══
1. **Bağlamlı:** Gerçek hayat senaryosu (Ahmet ailesiyle..., bir spor sahası..., bir tarif...)
2. **Çok adımlı:** 2-4 alt soru (a, b, c, d) veya birden fazla işlem
3. **Görsel ipucu:** Şekil/tablo/grafik referansı (metin olarak tanımla)
4. **Anlamlı/akıl yürütme:** En az bir alt soru "neden", "açıklayın", "doğru mu?" sentezi
5. **Disiplinler arası:** Mat+Fen, Mat+Coğrafya gibi köprü kur (mümkünse)
6. **Veri yorumu:** En az 1 soruda tablo/grafik veriyor olarak çık
7. **Açık uçlu sentez:** En az 1 soru tek doğru cevap dışında "yorum" ister

═══ ASLA ═══
✗ "X sayısının asal çarpanları" (1 adım, klasik)
✗ "Beşgenin iç açıları toplamı" (formül uygulama)
✗ Tek cümle, bağlamsız soru
✗ "Hesaplayın" tek başına emir → "düşününüz, açıklayınız" sentez

═══ ÇIKTI FORMATI (JSON) ═══
{{
  "ders": "{ders}",
  "konu": "{konu}",
  "sinif": "{sinif}",
  "kazanim": "MEB Maarif 2024 kazanım metni (2-3 cümle)",
  "ornekler": [
    {{
      "baslik": "Soru başlığı (örn: 'BAHCE PIKNIGINDE ORAN-ORANTI')",
      "soru_metni": "Tam soru metni — bağlam (2-4 cümle) + verilen bilgi + a/b/c alt sorular",
      "cevap_anahtari": "a) ... b) ... c) ... (her alt soru için adım adım çözüm)",
      "neden_yeni_nesil": "Bu sorunun yeni nesil olma sebebi (bağlam + sentez + ...)"
    }}
  ],
  "ogretmen_notlari": "Bu konuyu işlerken öğretmenin dikkat etmesi gerekenler (3-5 cümle)",
  "yaygin_hatalar": "Öğrencilerin yaptığı tipik hatalar (3-4 madde)"
}}

KRITIK: Sadece geçerli JSON döndür, kod bloğu yok, markdown yok.
3 örnek soru üret, hepsi 7 kriteri karşılasın. Türkçe yaz, akademik dil kullan.
Soru senaryoları çocuk/ortaokul yaşına UYGUN olsun (çok kompleks değil)."""


# ═══════════════════════════════════════════════════════════════════════════════
# ÜRETIM
# ═══════════════════════════════════════════════════════════════════════════════

async def generate_one_topic(client, sinif: str, ders: str, konu: str) -> Optional[dict]:
    """Tek bir konu için yeni nesil örnek paket üret."""
    prompt = GENERATION_PROMPT.format(
        sinif=sinif.replace("_sinif", ". Sınıf").replace("_lgs", " (LGS)"),
        ders=ders,
        konu=konu,
    )

    try:
        # 25.40n (Neo direktif): Cerebras gpt-oss-120b benchmark — 3sn vs Claude 100sn
        # Kalite EŞDEĞER (park/mimarlık/biyoloji disiplinler arası, açık uçlu sentez).
        # Maliyet: ~%2.5 Claude'un. Tercih: Cerebras (env: GENERATOR_PROVIDER=cerebras|claude)
        provider = os.getenv("GENERATOR_PROVIDER", "cerebras").lower()

        if provider == "cerebras":
            from cerebras_handler import CerebrasClient
            cclient = CerebrasClient()
            r = await cclient.complete_async(
                messages=[{"role": "user", "content": prompt}],
                system="Sen MEB Maarif uzmanı bir akademik içerik üreticisisin. Sadece geçerli JSON döndür.",
                model="gpt-oss-120b",
                max_tokens=6000,
                temperature=0.5,
            )
            text = (r.get("text") or "").strip()
        else:
            # Claude Sonnet streaming fallback
            _model = os.getenv("FERMAT_MODEL", "claude-sonnet-4-6")
            def _do_stream():
                chunks = []
                with client.messages.stream(
                    model=_model,
                    max_tokens=6500,
                    temperature=0.5,
                    messages=[{"role": "user", "content": prompt}],
                ) as stream:
                    for text_chunk in stream.text_stream:
                        chunks.append(text_chunk)
                return "".join(chunks)
            text = (await asyncio.to_thread(_do_stream)).strip()

        # Markdown JSON kod bloğu varsa temizle
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(l for l in lines if not l.startswith("```")).strip()
            if text.startswith("json"):
                text = text[4:].strip()

        parsed = json.loads(text)
        return parsed
    except json.JSONDecodeError as e:
        logger.warning(f"  [GEN] JSON parse fail: {e} (text head: {text[:150]})")
        return None
    except Exception as e:
        logger.warning(f"  [GEN] Hata: {e}")
        return None


def _build_rag_content(parsed: dict, sinif: str, ders: str, konu: str) -> str:
    """parsed JSON'i RAG'a yazmak icin tek string halinde formatla."""
    ornekler_text = ""
    for i, o in enumerate(parsed.get("ornekler", []), 1):
        ornekler_text += f"\n\n## Örnek {i}: {o.get('baslik', '')}\n"
        ornekler_text += f"\n{o.get('soru_metni', '')}\n"
        ornekler_text += f"\n**Cevap Anahtarı:**\n{o.get('cevap_anahtari', '')}\n"
        ornekler_text += f"\n**Neden Yeni Nesil:** {o.get('neden_yeni_nesil', '')}\n"

    return f"""# {sinif} — {ders} — {konu}

## MEB Maarif 2024 Kazanım
{parsed.get('kazanim', '')}

## Yeni Nesil Örnek Sorular (4 adet)
{ornekler_text}

## Öğretmen Notları
{parsed.get('ogretmen_notlari', '')}

## Yaygın Hatalar (öğrenciler en sık burada takılır)
{parsed.get('yaygin_hatalar', '')}
"""


async def insert_to_rag(parsed: dict, sinif: str, ders: str, konu: str) -> bool:
    """Üretilen paketi rag_content'e ekle (embedding ile)."""
    from db_pool import get_pool

    sinav_turu_map = {
        "6_sinif": "LGS_HAZIRLIK_6",
        "7_sinif": "LGS_HAZIRLIK_7",
        "8_sinif_lgs": "LGS",
        # 25.40n Neo direktif: Lise (SAY+EA odakli, SOZ atlandi)
        "9_sinif_tyt": "TYT",   # 9. sinif TYT temel konular
        "10_sinif_tyt": "TYT",  # 10. sinif TYT/AYT temel
        "11_sinif_ayt": "AYT",  # 11. sinif AYT
        "12_sinif_ayt": "AYT",  # 12. sinif AYT son tekrar
    }
    sinav_turu = sinav_turu_map.get(sinif, "LGS")

    icerik = _build_rag_content(parsed, sinif, ders, konu)
    baslik = f"{sinif.replace('_sinif', '. Sınıf').replace('_lgs', ' (LGS)')} — {ders} — {konu} (Yeni Nesil Örnek Paket)"

    # Embedding üret (rag_engine.embed_text sync — to_thread ile wrap)
    try:
        from rag_engine import embed_text
        emb = await asyncio.to_thread(embed_text, icerik[:3000])
        if not emb or len(emb) < 100:
            logger.warning(f"  [RAG] embedding fail (None or empty)")
            return False
    except Exception as e:
        logger.warning(f"  [RAG] embedding hata: {e}")
        return False

    # Anahtar kelimeler
    keywords = [
        sinif.replace("_sinif", ". sınıf").replace("_lgs", " LGS"),
        ders.lower(),
        konu.lower()[:50],
        "yeni nesil",
        "Maarif 2024",
        "örnek soru",
    ]

    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                """
                INSERT INTO rag_content
                  (sinav_turu, ders, konu, alt_konu, icerik_turu, baslik, icerik,
                   kaynak, zorluk, soru_sayisi, anahtar_kelimeler, embedding, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, NOW(), NOW())
                """,
                sinav_turu, ders, konu,
                None,  # alt_konu
                "yeni_nesil_ornek_paket",
                baslik, icerik,
                "MEB Maarif 2024 — Claude Sonnet üretim",
                "orta",
                len(parsed.get("ornekler", [])),
                keywords,
                str(emb),  # pgvector formatı: '[0.1, 0.2, ...]'
            )
            return True
        except Exception as e:
            logger.warning(f"  [RAG] INSERT hata: {e}")
            return False


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Üretim yap ama DB'ye yazma")
    parser.add_argument("--sinif", choices=["6_sinif", "7_sinif", "8_sinif_lgs", "all"],
                       default="all", help="Hangi sınıf (default: all)")
    parser.add_argument("--ders", default=None, help="Tek ders (örn: Matematik)")
    parser.add_argument("--max-konu", type=int, default=None, help="Konu sınırı (test için)")
    args = parser.parse_args()

    if not _ANTHROPIC_OK:
        print("[!] anthropic SDK kurulu degil.")
        sys.exit(1)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("[!] ANTHROPIC_API_KEY .env'de yok.")
        sys.exit(1)

    client = Anthropic(api_key=api_key, max_retries=3, timeout=90.0)

    # Hedef konu listesi
    targets = []
    classes = list(CURRICULUM.keys()) if args.sinif == "all" else [args.sinif]
    for sinif_key in classes:
        for ders_name, konular in CURRICULUM[sinif_key].items():
            if args.ders and args.ders.lower() not in ders_name.lower():
                continue
            for konu in konular:
                targets.append((sinif_key, ders_name, konu))

    if args.max_konu:
        targets = targets[:args.max_konu]

    print(f"[*] Toplam hedef konu: {len(targets)}")
    print(f"[*] Tahmini maliyet: ~${len(targets) * 0.04:.2f} (Claude Sonnet, ~4K token/konu)")
    print(f"[*] Dry-run: {args.dry_run}\n")

    success = 0
    failed = 0
    skipped_existing = 0

    # Mevcut RAG'da bu konu/sinif var mı kontrol — duplicate atla
    if not args.dry_run:
        from db_pool import db_fetch
        existing = await db_fetch(
            """SELECT sinav_turu, ders, konu FROM rag_content
               WHERE icerik_turu='yeni_nesil_ornek_paket'"""
        )
        existing_set = {(r['sinav_turu'], r['ders'], r['konu']) for r in existing}
    else:
        existing_set = set()

    sinav_turu_map = {
        "6_sinif": "LGS_HAZIRLIK_6",
        "7_sinif": "LGS_HAZIRLIK_7",
        "8_sinif_lgs": "LGS",
        # 25.40n Neo direktif: Lise (SAY+EA odakli, SOZ atlandi)
        "9_sinif_tyt": "TYT",   # 9. sinif TYT temel konular
        "10_sinif_tyt": "TYT",  # 10. sinif TYT/AYT temel
        "11_sinif_ayt": "AYT",  # 11. sinif AYT
        "12_sinif_ayt": "AYT",  # 12. sinif AYT son tekrar
    }

    # Duplicate filtre
    todo = []
    for sinif, ders, konu in targets:
        st = sinav_turu_map.get(sinif, "LGS")
        if (st, ders, konu) in existing_set:
            skipped_existing += 1
            continue
        todo.append((sinif, ders, konu))
    print(f"[*] Skip (zaten var): {skipped_existing}, Yeni üretilecek: {len(todo)}\n")

    # ── PARALLEL üretim — Cerebras 3sn cevap → 10 konu paralel mantikli
    PARALLEL = int(os.getenv("GENERATOR_PARALLEL", "10"))

    async def process_one(idx: int, sinif: str, ders: str, konu: str) -> tuple[bool, str]:
        """Tek konu üret + insert. Returns (success, log_line)."""
        try:
            parsed = await generate_one_topic(client, sinif, ders, konu)
            if not parsed:
                return False, f"  [{idx}] FAIL gen | {sinif} | {ders} | {konu[:40]}"
            if args.dry_run:
                return True, f"  [{idx}] OK dry-run, {len(parsed.get('ornekler', []))} ornek | {sinif} | {ders} | {konu[:40]}"
            ok = await insert_to_rag(parsed, sinif, ders, konu)
            if ok:
                return True, f"  [{idx}] OK insert + embedding | {sinif} | {ders} | {konu[:40]}"
            return False, f"  [{idx}] FAIL insert | {sinif} | {ders} | {konu[:40]}"
        except Exception as e:
            return False, f"  [{idx}] EXCEPTION {e} | {sinif} | {ders} | {konu[:40]}"

    # Batch'lerde işle (her batch içi paralel)
    for batch_start in range(0, len(todo), PARALLEL):
        batch = todo[batch_start:batch_start + PARALLEL]
        tasks = [process_one(batch_start + i + 1, s, d, k) for i, (s, d, k) in enumerate(batch)]
        results = await asyncio.gather(*tasks)
        for ok, line in results:
            print(line, flush=True)
            if ok:
                success += 1
            else:
                failed += 1

    print(f"\n[+] Bitti: {success} basarili, {failed} fail, {skipped_existing} skip")
    if not args.dry_run and success > 0:
        print(f"[+] RAG'a {success} yeni paket eklendi (sinav_turu: LGS_HAZIRLIK_6/7/LGS)")


if __name__ == "__main__":
    asyncio.run(main())
