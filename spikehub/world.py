"""The simulated hub, its devices, and the robot driving on a mat.

World units: centimetres, degrees. World coordinates have y pointing up;
heading 90 means the robot faces the top of the mat.
"""
from __future__ import annotations

import math
import threading
import time

TICK = 0.01  # physics step in seconds

PORTS = "ABCDEF"

# color ids used by the hub (same values as the `color` module)
COLOR_IDS = {"black": 0, "magenta": 1, "purple": 2, "blue": 3, "azure": 4, "turquoise": 5,
             "green": 6, "yellow": 7, "orange": 8, "red": 9, "white": 10}
# raw rgb (0..1024) and reflection the color sensor reports over each surface
SURFACE = {
    "white": ((1000, 1000, 1000), 100), "black": ((40, 40, 50), 6),
    "red": ((900, 120, 110), 45), "green": ((130, 620, 220), 30),
    "blue": ((110, 260, 880), 28), "yellow": ((980, 900, 160), 80),
    "magenta": ((900, 150, 700), 50), "azure": ((300, 700, 1000), 55),
    "orange": ((1000, 450, 100), 60), "purple": ((420, 150, 800), 25),
    "turquoise": ((150, 850, 800), 50),
}

WHEEL_DIAMETER = 5.6   # cm, the standard SPIKE Prime wheel
AXLE_TRACK = 11.2      # cm between wheel centres
ROBOT_RADIUS = 9.0     # cm, used for collisions
SENSOR_OFFSET = {"color": (8.0, 0.0), "distance": (10.0, 0.0), "force": (11.0, 0.0)}
# Grabber arm: the motor with role "arm". Turning it ARM_DOWN_DEG or more from where it started
# lowers it; a cube in ARM_ZONE (robot frame: cm ahead, cm to the side) is then carried.
ARM_DOWN_DEG = 45
ARM_ZONE = (7.0, 17.0, 6.0)

MOTOR_MAX = {"medium": 1110, "large": 1050, "small": 660}
MOTOR_TYPE_ID = {"medium": 0x30, "large": 0x31, "small": 0x41}

# Motor end states (motor.COAST etc.)
COAST, BRAKE, HOLD, CONTINUE, SMART_COAST, SMART_BRAKE = 0, 1, 2, 3, 4, 5


def default_config():
    return {
        "A": {"type": "motor", "model": "medium", "role": "left"},
        "B": {"type": "motor", "model": "medium", "role": "right"},
        "C": {"type": "color"},
        "D": {"type": "distance"},
        "E": {"type": "force"},
        "F": {"type": "motor", "model": "medium", "role": "arm"},
    }


# ---------------------------------------------------------------- mats
def _border(w, h, t=2):
    return [{"kind": "wall", "x": -t, "y": -t, "w": w + 2 * t, "h": t},
            {"kind": "wall", "x": -t, "y": h, "w": w + 2 * t, "h": t},
            {"kind": "wall", "x": -t, "y": 0, "w": t, "h": h},
            {"kind": "wall", "x": w, "y": 0, "w": t, "h": h}]


def _smooth(points, rounds=3):
    """Chaikin corner cutting, keeps the end points."""
    for _ in range(rounds):
        out = [points[0]]
        for (ax, ay), (bx, by) in zip(points, points[1:]):
            out += [[ax * .75 + bx * .25, ay * .75 + by * .25], [ax * .25 + bx * .75, ay * .25 + by * .75]]
        out.append(points[-1])
        points = out
    return [[round(x, 2), round(y, 2)] for x, y in points]


def _oval(cx, cy, rx, ry, n=48):
    return [[round(cx + rx * math.cos(2 * math.pi * i / n), 2),
             round(cy + ry * math.sin(2 * math.pi * i / n), 2)] for i in range(n + 1)]


MATS = {
    "playground": {
        "name": "Playground", "w": 200, "h": 120,
        "start": {"x": 25, "y": 20, "heading": 90},
        "hint": "Drive to the colored squares, follow the black loop, stop before the wall.",
        "shapes": [
            {"kind": "line", "color": "black", "width": 2.5, "points": _oval(120, 62, 52, 34)},
            {"kind": "rect", "color": "red", "x": 8, "y": 90, "w": 22, "h": 22},
            {"kind": "rect", "color": "blue", "x": 40, "y": 90, "w": 22, "h": 22},
            {"kind": "rect", "color": "green", "x": 8, "y": 58, "w": 22, "h": 22},
            {"kind": "rect", "color": "yellow", "x": 40, "y": 58, "w": 22, "h": 22},
            {"kind": "wall", "x": 183, "y": 20, "w": 6, "h": 80},
        ],
    },
    "line": {
        "name": "Line track", "w": 200, "h": 120,
        "start": {"x": 100, "y": 22, "heading": 0},
        "hint": "Follow the black line with the color sensor. Stop on the red square.",
        "shapes": [
            {"kind": "line", "color": "black", "width": 2.5, "points": _smooth([
                [100, 20], [160, 20], [180, 35], [180, 60], [150, 75], [150, 95],
                [120, 102], [80, 102], [50, 95], [50, 75], [20, 60], [20, 35], [40, 20], [80, 20]])},
            {"kind": "rect", "color": "red", "x": 78, "y": 13, "w": 8, "h": 14},
        ],
    },
    "camp1": {
        "name": "Camp 1: Drive a square", "w": 160, "h": 100,
        "start": {"x": 50, "y": 25, "heading": 0},
        "hint": "Follow the path: 40 cm sides, turning left at each corner, and finish back on the start circle.",
        # "guide" and "label" shapes are only drawn: sensors don't see them
        "shapes": [
            {"kind": "guide", "points": [[50, 25], [90, 25], [90, 65], [50, 65], [50, 31]], "arrow": True},
            {"kind": "label", "x": 50, "y": 13, "text": "START"},
            {"kind": "label", "x": 70, "y": 45, "text": "40 cm × 40 cm"},
        ],
    },
    "camp2": {
        "name": "Camp 2: Stop and grab", "w": 160, "h": 100,
        "start": {"x": 30, "y": 50, "heading": 0},
        "hint": "The marker is 30 cm in front of the distance sensor. Stop at it, lower the arm to grab the cube, and back away.",
        "shapes": [
            {"kind": "zone", "x": 12, "y": 38, "w": 36, "h": 24, "color": "#fff1b8", "label": "HOME", "home": True},
            {"kind": "marker", "x": 70, "y": 46, "w": 6, "h": 8, "label": "MARKER"},
            {"kind": "label", "x": 55, "y": 64, "text": "30 cm"},
        ],
        "cubes": [{"x": 65, "y": 50, "size": 5, "color": "#e0312b", "name": "Cube"}],
    },
    "relay": {
        "name": "Camp 2: Relay race", "w": 160, "h": 100,
        "start": {"x": 30, "y": 50, "heading": 0},
        "hint": "Four batons wait at the marker. Bring them home one at a time.",
        "shapes": [
            {"kind": "zone", "x": 12, "y": 38, "w": 36, "h": 24, "color": "#fff1b8", "label": "HOME", "home": True},
            {"kind": "marker", "x": 70, "y": 46, "w": 6, "h": 8, "label": "MARKER"},
            {"kind": "label", "x": 55, "y": 64, "text": "30 cm"},
        ],
        "cubes": [{"x": 63 + (i % 2) * 2.6, "y": 48.7 + (i // 2) * 2.6, "size": 2.4, "color": c, "name": n}
                  for i, (c, n) in enumerate([("#e0312b", "Red baton"), ("#1f6fe0", "Blue baton"),
                                              ("#ffd21a", "Yellow baton"), ("#1aa64a", "Green baton")])],
    },
    "maze": {
        "name": "Maze", "w": 160, "h": 120,
        "start": {"x": 20, "y": 18, "heading": 90},
        "hint": "Use the distance sensor to find a way to the green square.",
        "shapes": [
            {"kind": "rect", "color": "green", "x": 128, "y": 92, "w": 24, "h": 22},
            {"kind": "wall", "x": 40, "y": 0, "w": 5, "h": 80},
            {"kind": "wall", "x": 80, "y": 40, "w": 5, "h": 80},
            {"kind": "wall", "x": 120, "y": 0, "w": 5, "h": 80},
        ],
    },
}


def _point_in_rect(px, py, r):
    return r["x"] <= px <= r["x"] + r["w"] and r["y"] <= py <= r["y"] + r["h"]


def _dist_point_segment(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _circle_hits_rect(cx, cy, rad, r):
    nx = max(r["x"], min(cx, r["x"] + r["w"]))
    ny = max(r["y"], min(cy, r["y"] + r["h"]))
    return math.hypot(cx - nx, cy - ny) < rad


def _ray_rect(ox, oy, dx, dy, r):
    """Distance along ray (unit dir) to rect, or None."""
    tmin, tmax = -math.inf, math.inf
    for o, d, lo, hi in ((ox, dx, r["x"], r["x"] + r["w"]), (oy, dy, r["y"], r["y"] + r["h"])):
        if abs(d) < 1e-9:
            if o < lo or o > hi:
                return None
        else:
            t1, t2 = (lo - o) / d, (hi - o) / d
            tmin, tmax = max(tmin, min(t1, t2)), min(tmax, max(t1, t2))
    if tmax < max(tmin, 0):
        return None
    return max(tmin, 0)


# ---------------------------------------------------------------- devices
class Motor:
    def __init__(self, model="medium"):
        self.model = model
        self.pos = 0.0          # relative position (deg), what the program sees
        self.offset = 0.0       # relative_position = pos - offset
        self.vel = 0.0          # actual deg/s
        self.cmd = ("stop", BRAKE)
        self.accel = 1000.0
        self.decel = 1000.0
        self.duty = None        # set_duty_cycle value, -10000..10000
        self.moved = 0.0        # degrees turned during the last step
        self.stalled = False

    @property
    def vmax(self):
        return MOTOR_MAX.get(self.model, 1110)

    def target_velocity(self, now):
        kind = self.cmd[0]
        if kind == "run":
            return self.cmd[1]
        if kind == "deg":
            return self.cmd[1]
        if kind == "time":
            return self.cmd[1] if now < self.cmd[2] else 0.0
        if kind == "duty":
            return self.cmd[1] / 10000 * self.vmax
        return 0.0

    def busy(self):
        return self.cmd[0] in ("deg", "time")

    def step(self, dt, now):
        kind = self.cmd[0]
        tv = max(-self.vmax, min(self.vmax, self.target_velocity(now)))
        if kind == "stop" and self.cmd[1] in (COAST, SMART_COAST):
            # coasting: slow down gently
            rate = 2500
        elif kind == "stop":
            rate = 20000  # brake / hold
        else:
            rate = self.accel if abs(tv) > abs(self.vel) else self.decel
        dv = tv - self.vel
        self.vel += max(-rate * dt, min(rate * dt, dv))
        move = self.vel * dt
        before = self.pos
        if kind == "deg":
            _, v, start, target, stop = self.cmd
            done_sofar = abs(self.pos - start)
            if done_sofar + abs(move) >= abs(target):
                self.pos = start + math.copysign(abs(target), target)
                self.moved = self.pos - before   # the robot moves exactly as far as the wheel turned
                self._finish(stop)
                return
        self.pos += move
        self.moved = move
        if kind == "time" and now >= self.cmd[2]:
            self._finish(self.cmd[3])

    def _finish(self, stop):
        if stop == CONTINUE:
            self.cmd = ("run", self.vel)
        else:
            self.cmd = ("stop", stop)
            if stop not in (COAST, SMART_COAST):
                self.vel = 0.0

    def relative(self):
        return int(round(self.pos - self.offset))

    def absolute(self):
        a = int(round(self.pos)) % 360
        return a - 360 if a >= 180 else a

    def power(self):
        return int(max(-10000, min(10000, self.vel / self.vmax * 10000)))


# ---------------------------------------------------------------- world
class World:
    def __init__(self, mat="playground"):
        self.lock = threading.RLock()
        self.config = default_config()
        self.motors: dict[str, Motor] = {}
        self.pairs: dict[int, tuple[str, str]] = {}
        self.pixels = [0] * 25
        self.scroll = None          # active light_matrix.write animation
        self.power_light = "white"
        self.buttons = {"left": False, "right": False}
        self.button_since = {"left": 0.0, "right": 0.0}
        self.force_manual = False
        self.yaw_offset = 0.0
        self.events: list[dict] = []   # one-shot events for the UI (sounds)
        self.trail: list[tuple[float, float]] = []
        self.distance_pixels = [0, 0, 0, 0]
        self.config_version = 0
        self.cubes: list[dict] = []
        self.carried = None
        self.arm_ref = 0.0
        self.set_mat(mat)
        self.apply_config(self.config)
        self._running = False

    # -- setup
    def set_mat(self, key):
        with self.lock:
            self.mat_key = key if key in MATS else "playground"
            self.mat = MATS[self.mat_key]
            # markers are solid objects: the robot bumps into them and the distance sensor sees them
            self.walls = [s for s in self.mat["shapes"] if s["kind"] in ("wall", "marker")] + \
                _border(self.mat["w"], self.mat["h"])
            self.reset_robot()

    def reset_robot(self, x=None, y=None, heading=None):
        with self.lock:
            s = self.mat["start"]
            self.x = s["x"] if x is None else x
            self.y = s["y"] if y is None else y
            self.heading = s["heading"] if heading is None else heading
            self.yaw_offset = self.heading
            self.trail = [(self.x, self.y)]
            self.cubes = [dict(c) for c in self.mat.get("cubes", [])]
            self.carried = None
            m = self.arm_motor()
            self.arm_ref = m.pos if m else 0.0

    # -- grabber arm and cubes
    def arm_port(self):
        return next((p for p, d in self.config.items()
                     if d.get("type") == "motor" and d.get("role") == "arm" and p in self.motors), None)

    def arm_motor(self):
        p = self.arm_port()
        return self.motors.get(p) if p else None

    def arm_down(self):
        m = self.arm_motor()
        return bool(m) and abs(m.pos - self.arm_ref) >= ARM_DOWN_DEG

    def home_zone(self):
        return next((s for s in self.mat["shapes"] if s["kind"] == "zone" and s.get("home")), None)

    def _update_cubes(self):
        if not self.cubes:
            return
        r = math.radians(self.heading)
        cos, sin = math.cos(r), math.sin(r)
        home = self.home_zone()
        down = self.arm_down()
        if self.carried is not None:
            c = self.carried
            if down:
                c["x"] = self.x + c["ox"] * cos - c["oy"] * sin
                c["y"] = self.y + c["ox"] * sin + c["oy"] * cos
                return
            self.carried = None
            if home and _point_in_rect(c["x"], c["y"], home):
                n = sum(1 for k in self.cubes if _point_in_rect(k["x"], k["y"], home))
                self.events.append({"type": "notice", "text": f"{c.get('name', 'Cube')} delivered home ({n} of {len(self.cubes)})"})
            return
        if not down:
            return
        best = None
        for c in self.cubes:
            if home and len(self.mat.get("cubes", [])) > 1 and _point_in_rect(c["x"], c["y"], home):
                continue   # relay: don't pick delivered batons up again
            dx, dy = c["x"] - self.x, c["y"] - self.y
            ox, oy = dx * cos + dy * sin, -dx * sin + dy * cos
            if ARM_ZONE[0] <= ox <= ARM_ZONE[1] and abs(oy) <= ARM_ZONE[2] and (best is None or ox < best[1]):
                best = (c, ox, oy)
        if best:
            c, c["ox"], c["oy"] = best
            self.carried = c
            self.events.append({"type": "notice", "text": f"Grabbed the {c.get('name', 'cube').lower()}"})

    def apply_config(self, cfg):
        with self.lock:
            self.config = cfg
            old = self.motors
            self.motors = {}
            for p, d in cfg.items():
                if d.get("type") == "motor":
                    m = old.get(p) or Motor(d.get("model", "medium"))
                    m.model = d.get("model", "medium")
                    self.motors[p] = m

    def drive_ports(self):
        left = right = None
        for p, d in self.config.items():
            if d.get("type") == "motor" and d.get("role") == "left":
                left = p
            if d.get("type") == "motor" and d.get("role") == "right":
                right = p
        return left, right

    def set_drive_ports(self, left, right):
        """Called when a program pairs two motors: treat them as the wheels."""
        with self.lock:
            for p, d in self.config.items():
                if d.get("type") == "motor" and d.get("role") in ("left", "right"):
                    d["role"] = "arm"
            for p, role in ((left, "left"), (right, "right")):
                if p in self.config and self.config[p].get("type") == "motor":
                    self.config[p]["role"] = role

    def device_at(self, port):
        return self.config.get(port, {}).get("type")

    def ensure_device(self, port, kind, avoid=()):
        """Make the robot match the program: put a `kind` device on `port`,
        moving whatever was there to the port the device came from (or a free one)."""
        with self.lock:
            if self.device_at(port) == kind:
                return
            candidates = [p for p in PORTS if p != port and p not in avoid and self.device_at(p) == kind]
            source = next((p for p in candidates if self.config[p].get("role") not in ("left", "right")), None) \
                or next(iter(candidates), None)
            moved = dict(self.config.get(port, {}))
            if source:
                new = dict(self.config[source])
                self.config[source] = moved if moved.get("type") else {}
            else:
                new = {"type": kind}
                if kind == "motor":
                    new.update(model="medium", role="arm")
                if moved.get("type"):
                    free = next((p for p in PORTS if not self.device_at(p) and p not in avoid), None)
                    if free:
                        self.config[free] = moved
            self.config[port] = new
            if source:  # the two ports swapped devices, so swap the motor objects too
                at_port, at_source = self.motors.pop(port, None), self.motors.pop(source, None)
                if at_source:
                    self.motors[port] = at_source
                if at_port:
                    self.motors[source] = at_port
            self.apply_config(self.config)
            self.config_version += 1
            self.events.append({"type": "notice", "text": f"Moved the {kind} to port {port} to match the program"})

    # -- program-side reset when a program starts
    def program_reset(self):
        with self.lock:
            for m in self.motors.values():
                m.cmd = ("stop", BRAKE)
                m.vel = 0.0
                m.accel = m.decel = 1000.0
            self.pairs = {}
            self.pixels = [0] * 25
            self.scroll = None
            self.power_light = "white"
            self.yaw_offset = self.heading
            if self.carried is None:
                m = self.arm_motor()
                self.arm_ref = m.pos if m else 0.0   # the arm starts "up" where it is

    def program_stop(self):
        with self.lock:
            for m in self.motors.values():
                m.cmd = ("stop", COAST)
            self.scroll = None

    # -- physics
    def start(self):
        if self._running:
            return
        self._running = True
        threading.Thread(target=self._loop, name="physics", daemon=True).start()

    def _loop(self):
        nxt = time.monotonic()
        while self._running:
            now = time.monotonic()
            with self.lock:
                self.step(TICK, now)
            nxt += TICK
            delay = nxt - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                nxt = time.monotonic()

    def step(self, dt, now):
        for m in self.motors.values():
            m.step(dt, now)
        left, right = self.drive_ports()
        k = math.pi * WHEEL_DIAMETER / 360.0  # cm per wheel degree
        # wheel speeds from how far each motor actually turned this step (left motor is mirrored)
        vl = -self.motors[left].moved / dt * k if left in self.motors else 0.0
        vr = self.motors[right].moved / dt * k if right in self.motors else 0.0
        v = (vl + vr) / 2
        omega = math.degrees((vr - vl) / AXLE_TRACK)
        nh = self.heading + omega * dt
        rad = math.radians(nh)
        nx = self.x + v * math.cos(rad) * dt
        ny = self.y + v * math.sin(rad) * dt
        self.heading = nh
        if not self._collides(nx, ny):
            self.x, self.y = nx, ny
            lx, ly = self.trail[-1]
            if math.hypot(nx - lx, ny - ly) > 0.8:
                self.trail.append((nx, ny))
                if len(self.trail) > 4000:
                    self.trail = self.trail[-4000:]
        self._update_cubes()
        if self.scroll:
            self._step_scroll(now)

    def _collides(self, x, y):
        return any(_circle_hits_rect(x, y, ROBOT_RADIUS, w) for w in self.walls)

    # -- light matrix text
    def start_scroll(self, frames, ms_per_frame, intensity):
        self.scroll = {"frames": frames, "ms": ms_per_frame, "t0": time.monotonic(),
                       "intensity": intensity}

    def _step_scroll(self, now):
        s = self.scroll
        i = int((now - s["t0"]) * 1000 / s["ms"])
        if i >= len(s["frames"]):
            self.pixels = [0] * 25
            self.scroll = None
            return
        self.pixels = [s["intensity"] if b else 0 for b in s["frames"][i]]

    # -- sensors
    def _sensor_point(self, kind):
        ox, oy = SENSOR_OFFSET[kind]
        r = math.radians(self.heading)
        return (self.x + ox * math.cos(r) - oy * math.sin(r),
                self.y + ox * math.sin(r) + oy * math.cos(r))

    def surface_color(self, dx=0.0, dy=0.0):
        px, py = self._sensor_point("color")
        px, py = px + dx, py + dy
        if not (0 <= px <= self.mat["w"] and 0 <= py <= self.mat["h"]):
            return None
        for s in reversed(self.mat["shapes"]):
            if s["kind"] == "rect" and _point_in_rect(px, py, s):
                return s["color"]
            if s["kind"] == "line":
                pts = s["points"]
                for (ax, ay), (bx, by) in zip(pts, pts[1:]):
                    if _dist_point_segment(px, py, ax, ay, bx, by) <= s["width"] / 2:
                        return s["color"]
        return "white"

    # the sensor sees a small spot, so readings blend near edges (lets line followers steer smoothly)
    _SPOT = [(0, 0)] + [(0.9 * math.cos(a * math.pi / 4), 0.9 * math.sin(a * math.pi / 4)) for a in range(8)]

    def color_reading(self):
        c = self.surface_color()
        if c is None:
            return -1, (0, 0, 0), 0
        rs = gs = bs = refl = 0
        for dx, dy in self._SPOT:
            s = self.surface_color(dx, dy) or "black"
            (r, g, b), f = SURFACE.get(s, SURFACE["white"])
            rs, gs, bs, refl = rs + r, gs + g, bs + b, refl + f
        n = len(self._SPOT)
        return COLOR_IDS.get(c, -1), (rs // n, gs // n, bs // n), int(round(refl / n))

    def distance_mm(self):
        ox, oy = self._sensor_point("distance")
        r = math.radians(self.heading)
        dx, dy = math.cos(r), math.sin(r)
        best = None
        for w in self.walls:
            t = _ray_rect(ox, oy, dx, dy, w)
            if t is not None and (best is None or t < best):
                best = t
        if best is None or best * 10 > 2000:
            return -1
        return max(40, int(best * 10))

    def force_value(self):
        fx, fy = self._sensor_point("force")
        bumped = any(_circle_hits_rect(fx, fy, 1.5, w) for w in self.walls)
        pressed = bumped or self.force_manual
        return (60 if pressed else 0), pressed

    def yaw(self):
        y = (self.heading - self.yaw_offset + 180) % 360 - 180
        return y

    # -- snapshot for the UI
    def snapshot(self):
        with self.lock:
            ports = {}
            for p in PORTS:
                d = self.config.get(p, {})
                t = d.get("type")
                info = {"type": t}
                if t == "motor" and p in self.motors:
                    m = self.motors[p]
                    info.update(model=m.model, role=d.get("role"), position=m.relative(),
                                absolute=m.absolute(), speed=int(m.vel), power=m.power())
                elif t == "color":
                    cid, rgb, refl = self.color_reading()
                    info.update(color=cid, rgb=rgb, reflection=refl)
                elif t == "distance":
                    info.update(distance=self.distance_mm())
                elif t == "force":
                    f, pr = self.force_value()
                    info.update(force=f, pressed=pr)
                ports[p] = info
            ev, self.events = self.events, []
            return {
                "robot": {"x": round(self.x, 2), "y": round(self.y, 2),
                          "heading": round(self.heading, 2)},
                "pixels": list(self.pixels),
                "light": self.power_light,
                "yaw": round(self.yaw(), 1),
                "ports": ports,
                "events": ev,
                "trail_len": len(self.trail),
                "cubes": [{k: c[k] for k in ("x", "y", "size", "color")} | {"carried": c is self.carried} for c in self.cubes],
                "arm_down": self.arm_down() if self.arm_port() else None,
                "config_version": self.config_version,
                "config": {p: dict(d) for p, d in self.config.items()},
            }
