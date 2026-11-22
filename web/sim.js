// Robot simulator: the browser port of spikehub/world.py and the hub API in spikehub/runtime.py.
// World units are centimetres and degrees; y points up; heading 90 faces the top of the mat.

export const PORTS = "ABCDEF";
export const WHEEL_DIAMETER = 5.6;
const AXLE_TRACK = 11.2;
const ROBOT_RADIUS = 9.0;
const SENSOR_OFFSET = { color: [8, 0], distance: [10, 0], force: [11, 0] };
export const MOTOR_MAX = { medium: 1110, large: 1050, small: 660 };
export const COAST = 0, BRAKE = 1, HOLD = 2, CONTINUE = 3, SMART_COAST = 4, SMART_BRAKE = 5;

export const COLOR_IDS = { black: 0, magenta: 1, purple: 2, blue: 3, azure: 4, turquoise: 5, green: 6,
  yellow: 7, orange: 8, red: 9, white: 10 };
export const COLOR_BY_ID = Object.fromEntries(Object.entries(COLOR_IDS).map(([k, v]) => [v, k]));
const SURFACE = {
  white: [[1000, 1000, 1000], 100], black: [[40, 40, 50], 6], red: [[900, 120, 110], 45],
  green: [[130, 620, 220], 30], blue: [[110, 260, 880], 28], yellow: [[980, 900, 160], 80],
  magenta: [[900, 150, 700], 50], azure: [[300, 700, 1000], 55], orange: [[1000, 450, 100], 60],
  purple: [[420, 150, 800], 25], turquoise: [[150, 850, 800], 50],
};

export const now = () => performance.now() / 1000;

export function defaultConfig() {
  return {
    A: { type: "motor", model: "medium", role: "left" },
    B: { type: "motor", model: "medium", role: "right" },
    C: { type: "color" }, D: { type: "distance" }, E: { type: "force" },
    F: { type: "motor", model: "medium", role: "arm" },
  };
}

// ------------------------------------------------------------------ mats
const border = (w, h, t = 2) => [
  { kind: "wall", x: -t, y: -t, w: w + 2 * t, h: t }, { kind: "wall", x: -t, y: h, w: w + 2 * t, h: t },
  { kind: "wall", x: -t, y: 0, w: t, h }, { kind: "wall", x: w, y: 0, w: t, h }];
const oval = (cx, cy, rx, ry, n = 48) => Array.from({ length: n + 1 }, (_, i) =>
  [cx + rx * Math.cos(2 * Math.PI * i / n), cy + ry * Math.sin(2 * Math.PI * i / n)]);
function smooth(points, rounds = 3) {
  for (let r = 0; r < rounds; r++) {
    const out = [points[0]];
    for (let i = 0; i < points.length - 1; i++) {
      const [ax, ay] = points[i], [bx, by] = points[i + 1];
      out.push([ax * .75 + bx * .25, ay * .75 + by * .25], [ax * .25 + bx * .75, ay * .25 + by * .75]);
    }
    out.push(points[points.length - 1]);
    points = out;
  }
  return points;
}

export const MATS = {
  playground: {
    name: "Playground", w: 200, h: 120, start: { x: 25, y: 20, heading: 90 },
    hint: "Drive to the colored squares, follow the black loop, stop before the wall.",
    shapes: [
      { kind: "line", color: "black", width: 2.5, points: oval(120, 62, 52, 34) },
      { kind: "rect", color: "red", x: 8, y: 90, w: 22, h: 22 },
      { kind: "rect", color: "blue", x: 40, y: 90, w: 22, h: 22 },
      { kind: "rect", color: "green", x: 8, y: 58, w: 22, h: 22 },
      { kind: "rect", color: "yellow", x: 40, y: 58, w: 22, h: 22 },
      { kind: "wall", x: 183, y: 20, w: 6, h: 80 },
    ],
  },
  line: {
    name: "Line track", w: 200, h: 120, start: { x: 100, y: 22, heading: 0 },
    hint: "Follow the black line with the color sensor. Stop on the red square.",
    shapes: [
      { kind: "line", color: "black", width: 2.5, points: smooth([[100, 20], [160, 20], [180, 35], [180, 60],
        [150, 75], [150, 95], [120, 102], [80, 102], [50, 95], [50, 75], [20, 60], [20, 35], [40, 20], [80, 20]]) },
      { kind: "rect", color: "red", x: 78, y: 13, w: 8, h: 14 },
    ],
  },
  maze: {
    name: "Maze", w: 160, h: 120, start: { x: 20, y: 18, heading: 90 },
    hint: "Use the distance sensor to find a way to the green square.",
    shapes: [
      { kind: "rect", color: "green", x: 128, y: 92, w: 24, h: 22 },
      { kind: "wall", x: 40, y: 0, w: 5, h: 80 }, { kind: "wall", x: 80, y: 40, w: 5, h: 80 },
      { kind: "wall", x: 120, y: 0, w: 5, h: 80 },
    ],
  },
  colors: {
    name: "Color stripes", w: 200, h: 120, start: { x: 20, y: 60, heading: 0 },
    hint: "A row of colored stripes to drive across: good for 'if color is …' programs.",
    shapes: ["green", "yellow", "red", "blue", "magenta", "black"].map((c, i) =>
      ({ kind: "rect", color: c, x: 45 + i * 24, y: 10, w: 14, h: 100 })),
  },
};

const inRect = (px, py, r) => r.x <= px && px <= r.x + r.w && r.y <= py && py <= r.y + r.h;
function distSeg(px, py, ax, ay, bx, by) {
  const dx = bx - ax, dy = by - ay, L = dx * dx + dy * dy;
  const t = L === 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / L));
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}
function circleHitsRect(cx, cy, rad, r) {
  const nx = Math.max(r.x, Math.min(cx, r.x + r.w)), ny = Math.max(r.y, Math.min(cy, r.y + r.h));
  return Math.hypot(cx - nx, cy - ny) < rad;
}
function rayRect(ox, oy, dx, dy, r) {
  let tmin = -Infinity, tmax = Infinity;
  for (const [o, d, lo, hi] of [[ox, dx, r.x, r.x + r.w], [oy, dy, r.y, r.y + r.h]]) {
    if (Math.abs(d) < 1e-9) { if (o < lo || o > hi) return null; }
    else { const t1 = (lo - o) / d, t2 = (hi - o) / d; tmin = Math.max(tmin, Math.min(t1, t2)); tmax = Math.min(tmax, Math.max(t1, t2)); }
  }
  if (tmax < Math.max(tmin, 0)) return null;
  return Math.max(tmin, 0);
}

// ------------------------------------------------------------------ motors
export class Motor {
  constructor(model = "medium") {
    this.model = model; this.pos = 0; this.offset = 0; this.vel = 0;
    this.cmd = ["stop", BRAKE]; this.accel = 1000; this.decel = 1000;
  }
  get vmax() { return MOTOR_MAX[this.model] || 1110; }
  targetVelocity(t) {
    const [k] = this.cmd;
    if (k === "run" || k === "deg") return this.cmd[1];
    if (k === "time") return t < this.cmd[2] ? this.cmd[1] : 0;
    if (k === "duty") return this.cmd[1] / 10000 * this.vmax;
    return 0;
  }
  step(dt, t) {
    const k = this.cmd[0];
    const tv = Math.max(-this.vmax, Math.min(this.vmax, this.targetVelocity(t)));
    let rate;
    if (k === "stop") rate = (this.cmd[1] === COAST || this.cmd[1] === SMART_COAST) ? 2500 : 20000;
    else rate = Math.abs(tv) > Math.abs(this.vel) ? this.accel : this.decel;
    this.vel += Math.max(-rate * dt, Math.min(rate * dt, tv - this.vel));
    const move = this.vel * dt;
    if (k === "deg") {
      const [, , start, target, stop] = this.cmd;
      if (Math.abs(this.pos - start) + Math.abs(move) >= Math.abs(target)) {
        this.pos = start + Math.sign(target) * Math.abs(target);
        this.finish(stop);
        return;
      }
    }
    this.pos += move;
    if (k === "time" && t >= this.cmd[2]) this.finish(this.cmd[3]);
  }
  finish(stop) {
    if (stop === CONTINUE) this.cmd = ["run", this.vel];
    else { this.cmd = ["stop", stop]; if (stop !== COAST && stop !== SMART_COAST) this.vel = 0; }
  }
  relative() { return Math.round(this.pos - this.offset); }
  absolute() { let a = ((Math.round(this.pos) % 360) + 360) % 360; return a >= 180 ? a - 360 : a; }
  power() { return Math.round(Math.max(-10000, Math.min(10000, this.vel / this.vmax * 10000))); }
}

// ------------------------------------------------------------------ world
export class World {
  constructor(mat = "playground") {
    this.config = defaultConfig(); this.motors = {}; this.pairs = {};
    this.pixels = new Array(25).fill(0); this.scroll = null; this.powerLight = "white";
    this.buttons = { left: false, right: false }; this.buttonSince = { left: 0, right: 0 };
    this.forceManual = false; this.yawOffset = 0; this.trail = []; this.events = [];
    this.configVersion = 0;
    this.setMat(mat); this.applyConfig(this.config);
  }
  setMat(key) {
    this.matKey = MATS[key] ? key : "playground";
    this.mat = MATS[this.matKey];
    this.walls = this.mat.shapes.filter(s => s.kind === "wall").concat(border(this.mat.w, this.mat.h));
    this.resetRobot();
  }
  resetRobot() {
    const s = this.mat.start;
    this.x = s.x; this.y = s.y; this.heading = s.heading; this.yawOffset = this.heading;
    this.trail = [[this.x, this.y]];
  }
  applyConfig(cfg) {
    this.config = cfg;
    const old = this.motors; this.motors = {};
    for (const [p, d] of Object.entries(cfg)) {
      if (d.type === "motor") { const m = old[p] || new Motor(d.model); m.model = d.model || "medium"; this.motors[p] = m; }
    }
    this.configVersion++;
  }
  driveports() {
    let left = null, right = null;
    for (const [p, d] of Object.entries(this.config)) {
      if (d.type === "motor" && d.role === "left") left = p;
      if (d.type === "motor" && d.role === "right") right = p;
    }
    return [left, right];
  }
  setDrivePorts(left, right) {
    for (const d of Object.values(this.config)) if (d.type === "motor" && (d.role === "left" || d.role === "right")) d.role = "arm";
    if (this.config[left]?.type === "motor") this.config[left].role = "left";
    if (this.config[right]?.type === "motor") this.config[right].role = "right";
    this.configVersion++;
  }
  deviceAt(p) { return this.config[p]?.type; }
  // Make the robot match the program: put a `kind` device on `port`.
  ensureDevice(port, kind, avoid = []) {
    if (this.deviceAt(port) === kind) return;
    const cands = [...PORTS].filter(p => p !== port && !avoid.includes(p) && this.deviceAt(p) === kind);
    const source = cands.find(p => !["left", "right"].includes(this.config[p].role)) || cands[0] || null;
    const moved = { ...(this.config[port] || {}) };
    let fresh;
    if (source) {
      fresh = { ...this.config[source] };
      this.config[source] = moved.type ? moved : {};
      const atPort = this.motors[port], atSource = this.motors[source];
      delete this.motors[port]; delete this.motors[source];
      if (atSource) this.motors[port] = atSource;
      if (atPort) this.motors[source] = atPort;
    } else {
      fresh = { type: kind, ...(kind === "motor" ? { model: "medium", role: "arm" } : {}) };
      if (moved.type) { const free = [...PORTS].find(p => !this.deviceAt(p) && !avoid.includes(p)); if (free) this.config[free] = moved; }
    }
    this.config[port] = fresh;
    this.applyConfig(this.config);
    this.events.push({ type: "notice", text: `Moved the ${kind} to port ${port} to match the program` });
  }
  programReset() {
    for (const m of Object.values(this.motors)) { m.cmd = ["stop", BRAKE]; m.vel = 0; m.accel = m.decel = 1000; }
    this.pairs = {}; this.pixels = new Array(25).fill(0); this.scroll = null; this.powerLight = "white";
    this.yawOffset = this.heading;
  }
  programStop() {
    for (const m of Object.values(this.motors)) m.cmd = ["stop", COAST];
    this.scroll = null;
  }
  step(dt, t) {
    for (const m of Object.values(this.motors)) m.step(dt, t);
    const [left, right] = this.driveports();
    const k = Math.PI * WHEEL_DIAMETER / 360;
    const vl = this.motors[left] ? -this.motors[left].vel * k : 0;   // left motor is mirrored
    const vr = this.motors[right] ? this.motors[right].vel * k : 0;
    const v = (vl + vr) / 2, omega = (vr - vl) / AXLE_TRACK * 180 / Math.PI;
    const nh = this.heading + omega * dt, rad = nh * Math.PI / 180;
    const nx = this.x + v * Math.cos(rad) * dt, ny = this.y + v * Math.sin(rad) * dt;
    this.heading = nh;
    if (!this.walls.some(w => circleHitsRect(nx, ny, ROBOT_RADIUS, w))) {
      this.x = nx; this.y = ny;
      const [lx, ly] = this.trail[this.trail.length - 1];
      if (Math.hypot(nx - lx, ny - ly) > 0.8) { this.trail.push([nx, ny]); if (this.trail.length > 4000) this.trail.shift(); }
    }
    if (this.scroll) {
      const s = this.scroll, i = Math.floor((t - s.t0) * 1000 / s.ms);
      if (i >= s.frames.length) { this.pixels = new Array(25).fill(0); this.scroll = null; }
      else this.pixels = s.frames[i].map(b => b ? s.intensity : 0);
    }
  }
  sensorPoint(kind) {
    const [ox, oy] = SENSOR_OFFSET[kind], r = this.heading * Math.PI / 180;
    return [this.x + ox * Math.cos(r) - oy * Math.sin(r), this.y + ox * Math.sin(r) + oy * Math.cos(r)];
  }
  surfaceColor(dx = 0, dy = 0) {
    let [px, py] = this.sensorPoint("color"); px += dx; py += dy;
    if (!(0 <= px && px <= this.mat.w && 0 <= py && py <= this.mat.h)) return null;
    for (let i = this.mat.shapes.length - 1; i >= 0; i--) {
      const s = this.mat.shapes[i];
      if (s.kind === "rect" && inRect(px, py, s)) return s.color;
      if (s.kind === "line") {
        const pts = s.points;
        for (let j = 0; j < pts.length - 1; j++)
          if (distSeg(px, py, pts[j][0], pts[j][1], pts[j + 1][0], pts[j + 1][1]) <= s.width / 2) return s.color;
      }
    }
    return "white";
  }
  colorReading() {
    const c = this.surfaceColor();
    if (c === null) return [-1, [0, 0, 0], 0];
    const spot = [[0, 0]].concat(Array.from({ length: 8 }, (_, a) => [0.9 * Math.cos(a * Math.PI / 4), 0.9 * Math.sin(a * Math.PI / 4)]));
    let r = 0, g = 0, b = 0, f = 0;
    for (const [dx, dy] of spot) {
      const [[rr, gg, bb], ff] = SURFACE[this.surfaceColor(dx, dy) || "black"] || SURFACE.white;
      r += rr; g += gg; b += bb; f += ff;
    }
    const n = spot.length;
    return [COLOR_IDS[c] ?? -1, [Math.floor(r / n), Math.floor(g / n), Math.floor(b / n)], Math.round(f / n)];
  }
  distanceMm() {
    const [ox, oy] = this.sensorPoint("distance"), r = this.heading * Math.PI / 180;
    let best = null;
    for (const w of this.walls) { const t = rayRect(ox, oy, Math.cos(r), Math.sin(r), w); if (t !== null && (best === null || t < best)) best = t; }
    if (best === null || best * 10 > 2000) return -1;
    return Math.max(40, Math.round(best * 10));
  }
  forceValue() {
    const [fx, fy] = this.sensorPoint("force");
    const pressed = this.walls.some(w => circleHitsRect(fx, fy, 1.5, w)) || this.forceManual;
    return [pressed ? 60 : 0, pressed];
  }
  yaw() { return ((this.heading - this.yawOffset + 180) % 360 + 360) % 360 - 180; }
}

// ------------------------------------------------------------------ 5x5 font for light_matrix.write
const FONT = {
  A: ".#.|#.#|###|#.#|#.#", B: "##.|#.#|##.|#.#|##.", C: ".##|#..|#..|#..|.##", D: "##.|#.#|#.#|#.#|##.",
  E: "###|#..|##.|#..|###", F: "###|#..|##.|#..|#..", G: ".##|#..|#.#|#.#|.##", H: "#.#|#.#|###|#.#|#.#",
  I: "###|.#.|.#.|.#.|###", J: "..#|..#|..#|#.#|.#.", K: "#.#|#.#|##.|#.#|#.#", L: "#..|#..|#..|#..|###",
  M: "#...#|##.##|#.#.#|#...#|#...#", N: "#..#|##.#|#.##|#..#|#..#", O: ".#.|#.#|#.#|#.#|.#.",
  P: "##.|#.#|##.|#..|#..", Q: ".#.|#.#|#.#|##.|.##", R: "##.|#.#|##.|#.#|#.#", S: ".##|#..|.#.|..#|##.",
  T: "###|.#.|.#.|.#.|.#.", U: "#.#|#.#|#.#|#.#|###", V: "#.#|#.#|#.#|#.#|.#.",
  W: "#...#|#...#|#.#.#|##.##|#...#", X: "#.#|#.#|.#.|#.#|#.#", Y: "#.#|#.#|.#.|.#.|.#.", Z: "###|..#|.#.|#..|###",
  0: ".#.|#.#|#.#|#.#|.#.", 1: ".#.|##.|.#.|.#.|###", 2: "##.|..#|.#.|#..|###", 3: "##.|..#|.#.|..#|##.",
  4: "#.#|#.#|###|..#|..#", 5: "###|#..|##.|..#|##.", 6: ".##|#..|###|#.#|###", 7: "###|..#|.#.|.#.|.#.",
  8: "###|#.#|###|#.#|###", 9: "###|#.#|###|..#|##.", " ": "..|..|..|..|..", ".": ".|.|.|.|#",
  ",": "..|..|..|.#|#.", "!": "#|#|#|.|#", "?": "##.|..#|.#.|...|.#.", "-": "...|...|###|...|...",
  "+": "...|.#.|###|.#.|...", ":": ".|#|.|#|.", "'": "#|#|.|.|.", "=": "...|###|...|###|...",
};
function glyphCols(ch) {
  const rows = (FONT[ch.toUpperCase()] || FONT["?"]).split("|");
  return Array.from({ length: rows[0].length }, (_, c) => rows.map(r => r[c] === "#" ? 1 : 0));
}
const colsToFrame = cols => Array.from({ length: 25 }, (_, i) => cols[i % 5][Math.floor(i / 5)]);
function textFrames(text, msPerChar) {
  const blank = [0, 0, 0, 0, 0];
  if (text.length === 1) {
    const g = glyphCols(text), pad = 5 - g.length, l = Math.floor(pad / 2);
    return [[colsToFrame([...Array(l).fill(blank), ...g, ...Array(pad - l).fill(blank)])], null];
  }
  let cols = Array(5).fill(blank);
  for (const ch of text) cols = cols.concat(glyphCols(ch), [blank]);
  cols = cols.concat(Array(5).fill(blank));
  const frames = [];
  for (let i = 0; i + 5 <= cols.length; i++) frames.push(colsToFrame(cols.slice(i, i + 5)));
  return [frames, Math.max(20, msPerChar / 4)];
}

// ------------------------------------------------------------------ hub API used by programs
export class Hub {
  constructor(world) { this.world = world; }
  _letter(p) { if (typeof p === "string") return p.toUpperCase(); if (p < 0 || p > 5) throw new Error("invalid port"); return PORTS[p]; }
  _motor(p) {
    const l = this._letter(p);
    if (!this.world.motors[l]) this.world.ensureDevice(l, "motor");
    return this.world.motors[l];
  }
  _sensor(p, kind) { const l = this._letter(p); if (this.world.deviceAt(l) !== kind) this.world.ensureDevice(l, kind); return l; }
  _untilReplaced(m, cmd) { return { done: () => m.cmd !== cmd }; }
  _set(m, cmd, a, d) { if (a) m.accel = a; if (d) m.decel = d; m.cmd = cmd; return cmd; }

  // motor
  run(p, v) { this._set(this._motor(p), ["run", v]); }
  stop(p, stop = BRAKE) { this._motor(p).cmd = ["stop", stop]; }
  runForDegrees(p, deg, v, stop = BRAKE) {
    const m = this._motor(p);
    if (!deg || !v) return { done: () => true };
    const sign = Math.sign(deg) * Math.sign(v);
    return this._untilReplaced(m, this._set(m, ["deg", Math.abs(v) * sign, m.pos, Math.abs(deg) * sign, stop]));
  }
  runForTime(p, ms, v, stop = BRAKE) {
    const m = this._motor(p);
    return this._untilReplaced(m, this._set(m, ["time", v, performance.now() / 1000 + ms / 1000, stop]));
  }
  runToAbsolute(p, pos, v, direction = 2, stop = BRAKE) {
    const m = this._motor(p);
    let diff = (((pos - m.absolute()) % 360) + 360) % 360;
    if (direction === 1) diff = diff ? diff - 360 : 0;
    else if (direction !== 0) { const short = diff > 180 ? diff - 360 : diff; diff = direction === 2 ? short : (short > 0 ? short - 360 : short + 360); }
    if (!diff) { m.cmd = ["stop", stop]; return { done: () => true }; }
    return this._untilReplaced(m, this._set(m, ["deg", Math.sign(diff) * Math.abs(v), m.pos, diff, stop]));
  }
  resetRelative(p, pos = 0) { const m = this._motor(p); m.offset = m.pos - pos; }
  setDuty(p, pwm) { this._motor(p).cmd = ["duty", pwm]; }
  absolutePosition(p) { return this._motor(p).absolute(); }
  relativePosition(p) { return this._motor(p).relative(); }
  velocity(p) { return Math.round(this._motor(p).vel); }
  vmax(p) { return this._motor(p).vmax; }

  // motor pair (pair 0)
  pair(left, right) {
    const l = this._letter(left), r = this._letter(right);
    if (this.world.deviceAt(l) !== "motor") this.world.ensureDevice(l, "motor", [r]);
    if (this.world.deviceAt(r) !== "motor") this.world.ensureDevice(r, "motor", [l]);
    this.world.pairs[0] = [l, r];
    this.world.setDrivePorts(l, r);
  }
  _pair() {
    const p = this.world.pairs[0];
    if (!p) throw new Error("the movement motors are not set");
    return [this._motor(p[0]), this._motor(p[1])];
  }
  _pairGo(lv, rv, mk) {
    const [ml, mr] = this._pair();
    const cl = this._set(ml, mk(-lv, ml)), cr = this._set(mr, mk(rv, mr));   // left motor is mirrored
    return { done: () => ml.cmd !== cl && mr.cmd !== cr };
  }
  static steer(vel, s) {
    s = Math.max(-100, Math.min(100, s));
    return s >= 0 ? [vel, vel * (1 - s / 50)] : [vel * (1 + s / 50), vel];
  }
  move(steering, v) { const [lv, rv] = Hub.steer(v, steering); this._pairGo(lv, rv, w => ["run", w]); }
  moveTank(lv, rv) { this._pairGo(lv, rv, w => ["run", w]); }
  _degCmd(deg, vmax, stop) {
    return (w, m) => w === 0 ? ["stop", stop] : ["deg", w, m.pos, Math.sign(w) * Math.abs(deg) * Math.abs(w) / vmax, stop];
  }
  moveForDegrees(deg, steering, v, stop = BRAKE) {
    let [lv, rv] = Hub.steer(v, steering);
    if (deg < 0) { lv = -lv; rv = -rv; }
    const vmax = Math.max(Math.abs(lv), Math.abs(rv));
    if (!deg || !vmax) return { done: () => true };
    return this._pairGo(lv, rv, this._degCmd(deg, vmax, stop));
  }
  moveTankForDegrees(deg, lv, rv, stop = BRAKE) {
    if (deg < 0) { lv = -lv; rv = -rv; }
    const vmax = Math.max(Math.abs(lv), Math.abs(rv));
    if (!deg || !vmax) return { done: () => true };
    return this._pairGo(lv, rv, this._degCmd(deg, vmax, stop));
  }
  _timeCmd(ms, stop) { const end = performance.now() / 1000 + ms / 1000; return w => ["time", w, end, stop]; }
  moveForTime(ms, steering, v, stop = BRAKE) { const [lv, rv] = Hub.steer(v, steering); return this._pairGo(lv, rv, this._timeCmd(ms, stop)); }
  moveTankForTime(lv, rv, ms, stop = BRAKE) { return this._pairGo(lv, rv, this._timeCmd(ms, stop)); }
  pairStop(stop = BRAKE) { const [ml, mr] = this._pair(); ml.cmd = ["stop", stop]; mr.cmd = ["stop", stop]; }

  // sensors
  color(p) { this._sensor(p, "color"); return this.world.colorReading()[0]; }
  reflection(p) { this._sensor(p, "color"); return this.world.colorReading()[2]; }
  distance(p) { this._sensor(p, "distance"); return this.world.distanceMm(); }
  force(p) { this._sensor(p, "force"); return this.world.forceValue()[0]; }
  pressed(p) { this._sensor(p, "force"); return this.world.forceValue()[1]; }
  yawDecidegrees() { return Math.round(this.world.yaw() * 10); }
  resetYaw(angle = 0) { this.world.yawOffset = this.world.heading - angle / 10; }
  button(which) { return this.world.buttons[which]; }

  // light and sound
  write(text, intensity = 100, msPerChar = 500) {
    const [frames, perFrame] = textFrames(String(text), msPerChar);
    if (perFrame === null) {
      this.world.scroll = null; this.world.pixels = frames[0].map(b => b ? intensity : 0);
      const end = performance.now() + msPerChar; return { done: () => performance.now() >= end };
    }
    const s = { frames, ms: perFrame, t0: performance.now() / 1000, intensity };
    this.world.scroll = s;
    return { done: () => this.world.scroll !== s };
  }
  show(pixels) { this.world.scroll = null; this.world.pixels = pixels.slice(0, 25).map(p => Math.max(0, Math.min(100, p | 0))); }
  setPixel(x, y, b = 100) { this.world.scroll = null; if (x >= 0 && x < 5 && y >= 0 && y < 5) this.world.pixels[y * 5 + x] = Math.max(0, Math.min(100, b | 0)); }
  clear() { this.world.scroll = null; this.world.pixels = new Array(25).fill(0); }
  light(colorId) { this.world.powerLight = COLOR_BY_ID[colorId] || "white"; }
  beep(freq = 440, ms = 500, volume = 100) {
    this.world.events.push({ type: "beep", freq, duration: ms, volume });
    const end = performance.now() + ms; return { done: () => performance.now() >= end };
  }
}
