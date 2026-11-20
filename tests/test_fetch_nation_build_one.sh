#!/bin/bash
# Does one bad page fail on its own in fetch_nation's worker pool?
#
#     bash tests/test_fetch_nation_build_one.sh
#
# _build_one caught only Exception around build(): a SystemExit raised inside
# build (a tool refusing) ended the pool worker, its task was lost, and
# file_all's imap_unordered waited for it forever, so a full run hung
# (2026-10-14). meta() sat outside the try as well. Synthetic pages and a
# stubbed build only: no held page is read, nothing is written in the repo.
set -uo pipefail
cd "$(dirname "$0")/.."
tools="$PWD/tools"
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
out=$(cd "$tmp" && PYTHONPATH="$tools" timeout 60 python3 - <<'PY'
import multiprocessing, pathlib
import fetch_nation as F
def build(page, url, known):
    if "EXIT" in page: raise SystemExit("refused")
    if "BOOM" in page: raise ValueError("bad")
    return {"id": "ok"}, None
F.build = build
F._build_one.urls, F._build_one.known = {}, {}
paths = []
for name, body in [("a", "EXIT"), ("b", "BOOM"), ("c", "fine")]:
    p = pathlib.Path(name + ".html"); p.write_text(f"<title>Puzzle No. 1</title>{body}")
    paths.append(p)
with multiprocessing.get_context("fork").Pool(2) as pool:
    got = sorted(pool.imap_unordered(F._build_one, paths, chunksize=1),
                 key=lambda r: str(r[2]))
for number, puzzle, reason, held in got:
    print("ROW", puzzle and puzzle["id"], reason)
PY
)
rc=$?
fails=0
expect() { grep -qxF "$1" <<<"$out" && echo "  ok: $2" || { echo "  FAIL: $2 (want '$1')"; echo "$out"; fails=$((fails+1)); }; }
[ $rc = 0 ] && echo "  ok: the pool run finished" || { echo "  FAIL: the pool run did not finish (rc $rc, 124 = hung)"; fails=$((fails+1)); }
expect "ROW None SystemExit: refused" "a SystemExit in build is that page's reason, not a dead worker"
expect "ROW None ValueError: bad" "an ordinary error is still that page's reason"
expect "ROW ok None" "the good page still builds"
[ "$fails" = 0 ] && echo "fetch_nation build_one: all checks passed" || echo "fetch_nation build_one: $fails FAILED"
exit $((fails > 0))
