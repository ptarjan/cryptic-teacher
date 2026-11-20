#!/bin/bash
# A bag with no clue due never starts a session (pool_bag in tools/prereset_backfill.sh).
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$REPO/tools/prereset_backfill.sh"
fails=0
check() { if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1: expected [$2], got [$3]"; fails=$((fails + 1)); fi; }

tree="$(mktemp -d)"; trap 'rm -rf "$tree"' EXIT
RUNS="$tree/runs"; mkdir -p "$RUNS"
DRY_RUN=0 WAVE_WHAT="Backfill wordplay.delSingle for" wide=1 at=0
POOL_RUNS=() queue=(lead)
declare -A SHAPE_RULE_OF=()
eval "$(sed -n '/^pool_what() {/,/^}/p;/^bag_rule() {/,/^}/p;/^bag_field() {/,/^}/p;/^pool_bags() {/,/^}/p;/^pool_bag() {/,/^}/p' "$SCRIPT")"
BAG_FIELDS=" blocks.note "
ANSWER=""
# The stub reads its stdin like the real clue_bag.py: left unread, the printf feeding it dies of SIGPIPE
# when the stub exits first, pipefail fails the pipeline and pool_bag returns 0 (flaky on a loaded runner).
python3() { case "$1" in tools/clue_bag.py) cat >/dev/null; printf '%s\n' "$ANSWER" ;; *) echo 10 ;; esac; }

ANSWER="lead 0"; pool_bag lead; rc=$?
check "a bag of 0 clues due is refused" 1 "$rc"
check "and writes no bag file" "" "$(ls "$RUNS")"
ANSWER="lead 2"; pool_bag lead >/dev/null; rc=$?
check "a bag with clues due goes" 0 "$rc"
check "and is named in its bag file" "lead" "$(cat "$RUNS/lead.bag")"
rm -f "$RUNS"/*
WAVE_WHAT=Annotate ANSWER="lead 0"; pool_bag lead >/dev/null; rc=$?
check "Annotate's pool is not gated on a count (a whole puzzle is its own session)" 0 "$rc"

[ "$fails" = 0 ] && echo "zero-clue bag: all checks passed" || echo "zero-clue bag: $fails FAILED"
exit $((fails > 0))
