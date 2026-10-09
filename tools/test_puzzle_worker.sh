#!/bin/bash
# Is tools/puzzle_worker.sh the only thing that solves or annotates a puzzle,
# and is every cold solve made by the run that annotates it, its fill checked
# again before anything built on it ships?
#
# Paul's rule: we do not solve until we are hinting, and one turn does both. A
# solve run on its own pick spends a model on a grid the run may never
# annotate. The nightly and the burn differ only in which ids they work and how
# they pace it; the work itself
# is the worker's, so a second copy of the solve or annotate call anywhere is
# the place that rule would leak back in.
#
#     bash tools/test_puzzle_worker.sh
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
fails=0
check() { if [ "$2" = "$3" ]; then echo "  ok: $1"; else
  echo "  FAIL: $1"$'\n'"    expected: $3"$'\n'"    got:      $2"; fails=$((fails + 1)); fi; }

# Code only: tests, prose and data may name the prompts freely.
code=$(git ls-files -- '*.sh' '*.py' '*.toml' '*.js' '*.mjs' '*.yml' '*.yaml' |
       grep -v '^tools/test_\|^puzzles/\|^clues_only/')

echo "the solve and annotate prompts are run from exactly one file"
# A model run on a prompt file is an --append-system-prompt-file naming it, or
# naming a variable that could hold it.
check "solve_prompt.md / annotate_prompt.md as a system prompt" \
  "$(grep -l -E -- '-system-prompt-file"?,? +"?(tools/(solve|annotate)_prompt\.md|\$)' $code | tr '\n' ' ')" \
  "tools/puzzle_worker.sh "
check "the cold-solve task" \
  "$(grep -l 'Solve the cryptic crossword' $code | tr '\n' ' ')" "tools/puzzle_worker.sh "

echo "a solve is asked for only by the run that annotates the puzzle"
check "nothing calls a solve-only run" \
  "$(grep -l 'worker_solve\|run_solve' $code | tr '\n' ' ')" ""
# The nightly: the loop's one worker_annotate takes the fill, which only an
# unsolved id in that loop sets, and worker_apply checks it after the run.
loop=$(awk '/^    for num in \$pending; do$/,/^    done$/' tools/daily_update.sh)
check "the nightly calls worker_annotate once, inside its loop, with the fill" \
  "$(grep -c '^[^#]*worker_annotate ' tools/daily_update.sh) $(grep -c 'worker_annotate .*"\$fill"$' <<<"$loop")" "1 1"
check "the nightly sets a fill path only for an unsolved id" \
  "$(grep -c '^[^#]*fill="\$work_dir' tools/daily_update.sh) $(grep -A1 '\*" \$num "\*)' <<<"$loop" | grep -c 'fill="\$work_dir')" "1 1"
check "the nightly checks the fill once, after the run" \
  "$(grep -c '^[^#]*worker_apply ' tools/daily_update.sh) $(awk '/worker_annotate /{a=NR} /worker_apply /{p=NR} END{print (a && p && a < p)}' <<<"$loop")" "1 1"
# The burn: run_claude is the one caller of worker_annotate, and only
# pool_launch's annotate pool hands it a fill.
check "the burn calls worker_annotate only from run_claude, with the fill" \
  "$(grep -c '^[^#]*worker_annotate ' tools/prereset_backfill.sh) $(awk '/^run_claude\(\) \{/,/^\}/' tools/prereset_backfill.sh | grep -c 'worker_annotate .*"\$fill"$')" "1 1"
launch=$(awk '/^pool_launch\(\) \{/,/^\}/' tools/prereset_backfill.sh)
check "only the annotate pool gives a run a fill path" \
  "$(grep -c '^[^#]*fill="/tmp/ct-prereset-\$id\.fill"$' tools/prereset_backfill.sh) $(grep -B2 'fill="/tmp' <<<"$launch" | grep -c 'WAVE_WHAT" = Annotate')" "1 1"
check "the burn checks the fill only through solve_applied" \
  "$(grep -c '^[^#]*worker_apply ' tools/prereset_backfill.sh) $(awk '/^solve_applied\(\) \{/,/^\}/' tools/prereset_backfill.sh | grep -c 'worker_apply ')" "1 1"

echo "what is done to one puzzle after its run is the worker's alone"
# Validating a puzzle, committing it, pushing it on its own, reopening its
# answers and discarding it are per-puzzle steps; a scheduler that grows its
# own copy is the nightly and the burn drifting apart again.
for f in tools/daily_update.sh tools/prereset_backfill.sh; do
  check "$f does not validate a puzzle itself" \
    "$(grep -c '^[^#]*tools/validate_annotations\.py "\$' "$f")" "0"
  check "$f does not apply a fill itself" "$(grep -c '^[^#]*python3 tools/apply_solution\.py' "$f")" "0"
  # Each script's own commits are its run's: the nightly's fetched puzzles
  # (committed and pushed as HEAD before anything annotates, its subject from
  # tools/commit_subject.py) and closing sweep, the burn's republish. Anything
  # else is a puzzle's. The burn's hourly sync publishes each local commit
  # origin lacks, whatever it holds.
  check "$f does not commit or push one puzzle itself" \
    "$(grep '^[^#]*push_puzzle_commit\|^[^#]*git commit' "$f" | grep -vc "| python3 tools/commit_subject\.py \|Republish after \|push_puzzle_commit\.sh HEAD ||$\|push_puzzle_commit\.sh \"\$c\" \&\& continue$")" "0"
  check "$f does not reopen answers itself" "$(grep -c '^[^#]*tools/reopen_answers\.py' "$f")" "0"
  check "$f defines none of the worker's functions" \
    "$(grep -oE '^(worker_[a-z_]+|puzzle_spec|clues_spec|index_lock|index_unlock|discard_puzzle|stage_puzzle)\(\)' "$f" | tr '\n' ' ')" ""
  check "$f runs worker_finish once, so every puzzle it annotates is finished the same way" \
    "$(grep -c '^[^#]*worker_finish ' "$f")" "1"
  check "$f sources the worker" "$(grep -c '^\. "\$REPO/tools/puzzle_worker\.sh"$' "$f")" "1"
done
check "the nightly finishes a puzzle inside its annotation loop" \
  "$(grep -c 'worker_finish ' <<<"$loop")" "1"

echo "one run solves and annotates; the script then checks the fill"
# Driven with a fake claude and fake git and python3, so it spends nothing and
# touches no puzzle: what is checked is which calls the worker makes.
stub=$(mktemp -d)
trap 'rm -rf "$stub" tools/_ann_pw-test-$$.json tools/_puzzle_pw-test-$$.json' EXIT
cat >"$stub/claude" <<'STUB'
#!/bin/bash
printf '%s\n' "$*" >>"$CALLS"
# Everything after `-p <task>`, one argument per line, for the prefix check.
[ -n "${PREFIX:-}" ] && printf '%s\n' "${@:3}" >"$PREFIX"
# A run that solved: its fill is where its task said.
fill=$(sed -n 's/.*writing your fill to \([^;]*\);.*/\1/p' <<<"$*")
[ -n "$fill" ] && [ -n "${WRITE_FILL:-}" ] && echo '{"1-across": {"answer": "X", "definition": "x"}}' >"$fill"
echo "done"
STUB
chmod +x "$stub/claude"
# shellcheck disable=SC2329  # its stubs are called by the sourced worker
flow() (   # mode: accepted | refused | nofill | nohints | badhints
  PATH="$stub:$PATH" CALLS="$stub/calls" EVENTS="$stub/events"
  export CALLS
  : >"$CALLS"; : >"$EVENTS"
  [ "$1" = nofill ] || export WRITE_FILL=1
  # shellcheck disable=SC2034  # read by the sourced worker
  CLAUDE_HEADLESS=() WORKER_MODEL=opus WORKER_EFFORT=medium WORKER_WRAP="" WORKER_JOB=test
  . tools/puzzle_worker.sh
  session_id() { echo sid-1; }
  session_exists() { false; }
  git() { echo "git $*" >>"$EVENTS"; }
  alert() { echo "alert $*" >>"$EVENTS"; }
  discard_puzzle() { echo "discard $1" >>"$EVENTS"; }
  python3() {
    echo "python3 $*" >>"$EVENTS"
    case "$1" in
      tools/apply_solution.py)
        [ "$MODE" = refused ] && { echo "REJECTED — 1 problem(s), nothing written:"; echo "  1-across: crossing disagrees"; return 1; }
        echo "wrote 1 solutions" ;;
      tools/annotate_check.py)
        echo "session $CLAUDE_CODE_SESSION_ID" >>"$EVENTS"
        [ "$MODE" = nohints ] && { echo "annotate_check $2: STOPPED — the annotations were not applied"; return 2; }
        [ "$MODE" = badhints ] && { printf '  ERROR: 14A: no annotation.\nannotate_check %s: STOPPED\n' "$2"; return 2; } ;;
      tools/failed_inputs.py) echo "recorded" ;;
    esac
    return 0
  }
  MODE="$1"
  id="pw-test-$$" fill="$stub/fill" sidfile="$stub/sid"
  : >"tools/_ann_$id.json"
  worker_annotate "$id" "$stub/log" "$sidfile" "Annotate it from tools/_puzzle_$id.json." "" "$fill"
  echo "rc=$?"
  echo "calls=$(wc -l <"$CALLS" | tr -d ' ')"
  echo "sid=$(cat "$sidfile")"
  worker_apply "$id" "$fill" "$stub/log" "$stub/verdict" "$sidfile"
  echo "applied=$?"
  echo "ann=$([ -e "tools/_ann_$id.json" ] && echo kept || echo gone)"
)
got() { sed -n "s/^$1=//p" <<<"$out"; }

out=$(flow accepted)
argv=$(cat "$stub/calls") events=$(cat "$stub/events")
check "one claude call does both" "$(got calls)" "1"
check "its task sends it to the solve method, then the annotation" \
  "$(grep -c 'Read tools/solve_prompt.md.*this task: Annotate it' <<<"$argv")" "1"
check "on the annotation's system prompt" \
  "$(sed -n 's/.*--append-system-prompt-file \([^ ]*\).*/\1/p' <<<"$argv")" "tools/annotate_prompt.md"
check "with no web, since it solves" \
  "$(grep -o -- '--allowedTools [^ ]*' <<<"$argv" | grep -c 'WebSearch\|WebFetch')" "0"
check "its conversation is marked as a solve's" "$(got sid)" "sid-1 solve"
check "the fill is applied from the committed puzzle, then the hints put back" \
  "$(grep -o 'git checkout\|tools/apply_solution.py [^ ]* --fill\|tools/solve_misses.py keep-log\|tools/annotate_check.py' <<<"$events" | tr '\n' '|')" \
  "git checkout|tools/apply_solution.py pw-test-$$ --fill|tools/solve_misses.py keep-log|tools/annotate_check.py|"
check "as the run's own session, where their author is read" "$(grep -c '^session sid-1$' <<<"$events")" "1"
check "and accepted" "$(got applied)" "0"
check "with nothing recorded or discarded" "$(grep -c 'failed_inputs\|^discard' <<<"$events")" "0"

out=$(flow refused)
events=$(cat "$stub/events")
check "a refused fill is rejected" "$(got applied)" "1"
check "and recorded in the solve ledger as judged, with the applier's reason" \
  "$(grep -c 'failed_inputs.py record solve pw-test-[0-9]* --judged --reason   1-across: crossing disagrees' <<<"$events")" "1"
check "its puzzle and rows discarded" "$(grep -c '^discard pw-test' <<<"$events")" "1"
check "its hints never applied" "$(grep -c 'tools/annotate_check.py' <<<"$events")" "0"
check "and its annotation file gone, so no later run builds on it" "$(got ann)" "gone"

out=$(flow nohints)
events=$(cat "$stub/events")
check "hints that did not land reject the solve" "$(got applied)" "2"
check "its puzzle and rows discarded, so no fill ships without them" "$(grep -c '^discard pw-test' <<<"$events")" "1"
check "said out loud" "$(grep -c '^alert test solved pw-test-[0-9]* but could not put its hints back' <<<"$events")" "1"
check "with nothing recorded against the fill" "$(grep -c 'failed_inputs' <<<"$events")" "0"

out=$(flow badhints)
events=$(cat "$stub/events")
check "hints the validator refused reject the solve" "$(got applied)" "2"
check "and are recorded against the puzzle as judged, with the error" \
  "$(grep -c 'failed_inputs.py record annotate pw-test-[0-9]* --judged --reason   ERROR: 14A: no annotation.' <<<"$events")" "1"

out=$(flow nofill)
events=$(cat "$stub/events")
check "a run that wrote no fill is rejected" "$(got applied)" "1"
check "recorded unjudged, for the ledger to tell a lockout from a verdict" \
  "$(grep -c 'failed_inputs.py record solve pw-test-[0-9]* --reason done' <<<"$events")" "1"
check "without asking the applier" "$(grep -c 'apply_solution' <<<"$events")" "0"

echo "every run sends the same cached prefix; only the task differs"
# The system prompt, tool definitions and skill/agent listings come from these
# flags, so a flag that varied by puzzle or by kind of run would make every
# run write its own cache. --session-id, --allowedTools and --max-turns are
# not in the prompt and are masked.
prefix_args() (   # id fill
  PATH="$stub:$PATH" CALLS="$stub/calls" PREFIX="$stub/prefix"
  export CALLS PREFIX
  # shellcheck disable=SC2034  # read by the sourced worker
  CLAUDE_HEADLESS=(--strict-mcp-config) WORKER_MODEL=opus WORKER_EFFORT=medium WORKER_WRAP="" WORKER_JOB=test
  . tools/puzzle_worker.sh
  session_id() { echo sid-x; }
  session_exists() { false; }
  worker_annotate "$1" "$stub/log" "$stub/sid-$1" "Annotate $1." "" "$2" >/dev/null
  awk 'm { m = 0; print "<masked>"; next }
       /^--(session-id|allowedTools|max-turns)$/ { m = 1 } { print }' "$PREFIX"
)
keyed=$(prefix_args times-1 "")
solve=$(prefix_args guardian-2 "$stub/fill2")
check "a keyed run and a cold solve of another puzzle send identical prompt flags" \
  "$([ -n "$keyed" ] && [ "$keyed" = "$solve" ] && echo same || diff <(echo "$keyed") <(echo "$solve"))" "same"
check "the tool list is fixed by --tools" "$(grep -c -- '^--tools$' <<<"$keyed")" "1"

echo "a git add refused by another command's index.lock is tried again"
# shellcheck disable=SC2329  # its stubs are called by the sourced worker
stage_with() (   # how many adds are refused before one goes through
  CLAUDE_HEADLESS=() WORKER_MODEL=opus WORKER_EFFORT=medium WORKER_WRAP="" WORKER_JOB=test
  . tools/puzzle_worker.sh
  n=0
  git() { case "$1" in add) n=$((n + 1)); [ "$n" -gt "$REFUSE" ];; *) return 0;; esac; }
  python3() { return 0; }
  sleep() { :; }
  REFUSE="$1"
  stage_puzzle pw-test-$$ && echo "staged after $n" || echo "refused after $n"
)
check "two refusals, then staged" "$(stage_with 2)" "staged after 3"
check "a lock that never clears still fails, after five tries" "$(stage_with 99)" "refused after 5"

[ "$fails" = 0 ] && echo "puzzle worker: all checks passed" || echo "puzzle worker: $fails FAILED"
exit $((fails > 0))
