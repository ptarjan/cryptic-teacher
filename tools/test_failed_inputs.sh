#!/bin/bash
# Is a failed puzzle skipped the next night, and back once its inputs change?
#
# The blocks of tools/daily_update.sh that read and write the failure ledger are
# READ OUT of that file by their own first and last lines rather than copied
# here, then driven against a scratch ledger and scratch puzzles. Nothing in
# the checkout is written; the last check says so.
#
#     bash tools/test_failed_inputs.sh
set -uo pipefail
cd "$(dirname "$0")/.."
REPO="$PWD"
fails=0
check() { if [ "$2" = "$3" ]; then echo "  ok: $1"; else
  echo "  FAIL: $1"$'\n'"    expected: $3"$'\n'"    got:      $2"; fails=$((fails + 1)); fi; }
tree_before=$(git status --porcelain)

pick=$(awk '/^annotate_blocked=/,/^)$/' tools/daily_update.sh)
charge=$(awk '/^record_annotate_failure\(\)/,/^}$/' tools/daily_update.sh)
# The settling loop is the `for num in $annotated_nums` that clears the ledger;
# another loop of the same shape comes first, so match on what it does.
settle=$(awk '
  /^for num in \$annotated_nums; do$/ { capturing=1; buf=$0 "\n"; next }
  capturing {
    buf = buf $0 "\n"
    if ($0 ~ /^done$/) {
      if (buf ~ /failed_inputs\.py clear/) { printf "%s", buf; exit }
      capturing=0; buf=""
    }
  }
' tools/daily_update.sh)
for block in pick charge settle; do
  [ -n "${!block}" ] ||
    { echo "FAIL: the $block block is no longer where this test reads it from"; exit 1; }
done

sand=$(mktemp -d)
trap 'rm -rf "$sand"' EXIT
ln -s "$REPO/tools" "$sand/tools"
mkdir -p "$sand/puzzles"
export FAILED_INPUTS_FILE="$sand/ledger.json"
export FAILED_INPUTS_PUZZLES="$sand/puzzles"
ledger() { python3 tools/failed_inputs.py "$@"; }

puzzle() {  # id answer [annotation-type] — one-entry puzzle file
  python3 - "$sand/puzzles/$1.json" "$2" "${3:-}" <<'EOF'
import json, sys
path, answer, ann = sys.argv[1:]
e = {"id": "1-across", "clue": "Test (3)", "solution": answer, "length": 3,
     "position": {"x": 0, "y": 0}, "direction": "across"}
if ann:
    e["annotation"] = {"type": ann}
json.dump({"id": path.rsplit("/", 1)[1][:-5], "dimensions": {"rows": 3, "cols": 3},
           "entries": [e]}, open(path, "w"))
EOF
}
index() {  # each argument is id:date:annotated
  python3 - "$sand/puzzles/index.json" "$@" <<'EOF'
import json, sys
out = []
for arg in sys.argv[2:]:
    pid, when, done = arg.split(":")
    out.append({"id": pid, "date": int(when), "annotated": done == "yes",
                "hasSolutions": True})
json.dump({"puzzles": out}, open(sys.argv[1], "w"))
EOF
}
queue() { ( cd "$sand" && ANNOTATE_MAX=2 eval "$pick" && printf '%s\n' "$pending" ); }
eval "$charge"

puzzle ct-1 CAT; puzzle ct-2 DOG; puzzle ct-3 EMU
index ct-1:300:no ct-2:200:no ct-3:100:no

echo "a puzzle is in the queue until it fails"
check "the two newest" "$(queue)" "ct-1 ct-2"

echo "a validator's rejection is recorded, whatever words the clue error quotes"
record_annotate_failure ct-1 "validation rejected tonight's annotation: ERROR 1-across: 'network' is not a definition" --judged >/dev/null
check "ct-1 is skipped" "$(ledger skipped annotate)" "ct-1"

echo "a transient failure is not recorded, so it retries next night"
record_annotate_failure ct-2 "ct-2 failed: API Error: 529 overloaded" >/dev/null
record_annotate_failure ct-2 "ct-2 failed: Claude AI usage limit reached" >/dev/null
record_annotate_failure ct-2 "five-hour window 92% spent (limit 70%)" >/dev/null
check "only ct-1 is skipped" "$(ledger skipped annotate)" "ct-1"

echo "the next night the failed puzzle is left out and the budget refilled"
check "ct-2 and ct-3 instead" "$(queue)" "ct-2 ct-3"
check "and the log counts it" "$(ledger summary)" \
  "skipped as failed on unchanged inputs: 1 — annotate 1 (ct-1)"

echo "half an annotation left on disk is not a new input"
puzzle ct-1 CAT "charade"
check "still skipped" "$(queue)" "ct-2 ct-3"

echo "a hand-fixed answer is a new input, and the puzzle comes back by itself"
puzzle ct-1 COT
check "back at the head of the queue" "$(queue)" "ct-1 ct-2"
check "and the stale record is dropped" "$(ledger summary)" \
  "skipped as failed on unchanged inputs: 0"
check "from the file too" "$(python3 -c "import json; print(json.load(open('$FAILED_INPUTS_FILE'))['annotate'])")" "{}"

echo "a clean run clears the record; a clean exit that annotated nothing records one"
record_annotate_failure ct-3 "ct-3 ran past 90m without finishing and was stopped" >/dev/null
check "a wall-clock kill is the puzzle's" "$(ledger skipped annotate)" "ct-3"
index ct-1:300:no ct-2:200:no ct-3:100:yes
annotated_nums="ct-2 ct-3"
( cd "$sand" && eval "$settle" ) >/dev/null
check "ct-3 cleared, ct-2 recorded" "$(ledger skipped annotate | tr '\n' ' ')" "ct-2 "

echo "the cold solve uses the same rule"
puzzle ct-4 ""
ledger record solve ct-4 --judged --reason "crossings disagree at 1-across" >/dev/null
check "skipped" "$(ledger skipped solve)" "ct-4"
puzzle ct-4 GNU
check "answers arriving are a new input" "$(ledger skipped solve)" ""

echo "the working tree is untouched"
check "git status unchanged" "$(git status --porcelain)" "$tree_before"

[ "$fails" = 0 ] && echo "failed inputs: all checks passed" || echo "failed inputs: $fails FAILED"
exit $((fails > 0))
