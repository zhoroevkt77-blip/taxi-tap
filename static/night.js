// 🌙 Түнкү карта: күн батып 20 мүнөт өткөндө карта өзү караңгы болот, күн чыгардан 20 мүнөт мурун жарык болот.
// Күндүн чыгышы/батышы телефондо эсептелет (интернет керек эмес). Жөндөө: localStorage.mapTheme = auto | light | dark
(function () {
  const LAT = 41.0, LON = 72.9, PAD = 20 * 60000, R = Math.PI / 180;
  const sin = x => Math.sin(x * R), cos = x => Math.cos(x * R);
  function sun(ms, lat, lon) {                       // Wikipedia: Sunrise equation
    const n = Math.round(ms / 86400000 + 2440587.5 - 2451545.0008 - lon / 360);
    const Js = n - lon / 360;                        // жергиликтүү күн ортосу (J2000ден бери күн)
    const M = (357.5291 + 0.98560028 * Js) % 360;
    const C = 1.9148 * sin(M) + 0.02 * sin(2 * M) + 0.0003 * sin(3 * M);
    const lam = (M + C + 180 + 102.9372) % 360;
    const Jt = 2451545 + Js + 0.0053 * sin(M) - 0.0069 * sin(2 * lam);
    const d = Math.asin(sin(lam) * sin(23.4397)) / R;
    const w = Math.acos((sin(-0.833) - sin(lat) * sin(d)) / (cos(lat) * cos(d))) / R;
    const toMs = J => (J - 2440587.5) * 86400000;
    return {rise: toMs(Jt - w / 360), set: toMs(Jt + w / 360)};
  }
  function isNight(ms) {
    ms = ms || Date.now();
    const s = sun(ms, LAT, LON);
    return ms > s.set + PAD || ms < s.rise - PAD;
  }
  const mode = () => { try { return localStorage.mapTheme || "auto"; } catch (e) { return "auto"; } };
  function apply() {
    const m = mode(), dark = m === "dark" || (m === "auto" && isNight());
    document.documentElement.classList.toggle("mapnight", dark);
  }
  const hm = ms => new Date(ms).toLocaleTimeString("ru-RU", {hour:"2-digit", minute:"2-digit"});
  window.NIGHT = {
    sun, isNight, apply, mode,
    set(m) { try { localStorage.mapTheme = m; } catch (e) {} apply(); },
    html() {
      const s = sun(Date.now(), LAT, LON), m = mode();
      const b = (k, t) => `<button data-mt="${k}" class="${m === k ? "on" : ""}">${t}</button>`;
      return `<div class="mtheme"><b>🌙 Түнкү карта</b><div class="muted">Авто: бүгүн ${hm(s.set + PAD)} – ${hm(s.rise - PAD + 86400000)} караңгы</div>
        <div class="mt-b">${b("auto", "Авто")}${b("light", "☀️ Жарык")}${b("dark", "🌙 Караңгы")}</div></div>`;
    },
    bind(root) {
      (root || document).querySelectorAll("[data-mt]").forEach(x => x.onclick = () => {
        NIGHT.set(x.dataset.mt);
        x.parentNode.querySelectorAll("[data-mt]").forEach(y => y.classList.toggle("on", y === x));
      });
    }
  };
  apply();
  setInterval(apply, 60000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) apply(); });
})();
