// Такси ТАП! — service worker: тиркеме катары орнотуу жана интернет жок болсо жөнөкөй бет.
// API'лер жана карта кэштелбейт — абал ар дайым жаңы болушу керек.
const SHELL = "taxitap-v222";
const PAGES = ["/", "/driver", "/static/area.js?v=16", "/static/voice.js?v=8", "/static/night.js?v=2", "/static/dark.css?v=21", "/static/manifest.json", "/static/icon-192.png", "/static/logo.png", "/static/n_home.webp?v=24", "/static/n_trips.webp?v=24", "/static/n_go.webp?v=24", "/static/n_go_on.webp?v=1", "/static/n_help.webp?v=24", "/static/n_cab.webp?v=24", "/static/n_earn.webp?v=24", "/static/r_bag.webp?v=24", "/static/r_car.webp?v=24", "/static/cb_tl.webp?v=24", "/static/cb_tr.webp?v=24", "/static/qr.js", "/static/qrshare.js", "/static/c_car.webp?v=24",
  "/static/h_taxi.webp?v=24", "/static/h_box.webp?v=24", "/static/h_girl.webp?v=25", "/static/h_map.webp?v=25"];
self.addEventListener("install", e => e.waitUntil(caches.open(SHELL).then(c => c.addAll(PAGES)).then(() => self.skipWaiting())));
self.addEventListener("activate", e => e.waitUntil(
  caches.keys().then(ks => Promise.all(ks.filter(k => k !== SHELL && k !== "taxitap-voice").map(k => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin || u.pathname.startsWith("/api/")) return;
  if (u.pathname.startsWith("/voice/")) {                 // кыргызча үн: бир жолу жүктөлөт, андан кийин интернетсиз да ойнойт
    e.respondWith(caches.open("taxitap-voice").then(c => c.match(e.request).then(hit => hit || fetch(e.request).then(r => {
      if (r.ok) c.put(e.request, r.clone()); return r; }))));
    return;
  }
  // тармак биринчи, болбосо кэш
  e.respondWith(fetch(e.request).then(r => {
    if (r.ok && PAGES.includes(u.pathname)) { const c = r.clone(); caches.open(SHELL).then(x => x.put(e.request, c)); }
    return r;
  }).catch(() => caches.match(e.request).then(r => r || new Response(
    "<meta charset=utf-8><body style='font-family:sans-serif;padding:40px;text-align:center'><h2>Интернет жок</h2><p>Байланыш калыбына келгенде бетти жаңылаңыз.</p>",
    {headers: {"Content-Type": "text/html; charset=utf-8"}}))));
});
