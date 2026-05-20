/* FermatAI Service Worker (Oturum 25.40 — Neo PWA direktif)
 * Strateji:
 *   - Static asset (manifest, icon, CSS, JS CDN): stale-while-revalidate (önce cache, arka planda güncelle)
 *   - HTML/chat ana sayfa: STALE-WHILE-REVALIDATE (Neo bug fix — anında açılış)
 *   - /render/{uuid}: stale-while-revalidate (öğrenci offline iken arşivlenmiş simülasyonu açar)
 *   - /chat/stream (SSE): sürekli network — cache YOK
 *   - POST/PUT/DELETE: sürekli network — cache YOK
 *   - /api/, /agent: network-first (data sorgusu fresh olmalı)
 *
 * 25.40 (Neo): /chat artık cache-first → PWA açılışı 1sn beyaz ekran ortadan kalktı
 * Versiyon değiştir → tüm cache temizlenir.
 */
const VERSION = 'fermatai-v25.47-render-ux-reveal-contrast';
const STATIC_CACHE = `${VERSION}-static`;
const RENDER_CACHE = `${VERSION}-render`;
const RUNTIME_CACHE = `${VERSION}-runtime`;

// 25.41 (Neo bug 7 May konuşma analizi):
// Neo "yazarken mesajlarım kayboluyor" bildirdi. Brief #18:
// skipWaiting() + clients.claim() bot her güncellendiğinde sayfa reload tetikliyor
// → kullanıcının yazdığı mesaj kayboluyor.
// FIX: ikisi de KALDIRILDI. Yeni SW ancak tüm sekmeler kapanınca aktive olur,
// kullanıcı aktif yazarken reload önlenir. CSS/JS bug fix'leri kullanıcı manuel
// yeniden açana kadar gecikebilir — kabul edilebilir trade-off.
self.addEventListener('install', (event) => {
  console.log('[SW]', VERSION, 'install (skipWaiting AKTIF — 25.43 hamburger F5 fix)');
  // 25.43-CACHE-FIX (Neo 10 May): Hamburger F5 sonrasi calismiyor sorunu — eski SW
  // mevcut sekmede aktif kaliyordu, eski cached HTML/JS donuyordu. skipWaiting +
  // clients.claim AKTIF EDILDI ki yeni SW hemen aktive olsun. Trade-off: kullanici
  // yaziyorken cok nadir bir reload tetiklenebilir — hamburger calismazlığına gore
  // kabul edilebilir.
  self.skipWaiting();
});

// Activate: eski cache'leri temizle (clients.claim() KALDIRILDI)
self.addEventListener('activate', (event) => {
  console.log('[SW]', VERSION, 'activate (clients.claim AKTIF)');
  event.waitUntil(
    Promise.all([
      caches.keys().then(keys =>
        Promise.all(
          keys.filter(k => !k.startsWith(VERSION)).map(k => {
            console.log('[SW] eski cache silindi:', k);
            return caches.delete(k);
          })
        )
      ),
      // 25.43-CACHE-FIX: clients.claim() AKTIF — mevcut sekmeler de yeni SW'ye gecsin
      // Aksi takdirde Neo'nun sekmesi eski SW ile takılı kalıyor F5 sonrası
      self.clients.claim()
    ])
  );
});

// Fetch: strateji router
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Sadece GET cache et
  if (request.method !== 'GET') return;

  // SSE streaming endpoint — asla cache etme
  if (url.pathname.includes('/chat/stream')) {
    return; // varsayılan network davranışına bırak
  }

  // Auth/agent/api endpoints — network-first (data fresh)
  if (
    url.pathname.startsWith('/agent') ||
    url.pathname.startsWith('/api/') ||
    url.pathname.startsWith('/auth/') ||
    url.pathname.startsWith('/login') ||
    url.pathname.includes('webhook')
  ) {
    return; // network-only
  }

  // /render/{uuid} — öğrenci arşivlenmiş simülasyonu offline açabilsin
  if (url.pathname.startsWith('/render/') && !url.pathname.includes('archive')) {
    event.respondWith(staleWhileRevalidate(request, RENDER_CACHE));
    return;
  }

  // 25.46+ (Neo 17 May): /static/games/ ve /chess BYPASS — mini-oyunlar
  // surekli guncelleniyor, cache eskirse yeni Stockfish/chess.html serve edilmez.
  // Backend zaten no-cache header gonderiyor; SW araya GIRMESIN.
  if (
    url.pathname.startsWith('/static/games/') ||
    url.pathname === '/chess' ||
    url.pathname.startsWith('/chess?')
  ) {
    return;  // SW intercept yok — fresh fetch her zaman
  }

  // Static assets (manifest, icon, fonts)
  if (
    url.pathname.endsWith('.json') ||
    url.pathname.endsWith('.png') ||
    url.pathname.endsWith('.svg') ||
    url.pathname.endsWith('.ico') ||
    url.pathname.endsWith('.woff2') ||
    url.pathname.endsWith('.woff') ||
    url.pathname.includes('/static/')
  ) {
    event.respondWith(staleWhileRevalidate(request, STATIC_CACHE));
    return;
  }

  // CDN scripts (jsdelivr, unpkg, cdnjs) — long cache
  if (
    url.hostname.includes('jsdelivr.net') ||
    url.hostname.includes('unpkg.com') ||
    url.hostname.includes('cdnjs.cloudflare.com') ||
    url.hostname.includes('googleapis.com') ||
    url.hostname.includes('gstatic.com')
  ) {
    event.respondWith(staleWhileRevalidate(request, STATIC_CACHE));
    return;
  }

  // /chat ana sayfa — NETWORK-ONLY (25.43 Neo hamburger F5 fix 10 May)
  // ESKI: networkFirst (cache fallback offline) → eski cached HTML donuyordu F5'te
  // YENI: SW araya HIC girmesin, browser her seferinde direkt network'ten alir.
  // Backend zaten Cache-Control: no-cache, no-store header gonderiyor.
  // Offline destegi /chat icin kaybolur (kabul edilebilir — chat backend'siz
  // calismaz zaten).
  if (url.pathname === '/chat' || url.pathname === '/chat/') {
    return;  // SW intercept yok, native fetch
  }

  // Diğer same-origin GET — runtime cache
  if (url.origin === self.location.origin) {
    event.respondWith(staleWhileRevalidate(request, RUNTIME_CACHE));
    return;
  }
});

// Stale-while-revalidate: cache'den hemen ver, arka planda güncelle
async function staleWhileRevalidate(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  const networkPromise = fetch(request)
    .then(response => {
      if (response && response.status === 200) {
        cache.put(request, response.clone()).catch(() => {});
      }
      return response;
    })
    .catch(() => cached); // network hatası → cached versiyon

  return cached || networkPromise;
}

// Network-first: önce ağ, hata olursa cache'den
async function networkFirst(request, cacheName) {
  const cache = await caches.open(cacheName);
  try {
    const response = await fetch(request);
    if (response && response.status === 200) {
      cache.put(request, response.clone()).catch(() => {});
    }
    return response;
  } catch (err) {
    const cached = await cache.match(request);
    if (cached) {
      console.log('[SW] offline, cache döndü:', request.url);
      return cached;
    }
    throw err;
  }
}

// ═══════════════════════════════════════════════════════════════════════
// 25.40l (Neo direktif) — KURUMSAL PRO PUSH HANDLER
//
// Strateji: Öğrenciyi WhatsApp'tan PWA app'e ÇEKMEK.
// Push = nazik tetikleyici, mesaj atmak gibi taciz değil.
// Kurumsal kimlik: logo + başlık + ton — her bildirim PRO görünür.
//
// Backend payload schema (push_service.py _build_payload):
//   {title, body, icon, badge, click_url, tag, image, actions, vibrate,
//    requireInteraction, silent, timestamp, data}
// ═══════════════════════════════════════════════════════════════════════
self.addEventListener('push', (event) => {
  // Default — backend payload göndermezse fallback
  let data = {
    title: 'FermatAI',
    body: 'Yeni bir bildirimin var',
    icon: '/static/img/fermatai-192.png',
    badge: '/static/img/fermatai-192.png',
    click_url: '/chat',
    tag: 'fermatai_default',
    vibrate: [120, 60, 120],
    requireInteraction: false,
    silent: false,
  };

  try {
    if (event.data) {
      const incoming = event.data.json();
      data = Object.assign({}, data, incoming);
    }
  } catch (e) {
    console.warn('[SW] push payload parse fail:', e);
  }

  // Notification options — kurumsal pro
  const options = {
    body: data.body,
    icon: data.icon || '/static/img/fermatai-192.png',
    badge: data.badge || '/static/img/fermatai-192.png',
    tag: data.tag || 'fermatai_default',
    renotify: data.renotify === true,  // Aynı tag varsa normalde tekrar gösterme
    vibrate: data.vibrate || [120, 60, 120],
    requireInteraction: data.requireInteraction === true,
    silent: data.silent === true,
    timestamp: data.timestamp || Date.now(),
    data: {
      click_url: data.click_url || '/chat',
      tag: data.tag,
      ...(data.data || {}),
    },
  };

  // Opsiyonel: hero image (Android büyük görsel)
  if (data.image) options.image = data.image;
  // Opsiyonel: action buttons (Aç / Sonra)
  if (data.actions && Array.isArray(data.actions)) options.actions = data.actions;
  // Opsiyonel: dir/lang
  if (data.dir) options.dir = data.dir;
  options.lang = data.lang || 'tr';

  event.waitUntil(
    self.registration.showNotification(data.title || 'FermatAI', options)
  );
});

// Notification tıklanınca PWA aç + chat'e yönlendir
self.addEventListener('notificationclick', (event) => {
  // Action button tıklandıysa hangi action?
  const action = event.action;  // "open" | "later" | "" (gövde)
  event.notification.close();

  if (action === 'later') {
    // Kullanıcı "Sonra" dedi — sessizce kapat, log için backend'e bildirebiliriz
    return;
  }

  const data = event.notification.data || {};
  // Kurumsal: tam URL (PWA standalone bunu absolute olarak değerlendirir)
  let targetUrl = data.click_url || '/chat';
  // Eğer relative ise full URL'e çevir (PWA standalone için)
  if (targetUrl.startsWith('/')) {
    targetUrl = self.location.origin + targetUrl;
  }

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(clients => {
      // 1) Açık client var mı? Varsa fokusla + URL navigate
      for (const client of clients) {
        // chat URL'i veya origin'le başlıyorsa fokuslama önceliği
        if (client.url.startsWith(self.location.origin) && 'focus' in client) {
          // navigate gerekirse (deep link varsa)
          if ('navigate' in client && targetUrl !== client.url) {
            return client.navigate(targetUrl).then(() => client.focus()).catch(() => client.focus());
          }
          return client.focus();
        }
      }
      // 2) Açık tab yoksa yeni window aç (PWA standalone'da app olarak)
      if (self.clients.openWindow) {
        return self.clients.openWindow(targetUrl);
      }
    })
  );
});

// notification kapatıldıysa (kullanıcı dismiss) — opsiyonel telemetry
self.addEventListener('notificationclose', (event) => {
  const tag = event.notification.tag;
  console.log('[SW] notification closed (dismissed):', tag);
});

// pushsubscriptionchange — browser subscription rotated (re-subscribe gerek)
self.addEventListener('pushsubscriptionchange', (event) => {
  console.log('[SW] subscription change, re-subscribe gerek');
  // Ana sayfa açıldığında postMessage ile bildirilebilir, şimdilik sessiz
});
