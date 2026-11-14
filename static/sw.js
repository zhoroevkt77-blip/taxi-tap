// Такси ТАП! — service worker: тиркеме катары орнотуу жана интернет жок болсо жөнөкөй бет.
// API'лер жана карта кэштелбейт — абал ар дайым жаңы болушу керек.
const SHELL = "taxitap-v93";
const PAGES = ["/", "/driver", "/static/area.js", "/static/manifest.json", "/static/icon-192.png", "/static/logo.png", "/static/n_home.webp?v=8", "/static/n_trips.webp?v=8", "/static/n_go.webp?v=8", "/static/n_help.webp?v=8", "/static/n_cab.webp?v=8", "/static/n_earn.webp?v=8", "/static/r_bag.webp?v=8", "/static/r_car.webp?v=8", "/static/cb_tl.webp?v=8", "/static/cb_tr.webp?v=8", "/static/qr.js", "/static/qrshare.js", "/static/c_car.webp?v=8",
  "/static/h_taxi.webp?v=8", "/static/h_box.webp?v=8", "/static/h_girl.webp?v=8", "/static/h_map.webp?v=8"];
self.addEventListener("install", e => e.waitUntil(caches.open(SHELL).then(c => c.addAll(PAGES)).then(() => self.skipWaiting())));
self.addEventListener("activate", e => e.waitUntil(
  caches.keys().then(ks => Promise.all(ks.filter(k => k !== SHELL).map(k => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin || u.pathname.startsWith("/api/")) return;
  // тармак биринчи, болбосо кэш
  e.respondWith(fetch(e.request).then(r => {
    if (r.ok && PAGES.includes(u.pathname)) { const c = r.clone(); caches.open(SHELL).then(x => x.put(e.request, c)); }
    return r;
  }).catch(() => caches.match(e.request).then(r => r || new Response(
    "<meta charset=utf-8><body style='font-family:sans-serif;padding:40px;text-align:center'><h2>Интернет жок</h2><p>Байланыш калыбына келгенде бетти жаңылаңыз.</p>",
    {headers: {"Content-Type": "text/html; charset=utf-8"}}))));
});
