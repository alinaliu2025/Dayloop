// dayloop service worker — caches the app shell so it opens instantly and
// works offline. NEVER caches /api/ — that data must always be live.
// (Service workers only run over https or on localhost; over a plain-http
//  LAN address the app still works, it just won't cache offline.)
const CACHE = "dayloop-v2";
const SHELL = [
  "/", "/index.html", "/manifest.webmanifest",
  "/icon-192.png", "/icon-512.png", "/icon-180.png",
];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys()
      .then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith("/api/")) return;   // always hit the network
  // app shell: cache-first, fall back to network
  e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
});
