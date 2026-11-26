import { World, MATS, PORTS, COLOR_BY_ID, defaultConfig, now } from "./sim.js?v=4";
import { BlockRunner, Project, readProject, COLOR_NAMES, ProjectError } from "./blocks.js?v=4";

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

// ------------------------------------------------------------------ example projects (built in)
// Small helper for writing Word Block projects in code, in the same shape as a .llsp3 file.
function builder(name) {
  const p = new Project(name);
  p.type = "word-blocks";
  let n = 0;
  const B = p.blocks;
  const add = (op, o = {}) => { const id = "ex" + (n++); B[id] = { opcode: op, next: null, parent: null, inputs: o.inputs || {}, fields: o.fields || {}, shadow: !!o.shadow, topLevel: !!o.top, x: o.x || 0, y: o.y || 0 }; return id; };
  const menu = (op, value) => add(op, { shadow: true, fields: { ["field_" + op]: [value, null] } });
  const lit = v => [1, [4, String(v)]];
  const chain = ids => { for (let i = 0; i < ids.length - 1; i++) { B[ids[i]].next = ids[i + 1]; B[ids[i + 1]].parent = ids[i]; } return ids[0]; };
  const dir = d => [1, menu("flippermove_custom-icon-direction", d)];
  return { p, add, menu, lit, chain, dir };
}

function colorExample() {
  const { p, add, menu, lit, chain, dir } = builder("Example: Color stripes");
  const isColor = c => add("flippersensors_isColor", { inputs: { PORT: [1, menu("flippersensors_color-sensor-selector", "C")], VALUE: [1, menu("flippersensors_color-selector", String(c))] } });
  const heart = "0909099999999990999000900";
  chain([
    add("flipperevents_whenProgramStarts", { top: true, y: 0 }),
    add("flippermove_setMovementPair", { inputs: { PAIR: [1, menu("flippermove_movement-port-selector", "AB")] } }),
    add("flippermove_movementSpeed", { inputs: { SPEED: lit(30) } }),
    add("flipperlight_lightDisplayText", { inputs: { TEXT: [1, [10, "Go"]] } }),
    add("flippermove_startMove", { inputs: { DIRECTION: dir("forward") } }),
    add("control_wait_until", { inputs: { CONDITION: [2, isColor(9)] } }),
    add("flippermove_stopMove"),
    add("flipperlight_lightDisplayImageOn", { inputs: { MATRIX: [1, menu("flipperlight_matrix-5x5-brightness-image", heart)] } }),
    add("flippersound_beepForTime", { inputs: { NOTE: lit(72), DURATION: lit(0.3) } }),
    add("flippermove_move", { inputs: { DIRECTION: dir("back"), VALUE: lit(10) }, fields: { UNIT: ["cm", null] } }),
  ]);
  for (const [i, c] of [6, 7].entries()) {
    chain([
      add("flipperevents_whenColor", { top: true, y: 100 + i, inputs: { PORT: [1, menu("flippersensors_color-sensor-selector", "C")], OPTION: [1, menu("flippersensors_color-selector", String(c))] } }),
      add("flipperlight_centerButtonLight", { inputs: { COLOR: [1, menu("flipperlight_color-selector-vertical", String(c))] } }),
    ]);
  }
  return p;
}

// Drives around the Playground: go forward until the distance sensor sees a wall or mat edge
// closer than 15 cm, then turn right and carry on. The hub light shows when a wall is near.
function distanceExample() {
  const { p, add, menu, lit, chain, dir } = builder("Example: Distance sensor");
  const distPort = () => [1, menu("flippersensors_distance-sensor-selector", "D")];
  const isCloser = cm => add("flippersensors_isDistance", { inputs: { PORT: distPort(), VALUE: lit(cm) }, fields: { COMPARATOR: ["<", null], UNIT: ["cm", null] } });
  const loopBody = chain([
    add("flippermove_startMove", { inputs: { DIRECTION: dir("forward") } }),
    add("control_wait_until", { inputs: { CONDITION: [2, isCloser(15)] } }),
    add("flippermove_stopMove"),
    add("flippersound_beepForTime", { inputs: { NOTE: lit(67), DURATION: lit(0.2) } }),
    add("flippermove_move", { inputs: { DIRECTION: dir("clockwise"), VALUE: lit(0.5) }, fields: { UNIT: ["rotations", null] } }),
  ]);
  chain([
    add("flipperevents_whenProgramStarts", { top: true, y: 0 }),
    add("flippermove_setMovementPair", { inputs: { PAIR: [1, menu("flippermove_movement-port-selector", "AB")] } }),
    add("flippermove_movementSpeed", { inputs: { SPEED: lit(40) } }),
    add("control_forever", { inputs: { SUBSTACK: [2, loopBody] } }),
  ]);
  const when = (comparator, color, y) => chain([
    add("flipperevents_whenDistance", { top: true, y, inputs: { PORT: distPort(), VALUE: lit(20) }, fields: { COMPARATOR: [comparator, null], UNIT: ["cm", null] } }),
    add("flipperlight_centerButtonLight", { inputs: { COLOR: [1, menu("flipperlight_color-selector-vertical", String(color))] } }),
  ]);
  when("<", 9, 100);   // red when a wall is closer than 20 cm
  when(">", 6, 101);   // green again when it is farther than 20 cm
  return p;
}

// Learning camp 1 (Competition-Ready "Training Camp 1: Driving Around"): drive in a square.
// Practice Driving Base: drive motors on C (left) and D (right), no sensors.
function camp1Example() {
  const { p, add, menu, lit, chain, dir } = builder("Camp 1: Drive a square");
  const side = chain([
    add("flippermove_move", { inputs: { DIRECTION: dir("forward"), VALUE: lit(40) }, fields: { UNIT: ["cm", null] } }),
    add("flippermove_steer", { inputs: { STEERING: [1, menu("flippermove_rotation-wheel", "-100")], VALUE: lit(0.5) }, fields: { UNIT: ["rotations", null] } }),
  ]);
  chain([
    add("flipperevents_whenProgramStarts", { top: true }),
    add("flippermove_setMovementPair", { inputs: { PAIR: [1, menu("flippermove_movement-port-selector", "CD")] } }),
    add("flippermove_movementSpeed", { inputs: { SPEED: lit(50) } }),
    add("control_repeat", { inputs: { TIMES: [1, [6, "4"]], SUBSTACK: [2, side] } }),
  ]);
  return p;
}

const CAMP1_GUIDE = `
<h3>Camp 1 · Driving around</h3>
<p><b>Goal:</b> make your Driving Base move in a square and finish where it started.</p>
<p><b>Robot:</b> the Practice Driving Base with no sensors. The drive motors are on <b>C (left)</b> and <b>D (right)</b>.
If your robot uses other ports, change the "set movement motors" block.</p>
<h4>Steps</h4>
<ol>
  <li><b>One side.</b> Use <i>move ↑ forward for 40 cm</i>. Run it, then measure how far the robot went.</li>
  <li><b>One corner.</b> Use <i>move steering −100 for 0.5 rotations</i>. Steering −100 spins the robot on the spot to the left.
    Change 0.5 until the turn is exactly a quarter turn (90°).</li>
  <li><b>Find the pattern.</b> A square is "drive a side, turn a corner", four times.
    Put those two blocks inside <i>repeat 4</i>.</li>
  <li><b>Run the program.</b> The robot should trace the path and stop back on the START circle, facing the way it started.</li>
</ol>
<h4>Why these numbers?</h4>
<ul>
  <li>The wheels are 5.6 cm across, so one wheel rotation drives π × 5.6 ≈ <b>17.6 cm</b>. 40 cm is about 2.3 rotations.</li>
  <li>When the robot spins on the spot, each wheel drives around a circle as wide as the gap between the wheels (11.2 cm).
    A quarter of that circle is π × 11.2 ÷ 4 ≈ 8.8 cm, which is <b>0.5 rotations</b>.</li>
  <li>A real robot's wheels slip a little and its wheel gap may differ, so you may need 0.48 or 0.52. Testing and adjusting is the real skill.</li>
</ul>
<h4>Try this</h4>
<ul>
  <li>Make a bigger square with 60 cm sides. Does it still fit on the mat?</li>
  <li>Change steering to <b>100</b>. Which way does the square go now?</li>
  <li>Make a triangle: repeat 3 and turn 120° (about 0.67 rotations).</li>
  <li>Make it faster with movement speed 80 %. Is it still accurate?</li>
  <li>Expert: turn using the yaw angle instead of rotations: <i>set yaw angle to 0</i>, <i>start moving steering −100</i>,
    <i>wait until yaw angle &lt; −90</i>, <i>stop moving</i>.</li>
</ul>
<details><summary>The same program in Python</summary>
<pre>from hub import port
import motor_pair, runloop

async def main():
    motor_pair.pair(motor_pair.PAIR_1, port.C, port.D)
    for side in range(4):
        # 40 cm = 40 / 17.6 × 360 ≈ 819 wheel degrees
        await motor_pair.move_for_degrees(motor_pair.PAIR_1, 819, 0, velocity=555)
        # turn left 90°: steering -100 for half a rotation
        await motor_pair.move_for_degrees(motor_pair.PAIR_1, 180, -100, velocity=555)

runloop.run(main())</pre>
</details>`;

// Learning camp 2 (Competition-Ready "Training Camp 2: Playing with Objects").
// Practice Driving Base with a Distance Sensor (F) and an Arm (motor E).
function camp2Program(name, relay) {
  const { p, add, menu, lit, chain, dir } = builder(name);
  const port = (op, v) => [1, menu(op, v)];
  const closer = cm => add("flippersensors_isDistance", { inputs: { PORT: port("flippersensors_distance-sensor-selector", "F"), VALUE: lit(cm) }, fields: { COMPARATOR: ["<", null], UNIT: ["cm", null] } });
  const arm = (direction, deg) => add("flippermotor_motorTurnForDirection", { inputs: { PORT: port("flippermotor_multiple-port-selector", "E"), DIRECTION: [1, menu("flippermotor_custom-icon-direction", direction)], VALUE: lit(deg) }, fields: { UNIT: ["degrees", null] } });
  const trip = [
    add("flippermove_startMove", { inputs: { DIRECTION: dir("forward") } }),
    add("control_wait_until", { inputs: { CONDITION: [2, closer(8)] } }),
    add("flippermove_stopMove"),
    arm("clockwise", 90),                                              // lower the arm over the cube
    add("flippermove_move", { inputs: { DIRECTION: dir("back"), VALUE: lit(22) }, fields: { UNIT: ["cm", null] } }),
    arm("counterclockwise", 90),                                       // raise the arm: let go
  ];
  const setup = [
    add("flipperevents_whenProgramStarts", { top: true }),
    add("flippermove_setMovementPair", { inputs: { PAIR: [1, menu("flippermove_movement-port-selector", "CD")] } }),
    add("flippermove_movementSpeed", { inputs: { SPEED: lit(30) } }),
  ];
  if (relay) {
    const body = chain([...trip, add("control_wait", { inputs: { DURATION: lit(1) } })]);
    chain([...setup, add("control_repeat", { inputs: { TIMES: [1, [6, "4"]], SUBSTACK: [2, body] } })]);
  } else chain([...setup, ...trip]);
  return p;
}

const CAMP2_GUIDE = `
<h3>Camp 2 · Playing with objects</h3>
<p><b>Goal:</b> use the distance sensor to stop at an object, grab a cube with the arm, and win a relay race.</p>
<p><b>Robot:</b> the Practice Driving Base with a <b>Distance Sensor on F</b> and an <b>Arm on motor E</b>, driving with C (left) and D (right).
In the simulator, turning the arm motor 45° or more lowers it, and it grabs a cube just in front of the robot.
Turning it back raises it and lets go.</p>
<h4>Steps</h4>
<ol>
  <li><b>Stop at the marker by guessing.</b> The marker is 30 cm in front of the sensor. Try <i>move ↑ forward for 22 cm</i>.
    Too far or not far enough? Change the number.</li>
  <li><b>Stop at the marker with the sensor.</b> <i>start moving ↑ forward</i>, <i>wait until F is closer than 8 cm</i>, <i>stop moving</i>.
    Move the marker or the robot and try both programs again. Which one always works?</li>
  <li><b>Grab the cube.</b> After stopping, <i>E run ↻ clockwise for 90 degrees</i> lowers the arm onto the cube.
    Then <i>move ↓ back for 22 cm</i> to bring it home, and <i>E run ↺ counterclockwise for 90 degrees</i> to let go.
    This is the <b>Camp 2: Stop and grab</b> example.</li>
  <li><b>Relay race.</b> Four batons wait at the marker. Put the trip inside <i>repeat 4</i> and add <i>wait 1 seconds</i>
    so a teammate can take each baton. This is the <b>Camp 2: Relay race</b> example. The feed counts each baton that reaches HOME.</li>
</ol>
<h4>Why these numbers?</h4>
<ul>
  <li>The distance sensor sits about 10 cm in front of the middle of the robot. Stopping when it reads 8 cm leaves the cube right under the arm.</li>
  <li>The sensor sees the tall marker but not the low cube. On a real robot, keep the raised arm high enough to pass over the cube
    without blocking the sensor.</li>
  <li>Backing up 22 cm returns the robot to where it started, inside HOME.</li>
</ul>
<h4>Try this</h4>
<ul>
  <li>Stop at 5 cm or at 12 cm. Can the arm still reach the cube?</li>
  <li>Make the relay faster: speed up the driving, and remove the wait.</li>
  <li>Bring the cube back using the distance sensor too: drive back until F is farther than 30 cm.</li>
  <li>Write your own game rules with a different object and challenge another team.</li>
</ul>
<details><summary>The relay race in Python</summary>
<pre>from hub import port
import motor, motor_pair, distance_sensor, runloop

async def main():
    motor_pair.pair(motor_pair.PAIR_1, port.C, port.D)
    for baton in range(4):
        motor_pair.move(motor_pair.PAIR_1, 0, velocity=333)
        while distance_sensor.distance(port.F) == -1 or distance_sensor.distance(port.F) > 80:   # mm
            await runloop.sleep_ms(10)
        motor_pair.stop(motor_pair.PAIR_1)
        await motor.run_for_degrees(port.E, 90, 832)          # lower the arm
        await motor_pair.move_for_degrees(motor_pair.PAIR_1, -450, 0, velocity=333)   # back 22 cm
        await motor.run_for_degrees(port.E, -90, 832)         # raise the arm, let go
        await runloop.sleep_ms(1000)

runloop.run(main())</pre>
</details>`;

// Learning camp 3 (Competition-Ready "Training Camp 3: React to Lines").
// Driving Base with a Color Sensor on B, reading reflected light; drive motors C (left) + D (right).
function camp3Program(name, follow) {
  const { p, add, menu, lit, chain, dir } = builder(name);
  const onBlack = () => add("flippersensors_isReflectivity", { inputs: { PORT: [1, menu("flippersensors_color-sensor-selector", "B")], VALUE: lit(50) }, fields: { COMPARATOR: ["<", null] } });
  const steer = v => add("flippermove_startSteer", { inputs: { STEERING: [1, menu("flippermove_rotation-wheel", String(v))] } });
  const setup = [
    add("flipperevents_whenProgramStarts", { top: true }),
    add("flippermove_setMovementPair", { inputs: { PAIR: [1, menu("flippermove_movement-port-selector", "CD")] } }),
    add("flippermove_movementSpeed", { inputs: { SPEED: lit(30) } }),
  ];
  if (follow) {
    const ifElse = add("control_if_else", { inputs: { CONDITION: [2, onBlack()], SUBSTACK: [2, steer(50)], SUBSTACK2: [2, steer(-50)] } });
    chain([...setup, add("control_forever", { inputs: { SUBSTACK: [2, ifElse] } })]);
  } else {
    chain([...setup,
      add("flippermove_startMove", { inputs: { DIRECTION: dir("forward") } }),
      add("control_wait_until", { inputs: { CONDITION: [2, onBlack()] } }),
      add("flippermove_stopMove"),
      add("flippersound_beepForTime", { inputs: { NOTE: lit(72), DURATION: lit(0.2) } }),
    ]);
  }
  return p;
}

const CAMP3_GUIDE = `
<h3>Camp 3 · Reacting to lines</h3>
<p><b>Goal:</b> use the color sensor to stop at a black line, then follow a black line.</p>
<p><b>Robot:</b> the Driving Base with a <b>Color Sensor on B</b> pointing down at the mat, driving with C (left) and D (right).
The sensor measures <b>reflected light</b>: white mat ≈ 100 %, black line ≈ 6 %. Halfway, <b>50 %</b>, is a good line between "black" and "white".
Watch port B in the Ports panel while the robot moves.</p>
<h4>Steps</h4>
<ol>
  <li><b>Stop at the line.</b> <i>start moving ↑ forward</i>, <i>wait until B reflection is &lt; 50 %</i>, <i>stop moving</i>.
    This is the <b>Camp 3: Stop at the line</b> example. Try it from different starting spots. It always finds the line.</li>
  <li><b>Follow the line.</b> In a <i>forever</i> loop: if B reflection is &lt; 50 % (on black), <i>start moving steering 50</i>.
    Otherwise (on white), <i>start moving steering −50</i>. This is the <b>Camp 3: Follow the line</b> example.</li>
  <li><b>Why 50 and −50?</b> At steering 50 one wheel stops and the other drives, so the robot still moves forward while it turns.
    With 100 and −100 it spins on the spot and wobbles without getting anywhere. Try it!</li>
  <li><b>Race.</b> Make it faster: change the movement speed. At 30 % the robot holds the line. Somewhere around 40 % it starts to lose it on the curves.
    Can you make it fast <i>and</i> safe, for example with smaller steering like 30 and −30?</li>
</ol>
<h4>How the line follower works</h4>
<ul>
  <li>The robot really follows the <b>edge</b> of the line: on black it turns one way, on white the other, so it zig-zags along the border.</li>
  <li>That's why it goes around the loop in one direction only. Turn it around and it follows the other edge.</li>
  <li>Using <i>if … else</i> means every pass of the loop makes exactly one decision. That's simpler and quicker than two separate <i>if</i> blocks.</li>
</ul>
<h4>Try this</h4>
<ul>
  <li>Load the <b>Camp 3: Line ideas</b> mat and run your follower. What happens at the right angle, the T-junction, the gap and the red line?</li>
  <li>Stop at the red line: add a check for <i>B is color red</i>.</li>
  <li>Change the 50 % threshold to 30 % or 70 %. What changes, and why?</li>
  <li>Count the lines you cross on the <b>Color stripes</b> mat with a variable.</li>
</ul>
<details><summary>The same programs in Python</summary>
<pre>from hub import port
import motor_pair, color_sensor, runloop

async def main():
    motor_pair.pair(motor_pair.PAIR_1, port.C, port.D)

    # 1. stop at the line
    motor_pair.move(motor_pair.PAIR_1, 0, velocity=333)
    while color_sensor.reflection(port.B) >= 50:
        await runloop.sleep_ms(10)
    motor_pair.stop(motor_pair.PAIR_1)

    # 2. follow the line (use this part on the Follow the line mat)
    # while True:
    #     if color_sensor.reflection(port.B) < 50:
    #         motor_pair.move(motor_pair.PAIR_1, 50, velocity=333)
    #     else:
    #         motor_pair.move(motor_pair.PAIR_1, -50, velocity=333)
    #     await runloop.sleep_ms(10)

runloop.run(main())</pre>
</details>`;

const CAMP3_ROBOT = {
  A: {}, B: { type: "color" }, C: { type: "motor", model: "medium", role: "left" },
  D: { type: "motor", model: "medium", role: "right" }, E: {}, F: {},
};

const CAMP2_ROBOT = {
  A: {}, B: {}, C: { type: "motor", model: "medium", role: "left" }, D: { type: "motor", model: "medium", role: "right" },
  E: { type: "motor", model: "medium", role: "arm" }, F: { type: "distance" },
};

const CAMP_ROBOT = {
  A: {}, B: {}, C: { type: "motor", model: "medium", role: "left" }, D: { type: "motor", model: "medium", role: "right" },
  E: {}, F: {},
};

const EXAMPLES = {
  camp3stop: { mat: "camp3stop", make: () => camp3Program("Camp 3: Stop at the line", false), config: CAMP3_ROBOT, guide: CAMP3_GUIDE,
    hint: "Learning camp 3: drive forward and stop on the black line using reflected light." },
  camp3follow: { mat: "camp3follow", make: () => camp3Program("Camp 3: Follow the line", true), config: CAMP3_ROBOT, guide: CAMP3_GUIDE,
    hint: "Learning camp 3: follow the black loop. Can you make it faster without losing the line?" },
  camp3ideas: { mat: "camp3ideas", make: () => camp3Program("Camp 3: Line ideas", true), config: CAMP3_ROBOT, guide: CAMP3_GUIDE,
    hint: "Learning camp 3: the same line follower on a harder track. Watch what happens at each special spot." },
  camp2: { mat: "camp2", make: () => camp2Program("Camp 2: Stop and grab", false), config: CAMP2_ROBOT, guide: CAMP2_GUIDE,
    hint: "Learning camp 2: stop at the marker with the distance sensor, grab the cube with the arm, and bring it HOME." },
  relay: { mat: "relay", make: () => camp2Program("Camp 2: Relay race", true), config: CAMP2_ROBOT, guide: CAMP2_GUIDE,
    hint: "Learning camp 2 relay race: bring all four batons HOME, one trip at a time." },
  camp1: { mat: "camp1", make: camp1Example, config: CAMP_ROBOT, guide: CAMP1_GUIDE,
    hint: "Learning camp 1: make the Driving Base move in a square. Press Run project, then read the camp guide below the program." },
  colors: { mat: "colors", make: colorExample,
    hint: "Example: drives across the stripes, lights the hub green and yellow, and stops on red. Drag the robot onto colors to try the sensor." },
  distance: { mat: "playground", make: distanceExample,
    hint: "Example: drives forward until the distance sensor (port D) sees a wall or mat edge closer than 15 cm, then turns right. The hub light goes red near walls. Watch the dashed line and port D." },
};
function loadExample(key) {
  const ex = EXAMPLES[key];
  setMat(ex.mat);
  world.applyConfig(structuredClone(ex.config || defaultConfig()));
  showProject(ex.make(), null, ex.hint);
  showGuide(ex.guide);
}
function showGuide(html) {
  $("#guideCard").hidden = !html;
  $("#guide").innerHTML = html || "";
}

// ------------------------------------------------------------------ project bar
function showProject(p, label, hint) {
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
  $("#projHint").textContent = hint || "Press Run project, then watch the robot and the blocks. Drag the robot onto colors or near walls to try your sensors.";
  const scripts = p.scripts();
  if (!scripts.length) { box.innerHTML = '<p class="hint">This project has no blocks under a "when" block yet.</p>'; return; }
  for (const sc of scripts) { const d = document.createElement("div"); d.className = "script"; renderSeq(sc, d); box.appendChild(d); }
}
async function openFile(file) {
  try {
    const p = await readProject(file);
    showProject(p);
    showGuide(null);
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
$("#exampleSel").onchange = e => { if (e.target.value) loadExample(e.target.value); e.target.value = ""; };
$("#runBtn").onclick = () => {
  if (!project || project.type === "python") return;
  $("#feed").textContent = ""; world.trail = [[world.x, world.y]];
  if (world.mat.cubes) world.resetRobot();   // challenges with objects always start from the beginning
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
    else if (s.kind === "guide") drawGuide(s);
    else if (s.kind === "zone") {
      ctx.fillStyle = s.color || "#fff1b8"; ctx.fillRect(X(s.x), Y(s.y + s.h), s.w * scale, s.h * scale);
      ctx.strokeStyle = "#d9b84a"; ctx.setLineDash([6, 4]); ctx.lineWidth = 1.5;
      ctx.strokeRect(X(s.x), Y(s.y + s.h), s.w * scale, s.h * scale); ctx.setLineDash([]);
      if (s.label) { ctx.fillStyle = "#8a6d00"; ctx.font = `700 ${Math.max(10, 2.2 * scale)}px Inter, system-ui, sans-serif`;
        ctx.textAlign = "left"; ctx.textBaseline = "top"; ctx.fillText(s.label, X(s.x) + 4, Y(s.y + s.h) + 4); }
    } else if (s.kind === "marker") {
      ctx.fillStyle = "#3d4248"; ctx.fillRect(X(s.x), Y(s.y + s.h), s.w * scale, s.h * scale);
      ctx.fillStyle = "#ffc917"; ctx.fillRect(X(s.x), Y(s.y + s.h * 0.6), s.w * scale, s.h * 0.2 * scale);
      if (s.label) { ctx.fillStyle = "#5f6870"; ctx.font = `600 ${Math.max(10, 2.2 * scale)}px Inter, system-ui, sans-serif`;
        ctx.textAlign = "center"; ctx.textBaseline = "bottom"; ctx.fillText(s.label, X(s.x + s.w / 2), Y(s.y + s.h) - 4); }
    }
    else if (s.kind === "label") {
      ctx.fillStyle = "#5f6870"; ctx.font = `600 ${Math.max(11, 2.6 * scale)}px Inter, system-ui, sans-serif`;
      ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(s.text, X(s.x), Y(s.y));
    }
  }
  const st = mat.start; ctx.strokeStyle = "#9aa1a6"; ctx.setLineDash([4, 4]); ctx.lineWidth = 1.5;
  ctx.beginPath(); ctx.arc(X(st.x), Y(st.y), 9 * scale, 0, 7); ctx.stroke(); ctx.setLineDash([]);
  if (world.trail.length > 1) {
    ctx.strokeStyle = "rgba(255,170,0,.85)"; ctx.lineWidth = 2; ctx.beginPath();
    world.trail.forEach(([x, y], i) => i ? ctx.lineTo(X(x), Y(y)) : ctx.moveTo(X(x), Y(y))); ctx.stroke();
  }
  for (const c of world.cubes) if (c !== world.carried) drawCube(c);
  drawRobot();
  if (world.carried) drawCube(world.carried);
}
function drawCube(c) {
  const h = c.size / 2;
  ctx.fillStyle = c.color; ctx.strokeStyle = "rgba(0,0,0,.45)"; ctx.lineWidth = 1;
  ctx.fillRect(X(c.x - h), Y(c.y + h), c.size * scale, c.size * scale);
  ctx.strokeRect(X(c.x - h), Y(c.y + h), c.size * scale, c.size * scale);
}
// A path for the robot to follow (drawn only; sensors don't see it), with an arrowhead at the end.
function drawGuide(s) {
  const pts = s.points;
  ctx.strokeStyle = "#2a2f35"; ctx.lineWidth = Math.max(2, 0.6 * scale); ctx.lineCap = ctx.lineJoin = "square";
  ctx.beginPath(); pts.forEach(([x, y], i) => i ? ctx.lineTo(X(x), Y(y)) : ctx.moveTo(X(x), Y(y))); ctx.stroke();
  if (s.arrow && pts.length > 1) {
    const [x1, y1] = pts[pts.length - 2], [x2, y2] = pts[pts.length - 1];
    const a = Math.atan2(-(y2 - y1), x2 - x1), L = 3 * scale;
    ctx.beginPath();
    ctx.moveTo(X(x2) - L * Math.cos(a - 0.6), Y(y2) - L * Math.sin(a - 0.6));
    ctx.lineTo(X(x2), Y(y2));
    ctx.lineTo(X(x2) - L * Math.cos(a + 0.6), Y(y2) - L * Math.sin(a + 0.6));
    ctx.lineCap = "round"; ctx.stroke();
  }
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
  if (world.armPort()) {
    // grabber arm: a raised bar when up, two open jaws reaching forward when lowered
    ctx.fillStyle = "#6d747b";
    if (world.armDown()) { rr(10.5, -6.2, 7, 1.4, .4); ctx.fill(); rr(10.5, 4.8, 7, 1.4, .4); ctx.fill(); rr(10, -6.2, 1.4, 12.4, .4); ctx.fill(); }
    else { rr(10, -6.2, 1.4, 12.4, .4); ctx.fill(); }
  }
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

loadExample("camp1");
buildPorts();
requestAnimationFrame(frame);
