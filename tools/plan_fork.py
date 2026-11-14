"""Run one function in a forked child and take its pickled answer back.

The edition queue's parent keeps the heap a plan pass leaves behind (~2.4 GB
RSS after the first plan, none of it returned by malloc_trim): the plan runs
here in a child that exits, so its heap goes with it. edition_queue.plan_forked
is the caller; it ships back what the parent reads from the caches the plan
fills (fa._PLANNED_DIRS, the time of the last cache save)."""
import ctypes
import os
import pickle
import signal
import tempfile
import threading
import time
from pathlib import Path

#: Where a child leaves its answer for the parent (a pipe would block the child once it fills).
DIR = Path(os.path.expanduser("~/.cache/corpus_queue"))
#: Seconds the parent waits for a child before it kills it and plans in-process (a cold plan is minutes).
TIMEOUT = float(os.environ.get("CT_PLAN_FORK_TIMEOUT", "3600"))


def enabled():
    return os.environ.get("CT_PLAN_FORK", "1") not in ("", "0")


def fresh_locks(locks):
    """In the child, replace each (module, name) lock, or each lock in a dict, with a new one: a thread of the
    parent may have held it at the fork, and nothing would ever release it here."""
    for mod, name in locks:
        cur = getattr(mod, name)
        if isinstance(cur, dict):
            for k in list(cur):
                cur[k] = threading.Lock()
        else:
            setattr(mod, name, threading.Lock())


def run(fn, locks=()):
    """("ok", fn()'s answer), ("err", the exception fn raised) or ("failed", why: no fork, the child died,
    timed out or left an answer that would not load); the caller plans in-process on "failed"."""
    try:
        DIR.mkdir(parents=True, exist_ok=True)
        fd, path = tempfile.mkstemp(dir=DIR, prefix="plan_fork.", suffix=".pickle")
        os.close(fd)
    except OSError as e:
        return "failed", f"no answer file ({type(e).__name__}: {e})"
    try:
        pid = os.fork()
    except OSError as e:
        os.unlink(path)
        return "failed", f"fork ({type(e).__name__}: {e})"
    if pid == 0:
        code = 1
        try:
            try:  # the parent's end (a reload's re-exec) takes the child with it
                ctypes.CDLL("libc.so.6").prctl(1, signal.SIGKILL)
            except (OSError, AttributeError):
                pass
            fresh_locks(locks)
            try:
                answer = ("ok", fn())
            except BaseException as e:
                answer = ("err", e)
            try:
                blob = pickle.dumps(answer, protocol=pickle.HIGHEST_PROTOCOL)
            except Exception as e:  # an exception that will not pickle, or a plan that holds an object that will not
                blob = pickle.dumps(("failed", f"answer not picklable ({type(e).__name__}: {e})"))
            with open(path, "wb") as f:
                f.write(blob)
            os.rename(path, path + ".ready")  # whole before the parent looks
            code = 0
        finally:
            os._exit(code)
    begun = time.monotonic()
    ready = path + ".ready"
    gone = False  # the child reaped (by the parent's own waitpid(-1) reaper, which may take it first)
    try:
        while not os.path.exists(ready):
            if not gone:
                try:
                    done, _ = os.waitpid(pid, os.WNOHANG)
                except ChildProcessError:
                    done = pid
                if done:
                    gone = True
                    continue  # one more look for the answer it left
            else:
                return "failed", "child ended with no answer"
            if time.monotonic() - begun > TIMEOUT:
                os.kill(pid, signal.SIGKILL)
                try:
                    os.waitpid(pid, 0)
                except ChildProcessError:
                    pass
                return "failed", f"timed out after {TIMEOUT:.0f}s"
            time.sleep(0.5)
        if not gone:
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
        try:
            with open(ready, "rb") as f:
                return pickle.load(f)
        except Exception as e:
            return "failed", f"answer unreadable ({type(e).__name__}: {e})"
    finally:
        for name in (path, ready):
            try:
                os.unlink(name)
            except OSError:
                pass
