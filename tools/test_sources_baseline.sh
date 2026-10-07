#!/bin/bash
# A refile that rewords a clue is the source's change, not the annotator's.
#
# The nightly refiles blog-built Telegraph puzzles from the paper's own copy,
# which can reword a clue and drop the annotation written for the old words.
# The validator holds every annotated clue to HEAD's words
# (check_clue_unchanged), so daily_update.sh commits what the phases before
# annotation wrote (commit_sources): HEAD is then the clue the annotator was
# handed, and an uncommitted refile cannot make its annotation a rewrite.
#
# The commit_sources block is READ OUT of daily_update.sh and run in a scratch
# repo; nothing in the checkout is written.
#
#     bash tools/test_sources_baseline.sh
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
REPO="$PWD"
fails=0
check() { if [ "$2" = "$3" ]; then echo "  ok: $1"; else
  echo "  FAIL: $1"$'\n'"    expected: $3"$'\n'"    got:      $2"; fails=$((fails + 1)); fi; }

block=$(awk '/^commit_sources\(\) \{$/,/^}$/' tools/daily_update.sh)
[ -n "$block" ] || { echo "FAIL: commit_sources is no longer where this test reads it from"; exit 1; }

sand=$(mktemp -d)
trap 'rm -rf "$sand" "$sand.out"' EXIT
mkdir -p "$sand/puzzles/telegraph/2026"
ln -s "$REPO/tools" "$sand/tools"
P="puzzles/telegraph/2026/telegraph-1.json"
clue() {  # clue <text> [annotated] — write the one-entry puzzle
  python3 - "$sand/$P" "$1" "${2:-}" <<'EOF'
import json, sys
path, text, ann = sys.argv[1:]
e = {"number": 10, "direction": "across", "position": {"x": 0, "y": 0}, "length": 5,
     "clue": {"text": text, "enumeration": "5"}, "solution": "SHELL"}
if ann:
    e["annotation"] = {"type": ["container"], "answer": "SHELL"}
json.dump({"id": "telegraph-1", "source": {"retrievedFrom": "publisher"}, "entries": [e]},
          open(path, "w"))
EOF
}
validate() {  # -> the clue-changed errors check_clue_unchanged reports, or "clean"
  python3 - "$sand" "$sand/$P" <<'EOF'
import json, sys
from pathlib import Path
sys.path.insert(0, "tools")
import validate_annotations as V
V.ROOT = Path(sys.argv[1])
errs = []
V.check_clue_unchanged(json.load(open(sys.argv[2])), Path(sys.argv[2]), errs)
print(len(errs) if errs else "clean")
EOF
}
git() { command git -C "$sand" "$@"; }
git init -q && git config user.email t@t && git config user.name t
echo tools >> "$sand/.git/info/exclude"
clue "Hawk protected hard covering of an egg" yes
git add -A && git commit -qm blog
echo stray > "$sand/notes.txt"

echo "an uncommitted refile makes the fresh annotation a rewrite"
clue "Hawk protects hard covering of an egg"     # the refile drops the annotation
clue "Hawk protects hard covering of an egg" yes # tonight's annotation of it
check "without commit_sources it fails" "$(validate)" "1"

echo "commit_sources makes the refile HEAD before anything annotates"
clue "Hawk protects hard covering of an egg"
eval "$block"
( cd "$sand" && sources_committed="" && commit_sources && echo "$sources_committed" ) > "$sand.out"
check "it committed" "$(cat "$sand.out")" "1"
check "only the puzzles" "$(git status --porcelain)" "?? notes.txt"
clue "Hawk protects hard covering of an egg" yes
check "the annotation of the refiled clue validates" "$(validate)" "clean"

echo "a rewrite after the commit is still the annotator's"
clue "Hawk shields hard covering of an egg" yes
check "and fails" "$(validate)" "1"

echo "a rejected annotation reverts to the refile, which stands"
git checkout -q -- "$P"
check "the source's clue" "$(python3 -c "import json; print(json.load(open('$sand/$P'))['entries'][0]['clue']['text'])")" \
  "Hawk protects hard covering of an egg"

echo "with nothing fetched it commits nothing"
( cd "$sand" && sources_committed="" && commit_sources && echo "${sources_committed:-none}" ) > "$sand.out"
check "no commit" "$(cat "$sand.out") $(git rev-list --count HEAD)" "none 2"

[ "$fails" = 0 ] && echo "SOURCES BASELINE PASSED" || echo "$fails check(s) failed"
exit $((fails > 0))
