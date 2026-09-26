#!/bin/bash
# Does tools/add_abbreviation.py survive the thing that actually happened?
#
# tools/prereset_backfill.sh runs four annotator sessions at once, and more
# than one of them can decide the same clue-writing pass needs a new
# abbreviation. Before this script existed, "add the row" meant read the whole
# JSON, add a row in memory, write the whole file back — and when two sessions
# did that at nearly the same time, whichever write landed second won, silently
# discarding the first session's row. Both writes were valid JSON, so nothing
# ever complained; a row just stopped being there. This test's last case is the
# one that matters: fire off several adds in parallel and check every row
# survived, because a lock that is only ever exercised by one caller at a time
# proves nothing about the bug it exists to fix.
#
#     bash tools/test_add_abbreviation.sh
set -uo pipefail
cd "$(dirname "$0")/.."
fails=0
check() { if [ "$2" = "$3" ]; then echo "  ok: $1"; else
  echo "  FAIL: $1"$'\n'"    expected: $3"$'\n'"    got:      $2"; fails=$((fails + 1)); fi; }

# A sandboxed copy of the script AND the table, in the same relative layout
# (tools/add_abbreviation.py finds the table via its OWN path, not the cwd), so
# every case below writes to a throwaway file and the tracked table never
# moves for a test run.
sand=$(mktemp -d)
trap 'rm -rf "$sand"' EXIT
mkdir -p "$sand/tools/data"
cp tools/add_abbreviation.py tools/build_abbreviations.py "$sand/tools/"
cp tools/data/abbreviations.json "$sand/tools/data/abbreviations.json"
add() { python3 "$sand/tools/add_abbreviation.py" "$@"; }
row() { python3 -c "
import json
print(json.load(open('$sand/tools/data/abbreviations.json'))['abbreviations'].get('$1', []))
"; }

echo "a fresh add creates the row:"
add ZZ testsense >/dev/null
check "the new row exists" "$(row ZZ)" "['testsense']"

echo "adding the same sense again is a no-op:"
before=$(md5sum "$sand/tools/data/abbreviations.json" | cut -d' ' -f1)
add ZZ testsense >/dev/null
after=$(md5sum "$sand/tools/data/abbreviations.json" | cut -d' ' -f1)
check "the file did not change" "$after" "$before"
check "the row still has exactly one sense" "$(row ZZ)" "['testsense']"

echo "a no-op on an untouched row leaves the file byte-identical too:"
# The sandbox is a byte-for-byte copy of the real table (copied above, not
# reconstructed), so a no-op against an entry the real table already has —
# "about" is A's very first sense — is the same proof as running it against
# the tracked file, without a test needing to touch the tracked file at all.
before=$(md5sum "$sand/tools/data/abbreviations.json" | cut -d' ' -f1)
add A about >/dev/null
after=$(md5sum "$sand/tools/data/abbreviations.json" | cut -d' ' -f1)
check "an existing letter's existing sense changes nothing" "$after" "$before"

echo "a second sense is appended, sorted, existing rows untouched elsewhere:"
add AB stopgap >/dev/null
check "AB gained the new sense alongside the old ones" "$(row AB)" \
  "['sailor', 'seaman', 'stopgap']"

echo "a sense that differs only in punctuation takes the existing spelling:"
add ZY "High-Speed" >/dev/null
check "the table's own spelling lands, not a second anchor" "$(row ZY)" "['high speed']"
add ZY "test sense" "test-sense" >/dev/null
check "two spellings in one call land once" "$(row ZY)" "['high speed', 'test sense']"

echo "several concurrent adds to the same row all survive:"
pids=()
for i in $(seq 1 10); do
  add QQ "sense$i" >/dev/null &
  pids+=("$!")
done
for p in "${pids[@]}"; do wait "$p"; done
got=$(row QQ)
missing=0
for i in $(seq 1 10); do
  case "$got" in *"sense$i"*) ;; *) missing=$((missing + 1));; esac
done
check "all 10 concurrent senses landed" "$missing" "0"
check "the table is still valid JSON" \
  "$(python3 -c "import json; json.load(open('$sand/tools/data/abbreviations.json')); print('ok')")" "ok"

if [ "$fails" -eq 0 ]; then echo "add_abbreviation: all checks passed"; else
  echo "add_abbreviation: $fails check(s) failed"; exit 1; fi
