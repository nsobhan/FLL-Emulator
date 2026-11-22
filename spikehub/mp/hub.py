# Stand-in for the hub's `hub` module. `config` is local; everything else
# (light_matrix, port, sound, button, motion_sensor, light, ...) is looked up in the simulator.
import _host

config = {"module_tunnel": _host.tunnel}


def __getattr__(name):
    return _host.attr("hub." + name)
