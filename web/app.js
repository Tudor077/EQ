// EQ - the page. Talks to Python through window.pywebview.api; opened as a
// plain file in a browser it runs on a mock instead, so the UI can be worked on
// without the app (and without touching the real sound).

"use strict";

const $ = (id) => document.getElementById(id);
const RATE = 48000, FMIN = 20, FMAX = 20000, GMAX = 18;
const MAX_BANDS = 16;
const TYPES = [
  ["bell", "Bell"], ["lowshelf", "Low shelf"], ["highshelf", "High shelf"],
  ["lowcut", "Low cut"], ["highcut", "High cut"], ["notch", "Notch"],
];
const HAS_GAIN = { bell: 1, lowshelf: 1, highshelf: 1 };

let api = null;
let S = null;               // last state from Python
let bands = [];             // the active preset's bands, edited locally
let sel = -1;               // selected band
let spec = null, specF = null;
let editingUntil = 0;       // ignore server bands while the user is mid-edit
let drag = null;

// ---------------------------------------------------------------- the maths
// RBJ biquads, the same formulas apo.py writes and Equalizer APO runs.
function coeffs(b) {
  const a = Math.pow(10, (b.gain || 0) / 40), w = 2 * Math.PI * b.freq / RATE;
  const cw = Math.cos(w), sw = Math.sin(w), al = sw / (2 * Math.max(b.q || 0.707, 0.05));
  let c;
  switch (b.type) {
    case "bell": c = [1 + al * a, -2 * cw, 1 - al * a, 1 + al / a, -2 * cw, 1 - al / a]; break;
    case "lowshelf": case "highshelf": {
      const s = b.type === "lowshelf" ? 1 : -1, sq = 2 * Math.sqrt(a) * al;
      c = [a * ((a + 1) - s * (a - 1) * cw + sq), 2 * s * a * ((a - 1) - s * (a + 1) * cw),
           a * ((a + 1) - s * (a - 1) * cw - sq), (a + 1) + s * (a - 1) * cw + sq,
           -2 * s * ((a - 1) + s * (a + 1) * cw), (a + 1) + s * (a - 1) * cw - sq]; break;
    }
    case "lowcut": c = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2, 1 + al, -2 * cw, 1 - al]; break;
    case "highcut": c = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2, 1 + al, -2 * cw, 1 - al]; break;
    case "notch": c = [1, -2 * cw, 1, 1 + al, -2 * cw, 1 - al]; break;
  }
  const a0 = c[3];
  return [c[0] / a0, c[1] / a0, c[2] / a0, c[4] / a0, c[5] / a0];
}
function magDb(k, f) {
  const w = 2 * Math.PI * f / RATE, c1 = Math.cos(w), s1 = -Math.sin(w), c2 = Math.cos(2 * w), s2 = -Math.sin(2 * w);
  const nr = k[0] + k[1] * c1 + k[2] * c2, ni = k[1] * s1 + k[2] * s2;
  const dr = 1 + k[3] * c1 + k[4] * c2, di = k[3] * s1 + k[4] * s2;
  return 10 * Math.log10(Math.max((nr * nr + ni * ni) / (dr * dr + di * di), 1e-18));
}

// ---------------------------------------------------------------- geometry
const cv = $("cv"), ctx = cv.getContext("2d");
let W = 0, H = 0, DPR = 1;
const PAD = { l: 48, r: 18, t: 30, b: 34 };
function resize() {
  DPR = window.devicePixelRatio || 1;
  const r = cv.getBoundingClientRect();
  W = r.width; H = r.height;
  cv.width = Math.round(W * DPR); cv.height = Math.round(H * DPR);
}
const fx = (f) => PAD.l + (Math.log(f / FMIN) / Math.log(FMAX / FMIN)) * (W - PAD.l - PAD.r);
const xf = (x) => FMIN * Math.pow(FMAX / FMIN, (x - PAD.l) / (W - PAD.l - PAD.r));
const gy = (g) => PAD.t + (1 - (g + GMAX) / (2 * GMAX)) * (H - PAD.t - PAD.b);
const yg = (y) => (1 - (y - PAD.t) / (H - PAD.t - PAD.b)) * 2 * GMAX - GMAX;
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const fmtF = (f) => f >= 1000 ? (f / 1000).toFixed(f >= 10000 ? 1 : 2).replace(/\.?0+$/, "") + "k" : Math.round(f) + "";

// ---------------------------------------------------------------- drawing
function draw() {
  ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  ctx.clearRect(0, 0, W, H);
  const x0 = PAD.l, x1 = W - PAD.r, y0 = PAD.t, y1 = H - PAD.b;

  // grid
  ctx.font = "11px 'NType82 Mono', monospace";
  ctx.textAlign = "center";
  for (const f of [20, 30, 40, 50, 60, 80, 100, 200, 300, 400, 500, 600, 800, 1000, 2000, 3000, 4000, 5000, 6000, 8000, 10000, 20000]) {
    const x = fx(f), major = [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000].includes(f);
    ctx.strokeStyle = major ? "#222" : "#171717";
    ctx.beginPath(); ctx.moveTo(x, y0); ctx.lineTo(x, y1); ctx.stroke();
    if (major) { ctx.fillStyle = "#555"; ctx.fillText(fmtF(f), x, y1 + 18); }
  }
  ctx.textAlign = "right";
  for (let g = -GMAX; g <= GMAX; g += 6) {
    const y = gy(g);
    ctx.strokeStyle = g === 0 ? "#333" : "#1c1c1c";
    ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x1, y); ctx.stroke();
    ctx.fillStyle = "#555"; ctx.fillText((g > 0 ? "+" : "") + g, x0 - 10, y + 4);
  }

  // live spectrum: -90..-10 dBFS over the full height, dim, behind everything
  if (spec && specF) {
    ctx.beginPath(); ctx.moveTo(fx(specF[0]), y1);
    for (let i = 0; i < spec.length; i++) {
      const v = clamp((spec[i] + 90) / 80, 0, 1);
      ctx.lineTo(fx(specF[i]), y1 - v * (y1 - y0));
    }
    ctx.lineTo(fx(specF[specF.length - 1]), y1); ctx.closePath();
    ctx.fillStyle = "rgba(255,255,255,0.07)"; ctx.fill();
    ctx.strokeStyle = "rgba(255,255,255,0.18)"; ctx.lineWidth = 1; ctx.stroke();
  }

  const N = Math.max(200, Math.round(x1 - x0));
  const freqs = Array.from({ length: N }, (_, i) => FMIN * Math.pow(FMAX / FMIN, i / (N - 1)));
  const on = bands.filter((b) => b.on !== false);
  const ks = bands.map((b) => coeffs(b));

  // headphone correction, dashed
  const ae = S && S.autoeq_on && S.autoeq ? S.autoeq.bands.map(coeffs) : null;
  if (ae) {
    ctx.setLineDash([4, 5]); ctx.strokeStyle = "#5a5a5a"; ctx.lineWidth = 1.5;
    ctx.beginPath();
    freqs.forEach((f, i) => { const g = ae.reduce((s, k) => s + magDb(k, f), 0); i ? ctx.lineTo(fx(f), gy(clamp(g, -GMAX, GMAX))) : ctx.moveTo(fx(f), gy(clamp(g, -GMAX, GMAX))); });
    ctx.stroke(); ctx.setLineDash([]);
  }

  // the selected band's own shape, filled red
  if (sel >= 0 && bands[sel]) {
    const k = ks[sel];
    ctx.beginPath(); ctx.moveTo(x0, gy(0));
    freqs.forEach((f) => ctx.lineTo(fx(f), gy(clamp(magDb(k, f), -GMAX, GMAX))));
    ctx.lineTo(x1, gy(0)); ctx.closePath();
    ctx.fillStyle = bands[sel].on === false ? "rgba(255,255,255,0.05)" : "rgba(215,25,32,0.22)"; ctx.fill();
  }

  // the sum - what you hear
  ctx.strokeStyle = S && !S.enabled ? "#555" : "#fff"; ctx.lineWidth = 2.5;
  ctx.beginPath();
  freqs.forEach((f, i) => {
    let g = 0;
    bands.forEach((b, j) => { if (b.on !== false) g += magDb(ks[j], f); });
    const y = gy(clamp(g, -GMAX, GMAX));
    i ? ctx.lineTo(fx(f), y) : ctx.moveTo(fx(f), y);
  });
  ctx.stroke();

  // handles
  bands.forEach((b, i) => {
    const x = fx(b.freq), y = gy(HAS_GAIN[b.type] ? b.gain : 0);
    const isSel = i === sel;
    ctx.beginPath(); ctx.arc(x, y, isSel ? 13 : 11, 0, 2 * Math.PI);
    ctx.fillStyle = b.on === false ? "#222" : isSel ? "#D71920" : "#fff"; ctx.fill();
    ctx.fillStyle = b.on === false ? "#777" : isSel ? "#fff" : "#000";
    ctx.font = "12px 'NType82 Mono', monospace"; ctx.textAlign = "center";
    ctx.fillText(String(i + 1), x, y + 4);
    if (isSel) {
      ctx.fillStyle = "#fff"; ctx.font = "15px 'NDot 55', monospace";
      const lbl = fmtF(b.freq) + "Hz" + (HAS_GAIN[b.type] ? "  " + (b.gain > 0 ? "+" : "") + b.gain.toFixed(1) + "dB" : "") + "  Q" + b.q.toFixed(2);
      ctx.textAlign = x > W - 220 ? "right" : "left";
      ctx.fillText(lbl, x + (x > W - 220 ? -22 : 22), y - 18);
    }
  });
}

// ---------------------------------------------------------------- interaction
function hit(x, y) {
  for (let i = bands.length - 1; i >= 0; i--) {
    const b = bands[i], hx = fx(b.freq), hy = gy(HAS_GAIN[b.type] ? b.gain : 0);
    if ((x - hx) ** 2 + (y - hy) ** 2 < 15 * 15) return i;
  }
  return -1;
}
function pos(e) { const r = cv.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; }

cv.addEventListener("mousedown", (e) => {
  if (e.button !== 0) return;
  const [x, y] = pos(e), i = hit(x, y);
  hideMenu();
  sel = i;
  if (i >= 0) drag = { b: bands[i], x, y, f: bands[i].freq, g: bands[i].gain };
  renderBand();
});
window.addEventListener("mousemove", (e) => {
  if (!drag) { const [x, y] = pos(e); cv.style.cursor = hit(x, y) >= 0 ? "grab" : "crosshair"; return; }
  const [x, y] = pos(e), b = drag.b;
  const k = e.shiftKey ? 0.15 : 1;                      // Shift = fine
  const fNew = xf(drag.x + (x - drag.x) * k) * (drag.f / xf(drag.x));
  b.freq = Math.round(clamp(fNew, FMIN, FMAX) * 10) / 10;
  if (HAS_GAIN[b.type]) b.gain = Math.round(clamp(drag.g + (yg(drag.y + (y - drag.y) * k) - yg(drag.y)), -GMAX, GMAX) * 10) / 10;
  cv.style.cursor = "grabbing";
  pushBands(); renderBand(true);
});
window.addEventListener("mouseup", () => { if (drag) { drag = null; pushBands(true); } });

cv.addEventListener("dblclick", (e) => {
  const [x, y] = pos(e), i = hit(x, y);
  if (i >= 0) { removeBand(i); return; }
  if (bands.length >= MAX_BANDS) return warn(`${MAX_BANDS} bands at most`);
  bands.push({ type: "bell", freq: Math.round(xf(x)), gain: Math.round(clamp(yg(y), -GMAX, GMAX) * 10) / 10, q: 1.0, on: true });
  sel = bands.length - 1;
  pushBands(true); renderBand();   // pushBands renumbers, so sel moves to the new band's place
});
cv.addEventListener("wheel", (e) => {
  const [x, y] = pos(e); let i = hit(x, y);
  if (i < 0) i = sel;
  if (i < 0) return;
  e.preventDefault();
  const b = bands[i];
  b.q = Math.round(clamp(b.q * Math.pow(1.12, e.deltaY > 0 ? -1 : 1), 0.1, 24) * 100) / 100;
  sel = i; pushBands(); renderBand(true);
}, { passive: false });
cv.addEventListener("contextmenu", (e) => {
  e.preventDefault();
  const [x, y] = pos(e), i = hit(x, y);
  if (i < 0) return;
  sel = i; renderBand();
  showMenu(e.clientX, e.clientY, [
    ...TYPES.map(([t, n]) => ({ label: n, on: bands[i].type === t, fn: () => setType(i, t) })),
    { label: bands[i].on === false ? "Turn on" : "Turn off", fn: () => toggleBand(i) },
    { label: "Remove", fn: () => removeBand(i) },
  ]);
});
window.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s" && !$("dlg").open) {
    e.preventDefault();
    (e.shiftKey ? $("psaveas") : $("psave")).click();
    return;
  }
  if (e.target.tagName === "INPUT" || $("dlg").open) return;
  if ((e.key === "Delete" || e.key === "Backspace") && sel >= 0) removeBand(sel);
  if (e.key === "Escape") { sel = -1; hideMenu(); renderBand(); }
});

function setType(i, t) {
  const b = bands[i];
  b.type = t;
  if (t === "lowcut" || t === "highcut") b.q = 0.707;
  pushBands(true); renderBand();
}
function toggleBand(i) { bands[i].on = bands[i].on === false; pushBands(true); renderBand(); }
function removeBand(i) { bands.splice(i, 1); sel = Math.min(sel, bands.length - 1); if (sel === i) sel = -1; pushBands(true); renderBand(); }

let pushTimer = null;
// Bands are numbered low to high, always: a band dragged past its neighbour
// takes its number, so the chips and the handles read 1, 2, 3 left to right.
// The selection follows the band itself, not its old index.
function renumber() {
  const keep = bands[sel];
  bands.sort((a, b) => a.freq - b.freq);
  sel = keep ? bands.indexOf(keep) : -1;
}

function pushBands(now) {
  renumber();
  editingUntil = performance.now() + 1500;
  clearTimeout(pushTimer);
  const send = () => api.set_bands(JSON.parse(JSON.stringify(bands)));
  if (now) send(); else pushTimer = setTimeout(send, 30);
}

// ---------------------------------------------------------------- menus, dialogs
function showMenu(x, y, items) {
  const m = $("menu"); m.innerHTML = "";
  items.forEach((it) => { const b = document.createElement("button"); b.textContent = it.label; if (it.on) b.className = "on"; b.onclick = () => { hideMenu(); it.fn(); }; m.appendChild(b); });
  m.hidden = false;
  m.style.left = Math.min(x, innerWidth - 180) + "px"; m.style.top = Math.min(y, innerHeight - 300) + "px";
}
function hideMenu() { $("menu").hidden = true; }
document.addEventListener("mousedown", (e) => { if (!$("menu").contains(e.target)) hideMenu(); });

// The app's own dialog, for names and for yes/no - the browser's confirm()
// shows "127.0.0.1 says", which is the page's address, not anything useful.
function confirmBox(text) {
  return ask(text, null).then((v) => v !== null);
}
function ask(title, value, check) {
  const isConfirm = value === null;
  return new Promise((res) => {
    const d = $("dlg"); $("dlgt").textContent = title; $("dlgi").value = value || ""; $("dlge").textContent = "";
    $("dlgi").hidden = isConfirm;
    d.showModal(); if (!isConfirm) $("dlgi").select();
    $("dlgok").onclick = (e) => {
      if (isConfirm) return;
      const v = $("dlgi").value.trim();
      const err = !v ? "Type a name" : check ? check(v) : "";
      if (err) { e.preventDefault(); $("dlge").textContent = err; }
    };
    $("dlgi").oninput = () => { $("dlge").textContent = ""; };
    // Enter = OK. Left to the form, Enter "submits" with the FIRST button,
    // which is Cancel - so pressing Enter after typing a name threw it away.
    $("dlgi").onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); $("dlgok").click(); } };
    d.onkeydown = (e) => { if (e.key === "Enter" && isConfirm) { e.preventDefault(); $("dlgok").click(); } };
    d.onclose = () => res(d.returnValue === "ok" ? (isConfirm ? "" : $("dlgi").value.trim()) : null);
  });
}
let warnT = null;
function warn(t) { const w = $("warn"); w.textContent = t; w.hidden = false; clearTimeout(warnT); warnT = setTimeout(() => (w.hidden = true), 2500); }

// ---------------------------------------------------------------- panels
function renderBand(fromDrag) {
  const chips = $("bandchips"); chips.innerHTML = "";
  bands.forEach((b, i) => {
    const c = document.createElement("button");
    c.className = (i === sel ? "sel " : "") + (b.on === false ? "off" : "");
    c.innerHTML = `<i></i>${i + 1} · ${fmtF(b.freq)}`;
    c.onclick = () => { sel = i; renderBand(); };
    chips.appendChild(c);
  });
  const b = bands[sel];
  $("editor").hidden = !b; $("noband").hidden = !!b;
  if (!b) return;
  const tw = $("types");
  if (!fromDrag || !tw.children.length) {
    tw.innerHTML = "";
    TYPES.forEach(([t, n]) => { const x = document.createElement("button"); x.textContent = n; x.dataset.t = t; x.onclick = () => setType(sel, t); tw.appendChild(x); });
  }
  [...tw.children].forEach((x) => x.classList.toggle("on", x.dataset.t === b.type));
  for (const [id, v] of [["f", Math.round(b.freq)], ["g", b.gain.toFixed(1)], ["q", b.q.toFixed(2)]])
    if (document.activeElement !== $(id)) $(id).value = v;
  $("g").disabled = !HAS_GAIN[b.type];
  $("g").parentElement.style.opacity = HAS_GAIN[b.type] ? 1 : 0.35;
  $("bon").textContent = b.on === false ? "Off" : "On";
  $("bon").classList.toggle("on", b.on !== false);
}
for (const [id, key, lo, hi] of [["f", "freq", 10, 22000], ["g", "gain", -24, 24], ["q", "q", 0.1, 24]]) {
  $(id).addEventListener("change", () => {
    const b = bands[sel], v = parseFloat($(id).value);
    if (!b) return;
    if (isNaN(v)) { renderBand(); return warn("That isn't a number"); }
    b[key] = clamp(v, lo, hi); pushBands(true); renderBand();
  });
}
$("bon").onclick = () => sel >= 0 && toggleBand(sel);
$("bdel").onclick = () => sel >= 0 && removeBand(sel);

function renderTop() {
  $("power").classList.toggle("on", S.enabled);
  $("power").textContent = S.enabled ? "On" : "Bypass";
  $("autopre").classList.toggle("on", S.auto_preamp);
  $("preamp").textContent = (S.effective_preamp > 0 ? "+" : "") + S.effective_preamp.toFixed(1);
  $("device").textContent = S.device || "-";
  const dw = $("devwarn");
  // Windows names the same output "Speakers (2- Realtek(R) Audio)" in one API
  // and "Speakers (Realtek(R) Audio)" in another: drop the "2- " before comparing
  const norm = (n) => n.replace(/\(\d+- /, "(").trim().toLowerCase();
  if (S.device && S.apo_devices && !S.apo_devices.some((d) => norm(d) === norm(S.device))) {
    dw.hidden = false;
    $("devname").textContent = S.device;
  } else dw.hidden = true;
  const p = $("presets"); p.innerHTML = "";
  S.order.forEach((n, i) => {
    const b = document.createElement("button");
    b.className = n === S.active ? "on" : "";
    const dirty = S.drafts && S.drafts[n];
    b.innerHTML = `${esc(n)}${dirty ? `<b class="dirty" title="Unsaved changes"></b>` : ""}${i < 9 ? `<sup>${i + 1}</sup>` : ""}`;
    b.onclick = () => api.activate(n).then(refresh);
    p.appendChild(b);
  });
}
function renderSide() {
  const cur = S.current, fxs = cur.fx || {};
  $("loud").classList.toggle("on", !!fxs.loudness); $("loud").textContent = fxs.loudness ? "On" : "Off";
  if (document.activeElement !== $("xf")) $("xf").value = Math.round((fxs.crossfeed || 0) * 100);
  $("xfv").textContent = Math.round((fxs.crossfeed || 0) * 100);
  $("aeon").classList.toggle("on", S.autoeq_on); $("aeon").textContent = S.autoeq_on ? "On" : "Off";
  $("aecur").textContent = S.autoeq ? `${S.autoeq.name} · ${S.autoeq.bands.length} filters` : "No correction";
  $("auto").classList.toggle("on", S.auto_switch);
  $("psave").classList.toggle("on", S.dirty);
  $("prevert").hidden = !S.dirty;
  $("pstate").textContent = S.dirty ? `"${S.active}" has unsaved changes` : `"${S.active}" is saved`;
  $("pstate").classList.toggle("unsaved", S.dirty);
  $("fg").textContent = S.foreground || "-";
  const opts = (v) => S.order.map((n) => `<option ${n === v ? "selected" : ""}>${esc(n)}</option>`).join("");
  $("base").innerHTML = opts(S.base);
  const r = $("rules"); r.innerHTML = "";
  Object.entries(S.rules).forEach(([exe, p]) => {
    const d = document.createElement("div");
    d.className = "rule" + (exe === S.foreground ? " live" : "");
    d.innerHTML = `<span title="${esc(exe)}">${esc(exe.replace(/\.exe$/, ""))}</span><select>${opts(p)}</select><button title="Remove">×</button>`;
    d.querySelector("select").onchange = (e) => api.set_rule(exe, e.target.value).then(refresh);
    d.querySelector("button").onclick = () => api.set_rule(exe, "").then(refresh);
    r.appendChild(d);
  });
  if (!Object.keys(S.rules).length) r.innerHTML = `<div class="sub" style="margin:0">No rules yet</div>`;
  $("addfg").disabled = !S.foreground;
}
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

$("opensel").onclick = () => api.open_apo_selector && api.open_apo_selector();
$("power").onclick = () => api.set("enabled", !S.enabled).then(refresh);
$("autopre").onclick = () => api.set("auto_preamp", !S.auto_preamp).then(refresh);
$("loud").onclick = () => api.set_fx({ loudness: !(S.current.fx || {}).loudness }).then(refresh);
$("xf").oninput = () => { $("xfv").textContent = $("xf").value; editingUntil = performance.now() + 1500; };
$("xf").onchange = () => api.set_fx({ crossfeed: $("xf").value / 100 }).then(refresh);
$("aeon").onclick = () => { if (!S.autoeq) return warn("Search for your headphones first"); api.set("autoeq_on", !S.autoeq_on).then(refresh); };
$("auto").onclick = () => api.set("auto_switch", !S.auto_switch).then(refresh);
$("base").onchange = (e) => api.set("base", e.target.value).then(refresh);
$("addfg").onclick = () => S.foreground && api.set_rule(S.foreground, S.active).then(refresh);
$("psave").onclick = () => { if (!S.dirty) return warn("Nothing to save"); api.save().then(refresh); };
$("psaveas").onclick = async () => { const n = await ask("Save as a new preset", S.active + " 2", (v) => S.presets[v] ? "A preset with that name already exists" : ""); if (n) api.save_as(n).then(refresh); };
$("prevert").onclick = () => { if (!S.dirty) return; confirmBox(`Discard the changes to "${S.active}"?`).then((ok) => ok && api.revert().then(() => { editingUntil = 0; refresh(); })); };
$("pexp").onclick = async () => {
  if (!api.export_presets) return warn("Export only works in the app");
  const r = await api.export_presets();
  if (r.ok) warn(`Exported ${r.count} presets`);
  else if (!r.cancelled) warn("Export failed: " + r.error);
};
$("pimp").onclick = async () => {
  if (!api.import_presets) return warn("Import only works in the app");
  const r = await api.import_presets();
  if (r.ok) { warn(r.names.length ? `Imported: ${r.names.join(", ")}` : "The file had no presets"); refresh(); }
  else if (!r.cancelled) warn("Import failed: " + r.error);
};
$("pren").onclick = async () => { const n = await ask("New name", S.active, (v) => v !== S.active && S.presets[v] ? "That name is taken" : ""); if (n && n !== S.active) api.rename(S.active, n).then(refresh); };
$("pdel").onclick = () => { if (S.order.length <= 1) return warn("At least one preset has to stay"); confirmBox(`Delete the preset "${S.active}"?`).then((ok) => ok && api.delete(S.active).then(refresh)); };

let aeT = null;
$("aeq").oninput = () => {
  clearTimeout(aeT);
  const q = $("aeq").value.trim();
  if (q.length < 2) { $("aeres").innerHTML = ""; return; }
  aeT = setTimeout(async () => {
    $("aeres").innerHTML = `<div class="sub" style="margin:0">Searching…</div>`;
    const r = await api.autoeq_search(q);
    if (!r.ok) { $("aeres").innerHTML = `<div class="err">Couldn't get the AutoEQ list: ${esc(r.error)}</div>`; return; }
    if (!r.results.length) { $("aeres").innerHTML = `<div class="sub" style="margin:0">No model found</div>`; return; }
    $("aeres").innerHTML = "";
    r.results.forEach((h) => {
      const b = document.createElement("button");
      b.innerHTML = `${esc(h.name)}<small>${esc(h.source)}</small>`;
      b.onclick = async () => {
        b.disabled = true;
        const p = await api.autoeq_load(h.folder);
        if (!p.ok) return warn("Couldn't download the profile");
        $("aeres").innerHTML = ""; $("aeq").value = ""; refresh();
      };
      $("aeres").appendChild(b);
    });
  }, 250);
};

// ---------------------------------------------------------------- sync
async function refresh() {
  S = await api.state();
  const fresh = S.current.bands;
  if (performance.now() > editingUntil && !drag) {
    if (JSON.stringify(fresh) !== JSON.stringify(bands)) {
      bands = JSON.parse(JSON.stringify(fresh));
      if (sel >= bands.length) sel = -1;
      renderBand();
    }
  }
  renderTop(); renderSide();
}

function loop() { draw(); requestAnimationFrame(loop); }
async function pollSpectrum() {
  try { spec = await api.spectrum(); } catch (e) {}
  setTimeout(pollSpectrum, 33);
}

async function start(a) {
  api = a;
  resize(); new ResizeObserver(resize).observe(cv);   // the canvas box, not just the window
  specF = await api.spectrum_freqs();
  await refresh(); renderBand();
  setInterval(refresh, 1000);
  pollSpectrum(); loop();
}

// ---------------------------------------------------------------- mock (browser only)
function mockApi() {
  const st = {
    enabled: true, auto_preamp: true, preamp: 0, active: "Flat", base: "Flat", auto_switch: true,
    order: ["Flat", "Bass", "Cabin"], rules: { "beamng.drive.x64.exe": "Cabin" }, autoeq: null, autoeq_on: false,
    foreground: "spotify.exe", device: "Headphones (HyperX Cloud III)",
    presets: {
      Flat: { bands: [], fx: {} },
      Bass: { bands: [{ type: "lowshelf", freq: 90, gain: 6, q: 0.7, on: true }, { type: "bell", freq: 250, gain: -1.5, q: 1, on: true }], fx: {} },
      Cabin: { bands: [{ type: "lowcut", freq: 22, gain: 0, q: 0.7, on: true }, { type: "bell", freq: 55, gain: 4, q: 1.2, on: true }, { type: "highshelf", freq: 2200, gain: -9, q: 0.7, on: true }], fx: { crossfeed: 0.6 } },
    },
  };
  const F = Array.from({ length: 120 }, (_, i) => 20 * Math.pow(2, i / 12));
  const peak = () => { let m = 0; for (let i = 0; i < 240; i++) { const f = 20 * Math.pow(1000, i / 239); let g = 0; cur().bands.forEach((b) => { if (b.on !== false) g += magDb(coeffs(b), f); }); m = Math.max(m, g); } return -Math.round(m * 10) / 10; };
  const P = (v) => Promise.resolve(v);
  st.drafts = {};
  const cur = () => st.drafts[st.active] || st.presets[st.active];
  const draft = () => (st.drafts[st.active] = st.drafts[st.active] || JSON.parse(JSON.stringify(st.presets[st.active])));
  let t = 0;
  return {
    state: () => P(JSON.parse(JSON.stringify({ ...st, current: cur(), dirty: !!st.drafts[st.active], effective_preamp: st.auto_preamp ? peak() : st.preamp }))),
    spectrum_freqs: () => P(F),
    spectrum: () => { t += 0.05; return P(F.map((f, i) => -30 - 18 * Math.log10(f / 100 + 1) + 6 * Math.sin(t + i / 5) + Math.random() * 4)); },
    set_bands: (b) => { draft().bands = b.slice().sort((x, y) => x.freq - y.freq); return P(); },
    set_fx: (f) => { draft().fx = Object.assign({}, draft().fx, f); return P(); },
    save: () => { if (st.drafts[st.active]) { st.presets[st.active] = st.drafts[st.active]; delete st.drafts[st.active]; } return P(); },
    revert: () => { delete st.drafts[st.active]; return P(); },
    set: (k, v) => { st[k] = v; return P(); },
    activate: (n) => { st.active = n; return P(); },
    save_as: (n) => { st.presets[n] = JSON.parse(JSON.stringify(cur())); delete st.drafts[st.active]; st.order.push(n); st.active = n; return P(); },
    rename: (o, n) => { st.presets[n] = st.presets[o]; delete st.presets[o]; st.order = st.order.map((x) => (x === o ? n : x)); st.active = n; return P(); },
    delete: (n) => { delete st.presets[n]; st.order = st.order.filter((x) => x !== n); st.active = st.order[0]; return P(); },
    set_rule: (e, p) => { if (p) st.rules[e] = p; else delete st.rules[e]; return P(); },
    autoeq_search: (q) => P({ ok: true, results: [{ name: "HyperX Cloud III", source: "Rtings on HMS II.3", folder: "x" }] }),
    autoeq_load: () => { st.autoeq = { name: "HyperX Cloud III", bands: [{ type: "lowshelf", freq: 105, gain: 5.3, q: 0.7 }, { type: "bell", freq: 3839, gain: -9.6, q: 0.4 }, { type: "bell", freq: 6000, gain: 4, q: 2 }] }; st.autoeq_on = true; return P({ ok: true }); },
  };
}

if (window.pywebview && window.pywebview.api) start(window.pywebview.api);
else {
  let started = false;
  window.addEventListener("pywebviewready", () => { if (!started) { started = true; start(window.pywebview.api); } });
  setTimeout(() => { if (!started && !window.pywebview) { started = true; start(mockApi()); } }, 400);
}
