"""Local web page showing the simulated robot, hub and protocol log."""
from __future__ import annotations

import asyncio
import json
import os

from aiohttp import web, WSMsgType

from .service import HubService
from .world import MATS, default_config
from .blocks import ProjectError
from .examples import EXAMPLES

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def make_app(service: HubService) -> web.Application:
    world = service.world
    app = web.Application(client_max_size=32 * 1024 * 1024)

    async def index(request):
        return web.FileResponse(os.path.join(STATIC, "index.html"))

    async def ws_handler(request):
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        queue: asyncio.Queue = asyncio.Queue()

        def listener(msg):
            queue.put_nowait(msg)

        service.listeners.append(listener)
        await ws.send_json({
            "type": "init",
            "mats": {k: {kk: v[kk] for kk in ("name", "w", "h", "shapes", "start", "hint")} for k, v in MATS.items()},
            "mat": world.mat_key, "config": world.config, "log": service.log_items,
            "console": "".join(service.console_lines), "ble": service.ble_state,
            "ble_detail": service.ble_detail, "slots": service.slot_summary(),
            "running": service.program_running(), "trail": world.trail,
            "examples": [{"key": k, "name": v["name"], "mat": v["mat"]} for k, v in EXAMPLES.items()],
            "firmware": ".".join(map(str, service.firmware)), "hub_name": service.hub_name,
            "actions": service.actions,
            "project": project_info(),
        })

        async def pump():
            sent_trail = len(world.trail)
            while not ws.closed:
                snap = world.snapshot()
                with world.lock:
                    if len(world.trail) < sent_trail:
                        sent_trail = 0
                        snap["trail_reset"] = True
                    snap["trail_add"] = world.trail[sent_trail:]
                    sent_trail = len(world.trail)
                snap["type"] = "state"
                snap["running"] = service.program_running()
                snap["active"] = service.active_blocks()
                msgs = [snap]
                while not queue.empty():
                    msgs.append(queue.get_nowait())
                try:
                    await ws.send_str(json.dumps({"type": "batch", "items": msgs}))
                except ConnectionResetError:
                    break
                await asyncio.sleep(1 / 30)

        pump_task = asyncio.ensure_future(pump())
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    handle_command(json.loads(msg.data))
                except Exception as e:
                    service.log("--", f"UI command failed: {e}")
        finally:
            pump_task.cancel()
            if listener in service.listeners:
                service.listeners.remove(listener)
        return ws

    def project_info():
        p = service.project
        if p is None:
            return None
        info = {"type": p.type, "name": p.name}
        if p.type == "python":
            info["python"] = p.python
        else:
            info["scripts"] = p.scripts()
            info["sounds"] = sorted(p.sounds)
        return info

    async def upload_project(request):
        data = await request.read()
        name = request.headers.get("X-Filename", "project.llsp3")
        if len(data) > 30_000_000:
            return web.json_response({"error": "That file is too big for a SPIKE project."}, status=413)
        try:
            return web.json_response(service.load_project(data, name))
        except ProjectError as e:
            return web.json_response({"error": str(e)}, status=400)
        except Exception as e:
            return web.json_response({"error": f"Couldn't read that project file ({e})."}, status=400)

    async def project_sound(request):
        p = service.project
        f = request.match_info["file"]
        snd = next((s for s in (p.sounds.values() if p else []) if s["file"] == f), None)
        if snd is None:
            raise web.HTTPNotFound()
        ctype = "audio/wav" if f.endswith(".wav") else "audio/mpeg"
        return web.Response(body=snd["data"], content_type=ctype)

    def handle_command(c):
        kind = c.get("cmd")
        if kind == "set_mat":
            service.stop_program()
            world.set_mat(c["mat"])
            service.emit({"type": "mat", "mat": world.mat_key})
        elif kind == "reset_robot":
            world.reset_robot()
        elif kind == "place_robot":
            with world.lock:
                world.x, world.y = float(c["x"]), float(c["y"])
                if "heading" in c:
                    world.heading = float(c["heading"])
                world.trail = [(world.x, world.y)]
        elif kind == "clear_trail":
            with world.lock:
                world.trail = [(world.x, world.y)]
        elif kind == "button":
            import time
            with world.lock:
                world.buttons[c["name"]] = bool(c["pressed"])
                world.button_since[c["name"]] = time.monotonic()
        elif kind == "force":
            world.force_manual = bool(c["pressed"])
        elif kind == "config":
            cfg = c["config"]
            world.apply_config(cfg)
            service.emit({"type": "config", "config": world.config})
        elif kind == "reset_config":
            world.apply_config(default_config())
            service.emit({"type": "config", "config": world.config})
        elif kind == "run_source":
            service.run_source(c["source"], name=c.get("name", "pasted program"))
        elif kind == "run_example":
            ex = EXAMPLES[c["key"]]
            if world.mat_key != ex["mat"]:
                world.set_mat(ex["mat"])
                service.emit({"type": "mat", "mat": world.mat_key})
            else:
                world.reset_robot()
            service.run_source(ex["source"], name=ex["name"])
        elif kind == "run_slot":
            slot = int(c["slot"])
            if slot in service.slots:
                service.start_slot(slot)
        elif kind == "stop":
            service.stop_program()
        elif kind == "run_project":
            service.run_project()
        elif kind == "clear_console":
            service.console_lines = []

    async def snippet(request):
        return web.FileResponse(os.path.join(os.path.dirname(os.path.dirname(STATIC)),
                                             "laptop-extension", "show-virtual-hub.js"))

    app.router.add_get("/", index)
    app.router.add_get("/laptop/show-virtual-hub.js", snippet)
    app.router.add_get("/ws", ws_handler)
    app.router.add_post("/api/project", upload_project)
    app.router.add_get("/project/sound/{file}", project_sound)
    app.router.add_static("/static", STATIC)
    return app
