"""Where each of an annotation's definitions sits in its clue.

An annotation's `definitions` is a list of {text, at, note}: `text` the clue
words verbatim, `at` their offset in the clue's `text` (its words; the
enumeration is kept apart) in Unicode code points, so that
clue[at:at + len(text)] == text. Writers give `text`; `place` fills `at`.

Most definitions occur once in their clue. When one occurs more than once,
`at` is the occurrence that, in order:

  1. stands as whole words (the "art" of "man's art", not of "Part"),
  2. does not overlap another definition of the same clue (a double
     definition's "Down" is not the one inside "as in Watership Down?"),
  3. touches the clue's start or end, with only spaces and punctuation
     between, since a definition sits at one end of a cryptic clue.

A text these leave ambiguous needs `at` written by hand; `place` refuses to
guess.
"""
import re
from groups import entry_id


def span_ok(d, clue):
    at = d.get("at")
    return (isinstance(at, int) and not isinstance(at, bool) and at >= 0
            and clue[at:at + len(d.get("text") or "")] == d.get("text"))


def _found(text, hay):
    out, i = [], hay.find(text)
    while i >= 0:
        out.append(i)
        i = hay.find(text, i + 1)
    return out


def candidates(text, clue):
    """Offsets of `text` in `clue`, narrowed by rule 1 where that leaves any."""
    found = _found(text, clue)

    def whole(i):
        j = i + len(text)
        return not ((i and clue[i - 1].isalnum() and text[0].isalnum())
                    or (j < len(clue) and clue[j].isalnum() and text[-1].isalnum()))
    return [i for i in found if whole(i)] or found


# Typed quotes differ from printed ones; each maps one code point to one, so a
# folded match sits at the same offsets in the real clue.
QUOTES = str.maketrans("\u2018\u2019\u201c\u201d", "''\"\"")


def respell(text, clue):
    """`text` spelt as `clue` prints it, when they differ only in quote marks."""
    if not text or text in clue:
        return text
    i = clue.translate(QUOTES).find(text.translate(QUOTES))
    return clue[i:i + len(text)] if i >= 0 else text


def _at_an_end(clue, i, n):
    return not re.search(r"\w", clue[:i]) or not re.search(r"\w", clue[i + n:])


def place(definitions, clue):
    """`definitions` with every `at` filled and the list in clue order.

    An `at` that already points at its text is kept. Raises ValueError naming
    each text that is not in the clue or that the rules leave ambiguous."""
    defs = [dict(d) for d in definitions]
    for d in defs:
        if isinstance(d.get("text"), str):
            d["text"] = respell(d["text"], clue)
    todo = {k: candidates(d.get("text") or "", clue)
            for k, d in enumerate(defs) if not span_ok(d, clue)}
    for k in todo:
        defs[k].pop("at", None)
    progress = True
    while todo and progress:
        progress = False
        spans = [(d["at"], d["at"] + len(d["text"])) for d in defs if "at" in d]
        for k, found in list(todo.items()):
            n = len(defs[k]["text"])
            free = [i for i in found if not any(i < b and a < i + n for a, b in spans)] or found
            ends = [i for i in free if _at_an_end(clue, i, n)]
            pick = free if len(free) == 1 else ends if len(ends) == 1 else None
            if pick:
                defs[k]["at"] = pick[0]
                del todo[k]
                progress = True
                break
    if todo:
        why = []
        for k, found in todo.items():
            text = defs[k].get("text")
            if not found:
                why.append(f"definition {text!r} is not in the clue {clue!r}")
            else:
                why.append(f"definition {text!r} occurs {len(found)} times in {clue!r} "
                           f"(at {', '.join(map(str, found))}) and the rules in "
                           f"tools/definitions.py do not pick one: give its `at`")
        raise ValueError("; ".join(why))
    return sorted(defs, key=lambda d: d["at"])


def place_puzzle(puzzle):
    """`puzzle` with every annotation's definitions placed; raises ValueError,
    naming the entry, for one `place` cannot place."""
    for e in puzzle.get("entries", []):
        ann = e.get("annotation")
        if not isinstance(ann, dict) or not isinstance(ann.get("definitions"), list):
            continue
        if not all(isinstance(d, dict) for d in ann["definitions"]):
            continue
        try:
            ann["definitions"] = place(ann["definitions"], e["clue"].get("text", ""))
        except ValueError as err:
            raise ValueError(f"{puzzle.get('id')} {entry_id(e)}: {err}") from None
    return puzzle


def texts(ann):
    """The definition texts of an annotation, in clue order."""
    return [d["text"] for d in (ann or {}).get("definitions") or [] if d.get("text")]
