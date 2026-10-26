#!/usr/bin/env python3
# Does tools/gale_idle.py let a cryptic-gale-inbox tick skip its worktree
# setup only when the tick would do nothing: the progress page rendered
# within the hour and no download since (or one, but the page under
# RENDER_MIN old), and no fresh edition waiting with no full pass running;
# and does it force a full tick MAX_SKIP after the last? Does
# tools/vlm_health.py --quick skip only an up VLM that was not down?
#
#     python3 tests/test_gale_idle.py
#
# Files in a temp dir; no network, no git.
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools"))
import os
import sys
import atexit
import shutil
import tempfile
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["PYTHONPATH"] = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
tmp = tempfile.mkdtemp()
atexit.register(shutil.rmtree, tmp, True)
sys.argv[1:] = [tmp]

import json, os, sys, types
from pathlib import Path
import gale_idle as g

tmp = Path(sys.argv[1])
fails = 0
def check(what, want, got):
    global fails
    print(("ok   " if want == got else "FAIL ") + what + ("" if want == got else f": expected {want!r}, got {got!r}"))
    fails += want != got

for name in ("CHECKLIST", "FETCHED", "EDITIONS", "RUNNING", "STATE", "FULL"):
    setattr(g, name, tmp / name)
now = 1_000_000_000.0
def at(p, ago):
    p.write_text("{}")
    os.utime(p, (now - ago, now - ago))

at(g.FULL, 60)
check("no manifest: sync skips anyway", None, g.why_run(now))
at(g.EDITIONS, 2 * g.FRESH)
check("no page yet: render", "progress page due", g.why_run(now))
at(g.CHECKLIST, g.RENDER_EVERY + 1)
check("page over an hour old: render", "progress page due", g.why_run(now))
at(g.CHECKLIST, 120)
check("page fresh, nothing new: skip", None, g.why_run(now))
at(g.FETCHED, 30)
check("download since, page under RENDER_MIN old: skip", None, g.why_run(now))
at(g.CHECKLIST, g.RENDER_MIN + 10)
check("download since, page over RENDER_MIN old: render", "gale_fetch logged a download", g.why_run(now))
at(g.FETCHED, g.RENDER_MIN + 60)
at(g.EDITIONS, 60)
check("fresh edition, no pass running: run (kick)",
      "a fresh edition may wait with no pass running", g.why_run(now))
g.RUNNING.write_text(json.dumps({"pid": os.getpid(),
                                 "start": Path(f"/proc/{os.getpid()}/stat").read_text().rsplit(")", 1)[1].split()[19]}))
check("fresh edition, pass running: skip", None, g.why_run(now))
g.RUNNING.write_text(json.dumps({"pid": os.getpid(), "start": "1"}))
check("running.json of a dead pass: run", "a fresh edition may wait with no pass running", g.why_run(now))
g.STATE.write_text(json.dumps({"held": True}))
check("fresh edition, pass held: skip (kick would not start it)", None, g.why_run(now))
at(g.FULL, g.MAX_SKIP)
check("no full tick in MAX_SKIP: run", "no full tick in MAX_SKIP", g.why_run(now))
g.FULL.unlink()
check("never a full tick: run", "no full tick in MAX_SKIP", g.why_run(now))

# vlm_health.py --quick, its imports stubbed (watchlib is household's).
seen = []
sys.modules["watchlib"] = types.SimpleNamespace(Watcher=lambda name: types.SimpleNamespace(seen=list(seen)))
import vlm_health as v
v.serving = lambda: True
check("vlm up, was up: skip", 0, v.quick())
seen[:] = ["vlm-health\t" + json.dumps({"down_since": 5})]
check("vlm up, was down: full tick (says it is back)", 1, v.quick())
seen[:] = []
v.serving = lambda: False
check("vlm down: full tick", 1, v.quick())
sys.exit(1 if fails else 0)
