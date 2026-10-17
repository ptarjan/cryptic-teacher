#!/bin/bash
# Does a rejected annotation alert only when the puzzle is parked?
#
#     bash tools/test_discard_alert.sh
#
# worker_finish (tools/puzzle_worker.sh, what both the nightly and the burn run
# after an annotation) is run with every command it calls stubbed. A rejected
# puzzle first goes back to its conversation once to be fixed. When the
# validator still rejects it and the run left model answers it could not
# parse, worker_reopen
# sends them back to be solved again: nothing is lost for good and nobody has
# anything to mend, so no alert. When there is nothing to reopen, or the
# reopen fails, the puzzle is parked until a person changes its inputs, and
# that alert goes out with the validator's errors. When the run's only failure
# is answers left to a preamble the puzzle lacks (tools/await_preamble.py
# --which), the puzzle is marked to await it and committed: no alert, no park.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() {  # check <what> <expected> <got>
  if [ "$2" = "$3" ]; then echo "ok   $1"; else
    echo "FAIL $1: expected [$2], got [$3]"; fails=$((fails + 1)); fi
}

scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT
cd "$REPO" || exit 1
. tools/puzzle_worker.sh
ALERTS="$scratch/alerts"; RECORDS="$scratch/records"; FIXES="$scratch/fixes"
DROP=0; ANNOTATED=""; VERDICT=alert; WHICH=""; REOPEN_OK=1; VALID=1; CHANGED=1; WANTS=""; AWAIT_OK=1
export WORKER_JOB="the test"  # read by the sourced puzzle_worker.sh
alert() { echo "$*" >>"$ALERTS"; }
discard_puzzle() { :; }
worker_reopen() { [ "$REOPEN_OK" = 1 ]; }
worker_annotate() { echo "$4" >>"$FIXES"; }
worker_commit() { echo "commit $1" >>"$RECORDS"; }
index_lock() { :; }; index_unlock() { :; }; stage_puzzle() { :; }
git() { [ "$1" = status ] && [ "$CHANGED" = 1 ] && echo " M x"; return 0; }
python3() {
  case "$1" in
    tools/validate_annotations.py)
      [ "$2" = --deploy ] && return 0
      [ "$VALID" = 1 ] && return 0
      [ -n "$ANNOTATED" ] && echo "times-19116: 3/4 annotated — FAIL"
      if [ -n "$ANNOTATED" ] && [ ! -e "$scratch/dropped" ]; then echo "  ERROR: 5D: block gives II"; else echo "  ERROR: 5D: no annotation."; fi
      return 1 ;;
    tools/drop_failed_clues.py) echo "$*" >>"$RECORDS"; [ "$DROP" = 1 ] && { touch "$scratch/dropped"; echo "5-down"; } ;;
    tools/reopen_answers.py) [ -n "$WHICH" ] && echo "$WHICH"; return 0 ;;
    tools/await_preamble.py)
      [ "${3:-}" = --which ] && { [ -n "$WANTS" ] && echo "$WANTS"; return 0; }
      [ "$AWAIT_OK" = 1 ] && echo "marked $2" >>"$RECORDS"; [ "$AWAIT_OK" = 1 ] ;;
    tools/discard_alert.py) [ "$2" = judge ] && echo "$VERDICT"; return 0 ;;
    tools/failed_inputs.py) echo "$*" >>"$RECORDS"; return 0 ;;
    tools/puzzle_paths.py) echo "puzzles/times/2020/$2.json" ;;
    tools/annotate_check.py) return 1 ;;
    tools/check_annotation_loss.py|tools/own_rows.py) return 0 ;;
    *) echo "unexpected python3 $*" >&2; return 2 ;;
  esac
}
run() {  # run <which> <reopen ok> [valid] [changed] [wants] [await ok]
  WHICH="$1"; REOPEN_OK="$2"; VALID="${3:-0}"; CHANGED="${4:-1}"; WANTS="${5:-}"; AWAIT_OK="${6:-1}"
  rm -f "$ALERTS" "$RECORDS" "$FIXES" "$scratch/dropped"
  worker_finish times-19116 Annotate "$scratch/sid" "$scratch/log" >/dev/null 2>&1
}
count() { [ -f "$1" ] || { echo 0; return; }; grep -c "$2" "$1"; }

run "5-down" 1
check "rejected and reopened: worker_finish says solve it again" "2" "$?"
check "rejected: handed back to its conversation once first" "1" "$(count "$FIXES" 'does not validate')"
check "rejected and reopened: no alert" "0" "$(count "$ALERTS" .)"
check "rejected and reopened: not parked" "0" "$(count "$RECORDS" .)"

run "" 1
check "rejected, nothing to reopen: worker_finish fails" "1" "$?"
check "rejected, nothing to reopen: one discard alert" "1" "$(count "$ALERTS" 'Annotate times-19116 was discarded')"
check "rejected, nothing to reopen: alert quotes the validator" "1" "$(count "$ALERTS" '5D: no annotation')"
check "rejected, nothing to reopen: parked" "1" "$(count "$RECORDS" 'record annotate times-19116')"

run "5-down" 0
check "reopen failed: discard alert" "1" "$(count "$ALERTS" 'Annotate times-19116 was discarded')"
check "reopen failed: parked" "1" "$(count "$RECORDS" 'record annotate times-19116')"

run "" 1 1
check "valid: committed" "1" "$(count "$RECORDS" 'commit Annotate times-19116')"
check "valid: its failure record cleared" "1" "$(count "$RECORDS" 'clear annotate times-19116')"
check "valid: no fix run" "0" "$(count "$FIXES" .)"

run "" 1 1 0
check "a clean run that wrote nothing: not committed" "0" "$(count "$RECORDS" 'commit ')"
check "a clean run that wrote nothing: recorded against the puzzle" "1" "$(count "$RECORDS" 'record annotate times-19116')"

run "" 1 0 1 "1D 4D"
check "left to a missing preamble: worker_finish fails" "1" "$?"
check "left to a missing preamble: marked to await it" "1" "$(count "$RECORDS" 'marked times-19116')"
check "left to a missing preamble: committed" "1" "$(count "$RECORDS" 'commit Await the preamble for times-19116')"
check "left to a missing preamble: not parked on its inputs" "0" "$(count "$RECORDS" 'record annotate')"
check "left to a missing preamble: no alert" "0" "$(count "$ALERTS" .)"

run "" 1 0 1 "1D 4D" 0
check "could not mark it: parked on its inputs" "1" "$(count "$RECORDS" 'record annotate times-19116 --judged')"
check "could not mark it: one alert" "1" "$(count "$ALERTS" 'could not mark times-19116')"
check "could not mark it: not committed" "0" "$(count "$RECORDS" 'commit ')"

# tools/discard_alert.py decides who is woken (its own rules: test_discard_verdict.sh).
VERDICT=retry; run "" 1
check "first discard: no alert" "0" "$(count "$ALERTS" .)"
check "first discard: left unparked for a retry" "0" "$(count "$RECORDS" 'record annotate')"
VERDICT=ledger; run "" 1
check "a repeat of a seen class: no alert" "0" "$(count "$ALERTS" .)"
check "a repeat of a seen class: parked" "1" "$(count "$RECORDS" 'record annotate times-19116')"
VERDICT=silent; run "" 1
check "unmendable preamble case: no alert" "0" "$(count "$ALERTS" .)"
check "unmendable preamble case: parked" "1" "$(count "$RECORDS" 'record annotate times-19116')"
VERDICT=alert

# Clues that still fail after the fix run cost only their own hints.
DROP=1; ANNOTATED=1; VERDICT=retry; run "" 1
check "failed clue, first time: worker_finish ships (0)" "0" "$?"
check "failed clue, first time: dropped by tools/drop_failed_clues.py" "1" "$(count "$RECORDS" 'drop_failed_clues.py times-19116')"
check "failed clue, first time: the rest committed" "1" "$(count "$RECORDS" 'commit Annotate times-19116')"
check "failed clue, first time: left unparked so its tail is picked up" "0" "$(count "$RECORDS" 'record annotate')"
check "failed clue, first time: no alert" "0" "$(count "$ALERTS" .)"
check "failed clue, first time: the failure count is kept" "0" "$(count "$RECORDS" 'clear annotate')"
VERDICT=alert; run "" 1
check "failed clue, second time: the rest still ship" "1" "$(count "$RECORDS" 'commit Annotate times-19116')"
check "failed clue, second time: parked on its inputs" "1" "$(count "$RECORDS" 'record annotate times-19116 --judged')"
check "failed clue, second time: one alert naming the clue" "1" "$(count "$ALERTS" 'shipped without 5-down')"
VERDICT=ledger; run "" 1
check "failed clue, repeated class: parked, no alert" "1 0" "$(count "$RECORDS" 'record annotate times-19116') $(count "$ALERTS" .)"
VERDICT=alert; DROP=0; run "" 1
check "a failure naming no clue: still discarded (1)" "1" "$?"
check "a failure naming no clue: not committed" "0" "$(count "$RECORDS" 'commit ')"
check "a failure naming no clue: parked and alerted as before" "1 1" "$(count "$RECORDS" 'record annotate times-19116') $(count "$ALERTS" 'was discarded')"
DROP=0; ANNOTATED=""

if [ "$fails" = 0 ]; then echo "all passed"; else echo "$fails failed"; exit 1; fi
