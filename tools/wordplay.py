#!/usr/bin/env python3
"""A clue's wordplay as one line the model writes, and the tree a puzzle stores.

The model writes an expression; `parse` turns it into the stored tree,
`evaluate` works out the letters at every node and refuses a tree whose
letters are not the answer, and `render` writes a tree back as the expression.

Grammar
-------
    [clue words]LETTERS   a leaf: these clue words give LETTERS, before any
                          operation on them (papers gives ID; rev makes DI)
    [clue words]          a leaf whose letters are the words as written
                          (anagram fodder, hidden-word text)
    [in#2]                the second "in" in the clue; #n picks a repeat
    LETTERS               letters with no clue words (a preamble's piece, or
                          the letters a del/sub indicator names: del(x, H))
    A + B                 a charade, in answer order (inside ana() it is the
                          fodder's pieces, stored as the anagram's parts)
    op<indicator>(...)    an operation; <indicator words> follow the op they
                          signal, one <...> per phrase; `+<under>` is an
                          indicator on the charade
    ana(x)                anagram of x's letters (the answer slice decides order);
                          ana(x + y + z) shuffles several pieces as one pool
    rev(x)                x backwards
    ins(outer, inner)     inner put inside outer (the answer decides where)
    del(from, removed)    removed taken out of from (the answer decides where)
    hid(x)                letters hidden in x's words: hid([say no before]YNOBE),
                          or hid([say no before]) to let the answer pick them
    sound(x, SPELT)       x sounds like SPELT, the letters entered
    spoon(a, b)           a and b with their first consonants swapped;
                          spoon(a, b, SPELT) when the swap is by sound
    sub(x, OLD, NEW)      OLD in x replaced by NEW
    cyc(x)                x with letters moved from one end to the other
    pal(x)                x, which reads the same backwards; pal() with no x
                          when the answer itself is all the wordplay
    first(x) last(x) middle(x) outer(x) alt(x) regular(x) nth(n)(x)
                          letters picked from x's words: first letter (or
                          each word's first), middle letter(s) or all but the
                          ends, first and last, alternate letters, every
                          2nd/3rd, the nth
    cd([words])           cryptic definition: the words, no letters
    comp(x, y)            composite (subtractive) anagram: the letters of x are
                          the answer plus the letters of y, rearranged, so the
                          answer is an anagram of x with y taken out:
                          comp<sadly>([thirsted], [it's]) for DERTH
    reverse([words], "reading")
                          a reverse clue: the words read as wordplay that would
                          produce a word of the answer, and "reading" spells the
                          answer in the pieces they build, capitals joined by
                          spaces or +: reverse([What makes pets], "OUT + STEP")
                          for OUTSTEP (out signals an anagram of STEP: pets). It
                          is the whole wordplay; the definition stays a `def`
    rebus([words], "reading")
                          a rebus: the words are a picture (letters,
                          figures, layout) and "reading" says what it shows,
                          naming the picture's own capitals or figures:
                          rebus([HIJKLMNO], "H to O") for WATER. It is the whole
                          wordplay; with no `def` it is the whole clue
A double definition has no wordplay: two definitions and no expression.

Unchecked nodes: a tree filed before trees were checked may hold an
`"unchecked": true` node: an op node or leaf whose `gives` is taken as
stated, its parts shown but not checked, where the old blocks could not be
rebuilt step by step (a deletion of scattered letters, a selection from a
synonym). The expression has no way to write one, so a new annotation
cannot add any.

Stored tree: a leaf is {"words", "at", "gives"?, "note"?} ({"gives"} alone
for letters with no words); an op is {"op", "indicators"?: [{"text", "at",
"note"?}], "parts": [...]}, with "spelt" on homophone/spoonerism and "n" on
nth. "at" is filled when `parse` is given the clue.

An anagram's parts are its fodder, one pool of letters: `ana(x + y)` stores
x and y as the anagram's own parts, never a charade under it, since nothing
is joined in order (fodder_pool, and validate_annotations refuses a charade
directly under an anagram).

Shapes that read wrongly are refused for a new annotation (validate_annotations):
join pieces in one charade, never a charade with no indicator inside a charade;
give every op that needs one its indicator word (ana, rev, ins, del, hid, sound,
first/last/...); a cryptic definition is one cd([clue words]); no clue word sits
in two leaves or indicators, or in both the definition and the wordplay (unless
&lit); a selection over several words is one op over one multi-word leaf; a
leaf that gives a stretch of its own words is the selection, deletion or hidden
word as an op; the wordplay is never one leaf; every charade piece has clue words
(a bare-letters piece belongs in a leaf of the clue word that supplies it); an
anagram's container is the outer step, ins(outer, ana(x)), not ana(ins(...)).
"""
import argparse
import collections
import functools
import json
import re
import sys
import unicodedata

# Expression name -> stored op.
OPS = {"ana": "anagram", "rev": "reversal", "ins": "container", "del": "deletion",
       "hid": "hidden", "sound": "homophone", "spoon": "spoonerism",
       "sub": "substitution", "cyc": "cycling", "cd": "cryptic", "pal": "palindrome",
       "rebus": "rebus", "comp": "composite", "reverse": "reverse",
       "first": "first", "last": "last", "middle": "middle", "outer": "outer",
       "alt": "alternate", "regular": "regular", "nth": "nth"}
NAMES = {v: k for k, v in OPS.items()}
SELECT = ("first", "last", "middle", "outer", "alternate", "regular", "nth")
# How many parts each op takes: (fewest, most).
# ana() takes one argument; a charade written there becomes its parts (_fodder_parts).
ARITY = {"anagram": (1, 1), "reversal": (1, 1), "container": (2, 2), "deletion": (2, 2),
         "hidden": (1, 1), "homophone": (2, 2), "spoonerism": (2, 3),
         "substitution": (3, 3), "cycling": (1, 1), "cryptic": (1, 9), "palindrome": (0, 1),
         "rebus": (2, 2), "composite": (2, 2), "reverse": (2, 2),
         **{s: (1, 1) for s in SELECT}}
# A search that grows past this many candidate strings stops: no clue needs it.
CAP = 20000


class WordplayError(ValueError):
    """A parse or evaluation failure, worded for the model to act on."""


_NOT_AZ = re.compile(r"[^A-Z]")


@functools.lru_cache(maxsize=1 << 16)
def _letters_of_str(s):
    return _NOT_AZ.sub("", unicodedata.normalize("NFD", s).upper())


def letters(s):
    """A-Z, accents folded (É is E), everything else dropped."""
    return _letters_of_str(str(s or ""))


# ---------- parse ----------

class _Parser:
    def __init__(self, text):
        self.s = text
        self.i = 0

    def fail(self, msg):
        raise WordplayError(f"wordplay {self.s!r}: {msg} at column {self.i} "
                            f"(…{self.s[self.i:self.i + 15]!r})")

    def ws(self):
        while self.i < len(self.s) and self.s[self.i].isspace():
            self.i += 1

    def peek(self):
        self.ws()
        return self.s[self.i] if self.i < len(self.s) else ""

    def take(self, ch):
        if self.peek() != ch:
            self.fail(f"expected {ch!r}")
        self.i += 1

    def until(self, close):
        j = self.s.find(close, self.i)
        if j < 0:
            self.fail(f"no closing {close!r}")
        out, self.i = self.s[self.i:j], j + 1
        return out

    def indicators(self):
        out = []
        while self.peek() == "<":
            self.i += 1
            text = self.until(">").strip()
            if not text:
                self.fail("empty <indicator>")
            out.append({"text": text})
        return out

    def expr(self):
        parts, inds = [self.term()], []
        while self.peek() == "+":
            self.i += 1
            inds += self.indicators()
            parts.append(self.term())
        if len(parts) == 1:
            if inds:
                self.fail("an indicator on a charade needs a '+'")
            return parts[0]
        node = {"op": "charade", "parts": parts}
        if inds:
            node["indicators"] = inds
        return node

    def term(self):
        c = self.peek()
        if c == "(":
            self.i += 1
            node = self.expr()
            self.take(")")
            return node
        if c == "[":
            self.i += 1
            words = self.until("]").strip()
            if not words:
                self.fail("empty [clue words]")
            leaf = {"words": words}
            m = re.compile(r"[A-Z]+").match(self.s, self.i)
            if m:
                leaf["gives"] = m.group()
                self.i = m.end()
            return leaf
        m = re.compile(r"[A-Za-z]+").match(self.s, self.i)
        if not m:
            self.fail("expected [clue words], LETTERS, '(' or an op")
        word = m.group()
        after = self.s[m.end():].lstrip()
        if word.isupper() and not after.startswith(("(", "<")):
            self.i = m.end()
            return {"gives": word}
        if word not in OPS:
            self.fail(f"unknown op {word!r}; ops are {', '.join(OPS)}")
        self.i = m.end()
        op = OPS[word]
        node = {"op": op}
        if op == "nth":
            self.take("(")
            n = re.compile(r"\s*(\d+)\s*").match(self.s, self.i)
            if not n:
                self.fail("nth needs a number: nth(3)(x)")
            node["n"] = int(n.group(1))
            self.i = n.end()
            self.take(")")
        inds = self.indicators()
        self.take("(")
        args = [] if op == "palindrome" and self.peek() == ")" else [self.expr()]
        while args and self.peek() == ",":
            self.i += 1
            args.append(self.quoted() if op in ("rebus", "reverse") else self.expr())
        self.take(")")
        inds += self.indicators()
        if inds:
            node["indicators"] = inds
        lo, hi = ARITY[op]
        if not lo <= len(args) <= hi:
            want = {"homophone": "sound(x, SPELT)", "spoonerism": "spoon(a, b) or spoon(a, b, SPELT)",
                    "container": "ins(outer, inner)", "deletion": "del(from, removed)",
                    "substitution": "sub(x, OLD, NEW)",
                    "rebus": 'rebus([words], "reading")',
                    "composite": "comp(fodder, taken out)",
                    "reverse": 'reverse([words], "PIECE + PIECE")'}.get(op, f"{word}(x)")
            self.fail(f"{word} takes {want}, got {len(args)} argument(s)")
        if op in ("homophone", "spoonerism") and len(args) == hi:
            spelt = args.pop()
            if set(spelt) != {"gives"}:
                self.fail(f"{word}'s last argument is the spelling entered, bare LETTERS")
            node["spelt"] = spelt["gives"]
        if op == "rebus":
            if "reading" not in args[1] or "words" not in args[0] or set(args[0]) - {"words"}:
                self.fail('rebus takes rebus([picture words], "what it reads as"): the clue words '
                          'with no letters, then the reading in double quotes')
            node["reading"] = args.pop()["reading"]
        if op == "reverse":
            if "reading" not in args[1] or "words" not in args[0] or set(args[0]) - {"words"}:
                self.fail('reverse takes reverse([clue words], "PIECE + PIECE"): the clue words '
                          'with no letters, then the answer in its pieces, in double quotes')
            node["reading"] = args.pop()["reading"]
        node["parts"] = _fodder_parts(args[0], self) if op == "anagram" else args
        return node

    def quoted(self):
        """A "reading": text in double quotes (rebus's second argument)."""
        if self.peek() != '"':
            self.fail('expected the reading in double quotes: rebus([words], "reading")')
        self.i += 1
        text = self.until('"').strip()
        if not text:
            self.fail("empty reading")
        return {"reading": text}


def _fodder_parts(arg, parser=None):
    """ana(x)'s stored parts: x's pieces when x is a charade (nested ones too),
    in the order written, since an anagram's fodder is one pool and nothing
    under it is joined in sequence. A join with an indicator of its own is
    refused: order means nothing to a pool, so a word between pieces is a link
    word, and an anagram indicator goes on ana<...>."""
    if arg.get("op") != "charade" or arg.get("unchecked"):
        return [arg]
    if arg.get("indicators") and parser is not None:
        words = ", ".join(repr(i["text"]) for i in arg["indicators"])
        parser.fail(f"ana(x + y) is one pool of letters, not a charade, so +<{words}> has nothing "
                    f"to order: leave a word that only joins the pieces out (it is a link word), "
                    f"and write an anagram indicator as ana<...>")
    return [q for p in parts_of(arg) for q in _fodder_parts(p, parser)]


def fodder_pool(node):
    """An anagram's fodder as one node: its part, or its parts as a run (a
    reading of the pool in stored order). Built fresh, so never a key of
    evaluate()'s result."""
    parts = parts_of(node)
    return parts[0] if len(parts) == 1 else {"op": "charade", "parts": parts}


def parse(text, clue=None):
    """The tree for expression `text`; with `clue`, every leaf and indicator
    gets its `at` (offset in the clue) and words not in the clue are refused."""
    p = _Parser(str(text or ""))
    if not p.peek():
        raise WordplayError("wordplay is empty: write the expression, or leave `wp` out "
                            "for a double definition")
    node = p.expr()
    if p.peek():
        p.fail("unexpected text after the expression")
    if clue is not None:
        locate(node, clue)
    return node


def _spans(node, bare=False):
    """(dict, key) for every indicator and leaf's words in tree order; with
    `bare`, letters with no clue words too, keyed by those letters."""
    for ind in node.get("indicators") or []:
        yield ind, "text"
    if "words" in node:
        yield node, "words"
    elif bare and "op" not in node:
        yield node, "gives"
    for part in node.get("parts") or []:
        yield from _spans(part, bare)


def find_at(clue, text, nth=1, taken=()):
    """Offset of the nth whole-word copy of `text` in `clue` (any copy if no
    whole-word one), skipping copies that overlap `taken` spans; None if absent.

    str.find, not re.finditer(re.escape(text)): the same non-overlapping
    copies, but a pattern per distinct text overflowed re's cache and compiled
    afresh nearly every call -- most of annotation.view()'s time, which every
    deploy pays per puzzle on a full reindex and render."""
    hits, h = [], clue.find(text)
    while h >= 0:
        hits.append(h)
        h = clue.find(text, h + (len(text) or 1))
    whole = [h for h in hits if (h == 0 or not clue[h - 1].isalnum())
             and (h + len(text) == len(clue) or not clue[h + len(text)].isalnum())]
    pool = whole or hits
    if nth == 1:
        free = [h for h in pool if not any(h < b and a < h + len(text) for a, b in taken)]
        pool = free or pool
    return pool[nth - 1] if len(pool) >= nth else None


def not_in_clue(text, clue, nth=1):
    """The refusal for words a span names that the clue does not hold, saying
    what to change: a repeat that has no such copy, words the clue has but not
    side by side (write each run as its own [..] piece), or words it lacks."""
    head = f"{text!r} is not in the clue {clue!r}: "
    low = clue.lower()
    if nth > 1:
        have = len(re.findall(re.escape(text.lower()), low))
        return head + (f"the clue has {have} copy of those words, so there is no copy #{nth}: "
                       f"drop the `#{nth}`" if have == 1 else f"the clue has {have} copies, "
                       f"so there is no copy #{nth}")
    words = re.findall(r"[\w'’]+", text.lower())
    absent = [w for w in words if w not in low]
    if len(words) > 1 and not absent:
        return head + ("each word is in the clue but not side by side: give each run of "
                       "clue words its own [..] piece (the words between belong to other pieces "
                       "or are link words)")
    if absent:
        return head + (f"{', '.join(repr(w) for w in absent)} {'is' if len(absent) == 1 else 'are'} "
                       f"not among its words: copy the clue words exactly")
    return head + "copy the clue words exactly"


def locate(node, clue, taken=()):
    """Fill `at` on every span of `node` from `clue`; `#n` suffixes pick the
    nth copy and come off the stored text.

    Spans that already have an `at` are claimed first, then the rest longest
    first (tree order among equals): a short span placed first takes the first
    free copy of its words even when that copy sits inside a longer span
    ("in" inside "lost in": genius-209 22A, "Short key, article lost in
    pilgrimage, in great journey"), leaving the clue's other "in" uncovered,
    so it was derived as a link word."""
    used = list(taken)
    todo = []
    for span, key in _spans(node):
        text, nth = span[key], 1
        m = re.fullmatch(r"(.+?)#(\d+)", text) if "#" in text else None
        if m and text not in clue:
            text, nth = m.group(1), int(m.group(2))
            span[key] = text
        if "at" in span:
            used.append((span["at"], span["at"] + len(text)))
        else:
            todo.append((span, text, nth, key))
    todo.sort(key=lambda t: -len(t[1]))
    low = clue.lower() if len(clue.lower()) == len(clue) else None
    repeated = {t.lower() for _, t, n, _ in todo if n > 1}
    for span, text, nth, key in todo:
        # "fruit" and "fruit#2" for "Fruit fly turning peeled fruit": the first
        # copy is capitalised, so counting exact-case copies finds one and the
        # run was told there is no copy #2 (51 refusals in 48h). A text the
        # tree repeats is counted without regard to case, both copies alike.
        at = None
        if low and text.lower() in repeated:
            at = find_at(low, text.lower(), nth, used)
        if at is None:
            at = find_at(clue, text, nth, used)
        if at is None and low:
            at = find_at(low, text.lower(), nth, used)
        if at is not None and clue[at:at + len(text)] != text:
            span[key] = text = clue[at:at + len(text)]
        if at is None:
            raise WordplayError(not_in_clue(text, clue, nth))
        span["at"] = at
        used.append((at, at + len(text)))
    return node


# ---------- render ----------

def render(node):
    """The expression for a tree: parse(render(t)) == t, `at` aside. An
    unchecked node renders as `?op(...)=GIVES`, which does not parse."""
    if node.get("unchecked") and "op" in node:
        inner = render({k: v for k, v in node.items() if k not in ("unchecked", "gives")})
        return f"?{inner}={node.get('gives', '')}"
    if "op" not in node:
        if "words" not in node:
            return node.get("gives", "")
        return f"[{node['words']}]{node.get('gives', '')}"
    inds = "".join(f"<{i['text']}>" for i in node.get("indicators") or [])
    op = node["op"]
    if op == "charade":
        out = []
        for k, part in enumerate(parts_of(node)):
            s = render(part)
            if part.get("op") == "charade":
                s = f"({s})"
            out.append(s)
        joiner = f" +{inds} " if inds else " + "
        return joiner.join(out) if not inds else out[0] + joiner + " + ".join(out[1:])
    if op == "anagram" and len(parts_of(node)) > 1:
        return f"ana{inds}({render(fodder_pool(node))})"
    args = [render(p) for p in parts_of(node)]
    if "spelt" in node:
        args.append(node["spelt"])
    if op in ("rebus", "reverse"):
        args.append(f'"{node.get("reading", "")}"')
    head = NAMES[op] + (f"({node['n']})" if op == "nth" else "")
    return f"{head}{inds}({', '.join(args)})"


# ---------- evaluate ----------

class _NeedTarget(Exception):
    """An anagram's order is only known against the answer."""


def leaf_letters(node):
    return letters(node["gives"] if "gives" in node else node.get("words"))


def parts_of(node):
    """An op's parts. A file stores no empty list (puzzle_schema.prune: an
    absent key means empty), so `pal()` over the answer alone is stored with
    no `parts` key and every reader goes through here."""
    return node.get("parts") or []


def lettered(parts):
    """The parts that give letters: an unchecked leaf filed with no letters (an
    unchecked `gives: ""`, a note riding along) gives none."""
    return [p for p in parts if not (p.get("unchecked") and not letters(p.get("gives")))]


def _words(node):
    """The letters of each word under a selection, when it is a plain leaf."""
    if "op" not in node and "gives" not in node:
        return [w for w in (letters(x) for x in re.split(r"[\s\-–—/]+", node["words"])) if w]
    return None


def _select(op, n, s, words):
    out = set()
    words = words or [s]
    if not s:
        return out
    if op == "first":
        out |= {s[0], "".join(w[0] for w in words)}
    elif op == "last":
        out |= {s[-1], "".join(w[-1] for w in words)}
    elif op == "middle":
        h = len(s) // 2
        out |= {s[h] if len(s) % 2 else s[h - 1:h + 1]}
        if len(s) > 2:
            out.add(s[1:-1])
    elif op == "outer":
        out |= {s[0] + s[-1]} if len(s) > 1 else set()
    elif op == "alternate":
        out |= {s[0::2], s[1::2]}
    elif op == "regular":
        out |= {s[k::step] for step in (2, 3) for k in range(step)}
    elif op == "nth":
        if len(s) >= n:
            out.add(s[n - 1])
        if all(len(w) >= n for w in words):
            out.add("".join(w[n - 1] for w in words))
    return {x for x in out if x}


def _onset(s):
    m = re.match(r"[^AEIOU][^AEIOUY]*|", s)
    return m.group() if m.group() != s else s[:1]


def values(node):
    """Every string `node` can give, without the answer to steer it."""
    if node.get("unchecked"):
        return {letters(node.get("gives"))}
    if "op" not in node:
        return {leaf_letters(node)}
    op, parts = node["op"], parts_of(node)
    if op == "anagram":
        raise _NeedTarget(node)
    if op in ("cryptic", "rebus", "reverse", "composite"):
        raise _NeedTarget(node)
    if op == "charade":
        out = {""}
        for p in parts:
            out = {a + b for a in out for b in values(p)}
            if len(out) > CAP:
                raise WordplayError(f"{render(node)} has too many readings to check: "
                                    f"write the letters each part gives")
        return out
    if op == "reversal":
        return {v[::-1] for v in values(parts[0])}
    if op == "container":
        return {o[:k] + i + o[k:] for o in values(parts[0]) for i in values(parts[1])
                for k in range(1, len(o))}
    if op == "deletion":
        out = set()
        for f in values(parts[0]):
            for r in values(parts[1]):
                out |= {f[:k] + f[k + len(r):] for k in range(len(f)) if f.startswith(r, k)}
        return out
    if op == "hidden":
        leaf = parts[0]
        text = letters(leaf.get("words"))
        if "gives" in leaf:
            return {leaf["gives"]} if leaf["gives"] in text else set()
        return {text[a:b] for a in range(len(text)) for b in range(a + 1, len(text) + 1)}
    if op == "homophone":
        return {node["spelt"]}
    if op == "spoonerism":
        if "spelt" in node:
            return {node["spelt"]}
        out = set()
        for a in values(parts[0]):
            for b in values(parts[1]):
                for oa, ob in ((_onset(a), _onset(b)), (a[:1], b[:1])):
                    out.add(ob + a[len(oa):] + oa + b[len(ob):])
        return out
    if op == "substitution":
        out = set()
        for x in values(parts[0]):
            for old in values(parts[1]):
                for new in values(parts[2]):
                    out |= {x[:k] + new + x[k + len(old):] for k in range(len(x)) if x.startswith(old, k)}
        return out
    if op == "cycling":
        return {v[k:] + v[:k] for v in values(parts[0]) for k in range(1, len(v))}
    if op == "palindrome":
        real = lettered(parts)
        if not real:
            # pal() alone: the answer is the wordplay, known only against it.
            raise _NeedTarget(node)
        out = values(real[0] if len(real) == 1 else {"op": "charade", "parts": real})
        return {v for v in out if v == v[::-1]}
    if op in SELECT:
        words = _words(parts[0])
        return set().union(*(_select(op, node.get("n"), v, words) for v in values(parts[0])))
    raise WordplayError(f"unknown op {op!r}")


def lengths(node):
    """Every length `node` can give."""
    op = node.get("op")
    if node.get("unchecked"):
        return {len(letters(node.get("gives")))}
    if op == "anagram":
        return lengths(fodder_pool(node))
    if op == "reversal":
        return lengths(parts_of(node)[0])
    if op in ("cryptic", "rebus", "reverse"):
        return None
    if op == "composite":
        try:
            return {len(f) - len(m) for f in _bag(parts_of(node)[0]) for m in values(parts_of(node)[1])}
        except (_NeedTarget, WordplayError):
            return None
    if op == "charade":
        out = {0}
        for p in parts_of(node):
            ls = lengths(p)
            if ls is None:
                return None
            out = {a + b for a in out for b in ls}
        return out
    if op == "container":
        a, b = lengths(parts_of(node)[0]), lengths(parts_of(node)[1])
        return None if a is None or b is None else {x + y for x in a for y in b}
    try:
        return {len(v) for v in values(node)}
    except _NeedTarget:
        return None


def _bag(node):
    """The sorted letters of `node` where its order is open (anagram fodder)."""
    try:
        return {"".join(sorted(v)) for v in values(node)}
    except _NeedTarget:
        op = node["op"]
        if op == "anagram":
            return _bag(fodder_pool(node))
        if op == "reversal":
            return _bag(parts_of(node)[0])
        if op == "charade":
            out = {""}
            for p in parts_of(node):
                out = {"".join(sorted(a + b)) for a in out for b in _bag(p)}
            return out
        if op == "container":
            return {"".join(sorted(a + b)) for a in _bag(parts_of(node)[0]) for b in _bag(parts_of(node)[1])}
        raise WordplayError(f"{render(node)}: an anagram inside {NAMES[op]}() can't be "
                            f"checked; write the letters it gives as a leaf")


def match(node, want, got=None):
    """{id(node): letters} for `node` and everything under it giving `want`,
    or None when it can't."""
    got = {} if got is None else got
    op = node.get("op")
    if node.get("unchecked"):
        # Its letters are its `gives`, none when absent (a file stores no ""),
        # as values() and lengths() read it.
        ok = letters(node.get("gives")) == want
        for p in node.get("parts") or []:
            _fill(p, got)
    elif op is None:
        ok = leaf_letters(node) == want
    elif op in ("cryptic", "rebus", "reverse"):
        ok = True
        for p in parts_of(node):
            _fill(p, got)
    elif op == "composite":
        ok = _match_composite(node, want, got)
    elif op == "charade":
        ok = _match_run(parts_of(node), want, got)
    elif op == "reversal":
        ok = match(parts_of(node)[0], want[::-1], got) is not None
    elif op == "anagram":
        child = fodder_pool(node)
        ok = False
        if "".join(sorted(want)) in _bag(child):
            try:
                # A reading that is a real anagram first (one already in the
                # answer's order is no anagram: _check_ops), then the first in
                # order, so the result never depends on set order.
                same = sorted((v for v in values(child) if sorted(v) == sorted(want)),
                              key=lambda v: (v == want, v))
            except _NeedTarget:
                same = []
            ok = True
            if same:
                match(child, same[0], got)
                if len(parts_of(node)) > 1:
                    got.pop(id(child), None)
    elif op == "container":
        ok = _match_container(node, want, got)
    elif op == "deletion":
        ok = False
        for f in sorted(values(parts_of(node)[0])):
            for r in sorted(values(parts_of(node)[1])):
                if any(f.startswith(r, k) and f[:k] + f[k + len(r):] == want for k in range(len(f))):
                    match(parts_of(node)[0], f, got)
                    match(parts_of(node)[1], r, got)
                    ok = True
                    break
            if ok:
                break
    elif op == "palindrome":
        real = lettered(parts_of(node))
        ok = want == want[::-1] and (not real or _match_run(real, want, got))
        for p in parts_of(node):
            if not any(p is r for r in real):
                _fill(p, got)
    elif op in ("homophone", "spoonerism") and "spelt" in node:
        ok = node["spelt"] == want
        for p in parts_of(node):
            _fill(p, got)
    else:
        ok = want in values(node)
        if ok:
            for p in parts_of(node):
                if op == "hidden":
                    got[id(p)] = want
                else:
                    _fill(p, got)
    if not ok:
        return None
    got[id(node)] = want
    return got


def _match_composite(node, want, got):
    """The fodder's letters are the answer's plus the letters taken out."""
    fodder, minus = parts_of(node)
    bags = _bag(fodder)
    for m in sorted(values(minus)):
        if "".join(sorted(want + m)) in bags:
            match(minus, m, got)
            try:
                same = sorted(v for v in values(fodder) if sorted(v) == sorted(want + m))
            except _NeedTarget:
                same = []
            if same:
                match(fodder, same[0], got)
            return True
    return False


def _fill(node, got):
    """Record a concrete reading of `node` where no answer steers it."""
    try:
        vs = sorted(values(node))
    except _NeedTarget:
        return
    if vs:
        match(node, vs[0], got)


def _match_run(parts, want, got):
    if not parts:
        return want == ""
    head, rest = parts[0], parts[1:]
    ls = lengths(head)
    cands = range(len(want) + 1) if ls is None else sorted(ls)
    for n in cands:
        if n > len(want):
            continue
        trial = dict(got)
        if match(head, want[:n], trial) is not None and _match_run(rest, want[n:], trial):
            got.update(trial)
            return True
    return False


def _match_container(node, want, got):
    outer, inner = parts_of(node)
    for n in sorted(lengths(inner) or range(1, len(want))):
        for k in range(1, len(want) - n):
            trial = dict(got)
            if (match(inner, want[k:k + n], trial) is not None
                    and match(outer, want[:k] + want[k + n:], trial) is not None):
                got.update(trial)
                return True
    return False


def _gives(node):
    try:
        vs = sorted(values(node), key=lambda v: (len(v), v))
    except _NeedTarget:
        b = sorted(_bag(node))
        return f"the letters {b[0]}" if len(b) == 1 else "letters in some order"
    except WordplayError:
        return "too many readings"
    if not vs:
        return "nothing"
    return vs[0] if len(vs) == 1 else " or ".join(vs[:4]) + (" …" if len(vs) > 4 else "")


def diagnose(node, want):
    """The deepest node that fails to give its share of `want`, in words."""
    op = node.get("op")
    ls = lengths(node)
    if op == "charade" and all(lengths(p) and len(lengths(p)) == 1 for p in parts_of(node)):
        sizes = [next(iter(lengths(p))) for p in parts_of(node)]
        if sum(sizes) == len(want):
            at = 0
            for p, n in zip(parts_of(node), sizes):
                if match(p, want[at:at + n]) is None:
                    return diagnose(p, want[at:at + n])
                at += n
    if op == "reversal" and ls and len(want) in ls:
        child = parts_of(node)[0]
        if "op" not in child and leaf_letters(child) == want:
            return (f"{render(child)} already reads {want}, but a leaf gives its letters "
                    f"before the reversal: write {render({**child, 'gives': want[::-1]})} inside rev()")
        return diagnose(child, want[::-1]) + " (inside the reversal, read backwards)"
    if op == "palindrome":
        if want != want[::-1]:
            return f"{render(node)}: {want} does not read the same backwards"
        real = lettered(parts_of(node))
        return diagnose(real[0] if len(real) == 1 else {"op": "charade", "parts": real}, want)
    if op == "composite":
        fodder, minus = parts_of(node)
        try:
            bags, taken = _bag(fodder), values(minus)
        except (WordplayError, _NeedTarget) as e:
            return str(e)
        if not bags or not taken:
            return f"{render(node)} gives no letters"
        bag, m = min(bags, key=len), min(taken, key=len)
        extra = "".join(sorted((_count(bag) - _count(want + m)).elements()))
        short = "".join(sorted((_count(want + m) - _count(bag)).elements()))
        return (f"{render(node)}: the fodder has the letters {bag}, which must be the answer {want} "
                f"plus the letters taken out ({m}), {len(want + m)} in all" +
                (f"; the fodder has {extra} to spare" if extra else "") +
                (f"; it lacks {short}" if short else ""))
    if op == "anagram":
        try:
            bags = _bag(fodder_pool(node))
        except WordplayError as e:
            return str(e)
        if not bags:
            return _gives_nothing(fodder_pool(node))
        bag = min(bags, key=len)
        extra = "".join(sorted((_count(bag) - _count(want)).elements()))
        short = "".join(sorted((_count(want) - _count(bag)).elements()))
        return (f"{render(node)} has the letters {bag}; the answer needs an anagram of {want} "
                f"here" + (f" (the fodder has {extra} to spare" if extra else " (") +
                (f"{'; ' if extra else ''}it lacks {short})" if short else ")"))
    msg = f"{render(node)} gives {_gives(node)}; the answer needs {want} here"
    if op is None and leaf_letters(node)[::-1] == want:
        msg += (f". {leaf_letters(node)} reads backwards: a leaf's letters come before any "
                f"operation, so write rev<indicator>(...) round it")
    elif ls is not None and len(want) not in ls:
        msg += f" ({'/'.join(map(str, sorted(ls)))} letters against {len(want)})"
    return msg


def _gives_nothing(node):
    """The deepest node under `node` that can give no letters at all, in words
    (anagram fodder whose deletion finds no run to take out)."""
    for p in node.get("parts") or []:
        try:
            if not values(p):
                return _gives_nothing(p)
        except (_NeedTarget, WordplayError):
            pass
    if node.get("op") == "deletion":
        whole, gone = parts_of(node)
        return (f"{render(node)} gives nothing: {render(gone)} is not one run of the "
                f"letters {render(whole)} gives. Letters taken from more than one place "
                f"are one del per run, e.g. del(del(x, N), OT)")
    return f"{render(node)} gives no letters"


def _count(s):
    return collections.Counter(s)


#: The ops whose evaluation reads a fixed part by position, so the count must be
#: exact. The rest take their shape from elsewhere (a charade has any number, a
#: homophone may carry its spelling in `spelt`, ana() takes a charade's parts).
COUNTED = ("reversal", "container", "deletion", "hidden", "substitution", "cycling",
           *SELECT)


def _check_arity(node):
    """A stored tree is not parsed, so an op filed with the wrong number of parts
    reaches the evaluator as it is; refuse it with the count it wants. An
    unchecked node stands for its `gives` and is not looked into."""
    if node.get("unchecked"):
        return
    op = node.get("op")
    parts = node.get("parts") or []
    if op in COUNTED:
        lo, hi = ARITY[op]
        if not lo <= len(parts) <= hi:
            want = str(lo) if lo == hi else f"{lo} to {hi}"
            raise WordplayError(f"{NAMES[op]}() takes {want} part(s), the tree files {len(parts)}: "
                                f"{render(node)}")
    for p in parts:
        _check_arity(p)


def evaluate(tree, answer):
    """{id(node): letters} with every node of `tree` giving its share of
    `answer`'s letters; raises WordplayError naming the node that breaks."""
    want = letters(answer)
    _check_arity(tree)
    try:
        got = match(tree, want)
        if got is None:
            raise WordplayError(f"the wordplay does not give {want}: {diagnose(tree, want)}")
    except _NeedTarget as e:
        raise WordplayError(f"{render(e.args[0])} sits where its letters have to be known in "
                            f"order (inside del, sub, a selection or a homophone): write the "
                            f"letters it gives as a leaf instead") from None
    except (IndexError, KeyError, TypeError) as e:
        raise WordplayError(f"the tree is not shaped as its ops need ({type(e).__name__} {e}): "
                            f"{render(tree)}") from None
    _check_ops(tree, got)
    _check_rebus(tree, want)
    _check_reverse(tree, want)
    return got


#: A run of capitals and figures in a reading, naming the picture's own
#: characters: H, O2, W-H-E-A-T. A word with a lower-case letter is prose.
PICTURE_TOKEN = re.compile(r"(?<![\w'’])[A-Z0-9](?:-?[A-Z0-9])*(?![\w'’])")


def _alnum(s):
    return re.sub(r"[^A-Z0-9]", "", unicodedata.normalize("NFD", str(s or "")).upper())


def _in_order(token, picture):
    """`token`'s characters appear in `picture` in order (IOU in IO2U)."""
    it = iter(picture)
    return all(ch in it for ch in token)


def _check_rebus(tree, want):
    """A rebus is the whole wordplay, and its reading names characters
    the picture shows (so it reads the picture rather than restating the
    answer) without being the answer itself."""
    for node in _walk(tree):
        if node.get("op") != "rebus" or node.get("unchecked"):
            continue
        if node is not tree:
            raise WordplayError(f"{render(node)}: a rebus is the whole wordplay, "
                                f"never a piece of it; write rebus(...) alone")
        words = parts_of(node)[0].get("words")
        reading = node.get("reading") or ""
        named = PICTURE_TOKEN.findall(reading)
        if not named:
            raise WordplayError(f"{render(node)}: the reading names none of the picture's "
                                f"characters; say what it shows in its own capitals and "
                                f"figures (\"H to O\", \"P, the core of apple\")")
        missing = [t for t in named if not _in_order(_alnum(t), _alnum(words))]
        if missing:
            raise WordplayError(f"{render(node)}: the reading names {', '.join(missing)}, "
                                f"which the picture {words!r} does not show")
        if letters(reading) == want:
            raise WordplayError(f"{render(node)}: the reading is the answer; say what the "
                                f"picture shows that turns into it")


def _check_reverse(tree, want):
    """A reverse clue is the whole wordplay, and its reading spells the
    answer in pieces: two or more, capitals joined by spaces or +, whose
    letters in order are the answer (OUT + STEP for OUTSTEP). One piece is
    the answer itself and says nothing."""
    for node in _walk(tree):
        if node.get("op") != "reverse" or node.get("unchecked"):
            continue
        if node is not tree:
            raise WordplayError(f"{render(node)}: a reverse clue is the whole wordplay, "
                                f"never a piece of it; write reverse(...) alone")
        reading = node.get("reading") or ""
        pieces = [x for x in re.split(r"[\s+]+", reading) if x]
        if len(pieces) < 2 or any(x != x.upper() or not letters(x) for x in pieces):
            raise WordplayError(f"{render(node)}: the reading is the answer's pieces in capitals, "
                                f"two or more joined by spaces or +: \"OUT + STEP\"")
        if letters(reading) != want:
            raise WordplayError(f"{render(node)}: the reading's pieces spell {letters(reading)}, "
                                f"not the answer {want}")


def _walk(node):
    out = []

    def go(n):  # a list, not a generator: nested yields cost per level
        out.append(n)
        for p in n.get("parts") or ():
            go(p)
    go(node)
    return out


def _spells_in_order(parts, want):
    """Whether `parts` read as a plain charade can give `want`: match() may
    have placed an insertion so the anagram above it looks like it moves
    letters, when another placement spells the answer with none moved."""
    ops = {n.get("op") for p in parts for n in _walk(p) if n.get("parts")}
    if "container" not in ops or not ops <= {"container", "charade"}:
        return False  # a deletion or the like picks its letters to fit any target
    try:
        return match({"op": "charade", "parts": parts}, want) is not None
    except (_NeedTarget, IndexError, KeyError, TypeError):
        return False


def _check_ops(node, got):
    """Steps that leave their letters as they were say nothing."""
    if node.get("unchecked"):
        return
    op = node.get("op")
    for p in node.get("parts") or []:
        _check_ops(p, got)
    if op == "anagram":
        parts = parts_of(node)
        read = "".join(got[id(p)] for p in parts) if all(id(p) in got for p in parts) else None
        if read != got.get(id(node)) and got.get(id(node)) and _spells_in_order(parts, got[id(node)]):
            read = got[id(node)]  # the match scrambled a container the fodder can give in order
        if read is not None and read == got.get(id(node)):
            raise WordplayError(f"{render(node)}: the fodder already reads "
                                f"{got[id(node)]}, so there is no anagram")
    if op == "reversal" and got.get(id(node)) and got[id(node)] == got[id(node)][::-1]:
        raise WordplayError(f"{render(node)}: {got[id(node)]} reads the same backwards, "
                            f"so the reversal does nothing")


def _fold(text):
    return " ".join(re.findall(r"\w+", text.lower()))


def _rekey(notes, tree):
    """Land each leftover note on the one span with no note whose words are the
    note's key apart from case, punctuation and spacing, or (when exactly one
    span qualifies) contain it or are contained in it. Those keys name the span
    plainly and the run was only sent back to retype them (172 of the
    'name no span' refusals in 48h). Anything ambiguous stays refused."""
    for key in list(notes):
        want = _fold(re.sub(r"#\d+$", "", key))
        if not want:
            continue
        free = [(s, k) for s, k in _spans(tree, True) if "note" not in s and _fold(s[k])]
        for hit in ([x for x in free if _fold(x[0][x[1]]) == want],
                    [x for x in free if f" {want} " in f" {_fold(x[0][x[1]])} "
                     or (len(_fold(x[0][x[1]]).split()) > 1 and f" {_fold(x[0][x[1]])} " in f" {want} ")]):
            if len(hit) == 1:
                hit[0][0]["note"] = notes.pop(key)
                break
            if hit:
                break


def translate(clue_out, clue, answer, taken=(), respell=None):
    """The stored tree for one clue of model output ({"wp", "notes"}),
    checked against `answer`. Notes are keyed by span words (`#2` for a
    repeat), or a bare piece's letters, and land on the span they name.
    `taken` are (start, end) clue spans already used (the definitions), so a
    word in both picks another copy; `respell(text, clue)` spells each span's
    words as the clue prints them first (a retyped apostrophe or capital)."""
    tree = parse(clue_out["wp"])
    if respell:
        for span, key in _spans(tree):
            if not re.search(r"#\d+$", span[key]):
                span[key] = respell(span[key], clue)
    locate(tree, clue, taken)
    notes = dict(clue_out.get("notes") or {})
    seen = {}
    raw = list(_spans(parse(clue_out["wp"]), True))
    for (span, key), (orig, _) in zip(_spans(tree, True), raw):
        name = orig[key]
        base = re.sub(r"#\d+$", "", name)
        seen[base] = seen.get(base, 0) + 1
        for k in (name, base if seen[base] == 1 else f"{base}#{seen[base]}"):
            if k in notes:
                span["note"] = notes.pop(k)
                break
    if notes:
        _rekey(notes, tree)
    if notes:
        keys = [s[k] for s, k in _spans(tree, True) if "note" not in s]
        raise WordplayError(f"notes {sorted(notes)} name no span of the wordplay; key each "
                            f"note by its words as written in the expression"
                            + (f" (spans with no note yet: {keys})" if keys else
                               " (every span has a note already)"))
    evaluate(tree, answer)
    return tree


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("expression")
    ap.add_argument("--answer")
    ap.add_argument("--clue")
    a = ap.parse_args()
    try:
        tree = parse(a.expression, a.clue)
        if a.answer:
            evaluate(tree, a.answer)
    except WordplayError as e:
        sys.exit(str(e))
    print(json.dumps(tree, indent=1))


if __name__ == "__main__":
    main()
