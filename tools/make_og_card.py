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
wording of the rungs is lifted from app.js's ladderSteps() by hand ONCE, and the
clue, definition, indicator and hidden span are read from the annotation, so a
card that disagrees with the app is a build error rather than a thing nobody
noticed. The highlight in particular is computed, not marked up: it finds where
the answer's letters actually sit inside the clue and fails if they don't.

The clue is a hidden word on purpose. It is the one family whose mechanism is
fully visible in a still image: the answer is right there in the clue and the
reader gets the aha without being told it. An anagram card would just be a claim.

Usage:  python3 tools/make_og_card.py [puzzle] [entry-id]   (run by make_og.sh)
"""
import html
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CARD = REPO / "tools" / "og_card.html"
# Quiptic 1,393 3D: "Woman found in Oregon or Maine (5)" — five short words, a
# definition anyone can check, and NORMA sitting across the state line.
DEFAULT_PUZZLE = 1393
DEFAULT_ENTRY = "3-down"


def load(number):
    text = (REPO / f"puzzles/{number}.js").read_text(encoding="utf-8")
    import json
    body = text.split("/*JSON-START*/", 1)[1].rsplit("/*JSON-END*/", 1)[0]
    return json.loads(body)


def span_of(clue, phrase, start=0):
    """Where `phrase` sits in `clue`, tolerant of the typographic apostrophes and
    dashes the papers use and the annotations sometimes don't."""
    def norm(s):
        return (s.replace("’", "'").replace("‘", "'")
                 .replace("–", "-").replace("—", "-").lower())
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
    want = answer.replace(" ", "").upper()
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


def build(number, entry_id):
    puz = load(number)
    entry = next((e for e in puz["entries"] if e["id"] == entry_id), None)
    if not entry:
        raise SystemExit(f"og card: puzzle {number} has no entry {entry_id}")
    ann = entry.get("annotation") or {}
    if "hidden" not in (ann.get("type") or ""):
        raise SystemExit(f"og card: {entry_id} is a {ann.get('type')!r}; the card's "
                         "layout shows the answer hiding in the clue, which only a "
                         "hidden word does")
    clue = re.sub(r"\s*\(\d+[\d,\-]*\)\s*$", "", entry["clue"])
    enumeration = entry["clue"][len(clue):].strip()
    block = (ann.get("blocks") or [{}])[0]

    ds, de = span_of(clue, ann["definition"])
    inds = [span_of(clue, i) for i in ann.get("indicators", [])]
    hs, he = hidden_span(clue, block["clueFragment"], ann["answer"])

    # The rungs, in the app's order and close to the app's words. Trimmed, because
    # a card is read in a thumbnail — but never rephrased into a claim the app
    # doesn't make.
    rungs = [
        ("Extraction",
         "The answer&rsquo;s letters are already sitting in the clue, in order."),
        (f'The definition is <mark class="def">{html.escape(ann["definition"])}</mark>',
         "Everything else is wordplay."),
        (f'<mark class="ind">{html.escape(ann["indicators"][0])}</mark> '
         "says so out loud",
         "Two states, carrying letters across the border."),
    ]
    steps = "".join(
        f'<li><span class="n">{i + 1}</span><span class="t"><b>{head}</b>'
        f'<span class="sub">{tail}</span></span></li>'
        for i, (head, tail) in enumerate(rungs))

    clue_html = marked_clue(clue, [(ds, de, "def"), (hs, he, "hit")]
                            + [(s, e, "ind") for s, e in inds])
    # The answer is the one thing the card withholds. A reader who has followed
    # the three rungs can now read it straight off the clue — which is the whole
    # sales pitch, and it only works if we don't say it for them.
    dots = "".join('<span class="dot"></span>' for _ in ann["answer"])

    return f"""<!--CARD-START {number} {entry_id}-->
  <div class="clue">{clue_html} <span class="enum">{html.escape(enumeration)}</span></div>
  <ol class="rungs">{steps}</ol>
  <div class="held"><span class="lbl">Answer</span><span class="dots">{dots}</span>
    <span class="held-note">&mdash; yours to spot, not ours to hand over</span></div>
  <!--CARD-END-->"""


def main():
    number = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PUZZLE
    entry_id = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_ENTRY
    text = CARD.read_text(encoding="utf-8")
    new, n = re.subn(r"<!--CARD-START.*?<!--CARD-END-->", lambda _: build(number, entry_id),
                     text, flags=re.S)
    if n != 1:
        raise SystemExit("og_card.html is missing its <!--CARD-START--> markers")
    CARD.write_text(new, encoding="utf-8")
    print(f"og card: puzzle {number} {entry_id}, hidden span checked")


if __name__ == "__main__":
    main()
