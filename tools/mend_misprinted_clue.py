"""Mechanical mend for an annotation that quotes a clue word the clue prints misspelt ('attempt' for
the clue's 'arrempt'): the refusal "... is not in the clue" cost a model turn or three (printedClue
before the first check), the top first-check failure in the 11-21 annotate cost audit.

The direction rule that keeps a model slip from becoming a silent wrong annotation: the clue is the one
that is repaired only when the QUOTE's word is a word (the lexicon has it), the clue's word is not (not the
lexicon's, nor a word the corpus's clues use), exactly one clue word is within two edits of it, and the
word is six letters or more. 'sort' for 'sought' (both words), 'Maphigian' for 'Malpighian' (neither in
the lexicon), 'balme' for 'blame' (the quote is the slip: definitions._typo_runs mends that one) are left.
The repaired clue goes to `printedClue` and is checked by file_rows like the model's own."""
import re

import clue_text as ct
import definitions
import ocr_clues
import validate_annotations as V
import wordplay

WORD = re.compile(r"[\w'’]+")
MIN_LEN = 6
MAX_EDITS = 2
DECLARED_EDITS = 3      # the model named both words, so the OCR edit cap (V.OCR_MISREAD_EDITS) is the limit
EVIDENCE = "OCR misread: the text has {c!r} where the wordplay needs {q!r}"
# Pairs of real words the OCR reads for one another so often (11-17..21 audit: 9 'quote not in clue'
# refusals of 'five' for the clue's 'few', the 'fi' read as 'e'): clue word -> the word the quote has.
KNOWN_MISREADS = {"few": "five"}
def quotes(a):
    """The clue words an annotation quotes: its `def` and the pieces of its `wp`."""
    out = []
    if isinstance(a.get("def"), str):
        out.append(a["def"])
    try:
        tree = wordplay.parse(a.get("wp"))
        out += [d[k] for d, k in wordplay._spans(tree) if isinstance(d.get(k), str)]
    except Exception:
        pass
    return out


def repaired(quoted, clue):
    """(the clue with its misprints mended, [(clue word, quote word)]); (None, []) when none is."""
    toks = [(m.group(), m.start(), m.end()) for m in WORD.finditer(clue)]
    have = {t[0].casefold() for t in toks}
    said = {w.casefold() for q in quoted for w in WORD.findall(q)}
    swaps = {}
    for q in quoted:
        for w in WORD.findall(q):
            if w.casefold() in have or len(w) < MIN_LEN or not w.isalpha() or not ocr_clues.is_word(w):
                continue
            near = [t for t in toks if t[0].isalpha() and t[0].casefold() not in said
                    and definitions._lev(w.casefold(), t[0].casefold()) <= MAX_EDITS
                    and not ocr_clues.known(t[0])]
            if len(near) == 1 and sum(t[0] == near[0][0] for t in toks) == 1:
                swaps[near[0][1]] = (near[0], w)
    swaps.update(_look_alike_swaps(quoted, toks, have, said, swaps))
    # two quote words claiming one clue word is no repair
    if not swaps or len({v[1].casefold() for v in swaps.values()}) != len(swaps):
        return None, []
    new = clue
    for start, ((c, _, end), w) in sorted(swaps.items(), reverse=True):
        new = new[:start] + (w[0].upper() + w[1:] if c[0].isupper() else w) + new[end:]
    return new, [(c, w) for (c, _, _), w in swaps.values()]


def _look_alike_swaps(quoted, toks, have, said, taken):
    """{clue offset: (clue token, quote word)} for each quote word the clue lacks that is a clue
    token's look-alike (glyph_fold: 'A1' or 'Ai' for the clue's 'Al', 'turn' for 'tum') or the
    word the OCR is known to give for it (KNOWN_MISREADS). The clue token must be the only one of
    its fold and occur once, and the quote's own words must not use it: any length, since the
    glyphs, not a lexicon, are the evidence."""
    out = {}
    for q in quoted:
        for w in WORD.findall(q):
            if w.casefold() in have or not w.isalnum():
                continue
            near = [t for t in toks if t[0].casefold() not in said and t[0].casefold() != w.casefold()
                    and (ct.glyph_fold(t[0]) == ct.glyph_fold(w) or KNOWN_MISREADS.get(t[0].casefold()) == w.casefold())]
            if len(near) == 1 and near[0][1] not in taken and sum(t[0] == near[0][0] for t in toks) == 1 \
                    and sum(ct.glyph_fold(t[0]) == ct.glyph_fold(near[0][0]) for t in toks) == 1:
                out[near[0][1]] = (near[0], w)
    return out


def declared(quoted, clue, evidence):
    """(the clue with the one misprint the model's own evidence names mended, [(clue word, quote word)])
    for a printedClue that corrected nothing ('OCR misread: five (V) for few' beside the clue as shown):
    the model said which clue word it read as which, so both words may be real words and short (the
    plain rule needs six letters and a non-word). A quote word absent from the clue (a word, a digit
    or a letter) that the evidence names takes the one unquoted clue word that is its look-alike
    (glyph_fold: the clue's '4' for 'A'), or within three edits when the evidence names that word too,
    or within two (one if a short word has a digit, else none) when it does not ('chain' for 'plain',
    '1dn' for 'dn'); once in the clue. More than one such clue word is no mend. Failing that, the run of clue the
    evidence quotes ('read as 'El /.'') is the debris of the one absent quote word and is replaced by it."""
    said_ev = {w.strip("'’").casefold() for w in WORD.findall(evidence)}     # 'aid' quoted is aid
    toks = [(m.group(), m.start(), m.end()) for m in WORD.finditer(clue)]
    have = {t[0].casefold() for t in toks}
    said = {w.casefold() for q in quoted for w in WORD.findall(q)}
    absent = {w.casefold(): w for q in quoted for w in WORD.findall(q)
              if w.casefold() not in have and w.isalnum() and w.casefold() in said_ev}
    swaps = {}
    for w in absent.values():
        cap = 2 if len(w) >= 4 else int(any(c.isdigit() for c in w))
        near = [t for t in toks if t[0].isalnum() and t[0].casefold() not in said
                and (ct.glyph_fold(t[0]) == ct.glyph_fold(w)
                     or definitions._lev(w.casefold(), t[0].casefold())
                     <= (DECLARED_EDITS if t[0].casefold() in said_ev and len(w) >= 3 else cap))]
        if len(near) == 1 and sum(t[0] == near[0][0] for t in toks) == 1:
            swaps[near[0][1]] = (near[0], w)
    if swaps and len({v[1].casefold() for v in swaps.values()}) == len(swaps):
        new = clue
        for start, ((c, _, end), w) in sorted(swaps.items(), reverse=True):
            new = new[:start] + (w[0].upper() + w[1:] if c[0].isupper() else w) + new[end:]
        return new, [(c, w) for (c, _, _), w in swaps.values()]
    for found in (_anchored(absent, toks, said, clue, evidence), _run_swap(quoted, absent, toks, clue)):
        if found:
            return found
    runs = [r for r in re.findall(r"'([^']{2,20})'", evidence) if clue.count(r) == 1]
    if len(absent) == 1 and len(runs) == 1:
        (w,) = absent.values()
        return clue.replace(runs[0], w), [(runs[0], w)]
    return None, []


def _anchored(absent, toks, said, clue, evidence):
    """(the clue with the one absent quote word put in, [(clue word, quote word)]) when the evidence
    quotes the words round it and exactly one placing makes the clue hold them: 'No. 10?' for the
    clue's 'No. To?' (the '10' the model quoted), 'Ill-bred' for 'Il-bred', 'E.g.A. Bronte' for
    'L.g.A. Bronte', or the word the scan dropped ('to a filthy' for 'to filthy': a short word, put
    between the two clue words the evidence has it between). The words round it are the anchor, so
    a clue word merely near the quote's is not enough; two placings that hold the anchor mend nothing."""
    tail = evidence.rsplit(":", 1)[-1]
    chunks = [c.strip(",;:") for c in tail.split()]
    lowclue = clue.casefold()
    tailwords = {x.strip("'’").casefold() for x in WORD.findall(tail)}     # a word the evidence keeps is not swapped out
    out = []
    for w in absent.values():
        ctxs = []
        for i, c in enumerate(chunks):
            if w.casefold() in {x.strip("'’").casefold() for x in WORD.findall(c)}:
                ctxs += [c] if len(c) > len(w) else []
                ctxs += [" ".join(chunks[i - 1:i + 1])] if i else []
                ctxs += [" ".join(chunks[i:i + 2])] if i + 1 < len(chunks) else []
        ctxs = [c.casefold() for c in ctxs if w.casefold() in c.casefold() and c.casefold() not in lowclue]
        if not ctxs:
            return None
        subs = [(t, clue[:t[1]] + w + clue[t[2]:]) for t in toks
                if t[0].casefold() not in said | tailwords and definitions._lev(w.casefold(), t[0].casefold()) <= DECLARED_EDITS]
        subs = [(t, c) for t, c in subs if any(x in c.casefold() for x in ctxs)]
        ins = []
        if len(w) <= 3 and w.isalpha():
            mine = " ".join(WORD.findall(tail)).casefold()
            plain = " ".join(WORD.findall(clue)).casefold()
            for t, u in zip(toks, toks[1:]):
                tri = " ".join([t[0], w, u[0]]).casefold()
                if clue[t[2]:u[1]].strip() == "" and tri in mine and tri not in plain:
                    ins.append((None, clue[:t[2]] + " " + w + clue[t[2]:]))
        placings = subs + ins
        if len(placings) != 1:
            return None
        t, new = placings[0]
        out.append((new, (t[0] if t else "", w)))
    if len(out) != 1:
        return None
    return out[0][0], [out[0][1]]


def _run_swap(quoted, absent, toks, clue):
    """(the clue with the garbled run replaced by the quote's word, [(run, word)]) when a quote has the
    one absent word between words the clue has on both sides and the clue's words between them are one
    or two scrap tokens of two letters or fewer ('like 8 S horse' for 'like a horse'): the model read
    through debris the scan left. Exactly one such run in the clue, and one absent word."""
    if len(absent) != 1:
        return None
    (w,) = absent.values()
    low = [t[0].casefold() for t in toks]
    runs = set()
    for q in quoted:
        qw = [x.casefold() for x in WORD.findall(q)]
        if w.casefold() not in qw:
            continue
        i = qw.index(w.casefold())
        before, after = qw[:i], qw[i + 1:]
        if not before or not after:
            continue
        for k in range(len(toks)):
            for gap in (1, 2):
                a, b = k + len(before), k + len(before) + gap
                if (low[k:a] == before and low[b:b + len(after)] == after and a < b <= len(toks)
                        and all(len(t[0]) <= 2 for t in toks[a:b])):
                    runs.add((toks[a][1], toks[b - 1][2]))
    if len(runs) != 1:
        return None
    (s, e), = runs
    return clue[:s] + w + clue[e:], [(clue[s:e], w)]


def mend(a, shown, source_ocr):
    """printedClue [clue as printed, evidence] for model-shape annotation `a` against the clue as
    shown, or None. Only an OCR'd source (a printed word read wrong), never one that has a printedClue
    already or whose repair V.clue_row_problems / the OCR edit cap would refuse."""
    if not (isinstance(a, dict) and source_ocr and shown):
        return None
    pc = a.get("printedClue")
    if pc is not None and not (isinstance(pc, list) and len(pc) == 2 and all(isinstance(x, str) for x in pc)
                               and pc[0].strip() == shown.strip()):
        return None       # a printedClue that corrects something is the model's own: left
    new, pairs = declared(quotes(a), shown, pc[1]) if pc else (None, [])
    why = pc[1] if pc and len(pc[1]) >= 25 else "; ".join(EVIDENCE.format(c=c, q=q) for c, q in pairs)
    if not new:
        new, pairs = repaired(quotes(a), shown)
        why = "; ".join(EVIDENCE.format(c=c, q=q) for c, q in pairs)
    if not new:
        return None
    if V.clue_row_problems(shown, new, why) or V.ocr_misread_edits(shown, new) > V.OCR_MISREAD_EDITS:
        return None
    return [new, why]
