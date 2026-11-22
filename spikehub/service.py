"""Hub message handling, independent of the Bluetooth transport."""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import struct
import time
import uuid

from . import protocol as P
from .blocks import BlockRunner, Project
from .mpruntime import MpRuntime
from .runtime import Runtime
from .world import World, PORTS, MOTOR_TYPE_ID

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(HERE, "uploads")
LOG_DIR = os.path.join(HERE, "logs")


class HubService:
    def __init__(self, world: World, firmware=(1, 6, 62), rpc=(1, 0, 0), name="Sim Hub"):
        self.world = world
        self.firmware = firmware
        self.rpc = rpc
        self.hub_name = name
        self.device_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, "spike-virtual-hub").bytes
        self.loop: asyncio.AbstractEventLoop | None = None
        self.transport_send = None        # async callable(bytes frame) set by the BLE layer
        self.reader = P.FrameReader()
        self.slots: dict[int, dict] = {}
        self.upload = None
        self.running_slot = None
        self.notify_interval = 0
        self._notify_task = None
        self.listeners = []               # callables(dict) for the web UI
        self.log_items: list[dict] = []
        self.console_lines: list[str] = []
        self.ble_state = "starting"
        self.ble_detail = ""
        self.actions: list[dict] = []
        mp = MpRuntime(world, self._console_from_thread, self._state_from_thread,
                       on_action=self._action_from_thread, tunnel_out=self._tunnel_from_program)
        if mp.available:
            self.runtime = mp
        else:  # fall back to running Python text only
            self.runtime = Runtime(world, self._console_from_thread, self._state_from_thread)
        self.blocks = BlockRunner(world, self._console_from_thread, self._state_from_thread,
                                  on_action=self._action_from_thread, on_event=self._event_from_thread)
        self.project: Project | None = None
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        os.makedirs(LOG_DIR, exist_ok=True)
        self._logfile = open(os.path.join(LOG_DIR, dt.datetime.now().strftime("session-%Y%m%d-%H%M%S.log")),
                             "a", buffering=1)

    # ------------------------------------------------------------ plumbing
    def attach_loop(self, loop):
        self.loop = loop

    def emit(self, msg: dict):
        for f in list(self.listeners):
            try:
                f(msg)
            except Exception:
                pass

    def log(self, direction: str, text: str, raw: bytes | None = None):
        item = {"t": time.strftime("%H:%M:%S"), "dir": direction, "text": text,
                "hex": raw.hex(" ") if raw is not None and len(raw) <= 64 else
                (raw[:64].hex(" ") + " …" if raw is not None else "")}
        self.log_items.append(item)
        self.log_items = self.log_items[-300:]
        self._logfile.write(f"{item['t']} {direction} {text} {item['hex']}\n")
        self.emit({"type": "log", "item": item})

    def set_ble(self, state, detail=""):
        self.ble_state, self.ble_detail = state, detail
        self.log("--", f"Bluetooth: {state} {detail}".strip())
        self.emit({"type": "ble", "state": state, "detail": detail})
        if state != "connected":
            self.set_notify_interval(0)

    async def send(self, payload: bytes, quiet=False):
        if not quiet:
            self.log("hub→app", P.MESSAGE_NAMES.get(payload[0], hex(payload[0])), payload)
        if self.transport_send:
            await self.transport_send(P.pack(payload))

    def send_threadsafe(self, payload: bytes):
        if self.loop:
            asyncio.run_coroutine_threadsafe(self.send(payload), self.loop)

    # ------------------------------------------------------------ incoming
    def on_data(self, data: bytes):
        """Raw bytes written by the app to the RX characteristic."""
        for frame in self.reader.feed(data):
            try:
                msg = P.unpack(frame)
            except Exception as e:
                self.log("app→hub", f"undecodable frame ({e})", frame)
                continue
            if msg:
                asyncio.ensure_future(self.handle(msg))

    async def handle(self, m: bytes):
        mid = m[0]
        name = P.MESSAGE_NAMES.get(mid, f"unknown message 0x{mid:02x}")
        quiet = mid == P.TRANSFER_CHUNK_REQUEST
        if not quiet:
            self.log("app→hub", name, m)

        if mid == P.INFO_REQUEST:
            await self.send(P.info_response(rpc=self.rpc, fw=self.firmware))
        elif mid == P.GET_HUB_NAME_REQUEST:
            await self.send(P.name_response(self.hub_name))
        elif mid == P.SET_HUB_NAME_REQUEST:
            self.hub_name = P.cstr(m[1:]) or self.hub_name
            await self.send(P.status(P.SET_HUB_NAME_RESPONSE))
        elif mid == P.DEVICE_UUID_REQUEST:
            await self.send(bytes([P.DEVICE_UUID_RESPONSE]) + self.device_uuid)
        elif mid == P.DEVICE_NOTIFICATION_REQUEST:
            (interval,) = struct.unpack("<H", m[1:3])
            self.set_notify_interval(interval)
            await self.send(P.status(P.DEVICE_NOTIFICATION_RESPONSE))
        elif mid == P.CLEAR_SLOT_REQUEST:
            existed = self.slots.pop(m[1], None) is not None
            await self.send(P.status(P.CLEAR_SLOT_RESPONSE, True))
            self.emit({"type": "slots", "slots": self.slot_summary()})
            if not existed:
                self.log("--", f"slot {m[1]} was already empty")
        elif mid == P.START_FILE_UPLOAD_REQUEST:
            # name is a null-terminated string; slot and crc follow the terminator
            term = m.index(0, 1)
            fname = m[1:term].decode("utf8", "replace")
            slot, file_crc = struct.unpack("<BI", m[term + 1:term + 6])
            self.upload = {"name": fname, "slot": slot, "crc": file_crc, "buf": bytearray(),
                           "running": 0, "chunks": 0}
            self.log("--", f"upload started: '{fname}' into slot {slot}")
            await self.send(P.status(P.START_FILE_UPLOAD_RESPONSE, True))
        elif mid == P.TRANSFER_CHUNK_REQUEST:
            running_crc, size = struct.unpack("<IH", m[1:7])
            chunk = m[7:7 + size]
            ok = self.upload is not None
            if ok:
                up = self.upload
                up["running"] = P.crc(chunk, up["running"])
                up["buf"] += chunk
                up["chunks"] += 1
                if up["running"] != running_crc:
                    self.log("--", f"chunk CRC mismatch (got {running_crc:08x}, "
                                   f"computed {up['running']:08x}); accepting anyway")
            await self.send(P.status(P.TRANSFER_CHUNK_RESPONSE, ok), quiet=True)
            if ok and P.crc(bytes(self.upload["buf"])) == self.upload["crc"]:
                self._finish_upload()
        elif mid == P.PROGRAM_FLOW_REQUEST:
            stop, slot = m[1], m[2]
            if self.upload and self.upload["buf"]:
                self._finish_upload()
            if stop:
                self.stop_program()
                await self.send(P.status(P.PROGRAM_FLOW_RESPONSE, True))
            else:
                ok = slot in self.slots
                await self.send(P.status(P.PROGRAM_FLOW_RESPONSE, ok))
                if ok:
                    self.start_slot(slot)
                else:
                    self.log("--", f"no program in slot {slot}")
        elif mid == P.TUNNEL_MESSAGE:
            (size,) = struct.unpack("<H", m[1:3])
            if isinstance(self.runtime, MpRuntime) and self.runtime.running:
                self.runtime.tunnel_in.append(bytes(m[3:3 + size]))
        elif mid in (P.START_FIRMWARE_UPLOAD_REQUEST, P.BEGIN_FIRMWARE_UPDATE_REQUEST):
            self.log("--", "the app asked for a firmware update; the virtual hub declines")
            await self.send(bytes([mid + 1, P.NACK]) + (b"\0\0\0\0" if mid == P.START_FIRMWARE_UPLOAD_REQUEST else b""))
        else:
            self.log("--", f"no handler for 0x{mid:02x}")

    def _finish_upload(self):
        up, self.upload = self.upload, None
        data = bytes(up["buf"])
        ok = P.crc(data) == up["crc"]
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in up["name"]) or "program"
        path = os.path.join(UPLOAD_DIR, f"{stamp}-slot{up['slot']}-{safe}")
        with open(path, "wb") as f:
            f.write(data)
        self.slots.setdefault(up["slot"], {"files": {}})["files"][up["name"]] = data
        kind = "Python source" if self._as_text(data) is not None else "compiled MicroPython"
        self.log("--", f"upload finished: {len(data)} bytes, {up['chunks']} chunks, "
                       f"CRC {'ok' if ok else 'MISMATCH'}, {kind}. Saved to uploads/{os.path.basename(path)}")
        self.emit({"type": "slots", "slots": self.slot_summary()})

    @staticmethod
    def _as_text(data: bytes):
        if data[:1] == b"M":  # MicroPython .mpy header
            return None
        try:
            return data.decode("utf8")
        except UnicodeDecodeError:
            return None

    def slot_summary(self):
        out = {}
        for k, v in sorted(self.slots.items()):
            files = v["files"]
            main = next((n for n in files if n.startswith("program.")), next(iter(files), "?"))
            out[str(k)] = {"name": main, "files": sorted(files), "size": sum(len(d) for d in files.values()),
                           "title": self._program_title(files.get(main, b""))}
        return out

    @staticmethod
    def _program_title(data: bytes):
        """Compiled programs carry the project name as their source file name."""
        def varuint(i):
            v = 0
            while True:
                b = data[i]
                i += 1
                v = (v << 7) | (b & 0x7F)
                if not b & 0x80:
                    return v, i
        if data[:1] != b"M" or len(data) < 8:
            return ""
        try:
            _, i = varuint(4)      # number of qstrs
            _, i = varuint(i)      # number of constant objects
            n, i = varuint(i)      # first qstr = source file name, stored as len << 1
            name = data[i:i + (n >> 1)].decode("utf8").strip()
            return name if name.isprintable() else ""
        except (IndexError, UnicodeDecodeError):
            return ""

    # ------------------------------------------------------------ programs
    def start_slot(self, slot):
        files = self.slots[slot]["files"]
        self.running_slot = slot
        if isinstance(self.runtime, MpRuntime):
            title = self.slot_summary()[str(slot)]["title"] or "program"
            self.log("--", f"running slot {slot}: {', '.join(sorted(files))}")
            self.emit({"type": "program_source", "name": title,
                       "source": self._as_text(files.get("program.py", b"M")) or
                       "(compiled program: the app sent MicroPython bytecode, so there is no text to show)"})
            self.blocks.stop(wait=True)
            self.actions = []
            self.emit({"type": "actions_reset", "title": title})
            self.runtime.start_files(files)
            return
        entry = {"data": files.get("program.py") or next(iter(files.values())), "name": "program.py"}
        src = self._as_text(entry["data"])
        if src is None:
            msg = (f"Slot {slot} holds a compiled program ({len(entry['data'])} bytes). "
                   "The simulator can only run Python source so far.")
            self.log("--", msg)
            self.console(msg + "\n")
            self.send_threadsafe(P.program_flow_notification(True))
            return
        self.run_source(src, slot=slot, name=entry["name"])

    # ------------------------------------------------------------ project files (.llsp3)
    def load_project(self, data: bytes, filename: str) -> dict:
        if filename.lower().endswith(".py"):
            self.project = None
            return {"type": "python", "name": filename, "python": data.decode("utf8", "replace")}
        project = Project(data, filename)
        self.project = project
        info = {"type": project.type, "name": project.name}
        if project.type == "python":
            info["python"] = project.python
        else:
            info["scripts"] = project.scripts()
            info["sounds"] = sorted(project.sounds)
        self.log("--", f"opened project '{project.name}' ({project.type}) from {filename}")
        self.emit({"type": "project", **info})
        return info

    def run_project(self):
        p = self.project
        if p is None:
            return
        self.stop_program(wait=True)
        self.actions = []
        self.emit({"type": "actions_reset", "title": p.name})
        if p.type == "python":
            self.run_source(p.python, name=p.name)
        else:
            self.log("--", f"running block project '{p.name}'")
            self.blocks.start_project(p)

    def program_running(self):
        return self.runtime.running or self.blocks.running

    def active_blocks(self):
        return list(self.blocks.active) if self.blocks.running else []

    def _event_from_thread(self, ev):
        with self.world.lock:
            self.world.events.append(ev)

    def run_source(self, src, slot=None, name="program.py"):
        self.running_slot = slot
        self.log("--", f"running {name}" + (f" from slot {slot}" if slot is not None else ""))
        self.emit({"type": "program_source", "name": name, "source": src})
        self.blocks.stop(wait=True)
        self.actions = []
        self.emit({"type": "actions_reset", "title": name})
        self.runtime.start(src)

    def stop_program(self, wait=False):
        self.runtime.stop(wait=wait)
        self.blocks.stop(wait=wait)

    def console(self, text: str):
        self.console_lines.append(text)
        self.console_lines = self.console_lines[-500:]
        self.emit({"type": "console", "text": text})
        raw = text.encode("utf8")
        for i in range(0, len(raw), 255):
            part = raw[i:i + 255].decode("utf8", "ignore")
            if self.loop:
                asyncio.run_coroutine_threadsafe(self.send(P.console_notification(part), quiet=True), self.loop)

    def _console_from_thread(self, text):
        if self.loop:
            self.loop.call_soon_threadsafe(self.console, text)

    def _action_from_thread(self, text, replace):
        if self.loop:
            self.loop.call_soon_threadsafe(self._action, text, replace)

    def _action(self, text, replace):
        item = {"t": time.strftime("%H:%M:%S"), "text": text}
        if replace and self.actions:
            self.actions[-1] = item
        else:
            self.actions.append(item)
            self.actions = self.actions[-200:]
        self.emit({"type": "action", "item": item, "replace": replace})

    def _tunnel_from_program(self, data: bytes):
        self.send_threadsafe(bytes([P.TUNNEL_MESSAGE]) + struct.pack("<H", len(data)) + data)

    def _state_from_thread(self, running):
        if not self.loop:
            return
        def go():
            self.emit({"type": "program", "running": running})
            asyncio.ensure_future(self.send(P.program_flow_notification(not running)))
        self.loop.call_soon_threadsafe(go)

    # ------------------------------------------------------------ device notifications
    def set_notify_interval(self, ms):
        self.notify_interval = ms
        if self._notify_task:
            self._notify_task.cancel()
            self._notify_task = None
        if ms and self.loop:
            self._notify_task = asyncio.ensure_future(self._notify_loop())

    async def _notify_loop(self):
        try:
            while self.notify_interval:
                await self.send(self.device_status(), quiet=True)
                await asyncio.sleep(max(0.05, self.notify_interval / 1000))
        except asyncio.CancelledError:
            pass

    def device_status(self) -> bytes:
        w = self.world
        with w.lock:
            parts = [P.dev_battery(100),
                     P.dev_imu(0, 0, int(round(w.yaw())), 0, 0, (0, 0, 1000)),
                     P.dev_matrix(w.pixels)]
            for i, p in enumerate(PORTS):
                d = w.config.get(p, {})
                t = d.get("type")
                if t == "motor" and p in w.motors:
                    m = w.motors[p]
                    speed = int(max(-100, min(100, m.vel / m.vmax * 100)))
                    rel = max(-2**31, min(2**31 - 1, m.relative()))
                    parts.append(P.dev_motor(i, MOTOR_TYPE_ID.get(m.model, 0x30), m.absolute(),
                                             m.power(), speed, rel))
                elif t == "color":
                    cid, (r, g, b), _ = w.color_reading()
                    parts.append(P.dev_color(i, cid if cid >= 0 else -1, r, g, b))
                elif t == "distance":
                    parts.append(P.dev_distance(i, w.distance_mm()))
                elif t == "force":
                    f, pr = w.force_value()
                    parts.append(P.dev_force(i, f, pr))
        return P.device_notification(parts)
