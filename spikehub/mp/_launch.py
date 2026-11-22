# Starts a program the way the hub does: imports `program` (program.py or program.mpy).
import sys

_real_sys = sys


class _Sys:
    # Word Block programs set sys.tracebacklimit, which desktop MicroPython lacks.
    tracebacklimit = 1000

    def __getattr__(self, name):
        return getattr(_real_sys, name)


sys.modules["sys"] = _Sys()

import _host
_host.rpc({"hello": 1})

try:
    __import__(_real_sys.argv[1] if len(_real_sys.argv) > 1 else "program")
except SystemExit:
    pass
except KeyboardInterrupt:
    pass
except BaseException as e:
    _real_sys.print_exception(e)
    _real_sys.exit(1)
