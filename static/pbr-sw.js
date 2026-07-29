/* PBR — Service Worker: caché de estáticos + páginas visitadas para modo sin conexión.
 * Versión de caché: subir el sufijo tras cambios importantes. */
const CACHE_STATIC = "pbr-static-v3";
const CACHE_PAGES = "pbr-pages-v3";

const PRECACHE_URLS = [
  "/static/offline.html",
  "/static/theme.css",
  "/static/favicon.svg",
  "/static/js/pbr-viewport.js",
  "/static/js/pbr-offline.js",
  "/static/js/pbr-loader.js",
  "/static/js/pbr-header.js",
  "/static/js/pbr-sidebar.js",
];

/** No cachear HTML con tokens CSRF / sesión (provoca 403 al enviar formularios). */
function isAuthSensitivePath(pathname) {
  const p = pathname.replace(/\/+$/, "") || "/";
  if (p === "/login" || p === "/logout") return true;
  if (p.startsWith("/accounts/")) return true;
  if (p.includes("sensitive") || p.includes("reauth")) return true;
  return false;
}

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
      const keep = new Set([CACHE_STATIC, CACHE_PAGES]);
      const keys = await caches.keys();
      await Promise.all(keys.filter((k) => !keep.has(k)).map((k) => caches.delete(k)));
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
        const noCachePage = isAuthSensitivePath(url.pathname);
        try {
          const fresh = await fetch(request, noCachePage ? { cache: "no-store" } : undefined);
          if (fresh && fresh.ok && !noCachePage) {
            const copy = fresh.clone();
            const pages = await caches.open(CACHE_PAGES);
            await pages.put(request, copy);
          }
          return fresh;
        } catch (_) {
          if (noCachePage) {
            return new Response(
              "<!DOCTYPE html><html lang='es'><meta charset='utf-8'><title>Sin conexión</title>" +
                "<body style='font-family:system-ui;padding:2rem'><h1>Sin conexión</h1>" +
                "<p>No se puede iniciar sesión sin Internet. Vuelva a intentarlo cuando tenga red.</p></body>",
              {
                status: 503,
                headers: { "Content-Type": "text/html; charset=utf-8" },
              }
            );
          }
          const cachedPage =
            (await caches.match(request)) ||
            (await caches.match(request, { ignoreSearch: true }));
          if (cachedPage) return cachedPage;
          const offline = await caches.match("/static/offline.html");
          if (offline) return offline;
          return new Response(
            "<!DOCTYPE html><html lang='es'><meta charset='utf-8'><title>Sin conexión</title>" +
              "<body style='font-family:system-ui;padding:2rem'><h1>Sin conexión a Internet</h1>" +
              "<p>Puede seguir trabajando cuando recupere páginas ya visitadas. Al volver la red se sincronizarán los cambios.</p></body>",
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
  if (event.data === "SYNC_NOW") {
    self.clients.matchAll({ type: "window" }).then((clients) => {
      clients.forEach((c) => c.postMessage({ type: "PBR_SYNC_NOW" }));
    });
  }
});
