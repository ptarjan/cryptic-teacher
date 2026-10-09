#!/bin/bash
# Does a run stopped from outside resume its own conversation, with its edits
# back when that is honest and a note saying so when not?
#
#     bash tools/test_worker_resume.sh
#
# A restart (or a unit's time limit) kills a run whose transcript is on disk
# and whose edits sit in a tree the next start resets. tools/puzzle_worker.sh
# sets them aside before the reset (worker_set_aside_tree) and the next launch
# of the puzzle puts them back (worker_put_back). The decisions pinned here:
# edits come back only when master has not touched the puzzle since; restored
# edits that validate are kept, anything else is discarded; either way the
# conversation resumes with a note that says which; a record a day old or
# whose transcript is gone starts fresh instead.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() {  # check <what> <expected> <got>
  if [ "$2" = "$3" ]; then echo "ok   $1"; else
    echo "FAIL $1: expected [$2], got [$3]"; fails=$((fails + 1)); fi
}

t="$(mktemp -d)"
trap 'rm -rf "$t"' EXIT
t="$(cd "$t" && pwd -P)"
export CLAUDE_CONFIG_DIR="$t/cfg"
alert() { echo "ALERT: $*"; }
. "$REPO/tools/claude_session.sh"
. "$REPO/tools/puzzle_worker.sh"

# A repo with the real own_rows.py, and stand-ins for the tools the worker
# calls whose own behaviour is not under test: a puzzle validates unless it
# says BROKEN.
main="$t/main"
mkdir -p "$main/tools/data" "$main/puzzles/s/2026" "$main/clues_only/s"
printf 'SOURCE_LIGHT_WRONG = {\n}\n' >"$main/tools/fetch_puzzle.py"
cp "$REPO/tools/own_rows.py" "$REPO/tools/json_merge.py" "$REPO/tools/puzzle_schema.py" "$main/tools/"
cp "$REPO/tools/data/puzzle.schema.json" "$main/tools/data/"
for f in setter_error source_answer_wrong source_clue_wrong; do
  printf '{\n "z-1/1-across": ["x", "Y", "a sibling\x27s row"]\n}\n' >"$main/tools/data/$f.json"
done
cat >"$main/tools/puzzle_paths.py" <<'PY'
import glob, sys
for pid in sys.argv[1:]:
    print((glob.glob(f"puzzles/*/*/{pid}.json") or [f"puzzles/s/2026/{pid}.json"])[0])
PY
printf 'import glob, sys\nsys.exit("BROKEN" in open(glob.glob(f"puzzles/*/*/{sys.argv[1]}.json")[0]).read())\n' \
  >"$main/tools/validate_annotations.py"
printf 'import sys\n' >"$main/tools/discard_clue_rows.py"
printf '_*\n' >"$main/tools/.gitignore"
for id in a b c d e f; do echo '{"clues": "original"}' >"$main/puzzles/s/2026/s-$id.json"; done
echo '{"clues": "only"}' >"$main/clues_only/s/s-h.json"
git -C "$main" init -q -b master
git -C "$main" add -A
git -C "$main" -c user.name=t -c user.email=t@t commit -q -m base
git -C "$main" worktree add -q --detach "$t/tree" master
git -C "$main" worktree add -q --detach "$t/tree2" master
tree="$t/tree"

# Where the CLI keeps a cwd's transcripts.
proj() { printf '%s/projects/%s' "$CLAUDE_CONFIG_DIR" "${1//[^A-Za-z0-9]/-}"; }
# A run started in tree $1 on puzzle $2: its record and its transcript.
start_run() {  # tree id [kind]
  local sidfile
  sidfile="$(cd "$1" && worker_runs burn)/$2.sid"
  echo "sid-$2${3:+ $3}" >"$sidfile"
  echo "$1" >"${sidfile%.sid}.tree"
  mkdir -p "$(proj "$1")"
  : >"$(proj "$1")/sid-$2.jsonl"
  printf '%s\n' "$sidfile"
}
# The restart: every record of the tree set aside, then the tree reset.
restart() {  # tree
  worker_set_aside_tree "$1"
  git -C "$1" reset -q --hard master
}
put_back() {  # id -> rc, the note in $t/note
  rm -f "$t/note"
  (cd "$tree" && worker_put_back "$1" Annotate "$t/note" "$(worker_runs burn)/$1.sid" >"$t/out" 2>&1); local rc=$?; [ -n "${DEBUG:-}" ] && cat "$t/out" >&2; return $rc
}
note() { cat "$t/note" 2>/dev/null; }
runs="$(cd "$tree" && worker_runs burn)"

echo "edits that validate, master untouched: put back, kept, resumed"
start_run "$tree" s-a >/dev/null
echo '{"clues": "annotated half"}' >"$tree/puzzles/s/2026/s-a.json"
echo '{"1a": "hint"}' >"$tree/tools/_ann_s-a.json"
printf '{\n "s-a/1-across": ["x", "Y", "why"],\n "z-1/1-across": ["x", "Y", "a sibling\x27s row"]\n}\n' >"$tree/tools/data/source_clue_wrong.json"
restart "$tree"
rm -f "$tree/tools/_ann_s-a.json"
put_back s-a; rc=$?
check "resumes" "0" "$rc"
check "the puzzle's edits are back" '{"clues": "annotated half"}' "$(cat "$tree/puzzles/s/2026/s-a.json")"
check "its annotation file is back" '{"1a": "hint"}' "$(cat "$tree/tools/_ann_s-a.json" 2>/dev/null)"
check "its row of the source tables is back beside the sibling's" "2" "$(grep -c '"s-a/1-across"\|"z-1/1-across"' "$tree/tools/data/source_clue_wrong.json")"
check "the note says the edits are as it left them" "1" "$(note | grep -c 'exactly as you left them')"
check "the record stays for the run, its aside is gone" "yes no" \
  "$([ -s "$runs/s-a.sid" ] && echo yes || echo no) $([ -e "$runs/s-a.aside" ] && echo yes || echo no)"

echo "master changed the puzzle meanwhile: nothing comes back, the note says why"
start_run "$tree" s-b >/dev/null
echo '{"clues": "run edit"}' >"$tree/puzzles/s/2026/s-b.json"
worker_set_aside_tree "$tree"
echo '{"clues": "fixed upstream"}' >"$main/puzzles/s/2026/s-b.json"
git -C "$main" -c user.name=t -c user.email=t@t commit -q -am upstream
git -C "$tree" reset -q --hard master
put_back s-b; rc=$?
check "resumes" "0" "$rc"
check "master's version stands" '{"clues": "fixed upstream"}' "$(cat "$tree/puzzles/s/2026/s-b.json")"
check "the note says master changed it and the edits are gone" "1 1" \
  "$(note | grep -c 'changed it while you were stopped') $(note | grep -c 'edits you had made to it are gone')"

echo "edits that do not validate: discarded, the conversation still resumes"
start_run "$tree" s-c >/dev/null
echo '{"clues": "BROKEN mid-write"}' >"$tree/puzzles/s/2026/s-c.json"
echo '{"1a": "hint"}' >"$tree/tools/_ann_s-c.json"
restart "$tree"
put_back s-c; rc=$?
check "resumes" "0" "$rc"
check "the half-written file is put back as committed" '{"clues": "original"}' "$(cat "$tree/puzzles/s/2026/s-c.json")"
check "the note says the edits are gone and the annotation file is intact" "1 1" \
  "$(note | grep -c 'edits you had made to it are gone') $(note | grep -c 'tools/_ann_s-c.json is as you left it')"

echo "a run from another tree is resumed here, that tree left alone"
start_run "$t/tree2" s-d >/dev/null
echo '{"clues": "from tree2"}' >"$t/tree2/puzzles/s/2026/s-d.json"
put_back s-d; rc=$?
check "resumes" "0" "$rc"
check "its edits are copied here" '{"clues": "from tree2"}' "$(cat "$tree/puzzles/s/2026/s-d.json")"
check "its own tree is untouched" '{"clues": "from tree2"}' "$(cat "$t/tree2/puzzles/s/2026/s-d.json")"
check "its transcript is copied into this tree's project to resume from" "yes" \
  "$( (cd "$tree" && session_here sid-s-d) && [ -f "$(proj "$tree")/sid-s-d.jsonl" ] && echo yes || echo no)"
check "a reset of this tree does not set aside a record of another" "no" \
  "$(start_run "$t/tree2" s-f >/dev/null; worker_set_aside_tree "$tree"; [ -e "$runs/s-f.aside" ] && echo yes || echo no)"

echo "a record a day old, or with no transcript, starts fresh"
sidfile=$(start_run "$tree" s-e)
touch -t "$(date -d '2 days ago' +%Y%m%d%H%M 2>/dev/null || date -v-2d +%Y%m%d%H%M)" "$sidfile"
put_back s-e; rc=$?
check "a stale record: fresh, and forgotten" "1 no" "$rc $([ -e "$sidfile" ] && echo yes || echo no)"
sidfile=$(start_run "$tree" s-e)
rm -f "$CLAUDE_CONFIG_DIR"/projects/*/sid-s-e.jsonl
put_back s-e; rc=$?
check "no transcript: fresh, and forgotten" "1 no" "$rc $([ -e "$sidfile" ] && echo yes || echo no)"
put_back s-nothing; rc=$?
check "no record: fresh" "1" "$rc"

echo "a cold solve's promotion: the new file back, the clues-only file gone again"
start_run "$tree" s-h solve >/dev/null
rm "$tree/clues_only/s/s-h.json"
echo '{"clues": "solved"}' >"$tree/puzzles/s/2026/s-h.json"
echo 'FILL' >"$runs/s-h.fill"
restart "$tree"
put_back s-h; rc=$?
check "resumes" "0" "$rc"
check "the solved file is back and the clues-only file gone" '{"clues": "solved"} gone' \
  "$(cat "$tree/puzzles/s/2026/s-h.json") $([ -e "$tree/clues_only/s/s-h.json" ] && echo there || echo gone)"
check "its kind and fill survive" "solve FILL" "$(worker_kind "$runs/s-h.sid") $(cat "$runs/s-h.fill")"

if [ "$fails" -gt 0 ]; then echo "worker resume: $fails check(s) failed"; exit 1; fi
echo "worker resume: all checks passed"
