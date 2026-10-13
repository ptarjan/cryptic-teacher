#!/usr/bin/env bash
# Does .githooks/pre-commit run each check only when the commit stages what it
# reads, and cost next to nothing otherwise? Paul 10-13: "Why does precommit
# take 6 seconds to do nothing?" Each case stages into a throwaway index
# (GIT_INDEX_FILE, so the real index and tree are untouched) with python3 and
# node shims that log their arguments: a commit staging no checked input starts
# neither and finishes within NOOP_BUDGET; a puzzle commit (what the OCR pass
# makes) starts one Python, tools/precommit_puzzles.py, and no layout check; an
# added tool gets the layout and SMOKE_DEPS checks; a deleted puzzle the two
# rename checks. Then tools/precommit_puzzles.py for real: a filed puzzle
# passes, one whose clue no longer holds its annotation's quote is refused.
set -euo pipefail
cd "$(dirname "$0")/.."
NOOP_BUDGET=0.5  # seconds, best of three; the hook takes ~0.03 s when idle
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir "$tmp/bin"
for b in python3 node; do
  printf '#!/bin/sh\necho "%s $*" >> "%s/calls"\n' "$b" "$tmp" > "$tmp/bin/$b"
  chmod +x "$tmp/bin/$b"
done
mapfile -t two < <(git ls-files 'puzzles/*/*/*.json' | grep -v '/index\.json$' | head -2)
other=$(git rev-parse "HEAD:.gitignore")
fail() { echo "test_precommit_speed: $*"; exit 1; }

stage() {  # stage <update-index args...>: a fresh index from HEAD's, then this change
  GIT_INDEX_FILE="$tmp/index" git read-tree HEAD
  GIT_INDEX_FILE="$tmp/index" git update-index "$@"
}
hook() {  # hook: run the hook on the staged index; the shims' log in $calls
  : > "$tmp/calls"
  GIT_INDEX_FILE="$tmp/index" PATH="$tmp/bin:$PATH" sh .githooks/pre-commit \
    || fail "the hook refused: $(cat "$tmp/calls")"
  calls=$(cat "$tmp/calls")
}
has() { grep -qF -- "$1" <<<"$calls" || fail "$2: wanted '$1', ran: ${calls:-nothing}"; }
lacks() { ! grep -qF -- "$1" <<<"$calls" || fail "$2: ran '$1', ran: $calls"; }

# A commit touching nothing a check reads: no Python, no node, and fast.
stage --cacheinfo "100644,$other,README.md"
best=9
for _ in 1 2 3; do
  s=$EPOCHREALTIME; hook; e=$EPOCHREALTIME
  [ -z "$calls" ] || fail "a README edit started: $calls"
  best=$(awk -v s="$s" -v e="$e" -v b="$best" 'BEGIN { t = e - s; print (t < b ? t : b) }')
done
awk -v t="$best" -v b="$NOOP_BUDGET" 'BEGIN { exit !(t <= b) }' \
  || fail "a no-op commit took ${best}s, over its ${NOOP_BUDGET}s budget"

# An edited puzzle: its two checks, in one Python start, and nothing else.
stage --cacheinfo "100644,$(git rev-parse "HEAD:${two[1]}"),${two[0]}"
hook
[ "$calls" = "python3 tools/precommit_puzzles.py ${two[0]}" ] \
  || fail "an edited puzzle ran: $calls"

# A new puzzle (the OCR pass's commit): a new path, but an exempt one.
stage --add --cacheinfo "100644,$(git rev-parse "HEAD:${two[0]}"),puzzles/times/1900/times-0.json"
hook
has "python3 tools/precommit_puzzles.py puzzles/times/1900/times-0.json" "a new puzzle"
lacks "build_readme" "a new puzzle"
lacks "renamed_ids" "a new puzzle"

# A new tool: the layout check and the SMOKE_DEPS check, and no puzzle check.
stage --add --cacheinfo "100644,$other,tools/zz_new_tool.py"
hook
has "python3 tools/build_readme.py --check-layout" "a new tool"
has "node tools/test_ci_cache_deps.js" "a new tool"
lacks "precommit_puzzles" "a new tool"

# An edit to the layout table: the layout check.
stage --cacheinfo "100644,$other,docs/LAYOUT.md"
hook
has "build_readme.py --check-layout" "a LAYOUT.md edit"

# A deleted puzzle: both rename checks.
stage --force-remove "${two[0]}"
hook
has "python3 tools/renamed_ids.py --check-staged" "a deleted puzzle"
has "python3 tools/puzzle_rows.py --check-staged" "a deleted puzzle"

# The puzzle checks themselves.
python3 tools/precommit_puzzles.py "${two[0]}" 2>/dev/null \
  || fail "precommit_puzzles.py refused ${two[0]} as filed"
annotated=$({ git grep -l '"annotation": {' HEAD -- 'puzzles/cryptic/*.json' || true; } | head -1 | cut -d: -f2-)
python3 - "$annotated" "$tmp/broken.json" <<'EOF'
import json, sys
p = json.load(open(sys.argv[1]))
e = next(e for e in p["entries"] if isinstance(e.get("annotation"), dict))
e["clue"]["text"] = "Zzz (3)"
json.dump(p, open(sys.argv[2], "w"))
EOF
if out=$(python3 tools/precommit_puzzles.py "$tmp/broken.json" 2>&1); then
  fail "precommit_puzzles.py passed a clue that no longer holds its annotation's quotes"
fi
grep -q "QUOTE" <<<"$out" || fail "a broken quote, but no QUOTE flag: $out"
echo "test_precommit_speed: ok (no-op hook ${best}s)"
