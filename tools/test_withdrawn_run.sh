#!/bin/bash
# Does a run that takes back its own work ship none of it? genius-268 (10-13)
# rejected its own run and asked for a `git checkout` its permissions refused;
# the second validation passed the file it had meant to revert, and its 29
# hints and guessed fills were committed as "Annotate genius-268". A run now
# withdraws with `annotate_check.py <ID> --withdraw`, and the harness
# (worker_withdrawn / worker_withdraw in tools/puzzle_worker.sh) puts the
# puzzle back itself.
#
#     bash tools/test_withdrawn_run.sh
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
fails=0
check() { if [ "$2" = "$3" ]; then echo "  ok: $1"; else
  echo "  FAIL: $1"$'\n'"    expected: $3"$'\n'"    got:      $2"; fails=$((fails + 1)); fi; }

. tools/puzzle_worker.sh
CLAUDE_HEADLESS=()
WORKER_MODEL=opus WORKER_EFFORT=medium WORKER_WRAP="" WORKER_JOB=test
id=zz-withdraw-test
d=$(mktemp -d)
trap 'rm -rf "$d"; rm -f "tools/_withdrawn_$id.txt" "tools/_ann_$id.json"' EXIT
calls="$d/calls"
alert() { echo "ALERT $*" >>"$calls"; }
# Every step that would touch the tree or the index is recorded instead.
discard_puzzle() { echo "DISCARD $1" >>"$calls"; }
stage_puzzle() { echo "STAGE $1" >>"$calls"; }
worker_commit() { echo "COMMIT $1" >>"$calls"; }
worker_reopen() { echo "REOPEN $1" >>"$calls"; }
index_lock() { :; }
VALID=0
python3() {
  echo "python3 $*" >>"$calls"
  case "$1" in
    tools/validate_annotations.py) return "$VALID" ;;
    tools/puzzle_paths.py) echo "puzzles/x/2025/$2.json" ;;
  esac
  return 0
}
reset() { : >"$calls"; rm -f "tools/_withdrawn_$id.txt"; echo '{}' >"tools/_ann_$id.json"; }

echo "genius-268's own last words (no marker) are a withdrawal"
reset
cat >"$d/out" <<'EOF'
- The first check run copied those 29 annotations into `puzzles/genius/2025/genius-268.json`. The solve prompt says to annotate nothing in this case, so I tried `git checkout` to remove them, but it needed approval I couldn't get here. Running `git checkout -- puzzles/genius/2025/genius-268.json` and re-applying the fill would leave the fill only.

GUESS: 9A ASSAILER; LIKELY: 3D SHATTERED, 13A TEAR, 8D GRIMACE, 26A TERM; all others CONFIDENT
EOF
_worker_finish "$id" Annotate "$d/$id.sid" "$d/out" >"$d/said"
check "worker_finish discards it (1)" "$?" 1
check "nothing staged or committed, though it validates" "$(grep -c '^STAGE\|^COMMIT' "$calls")" 0
check "the puzzle is put back" "$(grep -c "^DISCARD $id" "$calls")" 1
check "its annotation file goes" "$([ -e "tools/_ann_$id.json" ] && echo kept || echo gone)" gone
check "recorded against its inputs" "$(grep -c "failed_inputs.py record annotate $id --judged" "$calls")" 1
check "the log says why" "$(grep -c 'withdrew its own work.*git revert' "$d/said")" 1

echo "the sanctioned route: annotate_check.py --withdraw leaves the marker"
reset
out=$(command python3 tools/annotate_check.py genius-268 --withdraw "9A, 13A and 26A beat me" 2>&1)
check "it exits 0 and says the file is put back" "$? $(grep -c 'put back as committed' <<<"$out")" "0 1"
check "the marker holds the reason" "$(cat tools/_withdrawn_genius-268.txt 2>/dev/null)" "9A, 13A and 26A beat me"
rm -f tools/_withdrawn_genius-268.txt
echo "a reason" >"tools/_withdrawn_$id.txt"
echo "all CONFIDENT" >"$d/out"
_worker_finish "$id" Annotate "$d/$id.sid" "$d/out" >"$d/said"
check "a marked run is discarded, not committed" "$? $(grep -c '^COMMIT' "$calls")" "1 0"
check "the marker is consumed" "$([ -e "tools/_withdrawn_$id.txt" ] && echo kept || echo gone)" gone

echo "a fix run that withdraws ships nothing either"
reset
VALID=1
worker_annotate() { echo "FIXRUN" >>"$calls"; echo "fix" >"tools/_withdrawn_$1.txt"; echo "LIKELY: 3D X" >"$2"; }
echo "all CONFIDENT" >"$d/out"
_worker_finish "$id" Annotate "$d/$id.sid" "$d/out" >"$d/said"
check "discarded after the fix run, never reopened or committed" \
  "$? $(grep -c '^FIXRUN' "$calls") $(grep -c '^COMMIT\|^REOPEN\|^STAGE' "$calls")" "1 1 0"
# shellcheck disable=SC2016  # the pattern matches the literal text
check "the fix prompt names the sanctioned route" \
  "$(grep -c 'annotate_check.py \$id --withdraw' tools/puzzle_worker.sh)" 1
VALID=0

echo "a withdrawn solve has neither its fill nor its hints applied"
reset
echo "why" >"tools/_withdrawn_$id.txt"
echo '{}' >"$d/fill"
worker_apply "$id" "$d/fill" "$d/out" "$d/verdict" "$d/$id.sid" >/dev/null
check "worker_apply returns 2 (no alert in the nightly)" "$?" 2
check "the applier never runs" "$(grep -c 'apply_solution.py' "$calls")" 0

echo "a stopped run that withdrew is not resumed into its edits"
reset
echo "why" >"tools/_withdrawn_$id.txt"
echo "note" >"$d/note"
worker_failed "$id" Annotate "$d/note" "$d/$id.sid"
check "discarded, no resume note" "$? $(grep -c "^DISCARD" "$calls") $([ -e "$d/note" ] && echo note || echo none)" "1 1 none"

echo "an ordinary run is not taken for a withdrawal"
rm -f "tools/_withdrawn_$id.txt"
echo "LIKELY: 3D RESET, 5A RESTORED, 7D CHECKOUT GIRL; all others CONFIDENT" >"$d/out"
worker_withdrawn "$id" "$d/out" >/dev/null
check "answers in a confidence line are not a git request" "$?" 1
worker_withdrawn "$id" >/dev/null
check "no marker, no output: not withdrawn" "$?" 1

echo "a fresh conversation clears a stale marker"
# shellcheck disable=SC2016  # the pattern matches the literal text
check "worker_annotate removes it before a new session" \
  "$(awk '/^worker_annotate\(\) \{/,/^\}/' tools/puzzle_worker.sh | grep -c 'rm -f "tools/_withdrawn_\$id.txt"')" 1

[ "$fails" = 0 ] && echo "withdrawn run: all checks passed" || echo "withdrawn run: $fails FAILED"
exit $((fails > 0))
