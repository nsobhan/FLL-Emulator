# Stand-in for the hub's `motor_pair` module: every name is looked up in the simulator.
import _host


def __getattr__(name):
    return _host.attr("motor_pair." + name)
