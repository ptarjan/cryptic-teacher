#!/bin/bash
# Does a rejected annotation alert only when the puzzle is parked?
#
#     bash tools/test_discard_alert.sh
#
# commit_puzzle is read out of tools/prereset_backfill.sh and run on its retry
# pass with every command it calls stubbed. When the validator rejects the
# puzzle and the run left model answers it could not parse, reopen_answers
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
eval "$(sed -n '/^commit_puzzle() {/,/^}/p' "$REPO/tools/prereset_backfill.sh")"
export DRY_RUN=0
ALERTS="$scratch/alerts"; RECORDS="$scratch/records"
WHICH=""; REOPEN_OK=1
alert() { echo "$*" >>"$ALERTS"; }
discard_puzzle() { :; }
reopen_answers() { [ "$REOPEN_OK" = 1 ]; }
python3() {
  case "$1" in
    tools/validate_annotations.py) echo "  ERROR: 5D: no annotation."; return 1 ;;
    tools/reopen_answers.py) [ -n "$WHICH" ] && echo "$WHICH"; return 0 ;;
    tools/failed_inputs.py) echo "$*" >>"$RECORDS"; return 0 ;;
    *) echo "unexpected python3 $*" >&2; return 2 ;;
  esac
}
run() {  # run <which> <reopen ok>
  WHICH="$1"; REOPEN_OK="$2"; rm -f "$ALERTS" "$RECORDS"
  commit_puzzle times-19116 Annotate retry >/dev/null 2>&1
}
count() { [ -f "$1" ] && grep -c "$2" "$1" || echo 0; }

run "5-down" 1
check "rejected and reopened: commit_puzzle fails" "1" "$?"
check "rejected and reopened: no alert" "0" "$(count "$ALERTS" .)"
check "rejected and reopened: not parked" "0" "$(count "$RECORDS" .)"

run "" 1
check "rejected, nothing to reopen: commit_puzzle fails" "1" "$?"
check "rejected, nothing to reopen: one discard alert" "1" "$(count "$ALERTS" 'Annotate times-19116 was discarded')"
check "rejected, nothing to reopen: alert quotes the validator" "1" "$(count "$ALERTS" '5D: no annotation')"
check "rejected, nothing to reopen: parked" "1" "$(count "$RECORDS" 'record annotate times-19116')"

run "5-down" 0
check "reopen failed: discard alert" "1" "$(count "$ALERTS" 'Annotate times-19116 was discarded')"
check "reopen failed: parked" "1" "$(count "$RECORDS" 'record annotate times-19116')"

if [ "$fails" = 0 ]; then echo "all passed"; else echo "$fails failed"; exit 1; fi
