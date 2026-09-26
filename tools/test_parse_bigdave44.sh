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

[ $fails -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
