#!/usr/bin/env python3
# Does the deploy check actually look at the deploy before it calls one failed?
#
# tools/wait_for_deploy.py is what a session runs after a push before saying
# "reload". A verdict reached without fetching anything is worse than none: it
# reports on the site while describing the working tree.
#
#     python3 tests/test_wait_for_deploy.py
#
# Three things: the stamps it expects are the stamps the stamper writes, it can
# still name them when index.html carries none, and a verdict is only ever
# reached after the live page has been read.
import io
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.chdir(REPO)
sys.path.insert(0, "tools")
import stamp_assets
import wait_for_deploy as w

fails = 0
sand = Path(tempfile.mkdtemp())


def check(what, got, expected):
    global fails
    if got == expected:
        print(f"  ok: {what}")
    else:
        print(f"  FAIL: {what}\n    expected: {expected}\n    got:      {got}")
        fails += 1


def section(fn):
    """The section's printed lines, or 'raised: ...' if it blew up."""
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            fn()
    except Exception:
        traceback.print_exc()
        return "raised: " + buf.getvalue().strip()
    return buf.getvalue().strip()


def count(out, line):
    return out.splitlines().count(line)


try:
    print("the hashes it waits for are the hashes the stamper writes")

    # Through stamp_assets' own asset_url() and back out through the watcher's
    # regex, so a change to either the digest or the ?v= form breaks this and not
    # a silent agreement between two copies of md5[:8].
    def agree():
        written = w.stamps(" ".join(stamp_assets.asset_url(rel) for rel in w.ASSETS))
        print("agree" if written == w.want_stamps() else
              f"differ: stamper {written} watcher {w.want_stamps()}")
    check("stamp_assets and wait_for_deploy name the same hash for every asset", section(agree), "agree")

    print("and an unstamped index.html does not hide them")
    # Every committed index.html is unstamped (the deploy workflow stamps its own
    # checkout), so the real working tree looks like this, and the expected hashes
    # must come from the assets, not from index.html. Run against a scratch copy of
    # index.html and stamp_assets.py rather than the real tracked file:
    # stamp_assets.INDEX_HTML is resolved from the script's own __file__, so
    # copying the script alongside the copy is what points --unstamp at the copy,
    # and a crash here can never leave the working tree dirty.
    scratch = sand / "scratch"
    (scratch / "tools").mkdir(parents=True)
    shutil.copy("index.html", scratch / "index.html")
    shutil.copy("tools/stamp_assets.py", scratch / "tools" / "stamp_assets.py")
    subprocess.run([sys.executable, str(scratch / "tools" / "stamp_assets.py"), "--unstamp"],
                   stdout=subprocess.DEVNULL)

    def unstamped():
        page = (scratch / "index.html").read_text()
        print("unstamped" if not w.stamps(page) else "still stamped", len(w.want_stamps()))
    check("the expected stamps come from the assets, not from the page", section(unstamped), "unstamped 3")

    print("no verdict is reached without reading the live page")

    def live():
        head = "0" * 40
        want = w.want_stamps()
        live_page = " ".join(f'"{k}?v={v}"' for k, v in want.items())
        w.built_commit = lambda: head
        w.shipped_index_stamp = lambda sha: want["puzzles/index.js"]
        w.subprocess.run = lambda *a, **k: type("R", (), {"stdout": head, "returncode": 0})()

        looked = []

        def run(page):
            looked.clear()

            def fetch():
                looked.append(page)
                return page
            w.fetch = fetch
            err, out = io.StringIO(), io.StringIO()
            sys.argv = ["wait_for_deploy.py", "--check"]
            with redirect_stderr(err), redirect_stdout(out):
                code = w.main()
            return code, (err.getvalue() + out.getvalue()).strip(), len(looked)

        code, _, n = run(live_page)
        print(f"live {code} fetched {n}")
        code, note, n = run(live_page.replace("style.css?v=" + want["style.css"],
                                              "style.css?v=deadbeef"))
        print(f"stale {code} fetched {n} names {'style.css' in note and 'deadbeef' in note}")
    real_run = subprocess.run
    try:
        out = section(live)
    finally:
        subprocess.run = real_run
    check("a matching page and commit is live", count(out, "live 0 fetched 1"), 1)
    check("a stale stamp fails, after looking, and says which asset and what it got",
          count(out, "stale 1 fetched 1 names True"), 1)

    print("a build that has not finished is not a site that never came back")

    # The github-pages environment deploys one commit at a time, so a push that
    # lands behind another waits in the queue for minutes before its own build
    # starts. The clock running out is only a failure if nothing is coming, so the
    # verdict asks what the build is doing.
    def queued():
        head = "0" * 40
        want = w.want_stamps()
        stale = " ".join(f'"{k}?v=deadbeef"' for k in want)
        w.fetch = lambda: stale
        w.built_commit = lambda: "f" * 40
        w.shipped_index_stamp = lambda sha: w.want_stamps()["puzzles/index.js"]
        w.subprocess.run = lambda *a, **k: type("R", (), {"stdout": head, "returncode": 0})()
        w.time.sleep = lambda _s: None
        w.contains = lambda built, sha: built == sha

        asked = []

        def run(states, max_wait):
            asked.clear()

            def deploy_status(sha):
                asked.append(sha)
                return states[min(len(asked) - 1, len(states) - 1)]
            w.deploy_status = deploy_status
            err, out = io.StringIO(), io.StringIO()
            sys.argv = ["wait_for_deploy.py", "--timeout", "0", "--max-wait", str(max_wait)]
            with redirect_stderr(err), redirect_stdout(out):
                code = w.main()
            return code, (err.getvalue() + out.getvalue()).strip()

        code, note = run(["in_progress", "in_progress", "failure"], 60)
        print(f"queued {code} asked {len(asked)} says {'failure' in note}")
        code, note = run(["in_progress"], 0)
        print(f"ceiling {code} asked {len(asked)} says {'in_progress' in note}")
        code, note = run([""], 60)
        print(f"norun {code} asked {len(asked)}")
        code, note = run(["pending", "success"], 60)
        print(f"pending {code} asked {len(asked)}")
        # A later push's build carries this commit: that is this commit published.
        w.contains = lambda built, sha: True
        code, note = run(["cancelled"], 60)
        print(f"superseded {code} asked {len(asked)}")
    real_sleep = w.time.sleep
    try:
        out = section(queued)
    finally:
        subprocess.run = real_run
        w.time.sleep = real_sleep
    check("it waits out a queued build and then reports what the build actually did",
          count(out, "queued 1 asked 3 says True"), 1)
    check("it gives up at --max-wait and names the state it gave up on",
          count(out, "ceiling 1 asked 1 says True"), 1)
    check("and with no build for the commit at all it fails on the first look",
          count(out, "norun 1 asked 1"), 1)
    check("a pending build is waited on like a queued one", count(out, "pending 1 asked 2"), 1)
    check("a later build that contains the commit is the commit live",
          count(out, "superseded 0 asked 0"), 1)
finally:
    shutil.rmtree(sand, ignore_errors=True)

print("wait for deploy: all checks passed" if not fails else f"wait for deploy: {fails} FAILED")
sys.exit(1 if fails else 0)
