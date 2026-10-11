#!/bin/bash
# Do the fifteensquared readers find a category's posts off the index, without
# opening every cached post, and does tools/ft_puzzles.py's budget count its
# parse?
#
#     bash tools/test_fifteensquared_index.sh
#
# Opening every post over the container's virtiofs mount took ~15 minutes per
# pass, twice per FT run, and ran the ft unit past its limit. Everything here is
# a temp cache; nothing touches the network or the corpus.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
fails=0
check() {  # check <what> <expected> <got>
  if [ "$2" = "$3" ]; then echo "ok   $1"; else
    echo "FAIL $1: expected [$2], got [$3]"; fails=$((fails + 1)); fi
}

out=$(CT_DOWNLOADS="$TMP" PYTHONPATH="$REPO/tools" python3 - <<'PY'
import builtins, json, pathlib
import fetch_fifteensquared as f

f.POSTS.mkdir(parents=True)
for i, cats in ((1, [6]), (2, [4]), (3, [6, 4])):
    (f.POSTS / f"{i}.json").write_text(json.dumps({"id": i, "categories": cats}))
print("FIRST", [p.name for p in f.category_post_files(6)])

# Built once, the index is all a second read opens.
opened = []
real_read = pathlib.Path.read_text
def spy(self, *a, **k):
    opened.append(self.name)
    return real_read(self, *a, **k)
pathlib.Path.read_text = spy
f.category_post_files(6)
print("OPENED", opened)

# A post a killed run stored without rewriting the index joins it; a post
# gone from the cache leaves it.
opened.clear()
(f.POSTS / "5.json").write_text(json.dumps({"id": 5, "categories": [6]}))
(f.POSTS / "1.json").unlink()
print("TOPPED", [p.name for p in f.category_post_files(6)], sorted(opened))

PY
)
field() { printf '%s\n' "$out" | sed -n "s/^$1 //p"; }
check "a category's posts read off the posts once" "['1.json', '3.json']" "$(field FIRST)"
check "a second read opens only the index" "['post_categories.json']" "$(field OPENED)"
check "a post stored outside the index joins it, a deleted one leaves" \
  "['3.json', '5.json'] ['5.json', 'post_categories.json']" "$(field TOPPED)"

budget=$(CT_DOWNLOADS="$TMP" PYTHONPATH="$REPO/tools" python3 - <<'PY'
import time
import ft_puzzles as F
F.parse = lambda: (time.sleep(1.2), ([], []))[1]
seen = []
F.grids = lambda limit, nodes, budget: seen.append(budget)
F.file = lambda write, limit: ([], __import__("collections").Counter())
F.main(["--budget-seconds", "10", "--dry-run"])
print("BUDGET", round(seen[0]))
PY
)
check "ft_puzzles spends its parse out of --budget-seconds" "BUDGET 9" "$(printf '%s\n' "$budget" | grep BUDGET)"

[ "$fails" -eq 0 ] && echo "all ok" || { echo "$fails failure(s)"; exit 1; }
