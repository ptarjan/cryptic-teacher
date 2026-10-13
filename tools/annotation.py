"""An annotation's two groups, read the same way by every tool.

`explanation` is the prose the last hint rung prints (walkthrough, surface,
definitionFit); `assembly` rebuilds the answer for a machine to check (pieces,
anagrams, reversals). tools/data/puzzle.schema.json says what each key means.
"""
import re
import unicodedata


def _parts(node):
    """An op's parts; a stored file has no empty list (see wordplay.parts_of)."""
    return node.get("parts") or []


def explanation(ann):
    """The annotation's prose: walkthrough, surface, definitionFit."""
    x = ann.get("explanation")
    return x if isinstance(x, dict) else {}


def assembly(ann):
    """The annotation's machine-checkable rebuild: pieces, anagrams, reversals."""
    x = ann.get("assembly")
    return x if isinstance(x, dict) else {}


def _letters(s):
    """A-Z letters, accents folded (É is E), as validate_annotations.letters."""
    return re.sub(r"[^A-Z]", "", unicodedata.normalize("NFD", str(s or "")).upper())


def wordplay_letters(ann, entry):
    """The letters the clue's wordplay builds: the entry's `alteration.from`
    where the preamble alters answers before entry, else the answer."""
    alt = (entry or {}).get("alteration")
    if isinstance(alt, dict) and alt.get("from"):
        return _letters(alt["from"])
    return _letters(ann.get("answer") or (entry or {}).get("solution"))


def whole_anagram(ann, entry=None):
    """The fodder of the anagram whose gives is the whole wordplay word
    (wordplay_letters), or None."""
    want = wordplay_letters(ann, entry)
    for a in assembly(ann).get("anagrams") or []:
        if want and isinstance(a, dict) and _letters(a.get("gives")) == want:
            return a.get("fodder")
    return None


# ---------- format v2: the fields a stored wordplay tree implies ----------
# The tree is tools/wordplay.py's; view() turns it back into the fields the
# app and the checks read today (type, answer, indicators with `for`,
# linkWords, blocks, assembly), so nothing downstream has to change.

# Stored op -> the clue type it names ($defs/clueType).
OP_TYPE = {"charade": "charade", "anagram": "anagram", "reversal": "reversal",
           "container": "container", "deletion": "deletion", "hidden": "hidden_word",
           "homophone": "homophone", "spoonerism": "spoonerism",
           "substitution": "substitution", "cycling": "cycling",
           "cryptic": "cryptic_definition", "palindrome": "palindrome", "first": "letter_selection",
           "last": "letter_selection", "middle": "letter_selection",
           "outer": "letter_selection", "alternate": "letter_selection",
           "regular": "letter_selection", "nth": "letter_selection"}
# A separator mark as the display answer writes it; any other mark is a space.
MARK_TEXT = {",": " ", "-": "-", "'": "'", "’": "'"}
# Edge characters that are punctuation round a link word, not part of it.
LINK_STRIP = " \t,;:.!?—–-…\"“”()[]"
BLOCK_KEYS = ("clueFragment", "gives", "select", "soundsLike", "note")


def entry_id(entry):
    return f"{entry['number']}-{entry['direction']}"


def display_answer(entry, puzzle=None):
    """The answer spaced and hyphenated as the enumeration divides it; a
    linked answer joins its group's lights in order, a mark at a light's
    length falling between it and the next."""
    by_id = {entry_id(e): e for e in (puzzle or {}).get("entries") or []}
    by_id[entry_id(entry)] = entry
    out = []
    for eid in entry.get("group") or [entry_id(entry)]:
        light = by_id[eid]
        marks = {}
        for s in (light.get("clue") or {}).get("separators") or []:
            marks[s["at"]] = marks.get(s["at"], "") + MARK_TEXT.get(s["mark"], " ")
        for k, ch in enumerate(str(light.get("solution") or ""), 1):
            out.append(ch + marks.get(k, ""))
    return "".join(out).strip(" -")


# An enumeration this code reads as word lengths and the marks between them:
# "8", "3,5", "2-3,4", "4'1". Worded ones ("two words") say nothing reliable.
ENUM_SHAPE = re.compile(r"\s*\d+(\s*[,.\-–'’\s]\s*\d+)*\s*")
ENUM_MARK = {"-": "-", "–": "-", "'": "'", "’": "'"}


def _enum_marks(enum):
    """{letters before it: mark text} for a printed enumeration, and its total;
    None when the enumeration is missing or not plain digits and marks."""
    enum = str(enum or "")
    if not ENUM_SHAPE.fullmatch(enum):
        return None
    marks, n = {}, 0
    for tok in re.findall(r"\d+|[^\d\s]|\s+", enum.strip()):
        if tok.isdigit():
            n += int(tok)
        elif n not in marks or ENUM_MARK.get(tok):
            marks[n] = ENUM_MARK.get(tok.strip(), " ")
    return marks, n


# Series whose printed enumerations count letters only (Azed marks a word
# break in 23 of 19,690, the Listener in none): their answers' spacing is a
# fact the enumeration can't give, kept as `spelling` (tools/convert_v2.py).
LETTER_COUNT_ONLY = {"azed", "listener"}


def answer_marks(entry, puzzle=None):
    """Where the setter breaks the answer: {letters before it: " ", "-" or "'"}
    and the answer's letter count, read from the light's separators where it
    has them, else from its printed enumeration (whose word lengths must add
    up to the answer). None when nothing printed says, so the stored spacing
    stands (a Listener's bare clue), and for a linked answer: its first leg
    prints the whole group's enumeration, so no one light's marks place the
    group's breaks (validate_annotations skips it for the same reason)."""
    if len(entry.get("group") or []) > 1:
        return None
    clue = entry.get("clue") or {}
    if not clue.get("separators") and str((puzzle or {}).get("id", "")).rsplit("-", 1)[0] in LETTER_COUNT_ONLY:
        # Its enumeration counts letters, not words: (8) says nothing about
        # LOVE-FEAT's hyphen (azed-1907), so the stored spelling stands.
        return None
    if clue.get("separators"):
        if not entry.get("solution"):
            return None
        marks = {}
        for s in clue["separators"]:
            marks[s["at"]] = marks.get(s["at"], "") + MARK_TEXT.get(s["mark"], " ")
        return marks, len(_letters(entry["solution"]))
    return _enum_marks(clue.get("enumeration"))


def spaced(text, entry, puzzle=None):
    """`text` (an answer) with its word breaks and hyphens taken from the
    setter's enumeration, never from whoever spelled it: (8) makes WAR PAINT
    WARPAINT, (3,5) makes WARPAINT WAR PAINT, (3-5) WAR-PAINT. The text's own
    letters, accents and apostrophes stay. Unchanged when no enumeration
    speaks or its lengths do not add up to the text's letters."""
    got = answer_marks(entry, puzzle)
    if not text or got is None:
        return text
    marks, total = got
    if len(_letters(text)) != total:
        return text
    out, n = [], 0
    for ch in str(text):
        if ch in " -–—":
            continue
        if _letters(ch):
            if n in marks and n:
                mark = marks[n]
                out.append(mark if not (mark == "'" and out and out[-1] in "'’") else "")
            n += 1
        out.append(ch)
    return "".join(out).strip(" -")


def _walk(node, parent=None):
    """(node, parent) for every node, its parts before the op joining them."""
    for p in node.get("parts") or []:
        yield from _walk(p, node)
    yield node, parent


def _types(tree):
    """Every op's clue type, in the order applied."""
    import wordplay
    out = []
    for node, parent in _walk(tree):
        op = node.get("op")
        # An anagram's fodder is one heap of letters, not a charade, unless
        # the join has an indicator of its own (its `for` names the charade).
        if not op or (op == "charade" and parent and parent.get("op") == "anagram"
                      and not node.get("indicators")):
            continue
        # Nor is a join of one lettered part and notes riding along (legacy
        # blocks that give nothing): everyman-3002 12A, R AND Y named by
        # "outskirts of Rugby", filed its "characters" as such a block and is
        # one letter selection, as its legacy type said.
        if op == "charade" and not node.get("indicators") and len(wordplay.lettered(_parts(node))) < 2:
            continue
        if OP_TYPE[op] not in out:
            out.append(OP_TYPE[op])
    # A wordplay that is one leaf (a single block, as legacy filed it) is a
    # charade of one part.
    return out or (["charade"] if tree.get("op") in (None, "charade") else [])


def _block(**kw):
    return {k: kw[k] for k in BLOCK_KEYS if kw.get(k) not in (None, "")}


def _blocks(node, got):
    """The app's blocks: one per run of clue words (or supplied letters), in
    tree order, `gives` the letters before any op joins them to others; a
    selection or homophone of one leaf is one block with `select` or
    `soundsLike`."""
    import wordplay
    op = node.get("op")
    if op is None:
        # An unchecked legacy leaf keeps the select or soundsLike it was filed with.
        # An unchecked leaf without gives gives no letters (wordplay.match).
        gives = None if node.get("unchecked") and "gives" not in node else wordplay.leaf_letters(node)
        return [_block(clueFragment=node.get("words"), gives=gives,
                       select=node.get("select"), soundsLike=node.get("soundsLike"),
                       note=node.get("note"))]
    parts = _parts(node)
    if node.get("unchecked"):
        # A legacy step taken as filed shows its parts' blocks as they were.
        return [b for p in parts for b in _blocks(p, got)]
    if op == "cryptic":
        return [_block(clueFragment=p.get("words"), note=p.get("note")) for p in parts]
    one = len(parts) == 1 and "op" not in parts[0] and "words" in parts[0]
    if OP_TYPE[op] == "letter_selection" and one:
        b = _blocks(parts[0], got)[0]
        return [_block(**{**b, "gives": got.get(id(node)) or min(wordplay.values(node), default=None),
                          "select": node["n"] if op == "nth" else op})]
    if op == "hidden" and one:
        b = _blocks(parts[0], got)[0]
        return [_block(**{**b, "gives": got.get(id(node)) or wordplay.leaf_letters(parts[0])})]
    if op == "homophone" and one:
        b = _blocks(parts[0], got)[0]
        return [_block(**{**b, "gives": node["spelt"], "soundsLike": b.get("gives")})]
    if op in ("deletion", "substitution"):
        # Letters an indicator names have no clue words and are no block.
        parts = [parts[0]] + [p for p in parts[1:] if "op" in p or "words" in p]
    return [b for p in parts for b in _blocks(p, got)]


def _pieces(node, got):
    """The answer in the chunks the tree builds, in answer order."""
    from derive_assembly import _cut

    import wordplay
    op = node.get("op")
    if node.get("unchecked"):
        return [got[id(node)]]
    if op == "charade" or (op == "palindrome" and wordplay.lettered(_parts(node))):
        return [x for p in _parts(node) for x in _pieces(p, got) if x]
    if op == "reversal":
        return [p[::-1] for p in reversed(_pieces(_parts(node)[0], got))]
    if op == "container":
        outer, inner = _parts(node)
        o, i, r = got[id(outer)], got[id(inner)], got[id(node)]
        k = next(k for k in range(1, len(o)) if o[:k] + i + o[k:] == r)
        head, tail = _cut(_pieces(outer, got), k)
        return head + _pieces(inner, got) + tail
    return [got[id(node)]]


def _first_at(node):
    """Where the node's first clue word starts, or None when it has none."""
    ats = [n["at"] for n, _ in _walk(node) if "at" in n]
    return min(ats) if ats else None


def _fodder(node, got):
    """An anagram's fodder letters as the clue prints them. Its fodder is one
    heap, so a charade under it may be filed in any order; the letters are
    read off its parts in clue order (as legacy files kept them), so the app
    deals the same tiles and the fodder it shows reads like the clue. A part
    with no clue words (supplied letters) keeps the tree order."""
    child = _parts(node)[0]
    if id(child) not in got:
        return "".join(sorted(got[id(node)]))
    parts = child.get("parts") or []
    if (child.get("op") != "charade" or child.get("unchecked")
            or not all(id(p) in got for p in parts)):
        return got[id(child)]
    ats = [_first_at(p) for p in parts]
    if None in ats:
        return got[id(child)]
    return "".join(got[id(p)] for _, p in sorted(zip(ats, parts), key=lambda it: it[0]))


def _assembly(tree, got):
    if tree.get("op") == "cryptic":
        return {}
    out = {}
    pieces = [p for p in _pieces(tree, got) if p]
    if len(pieces) > 1:
        out["pieces"] = pieces
    # An unchecked anagram (a setter's slip, or a legacy step taken as filed)
    # is listed too when its fodder's letters are known, so the ring deals
    # them and validate_annotations holds a slip to tools/data/setter_error.json.
    anas = [{"fodder": _fodder(n, got) or "".join(sorted(got[id(n)])), "gives": got[id(n)]}
            for n, _ in _walk(tree) if n.get("op") == "anagram" and id(n) in got
            and (not n.get("unchecked") or (len(_parts(n)) == 1 and id(_parts(n)[0]) in got))]
    revs = [{"from": got[id(_parts(n)[0])], "to": got[id(n)]}
            for n, _ in _walk(tree) if n.get("op") == "reversal" and id(_parts(n)[0]) in got
            and not n.get("unchecked")]
    if anas:
        out["anagrams"] = anas
    if revs:
        out["reversals"] = revs
    return out


def link_words(clue, spans):
    """The clue's runs of words no (at, text) span covers, punctuation trimmed."""
    covered = [False] * len(clue)
    for at, text in spans:
        for k in range(at, min(len(clue), at + len(text))):
            covered[k] = True
    out, run = [], ""
    for ch, c in zip(clue + "\0", covered + [True]):
        if not c:
            run += ch
            continue
        if run.strip(LINK_STRIP):
            out.append(run.strip(LINK_STRIP))
        run = ""
    return out


def definition_indicator_type(ann):
    """What an indicator on a definition signals: a second meaning when the
    clue has two definitions or more, else the whole clue read as one (&lit).
    These steer how the definitions read, not the letters, so they hang on a
    definition rather than on a wordplay op."""
    return "double_definition" if len(ann.get("definitions") or []) > 1 else "and_lit"


def view(ann, entry, puzzle=None):
    """A format v2 annotation (definitions, wordplay tree, explanation, ...)
    with the fields it implies, in the shape the app reads today: type,
    answer, indicators with `for`, linkWords, blocks and assembly. Two
    definitions make a double definition, with or without wordplay beside
    them. Raises wordplay.WordplayError when the tree does not give the
    answer, or names words the clue does not have."""
    import copy

    import wordplay
    clue = ((entry or {}).get("clue") or {}).get("text") or ""
    defs = ann.get("definitions") or []
    tree = copy.deepcopy(ann.get("wordplay"))
    # The setter's enumeration spaces the answer, whatever a spelling says.
    answer = spaced(ann.get("spelling") or display_answer(entry, puzzle), entry, puzzle)
    got, types = {}, (["double_definition"] if len(defs) > 1 else [])
    def_spans = [(d["at"], d["at"] + len(d["text"])) for d in defs if "at" in d]
    def_inds = [copy.deepcopy(i) for d in defs for i in d.get("indicators") or []]
    if def_inds:
        wordplay.locate({"indicators": def_inds}, clue, def_spans)
    if tree:
        wordplay.locate(tree, clue, def_spans + [(i["at"], i["at"] + len(i["text"])) for i in def_inds])
        alt = entry.get("alteration")
        got = wordplay.evaluate(tree, alt["from"] if isinstance(alt, dict) and alt.get("from") else answer)
        types += [t for t in _types(tree) if t not in types]
    if ann.get("andLit"):
        types.append("and_lit")
    out = {"type": types, "answer": answer}
    if "definitions" in ann:
        # `meaning` is shown as the definition's block note, as legacy kept it.
        out["definitions"] = [{k: v for k, v in d.items() if k not in ("indicators", "meaning")}
                              for d in ann["definitions"]]
    if "definedByPreamble" in ann:
        out["definedByPreamble"] = ann["definedByPreamble"]
    nodes = [n for n, _ in _walk(tree)] if tree else []
    dtype = definition_indicator_type(ann)
    inds = sorted([(i, OP_TYPE[n["op"]]) for n in nodes for i in n.get("indicators") or []] +
                  [(i, dtype) for i in def_inds], key=lambda it: it[0]["at"])
    if inds:
        out["indicators"] = [{"text": i["text"], "for": t, **({"note": i["note"]} if "note" in i else {})}
                             for i, t in inds]
    spans = [(d["at"], d["text"]) for d in defs if "at" in d]
    spans += [(i["at"], i["text"]) for i, _ in inds] + [(n["at"], n["words"]) for n in nodes if "words" in n]
    links = link_words(clue, spans)
    if links:
        out["linkWords"] = links
    # A double definition's blocks say what each definition means: `meaning`.
    # A definition's `note` is the definitions rung's, never a block's: that
    # rung comes later, so a note may say what a block may not (times-29410
    # 26A named FLY BY NIGHT in one).
    dd_blocks = [_block(clueFragment=d["text"], note=d.get("meaning")) for d in defs]
    # A tree that gives no block (a palindrome of the whole answer) leaves a
    # double definition its definitions' blocks.
    out["blocks"] = (_blocks(tree, got) or (dd_blocks if len(defs) > 1 else [])) if tree else dd_blocks
    if tree and (asm := _assembly(tree, got)):
        out["assembly"] = asm
    for key in ("explanation", "features", "hiddenLetter"):
        if key in ann:
            out[key] = ann[key]
    return out


# Puzzle-level keys a format v2 file stores only for display_name().
V2_NAME_KEYS = ("prize", "title", "label")


def view_puzzle(puzzle, problems=None):
    """A format v2 puzzle in the legacy shape every reader takes today:
    `series` and `name` derived, `prize`/`title`/`label` folded into the name,
    and each annotation replaced by view(). A legacy puzzle comes back as it
    is. An annotation whose tree does not give its answer is left out, and
    (where, message) appended to `problems` when given."""
    import puzzle_schema
    import series
    import wordplay
    if not puzzle_schema.is_v2(puzzle):
        return puzzle

    def viewed(where, held, ann):
        try:
            return view(ann, held, puzzle)
        except (wordplay.WordplayError, KeyError, TypeError, ValueError, StopIteration) as e:
            if problems is not None:
                problems.append((where, f"{type(e).__name__}: {e}" if not isinstance(
                    e, wordplay.WordplayError) else str(e)))
            return None
    seen = {where: viewed(where, held, ann) for where, held, ann in puzzle_schema.annotations(puzzle)}

    def holder(h, where):
        if "annotation" not in h:
            return h
        out = {k: v for k, v in h.items() if k != "annotation"}
        if seen.get(where) is not None:
            out["annotation"] = seen[where]
        return out
    out = {}
    for k, v in puzzle.items():
        if k in V2_NAME_KEYS:
            continue
        out[k] = v
        if k == "number":
            out["series"] = series.parse_id(puzzle["id"])[0]
            out["name"] = series.display_name(puzzle)
    entries = []
    for i, e in enumerate(puzzle.get("entries") or []):
        x = holder(e, f"$.entries[{i}].annotation")
        if e.get("alsoLeads"):
            x["alsoLeads"] = [holder(h, f"$.entries[{i}].alsoLeads[{k}].annotation")
                              for k, h in enumerate(e["alsoLeads"])]
        entries.append(x)
    out["entries"] = entries
    if puzzle.get("offGrid"):
        out["offGrid"] = [holder(h, f"$.offGrid[{k}].annotation") for k, h in enumerate(puzzle["offGrid"])]
    return out


# ---------- the model's shape: what an annotate run writes ----------
# A run writes one line of wordplay per clue, not the stored tree: `def` (the
# definition's clue words, or a list of two for a double definition), `wp`
# (tools/wordplay.py's expression; left out for a double definition) and
# `notes` keyed by the words of any span: a definition, an indicator, a leaf
# (`#2` for a repeat, a bare piece's letters for a piece with no words).
# from_model() turns it into the stored v2 annotation, checking the letters;
# view() turns that into the legacy shape where a file is still legacy.

# Keys the model shape passes through as they are (the v2 annotation's own).
MODEL_PASS = ("definedByPreamble", "andLit", "explanation", "features", "hiddenLetter", "alteration")
MODEL_KEYS = ("def", "wp", "notes", "answer") + MODEL_PASS
# Legacy keys a model-shape clue may not carry: derived from `wp`.
LEGACY_KEYS = ("type", "blocks", "definitions", "indicators", "linkWords", "assembly")


def is_model(ann):
    """Whether `ann` is in the model's shape: it has `def` or `wp` (which no
    other shape has), or has neither the legacy keys nor a stored tree. An
    old-prompt run's output (type, blocks, ...) goes the old way; a model
    clue with a stray legacy key stays the model's, so from_model names it."""
    if not isinstance(ann, dict):
        return False
    if "def" in ann or "wp" in ann:
        return True
    return (not any(k in ann for k in LEGACY_KEYS + ("wordplay",))
            and any(k in ann for k in ("definedByPreamble", "notes")))


def from_model(m, entry, puzzle=None):
    """The stored v2 annotation for one clue in the model's shape, its
    wordplay evaluated against the answer (the entry's `alteration.from`
    where the preamble alters it). Raises wordplay.WordplayError, worded for
    the run to act on: a word not in the clue, a note naming no span, an
    unknown key, a parse whose letters are not the answer (naming the node)."""
    import definitions as D
    import wordplay
    unknown = sorted(set(m) - set(MODEL_KEYS))
    if unknown:
        hint = ""
        if set(unknown) & set(LEGACY_KEYS):
            hint = (": write `def`, `wp` and `notes` (annotate_prompt.md's Schema); the clue "
                    "type, link words, indicators' `for`, blocks and assembly are worked out from `wp`")
        raise wordplay.WordplayError(f"unknown key{'s' if len(unknown) > 1 else ''} "
                                     f"{', '.join(unknown)}{hint}")
    clue = ((entry or {}).get("clue") or {}).get("text") or ""
    entry = dict(entry or {})
    if isinstance(m.get("alteration"), dict):
        entry["alteration"] = m["alteration"]
    raw_defs = m.get("def")
    raw_defs = [] if raw_defs is None else raw_defs if isinstance(raw_defs, list) else [raw_defs]
    defs = [dict(d) if isinstance(d, dict) else {"text": d} for d in raw_defs]
    if any(not isinstance(d.get("text"), str) or not d["text"] for d in defs):
        raise wordplay.WordplayError("`def` is the definition's clue words, a string (or a list "
                                     "of two for a double definition)")
    if defs:
        try:
            defs = D.place(defs, clue)
        except ValueError as e:
            raise wordplay.WordplayError(f"{e}; write that def as {{\"text\": ..., \"at\": <offset>}}") from None
    if not isinstance(m.get("notes", {}), dict):
        raise wordplay.WordplayError("`notes` is an object keyed by span words")
    notes = dict(m.get("notes") or {})
    wp = m.get("wp")
    names = set()
    if wp:
        names = {re.sub(r"#\d+$", "", s[k]) for s, k in wordplay._spans(wordplay.parse(wp), True)}
    for d in defs:
        if d["text"] in notes and d["text"] not in names:
            d["meaning" if len(defs) > 1 else "note"] = notes.pop(d["text"])
    out = {}
    if defs:
        out["definitions"] = defs
    for k in ("definedByPreamble", "andLit"):
        if k in m:
            out[k] = m[k]
    display = display_answer(entry, puzzle) if entry.get("solution") else None
    if m.get("answer"):
        if display is not None and _letters(m["answer"]) != _letters(display):
            raise wordplay.WordplayError(f"answer {m['answer']!r} is not the grid's {display!r}; "
                                         f"leave `answer` out unless it corrects a (MODEL) answer "
                                         f"or spells one with an apostrophe or accent")
        # Word breaks and hyphens are the enumeration's, never the model's: a
        # model's WAR PAINT against a printed (8) is WARPAINT, and is no spelling.
        said = spaced(m["answer"], entry, puzzle)
        if display is None or said != spaced(display, entry, puzzle):
            out["spelling"] = said
    if wp:
        alt = entry.get("alteration")
        want = (alt["from"] if isinstance(alt, dict) and alt.get("from")
                else out.get("spelling") or display)
        taken = [(d["at"], d["at"] + len(d["text"])) for d in defs]
        out["wordplay"] = wordplay.translate({"wp": wp, "notes": notes}, clue, want, taken, D.respell)
    elif notes:
        raise wordplay.WordplayError(f"notes {sorted(notes)} name no definition, and there is no `wp`")
    elif len(defs) < 2 and not m.get("definedByPreamble"):
        raise wordplay.WordplayError("no `wp`: only a double definition (two `def`s) has no wordplay")
    for k in ("explanation", "features", "hiddenLetter", "alteration"):
        if k in m:
            out[k] = m[k]
    return out


def to_model(ann):
    """A stored v2 annotation in the model's shape (the prompt's worked
    examples, a run's existingAnnotations). Indicators on a definition and a
    double definition's `note` beside its `meaning` have no model form and
    are left out; an unchecked legacy step renders as `?op(...)=LETTERS`."""
    import wordplay
    defs = ann.get("definitions") or []
    out = {}
    if defs:
        out["def"] = defs[0]["text"] if len(defs) == 1 else [d["text"] for d in defs]
    tree = ann.get("wordplay")
    if tree:
        out["wp"] = wordplay.render(tree)
    if ann.get("spelling"):
        out["answer"] = ann["spelling"]
    for k in ("definedByPreamble", "andLit"):
        if k in ann:
            out[k] = ann[k]
    notes = {}
    for d in defs:
        n = d.get("meaning", d.get("note")) if len(defs) > 1 else d.get("note")
        if n:
            notes[d["text"]] = n
    if tree:
        seen = {}
        for span, key in wordplay._spans(tree, True):
            name = span[key]
            seen[name] = seen.get(name, 0) + 1
            if span.get("note"):
                notes[name if seen[name] == 1 else f"{name}#{seen[name]}"] = span["note"]
    if notes:
        out["notes"] = notes
    for k in ("explanation", "features", "hiddenLetter"):
        if k in ann:
            out[k] = ann[k]
    return out
