// Үйрөткүч (story сыяктуу): tutShow(кадамдар, localStorage ачкычы). Жүргүнчү жана айдоочу баракчалары колдонот.
(function () {
  const st = document.createElement("style");
  st.textContent = "/* Үйрөткүч (story) */\n#tut{position:fixed;inset:0;z-index:9000;background:radial-gradient(120% 70% at 50% 0%,#fff6cf 0%,#fffdf5 55%,#fff 100%);display:flex;flex-direction:column;align-items:center;padding:calc(env(safe-area-inset-top) + 12px) 18px calc(env(safe-area-inset-bottom) + 14px);user-select:none;-webkit-user-select:none;touch-action:manipulation;animation:tutIn .25s ease}\n@keyframes tutIn{from{opacity:0;transform:scale(.98)}to{opacity:1}}\n#tut .tb{display:flex;gap:5px;width:100%}#tut .tb i{flex:1;height:4px;border-radius:3px;background:#e2ded2;overflow:hidden}#tut .tb i b{display:block;height:100%;width:0;background:#16161a}\n#tut .tx{position:absolute;right:14px;top:calc(env(safe-area-inset-top) + 26px);width:40px;height:40px;border:0;border-radius:50%;background:rgba(0,0,0,.06);font-size:22px;color:#16161a;z-index:3}\n#tut h2{margin:30px 46px 0;text-align:center;font-size:22px;line-height:1.2;color:#16161a}\n#tut .ph{position:relative;flex:1;min-height:0;margin:16px 0 0;display:flex;align-items:center;justify-content:center;width:100%}\n#tut .fr{position:relative;height:100%;max-height:520px;aspect-ratio:390/844;border:7px solid #16161a;border-radius:30px;overflow:hidden;background:#fff;box-shadow:0 18px 40px rgba(0,0,0,.18)}\n#tut .fr img{width:100%;height:100%;object-fit:cover;display:block}\n#tut .hl{position:absolute;border:3px solid #ffc61a;border-radius:16px;box-shadow:0 0 0 2000px rgba(0,0,0,.28);animation:tutP 1.4s ease-in-out infinite}\n@keyframes tutP{50%{border-color:#ff9f0a;transform:scale(1.04)}}\n#tut .hero{display:flex;flex-direction:column;align-items:center;gap:14px}#tut .hero img{width:210px}#tut .hero .lg{font-size:30px;font-weight:800;color:#16161a}#tut .hero .lg span{color:#f5b400}\n#tut p.c{margin:16px 6px 0;text-align:center;font-size:16.5px;line-height:1.4;color:#2c2c33;min-height:3.4em}\n#tut .nm{margin-top:8px;font-weight:700;color:#8a8a93;font-size:15px}#tut .nm b{color:#16161a}\n#tut .ok{margin-top:10px;width:100%;height:50px;border:0;border-radius:16px;background:#ffc61a;font:inherit;font-weight:700;font-size:17px;color:#16161a}\n#tut .tap{position:absolute;top:80px;bottom:120px;width:40%;z-index:2}#tut .tap.l{left:0}#tut .tap.r{right:0;width:60%}";
  document.head.appendChild(st);
})();
function tutShow(TUT, key) {
  if (document.getElementById("tut")) return;
  try { localStorage[key] = "1"; } catch (e) {}
  const el = document.createElement("div"); el.id = "tut"; document.body.appendChild(el);
  let i = 0, t0 = 0, raf = 0, paused = false, pausedAt = 0; const DUR = 10000;
  const close = () => { cancelAnimationFrame(raf); el.remove(); };
  const show = n => {
    i = Math.max(0, Math.min(TUT.length - 1, n)); const s = TUT[i], last = i === TUT.length - 1;
    const b = s.b ? `<i class="hl" style="left:${s.b[0] - 1.5}%;top:${s.b[1] - .8}%;width:${s.b[2] + 3}%;height:${s.b[3] + 1.6}%"></i>` : "";
    el.innerHTML = `<div class="tb">${TUT.map((_, k) => `<i><b style="width:${k < i ? 100 : 0}%"></b></i>`).join("")}</div>
      <button class="tx" aria-label="Жабуу">✕</button><h2>${s.t}</h2>
      <div class="ph">${s.i ? `<div class="fr"><img src="/static/tut_${s.i}.webp?v=1" alt="">${b}</div>` : `<div class="hero"><img src="/static/${TUT[0].img || "r_car"}.webp?v=24" alt=""><div class="lg">ТАКСИ <span>ТАП!</span></div></div>`}</div>
      <p class="c">${s.c}</p><div class="nm"><b>${i + 1}</b>/${TUT.length}</div>
      ${last ? `<button class="ok">✓ Түшүндүм</button>` : ""}<div class="tap l"></div><div class="tap r"></div>`;
    el.querySelector(".tx").onclick = close; const ok = el.querySelector(".ok"); if (ok) ok.onclick = close;
    const l = el.querySelector(".tap.l"), r = el.querySelector(".tap.r");
    l.onclick = () => show(i - 1); r.onclick = () => last ? null : show(i + 1);
    [l, r].forEach(z => { z.onpointerdown = () => { paused = true; pausedAt = performance.now(); };
      z.onpointerup = z.onpointercancel = z.onpointerleave = () => { if (paused) { t0 += performance.now() - pausedAt; paused = false; } }; });
    t0 = performance.now();
  };
  const tick = now => {
    if (!document.getElementById("tut")) return;
    if (!paused) { const f = Math.min(1, (now - t0) / DUR), bar = el.querySelectorAll(".tb i b")[i]; if (bar) bar.style.width = (f * 100) + "%";
      if (f >= 1 && i < TUT.length - 1) show(i + 1); }
    raf = requestAnimationFrame(tick);
  };
  show(0); raf = requestAnimationFrame(tick);
}
