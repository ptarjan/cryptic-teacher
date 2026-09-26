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

facts() {  # facts <blog> <clue> <html> -> the published facts of that one clue, as JSON
  REPO="$REPO" python3 - "$1" "$2" "$3" <<'PY'
import json, os, sys
sys.path.insert(0, os.path.join(os.environ["REPO"], "tools"))
import blog_facts as bf
blog, clue, html = sys.argv[1:]
entries = [("1-across", bf.clue_body(clue), "X")]
got = bf.facts_for_post(blog, entries, {"content": html}).get("1-across")
print(json.dumps(bf.publishable(got), sort_keys=True) if got else "NONE")
PY
}

# fifteensquared: the clue in blue with the definition underlined, then the explanation.
FS='<table><tr><td>9</td><td><b>SARI</b></td><td><font color="blue"><u>Cloth</u> sample in Mombasa rickshaw (4)</font><br />Hidden in mombaSA Rickshaw</td></tr>
<tr><td>10</td><td><b>HAMMERTOE</b></td><td><font color="blue"><u>Digital discomfort</u> caused as actor pressed remote (9)</font><br />HAM (actor) + REMOTE*</td></tr></table>'
check "fifteensquared definition and hidden type" \
  '{"definition": ["Cloth"], "type": "hidden word"}' \
  "$(facts fifteensquared 'Cloth sample in Mombasa rickshaw (4)' "$FS")"
check "an anagram named by its star, explanation bounded by the next clue" \
  '{"definition": ["Digital discomfort"], "type": "anagram"}' \
  "$(facts fifteensquared 'Digital discomfort caused as actor pressed remote (9)' "$FS")"

# Two underlines with only a space between them are two spans.
DD='<p>3 <u>Consequence</u> of <u>lob</u>? (6)<br/>Double definition</p>'
check "double definition keeps both halves" \
  '{"definition": ["Consequence", "lob"], "type": "double definition"}' \
  "$(facts fifteensquared 'Consequence of lob? (6)' "$DD")"
SPLIT='<p>3 <u>Consequence</u> of <u>lob</u>? (6)<br/>UP + SHOT</p>'
check "two spans that are not a double definition ship no definition" \
  '{}' "$(facts fifteensquared 'Consequence of lob? (6)' "$SPLIT")"

check "an underline cutting into a word is refused" \
  'NONE' "$(facts fifteensquared 'Cloth sample (4)' '<p>C<u>loth</u> sample (4)<br/>x</p>' | sed 's/{}/NONE/')"
check "a hedged type is not a type" \
  '{"definition": ["Sack"]}' \
  "$(facts fifteensquared 'Sack one likely to get fired (5)' '<p><u>Sack</u> one likely to get fired (5)<br/>RIFLE: almost a double definition</p>')"

# timesforthetimes: brackets are indicators only where the post's key says so.
KEY='<p>definitions underlined, [anagrinds, containment, reversal and other indicators in square ones]</p>'
TT='<tr><td>6</td><td><span><i><b><u>Pick</u></b></i> brief lecture arranged during afternoon (8)</span></td></tr>
<tr><td></td><td><b>PLECTRUM</b></td></tr><tr><td></td><td>Anagram [arranged] of LECTUR{e} [brief] contained by [during] PM (afternoon)</td></tr>'
check "timesforthetimes bracketed indicators under the key" \
  '{"definition": ["Pick"], "indicators": ["arranged", "brief", "during"], "type": "anagram"}' \
  "$(facts timesforthetimes 'Pick brief lecture arranged during afternoon (8)' "$KEY$TT")"
check "no key, no indicators: other bloggers bracket glosses" \
  '{"definition": ["Pick"], "type": "anagram"}' \
  "$(facts timesforthetimes 'Pick brief lecture arranged during afternoon (8)' "$TT")"

# bigdave44: indicators in italics inside parentheses, answer in a spoiler.
BD='<p>1a <u>Oscar</u> and Maya wed recklessly after entering a club? (7,5)<br />
<span class="spoiler">ACADEMY AWARD</span>: An anagram (<em>recklessly</em>) of MAYA WED</p>
<p>10a Match over, <span style="text-decoration: underline;">get visibly elated</span> (5,2)<br/>LIGHT UP</p>'
check "bigdave44 italic indicator and anagram" \
  '{"definition": ["Oscar"], "indicators": ["recklessly"], "type": "anagram"}' \
  "$(facts bigdave44 'Oscar and Maya wed recklessly after entering a club? (7,5)' "$BD")"
check "bigdave44 underline by style" \
  '{"definition": ["get visibly elated"]}' \
  "$(facts bigdave44 'Match over, get visibly elated (5,2)' "$BD")"

# A cross-reference is part of the clue, so a digit inside the underline stays.
check "digits inside a definition are kept" \
  '{"definition": ["3 characters"], "type": "hidden word"}' \
  "$(facts fifteensquared '3 characters in hotel ate ridiculously (8)' '<p>16 <u>3 characters</u> in hotel ate ridiculously (8)<br/>Hidden in hotEL ATE RIDiculously</p>')"

[ "$fails" -eq 0 ] && echo "all blog_facts checks passed" || { echo "$fails failed"; exit 1; }
