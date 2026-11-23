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
// Аймактан сырткарысын күңүрттөтүү (canvas): ар бир район/шаар «тешик» болуп кесилет, кесилиштер (мис. Сузактын ичиндеги Манас) жарык калат
function areaMask(gj) {
  const polys = gj.type === "Polygon" ? [gj.coordinates] : gj.coordinates;
  const Mask = L.Layer.extend({
    onAdd(m) {
      this._m = m; this._c = L.DomUtil.create("canvas", "leaflet-zoom-hide");
      this._c.style.pointerEvents = "none"; m.getPane("overlayPane").appendChild(this._c);
      m.on("move moveend zoomend resize viewreset", this._draw, this); this._draw();
    },
    onRemove(m) { m.off("move moveend zoomend resize viewreset", this._draw, this); this._c.remove(); },
    _draw() {
      const m = this._m, c = this._c, sz = m.getSize(), r = window.devicePixelRatio || 1;
      L.DomUtil.setPosition(c, m.containerPointToLayerPoint([0, 0]));
      c.width = sz.x * r; c.height = sz.y * r; c.style.width = sz.x + "px"; c.style.height = sz.y + "px";
      const x = c.getContext("2d"); x.setTransform(r, 0, 0, r, 0, 0);
      x.fillStyle = "rgba(21,39,65,.3)"; x.fillRect(0, 0, sz.x, sz.y);
      x.globalCompositeOperation = "destination-out"; x.fillStyle = "#000";
      polys.forEach(p => { x.beginPath();
        p.forEach(ring => ring.forEach(([lon, lat], i) => { const q = m.latLngToContainerPoint([lat, lon]); i ? x.lineTo(q.x, q.y) : x.moveTo(q.x, q.y); }));
        x.fill("evenodd"); });
      x.globalCompositeOperation = "source-over";
    }
  });
  return new Mask();
}
async function setupArea(map, opts = {}) {
  try {
    const a = await (await fetch("/api/area")).json();
    window.AREA = a;
    if (!a.on) return a;
    const [s, w, n, e] = a.bbox, pad = 0.06;
    if (opts.bounds !== false) {                       // айдоочунун картасында чектөө жок — каалаган жерге жылдыра алат
      map.setMaxBounds(L.latLngBounds([s - pad, w - pad], [n + pad, e + pad]));
      map.options.maxBoundsViscosity = 0.9;
      map.setMinZoom(opts.minZoom || 10);
    }
    const holes = areaRings(a.geojson).map(r => r.map(([lon, lat]) => [lat, lon]));
    if (L.Layer && L.Layer.extend && map.latLngToContainerPoint) areaMask(a.geojson).addTo(map);
    else L.polygon([[[89, -179], [89, 179], [-89, 179], [-89, -179]], ...holes],
      {stroke: false, fillColor: "#152741", fillOpacity: 0.3, interactive: false}).addTo(map);
    holes.forEach(h => L.polyline(h.concat([h[0]]), {color: "#17365C", weight: 2, dashArray: "6 6", opacity: .55, interactive: false}).addTo(map));
    if (opts.center !== false) map.setView(a.center, opts.zoom || 14);
    return a;
  } catch (err) { return null; }
}

// «🗺 Аймакты көрүү»: иштөө аймагынын чегин сары сызык менен көрсөтөт
let _areaHl = null;
function showAreaOnMap(map, onClose) {
  const a = window.AREA; if (!a || !a.geojson) return;
  const rings = areaRings(a.geojson).map(r => r.map(([lon, lat]) => [lat, lon]));
  if (_areaHl) _areaHl.remove();
  _areaHl = L.layerGroup().addTo(map);
  rings.forEach(r => L.polygon(r, {color:"#ffb703", weight:5, fillColor:"#ffc61a", fillOpacity:.12, interactive:false}).addTo(_areaHl));
  const pts = rings.flat();
  if (pts.length) { if (map.setMaxBounds) map.setMaxBounds(null); map.fitBounds(L.latLngBounds(pts), {padding:[40, 40]}); }
  window.SHEET && SHEET.collapse && SHEET.collapse();
  document.querySelectorAll(".areachip").forEach(x => x.remove());
  const c = document.createElement("div"); c.className = "areachip";
  c.innerHTML = `<img src="/static/c_map.webp?v=24" alt=""><span><b>${a.title || a.name}</b><small>Сары сызыктын ичинде заказ келет</small></span><button aria-label="Жабуу">✕</button>`;
  c.querySelector("button").onclick = () => { c.remove(); if (_areaHl) { _areaHl.remove(); _areaHl = null; } onClose && onClose(); };
  document.body.appendChild(c);
}

// Унаанын сүрөтү: айдоочу тандаган түскө боёлгон
const CAR_IMG = {"Ак":"ak", "Кара":"kara", "Күмүш":"kumush", "Боз":"boz", "Асфальт":"asfalt", "Көк":"kok", "Кызыл":"kyzyl",
  "Жашыл":"jashyl", "Сары":"sary", "Күрөң":"kuron", "Кызгылт":"kyzgylt"};
function carImg(color) {
  const c = (color || "").trim(), k = CAR_IMG[c] || Object.entries(CAR_IMG).find(([n]) => c.toLowerCase().startsWith(n.toLowerCase().slice(0, 4)))?.[1] || "ak";
  return `/static/car_${k}.webp?v=4`;
}
// KG номер рамкасы: «04KG338APG» → [04 | 🇰🇬KG | 338 APG]
function kgPlate(p) {
  const CY = {А:"A", В:"B", Е:"E", К:"K", М:"M", Н:"H", О:"O", Р:"P", С:"C", Т:"T", У:"Y", Х:"X", Г:"G", Д:"D", Л:"L", И:"I", Ф:"F", З:"Z", Ж:"J"};
  const n = String(p || "").toUpperCase().replace(/[А-ЯЁ]/g, c => CY[c] || c).replace(/[^0-9A-Z]/g, "");
  const m = /^(0[1-9])(?:KG)?(\d{3})([A-Z]{2,3})$/.exec(n);
  return m ? `<span class="kgpl"><b>${m[1]}</b><i>🇰🇬<br>KG</i><b>${m[2]} ${m[3]}</b></span>` : `<span class="kgpl"><b>${String(p || "").replace(/[<>&"]/g, "")}</b></span>`;
}
// «Асфальт түстө Хюндай Солярис»
function carText(color, model) { color = (color || "").trim(); model = (model || "").trim(); return color && model ? `${color} түстө ${model}` : (model || color); }

// ---------- тиркеме катары орнотуу (PWA) ----------
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
window.INSTALL = null;
window.addEventListener("beforeinstallprompt", e => { e.preventDefault(); window.INSTALL = e; instBar(); });
window.addEventListener("appinstalled", () => { window.INSTALL = null; const x = document.getElementById("instBar"); if (x) x.remove(); });
// Сайт ачылганда эле өйдө жакта «Орнотуу» тилкеси чыгат (жапса — 1 күн чыкпайт)
function instBar() {
  if (window.matchMedia("(display-mode: standalone)").matches || navigator.standalone) return;
  try { if (Date.now() - (+localStorage.getItem("instNo") || 0) < 864e5) return; } catch (e) {}
  if (document.getElementById("instBar") || !document.body) return;
  const ios = /iphone|ipad/i.test(navigator.userAgent);
  const can = !!window.INSTALL;
  const d = document.createElement("div"); d.id = "instBar";
  const drv = location.pathname.startsWith("/driver");
  d.innerHTML = `<img src="${drv ? "/static/icon-d-192.png?v=1" : "/static/logo.png"}" alt=""><div><b>${drv ? "«ТАП Айдоочу» тиркемеси" : "Такси ТАП! тиркемеси"}</b><small>${can ? "Телефонго орнотуп алыңыз — бир басуу менен ачылат"
    : ios ? "Safari: «Бөлүшүү» ⬆️ → «На экран „Домой“»" : "Chrome менюсу ⋮ → «Добавить на гл. экран» → «Установить»"}</small></div>
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
  const drv = location.pathname.startsWith("/driver");
  if (window.INSTALL) return `<button class="btn ghost" id="instBtn">📲 ${drv ? "«ТАП Айдоочу» иконкасын телефонго орнотуу" : "Телефонго тиркеме катары орнотуу"}</button>`;
  if (ios) return `<p class="muted" style="margin-top:10px">📲 Орнотуу: Safari'де «Бөлүшүү» → «На экран „Домой“».</p>`;
  if (/android/i.test(navigator.userAgent)) return `<p class="muted" style="margin-top:10px">📲 Орнотуу: Chrome'дун менюсу ⋮ → «Установить приложение» же «Добавить на главный экран».</p>`;
  return "";
}
function bindInstall() {
  const b = document.getElementById("instBtn");
  if (b) b.onclick = async () => { window.INSTALL.prompt(); await window.INSTALL.userChoice; window.INSTALL = null; b.remove(); };
}

// ---------- Төмөнкү барак: өйдө-ылдый сүрүү (картаны көрүү үчүн) ----------
// Тутканы (сызыкча) ылдый сүрсөңүз — барак жыйылып, карта көрүнөт; өйдө сүрсөңүз же бассаңыз — ачылат.
window.SHEET = (function () {
  // Барак: тутканы же барактын өзүн (жогору жакта турганда) сүрүп жабуу/ачуу; тез «серпсе» — ошол жакка кетет.
  let sheet = null, grab = null, cur = 0, collapsed = false;
  let st = null;                 // {y, x, t, base, fromGrab, drag, decided, lastY, lastT, v}
  const PEEK = 110;
  const max = () => sheet ? Math.max(0, sheet.offsetHeight - PEEK) : 0;
  function set(y, anim) {
    cur = Math.max(0, Math.min(max(), y));
    sheet.style.transition = anim ? "transform .22s cubic-bezier(.2,.8,.2,1)" : "none";
    sheet.style.transform = cur ? `translateY(${cur}px)` : "";
    window.dispatchEvent(new Event("sheetmove"));
  }
  function snap(c) { collapsed = c; set(c ? max() : 0, true); grab && grab.classList.toggle("down", c); sheet.classList.toggle("folded", c); if (c) sheet.scrollTop = 0; }
  const interactive = el => el && el.closest && el.closest("input,textarea,select,.res,.cls,.chips,.quick,table,.lnk-b");
  function down(y, x, target) {
    st = {y, x, t: Date.now(), base: cur, fromGrab: !!(grab && grab.contains(target)), drag: false, decided: false,
          lastY: y, lastT: Date.now(), v: 0, target};
  }
  function move(y, x, e) {
    if (!st) return;
    const dy = y - st.y, dx = x - st.x, now = Date.now();
    if (!st.decided) {
      if (Math.abs(dy) < 6 && Math.abs(dx) < 6) return;
      st.decided = true;
      const vertical = Math.abs(dy) > Math.abs(dx);
      st.drag = vertical && (st.fromGrab || collapsed || (sheet.scrollTop <= 0 && dy > 0 && !interactive(st.target)));
    }
    if (!st.drag) return;
    e && e.cancelable && e.preventDefault();
    const dt = Math.max(1, now - st.lastT);
    st.v = 0.7 * st.v + 0.3 * ((y - st.lastY) / dt);      // px/ms, жумшартылган
    st.lastY = y; st.lastT = now;
    set(st.base + dy, false);
  }
  function up() {
    if (!st) return;
    const s0 = st; st = null;
    if (!s0.drag) {
      if (!s0.decided && s0.fromGrab) return snap(!collapsed);          // туткасын басса — которуштурат
      if (!s0.decided && collapsed && !interactive(s0.target)) return snap(false);   // жабык баракты басса — ачылат
      return;
    }
    if (s0.v > 0.35) return snap(true);                  // ылдый серпти
    if (s0.v < -0.35) return snap(false);                // өйдө серпти
    snap(cur > max() * 0.35);
  }
  function init(el) {
    sheet = el; grab = el.querySelector(".grab"); if (!grab) return;
    el.addEventListener("touchstart", e => down(e.touches[0].clientY, e.touches[0].clientX, e.target), {passive:true});
    el.addEventListener("touchmove", e => move(e.touches[0].clientY, e.touches[0].clientX, e), {passive:false});
    el.addEventListener("touchend", up); el.addEventListener("touchcancel", up);
    grab.addEventListener("mousedown", e => { down(e.clientY, e.clientX, e.target); e.preventDefault(); });
    window.addEventListener("mousemove", e => move(e.clientY, e.clientX, e));
    window.addEventListener("mouseup", up);
  }
  return {
    init,
    refresh() { if (sheet && collapsed) set(max(), false); },
    expand() { if (sheet && collapsed) snap(false); },
    collapse() { if (sheet && !collapsed) snap(true); },
    isOpen() { return !!sheet && !collapsed; },
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
    ${row("p", '<img class="lki" src="/static/r_bag.webp?v=24" alt="">', "Жүргүнчүлөр үчүн", o + "/", "Таксини ушул жерден чакырышат")}
    ${row("d", '<img class="lki rc" src="/static/r_car.webp?v=24" alt="">', "Айдоочулар үчүн", o + "/driver", "Айдоочу болуп катталуу")}
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
  let compFn = null, compAng = 0, onFix = null, single = false, showComp = false;
  let map = null, marker = null, pos = null, head = null, gpsHead = null, wrap = null, onLocate = null, watching = false, oriOn = false;
  const ARROW = `<img src="/static/nav_arrow.webp?v=4" width="54" height="54" alt="" draggable="false" style="display:block;pointer-events:none">`;
  const LOC = `<svg viewBox="0 0 24 24" width="24" height="24"><path d="M21.5 2.5 L2.8 10.3 L11 12.9 L13.7 21.2 Z" fill="#16161a" stroke="#16161a" stroke-width="1.2" stroke-linejoin="round"/></svg>`;
  const COMP = `<svg viewBox="0 0 40 40" width="34" height="34"><path d="M20 4 L26 20 L14 20 Z" fill="#ff3b30"/><path d="M20 36 L26 20 L14 20 Z" fill="#c9c9cf"/><circle cx="20" cy="20" r="2.6" fill="#fff"/></svg>`;
  // Жүргүнчүдө жебе жок — жөн гана «сиз бул жердесиз» деген тегерек чекит
  function icon() { return document.body.classList.contains("ridp")
    ? L.divIcon({className:"", html:`<div class="medot"><i></i><b></b><span class="melbl">Сиз ушул жердесиз</span></div>`, iconSize:[30,30], iconAnchor:[15,15]})
    : L.divIcon({className:"", html:`<div class="navme"><i></i><b class="navarr">${ARROW}</b></div>`, iconSize:[52,52], iconAnchor:[26,26]}); }
  function paint() {
    const h = gpsHead !== null ? gpsHead : head;
    document.querySelectorAll(".navarr").forEach(e => e.style.transform = `rotate(${h || 0}deg)`);
    const c = document.getElementById("navComp");
    if (c && compFn && single) {                         // бир баскыч: «Жол өйдө» күйүк болсо — компас, болбосо ➤ (ошол эле жерде)
      c.firstChild.style.transform = `rotate(${compAng}deg)`; c.classList.toggle("hide", !showComp);
      const l = document.getElementById("navLoc"); if (l) l.classList.toggle("hide", showComp);
    } else if (c && compFn) { c.firstChild.style.transform = `rotate(${compAng}deg)`; c.classList.remove("hide"); }
    else if (c) { c.firstChild.style.transform = `rotate(${-(head || 0)}deg)`; c.classList.toggle("hide", head === null); }
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
  // GPS «секирип» кетпесин: жаңы так чекит бар болсо, тактыгы начар (>100 м) же эскирген чекитти этибарга албайбыз
  let goodAt = 0, lastTs = 0;
  function accept(c, ts) {
    const now = Date.now(), acc = (c && c.accuracy) || 0;
    if (ts && ts < lastTs) return false;                                   // эски чекит кийин келип калды
    if (acc > 100 && now - goodAt < 30000) return false;                   // начар чекит, жакында так чекит болгон
    if (ts) lastTs = ts; if (acc <= 100) goodAt = now;
    return true;
  }
  function set(p, gh, speed) {
    pos = p; gpsHead = (typeof gh === "number" && !isNaN(gh) && (speed || 0) > 1.5) ? gh : null;
    if (!map) return;
    // Аймактан сырткары турса да картада көрүнсүн: чекти ошол жерге чейин кеңейтебиз
    const mb = map.options && map.options.maxBounds;
    if (mb && mb.contains && !mb.contains(p)) {
      const d = 0.03; map.setMaxBounds(L.latLngBounds(mb.getSouthWest(), mb.getNorthEast()).extend([p[0] - d, p[1] - d]).extend([p[0] + d, p[1] + d]));
    }
    if (!marker) { const rid = document.body.classList.contains("ridp");
      marker = L.marker(p, {icon:icon(), interactive:rid, zIndexOffset:rid ? 300 : 900, keyboard:false}).addTo(map);
      if (rid) marker.on("click", () => { if (pos) map.setView(pos, Math.max(map.getZoom(), 16)); }); }
    else { if (map.hasLayer && !map.hasLayer(marker)) marker.addTo(map); marker.setLatLng(p); }
    paint();
  }
  let wid = null, wFix = 0;
  function watch() {
    if (watching || !navigator.geolocation) return; watching = true; wFix = Date.now();
    wid = navigator.geolocation.watchPosition(p => { wFix = Date.now(); if (!accept(p.coords, p.timestamp)) return;
        const ll = [p.coords.latitude, p.coords.longitude]; set(ll, p.coords.heading, p.coords.speed); if (onFix) onFix(ll, p.coords.heading, p.coords.speed, p.coords.accuracy); },
      () => {}, {enableHighAccuracy:true, maximumAge:0, timeout:20000});
  }
  setInterval(() => {                             // GPS үнсүз токтоп калса (Android) — кайра иштетебиз
    if (!watching || document.visibilityState !== "visible" || Date.now() - wFix < 20000) return;
    try { navigator.geolocation.clearWatch(wid); } catch (e) {} watching = false; watch();
  }, 5000);
  function place() {
    if (!wrap) return;
    const v = window.SHEET ? SHEET.visible() : 0;
    wrap.style.bottom = (Math.max(v, 0) + 14) + "px";
    wrap.style.visibility = (v + 14 + (wrap.offsetHeight || 54) > window.innerHeight - 190) ? "hidden" : "";   // барак бийик болсо — үстүңкү баскычтарды жаап калбасын
  }
  function init(m, opts) {
    window.NAV_ACCEPT = accept;
    map = m; onLocate = (opts && opts.onLocate) || null; compFn = (opts && opts.onComp) || null; onFix = (opts && opts.onFix) || null; single = !!(opts && opts.single);
    wrap = document.createElement("div"); wrap.className = "navbtns"; wrap.id = "navBtns";
    wrap.innerHTML = `<button class="navb sat" id="navSat" aria-label="Спутник / Карта"><img src="/static/ic_sat.webp?v=24" alt="" style="width:44px;height:30px;object-fit:contain"></button><button class="navb hide" id="navComp" aria-label="Компас (түндүк)">${COMP}</button><button class="navb" id="navLoc" aria-label="Мен турган жер">${LOC}</button>`;
    document.body.appendChild(wrap);
    satInit(m, wrap.querySelector("#navSat"));
    wrap.querySelector("#navComp").firstChild.style.transition = "transform .2s linear";
    wrap.querySelector("#navLoc").onclick = () => { askOri(); watch(); if (onLocate) onLocate(); else if (pos) map.setView(pos, Math.max(map.getZoom(), 16)); };
    wrap.querySelector("#navComp").onclick = () => { askOri(); if (compFn) return compFn(); if (pos) map.setView(pos, Math.max(map.getZoom(), 17)); };
    listenOri(); watch();
    window.addEventListener("sheetmove", place); window.addEventListener("resize", place);
    setInterval(place, 300); place();
    document.addEventListener("click", askOri, {once:true});
  }
  function comp(a, show) { compAng = a; if (show !== undefined) showComp = !!show; paint(); }
  return {init, set, place, comp, pos: () => pos};
})();

// ---------- Спутник ↔ Карта ----------
const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/";
function satInit(map, btn) {
  let sat = null, on = false;
  try { on = localStorage.mapSat === "1"; } catch (e) {}
  const apply = () => {
    if (on && !sat) sat = L.layerGroup([
      // Спутник сүрөтү жок жерде (blankTile=false → 404) боз «Map data not available» эмес, астындагы кадимки карта көрүнөт
      L.tileLayer(ESRI + "World_Imagery/MapServer/tile/{z}/{y}/{x}?blankTile=false", {maxZoom:19, maxNativeZoom:18, attribution:"© Esri", errorTileUrl:"data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw=="}),
      L.tileLayer(ESRI + "Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}", {maxZoom:19, maxNativeZoom:17}),
      L.tileLayer(ESRI + "Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}", {maxZoom:19, maxNativeZoom:17})]);
    if (on) sat.addTo(map);
    else if (sat) map.removeLayer(sat);
    if (map.getContainer) map.getContainer().classList.toggle("satmode", on);
    btn.innerHTML = `<img src="/static/${on ? "c_map" : "ic_sat"}.webp?v=24" alt="" style="width:44px;height:30px;object-fit:contain">`; btn.classList.toggle("on", on);
    btn.setAttribute("aria-label", on ? "Картага өтүү" : "Спутникке өтүү");
  };
  btn.onclick = () => { on = !on; try { localStorage.mapSat = on ? "1" : "0"; } catch (e) {} apply();
    if (typeof toast === "function") toast(on ? "🛰 Спутник · көчөлөрдүн аттары менен" : "🗺 Кадимки карта", 1800); };
  apply();
}

// ---------- Кыска кабар (5 сек) ----------
function toast(text, ms) {
  let t = document.getElementById("toast");
  if (!t) { t = document.createElement("div"); t.id = "toast"; document.body.appendChild(t); }
  t.textContent = text; t.classList.add("on"); t.classList.toggle("ok", /^✓/.test(text));
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("on"), ms || 5000);
  t.onclick = () => t.classList.remove("on");
}

// Ылдыйкы менюдагы «Кабинет» — колдонуучунун өз сүрөтү (жок болсо — аты баш тамгасы сары тегеректе)
function navAvatar(av, name) {
  const a = document.querySelector('#bnav [data-k="cab"]'); if (!a) return;
  const old = a.querySelector("img, .navav"); if (!old) return;
  const el = document.createElement(av ? "img" : "span"); el.className = "navav";
  if (av) { el.src = av; el.alt = ""; el.onerror = () => navAvatar(null, name); }
  else el.textContent = ((name || "").trim()[0] || "?").toUpperCase();
  old.replaceWith(el);
}
