#!/bin/bash
# Does tools/genius_puzzles.py read an old Guardian article page's text
# without markup, keep the Genius's printed pair of counts, and does the write
# gate refuse a tag's remnant in any string?
#
#     bash tools/test_genius_puzzles.sh
#
# The article reader once began its capture mid-tag, so ` class="dcr-47amn7">`
# (the tag's rest, with no "<" for the tag strip to take) was filed as the
# preamble of 25 puzzles; and enumeration.split() cut "(4,3)" off genius-135's
# "(4,3) (7)" as an echo of the 7. Hand-built inputs, plus a look at those
# filed files.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() {  # check <what> <expected> <got>
  if [ "$2" = "$3" ]; then echo "ok   $1"; else
    echo "FAIL $1: expected [$2], got [$3]"; fails=$((fails + 1)); fi
}

out=$(cd "$REPO" && PYTHONPATH="$REPO/tools" python3 - <<'PY'
import glob, json
import genius_puzzles as G
import enumeration as E
import validate_annotations as V

page = ('<div data-gu-name="standfirst" class="dcr-47amn7"></div>'
        '<aside data-gu-name="meta" class="dcr-1mjlkeb">byline</aside>'
        '<div data-gu-name="body" class="dcr-13wig6c"><p class="dcr-1s160rg">'
        '<strong>Across</strong><br/><strong>1</strong> Leaves disappear (4,3) (7)'
        '<br/><strong>5</strong> Nice art (7)</p></div>'
        '<div data-gu-name="footer">Explore more on these topics</div>')
text = G.article_text(page)
print("text-no-markup", "class=" not in text and "dcr-" not in text)
parsed = G.parse_text(text)
print("empty-standfirst-no-preamble", parsed["preamble"])
print("pair-read", parsed["clues"][0]["clue"], "|", parsed["clues"][0]["enumeration"])

small = G.parse_text("In order to enter the competition, entries must be submitted in the form "
                     "below (including a valid email address). This grid was updated on 4 February "
                     "2015 to correct an error. In 11 clues the wordplay produces a letter. "
                     "Across 1 Clue words here (5)")
print("small-print-cut", small["preamble"])

both = G.parse_text("Fill in the blanks. Across Down 1 Swiss bank (8) 5 Guardian setters (6) "
                    "1 Arm supporter (6) 2 Just a little (9)")
print("headings-together", [(c["lights"][0][0], c["lights"][0][1][0]) for c in both["clues"]])
tail = G.parse_text("Clues ACross Instructions Eight solutions comprise the theme. GENIUS 165 SET BY VLAD "
                    "Down 1 Work for two (3,5) 3 See preamble 4 Open land (4) "
                    "1 See preamble 6 With money (3,2,1,4)")
print("unheaded-run", [(c["lights"][0][0], c["lights"][0][1][0], c["clue"]) for c in tail["clues"]])

print("split-echo", E.split("Set meal (5,1'4) (5,5)"))
print("split-paired", E.split("Leaves disappear (4,3) (7)", paired=True))
print("echoed", E.echoed("Leaves disappear (4,3) (7)"), E.echoed("Words (3) (7)"), E.echoed("Words (7)"))
c = E.clue("Leaves disappear (4,3) (7)", pairedCount=True)
print("clue-paired", c)
print("unsplit-paired", E.unsplit(c, {7}),
      E.unsplit({"text": "Leaves disappear (4,3)", "enumeration": "7"}, {7}))
print("printed-paired", E.printed(c))

for i, s in enumerate(['class="dcr-47amn7">', "dcr-47amn7", '<p>x</p>', "Plain words (4,3)", "a class act"]):
    errs = []
    V.text_errors({"preamble": s}, errs)
    print(f"markup{i}", bool(errs))

bad = [f for f in glob.glob("puzzles/genius/*/genius-*.json")
       if V.MARKUP_RE.search(json.dumps(json.load(open(f)), ensure_ascii=False).replace('\\"', '"'))]
print("corpus-genius-clean", bad)
f = glob.glob("puzzles/genius/*/genius-135.json")
if f:
    e = json.load(open(f[0]))["entries"][0]["clue"]
    print("genius-135-1a", E.printed(e), e.get("pairedCount"))

# Layout faults that held 233 161 162 112 165 76 (2026-10-12).
cl = G.parse_text("Genius No 233 Across 8 Bit of theatre role almost went wrong 9 Outlines injuries, losing time "
                  "10 Amount of drink 11 Article about dancing in the Guardian? 12 Retreats in France from Poles "
                  "All down clues and solutions are normal. All across ones are shifted. Down 1 Upshot mostly (6) 2 Shiner (4)")
print("countless", [(c["lights"][0][0], c["clue"]) for c in cl["clues"][:6]])
print("countless-preamble", cl["preamble"])
lost = G.parse_text("Across 1 Light meat (6) Down 7 I live (4) 8 Dropping belt (4) 2 Amazing half day (10) 13 One taking over (8)")
print("lost-leading-1", [c["lights"][0] for c in lost["clues"]])
stray = G.parse_text("Across 1 Light meat (6) Down 5 Press carpet (6) 19 Feature of brute (8) 7 By one (7) 19 Feature of brute (8) 20 Germany (7)")
print("stray-copy", [c["lights"][0][0] for c in stray["clues"] if c["lights"][0][1] == "down"])
two = G.parse_text("Across 20 Short key (4,4) 22,17,3 Short key, article (6,7) 22,2,5 Overcome a novel (4,4,5) 23 Short book (3)")
print("two-22s", [c["lights"] for c in two["clues"]])
st = G.parse_text("Across 1 See special instructions 10 Make out (9) 26 See special instructions (8) Down 2 One (7)")
print("stub-uncounted", [(c["lights"][0][0], c["clue"]) for c in st["clues"]])
sl = [{"lights": [(12, "across")], "clue": "Heritage (3,8)", "enumeration": "3,8"},
      {"lights": [(2, "down")], "clue": "See 12 across", "enumeration": None},
      {"lights": [(12, "down")], "clue": "Jack (3)", "enumeration": "3"}]
G.see_links(sl)
print("see-way", sl[0]["lights"], sl[2]["lights"])
print("unnumbered", G.unnumbered("Solutions to the remaining clues have their place About this (4,3) Anti pig (7) "
                                 "Art in tears (7) Barren function (4,5) Boy (5)"),
      G.unnumbered("8 Extremely insalubrious (8) 9 Novel (6) 10 Voyeur (13) 11 Story (9) 12 Vehicle (5)"))
for n, want in ((161, None), (162, None), (165, 8)):
    f = glob.glob(f"puzzles/genius/*/genius-{n}.json")
    if f:
        es = json.load(open(f[0]))["entries"]
        print(f"filed-{n}", len(es), sum(bool(e["clue"].get("missing")) for e in es))
PY
)
echo "$out" | sed 's/^/     /'
get() { echo "$out" | grep "^$1 " | head -1 | cut -d' ' -f2-; }

check "article text carries no tag remnant" "True" "$(get text-no-markup)"
check "an empty standfirst is no preamble" "None" "$(get empty-standfirst-no-preamble)"
check "the reader keeps both counts on the clue" "Leaves disappear (4,3) (7) | 7" "$(get pair-read)"
check "competition small print and grid notes are cut" "In 11 clues the wordplay produces a letter." "$(get small-print-cut)"
check "headings printed together: first run is the first heading's" "[(1, 'a'), (5, 'a'), (1, 'd'), (2, 'd')]" "$(get headings-together)"
check "an unheaded run after Down is Across; See preamble is a stub" "[(1, 'd', 'Work for two (3,5)'), (3, 'd', 'See preamble'), (4, 'd', 'Open land (4)'), (1, 'a', 'See preamble'), (6, 'a', 'With money (3,2,1,4)')]" "$(get unheaded-run)"
check "an echo of one total is still cut by default" "('Set meal', '5,5')" "$(get split-echo)"
check "a paired split keeps the first count" "('Leaves disappear (4,3)', '7')" "$(get split-paired)"
check "echoed: same totals only" "True False False" "$(get echoed)"
check "clue() carries pairedCount" "{'text': 'Leaves disappear (4,3)', 'enumeration': '7', 'pairedCount': True}" "$(get clue-paired)"
check "the gate passes a paired count, refuses an unflagged one" "False True" "$(get unsplit-paired)"
check "printed() shows both counts" "Leaves disappear (4,3) (7)" "$(get printed-paired)"
check "a tag remnant is markup" "True" "$(get markup0)"
check "a bare dcr- class is markup" "True" "$(get markup1)"
check "a tag is markup" "True" "$(get markup2)"
check "a count is not markup" "False" "$(get markup3)"
check "the word class is not markup" "False" "$(get markup4)"
check "no filed Genius carries markup" "[]" "$(get corpus-genius-clean)"
check "genius-135 1-across prints (4,3) (7)" "After onset of winter, ordinary leaves disappear (4,3) (7) True" "$(get genius-135-1a)"
check "a list printed without counts is cut at its clue numbers (233)" "[(8, 'Bit of theatre role almost went wrong'), (9, 'Outlines injuries, losing time'), (10, 'Amount of drink'), (11, 'Article about dancing in the Guardian?'), (12, 'Retreats in France from Poles'), (1, 'Upshot mostly (6)')]" "$(get countless)"
check "the prose after a countless list stays the preamble" "All down clues and solutions are normal. All across ones are shifted." "$(get countless-preamble)"
check "a number that lost its leading 1 is mended (161)" "[(1, 'across'), (7, 'down'), (8, 'down'), (12, 'down'), (13, 'down')]" "$(get lost-leading-1)"
check "a stray copy of a later clue is dropped (162)" "[5, 7, 19, 20]" "$(get stray-copy)"
check "two clues headed by one number both read (209)" "[[(20, 'across')], [(22, 'across'), (17, 'across'), (3, 'across')], [(22, 'across'), (2, 'across'), (5, 'across')], [(23, 'across')]]" "$(get two-22s)"
check "See special instructions with no count is a stub; with one, a clue (112, 92)" "[(1, 'See special instructions'), (10, 'Make out (9)'), (26, 'See special instructions (8)'), (2, 'One (7)')]" "$(get stub-uncounted)"
check "See 12 across joins 12 across, not 12 down (162)" "[(12, 'across'), (2, 'down')] [(12, 'down')]" "$(get see-way)"
check "unnumbered clues in the preamble are counted; numbered ones are not (76, 157)" "5 0" "$(get unnumbered)"
[ -z "$(get filed-165)" ] || check "genius-165 files its eight See-preamble lights unclued" "32 8" "$(get filed-165)"

[ "$fails" -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
