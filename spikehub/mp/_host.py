# MicroPython side: talks to the simulator (CPython) over a local socket.
# Each request is one JSON line; each reply is one JSON line.
import socket
import json
import os

_sock = None
_cache = {}

_ERRORS = {
    "OSError": OSError, "ValueError": ValueError, "TypeError": TypeError,
    "RuntimeError": RuntimeError, "AttributeError": AttributeError,
    "IndexError": IndexError, "KeyError": KeyError, "ZeroDivisionError": ZeroDivisionError,
}


def _conn():
    global _sock
    if _sock is None:
        port = int(os.getenv("SIMHUB_PORT"))
        s = socket.socket()
        s.connect(socket.getaddrinfo("127.0.0.1", port)[0][-1])
        _sock = s
    return _sock


def _decode(v):
    if isinstance(v, dict) and "__t" in v:
        return tuple(_decode(x) for x in v["__t"])
    if isinstance(v, list):
        return [_decode(x) for x in v]
    return v


def rpc(msg):
    s = _conn()
    s.write(json.dumps(msg) + "\n")
    line = s.readline()
    if not line:
        raise SystemExit
    r = json.loads(line)
    if "e" in r:
        kind, args = r["e"]
        raise _ERRORS.get(kind, RuntimeError)(*args)
    return r


class Op:
    """Returned by hub calls that take time (motor moves, text, beeps).
    The action has already started; awaiting it waits until it is done."""

    def __init__(self, op_id):
        self.id = op_id

    def __iter__(self):
        while not rpc({"d": self.id})["r"]:
            yield
        return 0

    __await__ = __iter__

    def __repr__(self):
        return "<awaitable>"


class Func:
    def __init__(self, path):
        self.path = path

    def __call__(self, *args, **kwargs):
        r = rpc({"c": self.path, "a": list(args), "k": kwargs})
        if "op" in r:
            return Op(r["op"])
        return _decode(r.get("r"))

    def __repr__(self):
        return "<function %s>" % self.path


class Mod:
    def __init__(self, path):
        self._path = path

    def __getattr__(self, name):
        return attr(self._path + "." + name)

    def __repr__(self):
        return "<module '%s'>" % self._path


def attr(path):
    if path in _cache:
        return _cache[path]
    r = rpc({"g": path})
    if "f" in r:
        v = Func(path)
    elif "m" in r:
        v = Mod(path)
    else:
        v = _decode(r.get("r"))
    _cache[path] = v
    return v


class Tunnel:
    """hub.config["module_tunnel"]: raw messages to and from the SPIKE app
    (used for sounds and graphs that play on the laptop)."""

    def __init__(self):
        self._cb = None

    def send(self, data):
        rpc({"c": "_tunnel.send", "a": [list(bytes(data))], "k": {}})
        return True

    def callback(self, cb=None):
        self._cb = cb
        import _sched
        if cb is not None and self._poll not in _sched.hooks:
            _sched.hooks.append(self._poll)

    def connected(self):
        return rpc({"c": "_tunnel.connected", "a": [], "k": {}}).get("r", False)

    def _poll(self):
        if self._cb is None:
            return
        for m in rpc({"c": "_tunnel.recv", "a": [], "k": {}}).get("r") or []:
            self._cb(bytes(m))


tunnel = Tunnel()
