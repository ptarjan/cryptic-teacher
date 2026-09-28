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
check "an answer spelt both ways in one run is read forward, taking no reversal" "hidden word" \
  'Mate getting into top position (4)' OPPO
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

# Our annotations are a second source of indicators, but a clue never
# confirms itself: its own annotation is taken out of the lexicon it is read with.
ours=$(cd "$REPO/tools" && python3 -c '
import letter_facts as l
clue = "Teacher expresses disapproval holding the minerals (8)"
facts = {"type": "container", "definition": ["Teacher"], "indicators": ["holding"],
         "blocks": [["TUTS", "expresses disapproval"], ["ORES", "minerals"]]}
own = ("q", "e", clue, "TUTORESS", facts)
box = lambda w, n: [(f"{w}{i}", "e", f"Box {w} the key", "BKOEYX",
                     {"type": "container", "definition": ["Box"], "indicators": [w]}) for i in range(n)]
blogs = box("within", 25)  # "the", left over in all of them and never named, is a link word
read = lambda ilex: l.infer_indicators(clue, "TUTORESS", {k: v for k, v in facts.items() if k != "indicators"}, ilex)
print(read(l.Indicators(blogs, extra=box("holding", l.MIN_INDICATOR) + [own])),
      read(l.Indicators(blogs, extra=box("holding", l.MIN_INDICATOR - 1) + [own])),
      read(l.Indicators(blogs + box("holding", l.MIN_INDICATOR - 1) + [own])))')
want="['holding'] None ['holding']"
if [ "$ours" = "$want" ]; then echo "ok   our annotations add indicators, never a clue's own"; else
  echo "FAIL annotations as indicators: expected [$want], got [$ours]"; fails=$((fails + 1)); fi

# Our annotations are a second source of the published block lexicon ("zorp" read as AB).
ours=$(cd "$REPO/tools" && python3 -c '
import letter_facts as l
zorp = lambda n: [(f"z{i}", "e", "Zorp here (3)", "ABX", {"blocks": [["AB", "zorp"]]}) for i in range(n)]
print(l.Lexicon([], extra=zorp(l.MIN_SEEN)).spellings(("ZORP",)), l.Lexicon(zorp(1), extra=zorp(l.MIN_SEEN - 2)).spellings(("ZORP",)))')
want="{'AB'} set()"
if [ "$ours" = "$want" ]; then echo "ok   our annotations add readings to the block lexicon"; else
  echo "FAIL annotations as blocks: expected [$want], got [$ours]"; fails=$((fails + 1)); fi

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

# A word beside a new block that blogs take into blocks now and then ("in",
# 10% of the time) is left out of it where it ends one seldom and the words
# with it read as nothing; one they take in 30% of the time stops the claim.
# Fodder in two pieces with a word between is anagrammed as one, side by side
# it is one piece, so the two are no reading.
edges=$(cd "$REPO/tools" && python3 -c '
import letter_facts as l
rows = [(f"p{i}", "e", "Mistake blunder (5)", "GAFFE", {"blocks": [["GAFFE", "blunder"]]}) for i in range(5)]
lex, dlex = l.Lexicon(rows), l.Definitions(rows)
said = {"caps": ["GAFFE", "R"]}
def read(edge):
    lex.edge = {("L", "IN"): edge}
    return l.infer_fuzzy_blocks("Boss in blunder right (6)", "GAFFER", {"definition": ["Boss"]}, lex, dlex, said)
anagram = {"anagram": True, "printed": ["arena", "band"]}
def fodder(clue):
    lex.edge = {("L", "WITH"): [0, 50], ("R", "PLAYING"): [0, 50]}
    return l.infer_fuzzy_blocks(clue, "NAANBREAD", {"definition": ["Indian side"], "blocks": [["ARENA", "arena", "anagrammed"]]},
                                lex, dlex, anagram)
print(read([10, 90]), read([30, 70]), fodder("Indian side in arena with band playing (4,5)"),
      fodder("Indian side in arena band playing (4,5)"))')
want="[('GAFFE', 'blunder'), ('R', 'right')] None [('BAND', 'band', 'anagrammed')] []"
if [ "$edges" = "$want" ]; then echo "ok   a word blogs seldom take into a block is left out of it, and fodder apart in the clue is anagrammed as one"; else
  echo "FAIL edges and fodder: expected [$want], got [$edges]"; fails=$((fails + 1)); fi

# A hidden word's block is its carrier, the one run of words outside the
# definition that spells it (backwards for a reversal, or for a "hidden word"
# not spelt forward), and it wants an
# indicator for the hiding. A clue is complete with a definition, full blocks
# and the indicators they want, none for a charade, and a double definition
# with its two halves.
blockless=$(cd "$REPO/tools" && python3 -c '
import letter_facts as l
h = {"type": "hidden word", "definition": ["Bird"]}
carrier = l.infer_carrier("Bird spotted in Leatherhead (4)", "RHEA", h)
print(carrier, l.infer_carrier("Bird spotted in Leatherhead (4)", "RHEA", {**h, "type": "hidden word + reversal"}),
      l.infer_carrier("Bird in Leatherhead or Leatherhead (4)", "RHEA", h), l.needed("RHEA", carrier),
      l.infer_carrier("Ruler rejects any dubious packages from the East (6)", "DYNAST", {"type": "hidden word"}))
blocks = {"blocks": [[*carrier[0], "inferred"]]}
print(l.complete("RHEA", {**h, **blocks}), l.complete("RHEA", {**h, **blocks, "indicators": ["spotted in"]}),
      l.complete("TIRE", {"type": "double definition", "definition": ["Tire", "wheel cover"]}),
      l.complete("CUBA", {"definition": ["island"], "blocks": [["CUB", "Baby animal"], ["A", "a"]]}))')
want="[('RHEA', 'Leatherhead')] [] [] {'hidden'} [('DYNAST', 'rejects any dubious')]
False True True True"
if [ "$blockless" = "$want" ]; then echo "ok   a hidden word's carrier is read where one run spells it, and a clue is complete with the parts its kind has"; else
  echo "FAIL block-less types: expected [$want], got [$blockless]"; fails=$((fails + 1)); fi

# A forward hidden word, an anagram or a container the lexicon reads no
# indicator for takes the free words, one run, less an end word blogs leave
# out and a closing "'s"; not where blogs both
# take it in and leave it out, nor where the free words are not one run.
hiding=$(cd "$REPO/tools" && python3 -c '
import letter_facts as l
class Ilex:
    def __init__(s, sides): s.sides = sides
    def side(s, side, w): return s.sides.get((side, w), True)
def run(clue, carrier, sides):
    body, ws, at = l.spans(clue)
    taken = l.locate("Region", ws) | l.locate(carrier, ws)
    return l.free_words_indicator(ws, at, body, taken, Ilex(sides))
print(run("Region situated in Far East (4)", "Far East", {("R", "IN"): False}),
      run("Region situated in Far East (4)", "Far East", {("R", "IN"): None}),
      run("Region situated in Far East today (4)", "Far East", {}),
      run("Region criminal’s Far East (4)", "Far East", {}))')
want="['situated'] None None ['criminal']"
if [ "$hiding" = "$want" ]; then echo "ok   a one-part clue's indicator is its free words, one run, less the end words blogs leave out"; else
  echo "FAIL hiding run: expected [$want], got [$hiding]"; fails=$((fails + 1)); fi

# A homophone's or a spoonerism's block is the blog's, heard: the words it
# gives for the clue words, kept as soundsLike (blog_facts.heard_blocks), where
# they sound like the whole answer, or swapped, like a spoonerism's parts, and
# from the clue word before them too where that is the first word heard.
# Such a clue wants that part's indicator, and with it and a definition is complete.
heard=$(cd "$REPO/tools" && python3 -c '
import blog_facts as b, letter_facts as l
tun = b.heard_blocks("homophone", [["TUN", "beer cask"]], "TON")
spoon = b.heard_blocks("spoonerism", [["COARSE", "common"], ["MODE", "kind"]], "MORSECODE")
print(tun, spoon)
print(b.heard_blocks("homophone", [["A RIVAL", "competitor"]], "ARRIVAL", "We’re told a competitor’s coming"))
print(b.heard_blocks("homophone", [["UP", "getting out of bed"]], "TEEUP"),
      b.heard_blocks("homophone", [["ARSE", "bottom"]], "ARSIS"), b.heard_blocks("charade", [["TUN", "x"]], "TON"))
h = {"type": "homophone", "definition": ["Heavyweight"], "blocks": tun}
print(l.coverage("TON", h), l.needed("TON", tun, "homophone"), l.needed("MORSECODE", spoon, "spoonerism"),
      l.complete("TON", h), l.complete("TON", {**h, "indicators": ["by the sound of it"]}))')
want="[['TON', 'beer cask', {'soundsLike': 'TUN'}]] [['MORSE', 'common', {'soundsLike': 'COARSE'}], ['CODE', 'kind', {'soundsLike': 'MODE'}]]
[['ARRIVAL', 'a competitor', {'soundsLike': 'A RIVAL'}]]
[['UP', 'getting out of bed']] [['ARSE', 'bottom']] [['TUN', 'x']]
full {'homophone'} {'spoonerism'} False True"
if [ "$heard" = "$want" ]; then echo "ok   a homophone's and a spoonerism's blocks are heard where they sound like the answer, and want their indicator"; else
  echo "FAIL heard blocks: expected [$want], got [$heard]"; fails=$((fails + 1)); fi

# An anagram the blog gave no blocks has the fodder the letters read for its
# block, as blogs write it (its letters, not the answer's); untyped, none. A
# piece read only as the clue's own answer less a letter (LUMBAGO from "Lead",
# underlined for PLUMBAGO) is the definition the blog left out, so no claim.
own=$(cd "$REPO/tools" && python3 -c '
import letter_facts as l
clue = "Men on phone exchange will be a rarity"
print(l.infer_fodder(clue, "PHENOMENON", {"type": "anagram", "definition": ["a rarity"]}, {}),
      l.infer_fodder(clue, "PHENOMENON", {"definition": ["a rarity"]}, {}))
rows = [("d", "e", "Lead (8)", "PLUMBAGO", {"definition": ["Lead"]})]
lex, dlex = l.Lexicon(rows), l.Definitions(rows)
lex.edge = {(side, w): [0, 50] for side in "LR" for w in ("WITH", "ON")}
said = {"caps": ["LUMBAGO", "P"]}
print(l.infer_fuzzy_blocks("Lead with pressure on bad back (8)", "PLUMBAGO", {}, lex, dlex, said),
      sorted(l.infer_fuzzy_blocks("Lead with pressure on bad back (8)", "PLUMBAGO", {}, lex, l.Definitions([]),
                                  {"caps": ["LUMBAGO", "P"], "near": [["LUMBAGO", "Lead"]]})))')
want="[('MEN ON PHONE', 'Men on phone', 'anagrammed')] []
None [('LUMBAGO', 'Lead'), ('P', 'pressure')]"
if [ "$own" = "$want" ]; then echo "ok   an anagram with no blocks gets its fodder, and a clue's own answer is not read from its definition"; else
  echo "FAIL fodder and own answer: expected [$want], got [$own]"; fails=$((fails + 1)); fi

# Clue words the write-up prints in capitals, with the answer's letters but
# neither in a row nor reversed, are anagram fodder though it names no anagram.
caps=$(cd "$REPO/tools" && python3 -c '
import letter_facts as l
lex, dlex = l.Lexicon([]), l.Definitions([])
lex.edge = {("R", "WRECKED"): [0, 50], ("R", "TURNING"): [0, 50]}
print(l.infer_fuzzy_blocks("Great Dane wrecked open-air restaurant (3,6)", "TEAGARDEN", {"definition": ["open-air restaurant"]},
                           lex, dlex, {"caps": ["GREATDANE"], "printed": ["Great Dane"]}),
      l.infer_fuzzy_blocks("Ivan turning up (4)", "NAVI", {}, lex, dlex, {"caps": ["IVAN"], "printed": ["Ivan"]}))')
want="[('GREATDANE', 'Great Dane', 'anagrammed')] []"
if [ "$caps" = "$want" ]; then echo "ok   fodder printed in capitals is an anagram's, a reversal's is not"; else
  echo "FAIL fodder in capitals: expected [$want], got [$caps]"; fails=$((fails + 1)); fi

[ "$fails" -eq 0 ] && echo "all letter_facts checks passed" || { echo "$fails failed"; exit 1; }
