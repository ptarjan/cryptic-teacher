"""Hot reload for the long-running queues (tools/edition_queue.py).

Paul 10-18: "I hate waiting queue cycles. Can't the queues just get new code
automatically or can't you just kill -HUP them and they wind down and
restart."

A queue reloads on either of two triggers, both ending the same way (the
queue stops starting units, hands the ones running over to its next image or
drains them, and exits RELOAD_RC so the wrapper, tools/ocr_full_pass.sh,
moves its tree to origin/master and starts the new code at once):

  * `kill -HUP <the python pid>` (never the wrapper's bash: that one stops);
  * Watcher: every CT_RELOAD_POLL seconds (180) a background thread fetches
    origin/master and compares the tree's own HEAD with it, over the paths
    code_changed() calls code. A puzzle-only push (durable.sh pushes puzzles
    every 300s) never triggers it. CT_AUTO_RELOAD=0 turns this trigger off.

CT_RELOAD_GRACE (1200s) caps how long a queue that cannot hand its units over
(no --handoff) waits for them before it stops them the way a game does (TERM,
left deferred, never a failure).
"""
import os
import subprocess
import threading
from pathlib import Path

#: The exit status of a queue that ended to be reloaded (EX_TEMPFAIL).
RELOAD_RC = 75
#: Paths under these are code. Everything else (puzzles/, docs) is data.
CODE_PREFIXES = ("tools/",)


def code_path(path):
    """Whether a changed file `path` (repo-relative) can change a running
    queue: anything under tools/ but the tests and the prose."""
    if not path.startswith(CODE_PREFIXES):
        return False
    name = path.rsplit("/", 1)[-1]
    return not (name.startswith("test_") or name.endswith((".md", ".txt")))


def code_changed(paths):
    """The code files among `paths` (the names a diff lists), sorted."""
    return sorted(p for p in paths if code_path(p))


def enabled(env=None):
    """Whether the queue reloads itself when master's code moves (CT_AUTO_RELOAD=0 opts out)."""
    return (os.environ if env is None else env).get("CT_AUTO_RELOAD", "1").strip().lower() not in ("0", "no", "off", "false", "")


def poll_seconds(env=None):
    try:
        return max(10.0, float((os.environ if env is None else env).get("CT_RELOAD_POLL", "180")))
    except ValueError:
        return 180.0


def grace_seconds(env=None):
    try:
        return max(0.0, float((os.environ if env is None else env).get("CT_RELOAD_GRACE", "1200")))
    except ValueError:
        return 1200.0


def git(repo, *args, timeout=60):
    """stdout of `git -C repo args`, or None when it fails or times out."""
    try:
        done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


class Watcher:
    """Notices that origin/master's code differs from the tree this process
    loaded. `base` is the commit the process started on (the tree's HEAD
    then); a later move of the tree does not matter, only the code the
    process runs does, so the comparison stays against `base`."""

    def __init__(self, repo, base=None, remote="origin", branch="master", fetch=True):
        self.repo = Path(repo)
        self.remote, self.branch, self.fetch = remote, branch, fetch
        out = base or git(self.repo, "rev-parse", "HEAD")
        self.base = out.strip() if out else None
        self.hit = None  # the code files that differ, once seen
        self._stop = threading.Event()

    def check(self):
        """Fetch (when asked) and compare once: the changed code files, [] when
        none, None when the repo cannot be read (a failed fetch compares what is there)."""
        if not self.base:
            return None
        if self.fetch:
            git(self.repo, "fetch", "-q", self.remote, self.branch, timeout=45)
        out = git(self.repo, "diff", "--name-only", self.base, f"{self.remote}/{self.branch}", "--", *CODE_PREFIXES)
        if out is None:
            return None
        files = code_changed(out.split("\n"))
        if files:
            self.hit = files
        return files

    def start(self, interval=None):
        """Check every `interval` seconds on a daemon thread until a change is seen."""
        interval = poll_seconds() if interval is None else interval

        def loop():
            while not self._stop.wait(interval):
                if self.check():
                    return

        threading.Thread(target=loop, daemon=True, name="hot-reload").start()
        return self

    def stop(self):
        self._stop.set()


def summary(files, limit=4):
    """Short text for a log line: the first few files and the count."""
    return ", ".join(files[:limit]) + (f" and {len(files) - limit} more" if len(files) > limit else "")
