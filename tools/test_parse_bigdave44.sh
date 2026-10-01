#!/bin/bash
# Does tools/parse_bigdave44.py read each era of the blog, and date and byline
# each puzzle only from what its posts prove?
#
#     bash tools/test_parse_bigdave44.sh
#
# A misread answer is a wrong light length and so a wrong grid, a blogger read
# as the setter puts the wrong name on a puzzle, and a review's post date is a
# week after the paper printed it. The fixtures are hand-built posts, so
# nothing here reads the cache.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() {  # check <what> <expected> <got>
  if [ "$2" = "$3" ]; then echo "ok   $1"; else
    echo "FAIL $1: expected [$2], got [$3]"; fails=$((fails + 1)); fi
}

out=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
import datetime
import parse_bigdave44 as B

def post(pid, title, body, date="2026-09-25T09:00:00", cats=(6, 43)):
    return {"id": pid, "date": date, "slug": f"p{pid}", "link": f"https://bigdave44.com/p{pid}",
            "title": {"rendered": title}, "content": {"rendered": body}, "categories": list(cats)}

CATS = {1373: {"name": "Dada", "parent": 11}, 7654: {"name": "Zandio (Sunday)", "parent": 7625},
        43: {"name": "DT Cryptic Crosswords", "parent": 6}}
show = lambda es: " ".join(f"{e['number']}{e['direction'][0]}={e['answer']}" for e in es)

# 2020s: the answer in a button span, the heading bold.
modern = post(1, "DT 31354", """
<h2>Daily Telegraph Cryptic No 31354</h2><h2>Hints and tips by Mr K</h2>
<p><strong>Across</strong></p>
<p><strong>1a</strong> &nbsp; First lick of paint on great <span class="dls">building</span> (6)<br />
<span class="km2" title="Answer"><span class="hc"> PREFAB</span></span>: Link together</p>
<p><strong>15a</strong> &nbsp; Old US president backing Farage? (5,7)<br />
<span class="km2"><span class="hc"> NIGEL KENNEDY</span></span>: A 1960s US president</p>
<p><strong>Down</strong></p>
<p><strong>2d</strong> &nbsp; Rotten apple (4)<br /><span class="hc"> BADE</span>: no</p>""")
p = B.read_post(modern, CATS)
print("MODERN", p["series"], p["number"], show(p["entries"]), p["setter"])
print("CLUE", p["entries"][0]["clue"], "|", p["entries"][1]["enumeration"])

# Until ~2015: white text in braces, "Across Clues", and no Down heading.
braced = post(2, "DT 26869", """
<p><strong>Across Clues</strong></p>
<p>9a  Fragrance brought about by glamor (5)<br />
{<span style="color: #ffffff;">AROMA</span>} &#8211; hidden backwards</p>
<p>1d  Firm has obligation (7)<br />
{ <span style="color: #ffffff;">COTERIE</span> } &#8211; string together</p>""", date="2012-01-05T11:00:00")
print("BRACED", show(B.read_post(braced, CATS)["entries"]))

# The Toughie's heading names the setter; the blogger's line never does.
tough = post(3, "Toughie 2717", """<p>Toughie No 2717 by Robyn</p><p>Hints and tips by Miffypops</p>
<p>Across</p><p>1a Spotting little upper-class man (11)<br/>UNOBSERVANT: A charade</p>""")
print("BYLINE", B.read_post(tough, CATS)["setter"])
print("CATEGORY", B.read_post(post(4, "Toughie 3762", "<p>Across</p>", cats=(6, 43, 11, 1373)), CATS)["setter"],
      B.read_post(post(5, "Sunday Toughie 241 (full review)", "<p>x</p>", cats=(6, 7625, 7654)), CATS)["setter"])
titled = post(7, "Toughie 2257", """<p>Toughie No 2257</p><p>Double, double toil and trouble by Firefly</p>
<p>Hints and tips by 2Kiwis</p><p>Across</p>""")
review = post(8, "ST 2500", """<p>Sunday Telegraph Cryptic No 2500</p><p>A full analysis by Peter Biddlecombe</p>""")
print("TITLED", B.read_post(titled, CATS)["setter"], B.read_post(review, CATS)["setter"])
typo = post(9, "DT 28148", """<p><strong>Down</strong></p><p>21d   <u>Equipment</u> &amp;npsp;<u>belt</u>? (7)<br />
<span class="hc">CLOBBER</span>: two definitions</p>""")
# The count typed wrong, (7,6) over CONSOLE TABLE: the letters-only answer
# has lost the break, so the printed form rides along for the filer's recount.
miscounted = post(10, "DT 30927", """<p><strong>Across</strong></p>
<p><strong>1a</strong> Furniture piece at home, in charge (7,6)<br />
<span class="hc">CONSOLE TABLE</span>: a charade</p>
<p><strong>9a</strong> Meal cut short (3)<br /><span class="hc">TEA</span>: no</p>""")
es = B.read_post(miscounted, CATS)["entries"]
print("SPACED", *(f"{e['answer']}/{e.get('answer_spaced')}" for e in es))
import file_blog_puzzles as F
lights = {"a": {"solution": "CONSOLE"}, "b": {"solution": "TABLE"}, "c": {"solution": "CONSOLETABLE"}}
print("RECOUNT", F.from_answer(["c"], lights, "7,6", "CONSOLE TABLE"),
      F.from_answer(["c"], lights, "7,6"), F.from_answer(["c"], lights, "7,6", "CONSOLE TABLES"),
      F.from_answer(["a", "b"], lights, "12", "CON-SOLE TABLE"))
# ONETRACK MIND printed, (9,4) typed: the blog lost the hyphen, and its right
# count over the same answer in other puzzles is the paper's.
typed = F.typed_counts([{"entries": [{"answer": "ONETRACKMIND", "enumeration": e}
                                     for e in ("3-5,4", "3-5, 4", "9,4", "8,4")]}])
one = {"x": {"solution": "ONETRACKMIND"}}
print("TYPED", F.from_answer(["x"], one, "9,4", "ONETRACK MIND", typed),
      F.from_answer(["x"], one, "9,4", "ONETRACK MIND"))
# A bare clue number before a clue whose first word is "A": "1 A" is no
# across suffix, while a spaced lowercase "9 a.", a glued "11ac." and a
# "3dFares" typed with no space are.
bare = post(11, "Toughie 3589", """<p><strong>Across</strong></p>
<p>1 A moral purge modified indoor pastime (7,4)<br/><span class="hc">PARLOUR GAME</span>: anagram</p>
<p>9 a. Forbid chaotic vote (4)<br/><span class="hc">VETO</span>: anagram</p>
<p>11ac. Draw attention to showy plant (4)<br/><span class="hc">FLAG</span>: double</p>
<p><strong>Down</strong></p>
<p>2 A line initially sprinted over too (4)<br/><span class="hc">ALSO</span>: charade</p>
<p>3dFares going up on flights? (10)<br/><span class="hc">PASSENGERS</span>: cd</p>""")
print("BARE_A", " | ".join(f"{e['number']}{e['direction'][0]} {e['clue']}" for e in B.read_post(bare, CATS)["entries"]))
print("NPSP", B.read_post(typo, CATS)["entries"][0]["clue"])
print("BLOGGER", B.read_post(post(6, "DT 31000", "<p>Hints and tips by Deep Threat</p>"), CATS)["setter"])
print("SERIES", *(B.series_and_number(post(0, t, ""), "")[0] for t in (
    "DT 31349 (Full Review)", "Toughie 3762", "ST 3385", "Sunday Toughie 242 (Hints)", "EV 700 (Solution)")))

# A prize puzzle: hints on the Sunday with no answers, the review days later.
hints = post(7, "ST 3385 (Hints)", "<p>Across</p><p>1a Clue (5)</p><p>A hint</p>",
             date="2026-09-20T10:00:00")
review = post(8, "ST 3385 (Full Review)", """<p>Sunday Telegraph Cryptic No 3385</p>
<p>A full review by Rahmat Ali</p><p>This puzzle was published on 20<sup>th</sup> September 2026</p>
<p>Across</p><p>1a Clue (5)<br/>HELLO: yes</p>""", date="2026-09-24T09:00:00")
late = post(9, "ST 3386 (Full Review)", "<p>Review by X</p><p>Across</p><p>1a Clue (5)<br/>HELLO: yes</p>",
            date="2026-10-01T09:00:00")
recs = {(r["series"], r["number"]): r for r in B.records([B.read_post(q, CATS) for q in (hints, review, late)])}
st = recs[("sundaytel", 3385)]
print("GROUPED", len(recs), st["post_id"], st["printed"])
print("REVIEW_UNDATED", recs[("sundaytel", 3386)]["printed"])
print("STATED", B.read_post(review, CATS)["published"])
print("WRONG_DAY", B.print_date("sundaytel", [dict(B.read_post(hints, CATS), date="2026-09-24")])[0])

# A blogger's note after the enumeration is cut off; a count inside the
# clue that is a cross-reference stays.
for c in ("Dismissal is memory associated with cricket ground (7) Revised on-line clue: Getting rid of pop group at front of Underground station",
          "Food from abroad cooked by exotic baker with book (5,5) [online clue] Dark bone possibly linked to black food from East (5,5) [paper clue]",
          "Whitish heraldic stripe (4) (paper version)",
          "Jogger to step into ground (4-2,4) [not (7,4) as published]",
          "Tab made from tobacco, untipped (7) –",
          "Bird with yellow part, one concealed (6) Clue revised online to “Bird with round part...\" as the original...",
          "Here we go again! (4,4) Here we go again! (4,4)",
          "Son (10) enthralled by foreign song — he did this? (8)",
          "First lick of paint on great building (6)"):
    print("NOTE", B.note_cut(c))
noted = post(12, "DT 27398", """<p><strong>Across</strong></p>
<p><strong>1a</strong> Whitish heraldic stripe (4) (paper version)<br /><span class="hc">PALE</span>: no</p>""")
print("NOTED", *(f"{e['clue']}|{e['enumeration']}" for e in B.read_post(noted, CATS)["entries"]))

D = datetime.date
print("CADENCE", B.by_cadence("telegraph", {100: D(2026, 9, 18), 101: None, 102: D(2026, 9, 21)}).get(101))
print("CADENCE_SHORT", B.by_cadence("telegraph", {100: D(2026, 9, 18), 101: None, 102: D(2026, 9, 19)}))
print("CADENCE_WEEKS", sorted(B.by_cadence("sundaytel", {1: D(2026, 9, 6), 4: D(2026, 9, 27)}).items()))
PY
)
echo "$out" | grep -v "^[A-Z_]* " | sed 's/^/  | /'
got() { echo "$out" | grep "^$1 " | cut -d' ' -f2-; }

check "a modern post: series, number, answers with their lengths, no setter" \
  "telegraph 31354 1a=PREFAB 15a=NIGELKENNEDY 2d=BADE None" "$(got MODERN)"
check "the clue keeps its text and enumeration" \
  "First lick of paint on great building (6) | 5,7" "$(got CLUE)"
check "a braced white-on-white answer is read; the suffix gives the direction" \
  "9a=AROMA 1d=COTERIE" "$(got BRACED)"
check "the Toughie heading's byline is the setter" "Robyn" "$(got BYLINE)"
check "a setter category names the setter" "Dada Zandio" "$(got CATEGORY)"
check "the blogger is never the setter" "None" "$(got BLOGGER)"
check "a bare Toughie heading's next line bylines it; an analysis line never does" \
  "Firefly None" "$(got TITLED)"
check "a bare number then \"A ...\" keeps the A; spaced lowercase and "ac" suffixes still direct" \
  "1a A moral purge modified indoor pastime (7,4) | 9a Forbid chaotic vote (4) | 11a Draw attention to showy plant (4) | 2d A line initially sprinted over too (4) | 3d Fares going up on flights? (10)" \
  "$(got BARE_A)"
check "the blog's &npsp; typo is a space, not text" "Equipment belt? (7)" "$(got NPSP)"
check "the printed answer's word breaks ride along; the letters-only answer is unchanged" \
  "CONSOLETABLE/CONSOLE TABLE TEA/None" "$(got SPACED)"
check "the recount takes the printed breaks, and falls back when they are absent or wrong" \
  "7,5 None None 3-4,5" "$(got RECOUNT)"
check "a count typed right elsewhere over the same answer beats the printed breaks" \
  "3-5,4 8,4" "$(got TYPED)"
check "the title names the series; EV is none of ours" \
  "telegraph toughie sundaytel sundaytough None" "$(got SERIES)"
check "hints and review are one puzzle, the review's list, the stated date" \
  "2 8 2026-09-20" "$(got GROUPED)"
check "a review alone is undated" "None" "$(got REVIEW_UNDATED)"
check "the review's published-on line is read" "2026-09-20" "$(got STATED)"
check "a Sunday paper's post on a Thursday dates nothing" "None" "$(got WRONG_DAY)"
check "Saturday between Friday and Monday" "2026-09-19" "$(got CADENCE)"
check "too few print days between dates nothing" "{}" "$(got CADENCE_SHORT)"
check "weekly numbers between two Sundays take the Sundays" \
  "[(2, datetime.date(2026, 9, 13)), (3, datetime.date(2026, 9, 20))]" "$(got CADENCE_WEEKS)"
check "a blogger's note after the enumeration is cut; a cross-reference count stays" \
"('Dismissal is memory associated with cricket ground (7)', '7')
('Food from abroad cooked by exotic baker with book (5,5)', '5,5')
('Whitish heraldic stripe (4)', '4')
('Jogger to step into ground (4-2,4)', '4-2,4')
('Tab made from tobacco, untipped (7)', '7')
('Bird with yellow part, one concealed (6)', '6')
('Here we go again! (4,4)', '4,4')
None
None" "$(got NOTE)"
check "the parser stores the clue cut at its enumeration" \
  "Whitish heraldic stripe (4)|4" "$(got NOTED)"

[ $fails -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
