#!/bin/bash
# Does tools/file_georgeho_puzzles.py read georgeho's rows into the record the
# grid rebuild and file_blog_puzzles.build take?
#
#     bash tools/test_file_georgeho_puzzles.sh
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() {  # check <what> <expected> <got>
  if [ "$2" = "$3" ]; then echo "ok   $1"; else
    echo "FAIL $1: expected [$2], got [$3]"; fails=$((fails + 1)); fi
}
out=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
import file_georgeho_puzzles as G
print("LIGHTS", G.lights_of("13/15a", "d"), G.lights_of("26,10", "d"), G.lights_of("Great", "a"))
print("COUNT", G.count_of("ROMAN WALL"), G.count_of("NON-FATAL"), G.count_of("SWAP"))
U = "http://bigdave44.com/2010/01/04/toughie-250/"
rows = [("toughie-250", U, "Toughie 250", "1a", "Hands over exchange here (4)", "SWAP"),
        ("toughie-250", U, "Toughie 250", "5", "A Roman barrier", "ROMAN WALL"),
        ("toughie-250", U, "Toughie 250", "2", "Wimps", "MILKSOPS"),
        ("toughie-250", U, "Toughie 250", "3/4", "Linked", "AT A LOSS"),
        ("toughie-250", U, "Toughie 250", "4", "See 3", "nan")]
rec, why = G.record("toughie-250", rows)
print("REC", why, rec["date"], rec["number"],
      [(e["number"], e["direction"], e["clue"], e["counted"]) for e in rec["entries"]])
print("LINKED", rec["unsplit"][0]["lights"], rec["unsplit"][0]["enumeration"])
print("NODATE", G.record("x-1", [("x-1", "https://example.com/1.html", "X 1", "1a", "c", "A")])[1])
PY
)
field() { awk -v k="$1" '$1==k {$1=""; sub(/^ /,""); print}' <<<"$out"; }
check "a linked cell's suffix covers every number; a bare one takes the heading" \
      "[(13, 'across'), (15, 'across')] [(26, 'down'), (10, 'down')] None" "$(field LIGHTS)"
check "a count is read off the blogger's word breaks" "5,4 3-5 4" "$(field COUNT)"
check "the post date is the url's; numbers that start again are the downs; a missing count is marked" \
      "None 2010-01-04 250 [(1, 'across', 'Hands over exchange here (4)', False), (5, 'across', 'A Roman barrier (5,4)', True), (2, 'down', 'Wimps (8)', True)]" \
      "$(field REC)"
check "a linked answer is left for the grid to split" "[[3, 'down'], [4, 'down']] 2,1,4" "$(field LINKED)"
check "a post with no date is not a record" "no post date" "$(field NODATE)"
if [ "$fails" -gt 0 ]; then echo "$fails FAILURE(S)"; exit 1; fi
echo "file_georgeho_puzzles: all checks passed"
