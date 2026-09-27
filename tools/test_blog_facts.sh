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
  '{"blocks": [["HAM", "actor"], ["REMOTE", "remote", "anagrammed"]], "definition": ["Digital discomfort"], "type": "charade + anagram"}' \
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
  '{"blocks": [["LECTUR", "lecture", "anagrammed"], ["PM", "afternoon"]], "definition": ["Pick"], "indicators": ["arranged", "brief", "during"], "type": "anagram + container + deletion"}' \
  "$(facts timesforthetimes 'Pick brief lecture arranged during afternoon (8)' "$KEY$TT" PLECTRUM)"
check "no key: a bracket after an operation or a cut names its indicator, never a source" \
  '{"blocks": [["LECTUR", "lecture", "anagrammed"], ["PM", "afternoon"]], "definition": ["Pick"], "indicators": ["arranged", "during", "brief"], "type": "anagram + container + deletion"}' \
  "$(facts timesforthetimes 'Pick brief lecture arranged during afternoon (8)' "$TT" PLECTRUM)"

# bigdave44: indicators in italics inside parentheses, answer in a spoiler.
BD='<p>1a <u>Oscar</u> and Maya wed recklessly after entering a club? (7,5)<br />
<span class="spoiler">ACADEMY AWARD</span>: An anagram (<em>recklessly</em>) of MAYA WED</p>
<p>10a Match over, <span style="text-decoration: underline;">get visibly elated</span> (5,2)<br/>LIGHT UP</p>'
check "a named anagram whose fodder does not hold the answer is not typed, but its fodder is a block" \
  '{"blocks": [["MAYA WED", "Maya wed", "anagrammed"]], "definition": ["Oscar"], "indicators": ["recklessly"]}' \
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
  '{"blocks": [["HERON", "heron", "anagrammed"], ["MO", "second"]], "definition": ["Bird"], "indicators": ["flapping"], "type": "charade + anagram"}' \
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

# Times 29042, one key-bracketed post: a cut word that leaves the answer, a
# doubled letter, and brackets that also gloss or hold fodder.
T29='<p>definitions underlined, [anagrinds, containment, reversal and other indicators in square ones]</p>'
check "the answer as a word less a cut is that word's block; a bracket's gloss is a block and the rest its indicator" \
  '{"blocks": [["RESIGN", "Give up work"], ["S", "son"]], "definition": ["hold sway"], "indicators": ["releasing"], "type": "deletion"}' \
  "$(facts timesforthetimes 'Give up work, releasing son to hold sway (5)' "$T29<p>10 Give up work, releasing son to <u>hold sway</u> (5)<br/>REIGN<br/>RE{s}IGN {give up work} [releasing son – s]</p>" REIGN)"
check "B+B (bishops) is the block BB, and the container is spelled" \
  '{"blocks": [["BB", "bishops"], ["NILE", "river"]], "definition": ["Quick bite"], "indicators": ["demanded in middle of"], "type": "container"}' \
  "$(facts timesforthetimes 'Quick bite bishops demanded in middle of river (6)' "$T29<p>18 <u>Quick bite</u> bishops demanded in middle of river (6)<br/>NIBBLE<br/>B+B (bishops) contained by [demanded in middle of] NILE (river).</p>" NIBBLE)"
check "fodder at the end of a bracket is not the indicator" \
  '{"blocks": [["CANTERBURY", "See"], ["BELLS", "beautiful girls"]], "definition": ["flowers"], "indicators": ["cutting last of"], "type": "charade + deletion"}' \
  "$(facts timesforthetimes 'See beautiful girls cutting last of ornate flowers (10,5)' "$T29<p>6 See beautiful girls cutting last of ornate <u>flowers</u> (10,5)<br/>CANTERBURY BELLS<br/>CANTERBURY (see), BELL{e}S (beautiful girls) [cutting last of {ornat}e]</p>" CANTERBURYBELLS)"

check "a cut word glossed with its cut is no block: STOA{t} (tailless) is not STOAT" \
  '{"definition": ["colonnade"], "indicators": ["Tailless"], "type": "deletion"}' \
  "$(facts timesforthetimes 'Tailless furry creature by colonnade (4)' '<p>1 Tailless furry creature by <u>colonnade</u> (4)<br/>STOA – STOA{t} (furry creature without last letter – tailless)</p>' STOA)"
check "a letter and a cut word starting with it are not a doubled letter" \
  '{"blocks": [["EG", "Eulogising"], ["G", "good"], ["SHE", "woman"], ["LL", "lines"]], "definition": ["of great delicacy"], "type": "charade + outer letters"}' \
  "$(facts fifteensquared 'Eulogising emptily good woman lines of great delicacy (8)' '<p>1 Eulogising emptily good woman lines <u>of great delicacy</u> (8)<br/>E(ulogisin)G + G(ood) + SHE (“woman”) + LL (“lines”)</p>' EGGSHELL)"

# Definition marks other than <u>, and the refusal that keeps bold italic narrow.
check "text-decoration-line underlines too" \
  '["Finish"]' \
  "$(facts timesforthetimes 'Finish burlesque topless (3,2)' '<p>1 <span style="text-decoration-line: underline;">Finish</span> burlesque topless (3,2)<br/>x</p>' ENDUP | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin).get("definition")))')"
check "fifteensquared's fts-definition class is the underline" \
  '["Greek lyric poet"]' \
  "$(facts fifteensquared 'Unusually arcane about Greek lyric poet (8)' '<p>14 <span class="fts-clue">Unusually arcane about </span><span class="fts-definition">Greek lyric poet</span> (8)<br/>x</p>' ANACREON | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin).get("definition")))')"
check "bold italic is the definition only on a post with no underline" \
  '["city"] null' \
  "$(for u in '' '<u>x</u>'; do facts fifteensquared 'The fisherman’s bringing up food for the city (5,10)' "$u<p>5 The fisherman’s bringing up food for the <strong><em>city</em></strong> (5,10)<br/>x</p>" SAINTPETERSBURG | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin).get("definition")))'; done | paste -sd' ')"
check "the clue's operator in brackets between blocks: LASS (girl) [wrapping] G" \
  '{"blocks": [["MINUTE", "Tiny"], ["LASS", "girl"], ["G", "grand"]], "definition": ["timing device"], "indicators": ["wrapping"], "type": "charade + container"}' \
  "$(facts timesforthetimes 'Tiny girl wrapping grand timing device (6-5)' '<p>12 Tiny girl wrapping grand <u>timing device</u> (6-5)<br/>MINUTE-GLASS – MINUTE (tiny) LASS (girl) [wrapping] G (grand).</p>' MINUTEGLASS)"
check "minus the first letter trims; a curly quote opening a source; ', for' starts prose" \
  '{"blocks": [["SEND UP", "burlesque"]], "definition": ["Finish"], "indicators": ["topless"], "type": "deletion"}' \
  "$(facts timesforthetimes 'Finish burlesque topless (3,2)' '<p>1 <u>Finish</u> burlesque topless (3,2)<br/>END UP – SEND UP (burlesque), minus the first letter (topless), for leader of the gang.</p>' ENDUP)"
check "a source quoted with a closing quote, an apostrophe inside it" \
  '[["IS ON", "hasn’t been cancelled"], ["UN", "international organisation"]]' \
  "$(facts fifteensquared 'Concert hasn’t been cancelled in support of international organisation (6)' '<p>3 <u>Concert</u> hasn’t been cancelled in support of international organisation (6)<br/>IS ON=”hasn’t been cancelled”, supporting U[nited] N[ations]=”international organisation”</p>' UNISON | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin).get("blocks"), ensure_ascii=False))')"

# Anagram fodder is a block of the clue's own words, marked "anagrammed", kept
# only where its letters check against the answer, all of them or a part.
blk() { python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin).get("blocks"), ensure_ascii=False))'; }
check "(X)* with its indicator after: the whole answer's fodder" \
  '[["IN HAT", "in hat", "anagrammed"]]' \
  "$(facts fifteensquared 'Thane disguised in hat (5)' '<p>1 <u>Thane</u> disguised in hat (5)<br/>THAIN (IN HAT)* (disguised)</p>' THAIN | blk)"
check "an anagram (gloss) of a quoted phrase" \
  '[["SAME SAD", "same sad", "anagrammed"]]' \
  "$(facts bigdave44 'Crowded same sad converts (6)' '<p>1 <u>Crowded</u> same sad converts (7)<br/>An anagram (‘converts’) of ‘same sad’</p>' AMASSED | blk)"
check "WORD* then an AInd: fodder that is part of the answer" \
  '[["TURN", "turn", "anagrammed"], ["IP", "Ipswich"]]' \
  "$(facts fifteensquared 'Vegetable to turn off at Ipswich (6)' '<p>1 <u>Vegetable</u> to turn off at Ipswich (6)<br/>TURN* AInd: off + IP (Ipswich)</p>' TURNIP | blk)"
check "fodder spread over the clue is a block a run" \
  '[["A COURT", "a court", "anagrammed"], ["GRASS", "grass", "anagrammed"]]' \
  "$(facts timesforthetimes 'Sweetener a court arranged with grass (6,5)' '<p>1 <u>Sweetener</u> a court arranged with grass (6,5)<br/>CASTOR SUGAR – (A COURT GRASS)*.</p>' CASTORSUGAR | blk)"
check "fodder's lower-case letters are the ones not used: SLALOM RaCE" \
  '[["SLALOM RCE", "slalom race", "anagrammed"]]' \
  "$(facts fifteensquared 'Less advanced slalom race arranged for anyone who wants to enter (3,6)' '<p>1 Less advanced slalom race arranged for <u>anyone who wants to enter</u> (3,6)<br/>SLALOM RaCE* (without A – advanced)</p>' ALLCOMERS | blk)"
check "fodder whose letters do not check, or that is not the clue's words, is no block" \
  'null null' \
  "$(facts fifteensquared 'Fruit peel cut (5)' '<p>1 <u>Fruit</u> peel cut (5)<br/>(PEEL CUT)*</p>' LEMON | blk) $(facts fifteensquared 'Fruit ruined, lemon (5)' '<p>1 <u>Fruit</u> ruined, lemon (5)<br/>(MELON)*</p>' MELON | blk)"
check "a denied anagram names no fodder" \
  'null' \
  "$(facts fifteensquared 'Planet heart (5)' '<p>1 <u>Planet</u> heart (5)<br/>Not an anagram of HEART, sadly</p>' EARTH | blk)"

[ "$fails" -eq 0 ] && echo "all blog_facts checks passed" || { echo "$fails failed"; exit 1; }
