// Service worker mínimo, escrito a mano (sin workbox/build-time generation) para que
// la PWA sea instalable. Network-first para TODO (shell y /api): esta es una
// herramienta de trading en vivo, nunca debe servir código o datos viejos mientras
// haya conexión — el caché es solo el fallback para cuando estás offline.
//
// v2: v1 usaba cache-first para el shell con un nombre de caché fijo, así que una vez
// instalada la PWA quedaba pegada al bundle JS del momento de instalación para
// siempre (activate() nunca lo invalidaba porque el nombre nunca cambiaba entre
// builds) — cambios de código posteriores (ej. "Refrescar" en Mis Órdenes) nunca
// llegaban al teléfono sin desinstalar la app. Subir CACHE_VERSION en cada cambio de
// este archivo fuerza la limpieza del caché viejo en el próximo activate().
const CACHE_VERSION = "v2";
const SHELL_CACHE = `eve-screener-shell-${CACHE_VERSION}`;
const API_CACHE = `eve-screener-api-${CACHE_VERSION}`;

self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k !== SHELL_CACHE && k !== API_CACHE)
          .map((k) => caches.delete(k)),
      ),
    ),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") {
    return; // no cacheable (Cache API solo acepta GET) — directo a la red, sin fallback offline
  }

  const url = new URL(event.request.url);
  const cacheName = url.pathname.startsWith("/api/") ? API_CACHE : SHELL_CACHE;

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const clone = response.clone();
        caches.open(cacheName).then((cache) => cache.put(event.request, clone));
        return response;
      })
      .catch(() => caches.match(event.request)),
  );
});
