#!/usr/bin/env python3
"""Block until the live site is serving what is in the working tree.

"Fixed and pushed — reload the iPad" is a lie for the minute or two that GitHub
Pages takes to build, and the person who reloads inside that window sees the old
bug and reasonably concludes the fix did not work (Paul, 2026-08-16). Pushing is
not deploying. Nobody should be told to reload until this exits 0.

Two checks, because either one alone passes on a deploy that has not happened.
The commit GitHub Pages last built must be the local HEAD, which covers every
file in the push — a change to markup or to a generated page moves no asset
stamp, and a stamps-only check called such a deploy live the instant it was
pushed. And the live index.html must carry the hashes the local asset files
have right now, which the commit check cannot see: the commit is built, but
the CDN can still be handing out the previous page, and the stamps are what a
reload actually picks up.

    python3 tools/wait_for_deploy.py            # poll until live, or fail
    python3 tools/wait_for_deploy.py --check    # one look, no waiting

Exit 0 live, 1 timed out or mismatched. Run it as the last step of the deploy
pipeline, after the push.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from stamp_assets import digest                      # noqa: E402 - needs ROOT on the path

URL = "https://cryptic.paultarjan.com/"
REPO = "ptarjan/cryptic-teacher"
WORKFLOW = ".github/workflows/pages.yml"
ASSETS = ["app.js", "style.css", "puzzles/index.js"]
STAMP = re.compile(r'(app\.js|style\.css|puzzles/index\.js)\?v=([a-f0-9]+)')


def stamps(text):
    return dict(STAMP.findall(text))


def want_stamps():
    """The hash each asset should carry live, computed from the files themselves
    rather than parsed out of local index.html.

    daily_update.sh unstamps index.html before committing (the deploy workflow
    stamps its own checkout, so what ships is stamped and what is stored is not)
    and runs this script straight afterwards, against that same working tree. An
    unstamped index.html holds no expected hashes at all, so reading it made a
    healthy tree indistinguishable from an undeployed site and failed before
    either GitHub or the live page was ever looked at.

    digest() comes from stamp_assets, which is what writes the live stamps: the
    check and the thing it checks cannot disagree about how a hash is made.
    """
    return {rel: digest(rel) for rel in ASSETS}


def shipped_index_stamp(head):
    """The stamp CI gives puzzles/index.js when it builds `head`.

    The index is gitignored and CI rebuilds it from the commit, so the copy in
    this working tree is whatever the last local --reindex left, and it can
    describe a different set of puzzles than the one pushed. Build it the way
    the deploy workflow does, in a clean checkout of `head`, and hash that.
    """
    tmp = tempfile.mkdtemp(prefix="deploy-index-")
    try:
        subprocess.run(["git", "worktree", "add", "-q", "--detach", tmp, head],
                       cwd=ROOT, check=True, capture_output=True)
        # The same steps, in the same order, as .github/workflows/pages.yml:
        # the reindex restamps index.html, which needs the glossary built.
        for step in (["tools/build_abbreviations.py"],
                     ["tools/fetch_puzzle.py", "--reindex"]):
            run = subprocess.run([sys.executable, *step], cwd=tmp,
                                 capture_output=True, text=True)
            if run.returncode:
                raise RuntimeError(f"{' '.join(step)} failed building the index to "
                                   f"compare: {(run.stderr or run.stdout).strip()[-400:]}")
        return digest(os.path.join(tmp, "puzzles/index.js"))
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", tmp],
                       cwd=ROOT, capture_output=True)


def fetch():
    # Pages sits behind a CDN; without this we can poll a cached copy of the old
    # page for the whole timeout and report a failure that never existed.
    req = urllib.request.Request(URL, headers={
        "Cache-Control": "no-cache", "Pragma": "no-cache",
        "User-Agent": "cryptic-teacher-deploy-check",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "replace")


def _gh(path):
    """gh api <path> parsed, or None if gh cannot answer at all."""
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True,
                         timeout=30, cwd=ROOT)
    return json.loads(out.stdout) if out.returncode == 0 else None


def built_commit():
    """The commit GitHub Pages is currently serving, or None if it cannot say.

    Read off the github-pages deployments, not /pages/builds/latest: that legacy
    endpoint only describes Pages' own builder, so a site deployed by a workflow
    (.github/workflows/pages.yml) leaves it frozen at whatever it built last, and
    a check against it fails every deploy from then on.

    "" means a deployment is in flight — newer than the last successful one, so
    the caller should keep waiting. Unreachable API, no gh, no auth: return None
    and let the stamps decide, so a laptop without gh still gets the old check
    rather than a hard failure.
    """
    try:
        deployments = _gh(f"repos/{REPO}/deployments"
                          "?environment=github-pages&per_page=5")
        if deployments is None:
            return None
        for dep in deployments:
            states = _gh(f"repos/{REPO}/deployments/{dep['id']}/statuses?per_page=10")
            if states is None:
                return None
            if any(st.get("state") == "success" for st in states):
                return dep["sha"]
        return ""
    except Exception:                                 # noqa: BLE001 - "cannot say"
        return None


def contains(built, head):
    """Whether the commit Pages built already includes `head`.

    Every push to master cancels the deploy still waiting behind it
    (pages.yml's concurrency group), so while anything else is pushing, the
    build that carries a commit is often a later one. That later build is
    this commit being published, not this commit going missing.
    """
    if not built or built == head:
        return built == head
    for _ in range(2):
        r = subprocess.run(["git", "merge-base", "--is-ancestor", head, built],
                           cwd=ROOT, capture_output=True)
        if r.returncode in (0, 1):
            return r.returncode == 0
        subprocess.run(["git", "fetch", "-q", "origin", "master"], cwd=ROOT,
                       capture_output=True)
    return False


def deploy_status(sha):
    """How far the Pages workflow has got with `sha`.

    "queued" or "in_progress" is a build that has not finished, which is not
    the same thing as a site that is never going to update: the github-pages
    environment takes one deployment at a time, so a push that lands while
    another holds it sits in the queue for minutes before its own build
    starts. Otherwise the conclusion ("success", "failure", "cancelled"), ""
    when GitHub knows of no run for the commit, and None when it cannot be
    asked at all.
    """
    runs = _gh(f"repos/{REPO}/actions/runs?head_sha={sha}&per_page=20")
    if runs is None:
        return None
    state = ""
    for run in runs.get("workflow_runs", []):
        if run.get("path") == WORKFLOW:
            state = (run.get("status") if run.get("status") != "completed"
                     else run.get("conclusion")) or ""
            break
    if state != "cancelled":
        return state
    # Cancelled because a later push superseded it: that push's build is the
    # one that publishes this commit, so its state is this commit's state.
    later = _gh(f"repos/{REPO}/actions/runs?branch=master&per_page=30")
    for run in (later or {}).get("workflow_runs", []):
        if (run.get("path") == WORKFLOW and run.get("head_sha") != sha
                and contains(run.get("head_sha"), sha)):
            if run.get("status") != "completed":
                return run.get("status") or ""
            if run.get("conclusion") != "cancelled":
                return run.get("conclusion") or ""
    return state


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="one look, do not wait")
    ap.add_argument("--timeout", type=int, default=300)
    # The ceiling on extending that timeout while a build is still coming. It
    # only has to be longer than a queue plus a build, because the wait ends
    # the moment the site answers.
    ap.add_argument("--max-wait", type=int, default=1800)
    args = ap.parse_args()

    want = want_stamps()

    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                          text=True, cwd=ROOT).stdout.strip()
    want["puzzles/index.js"] = shipped_index_stamp(head)
    deadline = time.time() + (0 if args.check else args.timeout)
    ceiling = time.time() + (0 if args.check else args.max_wait)
    while True:
        try:
            built = built_commit()
            live = stamps(fetch())
            diff = {k: (v, live.get(k)) for k, v in want.items() if live.get(k) != v}
            if built and built != head and contains(built, head):
                # A later build carries this commit; its assets are its own.
                print(f"live: commit {head[:8]} is in the deployed {built[:8]}")
                return 0
            if not diff and built in (None, head):
                print("live: " + ", ".join(f"{k}?v={v}" for k, v in sorted(want.items()))
                      + (f", commit {head[:8]}" if built else ", commit unverified"))
                return 0
            note = "; ".join(f"{k} want {w} got {g}" for k, (w, g) in sorted(diff.items()))
            if built not in (None, head):
                note = ((note + "; ") if note else "") + (
                    f"Pages has {built[:8] or 'a build in flight'}, want {head[:8]}")
        except Exception as exc:                      # noqa: BLE001 - any failure is "not live yet"
            note = f"{type(exc).__name__}: {exc}"
        if time.time() >= deadline:
            # Out of clock is not the same as out of hope. Ask what the build
            # is doing before calling it a failure: one that is still queued or
            # running will publish, and the alert this returns says the site
            # never came back, which is a different and alarming claim. Not
            # under --check, which promises one look and no waiting.
            state = "" if args.check else deploy_status(head)
            if state in ("queued", "pending", "waiting", "in_progress") and time.time() < ceiling:
                deadline = min(ceiling, time.time() + args.timeout)
                print(f"still {state} for {head[:8]}, waiting on ({note})", flush=True)
                time.sleep(10)
                continue
            if state:
                note += f"; the Pages build for {head[:8]} is {state}"
            print(f"NOT DEPLOYED: {note}", file=sys.stderr)
            return 1
        print(f"waiting for deploy ({note})", flush=True)
        time.sleep(10)


if __name__ == "__main__":
    sys.exit(main())
