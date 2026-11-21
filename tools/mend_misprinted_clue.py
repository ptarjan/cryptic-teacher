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
    said_ev = {w.casefold() for w in WORD.findall(evidence)}
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
    runs = [r for r in re.findall(r"'([^']{2,20})'", evidence) if clue.count(r) == 1]
    if len(absent) == 1 and len(runs) == 1:
        (w,) = absent.values()
        return clue.replace(runs[0], w), [(runs[0], w)]
    return None, []


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
