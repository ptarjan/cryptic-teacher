"""An annotation's two groups, read the same way by every tool.

`explanation` is the prose the last hint rung prints (walkthrough, surface,
definitionFit); `assembly` rebuilds the answer for a machine to check (pieces,
anagrams, reversals). tools/data/puzzle.schema.json says what each key means.
"""
import re
import unicodedata


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


def _walk(node, parent=None):
    """(node, parent) for every node, its parts before the op joining them."""
    for p in node.get("parts") or []:
        yield from _walk(p, node)
    yield node, parent


def _types(tree):
    """Every op's clue type, in the order applied."""
    out = []
    for node, parent in _walk(tree):
        op = node.get("op")
        # An anagram's fodder is one heap of letters, not a charade.
        if not op or (op == "charade" and parent and parent.get("op") == "anagram"):
            continue
        if OP_TYPE[op] not in out:
            out.append(OP_TYPE[op])
    return out


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
        return [_block(clueFragment=node.get("words"), gives=wordplay.leaf_letters(node),
                       select=node.get("select"), soundsLike=node.get("soundsLike"),
                       note=node.get("note"))]
    parts = node["parts"]
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
    if op == "charade" or (op == "palindrome" and wordplay.lettered(node["parts"])):
        return [x for p in node["parts"] for x in _pieces(p, got) if x]
    if op == "reversal":
        return [p[::-1] for p in reversed(_pieces(node["parts"][0], got))]
    if op == "container":
        outer, inner = node["parts"]
        o, i, r = got[id(outer)], got[id(inner)], got[id(node)]
        k = next(k for k in range(1, len(o)) if o[:k] + i + o[k:] == r)
        head, tail = _cut(_pieces(outer, got), k)
        return head + _pieces(inner, got) + tail
    return [got[id(node)]]


def _assembly(tree, got):
    if tree.get("op") == "cryptic":
        return {}
    out = {}
    pieces = [p for p in _pieces(tree, got) if p]
    if len(pieces) > 1:
        out["pieces"] = pieces
    anas = [{"fodder": got.get(id(n["parts"][0])) or "".join(sorted(got[id(n)])), "gives": got[id(n)]}
            for n, _ in _walk(tree) if n.get("op") == "anagram" and id(n) in got and not n.get("unchecked")]
    revs = [{"from": got[id(n["parts"][0])], "to": got[id(n)]}
            for n, _ in _walk(tree) if n.get("op") == "reversal" and id(n["parts"][0]) in got
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
    answer = ann.get("spelling") or display_answer(entry, puzzle)
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
        out["definitions"] = [{k: v for k, v in d.items() if k != "indicators"} for d in ann["definitions"]]
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
    # A double definition's blocks say what each definition means (`meaning`,
    # or its `note` when it has no separate meaning).
    out["blocks"] = (_blocks(tree, got) if tree else
                     [_block(clueFragment=d["text"], note=d.get("meaning", d.get("note"))) for d in defs])
    if tree and (asm := _assembly(tree, got)):
        out["assembly"] = asm
    for key in ("explanation", "features", "hiddenLetter"):
        if key in ann:
            out[key] = ann[key]
    return out
