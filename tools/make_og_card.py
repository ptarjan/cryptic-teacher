#!/usr/bin/env python3
"""Fill the social card with a real clue and its real hint ladder.

The card used to be a crossword grid beside the tagline. A grid says "crossword"
and stops there — it shows the thing people already know they find impenetrable.
What this site actually does is take one clue apart, and that is a picture: the
clue, the definition marked, the indicator marked, the letters found where they
were hiding, and the answer still covered up. Someone who has never solved a
cryptic can read the whole card in four seconds and know both what the site is
and that the trick is learnable.

Everything on it comes out of a published puzzle. Nothing here is retyped — the
wording of the rungs is the app's own, the family labels and blurbs are checked
against app.js's FAMILIES table on every build, and the clue, definition,
indicator and hidden span are read from the annotation. A card that disagrees
with the app is a build error rather than a thing nobody noticed. The highlight
in particular is computed, not marked up: it finds where the answer's letters
actually sit inside the clue and fails if they don't.

Every puzzle page gets its own card, showing the best clue in that puzzle
(2026-08-08). One shared card meant a hundred pages unfurling as the same
picture of somebody else's crossword; the clue on the card is now from the
puzzle you are actually sharing. "Best" is decided by score(), and it is a
question about the PICTURE rather than about the clue's merit as a clue — these
are published setters, so soundness is a given and what varies is whether the
mechanism survives being looked at for four seconds in a thumbnail. A clue
qualifies only if its mechanism is visible in a still image: the answer's
letters underlined where they hide, or the anagram fodder shown unscrambled, or
failing those an indicator to point at. An unqualified puzzle keeps the site
card rather than shipping a weak one.

The answer is the one thing every card withholds, so no card may contain it —
check_no_answer() enforces that on the rendered HTML, because the rungs are
assembled from annotation prose that frequently does give it away.

Usage:
  python3 tools/make_og_card.py                    # site card, in tools/og_card.html
  python3 tools/make_og_card.py 30066              # best clue in one puzzle
  python3 tools/make_og_card.py 30066 4-down       # a clue you picked yourself
  python3 tools/make_og_card.py --out /tmp/c.html 30066
  python3 tools/make_og_card.py --list             # puzzles that can carry a card
"""
import html
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import app_tables  # noqa: E402 — app.js's tables, read from app.js
from fetch_puzzle import puzzle_files  # noqa: E402 — one glob for every tool
CARD = REPO / "tools" / "og_card.html"
APP = REPO / "app.js"
# Quiptic 1,393 3D: "Woman found in Oregon or Maine (5)" — five short words, a
# definition anyone can check, and NORMA sitting across the state line. This is
# the card for the homepage and for any puzzle that has no card of its own.
DEFAULT_PUZZLE = "quiptic-1393"
DEFAULT_ENTRY = "3-down"

# The card has to describe a clue in the same words as the app that teaches it,
# so it renders from the app's own table rather than a port of it. See
# tools/app_tables.py for why there is no copy here to keep in step.
FAMILIES = app_tables.families()
FALLBACK_FAMILY = app_tables.FALLBACK_FAMILY


def family_of(type_):
    return app_tables.family_of(type_, FAMILIES)


def first_sentence(text):
    """The head of a blurb: enough for a thumbnail, still the app's own words."""
    head = re.split(r"\s+—\s+|(?<=[.!?])\s+", text.strip())[0].rstrip(".") + "."
    # The clue beside it is set from a newspaper's own copy, curly quotes and
    # all; a straight apostrophe in our prose two lines below it looks like a
    # rendering fault rather than a choice.
    return head.replace("'", "’")


# Every "number" below is really a puzzle ID ("cryptic-30089") — the key a file
# is named by. The number is what the CARD prints; this is what finds it.
def load(pid):
    text = (REPO / f"puzzles/{pid}.js").read_text(encoding="utf-8")
    body = text.split("/*JSON-START*/", 1)[1].rsplit("/*JSON-END*/", 1)[0]
    return json.loads(body)


def norm(s):
    return (s.replace("’", "'").replace("‘", "'")
             .replace("–", "-").replace("—", "-").lower())


def span_of(clue, phrase, start=0):
    """Where `phrase` sits in `clue`, tolerant of the typographic apostrophes and
    dashes the papers use and the annotations sometimes don't."""
    i = norm(clue).find(norm(phrase), start)
    if i < 0:
        raise SystemExit(f"og card: {phrase!r} is not in the clue {clue!r}")
    return i, i + len(phrase)


def hidden_span(clue, fragment, answer):
    """Where the answer's letters lie inside the fragment, spaces and all.

    Computed rather than declared: this is the one part of the card that makes a
    factual claim about the clue's letters, so it is checked against them. A
    hidden word runs contiguously once you ignore everything that isn't a letter,
    which is exactly what makes it findable in the first place.
    """
    fs, fe = span_of(clue, fragment)
    letters = [i for i in range(fs, fe) if clue[i].isalpha()]
    want = re.sub(r"[^A-Z]", "", answer.upper())
    for k in range(len(letters) - len(want) + 1):
        run = letters[k:k + len(want)]
        if "".join(clue[i] for i in run).upper() == want:
            return run[0], run[-1] + 1
    raise SystemExit(f"og card: {answer!r} is not hidden in {fragment!r} — the "
                     "card's whole point is that it is, so this is a real error")


def marked_clue(clue, marks):
    """The clue with non-overlapping spans wrapped. Overlap is a design error, so
    it raises rather than nesting tags and rendering something misleading."""
    marks = sorted(marks)
    for (_, prev_end, _), (start, _, _) in zip(marks, marks[1:]):
        if start < prev_end:
            raise SystemExit("og card: two marks overlap in the clue")
    out, at = [], 0
    for start, end, cls in marks:
        out.append(html.escape(clue[at:start]))
        out.append(f'<mark class="{cls}">{html.escape(clue[start:end])}</mark>')
        at = end
    out.append(html.escape(clue[at:]))
    return "".join(out)


def bare_clue(entry):
    """The clue without its enumeration, plus the enumeration on its own."""
    clue = re.sub(r"\s*\(\d+[\d,\-\s]*\)\s*$", "", entry["clue"])
    return clue, entry["clue"][len(clue):].strip()


def plan(entry):
    """What this clue's card would show, or None if it can't carry one.

    Three things can make a mechanism visible in a still picture, and a clue
    needs at least one of them: the answer's own letters underlined where they
    hide, the anagram fodder laid out unscrambled, or an indicator word to point
    at. Everything else — a charade with no indicator, say — is a card that just
    reprints a clue and marks the definition, which teaches nobody anything they
    couldn't have guessed.
    """
    ann = entry.get("annotation") or {}
    if not ann.get("definition") or not ann.get("answer") or not entry.get("clue"):
        return None
    clue, _ = bare_clue(entry)
    if len(clue) > 78:
        return None                                 # no type size makes this fit
    t = (ann.get("type") or "").lower()
    p = {"clue": clue, "ann": ann, "hidden": None, "fodder": None,
         "indicator": None, "family": family_of(ann.get("type"))}
    try:
        p["definition"] = span_of(clue, ann["definition"])
        for ind in ann.get("indicators") or []:
            p["indicator"] = p["indicator"] or ind
            span_of(clue, ind)                      # must be quotable from the clue
        if "hidden" in t and "reversal" not in t:
            block = next((b for b in ann.get("blocks") or []
                          if b.get("clueFragment")), None)
            if block:
                p["hidden"] = hidden_span(clue, block["clueFragment"], ann["answer"])
        fodder = ((ann.get("anagram") or {}).get("fodder") or "").strip()
        # A fodder line is only worth showing when it is the whole story. With a
        # second mechanism stacked on top, the letters on the card are not the
        # letters that get shuffled, and a card that shows the wrong ones is
        # worse than a card that shows none.
        # And only when the reader can find every one of those letters on the
        # card. Plenty of "anagram" annotations quietly substitute first: 30,079's
        # fodder is CRUELLY AT MAN, but the clue says "crew", and a rung reading
        # "Shuffle CRUELLY AT MAN" over a clue with no MAN in it asks the reader to
        # take a step the picture never shows. Such a clue keeps its indicator rung.
        if fodder and t == "anagram" and all(
                re.search(rf"(?<![A-Za-z]){w}(?![A-Za-z])", clue, re.I)
                for w in re.findall(r"[A-Za-z]+", fodder)):
            p["fodder"] = fodder
    except SystemExit:
        return None                                 # annotation and clue disagree
    if not (p["hidden"] or p["fodder"] or p["indicator"]):
        return None
    return p


def score(entry, p):
    """How good a PICTURE this clue makes. Higher is better; ties break on id.

    Not a judgement of the clue — these are published setters and the clue is
    theirs. What varies from clue to clue is whether a stranger scrolling past
    can take the mechanism in at a glance, and that is mostly about length and
    about whether the trick can be pointed at rather than described.
    """
    ann, clue = p["ann"], p["clue"]
    s = 0.0
    # Visible mechanism, in the order of how much of itself a still image shows.
    if p["hidden"]:
        s += 6                  # the answer is right there, underlined
    elif p["fodder"]:
        s += 3                  # the letters are there, just not in order
    elif p["indicator"]:
        s += 1
    # Length. The clue is the biggest thing on the card and it is read in a
    # thumbnail; past about sixty characters it wraps to a third line and the
    # rungs get squeezed. Very short clues are legible but say too little.
    n = len(clue)
    s -= max(0, n - 58) * 0.10
    s -= max(0, 24 - n) * 0.15
    # A definition at one end is the rule the card's second rung teaches; a clue
    # that demonstrates it is worth more than one that quietly doesn't.
    ds, de = p["definition"]
    if ds == 0 or de == len(clue):
        s += 1
    # Answers spelled out as blanks along the footer: past about fifteen letters
    # the row of boxes runs out of card to sit on.
    letters = len(re.sub(r"[^A-Za-z]", "", ann["answer"]))
    s -= max(0, letters - 15) * 0.5
    # Surface reading. Punctuation that splits the clue into fragments (colons,
    # semicolons, ellipses) reads as machinery rather than as a sentence, and a
    # sentence is what makes someone stop scrolling.
    if re.search(r"[:;]|\.\.\.|…", clue):
        s -= 1
    if len(clue.split()) < 4:
        s -= 1
    return s


def pick(number):
    """The best clue in one puzzle, as (entry_id, plan), or (None, None).

    Candidates are tried in score order and the first one that actually draws
    wins. Scoring can't see everything that makes a card impossible — a rung
    that turns out to name the answer, two marks that overlap — and a puzzle
    with twenty-nine other clues in it should quietly show one of those rather
    than fail the nightly build over its best one.
    """
    ranked = []
    for entry in load(number)["entries"]:
        p = plan(entry)
        if p:
            ranked.append(((score(entry, p), entry["id"]), entry, p))
    for _, entry, p in sorted(ranked, key=lambda r: r[0], reverse=True):
        try:
            compose(entry, p)
        except SystemExit:
            continue
        return entry["id"], p
    return None, None


IND_QUOTES = "\"'‘’“”"


def indicator_gloss(ann, ind, family):
    """The annotation's own words for why this indicator means what it means.

    Written wordplay explanations almost always open by glossing the indicator —
    "'Some' tells you to take only part of what follows", "'Put in' flags a
    hidden word" — and that sentence is better than anything the card can say
    generically, because it is about THIS word rather than about the family. The
    card was writing its own line and ignoring one already sitting in the file.

    Only the opening clause is taken. The rest of a walkthrough is about the
    clue, not the indicator ("...and the answer straddles the comma"), and the
    rung is one line read in a thumbnail. Anything that won't fit, doesn't lead
    with the indicator, or gives the answer away returns None and the caller
    keeps its generic wording — a card should never be blocked by prose.

    Borrowed prose that names the wrong mechanism is dropped rather than fatal:
    check_prose_stays_in_family guards words the CARD chose, and these are the
    annotator's. annotate_prompt.md carries the same rule for the source.
    """
    walk = (ann.get("walkthrough") or "").strip()
    if not walk:
        return None
    first = re.split(r"(?<=[.!?])\s+", walk)[0]
    m = re.match(rf"[{IND_QUOTES}]?{re.escape(ind)}[{IND_QUOTES}]?\s+(.+)",
                 first, re.I)
    if not m:
        return None
    tail = re.split(r"\s*[;:]\s*|,\s+(?:and|so|but|which|then)\s+|\s+—\s+",
                    m.group(1))[0].rstrip(" .,;:—")
    if not tail or len(ind) + 1 + len(tail) > 64:
        return None
    answer = re.sub(r"[^A-Za-z]+", r"[^A-Za-z]*", ann["answer"].strip())
    if re.search(rf"(?<![A-Za-z]){answer}(?![A-Za-z])", tail, re.I):
        return None
    head = f'<mark class="ind">{html.escape(ind)}</mark> {html.escape(tail)}'
    try:
        check_prose_stays_in_family(head, family)
    except RuntimeError:
        return None
    return head


def rungs_for(p):
    """Three rungs, in the app's order and close to the app's words.

    Trimmed, because a card is read in a thumbnail — but never rephrased into a
    claim the app doesn't make, and never carrying the answer.
    """
    ann = p["ann"]
    label, blurb, _ = p["family"]
    out = [(html.escape(label), html.escape(first_sentence(blurb)))]
    out.append((f'The definition is <mark class="def">'
                f'{html.escape(ann["definition"])}</mark>',
                "Everything else is wordplay."))
    gloss = (indicator_gloss(ann, p["indicator"], p["family"])
             if p["indicator"] else None)
    if p["hidden"] and p["indicator"]:
        out.append((gloss or
                    (f'<mark class="ind">{html.escape(p["indicator"])}</mark> '
                     "says it is hidden here"),
                    "The underline is the answer, in order, straddling the words."))
    elif p["fodder"]:
        # Name the indicator, don't just paint it. The card marks it pink in the
        # clue either way, and a pink word the rungs never mention reads as an
        # unexplained claim — on 30,079 it was enough to make me doubt a correct
        # annotation, when the actual answer was that the obvious-looking
        # candidate was inside the fodder and this word was the real one.
        n = len(re.sub(r"[^A-Za-z]", "", p["fodder"]))
        head = f'Shuffle <span class="fodder">{html.escape(p["fodder"])}</span>'
        if p["indicator"]:
            head = (f'<mark class="ind">{html.escape(p["indicator"])}</mark> '
                    f'says to shuffle <span class="fodder">'
                    f'{html.escape(p["fodder"])}</span>')
        out.append((head,
                    f"{n} letters, and the enumeration says where they land."))
    elif p["indicator"]:
        out.append((gloss or
                    (f'The instruction is <mark class="ind">'
                     f'{html.escape(p["indicator"])}</mark>'),
                    "It tells you what to do with the rest."))
    else:
        out.append(("The answer is hiding in the clue itself",
                    "The underline is where its letters sit, in order."))
    return out


def check_no_answer(clue_html, prose_html, answer):
    """No card may print the answer.

    The rungs are built out of annotation prose written for a reader who has
    already given up — `gives` fields and block notes say the answer outright —
    so this is a live hazard rather than a theoretical one. It is only ever a
    whole-word match: a hidden-word card deliberately shows the answer's LETTERS
    inside other words, and that is the card working, not the card leaking.

    The two halves are read differently, and the difference is the whole trick.
    Tags are stripped from the clue with nothing in their place, because the
    marks sit mid-word and MERE hiding in "shimmered" must not be pulled apart
    into a word by removing the underline around it. In the rungs they are
    stripped to a space instead, so that an answer wrapped in its own tag can't
    hide inside a join.
    """
    word = re.sub(r"[^A-Za-z]+", r"[^A-Za-z]*", answer.strip())
    pattern = rf"(?<![A-Za-z]){word}(?![A-Za-z])"
    for part, joiner in ((clue_html, ""), (prose_html, " ")):
        if re.search(pattern, html.unescape(re.sub(r"<[^>]+>", joiner, part)), re.I):
            raise SystemExit(f"og card: the card prints the answer {answer!r}, "
                             "which is the one thing it exists not to do")


# Phrases that name a device rather than describe one. Each belongs on its own
# family's cards and is a wrong signpost anywhere else. Deliberately short: only
# wording that in a cryptic can mean nothing but this one mechanism. "Says",
# "said" and "inside" are ordinary English in an instruction — listing them would
# flag "says to shuffle" and teach nobody anything.
FAMILY_SIGNALS = {
    "Sound": ("aloud", "out loud", "sounds like", "we hear", "reportedly",
              "spoken", "pronounced", "homophone"),
    "Rearrangement": ("anagram", "shuffle", "scrambled", "jumbled", "rearranged"),
    "Extraction": ("hidden", "hiding", "buried", "concealed"),
    "Alteration": ("reversed", "backwards", "turned around", "inserted"),
}


def check_prose_stays_in_family(prose_html, family):
    """The card's own words may not borrow another family's signal.

    Rung 3 on a hidden-word card read "<ind> says so out loud" from the day the
    cards shipped. "Out loud" was meant as "announces itself", but in a cryptic
    it means one thing only — the answer is a soundalike. So the same card said
    Extraction on rung 1 and pointed at Sound on rung 3, about the same clue, to
    a reader who is there precisely because they don't yet know the difference.

    Only the card's OWN prose is scanned. The marks hold the setter's words and
    the annotator's, and an Extraction clue is perfectly entitled to an indicator
    that reads like a homophone; that is the clue, not the card mis-teaching it.

    Not a SystemExit, unlike every other check here, because pick() treats that
    as "this clue can't draw" and quietly tries the next one. A borrowed signal
    is a defect in the template, not in the clue, so falling back would hide it
    behind a different card and ship it on all the rest. It should stop a build.

    CALIBRATION (2026-08-08, every card the 23 eligible puzzles can draw): 0
    flagged once the hidden rung was reworded — this is the fix held in place,
    not a backlog.
    """
    own = FAMILY_SIGNALS.get(family[0], ())
    # The marks and the fodder are quoted from the clue and the annotation. Only
    # the words the card puts around them are ours to be judged on.
    mine = re.sub(r'<mark\b[^>]*>.*?</mark>|<span class="fodder">.*?</span>',
                  " ", prose_html, flags=re.S)
    mine = html.unescape(re.sub(r"<[^>]+>", " ", mine)).lower()
    for label, signals in FAMILY_SIGNALS.items():
        if label == family[0]:
            continue
        for sig in signals:
            if sig in mine and sig not in own:
                raise RuntimeError(
                    f"og card: this {family[0]} card's own prose says {sig!r}, which "
                    f"names the {label} mechanism. The card would teach one device "
                    f"in rung 1 and point at another lower down — reword it.")


def compose(entry, p, number=0):
    """The card's inner HTML for one clue, or SystemExit if it can't be drawn."""
    ann, clue = p["ann"], p["clue"]
    _, enumeration = bare_clue(entry)

    marks = [(*p["definition"], "def")]
    if p["hidden"]:
        marks.append((*p["hidden"], "hit"))
    for ind in ann.get("indicators") or []:
        marks.append((*span_of(clue, ind), "ind"))
    try:
        clue_html = marked_clue(clue, marks)
    except SystemExit:
        # Overlapping marks are a real defect in the annotation, but not one
        # worth failing a nightly image build over: the definition alone still
        # makes an honest card.
        clue_html = marked_clue(clue, [(*p["definition"], "def")])

    steps = "".join(
        f'<li><span class="n">{i + 1}</span><span class="t"><b>{head}</b>'
        f'<span class="sub">{tail}</span></span></li>'
        for i, (head, tail) in enumerate(rungs_for(p)))

    # The answer is the one thing the card withholds. A reader who has followed
    # the three rungs can now work it out — which is the whole sales pitch, and
    # it only works if we don't say it for them.
    dots = "".join('<span class="dot"></span>' if c.isalnum() else
                   '<span class="gap"></span>' for c in ann["answer"])

    # Type size by clue length, because the clue is the only element on the card
    # whose height nobody controls. At 52px a clue wraps at about forty
    # characters, and a two-line clue at that size pushes the answer row off the
    # bottom of the 630px card — which is how the first cut of this shipped a
    # 30,066 card with its bottom row sliced in half. The thresholds are set so
    # that nothing ever takes three lines; plan() refuses anything longer still.
    size = " small" if len(clue) > 64 else " long" if len(clue) > 36 else ""
    check_no_answer(clue_html, steps, ann["answer"])
    check_prose_stays_in_family(steps, p["family"])
    return f"""<!--CARD-START {number} {entry["id"]}-->
  <div class="clue{size}">{clue_html} <span class="enum">{html.escape(enumeration)}</span></div>
  <ol class="rungs">{steps}</ol>
  <div class="held"><span class="lbl">Answer</span><span class="dots">{dots}</span></div>
  <!--CARD-END-->"""


def build(number, entry_id=None):
    """One puzzle's card: the clue you named, or the best clue it has."""
    entries = load(number)["entries"]
    if entry_id is None:
        entry_id, p = pick(number)
        if not entry_id:
            raise SystemExit(f"og card: no clue in puzzle {number} can carry a card")
    else:
        entry = next((e for e in entries if e["id"] == entry_id), None)
        if not entry:
            raise SystemExit(f"og card: puzzle {number} has no entry {entry_id}")
        p = plan(entry)
        if not p:
            raise SystemExit(f"og card: {number} {entry_id} has no annotation the "
                             "card can draw — see plan()")
    return compose(next(e for e in entries if e["id"] == entry_id), p, number)


def alt_text(number, entry_id=None):
    """What a screen reader gets. Describes the card, so it is generated beside
    it — an alt text that has drifted from the picture is worse than none."""
    if entry_id is None:
        entry_id, p = pick(number)
    else:
        p = plan(next(e for e in load(number)["entries"] if e["id"] == entry_id))
    if not p:
        return None
    shown = ("the answer underlined where it hides in the clue" if p["hidden"] else
             "the letters to be rearranged spelled out" if p["fodder"] else
             "the indicator marked")
    entry = next(e for e in load(number)["entries"] if e["id"] == entry_id)
    return (f'The cryptic clue "{entry["clue"]}" taken apart: the definition '
            f'marked, {shown}, and the answer itself left blank.')


def render(number, entry_id, out_path):
    text = CARD.read_text(encoding="utf-8")
    new, n = re.subn(r"<!--CARD-START.*?<!--CARD-END-->",
                     lambda _: build(number, entry_id), text, flags=re.S)
    if n != 1:
        raise SystemExit("og_card.html is missing its <!--CARD-START--> markers")
    Path(out_path).write_text(new, encoding="utf-8")


def main():
    args = sys.argv[1:]
    if "--list" in args:
        # Which puzzles can carry a card, for make_og.sh to loop over. Printed
        # rather than globbed by the shell so that "has a usable annotation" is
        # decided in exactly one place.
        for f in puzzle_files():
            if pick(f.stem)[0]:
                print(f.stem)
        return 0
    out = CARD
    if "--out" in args:
        i = args.index("--out")
        out = Path(args[i + 1])
        del args[i:i + 2]
    number = args[0] if args else DEFAULT_PUZZLE
    entry_id = args[1] if len(args) > 1 else (DEFAULT_ENTRY if not args else None)
    render(number, entry_id, out)
    chosen = entry_id or pick(number)[0]
    print(f"og card: puzzle {number} {chosen} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
