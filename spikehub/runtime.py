"""Runs a SPIKE App 3 (hub OS 3) Python program against the simulated world.

The program gets fake versions of the hub modules (hub, motor, motor_pair,
color_sensor, distance_sensor, force_sensor, runloop, color, device, app, ...)
that drive `World` instead of real hardware.
"""
from __future__ import annotations

import asyncio
import builtins
import math
import sys
import threading
import time as _time
import traceback
import types

from . import world as W
from .world import PORTS, COLOR_IDS

PROGRAM_FILE = "program.py"


class StopProgram(BaseException):
    """Raised inside the program thread when the program is stopped."""


# ---------------------------------------------------------------- 5x5 font and images
_FONT_ROWS = {
    "A": ".#.|#.#|###|#.#|#.#", "B": "##.|#.#|##.|#.#|##.", "C": ".##|#..|#..|#..|.##",
    "D": "##.|#.#|#.#|#.#|##.", "E": "###|#..|##.|#..|###", "F": "###|#..|##.|#..|#..",
    "G": ".##|#..|#.#|#.#|.##", "H": "#.#|#.#|###|#.#|#.#", "I": "###|.#.|.#.|.#.|###",
    "J": "..#|..#|..#|#.#|.#.", "K": "#.#|#.#|##.|#.#|#.#", "L": "#..|#..|#..|#..|###",
    "M": "#...#|##.##|#.#.#|#...#|#...#", "N": "#..#|##.#|#.##|#..#|#..#",
    "O": ".#.|#.#|#.#|#.#|.#.", "P": "##.|#.#|##.|#..|#..", "Q": ".#.|#.#|#.#|##.|.##",
    "R": "##.|#.#|##.|#.#|#.#", "S": ".##|#..|.#.|..#|##.", "T": "###|.#.|.#.|.#.|.#.",
    "U": "#.#|#.#|#.#|#.#|###", "V": "#.#|#.#|#.#|#.#|.#.", "W": "#...#|#...#|#.#.#|##.##|#...#",
    "X": "#.#|#.#|.#.|#.#|#.#", "Y": "#.#|#.#|.#.|.#.|.#.", "Z": "###|..#|.#.|#..|###",
    "0": ".#.|#.#|#.#|#.#|.#.", "1": ".#.|##.|.#.|.#.|###", "2": "##.|..#|.#.|#..|###",
    "3": "##.|..#|.#.|..#|##.", "4": "#.#|#.#|###|..#|..#", "5": "###|#..|##.|..#|##.",
    "6": ".##|#..|###|#.#|###", "7": "###|..#|.#.|.#.|.#.", "8": "###|#.#|###|#.#|###",
    "9": "###|#.#|###|..#|##.", " ": "..|..|..|..|..", ".": ".|.|.|.|#", ",": "..|..|..|.#|#.",
    "!": "#|#|#|.|#", "?": "##.|..#|.#.|...|.#.", "-": "...|...|###|...|...",
    "+": "...|.#.|###|.#.|...", ":": ".|#|.|#|.", "'": "#|#|.|.|.", "=": "...|###|...|###|...",
    "/": "..#|..#|.#.|#..|#..", "%": "#.#|..#|.#.|#..|#.#", "(": ".#|#.|#.|#.|.#",
    ")": "#.|.#|.#|.#|#.", "<": "..#|.#.|#..|.#.|..#", ">": "#..|.#.|..#|.#.|#..",
}


def _glyph_cols(ch):
    rows = _FONT_ROWS.get(ch.upper(), _FONT_ROWS["?"]).split("|")
    w = len(rows[0])
    return [[1 if rows[r][c] == "#" else 0 for r in range(5)] for c in range(w)]


def _center(cols):
    pad = 5 - len(cols)
    left = pad // 2
    return [[0] * 5] * left + cols + [[0] * 5] * (pad - left)


def _cols_to_frame(cols):
    return [cols[c][r] for r in range(5) for c in range(5)]


def text_frames(text, ms_per_char):
    """Return (frames, ms_per_frame) for light_matrix.write."""
    if len(text) == 1:
        return [_cols_to_frame(_center(_glyph_cols(text)))], None
    cols = [[0] * 5] * 5
    for ch in text:
        cols += _glyph_cols(ch) + [[0] * 5]
    cols += [[0] * 5] * 5
    frames = [_cols_to_frame(cols[i:i + 5]) for i in range(len(cols) - 4)]
    per_frame = max(20, ms_per_char / 4)
    return frames, per_frame


_IMAGES = {
    "ROBOT": "99999:90909:99999:09090:99999", "HEART": "09090:99999:99999:09990:00900",
    "HEART_SMALL": "00000:09090:09990:00900:00000", "HAPPY": "00000:09090:00000:90009:09990",
    "SMILE": "00000:00000:00000:90009:09990", "SAD": "00000:09090:00000:09990:90009",
    "CONFUSED": "00000:09090:00000:09090:90909", "ANGRY": "90009:09090:00000:99999:90909",
    "ASLEEP": "00000:99099:00000:09990:00000", "SURPRISED": "09090:00000:00900:09090:00900",
    "SILLY": "90009:00000:99999:00909:00999", "FABULOUS": "99999:99099:00000:09090:09990",
    "MEH": "09090:00000:00090:00900:09000", "YES": "00000:00009:00090:90900:09000",
    "NO": "90009:09090:00900:09090:90009",
}
_CLOCK = ["CLOCK%d" % h for h in (12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11)]
_MORE = {
    "ARROW_N": "00900:09990:90909:00900:00900", "ARROW_NE": "00999:00099:00909:09000:90000",
    "ARROW_E": "00900:00090:99999:00090:00900", "ARROW_SE": "90000:09000:00909:00099:00999",
    "ARROW_S": "00900:00900:90909:09990:00900", "ARROW_SW": "00009:00090:90900:99000:99900",
    "ARROW_W": "00900:09000:99999:09000:00900", "ARROW_NW": "99900:99000:90900:00090:00009",
    "GO_RIGHT": "09000:00900:00090:00900:09000", "GO_LEFT": "00090:00900:09000:00900:00090",
    "GO_UP": "00000:00900:09090:90009:00000", "GO_DOWN": "00000:90009:09090:00900:00000",
    "TRIANGLE": "00000:00900:09090:99999:00000", "TRIANGLE_LEFT": "90000:99000:90900:90090:99999",
    "CHESSBOARD": "09090:90909:09090:90909:09090", "DIAMOND": "00900:09090:90009:09090:00900",
    "DIAMOND_SMALL": "00000:00900:09090:00900:00000", "SQUARE": "99999:90009:90009:90009:99999",
    "SQUARE_SMALL": "00000:09990:09090:09990:00000", "RABBIT": "90900:90900:99990:99090:99990",
    "COW": "90009:90009:99999:09990:00900", "MUSIC_CROTCHET": "00900:00900:00900:99900:99900",
    "MUSIC_QUAVER": "00900:00990:00909:99900:99900", "MUSIC_QUAVERS": "09999:09009:09009:99099:99099",
    "PITCHFORK": "90909:90909:99999:00900:00900", "XMAS": "00900:09990:00900:09990:99999",
    "PACMAN": "09999:99090:99900:99990:09999", "TARGET": "00900:09990:99099:09990:00900",
    "TSHIRT": "99099:99999:09990:09990:09990", "ROLLERSKATE": "00099:00099:99999:99999:09090",
    "DUCK": "09900:99900:09999:09990:00000", "HOUSE": "00900:09990:99999:09990:09090",
    "TORTOISE": "00000:09990:99999:09090:00000", "BUTTERFLY": "99099:99999:00900:99999:99099",
    "STICKFIGURE": "00900:99999:00900:09090:90009", "GHOST": "99999:90909:99999:99999:90909",
    "SWORD": "00900:00900:00900:09990:00900", "GIRAFFE": "99000:09000:09000:09990:09090",
    "SKULL": "09990:90909:99999:09990:09990", "UMBRELLA": "09990:99999:00900:90900:09900",
    "SNAKE": "99000:99099:09090:09990:00000",
}
IMAGE_NAMES = list(_IMAGES) + _CLOCK + list(_MORE)  # IMAGE_ROBOT = 1, ...


def _clock_image(i):
    px = [0] * 25
    a = math.radians(90 - i * 30)
    for t in (0, 1, 2):
        x = round(2 + t * math.cos(a))
        y = round(2 - t * math.sin(a))
        px[y * 5 + x] = 100
    return px


def image_pixels(n):
    if not 1 <= n <= len(IMAGE_NAMES):
        return [100 if (i % 6 == 0 or i % 4 == 0) and i not in (0, 24) else 0 for i in range(25)]
    name = IMAGE_NAMES[n - 1]
    if name.startswith("CLOCK"):
        return _clock_image(_CLOCK.index(name))
    pattern = (_IMAGES.get(name) or _MORE[name]).replace(":", "")
    return [int(c) * 100 // 9 for c in pattern]


# ---------------------------------------------------------------- awaitable operations
class Op:
    """What hub OS 3 returns from motion/sound/text calls: starts immediately,
    can optionally be awaited to wait until it has finished."""

    def __init__(self, rt: "Runtime", done, result=0):
        self._rt, self._done, self._result = rt, done, result

    def __await__(self):
        while not self._done():
            self._rt.check()
            yield from asyncio.sleep(0.005).__await__()
        return self._result

    def __repr__(self):
        return "<awaitable>"


def _const(**kw):
    return kw


# ---------------------------------------------------------------- runtime
class Runtime:
    def __init__(self, world: W.World, console, on_state):
        self.world = world
        self.console = console          # callable(str)
        self.on_state = on_state        # callable(running: bool)
        self._stop = threading.Event()
        self._thread = None
        self.running = False
        self.started_at = 0.0

    # -- control
    def start(self, source: str, filename=PROGRAM_FILE):
        self.stop(wait=True)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, args=(source, filename),
                                        name="program", daemon=True)
        self.running = True
        self.started_at = _time.monotonic()
        self._thread.start()

    def stop(self, wait=False):
        if self._thread and self._thread.is_alive():
            self._stop.set()
            if wait:
                self._thread.join(timeout=2)

    def check(self):
        if self._stop.is_set():
            raise StopProgram()

    def _done_after(self, seconds):
        end = _time.monotonic() + seconds
        return lambda: _time.monotonic() >= end

    # -- thread body
    def _run(self, source, filename):
        self.world.program_reset()
        self.on_state(True)
        mods = self._modules()
        real_import = builtins.__import__

        def sim_import(name, globals=None, locals=None, fromlist=(), level=0):
            root = name.split(".")[0]
            if root in mods:
                mod = mods[root]
                if fromlist or "." not in name:
                    if "." in name:  # from hub.x import y
                        for part in name.split(".")[1:]:
                            mod = getattr(mod, part)
                    return mod
                return mod
            return real_import(name, globals, locals, fromlist, level)

        sim_builtins = dict(vars(builtins))
        sim_builtins["__import__"] = sim_import
        sim_builtins["print"] = self._print
        sim_builtins["input"] = lambda *a: ""
        g = {"__name__": "__main__", "__builtins__": sim_builtins, "__file__": filename}

        def tracer(frame, event, arg):
            if frame.f_code.co_filename != filename:
                return None
            if self._stop.is_set():
                raise StopProgram()
            return local_tracer

        def local_tracer(frame, event, arg):
            if event == "line" and self._stop.is_set():
                raise StopProgram()
            return local_tracer

        sys.settrace(tracer)
        try:
            code = compile(source, filename, "exec")
            exec(code, g)
        except StopProgram:
            pass
        except SystemExit:
            pass
        except BaseException:
            et, ev, tb = sys.exc_info()
            lines = traceback.format_exception(et, ev, tb)
            # keep only frames from the program itself
            keep = [lines[0]] + [l for l in lines[1:-1] if filename in l] + [lines[-1]]
            self.console("".join(keep))
        finally:
            sys.settrace(None)
            self.world.program_stop()
            self.running = False
            self.on_state(False)

    def _print(self, *args, sep=" ", end="\n", **kw):
        self.check()
        self.console(sep.join(str(a) for a in args) + end)

    # -- helpers
    def _port(self, p):
        if isinstance(p, str):
            p = PORTS.index(p.upper())
        if not isinstance(p, int) or not 0 <= p < 6:
            raise ValueError("invalid port")
        return PORTS[p]

    def _motor(self, p):
        letter = self._port(p)
        if letter not in self.world.motors:
            self.world.ensure_device(letter, "motor")
        m = self.world.motors.get(letter)
        if m is None:
            raise OSError(19, "ENODEV: no motor on port %s" % letter)
        return m

    def _sensor(self, p, kind):
        letter = self._port(p)
        if self.world.device_at(letter) != kind:
            self.world.ensure_device(letter, kind)
        if self.world.device_at(letter) != kind:
            raise OSError(19, "ENODEV: no %s sensor on port %s" % (kind, letter))
        return letter

    # -- module construction
    def _modules(self):
        rt, world = self, self.world
        lock = world.lock

        def module(name, **attrs):
            m = types.ModuleType(name)
            m.__dict__.update(attrs)
            return m

        # ------------- color
        color = module("color", UNKNOWN=-1, **{k.upper(): v for k, v in COLOR_IDS.items()})

        # ------------- motor
        def m_cmd(m, cmd, accel=None, decel=None):
            if accel:
                m.accel = float(accel)
            if decel:
                m.decel = float(decel)
            m.cmd = cmd
            return cmd

        def op_until_replaced(m, cmd):
            return Op(rt, lambda: m.cmd is not cmd)

        def run(port, velocity, *, acceleration=1000):
            rt.check()
            with lock:
                m = rt._motor(port)
                m_cmd(m, ("run", float(velocity)), acceleration)

        def stop(port, *, stop=W.BRAKE):
            rt.check()
            with lock:
                rt._motor(port).cmd = ("stop", stop)

        def run_for_degrees(port, degrees, velocity, *, stop=W.BRAKE, acceleration=1000,
                            deceleration=1000):
            rt.check()
            with lock:
                m = rt._motor(port)
                sign = math.copysign(1, degrees) * math.copysign(1, velocity)
                v = abs(velocity) * sign
                if degrees == 0 or velocity == 0:
                    return Op(rt, lambda: True)
                cmd = m_cmd(m, ("deg", v, m.pos, abs(degrees) * sign, stop), acceleration, deceleration)
            return op_until_replaced(m, cmd)

        def run_for_time(port, duration, velocity, *, stop=W.BRAKE, acceleration=1000,
                         deceleration=1000):
            rt.check()
            with lock:
                m = rt._motor(port)
                cmd = m_cmd(m, ("time", float(velocity), _time.monotonic() + duration / 1000, stop),
                            acceleration, deceleration)
            return op_until_replaced(m, cmd)

        def _go_by(m, diff, velocity, stop, a, d):
            if diff == 0:
                m.cmd = ("stop", stop)
                return Op(rt, lambda: True)
            v = math.copysign(abs(velocity), diff)
            cmd = m_cmd(m, ("deg", v, m.pos, diff, stop), a, d)
            return op_until_replaced(m, cmd)

        def run_to_absolute_position(port, position, velocity, *, direction=2, stop=W.BRAKE,
                                     acceleration=1000, deceleration=1000):
            rt.check()
            with lock:
                m = rt._motor(port)
                diff = (position - m.absolute()) % 360       # 0..359 clockwise
                if direction == 0:     # clockwise
                    pass
                elif direction == 1:   # counterclockwise
                    diff = diff - 360 if diff else 0
                else:
                    short = diff - 360 if diff > 180 else diff
                    diff = short if direction == 2 else (short - 360 if short > 0 else short + 360)
                return _go_by(m, diff, velocity, stop, acceleration, deceleration)

        def run_to_relative_position(port, position, velocity, *, stop=W.BRAKE, acceleration=1000,
                                     deceleration=1000):
            rt.check()
            with lock:
                m = rt._motor(port)
                return _go_by(m, position - m.relative(), velocity, stop, acceleration, deceleration)

        def relative_position(port):
            rt.check()
            with lock:
                return rt._motor(port).relative()

        def reset_relative_position(port, position=0):
            with lock:
                m = rt._motor(port)
                m.offset = m.pos - position

        def absolute_position(port):
            rt.check()
            with lock:
                return rt._motor(port).absolute()

        def velocity(port):
            rt.check()
            with lock:
                return int(rt._motor(port).vel)

        def set_duty_cycle(port, pwm):
            with lock:
                rt._motor(port).cmd = ("duty", float(pwm))

        def get_duty_cycle(port):
            with lock:
                return rt._motor(port).power()

        def info(port):
            # used by compiled Word Blocks: info(port)[1] is the motor's top speed (deg/s)
            with lock:
                m = rt._motor(port)
                return ({"medium": 48, "large": 49, "small": 65}.get(m.model, 48), int(m.vmax))

        motor = module(
            "motor", run=run, stop=stop, run_for_degrees=run_for_degrees, run_for_time=run_for_time,
            run_to_absolute_position=run_to_absolute_position,
            run_to_relative_position=run_to_relative_position, relative_position=relative_position,
            reset_relative_position=reset_relative_position, absolute_position=absolute_position,
            velocity=velocity, set_duty_cycle=set_duty_cycle, get_duty_cycle=get_duty_cycle, info=info,
            COAST=W.COAST, BRAKE=W.BRAKE, HOLD=W.HOLD, CONTINUE=W.CONTINUE,
            SMART_COAST=W.SMART_COAST, SMART_BRAKE=W.SMART_BRAKE,
            CLOCKWISE=0, COUNTERCLOCKWISE=1, SHORTEST_PATH=2, LONGEST_PATH=3,
            READY=0, RUNNING=1, STALLED=2, CANCELLED=3, ERROR=4, DISCONNECTED=5,
        )

        # ------------- motor_pair
        def _pair(pair_id):
            p = world.pairs.get(pair_id)
            if p is None:
                raise RuntimeError("motor pair %d is not set up; call motor_pair.pair() first" % (pair_id + 1))
            return world.motors[p[0]], world.motors[p[1]]

        def pair(pair_id, left_motor, right_motor):
            with lock:
                l, r = rt._port(left_motor), rt._port(right_motor)
                for letter, avoid in ((l, (r,)), (r, (l,))):
                    if world.device_at(letter) != "motor":
                        world.ensure_device(letter, "motor", avoid=avoid)
                rt._motor(l), rt._motor(r)
                world.pairs[pair_id] = (l, r)
                world.set_drive_ports(l, r)

        def unpair(pair_id):
            with lock:
                world.pairs.pop(pair_id, None)

        def steer(vel, steering):
            s = max(-100, min(100, steering))
            if s >= 0:
                return vel, vel * (1 - s / 50)
            return vel * (1 + s / 50), vel

        def _pair_go(pair_id, lv, rv, mk_cmd, accel, decel):
            ml, mr = _pair(pair_id)
            cl = m_cmd(ml, mk_cmd(-lv, ml), accel, decel)   # left motor is mirrored
            cr = m_cmd(mr, mk_cmd(rv, mr), accel, decel)
            return Op(rt, lambda: ml.cmd is not cl and mr.cmd is not cr)

        def _deg_cmd(degrees, vmax, stop):
            def mk(v, m):
                if v == 0:
                    return ("stop", stop)
                amount = abs(degrees) * abs(v) / vmax
                return ("deg", v, m.pos, math.copysign(amount, v), stop)
            return mk

        def _signed(degrees, lv, rv):
            if degrees < 0:
                return -lv, -rv
            return lv, rv

        def move(pair_id, steering, *, velocity=360, acceleration=1000):
            rt.check()
            with lock:
                lv, rv = steer(velocity, steering)
                _pair_go(pair_id, lv, rv, lambda v, m: ("run", v), acceleration, None)

        def move_tank(pair_id, left_velocity, right_velocity, *, acceleration=1000):
            rt.check()
            with lock:
                _pair_go(pair_id, left_velocity, right_velocity, lambda v, m: ("run", v), acceleration, None)

        def move_for_degrees(pair_id, degrees, steering, *, velocity=360, stop=W.BRAKE,
                             acceleration=1000, deceleration=1000):
            rt.check()
            with lock:
                lv, rv = _signed(degrees, *steer(velocity, steering))
                vmax = max(abs(lv), abs(rv)) or 1
                if degrees == 0 or vmax == 0:
                    return Op(rt, lambda: True)
                return _pair_go(pair_id, lv, rv, _deg_cmd(degrees, vmax, stop), acceleration, deceleration)

        def move_tank_for_degrees(pair_id, degrees, left_velocity, right_velocity, *, stop=W.BRAKE,
                                  acceleration=1000, deceleration=1000):
            rt.check()
            with lock:
                lv, rv = _signed(degrees, left_velocity, right_velocity)
                vmax = max(abs(lv), abs(rv))
                if degrees == 0 or vmax == 0:
                    return Op(rt, lambda: True)
                return _pair_go(pair_id, lv, rv, _deg_cmd(degrees, vmax, stop), acceleration, deceleration)

        def _time_cmd(duration, stop):
            end = _time.monotonic() + duration / 1000
            return lambda v, m: ("time", v, end, stop)

        def move_for_time(pair_id, duration, steering, *, velocity=360, stop=W.BRAKE,
                          acceleration=1000, deceleration=1000):
            rt.check()
            with lock:
                lv, rv = steer(velocity, steering)
                return _pair_go(pair_id, lv, rv, _time_cmd(duration, stop), acceleration, deceleration)

        def move_tank_for_time(pair_id, left_velocity, right_velocity, duration, *, stop=W.BRAKE,
                               acceleration=1000, deceleration=1000):
            rt.check()
            with lock:
                return _pair_go(pair_id, left_velocity, right_velocity, _time_cmd(duration, stop),
                                acceleration, deceleration)

        def pair_stop(pair_id, *, stop=W.BRAKE):
            rt.check()
            with lock:
                ml, mr = _pair(pair_id)
                ml.cmd = ("stop", stop)
                mr.cmd = ("stop", stop)

        motor_pair = module(
            "motor_pair", PAIR_1=0, PAIR_2=1, PAIR_3=2, pair=pair, unpair=unpair, move=move,
            move_tank=move_tank, move_for_degrees=move_for_degrees,
            move_tank_for_degrees=move_tank_for_degrees, move_for_time=move_for_time,
            move_tank_for_time=move_tank_for_time, stop=pair_stop,
        )

        # ------------- sensors
        def cs_color(port):
            rt.check()
            with lock:
                rt._sensor(port, "color")
                return world.color_reading()[0]

        def cs_reflection(port):
            rt.check()
            with lock:
                rt._sensor(port, "color")
                return world.color_reading()[2]

        def cs_rgbi(port):
            rt.check()
            with lock:
                rt._sensor(port, "color")
                _, rgb, _ = world.color_reading()
                return (*rgb, max(rgb))

        color_sensor = module("color_sensor", color=cs_color, reflection=cs_reflection, rgbi=cs_rgbi)

        def ds_distance(port):
            rt.check()
            with lock:
                rt._sensor(port, "distance")
                return world.distance_mm()

        def ds_show(port, pixels):
            with lock:
                rt._sensor(port, "distance")
                world.distance_pixels = list(pixels)[:4]

        def ds_set_pixel(port, x, y, intensity):
            with lock:
                rt._sensor(port, "distance")
                world.distance_pixels[(y % 2) * 2 + (x % 2)] = intensity

        def ds_get_pixel(port, x, y):
            return world.distance_pixels[(y % 2) * 2 + (x % 2)]

        def ds_clear(port):
            world.distance_pixels = [0, 0, 0, 0]

        distance_sensor = module("distance_sensor", distance=ds_distance, show=ds_show,
                                 set_pixel=ds_set_pixel, get_pixel=ds_get_pixel, clear=ds_clear)

        def fs_force(port):
            rt.check()
            with lock:
                rt._sensor(port, "force")
                return world.force_value()[0]

        def fs_pressed(port):
            rt.check()
            with lock:
                rt._sensor(port, "force")
                return world.force_value()[1]

        def fs_raw(port):
            return fs_force(port) * 10

        force_sensor = module("force_sensor", force=fs_force, pressed=fs_pressed, raw=fs_raw)

        # ------------- hub
        def lm_write(text, intensity=100, time_per_character=500):
            rt.check()
            text = str(text)
            frames, per_frame = text_frames(text, time_per_character)
            with lock:
                if per_frame is None:
                    world.scroll = None
                    world.pixels = [intensity if b else 0 for b in frames[0]]
                    return Op(rt, rt._done_after(time_per_character / 1000))
                world.start_scroll(frames, per_frame, intensity)
                s = world.scroll
            return Op(rt, lambda: world.scroll is not s)

        def lm_show(pixels):
            with lock:
                world.scroll = None
                world.pixels = [max(0, min(100, int(p))) for p in list(pixels)[:25]]

        def lm_show_image(image):
            rt.check()
            with lock:
                world.scroll = None
                world.pixels = image_pixels(int(image))

        def lm_set_pixel(x, y, intensity=100):
            rt.check()
            with lock:
                world.scroll = None
                if 0 <= x < 5 and 0 <= y < 5:
                    world.pixels[y * 5 + x] = max(0, min(100, int(intensity)))

        def lm_get_pixel(x, y):
            return world.pixels[y * 5 + x]

        def lm_clear():
            with lock:
                world.scroll = None
                world.pixels = [0] * 25

        lm_attrs = {"IMAGE_" + n: i + 1 for i, n in enumerate(IMAGE_NAMES)}
        light_matrix = module("light_matrix", write=lm_write, show=lm_show, show_image=lm_show_image,
                              set_pixel=lm_set_pixel, get_pixel=lm_get_pixel, clear=lm_clear,
                              set_orientation=lambda o: o, get_orientation=lambda: 0, **lm_attrs)

        color_names = {v: k for k, v in COLOR_IDS.items()}

        def light_color(which, c):
            with lock:
                if which == 0:
                    world.power_light = color_names.get(c, "white")

        light = module("light", POWER=0, CONNECT=1, color=light_color)

        def beep(freq=440, duration=500, volume=100):
            rt.check()
            with lock:
                world.events.append({"type": "beep", "freq": freq, "duration": duration,
                                     "volume": volume})
            return Op(rt, rt._done_after(duration / 1000))

        sound = module("sound", beep=beep, stop=lambda: world.events.append({"type": "stop"}),
                       volume=lambda v: None, ANY=-2, DEFAULT=-1, WAVEFORM_SINE=1,
                       WAVEFORM_SAWTOOTH=3, WAVEFORM_SQUARE=2, WAVEFORM_TRIANGLE=1)

        def b_pressed(btn):
            rt.check()
            key = {1: "left", 2: "right"}.get(btn)
            with lock:
                if key and world.buttons[key]:
                    return int((_time.monotonic() - world.button_since[key]) * 1000) or 1
            return 0

        button = module("button", LEFT=1, RIGHT=2, pressed=b_pressed)

        def tilt_angles():
            rt.check()
            with lock:
                return (int(round(world.yaw() * 10)), 0, 0)

        def reset_yaw(angle=0):
            with lock:
                world.yaw_offset = world.heading - angle / 10

        motion_sensor = module(
            "motion_sensor", tilt_angles=tilt_angles, reset_yaw=reset_yaw,
            acceleration=lambda raw=False: (0, 0, 1000), angular_velocity=lambda raw=False: (0, 0, 0),
            up_face=lambda: 0, gesture=lambda: -1, stable=lambda: True, quaternion=lambda: (1, 0, 0, 0),
            set_yaw_face=lambda f: True, get_yaw_face=lambda: 0, tap_count=lambda: 0,
            reset_tap_count=lambda: None,
            TOP=0, FRONT=1, RIGHT=2, BOTTOM=3, BACK=4, LEFT=5,
            TAPPED=0, DOUBLE_TAPPED=1, SHAKEN=2, FALLING=3, UNKNOWN=-1,
        )

        port_mod = module("port", **{c: i for i, c in enumerate(PORTS)})
        hub = module("hub", port=port_mod, light_matrix=light_matrix, light=light, sound=sound,
                     button=button, motion_sensor=motion_sensor,
                     temperature=lambda: 250, device_uuid=lambda: "virtual-hub",
                     hardware_id=lambda: "VIRTUAL", power_off=lambda: rt._stop.set())

        # ------------- device
        DEV_IDS = {"medium": 48, "large": 49, "small": 65}

        def dev_id(p):
            letter = rt._port(p)
            d = world.config.get(letter, {})
            t = d.get("type")
            if t == "motor":
                return DEV_IDS.get(d.get("model"), 48)
            return {"color": 61, "distance": 62, "force": 63}.get(t, 0)

        device = module("device", id=dev_id, ready=lambda p: dev_id(p) != 0,
                        data=lambda p: (), get_duty_cycle=get_duty_cycle,
                        set_duty_cycle=set_duty_cycle)

        # ------------- runloop
        def rl_run(*functions):
            async def main():
                await asyncio.gather(*functions)
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(main())
            finally:
                loop.close()

        def sleep_ms(duration):
            return Op(rt, rt._done_after(duration / 1000))

        def until(function, timeout=0):
            end = _time.monotonic() + timeout / 1000 if timeout else None
            return Op(rt, lambda: bool(function()) or (end is not None and _time.monotonic() >= end))

        runloop = module("runloop", run=rl_run, sleep_ms=sleep_ms, until=until)

        # ------------- MicroPython-style time
        def t_sleep(s):
            end = _time.monotonic() + s
            while _time.monotonic() < end:
                rt.check()
                _time.sleep(min(0.01, max(0, end - _time.monotonic())))

        t0 = _time.monotonic()
        mtime = module(
            "time", sleep=t_sleep, sleep_ms=lambda ms: t_sleep(ms / 1000),
            sleep_us=lambda us: t_sleep(us / 1e6),
            ticks_ms=lambda: int((_time.monotonic() - t0) * 1000),
            ticks_us=lambda: int((_time.monotonic() - t0) * 1e6),
            ticks_diff=lambda a, b: a - b, ticks_add=lambda a, b: a + b,
            time=_time.time, localtime=_time.localtime, monotonic=_time.monotonic,
        )

        # ------------- app (sounds and screen on the device running the SPIKE app)
        class _AppStub(types.ModuleType):
            def __getattr__(self, name):
                if name.startswith("__"):
                    raise AttributeError(name)

                def call(*a, **k):
                    with lock:
                        world.events.append({"type": "app", "call": "%s.%s" % (self.__name__, name)})
                    return Op(rt, lambda: True)
                return call

        app = module("app")
        for sub in ("sound", "music", "display", "bargraph", "linegraph"):
            setattr(app, sub, _AppStub("app." + sub))

        orientation = module("orientation", UP=0, RIGHT=1, DOWN=2, LEFT=3)
        color_matrix = module("color_matrix", show=lambda p, px: None, clear=lambda p: None,
                              set_pixel=lambda p, x, y, px: None, get_pixel=lambda p, x, y: (0, 0))

        return {
            "hub": hub, "motor": motor, "motor_pair": motor_pair, "color": color,
            "color_sensor": color_sensor, "distance_sensor": distance_sensor,
            "force_sensor": force_sensor, "runloop": runloop, "device": device, "app": app,
            "orientation": orientation, "color_matrix": color_matrix,
            "time": mtime, "utime": mtime,
        }
