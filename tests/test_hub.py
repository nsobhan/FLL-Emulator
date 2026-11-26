import os
import random
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spikehub import protocol as P
from spikehub.world import World
from spikehub.runtime import Runtime

# test vectors from LEGO's spike-prime-docs examples/python/_tests/test_cobs.py
CASES = (
    (bytes((0, 1, 2, 3, 4, 5, 6, 0, 1, 2, 3, 4, 5, 84, 234, 54, 0, 45, 23, 12)),
     bytes((0, 84, 168, 4, 0, 7, 6, 5, 84, 168, 10, 0, 7, 6, 87, 233, 53, 5, 46, 20, 15, 2))),
    (bytes((255, 254, 223, 213, 125, 175, 100, 97, 54, 21, 65, 45)),
     bytes((12, 252, 253, 220, 214, 126, 172, 103, 98, 53, 22, 66, 46, 2))),
)


class Protocol(unittest.TestCase):
    def test_vectors(self):
        for raw, wire in CASES:
            self.assertEqual(P.pack(raw), wire)
            self.assertEqual(P.unpack(wire), raw)

    def test_roundtrip_random(self):
        rnd = random.Random(1)
        for n in (0, 1, 83, 84, 85, 200, 1000):
            data = bytes(rnd.randrange(256) for _ in range(n)) or b"\x00"
            self.assertEqual(P.unpack(P.pack(data)), data)

    def test_frame_reader_split(self):
        frame = P.pack(b"hello world" * 20)
        r = P.FrameReader()
        out = []
        for i in range(0, len(frame), 7):
            out += r.feed(frame[i:i + 7])
        self.assertEqual(len(out), 1)
        self.assertEqual(P.unpack(out[0]), b"hello world" * 20)


def run_program(src, seconds):
    w = World()
    w.start()
    log = []
    rt = Runtime(w, log.append, lambda s: None)
    rt.start(src)
    t = time.monotonic()
    while rt.running and time.monotonic() - t < seconds:
        time.sleep(0.02)
    rt.stop(wait=True)
    return w, log


class Programs(unittest.TestCase):
    def test_drive_forward(self):
        src = """
from hub import port
import motor_pair, runloop
async def main():
    motor_pair.pair(motor_pair.PAIR_1, port.A, port.B)
    await motor_pair.move_for_degrees(motor_pair.PAIR_1, 360, 0, velocity=500)
    print("done")
runloop.run(main())
"""
        w, log = run_program(src, 5)
        self.assertIn("done\n", log)
        # one wheel turn = pi * 5.6 cm forward; robot starts facing up at y=20
        self.assertAlmostEqual(w.y - 20, 17.59, delta=0.6)
        self.assertAlmostEqual(w.x, 25, delta=0.3)

    def test_turn_and_yaw(self):
        src = """
from hub import port, motion_sensor
import motor_pair, runloop
async def main():
    motor_pair.pair(motor_pair.PAIR_1, port.A, port.B)
    motion_sensor.reset_yaw(0)
    await motor_pair.move_for_degrees(motor_pair.PAIR_1, 180, 100, velocity=300)
    print(motion_sensor.tilt_angles()[0])
runloop.run(main())
"""
        w, log = run_program(src, 5)
        yaw = int(log[0]) / 10
        # spin right: 180 wheel deg each way -> 2*(pi*5.6/2)/11.2 rad = 90 degrees clockwise
        self.assertAlmostEqual(yaw, -90, delta=4)

    def test_sensors_and_errors(self):
        src = """
from hub import port, light_matrix
import color_sensor, distance_sensor, color
print(color_sensor.color(port.C) == color.WHITE, distance_sensor.distance(port.D) > 0)
light_matrix.show_image(light_matrix.IMAGE_HEART)
color_sensor.color(port.A)
"""
        w, log = run_program(src, 3)
        self.assertEqual(log[0], "True True\n")
        # using a sensor on another port moves it there to match the program
        self.assertEqual(w.config["A"]["type"], "color")
        self.assertEqual(w.config["C"]["type"], "motor")
        self.assertEqual(w.pixels[0], 0)
        self.assertEqual(w.pixels[1], 100)

    def test_stop_infinite_loop(self):
        w = World()
        w.start()
        rt = Runtime(w, lambda s: None, lambda s: None)
        rt.start("while True:\n    pass\n")
        time.sleep(0.2)
        rt.stop(wait=True)
        self.assertFalse(rt.running)


BLOCKS_STYLE = """
from _system import scratch
from hub import port, light_matrix
import motor_pair, runloop, sys

sys.tracebacklimit = 0
motor_pair.pair(motor_pair.PAIR_1, port.C, port.D)

async def stack_1(this):
    while True:
        with this as event:
            await event
            print("start")
            await motor_pair.move_for_degrees(motor_pair.PAIR_1, 360, 0, velocity=500)
            await this.broadcast("hello")
            print("after broadcast")
            await this.wait(100)
            this.stop_this()
            print("never printed")

async def stack_2(this):
    while True:
        with this as event:
            await event
            print("got hello")
            yield
            light_matrix.show_image(light_matrix.IMAGE_HEART)

vm = scratch.VM()
vm.add_start(stack_1)
vm.add_receive(stack_2, "hello")
vm.run()
"""


@unittest.skipUnless(__import__("shutil").which("micropython"), "MicroPython not installed")
class MicroPythonRunner(unittest.TestCase):
    def run_mp(self, src, seconds=10):
        from spikehub.mpruntime import MpRuntime
        w = World()
        w.start()
        out, actions = [], []
        rt = MpRuntime(w, out.append, lambda s: None, on_action=lambda t, r: actions.append(t))
        rt.start(src)
        t = time.monotonic()
        while rt.running and time.monotonic() - t < seconds:
            time.sleep(0.02)
        still = rt.running
        rt.stop(wait=True)
        time.sleep(0.1)
        return w, "".join(out), actions, still

    def test_blocks_style_program(self):
        w, out, actions, still = self.run_mp(BLOCKS_STYLE, seconds=3)
        self.assertTrue(still, "block programs keep running until stopped, like on the hub")
        self.assertEqual(out, "start\ngot hello\nafter broadcast\n")
        self.assertAlmostEqual(w.y - 20, 17.59, delta=0.6)
        self.assertEqual(w.config["C"].get("role"), "left")
        self.assertEqual(w.pixels[1], 100)
        self.assertIn("Use motors C (left) and D (right) for driving", actions)

    def test_python_errors_reach_console(self):
        w, out, actions, still = self.run_mp("import motor\nmotor.run(9, 100)\n", 5)
        self.assertIn("ValueError", out)

    def test_start_moving_keeps_driving(self):
        src = BLOCKS_STYLE.split("async def stack_1")[0] + """
async def stack_1(this):
    while True:
        with this as event:
            await event
            motor_pair.move_tank(motor_pair.PAIR_1, 500, 500)

vm = scratch.VM()
vm.add_start(stack_1)
vm.run()
"""
        w, out, actions, still = self.run_mp(src, seconds=1.5)
        self.assertTrue(still)
        self.assertGreater(w.y - 20, 15, "robot should still be driving after the stack finished")


def make_llsp3(blocks, variables=None):
    import io, json, zipfile
    proj = {"targets": [{"isStage": True, "name": "Stage", "blocks": {}, "variables": {}, "broadcasts": {}},
                        {"isStage": False, "name": "p", "blocks": blocks, "variables": variables or {},
                         "broadcasts": {}, "sounds": []}]}
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z:
        z.writestr("project.json", json.dumps(proj))
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w") as z:
        z.writestr("manifest.json", json.dumps({"type": "word-blocks", "name": "Test blocks"}))
        z.writestr("scratch.sb3", inner.getvalue())
    return outer.getvalue()


def blk(op, nxt=None, inputs=None, fields=None, top=False, shadow=False):
    return {"opcode": op, "next": nxt, "inputs": inputs or {}, "fields": fields or {}, "topLevel": top,
            "shadow": shadow}


TEST_BLOCKS = {
    "hat": blk("flipperevents_whenProgramStarts", "mv", top=True),
    "mv": blk("flippermove_move", "rep", {"DIRECTION": [1, "dir"], "VALUE": [1, [4, "10"]]}, {"UNIT": ["cm", None]}),
    "dir": blk("flippermove_custom-icon-direction", fields={"field_flippermove_custom-icon-direction": ["forward", None]}, shadow=True),
    "rep": blk("control_repeat", "bc", {"TIMES": [1, [6, "3"]], "SUBSTACK": [2, "chg"]}),
    "chg": blk("data_changevariableby", None, {"VALUE": [1, [4, "2"]]}, {"VARIABLE": ["count", "v1"]}),
    "bc": blk("event_broadcastandwait", None, {"BROADCAST_INPUT": [1, [11, "go", "b1"]]}),
    "rx": blk("event_whenbroadcastreceived", "say", fields={"BROADCAST_OPTION": ["go", "b1"]}, top=True),
    "say": blk("flipperlight_lightDisplayImageOn", None, {"MATRIX": [1, "mx"]}),
    "mx": blk("flipperlight_matrix-5x5-brightness-image", fields={"field_flipperlight_matrix-5x5-brightness-image": ["9" * 25, None]}, shadow=True),
}


class ArmAndCubes(unittest.TestCase):
    def test_grab_carry_and_deliver(self):
        w = World("camp2")
        w.apply_config({"C": {"type": "motor", "model": "medium", "role": "left"},
                        "D": {"type": "motor", "model": "medium", "role": "right"},
                        "E": {"type": "motor", "model": "medium", "role": "arm"}, "F": {"type": "distance"}})
        w.reset_robot()
        w.x = 52.0                                    # stopped in front of the marker, cube under the arm
        self.assertEqual(w.distance_mm(), 80)         # sensor sees the marker, not the low cube
        w.motors["E"].pos += 90                       # lower the arm
        w.step(0.01, time.monotonic())
        self.assertIs(w.carried, w.cubes[0])
        w.x = 30.0                                    # back home
        w.step(0.01, time.monotonic())
        self.assertAlmostEqual(w.cubes[0]["x"], 43.0, delta=0.5)
        w.motors["E"].pos -= 90                       # raise the arm: let go
        w.step(0.01, time.monotonic())
        self.assertIsNone(w.carried)
        self.assertTrue(any("delivered home (1 of 1)" in e.get("text", "") for e in w.events))


class BlockProjects(unittest.TestCase):
    def test_render(self):
        from spikehub.blocks import Project
        p = Project(make_llsp3(TEST_BLOCKS, {"v1": ["count", 0]}))
        texts = [n["text"] for s in p.scripts() for n in s]
        self.assertIn("move ↑ forward for 10 cm", texts)
        self.assertIn("repeat 3", texts)
        self.assertIn("when I receive go", texts)

    def test_run(self):
        from spikehub.blocks import Project, BlockRunner
        w = World()
        w.start()
        actions = []
        r = BlockRunner(w, lambda s: None, lambda s: None, on_action=lambda t, rep: actions.append(t))
        r.start_project(Project(make_llsp3(TEST_BLOCKS, {"v1": ["count", 0]})))
        seen = set()
        t = time.monotonic()
        while time.monotonic() - t < 4 and w.pixels[0] == 0:
            seen.update(r.active)
            time.sleep(0.01)
        time.sleep(0.2)
        self.assertTrue(r.running, "block projects keep running until stopped")
        r.stop(wait=True)
        self.assertAlmostEqual(w.y - 20, 10, delta=0.6)
        self.assertEqual(r.vars["v1"], 6)
        self.assertEqual(w.pixels, [100] * 25)
        self.assertIn("mv", seen)


if __name__ == "__main__":
    unittest.main()
