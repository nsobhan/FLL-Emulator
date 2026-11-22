"""Start the virtual SPIKE Prime hub.

    .venv/bin/python run.py            # Bluetooth hub + robot view at http://localhost:8765
    .venv/bin/python run.py --no-ble   # robot view only (run sample or pasted programs)
"""
import argparse
import asyncio
import logging
import webbrowser

from aiohttp import web

from spikehub.ble import BleHub
from spikehub.service import HubService
from spikehub.web import make_app
from spikehub.world import World


async def main(args):
    world = World()
    world.start()
    fw = tuple(int(x) for x in args.firmware.split("."))
    service = HubService(world, firmware=fw, name=args.name)
    service.attach_loop(asyncio.get_running_loop())

    runner = web.AppRunner(make_app(service))
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", args.port).start()
    url = f"http://localhost:{args.port}"
    print(f"Robot view: {url}")
    if not args.no_browser:
        webbrowser.open(url)

    if args.no_ble:
        service.set_ble("off", "started with --no-ble")
    else:
        await BleHub(service, name=args.name).start()
        print(f"Bluetooth: {service.ble_state} {service.ble_detail}")
    await asyncio.Event().wait()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Virtual SPIKE Prime hub")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--name", default="Sim Hub", help="Bluetooth name (max 9 characters)")
    p.add_argument("--firmware", default="1.6.62", help="firmware version reported to the app")
    p.add_argument("--no-ble", action="store_true", help="don't start the Bluetooth hub")
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--debug", action="store_true")
    a = p.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.debug else logging.WARNING)
    try:
        asyncio.run(main(a))
    except KeyboardInterrupt:
        pass
