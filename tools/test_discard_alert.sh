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
# that alert goes out with the validator's errors.
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
WHICH=""; REOPEN_OK=1; VALID=1; CHANGED=1
alert() { echo "$*" >>"$ALERTS"; }
discard_puzzle() { :; }
worker_reopen() { [ "$REOPEN_OK" = 1 ]; }
worker_annotate() { echo "$4" >>"$FIXES"; }
worker_commit() { echo "commit $1" >>"$RECORDS"; }
index_lock() { :; }; index_unlock() { :; }; stage_puzzle() { :; }
git() { [ "$1" = status ] && [ "$CHANGED" = 1 ] && echo " M x"; return 0; }
python3() {
  case "$1" in
    tools/validate_annotations.py) [ "$VALID" = 1 ] && return 0; echo "  ERROR: 5D: no annotation."; return 1 ;;
    tools/reopen_answers.py) [ -n "$WHICH" ] && echo "$WHICH"; return 0 ;;
    tools/failed_inputs.py) echo "$*" >>"$RECORDS"; return 0 ;;
    tools/puzzle_paths.py) echo "puzzles/times/2020/$2.json" ;;
    tools/annotate_check.py) return 1 ;;
    tools/check_annotation_loss.py|tools/own_rows.py) return 0 ;;
    *) echo "unexpected python3 $*" >&2; return 2 ;;
  esac
}
run() {  # run <which> <reopen ok> [valid] [changed]
  WHICH="$1"; REOPEN_OK="$2"; VALID="${3:-0}"; CHANGED="${4:-1}"; rm -f "$ALERTS" "$RECORDS" "$FIXES"
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

if [ "$fails" = 0 ]; then echo "all passed"; else echo "$fails failed"; exit 1; fi
