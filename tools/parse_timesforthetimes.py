#!/usr/bin/env python3
"""Turn cached timesforthetimes.co.uk posts into clue and answer records.

The Times withholds its grids, but this blog prints, for every puzzle, the
clue NUMBER under an Across or Down heading and the ANSWER. Number, direction
and answer length are the whole input to tools/reconstruct_grid.py, so these
records are what a Times grid gets rebuilt from. From about 2017 the posts
carry the clue TEXT and its enumeration too, which is what makes the puzzle
teachable rather than merely drawable.

Three eras of markup, one parser: the posts are flattened to lines and read as
a stream, because every era puts the number, the clue and the answer on lines
of their own once the tags are gone — a 2025 table cell, a 2020 <br>-separated
paragraph and a 2010 table row differ in tags and not in shape.

Reads the cache `tools/fetch_wp_blog.py timesforthetimes` writes; never the network.
"""
import argparse
import html
import json
import re
import sys
import unicodedata
from pathlib import Path

CACHE = Path.home() / "cryptic-setter-data" / "timesforthetimes"
POSTS = CACHE / "posts"
OUT = CACHE / "parsed.jsonl"

SERIES = {
    11: "Daily Cryptic",
    12: "Quick Cryptic",
    21: "Weekend Cryptic",
    14: "Jumbo Cryptic",
    13: "Mephisto",
    24: "Monthly Club Special",
    26: "Other Crosswords",
}

#: How many entries each series really has, give or take a blogger who skipped
#: one. Outside this range the post is reported, never emitted: a parser that
#: quietly under-extracts is indistinguishable from a blogger who wrote less.
PLAUSIBLE = {
    "Daily Cryptic": (24, 34),
    "Quick Cryptic": (20, 30),
    "Weekend Cryptic": (24, 34),
    # A Times Jumbo runs to 62 lights, a Sunday Times Jumbo to 70.
    "Jumbo Cryptic": (40, 72),
    "Mephisto": (24, 42),
    "Monthly Club Special": (24, 42),
}

#: Tags that end a line of reading, whatever era drew them.
BREAKS = re.compile(r"</?(?:br|p|div|tr|td|th|li|h[1-6]|table|tbody)\b[^>]*>",
                    re.I)
TAG = re.compile(r"<[^>]+>")
HEADING = re.compile(r"^(across|down)\b[\s:.]*$", re.I)
#: A clue can open with a time or a decimal -- "5:37, perhaps, is when most
#: are watching?" -- and that is clue text, not clue number 5. Nor is a longer
#: number a clue number: "1066 Pevensey event" is not clue 10.
NUMBERED = re.compile(r"^(\d{1,2})(?!\d|[.:]\d)\s*[.):]?\s*(.*)$")
#: An answer is the line's leading run of capitals, ended by whichever mark
#: the wordplay hangs off — a dash, an equals sign, a colon or a semicolon. A
#: plain hyphen ends it only when a space is on either side of it, or
#: WELL-KNOWN truncates to WELL: "NISAN -Granny NAN" is a dash typed short. A
#: full stop ends it when a sentence follows, "IDEA. Less than perfect
#: (IDEA)l", or wordplay in capitals does: "ADOPT. AD=notice", "ACT UP. A – CT
#: – UP" -- but not after an initial, "T + R. ELLIS", "A N.Y. WAY =", nor after
#: an abbreviation the answer goes on past, "ST. HELENA – S for Society".
ANSWER = re.compile(
    r"^([A-Z][A-Z0-9'\u2019()\[\]+,. \-]{1,70}?)"
    r"(?:\s*(?:[\u2013\u2014=;:]|-\s|-\s*$|$)|\s+-"
    r"|\.\s+(?=[A-Z][a-z])|(?<=[A-Z]{2})\.\s+(?=[A-Z']+\s*=|[A-Z]\s*[\u2013\u2014-]))")
#: Wordplay written into the answer itself: S(L)OUGH, YOR[I+C]K, RICE,PAPER.
#: The letters in order are the answer — the brackets are the blogger showing
#: their working, and the comma is the space between two words.
ANSWER_MARKUP = re.compile(r"[()\[\]+.]")
#: …except when the comma is what ends the answer, as in "NARCOSIS, anagram of
#: CAR". A word of the answer is printed in capitals; the wordplay that follows
#: a comma is prose, so the case of the next word settles which one it is.
WORDPLAY_COMMA = re.compile(r",\s+(?=[a-z])")
#: A deleted letter written in lower case inside the answer: SWANSON[g], IN(v).
DROPPED_LETTERS = re.compile(r"[\[(][a-z]+[\])]")
#: A mark that already ends a printed answer outside of any aside -- see
#: ANSWER below. Found ahead of an aside, it means the printed answer ended
#: before the aside was ever reached: "RED,LEICESTER -- (I ELDER
#: reversed)-CE-STER(n)" stops at the dash with the comma still part of the
#: answer, so nothing about the aside that follows is this module's to read.
HARD_TERMINATOR = re.compile(r"[–—;]")
#: A parenthetical the blogger wrote as commentary on a fragment, not as part
#: of the answer: "(= 'amount of business')" glosses what a charade piece
#: means, "(canvasser, i.e. painter)" is an aside. Wordplay written INTO the
#: answer -- S(L)OUGH, (GIN)* -- is always upper case inside the parens; a
#: lower case letter anywhere inside is what marks this one as prose instead.
#: This also matches DROPPED_LETTERS' short pure-letter markers -- (v), (w)
#: -- but _aside_cut below leaves anything it cannot place safely untouched,
#: so DROPPED_LETTERS, run after, still takes them exactly as it always has.
ASIDE = re.compile(r"\([^()]*[a-z][^()]*\)")
#: An aside that names the clue's type -- "AIRMAIL (cryptic definition)",
#: "TOSH (2 defs)", "SHOW-JUMPERS (1 def, 1 literal interpretation)" -- says
#: nothing about the letters, so a printed answer standing alone before it
#: ends there.
CLUE_TYPE = re.compile(
    r"^\((?:\d|one|two|three|double|triple|cryptic|straight|&\s*lit)"
    r"[^()]*\bdef", re.I)
#: Deleted letters, marked two ways across the eras, are not in the answer.
DELETED = re.compile(r"<(s|strike|del)\b[^>]*>.*?</\1>", re.I | re.S)
#: A braced deletion never crosses a line: "{bu}RI{ed{" mistypes its closing
#: brace, and a brace that may run on to the next "}" deletes every clue between.
#: In a clue line -- one ending in its enumeration -- braces mark the hidden
#: word instead, "dishe{s a la Mi}lanese (6)", and only the braces go.
BRACED = re.compile(r"\{[^{}\n]*\}")
#: A struck clue's correction: "<del>old clue</del>. Clue was later amended to
#: read: new clue". The strike is gone by now; this lead-in goes with it.
AMENDED = re.compile(r"^[.\s]*(?:(?:this|the clue|clue)\s+(?:was\s+)?(?:later\s+)?"
                     r"amended\b[^:]{0,40}?\bto(?:\s+read)?:?\s*)", re.IGNORECASE)
#: An enumeration still open at the end of a line: "(7-", "(4,".
OPEN_ENUM = re.compile(r"\(\d{1,2}(?:[,\-\u2013\s]+\d{1,2})*[,\-\u2013]$")
#: A clue's enumeration: word lengths, none of them longer than a grid is
#: wide. "Special Providence (1930)" ends in a year, not in a count; "( 3,4)"
#: is a space typed inside the bracket.
ENUM = re.compile(r"\(\s*(\d{1,2}(?:[,\-–\s]+\d{1,2})*)[,\-–\s]*\)\s*$")
#: An enumeration typed at a clue's end but not in ENUM's shape: unclosed,
#: closed by a brace ("(3,5}", "(6)}"), dotted, or followed by punctuation.
LOOSE_ENUM = re.compile(r"\s*[({]\s*(\d{1,2}(?:[,\-\u2013.\s]+\d{1,2})*)\s*\)?\}?[\s.,;:]*$")
#: A count in words, Mephisto's "(9, three words)": the clue already has one.
WORDED_ENUM = re.compile(r"\(\s*\d{1,2}\b[^()]*\bwords?\b[^()]*\)[\s.,;:]*$")
#: A clue that covers two or more lights heads its list of them: "10/11",
#: "1,5", "4, 9", "9 & 27", "16 and 8", "20/17a", "59/53ac", "1/29/19dn",
#: "6/6dn", "3 & 18A.". A suffix names the light's direction; without one the
#: light runs in the direction of the heading it was printed under, which is
#: why 6/6dn is two different lights and 10/10 is not a linked clue at all.
LINK_HEAD = re.compile(
    r"^(\d{1,2})\s*(across|ac|a|down|dn|d)?"
    r"((?:\s*(?:,|/|&|and)\s*\d{1,2}\s*(?:across|ac|a|down|dn|d)?\b){1,3})",
    re.I)
LINK_PART = re.compile(r"(\d{1,2})\s*(across|ac|a|down|dn|d)?\b", re.I)
DIRECTION_OF = {"a": "across", "ac": "across", "across": "across",
                "d": "down", "dn": "down", "down": "down"}
#: What a linked head leaves before the clue starts: "4 & 29: A notable…".
LINK_TAIL = re.compile(r"^[\s.:;)\-–—]+")
#: A number cell with a stray mark typed into it -- "(10", ".7" -- is still
#: that number's cell. Never a closed pair: "(4)" alone is an enumeration.
STRAY_NUMBER = re.compile(r"^(?:\(\s*(\d{1,2})|\.\s*(\d{1,2})\.?)$")
#: A number cell can name its direction too -- "12d", "20a", "5ac" -- and is
#: still a bare number cell, not clue number 12 with clue text "d".
BARE_SUFFIX = re.compile(r"^(across|ac|a|down|dn|d)\.?$", re.I)
#: "See 15", "See 3 (9)", "See 12 across", "See 12a" — a light whose clue lives on another
#: light. tools/normalise_linked_enumerations.py reads the same shape; this is
#: how the whole corpus spells a continuation.
CONTINUATION = re.compile(r"^\s*See\s+(\d+)(?:[ad]\b|\b)", re.IGNORECASE)
#: "See 12a": a pointer with its direction glued on. "See 12 Down": one named.
GLUED_POINTER = re.compile(r"^\s*See\s+(\d+)([ad])\s*$", re.IGNORECASE)
NAMED_WAY = re.compile(r"^\s*See\s+\d+\s*(?:across|down|ac|dn|a|d)\b", re.IGNORECASE)
#: Where one word of an answer ends and the next begins, as printed. An
#: apostrophe is inside a word (CAT O' NINE TAILS is four words); a comma is a
#: word break in the eras that print RICE,PAPER.
WORD_BREAK = re.compile(r"[ ,\-–—]+")
#: No light in any of these puzzles, blocked or barred, is shorter than this.
#: A "split" that hands a light one or two letters has found a word break that
#: is not a light break — A,TSIXES,AND,SEVENS is one light and four words.
MIN_LIGHT = 3
#: Blog slugs put the puzzle number first: times-29572-…, qc-1255-by-hurley,
#: monthly-club-special-20231-…. The title is the fallback when it does not.
NUMBER_IN = re.compile(r"(\d{3,5})")


def unbrace(ln):
    """A clue line keeps its braced letters; any other line loses them."""
    kept = BRACED.sub(lambda m: m.group(0)[1:-1], ln)
    return kept if ENUM.search(kept) else BRACED.sub("", ln)


def lines(rendered):
    """Flatten post HTML to the lines the era-independent reader walks."""
    text = DELETED.sub("", rendered)
    text = BREAKS.sub("\n", text)
    text = TAG.sub("", text)
    text = html.unescape(text)
    # Some 2014 posts are double-encoded: "&amp;nbsp" survives one unescape as
    # "&nbsp", glued to the answer it indents.
    text = re.sub(r"&nbsp;?", " ", text)
    text = text.replace("\t", "\n").replace("\xa0", " ")
    # An enumeration broken over a tag, "(7-" then "2)", is one line: its tail
    # read alone is a bare clue number 2.
    out, open_at = [], None
    for ln in (re.sub(r"\s+", " ", ln).strip() for ln in text.split("\n")):
        ln = AMENDED.sub("", unbrace(ln))
        if open_at is not None and re.match(r"\d", ln):
            out[open_at] += ln
            open_at = None
            continue
        out.append(ln)
        if ln:
            open_at = len(out) - 1 if OPEN_ENUM.search(ln) else None
    return out


def puzzle_number(post):
    """The puzzle's number, off the slug or else the title.

    A slug WordPress made up itself is the post id -- "50707-2" -- and says
    nothing about the puzzle, so the title answers instead, where a number may
    be printed with its thousands comma: "Times 27,365".
    """
    m = NUMBER_IN.search(post.get("slug", ""))
    if not m or int(m.group(1)) == post.get("id"):
        title = html.unescape(post.get("title", {}).get("rendered", ""))
        m = NUMBER_IN.search(re.sub(r"(?<=\d),(?=\d{3}\b)", "", title))
    return int(m.group(1)) if m else None


WEEKDAY = r"(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day\b"
NAME = rf"(?!{WEEKDAY})[A-Z][\w'’]*"
#: The byline sits between the title's first number and the title's own dash or
#: colon: "QC 2426 from Hurley: Make your peace", "Times Quick Cryptic No
#: 919 – by Teazel", "1348by Tracy". A struck-out name or an aside right after
#: "by" is skipped for the one after it. The name is up to three capitalised
#: words ("Robert Price", "Bob and Margaret"), ending before a weekday.
BYLINE = re.compile(
    r"\D*\d[\d,]*\s*(?:[–—-]\s*(?=by\b))?(?:[^–—:]*?\b)?(?:by|By|from)\s+"
    r"(?:<del>.*?</del>\s*|\([^)]*\)\s*)?"
    rf"({NAME}(?: (?:and )?{NAME}){{0,2}})")
#: Titles that spell a setter two ways.
SETTER_ALIAS = {"Tracey": "Tracy", "Margaret and Bob": "Bob and Margaret"}


def setter_from_title(title):
    """The setter the post's title names, or None: the blog is the only
    source of a Times Quick or Sunday Times byline."""
    m = BYLINE.match(html.unescape(title or ""))
    return m and SETTER_ALIAS.get(m.group(1), m.group(1))


#: The Times Cryptic passed 20000 decades before the blog began, and the Quick
#: Cryptic has yet to reach 4000, so a puzzle number says which of the two a
#: post is when its category disagrees.
TIMES_CRYPTIC_FROM = 20000
QUICK_BELOW = 4000
QUICK_TITLE = re.compile(r"\bquick\s+cryptic\b", re.I)


def filed_series(post, series, number):
    """The series a post's category files it under, corrected by its number.

    The category is set by hand and is sometimes wrong: a Times Cryptic filed
    as a Quick Cryptic gets rebuilt on a 13x13 grid it cannot fit. A number
    only a Times Cryptic reaches moves it back; a Quick Cryptic filed as a
    daily moves only when its title says Quick Cryptic as well, because a
    daily's number read off a title can come out short.
    """
    if series == "Quick Cryptic" and number and number >= TIMES_CRYPTIC_FROM:
        return "Daily Cryptic"
    title = html.unescape(post.get("title", {}).get("rendered", ""))
    if (series == "Daily Cryptic" and number and number < QUICK_BELOW
            and QUICK_TITLE.search(title)):
        return "Quick Cryptic"
    return series


def _aside_cut(rest, kept_so_far, prefix, m):
    """Where to cut for one aside, or None to leave it untouched.

    A real terminator (a dash, a semicolon) ahead of the aside already ended
    the printed answer earlier in the line -- "RED,LEICESTER -- (I ELDER
    reversed)-CE-STER(n)" stops at the dash, comma and all, so the aside is
    commentary on the CLUE and is not ours to read.

    A comma ahead of it, short of that, already opened a wordplay clause --
    "SPOON-FEED, SPOON (the golf club) + FEED" restates the answer's own
    fragments in upper case once the derivation starts, so the whole clause
    from the comma on is cut. This is WORDPLAY_COMMA's own rule (a comma
    opens the derivation), just no longer blind to a derivation that
    capitalises its restated fragments -- UNLESS an earlier, untouched aside
    already sits in the kept text, because then the comma is not the first
    sign of trouble and cutting back to it would still keep that aside's own
    unresolved parenthesis.

    A gloss written "(= ...)" is definitional -- "TURN OVER (= 'amount of
    business')" -- and the answer can run on past it when a '+' follows,
    because that is how this corpus writes a second charade fragment on:
    "... + A NEW LEAF". Anything else after a '=' gloss is where the printed
    answer actually stops, same as it always has (a bare '=' is already one
    of the marks that ends one); the gloss becomes a semicolon rather than
    nothing, so the regex has a terminator to find there instead of running
    on or hunting for one that was never there.

    Any OTHER aside -- "(canvasser, i.e. painter)" -- is commentary on a
    fragment already written in upper case, never a gloss of its own, so it
    never grants a continuation either; it only ends the answer, and only
    when the text since the last cut is a single '+'-joined run with no
    earlier untouched aside. That combination is what tells a charade still
    being built ("N + A + GOYA (canvasser, i.e. painter)") apart from an
    answer some bloggers restate right after stating it in full ("AWARD A +
    WARD (rev of DRAW...)", "MANNISH M (married) ANN (name of woman)..."),
    where nothing marks where the restatement should stop and the whole
    line is refused rather than guessed at.

    None of the above ever applies to an aside fused straight onto a letter
    with no space, on either side. Before it: "M(otor) S(hip) = MODEMS" is a
    charade of abbreviations, each gloss naming what the ONE letter in front
    of it stands for, not a definition to read past or stop at -- the answer
    is already complete in the fragments themselves, same as DROPPED_LETTERS'
    own short markers. After it: "ST + A + (i)MPEDE" drops the 'i' and runs
    straight into "MPEDE", not into more of this module's answer, and
    touching it here would cut the answer off before the letters the
    deletion glues onto. Nor does any of this apply inside a still-open
    square bracket: "BRI[O + CH(eck)]E" nests a gloss INSIDE an insertion,
    and the insertion, not the gloss, is what decides where this stretch of
    the answer ends.
    """
    combined = kept_so_far + prefix
    if (rest[m.end():m.end() + 1].isalnum()
            or (prefix and prefix[-1].isalnum())
            or (not prefix and kept_so_far and kept_so_far[-1].isalnum())
            or combined.count("[") > combined.count("]")):
        return None
    if HARD_TERMINATOR.search(prefix):
        return None
    if (not kept_so_far and CLUE_TYPE.match(m.group(0))
            and re.fullmatch(r"[A-Z][A-Z'\u2019 \-]*[A-Z]\s*", prefix)):
        return prefix, ";"
    comma = prefix.find(",")
    if comma != -1:
        kept = kept_so_far + prefix[:comma]
        # A period ahead of the comma is itself already a break between the
        # answer and its derivation -- "CUTLASS. CUTL,A,S,S (a couple of
        # Seconds)" -- so the comma is inside the derivation's own listing,
        # not the boundary that starts it, and cutting back to it would
        # still keep part of that listing.
        if "(" in kept or "." in kept:
            return None
        # The word right after the comma has to be a REPEAT of something
        # already in the kept answer for the comma to be where a derivation
        # starts. "BEST,RADDLES(hurdles)" is a genuine two-word answer --
        # RADDLES is not anywhere in BEST -- so the comma stays exactly the
        # kind of word break RICE,PAPER already relies on, and cutting there
        # would throw away the second word instead of an aside. A fragment
        # under MIN_LIGHT letters is too short to trust either way --
        # "GAL,A,GE=(earth) goddess" would misread its own single "A" as a
        # repeat of the "A" already sitting inside "GAL" -- so it is treated
        # as not a repeat, same as a longer one that plainly is not. And it
        # has to repeat a WHOLE earlier word, not just share letters with
        # one -- "AWAY -A, WAY (path)" builds AWAY out of A and WAY, and WAY
        # is plain substring of AWAY without restating anything.
        word = re.match(r"[A-Z]+", prefix[comma + 1:].lstrip())
        if (not word or len(word.group()) < MIN_LIGHT
                or word.group() not in WORD_BREAK.split(kept)):
            return None
        return prefix[:comma], ";"
    if rest[m.start() + 1] == "=":
        after = rest[m.end():].lstrip()
        return prefix, (" " if after.startswith("+") else ";")
    if "+" in prefix and "(" not in kept_so_far:
        # Every '+'-joined fragment before the aside has to be a single
        # token, not just the first: "C + ASUS BE (anag) + ILL (rev)" would
        # otherwise pass on "C" alone and still cut ASUS BE off, the same
        # restatement risk AWARD's "AWARD A + WARD (rev...)" already guards
        # against, just one fragment further in.
        parts = [seg.strip() for seg in prefix.split("+")]
        if all(parts) and all(" " not in seg for seg in parts):
            # "TRIP + O (round) + LI" is already, visibly, a charade in
            # progress -- a '+' both sides of the aside -- so a '+' after it
            # is one more fragment of the SAME charade, not a new one, and
            # the answer reads on past it exactly as a '(= ...)' gloss does.
            after = rest[m.end():].lstrip()
            return prefix, (" " if after.startswith("+") else ";")
    return None


def _drop_asides(rest):
    """Cut every aside the printed answer can be read past, per _aside_cut."""
    out, pos = [], 0
    for m in ASIDE.finditer(rest):
        prefix = rest[pos:m.start()]
        cut = _aside_cut(rest, "".join(out), prefix, m)
        if cut is None:
            out.append(prefix)
            out.append(m.group(0))            # not ours to touch: put it back
        else:
            kept, filler = cut
            out.append(kept)
            out.append(filler)
        pos = m.end()
    out.append(rest[pos:])
    return "".join(out)


def printed_answer(rest):
    """This line's answer as the blogger printed it, or None if it is a clue.

    The word breaks are kept here and thrown away by is_answer, because one
    caller needs them: a linked clue is split between its lights AT a word
    break, and the printing is where those breaks are.
    """
    # A grid square holds a bare letter: ETAGERE is what ÉTAGÈRE writes in.
    rest = "".join(c for c in unicodedata.normalize("NFKD", rest)
                   if not unicodedata.combining(c))
    rest = DROPPED_LETTERS.sub("", WORDPLAY_COMMA.split(_drop_asides(rest), 1)[0])
    m = ANSWER.match(rest)
    if not m:
        return None
    word = ANSWER_MARKUP.sub("", m.group(1))
    letters = re.sub(r"[^A-Z]", "", word)
    if len(letters) < 3 or len(word) > 60:
        return None
    return word


#: One word of a printed answer as answer_by_enum reads it: capitals, with an
#: apostrophe inside (O'ER), ended by anything that is not a lower-case letter.
CAPS_WORD = re.compile(r"[\s,\-\u2013\u2014]*([A-Z][A-Z'\u2019]*)(?![a-z])")
#: One word of answer_by_enum's fallback: capitals, not glossed by a bracket.
GLOSSLESS_WORD = re.compile(r"[ \-]*([A-Z][A-Z'\u2019]+)(?![a-z(\[])")
#: An answer typed in ordinary case -- "Champion - double definition",
#: "Estonia - E and STONIA" -- counts only with the dash after it, because a
#: line of wordplay opens with an ordinary word too: "Anagram of..." is (7).
TITLE_WORD = re.compile(r"[\s\-]*([A-Za-z][A-Za-z'\u2019]*)")
TITLE_END = re.compile(r"\s*[\u2013\u2014-]\s")


#: A first name, bracketed or not, typed ahead of an answer in capitals.
NAME_FIRST = re.compile(r"\(?[A-Z][a-z]+\)?\s+(?=[A-Z]{2})")


def answer_by_enum(line, enum):
    """The answer on the line after a clue, read off its enumeration.

    Some answers are printed with nothing after them to end on -- "AGENCIES GEN
    (information) inside...", "BOND, James Bond", "CHOP CHOP! - CHOP * 2",
    "\u2018TIS -many...", "Range - fury" -- so printed_answer, which needs
    capitals and a mark to stop at, finds no answer at all. The clue's
    enumeration is a second source for where it stops: the leading words ARE
    the answer when their letter counts are, word for word, the counts the
    enumeration gives. Anything short of an exact match is not an answer.

    It also overrules a printed answer of the wrong length: "ESSAY  ESSAY(ed)",
    "HOCKEY. C=caught", "ALIBI  CD" run the wordplay on with no dash between,
    and the answer is the part the enumeration counts.
    """
    counts = [int(n) for n in re.findall(r"\d+", enum or "")]
    if not counts:
        return None
    line = "".join(c for c in unicodedata.normalize("NFKD", line)
                   if not unicodedata.combining(c))
    line = line.lstrip("\u2018\u201c'\"")
    # A name can stand in front of the answer, "Jean COCTEAU – CO + ..." or
    # "(Desmond) TUTU – TU", and then the dash after the answer is required.
    named = NAME_FIRST.match(line)
    tries = [(CAPS_WORD, None, 0), (TITLE_WORD, TITLE_END, 0)]
    if named:
        tries.append((CAPS_WORD, TITLE_END, named.end()))
    for word_re, ender, start in tries:
        words, pos = [], start
        for n in counts:
            m = word_re.match(line, pos)
            if not m or len(re.sub(r"[^A-Za-z]", "", m.group(1))) != n:
                break
            words.append(m.group(1).upper())
            pos = m.end()
        else:
            if ender is None or ender.match(line, pos):
                return " ".join(words)
    # The blog's enumeration can be the one mistyped -- "POM POM" under (6),
    # "GRACENOTE" under (5,4) -- so leading capitals that count the
    # enumeration's total are the answer too. A word the blogger glosses,
    # "U(niversity)", is wordplay, and ends the search; so does a dash or a
    # one-letter word, which is where the prose starts: "TEA ROSE A neat...".
    total, got, pos = sum(counts), [], 0
    while sum(map(len, got)) < total:
        m = GLOSSLESS_WORD.match(line, pos)
        if not m:
            return None
        got.append(re.sub(r"[^A-Z]", "", m.group(1)))
        pos = m.end()
    return " ".join(got) if sum(map(len, got)) == total else None


#: A printed answer the blogger ended with a dash: "PINCH POINT - PINCH...".
#: That is the answer as they meant it, and an enumeration disagreeing with it
#: is the typo -- "(5)" for (5,5) -- so it is never cut down to fit.
DASH_ENDED = re.compile(r"^[^a-z\u2013\u2014]*?[A-Z!?.']\s*(?:[\u2013\u2014]|-\s)")


def enum_fits(printed, enum):
    """Has this printed answer the letter count its enumeration gives?"""
    counts = [int(n) for n in re.findall(r"\d+", enum or "")]
    return printed is not None and len(re.sub(r"[^A-Z]", "", printed)) == sum(counts)


def answer_line(line):
    """printed_answer, for a line that may instead be a clue.

    A clue can open in capitals -- "RIP, weightlifter? Sentimental stuff
    (4-6)", "WASP, say, taking the vote... (10)" -- and it ends in its
    enumeration, which the capitals it opens with do not have the length of.
    An answer printed with its count, "SLOUGH (6)", does.
    """
    printed = printed_answer(line)
    e = ENUM.search(line)
    if printed and e and not enum_fits(printed, e.group(1)):
        return None
    return printed


def is_answer(rest):
    """The letters of this line's answer, or None if it is a clue.

    A light is contiguous letters, so a comma means a word break in one era
    and a wordplay join in another (RICE,PAPER against A,CADE,MIA) and neither
    survives into the answer.
    """
    word = printed_answer(rest)
    return None if word is None else re.sub(r"[^A-Z]", "", word)


def printed_enumeration(printed):
    """ "ROLLER COASTER" -> "6,7", "SHOW-JUMPERS" -> "4-7"; None if no letters."""
    parts = re.split(r"([ ,\-\u2013\u2014]+)", printed)
    out = ""
    for i, part in enumerate(parts):
        if i % 2:
            out += "-" if re.search(r"[\-\u2013\u2014]", part) else ","
        else:
            n = len(re.sub(r"[^A-Z]", "", part))
            if not n:
                return None
            out += str(n)
    return out or None


def answer_words(printed):
    """The words of a printed answer: "YORKSHIRE DALES" -> ["YORKSHIRE", "DALES"]."""
    return [w for w in (re.sub(r"[^A-Z]", "", part)
                        for part in WORD_BREAK.split(printed)) if w]


def link_lights(match, direction):
    """The lights a linked head names, in the order the answer runs through them.

    None when the numbers are not a linked head: two names for the same light
    ("10/10, but I'm in Denver airport") is a blogger writing prose, and the
    order the lights are printed in is the only thing that says which letters
    go where, so a repeat has nothing to say.
    """
    lights = [(int(match.group(1)),
               DIRECTION_OF.get((match.group(2) or "").lower(), direction))]
    for number, suffix in LINK_PART.findall(match.group(3)):
        lights.append((int(number),
                       DIRECTION_OF.get(suffix.lower(), direction)))
    return None if len(set(lights)) != len(lights) else lights


def link_pieces(lights, printed, enum):
    """Which letters of a linked answer belong to which light, or None to refuse.

    A light boundary inside a linked answer is a WORD boundary — that is how
    this corpus reads every split answer — so the printed answer's own words
    are the only slice points there are. One word per light is therefore the
    one case the blog settles; with more words than lights it does not say
    which break is the light break, and nothing chooses between COME HELL /
    OR HIGH WATER and COME HELL OR HIGH / WATER. Refused, never guessed: a
    wrong split reconstructs a wrong grid that nobody can see is wrong.

    Fewer words than lights is not a linked answer at all — a light cannot be
    part of a word — so the line opened with numbers that meant something else
    ("4/7 of 19 is a very small amount") and is read as the clue its first
    number names.

    The enumeration is the cross-check, not the slicer: it and the answer come
    off different lines, so a disagreement between them means one was misread.
    It only gets a vote when it counts the whole answer, because a blogger who
    prints a linked clue's enumeration as the LEADING light's count alone —
    "(8)" over LAUGHING GEAR — is not disagreeing about anything.
    """
    words = answer_words(printed)
    if len(words) < len(lights):
        return [(lights[0], "".join(words))]
    if len(words) != len(lights) or min(len(w) for w in words) < MIN_LIGHT:
        return None
    counts = [int(n) for n in re.findall(r"\d+", enum or "")]
    if sum(counts) == sum(len(w) for w in words) and counts != [len(w) for w in words]:
        return None
    return list(zip(lights, words))


def continuation_target(clue):
    """The number a "See N" clue points at, or None if this clue is a real one."""
    m = CONTINUATION.match(clue or "")
    return int(m.group(1)) if m else None


#: How many lines after a clue its enumeration may pick the answer out of.
CLUED_REACH = 2

#: The number an unnumbered clue carries until number_orphans places it.
ORPHAN = 0


def number_orphans(entries):
    """Give each unnumbered clue the one number it can be, or drop it.

    A list runs in number order, so an unnumbered clue printed between 11 and
    13 across is a light numbered 12 -- the one number between its neighbours
    that its direction does not already have. When there are two such numbers
    it is dropped, and so is a whole-grid guess like "the one number no light
    carries": the missing number may be a different light the blogger left
    out, and a guessed number reconstructs a wrong grid.
    """
    kept = []
    for e in entries:
        if e["number"] != ORPHAN:
            kept.append(e)
            continue
        same = [x for x in entries if x["direction"] == e["direction"]]
        mine = same.index(e)
        before = [x["number"] for x in same[:mine] if x["number"] != ORPHAN]
        after = [x["number"] for x in same[mine + 1:] if x["number"] != ORPHAN]
        if not before or not after:
            continue
        taken = {x["number"] for x in same}
        free = [n for n in range(before[-1] + 1, after[0]) if n not in taken]
        if len(free) == 1:
            e["number"] = free[0]
            kept.append(e)
    entries[:] = kept


def one_entry_per_light(entries):
    """One light, one entry — two answers on one light is a list no grid fits.

    A linked group emits an entry for every light it covers and the blogger
    may ALSO have printed one of those lights on a line of its own. Where the
    two agree the repeat is dropped.

    Where they disagree, the light is already spoken for and the continuation
    is the one in the wrong place: the blog numbered it without a direction —
    "7/10", not "7/10dn" — so it took the direction of the heading its clue
    was printed under, and the other direction is the only one left for it.
    """
    seen, kept = {}, []
    for e in entries:
        key = (e["number"], e["direction"])
        if seen.get(key) == e["answer"]:
            continue
        if key in seen and continuation_target(e["clue"]) is not None:
            other = "down" if e["direction"] == "across" else "across"
            if (e["number"], other) not in seen:
                e["direction"] = other
                key = (e["number"], other)
        seen[key] = e["answer"]
        kept.append(e)
    entries[:] = kept


def trim_continuations(entries):
    """Take back the letters a leader printed that belong to another light.

    Some bloggers print a linked answer once under its leading light and then
    print it AGAIN under the continuation, whose clue is "See 3": LAUGHING
    GEAR at 3 down and GEAR at 18 across. Left alone that is one light four
    letters too long and one light counted twice, which is a light list no
    grid fits. The continuation's own printing is exact, so the leader gives
    those letters back.

    The leader is found by its letters, not by its direction: "See 3" does not
    say which 3, and the light whose answer ENDS in the continuation's answer
    is the one that is carrying it. A number where both directions would
    answer is left alone.
    """
    by_number = {}
    for e in entries:
        by_number.setdefault(e["number"], []).append(e)
    for e in entries:
        target = continuation_target(e["clue"])
        if target is None:
            continue
        leaders = [x for x in by_number.get(target, [])
                   if x is not e and len(x["answer"]) > len(e["answer"])
                   and x["answer"].endswith(e["answer"])]
        if len(leaders) == 1:
            leader = leaders[0]
            leader["answer"] = leader["answer"][:-len(e["answer"])]


def parse_post(post):
    """One post to its entries. Returns None for anything that is not a puzzle."""
    cats = post.get("categories", [])
    series = next((SERIES[c] for c in cats if c in SERIES), None)
    if series is None:
        return None

    entries, unsplit = read_entries(lines(post["content"]["rendered"]))
    if not entries and not unsplit:
        return None
    number = puzzle_number(post)
    rec = {
        "post_id": post["id"], "date": post["date"][:10], "slug": post["slug"],
        "link": post.get("link"), "series": filed_series(post, series, number),
        "number": number,
        "title": html.unescape(post.get("title", {}).get("rendered", "")),
        "entries": entries,
    }
    if unsplit:
        rec["unsplit"] = unsplit
    return rec


def read_entries(rendered):
    """(entries, unsplit) off a post's flattened lines: every light the clue
    list names, with its clue, answer and enumeration, and the linked clues
    whose split the post does not settle."""
    entries, unsplit = [], []
    direction, lights, clue, enum, head_clue = None, None, None, None, None
    # A bare number cell owns the line after it: in the table eras the clue
    # (or the answer) sits in the next cell, and a clue that opens with a
    # number -- "24-hour periods", "10 pence secured", "3D viewer" -- is that
    # light's clue, not a new light.
    bare = False
    # Lines after a clue still read by its enumeration: the answer, or one
    # aside first ("…He's so sappy, I just can't help it!") and then it.
    just_clued = 0
    # A light is answered once, so a number line naming one that already has
    # its answer is the blogger's prose -- "1 SEN = 1/100th of a yen" under
    # 12's answer -- not the light again. A number that merely goes backwards
    # is left alone: that is a typo ("28" for 18), and refusing it would take
    # every light after the typo with it. A post with no Down heading at all
    # starts its Down list where the numbers restart at 1 or 2.
    headed_down = any(HEADING.match(ln) and HEADING.match(ln).group(1).lower()
                      == "down" for ln in rendered)
    last, answered = 0, set()

    def flush(printed):
        nonlocal last, clue, enum
        if not lights or not printed:
            return
        # Some bloggers copy the clue without its enumeration. The answer
        # they print under it has the word breaks, so the count is theirs.
        # A count typed malformed -- "(10", "{10)", "(7),", "(3.4)" -- is replaced by
        # the well-formed one when its total is the answer's.
        if enum is None and clue and not CONTINUATION.match(clue):
            enum = printed_enumeration(printed)
            loose = LOOSE_ENUM.search(clue)
            if loose:
                typed = re.sub(r"[.\s]+", ",", loose.group(1).strip())
                if enum_fits(printed, typed):
                    enum = typed
                clue = f"{clue[:loose.start()]} ({enum})" if enum else clue
            elif enum and not WORDED_ENUM.search(clue):
                clue = f"{clue} ({enum})"
        # "(35)" over HAY FEVER: the blog dropped the comma from (3,5). Read
        # as the printed answer's words when their counts are its digits.
        words = printed_enumeration(printed)
        if (enum and words and re.fullmatch(r"\d+", enum) and not enum_fits(printed, enum)
                and re.sub(r"\D", "", words) == enum):
            enum = words
            m = ENUM.search(clue or "")
            clue = f"{clue[:m.start()]}({enum})" if m else clue
        if lights[0][1] == direction:  # a linked group sits at its leader
            last = max(last, lights[0][0])
        if len(lights) == 1:
            answered.add(lights[0])
        letters = re.sub(r"[^A-Z]", "", printed)
        pieces = ([(lights[0], letters)] if len(lights) == 1
                  else link_pieces(lights, printed, enum))
        if pieces is None:            # a linked clue whose split the blog
            unsplit.append({          # does not settle: reported, not guessed
                "lights": [[n, d] for n, d in lights],
                "answer": letters, "enumeration": enum,
            })
            return
        # link_pieces handing back one light for a head that named several is
        # it saying those numbers were never a linked head, so the numbers are
        # part of the clue and go back into its text.
        text = head_clue if len(pieces) < len(lights) else clue
        leader = pieces[0][0][0]
        for i, ((n, d), piece) in enumerate(pieces):
            entries.append({
                "number": n, "direction": d, "answer": piece,
                # The corpus's leader form: the WHOLE answer's enumeration sits
                # on the light that carries the clue and every continuation
                # carries null, pointing back with the "See N" the blog writes.
                "clue": text if i == 0 else (f"See {leader}" if text else None),
                "enumeration": enum if i == 0 else None,
            })
        if len(lights) > 1:
            entries[-len(pieces)].update(_head=lights[1:], _plain=clue)

    for ln in rendered:
        if not ln:
            continue
        stray = STRAY_NUMBER.match(ln)
        if stray:
            ln = stray.group(1) or stray.group(2)
        # DOWN and ACROSS are answers too: under a clue still waiting for its
        # answer, a heading-shaped line its enumeration counts is that answer.
        if HEADING.match(ln) and not (lights and clue and enum_fits(ln.upper(), enum)):
            heading = HEADING.match(ln).group(1).lower()
            if direction is None and heading == "across":
                # Whatever came before the Across list is the blogger's
                # preamble -- "1ac END UP went straight in", then a glossary
                # line "DDCDH: DD/CD hybrid" to answer it -- not the puzzle.
                entries.clear()
                unsplit.clear()
                answered.clear()
            direction = heading
            last = 0
            lights, clue, enum = None, None, None
            continue
        rest, these = None, None
        owned, bare = bare, False
        clued = just_clued > 0 and lights is not None
        just_clued = max(just_clued - 1, 0)
        m = NUMBERED.match(ln)
        if owned and m and (not m.group(2) or BARE_SUFFIX.match(m.group(2))):
            owned = False             # another bare number: a new light
        # A linked head only counts inside a clue list. Before the first
        # heading the blogger is writing about the puzzle, and "23ac / 24ac
        # CHARACTER ACTORS" in a preamble is a remark, not a clue.
        m = LINK_HEAD.match(ln) if direction and not owned else None
        if m:
            these = link_lights(m, direction)
            rest = LINK_TAIL.sub("", ln[m.end():]).strip()
            # A line of prose can open with numbers too ("4, 11 & 15 were also
            # pretty similar"). What a clue line always ends in is its own
            # enumeration, and a bare head cell ends at the numbers, so
            # anything else after them is somebody talking about the puzzle.
            if rest and not (ENUM.search(rest) or printed_answer(rest)):
                these = None
        if these is None and not owned:
            m = NUMBERED.match(ln)
            if m:
                number, rest = int(m.group(1)), m.group(2).strip()
                way = direction or "across"
                suffix = BARE_SUFFIX.match(rest)
                if suffix:
                    rest, way = "", DIRECTION_OF[suffix.group(1).lower()]
                if (direction == "across" and not headed_down and not suffix
                        and number <= 2 < last):
                    direction, way, last = "down", "down", 0
                if (number, way) not in answered:
                    these = [(number, way)]
        if these is not None:
            lights, clue, enum = these, None, None
            head_clue = ln if len(these) > 1 else None
            if not rest:              # a bare number cell; its row follows
                bare = True
                continue
            printed = answer_line(rest)
            if printed:               # number and answer on one line
                flush(printed)
                lights = None
                continue
            clue = rest               # number and clue text on one line
            e = ENUM.search(rest)
            enum = e.group(1).strip() if e else None
            just_clued = CLUED_REACH
            continue
        printed = answer_line(ln)
        # A linked answer may carry only its leading light's count, "(8)" over
        # LAUGHING GEAR, so only an answer with none is read off it there.
        if clued and (printed is None or (len(lights) == 1
                                          and not enum_fits(printed, enum)
                                          and not DASH_ENDED.match(ln))):
            printed = answer_by_enum(ln, enum) or printed
        if printed and lights is not None:
            flush(printed)
            lights, clue, enum = None, None, None
            continue
        # A clue cell broken by <br /> -- "…get together for" then
        # "programme (4,5)" -- is one clue, up to the fragment with its count.
        if lights is not None and clue and enum is None and clued and not CONTINUATION.match(clue):
            clue = f"{clue} {ln}"
            e = ENUM.search(clue)
            enum = e.group(1).strip() if e else None
            continue
        # The cell after a bare number is its clue even without an
        # enumeration, once it is not the answer.
        if lights is not None and clue is None and (
                ENUM.search(ln) or CONTINUATION.match(ln)
                or (owned and re.search(r"[a-z]", ln))):
            clue = ln                 # the clue arrived in its own cell
            e = ENUM.search(ln)
            enum = e.group(1).strip() if e else None
            just_clued = CLUED_REACH
        elif lights is None and direction and ENUM.search(ln):
            # A clue with no light of its own: its number was left off, or
            # was one already answered ("7" typed for 17). number_orphans
            # decides what it is once the whole list has been read.
            lights, clue = [(ORPHAN, direction)], ln
            enum = ENUM.search(ln).group(1).strip()
            just_clued = CLUED_REACH

    number_orphans(entries)
    one_entry_per_light(entries)
    trim_continuations(entries)
    leader_form(entries)
    return entries, unsplit


def leader_form(entries):
    """Put the whole linked answer's count on the light its head leads.

    A blogger may print only the leading light's own count under a linked
    head -- "11a and 7d He and I are prominent members... (8)" over PERIODIC
    TABLE -- and may print the leader's letters alone, the continuation's on a
    line of its own: "2d & 3 Down ... (6)" MOULIN, then "3d See 2 Down (5)"
    ROUGE. Once every light the head names is a "See" pointing back at it, the
    head was a real link, so its numbers leave the clue, the leader counts the
    whole answer, one part per light in the head's order (each continuation's
    own count, else its answer's length, which the blog's split printed), and
    every continuation carries null. A head that names a light no pointer
    answers stays as the clue's text: "4/7 of 19 is..." is prose.
    """
    for lead in entries:
        head, plain = lead.pop("_head", None), lead.pop("_plain", None)
        if not head:
            continue
        rest = []
        for n, d in head:
            points = [e for e in entries if e["number"] == n and e is not lead
                      and continuation_target(e.get("clue")) == lead["number"]]
            points.sort(key=lambda e: e["direction"] != d)
            rest.append(points[0] if points else None)
        if None in rest:
            continue
        if plain is not None:
            lead["clue"] = plain
        own = lead.get("enumeration")
        if not own:
            continue
        if enum_fits(lead["answer"], own):
            whole = ",".join([own] + [e.get("enumeration") or str(len(e["answer"]))
                                      for e in rest])
            lead["enumeration"] = whole
            m = ENUM.search(lead["clue"] or "")
            if m:
                lead["clue"] = f"{lead['clue'][:m.start()]}({whole})"
        # A pointer loses its own count and its glued suffix ("See 12a (5)" is
        # "See 12 across"), and names the leader's direction where the other
        # light numbered N, the one in its own direction, would be read instead.
        twin = any(e["number"] == lead["number"] and e["direction"] != lead["direction"]
                   for e in entries)
        for e in rest:
            e["enumeration"] = None
            m = ENUM.search(e["clue"])
            text = e["clue"][:m.start()].rstrip() if m else e["clue"]
            glued = GLUED_POINTER.match(text)
            if glued:
                text = f"See {glued.group(1)} {DIRECTION_OF[glued.group(2).lower()]}"
            if twin and e["direction"] != lead["direction"] and not NAMED_WAY.match(text):
                text = f"{text} {lead['direction']}"
            e["clue"] = text


def leader_numbers(entries):
    """The numbers that lead a linked group, named by their continuations."""
    return {n for n in (continuation_target(e.get("clue")) for e in entries) if n}


def enum_agrees(entry, leaders=()):
    """Does the answer have the length its own enumeration claims?

    The two come from different halves of the post — the clue line and the
    answer line — so agreement is the one check that catches a misread answer
    without a human reading it. Entries with no enumeration cannot be checked,
    and neither can a light that LEADS a linked group: it holds the whole
    group's enumeration by the corpus's leader form and only its own letters,
    so the two disagree by design.
    """
    if not entry.get("enumeration") or entry.get("number") in leaders:
        return None
    want = sum(int(n) for n in re.findall(r"\d+", entry["enumeration"]))
    return want == len(entry["answer"])


def plausible(rec):
    lo_hi = PLAUSIBLE.get(rec["series"])
    return lo_hi is None or lo_hi[0] <= len(rec["entries"]) <= lo_hi[1]


def run(write=True, limit=None):
    files = sorted(POSTS.glob("*.json"))
    if limit:
        files = files[:limit]
    if not files:
        print(f"no cached posts in {POSTS} — run tools/fetch_wp_blog.py timesforthetimes")
        return None
    by_year, by_series, odd, unsplit = {}, {}, [], []
    kept = withtext = checked = agreed = 0
    out = open(OUT, "w", encoding="utf-8") if write else None
    for f in files:
        post = json.loads(f.read_text(encoding="utf-8"))
        rec = parse_post(post)
        if rec is None:
            continue
        ok = plausible(rec)
        year = rec["date"][:4]
        texts = sum(1 for e in rec["entries"] if e["clue"])
        full_text = texts >= len(rec["entries"]) * 0.8
        y = by_year.setdefault(year, [0, 0, 0])
        y[0] += 1
        y[1] += ok
        y[2] += ok and full_text
        s = by_series.setdefault(rec["series"], [0, 0, 0])
        s[0] += 1
        s[1] += ok
        s[2] += ok and full_text
        if not ok:
            odd.append((rec["slug"], rec["series"], len(rec["entries"])))
            continue
        kept += 1
        withtext += full_text
        for u in rec.get("unsplit", ()):
            unsplit.append((rec["slug"], rec["series"], u))
        leaders = leader_numbers(rec["entries"])
        for e in rec["entries"]:
            a = enum_agrees(e, leaders)
            if a is not None:
                checked += 1
                agreed += a
        if out:
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if out:
        out.close()
    return {"files": len(files), "kept": kept, "withtext": withtext,
            "checked": checked, "agreed": agreed, "unsplit": unsplit,
            "odd": odd, "by_year": by_year, "by_series": by_series}


def report(r):
    print(f"{r['files']} cached post(s) read")
    print(f"{r['kept']} puzzle(s) parsed with a plausible entry count")
    print(f"  {r['withtext']} with clue text, "
          f"{r['kept'] - r['withtext']} number+answer only")
    print(f"{len(r['odd'])} post(s) failed the entry-count check "
          f"(parsed, not emitted)")
    print(f"{len(r['unsplit'])} linked clue(s) the blog does not split "
          f"(no entry emitted for their lights)")
    if r["checked"]:
        pct = 100.0 * r["agreed"] / r["checked"]
        print(f"{r['agreed']}/{r['checked']} entries ({pct:.1f}%) have the "
              f"answer length their own enumeration claims")
    print("\nBY SERIES  (parsed / plausible / with clue text)")
    for s, (n, ok, t) in sorted(r["by_series"].items(), key=lambda kv: -kv[1][0]):
        print(f"  {s:<22} {n:>5} / {ok:>5} / {t:>5}")
    print("\nBY YEAR  (parsed / plausible / with clue text)")
    for y, (n, ok, t) in sorted(r["by_year"].items()):
        print(f"  {y}  {n:>4} / {ok:>4} / {t:>4}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--status", action="store_true",
                    help="parse and report coverage without writing the output")
    ap.add_argument("--limit", type=int, help="read only the first N posts")
    ap.add_argument("--show", help="parse one cached post id or slug and print it")
    ap.add_argument("--odd", action="store_true",
                    help="list the posts that failed the entry-count check")
    a = ap.parse_args()

    if a.show:
        for f in POSTS.glob("*.json"):
            post = json.loads(f.read_text(encoding="utf-8"))
            if a.show in (str(post["id"]), post["slug"]):
                print(json.dumps(parse_post(post), ensure_ascii=False, indent=2))
                return 0
        print(f"no cached post {a.show}")
        return 2

    r = run(write=not a.status, limit=a.limit)
    if r is None:
        return 1
    report(r)
    if a.odd:
        print("\nFAILED THE ENTRY-COUNT CHECK")
        for slug, series, n in r["odd"][:80]:
            print(f"  {n:>3}  {series:<22} {slug}")
        print("\nLINKED CLUES LEFT UNSPLIT")
        for slug, series, u in r["unsplit"][:80]:
            where = " ".join(f"{n}{d[0]}" for n, d in u["lights"])
            print(f"  {where:<14} {u['answer']:<26} ({u['enumeration']}) "
                  f"{series:<16} {slug}")
    if not a.status:
        print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
