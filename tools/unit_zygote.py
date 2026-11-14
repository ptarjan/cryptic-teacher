#!/usr/bin/env python3
"""A fork server for the edition queue's unit processes.

Every unit used to be a fresh `python edition_queue.py unit ...`: ~170 MB of
private memory right after its imports (numpy, PIL, ~140 tools/ modules), times
the 14-24 units the RAM gate allows. Here one long-lived process imports what a
unit loads once (the load_unit set of edition_queue), and forks each unit from
that: the imported pages are shared copy-on-write, so a unit costs its own work
only (measured: Pss ~170 -> ~25 MB right after start).

Protocol (a unix socketpair the queue holds the other end of, close-on-exec,
so a queue that exits or re-execs ends this process by EOF):
  zygote -> queue: "ready\\n" once its imports are done.
  queue -> zygote: one JSON line {"argv": [...], "env": {...}}.
  zygote -> queue: one JSON line {"pid": N} or {"stale": true} (the tools/
  tree moved since the imports: the queue spawns that unit afresh, and
  restarts this process) or {"error": "..."}.
The unit is the queue's own child, not this process's: it is forked twice, the
middle process exits, and the queue (PR_SET_CHILD_SUBREAPER) inherits the
orphan, so its waitpid, exit codes (rc 75 ...) and killpg work as for
os.posix_spawn. The unit runs edition_queue.py as __main__ (runpy) with the
argv and the environment it would have had, in its own process group, with the
queue's stdout and stderr.
"""
import json
import os
import signal
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))

#: Environment keys that may differ between the queue's and a unit's environment
#: (all read at call time, never at import), else the unit is spawned afresh.
PER_UNIT_ENV = frozenset({"CT_EDITION_UNIT", "SPT_NOENV", "CT_VLM_DEFER", "CT_VLM_SPOOL", "OCR_REMOTE_DEFER",
                          "OCR_REMOTE"})

ENV = "CT_UNIT_ZYGOTE"  # "0" turns it off


def preload(modules):
    """Import the tools/ modules a unit of any paper loads (edition_queue.load_unit), not the queue's own."""
    import importlib
    import code_reach
    reach = set()
    for name in modules:
        reach |= code_reach.modules(name)
    for name in sorted(reach | {"downloads", "edition_commit", "ocr_remote", "scan_queue"}):
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as err:
            if (err.name or "").partition(".")[0] in reach:
                raise


def unit_process(req, sock):
    """In the forked unit process: become `req`'s unit (EXITS)."""
    code = 1
    try:
        os.setpgid(0, 0)
        signal.pthread_sigmask(signal.SIG_SETMASK, ())
        os.close(sock.detach())
        os.environ.clear()
        os.environ.update(req["env"])
        sys.argv = list(req["argv"][1:])
        import runpy
        runpy.run_path(sys.argv[0], run_name="__main__")
        code = 0
    except SystemExit as e:
        if e.code is None:
            code = 0
        elif isinstance(e.code, int):
            code = e.code
        else:
            print(e.code, file=sys.stderr)
    except BaseException:
        import traceback
        traceback.print_exc()
    finally:
        for f in (sys.stdout, sys.stderr):
            try:
                f.flush()
            except Exception:
                pass
        os._exit(code)


def fork_unit(req, sock):
    """The pid of a new unit process of `req`, orphaned to the queue."""
    r, w = os.pipe()
    mid = os.fork()
    if mid == 0:
        try:
            os.close(r)
            pid = os.fork()
            if pid == 0:
                os.close(w)
                unit_process(req, sock)  # never returns
            os.write(w, str(pid).encode())
        finally:
            os._exit(0)
    os.close(w)
    with os.fdopen(r) as f:
        text = f.read()
    os.waitpid(mid, 0)
    return int(text)


def serve(fd, modules):
    import socket
    for var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(var, "1")  # as edition_queue's unit dispatch sets them, before numpy loads
    sock = socket.socket(fileno=fd)
    import code_reach
    sig = code_reach._signature_of()
    preload(modules)
    sock.sendall(b"ready\n")
    for line in sock.makefile("rb"):
        try:
            if code_reach._signature_of() != sig:
                sock.sendall(b'{"stale": true}\n')
                return
            req = json.loads(line)
            reply = {"pid": fork_unit(req, sock)}
        except Exception as e:  # the queue spawns that unit afresh
            reply = {"error": repr(e)}
        sock.sendall(json.dumps(reply).encode() + b"\n")


class Client:
    """The queue's end: Client(modules).spawn(argv, env) is the pid of a unit forked by the server, or None
    (not ready, off, stale, broken, env differs: spawn it afresh, as before)."""

    def __init__(self, modules):
        self.modules = list(modules)
        self.proc = None
        self.sock = None
        self.base = None
        self.ready = False
        self.failures = 0
        self.buf = b""

    def enabled(self):
        if os.environ.get(ENV, "1") == "0" or self.failures >= 3 or not hasattr(os, "fork"):
            return False
        import importlib.util
        return importlib.util.find_spec("setproctitle") is not None  # units name themselves in ps

    def start(self):
        import socket
        import subprocess
        import ctypes
        mine, theirs = socket.socketpair()
        try:
            ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0)  # PR_SET_CHILD_SUBREAPER
        except (OSError, AttributeError):
            self.failures = 99
            return
        self.base = dict(os.environ)
        self.proc = subprocess.Popen([sys.executable, os.path.join(TOOLS, "unit_zygote.py"), "serve", str(theirs.fileno()),
                                      *self.modules], pass_fds=[theirs.fileno()], stdin=subprocess.DEVNULL)
        theirs.close()
        self.sock, self.ready, self.buf = mine, False, b""

    def stop(self):
        if self.sock is not None:
            self.sock.close()
        if self.proc is not None:
            self.proc.poll()
        self.sock = self.proc = None
        self.ready = False

    def _line(self, timeout):
        import select
        end = None if timeout is None else __import__("time").monotonic() + timeout
        while b"\n" not in self.buf:
            left = None if end is None else max(0, end - __import__("time").monotonic())
            if not select.select([self.sock], [], [], left)[0]:
                return None
            chunk = self.sock.recv(4096)
            if not chunk:
                raise EOFError("unit zygote closed")
            self.buf += chunk
        line, _, self.buf = self.buf.partition(b"\n")
        return line

    def spawn(self, argv, env):
        if not self.enabled():
            return None
        try:
            if self.proc is None:
                self.start()
                return None
            if self.proc.poll() is not None:
                raise EOFError("unit zygote exited")
            if not self.ready:
                line = self._line(0)
                if line is None:
                    return None
                self.ready = line == b"ready"
                if not self.ready:
                    raise EOFError(f"unit zygote said {line!r}")
            if {k for k in set(env) | set(self.base) if env.get(k) != self.base.get(k)} - PER_UNIT_ENV:
                return None
            self.sock.sendall(json.dumps({"argv": argv, "env": env}).encode() + b"\n")
            line = self._line(30)
            if line is None:
                raise EOFError("unit zygote did not answer")
            reply = json.loads(line)
            if reply.get("stale"):
                self.stop()
                return None
            return reply.get("pid")
        except (OSError, EOFError, ValueError) as e:
            print(f"unit zygote: {e}; spawning units afresh", file=sys.stderr, flush=True)
            self.failures += 1
            self.stop()
            return None


if __name__ == "__main__" and sys.argv[1:2] == ["serve"]:
    serve(int(sys.argv[2]), sys.argv[3:])
