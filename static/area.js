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
