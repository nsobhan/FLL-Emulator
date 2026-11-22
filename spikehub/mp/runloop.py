# hub OS 3 `runloop` module on top of the simulator's scheduler.
import time
import _sched


def run(*functions):
    started = [_sched.spawn(f) for f in functions]
    _sched.run(until=lambda: all(t.done for t in started))


def sleep_ms(duration):
    yield int(duration)


def until(function, timeout=0):
    start = time.ticks_ms()
    while not function():
        if timeout and time.ticks_diff(time.ticks_ms(), start) >= timeout:
            return False
        yield
    return True
