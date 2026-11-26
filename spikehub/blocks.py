"""Open SPIKE App 3 project files (.llsp3) and run Word Block programs directly.

A .llsp3 file is a zip with manifest.json plus either scratch.sb3 (blocks; itself a
zip holding project.json and sound files) or projectbody.json (Python).

Word Blocks run in an interpreter with Scratch-style scheduling: every hat block
starts a thread, threads take turns, and loops give up their turn each time round.
The interpreter reports which block each thread is running so the page can
highlight it. Hardware calls go through the same simulated hub modules as
Python programs, and the numbers follow what the SPIKE app's own compiler uses
(default movement speed 50%, motor speed 75%, yaw = -tilt_angles()[0] / 10, ...).
"""
from __future__ import annotations

import io
import json
import math
import random
import re
import threading
import time
import zipfile

from . import world as W
from .runtime import Runtime, StopProgram

WHEEL_CIRCUMFERENCE_CM = math.pi * W.WHEEL_DIAMETER
COLOR_NAMES = {-1: "no color", 0: "black", 1: "magenta", 2: "purple", 3: "blue", 4: "azure",
               5: "turquoise", 6: "green", 7: "yellow", 8: "orange", 9: "red", 10: "white"}
DIRECTION_WORDS = {"clockwise": "↻ clockwise", "counterclockwise": "↺ counterclockwise",
                   "forward": "↑ forward", "back": "↓ back", "backward": "↓ back",
                   "shortest": "shortest path"}
FORWARD = {"forward", "fwd", "f", "straight"}
BACKWARD = {"back", "backward", "backwards", "rev", "reverse", "b"}
CW = {"cw", "clock", "clockwise", "right"}
CCW = {"ccw", "counter", "counterclockwise", "left"}

CATEGORY = [
    ("flipperevents_", "events"), ("event_", "events"), ("flippermoremove_", "move"),
    ("flippermove_", "move"), ("flippermoremotor_", "motor"), ("flippermotor_", "motor"),
    ("flipperlight_", "light"), ("flippersound_", "sound"), ("flippermusic_", "sound"),
    ("flippersensors_", "sensors"), ("flippermoresensors_", "sensors"),
    ("flippercontrol_", "control"), ("control_", "control"), ("operator_", "operators"),
    ("data_", "variables"), ("procedures_", "myblocks"), ("argument_", "myblocks"),
]


def category(op):
    return next((c for p, c in CATEGORY if op.startswith(p)), "other")


# --------------------------------------------------------------------- project files
class ProjectError(Exception):
    pass


class Project:
    def __init__(self, data: bytes, filename="project.llsp3"):
        self.filename = filename
        try:
            outer = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise ProjectError("This isn't a SPIKE project file. Save the project from the SPIKE app "
                               "(File > Save to your device) and pick the .llsp3 file.")
        names = outer.namelist()
        self.manifest = json.loads(outer.read("manifest.json")) if "manifest.json" in names else {}
        self.name = self.manifest.get("name") or filename
        self.type = self.manifest.get("type", "")
        self.python = None
        self.blocks = {}
        self.variables = {}
        self.lists = {}
        self.broadcasts = {}
        self.sounds = {}
        if "projectbody.json" in names:
            body = json.loads(outer.read("projectbody.json"))
            self.type = "python"
            self.python = body.get("main", "")
        elif "scratch.sb3" in names:
            inner = zipfile.ZipFile(io.BytesIO(outer.read("scratch.sb3")))
            proj = json.loads(inner.read("project.json"))
            for t in proj.get("targets", []):
                for vid, v in t.get("variables", {}).items():
                    self.variables[vid] = {"name": v[0], "value": v[1]}
                for lid, l in t.get("lists", {}).items():
                    self.lists[lid] = {"name": l[0], "value": list(l[1])}
                self.broadcasts.update(t.get("broadcasts", {}))
                for s in t.get("sounds", []):
                    fn = s.get("md5ext") or f"{s.get('assetId')}.{s.get('dataFormat', 'wav')}"
                    if fn in inner.namelist():
                        rate = s.get("rate") or 44100
                        self.sounds[s["name"]] = {"file": fn, "data": inner.read(fn),
                                                  "seconds": (s.get("sampleCount") or rate) / rate}
                if not t.get("isStage"):
                    self.blocks.update({k: v for k, v in t.get("blocks", {}).items() if isinstance(v, dict)})
            if self.type in ("icon-blocks",):
                raise ProjectError("Icon Block projects aren't supported yet. Word Block and Python projects work.")
            self.type = "word-blocks"
        else:
            raise ProjectError("This project file has no program in it.")

    @property
    def hats(self):
        return [bid for bid, b in self.blocks.items() if b.get("topLevel") and
                (b["opcode"].startswith(("flipperevents_when", "event_when")) or b["opcode"] == "procedures_definition")]

    # ------------------------------------------------------------------ rendering
    def field(self, b, name=None):
        f = b.get("fields", {})
        if name is None:
            if not f:
                return None
            name = next(iter(f))
        v = f.get(name)
        return v[0] if v else None

    def input_text(self, b, name):
        inp = b.get("inputs", {}).get(name)
        if not inp:
            return "?"
        ref = inp[1]
        if isinstance(ref, list):
            return str(ref[1]) if len(ref) > 1 else "?"
        blk = self.blocks.get(ref)
        if blk is None:
            return "?"
        if is_menu(blk):
            return menu_text(blk["opcode"], self.field(blk))
        return "(" + self.text(ref) + ")"

    def text(self, bid):
        b = self.blocks[bid]
        op = b["opcode"]
        tpl = TEXT.get(op)
        if tpl is None:
            words = re.sub(r"([a-z])([A-Z])", r"\1 \2", op.split("_", 1)[-1]).lower()
            parts = [words] + [self.input_text(b, k) for k in b.get("inputs", {}) if k not in ("SUBSTACK", "SUBSTACK2")]
            return " ".join(parts)

        def sub(m):
            key = m.group(1)
            if key.startswith("@"):
                key = key[1:]
                v = self.field(b, key)
                if key == "VARIABLE" or key == "LIST" or key == "BROADCAST_OPTION":
                    return str(v)
                return menu_text(key.lower(), v)
            return self.input_text(b, key)
        out = re.sub(r"\{(@?[A-Z0-9_]+)\}", sub, tpl)
        if op == "procedures_call" or op == "procedures_definition":
            out = proc_text(self, b)
        return out

    def tree(self, bid):
        """Nested description of a script for the page."""
        out = []
        while bid:
            b = self.blocks.get(bid)
            if b is None:
                break
            op = b["opcode"]
            node = {"id": bid, "op": op, "cat": category(op), "text": self.text(bid),
                    "hat": bid in self.hats}
            for key, slot in (("SUBSTACK", "body"), ("SUBSTACK2", "else")):
                inp = b.get("inputs", {}).get(key)
                if inp and isinstance(inp[1], str):
                    node[slot] = self.tree(inp[1])
                elif key == "SUBSTACK" and op in C_BLOCKS:
                    node[slot] = []
            if op == "control_if_else" and "else" not in node:
                node["else"] = []
            out.append(node)
            bid = b.get("next")
        return out

    def scripts(self):
        hats = sorted(self.hats, key=lambda h: (self.blocks[h].get("y", 0), self.blocks[h].get("x", 0)))
        return [self.tree(h) for h in hats]


C_BLOCKS = {"control_forever", "control_repeat", "control_repeat_until", "control_if", "control_if_else",
            "control_while", "control_for_each"}


def is_menu(b):
    return not b.get("inputs") and len(b.get("fields", {})) == 1 and b.get("shadow", True) and \
        not b["opcode"].startswith(("data_", "argument_"))


def menu_text(op, v):
    if v is None:
        return "?"
    s = str(v)
    if "color" in op and re.fullmatch(r"-?\d+", s):
        return COLOR_NAMES.get(int(s), s)
    if s.startswith("{"):
        try:
            return json.loads(s).get("name", s)
        except ValueError:
            return s
    if "matrix" in op and re.fullmatch(r"[0-9]{25}", s):
        return "▦"
    return DIRECTION_WORDS.get(s, s)


def proc_text(project, b):
    m = b.get("mutation") or {}
    if b["opcode"] == "procedures_definition":
        proto = project.blocks.get(b.get("inputs", {}).get("custom_block", [None, None])[1]) or {}
        m = proto.get("mutation") or {}
        return "define " + re.sub(r"%[snb]", "( )", m.get("proccode", "my block"))
    code = m.get("proccode", "my block")
    ids = json.loads(m.get("argumentids", "[]") or "[]")
    vals = iter(project.input_text(b, i) for i in ids)
    return re.sub(r"%[snb]", lambda _: next(vals, "?"), code)


TEXT = {
    # events
    "flipperevents_whenProgramStarts": "when program starts",
    "flipperevents_whenColor": "when {PORT} is color {OPTION}",
    "flipperevents_whenPressed": "when {PORT} is {@OPTION}",
    "flipperevents_whenDistance": "when {PORT} is {@COMPARATOR} {VALUE} {@UNIT}",
    "flipperevents_whenButton": "when {@BUTTON} button {@EVENT}",
    "flipperevents_whenCondition": "when {CONDITION}",
    "flipperevents_whenTimer": "when timer > {VALUE}",
    "flipperevents_whenOrientation": "when hub {VALUE} is up",
    "flipperevents_whenGesture": "when hub is {@EVENT}",
    "event_whenbroadcastreceived": "when I receive {@BROADCAST_OPTION}",
    "event_broadcast": "broadcast {BROADCAST_INPUT}",
    "event_broadcastandwait": "broadcast {BROADCAST_INPUT} and wait",
    # movement
    "flippermove_move": "move {DIRECTION} for {VALUE} {@UNIT}",
    "flippermove_startMove": "start moving {DIRECTION}",
    "flippermove_steer": "move steering {STEERING} for {VALUE} {@UNIT}",
    "flippermove_startSteer": "start moving steering {STEERING}",
    "flippermove_stopMove": "stop moving",
    "flippermove_movementSpeed": "set movement speed to {SPEED} %",
    "flippermove_setMovementPair": "set movement motors to {PAIR}",
    "flippermove_setDistance": "set 1 motor rotation to {DISTANCE} {@UNIT}",
    "flippermoremove_startDualSpeed": "start moving with {LEFT} % and {RIGHT} % speed",
    "flippermoremove_moveDualSpeed": "move with {LEFT} % and {RIGHT} % speed for {VALUE} {@UNIT}",
    "flippermoremove_startDualPower": "start moving with {LEFT} % and {RIGHT} % power",
    # motors
    "flippermotor_motorTurnForDirection": "{PORT} run {DIRECTION} for {VALUE} {@UNIT}",
    "flippermotor_motorGoDirectionToPosition": "{PORT} go {@DIRECTION} to position {POSITION}",
    "flippermotor_motorStartDirection": "{PORT} start motor {DIRECTION}",
    "flippermotor_motorStop": "{PORT} stop motor",
    "flippermotor_motorSetSpeed": "{PORT} set speed to {SPEED} %",
    "flippermotor_absolutePosition": "{PORT} position",
    "flippermotor_speed": "{PORT} speed",
    "flippermoremotor_motorSetDegreeCounted": "{PORT} set relative position to {VALUE}",
    "flippermoremotor_position": "{PORT} relative position",
    "flippermoremotor_motorStartPower": "{PORT} start motor at {POWER} % power",
    # light
    "flipperlight_lightDisplayText": "write {TEXT}",
    "flipperlight_lightDisplayImageOn": "turn on {MATRIX}",
    "flipperlight_lightDisplayImageOnForTime": "turn on {MATRIX} for {VALUE} seconds",
    "flipperlight_lightDisplayOff": "turn off pixels",
    "flipperlight_lightDisplaySetPixel": "set pixel {X} , {Y} to {BRIGHTNESS} %",
    "flipperlight_lightDisplaySetBrightness": "set pixel brightness to {BRIGHTNESS} %",
    "flipperlight_centerButtonLight": "set Center Button light to {COLOR}",
    "flipperlight_ultrasonicLightUp": "{PORT} light up {VALUE}",
    # sound
    "flippersound_playSoundUntilDone": "play sound {SOUND} until done",
    "flippersound_playSound": "start sound {SOUND}",
    "flippersound_beepForTime": "play beep {NOTE} for {DURATION} seconds",
    "flippersound_beep": "start playing beep {NOTE}",
    "flippersound_stopSound": "stop all sounds",
    # sensors
    "flippersensors_isColor": "{PORT} is color {VALUE} ?",
    "flippersensors_color": "{PORT} color",
    "flippersensors_isReflectivity": "{PORT} reflection is {@COMPARATOR} {VALUE} % ?",
    "flippersensors_reflectivity": "{PORT} reflection",
    "flippersensors_isDistance": "{PORT} is {@COMPARATOR} {VALUE} {@UNIT} ?",
    "flippersensors_distance": "{PORT} distance in {@UNIT}",
    "flippersensors_isPressed": "{PORT} is {@OPTION} ?",
    "flippersensors_force": "{PORT} pressure in {@UNIT}",
    "flippersensors_orientationAxis": "{@AXIS} angle",
    "flippersensors_resetYaw": "set yaw angle to 0",
    "flippersensors_buttonIsPressed": "{@BUTTON} button {@EVENT} ?",
    "flippersensors_timer": "timer",
    "flippersensors_resetTimer": "reset timer",
    # control
    "control_wait": "wait {DURATION} seconds",
    "control_wait_until": "wait until {CONDITION}",
    "control_repeat": "repeat {TIMES}",
    "control_forever": "forever",
    "control_if": "if {CONDITION} then",
    "control_if_else": "if {CONDITION} then",
    "control_repeat_until": "repeat until {CONDITION}",
    "control_stop": "stop {@STOP_OPTION}",
    "flippercontrol_stopOtherStacks": "stop other stacks",
    # operators
    "operator_add": "{NUM1} + {NUM2}", "operator_subtract": "{NUM1} - {NUM2}",
    "operator_multiply": "{NUM1} × {NUM2}", "operator_divide": "{NUM1} / {NUM2}",
    "operator_mod": "{NUM1} mod {NUM2}", "operator_random": "pick random {FROM} to {TO}",
    "operator_gt": "{OPERAND1} > {OPERAND2}", "operator_lt": "{OPERAND1} < {OPERAND2}",
    "operator_equals": "{OPERAND1} = {OPERAND2}", "operator_and": "{OPERAND1} and {OPERAND2}",
    "operator_or": "{OPERAND1} or {OPERAND2}", "operator_not": "not {OPERAND}",
    "operator_join": "join {STRING1} {STRING2}", "operator_letter_of": "letter {LETTER} of {STRING}",
    "operator_length": "length of {STRING}", "operator_contains": "{STRING1} contains {STRING2} ?",
    "operator_round": "round {NUM}", "operator_mathop": "{@OPERATOR} of {NUM}",
    # variables
    "data_variable": "{@VARIABLE}", "data_setvariableto": "set {@VARIABLE} to {VALUE}",
    "data_changevariableby": "change {@VARIABLE} by {VALUE}",
    "data_listcontents": "{@LIST}", "data_addtolist": "add {ITEM} to {@LIST}",
    "data_deleteoflist": "delete {INDEX} of {@LIST}", "data_deletealloflist": "delete all of {@LIST}",
    "data_itemoflist": "item {INDEX} of {@LIST}", "data_lengthoflist": "length of {@LIST}",
    "data_listcontainsitem": "{@LIST} contains {ITEM} ?",
    "data_insertatlist": "insert {ITEM} at {INDEX} of {@LIST}",
    "data_replaceitemoflist": "replace item {INDEX} of {@LIST} with {ITEM}",
    "procedures_call": "", "procedures_definition": "",
}


# --------------------------------------------------------------------- Scratch value rules
def num(v):
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, (int, float)):
        return v if not (isinstance(v, float) and math.isnan(v)) else 0
    try:
        f = float(str(v).strip())
        return int(f) if f.is_integer() and "." not in str(v) else f
    except ValueError:
        return 0


def compare(a, b):
    try:
        fa, fb = float(str(a).strip()), float(str(b).strip())
        if str(a).strip() and str(b).strip():
            return (fa > fb) - (fa < fb)
    except ValueError:
        pass
    sa, sb = str(a).lower(), str(b).lower()
    return (sa > sb) - (sa < sb)


def truthy(v):
    if isinstance(v, str):
        return v.lower() not in ("", "0", "false")
    return bool(v)


def fmt(v):
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


# --------------------------------------------------------------------- the interpreter
class _Stop(Exception):
    """Ends one thread (stop this stack)."""


class _Thread:
    def __init__(self, hat_id, gen):
        self.hat = hat_id
        self.gen = gen
        self.current = None
        self.done = False


class BlockRunner:
    """Runs a Word Blocks Project. Same start/stop/running interface as the other runtimes."""

    TICK = 0.01

    def __init__(self, world: W.World, console, on_state, on_action=None, on_event=None):
        self.world = world
        self.console = console
        self.on_state = on_state
        self.on_action = on_action or (lambda text, replace: None)
        self.on_event = on_event or (lambda ev: None)
        self.running = False
        self.project: Project | None = None
        self._thread = None
        self._stop = threading.Event()
        self.active: list[str] = []

    # -- control
    def start_project(self, project: Project):
        self.stop(wait=True)
        self.project = project
        self._stop.clear()
        self.running = True
        self._thread = threading.Thread(target=self._main, name="blocks", daemon=True)
        self._thread.start()

    def stop(self, wait=False):
        if self._thread and self._thread.is_alive():
            self._stop.set()
            self.rt._stop.set()
            if wait:
                self._thread.join(timeout=2)

    # -- main loop
    def _main(self):
        p = self.project
        self.world.program_reset()
        self.on_state(True)
        self.rt = Runtime(self.world, self.console, lambda s: None)
        self.mods = self.rt._modules()
        self.vars = {vid: v["value"] for vid, v in p.variables.items()}
        self.lists = {lid: list(l["value"]) for lid, l in p.lists.items()}
        self.move_pair = ("A", "B")
        self.move_speed = 50
        self.motor_speed = {}
        self.rotation_cm = WHEEL_CIRCUMFERENCE_CM
        self.timer0 = time.monotonic()
        self.threads: list[_Thread] = []
        self.hat_prev = {}
        self._fed = {}
        self.procs = self._find_procs()
        try:
            self._pair(*self.move_pair, quiet=True)
        except Exception:
            pass
        for h in p.hats:
            if p.blocks[h]["opcode"] == "flipperevents_whenProgramStarts":
                self._spawn(h)
        try:
            while not self._stop.is_set():
                self._check_hats()
                for th in list(self.threads):
                    if th.done:
                        continue
                    try:
                        next(th.gen)
                    except StopIteration:
                        th.done = True
                    except _Stop:
                        th.done = True
                self.threads = [t for t in self.threads if not t.done]
                active = [t.current for t in self.threads if t.current]
                if active != self.active:
                    self.active = active
                time.sleep(self.TICK)
        except StopProgram:
            pass
        except Exception as e:
            self.console(f"Error in block program: {e}\n")
        finally:
            self.active = []
            self.world.program_stop()
            self.running = False
            self.on_state(False)

    def _spawn(self, hat_id):
        # a hat that is already running restarts, like Scratch
        for t in self.threads:
            if t.hat == hat_id:
                t.done = True
        th = _Thread(hat_id, None)
        th.gen = self._run_script(th, self.project.blocks[hat_id].get("next"))
        self.threads.append(th)
        return th

    def _hat_running(self, hat_id):
        return any(t.hat == hat_id and not t.done for t in self.threads)

    def _check_hats(self):
        p = self.project
        for h in p.hats:
            b = p.blocks[h]
            op = b["opcode"]
            if op in ("flipperevents_whenProgramStarts", "event_whenbroadcastreceived", "procedures_definition"):
                continue
            try:
                val = self._hat_condition(b)
            except (StopProgram, _Stop):
                raise
            except Exception:
                val = False
            prev = self.hat_prev.get(h, False)
            self.hat_prev[h] = val
            if val and not prev and not self._hat_running(h):
                self.on_action("▶ " + p.text(h), False)
                self._spawn(h)

    def _hat_condition(self, b):
        op = b["opcode"]
        if op == "flipperevents_whenColor":
            return self._color(self.value(b, "PORT")) == str(self.value(b, "OPTION"))
        if op == "flipperevents_whenPressed":
            return self._pressed(self.value(b, "PORT"), self.project.field(b, "OPTION"))
        if op == "flipperevents_whenDistance":
            d = self._distance(self.value(b, "PORT"), self.project.field(b, "UNIT"))
            return self._cmp(d, self.project.field(b, "COMPARATOR"), num(self.value(b, "VALUE")))
        if op == "flipperevents_whenButton":
            return self._button(self.project.field(b, "BUTTON"), self.project.field(b, "EVENT"))
        if op == "flipperevents_whenCondition":
            return truthy(self.value(b, "CONDITION"))
        if op == "flipperevents_whenTimer":
            return time.monotonic() - self.timer0 > num(self.value(b, "VALUE"))
        return False

    # -- scripts
    def _run_script(self, th, bid):
        try:
            yield from self._run_seq(th, bid)
        except _Stop:
            pass
        th.current = None

    def _run_seq(self, th, bid, args=None):
        while bid and not self._stop.is_set():
            b = self.project.blocks.get(bid)
            if b is None:
                return
            th.current = bid
            yield from self._exec(th, bid, b, args)
            bid = b.get("next")

    def _substack(self, b, name):
        inp = b.get("inputs", {}).get(name)
        return inp[1] if inp and isinstance(inp[1], str) else None

    def _wait_op(self, op):
        while op is not None and not op._done():
            if self._stop.is_set():
                raise StopProgram()
            yield

    def _wait_seconds(self, s):
        end = time.monotonic() + max(0.0, s)
        while time.monotonic() < end:
            yield

    def _feed(self, bid):
        # blocks inside a fast loop would flood the feed: show each at most once a second
        now = time.monotonic()
        if now - self._fed.get(bid, -9) < 1.0:
            self._fed[bid] = now
            return
        self._fed[bid] = now
        self.on_action(self.project.text(bid), False)

    def _exec(self, th, bid, b, args):
        op = b["opcode"]
        p = self.project
        mp, mo = self.mods["motor_pair"], self.mods["motor"]
        # ---------------- control
        if op == "control_forever":
            sub = self._substack(b, "SUBSTACK")
            while True:
                yield from self._run_seq(th, sub, args)
                th.current = bid
                yield
        elif op == "control_repeat":
            sub = self._substack(b, "SUBSTACK")
            for _ in range(max(0, int(round(num(self.value(b, "TIMES", args)))))):
                yield from self._run_seq(th, sub, args)
                th.current = bid
                yield
        elif op == "control_repeat_until":
            sub = self._substack(b, "SUBSTACK")
            while not truthy(self.value(b, "CONDITION", args)):
                yield from self._run_seq(th, sub, args)
                th.current = bid
                yield
        elif op == "control_if":
            if truthy(self.value(b, "CONDITION", args)):
                yield from self._run_seq(th, self._substack(b, "SUBSTACK"), args)
        elif op == "control_if_else":
            key = "SUBSTACK" if truthy(self.value(b, "CONDITION", args)) else "SUBSTACK2"
            yield from self._run_seq(th, self._substack(b, key), args)
        elif op == "control_wait":
            self._feed(bid)
            yield from self._wait_seconds(num(self.value(b, "DURATION", args)))
        elif op == "control_wait_until":
            while not truthy(self.value(b, "CONDITION", args)):
                yield
        elif op == "control_stop":
            opt = p.field(b, "STOP_OPTION")
            self._feed(bid)
            if opt == "this script" or opt == "this stack":
                raise _Stop()
            if opt in ("other scripts in sprite", "other scripts in stage"):
                self._stop_others(th)
            else:
                raise StopProgram()
        elif op == "flippercontrol_stopOtherStacks":
            self._stop_others(th)
        # ---------------- events
        elif op in ("event_broadcast", "event_broadcastandwait"):
            msg = str(self.value(b, "BROADCAST_INPUT", args))
            self._feed(bid)
            started = [self._spawn(h) for h in p.hats if p.blocks[h]["opcode"] == "event_whenbroadcastreceived"
                       and str(p.field(p.blocks[h], "BROADCAST_OPTION")).lower() == msg.lower()]
            if op == "event_broadcastandwait":
                yield
                while any(not t.done for t in started):
                    yield
        # ---------------- movement
        elif op in ("flippermove_move", "flippermove_steer"):
            self._feed(bid)
            unit = p.field(b, "UNIT")
            value = num(self.value(b, "VALUE", args))
            speed = self._pair_speed()
            if op == "flippermove_move":
                d = str(self.value(b, "DIRECTION", args)).lower()
                steer = 100 if d in CW else -100 if d in CCW else 0
                if d in BACKWARD:
                    speed = -speed
            else:
                steer = self._steering(self.value(b, "STEERING", args))
            self._pair(*self.move_pair, quiet=True)
            if unit == "seconds":
                yield from self._wait_op(mp.move_for_time(0, int(value * 1000), steer, velocity=int(speed)))
            else:
                yield from self._wait_op(mp.move_for_degrees(0, int(round(self._degrees(value, unit))), steer,
                                                             velocity=int(speed)))
        elif op in ("flippermove_startMove", "flippermove_startSteer"):
            self._feed(bid)
            speed = self._pair_speed()
            if op == "flippermove_startMove":
                d = str(self.value(b, "DIRECTION", args)).lower()
                steer = 100 if d in CW else -100 if d in CCW else 0
                if d in BACKWARD:
                    speed = -speed
            else:
                steer = self._steering(self.value(b, "STEERING", args))
            self._pair(*self.move_pair, quiet=True)
            mp.move(0, steer, velocity=int(speed))
        elif op == "flippermove_stopMove":
            self._feed(bid)
            self._pair(*self.move_pair, quiet=True)
            mp.stop(0)
        elif op == "flippermove_movementSpeed":
            self._feed(bid)
            self.move_speed = max(-100, min(100, num(self.value(b, "SPEED", args))))
        elif op == "flippermove_setMovementPair":
            self._feed(bid)
            pair = re.sub(r"[^A-F]", "", str(self.value(b, "PAIR", args)).upper())
            if len(pair) == 2:
                self.move_pair = (pair[0], pair[1])
                self._pair(*self.move_pair)
        elif op == "flippermove_setDistance":
            self._feed(bid)
            d = num(self.value(b, "DISTANCE", args))
            self.rotation_cm = d * 2.54 if p.field(b, "UNIT") == "inches" else d
        elif op in ("flippermoremove_startDualSpeed", "flippermoremove_startDualPower"):
            self._feed(bid)
            vmax = self._pair_vmax()
            self._pair(*self.move_pair, quiet=True)
            mp.move_tank(0, int(num(self.value(b, "LEFT", args)) * vmax / 100),
                         int(num(self.value(b, "RIGHT", args)) * vmax / 100))
        elif op == "flippermoremove_moveDualSpeed":
            self._feed(bid)
            vmax = self._pair_vmax()
            lv = int(num(self.value(b, "LEFT", args)) * vmax / 100)
            rv = int(num(self.value(b, "RIGHT", args)) * vmax / 100)
            unit, value = p.field(b, "UNIT"), num(self.value(b, "VALUE", args))
            self._pair(*self.move_pair, quiet=True)
            if unit == "seconds":
                yield from self._wait_op(mp.move_tank_for_time(0, lv, rv, int(value * 1000)))
            else:
                yield from self._wait_op(mp.move_tank_for_degrees(0, int(self._degrees(value, unit)), lv, rv))
        # ---------------- motors
        elif op == "flippermotor_motorTurnForDirection":
            self._feed(bid)
            unit, value = p.field(b, "UNIT"), num(self.value(b, "VALUE", args))
            sign = -1 if str(self.value(b, "DIRECTION", args)).lower() in CCW else 1
            ops = []
            for port in self._ports(self.value(b, "PORT", args)):
                v = sign * self._motor_velocity(port)
                if unit == "seconds":
                    ops.append(mo.run_for_time(port, int(value * 1000), int(v)))
                else:
                    deg = value * 360 if unit == "rotations" else value
                    ops.append(mo.run_for_degrees(port, int(round(deg)), int(v)))
            for o in ops:
                yield from self._wait_op(o)
        elif op == "flippermotor_motorStartDirection":
            self._feed(bid)
            sign = -1 if str(self.value(b, "DIRECTION", args)).lower() in CCW else 1
            for port in self._ports(self.value(b, "PORT", args)):
                mo.run(port, int(sign * self._motor_velocity(port)))
        elif op == "flippermotor_motorStop":
            self._feed(bid)
            for port in self._ports(self.value(b, "PORT", args)):
                mo.stop(port)
        elif op == "flippermotor_motorSetSpeed":
            self._feed(bid)
            for port in self._ports(self.value(b, "PORT", args)):
                self.motor_speed[port] = max(-100, min(100, num(self.value(b, "SPEED", args))))
        elif op == "flippermotor_motorGoDirectionToPosition":
            self._feed(bid)
            d = str(p.field(b, "DIRECTION") or self.value(b, "DIRECTION", args)).lower()
            direction = 0 if d in CW else 1 if d in CCW else 2
            ops = [mo.run_to_absolute_position(port, int(num(self.value(b, "POSITION", args))) % 360,
                                               int(abs(self._motor_velocity(port))), direction=direction)
                   for port in self._ports(self.value(b, "PORT", args))]
            for o in ops:
                yield from self._wait_op(o)
        elif op == "flippermoremotor_motorSetDegreeCounted":
            self._feed(bid)
            for port in self._ports(self.value(b, "PORT", args)):
                mo.reset_relative_position(port, int(num(self.value(b, "VALUE", args))))
        elif op == "flippermoremotor_motorStartPower":
            self._feed(bid)
            for port in self._ports(self.value(b, "PORT", args)):
                mo.set_duty_cycle(port, int(num(self.value(b, "POWER", args)) * 100))
        # ---------------- light
        elif op == "flipperlight_lightDisplayText":
            self._feed(bid)
            yield from self._wait_op(self.mods["hub"].light_matrix.write(fmt(self.value(b, "TEXT", args))))
        elif op in ("flipperlight_lightDisplayImageOn", "flipperlight_lightDisplayImageOnForTime"):
            self._feed(bid)
            self.mods["hub"].light_matrix.show(self._matrix(self.value(b, "MATRIX", args)))
            if op.endswith("ForTime"):
                yield from self._wait_seconds(num(self.value(b, "VALUE", args)))
                self.mods["hub"].light_matrix.clear()
        elif op == "flipperlight_lightDisplayOff":
            self._feed(bid)
            self.mods["hub"].light_matrix.clear()
        elif op == "flipperlight_lightDisplaySetPixel":
            self._feed(bid)
            self.mods["hub"].light_matrix.set_pixel(int(num(self.value(b, "X", args))) - 1,
                                                    int(num(self.value(b, "Y", args))) - 1,
                                                    int(num(self.value(b, "BRIGHTNESS", args))))
        elif op == "flipperlight_centerButtonLight":
            self._feed(bid)
            self.mods["hub"].light.color(0, int(num(self.value(b, "COLOR", args))))
        # ---------------- sound
        elif op in ("flippersound_playSoundUntilDone", "flippersound_playSound"):
            self._feed(bid)
            name = str(self.value(b, "SOUND", args))
            if name.startswith("{"):
                try:
                    name = json.loads(name).get("name", name)
                except ValueError:
                    pass
            snd = p.sounds.get(name)
            self.on_event({"type": "sound", "name": name, "file": snd["file"] if snd else None})
            if op.endswith("UntilDone"):
                yield from self._wait_seconds(snd["seconds"] if snd else 1.0)
        elif op in ("flippersound_beepForTime", "flippersound_beep"):
            self._feed(bid)
            note = num(self.value(b, "NOTE", args)) or 60
            freq = 440 * 2 ** ((note - 69) / 12)
            dur = num(self.value(b, "DURATION", args)) if op.endswith("ForTime") else 1
            yield from self._wait_op(self.mods["hub"].sound.beep(int(freq), int(dur * 1000)))
        elif op == "flippersound_stopSound":
            self.on_event({"type": "stop"})
        # ---------------- sensors (statements)
        elif op == "flippersensors_resetYaw":
            self._feed(bid)
            self.mods["hub"].motion_sensor.reset_yaw(0)
        elif op == "flippersensors_resetTimer":
            self.timer0 = time.monotonic()
        # ---------------- variables
        elif op == "data_setvariableto":
            vid = (b["fields"]["VARIABLE"] + [None])[1]
            self.vars[vid] = self.value(b, "VALUE", args)
        elif op == "data_changevariableby":
            vid = (b["fields"]["VARIABLE"] + [None])[1]
            self.vars[vid] = num(self.vars.get(vid, 0)) + num(self.value(b, "VALUE", args))
        elif op.startswith("data_") and "LIST" in b.get("fields", {}):
            self._list_stmt(b, op, args)
        # ---------------- my blocks
        elif op == "procedures_call":
            code = (b.get("mutation") or {}).get("proccode")
            proc = self.procs.get(code)
            if proc:
                ids = json.loads((b.get("mutation") or {}).get("argumentids", "[]") or "[]")
                values = {proc["names"][i]: self.value(b, a, args) for i, a in enumerate(ids) if i < len(proc["names"])}
                yield from self._run_seq(th, proc["body"], values)
        elif op.startswith(("flipperevents_when", "event_when", "procedures_definition")):
            pass
        else:
            self.on_action(f"⚠ The simulator can't run this block yet: {p.text(bid)}", False)
        yield

    def _stop_others(self, th):
        for t in self.threads:
            if t is not th:
                t.done = True

    def _list_stmt(self, b, op, args):
        lid = (b["fields"]["LIST"] + [None])[1]
        lst = self.lists.setdefault(lid, [])
        if op == "data_addtolist":
            lst.append(self.value(b, "ITEM", args))
        elif op == "data_deletealloflist":
            lst.clear()
        elif op == "data_deleteoflist":
            i = self._index(self.value(b, "INDEX", args), lst)
            if i is not None:
                lst.pop(i)
        elif op == "data_insertatlist":
            i = self._index(self.value(b, "INDEX", args), lst + [None])
            if i is not None:
                lst.insert(i, self.value(b, "ITEM", args))
        elif op == "data_replaceitemoflist":
            i = self._index(self.value(b, "INDEX", args), lst)
            if i is not None:
                lst[i] = self.value(b, "ITEM", args)

    @staticmethod
    def _index(v, lst):
        if str(v) == "last":
            return len(lst) - 1 if lst else None
        i = int(num(v)) - 1
        return i if 0 <= i < len(lst) else None

    def _find_procs(self):
        p = self.project
        procs = {}
        for bid, b in p.blocks.items():
            if b["opcode"] == "procedures_definition":
                proto = p.blocks.get(b["inputs"]["custom_block"][1]) or {}
                m = proto.get("mutation") or {}
                procs[m.get("proccode")] = {"body": b.get("next"),
                                           "names": json.loads(m.get("argumentnames", "[]") or "[]")}
        return procs

    # -- values
    def value(self, b, name, args=None):
        inp = b.get("inputs", {}).get(name)
        if not inp:
            f = b.get("fields", {}).get(name)
            return f[0] if f else ""
        ref = inp[1]
        if isinstance(ref, list):
            return ref[1] if len(ref) > 1 else ""
        if ref is None:
            return ""
        return self.eval(ref, args)

    def eval(self, bid, args=None):
        p = self.project
        b = p.blocks.get(bid)
        if b is None:
            return ""
        op = b["opcode"]
        if is_menu(b):
            return p.field(b)
        v = lambda n: self.value(b, n, args)
        if op == "operator_add":
            return num(v("NUM1")) + num(v("NUM2"))
        if op == "operator_subtract":
            return num(v("NUM1")) - num(v("NUM2"))
        if op == "operator_multiply":
            return num(v("NUM1")) * num(v("NUM2"))
        if op == "operator_divide":
            d = num(v("NUM2"))
            return num(v("NUM1")) / d if d else math.inf
        if op == "operator_mod":
            d = num(v("NUM2"))
            return num(v("NUM1")) % d if d else 0
        if op == "operator_random":
            a, c = num(v("FROM")), num(v("TO"))
            lo, hi = min(a, c), max(a, c)
            if isinstance(lo, int) and isinstance(hi, int):
                return random.randint(lo, hi)
            return random.uniform(lo, hi)
        if op == "operator_gt":
            return compare(v("OPERAND1"), v("OPERAND2")) > 0
        if op == "operator_lt":
            return compare(v("OPERAND1"), v("OPERAND2")) < 0
        if op == "operator_equals":
            return compare(v("OPERAND1"), v("OPERAND2")) == 0
        if op == "operator_and":
            return truthy(v("OPERAND1")) and truthy(v("OPERAND2"))
        if op == "operator_or":
            return truthy(v("OPERAND1")) or truthy(v("OPERAND2"))
        if op == "operator_not":
            return not truthy(v("OPERAND"))
        if op == "operator_join":
            return fmt(v("STRING1")) + fmt(v("STRING2"))
        if op == "operator_letter_of":
            s, i = fmt(v("STRING")), int(num(v("LETTER"))) - 1
            return s[i] if 0 <= i < len(s) else ""
        if op == "operator_length":
            return len(fmt(v("STRING")))
        if op == "operator_contains":
            return fmt(v("STRING2")).lower() in fmt(v("STRING1")).lower()
        if op == "operator_round":
            return int(math.floor(num(v("NUM")) + 0.5))
        if op == "operator_mathop":
            return mathop(p.field(b, "OPERATOR"), num(v("NUM")))
        if op == "data_variable":
            return self.vars.get((b["fields"]["VARIABLE"] + [None])[1], 0)
        if op == "data_listcontents":
            return " ".join(fmt(x) for x in self.lists.get((b["fields"]["LIST"] + [None])[1], []))
        if op == "data_itemoflist":
            lst = self.lists.get((b["fields"]["LIST"] + [None])[1], [])
            i = self._index(v("INDEX"), lst)
            return lst[i] if i is not None else ""
        if op == "data_lengthoflist":
            return len(self.lists.get((b["fields"]["LIST"] + [None])[1], []))
        if op == "data_listcontainsitem":
            lst = self.lists.get((b["fields"]["LIST"] + [None])[1], [])
            return any(compare(x, v("ITEM")) == 0 for x in lst)
        if op == "argument_reporter_string_number" or op == "argument_reporter_boolean":
            return (args or {}).get(p.field(b, "VALUE"), "")
        # sensors
        if op == "flippersensors_isColor":
            return self._color(v("PORT")) == str(v("VALUE"))
        if op == "flippersensors_color":
            return int(self._color(v("PORT")))
        if op == "flippersensors_reflectivity":
            return self._reflection(v("PORT"))
        if op == "flippersensors_isReflectivity":
            return self._cmp(self._reflection(v("PORT")), p.field(b, "COMPARATOR"), num(v("VALUE")))
        if op == "flippersensors_isDistance":
            return self._cmp(self._distance(v("PORT"), p.field(b, "UNIT")), p.field(b, "COMPARATOR"), num(v("VALUE")))
        if op == "flippersensors_distance":
            d = self._distance(v("PORT"), p.field(b, "UNIT"))
            return d if d is not None else -1
        if op == "flippersensors_isPressed":
            return self._pressed(v("PORT"), p.field(b, "OPTION"))
        if op == "flippersensors_force":
            port = self._ports(v("PORT"))[0]
            f = self.mods["force_sensor"].force(port)
            return f / 10 if p.field(b, "UNIT") == "newton" else f
        if op == "flippersensors_orientationAxis":
            axis = p.field(b, "AXIS")
            yaw = self.mods["hub"].motion_sensor.tilt_angles()[0]
            return int(round(-yaw / 10)) if axis == "yaw" else 0
        if op == "flippersensors_buttonIsPressed":
            return self._button(p.field(b, "BUTTON"), p.field(b, "EVENT"))
        if op == "flippersensors_timer":
            return round(time.monotonic() - self.timer0, 2)
        if op == "flippermotor_absolutePosition":
            return self.mods["motor"].absolute_position(self._ports(v("PORT"))[0]) % 360
        if op == "flippermotor_speed":
            port = self._ports(v("PORT"))[0]
            m = self.mods["motor"]
            return int(m.velocity(port) / m.info(port)[1] * 100)
        if op == "flippermoremotor_position":
            return self.mods["motor"].relative_position(self._ports(v("PORT"))[0])
        return 0

    # -- helpers
    @staticmethod
    def _ports(v):
        letters = re.sub(r"[^A-F]", "", str(v).upper())
        return [W.PORTS.index(c) for c in letters] or [0]

    def _color(self, port_value):
        return str(self.mods["color_sensor"].color(self._ports(port_value)[0]))

    def _reflection(self, port_value):
        return self.mods["color_sensor"].reflection(self._ports(port_value)[0])

    def _distance(self, port_value, unit):
        mm = self.mods["distance_sensor"].distance(self._ports(port_value)[0])
        if mm < 0:
            return None
        if unit == "inches":
            return mm / 25.4
        if unit == "%":
            return mm / 20
        return mm / 10

    def _pressed(self, port_value, option):
        port = self._ports(port_value)[0]
        pressed = self.mods["force_sensor"].pressed(port)
        if option == "released":
            return not pressed
        if option == "hardpressed":
            return self.mods["force_sensor"].force(port) >= 80
        return pressed

    def _button(self, which, event):
        hb = self.mods["hub"].button
        pressed = bool(hb.pressed(hb.LEFT if which == "left" else hb.RIGHT))
        return not pressed if event == "released" else pressed

    @staticmethod
    def _cmp(a, comparator, b):
        if a is None:
            return comparator == ">"   # nothing in sight counts as far away
        return {"<": a < b, ">": a > b, "=": abs(a - b) < 0.5}.get(comparator, False)

    def _pair(self, left, right, quiet=False):
        mp = self.mods["motor_pair"]
        mp.pair(0, W.PORTS.index(left), W.PORTS.index(right))
        if not quiet:
            self.on_action(f"Using motors {left} (left) and {right} (right) for moving", False)

    def _pair_vmax(self):
        m = self.world.motors
        return min(m[p].vmax if p in m else 1110 for p in self.move_pair)

    def _pair_speed(self):
        return self.move_speed * self._pair_vmax() / 100

    def _motor_velocity(self, port):
        letter = W.PORTS[port]
        m = self.world.motors.get(letter)
        vmax = m.vmax if m else 1110
        return self.motor_speed.get(port, 75) * vmax / 100

    def _degrees(self, value, unit):
        if unit == "cm":
            return value / self.rotation_cm * 360
        if unit == "inches":
            return value * 2.54 / self.rotation_cm * 360
        if unit == "rotations":
            return value * 360
        return value  # degrees

    @staticmethod
    def _steering(v):
        m = re.search(r"-?((\d*\.?\d+)|(\d+\.?))$", str(v))
        return max(-100, min(100, int(round(float(m.group(0)))))) if m else 0

    @staticmethod
    def _matrix(v):
        s = str(v)
        if re.fullmatch(r"[0-9]{25}", s):
            return [int(c) * 100 // 9 for c in s]
        return [0] * 25


def mathop(name, x):
    try:
        return {
            "abs": abs, "floor": math.floor, "ceiling": math.ceil, "sqrt": math.sqrt,
            "sin": lambda a: math.sin(math.radians(a)), "cos": lambda a: math.cos(math.radians(a)),
            "tan": lambda a: math.tan(math.radians(a)), "asin": lambda a: math.degrees(math.asin(a)),
            "acos": lambda a: math.degrees(math.acos(a)), "atan": lambda a: math.degrees(math.atan(a)),
            "ln": math.log, "log": math.log10, "e ^": math.exp, "10 ^": lambda a: 10 ** a,
        }[name](x)
    except (KeyError, ValueError):
        return 0
