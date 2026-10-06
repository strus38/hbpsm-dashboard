// Page installée sur l'écran d'accueil (GitHub Pages) : elle s'ouvre toujours sur la dernière version
// (le réseau d'abord), et sur la copie gardée ici quand il n'y a pas de connexion. Les données ne
// passent pas par ici : la page garde déjà sa dernière copie chiffrée.
const CACHE = "hbpsm-page-v1";
const SHELL = ["./", "manifest.webmanifest", "icons/icon-192.png", "icons/icon-512.png"];

self.addEventListener("install", ev => {
  ev.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).catch(() => {}).then(() => self.skipWaiting()));
});
self.addEventListener("activate", ev => {
  ev.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", ev => {
  const req = ev.request, url = new URL(req.url);
  if(req.method !== "GET" || url.origin !== location.origin) return;   // données, logos, polices : comme d'habitude
  if(req.mode === "navigate"){
    ev.respondWith(fetch(req).then(res => {
      if(res.ok){ const copy = res.clone(); caches.open(CACHE).then(c => c.put("./", copy)); }
      return res;
    }).catch(() => caches.match("./")));
    return;
  }
  // icônes et manifeste : la copie gardée ; jamais la page elle-même (la page vérifie sa propre version)
  if(SHELL.slice(1).some(p => url.pathname.endsWith("/" + p))) ev.respondWith(caches.match(req).then(hit => hit || fetch(req)));
});
