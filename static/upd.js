// Такси ТАП! — жаңы версия чыкса, экранда «Жаңыртуу» билдирүүсү чыгат
(function () {
  let V0 = null, shown = false;
  const chk = async () => {
    if (shown) return;
    try {
      const r = await fetch("/api/ver", {cache: "no-store", credentials: "same-origin"}); if (!r.ok) return;
      const v = (await r.json()).v; if (!v) return;
      if (V0 === null) { V0 = v; return; }
      if (v !== V0) show();
    } catch (e) {}
  };
  function show() {
    shown = true;
    const b = document.createElement("button"); b.className = "updbar"; b.type = "button";
    b.innerHTML = "<span>🔄</span><b>Жаңы версия бар</b><i>Жаңыртуу</i>";
    b.onclick = () => { b.disabled = true; b.querySelector("i").textContent = "…"; location.reload(); };
    const st = document.createElement("style");
    st.textContent = ".updbar{position:fixed;left:50%;top:calc(env(safe-area-inset-top,0px) + 74px);transform:translateX(-50%);z-index:9999;display:flex;align-items:center;gap:8px;border:0;border-radius:999px;padding:8px 8px 8px 14px;background:#16161a;color:#fff;font:inherit;font-size:15px;box-shadow:0 8px 24px rgba(0,0,0,.35);white-space:nowrap;animation:updin .35s ease}.updbar i{font-style:normal;font-weight:700;background:#ffd31a;color:#16161a;border-radius:999px;padding:6px 12px}@keyframes updin{from{opacity:0;transform:translate(-50%,-12px)}}";
    document.head.appendChild(st); document.body.appendChild(b);
  }
  chk(); setInterval(chk, 120000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) chk(); });
})();
