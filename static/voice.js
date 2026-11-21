// Телефондогу каталарды серверге жиберебиз (Railway логунда «JSLOG»)
function jslog(m) { try { navigator.sendBeacon ? navigator.sendBeacon("/api/jslog", new Blob([JSON.stringify({m:String(m) + " | " + navigator.userAgent.slice(0, 120)})], {type:"application/json"}))
  : fetch("/api/jslog", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({m:String(m)})}); } catch (e) {} }
window.addEventListener("error", e => jslog("ERR " + (e.message || "") + " @" + (e.filename || "").split("/").pop() + ":" + e.lineno));
window.addEventListener("unhandledrejection", e => jslog("REJ " + ((e.reason && (e.reason.stack || e.reason.message)) || e.reason)));
// Такси ТАП! — кыргызча үн: админ жазган клиптер (/voice/<key>.wav) улам-улам ойнойт; жок сөздү телефондун үнү окуйт.
// Айдоочу да, жүргүнчү да колдонот. localStorage: voice = on|off, vmode = ky|tts.
const VLBL = {
  new_order:"Жаңы заказ", new_delivery:"Жеткирүү заказы", next_order:"Кийинки заказ", som:"сом", km:"километр", point:"бүтүн", tenth:"ондон",
  goal:"Күндүк максат аткарылды", voice_on:"Үн күйгүзүлдү",
  d_cancel:"Жүргүнчү заказды жокко чыгарды", d_msg:"Жүргүнчүдөн билдирүү келди", d_near:"Жүргүнчүгө жеттиңиз",
  d_wait5:"Беш мүнөт өттү, жүргүнчү келбесе баскычты басыңыз", d_done:"Сапар бүттү", d_lowbal:"Балансыңыз аз, толуктаңыз",
  d_missed:"Заказ башка айдоочуга өттү", d_online:"Линиядасыз", d_offline:"Линиядан чыктыңыз", d_hot:"Бул жерде заказ көп",
  r_found:"Айдоочу табылды", r_arrived:"Айдоочу келди, чыгыңыз", r_msg:"Айдоочудан билдирүү келди", r_go:"Ак жол!", d_out:"Аймактан чыгып кеттиңиз", d_in:"Аймакка кирдиңиз, линияга чыгасызбы?",
  n0:"нөл", n1:"бир", n2:"эки", n3:"үч", n4:"төрт", n5:"беш", n6:"алты", n7:"жети", n8:"сегиз", n9:"тогуз",
  n10:"он", n20:"жыйырма", n30:"отуз", n40:"кырк", n50:"элүү", n60:"алтымыш", n70:"жетимиш", n80:"сексен", n90:"токсон", n100:"жүз", n1000:"миң"};
const voiceOn = () => { try { return localStorage.getItem("voice") !== "off"; } catch (e) { return true; } };
const vset = () => { try { return +(localStorage.getItem("vset") || 1) || 1; } catch (e) { return 1; } };
const VSET_IC = {1:"👨", 2:"👨", 3:"👩", 4:"👩"};
const vmode = () => { try { return localStorage.getItem("vmode") || "ky"; } catch (e) { return "ky"; } };
let VOICE = null, VBUF = {}, VGEN = 0, VSRC = null, VCTX = null;
const vctx = () => VCTX = VCTX || new (window.AudioContext || window.webkitAudioContext)();
// Браузер үндү колдонуучу экранга тийгенден кийин гана уруксат берет — биринчи тийүүдө ачабыз.
["pointerdown", "touchstart", "keydown"].forEach(ev => document.addEventListener(ev, () => { try { vctx().resume(); } catch (e) {} }, {passive:true}));
function kyNum(n) {                       // 0..999999 → клиптердин ачкычтары (мис. 250 → эки жүз элүү)
  n = Math.max(0, Math.floor(+n || 0)); if (!n) return ["n0"]; const o = [];
  if (n >= 1000) { const t = Math.floor(n / 1000); if (t > 1) o.push(...kyNum(t)); o.push("n1000"); n %= 1000; }
  if (n >= 100) { const h = Math.floor(n / 100); if (h > 1) o.push("n" + h); o.push("n100"); n %= 100; }
  if (n >= 10) { o.push("n" + Math.floor(n / 10) * 10); n %= 10; }
  if (n) o.push("n" + n);
  return o;
}
// Заказ сүйлөмү админ түзгөн тартипте: {price} → сандар, {km} → бүтүн ондон сандары
function kyKmN(x) { const v = Math.round((+x || 0) * 10) / 10, i = Math.floor(v), d = Math.round((v - i) * 10);
  return [...kyNum(i), ...(d ? ["point", "tenth", "n" + d] : [])]; }
function orderToks(kind, price, km) {
  const t = (VOICE && VOICE.tpl && VOICE.tpl[kind]) || [kind, "{price}", "som", "{km}", "km"], o = [];
  for (let i = 0; i < t.length; i++) {
    if (t[i] === "{price}") { if (price) o.push(...kyNum(price)); else if (t[i + 1] === "som") i++; }
    else if (t[i] === "{km}") { if (km != null && km !== "") o.push(...kyKmN(km)); else if (t[i + 1] === "km") i++; }
    else o.push(t[i]);
  }
  return o;
}
function kyKm(x) { const v = Math.round((+x || 0) * 10) / 10, i = Math.floor(v), d = Math.round((v - i) * 10);
  return [...kyNum(i), ...(d ? ["point", "tenth", "n" + d] : []), "km"]; }
function tts(text, done) {
  if (!text || !("speechSynthesis" in window)) return done && done();
  try {
    const u = new SpeechSynthesisUtterance(text);
    const vs = speechSynthesis.getVoices(), v = vs.find(x => /^ky/i.test(x.lang)) || vs.find(x => /^ru/i.test(x.lang));
    if (v) u.voice = v; u.lang = v ? v.lang : "ru-RU"; u.rate = 1.0;
    if (done) { let f = false; const fin = () => { if (!f) { f = true; done(); } }; u.onend = u.onerror = fin; setTimeout(fin, 6000); }
    speechSynthesis.speak(u);
  } catch (e) { done && done(); }
}
async function voiceLoad() {
  try {
    let v = await (await fetch("/api/voice?set=" + vset(), {credentials:"same-origin"})).json(); if (!v || !v.sets) return;
    if (!v.have.length) {                   // тандалган үн жазыла элек → эң көп жазылган үн
      const best = v.sets.slice().sort((a, b) => b.have.length - a.have.length)[0];
      if (best && best.have.length) v = Object.assign({}, v, {set:best.id, have:best.have});
    }
    VOICE = v;
    const ac = vctx();
    for (const k of v.have) {
      if (VBUF[k] && VBUF[k].ver === v.ver && VBUF[k].set === v.set) continue;
      const r = await fetch(`/voice/${v.set}/${k}.wav?v=${v.ver}`); if (!r.ok) continue;
      const ab = await r.arrayBuffer();
      const b = await Promise.race([new Promise((ok, no) => { const pr = ac.decodeAudioData(ab, ok, no); pr && pr.catch && pr.catch(no); }),
        new Promise((_, no) => setTimeout(() => no("timeout"), 4000))]).catch(() => null);
      if (b) VBUF[k] = {ver:v.ver, set:v.set, b};
    }
    Object.keys(VBUF).forEach(k => { if (!v.have.includes(k)) delete VBUF[k]; });
    window.VOICE_HOOK && window.VOICE_HOOK();
  } catch (e) {}
}
// speak(["new_order", ...kyNum(80), "som"], 750) — wait: бип бүткөнчө күтүү (мс)
const VL = k => (VOICE && VOICE.texts && VOICE.texts[k]) || VLBL[k] || "";   // админдин өз тексти биринчи
function speak(toks, wait) {
  if (toks && VOICE && VOICE.after) toks = toks.flatMap(k => [k, ...(VOICE.after[k] || []).filter(c => !toks.includes(c))]);   // кошумча сөздөр окуядан кийин
  VGEN++; try { VSRC && VSRC.stop(); } catch (e) {} try { "speechSynthesis" in window && speechSynthesis.cancel(); } catch (e) {}
  if (!toks || !toks.length || !voiceOn() || vmode() === "off") return;
  if (vmode() !== "ky" || !toks.some(k => VBUF[k])) { const t = toks.map(VL).join(" "); return wait ? setTimeout(() => tts(t), wait) : tts(t); }
  const g = VGEN; let i = 0;
  const next = () => {
    if (g !== VGEN || i >= toks.length) return; const k = toks[i++];
    if (!VBUF[k]) return tts(VL(k), next);
    try { const ac = vctx(); ac.resume && ac.resume(); const src = ac.createBufferSource(); src.buffer = VBUF[k].b; src.connect(ac.destination);
      src.onended = () => setTimeout(next, 30); VSRC = src; src.start(); } catch (e) { next(); }
  };
  setTimeout(next, wait || 0);
}
const say = () => speak([]);
voiceLoad(); setInterval(voiceLoad, 10 * 60 * 1000);
