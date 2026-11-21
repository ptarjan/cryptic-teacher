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

import definitions
import ocr_clues
import validate_annotations as V
import wordplay

WORD = re.compile(r"[\w'’]+")
MIN_LEN = 6
MAX_EDITS = 2
DECLARED_EDITS = 3      # the model named both words, so the OCR edit cap (V.OCR_MISREAD_EDITS) is the limit
EVIDENCE = "OCR misread: the text has {c!r} where the wordplay needs {q!r}"


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
    # two quote words claiming one clue word is no repair
    if not swaps or len({v[1].casefold() for v in swaps.values()}) != len(swaps):
        return None, []
    new = clue
    for start, ((c, _, end), w) in sorted(swaps.items(), reverse=True):
        new = new[:start] + (w[0].upper() + w[1:] if c[0].isupper() else w) + new[end:]
    return new, [(c, w) for (c, _, _), w in swaps.values()]


def declared(quoted, clue, evidence):
    """(the clue with the one misprint the model's own evidence names mended, [(clue word, quote word)])
    for a printedClue that corrected nothing ('OCR misread: five (V) for few' beside the clue as shown):
    the model said which clue word it read as which, so both words may be real words and short (the
    plain rule needs six letters and a non-word). Needs one quote word absent from the clue, exactly one
    unquoted clue word within three edits of it, once in the clue, and both words in the evidence."""
    said_ev = {w.casefold() for w in WORD.findall(evidence)}
    toks = [(m.group(), m.start(), m.end()) for m in WORD.finditer(clue)]
    have = {t[0].casefold() for t in toks}
    said = {w.casefold() for q in quoted for w in WORD.findall(q)}
    swaps = {}
    for q in quoted:
        for w in WORD.findall(q):
            if w.casefold() in have or len(w) < 3 or not w.isalpha() or w.casefold() not in said_ev:
                continue
            near = [t for t in toks if t[0].isalpha() and t[0].casefold() not in said
                    and t[0].casefold() in said_ev
                    and definitions._lev(w.casefold(), t[0].casefold()) <= DECLARED_EDITS]
            if len(near) == 1 and sum(t[0] == near[0][0] for t in toks) == 1:
                swaps[near[0][1]] = (near[0], w)
    if not swaps or len({v[1].casefold() for v in swaps.values()}) != len(swaps):
        return None, []
    new = clue
    for start, ((c, _, end), w) in sorted(swaps.items(), reverse=True):
        new = new[:start] + (w[0].upper() + w[1:] if c[0].isupper() else w) + new[end:]
    return new, [(c, w) for (c, _, _), w in swaps.values()]


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
    new, pairs = repaired(quotes(a), shown)
    why = "; ".join(EVIDENCE.format(c=c, q=q) for c, q in pairs)
    if not new and pc:
        new, pairs = declared(quotes(a), shown, pc[1])
        why = pc[1] if len(pc[1]) >= 25 else "; ".join(EVIDENCE.format(c=c, q=q) for c, q in pairs)
    if not new:
        return None
    if V.clue_row_problems(shown, new, why) or V.ocr_misread_edits(shown, new) > V.OCR_MISREAD_EDITS:
        return None
    return [new, why]
