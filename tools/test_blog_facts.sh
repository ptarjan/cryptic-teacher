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

# A hidden word the write-up shows rather than names: the answer set off by
# case or brackets inside the clue words it hides in, or called a lurker.
t() { facts "$1" "$2" "<p>1 $2<br/>$3</p>" "$4" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("type"))'; }
check "the answer in capitals inside the clue words is a hidden word, a clue capital no mark" \
  'hidden word' "$(t timesforthetimes 'Princely Valentino bleeding a little (5)' 'NOBLE – “a little” of the letters of ValentiNO BLEeding' NOBLE)"
check "the answer in brackets inside a clue word is a hidden word" \
  'hidden word' "$(t timesforthetimes 'Wild party in Gravesend (4)' 'RAVE – G(RAVE)send.' RAVE)"
check "the answer backwards in capitals is a reversed hidden word" \
  'hidden word + reversal' "$(t fifteensquared 'Bird seen soaring in Milton Keynes (4)' 'reversed, i.e. soaring in, in ‘milTON Keynes’' KNOT)"
check "a lurker the clue's letters hold is a hidden word" \
  'hidden word' "$(t bigdave44 'Responsibility deacon usually carries (4)' 'ONUS: A lurker hiding in (carries) deacon usually.' ONUS)"
check "a lurker the clue's letters do not hold is not" \
  'None' "$(t bigdave44 'Responsibility deacon carries (4)' 'ONUS: not a lurker, a word for it.' ONUS)"
check "letters cut off one end of a clue word are a deletion, not a hidden word" \
  'None' "$(t fifteensquared 'Endless hatred of seaweed (5)' 'HATRE(d)' HATRE)"
check "the core of a clue word under a selecting word is not a hidden word" \
  'None' "$(t fifteensquared 'Heart of start is a star (3)' 's(TAR)t' TAR)"
check "bigdave44's \"2 meanings\" is a double definition" \
  'double definition' "$(t bigdave44 'Extraordinary red (4)' '{RARE} 2 meanings: extraordinary/red (as underdone meat)' RARE)"
check "\"is placed around\" is read past to its operator" \
  'anagram + container' "$(t bigdave44 'Grave-digger needs stone to be put in position about ten (6)' '{SEXTON} – An anagram (to be put in position) of STONE is placed around X (ten).' SEXTON)"
check "\"another (gloss) of\" after an anagram is a second anagram" \
  'anagram + container' "$(t bigdave44 'I’m so aroused in fancy lace underwear (8)' 'CAMISOLE An anagram (aroused) of IM SO inserted into another (fancy) of LACE' CAMISOLE)"
check "IS in capitals before an operator is letters, not filler" \
  'charade + container' "$(t timesforthetimes 'Seafood from Hull is served in fine hotel (9)' 'SHELLFISH – SHELL(hull), then IS inside F(fine) and H(hotel)' SHELLFISH)"
ind() { facts "$1" "$2" "<p>1 $2<br/>$3</p>" "$4" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("indicators"))'; }
check "a gloss on letters put in, not clue words, holds their source: only its container word is the indicator" \
  "['round']" "$(ind bigdave44 'Travel guide and staff going round one area, politician round another (4,3)' 'ROAD MAP – MP (politician) into which a second A is inserted (round another).' ROADMAP)"
check "a gloss on clue words put in is the indicator whole" \
  "['standing in']" "$(ind bigdave44 'Nasty chore, standing in queue after arranging method of payment (10)' 'EUROCHEQUE – a nasty CHORE is inserted into (standing in) an anagram of QUEUE' EUROCHEQUE)"

# Two underlines with only a space between them are two spans.
DD='<p>3 <u>Consequence</u> of <u>lob</u>? (6)<br/>Double definition</p>'
check "double definition keeps both halves" \
  '{"definition": ["Consequence", "lob"], "type": "double definition"}' \
  "$(facts fifteensquared 'Consequence of lob? (6)' "$DD" UPSHOT)"
SPLIT='<p>3 <u>Consequence</u> of <u>lob</u>? (6)<br/>UP + SHOT</p>'
check "two spans that are not a double definition ship no definition" \
  '{}' "$(facts fifteensquared 'Consequence of lob? (6)' "$SPLIT" UPSHOT)"
# A blogger who underlines both ends and names no type has marked a double
# definition; one whose explanation spells the answer has marked a split one.
check "two spans at the two ends, the explanation no wordplay, are a double definition" \
  '{"definition": ["Criminal", "tendency"], "type": "double definition"}' \
  "$(facts bigdave44 'Criminal tendency (4)' '<p>1a <u>Criminal</u> <u>tendency</u> (4)<br/>BENT – Slang for criminal or a tendency or inclination</p>' BENT)"
check "two spans at the two ends round wordplay are not" \
  '{"blocks": [["RASH VOTE", "Rash vote", "anagrammed"]]}' "$(facts timesforthetimes 'Rash vote cast before end of day could be this? (9)' \
    '<p>1 <u>Rash vote cast before end of day could be</u> <u>this</u>? (9)<br/>OVERHASTY – (rash vote)* + last letter of daY</p>' OVERHASTY)"
check "two spans with a clue word before the first are not" \
  '{}' "$(facts fifteensquared 'Heartless type shot big game (4)' \
    '<p>1 Heartless type shot <u>big</u> <u>game</u> (4)<br/>definition as in a Test Match</p>' TEST)"

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
  '{"definition": ["Port"], "type": "hidden word"}' \
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

# Blocks the blog left out, read off the letters (tools/letter_facts.py): the
# answer split one way only into runs of clue words, each read as blogs read
# those words in other puzzles. A corpus made up here stands in for theirs.
lex() {  # lex <clue> <answer> <facts JSON> -> the blocks infer_blocks adds, as JSON
  REPO="$REPO" python3 - "$1" "$2" "$3" <<'PY'
import json, os, sys
sys.path.insert(0, os.path.join(os.environ["REPO"], "tools"))
import letter_facts as lf
row = lambda n, clue, blocks: (f"p{n}", "1-across", clue, "", {"blocks": blocks})
corpus = [row(n, "Hat with church one (8)", [["CAP", "hat"], ["CE", "church"], ["I", "one"]]) for n in range(5)]
corpus += [row(10 + n, "Old saint and dog (5)", [["D", "and"]]) for n in range(3)]
corpus += [row(20 + n, "Tom and Jerry (3)", []) for n in range(700)]
if os.environ.get("ICE"):  # a second reading of the same words
    corpus += [row(30 + n, "Frozen one church (3)", [["ICE", "one church"]]) for n in range(3)]
got = lf.infer_blocks(sys.argv[1], sys.argv[2], json.loads(sys.argv[3]), lf.Lexicon(corpus))
print(json.dumps(got, ensure_ascii=False))
PY
}
check "missing blocks: the answer split into words blogs read so elsewhere" \
  '[["I", "one"], ["CE", "church"], ["CAP", "hat"]]' \
  "$(lex 'Polar covering: one church hat (6)' ICECAP '{"definition": ["Polar covering"]}')"
check "the blog's own blocks stay, and only the missing ones are added" \
  '[["I", "one"], ["CE", "church"]]' \
  "$(lex 'Polar covering: one church hat (6)' ICECAP '{"definition": ["Polar covering"], "blocks": [["CAP", "hat"]]}')"
check "a block around the others is a container" \
  '[["CE", "Church"], ["CAP", "hat"]]' \
  "$(lex 'Church wearing hat (5)' CCEAP '{"indicators": ["wearing"]}')"
check "a word blogs leave out of blocks beside them may stay out" \
  '[["I", "one"], ["CE", "church"], ["CAP", "hat"]]' \
  "$(lex 'Polar covering: one church with hat (6)' ICECAP '{"definition": ["Polar covering"]}')"
check "a word beside a block that blogs have never left out makes its span a guess" \
  'null' "$(lex 'Polar covering: one church hat, perhaps (6)' ICECAP '{"definition": ["Polar covering"]}')"
check "two splits of the answer are undecided" \
  'null' "$(ICE=1 lex 'Polar covering: one church hat (6)' ICECAP '{"definition": ["Polar covering"]}')"
check "a reading blogs gave in too few of the clues its words stand in is not read" \
  '[]' "$(lex 'Frozen: one church and (4)' ICED '{"definition": ["Frozen"]}')"
check "an anagram's letters are not split into blocks" \
  '[]' "$(lex 'Polar covering: one church hat (6)' ICECAP '{"definition": ["Polar covering"], "type": "anagram"}')"
check "a possessive reads as the word, written as blogs write it" \
  '[["I", "one"], ["CE", "church"], ["CAP", "hat"]]' \
  "$(lex 'Polar covering: one church’s hat (6)' ICECAP '{"definition": ["Polar covering"]}')"

# What a write-up says short of its blocks, for letter_facts to read blocks
# off: the capitals in the answer, the clue words it glosses them with (not
# the words its prose runs on into), the clue words it prints, what it names.
check "leads: capitals, their glosses, the clue words printed, an anagram and a letter taken" \
  '{"anagram": true, "caps": ["DULCIE", "IMER", "M"], "letter": true, "near": [["DULCIE", "Girl"], ["IMER", "right instrument"], ["M", "entertaining"]], "printed": ["Girl entertaining", "right instrument"]}' \
  "$(REPO="$REPO" python3 -c '
import json, os, sys
sys.path.insert(0, os.path.join(os.environ["REPO"], "tools"))
import blog_facts as bf
print(json.dumps(bf.leads("DULCIE (girl) entertaining M, then IMER = right instrument, an anagram; the first letter",
                          "Girl entertaining millions with right instrument", "DULCIMER"), sort_keys=True))')"

# An inferred block is marked, and every reader tells it from the blog's.
check "an inferred block is marked, and the facts as stated drop it" \
  '{"blocks": [["CAP", "hat"], ["I", "one", "inferred"]], "inferred": ["blocks", "type"], "type": "charade"} {"blocks": [["CAP", "hat"]]}' \
  "$(REPO="$REPO" python3 -c '
import json, os, sys
sys.path.insert(0, os.path.join(os.environ["REPO"], "tools"))
import letter_facts as lf
f = lf.with_blocks({"blocks": [["CAP", "hat"]], "type": "charade", "inferred": ["type"]}, [("I", "one")])
print(json.dumps(f, sort_keys=True), json.dumps(lf.stated(f), sort_keys=True))')"
check "the site, the validator and --score take an inferred block as ours, not the blogger's" \
  '[{"clueFragment": "hat", "gives": "CAP"}, {"clueFragment": "one", "gives": "I", "inferred": true}] [] 1' \
  "$(REPO="$REPO" python3 -c '
import json, os, sys
sys.path.insert(0, os.path.join(os.environ["REPO"], "tools"))
import blog_facts as bf, fetch_puzzle as fp, validate_annotations as va
blocks = [["CAP", "hat"], ["OUCH", "one", "inferred"]]
e = {"id": "1-across", "number": 1, "direction": "across", "clue": "Polar covering: one hat (6)", "solution": "ICECAP",
     "annotation": {"blocks": [{"clueFragment": "hat", "gives": "CAP"}]}}
va.blog_facts_for = lambda p: {"name": "Blog", "url": "u", "entries": {"1-across": {"blocks": blocks}}}
w = []
va.check_blocks_against_blog({"entries": [e]}, w)
ann = fp.blog_annotation({**e, "blog": {"blocks": [["CAP", "hat"], ["I", "one", "inferred"]]}})
print(json.dumps(ann["blocks"]), json.dumps(w), len(bf._items("blocks", blocks)))')"
check "--score leaves an anagram's fodder out of the blocks, as the gold does" \
  '[["tl", "tea"]]' \
  "$(REPO="$REPO" python3 -c '
import json, os, sys
sys.path.insert(0, os.path.join(os.environ["REPO"], "tools"))
import blog_facts as bf
print(json.dumps(sorted(bf._items("blocks", [["TL", "tea"], ["LAGER", "lager", "anagrammed"]]))))')"
check "a hidden word's carrier gets the note ours write, the run in capitals" \
  '["hidden in saW HIZbollah", "hidden backwards in whoM SIN A GROtesque", null]' \
  "$(REPO="$REPO" python3 -c '
import json, os, sys
sys.path.insert(0, os.path.join(os.environ["REPO"], "tools"))
import fetch_puzzle as fp
note = lambda sol, blocks: fp.blog_annotation({"solution": sol, "blog": {"blocks": blocks}})["blocks"][0].get("note")
print(json.dumps([note("WHIZ", [["WHIZ", "saw Hizbollah", "inferred"]]),
                  note("ORGANISM", [["ORGANISM", "whom sin a grotesque", "inferred"]]),
                  note("NOGGINS", [["GINS", "drinks"]])]))')"
check "the site takes inferred indicators as ours, not the blogger's" \
  'True True' \
  "$(REPO="$REPO" python3 -c '
import os, sys
sys.path.insert(0, os.path.join(os.environ["REPO"], "tools"))
import build_seo_pages as sp, letter_facts as lf
f = lf.with_indicators({"definition": ["Teacher"], "blocks": [["TUTS", "expresses disapproval"], ["ORES", "minerals"]]}, ["holding"])
html = sp.clue_html({"id": "1-across", "number": 1, "direction": "across", "solution": "TUTORESS",
                     "clue": "Teacher expresses disapproval holding minerals (8)", "blog": f})
print("holding</mark> <span class=\"s-note\">worked out from the letters</span>" in html,
      "Indicators worked out from the letters" in html)')"
check "the site and the validator take an inferred definition as ours, not the blogger's" \
  'True True 0' \
  "$(REPO="$REPO" python3 -c '
import os, sys
sys.path.insert(0, os.path.join(os.environ["REPO"], "tools"))
import build_seo_pages as sp, letter_facts as lf, validate_annotations as va
f = lf.with_definition({"blocks": [["TUTS", "expresses disapproval"], ["ORES", "minerals"]]}, ["Teacher"])
html = sp.clue_html({"id": "1-across", "number": 1, "direction": "across", "solution": "TUTORESS",
                     "clue": "Teacher expresses disapproval over minerals (8)", "blog": f})
e = {"id": "1-across", "number": 1, "direction": "across", "clue": "Teacher expresses disapproval over minerals (8)",
     "annotation": {"definition": "minerals"}}
va.blog_facts_for = lambda p: {"name": "b", "url": "u", "entries": {"1-across": f}}
w = []
va.check_definition_against_blog({"entries": [e]}, w)
print("Teacher</dfn> <span class=\"s-note\">worked out from the letters</span>" in html,
      "Definition worked out from the letters" in html, len(w))')"

[ "$fails" -eq 0 ] && echo "all blog_facts checks passed" || { echo "$fails failed"; exit 1; }
