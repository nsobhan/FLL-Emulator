# Stand-in for the hub's `orientation` module: every name is looked up in the simulator.
import _host


def __getattr__(name):
    return _host.attr("orientation." + name)
