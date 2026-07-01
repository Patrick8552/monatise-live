const CACHE_NAME = "monatise-shell-20260701-context-signal-50";
const SHELL_ASSETS = [
  "./",
  "./cg.html",
  "./dashboard/",
  "./game.html",
  "./coinglass-dashboard.html?v=20260701-market-icon",
  "./styles.css?v=20260629-crypto-trainer",
  "./app.js?v=20260701-auth-button-state",
  "./spotify.js?v=20260629-request-access-fix",
  "./game.js?v=20260629-crypto-trainer",
  "./assets/payout-clients.svg",
  "./coinglass-dashboard.css?v=20260701-market-icon",
  "./coinglass-dashboard.js?v=20260701-context-signal-50",
  "./manifest.webmanifest?v=20260701-yin-yang-icon",
  "./icon.svg?v=20260701-yin-yang-icon"
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
        const copy = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
        return response;
      })
      .catch(() => caches.match(request).then((cached) => cached || caches.match("./index.html")))
  );
});
