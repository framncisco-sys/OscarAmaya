/* PBR — Service Worker: caché de estáticos, página sin conexión y refresco al volver online.
 * Versión de caché: subir el sufijo tras cambios importantes en estáticos precargados. */
const CACHE_STATIC = "pbr-static-v1";

const PRECACHE_URLS = [
  "/static/offline.html",
  "/static/theme.css",
  "/static/favicon.svg",
];

function isSameOrigin(url) {
  return url.origin === self.location.origin;
}

function isGetNavigation(request) {
  if (request.method !== "GET") return false;
  if (request.mode === "navigate") return true;
  if (request.destination === "document") return true;
  const accept = request.headers.get("accept") || "";
  return accept.includes("text/html");
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(CACHE_STATIC);
      for (const url of PRECACHE_URLS) {
        try {
          await cache.add(new Request(url, { cache: "reload" }));
        } catch (e) {
          console.warn("[PBR-SW] precache falló:", url, e);
        }
      }
      await self.skipWaiting();
    })()
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys.filter((k) => k !== CACHE_STATIC).map((k) => caches.delete(k))
      );
      await self.clients.claim();
    })()
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (!isSameOrigin(url)) return;

  if (isGetNavigation(request)) {
    event.respondWith(
      (async () => {
        try {
          const fresh = await fetch(request);
          return fresh;
        } catch (_) {
          const cached = await caches.match("/static/offline.html");
          if (cached) return cached;
          return new Response(
            "<!DOCTYPE html><html lang='es'><meta charset='utf-8'><title>Sin conexión</title><p>Sin conexión a Internet.</p>",
            {
              status: 503,
              headers: { "Content-Type": "text/html; charset=utf-8" },
            }
          );
        }
      })()
    );
    return;
  }

  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      (async () => {
        const cached = await caches.match(request);
        const networkFetch = fetch(request)
          .then((response) => {
            if (response && response.ok) {
              const copy = response.clone();
              caches.open(CACHE_STATIC).then((cache) => cache.put(request, copy));
            }
            return response;
          })
          .catch(() => null);
        if (cached) {
          networkFetch.catch(() => {});
          return cached;
        }
        const net = await networkFetch;
        if (net) return net;
        return new Response("", { status: 504, statusText: "Sin conexión" });
      })()
    );
  }
});

self.addEventListener("message", (event) => {
  if (event.data === "SKIP_WAITING") {
    self.skipWaiting();
  }
});
