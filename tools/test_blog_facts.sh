#!/bin/bash
# Does tools/blog_facts.py read only what a write-up's markup states?
#
#     bash tools/test_blog_facts.sh
#
# Each fixture is one blog's house style, inline, because CI has no cache. The
# facts become hints on the site, so the refusals matter as much as the reads:
# an underline that cuts into a word, a hedged type, brackets on a post whose
# key says they hold glosses, two spans that are not a double definition.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() {  # check <what> <expected> <got>
  if [ "$2" = "$3" ]; then echo "ok   $1"; else
    echo "FAIL $1: expected [$2], got [$3]"; fails=$((fails + 1)); fi
}

facts() {  # facts <blog> <clue> <html> <answer> -> the published facts of that one clue, as JSON
  REPO="$REPO" python3 - "$1" "$2" "$3" "$4" <<'PY'
import json, os, sys
sys.path.insert(0, os.path.join(os.environ["REPO"], "tools"))
import blog_facts as bf
blog, clue, html, answer = sys.argv[1:]
entries = [("1-across", bf.clue_body(clue), answer)]
got = bf.facts_for_post(blog, entries, {"content": html}).get("1-across")
print(json.dumps(bf.publishable(got), sort_keys=True, ensure_ascii=False) if got else "NONE")
PY
}

# fifteensquared: the clue in blue with the definition underlined, then the explanation.
FS='<table><tr><td>9</td><td><b>SARI</b></td><td><font color="blue"><u>Cloth</u> sample in Mombasa rickshaw (4)</font><br />Hidden in mombaSA Rickshaw</td></tr>
<tr><td>10</td><td><b>HAMMERTOE</b></td><td><font color="blue"><u>Digital discomfort</u> caused as actor pressed remote (9)</font><br />HAM (actor) + REMOTE*</td></tr></table>'
check "fifteensquared definition and hidden type" \
  '{"definition": ["Cloth"], "type": "hidden word"}' \
  "$(facts fifteensquared 'Cloth sample in Mombasa rickshaw (4)' "$FS" SARI)"
check "a star and a plus spell the answer: anagram + charade, the block sourced" \
  '{"blocks": [["HAM", "actor"]], "definition": ["Digital discomfort"], "type": "charade + anagram"}' \
  "$(facts fifteensquared 'Digital discomfort caused as actor pressed remote (9)' "$FS" HAMMERTOE)"

# Two underlines with only a space between them are two spans.
DD='<p>3 <u>Consequence</u> of <u>lob</u>? (6)<br/>Double definition</p>'
check "double definition keeps both halves" \
  '{"definition": ["Consequence", "lob"], "type": "double definition"}' \
  "$(facts fifteensquared 'Consequence of lob? (6)' "$DD" UPSHOT)"
SPLIT='<p>3 <u>Consequence</u> of <u>lob</u>? (6)<br/>UP + SHOT</p>'
check "two spans that are not a double definition ship no definition" \
  '{}' "$(facts fifteensquared 'Consequence of lob? (6)' "$SPLIT" UPSHOT)"

check "an underline cutting into a word is refused" \
  'NONE' "$(facts fifteensquared 'Cloth sample (4)' '<p>C<u>loth</u> sample (4)<br/>x</p>' SARI | sed 's/{}/NONE/')"
check "a hedged type is not a type" \
  '{"definition": ["Sack"]}' \
  "$(facts fifteensquared 'Sack one likely to get fired (5)' '<p><u>Sack</u> one likely to get fired (5)<br/>RIFLE: almost a double definition</p>' RIFLE)"

# timesforthetimes: brackets are indicators only where the post's key says so.
KEY='<p>definitions underlined, [anagrinds, containment, reversal and other indicators in square ones]</p>'
TT='<tr><td>6</td><td><span><i><b><u>Pick</u></b></i> brief lecture arranged during afternoon (8)</span></td></tr>
<tr><td></td><td><b>PLECTRUM</b></td></tr><tr><td></td><td>Anagram [arranged] of LECTUR{e} [brief] contained by [during] PM (afternoon)</td></tr>'
check "timesforthetimes bracketed indicators under the key, a spelled compound type" \
  '{"blocks": [["LECTUR", "lecture"], ["PM", "afternoon"]], "definition": ["Pick"], "indicators": ["arranged", "brief", "during"], "type": "anagram + container + deletion"}' \
  "$(facts timesforthetimes 'Pick brief lecture arranged during afternoon (8)' "$KEY$TT" PLECTRUM)"
check "no key: a bracket after an operation or a cut names its indicator, never a source" \
  '{"blocks": [["LECTUR", "lecture"], ["PM", "afternoon"]], "definition": ["Pick"], "indicators": ["arranged", "during", "brief"], "type": "anagram + container + deletion"}' \
  "$(facts timesforthetimes 'Pick brief lecture arranged during afternoon (8)' "$TT" PLECTRUM)"

# bigdave44: indicators in italics inside parentheses, answer in a spoiler.
BD='<p>1a <u>Oscar</u> and Maya wed recklessly after entering a club? (7,5)<br />
<span class="spoiler">ACADEMY AWARD</span>: An anagram (<em>recklessly</em>) of MAYA WED</p>
<p>10a Match over, <span style="text-decoration: underline;">get visibly elated</span> (5,2)<br/>LIGHT UP</p>'
check "a named anagram whose fodder does not hold the answer is not typed" \
  '{"definition": ["Oscar"], "indicators": ["recklessly"]}' \
  "$(facts bigdave44 'Oscar and Maya wed recklessly after entering a club? (7,5)' "$BD" ACADEMYAWARD)"
check "bigdave44 underline by style" \
  '{"definition": ["get visibly elated"]}' \
  "$(facts bigdave44 'Match over, get visibly elated (5,2)' "$BD" LIGHTUP)"

# A cross-reference is part of the clue, so a digit inside the underline stays.
check "digits inside a definition are kept" \
  '{"definition": ["3 characters"], "type": "hidden word"}' \
  "$(facts fifteensquared '3 characters in hotel ate ridiculously (8)' '<p>16 <u>3 characters</u> in hotel ate ridiculously (8)<br/>Hidden in hotEL ATE RIDiculously</p>' ELATERID)"

# Building blocks: WORD (clue words), letters checked against the answer.
# FT 18486, fifteensquared's table: the answer, the clue, then the wordplay.
FT='<table><tr><td>1</td><td><strong>TAKE COVER</strong></td><td><div><span>Arrange insurance and </span><span style="text-decoration: underline">head for shelter</span><span> (4,5)</span></div></td></tr>
<tr><td colspan="2"></td><td><strong>TAKE</strong> (arrange) + <strong>COVER</strong> (insurance)</td></tr>
<tr><td>6</td><td><strong>SEÑOR</strong></td><td><div><span style="text-decoration: underline">European’s address</span><span> from individuals backing Republican (5)</span></div></td></tr>
<tr><td colspan="2"></td><td><strong>ONES</strong> (individuals) <em>reversed </em>(backing) + <strong>R</strong> (Republican)</td></tr></table>'
check "FT 18486 1A: blocks joined by + that spell the answer are a charade" \
  '{"blocks": [["TAKE", "Arrange"], ["COVER", "insurance"]], "definition": ["head for shelter"], "type": "charade"}' \
  "$(facts fifteensquared 'Arrange insurance and head for shelter (4,5)' "$FT" TAKECOVER)"
check "FT 18486 6A: an italic operation names its indicator, and the reversal is letter-checked" \
  '{"blocks": [["ONES", "individuals"], ["R", "Republican"]], "definition": ["European’s address"], "indicators": ["backing"], "type": "charade + reversal"}' \
  "$(facts fifteensquared 'European’s address from individuals backing Republican (5)' "$FT" SENOR)"
check "pieces that do not spell the answer are no type; a source not in the clue is no block" \
  '{"blocks": [["TAKE", "Arrange"]], "definition": ["head for shelter"]}' \
  "$(facts fifteensquared 'Arrange insurance and head for shelter (4,5)' '<p>1 Arrange insurance and <u>head for shelter</u> (4,5)<br/>TAKE (arrange) + CAVER (policy)</p>' TAKECOVER)"
check "clue words that hold the letters and a selecting word: the type would leave the selection out" \
  '{"blocks": [["TH", "most of the"], ["IN", "batting"]], "definition": ["Balding"]}' \
  "$(facts fifteensquared 'Balding most of the batting (4)' '<p>1 <u>Balding</u> most of the batting (4)<br/>TH (most of the) + IN (batting)</p>' THIN)"
check "an operator binds to the piece beside it: MO + (HERON)*, not an anagram of both" \
  '{"blocks": [["MO", "second"]], "definition": ["Bird"], "indicators": ["flapping"], "type": "charade + anagram"}' \
  "$(facts timesforthetimes 'Bird flapping heron after second (7)' '<p>1 <u>Bird</u> flapping heron after second (7)<br/>MOORHEN – anagram (flapping) of HERON, after MO (second)</p>' MOORHEN)"
check "a hidden word keeps its type and shows no blocks" \
  '{"definition": ["Record-holder"], "indicators": ["somewhat"], "type": "hidden word"}' \
  "$(facts timesforthetimes 'Record-holder, somewhat egotistical, bumptious (5)' '<p>1 <u>Record-holder</u>, somewhat egotistical, bumptious (5)<br/>ALBUM : Hidden in (somewhat) {egotistic}AL BUM{ptious}</p>' ALBUM)"

# Bracketed letters are the unused ones, which is a selection as often as a deletion.
check "the kept letters name the selection: O[penly] R[evered] is first letters, not a deletion" \
  '{"blocks": [["O", "openly"], ["R", "revered"]], "definition": ["Teacher"], "type": "charade + first letters"}' \
  "$(facts timesforthetimes 'Teacher openly revered at first by boy king (5)' '<p>1 <u>Teacher</u> openly revered at first by boy king (5)<br/>TUTOR – TUT + O[penly] R[evered].</p>' TUTOR)"
check "letters kept one in two are alternate letters, not a deletion" \
  '{"definition": ["Passion"], "indicators": ["regularly"], "type": "alternate letters"}' \
  "$(facts timesforthetimes 'Passion Zoe regularly (4)' '<p>1 <u>Passion</u> Zoe regularly (4)<br/>ZEAL – Z{o}E{e}A{r}L{y} [regularly]</p>' ZEAL)"
check "brackets at both ends of a run of words are a hidden word, never a deletion" \
  '{"definition": ["Port"]}' \
  "$(facts fifteensquared 'Port contributing to slipshod essay (6)' '<p>1 <u>Port</u> contributing to slipshod essay (6)<br/>[slipsh]OD ESSA[y]</p>' ODESSA)"
check "clue words that only say what to cut are no block's source" \
  '{"blocks": [["E", "European"]], "definition": ["Learned"]}' \
  "$(facts bigdave44 'Learned European wants hors d’oeuvres topped and tailed (7)' '<p>22d <u>Learned</u> European wants hors d’oeuvres topped and tailed (7)<br/>E(uropean) then CRUDITES without the initial C and final S (topped and tailed)</p>' ERUDITE)"

[ "$fails" -eq 0 ] && echo "all blog_facts checks passed" || { echo "$fails failed"; exit 1; }
