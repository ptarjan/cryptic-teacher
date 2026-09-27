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
check "a lone word's initial is a first letter unless it is a listed abbreviation" "charade + first letter" \
  'One from Yokohama being paid in yen (8)' YEARNING --block Y=Yokohama --block 'EARNING=being paid'
check "fodder less the blocks is left to a person" UNDECIDED \
  'Being dry, replacement unfortunately left out (10)' TEMPERANCE --block L=left --definition 'Being dry'
check "a Spooner clue is not an anagram" NONE \
  "Posy says no, according to Spooner (7)" NOSEGAY --block GOES=says --block NAY=no
check "a listed abbreviation is no selection" charade \
  'Soprano gets each singer fish (3,4)' SEABASS --block S=Soprano --block EA=each --block BASS=singer
check "a lone word cut short is a deletion" "deletion + reversal" \
  'March curtailed, flipping study intensely (4)' CRAM --block MARC=March
check "a lone word cut to two letters is a deletion" "charade + deletion" \
  'Sea curtailed at chair (4)' SEAT --block SE=sea --block AT=at --definition chair
check "two letters of a short word that are also its outer letters are undecided" UNDECIDED \
  "Extremely sick unclean kitchens: they're smelly (6)" SKUNKS --block SK=sick --block UN=unclean --block KS=kitchens
check "a short answer is not hidden by chance" NONE 'Tea and scones (3)' AND

written=$(cd "$REPO/tools" && python3 -c '
import letter_facts as l
print(l.written("anagram"), l.written("container + first letter"), l.written("charade"),
      l.stated({"type": "container", "typeCore": True, "inferred": ["type"], "definition": ["d"]}))')
want="('anagram', False) ('container', True) None {'definition': ['d']}"
if [ "$written" = "$want" ]; then echo "ok   a trusted reading is written whole, a core-trusted one as its core, marked"; else
  echo "FAIL written/stated: expected [$want], got [$written]"; fails=$((fails + 1)); fi

# Indicators read off a lexicon of what blogs named in other clues: "holding"
# and "within" are container indicators, "the" a word blogs leave over and never name.
inds=$(cd "$REPO/tools" && python3 -c '
import letter_facts as l
rows = [(f"p{i}", "e", f"Box {w} the key", "BKOEYX", {"type": "container", "definition": ["Box"], "indicators": [w]})
        for i in range(25) for w in ("holding", "within")]
ilex = l.Indicators(rows)
blocks = [["TUTS", "expresses disapproval"], ["ORES", "minerals"]]
def read(clue, **kw):
    return l.infer_indicators(clue, "TUTORESS", {"definition": ["Teacher"], "blocks": blocks, **kw}, ilex)
print(read("Teacher expresses disapproval holding the minerals (8)"),
      read("Teacher expresses disapproval holding the minerals within (8)"),
      read("Teacher expresses disapproval holding strange minerals (8)"),
      read("Teacher expresses disapproval holding the minerals (8)", indicators=["holding"]),
      l.stated({"indicators": ["holding"], "inferred": ["indicators"], "definition": ["d"]}))')
want="['holding'] None None [] {'definition': ['d']}"
if [ "$inds" = "$want" ]; then echo "ok   the one indicator the blocks want is read, not two rivals or an unknown word, and is not the blog's"; else
  echo "FAIL indicators: expected [$want], got [$inds]"; fails=$((fails + 1)); fi

# A definition read off the ones blogs underlined for the same answer: "Teacher"
# for TUTORESS in other clues. The word inside it must be wordplay or one blogs
# leave out of definitions ("for", never inside one), not a free word blogs may
# take in ("strict teacher"). An answer its enumeration says is half the light
# is not read at all.
defs=$(cd "$REPO/tools" && python3 -c '
import letter_facts as l
rows = [(f"p{i}", "e", f"Teacher for {w} (8)", "TUTORESS", {"definition": ["Teacher"]})
        for i, w in enumerate(["minerals", "tests", "ores", "a b", "x", "y"])]
dlex = l.Definitions(rows)
blocks = [["TUTS", "expresses disapproval"], ["ORES", "minerals"]]
def read(clue, **kw):
    return l.infer_definition(clue, "TUTORESS", {"blocks": blocks, **kw}, dlex)
print(read("Teacher expresses disapproval over minerals (8)"),
      read("Teacher for expresses disapproval over minerals (8)", blocks=[]),
      read("Expresses disapproval over minerals, strict teacher (8)", blocks=[]),
      read("Teacher expresses disapproval over minerals (8)", type="double definition"),
      l.infer_definition("Teacher expresses disapproval (8)", "TUTEE", {"blocks": blocks}, dlex),
      read("Teacher expresses disapproval over minerals (8,4)"),
      l.stated({"definition": ["Teacher"], "inferred": ["definition"], "type": "charade"}))')
want="['Teacher'] ['Teacher'] None [] [] [] {'type': 'charade'}"
if [ "$defs" = "$want" ]; then echo "ok   a definition blogs underlined for the answer is read where wordplay or a link word bounds it, and is not the blog's"; else
  echo "FAIL definitions: expected [$want], got [$defs]"; fails=$((fails + 1)); fi

# Blocks a write-up gives in prose (blog_facts.leads): its capitals, from clue
# words blogs read so or that it glosses them with, and fodder where it names
# an anagram. A lead the letters do not bear out, or two splits, is no claim.
fuzzy=$(cd "$REPO/tools" && python3 -c '
import json, letter_facts as l
rows = [(f"p{i}", "e", "Sailor after female gets right changed (3)", "ABFR",
         {"blocks": [["AB", "sailor"], ["F", "female"], ["R", "right"]]}) for i in range(5)]
rows += [("d", "e", "Misrepresent (5)", "BELIE", {"definition": ["Misrepresent"]})]
lex, dlex = l.Lexicon(rows), l.Definitions(rows)
def read(clue, answer, said, **kw):
    got = l.infer_fuzzy_blocks(clue, answer, {"definition": kw.get("d", [])}, lex, dlex, said)
    return None if got is None else sorted(got)
print(read("Misrepresent female intuition (6)", "BELIEF", {"caps": ["BELIE"], "printed": ["Misrepresent female"]}, d=["intuition"]),
      read("Boss blunder right (6)", "GAFFER", {"caps": ["GAFFE", "R"], "near": [["GAFFE", "blunder"]]}, d=["Boss"]),
      read("Boss blunder right (6)", "GAFFER", {"caps": ["GAFFE", "R"]}, d=["Boss"]),
      read("Scene changed after sailor gets leave (7)", "ABSENCE", {"anagram": True, "printed": ["Scene", "sailor"]}, d=["leave"]),
      read("Scene changed after sailor gets leave (7)", "ABSENCE", {"printed": ["Scene", "sailor"]}, d=["leave"]),
      read("Sailor right, right (3)", "ABR", {"caps": ["AB", "R"]}))
print(json.dumps(l.with_blocks({}, [("SCENE", "Scene", "anagrammed")])["blocks"]))')
want="[('BELIE', 'Misrepresent'), ('F', 'female')] [('GAFFE', 'blunder'), ('R', 'right')] [] [('AB', 'sailor'), ('SCENE', 'Scene', 'anagrammed')] [] None
[[\"SCENE\", \"Scene\", \"inferred\", \"anagrammed\"]]"
if [ "$fuzzy" = "$want" ]; then echo "ok   blocks a write-up gives in prose are read where its leads and the letters agree on one split"; else
  echo "FAIL fuzzy blocks: expected [$want], got [$fuzzy]"; fails=$((fails + 1)); fi

[ "$fails" -eq 0 ] && echo "all letter_facts checks passed" || { echo "$fails failed"; exit 1; }
