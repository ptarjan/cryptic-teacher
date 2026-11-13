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
import groups
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


# Characters that print alike and compare unequal: Guardian clues use curly
# quotes and en dashes, the Independent's straight ones and hyphens, and a model
# retyping clue words writes whichever it prefers. Each maps one code point to
# one, so a folded match sits at the same offsets in the real clue.
LOOKALIKES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"',
                            "\u201d": '"', "\u2013": "-", "\u2014": "-"})
WORD = re.compile(r"[^\W_]+")
# The enumeration the clue is shown with, "(5,8)" or "(2-3, 4)", which a model copies
# onto a definition although the clue's `text` keeps it apart.
ENUM_TAIL = re.compile(r"\s*\(\d+(?:\s*[,\-]\s*\d+)*\)\s*$")


def respell(text, clue):
    """`text` spelt as `clue` prints it: the clue's own characters for the same
    run of clue words, when the two differ only in quote marks and dashes, in
    case, or in the spaces and punctuation between the words ("Type of shirt"
    for "type of shirt", "that, Parisian" for "that Parisian"). `text` itself
    when it is in the clue already, or names no single run of clue words. A
    dash or ellipsis is spelt as the clue spells it first (dashes.quote): a
    link word "-" for the clue's " — " is "—", not the hyphen in "Non-U"."""
    import dashes  # lazy: dashes imports enumeration, which this module's users import
    if isinstance(text, str) and isinstance(clue, str):
        text = dashes.quote(text, clue)
    if not isinstance(text, str) or not text or text in clue:
        return text
    bare = ENUM_TAIL.sub("", text)
    if bare and bare != text:
        spelt = respell(bare, clue)
        if spelt in clue:
            return spelt
    i = clue.translate(LOOKALIKES).find(text.translate(LOOKALIKES))
    if i >= 0:
        return clue[i:i + len(text)]
    want = [w.casefold() for w in WORD.findall(text.translate(LOOKALIKES))]
    words = list(WORD.finditer(clue))
    n = len(want)
    found = {_with_edges(text, clue, words[k].start(), words[k + n - 1].end())
             for k in range(len(words) - n + 1)
             if [w.group().casefold() for w in words[k:k + n]] == want} if n else set()
    if len(found) == 1:
        return found.pop()
    return damaged_run(text, clue, misread=False) or text


def _fold_accents(s):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))


# A last word the clue prints whole but for one of these endings is the model's inflection, not a cut.
INFLECTIONS = {"s", "es", "d", "ed", "ing", "ly", "er", "ers", "est", "y"}


def damaged_run(text, clue, misread=True):
    """The clue's one run that `text` quotes when the clue is scan-damaged (the
    refusals' commonest cause: the model quotes the clue as printed, the stored
    clue has the scan's debris): a word broken by a hyphen or spaces ('dis,
    patched'), a stray capital or 'Check tod' banner between or inside words, a
    final word cut short ('a br' for 'a bribe'), an accent the quote dropped
    ('Bronte' for 'Brontë'). The clue's own characters for the run, or None
    when no run or more than one fits (that stays refused). `misread` also takes a
    run a letter or two off the quote's (the scan read a letter wrong: apply's
    mend; a committed fragment that far from its clue wants a printedClue)."""
    if not isinstance(text, str) or not isinstance(clue, str):
        return None
    want = [w.casefold() for w in WORD.findall(_fold_accents(text.translate(LOOKALIKES)))]
    toks = [(m.group(), m.start(), m.end()) for m in WORD.finditer(clue)]
    if not want or not toks:
        return None
    low = [_fold_accents(t[0]).casefold() for t in toks]
    # a lone capital, or a short all-capital string the quote does not use, is the scan's
    # stray print ('stan- AI. hard', 'sum LOHEN'); a real word the quote skips is not.
    junk = [bool(re.fullmatch(r"[A-HJ-Z]", t[0]))
            or bool(re.fullmatch(r"[A-Z]{2,4}", t[0]) and not any(w.startswith(low[k]) or w.endswith(low[k]) for w in want))
            for k, t in enumerate(toks)]
    for k in range(len(toks) - 1):
        if toks[k][0] == "Check" and low[k + 1] in ("tod", "toc"):
            junk[k] = junk[k + 1] = True
    runs = set()

    def word(qi, ci, first):
        """Ends (clue token index after, last used) matching want[qi] from token ci."""
        q, got, out = want[qi], "", []
        j = ci
        while j < len(toks):
            if junk[j]:
                if got == "" and first:
                    return out        # no debris at the run's edge
                j += 1
                continue
            got += low[j]
            if got == q:
                out.append(j)
            if not q.startswith(got):
                # the last word of the quote may be longer than the clue's cut-short end
                break
            j += 1
        if qi == len(want) - 1 and got and q.startswith(got) and got != q and len(got) >= 2 \
                and j == len(toks) and q[len(got):] not in INFLECTIONS:
            out.append(j - 1)
        return out

    def walk(qi, ci, start):
        for last in word(qi, ci, qi == 0):
            if qi == len(want) - 1:
                runs.add((start if start is not None else toks[ci][1], toks[last][2]))
            else:
                walk(qi + 1, last + 1, start if start is not None else toks[ci][1])

    for ci in range(len(toks)):
        if not junk[ci]:
            walk(0, ci, None)
    if not runs and misread:
        runs = _misread_runs(want, toks, low, junk)
    if len(runs) != 1:
        return None
    a, b = runs.pop()
    return clue[a:b]


# Letters a scan reads for one another: a quote that differs from the clue by one letter
# or by two of these pairs is the scan's misreading, not the model's.
_CONFUSED = {frozenset(p) for p in ("ce", "co", "eo", "ct", "et", "il", "it", "lt", "1l", "1i",
                                    "0o", "nu", "hb", "hl", "ao", "ft", "fl")}


def _lev(a, b):
    """Edit distance of a and b, a swap of two confusable letters costing half."""
    prev = [float(i) for i in range(len(b) + 1)]
    for i, ca in enumerate(a, 1):
        cur = [float(i)]
        for j, cb in enumerate(b, 1):
            swap = 0 if ca == cb else 0.5 if frozenset((ca, cb)) in _CONFUSED else 1
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + swap))
        prev = cur
    return prev[-1]


def _cut_short(q, parts):
    """True when the clue's word pieces `parts` (a window's tokens) spell the quote `q`
    but for one or two letters dropped from the inside or end of a word, as a scan
    cuts them ('unexpect' for 'unexpected', 'matin' for 'matinee', 'Th' for 'That'):
    never the start of a word, which would turn 'steadily' into 'unsteadily'."""
    got = "".join(parts)
    gap = len(q) - len(got)
    if not 1 <= gap <= 2 or len(got) < 3:
        return False
    starts = {sum(map(len, parts[:k])) for k in range(len(parts))}
    for k in range(1, len(got) + 1):
        if k not in starts and q == got[:k] + q[k:k + gap] + got[k:]:
            return True
    return False


def _word_bounds(want):
    """(start, end) of each word of the quote's letters run together."""
    out, at = [], 0
    for w in want:
        out.append((at, at + len(w)))
        at += len(w)
    return out


def _misread_runs(want, toks, low, junk):
    """{(start, end)} of the clue's run of words whose letters, run together, are the
    quote's letters give or take the scan's misreading: a letter read wrong or
    dropped ('Oil' for 'Coil', 'show' for 'snow'), confusable letters
    ('set-end' for 'second'), a word cut short ('caf' for 'cafes') or split with a
    letter misread ('Ec ward' for 'Edward'). Only the closest fit counts, and only
    when it is the one: two equally close runs, or a quote under four letters,
    mend nothing."""
    q = "".join(want)
    if len(q) < 4:
        return set()
    idx = [i for i in range(len(toks)) if not junk[i]]
    best, found = None, set()
    for a in range(len(idx)):
        got = ""
        for b in range(a, min(len(idx), a + len(want) + 3)):
            got += low[idx[b]]
            if abs(len(got) - len(q)) > 2:
                if len(got) > len(q):
                    break
                continue
            if q.startswith(got) and q[len(got):] in INFLECTIONS \
                    or got.startswith(q) and got[len(q):] in INFLECTIONS:
                continue          # the model's own inflection of the clue's word, not a misreading
            cut = _cut_short(q, [low[k] for k in idx[a:b + 1]])
            if not cut and any(_lev(q[:x] + q[y:], got) <= _lev(q, got) for x, y in _word_bounds(want)):
                continue          # the fit only drops a whole word of the quote ('a step' for 'step')
            edges = {x for x, _ in _word_bounds(want)} | {len(q)}
            if b > a and not cut and any(
                    (x in edges or x == 0 or y == len(got)) and _lev(q, got[:x] + got[y:]) <= _lev(q, got)
                    for x, y in _word_bounds([low[k] for k in idx[a:b + 1]])):
                continue          # a whole clue word the quote leaves out ('keep a' for 'keeps', 'Dog I saw');
                                  # one inside a quote's word ('avail a able') is the scan's split
            d = len(q) - len(got) if cut else _lev(q, got)
            if d <= 1 or (d <= 2 and cut):
                rank = (d, abs(b - a + 1 - len(want)))
                if best is None or rank < best:
                    best, found = rank, set()
                if rank == best:
                    found.add((toks[idx[a]][1], toks[idx[b]][2]))
    return found


def _one_edit(a, b):
    """True when `a` and `b` differ by one letter: swapped, dropped, added or changed."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        d = [i for i in range(len(a)) if a[i] != b[i]]
        return len(d) == 1 or (len(d) == 2 and d[1] == d[0] + 1
                               and a[d[0]] == b[d[1]] and a[d[1]] == b[d[0]])
    s, l = sorted((a, b), key=len)
    return any(l[:i] + l[i + 1:] == s for i in range(len(l)))


def near_run(text, clue):
    """The clue's one run of as many words as `text` that reads the same but for one
    word a letter off (four letters or more), as the clue prints it; else None.
    Only ever a hint for the refusal: whether the quote or the clue is the one that
    slipped (a scan's cut word, or the model's own typo) is not decidable here."""
    if not isinstance(text, str) or not isinstance(clue, str):
        return None
    want = [_fold_accents(w).casefold() for w in WORD.findall(text.translate(LOOKALIKES))]
    toks = [(m.start(), m.end(), _fold_accents(m.group()).casefold()) for m in WORD.finditer(clue)]
    n = len(want)
    runs = set()
    for k in range(len(toks) - n + 1 if n else 0):
        diff = [(w, t[2]) for w, t in zip(want, toks[k:k + n]) if w != t[2]]
        if len(diff) == 1 and min(map(len, diff[0])) >= 4 and _one_edit(*diff[0]):
            runs.add((toks[k][0], toks[k + n - 1][1]))
    if len(runs) != 1:
        return None
    a, b = runs.pop()
    return clue[a:b]


def _with_edges(text, clue, start, end):
    """clue[start:end], widened over the punctuation `text` has before its
    first word and after its last where the clue prints the same marks."""
    folded = clue.translate(LOOKALIKES)
    lead = re.match(r"\W*", text.translate(LOOKALIKES)).group()
    trail = re.search(r"\W*$", text.translate(LOOKALIKES)).group()
    for ch in reversed(lead):
        if start and folded[start - 1] == ch and not ch.isspace():
            start -= 1
        else:
            break
    for ch in trail:
        if end < len(clue) and folded[end] == ch and not ch.isspace():
            end += 1
        else:
            break
    return clue[start:end]


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
            if d["text"] not in clue and "#" not in d["text"]:
                d["text"] = damaged_run(d["text"], clue) or d["text"]
            m = re.fullmatch(r"(.+?)#(\d+)", d["text"]) if "#" in d["text"] else None
            if m and d["text"] not in clue and "at" not in d:
                # 'talk#2' as in a wordplay quote: the nth copy of the words; the
                # only copy when the clue prints them once.
                base, n = respell(m.group(1), clue), int(m.group(2))
                found = candidates(base, clue)
                if found and base in clue:
                    d["text"] = base
                    d["at"] = found[n - 1] if len(found) >= n else found[0] if len(found) == 1 else None
                    if d["at"] is None:
                        del d["at"]
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
                near = near_run(text, clue)
                why.append(f"definition {text!r} is not in the clue {clue!r}"
                           + (f": the clue as given reads {near!r} there, a letter off; quote the "
                              f"clue's own words" if near else ""))
            else:
                why.append(f"definition {text!r} occurs {len(found)} times in {clue!r} "
                           f"(at {', '.join(map(str, found))}) and the rules in "
                           f"tools/definitions.py do not pick one: give its `at`")
        raise ValueError("; ".join(why))
    return sorted(defs, key=lambda d: d["at"])


def place_puzzle(puzzle):
    """`puzzle` with every annotation's definitions placed; raises ValueError,
    naming the entry, for one `place` cannot place."""
    # Each clue holder: an entry, and each further answer it starts (alsoLeads).
    held = [(entry_id(e), h) for e in puzzle.get("entries", []) for h in [e] + list(e.get("alsoLeads") or [])]
    held += groups.off_grid(puzzle)   # and each clue entered off the grid
    for eid, h in held:
        ann = h.get("annotation")
        if not isinstance(ann, dict) or not isinstance(ann.get("definitions"), list):
            continue
        if not all(isinstance(d, dict) for d in ann["definitions"]):
            continue
        if not (h["clue"].get("text") or "").strip():
            continue   # a blank clue (an OCR read left it empty) has no words to place a definition in
        try:
            ann["definitions"] = place(ann["definitions"], h["clue"].get("text", ""))
        except ValueError as err:
            raise ValueError(f"{puzzle.get('id')} {eid}: {err}") from None
    return puzzle


def texts(ann):
    """The definition texts of an annotation, in clue order."""
    return [d["text"] for d in (ann or {}).get("definitions") or [] if d.get("text")]
