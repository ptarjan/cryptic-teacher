#!/bin/bash
# tools/reconstruct_grid.py's command line: several --lights run as separate
# searches (on the desktop under OCR_REMOTE; here, with it unset, in-process),
# and --words reaches the search.
#
#     bash tools/test_reconstruct_grid_cli.sh
cd "$(dirname "$0")/.." || exit 1
unset OCR_REMOTE
d=$(mktemp -d); trap 'rm -rf "$d"' EXIT
echo '[[1,"across",3],[4,"across",3],[5,"across",3],[1,"down",3],[2,"down",3],[3,"down",3]]' >"$d/open.json"
echo '{"across":[3,3,3],"down":[3,3,3]}' >"$d/dict.json"
echo '[null,null,null,null,null,null]' >"$d/words.json"
fails=0
check() { if grep -q "$2" <<<"$3"; then echo "ok   $1"; else echo "FAIL $1"; fails=$((fails+1)); fi; }
one=$(python3 tools/reconstruct_grid.py --lights "$d/open.json" --cols 3 --rows 3 2>&1)
check "one spec: a single grid, no header" "3x3: 1 grid(s)" "$one"
two=$(python3 tools/reconstruct_grid.py --lights "$d/open.json" --lights "$d/dict.json" \
  --words "$d/words.json" --cols 3 --rows 3 2>&1)
check "two specs: each searched and headed" "== lights 2 of 2 ==" "$two"
check "two specs: the first is answered" "== lights 1 of 2 ==" "$two"
[ "$(grep -c '^3x3: 1 grid' <<<"$two")" = 2 ] && echo "ok   both specs find the grid" \
  || { echo "FAIL both specs find the grid"; fails=$((fails+1)); }
[ "$fails" = 0 ] && echo "reconstruct_grid_cli: all checks passed" || echo "reconstruct_grid_cli: $fails FAILED"
exit $((fails > 0))
