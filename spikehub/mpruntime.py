"""Runs programs in real MicroPython (as the hub does), including the compiled
.mpy files the SPIKE app sends for Word Blocks and Python projects.

The MicroPython process imports stand-in hub modules (spikehub/mp/) that send
each hub call here over a local socket; this side carries them out on the
simulated `World` using the same module code as the CPython runtime.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import types

from .runtime import Op, Runtime

HERE = os.path.dirname(os.path.abspath(__file__))
MP_LIB = os.path.join(HERE, "mp")
RUN_ROOT = os.path.join(os.path.dirname(HERE), "run")

# hub calls that only read something: not shown in the robot's action feed
READS = {
    "color_sensor.color", "color_sensor.reflection", "color_sensor.rgbi",
    "distance_sensor.distance", "distance_sensor.get_pixel", "force_sensor.force",
    "force_sensor.pressed", "force_sensor.raw", "motor.relative_position",
    "motor.absolute_position", "motor.velocity", "motor.get_duty_cycle", "device.id",
    "device.ready", "device.data", "device.get_duty_cycle", "hub.button.pressed",
    "hub.motion_sensor.tilt_angles", "hub.motion_sensor.acceleration",
    "hub.motion_sensor.angular_velocity", "hub.motion_sensor.up_face",
    "hub.motion_sensor.gesture", "hub.motion_sensor.stable", "hub.motion_sensor.quaternion",
    "hub.motion_sensor.get_yaw_face", "hub.motion_sensor.tap_count",
    "hub.light_matrix.get_pixel", "hub.light_matrix.get_orientation", "hub.temperature",
    "hub.device_uuid", "hub.hardware_id", "motor.info", "motor_pair.unpair",
}

PORT_NAMES = "ABCDEF"
DEBUG = bool(os.environ.get("SIMHUB_DEBUG"))


def find_micropython():
    return shutil.which("micropython") or next(
        (p for p in ("/opt/homebrew/bin/micropython", "/usr/local/bin/micropython") if os.path.exists(p)), None)


def _encode(v):
    if isinstance(v, tuple):
        return {"__t": [_encode(x) for x in v]}
    if isinstance(v, list):
        return [_encode(x) for x in v]
    if isinstance(v, (int, float, str, bool)) or v is None:
        return v
    return repr(v)


def describe(path, args, kwargs):
    """A short, readable line for the action feed."""
    def port(p):
        return PORT_NAMES[p] if isinstance(p, int) and 0 <= p < 6 else p

    a = list(args)
    v = kwargs.get("velocity")
    try:
        if path == "motor_pair.move_for_degrees":
            return f"Drive {a[1]}° of wheel turn, steering {a[2]}" + (f", speed {v}" if v else "")
        if path == "motor_pair.move_for_time":
            return f"Drive for {a[1] / 1000:g} s, steering {a[2]}" + (f", speed {v}" if v else "")
        if path == "motor_pair.move":
            return f"Drive, steering {a[1]}" + (f", speed {v}" if v else "")
        if path == "motor_pair.move_tank":
            return f"Tank drive left {a[1]}, right {a[2]}"
        if path == "motor_pair.move_tank_for_degrees":
            return f"Tank drive {a[1]}°: left {a[2]}, right {a[3]}"
        if path == "motor_pair.move_tank_for_time":
            return f"Tank drive {a[3] / 1000:g} s: left {a[1]}, right {a[2]}"
        if path == "motor_pair.stop":
            return "Stop driving"
        if path == "motor_pair.pair":
            return f"Use motors {port(a[1])} (left) and {port(a[2])} (right) for driving"
        if path == "motor.run_for_degrees":
            return f"Motor {port(a[0])}: turn {a[1]}° at {a[2]}°/s"
        if path == "motor.run_for_time":
            return f"Motor {port(a[0])}: run {a[1] / 1000:g} s at {a[2]}°/s"
        if path == "motor.run":
            return f"Motor {port(a[0])}: run at {a[1]}°/s"
        if path == "motor.stop":
            return f"Motor {port(a[0])}: stop"
        if path == "motor.run_to_absolute_position":
            return f"Motor {port(a[0])}: go to position {a[1]}°"
        if path == "motor.run_to_relative_position":
            return f"Motor {port(a[0])}: go to {a[1]}° from its zero"
        if path == "motor.reset_relative_position":
            return f"Motor {port(a[0])}: set position to {a[1] if len(a) > 1 else 0}°"
        if path == "hub.light_matrix.write":
            return f"Write \"{a[0]}\" on the light matrix"
        if path == "hub.light_matrix.show_image":
            return "Show an image on the light matrix"
        if path == "hub.light_matrix.show":
            return "Light up the matrix"
        if path == "hub.light_matrix.set_pixel":
            return f"Light pixel ({a[0]}, {a[1]}) at {a[2] if len(a) > 2 else 100}%"
        if path == "hub.light_matrix.clear":
            return "Turn off the light matrix"
        if path == "hub.sound.beep":
            return f"Beep {a[0] if a else 440} Hz"
        if path == "hub.light.color":
            return "Change the hub button light"
        if path == "hub.motion_sensor.reset_yaw":
            return "Reset the yaw angle"
    except (IndexError, TypeError):
        pass
    parts = [repr(x) for x in a] + [f"{k}={val!r}" for k, val in kwargs.items()]
    return f"{path}({', '.join(parts)})"


class MpRuntime:
    """Same interface as Runtime (start / stop / running), backed by MicroPython."""

    def __init__(self, world, console, on_state, on_action=None, tunnel_out=None):
        self.world = world
        self.console = console
        self.on_state = on_state
        self.on_action = on_action or (lambda text, replace: None)
        self.tunnel_out = tunnel_out or (lambda data: None)
        self.tunnel_in: list[bytes] = []
        self.binary = find_micropython()
        self.proc = None
        self.running = False
        self._gen = 0
        self._lock = threading.Lock()

    @property
    def available(self):
        return self.binary is not None

    # ------------------------------------------------------------ control
    def start(self, source: str, filename="program.py"):
        self.start_files({"program.py": source.encode("utf8")})

    def start_files(self, files: dict[str, bytes], main="program"):
        self.stop(wait=True)
        os.makedirs(RUN_ROOT, exist_ok=True)
        rundir = tempfile.mkdtemp(prefix="run-", dir=RUN_ROOT)
        for name, data in files.items():
            with open(os.path.join(rundir, os.path.basename(name)), "wb") as f:
                f.write(data)

        self.world.program_reset()
        rt = Runtime(self.world, self.console, lambda s: None)
        mods = rt._modules()
        for native in ("runloop", "time", "utime"):
            mods.pop(native, None)
        self.tunnel_in = []

        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]

        env = dict(os.environ, MICROPYPATH=":".join([".frozen", rundir, MP_LIB]), SIMHUB_PORT=str(port))
        self._gen += 1
        gen = self._gen
        self.proc = subprocess.Popen(
            [self.binary, "-X", "heapsize=8M", os.path.join(MP_LIB, "_launch.py"), main],
            cwd=rundir, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.running = True
        self.on_state(True)

        proc = self.proc
        threading.Thread(target=self._serve, args=(server, rt, mods, proc), daemon=True).start()
        threading.Thread(target=self._pipe, args=(proc.stdout, False), daemon=True).start()
        threading.Thread(target=self._pipe, args=(proc.stderr, True), daemon=True).start()
        threading.Thread(target=self._wait, args=(proc, gen, rundir), daemon=True).start()

    def stop(self, wait=False):
        p = self.proc
        if p and p.poll() is None:
            p.terminate()
            if wait:
                try:
                    p.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    p.kill()

    def check(self):
        pass

    # ------------------------------------------------------------ threads
    def _wait(self, proc, gen, rundir):
        proc.wait()
        time.sleep(0.05)  # let the output threads finish
        if gen == self._gen:
            self.world.program_stop()
            self.running = False
            self.on_state(False)
        shutil.rmtree(rundir, ignore_errors=True)

    def _pipe(self, stream, is_err):
        buf = []
        for raw in iter(stream.readline, b""):
            text = raw.decode("utf8", "replace")
            if is_err:
                buf.append(text)
                if not text.startswith((" ", "Traceback")):
                    self.console("".join(buf))
                    buf = []
            else:
                self.console(text)
        if buf:
            self.console("".join(buf))
        stream.close()

    def _serve(self, server, rt, mods, proc):
        server.settimeout(10)
        try:
            conn, _ = server.accept()
        except OSError:
            self.console("The program could not connect to the simulator.\n")
            return
        finally:
            server.close()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        reader = conn.makefile("rb")
        ops: dict[int, Op] = {}
        next_id = 1
        last = {"path": None, "t": 0.0}
        try:
            for line in reader:
                if proc.poll() is not None:
                    break
                try:
                    msg = json.loads(line)
                    reply = self._handle(msg, mods, ops, last)
                    if isinstance(reply, Op):
                        ops[next_id] = reply
                        reply = {"op": next_id}
                        next_id += 1
                except Exception as e:  # report to the program as a hub error
                    args = list(e.args) if all(isinstance(a, (int, str)) for a in e.args) else [str(e)]
                    reply = {"e": [type(e).__name__, args]}
                if DEBUG:
                    print("rpc", line.decode().strip(), "->", reply, flush=True)
                conn.sendall((json.dumps(reply) + "\n").encode())
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass
        finally:
            conn.close()

    def _handle(self, msg, mods, ops, last):
        if "d" in msg:
            op = ops.get(msg["d"])
            done = op is None or op._done()
            if done:
                ops.pop(msg["d"], None)
            return {"r": done}
        if "g" in msg:
            obj = self._resolve(mods, msg["g"])
            if isinstance(obj, types.ModuleType):
                return {"m": 1}
            if callable(obj):
                return {"f": 1}
            return {"r": _encode(obj)}
        if "c" in msg:
            path, args, kwargs = msg["c"], msg.get("a", []), msg.get("k", {})
            if path.startswith("_"):
                return {"r": self._internal(path, args)}
            fn = self._resolve(mods, path)
            result = fn(*args, **kwargs)
            if path not in READS:
                now = time.monotonic()
                self.on_action(describe(path, args, kwargs),
                               last["path"] == path and now - last["t"] < 0.3)
                last["path"], last["t"] = path, now
            return result if isinstance(result, Op) else {"r": _encode(result)}
        if "hello" in msg:
            return {"r": True}
        raise ValueError("bad request")

    @staticmethod
    def _resolve(mods, path):
        parts = path.split(".")
        if parts[0] not in mods:
            raise AttributeError(f"no module named '{parts[0]}' in the simulator")
        obj = mods[parts[0]]
        for p in parts[1:]:
            if not hasattr(obj, p):
                raise AttributeError(f"'{'.'.join(parts[:-1])}' has no attribute '{p}' in the simulator")
            obj = getattr(obj, p)
        return obj

    def _internal(self, path, args):
        if path == "_tunnel.send":
            self.tunnel_out(bytes(args[0]))
            return True
        if path == "_tunnel.recv":
            msgs, self.tunnel_in = self.tunnel_in, []
            return [list(m) for m in msgs]
        if path == "_tunnel.connected":
            return True
        if path == "_vm.stack":
            label, running = args
            self.on_action(("▶ " if running else "■ ") + label, False)
            return True
        raise ValueError(path)
