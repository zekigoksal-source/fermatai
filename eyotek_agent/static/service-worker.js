/* FermatAI Service Worker (Oturum 25.40 — Neo PWA direktif)
 * Strateji:
 *   - Static asset (manifest, icon, CSS, JS CDN): stale-while-revalidate (önce cache, arka planda güncelle)
 *   - HTML/chat ana sayfa: network-first (her zaman fresh, çünkü mesaj akışı dinamik)
 *   - /render/{uuid}: stale-while-revalidate (öğrenci offline iken arşivlenmiş simülasyonu açar)
 *   - /chat/stream (SSE): sürekli network — cache YOK
 *   - POST/PUT/DELETE: sürekli network — cache YOK
 *   - /api/, /agent: network-first (data sorgusu fresh olmalı)
 *
 * Versiyon değiştir → tüm cache temizlenir.
 */
const VERSION = 'fermatai-v25.40';
const STATIC_CACHE = `${VERSION}-static`;
const RENDER_CACHE = `${VERSION}-render`;
const RUNTIME_CACHE = `${VERSION}-runtime`;

// Install: yapılacak prefetch yok, sadece skip waiting
self.addEventListener('install', (event) => {
  console.log('[SW]', VERSION, 'install');
  self.skipWaiting();
});

// Activate: eski cache'leri temizle
self.addEventListener('activate', (event) => {
  console.log('[SW]', VERSION, 'activate');
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(k => !k.startsWith(VERSION)).map(k => {
          console.log('[SW] eski cache silindi:', k);
          return caches.delete(k);
        })
      )
    ).then(() => self.clients.claim())
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

  // /chat ana sayfa — network-first (HTML her zaman fresh, fallback cache offline)
  if (url.pathname === '/chat' || url.pathname === '/chat/') {
    event.respondWith(networkFirst(request, RUNTIME_CACHE));
    return;
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

// Push notification (gelecek için hazır — backend henüz göndermiyor)
self.addEventListener('push', (event) => {
  let data = { title: 'FermatAI', body: 'Yeni bir mesaj var', icon: '/static/img/fermatai-192.png' };
  try {
    if (event.data) data = { ...data, ...event.data.json() };
  } catch (e) {}

  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: data.icon || '/static/img/fermatai-192.png',
      badge: '/static/img/fermatai-192.png',
      vibrate: [120, 60, 120],
      data: { url: data.url || '/chat' },
    })
  );
});

// Notification tıklanınca ana sayfaya götür (veya özel URL)
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) || '/chat';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(clients => {
      // Açık tab varsa ona git
      for (const client of clients) {
        if (client.url.includes('/chat') && 'focus' in client) {
          return client.focus();
        }
      }
      // Yoksa yeni tab aç
      if (self.clients.openWindow) return self.clients.openWindow(targetUrl);
    })
  );
});
