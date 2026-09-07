#!/bin/bash
# Does a puzzle that fails leave the queue, and does a good one stay in it?
#
# The ledger only ever matters on a night that has already gone wrong, which is
# the worst night to discover it was wired up backwards — a ledger that charges
# too eagerly blacklists puzzles nobody ever hears about again, and one that
# charges nothing is not there at all. So the three blocks of
# tools/daily_update.sh that write it are READ OUT of that file by their own
# first and last lines rather than copied here, and driven against a scratch
# ledger and a made-up index.
#
#     bash tools/test_annotate_attempts.sh
#
# The case that matters most is the second one: a run stopped by a usage lockout
# or an expired login must cost the puzzle nothing, because that run never got
# far enough to learn anything about it.
set -uo pipefail
cd "$(dirname "$0")/.."
REPO="$PWD"
fails=0
check() { if [ "$2" = "$3" ]; then echo "  ok: $1"; else
  echo "  FAIL: $1"$'\n'"    expected: $3"$'\n'"    got:      $2"; fails=$((fails + 1)); fi; }

pick=$(awk '/^annotate_blocked=/,/^)$/' tools/daily_update.sh)
charge=$(awk '/^record_annotate_failure\(\)/,/^}$/' tools/daily_update.sh)
settle=$(awk '/^for num in \$annotated_nums; do$/,/^done$/' tools/daily_update.sh)
for block in pick charge settle; do
  [ -n "${!block}" ] ||
    { echo "FAIL: the $block block is no longer where this test reads it from"; exit 1; }
done

# A sandbox with an index of its own, so nothing here depends on which puzzles
# the corpus happens to hold today, and tools/ reached by symlink so the blocks
# run the real annotate_attempts.py.
sand=$(mktemp -d)
trap 'rm -rf "$sand"' EXIT
ln -s "$REPO/tools" "$sand/tools"
mkdir -p "$sand/puzzles"
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
export ANNOTATE_ATTEMPTS_FILE="$sand/ledger.json"
export ANNOTATE_MAX_ATTEMPTS=2
ledger() { python3 tools/annotate_attempts.py "$@"; }
attempts() {  # how many failures the ledger holds against a puzzle
  python3 - "$ANNOTATE_ATTEMPTS_FILE" "$1" <<'EOF'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except (FileNotFoundError, ValueError):
    d = {}
print(d.get("puzzles", {}).get(sys.argv[2], {}).get("attempts", 0))
EOF
}
rm -f "$ANNOTATE_ATTEMPTS_FILE"

echo "a failed night is charged to the puzzle, with the session it died in"
eval "$charge"
record_annotate_failure ct-1 "ct-1 failed: API Error: exceeded the output token maximum" sid-9 >/dev/null
check "one attempt" "$(attempts ct-1)" "1"
check "and the session is kept, so tomorrow can resume it" "$(ledger session ct-1)" "sid-9"

echo "a lockout or a logged-out CLI is our fault, and costs the puzzle nothing"
record_annotate_failure ct-2 "ct-2 failed: Claude AI usage limit reached" sid-8 >/dev/null
record_annotate_failure ct-2 "ct-2 failed: Failed to authenticate: OAuth session expired" "" >/dev/null
record_annotate_failure ct-2 "five-hour window 92% spent (limit 70%)" "" >/dev/null
check "no attempts" "$(attempts ct-2)" "0"
check "and nothing to resume" "$(ledger session ct-2)" ""

echo "at the limit a puzzle leaves the queue, and the night's budget is refilled"
record_annotate_failure ct-1 "ct-1 failed: API Error: exceeded the output token maximum" sid-9 >/dev/null
check "two attempts" "$(attempts ct-1)" "2"
check "blocked" "$(ledger blocked)" "ct-1"
index ct-1:300:no ct-3:200:no ct-4:100:no
( cd "$sand" && ANNOTATE_MAX=2 eval "$pick" && printf '%s\n' "$pending" ) > "$sand/out"
check "the two newest that are not blocked, not one of them and a hole" \
  "$(cat "$sand/out")" "ct-3 ct-4"

echo "a person is told once, not every night for ever"
check "the first ask names it" "$(ledger blocked --if-changed)" "ct-1"
check "the second says nothing" "$(ledger blocked --if-changed)" ""
record_annotate_failure ct-5 "ct-5 failed: something broke" "" >/dev/null
record_annotate_failure ct-5 "ct-5 failed: something broke" "" >/dev/null
check "a puzzle joining them speaks up again" \
  "$(ledger blocked --if-changed | tr '\n' ' ')" "ct-1 ct-5 "

echo "a puzzle that ends up annotated anyway is forgotten, however that happened"
# A real id out of the corpus's own index, because the pruning reads the index
# beside annotate_attempts.py rather than one this test could invent — and that
# is the point of it: a blocked puzzle somebody annotates by hand, or one the
# blind-solve grading later strips a clue from, must not be held out of the
# queue by a count nobody remembers is there.
done_id=$(python3 -c 'import json; print(next(p["id"] for p in
          json.load(open("puzzles/index.json"))["puzzles"] if p["annotated"]))')
record_annotate_failure "$done_id" "failed: something broke" "" >/dev/null
record_annotate_failure "$done_id" "failed: something broke" "" >/dev/null
check "not blocked" "$(ledger blocked | grep -c "^$done_id\$")" "0"
check "and the count is gone with it" "$(attempts "$done_id")" "0"

echo "a clean exit that wrote no annotation is a lost night like any other"
index ct-6:300:yes ct-7:200:no
annotated_nums="ct-6 ct-7"
ann_sids=" ct-6:sid-6 ct-7:sid-7"
ann_session_of() { printf '%s\n' $ann_sids | sed -n "s/^$1://p" | tail -1; }
record_annotate_failure ct-6 "unused" "" >/dev/null
( cd "$sand" && eval "$settle" ) >/dev/null
check "the puzzle the index calls annotated is forgotten" "$(attempts ct-6)" "0"
check "the one that is still bare is charged" "$(attempts ct-7)" "1"
check "with its session, so tomorrow resumes rather than restarts" \
  "$(ledger session ct-7)" "sid-7"

[ "$fails" = 0 ] && echo "annotate attempts: all checks passed" || echo "annotate attempts: $fails FAILED"
exit $((fails > 0))
