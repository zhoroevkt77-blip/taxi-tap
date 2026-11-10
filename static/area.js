// Leaflet'тин демейки префиксинде желек бар — жөнөкөй «Leaflet» шилтемеси менен алмаштырылат.
// OpenStreetMap'тин атрибуциясы калат (лицензия талап кылат).
if (window.L && L.Control && L.Control.Attribution) {
  L.Control.Attribution.prototype.options.prefix = false;   // «Leaflet» жазуусу жок, «© OpenStreetMap» калат (лицензия талабы)
}
// Такси ТАП! — иштөө аймагы картада: чектен сырткары күңүрт, карта ошол жерден чыкпайт.
function areaRings(gj) {
  if (!gj) return [];
  if (gj.type === "Polygon") return [gj.coordinates[0]];
  if (gj.type === "MultiPolygon") return gj.coordinates.map(p => p[0]);
  return [];
}
function areaPip(lat, lon, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if ((yi > lat) !== (yj > lat) && lon < (xj - xi) * (lat - yi) / ((yj - yi) || 1e-12) + xi) inside = !inside;
  }
  return inside;
}
function inArea(lat, lon) {
  const a = window.AREA;
  return !a || !a.on || areaRings(a.geojson).some(r => areaPip(lat, lon, r));
}
async function setupArea(map, opts = {}) {
  try {
    const a = await (await fetch("/api/area")).json();
    window.AREA = a;
    if (!a.on) return a;
    const [s, w, n, e] = a.bbox, pad = 0.06;
    map.setMaxBounds(L.latLngBounds([s - pad, w - pad], [n + pad, e + pad]));
    map.options.maxBoundsViscosity = 0.9;
    map.setMinZoom(opts.minZoom || 10);
    const holes = areaRings(a.geojson).map(r => r.map(([lon, lat]) => [lat, lon]));
    L.polygon([[[89, -179], [89, 179], [-89, 179], [-89, -179]], ...holes],
      {stroke: false, fillColor: "#152741", fillOpacity: 0.3, interactive: false}).addTo(map);
    holes.forEach(h => L.polyline(h.concat([h[0]]), {color: "#17365C", weight: 2, dashArray: "6 6", interactive: false}).addTo(map));
    if (opts.center !== false) map.setView(a.center, opts.zoom || 14);
    return a;
  } catch (err) { return null; }
}

// ---------- тиркеме катары орнотуу (PWA) ----------
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
window.INSTALL = null;
window.addEventListener("beforeinstallprompt", e => { e.preventDefault(); window.INSTALL = e; });
function installHTML() {
  if (window.matchMedia("(display-mode: standalone)").matches) return "";
  const ios = /iphone|ipad/i.test(navigator.userAgent);
  if (window.INSTALL) return `<button class="btn ghost" id="instBtn">📲 Телефонго тиркеме катары орнотуу</button>`;
  if (ios) return `<p class="muted" style="margin-top:10px">📲 Орнотуу: Safari'де «Бөлүшүү» → «На экран „Домой“».</p>`;
  return "";
}
function bindInstall() {
  const b = document.getElementById("instBtn");
  if (b) b.onclick = async () => { window.INSTALL.prompt(); await window.INSTALL.userChoice; window.INSTALL = null; b.remove(); };
}

// ---------- Төмөнкү барак: өйдө-ылдый сүрүү (картаны көрүү үчүн) ----------
// Тутканы (сызыкча) ылдый сүрсөңүз — барак жыйылып, карта көрүнөт; өйдө сүрсөңүз же бассаңыз — ачылат.
window.SHEET = (function () {
  let sheet = null, grab = null, cur = 0, collapsed = false, start = null, base = 0, moved = false;
  const PEEK = 110;                                       // жыйылганда көрүнүп турган бөлүгү (px)
  const max = () => sheet ? Math.max(0, sheet.offsetHeight - PEEK) : 0;
  function set(y, anim) {
    cur = Math.max(0, Math.min(max(), y));
    sheet.style.transition = anim ? "transform .25s ease" : "none";
    sheet.style.transform = cur ? `translateY(${cur}px)` : "";
    window.dispatchEvent(new Event("sheetmove"));
  }
  function snap(c) { collapsed = c; set(c ? max() : 0, true); grab && grab.classList.toggle("down", c); }
  function down(y) { start = y; base = cur; moved = false; }
  function move(y, e) {
    if (start === null) return;
    const dy = y - start;
    if (Math.abs(dy) > 5) moved = true;
    if (moved) { e && e.cancelable && e.preventDefault(); set(base + dy, false); }
  }
  function up() {
    if (start === null) return;
    start = null;
    if (!moved) return snap(!collapsed);                 // жөн эле басса — которуштурат
    snap(cur > max() / 2);
  }
  function init(el) {
    sheet = el; grab = el.querySelector(".grab"); if (!grab) return;
    grab.addEventListener("touchstart", e => down(e.touches[0].clientY), {passive:true});
    grab.addEventListener("touchmove", e => move(e.touches[0].clientY, e), {passive:false});
    grab.addEventListener("touchend", up);
    grab.addEventListener("mousedown", e => { down(e.clientY); e.preventDefault(); });
    window.addEventListener("mousemove", e => move(e.clientY, e));
    window.addEventListener("mouseup", up);
  }
  return {
    init,
    refresh() { if (sheet && collapsed) set(max(), false); },       // мазмун өзгөргөндө
    expand() { if (sheet && collapsed) snap(false); },
    visible() { return sheet ? window.innerHeight - sheet.getBoundingClientRect().top : 0; },
  };
})();
document.addEventListener("DOMContentLoaded", () => { const s = document.querySelector(".sheet"); if (s && s.querySelector(".grab")) SHEET.init(s); });
