#!/bin/bash
# Does the deploy check actually look at the deploy before it calls one failed?
#
# tools/wait_for_deploy.py is the last step of the nightly push, and its failure
# wakes this channel with "GitHub Pages has not published the new build". An
# alert that fires without having fetched anything is worse than no alert: it
# reports on the site while describing the working tree.
#
#     bash tools/test_wait_for_deploy.sh
#
# Three things: the stamps it expects are the stamps the stamper writes, it can
# still name them when index.html carries none, and a verdict is only ever
# reached after the live page has been read.
set -uo pipefail
cd "$(dirname "$0")/.."
fails=0
sand=$(mktemp -d)
trap 'rm -rf "$sand"' EXIT
check() { if [ "$2" = "$3" ]; then echo "  ok: $1"; else
  echo "  FAIL: $1"$'\n'"    expected: $3"$'\n'"    got:      $2"; fails=$((fails + 1)); fi; }

echo "the hashes it waits for are the hashes the stamper writes"
# Through stamp_assets' own asset_url() and back out through the watcher's
# regex, so a change to either the digest or the ?v= form breaks this and not
# a silent agreement between two copies of md5[:8].
out=$(python3 - <<'EOF'
import sys
sys.path.insert(0, "tools")
import stamp_assets, wait_for_deploy
written = wait_for_deploy.stamps(
    " ".join(stamp_assets.asset_url(rel) for rel in wait_for_deploy.ASSETS))
print("agree" if written == wait_for_deploy.want_stamps() else
      f"differ: stamper {written} watcher {wait_for_deploy.want_stamps()}")
EOF
) || out="raised: $out"
check "stamp_assets and wait_for_deploy name the same hash for every asset" "$out" agree

echo "and an unstamped index.html does not hide them"
# daily_update.sh strips the stamps before committing and runs this script
# immediately afterwards, so the real working tree it runs against looks like
# this. Reading the expected hashes out of index.html made that deliberate
# state indistinguishable from a site that never deployed, and this script
# failed on its own precondition without ever looking at the site. Run against
# a scratch copy of index.html and stamp_assets.py rather than the real
# tracked file: stamp_assets.INDEX_HTML is resolved from the script's own
# __file__, so copying the script alongside the copy is what points --unstamp
# at the copy instead of the real one, and a crash here can never leave the
# working tree dirty the way a backup-and-restore of the real file would.
scratch="$sand/scratch"
mkdir -p "$scratch/tools"
cp index.html "$scratch/index.html"
cp tools/stamp_assets.py "$scratch/tools/stamp_assets.py"
python3 "$scratch/tools/stamp_assets.py" --unstamp >/dev/null
out=$(SCRATCH_INDEX="$scratch/index.html" python3 - <<'EOF'
import os, pathlib, sys
sys.path.insert(0, "tools")
import wait_for_deploy
page = pathlib.Path(os.environ["SCRATCH_INDEX"]).read_text()
print("unstamped" if not wait_for_deploy.stamps(page) else "still stamped",
      len(wait_for_deploy.want_stamps()))
EOF
) || out="raised: $out"
check "the expected stamps come from the assets, not from the page" "$out" "unstamped 3"

echo "no verdict is reached without reading the live page"
out=$(python3 - <<'EOF'
import io, sys
from contextlib import redirect_stderr, redirect_stdout
sys.path.insert(0, "tools")
import wait_for_deploy as w

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
EOF
) || out="raised: $out"
check "a matching page and commit is live" \
  "$(printf '%s' "$out" | grep -c '^live 0 fetched 1$')" 1
check "a stale stamp fails, after looking, and says which asset and what it got" \
  "$(printf '%s' "$out" | grep -c '^stale 1 fetched 1 names True$')" 1

echo "a build that has not finished is not a site that never came back"
# The github-pages environment deploys one commit at a time, so a push that
# lands behind another waits in the queue for minutes before its own build
# starts. On 2026-09-21 the nightly ran out of its five minutes while its build
# was still queued and alerted that the site had not published — it published
# four minutes later. The clock running out is only a failure if nothing is
# coming, so the verdict now asks.
out=$(python3 - <<'EOF'
import io, sys
from contextlib import redirect_stderr, redirect_stdout
sys.path.insert(0, "tools")
import wait_for_deploy as w

head = "0" * 40
want = w.want_stamps()
stale = " ".join(f'"{k}?v=deadbeef"' for k in want)
w.fetch = lambda: stale
w.built_commit = lambda: "f" * 40
w.shipped_index_stamp = lambda sha: w.want_stamps()["puzzles/index.js"]
w.subprocess.run = lambda *a, **k: type("R", (), {"stdout": head, "returncode": 0})()
w.time.sleep = lambda _s: None

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
EOF
) || out="raised: $out"
check "it waits out a queued build and then reports what the build actually did" \
  "$(printf '%s' "$out" | grep -c '^queued 1 asked 3 says True$')" 1
check "it gives up at --max-wait and names the state it gave up on" \
  "$(printf '%s' "$out" | grep -c '^ceiling 1 asked 1 says True$')" 1
check "and with no build for the commit at all it fails on the first look" \
  "$(printf '%s' "$out" | grep -c '^norun 1 asked 1$')" 1

[ "$fails" = 0 ] && echo "wait for deploy: all checks passed" || echo "wait for deploy: $fails FAILED"
exit $((fails > 0))
