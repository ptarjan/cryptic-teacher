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
# failed on its own precondition without ever looking at the site. Done to the
# real index.html because that is the file the real run reads; the stored form
# is unstamped anyway, so the restore is exact.
cp index.html "$sand/index.html"
trap 'cp "$sand/index.html" index.html; rm -rf "$sand"' EXIT
python3 tools/stamp_assets.py --unstamp >/dev/null
out=$(python3 - <<'EOF'
import pathlib, sys
sys.path.insert(0, "tools")
import wait_for_deploy
page = pathlib.Path("index.html").read_text()
print("unstamped" if not wait_for_deploy.stamps(page) else "still stamped",
      len(wait_for_deploy.want_stamps()))
EOF
) || out="raised: $out"
cp "$sand/index.html" index.html
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

[ "$fails" = 0 ] && echo "wait for deploy: all checks passed" || echo "wait for deploy: $fails FAILED"
exit $((fails > 0))
