const CACHE = "tribli-share-v2";
const PRECACHE = [
  "/", "/share", "/share/setup", "/share/shortcut",
  "/manifest.webmanifest", "/static/share.css",
  "/static/icons/icon-192.png", "/static/icons/icon-512.png"
];

self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE).then(cache => cache.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (event.request.method === "POST" && url.pathname === "/share") {
    event.respondWith(
      fetch(event.request).catch(() =>
        caches.match("/share").then(r => r || new Response("Offline — open TRIBLI and paste the post.", {
          status: 503,
          headers: { "Content-Type": "text/plain; charset=utf-8" }
        }))
      )
    );
    return;
  }
  if (event.request.method !== "GET") return;
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request))
  );
});
