# A small cooperative scheduler, like the one on the hub.
# Tasks are generators/coroutines. `yield` gives up the turn;
# `yield <ms>` sleeps for that many milliseconds.
import time

TICK_MS = 2
tasks = []
hooks = []        # functions called once per scheduler pass
_last_hook = 0


class Task:
    def __init__(self, gen):
        self.gen = gen
        self.wake = time.ticks_ms()
        self.done = False
        self.result = None
        self.pending = None   # exception to throw in at the next step


current = None


def spawn(gen):
    t = Task(gen)
    tasks.append(t)
    return t


def throw(task, exc):
    task.pending = exc
    task.wake = time.ticks_ms()


def _step(t, now):
    global current
    current = t
    try:
        if t.pending is not None:
            exc, t.pending = t.pending, None
            y = t.gen.throw(exc)
        else:
            y = t.gen.send(None)
    except StopIteration as e:
        t.done = True
        t.result = e.value if e.args else None
        return
    finally:
        current = None
    if y is None:
        t.wake = now
    else:
        try:
            t.wake = time.ticks_add(now, int(y))
        except (TypeError, ValueError):
            t.wake = now


def run(until=None):
    global _last_hook
    while True:
        now = time.ticks_ms()
        if time.ticks_diff(now, _last_hook) >= 20:
            _last_hook = now
            for h in list(hooks):
                h()
        tasks[:] = [t for t in tasks if not t.done]
        if until is not None and until():
            return
        if not tasks:
            return
        for t in list(tasks):
            if not t.done and time.ticks_diff(now, t.wake) >= 0:
                _step(t, now)
        time.sleep_ms(TICK_MS)
