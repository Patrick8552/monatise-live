const CACHE_NAME = "monatise-shell-20260818-universe-v1";
const SHELL_ASSETS = [
  "./",
  "./cg.html",
  "./dashboard/",
  "./game.html",
  "./memecoins.html",
  "./coinglass-dashboard.html?v=20260814-ui-depth-v1",
  "./styles.css?v=20260814-bugfix-v1",
  "./app.js?v=20260814-bugfix-v1",
  "./spotify.js?v=20260629-request-access-fix",
  "./game.js?v=20260629-crypto-trainer",
  "./assets/payout-clients.svg",
  "./coinglass-dashboard.css?v=20260814-ui-depth-v1",
  "./coinglass-dashboard.js?v=20260820-signal-core-v1",
  "./memecoins.css?v=20260715-memecoins",
  "./memecoins.js?v=20260814-bugfix-v1",
  "./manifest.webmanifest?v=20260727-brand-v2",
  "./favicon.ico?v=20260727-brand-v4",
  "./og.png?v=20260727-brand-v4",
  "./monatise-yinyang.svg?v=20260727-brand-v3",
  "./icon-180.png?v=20260727-brand-v2",
  "./icon-192.png?v=20260727-brand-v2",
  "./icon-512.png?v=20260727-brand-v2"
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.pathname.startsWith("/api/")) return;
  event.respondWith(
    fetch(request)
      .then((response) => {
        // Only cache successful responses -- otherwise a transient 404/500
        // (e.g. during a deploy race) gets cached and is then preferred
        // over the offline fallback on a later failed fetch. waitUntil
        // keeps the worker alive until the write actually completes.
        if (response.ok) {
          const copy = response.clone();
          event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.put(request, copy)));
        }
        return response;
      })
      .catch(() => caches.match(request).then((cached) => cached || caches.match("./index.html")))
  );
});
