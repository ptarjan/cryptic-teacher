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

if [ "$fails" -gt 0 ]; then echo "$fails FAILURE(S)"; exit 1; fi
echo "all checks passed"
