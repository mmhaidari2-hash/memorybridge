/* MemoryBridge app-shell service worker. Scope is /app/ only. */
const CACHE = "memorybridge-app-v1";
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
  if (url.pathname.startsWith("/v1/") || url.pathname === "/v1") return;
  if (url.origin !== self.location.origin || !url.pathname.startsWith("/app/")) return;
  if (event.request.method !== "GET") return;
  event.respondWith(
    fetch(event.request).then((response) => {
      if (response.ok) {
        const copy = response.clone();
        caches.open(CACHE).then((cache) => cache.put(event.request, copy));
      }
      return response;
    }).catch(() => caches.match(event.request))
  );
});
