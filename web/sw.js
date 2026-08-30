/* MemoryBridge app-shell service worker. Scope is /app/ only. */
const CACHE = "memorybridge-app-v2";
const OFFLINE_FALLBACK = "/app/landing.html";
const PRECACHE = [
  "/app/landing.html",
  "/app/onboarding.html",
  "/app/dashboard.html",
  "/app/records.html",
  "/app/pwa.js",
  "/app/local_store.js",
  "/app/manifest.webmanifest",
  "/app/icons/icon-192.png",
  "/app/icons/icon-512.png",
];

function isApiPath(pathname) {
  return pathname === "/v1" || pathname.startsWith("/v1/");
}

function isAppGet(request, url) {
  return request.method === "GET"
    && url.origin === self.location.origin
    && url.pathname.startsWith("/app/")
    && url.pathname !== "/app/sw.js"
    && !isApiPath(url.pathname);
}

function cacheOk(request, response) {
  if (response && response.ok) {
    const copy = response.clone();
    caches.open(CACHE).then((cache) => cache.put(request, copy));
  }
  return response;
}

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (isApiPath(url.pathname)) return;
  if (!isAppGet(event.request, url)) return;

  const accept = event.request.headers.get("accept") || "";
  const isDocument = event.request.mode === "navigate" || accept.includes("text/html");

  if (isDocument) {
    event.respondWith(
      fetch(event.request).then((response) => cacheOk(event.request, response)).catch(() =>
        caches.match(event.request).then((hit) => hit || caches.match(OFFLINE_FALLBACK))
      )
    );
    return;
  }

  event.respondWith(
    caches.match(event.request).then((hit) => {
      if (hit) {
        fetch(event.request).then((response) => cacheOk(event.request, response)).catch(() => undefined);
        return hit;
      }
      return fetch(event.request).then((response) => cacheOk(event.request, response));
    })
  );
});
