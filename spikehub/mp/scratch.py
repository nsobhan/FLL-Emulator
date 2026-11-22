# Engine for Word Block programs (what `from _system import scratch` gives
# compiled block programs on the hub). Each block stack is compiled to:
#
#   async def stack_1(this):
#       while True:
#           with this as event:
#               await event          # wait for the stack's trigger
#               ...blocks...
import _sched
import _host


class _StackStop(Exception):
    pass


class _ProgramStop(Exception):
    pass


def _sleep(ms):
    yield int(ms)


class _Trigger:
    def __init__(self, stack):
        self.stack = stack

    def __iter__(self):
        st = self.stack
        while not st.triggered:
            yield
        st.triggered = False
        st.running = True
        _host.rpc({"c": "_vm.stack", "a": [st.label, True], "k": {}})

    __await__ = __iter__


class _BroadcastWait:
    def __init__(self, targets):
        self.targets = targets

    def __iter__(self):
        yield
        while any(t.triggered or t.running for t in self.targets):
            yield

    __await__ = __iter__


class Stack:
    def __init__(self, vm, fn, kind, arg=None):
        self.vm = vm
        self.fn = fn
        self.kind = kind
        self.arg = arg
        self.triggered = kind == "start"
        self.running = False
        self.prev = False
        self.task = None
        self.label = "%s %d" % ({"start": "When program starts", "when": "When",
                                 "receive": "When I receive"}[kind], len(vm.stacks) + 1)
        if kind == "receive":
            self.label = "When I receive %s" % arg

    # `with this as event:`
    def __enter__(self):
        return _Trigger(self)

    def __exit__(self, exc_type, exc, tb):
        if self.running:
            _host.rpc({"c": "_vm.stack", "a": [self.label, False], "k": {}})
        self.running = False
        return exc_type is not None and issubclass(exc_type, _StackStop)

    # blocks that act on the program
    def wait(self, ms):
        return _sleep(ms)

    def broadcast(self, message):
        return self.vm.broadcast(message)

    def stop_this(self):
        raise _StackStop()

    def stop_other(self):
        for s in self.vm.stacks:
            if s is not self and s.running:
                _sched.throw(s.task, _StackStop())

    def stop_all(self):
        raise SystemExit

    def stop_exit(self):
        raise SystemExit


class VM:
    def __init__(self):
        self.stacks = []

    def add_start(self, fn):
        self.stacks.append(Stack(self, fn, "start"))

    def add_when(self, fn, condition):
        s = Stack(self, fn, "when")
        s.condition = condition
        self.stacks.append(s)

    def add_receive(self, fn, message):
        self.stacks.append(Stack(self, fn, "receive", message))

    def broadcast(self, message):
        targets = [s for s in self.stacks if s.kind == "receive" and s.arg == message]
        for s in targets:
            if s.running:
                _sched.throw(s.task, _StackStop())   # restart it, like Scratch
            s.triggered = True
        return _BroadcastWait(targets)

    def _check_when(self):
        for s in self.stacks:
            if s.kind != "when":
                continue
            v = bool(s.condition())
            if v and not s.prev and not s.running and not s.triggered:
                s.triggered = True
            s.prev = v

    def idle(self):
        return not any(s.running or s.triggered for s in self.stacks)

    def run(self):
        # Like the hub, a block program keeps running (and motors keep turning)
        # after its stacks finish, until Stop is pressed or a stop block runs.
        for s in self.stacks:
            s.task = _sched.spawn(s.fn(s))
        if any(s.kind == "when" for s in self.stacks):
            _sched.hooks.append(self._check_when)
        _sched.run()
