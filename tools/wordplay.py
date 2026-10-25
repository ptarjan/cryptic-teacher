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
    A + B                 a charade, in answer order, pieces side by side (ins
                          only where one piece is cut open by another). Every
                          clue piece that gives letters is a term: none is left
                          out (inside ana() they are the fodder's parts)
    op<indicator>(...)    an operation; <indicator words> follow the op they
                          signal, one <...> per phrase; `+<under>` is an
                          indicator on the charade. Every op but + needs its
                          indicator: no clue word signals it, the op is not there
    ana(x)                anagram of x's letters; ana(x + y + z) shuffles several
                          of the clue's own pieces as one pool. A single letter, a
                          pick at the answer's end, an abbreviation or a synonym
                          is spelt beside it, ana(x) + N, never scrambled in
    rev(x)                x backwards; an indicator naming a stretch (last pair
                          of, first three, half) turns only that stretch, 2+
                          letters: rev<last pair of>([mini vehicles]KARTS) for KARST
    rep(x)                x twice (leaf gives one copy): rep<twice>([boy]AL) for ALAL
    ins(outer, inner)     inner put inside outer (the answer decides where)
    del(from, removed)    removed taken out of from (the answer decides where):
                          one run, or scattered in the same order
                          (del([Equably], [by]BY) for EQUAL)
    hid(x)                letters hidden in x's words: hid([say no before]YNOBE),
                          or hid([say no before]) to let the answer pick them
    sound(x, SPELT)       x sounds like SPELT, the letters entered. x is ONE leaf
                          naming the word said aloud: sound<ind>([clue words]HEARD,
                          SPELT). Side-by-side leaves are merged for you; over a
                          step (first, del, hid) the leaf holds the step's letters
    spoon(a, b)           a and b with their first consonants swapped (written
                          letters); spoon(a, b, SPELT) when the swap is by sound,
                          SPELT the letters entered. Never put sound() round a
                          Spoonerism: spoon<Spooner's>([marry]MARRY, [fan]FAN, FERRYMAN)
    sub(x, OLD, NEW)      OLD in x replaced by NEW
    cyc(x)                x with letters moved from one end to the other
    move(x, MOVED)        MOVED, one run of x's letters, taken out and put back
                          elsewhere in x (the answer decides where), one step:
                          move<dropping>([England]ALBION, [ball]O) for ALBINO,
                          never ALBION + O with the first O deleted
    pal(x)                x, which reads the same backwards; pal() with no x
                          when the answer itself is all the wordplay
    first(x) last(x) middle(x) outer(x) alt(x) regular(x) nth(n)(x)
                          letters picked from x's words: first letter (or
                          each word's), middle letter(s) or all but the
                          ends, first and last, alternate, every 2nd/3rd, the nth.
                          x is the words picked FROM, never the pick:
                          alt<regularly>([most]) for MS, not ([most]MS). Over
                          several words it takes a comma list, never +:
                          outer<fringes of>([Argive], [Greece], [Anatolian]).
                          The indicator needs a note; the pick needs none
    cd([words])           cryptic definition: the words, no letters (a wp that
                          is one leaf is refused; no mechanism means a cd or a
                          double definition)
    comp(x, y)            composite anagram: x's letters are the answer plus y's
                          (never ana(del(...))): comp<sadly>([thirsted], [it's])
                          for DERTH
    reverse([words], "reading")
                          a reverse clue: the words read as wordplay that would
                          build the answer; "reading" spells it in the pieces,
                          capitals joined by spaces or +: reverse([What makes
                          pets], "OUT + STEP") for OUTSTEP. The whole wordplay;
                          the definition stays a `def`. Only when the reading
                          names the clue's own last words rearranged (pets ->
                          STEP); a phrase of 3+ words with no such word is
                          refused (reversePhrase): write what the words do
                          (ana, hid, charade), or cd([words]) if nothing builds
                          the answer
    rebus([words], "reading")
                          a picture of letters or figures, "reading" saying what
                          it shows: rebus([HIJKLMNO], "H to O") for WATER. The
                          whole wordplay; with no `def` it is the whole clue
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
&lit); a selection over several words is one op with a comma list of leaves; a
leaf that gives a stretch of its own words is the selection, deletion or hidden
word as an op; the wordplay is never one leaf; every charade piece has clue words
(a bare-letters piece belongs in a leaf of the clue word that supplies it); an
anagram's container is the outer step, ins(outer, ana(x)), not ana(ins(...)).
"""
import argparse
import collections
import copy
import functools
import itertools
import json
import re
import sys
import unicodedata

# Expression name -> stored op.
OPS = {"ana": "anagram", "rev": "reversal", "ins": "container", "del": "deletion",
       "hid": "hidden", "sound": "homophone", "spoon": "spoonerism",
       "sub": "substitution", "cyc": "cycling", "move": "move", "cd": "cryptic", "pal": "palindrome",
       "rebus": "rebus", "comp": "composite", "reverse": "reverse",
       "first": "first", "last": "last", "middle": "middle", "outer": "outer",
       "alt": "alternate", "regular": "regular", "nth": "nth", "rep": "repeat"}
NAMES = {v: k for k, v in OPS.items()}
# The fewest parts the written form takes where a stored tree may carry fewer: a spoonerism
# filed as one leaf with `soundsLike` (HAD MATTER), a substitution of the centre (sub(x, NEW)).
_STORED_SHORT = {"spoonerism": 2, "substitution": 3}
SELECT = ("first", "last", "middle", "outer", "alternate", "regular", "nth")
# How many parts each op takes: (fewest, most).
# ana() takes one argument; a charade written there becomes its parts (_fodder_parts).
ARITY = {"anagram": (1, 1), "reversal": (1, 1), "container": (2, 2), "deletion": (2, 9),
         "hidden": (1, 1), "homophone": (2, 2), "spoonerism": (1, 3),
         "substitution": (2, 3), "cycling": (1, 1), "move": (2, 2), "cryptic": (1, 9), "palindrome": (0, 1),
         "rebus": (2, 2), "composite": (2, 2), "reverse": (2, 2), "repeat": (1, 1),
         **{s: (1, 9) for s in SELECT}}  # a selection over a list: several parts, each giving its pick
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
            c = self.s[self.i:self.i + 1]
            if c == "<":
                self.fail("expected [clue words], LETTERS, '(' or an op; an <indicator> sits right after the "
                          "op or '+' it signals, never before a piece: ins<in>(A, B), or A +<after> B")
            if c.isdigit():
                self.fail("expected [clue words], LETTERS, '(' or an op; first/last take no count "
                          "(first<ind>([words]) picks one letter, each word's first over a list): write the "
                          "letters picked as a leaf, [arbiters]JUD, or nth(3)(x) for the nth letter")
            if c == "":
                self.fail("expected [clue words], LETTERS, '(' or an op; a '+' (or '+<indicator>') needs "
                          "the piece it joins after it: A + B, or A +<after> B")
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
        if op in _STORED_SHORT:  # the one-leaf spoon and two-part sub are stored forms, not written ones
            lo = _STORED_SHORT[op]
        if not lo <= len(args) <= hi:
            want = {"homophone": "sound(x, SPELT)", "spoonerism": "spoon(a, b) or spoon(a, b, SPELT)",
                    "container": "ins(outer, inner)", "deletion": "del(from, removed, ...)",
                    "substitution": "sub(x, OLD, NEW)", "move": "move(x, MOVED)",
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


def _masked(text):
    """`text` with the inside of every [..], <..> and ".." blanked to 'x' (same length), so
    the structure characters left are the expression's own."""
    out, close = [], None
    for ch in text:
        if close:
            out.append(ch if ch == close else "x")
            close = None if ch == close else close
        elif ch in "[<\"":
            out.append(ch)
            close = {"[": "]", "<": ">", '"': '"'}[ch]
        else:
            out.append(ch)
    return "".join(out)


def _top_level(masked, sep):
    """Offsets of `sep` in `masked` outside every bracket pair."""
    depth, hits = 0, []
    for i, ch in enumerate(masked):
        depth += ch == "(" or -(ch == ")")
        if ch == sep and depth == 0:
            hits.append(i)
    return hits


def _pieces(text, masked, sep):
    cuts = [-1] + _top_level(masked, sep) + [len(text)]
    return [text[a + 1:b].strip() for a, b in zip(cuts, cuts[1:])]


_PREFIX_PLUS = re.compile(r"\+\s*(<[^<>]*>(?:\s*<[^<>]*>)*)\s*\(")


def mend_charade_indicator(text):
    """`text` with a charade indicator written the way the parser does not take it, said
    in the one way it does; None when `text` has no such slip. Only the syntax moves: the
    pieces, their order and every word stay, and the answer still decides whether the
    result is right (translate checks it). Two slips, both 'the order word of a charade':
      A + B + +<after>C      the doubled '+' (the indicator IS the join): A + B +<after> C
      +<after>(A, B)         the join written as a prefix op over its pieces, comma list or
      +<after>(A + B)        a sum: (A +<after> B), the pieces nested when they are sums."""
    masked = _masked(text)
    changed = False
    # the doubled '+': the first one is the join's, the second only repeats it
    while (m := re.search(r"\+\s*(?=\+\s*<)", masked)):
        text, masked = text[:m.start()] + text[m.end():], masked[:m.start()] + masked[m.end():]
        changed = True
    # the prefix op: the last one first, so a nested one is mended before its parent
    for m in reversed(list(_PREFIX_PLUS.finditer(masked))):
        if masked[:m.start()].rstrip()[-1:] not in ("", "(", ","):
            continue            # `A +<after>(B + C)` is a join with a bracketed piece: it parses
        inner_at, depth, j = m.end(), 1, m.end()
        while j < len(masked) and depth:
            depth += masked[j] == "(" or -(masked[j] == ")")
            j += 1
        if depth:
            continue
        body, mbody = text[inner_at:j - 1], masked[inner_at:j - 1]
        args = _pieces(body, mbody, ",")
        if len(args) == 1:
            args = _pieces(body, mbody, "+")        # +<ind>(a + b): the sum's pieces
            keep = False
        else:
            keep = True                             # +<ind>(a, b): each arg stays one piece
        if len(args) < 2 or not all(args):
            continue
        parts = [f"({a})" if keep and _top_level(_masked(a), "+") else a for a in args]
        joined = f"({parts[0]} +{text[m.start(1):m.end(1)]} " + " + ".join(parts[1:]) + ")"
        text, masked = text[:m.start()] + joined + text[j:], masked[:m.start()] + _masked(joined) + masked[j:]
        changed = True
    return text if changed else None


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


_MARKS = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-",
                        "‑": "-", "‐": "-", "−": "-"})


def fold_marks(s):
    """`s` with curly quotes and dash kinds made straight, one character for one."""
    return s.translate(_MARKS)


def _gapped_runs(text, clue):
    """(the clue's stretch from the first to the last of `text`'s words, its runs of
    adjacent matched words) when the words all occur in the clue in order but with
    other words between; else None."""
    toks = [(m.group().lower(), m.start(), m.end())
            for m in re.finditer(r"[\w'’]+", fold_marks(clue))]
    words = [w.lower() for w in re.findall(r"[\w'’]+", fold_marks(text))]
    if len(words) < 2:
        return None
    for start in range(len(toks)):
        i, hit = start, []
        for w in words:
            while i < len(toks) and toks[i][0] != w:
                i += 1
            if i == len(toks):
                break
            hit.append(i)
            i += 1
        else:
            if hit[0] != start or hit[-1] - hit[0] + 1 == len(hit):
                continue
            runs, cur = [], [hit[0]]
            for a, b in zip(hit, hit[1:]):
                if b == a + 1:
                    cur.append(b)
                else:
                    runs.append(cur)
                    cur = [b]
            runs.append(cur)
            return (clue[toks[hit[0]][1]:toks[hit[-1]][2]],
                    [clue[toks[r[0]][1]:toks[r[-1]][2]] for r in runs])
    return None


def not_in_clue(text, clue, nth=1):
    """The refusal for words a span names that the clue does not hold, saying
    what to change: a repeat that has no such copy, words the clue has but not
    side by side (write each run as its own [..] piece), or words it lacks."""
    head = f"{text!r} is not in the clue {clue!r}: "
    low = clue.lower()
    if nth > 1:
        # Count what find_at counts: whole-word copies when there are any ("a" in
        # "inhabiting a region" is one copy, not the seven letters a inside words).
        have = (len(re.findall(rf"(?<!\w){re.escape(text.lower())}(?!\w)", low))
                or len(re.findall(re.escape(text.lower()), low)))
        return head + (f"the clue has {have} copy of those words, so there is no copy #{nth}: "
                       f"drop the `#{nth}`" if have == 1 else f"the clue has {have} copies, "
                       f"so there is no copy #{nth}")
    words = re.findall(r"[\w'’]+", text.lower())
    absent = [w for w in words if w not in low]
    if "#" in text:
        fixed = re.sub(r"#(\d+)(?=\s)", "", text)
        n = int(re.search(r"#(\d+)", text).group(1))
        hint = (f": write {fixed + '#' + str(n)!r}"
                if fixed != text and low.count(fixed.lower()) >= n else "")
        return head + ("`#n` goes once, at the very end of the quote (`fond#2`), and the "
                       "quote itself must be one unbroken run of clue words" + hint)
    runs = _gapped_runs(text, clue)
    if runs:
        return head + (f"those words sit in the clue in order but not side by side: the clue has "
                       f"{runs[0]!r} there. Quote that whole run if the words between belong to it; "
                       f"otherwise give each run its own piece: "
                       f"{', '.join(repr(r) for r in runs[1])} (an indicator: one <..> per run; "
                       f"wordplay: one [..] per run)")
    if len(words) > 1 and not absent:
        toks = re.findall(r"[\w'’]+", low)
        if all(w in toks for w in words):
            pos = [toks.index(w) for w in words]
            if pos != sorted(pos):
                return head + ("those words are in the clue but in a different order than "
                               "you wrote them: quote them as the clue has them, "
                               + ", ".join(repr(words[i]) for i in sorted(range(len(words)), key=pos.__getitem__))
                               + " (each run its own piece if other words sit between)")
        return head + ("each word is in the clue but not side by side: give each run of "
                       "clue words its own [..] piece (the words between belong to other pieces "
                       "or are link words)")
    if absent:
        return head + (f"{', '.join(repr(w) for w in absent)} {'is' if len(absent) == 1 else 'are'} "
                       f"not among its words: copy the clue words exactly")
    return head + "copy the clue words exactly"


_ELLIPSIS = re.compile(r"\s*(?:\.\.\.|…)\s*")


def _split_ellipsis(node, clue):
    """An indicator written 'taking ... into' (a phrase split round other words) is
    two indicators, 'taking' and 'into': the refusal asked for one <..> per run
    and the gap words are the model's own pieces. Only a text the clue does not
    print as it is (an ellipsis in the clue itself stays one indicator)."""
    inds = node.get("indicators")
    if inds:
        out = []
        for ind in inds:
            text = ind.get("text")
            parts = [p for p in _ELLIPSIS.split(text) if p.strip()] if isinstance(text, str) else []
            if len(parts) > 1 and text not in clue and _ELLIPSIS.search(text):
                out += [{**ind, "text": p} for p in parts]
            else:
                out.append(ind)
        node["indicators"] = out
    for p in node.get("parts") or ():
        _split_ellipsis(p, clue)


def _strip_inner_marks(text):
    """(`text` without `#n` marks, n) for a quote that put the mark inside it
    ('Greek#2 goddess', 'guy#2 at#2 St#2 Andrews') when every mark is the same n:
    the copy asked for is the quote's. None otherwise."""
    marks = set(re.findall(r"#(\d+)(?=\s|$)", text))
    if len(marks) != 1 or not re.search(r"#\d+\s", text):
        return None
    return re.sub(r"#\d+(?=\s|$)", "", text), int(marks.pop())


def _reordered_run(text, clue):
    """The clue's run of words that are `text`'s words in another order
    ('flambé, perhaps' for the clue's 'perhaps flambé'), when exactly one run of
    the clue has them; else None."""
    want = sorted(w.lower() for w in re.findall(r"[\w'’]+", fold_marks(text)))
    if len(want) < 2:
        return None
    toks = [(m.group().lower(), m.start(), m.end()) for m in re.finditer(r"[\w'’]+", fold_marks(clue))]
    runs = {(toks[i][1], toks[i + len(want) - 1][2]) for i in range(len(toks) - len(want) + 1)
            if sorted(t[0] for t in toks[i:i + len(want)]) == want}
    if len(runs) != 1:
        return None
    a, b = runs.pop()
    return a, clue[a:b]


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
        elif "#" in text and text not in clue and _strip_inner_marks(text):
            text, nth = _strip_inner_marks(text)
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
        if at is None:
            # Curly vs straight quotes and dash kinds: a 1:1 character fold, so the
            # offset is the clue's own and the stored text is the clue's spelling.
            folded = fold_marks(clue).lower()
            if len(folded) == len(clue):
                at = find_at(folded, fold_marks(text).lower(), nth, used)
        if at is None and nth > 1 and "#" not in text:
            # '#2' for a word the clue prints once: the only copy there is.
            if len(re.findall(rf"(?<!\w){re.escape(text.lower())}(?!\w)", clue.lower())) == 1:
                at = find_at(clue.lower(), text.lower(), 1, used) if low else find_at(clue, text, 1, used)
        if at is None and nth == 1 and "#" not in text:
            run = _reordered_run(text, clue)  # the words are there, in the clue's order
            if run:
                at, text = run
                span[key] = text
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
    """Every string `op` can pick from `s`. Where the leaf's words are known the pick
    is also made from any run of them (the leaf may carry an indicator word, "strain
    of MRSA"), and a first/last/outer pick is a stretch of any length ("40% of Truro"
    is TR), a middle pick any centred stretch (ACHE from teachers)."""
    out = set()
    if not s:
        return out
    words = words or [s]
    runs = [words[i:j] for i in range(len(words)) for j in range(i + 1, len(words) + 1)]
    if op in ("first", "last", "nth") and 2 < len(words) <= 7:
        # a linking word between them is skipped ("blancmange and jelly" for L, E)
        runs += [list(c) for k in range(2, len(words)) for c in itertools.combinations(words, k)
                 if c not in map(tuple, runs)]
    for run in runs:
        t = "".join(run)
        if op == "first":
            out |= {t[:k] for k in range(1, len(t))}
            out.add("".join(w[0] for w in run))
        elif op == "last":
            out |= {t[-k:] for k in range(1, len(t))}
            out.add("".join(w[-1] for w in run))
        elif op == "middle":
            h = len(t) // 2
            # the plain centre (a lone letter is its own middle), then wider stretches
            out.add(t[h] if len(t) % 2 else t[h - 1:h + 1])
            out |= {t[k:len(t) - k] for k in range(1, (len(t) + 1) // 2)}
        elif op == "outer":
            out |= {t[:k] + t[-k:] for k in range(1, len(t) // 2 + 1)}
            out.add("".join(w[0] + w[-1] for w in run if len(w) > 1))
        elif op == "alternate":
            out |= {t[0::2], t[1::2]}
            # a run that stops short of the last word's end ("Does Joan vouch" for DEJAVU,
            # the odd letters of DOESJOANVOU)
            out |= {t[0::2][:-1], t[1::2][:-1]} if len(t) >= 9 else set()
        elif op == "regular":
            out |= {t[k::step] for step in (2, 3, 4) for k in range(step)}
            # every other pair (DEEP from deCRepIT's pairs) and the letters left once
            # every 2nd/3rd is discarded (LUBE from pLUMBER's P, M, R)
            for step in (2, 3):
                chunks = [t[i:i + step] for i in range(0, len(t), step)]
                out |= {"".join(chunks[k::2]) for k in (0, 1)}
                out |= {"".join(c for i, c in enumerate(t) if i % step != k) for k in range(step)}
        elif op == "nth":
            if len(t) >= n:
                out.add(t[n - 1])
            if all(len(w) >= n for w in run):
                out.add("".join(w[n - 1] for w in run))
            out |= {t[n - 1:n - 1 + k] for k in (2, 3) if len(t) >= n - 1 + k}
    return {x for x in out if x}


def _spoon_sound(sounds, gives):
    """Whether `gives` can be the swap by sound of the two words in `sounds`: spelling
    shifts with the sound (BEST GEAR -> GUESTBEER), so the check is the frame, not the
    letters: it opens and closes as the second word does, and the first word's opening
    letter now sits inside."""
    ws = [letters(w) for w in (sounds or "").split()]
    if len(ws) != 2 or not all(ws) or len(gives) < 4:
        return False
    a, b = ws
    return gives[0] == b[0] and gives[-1] == b[-1] and a[0] != b[0] and a[0] in gives[1:]


def _onset(s):
    m = re.match(r"[^AEIOU][^AEIOUY]*|", s)
    return m.group() if m.group() != s else s[:1]


def _removals_all(f, rs):
    """Letters of each piece of `rs` taken out of `f` in turn (BASTARDS minus T, minus R)."""
    out = {f}
    for r in rs:
        out = set().union(*(_removals(x, r) for x in out)) if out else out
    return out


def _removals(f, r):
    """Every string left when the letters of `r` are taken out of `f`, each once, in
    order: one run (STING from NESTING), or scattered letters (B, Y from EQUABLY)."""
    if not r:
        return {f}
    states = {(0, "")}  # (letters of r gone so far, letters kept so far)
    for i, ch in enumerate(f):
        left = len(f) - i - 1  # letters after this one
        nxt = set()
        for j, kept in states:
            if len(r) - j <= left:
                nxt.add((j, kept + ch))
            if j < len(r) and ch == r[j] and len(r) - j - 1 <= left:
                nxt.add((j + 1, kept))
        states = nxt
        if len(states) > CAP:
            raise WordplayError(f"del({f}, {r}) has too many readings to check: delete in two steps")
    return {kept for j, kept in states if j == len(r)}


def _moves(f, m):
    """Every string `f` becomes when one run `m` of its letters is taken out and put
    back somewhere else (ALBION with its O dropped is ALBINO); never `f` itself."""
    if not m or len(m) >= len(f):
        return set()
    out = set()
    for k in range(len(f) - len(m) + 1):
        if f.startswith(m, k):
            rest = f[:k] + f[k + len(m):]
            out |= {rest[:j] + m + rest[j:] for j in range(len(rest) + 1)}
    return out - {f}


# What a reversal's indicators say about the stretch it turns round, not the whole word.
_ENDS = {"first": 0, "initial": 0, "opening": 0, "start": 0, "head": 0, "top": 0, "front": 0,
         "leading": 0, "beginning": 0, "last": 1, "final": 1, "closing": 1, "end": 1, "tail": 1,
         "bottom": 1, "finally": 1}
_SIZES = {"pair": 2, "couple": 2, "two": 2, "three": 3, "four": 4}
_MIDDLE = {"middle", "centre", "center", "central", "essentially", "inside"}


_SCATTER = {"separately", "variously", "individually", "scattered", "spread", "distributed",
            "dispersed", "apart", "each"}


def _scatters(node):
    """True when a container's indicators say the inner letters go in one by one
    ("variously interrupting", "separately within")."""
    toks = re.findall(r"[a-z]+", " ".join(i.get("text", "") for i in node.get("indicators") or []).lower())
    return any(t in _SCATTER for t in toks)


def _spread_in(o, i):
    """`o` with the letters of `i` dropped in one by one, in order, each at a different
    place inside it (never at either end): "AB variously interrupting LEVEE" is LEAVEBE."""
    if len(i) < 2 or len(i) > len(o) - 1:
        return set()
    return {"".join(o[a:b] + c for a, b, c in zip((0,) + gaps, gaps + (len(o),), tuple(i) + ("",)))
            for gaps in itertools.combinations(range(1, len(o)), len(i))}


def _span_words(node):
    """(sides, sizes, halves, middle): the position words in a reversal's indicators,
    or None when they name no stretch (an ordinary whole-word reversal)."""
    toks = re.findall(r"[a-z]+|\d+", " ".join(i.get("text", "") for i in node.get("indicators") or []).lower())
    sides = {_ENDS[t] for t in toks if t in _ENDS}
    sizes = {_SIZES[t] for t in toks if t in _SIZES} | {int(t) for t in toks if t.isdigit()}
    half = "half" in toks
    middle = any(t in _MIDDLE for t in toks)
    return (sides, sizes, half, middle) if sides or sizes or half or middle else None


def _span_flips(node, v):
    """The strings `v` becomes when the reversal turns round only the stretch its
    indicators name ("last pair of", "turning tail", "half sent back"): a proper stretch
    of 2+ letters at the end they name, of the size they name."""
    named = _span_words(node)
    if not named or len(v) < 3:
        return set()
    sides, sizes, half, middle = named
    out = set()
    for a in range(len(v)):
        for b in range(a + 2, len(v) + 1):
            n = b - a
            if n == len(v):
                continue
            if sizes and n not in sizes:
                continue
            if half and not sizes and n not in (len(v) // 2, (len(v) + 1) // 2):
                continue
            if sides and not middle and not ((0 in sides and a == 0) or (1 in sides and b == len(v))):
                continue
            out.add(v[:a] + v[a:b][::-1] + v[b:])
    return out - {v}


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
        vs = values(parts[0])
        return {v[::-1] for v in vs}.union(*(_span_flips(node, v) for v in vs))
    if op == "container":
        outs = {o[:k] + i + o[k:] for o in values(parts[0]) for i in values(parts[1])
                for k in range(1, len(o))}
        if _scatters(node):
            for o in values(parts[0]):
                for i in values(parts[1]):
                    outs |= _spread_in(o, i)
        return outs
    if op == "deletion":
        out = set()
        for f in values(parts[0]):
            for rs in itertools.product(*(sorted(values(p)) for p in parts[1:])):
                out |= _removals_all(f, rs)
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
        if len(parts) == 1:
            g = letters(parts[0].get("gives"))
            return {g} if _spoon_sound(parts[0].get("soundsLike"), g) else set()
        out = set()
        for a in values(parts[0]):
            for b in values(parts[1]):
                for oa, ob in ((_onset(a), _onset(b)), (a[:1], b[:1])):
                    out.add(ob + a[len(oa):] + oa + b[len(ob):])
        return out
    if op == "substitution" and len(parts) == 2:
        # the centre of x swapped for the other piece, in whichever order they are filed
        out = set()
        for a, b in ((0, 1), (1, 0)):
            for x in values(parts[a]):
                for new in values(parts[b]):
                    out |= {x[:k] + new + x[len(x) - k:] for k in range(1, (len(x) + 1) // 2)}
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
    if op == "repeat":
        return {v + v for v in values(parts[0]) if v}
    if op == "move":
        return {r for f in values(parts[0]) for m in values(parts[1]) for r in _moves(f, m)}
    if op == "palindrome":
        real = lettered(parts)
        if not real:
            # pal() alone: the answer is the wordplay, known only against it.
            raise _NeedTarget(node)
        out = values(real[0] if len(real) == 1 else {"op": "charade", "parts": real})
        return {v for v in out if v == v[::-1]}
    if op in SELECT and len(parts) > 1:
        # one indicator over a list: outer<fringes of>(Argive, Greece, Anatolian) picks from
        # each part in turn and joins the picks in order
        out = {""}
        for p in parts:
            out = {a + b for a in out for b in values({**node, "parts": [p]})}
            if len(out) > CAP:
                raise WordplayError(f"{render(node)} has too many readings to check")
        return out
    if op in SELECT:
        leaf = parts[0]
        if "op" not in leaf and leaf.get("words") and (leaf.get("select") or "gives" not in leaf):
            # a leaf that names its own pick (select: last, gives AM), or the bare clue words
            # (last<last>([Observer's]) is R): the pick is made here from the clue words, with
            # or without a possessive 's
            raw = re.split(r"[\s\-–—/]+", leaf["words"])
            out = set()
            for drop in (False, True):
                ws = [w for w in (letters(re.sub(r"['’]s$", "", w) if drop else w) for w in raw) if w]
                out |= _select(op, node.get("n"), "".join(ws), ws)
            return out
        words = _words(leaf)
        return set().union(*(_select(op, node.get("n"), v, words) for v in values(leaf)))
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
        if op == "repeat":
            return {"".join(sorted(b + b)) for b in _bag(parts_of(node)[0])}
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
        if not ok and _span_words(node):
            try:
                whole = sorted(v for v in values(parts_of(node)[0]) if want in _span_flips(node, v))
            except _NeedTarget:
                whole = []
            if whole:
                ok = match(parts_of(node)[0], whole[0], got) is not None
    elif op == "repeat":
        half = len(want) // 2
        ok = bool(want) and len(want) % 2 == 0 and want[:half] == want[half:] \
            and match(parts_of(node)[0], want[:half], got) is not None
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
            for rs in itertools.product(*(sorted(values(p)) for p in parts_of(node)[1:])):
                if want in _removals_all(f, rs):
                    match(parts_of(node)[0], f, got)
                    for p, r in zip(parts_of(node)[1:], rs):
                        match(p, r, got)
                    ok = True
                    break
            if ok:
                break
    elif op == "move":
        ok = False
        for f in sorted(values(parts_of(node)[0])):
            m = next((m for m in sorted(values(parts_of(node)[1])) if want in _moves(f, m)), None)
            if m is not None:
                match(parts_of(node)[0], f, got)
                match(parts_of(node)[1], m, got)
                ok = True
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
        if ok and op == "cycling" and len(parts_of(node)) == 1:
            # the reading of the part that cycles into the answer, not its default
            for v in sorted(values(parts_of(node)[0])):
                if want in values({**node, "parts": [{"gives": v, "unchecked": True}]}):
                    match(parts_of(node)[0], v, got)
                    break
            else:
                _fill(parts_of(node)[0], got)
        elif ok:
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
        # The shortest reading first: a selection's default is one letter, and a
        # longer stretch is only the answer's to ask for.
        vs = sorted(values(node), key=lambda v: (len(v), v))
    except _NeedTarget:
        return
    if vs:
        # Readings where every selection takes its plain default come first.
        try:
            plain = sorted(values(_defaulted(node)), key=lambda v: (len(v), v))
        except (_NeedTarget, WordplayError):
            plain = []
        match(node, next((v for v in plain if v in vs), vs[0]), got)


def _defaulted(node):
    """A copy of `node` with each selection over a leaf replaced by the letters its
    indicator plainly picks."""
    if not isinstance(node, dict) or node.get("unchecked") or "op" not in node:
        return node
    pick = _default_pick(node)
    if pick:
        return {"gives": pick, "unchecked": True}
    return {**node, "parts": [_defaulted(p) for p in node.get("parts") or []]}


def _default_pick(node, vs=None):
    """What a selection's indicator plainly asks of the leaf's letters (the first,
    the last, the outer pair, the centre, the nth), when that is a reading of it."""
    op, parts = node.get("op"), parts_of(node)
    if op not in ("first", "last", "outer", "middle", "nth") or len(parts) != 1:
        return None
    try:
        for s in sorted(values(parts[0])):
            h = len(s) // 2
            pick = {"first": s[:1], "last": s[-1:], "outer": s[:1] + s[-1:] if len(s) > 1 else "",
                    "middle": s[h] if len(s) % 2 else s[h - 1:h + 1],
                    "nth": s[node["n"] - 1:node["n"]] if node.get("n") else ""}[op]
            if pick and (vs is None or pick in vs):
                return pick
    except _NeedTarget:
        pass
    return None


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
    if _scatters(node):
        for n in sorted(lengths(inner) or range(2, len(want))):
            for pos in itertools.combinations(range(1, len(want) - 1), n):
                trial = dict(got)
                rest = "".join(c for j, c in enumerate(want) if j not in pos)
                if (match(inner, "".join(want[j] for j in pos), trial) is not None
                        and match(outer, rest, trial) is not None):
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


def _hint(node, want):
    """A one-sentence correction for two common right-parse-written-wrong shapes, or None:
    a selection or hidden word over a `+` run (the op applies to the run's letters, not
    to each word), and a spoonerism whose words are wrapped in sound()."""
    op, parts = node.get("op"), parts_of(node)
    if op in SELECT + ("hidden",) and len(parts) == 1 and parts[0].get("op") == "charade":
        pieces = parts_of(parts[0])
        name = NAMES[op]
        if op == "hidden":
            if all("op" not in p and "words" in p and "gives" not in p for p in pieces):
                merged = {"words": " ".join(p["words"] for p in pieces)}
                new = {**node, "parts": [merged]}
                try:
                    ok = match(new, want) is not None
                except (_NeedTarget, WordplayError):
                    ok = False
                if ok:
                    return f"hid() takes one leaf, so a hidden word across words is {render(new)}"
            return f"hid() takes one leaf, not a + list: put the words in one [bracket]"
        new = {**node, "parts": pieces}
        try:
            ok = match(new, want) is not None
        except (_NeedTarget, WordplayError):
            ok = False
        if ok:
            return f"{name}() over a + list works on the joined letters; commas apply it to each word: {render(new)}"
        return f"{name}() over a + list works on the joined letters; commas apply it to each word: {name}(a, b, c)"
    if op == "spoonerism" and "spelt" not in node and any(p.get("op") == "homophone" for p in parts):
        inner = [parts_of(p)[0] if p.get("op") == "homophone" else p for p in parts]
        if (len(inner) == 2 and all("op" not in p and leaf_letters(p) != want for p in inner)
                and _spoon_sound(" ".join(leaf_letters(p) for p in inner), want)):
            return (f"spoon() swaps the starts of its two words itself, so give it the clue words "
                    f"and the spelling heard, not sound(): {render({**node, 'parts': inner, 'spelt': want})}")
        return ("spoon() swaps the starts of its two words itself, so give it the clue words "
                "and the spelling heard, not sound(): spoon(a, b, SPELT)")
    return None


def diagnose(node, want):
    """The deepest node that fails to give its share of `want`, in words."""
    op = node.get("op")
    hint = _hint(node, want)
    if hint:
        return hint
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
        whole, *gones = parts_of(node)
        gone = gones[0] if len(gones) == 1 else {"op": "charade", "parts": gones}
        return (f"{render(node)} gives nothing: {render(gone)} is not letters of "
                f"{render(whole)} in order (one run, or scattered but in the same order). "
                f"Letters taken in another order are one del per piece, e.g. del(del(x, N), OT)")
    return f"{render(node)} gives no letters"


def _count(s):
    return collections.Counter(s)


#: The ops whose evaluation reads a fixed part by position, so the count must be
#: exact. The rest take their shape from elsewhere (a charade has any number, a
#: homophone may carry its spelling in `spelt`, ana() takes a charade's parts).
COUNTED = ("reversal", "repeat", "container", "deletion", "hidden", "substitution", "cycling", "move",
           "spoonerism", *SELECT)


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
        if op == "spoonerism" and len(parts) == 1 and not (
                "op" not in parts[0] and len((parts[0].get("soundsLike") or "").split()) == 2):
            raise WordplayError(f"spoon() takes 2 to 3 part(s), the tree files 1 (a one-part spoon is a leaf whose soundsLike is the two words "
                                f"before the swap, HAD MATTER): {render(node)}")
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
        else:
            _rekey_parts(notes, key, want, free)


_SMALL_WORDS = {"the", "and", "for", "but", "with", "from", "into", "over", "its", "are", "was", "has"}


def _rekey_parts(notes, key, want, free):
    """A note keyed by several free spans' words joined ('Munch nuts' for the
    free [Munch] and [nuts], 'held by' for [held], [by]) lands on each of them;
    one keyed by a phrase round exactly one free span ('Labour leader' for
    [Labour]) lands on that span. The spans' words must be the key's words with
    nothing over (as a multiset, in any order) for the joined form, and a lone
    span must be a word of 3+ letters that is not a small link word. Any other
    overlap stays refused."""
    words = want.split()
    inside = [x for x in free if _is_sub(_fold(x[0][x[1]]).split(), words)]
    if len(inside) > 1:
        got = sorted(w for x in inside for w in _fold(x[0][x[1]]).split())
        if got == sorted(words) and len({id(x[0]) for x in inside}) == len(inside):
            note = notes.pop(key)
            for span, _ in inside:
                span["note"] = note
    elif len(inside) == 1:
        text = _fold(inside[0][0][inside[0][1]])
        if len(words) > len(text.split()) and (len(text.split()) > 1 or
                                                 (len(text) >= 3 and text not in _SMALL_WORDS)):
            inside[0][0]["note"] = notes.pop(key)


def _is_sub(small, big):
    """Whether `small` (a list of words) is a run of `big`, or, for one word, among them."""
    n = len(small)
    return bool(n) and any(big[i:i + n] == small for i in range(len(big) - n + 1))


def translate(clue_out, clue, answer, taken=(), respell=None):
    """The stored tree for one clue of model output ({"wp", "notes"}),
    checked against `answer`. Notes are keyed by span words (`#2` for a
    repeat), or a bare piece's letters, and land on the span they name.
    `taken` are (start, end) clue spans already used (the definitions), so a
    word in both picks another copy; `respell(text, clue)` spells each span's
    words as the clue prints them first (a retyped apostrophe or capital)."""
    tree = parse(clue_out["wp"])
    _split_ellipsis(tree, clue)
    if respell:
        for span, key in _spans(tree):
            if not re.search(r"#\d+$", span[key]):
                span[key] = respell(span[key], clue)
    locate(tree, clue, taken)
    notes = dict(clue_out.get("notes") or {})
    seen = {}
    raw_tree = parse(clue_out["wp"])
    _split_ellipsis(raw_tree, clue)
    raw = list(_spans(raw_tree, True))
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
    if notes and not [1 for s, k in _spans(tree, True) if "note" not in s]:
        # Every span has its note: a leftover is a stray extra (the commonest 'name no
        # span' refusal in the annotate bag), and dropping it loses nothing.
        notes.clear()
    if notes:
        keys = [s[k] for s, k in _spans(tree, True) if "note" not in s]
        raise WordplayError(f"notes {sorted(notes)} name no span of the wordplay; key each "
                            f"note by its words as written in the expression"
                            + (f" (spans with no note yet: {keys})" if keys else
                               " (every span has a note already)"))
    _quote_bare_words(tree, clue, taken)
    try:
        evaluate(tree, answer)
    except WordplayError as err:
        tree = (_with_picks_dropped(tree, answer) or _with_hidden_merged(tree, clue, answer)
                or _with_after_swapped(tree, answer))
        if tree is None:
            left = unaccounted_words(locate_copy(clue_out, clue, taken), clue, taken)
            if left and "does not give" in str(err):
                raise WordplayError(f"{err}; clue words no leaf, indicator or definition covers "
                                    f"(a piece may be missing, or they are link words): "
                                    f"{', '.join(repr(w) for w in left)}") from None
            raise err
    return normalize(tree, clue, answer)[0]


def _quote_bare_words(tree, clue, taken=()):
    """Bare letters that spell, whole, a word or run of 2-3 words the clue prints
    exactly once and no leaf, indicator or definition covers get those words
    quoted: `ins<helmeted>(HAT, ...)` for the clue word 'hat' becomes
    `ins<helmeted>([hat]HAT, ...)`. The first check's 'a block with no
    clueFragment' (110 sessions in the 10-24/25 audit) is for letters the preamble
    supplies, and letters that are a clue word, spelt out, are that word's. Only
    3+ letters, one copy and one reading (a second uncovered run spelling the same
    letters is ambiguous): the rest stays refused."""
    used = [(s["at"], s["at"] + len(s[k])) for s, k in _spans(tree) if "at" in s] + list(taken)
    words = [(m.start(), m.end()) for m in re.finditer(r"[\w'’]+", clue)]
    for node in _all_nodes(tree):
        if "op" in node or "words" in node or node.get("unchecked"):
            continue
        want = re.sub(r"[^a-z]", "", str(node.get("gives") or "").lower())
        if len(want) < 3 or not str(node.get("gives") or "").isalpha():
            continue
        hits = []
        for i in range(len(words)):
            for j in range(i, min(i + 3, len(words))):
                a, b = words[i][0], words[j][1]
                if re.sub(r"[^a-z]", "", clue[a:b].lower()) == want and not any(a < y and x < b for x, y in used):
                    hits.append((a, b))
        if len(hits) == 1:
            a, b = hits[0]
            node["words"], node["at"] = clue[a:b], a
            used.append((a, b))


def _all_nodes(node):
    yield node
    for p in node.get("parts") or []:
        yield from _all_nodes(p)


def locate_copy(clue_out, clue, taken):
    """The model's wp parsed and located against `clue`, for reading spans only."""
    tree = parse(clue_out["wp"])
    _split_ellipsis(tree, clue)
    locate(tree, clue, taken)
    return tree


def unaccounted_words(tree, clue, taken=()):
    """The clue's words that no leaf, indicator or taken span (the definition) covers,
    in clue order: a wordplay that misses the answer has often left a piece out."""
    covered = list(taken)
    for span, key in _spans(tree):
        if "at" in span:
            covered.append((span["at"], span["at"] + len(span[key])))
    out = []
    for m in re.finditer(r"[\w'’]+", clue):
        if not any(a < m.end() and m.start() < b for a, b in covered):
            out.append(m.group(0))
    return out


#: Indicators that put the first piece of a two-piece charade after (or under) the second.
AFTER_WORDS = frozenset({
    "after", "following", "follows", "to follow", "behind", "pursuing", "chasing", "trailing",
    "on", "put on", "supporting", "in support of", "under", "underneath", "beneath", "below",
    "undermining"})


def _with_after_swapped(tree, answer):
    """A copy of `tree` with swap_after_pieces() applied when that makes it give
    `answer`, else None."""
    repaired = copy.deepcopy(tree)
    if not swap_after_pieces(repaired):
        return None
    try:
        evaluate(repaired, answer)
    except WordplayError:
        return None
    return repaired


def swap_after_pieces(tree):
    """[Politician]MP +<after> [tea]CHA is MP after CHA, written in clue order where a
    charade is in answer order (CHA + MP): the commonest charade slip among the
    'does not give the answer' refusals. A two-piece charade whose indicator says the
    first piece sits after (or under) the second has its pieces swapped. Returns how
    many charades changed; translate() keeps the change only when the tree then
    gives the answer, so a charade written in answer order, or an indicator that
    is not a placement, is never touched."""
    changed = 0
    for node in _walk(tree):
        parts = node.get("parts") or []
        inds = node.get("indicators") or []
        if (node.get("op") == "charade" and len(parts) == 2 and len(inds) == 1
                and inds[0].get("text", "").strip().lower() in AFTER_WORDS):
            parts.reverse()
            changed += 1
    return changed


def _with_hidden_merged(tree, clue, answer):
    """A copy of `tree` with merge_hidden_run() applied when that makes it give
    `answer`, else None."""
    repaired = copy.deepcopy(tree)
    if not merge_hidden_run(repaired, clue):
        return None
    try:
        evaluate(repaired, answer)
    except WordplayError:
        return None
    return repaired


def merge_hidden_run(tree, clue):
    """hid<ind>([Sign] + [a] + [road's]) is hid<ind>([Sign a road's]): a hidden word
    runs across the clue's words, which the run writes as a charade of one leaf per
    word where hid() wants one leaf (the 'hid() takes one leaf' refusal, the commonest
    sub-cause of 'wordplay does not give the answer'). The leaves, plain clue words
    with no letters of their own, that sit side by side in the clue are joined in
    place into one leaf, their notes joined. Returns how many hid() nodes changed;
    translate() keeps the change only when the tree then gives the answer."""
    changed = 0
    for node in _walk(tree):
        parts = node.get("parts") or []
        if node.get("op") != "hidden" or len(parts) != 1 or parts[0].get("op") != "charade":
            continue
        leaves = parts[0].get("parts") or []
        if (len(leaves) < 2 or parts[0].get("indicators")
                or not all("op" not in p and p.get("words") and "at" in p and "gives" not in p
                           and not p.get("select") and not p.get("unchecked") for p in leaves)):
            continue
        if any(clue[a["at"] + len(a["words"]):b["at"]].strip(" \t") or b["at"] < a["at"] + len(a["words"])
               for a, b in zip(leaves, leaves[1:])):
            continue
        first, last = leaves[0], leaves[-1]
        merged = {"words": clue[first["at"]:last["at"] + len(last["words"])], "at": first["at"]}
        notes = [p["note"].rstrip(". ") for p in leaves if p.get("note")]
        if notes:
            merged["note"] = "; ".join(notes)
        node["parts"] = [merged]
        changed += 1
    return changed


def _with_picks_dropped(tree, answer):
    """A copy of `tree` with drop_written_picks() applied when that makes it give
    `answer`, else None."""
    repaired = copy.deepcopy(tree)
    if not drop_written_picks(repaired):
        return None
    try:
        evaluate(repaired, answer)
    except WordplayError:
        return None
    return repaired


def drop_written_picks(tree):
    """Drop the letters of each leaf a selection op picks from that are already
    the op's pick from the leaf's own words: alt<regularly>([most]MS) is
    alt<regularly>([most]), since MS is the alternate letters of "most" and
    alternating MS again would give M or S. The commonest refusal in the
    annotate runs (a third of them): the run writes what the selection gives
    where the op wants the clue words it picks from. A leaf whose letters are
    no pick of its words ([dog]CUR under last) is a synonym the op picks
    from, and stays. Returns how many leaves changed; translate() keeps the
    change only when the tree then gives the answer."""
    changed = 0
    for node in _walk(tree):
        if node.get("op") not in SELECT:
            continue
        for leaf in parts_of(node):
            if ("op" in leaf or "gives" not in leaf or not leaf.get("words")
                    or leaf.get("select") or leaf.get("unchecked")):
                continue
            bare = {k: v for k, v in leaf.items() if k != "gives"}
            try:
                picks = values({**node, "parts": [bare]})
            except (WordplayError, _NeedTarget):
                continue
            if letters(leaf["gives"]) in picks:
                del leaf["gives"]
                changed += 1
    return changed


def normalize(tree, clue, answer):
    """(tree, [rewrites]): the canonical shape of a tree whose letters already check, by code
    (tools/tree_normalize.py: deletion inside the piece it cuts, one selection over a list,
    one reversal over adjacent reversed pieces). Run after evaluate(); a rewrite is kept only
    when evaluate() still gives the answer, so the letters are proved unchanged."""
    import tree_normalize
    try:
        new, used = tree_normalize.normalize(tree, clue, answer)
    except Exception:
        return tree, []
    if used:
        evaluate(new, answer)
    return (new, used) if used else (tree, [])


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
