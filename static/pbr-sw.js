/* PBR — Service Worker: caché de estáticos + páginas visitadas para modo sin conexión.
 * Versión de caché: subir el sufijo tras cambios importantes. */
const CACHE_STATIC = "pbr-static-v18";
const CACHE_PAGES = "pbr-pages-v18";

const PRECACHE_URLS = [
  "/static/offline.html",
  "/static/theme.css?v=18",
  "/static/favicon.svg",
  "/static/icons/pwa-192.png",
  "/static/js/pbr-viewport.js?v=18",
  "/static/js/pbr-offline.js?v=18",
  "/static/js/pbr-loader.js?v=18",
  "/static/js/pbr-header.js?v=18",
  "/static/js/pbr-sidebar.js?v=18",
  "/static/js/pbr-pwa-install.js?v=18",
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

function isCriticalStatic(pathname) {
  return (
    pathname === "/static/theme.css" ||
    pathname.startsWith("/static/js/pbr-") ||
    pathname === "/static/pbr-sw.js"
  );
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
        // Layout crítico: red primero (evita CSS/JS móvil viejo en el teléfono).
        if (isCriticalStatic(url.pathname)) {
          try {
            const fresh = await fetch(request, { cache: "no-cache" });
            if (fresh && fresh.ok) {
              const copy = fresh.clone();
              caches.open(CACHE_STATIC).then((cache) => cache.put(request, copy));
            }
            return fresh;
          } catch (_) {
            const cached = await caches.match(request);
            if (cached) return cached;
            return new Response("", { status: 504, statusText: "Sin conexión" });
          }
        }

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
