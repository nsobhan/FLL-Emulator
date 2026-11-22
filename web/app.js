import { World, MATS, PORTS, COLOR_BY_ID, defaultConfig, now } from "./sim.js";
import { BlockRunner, Project, readProject, COLOR_NAMES, ProjectError } from "./blocks.js";

const $ = s => document.querySelector(s);
const COLORS = { black: "#1d1f21", red: "#e0312b", green: "#1aa64a", blue: "#1f6fe0", yellow: "#ffd21a", magenta: "#d03ca8",
  azure: "#45b4f0", orange: "#ff8a1c", purple: "#7b3fc4", turquoise: "#21c7b8", white: "#ffffff" };

const world = new World("colors");
let project = null;
let audio = null;
const runner = new BlockRunner(world, {
  onAction: text => addAction(text),
  onState: running => setRunning(running),
  onSound: snd => { if (audio && snd) new Audio(snd.url).play().catch(() => {}); },
});

// ------------------------------------------------------------------ example project (built in)
function exampleProject() {
  const p = new Project("Example: Color stripes");
  p.type = "word-blocks";
  let n = 0;
  const B = p.blocks;
  const add = (op, o = {}) => { const id = "ex" + (n++); B[id] = { opcode: op, next: null, parent: null, inputs: o.inputs || {}, fields: o.fields || {}, shadow: !!o.shadow, topLevel: !!o.top, x: o.x || 0, y: o.y || 0 }; return id; };
  const menu = (op, value) => add(op, { shadow: true, fields: { ["field_" + op]: [value, null] } });
  const lit = v => [1, [4, String(v)]];
  const chain = ids => { for (let i = 0; i < ids.length - 1; i++) { B[ids[i]].next = ids[i + 1]; B[ids[i + 1]].parent = ids[i]; } return ids[0]; };
  const isColor = c => add("flippersensors_isColor", { inputs: { PORT: [1, menu("flippersensors_color-sensor-selector", "C")], VALUE: [1, menu("flippersensors_color-selector", String(c))] } });
  const heart = "0909099999999990999000900";
  chain([
    add("flipperevents_whenProgramStarts", { top: true, y: 0 }),
    add("flippermove_setMovementPair", { inputs: { PAIR: [1, menu("flippermove_movement-port-selector", "AB")] } }),
    add("flippermove_movementSpeed", { inputs: { SPEED: lit(30) } }),
    add("flipperlight_lightDisplayText", { inputs: { TEXT: [1, [10, "Go"]] } }),
    add("flippermove_startMove", { inputs: { DIRECTION: [1, menu("flippermove_custom-icon-direction", "forward")] } }),
    add("control_wait_until", { inputs: { CONDITION: [2, isColor(9)] } }),
    add("flippermove_stopMove"),
    add("flipperlight_lightDisplayImageOn", { inputs: { MATRIX: [1, menu("flipperlight_matrix-5x5-brightness-image", heart)] } }),
    add("flippersound_beepForTime", { inputs: { NOTE: lit(72), DURATION: lit(0.3) } }),
    add("flippermove_move", { inputs: { DIRECTION: [1, menu("flippermove_custom-icon-direction", "back")], VALUE: lit(10) }, fields: { UNIT: ["cm", null] } }),
  ]);
  for (const [i, c] of [[6, 6], [7, 7]].entries()) {
    chain([
      add("flipperevents_whenColor", { top: true, y: 100 + i, inputs: { PORT: [1, menu("flippersensors_color-sensor-selector", "C")], OPTION: [1, menu("flippersensors_color-selector", String(c[1]))] } }),
      add("flipperlight_centerButtonLight", { inputs: { COLOR: [1, menu("flipperlight_color-selector-vertical", String(c[1]))] } }),
    ]);
  }
  return p;
}

// ------------------------------------------------------------------ project bar
function showProject(p, label) {
  runner.stop();
  project = p;
  $("#projName").textContent = label || p.name;
  $("#projErr").hidden = true;
  const box = $("#blocks"); box.textContent = ""; blockEls = new Map(); lit = new Set();
  const isPy = p.type === "python";
  $("#pysrc").hidden = !isPy; box.hidden = isPy; $("#runBtn").disabled = isPy;
  if (isPy) {
    $("#pysrc").textContent = p.python;
    $("#projHint").textContent = "This is a Python project. Python runs in the Mac version (see the link below); here you can read the code.";
    return;
  }
  $("#projHint").textContent = "Press Run project, then watch the robot and the blocks. Drag the robot onto colors to try your sensors.";
  const scripts = p.scripts();
  if (!scripts.length) { box.innerHTML = '<p class="hint">This project has no blocks under a "when" block yet.</p>'; return; }
  for (const sc of scripts) { const d = document.createElement("div"); d.className = "script"; renderSeq(sc, d); box.appendChild(d); }
}
async function openFile(file) {
  try {
    const p = await readProject(file);
    showProject(p);
    world.resetRobot();
  } catch (e) {
    $("#projErr").textContent = e instanceof ProjectError ? e.message : `Couldn't open that file (${e.message}).`;
    $("#projErr").hidden = false;
  }
}
$("#projIn").onchange = e => { const f = e.target.files[0]; if (f) openFile(f); e.target.value = ""; };
const drop = $("#drop");
["dragenter", "dragover"].forEach(t => document.addEventListener(t, e => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach(t => document.addEventListener(t, e => { e.preventDefault(); if (t === "drop" || e.target === document.documentElement) drop.classList.remove("over"); }));
document.addEventListener("drop", e => { drop.classList.remove("over"); const f = e.dataTransfer?.files[0]; if (f) openFile(f); });
$("#exampleBtn").onclick = () => { setMat("colors"); showProject(exampleProject()); };
$("#runBtn").onclick = () => {
  if (!project || project.type === "python") return;
  $("#feed").textContent = ""; world.trail = [[world.x, world.y]];
  runner.start(project);
};
$("#stopBtn").onclick = () => runner.stop();

// ------------------------------------------------------------------ block view
let blockEls = new Map(), lit = new Set();
function renderSeq(nodes, parent) {
  for (const n of nodes) {
    const b = document.createElement("div");
    b.className = "blk" + (n.hat ? " hat" : ""); b.style.setProperty("--c", `var(--c-${n.cat})`);
    b.textContent = n.text; blockEls.set(n.id, b);
    if (n.body) {
      const w = document.createElement("div"); w.className = "cwrap"; w.style.setProperty("--c", `var(--c-${n.cat})`);
      const inner = document.createElement("div"); inner.className = "inner"; renderSeq(n.body, inner);
      w.append(b, inner);
      if (n.else) {
        const l = document.createElement("div"); l.className = "elselbl"; l.textContent = "else";
        const inner2 = document.createElement("div"); inner2.className = "inner"; renderSeq(n.else, inner2);
        w.append(l, inner2);
      }
      parent.appendChild(w);
    } else parent.appendChild(b);
  }
}
function highlight(ids) {
  const cur = new Set(ids);
  for (const id of lit) if (!cur.has(id)) blockEls.get(id)?.classList.remove("running");
  for (const id of cur) if (!lit.has(id)) {
    const el = blockEls.get(id); if (!el) continue;
    el.classList.add("running");
    const box = $("#blocks"), r = el.getBoundingClientRect(), br = box.getBoundingClientRect();
    if (r.top < br.top || r.bottom > br.bottom) box.scrollTop += r.top - br.top - br.height / 3;
  }
  lit = cur;
}

// ------------------------------------------------------------------ feed and run state
function addAction(text, note = false) {
  const feed = $("#feed");
  const li = document.createElement("li");
  li.className = note ? "note" : /^[▶■]/.test(text) ? "stack" : "";
  const t = document.createElement("span"); t.className = "t"; t.textContent = new Date().toTimeString().slice(0, 8);
  const x = document.createElement("span"); x.textContent = text;
  li.append(t, x);
  feed.querySelectorAll("li.now").forEach(e => e.classList.remove("now"));
  if (runner.running && !note) li.classList.add("now");
  feed.appendChild(li);
  while (feed.children.length > 300) feed.firstChild.remove();
  feed.scrollTop = feed.scrollHeight;
}
function setRunning(r) {
  $("#runPill").dataset.run = r ? "1" : "0";
  $("#runText").textContent = r ? "Program running" : "No program running";
  $("#stopBtn").disabled = !r;
  $("#runBtn").textContent = r ? "Restart" : "Run project";
  if (!r) { document.querySelectorAll("#feed li.now").forEach(e => e.classList.remove("now")); highlight([]); }
}

// ------------------------------------------------------------------ mat drawing and robot dragging
const cv = $("#mat"), ctx = cv.getContext("2d");
let scale = 5;
function setMat(key) { world.setMat(key); $("#matSel").value = key; $("#matHint").textContent = MATS[key].hint; resize(); }
for (const [k, v] of Object.entries(MATS)) $("#matSel").add(new Option(v.name, k));
$("#matSel").onchange = e => { runner.stop(); setMat(e.target.value); };
function resize() {
  const w = cv.clientWidth || 800, dpr = window.devicePixelRatio || 1;
  scale = w / world.mat.w; const h = world.mat.h * scale;
  cv.style.height = h + "px"; cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}
window.addEventListener("resize", resize);
const X = x => x * scale, Y = y => (world.mat.h - y) * scale;
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n);
const portOf = type => Object.entries(world.config).find(([, d]) => d.type === type)?.[0];

function draw() {
  const mat = world.mat;
  ctx.clearRect(0, 0, cv.width, cv.height);
  ctx.fillStyle = css("--mat"); ctx.fillRect(0, 0, X(mat.w), mat.h * scale);
  ctx.strokeStyle = css("--grid"); ctx.lineWidth = 1;
  for (let x = 10; x < mat.w; x += 10) { ctx.beginPath(); ctx.moveTo(X(x), 0); ctx.lineTo(X(x), Y(0)); ctx.stroke(); }
  for (let y = 10; y < mat.h; y += 10) { ctx.beginPath(); ctx.moveTo(0, Y(y)); ctx.lineTo(X(mat.w), Y(y)); ctx.stroke(); }
  for (const s of mat.shapes) {
    if (s.kind === "rect") { ctx.fillStyle = COLORS[s.color]; ctx.fillRect(X(s.x), Y(s.y + s.h), s.w * scale, s.h * scale); }
    else if (s.kind === "line") {
      ctx.strokeStyle = COLORS[s.color]; ctx.lineWidth = s.width * scale; ctx.lineCap = ctx.lineJoin = "round";
      ctx.beginPath(); s.points.forEach(([x, y], i) => i ? ctx.lineTo(X(x), Y(y)) : ctx.moveTo(X(x), Y(y))); ctx.stroke();
    } else if (s.kind === "wall") { ctx.fillStyle = css("--wall"); ctx.fillRect(X(s.x), Y(s.y + s.h), s.w * scale, s.h * scale); }
  }
  const st = mat.start; ctx.strokeStyle = "#9aa1a6"; ctx.setLineDash([4, 4]); ctx.lineWidth = 1.5;
  ctx.beginPath(); ctx.arc(X(st.x), Y(st.y), 9 * scale, 0, 7); ctx.stroke(); ctx.setLineDash([]);
  if (world.trail.length > 1) {
    ctx.strokeStyle = "rgba(255,170,0,.85)"; ctx.lineWidth = 2; ctx.beginPath();
    world.trail.forEach(([x, y], i) => i ? ctx.lineTo(X(x), Y(y)) : ctx.moveTo(X(x), Y(y))); ctx.stroke();
  }
  drawRobot();
}
function drawRobot() {
  const a = world.heading * Math.PI / 180;
  if (portOf("distance")) {
    const d = world.distanceMm(), sx = world.x + 10 * Math.cos(a), sy = world.y + 10 * Math.sin(a), len = d > 0 ? d / 10 : 60;
    ctx.strokeStyle = d > 0 ? "rgba(31,157,107,.8)" : "rgba(120,120,120,.35)"; ctx.setLineDash([5, 4]); ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.moveTo(X(sx), Y(sy)); ctx.lineTo(X(sx + len * Math.cos(a)), Y(sy + len * Math.sin(a))); ctx.stroke(); ctx.setLineDash([]);
  }
  ctx.save(); ctx.translate(X(world.x), Y(world.y)); ctx.rotate(-a); ctx.scale(scale, scale);
  ctx.fillStyle = "#2b2f33"; ctx.fillRect(-2.8, -8.6, 5.6, 2.2); ctx.fillRect(-2.8, 6.4, 5.6, 2.2);
  ctx.fillStyle = "#f4f4f1"; ctx.strokeStyle = "#8b9196"; ctx.lineWidth = .35; rr(-8, -6.3, 18, 12.6, 1.6); ctx.fill(); ctx.stroke();
  ctx.fillStyle = "#ffd21a"; rr(-6.5, -4.6, 9.5, 9.2, 1.2); ctx.fill();
  ctx.fillStyle = "#23272b"; rr(-5.9, -4, 8.3, 8, 1); ctx.fill();
  for (let i = 0; i < 25; i++) {
    const v = world.pixels[i] / 100;
    ctx.fillStyle = v > 0 ? `rgba(255,246,216,${0.25 + 0.75 * v})` : "#3a4046";
    ctx.fillRect(1.3 - Math.floor(i / 5) * 1.45, -3.1 + (i % 5) * 1.3, 1.05, 1.0);
  }
  if (portOf("color")) {
    const c = COLOR_BY_ID[world.colorReading()[0]] || "white";
    ctx.fillStyle = "#2b2f33"; ctx.beginPath(); ctx.arc(8, 0, 1.6, 0, 7); ctx.fill();
    ctx.fillStyle = COLORS[c]; ctx.beginPath(); ctx.arc(8, 0, 1, 0, 7); ctx.fill();
  }
  if (portOf("distance")) { ctx.fillStyle = "#2b2f33"; rr(9.2, -3, 1.6, 6, .6); ctx.fill(); }
  if (portOf("force")) { ctx.fillStyle = world.forceValue()[1] ? "#1f9d6b" : "#8b9196"; rr(10.6, -1, 1, 2, .3); ctx.fill(); }
  ctx.restore();
}
function rr(x, y, w, h, r) { ctx.beginPath(); ctx.roundRect ? ctx.roundRect(x, y, w, h, r) : ctx.rect(x, y, w, h); }

let drag = null;
const toWorld = e => { const b = cv.getBoundingClientRect(); return { x: (e.clientX - b.left) / scale, y: world.mat.h - (e.clientY - b.top) / scale }; };
cv.addEventListener("pointerdown", e => {
  const p = toWorld(e);
  if (Math.hypot(p.x - world.x, p.y - world.y) < 12) { drag = { dx: world.x - p.x, dy: world.y - p.y }; cv.setPointerCapture(e.pointerId); }
});
cv.addEventListener("pointermove", e => { if (!drag) return; const p = toWorld(e); world.x = p.x + drag.dx; world.y = p.y + drag.dy; world.trail = [[world.x, world.y]]; });
cv.addEventListener("pointerup", () => { drag = null; });
cv.addEventListener("wheel", e => {
  const p = toWorld(e);
  if (Math.hypot(p.x - world.x, p.y - world.y) < 15) { e.preventDefault(); world.heading += e.deltaY > 0 ? -5 : 5; }
}, { passive: false });
$("#rotL").onclick = () => { world.heading += 15; };
$("#rotR").onclick = () => { world.heading -= 15; };
$("#resetBtn").onclick = () => world.resetRobot();
$("#trailBtn").onclick = () => { world.trail = [[world.x, world.y]]; };

// ------------------------------------------------------------------ hub face, buttons and ports
const mx = $("#matrix"); for (let i = 0; i < 25; i++) mx.appendChild(document.createElement("i"));
function hold(el, down, up) {
  el.addEventListener("pointerdown", e => { el.classList.add("down"); el.setPointerCapture(e.pointerId); down(); });
  const u = () => { if (el.classList.contains("down")) { el.classList.remove("down"); up(); } };
  el.addEventListener("pointerup", u); el.addEventListener("pointercancel", u);
}
for (const [id, side] of [["#btnL", "left"], ["#btnR", "right"]])
  hold($(id), () => { world.buttons[side] = true; world.buttonSince[side] = now(); }, () => { world.buttons[side] = false; });

const DEVICES = [["", "Empty"], ["motor:medium", "Motor (medium)"], ["motor:large", "Motor (large)"], ["color", "Color sensor"], ["distance", "Distance sensor"], ["force", "Force sensor"]];
const ROLES = [["left", "left wheel"], ["right", "right wheel"], ["arm", "other"]];
let builtVersion = -1;
function buildPorts() {
  const box = $("#ports"); box.textContent = "";
  for (const p of PORTS) {
    const d = world.config[p] || {};
    const el = document.createElement("div"); el.className = "port";
    const top = document.createElement("div"); top.className = "top";
    const letter = document.createElement("span"); letter.className = "letter"; letter.textContent = p;
    const sel = document.createElement("select"); sel.id = "dev" + p; sel.setAttribute("aria-label", "Device on port " + p);
    DEVICES.forEach(([v, t]) => sel.add(new Option(t, v)));
    sel.value = d.type === "motor" ? "motor:" + (d.model || "medium") : (d.type || "");
    sel.onchange = () => {
      const [type, model] = sel.value.split(":"), cfg = structuredClone(world.config);
      cfg[p] = type ? { type, ...(model ? { model, role: cfg[p]?.role || "arm" } : {}) } : {};
      world.applyConfig(cfg);
    };
    top.append(letter, sel); el.appendChild(top);
    if (d.type === "motor") {
      const rs = document.createElement("select"); rs.id = "role" + p; rs.setAttribute("aria-label", "Role of motor " + p);
      ROLES.forEach(([v, t]) => rs.add(new Option(t, v))); rs.value = d.role || "arm";
      rs.onchange = () => { world.config[p].role = rs.value; world.applyConfig(world.config); };
      el.appendChild(rs);
    }
    const val = document.createElement("div"); val.className = "val"; val.id = "val" + p; el.appendChild(val);
    if (d.type === "force") {
      const b = document.createElement("button"); b.className = "btn small"; b.textContent = "Hold to press";
      hold(b, () => { world.forceManual = true; }, () => { world.forceManual = false; }); el.appendChild(b);
    }
    box.appendChild(el);
  }
  builtVersion = world.configVersion;
}
$("#cfgReset").onclick = () => world.applyConfig(defaultConfig());
function portValues() {
  for (const p of PORTS) {
    const el = $("#val" + p); if (!el) continue;
    const d = world.config[p] || {};
    if (d.type === "motor" && world.motors[p]) { const m = world.motors[p]; el.textContent = `${m.relative()}°  ${Math.round(m.vel)}°/s`; }
    else if (d.type === "color") {
      const [cid, , refl] = world.colorReading(), name = COLOR_NAMES[cid] || "none";
      el.innerHTML = `<span class="swatch" style="background:${COLORS[COLOR_BY_ID[cid]] || "transparent"}"></span>${name} · ${refl}%`;
    } else if (d.type === "distance") { const mm = world.distanceMm(); el.textContent = mm < 0 ? "nothing in range" : `${(mm / 10).toFixed(1)} cm`; }
    else if (d.type === "force") el.textContent = world.forceValue()[1] ? "pressed" : "released";
    else el.textContent = "–";
  }
}

// ------------------------------------------------------------------ sound
$("#soundBtn").onclick = () => {
  if (audio) { audio.close(); audio = null; } else audio = new AudioContext();
  $("#soundBtn").textContent = audio ? "Sound on" : "Sound off"; $("#soundBtn").setAttribute("aria-pressed", String(!!audio));
};
function playBeep(ev) {
  if (!audio) return;
  const o = audio.createOscillator(), g = audio.createGain();
  o.frequency.value = ev.freq; g.gain.value = 0.15 * (ev.volume / 100);
  o.connect(g).connect(audio.destination); o.start(); o.stop(audio.currentTime + ev.duration / 1000);
}

// ------------------------------------------------------------------ main loop: physics at 100 Hz, blocks every 10 ms
const DT = 0.01;
let last = now(), acc = 0;
function simulate() {
  const t = now();
  acc += Math.min(0.25, t - last); last = t;
  while (acc >= DT) { world.step(DT, now()); runner.tick(); acc -= DT; }
}
setInterval(simulate, 10);   // keeps going when the tab is in the background (browsers slow it down there)

function frame() {
  simulate();
  for (const ev of world.events.splice(0)) {
    if (ev.type === "beep") playBeep(ev);
    else if (ev.type === "notice") addAction(ev.text, true);
  }
  if (world.configVersion !== builtVersion) buildPorts();
  world.pixels.forEach((v, i) => { mx.children[i].style.background = v > 0 ? `color-mix(in srgb, var(--led-on) ${30 + v * 0.7}%, var(--led-off))` : ""; });
  const lc = COLORS[world.powerLight] || "#fff";
  $("#centerLight").style.borderColor = lc; $("#centerLight").style.boxShadow = `0 0 12px 2px ${lc}`;
  $("#yaw").textContent = `${Math.round(-world.yaw())}°`;
  $("#readout").textContent = `x ${world.x.toFixed(1)} cm   y ${world.y.toFixed(1)} cm   heading ${(((world.heading % 360) + 360) % 360).toFixed(0)}°`;
  portValues();
  highlight(runner.running ? runner.active : []);
  draw();
  requestAnimationFrame(frame);
}

setMat("colors");
showProject(exampleProject());
buildPorts();
requestAnimationFrame(frame);
