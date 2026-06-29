const CACHE_NAME = "monatise-shell-20260629-request-access-fix";
const SHELL_ASSETS = [
  "./",
  "./index.html",
  "./cg.html",
  "./dashboard/",
  "./game.html",
  "./coinglass-dashboard.html?v=20260617-trader-mode",
  "./styles.css?v=20260629-request-access-fix",
  "./app.js?v=20260629-request-access-fix",
  "./spotify.js?v=20260629-request-access-fix",
  "./game.js?v=20260629-request-access-fix",
  "./assets/payout-clients.svg",
  "./coinglass-dashboard.css?v=20260617-trader-mode",
  "./coinglass-dashboard.js?v=20260617-trader-mode",
  "./manifest.webmanifest?v=20260616-dashboard-install",
  "./icon-lotus.svg"
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
