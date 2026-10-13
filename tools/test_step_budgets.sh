#!/usr/bin/env bash
# Every step of the deploy (.github/workflows/pages.yml) is named and has a
# time budget in tools/data/deploy_budgets.json, and a step that reads the
# whole corpus says how it skips unchanged work (tools/step_budgets.py lint).
# Then the lint itself, on copies broken the ways a new step would break it.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 tools/step_budgets.py lint
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
wf=.github/workflows/pages.yml
table=tools/data/deploy_budgets.json
fails() {  # fails <label> <workflow> <table> <expected text>
  if out=$(python3 tools/step_budgets.py lint "$2" "$3"); then
    echo "test_step_budgets: lint passed $1"; exit 1
  fi
  grep -qF -- "$4" <<<"$out" || { echo "test_step_budgets: $1: wanted '$4', got:"; echo "$out"; exit 1; }
}
# A new step with no budget row.
sed 's|^      - name: Stamp the assets$|      - name: Squash the PNGs\n        run: true\n      - name: Stamp the assets|' "$wf" > "$tmp/new.yml"
fails "a step with no budget" "$tmp/new.yml" "$table" "build/Squash the PNGs: no row"
# A new unnamed step.
sed 's|^      - name: Stamp the assets$|      - run: true\n      - name: Stamp the assets|' "$wf" > "$tmp/unnamed.yml"
fails "an unnamed step" "$tmp/unnamed.yml" "$table" "has no name"
# A corpus step that drops its corpus mark and its cache.
python3 - "$table" "$tmp/nocorpus.json" <<'EOF'
import json, sys
t = json.load(open(sys.argv[1]))
t["build/Build the puzzle shims and reindex"] = {"seconds": 150}
json.dump(t, open(sys.argv[2], "w"))
EOF
fails "a corpus step not marked" "$wf" "$tmp/nocorpus.json" "reads the whole corpus"
# A corpus step marked, but with no cache, no incremental and no reason.
python3 - "$table" "$tmp/nocache.json" <<'EOF'
import json, sys
t = json.load(open(sys.argv[1]))
t["build/Build the puzzle shims and reindex"] = {"seconds": 150, "corpus": True}
json.dump(t, open(sys.argv[2], "w"))
EOF
fails "a corpus step with no cache" "$wf" "$tmp/nocache.json" "its row needs"
# The cache it names is gone from the workflow.
awk '/^      - name: Restore the row cache$/{skip=1; next} skip && /^      - /{skip=0} !skip' "$wf" > "$tmp/nocachestep.yml"
fails "a cache step removed" "$tmp/nocachestep.yml" "$table" "names cache step 'Restore the row cache'"
# A row for a step that is gone.
fails "a stale row" "$tmp/nocachestep.yml" "$table" "build/Restore the row cache: a budget row for a step pages.yml does not have"
echo "test_step_budgets: all passed"
