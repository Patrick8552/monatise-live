const CACHE_NAME = "monatise-shell-20260616-liq-map4";
const SHELL_ASSETS = [
  "./",
  "./index.html",
  "./cg.html",
  "./dashboard/",
  "./coinglass-dashboard.html?v=20260616-liq-map4",
  "./styles.css?v=20260615-signal-levels",
  "./app.js?v=20260615-signal-levels",
  "./coinglass-dashboard.css?v=20260616-liq-map4",
  "./coinglass-dashboard.js?v=20260616-liq-map4",
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
