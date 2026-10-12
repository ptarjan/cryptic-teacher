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
PY
)
echo "$out" | sed 's/^/     /'
get() { echo "$out" | grep "^$1 " | head -1 | cut -d' ' -f2-; }

check "article text carries no tag remnant" "True" "$(get text-no-markup)"
check "an empty standfirst is no preamble" "None" "$(get empty-standfirst-no-preamble)"
check "the reader keeps both counts on the clue" "Leaves disappear (4,3) (7) | 7" "$(get pair-read)"
check "competition small print and grid notes are cut" "In 11 clues the wordplay produces a letter." "$(get small-print-cut)"
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

[ "$fails" -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
