#!/bin/bash
# Does tools/parse_timesforthetimes.py still read all three eras of the blog?
#
#     bash tools/test_parse_timesforthetimes.sh
#
# The Times withholds its grids, and these records are what one gets rebuilt
# from, so a misread answer becomes a wrong light length and a grid that
# cannot be checked against anything. The blog changed its markup twice in
# twenty years and the old eras write the answer with the wordplay inside it
# — S(L)OUGH, YOR[I+C]K, ANN,ULET=lute*, SWANSON[g] — so each era gets a
# fixture here. They are inline snippets, not cached posts: CI has no cache.
#
# A LINKED clue covers two or more lights under one heading ("10/11") and the
# blog prints its answer once, whole. One entry for it is two mistakes at once
# — a light that is longer than any the grid holds, and a light that is not in
# the list at all — and both read downstream as a blog post with a hole in it.
# Splitting it wrongly is worse than not splitting it: the grid that comes back
# is wrong and looks fine, so every form the blog actually uses is a fixture
# here, and so is every shape that must be refused instead of guessed.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() {  # check <what> <expected> <got>
  if [ "$2" = "$3" ]; then echo "ok   $1"; else
    echo "FAIL $1: expected [$2], got [$3]"; fails=$((fails + 1)); fi
}

run() {  # run <fixture html> -> one "number|direction|answer|enumeration|clue" per line
  REPO="$REPO" python3 - "$1" <<'PY'
import os, sys, json, importlib.util
spec = importlib.util.spec_from_file_location(
    "p", os.path.join(os.environ["REPO"], "tools", "parse_timesforthetimes.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
post = {"id": 1, "date": "2020-01-01T00:00:00", "slug": "times-25184-x",
        "link": "x", "categories": [11], "content": {"rendered": sys.argv[1]}}
rec = mod.parse_post(post)
if rec is None:
    print("NONE")
    sys.exit()
for e in rec["entries"]:
    print("|".join([str(e["number"]), e["direction"], e["answer"],
                    e["enumeration"] or "", e["clue"] or ""]))
for u in rec.get("unsplit", []):
    print("|".join(["UNSPLIT", " ".join(f"{n}{d[0]}" for n, d in u["lights"]),
                    u["answer"], u["enumeration"] or ""]))
PY
}

# The 2025-onwards table: number in its own cell, clue in the next, answer in
# the row below it.
modern='<table><tr><td colspan="2"><strong>Across</strong></td></tr>
<tr><td>1</td><td><span>Christian Conservative caught scoffing at festival (8)</span></td></tr>
<tr><td></td><td><b>CATHOLIC</b> &#8211; C and C containing AT, and HOLI</td></tr>
<tr><td colspan="2"><strong>Down</strong></td></tr>
<tr><td>2</td><td><span>Die, as one might in a casino? (4,2,4,5)</span></td></tr>
<tr><td></td><td><b>CASH IN ONES CHIPS</b> &#8211; two definitions</td></tr></table>'
got="$(run "$modern")"
check "modern table: across clue and answer" \
  "1|across|CATHOLIC|8|Christian Conservative caught scoffing at festival (8)" \
  "$(echo "$got" | sed -n 1p)"
check "modern table: the Down heading switches direction" \
  "2|down|CASHINONESCHIPS|4,2,4,5|Die, as one might in a casino? (4,2,4,5)" \
  "$(echo "$got" | sed -n 2p)"

# The 2017-2024 prose: number and clue on one line, answer on the next, the
# whole entry separated by <br /> rather than by table cells.
prose='<p><b>ACROSS</b></p><p>1 <u>Starter </u>that&#8217;s Spain to a T, somehow (9)<br />
ANTIPASTO &#8211; anagram* of SPAIN TO A T<br />
6 <u>Name </u>of commoner quietly erased by church (5)<br />
CELEB &#8211; [p]LEB follows CE</p>'
got="$(run "$prose")"
check "prose era: the clue keeps its enumeration" \
  "1|across|ANTIPASTO|9|Starter that’s Spain to a T, somehow (9)" \
  "$(echo "$got" | sed -n 1p)"
check "prose era: second entry" \
  "6|across|CELEB|5|Name of commoner quietly erased by church (5)" \
  "$(echo "$got" | sed -n 2p)"

# Pre-2017: no clue text at all, and the answer is printed with the wordplay
# written through it. Every one of these is a real line from the archive.
old='<p><b>Across</b></p><table>
<tr><td>1</td><td>S(L)OUGH &#8211; one of my last in</td></tr>
<tr><td>5</td><td>PRO(CL + AI<s>d</s>)M</td></tr>
<tr><td>9</td><td>GOSSAMER = GOER about MASS rev</td></tr>
<tr><td>10</td><td>RICE,PAPER &#8211; RI(CEP-A)PER</td></tr>
<tr><td>11</td><td>NARCOSIS, anagram of CAR, SON IS</td></tr>
<tr><td>12</td><td>SWANSON[g] &#8211; Ref. Gloria</td></tr>
<tr><td>13</td><td>YOR[I+C]K &#8211; alas!</td></tr>
<tr><td>14</td><td>RAKISH &#8211; KI{ng} inside</td></tr></table>'
got="$(run "$old")"
check "old era: wordplay in brackets is not part of the answer" \
  "S(L)OUGH=SLOUGH PRO(CL+AId)M=PROCLAIM GOSSAMER=GOSSAMER RICE,PAPER=RICEPAPER" \
  "S(L)OUGH=$(echo "$got" | sed -n 1p | cut -d'|' -f3) \
PRO(CL+AId)M=$(echo "$got" | sed -n 2p | cut -d'|' -f3) \
GOSSAMER=$(echo "$got" | sed -n 3p | cut -d'|' -f3) \
RICE,PAPER=$(echo "$got" | sed -n 4p | cut -d'|' -f3)" 2>/dev/null
check "old era: a struck-through letter is deleted, not read" "PROCLAIM" \
  "$(echo "$got" | sed -n 2p | cut -d'|' -f3)"
check "old era: an equals sign ends the answer too" "GOSSAMER" \
  "$(echo "$got" | sed -n 3p | cut -d'|' -f3)"
check "old era: a comma before lower case is wordplay, not a word break" \
  "NARCOSIS" "$(echo "$got" | sed -n 5p | cut -d'|' -f3)"
check "old era: a lower-case deletion in brackets is dropped" "SWANSON" \
  "$(echo "$got" | sed -n 6p | cut -d'|' -f3)"
check "old era: square brackets are wordplay" "YORICK" \
  "$(echo "$got" | sed -n 7p | cut -d'|' -f3)"
check "old era: a braced deletion is dropped" "RAKISH" \
  "$(echo "$got" | sed -n 8p | cut -d'|' -f3)"
check "old era: no clue text, and none invented" "" \
  "$(echo "$got" | sed -n 1p | cut -d'|' -f5)"
check "old era: every entry found" "8" "$(echo "$got" | grep -c .)"

# LINKED CLUES, old era: the head names the lights and the answer is printed
# once, whole. Every separator and suffix below is a real line from the
# archive. A light boundary inside a linked answer is a WORD boundary, so the
# printed words are the slice points: one word per light and the split is
# forced.
linked='<p><b>Across</b></p><table>
<tr><td>10/11</td></tr>
<tr><td>YORKSHIRE DALES = (DRAY-HORSES LIKE)*</td></tr>
<tr><td>16,8</td></tr>
<tr><td>BRUSSELS SPROUTS; BRUSSELS + S.P. + ROUTS</td></tr>
<tr><td>3 &amp; 17</td></tr>
<tr><td>SPIKE MILLIGAN = (I + SPEAKING)* about MILL</td></tr>
<tr><td>18 and 14</td></tr>
<tr><td>BEEF STROGANOFF = (GOT SAFFRON)* after BEEF</td></tr>
<tr><td>6/6dn</td></tr>
<tr><td>GOOSE FLESH</td></tr>
<tr><td>1/29/19dn</td></tr>
<tr><td>GERARD MANLEY HOPKINS; (ONE PHRASING MARKEDLY)*</td></tr></table>'
got="$(run "$linked")"
check "linked: a slash head splits at the word break" \
  "10|across|YORKSHIRE|| 11|across|DALES||" \
  "$(echo "$got" | sed -n 1p) $(echo "$got" | sed -n 2p)"
check "linked: a comma head is the same clue" \
  "16|across|BRUSSELS|| 8|across|SPROUTS||" \
  "$(echo "$got" | sed -n 3p) $(echo "$got" | sed -n 4p)"
check "linked: an ampersand head is the same clue" \
  "3|across|SPIKE|| 17|across|MILLIGAN||" \
  "$(echo "$got" | sed -n 5p) $(echo "$got" | sed -n 6p)"
check "linked: a spelled-out and is the same clue" \
  "18|across|BEEF|| 14|across|STROGANOFF||" \
  "$(echo "$got" | sed -n 7p) $(echo "$got" | sed -n 8p)"
# 6/6dn is two lights, not one written twice: without the suffix a light runs
# in the direction of the heading it was printed under.
check "linked: a direction suffix moves that light to the other direction" \
  "6|across|GOOSE|| 6|down|FLESH||" \
  "$(echo "$got" | sed -n 9p) $(echo "$got" | sed -n 10p)"
check "linked: three lights, three words, one per light" \
  "1|across|GERARD|| 29|across|MANLEY|| 19|down|HOPKINS||" \
  "$(echo "$got" | sed -n 11p) $(echo "$got" | sed -n 12p) $(echo "$got" | sed -n 13p)"
check "linked: no entry is invented beyond the lights the head named" "13" \
  "$(echo "$got" | grep -c .)"

# The corpus's leader form for a split answer: the WHOLE answer's enumeration
# on the light that carries the clue, null on every continuation, and the
# continuation points back with the "See N" the blog itself writes. Anything
# reading a linked answer's count reads it off the leader.
leader='<p><b>Across</b></p><table>
<tr><td>7/10</td><td>for one dirty side&#8217;s outside right (6,8)</td></tr>
<tr><td>VULGAR FRACTION &#8212; VULGAR, &#8220;dirty&#8221; + F(R)ACTION</td></tr></table>'
got="$(run "$leader")"
check "linked: the leader carries the whole enumeration and the clue" \
  "7|across|VULGAR|6,8|for one dirty side’s outside right (6,8)" \
  "$(echo "$got" | sed -n 1p)"
check "linked: the continuation carries null and points back" \
  "10|across|FRACTION||See 7" "$(echo "$got" | sed -n 2p)"

# REFUSALS. The blog does not always say where the light break is, and a wrong
# split reconstructs a wrong grid that nobody can see is wrong. Each of these
# must emit NOTHING for the clue and say so, rather than pick one.
refuse='<p><b>Across</b></p><table>
<tr><td>23, 24</td><td>Is drunk with alcohol, emerge healthier (4,4,2,4,5)</td></tr>
<tr><td>COME HELL OR HIGH WATER &#8211; anagram</td></tr>
<tr><td>4/5</td></tr>
<tr><td>GO SLOWLY</td></tr>
<tr><td>30/48</td><td>Red-suited caller (5,5)</td></tr>
<tr><td>SANT ACLAUS &#8211; anagram</td></tr></table>'
got="$(run "$refuse")"
check "refusal: more words than lights names no break, so none is chosen" \
  "UNSPLIT|23a 24a|COMEHELLORHIGHWATER|4,4,2,4,5" "$(echo "$got" | sed -n 1p)"
# A light of one or two letters is not a light in any of these puzzles, so a
# split that produces one has found a word break that is not a light break.
check "refusal: a piece too short to be a light is not a split" \
  "UNSPLIT|4a 5a|GOSLOWLY|" "$(echo "$got" | sed -n 2p)"
# The enumeration and the answer are read off different lines. When they count
# the same letters into different words, one of them was misread.
check "refusal: enumeration and answer disagreeing about the words" \
  "UNSPLIT|30a 48a|SANTACLAUS|5,5" "$(echo "$got" | sed -n 3p)"
check "refusal: a refused clue puts no entry in the record at all" "0" \
  "$(echo "$got" | grep -vc UNSPLIT || true)"

# A "(= ...)" is the blogger glossing a charade fragment, not the answer
# stopping: "TURN OVER (= 'amount of business') + A NEW LEAF (= '...')" is
# one printed answer of five words, not "TURN OVER" cut short at the '=' its
# own gloss happens to contain. With only two lights named, five words is a
# split the blog does not settle (one word per light is the one case it
# does), so this is a REFUSAL too — but the letters it refuses on have to be
# the whole answer, not a truncated one, or the refusal is hiding the bug
# rather than proving it is fixed. This is the real shape of times.co.uk
# post 11738, clue 12/21.
gloss='<p><b>Across</b></p><table>
<tr><td>12/21</td></tr>
<tr><td>TURN OVER (= &#8216;amount of business&#8217;) + A NEW LEAF (= &#8216;an encouraging sign&#8217;) &#8211; the answer here was clear</td></tr>
<tr><td>18</td><td>FAT (= &#8216;big&#8217;)</td></tr></table>'
got="$(run "$gloss")"
# The plain case this must keep working: nothing follows the gloss, so it IS
# where the answer ends, same as it always has (a bare '=' already ends one).
check "gloss: a '(= ...)' with nothing after it still ends the answer there" \
  "18|across|FAT||" "$(echo "$got" | sed -n 1p)"
check "gloss: a '(= ...)' the answer runs past is not where it truncates" \
  "UNSPLIT|12a 21a|TURNOVERANEWLEAF|" "$(echo "$got" | sed -n 2p)"

# A line can open with numbers and not be a linked head. Fewer words than
# lights cannot be a split answer — a light cannot be part of a word — so this
# is the ordinary clue its first number names, and refusing it would throw
# away a light that was right.
notlinked='<p><b>Across</b></p><table>
<tr><td>4/7 of 19 is a very small amount (4)</td></tr>
<tr><td>IOTA &#8211; The answer to 19 is RIOT ACT</td></tr></table>'
check "not linked: four sevenths of 19 is one clue, not two lights" \
  "4|across|IOTA|4|4/7 of 19 is a very small amount (4)" "$(run "$notlinked")"

# Before the first heading the blogger is writing ABOUT the puzzle. A preamble
# that quotes a linked answer would otherwise file it as a clue, and file it
# under numbers the clue list then contradicts.
preamble='<p>23ac / 24ac CHARACTER ACTORS was the theme.</p>
<p><b>Across</b></p><table>
<tr><td>24</td><td>Thespian to go off (5)</td></tr>
<tr><td>ACTOR &#8211; anagram</td></tr></table>'
check "preamble: a linked answer quoted before the heading is not a clue" \
  "24|across|ACTOR|5|Thespian to go off (5)" "$(run "$preamble")"

# Some bloggers print a linked answer whole under the leader AND again under
# the continuation. The continuation's printing is the exact one, so the
# leader gives those letters back; left alone it is one light four letters too
# long and one light counted twice.
carried='<p><b>Across</b></p><table>
<tr><td>18</td></tr>
<tr><td>See 3 (4)</td></tr>
<tr><td>GEAR &#8211; See explanation at 3 down</td></tr></table>
<p><b>Down</b></p><table>
<tr><td>3</td></tr>
<tr><td>Drunk most of huge gin with a large mug (8)</td></tr>
<tr><td>LAUGHING GEAR &#8211; anagram</td></tr></table>'
got="$(run "$carried")"
check "carried: the continuation keeps its own printing" "18|across|GEAR|4|See 3 (4)" \
  "$(echo "$got" | sed -n 1p)"
check "carried: and the leader gives back the letters it does not hold" \
  "3|down|LAUGHING|8|Drunk most of huge gin with a large mug (8)" \
  "$(echo "$got" | sed -n 2p)"

# One light, one entry: a linked group emits every light it covers, and the
# blogger may have printed one of them on a line of its own as well.
twice='<p><b>Across</b></p><table>
<tr><td>1/5</td></tr>
<tr><td>COSTA BRAVA</td></tr>
<tr><td>5</td></tr>
<tr><td>BRAVA</td></tr></table>'
check "one light, one entry, however many times the blog printed it" "2" \
  "$(run "$twice" | grep -c .)"

# Three ways a light went missing, each one a hole no grid fits. A clue-type
# label is not wordplay, so the answer before it ends there; a dash typed with
# no space after it still ends the answer; and a clue that opens with a time
# is clue text, not the next clue number.
got="$(run '<p>Across</p><p>1</p><p>AIRMAIL (cryptic definition)</p>
<p>5</p><p>CROW’S FEET (2 defs) – nice</p>
<p>9</p><p>SHOW-JUMPERS (1 def, 1 literal interpretation)</p>')"
check "clue-type aside: a cryptic definition" "1|across|AIRMAIL||" "$(echo "$got" | sed -n 1p)"
check "clue-type aside: two defs after a two-word answer" "5|across|CROWSFEET||" \
  "$(echo "$got" | sed -n 2p)"
check "clue-type aside: a hyphenated answer" "9|across|SHOWJUMPERS||" "$(echo "$got" | sed -n 3p)"
check "clue-type aside: an ordinary aside still refuses a restated answer" "" \
  "$(run '<p>Across</p><p>1</p><p>MANNISH M (married) ANN (name of woman)</p>' | grep -v NONE)"
check "dash typed short: 'NISAN -Granny'" "4|across|NISAN|5|Granny is being kept inside for a month (5)" \
  "$(run '<p>Across</p><p>4 Granny is being kept inside for a month (5)<br />NISAN -Granny NAN and IS</p>')"
got="$(run '<p>Across</p><p>15</p><p>5:37, perhaps, is when most are watching? (5,4)</p><p>PRIME TIME</p>')"
check "a clue opening with a time is clue text" \
  "15|across|PRIMETIME|5,4|5:37, perhaps, is when most are watching? (5,4)" "$got"

# ONE NUMBER, ONE LIGHT. A light read twice is a list no grid fits, and each
# of these shapes printed the same number twice from a real post.
# A clue that opens with a number, in the cell after its bare number cell.
got="$(run '<p>Across</p><p>22</p><p>24-hour periods are stunning, reportedly (4)</p><p>DAYS &#8211; sounds like DAZE</p>
<p>24</p><p>Person imitating bird like a thrush (8)</p><p>EMULATOR &#8211; EMU + LATOR</p>')"
check "a clue opening with a number belongs to the bare cell before it" \
  "22|across|DAYS|4|24-hour periods are stunning, reportedly (4)
24|across|EMULATOR|8|Person imitating bird like a thrush (8)" "$got"
# A longer number is not its first two digits: "1066" is not clue 10.
check "a four-digit number is not a clue number" "" \
  "$(run '<p>Across</p><p>1066 and all that</p><p>HAROLD &#8211; x</p>' | grep -v NONE)"
check "a time in the preamble is not clue 1" "" \
  "$(run '<p>10:07 for me.</p><p>TYROL &#8211; my LOI</p><p>Across</p>' | grep -v NONE)"
# A number cell that names its direction is still a bare number cell.
got="$(run '<p>Down</p><p>12d</p><p>Chatted about paradise (13)</p><p>PREDESTINATED &#8211; x</p>
<p>29d</p><p>12 remade Badlands in Arizona (7,6)</p><p>PAINTED DESERT &#8211; x</p>')"
check "a direction-suffixed number cell is bare" \
  "12|down|PREDESTINATED|13|Chatted about paradise (13)
29|down|PAINTEDDESERT|7,6|12 remade Badlands in Arizona (7,6)" "$got"
# Prose under an answer that opens with an answered light's number.
got="$(run '<p>Across</p><p>1</p><p>Boozy yob (5,4)</p><p>LAGER LOUT &#8211; x</p>
<p>12</p><p>Eastern money consumed for legislative body (6)</p><p>SENATE &#8211; SEN ATE</p>
<p>1 SEN = 1/100th of a Japanese yen</p><p>Down</p>')"
check "prose naming an answered light is not that light again" \
  "1|across|LAGERLOUT|5,4|Boozy yob (5,4)
12|across|SENATE|6|Eastern money consumed for legislative body (6)" "$got"
# No Down heading: the Down list is where the numbers restart.
got="$(run '<p>Across</p><p>1 Absorbed (7)<br />ENGROSS &#8211; x</p><p>12 Liquid (9)<br />GLYCERINE &#8211; x</p>
<p>1 Hospitality (12)<br />ENTERTAINING &#8211; x</p>' | cut -d'|' -f1-3)"
check "a post with no Down heading restarts into Down" \
  "1|across|ENGROSS
12|across|GLYCERINE
1|down|ENTERTAINING" "$got"
# ...and a number that only goes backwards is a typo, kept, not refused.
got="$(run '<p>Across</p><p>17 ANTHILL &#8211; x</p><p>28 THE STICKS &#8211; x</p><p>19 OPENING &#8211; x</p>
<p>Down</p><p>1 ABC &#8211; x</p>' | cut -d'|' -f1-3)"
check "a typo'd number does not take the lights after it" \
  "17|across|ANTHILL
28|across|THESTICKS
19|across|OPENING
1|down|ABC" "$got"

# An announcement is not a puzzle. Emitting one would put a post with no
# entries into the output and let it be counted as coverage.
check "a post in no puzzle category is skipped" "NONE" \
  "$(REPO="$REPO" python3 -c '
import os, importlib.util
spec = importlib.util.spec_from_file_location("p", os.path.join(os.environ["REPO"], "tools", "parse_timesforthetimes.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(m.parse_post({"id":1,"date":"2020-01-01","slug":"meetup","categories":[20],"content":{"rendered":"<p>Across</p><p>1 THING &#8211; x</p>"}}) or "NONE")')"

# The enumeration and the answer are read off different lines, so their
# agreement is what catches a misread answer.
check "enumeration disagreement is detected" "False" \
  "$(REPO="$REPO" python3 -c '
import os, importlib.util
spec = importlib.util.spec_from_file_location("p", os.path.join(os.environ["REPO"], "tools", "parse_timesforthetimes.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(m.enum_agrees({"answer": "CAT", "enumeration": "5"}))')"

check "puzzle number comes off the slug" "25184" \
  "$(REPO="$REPO" python3 -c '
import os, importlib.util
spec = importlib.util.spec_from_file_location("p", os.path.join(os.environ["REPO"], "tools", "parse_timesforthetimes.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(m.puzzle_number({"slug": "times-quick-cryptic-25184-by-felix", "title": {"rendered": ""}}))')"

check "a slug WordPress made from the post id defers to the title" "27365 2162" \
  "$(REPO="$REPO" python3 -c '
import os, importlib.util
spec = importlib.util.spec_from_file_location("p", os.path.join(os.environ["REPO"], "tools", "parse_timesforthetimes.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(m.puzzle_number({"id": 50707, "slug": "50707-2", "title": {"rendered": "Times 27,365: Candy"}}),
      m.puzzle_number({"id": 9, "slug": "times-quick-cryptic-no-2162-by-tracy", "title": {"rendered": ""}}))')"

# The category is set by hand; the number moves a misfiled post back, and a
# daily whose title number reads short stays put unless its title says Quick.
check "a misfiled series is corrected by the puzzle number, and only then" \
  "Daily Cryptic|Quick Cryptic|Daily Cryptic|Quick Cryptic" \
  "$(REPO="$REPO" python3 -c '
import os, importlib.util
spec = importlib.util.spec_from_file_location("p", os.path.join(os.environ["REPO"], "tools", "parse_timesforthetimes.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
t = lambda s: {"title": {"rendered": s}}
print("|".join([m.filed_series(t("Times 27,365: Candy"), "Quick Cryptic", 27365),
                m.filed_series(t("Times Quick Cryptic No 2162 by Tracy"), "Daily Cryptic", 2162),
                m.filed_series(t("Times 27,365 is a quick one"), "Daily Cryptic", 365),
                m.filed_series(t("QC 3005 by Wurm"), "Quick Cryptic", 3005)]))')"

# A clue can open with a number of its own, including one that looks like a
# linked head. The row after a bare number cell is that number's clue.
numclue='<table><tr><td><strong>Across</strong></td></tr>
<tr><td>2</td><td>100 rhinos travelling from south-west? (7)</td></tr>
<tr><td></td><td><b>CORNISH</b> &#8211; C(100) + (RHINOS)*</td></tr>
<tr><td>16</td><td>4/7 of 19 is a very small amount (4)</td></tr>
<tr><td></td><td><b>IOTA</b> &#8211; four of RIOT ACT</td></tr></table>'
got="$(run "$numclue")"
check "a clue opening with a number stays with the bare cell before it" \
  "2|across|CORNISH|7|100 rhinos travelling from south-west? (7)" \
  "$(echo "$got" | sed -n 1p)"
check "a clue opening with a fraction is not a linked head" \
  "16|across|IOTA|4|4/7 of 19 is a very small amount (4)" \
  "$(echo "$got" | sed -n 2p)"

# An answer printed with its accents writes bare letters into the grid;
# dropping the accented letter, or the whole answer, loses the light.
accent='<table><tr><td><strong>Across</strong></td></tr>
<tr><td>3</td><td>Stand from beginning of extra time: add time on (7)</td></tr>
<tr><td></td><td><b>ÉTAGÈRE</b> &#8211; a display stand</td></tr></table>'
check "an accented answer is read as its bare letters" \
  "3|across|ETAGERE|7|Stand from beginning of extra time: add time on (7)" \
  "$(run "$accent")"

# A braced deletion with its closing brace mistyped must not run on to the
# next "}" in the post and delete every clue in between.
brace='<table><tr><td><strong>Across</strong></td></tr>
<tr><td>11</td><td>State failure over university essentially buried (8)</td></tr>
<tr><td></td><td><b>MISSOURI</b> &#8211; MISS, O, U, {bu}RI{ed{ [essentially]</td></tr>
<tr><td>12</td><td>Relax earl beset by very painful condition (3,3)</td></tr>
<tr><td></td><td><b>VEG OUT</b> &#8211; E in V GOUT</td></tr>
<tr><td>13</td><td>Writer&#8217;s guild met periodically (4)</td></tr>
<tr><td></td><td><b>GIDE</b> &#8211; G{u}I{l}D {m}E{t}</td></tr></table>'
check "an unclosed brace deletes nothing past its own line" \
  "MISSOURI VEGOUT GIDE" "$(run "$brace" | cut -d'|' -f3 | tr '\n' ' ' | sed 's/ $//')"

# An answer with no dash after it is read off the clue's enumeration: the
# leading words are the answer when their lengths are the enumeration's.
# Mixed case counts only with a dash after it, since wordplay opens with an
# ordinary word too, and a length that disagrees is never an answer.
nodash='<table><tr><td><strong>Across</strong></td></tr>
<tr><td>8</td><td>Case I mixed up, going round information bureaux (8)</td></tr>
<tr><td></td><td>AGENCIES GEN (information) inside an anagram of CASE I</td></tr>
<tr><td>9</td><td>Spy, English &#8212; or Flemish? (4)</td></tr>
<tr><td></td><td>BOND, James Bond</td></tr>
<tr><td>10</td><td>Pair of hacks get a move on! (4,4)</td></tr>
<tr><td></td><td>CHOP CHOP! &#8211; CHOP * 2</td></tr>
<tr><td>11</td><td>This is the end of many inflammatory diseases (3)</td></tr>
<tr><td></td><td>&#8216;TIS -many diseases end in -iTIS</td></tr>
<tr><td>12</td><td>Back winner (8)</td></tr>
<tr><td></td><td>Champion &#8211; double definition</td></tr>
<tr><td>13</td><td>Contrary gardener to come down in a state (8)</td></tr>
<tr><td></td><td>MARY (gardener) LAND (to come down)</td></tr>
<tr><td>14</td><td>Twisted relation (7)</td></tr>
<tr><td></td><td>Anagram of RELATION less one letter</td></tr></table>'
check "an answer with no dash is read off its enumeration, and only then" \
  "8:AGENCIES 9:BOND 10:CHOPCHOP 11:TIS 12:CHAMPION" \
  "$(run "$nodash" | cut -d'|' -f1,3 | tr '|\n' ': ' | sed 's/ $//')"

# The enumeration also cuts wordplay run on with no dash off an answer -- but
# an answer the blogger ended with a dash is theirs, and an enumeration
# disagreeing with it is the typo.
runon='<table><tr><td><strong>Across</strong></td></tr>
<tr><td>5</td><td>Paper attempted with no editor (5)</td></tr>
<tr><td></td><td><b>ESSAY</b>    ESSAY<del>ed</del></td></tr>
<tr><td>11</td><td>Congestion likely here: take train? (5)</td></tr>
<tr><td></td><td>PINCH POINT &#8211; PINCH + POINT</td></tr></table>'
check "run-on wordplay is cut to the enumeration; a dashed answer is kept" \
  "5:ESSAY 11:PINCHPOINT" \
  "$(run "$runon" | cut -d'|' -f1,3 | tr '|\n' ': ' | sed 's/ $//')"

# A clue can open in capitals; it ends in an enumeration those capitals do
# not have the length of, so it is the clue, not the answer. A year in
# brackets is not an enumeration, so an answer before one still counts.
capsclue='<table><tr><td><strong>Across</strong></td></tr>
<tr><td>24</td></tr>
<tr><td>RIP, weightlifter? Sentimental stuff (4-6)</td></tr>
<tr><td><b>TEAR JERKER</b> &#8211; RIP for TEAR, and JERKER</td></tr>
<tr><td>26</td></tr>
<tr><td>SPECIAL &#8211; Hamilton wrote Special Providence (1930)</td></tr></table>'
check "a clue opening in capitals is a clue; a year is no enumeration" \
  "24:TEARJERKER:4-6 26:SPECIAL:" \
  "$(run "$capsclue" | cut -d'|' -f1,3,4 | tr '|\n' ': ' | sed 's/ $//')"

# A full stop ends an answer when a sentence follows it.
stop='<p>ACROSS<br />5. Suggestion less than perfect.<br />IDEA. Less than perfect (IDEA)l.</p>'
check "a full stop before a sentence ends the answer" "IDEA" \
  "$(run "$stop" | cut -d'|' -f3)"

# A number cell with a stray mark in it is still that number; a closed pair
# on its own is an enumeration, not a number.
stray='<table><tr><td><strong>Across</strong></td></tr>
<tr><td>(10</td><td>Plain French, neutral in translation (2,7)</td></tr>
<tr><td></td><td><b>AU NATUREL</b> &#8211; A U + NEUTRAL*</td></tr>
<tr><td>.7</td><td>Long distance runner&#8217;s leg under floor mostly (6)</td></tr>
<tr><td></td><td><b>AMAZON</b> &#8211; ON under MAZ(e)</td></tr>
<tr><td>12</td><td>Fall (4)</td></tr>
<tr><td>(4)</td></tr>
<tr><td></td><td><b>DROP</b> &#8211; double definition</td></tr></table>'
check "a stray mark in a number cell is dropped; a lone (4) is no number" \
  "10:AUNATUREL 7:AMAZON 12:DROP" \
  "$(run "$stray" | cut -d'|' -f1,3 | tr '|\n' ': ' | sed 's/ $//')"

# A clue printed with no number is the one number between its neighbours
# that its direction lacks -- and dropped when there are two, because the
# whole-grid gap may be a different light the blogger left out.
orphan='<table><tr><td><strong>Across</strong></td></tr>
<tr><td>1</td><td>Claim gold&#8217;s fashionable for chair (13)</td></tr>
<tr><td></td><td><b>PROFESSORSHIP</b> &#8211; PROFESS OR&#8217;S HIP</td></tr>
<tr><td></td><td>Eastern, rockier-sounding land (7)</td></tr>
<tr><td></td><td><b>ESTONIA</b> &#8211; E STONIA</td></tr>
<tr><td>9</td><td>Advantage of clipping front of boundary shrubs (4)</td></tr>
<tr><td></td><td><b>EDGE</b> &#8211; hEDGE</td></tr>
<tr><td></td><td>Fish emitted unpleasant odour (5)</td></tr>
<tr><td></td><td><b>SMELT</b> &#8211; double definition</td></tr>
<tr><td>11</td><td>Pinch small duck (5)</td></tr>
<tr><td></td><td><b>STEAL</b> &#8211; S TEAL</td></tr></table>'
check "an unnumbered clue takes the one number it can be, or none" \
  "1:PROFESSORSHIP 9:EDGE 10:SMELT 11:STEAL" \
  "$(run "$orphan" | cut -d'|' -f1,3 | tr '|\n' ': ' | sed 's/ $//')"

if [ "$fails" -gt 0 ]; then echo "$fails FAILURE(S)"; exit 1; fi
echo "all checks passed"
