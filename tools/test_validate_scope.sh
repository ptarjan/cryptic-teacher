#!/usr/bin/env bash
# The deploy's validate job checks only what a push could have changed
# (tools/validate_scope.py): a puzzle edit, or a tools/ edit nothing the check
# reaches calls, stays incremental; a change to a rule, a table it reads, the
# authored puzzle's inputs or the workflow is a full check. And the full check
# spread across cores prints exactly what the serial one does.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 - <<'EOF'
import sys
sys.path.insert(0, "tools")
import validate_scope as v

src = open("tools/validate_annotations.py", encoding="utf-8").read()

def decide(changes, new_src=None):
    return v.decide(changes, lambda p: new_src if new_src is not None else src)

def expect(label, got, mode, text=""):
    if got[0] != mode or (text and text not in str(got[1])):
        sys.exit(f"test_validate_scope: {label}: wanted {mode} {text!r}, got {got}")

P = "puzzles/times/2002/times-21965.json"
expect("puzzle edits", decide([("A", P), ("M", "puzzles/nation/2013/nation-3270.json"),
                               ("D", "clues_only/nation/nation-3269.json"), ("D", "puzzles/x/2001/x-1.json")]),
       "files")
expect("the puzzles are named", v.decide([("A", P), ("M", "docs/NIGHTLY.md")]), "files")
assert v.decide([("A", P), ("M", "docs/NIGHTLY.md")])[1] == [P]
expect("a rename-looking status", v.decide([("R", P)]), "full", "R " + P)
expect("a fetcher nothing reaches", v.decide([("M", "tools/fetch_telegraph.py")]), "files")
expect("a test and the budgets", v.decide([("M", "tools/test_step_budgets.sh"),
                                            ("M", "tools/data/deploy_budgets.json"),
                                            ("M", "README.md")]), "files")
expect("a rule table", v.decide([("M", "tools/data/clue_types.json")]), "full", "clue_types.json")
expect("the backlog", v.decide([("M", "tools/annotation_backlog.json")]), "full", "annotation_backlog.json")
expect("the authored clues", v.decide([("M", "tools/data/authored_A001_clues.json")]), "full", "authored_A001_clues.json")
expect("the workflow", v.decide([("M", ".github/workflows/pages.yml")]), "full", "pages.yml")
expect("a reached module with no old text", v.decide([("M", "tools/validate_annotations.py")]), "full", "old text")
expect("a comment in the validator", decide([("M", "tools/validate_annotations.py")], src + "\n# a comment\n"), "files")
expect("a new rule", decide([("M", "tools/validate_annotations.py")], src.replace("POOL_MIN = 200", "POOL_MIN = 7")),
       "full", "POOL_MIN")
expect("an added reached module", v.decide([("A", "tools/validate_annotations.py")]), "full")
print("test_validate_scope: scope ok")
EOF
# The pool prints what the serial run prints: 500 puzzles is past POOL_MIN.
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
ls puzzles/times/*/*.json | sed -n 1,500p > "$tmp/files"
[ "$(wc -l < "$tmp/files")" -ge 300 ] || { echo "test_validate_scope: too few puzzles to reach the pool"; exit 1; }
VALIDATE_JOBS=1 xargs python3 tools/validate_annotations.py --deploy < "$tmp/files" > "$tmp/serial" 2>&1 || true
VALIDATE_JOBS=2 xargs python3 tools/validate_annotations.py --deploy < "$tmp/files" > "$tmp/pool" 2>&1 || true
cmp "$tmp/serial" "$tmp/pool" || { echo "test_validate_scope: pool output differs from serial"; diff "$tmp/serial" "$tmp/pool" | head; exit 1; }
[ -s "$tmp/serial" ] || { echo "test_validate_scope: no output"; exit 1; }
echo "test_validate_scope: all passed"
