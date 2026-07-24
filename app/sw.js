const CACHE_NAME = "monatise-shell-20260724-contact-v2";
const SHELL_ASSETS = [
  "./",
  "./cg.html",
  "./dashboard/",
  "./game.html",
  "./memecoins.html",
  "./coinglass-dashboard.html?v=20260724-crypto-framework-v2",
  "./styles.css?v=20260724-contact-v2",
  "./app.js?v=20260724-contact-v2",
  "./spotify.js?v=20260629-request-access-fix",
  "./game.js?v=20260629-crypto-trainer",
  "./assets/payout-clients.svg",
  "./coinglass-dashboard.css?v=20260717-market-primary",
  "./coinglass-dashboard.js?v=20260724-crypto-framework-v2",
  "./memecoins.css?v=20260715-memecoins",
  "./memecoins.js?v=20260715-memecoins",
  "./manifest.webmanifest?v=20260701-yinyang-png",
  "./icon.svg?v=20260701-yinyang-png",
  "./icon-180.png?v=20260701-yinyang-png",
  "./icon-192.png?v=20260701-yinyang-png",
  "./icon-512.png?v=20260701-yinyang-png"
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
