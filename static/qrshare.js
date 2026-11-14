/* Такси ТАП! — QR'ды бөлүшүү (WhatsApp, Telegram, Instagram, шилтеме) жана PNG сүрөтү.
   qr.js'тен кийин жүктөлөт. window.QRS.share({link, text, title}), window.QRS.png(link, px). */
(function () {
  const css = `.qrs-ov{position:fixed;inset:0;z-index:9999;background:rgba(20,20,30,.5);display:flex;align-items:flex-end;justify-content:center}
.qrs-b{background:#fff;width:100%;max-width:520px;border-radius:26px 26px 0 0;padding:14px 18px calc(22px + env(safe-area-inset-bottom,0px));font-family:Inter,system-ui,sans-serif;color:#16161a}
.qrs-b .g{width:46px;height:5px;border-radius:3px;background:#ddd;margin:0 auto 12px}
.qrs-b h3{display:flex;align-items:center;gap:10px;margin:0 0 12px;font-size:21px;font-weight:900}
.qrs-b h3 img{width:52px;height:38px;border-radius:19px;object-fit:cover;background:#f0f0f3}
.qrs-g{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;text-align:center;font-weight:800;font-size:12.5px}
.qrs-g button{border:0;background:none;font:inherit;color:inherit;cursor:pointer;padding:0}
.qrs-i{width:58px;height:58px;border-radius:18px;margin:0 auto 6px;display:grid;place-items:center;box-shadow:0 6px 14px rgba(0,0,0,.15)}
.qrs-i svg{width:30px;height:30px}
.qrs-t{background:#f6f6f8;border-radius:16px;padding:12px 14px;margin:14px 0 4px;font-size:14px;line-height:1.45;white-space:pre-line;word-break:break-word}
.qrs-m{font-size:13px;color:#16764f;font-weight:700;min-height:18px;margin:6px 2px}
.qrs-x{display:block;width:100%;border:0;border-radius:18px;background:#f1f1f4;padding:14px;font:800 16px Inter,system-ui,sans-serif;cursor:pointer;margin-top:6px}`;
  const I = {
    wa: '<svg viewBox="0 0 24 24" fill="#fff"><path d="M12 3a9 9 0 0 0-7.8 13.5L3 21l4.6-1.2A9 9 0 1 0 12 3z"/></svg>',
    tg: '<svg viewBox="0 0 24 24" fill="#fff"><path d="M21 4L3 11l6 2 2 6 3-4 5 4z"/></svg>',
    ig: '<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2"><rect x="4" y="4" width="16" height="16" rx="5"/><circle cx="12" cy="12" r="3.6"/><circle cx="16.8" cy="7.2" r=".6" fill="#fff"/></svg>',
    ln: '<svg viewBox="0 0 24 24" fill="none" stroke="#16161a" stroke-width="2.4" stroke-linecap="round"><path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/></svg>'
  };
  let styled = false;
  function png(link, px) {
    return new Promise(res => {
      const img = new Image(), svg = window.qrSvg(link, px || 600);
      img.onload = () => { const c = document.createElement("canvas"); c.width = c.height = px || 600;
        c.getContext("2d").drawImage(img, 0, 0, c.width, c.height); c.toBlob(b => res(b), "image/png"); };
      img.onerror = () => res(null);
      img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
    });
  }
  async function copy(t) { try { await navigator.clipboard.writeText(t); return true; } catch (e) { prompt("Көчүрүңүз:", t); return false; } }
  async function nativeShare(o, withFile) {
    try {
      const data = {title: o.title || "Такси ТАП!", text: o.text, url: o.link};
      if (withFile) { const b = await png(o.link, 600); if (b) { const f = new File([b], "taxi-tap-qr.png", {type: "image/png"});
        if (navigator.canShare && navigator.canShare({files: [f]})) data.files = [f]; } }
      await navigator.share(data); return true;
    } catch (e) { return false; }
  }
  function share(o) {
    if (!styled) { const s = document.createElement("style"); s.textContent = css; document.head.appendChild(s); styled = true; }
    const full = o.text + "\n" + o.link;
    const ov = document.createElement("div"); ov.className = "qrs-ov";
    ov.innerHTML = `<div class="qrs-b"><div class="g"></div><h3><img src="/static/c_gift.webp?v=8" alt="">Бөлүшүү</h3>
      <div class="qrs-g">
        <button data-k="wa"><div class="qrs-i" style="background:linear-gradient(135deg,#3ddc6f,#1fa855)">${I.wa}</div>WhatsApp</button>
        <button data-k="tg"><div class="qrs-i" style="background:linear-gradient(135deg,#45b5f0,#1f88d6)">${I.tg}</div>Telegram</button>
        <button data-k="ig"><div class="qrs-i" style="background:linear-gradient(135deg,#f9b233,#e1306c 55%,#833ab4)">${I.ig}</div>Instagram</button>
        <button data-k="ln"><div class="qrs-i" style="background:linear-gradient(135deg,#ffd31a,#fcbc00)">${I.ln}</div>Шилтеме</button></div>
      <div class="qrs-t"></div><div class="qrs-m"></div><button class="qrs-x">Жабуу</button></div>`;
    ov.querySelector(".qrs-t").textContent = full;
    const msg = t => ov.querySelector(".qrs-m").textContent = t, close = () => ov.remove();
    ov.onclick = e => { if (e.target === ov) close(); };
    ov.querySelector(".qrs-x").onclick = close;
    ov.querySelectorAll("[data-k]").forEach(b => b.onclick = async () => {
      const k = b.dataset.k;
      if (k === "wa") { if (!(navigator.share && await nativeShare(o, true))) window.open("https://wa.me/?text=" + encodeURIComponent(full), "_blank"); }
      else if (k === "tg") window.open("https://t.me/share/url?url=" + encodeURIComponent(o.link) + "&text=" + encodeURIComponent(o.text), "_blank");
      else if (k === "ig") {
        // Instagram'га сайттан түз жөнөтүүгө болбойт: QR сүрөтүн сактап, текстти көчүрөбүз
        if (navigator.share && await nativeShare(o, true)) return;
        const bl = await png(o.link, 900); if (bl) { const a = document.createElement("a"); a.href = URL.createObjectURL(bl); a.download = "taxi-tap-qr.png"; a.click(); }
        await copy(full); msg("✓ QR сүрөтү сакталды, текст көчүрүлдү — Instagram'дын Stories же постуна тиркеңиз");
      } else { await copy(o.link); msg("✓ Шилтеме көчүрүлдү"); }
    });
    document.body.appendChild(ov);
  }
  window.QRS = {share, png};
})();
