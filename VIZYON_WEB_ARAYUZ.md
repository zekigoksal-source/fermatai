# 🔮 Vizyon — Web Arayüz + Veli Dashboard

> **Durum:** NOT — ileride yapılabilir. Şu an mevcut gelişim sürecinden sapmıyoruz.
> **Tarih:** 15 Nisan 2026, Oturum 18 sonu
> **Kaynak:** Neo ile yapılan konuşma

## Özet

WhatsApp **yanında + aynı sisteme bağlı** bir web arayüzü. Öğrenci iki kanaldan birinde başlayıp diğerinde devam edebilir (aynı DB, aynı phone kimliği).

## Temel İstekler

1. **Sci-fi hissiyatlı tasarım** — dark theme, neon accent, mikro animasyonlar
2. **Streaming LLM** — "yazıyor..." canlı görünür, bekleme hissi yok
3. **Uzun diyaloglar** — YKS konularında saatlerce sohbet (açık kaynak LLM, 0 maliyet)
4. **WhatsApp ↔ Web senkron** — mesaj geçmişi ortak, kanallar arası geçiş
5. **Öğrenci dashboard** — sınav netleri grafik, zayıf konular, trend, hedef bölüm
6. **Veli dashboard** — çocuk(lar)ının özeti + AI sohbet (sınırlı)

## Teknik Mimari (hazır fikir)

### Backend — mevcut FastAPI'ye eklenti
- `/web/auth/request-otp` + `/web/auth/verify` (SMS OTP + JWT)
- `/web/chat/stream` (SSE streaming)
- `/web/history` (geçmiş konuşma)
- `/web/dashboard/data` (sınav/konu/grafik)
- **Tüm mevcut tool'lar yeniden kullanılır** (build_study_plan_context, get_ayt_analysis, vb.)

### Frontend
- **Next.js + TypeScript + Tailwind + shadcn/ui**
- **framer-motion** (mikro animasyonlar)
- **recharts** (radar chart ders netleri, line chart trend)

### LLM Stratejisi (karma)
- **Ollama merkez** (streaming, 0 maliyet, saatlerce sohbet)
- Kişisel veri gerektiğinde **Claude** (tool-calling + cache)
- Vision: **Claude Vision** (foto soru)

### Hosting
- Subdomain: `ogrenci.fermatvip.com` (veya benzeri)
- Ana Wix site korunur (pazarlama)
- DNS A kaydı + SSL (Let's Encrypt)

## Faz Planı (gerçekçi)

| Faz | İçerik | Süre |
|-----|--------|------|
| 1 — MVP Chat | Streaming chat + SMS auth + Ollama | 1 hafta |
| 2 — Dashboard | Grafikler + kişisel veri | 1-2 hafta |
| 3 — Sci-fi Tasarım | Dark theme, glow, animasyon | 3-5 gün |
| 4 — Veli Modülü | Veli login + çocuk özeti + sınırlı AI | 1 hafta |
| 5 — Gelişmiş | Sesli, foto, canlı öğretmen | ileride |

## Başlamadan Önceki Kararlar

1. Subdomain adı?
2. Hosting (VPS)?
3. Ana LLM (Ollama mı, daha büyük açık-kaynak mı, Claude cache mi)?
4. Veli modülü Faz 1'de mi Faz 4'te mi?

## Riskler

- Sunucu yükü: Ollama eş zamanlı kullanıcı → GPU kapasitesi planlanmalı
- Auth güvenliği: SMS OTP + JWT refresh
- CORS + SSL subdomain kurulumu
- **WhatsApp'ı bozmayacak** — web bağımsız kanal, eklenir, değiştirmez

## Mevcut Sistemle Uyum

✅ `fermat_core_agent.py` zaten kanal-bağımsız
✅ `agent_conversations` phone-bazlı → web aynı tabloyu kullanabilir
✅ Prompt caching uzun sohbetlerde maliyet düşük tutar
✅ Ollama zaten warm + streaming destekli
✅ Session Keeper Eyotek'i canlı tutar, web için de aynı

## ⚠️ Şu Anki Karar

**ŞİMDİLİK YAPMA.** Mevcut geliştirme + öğrenme sürecinde kal:
- Gözlem modu (canlı diyalog analizi)
- Bug sıcağı sıcağına müdahale
- WhatsApp kanalını mükemmelleştir

Web arayüzü vizyonu burada not. Gün gelince detayları buradan çıkarır, başlarız.
