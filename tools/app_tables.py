#!/usr/bin/env python3
"""app.js's teaching tables, read out of app.js.

`FAMILIES` and `TYPE_BLURBS` are the words a learner actually reads when the app
names what kind of clue they are looking at. Three other things need the same
words — the OG card, the Minute Cryptic word-count comparison, and the prompt the
annotation run follows — and each of them used to keep its own transcription.

Transcriptions rot. `make_og_card.py` even compared its copy against app.js on
every build and printed a clear failure when they diverged; the copy still sat
wrong for weeks, because a check that can only complain does not fix anything.
So there are no copies now: app.js is a browser file with no build step, so it
stays the source and everything else parses it. `tools/smoke_test.js` does the
same from the JavaScript side.

    python3 tools/app_tables.py        # print both tables

Anything added to those tables in app.js appears here with no edit. If a parse
comes back empty the table has moved or changed shape, and every caller raises
rather than quietly teaching from an empty vocabulary.
"""
import re
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app.js"


def _block(src, opener, closer):
    if opener not in src:
        raise SystemExit(f"app_tables: {APP.name} has no `{opener}` — the table "
                         f"moved or changed shape, and nothing else has a copy "
                         f"of it to fall back on.")
    return src.split(opener, 1)[1].split(closer, 1)[0]


def families(src=None):
    """[(label, blurb, (type-part substring, ...)), ...] in app.js's order.

    Order is load-bearing: familyOf takes the first match, so the list is sorted
    by which mechanism dominates a compound type.
    """
    src = src if src is not None else APP.read_text(encoding="utf-8")
    out = []
    for chunk in _block(src, "const FAMILIES = [", "\n  ];").split("{ label:")[1:]:
        label = re.search(r'^\s*"([^"]*)"', chunk).group(1)
        blurb = re.search(r'blurb:\s*"((?:[^"\\]|\\.)*)"', chunk).group(1)
        keys = tuple(re.findall(r't\.includes\("([^"]+)"\)', chunk))
        out.append((label, blurb.replace('\\"', '"'), keys))
    if not out:
        raise SystemExit("app_tables: FAMILIES parsed empty")
    return out


def type_blurbs(src=None):
    """[(type part, blurb), ...] — one sentence per mechanism, app.js's order."""
    src = src if src is not None else APP.read_text(encoding="utf-8")
    block = _block(src, "const TYPE_BLURBS = [", "\n  ];")
    out = [(k, v.replace('\\"', '"')) for k, v in
           re.findall(r'\["((?:[^"\\]|\\.)*)",\s*"((?:[^"\\]|\\.)*)"\]', block)]
    if not out:
        raise SystemExit("app_tables: TYPE_BLURBS parsed empty")
    return out


def family_of(type_, fams=None):
    """The family a (possibly compound) type belongs to. First match wins."""
    t = (type_ or "").lower()
    for fam in (fams if fams is not None else families()):
        if any(k in t for k in fam[2]):
            return fam
    return FALLBACK_FAMILY


# Shown when a type matches no family. The app has the same fallback; a card or a
# comparison that invented its own wording here would be describing a clue in
# words the app never says.
FALLBACK_FAMILY = ("Wordplay",
                   "The clue has a definition at one end and wordplay at the other.",
                   ())


def main():
    for label, blurb, keys in families():
        print(f"{label}\n  types: {', '.join(keys)}\n  {blurb}")
    print()
    for part, blurb in type_blurbs():
        print(f"{part}\n  {blurb}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
