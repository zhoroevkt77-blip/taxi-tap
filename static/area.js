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
window.addEventListener("beforeinstallprompt", e => { e.preventDefault(); window.INSTALL = e; instBar(); });
window.addEventListener("appinstalled", () => { window.INSTALL = null; const x = document.getElementById("instBar"); if (x) x.remove(); });
// Сайт ачылганда эле өйдө жакта «Орнотуу» тилкеси чыгат (жапса — 3 күн чыкпайт)
function instBar() {
  if (window.matchMedia("(display-mode: standalone)").matches || navigator.standalone) return;
  try { if (Date.now() - (+localStorage.getItem("instNo") || 0) < 3 * 864e5) return; } catch (e) {}
  if (document.getElementById("instBar") || !document.body) return;
  const ios = /iphone|ipad/i.test(navigator.userAgent);
  const can = !!window.INSTALL;
  const d = document.createElement("div"); d.id = "instBar";
  d.innerHTML = `<img src="/static/icon-192.png" alt=""><div><b>Такси ТАП! тиркемеси</b><small>${can ? "Телефонго орнотуп алыңыз — бир басуу менен ачылат"
    : ios ? "Safari: «Бөлүшүү» ⬆️ → «На экран „Домой“»" : "Браузердин менюсу ⋮ → «Башкы экранга кошуу»"}</small></div>
    ${can ? `<button id="instGo">Орнотуу</button>` : ""}<button id="instX" aria-label="Жабуу">✕</button>`;
  document.body.appendChild(d);
  d.querySelector("#instX").onclick = () => { try { localStorage.setItem("instNo", Date.now()); } catch (e) {} d.remove(); };
  const g = d.querySelector("#instGo");
  if (g) g.onclick = async () => { if (!window.INSTALL) return d.remove(); window.INSTALL.prompt(); const r = await window.INSTALL.userChoice; window.INSTALL = null; d.remove();
    if (r && r.outcome !== "accepted") try { localStorage.setItem("instNo", Date.now()); } catch (e) {} };
}
// Браузер өзү сунуштабаса (Яндекс, Samsung, iPhone) — 4 секунддан кийин колдонмо көрсөтөбүз
window.addEventListener("load", () => setTimeout(() => { if (!window.INSTALL && /android|iphone|ipad/i.test(navigator.userAgent)) instBar(); }, 4000));
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

// ---------- Такси ТАП! шилтемелери (кабинетте бөлүшүү үчүн) ----------
function linksHTML(bot) {
  const o = location.origin;
  const row = (id, ico, title, url, sub) => `<div class="lnk"><div class="lnk-t"><b>${ico} ${title}</b><span>${url.replace(/^https?:\/\//, "")}</span>${sub ? `<small>${sub}</small>` : ""}</div>
    <button class="lnk-b" data-copy="${url}">📋</button><button class="lnk-b" data-share="${url}" data-title="${title}">📤</button></div>`;
  return `<div class="lnks"><h3 style="margin:4px 0 8px">🔗 Такси ТАП! шилтемелери</h3>
    ${row("p", "🧳", "Жүргүнчүлөр үчүн", o + "/", "Таксини ушул жерден чакырышат")}
    ${row("d", "🚗", "Айдоочулар үчүн", o + "/driver", "Айдоочу болуп катталуу")}
    ${bot ? row("b", "✈️", "Telegram бот", "https://t.me/" + bot, "Номерди ырастоо жана билдирүүлөр") : ""}
    <p class="muted" style="margin:6px 0 0">📋 — көчүрүү, 📤 — WhatsApp, Telegram аркылуу жөнөтүү.</p></div>`;
}
function bindLinks() {
  document.querySelectorAll("[data-copy]").forEach(b => b.onclick = async () => {
    try { await navigator.clipboard.writeText(b.dataset.copy); b.textContent = "✓"; }
    catch (e) { prompt("Көчүрүп алыңыз:", b.dataset.copy); }
    setTimeout(() => b.textContent = "📋", 1500);
  });
  document.querySelectorAll("[data-share]").forEach(b => b.onclick = async () => {
    const url = b.dataset.share, text = "Такси ТАП! — Базар-Коргондо такси чакыруу:";
    if (navigator.share) { try { await navigator.share({title:"Такси ТАП!", text, url}); } catch (e) {} }
    else location.href = "https://wa.me/?text=" + encodeURIComponent(text + " " + url);
  });
}

// ---------- Навигация: сары жебе (мен), компас, «мен турган жер» баскычы ----------
// Жебе телефон кайсы жакты караса ошол жакка бурулат (жүрүп баратканда — GPS багыты).
window.NAV = (function () {
  let map = null, marker = null, pos = null, head = null, gpsHead = null, wrap = null, onLocate = null, watching = false, oriOn = false;
  const ARROW = `<svg viewBox="0 0 60 60" width="52" height="52"><defs>
      <linearGradient id="ga" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ffd84d"/><stop offset="1" stop-color="#f5a800"/></linearGradient>
      <linearGradient id="gb" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#e09a00"/><stop offset="1" stop-color="#b87800"/></linearGradient></defs>
    <path d="M30 4 L52 52 L30 41 Z" fill="url(#gb)"/><path d="M30 4 L8 52 L30 41 Z" fill="url(#ga)"/></svg>`;
  const LOC = `<svg viewBox="0 0 24 24" width="24" height="24"><path d="M21.5 2.5 L2.8 10.3 L11 12.9 L13.7 21.2 Z" fill="#16161a" stroke="#16161a" stroke-width="1.2" stroke-linejoin="round"/></svg>`;
  const COMP = `<svg viewBox="0 0 40 40" width="34" height="34"><path d="M20 4 L26 20 L14 20 Z" fill="#ff3b30"/><path d="M20 36 L26 20 L14 20 Z" fill="#c9c9cf"/><circle cx="20" cy="20" r="2.6" fill="#fff"/></svg>`;
  function icon() { return L.divIcon({className:"", html:`<div class="navme"><i></i><b class="navarr">${ARROW}</b></div>`, iconSize:[52,52], iconAnchor:[26,26]}); }
  function paint() {
    const h = gpsHead !== null ? gpsHead : head;
    document.querySelectorAll(".navarr").forEach(e => e.style.transform = `rotate(${h || 0}deg)`);
    const c = document.getElementById("navComp");
    if (c) { c.firstChild.style.transform = `rotate(${-(head || 0)}deg)`; c.classList.toggle("hide", head === null); }
  }
  function onOri(e) {
    let h = null;
    if (typeof e.webkitCompassHeading === "number") h = e.webkitCompassHeading;
    else if (e.absolute && typeof e.alpha === "number") h = 360 - e.alpha;
    if (h === null) return;
    const so = (screen.orientation && screen.orientation.angle) || window.orientation || 0;
    head = (h + so + 360) % 360; paint();
  }
  function listenOri() {
    if (oriOn) return; oriOn = true;
    if ("ondeviceorientationabsolute" in window) window.addEventListener("deviceorientationabsolute", onOri);
    else window.addEventListener("deviceorientation", onOri);
  }
  async function askOri() {                       // iPhone уруксат сурайт
    try { if (window.DeviceOrientationEvent && DeviceOrientationEvent.requestPermission) {
      if (await DeviceOrientationEvent.requestPermission() !== "granted") return; } } catch (e) {}
    listenOri();
  }
  function set(p, gh, speed) {
    pos = p; gpsHead = (typeof gh === "number" && !isNaN(gh) && (speed || 0) > 1.5) ? gh : null;
    if (!map) return;
    // Аймактан сырткары турса да картада көрүнсүн: чекти ошол жерге чейин кеңейтебиз
    const mb = map.options.maxBounds;
    if (mb && mb.contains && !mb.contains(p)) {
      const d = 0.03; map.setMaxBounds(L.latLngBounds(mb.getSouthWest(), mb.getNorthEast()).extend([p[0] - d, p[1] - d]).extend([p[0] + d, p[1] + d]));
    }
    if (!marker) marker = L.marker(p, {icon:icon(), interactive:false, zIndexOffset:900, keyboard:false}).addTo(map);
    else marker.setLatLng(p);
    paint();
  }
  function watch() {
    if (watching || !navigator.geolocation) return; watching = true;
    navigator.geolocation.watchPosition(p => set([p.coords.latitude, p.coords.longitude], p.coords.heading, p.coords.speed),
      () => {}, {enableHighAccuracy:true, maximumAge:3000, timeout:20000});
  }
  function place() {
    if (!wrap) return;
    const v = window.SHEET ? SHEET.visible() : 0;
    wrap.style.bottom = (Math.max(v, 0) + 14) + "px";
  }
  function init(m, opts) {
    map = m; onLocate = (opts && opts.onLocate) || null;
    wrap = document.createElement("div"); wrap.className = "navbtns"; wrap.id = "navBtns";
    wrap.innerHTML = `<button class="navb hide" id="navComp" aria-label="Компас (түндүк)">${COMP}</button><button class="navb" id="navLoc" aria-label="Мен турган жер">${LOC}</button>`;
    document.body.appendChild(wrap);
    wrap.querySelector("#navComp").firstChild.style.transition = "transform .2s linear";
    wrap.querySelector("#navLoc").onclick = () => { askOri(); watch(); if (onLocate) onLocate(); else if (pos) map.setView(pos, Math.max(map.getZoom(), 16)); };
    wrap.querySelector("#navComp").onclick = () => { askOri(); if (pos) map.setView(pos, Math.max(map.getZoom(), 17)); };
    listenOri(); watch();
    window.addEventListener("sheetmove", place); window.addEventListener("resize", place);
    setInterval(place, 300); place();
    document.addEventListener("click", askOri, {once:true});
  }
  return {init, set, place, pos: () => pos};
})();
