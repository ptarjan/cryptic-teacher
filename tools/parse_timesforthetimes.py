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

Reads the cache tools/fetch_timesforthetimes.py writes; never the network.
"""
import argparse
import html
import json
import re
import sys
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
#: are watching?" -- and that is clue text, not clue number 5.
NUMBERED = re.compile(r"^(\d{1,2})(?![.:]\d)\s*[.):]?\s*(.*)$")
#: An answer is the line's leading run of capitals, ended by whichever mark
#: the wordplay hangs off — a dash, an equals sign or a semicolon. A plain
#: hyphen ends it only when a space is on either side of it, or WELL-KNOWN
#: truncates to WELL: "NISAN -Granny NAN" is a dash typed short.
ANSWER = re.compile(
    r"^([A-Z][A-Z0-9'\u2019()\[\]+,. \-]{1,70}?)"
    r"(?:\s*(?:[\u2013\u2014=;]|-\s|-\s*$|$)|\s+-)")
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
BRACED = re.compile(r"\{[^}]*\}")
ENUM = re.compile(r"\((\d+[\d,\-–\s]*)\)\s*$")
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
#: "See 15", "See 3 (9)", "See 12 across" — a light whose clue lives on another
#: light. tools/normalise_linked_enumerations.py reads the same shape; this is
#: how the whole corpus spells a continuation.
CONTINUATION = re.compile(r"^\s*See\s+(\d+)\b", re.IGNORECASE)
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


def lines(rendered):
    """Flatten post HTML to the lines the era-independent reader walks."""
    text = DELETED.sub("", rendered)
    text = BREAKS.sub("\n", text)
    text = TAG.sub("", text)
    text = html.unescape(text)
    text = BRACED.sub("", text)
    text = text.replace("\t", "\n").replace("\xa0", " ")
    return [re.sub(r"\s+", " ", ln).strip() for ln in text.split("\n")]


def puzzle_number(post):
    m = NUMBER_IN.search(post.get("slug", ""))
    if not m:
        m = NUMBER_IN.search(html.unescape(post.get("title", {}).get("rendered", "")))
    return int(m.group(1)) if m else None


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
    rest = DROPPED_LETTERS.sub("", WORDPLAY_COMMA.split(_drop_asides(rest), 1)[0])
    m = ANSWER.match(rest)
    if not m:
        return None
    word = ANSWER_MARKUP.sub("", m.group(1))
    letters = re.sub(r"[^A-Z]", "", word)
    if len(letters) < 3 or len(word) > 60:
        return None
    return word


def is_answer(rest):
    """The letters of this line's answer, or None if it is a clue.

    A light is contiguous letters, so a comma means a word break in one era
    and a wordplay join in another (RICE,PAPER against A,CADE,MIA) and neither
    survives into the answer.
    """
    word = printed_answer(rest)
    return None if word is None else re.sub(r"[^A-Z]", "", word)


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

    entries, unsplit = [], []
    direction, lights, clue, enum, head_clue = None, None, None, None, None

    def flush(printed):
        if not lights or not printed:
            return
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

    for ln in lines(post["content"]["rendered"]):
        if not ln:
            continue
        if HEADING.match(ln):
            direction = HEADING.match(ln).group(1).lower()
            lights, clue, enum = None, None, None
            continue
        rest, these = None, None
        # A linked head only counts inside a clue list. Before the first
        # heading the blogger is writing about the puzzle, and "23ac / 24ac
        # CHARACTER ACTORS" in a preamble is a remark, not a clue.
        m = LINK_HEAD.match(ln) if direction else None
        if m:
            these = link_lights(m, direction)
            rest = LINK_TAIL.sub("", ln[m.end():]).strip()
            # A line of prose can open with numbers too ("4, 11 & 15 were also
            # pretty similar"). What a clue line always ends in is its own
            # enumeration, and a bare head cell ends at the numbers, so
            # anything else after them is somebody talking about the puzzle.
            if rest and not (ENUM.search(rest) or printed_answer(rest)):
                these = None
        if these is None:
            m = NUMBERED.match(ln)
            if m:
                these = [(int(m.group(1)), direction or "across")]
                rest = m.group(2).strip()
        if these is not None:
            lights, clue, enum = these, None, None
            head_clue = ln if len(these) > 1 else None
            if not rest:              # a bare number cell; its row follows
                continue
            printed = printed_answer(rest)
            if printed:               # number and answer on one line
                flush(printed)
                lights = None
                continue
            clue = rest               # number and clue text on one line
            e = ENUM.search(rest)
            enum = e.group(1).strip() if e else None
            continue
        printed = printed_answer(ln)
        if printed and lights is not None:
            flush(printed)
            lights, clue, enum = None, None, None
            continue
        if lights is not None and clue is None and (ENUM.search(ln)
                                                    or CONTINUATION.match(ln)):
            clue = ln                 # the clue arrived in its own cell
            e = ENUM.search(ln)
            enum = e.group(1).strip() if e else None

    one_entry_per_light(entries)
    trim_continuations(entries)
    if not entries and not unsplit:
        return None
    rec = {
        "post_id": post["id"], "date": post["date"][:10], "slug": post["slug"],
        "link": post.get("link"), "series": series, "number": puzzle_number(post),
        "entries": entries,
    }
    if unsplit:
        rec["unsplit"] = unsplit
    return rec


def leader_numbers(entries):
    """The numbers that lead a linked group, named by their continuations."""
    return {n for n in (continuation_target(e["clue"]) for e in entries) if n}


def enum_agrees(entry, leaders=()):
    """Does the answer have the length its own enumeration claims?

    The two come from different halves of the post — the clue line and the
    answer line — so agreement is the one check that catches a misread answer
    without a human reading it. Entries with no enumeration cannot be checked,
    and neither can a light that LEADS a linked group: it holds the whole
    group's enumeration by the corpus's leader form and only its own letters,
    so the two disagree by design.
    """
    if not entry["enumeration"] or entry.get("number") in leaders:
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
        print(f"no cached posts in {POSTS} — run tools/fetch_timesforthetimes.py")
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
