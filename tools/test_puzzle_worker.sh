#!/bin/bash
# Is tools/puzzle_worker.sh the only thing that solves or annotates a puzzle,
# and is every cold solve the first half of an annotation?
#
# Paul's rule: we do not solve until we are hinting. A solve run on its own
# pick spends a model on a grid the run may never annotate. The nightly and the
# burn differ only in which ids they work and how they pace it; the work itself
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

echo "a solve is asked for only on the way to an annotation"
# The nightly: inside the annotation loop, ahead of that puzzle's annotation.
loop=$(awk '/^    for num in \$pending; do$/,/^    done$/' tools/daily_update.sh)
check "the nightly calls worker_solve once" "$(grep -c '^[^#]*worker_solve ' tools/daily_update.sh)" "1"
check "inside its annotation loop" "$(grep -c 'worker_solve ' <<<"$loop")" "1"
check "before that loop's worker_annotate" \
  "$(awk '/worker_solve /{s=NR} /worker_annotate /{a=NR} END{print (s && a && s < a)}' <<<"$loop")" "1"
# And the loop is the only place the nightly runs a model on a puzzle at all.
check "the nightly calls worker_annotate only there" \
  "$(grep -c '^[^#]*worker_annotate ' tools/daily_update.sh) $(grep -c 'worker_annotate ' <<<"$loop")" "1 1"
# The burn: run_solve is the only caller, and only pool_launch's annotate pool
# reaches it; solve_applied puts the puzzle next in line for its annotation.
check "the burn calls worker_solve only from run_solve" \
  "$(grep -c '^[^#]*worker_solve ' tools/prereset_backfill.sh) $(awk '/^run_solve\(\) \{/,/^\}/' tools/prereset_backfill.sh | grep -c 'worker_solve ')" "1 1"
launch=$(awk '/^pool_launch\(\) \{/,/^\}/' tools/prereset_backfill.sh)
check "run_solve is launched only by pool_launch" \
  "$(grep -c '^[^#]*run_solve "' tools/prereset_backfill.sh) $(grep -c 'run_solve "' <<<"$launch")" "1 1"
check "and only for the annotate pool" \
  "$(grep -B2 'run_solve "' <<<"$launch" | grep -c 'WAVE_WHAT" = Annotate')" "1"
check "a solved puzzle is queued next, for its annotation" \
  "$(awk '/^solve_applied\(\) \{/,/^\}/' tools/prereset_backfill.sh | grep -c 'queue=("${queue\[@\]:0:$at}" "$id"')" "1"
# And both hand the solve's conversation on: the burn names the same sid file
# for the solve and the annotation that follows it.
check "the burn's solve and annotation share one sid file" \
  "$(grep -o 'worker_\(solve\|annotate\) .*"/tmp/ct-prereset-\$[a-z]*\.sid"' tools/prereset_backfill.sh | wc -l | tr -d ' ')" "2"
check "the nightly's solve and annotation share one sid file" \
  "$(grep -c 'worker_\(solve\|annotate\) .*"\$sidfile"' <<<"$loop")" "2"

echo "what is done to one puzzle after its run is the worker's alone"
# Validating a puzzle, committing it, pushing it on its own, reopening its
# answers and discarding it are per-puzzle steps; a scheduler that grows its
# own copy is the nightly and the burn drifting apart again.
for f in tools/daily_update.sh tools/prereset_backfill.sh; do
  check "$f does not validate a puzzle itself" \
    "$(grep -c '^[^#]*tools/validate_annotations\.py "\$' "$f")" "0"
  check "$f does not apply a fill itself" "$(grep -c '^[^#]*python3 tools/apply_solution\.py' "$f")" "0"
  # Each script's own commits are its run's: the nightly's fetched puzzles and
  # closing sweep, the burn's republish. Anything else is a puzzle's.
  check "$f does not commit or push one puzzle itself" \
    "$(grep '^[^#]*push_puzzle_commit\|^[^#]*git commit' "$f" | grep -vc "Daily update: \|Republish after ")" "0"
  check "$f does not reopen answers itself" "$(grep -c '^[^#]*tools/reopen_answers\.py' "$f")" "0"
  check "$f defines none of the worker's functions" \
    "$(grep -oE '^(worker_[a-z_]+|puzzle_spec|clues_spec|index_lock|index_unlock|discard_puzzle|stage_puzzle)\(\)' "$f" | tr '\n' ' ')" ""
  check "$f runs worker_finish once, so every puzzle it annotates is finished the same way" \
    "$(grep -c '^[^#]*worker_finish ' "$f")" "1"
  check "$f sources the worker" "$(grep -c '^\. "\$REPO/tools/puzzle_worker\.sh"$' "$f")" "1"
done
check "the nightly finishes a puzzle inside its annotation loop" \
  "$(grep -c 'worker_finish ' <<<"$loop")" "1"

[ "$fails" = 0 ] && echo "puzzle worker: all checks passed" || echo "puzzle worker: $fails FAILED"
exit $((fails > 0))
