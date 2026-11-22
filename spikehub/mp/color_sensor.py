# Stand-in for the hub's `color_sensor` module: every name is looked up in the simulator.
import _host


def __getattr__(name):
    return _host.attr("color_sensor." + name)
