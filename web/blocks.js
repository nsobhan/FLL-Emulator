// SPIKE App 3 project files (.llsp3) and a Word Blocks interpreter.
// Browser port of spikehub/blocks.py. Needs the JSZip global.
import { Hub, PORTS, WHEEL_DIAMETER, BRAKE, now } from "./sim.js?v=4";

const WHEEL_CIRCUMFERENCE_CM = Math.PI * WHEEL_DIAMETER;
export const COLOR_NAMES = { "-1": "no color", 0: "black", 1: "magenta", 2: "purple", 3: "blue", 4: "azure",
  5: "turquoise", 6: "green", 7: "yellow", 8: "orange", 9: "red", 10: "white" };
const DIRECTION_WORDS = { clockwise: "↻ clockwise", counterclockwise: "↺ counterclockwise", forward: "↑ forward",
  back: "↓ back", backward: "↓ back", shortest: "shortest path" };
const BACKWARD = new Set(["back", "backward", "backwards", "rev", "reverse", "b"]);
const CW = new Set(["cw", "clock", "clockwise", "right"]);
const CCW = new Set(["ccw", "counter", "counterclockwise", "left"]);
const CATEGORY = [["flipperevents_", "events"], ["event_", "events"], ["flippermoremove_", "move"],
  ["flippermove_", "move"], ["flippermoremotor_", "motor"], ["flippermotor_", "motor"], ["flipperlight_", "light"],
  ["flippersound_", "sound"], ["flippermusic_", "sound"], ["flippersensors_", "sensors"],
  ["flippermoresensors_", "sensors"], ["flippercontrol_", "control"], ["control_", "control"],
  ["operator_", "operators"], ["data_", "variables"], ["procedures_", "myblocks"], ["argument_", "myblocks"]];
const category = op => (CATEGORY.find(([p]) => op.startsWith(p)) || [0, "other"])[1];
const C_BLOCKS = new Set(["control_forever", "control_repeat", "control_repeat_until", "control_if", "control_if_else"]);

export class ProjectError extends Error {}

// ------------------------------------------------------------------ reading files
export async function readProject(file) {
  let outer;
  try { outer = await JSZip.loadAsync(file); }
  catch { throw new ProjectError("This isn't a SPIKE project file. In the SPIKE app use File, then Save to your device, and pick the .llsp3 file."); }
  const manifest = outer.file("manifest.json") ? JSON.parse(await outer.file("manifest.json").async("string")) : {};
  const p = new Project(manifest.name || file.name);
  if (outer.file("projectbody.json")) {
    p.type = "python";
    p.python = JSON.parse(await outer.file("projectbody.json").async("string")).main || "";
    return p;
  }
  if (!outer.file("scratch.sb3")) throw new ProjectError("This project file has no program in it.");
  if (manifest.type === "icon-blocks") throw new ProjectError("Icon Block projects aren't supported yet. Word Block projects work.");
  const inner = await JSZip.loadAsync(await outer.file("scratch.sb3").async("arraybuffer"));
  const proj = JSON.parse(await inner.file("project.json").async("string"));
  p.type = "word-blocks";
  for (const t of proj.targets || []) {
    for (const [id, v] of Object.entries(t.variables || {})) p.variables[id] = { name: v[0], value: v[1] };
    for (const [id, l] of Object.entries(t.lists || {})) p.lists[id] = { name: l[0], value: [...l[1]] };
    for (const s of t.sounds || []) {
      const fn = s.md5ext || `${s.assetId}.${s.dataFormat || "wav"}`;
      const f = inner.file(fn);
      if (f) {
        const rate = s.rate || 44100;
        p.sounds[s.name] = { url: URL.createObjectURL(new Blob([await f.async("arraybuffer")], { type: "audio/wav" })),
          seconds: (s.sampleCount || rate) / rate };
      }
    }
    if (!t.isStage) for (const [id, b] of Object.entries(t.blocks || {})) if (b && typeof b === "object" && !Array.isArray(b)) p.blocks[id] = b;
  }
  return p;
}

export class Project {
  constructor(name) { this.name = name; this.type = ""; this.python = null; this.blocks = {}; this.variables = {}; this.lists = {}; this.sounds = {}; }
  get hats() {
    return Object.entries(this.blocks).filter(([, b]) => b.topLevel &&
      (/^(flipperevents_when|event_when)/.test(b.opcode) || b.opcode === "procedures_definition")).map(([id]) => id);
  }
  field(b, name) {
    const f = b.fields || {};
    const key = name ?? Object.keys(f)[0];
    return f[key] ? f[key][0] : null;
  }
  inputText(b, name) {
    const inp = (b.inputs || {})[name];
    if (!inp) return "?";
    const ref = inp[1];
    if (Array.isArray(ref)) return ref.length > 1 ? String(ref[1]) : "?";
    const blk = this.blocks[ref];
    if (!blk) return "?";
    if (isMenu(blk)) return menuText(blk.opcode, this.field(blk));
    return "(" + this.text(ref) + ")";
  }
  text(id) {
    const b = this.blocks[id], op = b.opcode;
    if (op === "procedures_call" || op === "procedures_definition") return procText(this, b);
    const tpl = TEXT[op];
    if (tpl === undefined) {
      const words = op.split("_").slice(1).join("_").replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase();
      return [words, ...Object.keys(b.inputs || {}).filter(k => !k.startsWith("SUBSTACK")).map(k => this.inputText(b, k))].join(" ");
    }
    return tpl.replace(/\{(@?[A-Z0-9_]+)\}/g, (_, key) => {
      if (key.startsWith("@")) {
        key = key.slice(1);
        const v = this.field(b, key);
        return ["VARIABLE", "LIST", "BROADCAST_OPTION"].includes(key) ? String(v) : menuText(key.toLowerCase(), v);
      }
      return this.inputText(b, key);
    });
  }
  tree(id) {
    const out = [];
    const hats = new Set(this.hats);
    while (id && this.blocks[id]) {
      const b = this.blocks[id], op = b.opcode;
      const node = { id, op, cat: category(op), text: this.text(id), hat: hats.has(id) };
      for (const [key, slot] of [["SUBSTACK", "body"], ["SUBSTACK2", "else"]]) {
        const inp = (b.inputs || {})[key];
        if (inp && typeof inp[1] === "string") node[slot] = this.tree(inp[1]);
        else if (key === "SUBSTACK" && C_BLOCKS.has(op)) node[slot] = [];
      }
      if (op === "control_if_else" && !node.else) node.else = [];
      out.push(node);
      id = b.next;
    }
    return out;
  }
  scripts() {
    return this.hats.sort((a, b) => (this.blocks[a].y || 0) - (this.blocks[b].y || 0) || (this.blocks[a].x || 0) - (this.blocks[b].x || 0))
      .map(h => this.tree(h));
  }
}

const isMenu = b => !Object.keys(b.inputs || {}).length && Object.keys(b.fields || {}).length === 1 &&
  (b.shadow ?? true) && !/^(data_|argument_)/.test(b.opcode);

function menuText(op, v) {
  if (v === null || v === undefined) return "?";
  const s = String(v);
  if (op.includes("color") && /^-?\d+$/.test(s)) return COLOR_NAMES[s] ?? s;
  if (s.startsWith("{")) { try { return JSON.parse(s).name || s; } catch { return s; } }
  if (op.includes("matrix") && /^[0-9]{25}$/.test(s)) return "▦";
  return DIRECTION_WORDS[s] || s;
}

function procText(p, b) {
  if (b.opcode === "procedures_definition") {
    const proto = p.blocks[(b.inputs?.custom_block || [])[1]] || {};
    return "define " + (proto.mutation?.proccode || "my block").replace(/%[snb]/g, "( )");
  }
  const m = b.mutation || {}, ids = JSON.parse(m.argumentids || "[]");
  let i = 0;
  return (m.proccode || "my block").replace(/%[snb]/g, () => p.inputText(b, ids[i++]));
}

const TEXT = {
  flipperevents_whenProgramStarts: "when program starts", flipperevents_whenColor: "when {PORT} is color {OPTION}",
  flipperevents_whenPressed: "when {PORT} is {@OPTION}", flipperevents_whenDistance: "when {PORT} is {@COMPARATOR} {VALUE} {@UNIT}",
  flipperevents_whenButton: "when {@BUTTON} button {@EVENT}", flipperevents_whenCondition: "when {CONDITION}",
  flipperevents_whenTimer: "when timer > {VALUE}", event_whenbroadcastreceived: "when I receive {@BROADCAST_OPTION}",
  event_broadcast: "broadcast {BROADCAST_INPUT}", event_broadcastandwait: "broadcast {BROADCAST_INPUT} and wait",
  flippermove_move: "move {DIRECTION} for {VALUE} {@UNIT}", flippermove_startMove: "start moving {DIRECTION}",
  flippermove_steer: "move steering {STEERING} for {VALUE} {@UNIT}", flippermove_startSteer: "start moving steering {STEERING}",
  flippermove_stopMove: "stop moving", flippermove_movementSpeed: "set movement speed to {SPEED} %",
  flippermove_setMovementPair: "set movement motors to {PAIR}", flippermove_setDistance: "set 1 motor rotation to {DISTANCE} {@UNIT}",
  flippermoremove_startDualSpeed: "start moving with {LEFT} % and {RIGHT} % speed",
  flippermoremove_moveDualSpeed: "move with {LEFT} % and {RIGHT} % speed for {VALUE} {@UNIT}",
  flippermoremove_startDualPower: "start moving with {LEFT} % and {RIGHT} % power",
  flippermotor_motorTurnForDirection: "{PORT} run {DIRECTION} for {VALUE} {@UNIT}",
  flippermotor_motorGoDirectionToPosition: "{PORT} go {@DIRECTION} to position {POSITION}",
  flippermotor_motorStartDirection: "{PORT} start motor {DIRECTION}", flippermotor_motorStop: "{PORT} stop motor",
  flippermotor_motorSetSpeed: "{PORT} set speed to {SPEED} %", flippermotor_absolutePosition: "{PORT} position",
  flippermotor_speed: "{PORT} speed", flippermoremotor_motorSetDegreeCounted: "{PORT} set relative position to {VALUE}",
  flippermoremotor_position: "{PORT} relative position", flippermoremotor_motorStartPower: "{PORT} start motor at {POWER} % power",
  flipperlight_lightDisplayText: "write {TEXT}", flipperlight_lightDisplayImageOn: "turn on {MATRIX}",
  flipperlight_lightDisplayImageOnForTime: "turn on {MATRIX} for {VALUE} seconds", flipperlight_lightDisplayOff: "turn off pixels",
  flipperlight_lightDisplaySetPixel: "set pixel {X} , {Y} to {BRIGHTNESS} %", flipperlight_centerButtonLight: "set Center Button light to {COLOR}",
  flippersound_playSoundUntilDone: "play sound {SOUND} until done", flippersound_playSound: "start sound {SOUND}",
  flippersound_beepForTime: "play beep {NOTE} for {DURATION} seconds", flippersound_beep: "start playing beep {NOTE}",
  flippersound_stopSound: "stop all sounds",
  flippersensors_isColor: "{PORT} is color {VALUE} ?", flippersensors_color: "{PORT} color",
  flippersensors_isReflectivity: "{PORT} reflection is {@COMPARATOR} {VALUE} % ?", flippersensors_reflectivity: "{PORT} reflection",
  flippersensors_isDistance: "{PORT} is {@COMPARATOR} {VALUE} {@UNIT} ?", flippersensors_distance: "{PORT} distance in {@UNIT}",
  flippersensors_isPressed: "{PORT} is {@OPTION} ?", flippersensors_force: "{PORT} pressure in {@UNIT}",
  flippersensors_orientationAxis: "{@AXIS} angle", flippersensors_resetYaw: "set yaw angle to 0",
  flippersensors_buttonIsPressed: "{@BUTTON} button {@EVENT} ?", flippersensors_timer: "timer", flippersensors_resetTimer: "reset timer",
  control_wait: "wait {DURATION} seconds", control_wait_until: "wait until {CONDITION}", control_repeat: "repeat {TIMES}",
  control_forever: "forever", control_if: "if {CONDITION} then", control_if_else: "if {CONDITION} then",
  control_repeat_until: "repeat until {CONDITION}", control_stop: "stop {@STOP_OPTION}", flippercontrol_stopOtherStacks: "stop other stacks",
  operator_add: "{NUM1} + {NUM2}", operator_subtract: "{NUM1} - {NUM2}", operator_multiply: "{NUM1} × {NUM2}",
  operator_divide: "{NUM1} / {NUM2}", operator_mod: "{NUM1} mod {NUM2}", operator_random: "pick random {FROM} to {TO}",
  operator_gt: "{OPERAND1} > {OPERAND2}", operator_lt: "{OPERAND1} < {OPERAND2}", operator_equals: "{OPERAND1} = {OPERAND2}",
  operator_and: "{OPERAND1} and {OPERAND2}", operator_or: "{OPERAND1} or {OPERAND2}", operator_not: "not {OPERAND}",
  operator_join: "join {STRING1} {STRING2}", operator_letter_of: "letter {LETTER} of {STRING}", operator_length: "length of {STRING}",
  operator_contains: "{STRING1} contains {STRING2} ?", operator_round: "round {NUM}", operator_mathop: "{@OPERATOR} of {NUM}",
  data_variable: "{@VARIABLE}", data_setvariableto: "set {@VARIABLE} to {VALUE}", data_changevariableby: "change {@VARIABLE} by {VALUE}",
  data_listcontents: "{@LIST}", data_addtolist: "add {ITEM} to {@LIST}", data_deleteoflist: "delete {INDEX} of {@LIST}",
  data_deletealloflist: "delete all of {@LIST}", data_itemoflist: "item {INDEX} of {@LIST}", data_lengthoflist: "length of {@LIST}",
  data_listcontainsitem: "{@LIST} contains {ITEM} ?", data_insertatlist: "insert {ITEM} at {INDEX} of {@LIST}",
  data_replaceitemoflist: "replace item {INDEX} of {@LIST} with {ITEM}",
};

// ------------------------------------------------------------------ Scratch value rules
export function num(v) {
  if (typeof v === "boolean") return v ? 1 : 0;
  if (typeof v === "number") return Number.isNaN(v) ? 0 : v;
  const n = Number(String(v).trim());
  return String(v).trim() === "" || Number.isNaN(n) ? 0 : n;
}
function compare(a, b) {
  const sa = String(a).trim(), sb = String(b).trim();
  const na = Number(sa), nb = Number(sb);
  if (sa !== "" && sb !== "" && !Number.isNaN(na) && !Number.isNaN(nb)) return Math.sign(na - nb);
  const la = String(a).toLowerCase(), lb = String(b).toLowerCase();
  return la > lb ? 1 : la < lb ? -1 : 0;
}
const truthy = v => typeof v === "string" ? !["", "0", "false"].includes(v.toLowerCase()) : !!v;
const fmt = v => typeof v === "boolean" ? String(v) : typeof v === "number" && Number.isInteger(v) ? String(v) : String(v);

class StopProgram extends Error {}
class StopThread extends Error {}

// ------------------------------------------------------------------ interpreter
export class BlockRunner {
  constructor(world, { onAction, onState, onSound }) {
    this.world = world; this.hub = new Hub(world);
    this.onAction = onAction; this.onState = onState; this.onSound = onSound;
    this.running = false; this.threads = []; this.active = [];
  }
  start(project) {
    this.stop();
    const w = this.world;
    this.p = project; w.programReset();
    this.vars = Object.fromEntries(Object.entries(project.variables).map(([k, v]) => [k, v.value]));
    this.lists = Object.fromEntries(Object.entries(project.lists).map(([k, v]) => [k, [...v.value]]));
    // start with the robot's own drive motors (A+B on a robot that has none set)
    const [dl, dr] = this.world.driveports();
    this.movePair = dl && dr ? [dl, dr] : ["A", "B"]; this.moveSpeed = 50; this.motorSpeed = {}; this.rotationCm = WHEEL_CIRCUMFERENCE_CM;
    this.timer0 = now(); this.threads = []; this.hatPrev = {}; this.fed = {}; this.procs = this.findProcs();
    this.hatSet = this.p.hats;
    if (this.movePair.every(l => this.world.deviceAt(l) === "motor")) this.hub.pair(...this.movePair);
    this.running = true; this.onState(true);
    for (const h of this.hatSet) if (this.p.blocks[h].opcode === "flipperevents_whenProgramStarts") this.spawn(h);
  }
  stop() {
    if (!this.running) return;
    this.running = false; this.threads = []; this.active = [];
    this.world.programStop(); this.onState(false);
  }
  // one scheduler pass; called every ~10 ms
  tick() {
    if (!this.running) return;
    try {
      this.checkHats();
      for (const th of [...this.threads]) {
        if (th.done) continue;
        try { if (th.gen.next().done) th.done = true; }
        catch (e) { if (e instanceof StopThread) th.done = true; else throw e; }
      }
      this.threads = this.threads.filter(t => !t.done);
      this.active = this.threads.map(t => t.current).filter(Boolean);
    } catch (e) {
      if (!(e instanceof StopProgram)) this.onAction("⚠ " + e.message);
      this.stop();
    }
  }
  spawn(hat) {
    for (const t of this.threads) if (t.hat === hat) t.done = true;   // restart, like Scratch
    const th = { hat, current: null, done: false };
    th.gen = this.runSeq(th, this.p.blocks[hat].next, null);
    this.threads.push(th);
    return th;
  }
  checkHats() {
    for (const h of this.hatSet) {
      const b = this.p.blocks[h];
      if (["flipperevents_whenProgramStarts", "event_whenbroadcastreceived", "procedures_definition"].includes(b.opcode)) continue;
      let val = false;
      try { val = this.hatCondition(b); } catch (e) { if (e instanceof StopProgram) throw e; }
      const prev = this.hatPrev[h] || false;
      this.hatPrev[h] = val;
      if (val && !prev && !this.threads.some(t => t.hat === h && !t.done)) { this.onAction("▶ " + this.p.text(h)); this.spawn(h); }
    }
  }
  hatCondition(b) {
    const v = n => this.value(b, n), f = n => this.p.field(b, n);
    switch (b.opcode) {
      case "flipperevents_whenColor": return String(this.colorAt(v("PORT"))) === String(v("OPTION"));
      case "flipperevents_whenPressed": return this.pressedAt(v("PORT"), f("OPTION"));
      case "flipperevents_whenDistance": return this.cmp(this.distanceAt(v("PORT"), f("UNIT")), f("COMPARATOR"), num(v("VALUE")));
      case "flipperevents_whenButton": return this.buttonState(f("BUTTON"), f("EVENT"));
      case "flipperevents_whenCondition": return truthy(v("CONDITION"));
      case "flipperevents_whenTimer": return now() - this.timer0 > num(v("VALUE"));
    }
    return false;
  }
  feed(id) {
    const t = now();
    if (t - (this.fed[id] ?? -9) < 1) { this.fed[id] = t; return; }   // blocks in fast loops: once a second
    this.fed[id] = t;
    this.onAction(this.p.text(id));
  }
  *runSeq(th, id, args) {
    while (id && this.running) {
      const b = this.p.blocks[id];
      if (!b) return;
      th.current = id;
      yield* this.exec(th, id, b, args);
      id = b.next;
    }
  }
  sub(b, name) { const i = (b.inputs || {})[name]; return i && typeof i[1] === "string" ? i[1] : null; }
  *waitOp(op) { while (op && !op.done()) yield; }
  *waitSeconds(s) { const end = now() + Math.max(0, s); while (now() < end) yield; }

  *exec(th, id, b, args) {
    const op = b.opcode, p = this.p, hub = this.hub;
    const v = n => this.value(b, n, args), f = n => p.field(b, n);
    switch (op) {
      // control
      case "control_forever": for (;;) { yield* this.runSeq(th, this.sub(b, "SUBSTACK"), args); th.current = id; yield; }
      case "control_repeat": {
        const n = Math.max(0, Math.round(num(v("TIMES"))));
        for (let i = 0; i < n; i++) { yield* this.runSeq(th, this.sub(b, "SUBSTACK"), args); th.current = id; yield; }
        break;
      }
      case "control_repeat_until":
        while (!truthy(v("CONDITION"))) { yield* this.runSeq(th, this.sub(b, "SUBSTACK"), args); th.current = id; yield; }
        break;
      case "control_if": if (truthy(v("CONDITION"))) yield* this.runSeq(th, this.sub(b, "SUBSTACK"), args); break;
      case "control_if_else": yield* this.runSeq(th, this.sub(b, truthy(v("CONDITION")) ? "SUBSTACK" : "SUBSTACK2"), args); break;
      case "control_wait": this.feed(id); yield* this.waitSeconds(num(v("DURATION"))); break;
      case "control_wait_until": while (!truthy(v("CONDITION"))) yield; break;
      case "control_stop": {
        this.feed(id);
        const o = f("STOP_OPTION");
        if (o === "this script" || o === "this stack") throw new StopThread();
        if (o && o.startsWith("other scripts")) { this.stopOthers(th); break; }
        throw new StopProgram();
      }
      case "flippercontrol_stopOtherStacks": this.stopOthers(th); break;
      // events
      case "event_broadcast": case "event_broadcastandwait": {
        const msg = String(v("BROADCAST_INPUT")).toLowerCase();
        this.feed(id);
        const started = this.hatSet.filter(h => p.blocks[h].opcode === "event_whenbroadcastreceived" &&
          String(p.field(p.blocks[h], "BROADCAST_OPTION")).toLowerCase() === msg).map(h => this.spawn(h));
        if (op === "event_broadcastandwait") { yield; while (started.some(t => !t.done)) yield; }
        break;
      }
      // movement
      case "flippermove_move": case "flippermove_steer": {
        this.feed(id);
        let speed = this.pairSpeed(), steer;
        if (op === "flippermove_move") {
          const d = String(v("DIRECTION")).toLowerCase();
          steer = CW.has(d) ? 100 : CCW.has(d) ? -100 : 0;
          if (BACKWARD.has(d)) speed = -speed;
        } else steer = this.steering(v("STEERING"));
        hub.pair(...this.movePair);
        const unit = f("UNIT"), value = num(v("VALUE"));
        if (unit === "seconds") yield* this.waitOp(hub.moveForTime(value * 1000, steer, speed));
        else yield* this.waitOp(hub.moveForDegrees(Math.round(this.degrees(value, unit)), steer, speed));
        break;
      }
      case "flippermove_startMove": case "flippermove_startSteer": {
        this.feed(id);
        let speed = this.pairSpeed(), steer;
        if (op === "flippermove_startMove") {
          const d = String(v("DIRECTION")).toLowerCase();
          steer = CW.has(d) ? 100 : CCW.has(d) ? -100 : 0;
          if (BACKWARD.has(d)) speed = -speed;
        } else steer = this.steering(v("STEERING"));
        hub.pair(...this.movePair); hub.move(steer, speed);
        break;
      }
      case "flippermove_stopMove": this.feed(id); hub.pair(...this.movePair); hub.pairStop(); break;
      case "flippermove_movementSpeed": this.feed(id); this.moveSpeed = Math.max(-100, Math.min(100, num(v("SPEED")))); break;
      case "flippermove_setMovementPair": {
        this.feed(id);
        const pair = String(v("PAIR")).toUpperCase().replace(/[^A-F]/g, "");
        if (pair.length === 2) { this.movePair = [pair[0], pair[1]]; hub.pair(...this.movePair); }
        break;
      }
      case "flippermove_setDistance": this.feed(id); this.rotationCm = num(v("DISTANCE")) * (f("UNIT") === "inches" ? 2.54 : 1); break;
      case "flippermoremove_startDualSpeed": case "flippermoremove_startDualPower": {
        this.feed(id);
        const vm = this.pairVmax();
        hub.pair(...this.movePair); hub.moveTank(num(v("LEFT")) * vm / 100, num(v("RIGHT")) * vm / 100);
        break;
      }
      case "flippermoremove_moveDualSpeed": {
        this.feed(id);
        const vm = this.pairVmax(), lv = num(v("LEFT")) * vm / 100, rv = num(v("RIGHT")) * vm / 100;
        const unit = f("UNIT"), value = num(v("VALUE"));
        hub.pair(...this.movePair);
        if (unit === "seconds") yield* this.waitOp(hub.moveTankForTime(lv, rv, value * 1000));
        else yield* this.waitOp(hub.moveTankForDegrees(this.degrees(value, unit), lv, rv));
        break;
      }
      // motors
      case "flippermotor_motorTurnForDirection": {
        this.feed(id);
        const unit = f("UNIT"), value = num(v("VALUE"));
        const sign = CCW.has(String(v("DIRECTION")).toLowerCase()) ? -1 : 1;
        const ops = this.ports(v("PORT")).map(port => {
          const vel = sign * this.motorVelocity(port);
          return unit === "seconds" ? hub.runForTime(port, value * 1000, vel)
            : hub.runForDegrees(port, Math.round(unit === "rotations" ? value * 360 : value), vel);
        });
        for (const o of ops) yield* this.waitOp(o);
        break;
      }
      case "flippermotor_motorStartDirection": {
        this.feed(id);
        const sign = CCW.has(String(v("DIRECTION")).toLowerCase()) ? -1 : 1;
        for (const port of this.ports(v("PORT"))) hub.run(port, sign * this.motorVelocity(port));
        break;
      }
      case "flippermotor_motorStop": this.feed(id); for (const port of this.ports(v("PORT"))) hub.stop(port); break;
      case "flippermotor_motorSetSpeed": this.feed(id); for (const port of this.ports(v("PORT"))) this.motorSpeed[port] = Math.max(-100, Math.min(100, num(v("SPEED")))); break;
      case "flippermotor_motorGoDirectionToPosition": {
        this.feed(id);
        const d = String(f("DIRECTION") ?? v("DIRECTION")).toLowerCase();
        const dir = CW.has(d) ? 0 : CCW.has(d) ? 1 : 2;
        const ops = this.ports(v("PORT")).map(port => hub.runToAbsolute(port, ((Math.round(num(v("POSITION"))) % 360) + 360) % 360, Math.abs(this.motorVelocity(port)), dir));
        for (const o of ops) yield* this.waitOp(o);
        break;
      }
      case "flippermoremotor_motorSetDegreeCounted": this.feed(id); for (const port of this.ports(v("PORT"))) hub.resetRelative(port, num(v("VALUE"))); break;
      case "flippermoremotor_motorStartPower": this.feed(id); for (const port of this.ports(v("PORT"))) hub.setDuty(port, num(v("POWER")) * 100); break;
      // light
      case "flipperlight_lightDisplayText": this.feed(id); yield* this.waitOp(hub.write(fmt(v("TEXT")))); break;
      case "flipperlight_lightDisplayImageOn": case "flipperlight_lightDisplayImageOnForTime": {
        this.feed(id);
        const s = String(v("MATRIX"));
        hub.show(/^[0-9]{25}$/.test(s) ? [...s].map(c => Math.floor(Number(c) * 100 / 9)) : new Array(25).fill(0));
        if (op.endsWith("ForTime")) { yield* this.waitSeconds(num(v("VALUE"))); hub.clear(); }
        break;
      }
      case "flipperlight_lightDisplayOff": this.feed(id); hub.clear(); break;
      case "flipperlight_lightDisplaySetPixel": this.feed(id); hub.setPixel(num(v("X")) - 1, num(v("Y")) - 1, num(v("BRIGHTNESS"))); break;
      case "flipperlight_centerButtonLight": this.feed(id); hub.light(num(v("COLOR"))); break;
      // sound
      case "flippersound_playSoundUntilDone": case "flippersound_playSound": {
        this.feed(id);
        let name = String(v("SOUND"));
        if (name.startsWith("{")) { try { name = JSON.parse(name).name; } catch { /* keep */ } }
        const snd = p.sounds[name];
        this.onSound(snd);
        if (op.endsWith("UntilDone")) yield* this.waitSeconds(snd ? snd.seconds : 1);
        break;
      }
      case "flippersound_beepForTime": case "flippersound_beep": {
        this.feed(id);
        const note = num(v("NOTE")) || 60;
        const dur = op.endsWith("ForTime") ? num(v("DURATION")) : 1;
        yield* this.waitOp(hub.beep(440 * 2 ** ((note - 69) / 12), dur * 1000));
        break;
      }
      case "flippersound_stopSound": break;
      // sensors
      case "flippersensors_resetYaw": this.feed(id); hub.resetYaw(0); break;
      case "flippersensors_resetTimer": this.timer0 = now(); break;
      // variables
      case "data_setvariableto": this.vars[b.fields.VARIABLE[1]] = v("VALUE"); break;
      case "data_changevariableby": { const k = b.fields.VARIABLE[1]; this.vars[k] = num(this.vars[k] ?? 0) + num(v("VALUE")); break; }
      case "data_addtolist": case "data_deletealloflist": case "data_deleteoflist": case "data_insertatlist": case "data_replaceitemoflist":
        this.listStmt(b, op, args); break;
      // my blocks
      case "procedures_call": {
        const m = b.mutation || {}, proc = this.procs[m.proccode];
        if (proc) {
          const ids = JSON.parse(m.argumentids || "[]"), vals = {};
          ids.forEach((a, i) => { if (i < proc.names.length) vals[proc.names[i]] = v(a); });
          yield* this.runSeq(th, proc.body, vals);
        }
        break;
      }
      default:
        if (!/^(flipperevents_when|event_when|procedures_definition)/.test(op)) this.onAction(`⚠ The simulator can't run this block yet: ${p.text(id)}`);
    }
    yield;
  }
  stopOthers(th) { for (const t of this.threads) if (t !== th) t.done = true; }
  listStmt(b, op, args) {
    const lst = this.lists[b.fields.LIST[1]] ??= [];
    const v = n => this.value(b, n, args);
    if (op === "data_addtolist") lst.push(v("ITEM"));
    else if (op === "data_deletealloflist") lst.length = 0;
    else {
      const i = this.index(v("INDEX"), op === "data_insertatlist" ? [...lst, null] : lst);
      if (i === null) return;
      if (op === "data_deleteoflist") lst.splice(i, 1);
      else if (op === "data_insertatlist") lst.splice(i, 0, v("ITEM"));
      else lst[i] = v("ITEM");
    }
  }
  index(v, lst) {
    if (String(v) === "last") return lst.length ? lst.length - 1 : null;
    const i = Math.trunc(num(v)) - 1;
    return i >= 0 && i < lst.length ? i : null;
  }
  findProcs() {
    const procs = {};
    for (const b of Object.values(this.p.blocks)) if (b.opcode === "procedures_definition") {
      const m = (this.p.blocks[b.inputs.custom_block[1]] || {}).mutation || {};
      procs[m.proccode] = { body: b.next, names: JSON.parse(m.argumentnames || "[]") };
    }
    return procs;
  }

  // values
  value(b, name, args) {
    const inp = (b.inputs || {})[name];
    if (!inp) { const f = (b.fields || {})[name]; return f ? f[0] : ""; }
    const ref = inp[1];
    if (Array.isArray(ref)) return ref.length > 1 ? ref[1] : "";
    if (ref === null || ref === undefined) return "";
    return this.eval(ref, args);
  }
  eval(id, args) {
    const p = this.p, b = p.blocks[id];
    if (!b) return "";
    if (isMenu(b)) return p.field(b);
    const v = n => this.value(b, n, args), f = n => p.field(b, n), hub = this.hub;
    switch (b.opcode) {
      case "operator_add": return num(v("NUM1")) + num(v("NUM2"));
      case "operator_subtract": return num(v("NUM1")) - num(v("NUM2"));
      case "operator_multiply": return num(v("NUM1")) * num(v("NUM2"));
      case "operator_divide": { const d = num(v("NUM2")); return d ? num(v("NUM1")) / d : Infinity; }
      case "operator_mod": { const d = num(v("NUM2")); return d ? ((num(v("NUM1")) % d) + d) % d : 0; }
      case "operator_random": {
        const a = num(v("FROM")), c = num(v("TO")), lo = Math.min(a, c), hi = Math.max(a, c);
        return Number.isInteger(lo) && Number.isInteger(hi) ? lo + Math.floor(Math.random() * (hi - lo + 1)) : lo + Math.random() * (hi - lo);
      }
      case "operator_gt": return compare(v("OPERAND1"), v("OPERAND2")) > 0;
      case "operator_lt": return compare(v("OPERAND1"), v("OPERAND2")) < 0;
      case "operator_equals": return compare(v("OPERAND1"), v("OPERAND2")) === 0;
      case "operator_and": return truthy(v("OPERAND1")) && truthy(v("OPERAND2"));
      case "operator_or": return truthy(v("OPERAND1")) || truthy(v("OPERAND2"));
      case "operator_not": return !truthy(v("OPERAND"));
      case "operator_join": return fmt(v("STRING1")) + fmt(v("STRING2"));
      case "operator_letter_of": return fmt(v("STRING"))[Math.trunc(num(v("LETTER"))) - 1] ?? "";
      case "operator_length": return fmt(v("STRING")).length;
      case "operator_contains": return fmt(v("STRING1")).toLowerCase().includes(fmt(v("STRING2")).toLowerCase());
      case "operator_round": return Math.round(num(v("NUM")));
      case "operator_mathop": return mathop(f("OPERATOR"), num(v("NUM")));
      case "data_variable": return this.vars[b.fields.VARIABLE[1]] ?? 0;
      case "data_listcontents": return (this.lists[b.fields.LIST[1]] || []).map(fmt).join(" ");
      case "data_itemoflist": { const l = this.lists[b.fields.LIST[1]] || [], i = this.index(v("INDEX"), l); return i === null ? "" : l[i]; }
      case "data_lengthoflist": return (this.lists[b.fields.LIST[1]] || []).length;
      case "data_listcontainsitem": return (this.lists[b.fields.LIST[1]] || []).some(x => compare(x, v("ITEM")) === 0);
      case "argument_reporter_string_number": case "argument_reporter_boolean": return (args || {})[f("VALUE")] ?? "";
      case "flippersensors_isColor": return String(this.colorAt(v("PORT"))) === String(v("VALUE"));
      case "flippersensors_color": return this.colorAt(v("PORT"));
      case "flippersensors_reflectivity": return hub.reflection(this.ports(v("PORT"))[0]);
      case "flippersensors_isReflectivity": return this.cmp(hub.reflection(this.ports(v("PORT"))[0]), f("COMPARATOR"), num(v("VALUE")));
      case "flippersensors_isDistance": return this.cmp(this.distanceAt(v("PORT"), f("UNIT")), f("COMPARATOR"), num(v("VALUE")));
      case "flippersensors_distance": return this.distanceAt(v("PORT"), f("UNIT")) ?? -1;
      case "flippersensors_isPressed": return this.pressedAt(v("PORT"), f("OPTION"));
      case "flippersensors_force": { const fo = hub.force(this.ports(v("PORT"))[0]); return f("UNIT") === "newton" ? fo / 10 : fo; }
      case "flippersensors_orientationAxis": return f("AXIS") === "yaw" ? Math.round(-hub.yawDecidegrees() / 10) : 0;
      case "flippersensors_buttonIsPressed": return this.buttonState(f("BUTTON"), f("EVENT"));
      case "flippersensors_timer": return Math.round((now() - this.timer0) * 100) / 100;
      case "flippermotor_absolutePosition": return ((hub.absolutePosition(this.ports(v("PORT"))[0]) % 360) + 360) % 360;
      case "flippermotor_speed": { const port = this.ports(v("PORT"))[0]; return Math.trunc(hub.velocity(port) / hub.vmax(port) * 100); }
      case "flippermoremotor_position": return hub.relativePosition(this.ports(v("PORT"))[0]);
    }
    return 0;
  }

  // helpers
  ports(v) { const l = String(v).toUpperCase().replace(/[^A-F]/g, ""); return l ? [...l].map(c => PORTS.indexOf(c)) : [0]; }
  colorAt(pv) { return this.hub.color(this.ports(pv)[0]); }
  distanceAt(pv, unit) {
    const mm = this.hub.distance(this.ports(pv)[0]);
    if (mm < 0) return null;
    return unit === "inches" ? mm / 25.4 : unit === "%" ? mm / 20 : mm / 10;
  }
  pressedAt(pv, option) {
    const port = this.ports(pv)[0], pressed = this.hub.pressed(port);
    if (option === "released") return !pressed;
    if (option === "hardpressed") return this.hub.force(port) >= 80;
    return pressed;
  }
  buttonState(which, event) { const pr = this.hub.button(which === "right" ? "right" : "left"); return event === "released" ? !pr : pr; }
  cmp(a, c, b) { if (a === null) return c === ">"; return c === "<" ? a < b : c === ">" ? a > b : Math.abs(a - b) < 0.5; }
  pairVmax() { return Math.min(...this.movePair.map(l => this.world.motors[l]?.vmax ?? 1110)); }
  pairSpeed() { return this.moveSpeed * this.pairVmax() / 100; }
  motorVelocity(port) { const m = this.world.motors[PORTS[port]]; return (this.motorSpeed[port] ?? 75) * (m ? m.vmax : 1110) / 100; }
  degrees(value, unit) {
    if (unit === "cm") return value / this.rotationCm * 360;
    if (unit === "inches") return value * 2.54 / this.rotationCm * 360;
    if (unit === "rotations") return value * 360;
    return value;
  }
  steering(v) { const m = String(v).match(/-?((\d*\.?\d+)|(\d+\.?))$/); return m ? Math.max(-100, Math.min(100, Math.round(Number(m[0])))) : 0; }
}

function mathop(name, x) {
  const r = Math.PI / 180;
  const ops = { abs: Math.abs, floor: Math.floor, ceiling: Math.ceil, sqrt: Math.sqrt, sin: a => Math.sin(a * r),
    cos: a => Math.cos(a * r), tan: a => Math.tan(a * r), asin: a => Math.asin(a) / r, acos: a => Math.acos(a) / r,
    atan: a => Math.atan(a) / r, ln: Math.log, log: Math.log10, "e ^": Math.exp, "10 ^": a => 10 ** a };
  return ops[name] ? ops[name](x) : 0;
}
