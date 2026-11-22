"""SPIKE Prime BLE protocol: framing (COBS + XOR) and message encode/decode.

The COBS routines follow LEGO Education's published reference implementation
(https://github.com/LEGO/spike-prime-docs, Apache License 2.0, (c) 2024 The LEGO Group).
"""
from __future__ import annotations

import struct
from binascii import crc32 as _crc32

SERVICE_UUID = "0000FD02-0000-1000-8000-00805F9B34FB"
RX_UUID = "0000FD02-0001-1000-8000-00805F9B34FB"  # app -> hub (write without response)
TX_UUID = "0000FD02-0002-1000-8000-00805F9B34FB"  # hub -> app (notify)

# ---------------------------------------------------------------- framing
DELIMITER = 0x02
NO_DELIMITER = 0xFF
COBS_CODE_OFFSET = DELIMITER
MAX_BLOCK_SIZE = 84
XOR = 3


def cobs_encode(data: bytes) -> bytearray:
    buf = bytearray()
    code_index = block = 0

    def begin_block():
        nonlocal code_index, block
        code_index = len(buf)
        buf.append(NO_DELIMITER)
        block = 1

    begin_block()
    for byte in data:
        if byte > DELIMITER:
            buf.append(byte)
            block += 1
        if byte <= DELIMITER or block > MAX_BLOCK_SIZE:
            if byte <= DELIMITER:
                buf[code_index] = byte * MAX_BLOCK_SIZE + block + COBS_CODE_OFFSET
            begin_block()
    buf[code_index] = block + COBS_CODE_OFFSET
    return buf


def cobs_decode(data: bytes) -> bytearray:
    buf = bytearray()

    def unescape(code: int):
        if code == 0xFF:
            return None, MAX_BLOCK_SIZE + 1
        value, block = divmod(code - COBS_CODE_OFFSET, MAX_BLOCK_SIZE)
        if block == 0:
            block = MAX_BLOCK_SIZE
            value -= 1
        return value, block

    value, block = unescape(data[0])
    for byte in data[1:]:
        block -= 1
        if block > 0:
            buf.append(byte)
            continue
        if value is not None:
            buf.append(value)
        value, block = unescape(byte)
    return buf


def pack(payload: bytes) -> bytes:
    """Message bytes -> wire frame (COBS, XOR 3, trailing 0x02)."""
    buf = cobs_encode(payload)
    for i in range(len(buf)):
        buf[i] ^= XOR
    buf.append(DELIMITER)
    return bytes(buf)


def unpack(frame: bytes) -> bytes:
    """Wire frame -> message bytes."""
    start = 1 if frame and frame[0] == 0x01 else 0
    end = len(frame) - 1 if frame and frame[-1] == DELIMITER else len(frame)
    unframed = bytes(b ^ XOR for b in frame[start:end])
    return bytes(cobs_decode(unframed))


class FrameReader:
    """Reassembles frames that arrive split across several BLE writes."""

    def __init__(self):
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        frames = []
        for b in data:
            self._buf.append(b)
            if b == DELIMITER:
                frames.append(bytes(self._buf))
                self._buf.clear()
        return frames


def crc(data: bytes, seed: int = 0, align: int = 4) -> int:
    rem = len(data) % align
    if rem:
        data = data + b"\x00" * (align - rem)
    return _crc32(data, seed)


# ---------------------------------------------------------------- message ids
INFO_REQUEST = 0x00
INFO_RESPONSE = 0x01
START_FIRMWARE_UPLOAD_REQUEST = 0x0A
START_FIRMWARE_UPLOAD_RESPONSE = 0x0B
START_FILE_UPLOAD_REQUEST = 0x0C
START_FILE_UPLOAD_RESPONSE = 0x0D
TRANSFER_CHUNK_REQUEST = 0x10
TRANSFER_CHUNK_RESPONSE = 0x11
BEGIN_FIRMWARE_UPDATE_REQUEST = 0x14
BEGIN_FIRMWARE_UPDATE_RESPONSE = 0x15
SET_HUB_NAME_REQUEST = 0x16
SET_HUB_NAME_RESPONSE = 0x17
GET_HUB_NAME_REQUEST = 0x18
GET_HUB_NAME_RESPONSE = 0x19
DEVICE_UUID_REQUEST = 0x1A
DEVICE_UUID_RESPONSE = 0x1B
PROGRAM_FLOW_REQUEST = 0x1E
PROGRAM_FLOW_RESPONSE = 0x1F
PROGRAM_FLOW_NOTIFICATION = 0x20
CONSOLE_NOTIFICATION = 0x21
DEVICE_NOTIFICATION_REQUEST = 0x28
DEVICE_NOTIFICATION_RESPONSE = 0x29
TUNNEL_MESSAGE = 0x32
DEVICE_NOTIFICATION = 0x3C
CLEAR_SLOT_REQUEST = 0x46
CLEAR_SLOT_RESPONSE = 0x47

MESSAGE_NAMES = {v: k for k, v in globals().items() if k.isupper() and isinstance(v, int)
                 and k.endswith(("REQUEST", "RESPONSE", "NOTIFICATION", "MESSAGE"))}

ACK, NACK = 0x00, 0x01


def cstr(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("utf8", "replace")


def status(msg_id: int, ok: bool = True) -> bytes:
    return bytes([msg_id, ACK if ok else NACK])


def info_response(rpc=(1, 0, 0), fw=(1, 6, 62), max_packet=180, max_message=1000,
                  max_chunk=400, product=0x0000) -> bytes:
    return struct.pack("<BBBHBBHHHHH", INFO_RESPONSE, rpc[0], rpc[1], rpc[2],
                       fw[0], fw[1], fw[2], max_packet, max_message, max_chunk, product)


def name_response(name: str) -> bytes:
    raw = name.encode("utf8")[:29]
    return bytes([GET_HUB_NAME_RESPONSE]) + raw + b"\0" * (30 - len(raw))


def console_notification(text: str) -> bytes:
    raw = text.encode("utf8")[:255]
    return bytes([CONSOLE_NOTIFICATION]) + raw + b"\0"


def program_flow_notification(stop: bool) -> bytes:
    return bytes([PROGRAM_FLOW_NOTIFICATION, 1 if stop else 0])


# ---------------------------------------------------------------- device notification parts
def dev_battery(pct: int) -> bytes:
    return struct.pack("<BB", 0x00, pct)


def dev_imu(up_face, yaw_face, yaw, pitch, roll, acc=(0, 0, 0), gyro=(0, 0, 0)) -> bytes:
    return struct.pack("<BBBhhhhhhhhh", 0x01, up_face, yaw_face, yaw, pitch, roll, *acc, *gyro)


def dev_matrix(pixels: list[int]) -> bytes:
    return struct.pack("<B25B", 0x02, *pixels)


def dev_motor(port, dtype, abs_pos, power, speed, pos) -> bytes:
    return struct.pack("<BBBhhbi", 0x0A, port, dtype, abs_pos, power, speed, pos)


def dev_force(port, value, pressed) -> bytes:
    return struct.pack("<BBBB", 0x0B, port, value, 1 if pressed else 0)


def dev_color(port, color, r, g, b) -> bytes:
    return struct.pack("<BBbHHH", 0x0C, port, color, r, g, b)


def dev_distance(port, mm) -> bytes:
    return struct.pack("<BBh", 0x0D, port, mm)


def device_notification(parts: list[bytes]) -> bytes:
    payload = b"".join(parts)
    return struct.pack("<BH", DEVICE_NOTIFICATION, len(payload)) + payload
