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
import fetch_fifteensquared as f, media_manifest

def store(post):  # as fetch_posts does: the file, then its manifest row
    f.store(f.POSTS, post["id"], post)
    media_manifest.record_post(f.POSTS, post)

f.POSTS.mkdir(parents=True)
opened = []
real_read = pathlib.Path.read_text
def spy(self, *a, **k):
    opened.append(self.name)
    return real_read(self, *a, **k)
pathlib.Path.read_text = spy
for i, cats in ((1, [6]), (2, [4]), (3, [6, 4])):
    store({"id": i, "categories": cats})
print("FIRST", [p.name for p in f.category_post_files(6)], opened)

# A post stored later joins off its manifest row; still no post is opened.
opened.clear()
store({"id": 5, "categories": [6]})
print("TOPPED", [p.name for p in f.category_post_files(6)], sorted(opened))

PY
)
field() { printf '%s\n' "$out" | sed -n "s/^$1 //p"; }
check "a category's posts read off the manifest, opening no post" \
  "['1.json', '3.json'] ['posts-fifteensquared.jsonl']" "$(field FIRST)"
check "a post stored later joins off its manifest row" \
  "['1.json', '3.json', '5.json'] ['posts-fifteensquared.jsonl']" "$(field TOPPED)"

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
