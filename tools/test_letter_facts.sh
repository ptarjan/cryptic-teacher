#!/bin/bash
# Does tools/letter_facts.py read a type off the letters only where they allow one reading?
#
#     bash tools/test_letter_facts.sh
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() {  # check <what> <expected type> <clue> <answer> [--definition D] [--block L=words]...
  what=$1 want=$2
  shift 2
  got=$(python3 "$REPO/tools/letter_facts.py" --clue "$@" | python3 -c \
    'import json,sys; r=json.load(sys.stdin); print("NONE" if r is None else r.get("type") or "UNDECIDED")')
  if [ "$want" = "$got" ]; then echo "ok   $what"; else
    echo "FAIL $what: expected [$want], got [$got]"; fails=$((fails + 1)); fi
}

check "a run of words with the answer's letters is an anagram" anagram \
  'Men on phone exchange will be a rarity' PHENOMENON --definition 'a rarity'
check "the answer inside one word is hidden" "hidden word" 'Bird spotted in Leatherhead (4)' RHEA
check "the answer backwards across words is a hidden reversal" "hidden word + reversal" \
  'Ruler rejects any dubious packages from the East (6)' DYNAST
check "a block inside another is a container" container \
  'American novelist gets stuck penning English (5)' JAMES --block 'JAMS=gets stuck' --block E=English
check "one block taken out of another is a deletion" deletion \
  'How far across (ignoring depth)? A lungful (6)' BREATH --block 'BREADTH=How far across' --block D=depth
check "fodder beside a block is charade + anagram" "charade + anagram" \
  "Girl's to eat after brewing lager (9)" GERALDINE --block DINE=eat
check "a literal clue word inside a block is a container, not an anagram" container \
  'Try to catch the girl (7)' HEATHER --block HEAR=Try --definition girl
check "a letter taken from a word the source names is a first letter" "charade + reversal + first letter" \
  "Famous college backed Delius' overture (5)" NOTED --block ETON=college --block "D=Delius' overture"
check "a lone word's initial is an abbreviation, not a selection" charade \
  'One from Yokohama being paid in yen (8)' YEARNING --block Y=Yokohama --block 'EARNING=being paid'
check "fodder less the blocks is left to a person" UNDECIDED \
  'Being dry, replacement unfortunately left out (10)' TEMPERANCE --block L=left --definition 'Being dry'
check "a Spooner clue is not an anagram" NONE \
  "Posy says no, according to Spooner (7)" NOSEGAY --block GOES=says --block NAY=no
check "a short answer is not hidden by chance" NONE 'Tea and scones (3)' AND

[ "$fails" -eq 0 ] && echo "all letter_facts checks passed" || { echo "$fails failed"; exit 1; }
