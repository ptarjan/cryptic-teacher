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
    code_changed() calls code that are also in the queue's closure (queue_code). A puzzle-only push (durable.sh pushes puzzles
    every 300s) never triggers it. CT_AUTO_RELOAD=0 turns this trigger off.

CT_RELOAD_GRACE (1200s) caps how long a queue that cannot hand its units over
(no --handoff) waits for them before it stops them the way a game does (TERM,
left deferred, never a failure).
"""
import ast
import os
import re
import subprocess
import threading
from pathlib import Path

#: The exit status of a queue that ended to be reloaded (EX_TEMPFAIL).
RELOAD_RC = 75
#: Paths under these are code. Everything else (puzzles/, docs) is data.
CODE_PREFIXES = ("tools/",)


def code_path(path):
    """Whether a changed file `path` (repo-relative) can change a running
    queue: a tools/ script (.py, .sh, .js), not a test and not data (tools/data/,
    the .json files such as annotation_backlog.json, which change dozens of
    times an hour and are read fresh by every unit)."""
    if not path.startswith(CODE_PREFIXES) or path.startswith("tools/data/"):
        return False
    name = path.rsplit("/", 1)[-1]
    return name.endswith((".py", ".sh", ".js")) and not name.startswith("test_")


def code_changed(paths):
    """The code files among `paths` (the names a diff lists), sorted."""
    return sorted(p for p in paths if code_path(p))


_SCRIPT = re.compile(r"(?:[\w.-]*/)?(\w+\.(?:py|sh|js))")


def _docstrings(tree):
    ids = set()
    for n in ast.walk(tree):
        body = getattr(n, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            ids.add(id(body[0].value))
    return ids


def _needs(tools, name, names):
    """The tools/ files (of `names`) that file `name` loads or launches: a .py
    module's module-level imports (not a function's lazy ones), a file name in
    a string of its code (not its docstrings: a script it starts) or a module
    name in a module-level constant (importlib's FETCH_UNITS); in a .sh the shell scripts it runs or sources (comments dropped; the python a
    wrapper starts is not followed: queue_code's root is the queue); a .js has none."""
    try:
        text = (tools / name).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    out = set()
    if name.endswith(".py"):
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return set()
        skip = _docstrings(tree)
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                for x in ast.walk(node):
                    if isinstance(x, ast.Import):
                        out |= {a.name.split(".")[0] + ".py" for a in x.names}
                    elif isinstance(x, ast.ImportFrom) and x.module and not x.level:
                        out.add(x.module.split(".")[0] + ".py")
            if isinstance(node, ast.Assign):
                out |= {x.value + ".py" for x in ast.walk(node.value) if isinstance(x, ast.Constant) and isinstance(x.value, str)}
        for call in (c for c in ast.walk(tree) if isinstance(c, ast.Call)):
            for x in ast.walk(call):  # a script named as an argument (a command line), not in a message or table
                if isinstance(x, ast.Constant) and isinstance(x.value, str) and id(x) not in skip:
                    m = _SCRIPT.fullmatch(x.value)
                    if m:
                        out.add(m.group(1))
    elif name.endswith(".sh"):
        out |= set(re.findall(r"\b(\w+\.sh)\b", "\n".join(l for l in text.split("\n") if not l.lstrip().startswith("#"))))
    return out & names


def queue_code(tools, root="edition_queue.py"):
    """The tools/ files (repo-relative paths) a queue running `root` can run:
    root, the shell wrappers that start it, and what each loads or launches,
    transitively (_needs). A change to any other tools/ file (a fetcher the
    queue never starts, the site builders, tests) cannot change the queue."""
    tools = Path(tools)
    names = {p.name for p in tools.iterdir() if p.suffix in (".py", ".sh", ".js") and not p.name.startswith("test_")}
    todo = [root] + sorted(n for n in names if n.endswith(".sh") and root in (tools / n).read_text(errors="replace"))
    seen, leaves, wrappers = set(), set(), set(todo[1:])
    while todo:
        n = todo.pop()
        if n not in seen and n in names:
            seen.add(n)
            if n.endswith(".sh"):  # a wrapper's own scripts and helpers are leaves
                leaves |= {d for d in _needs(tools, n, names) if d.endswith(".sh")} if n in wrappers else set()
            else:
                todo += sorted(_needs(tools, n, names))
    return {f"tools/{n}" for n in seen | leaves}


def relevant(changed, closure):
    """(the `changed` code files in `closure`, those outside it)."""
    inside = [p for p in changed if p in closure]
    return inside, [p for p in changed if p not in closure]


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

    def __init__(self, repo, base=None, remote="origin", branch="master", fetch=True, closure=None):
        self.repo = Path(repo)
        self.closure = closure  # the files (repo-relative) that count, None for every code file
        self.ignored = []  # changed code files outside it, last seen
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
        if self.closure is not None:
            files, outside = relevant(files, self.closure)
            if outside and sorted(outside) != self.ignored:
                print(f"reload: ignoring {len(outside)} changed files outside the queue's code ({summary(sorted(outside))})", flush=True)
            self.ignored = sorted(outside)
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


if __name__ == "__main__":
    # `hot_reload.py check [repo]`, for the shell loops (tools/prereset_backfill.sh):
    # exit 0 and name the files when origin/master's code differs from the tree's
    # HEAD, 1 when it does not, the repo cannot be read or CT_AUTO_RELOAD=0.
    import sys

    changed = Watcher(sys.argv[2] if len(sys.argv) > 2 else ".").check() if sys.argv[1:2] == ["check"] and enabled() else None
    if changed:
        print(summary(changed))
    sys.exit(0 if changed else 1)
