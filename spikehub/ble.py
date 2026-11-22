"""Bluetooth LE peripheral that looks like a SPIKE Prime hub (macOS, via bless/CoreBluetooth)."""
from __future__ import annotations

import asyncio
import logging

from . import protocol as P
from .service import HubService

LOG = logging.getLogger("ble")


def _make_delegate_class(state):
    """Subclass bless's CoreBluetooth delegate to learn about subscriptions,
    the central's maximum notification size, and when the send queue frees up."""
    from bless.backends.corebluetooth import peripheral_manager_delegate as pmd

    Base = pmd.PeripheralManagerDelegate

    class HubDelegate(Base):
        def peripheralManager_central_didSubscribeToCharacteristic_(self, pm, central, characteristic):
            Base.peripheralManager_central_didSubscribeToCharacteristic_(self, pm, central, characteristic)
            try:
                size = int(central.maximumUpdateValueLength())
            except Exception:
                size = 20
            state["call"](state["on_subscribe"], central.identifier().UUIDString(), size)

        def peripheralManager_central_didUnsubscribeFromCharacteristic_(self, pm, central, characteristic):
            try:
                Base.peripheralManager_central_didUnsubscribeFromCharacteristic_(self, pm, central, characteristic)
            except KeyError:
                pass
            state["call"](state["on_unsubscribe"], central.identifier().UUIDString())

        def peripheralManagerIsReadyToUpdateSubscribers_(self, pm):
            state["call"](state["on_ready"])

        def peripheralManager_didReceiveReadRequest_(self, pm, request):
            state["call"](state["on_event"], "app read characteristic "
                          + request.characteristic().UUID().UUIDString())
            Base.peripheralManager_didReceiveReadRequest_(self, pm, request)

        def peripheralManager_didReceiveWriteRequests_(self, pm, requests):
            for r in requests:
                state["call"](state["on_event"], "app wrote %d bytes to %s" % (
                    len(bytes(r.value() or b"")), r.characteristic().UUID().UUIDString()))
            return Base.peripheralManager_didReceiveWriteRequests_(self, pm, requests)

        def peripheralManagerDidUpdateState_(self, pm):
            state["call"](state["on_event"], "Bluetooth radio state %d" % pm.state())
            return Base.peripheralManagerDidUpdateState_(self, pm)

    return HubDelegate


class BleHub:
    def __init__(self, service: HubService, name="Sim Hub"):
        self.service = service
        self.name = name[:9]   # advertisement only has room for a short name next to the UUID
        self.server = None
        self.notify_size = 20
        self._ready = asyncio.Event()
        self._send_lock = asyncio.Lock()
        self.centrals = set()

    async def start(self):
        loop = asyncio.get_running_loop()
        try:
            from bless import BlessServer, GATTCharacteristicProperties as Prop, GATTAttributePermissions as Perm
            from bless.backends.corebluetooth import server as cb_server
        except Exception as e:  # pragma: no cover
            self.service.set_ble("unavailable", f"bless could not load: {e}")
            return

        state = {
            "call": lambda f, *a: loop.call_soon_threadsafe(f, *a),
            "on_subscribe": self._on_subscribe,
            "on_unsubscribe": self._on_unsubscribe,
            "on_ready": self._ready.set,
            "on_event": lambda text: self.service.log("ble", text),
        }
        cb_server.PeripheralManagerDelegate = _make_delegate_class(state)

        self.server = BlessServer(name=self.name, loop=loop)
        self.server.read_request_func = lambda char, **kw: char.value
        self.server.write_request_func = self._on_write
        await self.server.add_new_service(P.SERVICE_UUID)
        await self.server.add_new_characteristic(
            P.SERVICE_UUID, P.RX_UUID,
            Prop.write_without_response | Prop.write, None, Perm.writeable)
        await self.server.add_new_characteristic(
            P.SERVICE_UUID, P.TX_UUID, Prop.notify, None, Perm.readable)
        try:
            await self.server.start()
        except Exception as e:
            self.service.set_ble("error", f"could not start advertising: {e}. "
                                          "Is Bluetooth on, and does this terminal have Bluetooth permission?")
            return
        self.service.transport_send = self.send_frame
        self.service.set_ble("advertising", f"as '{self.name}'")

    # -- callbacks (already on the asyncio loop thread unless noted)
    def _on_write(self, characteristic, value, **kw):
        # bless calls this from the CoreBluetooth queue
        data = bytes(value)
        self.service.loop.call_soon_threadsafe(self.service.on_data, data)

    def _on_subscribe(self, central_id, size):
        self.service.log("ble", f"app {central_id[:8]} subscribed to notifications (max {size} bytes)")
        self.centrals.add(central_id)
        self.notify_size = max(20, min(size, 512))
        self.service.reader = P.FrameReader()
        self.service.set_ble("connected", f"notify size {self.notify_size} bytes")

    def _on_unsubscribe(self, central_id):
        self.centrals.discard(central_id)
        if not self.centrals:
            self.service.runtime.stop()
            self.service.set_ble("advertising", "app disconnected")

    # -- outgoing
    async def send_frame(self, frame: bytes):
        if not self.server or not self.centrals:
            return
        async with self._send_lock:
            for i in range(0, len(frame), self.notify_size):
                packet = frame[i:i + self.notify_size]
                char = self.server.get_characteristic(P.TX_UUID)
                for attempt in range(200):
                    char.value = bytearray(packet)
                    if self.server.update_value(P.SERVICE_UUID, P.TX_UUID):
                        break
                    # transmit queue full: wait until CoreBluetooth says it is ready again
                    self._ready.clear()
                    try:
                        await asyncio.wait_for(self._ready.wait(), 0.25)
                    except asyncio.TimeoutError:
                        pass
                else:
                    LOG.warning("dropped a packet after repeated retries")
