/* Service worker.
 *
 * Strategy per request type:
 *   navigation   network-first, falling back to the cached shell when offline
 *   /static/*    stale-while-revalidate, so an update lands on the next load
 *   /api/covers  cache-first — cover bytes never change, and they dominate the
 *                data a phone pulls when scrolling results
 *   /api/stream  bypassed entirely: large files and range requests should not
 *                pass through the cache
 *   other /api   network-only; stale download progress would be worse than none
 *
 * The cache name is derived from the app version, which the page passes in when
 * registering (`/sw.js?v=2.0.0`). A new release therefore registers a different
 * script URL, which installs a new worker whose activate step drops every cache
 * belonging to the previous version. Hardcoding it here instead would leave old
 * entries behind forever and serve stale CSS after an update.
 */

const CACHE_VERSION = new URL(self.location).searchParams.get('v') || 'dev';
const SHELL_CACHE = `slskweb-shell-${CACHE_VERSION}`;
const COVER_CACHE = `slskweb-covers-${CACHE_VERSION}`;
const MAX_COVERS = 400;

const SHELL_ASSETS = [
  '/',
  '/static/css/app.css',
  '/static/css/fonts.css',
  '/static/js/app.js',
  '/static/js/i18n.js',
  '/static/js/vendor/alpine.min.js',
  '/static/fonts/dm-sans.woff2',
  '/static/fonts/space-mono-400.woff2',
  '/static/fonts/space-mono-700.woff2',
  '/static/logo-256.png',
  '/static/icons/icon-192.png',
  '/manifest.webmanifest',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      // addAll is all-or-nothing; a single 404 would abort the install.
      .then((cache) => Promise.allSettled(SHELL_ASSETS.map((url) => cache.add(url))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key.startsWith('slskweb-') && key !== SHELL_CACHE && key !== COVER_CACHE)
            .map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  );
});

/** Keep the cover cache from growing without bound (roughly FIFO). */
async function trimCache(cacheName, maxEntries) {
  const cache = await caches.open(cacheName);
  const keys = await cache.keys();
  if (keys.length <= maxEntries) return;
  await Promise.all(keys.slice(0, keys.length - maxEntries).map((key) => cache.delete(key)));
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(SHELL_CACHE);
  // ignoreSearch so a precached "/static/js/app.js" still answers a request for
  // "/static/js/app.js?v=2.0.0" when offline.
  const cached = (await cache.match(request)) || (await cache.match(request, { ignoreSearch: true }));
  const network = fetch(request)
    .then((response) => {
      if (response && response.ok) cache.put(request, response.clone());
      return response;
    })
    .catch(() => null);
  return cached || network.then((response) => response || Response.error());
}

async function cacheFirstCover(request) {
  const cache = await caches.open(COVER_CACHE);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request).catch(() => null);
  if (response && response.ok) {
    cache.put(request, response.clone());
    trimCache(COVER_CACHE, MAX_COVERS);
  }
  return response || Response.error();
}

async function networkFirstShell(request) {
  try {
    const response = await fetch(request);
    if (response && response.ok) {
      const cache = await caches.open(SHELL_CACHE);
      cache.put('/', response.clone());
    }
    return response;
  } catch {
    const cached = await caches.match('/', { ignoreSearch: true });
    return cached || Response.error();
  }
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Never intercept audio: range requests and multi-MB bodies.
  if (url.pathname.startsWith('/api/stream/')) return;

  if (request.mode === 'navigate') {
    event.respondWith(networkFirstShell(request));
    return;
  }
  if (url.pathname.startsWith('/api/covers/')) {
    event.respondWith(cacheFirstCover(request));
    return;
  }
  if (url.pathname.startsWith('/api/')) return; // network-only
  if (url.pathname.startsWith('/static/') || url.pathname === '/manifest.webmanifest') {
    event.respondWith(staleWhileRevalidate(request));
  }
});
