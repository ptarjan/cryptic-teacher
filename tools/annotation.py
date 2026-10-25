"""An annotation's two groups, read the same way by every tool.

`explanation` is the prose the last hint rung prints (walkthrough, surface,
definitionFit); `assembly` rebuilds the answer for a machine to check (pieces,
anagrams, reversals). tools/data/puzzle.schema.json says what each key means.
"""
import functools
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


_NOT_AZ = re.compile(r"[^A-Z]")


@functools.lru_cache(maxsize=1 << 16)   # spaced() asks it of every character of every answer
def _letters_of_str(s):
    return _NOT_AZ.sub("", unicodedata.normalize("NFD", s).upper())


def _letters(s):
    """A-Z letters, accents folded (É is E), as validate_annotations.letters."""
    return _letters_of_str(str(s or ""))


_ATOMS = frozenset((str, int, float, bool, type(None)))


def _clone(x):
    """copy.deepcopy for the JSON a puzzle file holds: dicts, lists and scalars."""
    # Leaves are passed over without a call: a tree is mostly strings and numbers.
    t = type(x)
    if t is dict:
        return {k: v if type(v) in _ATOMS else _clone(v) for k, v in x.items()}
    if t is list:
        return [v if type(v) in _ATOMS else _clone(v) for v in x]
    if isinstance(x, dict):
        return {k: _clone(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_clone(v) for v in x]
    if x is None or isinstance(x, (str, int, float, bool)):
        return x
    import copy
    return copy.deepcopy(x)


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


# ---------- the fields a stored wordplay tree implies ----------
# The tree is tools/wordplay.py's; view() turns it back into the fields the
# app and the checks read today (type, answer, indicators with `for`,
# linkWords, blocks, assembly), so nothing downstream has to change.

# Stored op -> the clue type it names ($defs/clueType).
OP_TYPE = {"charade": "charade", "anagram": "anagram", "reversal": "reversal",
           "container": "container", "deletion": "deletion", "hidden": "hidden_word",
           "homophone": "homophone", "spoonerism": "spoonerism",
           "substitution": "substitution", "cycling": "cycling", "move": "move",
           "cryptic": "cryptic_definition", "rebus": "rebus",
           "composite": "composite_anagram", "reverse": "reverse_clue",
           "palindrome": "palindrome", "repeat": "charade", "first": "letter_selection",
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


def _light_marks(light):
    """{letters before it: mark text} for one leg of a linked answer: its
    printed enumeration where that adds up to the leg, else none. Its
    separators are no help: a lead's are cut from the whole group's
    enumeration, and a "See 18" leg's are strays (cryptic-21913 24D LONG,
    (4), has one after LO)."""
    sol = str(light.get("solution") or "")
    got = _enum_marks((light.get("clue") or {}).get("enumeration"))
    return got[0] if got and got[1] == len(sol) else {}


def _lights(entry, puzzle=None):
    """The lights a (possibly linked) answer runs through, in order."""
    group = entry.get("group")
    if not group or (len(group) == 1 and group[0] == entry_id(entry)):
        return [entry]  # unlinked: no index of the puzzle's entries to build
    by_id = {entry_id(e): e for e in (puzzle or {}).get("entries") or []}
    by_id[entry_id(entry)] = entry
    return [by_id[eid] for eid in entry.get("group") or [entry_id(entry)]]


def group_marks(lights):
    """{letters before it: mark text} over a linked answer's joined letters
    from its lead's printed enumeration (DANCE TO THE MUSIC OF TIME
    (5,2,3,5,2,4) on a 15-letter light), or None when that enumeration does
    not add up to the whole answer (Private Eye prints each leg's own
    length: (4) on WORK of WORK OF ART). A light may end mid-word: ROOK +
    SPAWN is ROOKS PAWN (5,4), and FIREWATER (9) spans two lights. A group
    stored in another order than the answer reads (cryptic-21673's
    INTEREST + VESTED under (6,8)) is a data fault no spacing mends."""
    sols = [str(lt.get("solution") or "") for lt in lights]
    got = _enum_marks((lights[0].get("clue") or {}).get("enumeration"))
    return got[0] if got and got[1] == sum(map(len, sols)) else None


def display_answer(entry, puzzle=None):
    """The answer spaced and hyphenated as the enumeration divides it. A
    linked answer joins its group's lights in order, spaced by group_marks
    where the lead's enumeration speaks for the whole; otherwise each light
    is spaced by its own enumeration (or separators), and a word break falls
    between lights."""
    lights = _lights(entry, puzzle)
    if len(lights) == 1:
        marks = {}
        for s in (entry.get("clue") or {}).get("separators") or []:
            marks[s["at"]] = marks.get(s["at"], "") + MARK_TEXT.get(s["mark"], " ")
        sol = str(entry.get("solution") or "")
        return "".join(ch + marks.get(k, "") for k, ch in enumerate(sol, 1)).strip(" -")
    marks = group_marks(lights)
    if marks is not None:
        whole = "".join(str(lt.get("solution") or "") for lt in lights)
        return "".join(ch + marks.get(k, "") for k, ch in enumerate(whole, 1)).strip(" -")
    out = []
    for n, light in enumerate(lights):
        marks, sol = _light_marks(light), str(light.get("solution") or "")
        out += [ch + marks.get(k, "") for k, ch in enumerate(sol, 1)]
        if n < len(lights) - 1 and not marks.get(len(sol)):
            out.append(" ")
    return re.sub(r" {2,}", " ", "".join(out)).strip(" -")


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
# fact the enumeration can't give, kept as `spelling`.
# Mephisto prints "(10, two words)" where Chambers has two words (filed as
# 6,4 with separators) and a bare count for one word or a hyphenated one:
# USED-UP (6), LOG-HOUSE (8), L-PLATES (7); hyphens in 2 of 15,459.
LETTER_COUNT_ONLY = {"azed", "listener", "mephisto"}


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
    out = []

    def go(n, parent):  # a list, not a generator: nested yields cost per level
        for p in n.get("parts") or ():
            go(p, n)
        out.append((n, parent))
    go(node, parent)
    return out


def _types(tree):
    """Every op's clue type, in the order applied."""
    import wordplay
    out = []
    for node, parent in _walk(tree):
        op = node.get("op")
        # An anagram's fodder is one heap of letters, not a charade, unless
        # the join has an indicator of its own (its `for` names the charade).
        # Its pieces are the anagram's own parts now; this reads the charades
        # filed under one before that (the wordplay.anagramCharade allowance).
        if not op or (op == "charade" and parent and parent.get("op") == "anagram"
                      and not node.get("indicators")):
            continue
        # Nor is a join of one lettered part and notes riding along (blocks
        # that give nothing): everyman-3002 12A, R AND Y named by
        # "outskirts of Rugby", filed its "characters" as such a block and is
        # one letter selection.
        if op == "charade" and not node.get("indicators") and len(wordplay.lettered(_parts(node))) < 2:
            continue
        if OP_TYPE[op] not in out:
            out.append(OP_TYPE[op])
    # A wordplay that is one leaf (a single block) is a charade of one part.
    return out or (["charade"] if tree.get("op") in (None, "charade") else [])


def _block(**kw):
    return {k: kw[k] for k in BLOCK_KEYS if kw.get(k) not in (None, "")}


# ---------- abbreviation glosses: derived from the table, never stored ----------
# A leaf whose clue words -> letters pair is in tools/build_abbreviations.table()
# (the dictionary-backed table the site's glossary prints) needs no note: view()
# shows ABBREVIATION_GLOSS. A stored note that says only that is derivable, so
# the validator refuses it and from_model drops it (restates_abbreviation).
ABBREVIATION_GLOSS = "{gives} is a standard abbreviation for {words}"
_ABBR_PAIRS = None
#: The (clue word, letters) pairs is_abbreviation() looked up, while a caller
#: records them (a set): tools/page_cache.py re-checks a stored page's against
#: abbreviation_pairs() instead of keying every page on the table's lexicons.
ABBR_ASKED = None


def _abbr_key(s):
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def abbreviation_pairs():
    """{(clue word as capitals, letters)}: every sense the table holds."""
    global _ABBR_PAIRS
    if _ABBR_PAIRS is None:
        import build_abbreviations
        _ABBR_PAIRS = frozenset((_abbr_key(w), k) for k, ws in build_abbreviations.table().items()
                                for w in ws)
    return _ABBR_PAIRS


def is_abbreviation(leaf):
    """Whether a leaf's words give its letters by a sense the table holds."""
    if not isinstance(leaf, dict) or "op" in leaf or not leaf.get("words") or not leaf.get("gives"):
        return False
    pair = (_abbr_key(leaf["words"]), leaf["gives"])
    if ABBR_ASKED is not None:
        ABBR_ASKED.add(pair)
    return pair in abbreviation_pairs()


def abbreviation_gloss(leaf):
    """The note view() shows on a leaf the table explains, or None. A clue's
    capitalised first word reads in lower case ("With" -> with)."""
    if not is_abbreviation(leaf):
        return None
    words = leaf["words"]
    if leaf.get("at") == 0 and words[:1].isupper() and words[1:2].islower():
        words = words[0].lower() + words[1:]
    return ABBREVIATION_GLOSS.format(gives=leaf["gives"], words=words)


# Qualifiers that add nothing to "an abbreviation": the table already is the
# dictionary's record. A domain ("the cricket abbreviation", "as on taps", "the
# Roman numeral") is information the table does not hold, and stays.
_BARE_ADJ = (r"(?:standard|usual|common|commonest|recorded|conventional|familiar|accepted|"
             r"recogni[sz]ed|regular|established|normal|ordinary|everyday|customary|"
             r"well-known|frequent|simple|basic|dictionary|crossword|common crossword|"
             r"standard crossword|usual crossword)\s+")
_ABBR_WORD = r"(?:abbreviation|abbrev\.?|short form|shortening)"
_ART = r"(?:(?:the|a|an)\s+)?"
_RESTATE = (
    # [G is] [the] [standard] abbreviation [for|of [the] W]
    rf"(?:{{G}}\s+(?:is|=)\s+)?{_ART}(?:{_BARE_ADJ})?{_ABBR_WORD}(?:\s+(?:for|of)\s+{_ART}{{W}})?",
    # G abbreviates W, G is short for W, G stands for W, G = W, G for W
    rf"{{G}}\s+(?:abbreviates|is\s+short\s+for|stands\s+for|=|for|is\s+an?\s+abbreviation\s+of)\s+{_ART}{{W}}",
    # short for W, abbreviates W, stands for W
    rf"(?:short\s+for|abbreviates|stands\s+for)\s+{_ART}{{W}}",
    # W is abbreviated [to|as] G, W = G
    rf"{_ART}{{W}}\s+(?:is\s+)?(?:abbreviated|shortened)(?:\s+(?:to|as)\s+{{G}})?",
    rf"{_ART}{{W}}\s*(?:=|->|→)\s*{{G}}",
    rf"{{G}}\s*(?:->|→)\s*{_ART}{{W}}",
)


def _restate_re(gives, words):
    g = r"\W?".join(re.escape(c) for c in gives) + r"\.?"
    w = re.escape(words.strip())
    return re.compile(r"(?i)^(?:" + "|".join(
        p.replace("{G}", f"[\"'‘“]?{g}[\"'’”]?").replace("{W}", f"[\"'‘“]?{w}[\"'’”]?")
        for p in _RESTATE) + r")$")


_RESTATE_CACHE = {}


def restates_abbreviation(leaf):
    """Whether a leaf's stored note says nothing but that its letters are an
    abbreviation of its words, a pair the table holds ("W is the standard
    abbreviation for with", "standard abbreviation"). Such a note is
    derivable: view() shows abbreviation_gloss() instead. A note that adds
    anything (a domain, a source, a second step) is not."""
    note = leaf.get("note") if isinstance(leaf, dict) else None
    if not note or not is_abbreviation(leaf):
        return False
    key = (leaf["gives"], leaf["words"])
    if key not in _RESTATE_CACHE:
        _RESTATE_CACHE[key] = _restate_re(*key)
    text = re.sub(r"\s+", " ", note).strip().rstrip(".!;:").strip()
    return bool(_RESTATE_CACHE[key].match(text))


def strip_abbreviation_notes(tree):
    """Drop every restates_abbreviation note from a wordplay tree, in place.
    Returns how many were dropped."""
    n, stack = 0, [tree] if isinstance(tree, dict) else []
    while stack:
        node = stack.pop()
        if restates_abbreviation(node):
            del node["note"]
            n += 1
        stack += [p for p in node.get("parts") or [] if isinstance(p, dict)]
    return n


# ---------- selection and hidden-word block notes: derived from the op, never stored ----------
# A block that keeps some letters of its words has said why by its op, and the
# tree check has already proved the letters: the model need not write "first
# letter of X". The words are the block's clueFragment, so the note names none.
# A leaf's own note, when it has one, wins.
SELECT_NOTE = {"first": "first {letter}", "last": "last {letter}",
               "middle": "middle {letter}", "outer": "outer {letter} (first and last of each word)",
               "alternate": "alternate {letter}", "regular": "{letter} at regular intervals"}
HIDDEN_NOTE = "hidden inside these words"


def select_note(op, n, gives):
    """The note a one-leaf letter selection gets: what it keeps, from its op."""
    letter = "letter" if len(letters_only(gives)) == 1 else "letters"
    if op == "nth":
        return f"letter number {n} of each word" if isinstance(n, int) else f"the nth {letter} of each word"
    text = SELECT_NOTE.get(op)
    return text.format(letter=letter) if text else None


def article_gloss(leaf):
    """The note for the indefinite article "a" / "an" giving A, or None."""
    if "op" not in leaf and letters_only(leaf.get("words")).lower() in ("a", "an") \
            and leaf.get("gives") == "A" and not leaf.get("unchecked"):
        return "the indefinite article, A"
    return None


def letters_only(s):
    return re.sub(r"[^A-Za-z]", "", s or "")


def _blocks(node, got):
    """The app's blocks: one per run of clue words (or supplied letters), in
    tree order, `gives` the letters before any op joins them to others; a
    selection or homophone of one leaf is one block with `select` or
    `soundsLike`."""
    import wordplay
    op = node.get("op")
    if op is None:
        # An unchecked leaf keeps the select or soundsLike it was filed with.
        # An unchecked leaf without gives gives no letters (wordplay.match).
        gives = None if node.get("unchecked") and "gives" not in node else wordplay.leaf_letters(node)
        # A leaf the abbreviation table explains stores no note; its gloss is derived.
        return [_block(clueFragment=node.get("words"), gives=gives,
                       select=node.get("select"), soundsLike=node.get("soundsLike"),
                       note=node.get("note") or abbreviation_gloss(node) or article_gloss(node))]
    parts = _parts(node)
    if node.get("unchecked"):
        # An unchecked step taken as filed shows its parts' blocks as they were.
        return [b for p in parts for b in _blocks(p, got)]
    if op == "cryptic":
        return [_block(clueFragment=p.get("words"), note=p.get("note")) for p in parts]
    if op == "rebus":
        # The picture and how it reads; its letters are the whole answer, so none.
        return [_block(clueFragment=parts[0].get("words"),
                       note="; ".join(x for x in (node.get("reading"), parts[0].get("note")) if x))]
    if op == "reverse":
        # The clue words that read as wordplay. The pieces of the answer they
        # would build (`reading`) are the walkthrough's to say, not a block's.
        return [_block(clueFragment=parts[0].get("words"), note=parts[0].get("note"))]
    one = len(parts) == 1 and "op" not in parts[0] and "words" in parts[0]
    if OP_TYPE[op] == "letter_selection" and one:
        b = _blocks(parts[0], got)[0]
        gives = got.get(id(node)) or min(wordplay.values(node), key=lambda v: (len(v), v), default=None)
        return [_block(**{**b, "gives": gives, "select": node["n"] if op == "nth" else op,
                          "note": b.get("note") or select_note(op, node.get("n"), gives)})]
    if OP_TYPE[op] == "letter_selection" and len(parts) > 1 \
            and all("op" not in p and "words" in p for p in parts):
        # one selection over a list: a block per leaf, each with its own pick
        import itertools
        want = got.get(id(node))
        per = [sorted(wordplay.values({**node, "parts": [p]}), key=lambda v: (len(v), v)) for p in parts]
        picks = next((c for c in itertools.product(*per) if "".join(c) == want), None) \
            or tuple(v[0] if v else None for v in per)
        out = []
        for p, pick in zip(parts, picks):
            b = _blocks(p, got)[0]
            out.append(_block(**{**b, "gives": pick, "select": node["n"] if op == "nth" else op,
                                 "note": b.get("note") or select_note(op, node.get("n"), pick)}))
        return out
    if op == "hidden" and one:
        b = _blocks(parts[0], got)[0]
        return [_block(**{**b, "gives": got.get(id(node)) or wordplay.leaf_letters(parts[0]),
                          "note": b.get("note") or HIDDEN_NOTE})]
    if op == "homophone" and one:
        b = _blocks(parts[0], got)[0]
        return [_block(**{**b, "gives": node["spelt"], "soundsLike": b.get("gives")})]
    if op in ("deletion", "substitution", "move"):
        # Letters an indicator names have no clue words and are no block.
        parts = [parts[0]] + [p for p in parts[1:] if "op" in p or "words" in p]
    return [b for p in parts for b in _blocks(p, got)]


def repeat_copy_letters(tree):
    """The letters of the second copy every `repeat` step in `tree` writes out.
    The view shows a repeat's one copy as its blocks (the app says "twice" in
    the indicator), so the blocks fall one copy short of the answer by design:
    PAWPAW's blocks give PA + W. This is the missing copy, for a check that adds
    the blocks' letters up to the answer."""
    import wordplay
    out = ""
    for n, _ in _walk(tree or {}):
        if n.get("op") == "repeat" and not n.get("unchecked"):
            try:
                out += "".join(_letters(b.get("gives")) for p in _parts(n) for b in _blocks(p, {}))
            except wordplay.WordplayError:
                pass
    return out


def _cut(pieces, at):
    """`pieces` split at letter offset `at`, a piece cut in two if need be."""
    before, after, seen = [], [], 0
    for p in pieces:
        if seen + len(p) <= at:
            before.append(p)
        elif seen >= at:
            after.append(p)
        else:
            before.append(p[:at - seen])
            after.append(p[at - seen:])
        seen += len(p)
    return before, after


def _pieces(node, got):
    """The answer in the chunks the tree builds, in answer order."""
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


def _fodder_pieces(node):
    """An anagram's fodder pieces: its parts, or the parts of the one charade
    filed under it before an anagram could hold several (validate_annotations
    allows those only up to a puzzle's wordplay.anagramCharade allowance)."""
    parts = _parts(node)
    child = parts[0] if len(parts) == 1 else None
    if child is not None and child.get("op") == "charade" and not child.get("unchecked"):
        return _parts(child)
    return parts


def _fodder_letters(node, got):
    """The fodder's letters in stored order, or None when a piece's are unknown."""
    parts = _parts(node)
    if len(parts) == 1:
        return got.get(id(parts[0]))
    if not parts or not all(id(p) in got for p in parts):
        return None
    return "".join(got[id(p)] for p in parts)


def _fodder(node, got):
    """An anagram's fodder letters as the clue prints them. Its fodder is one
    heap, so its pieces may be filed in any order; the letters are read off
    them in clue order, so the app deals the same tiles and the fodder it
    shows reads like the clue. A piece with no clue words (supplied letters)
    keeps the tree order."""
    whole = _fodder_letters(node, got)
    if whole is None:
        return "".join(sorted(got[id(node)]))
    parts = _fodder_pieces(node)
    if len(parts) < 2 or not all(id(p) in got for p in parts):
        return whole
    ats = [_first_at(p) for p in parts]
    if None in ats:
        return whole
    return "".join(got[id(p)] for _, p in sorted(zip(ats, parts), key=lambda it: it[0]))


#: The letters a setter's slip may cost an anagram, extra and missing together
#: (validate_annotations.SETTER_ERROR_LETTERS reads this).
SLIP_LETTERS = 2


def _slip_size(fodder, gives):
    from collections import Counter
    a, b = Counter(_letters(fodder)), Counter(_letters(gives))
    return sum(((a - b) + (b - a)).values())


def _assembly(tree, got):
    if tree.get("op") in ("cryptic", "rebus", "reverse"):
        return {}
    out = {}
    pieces = [p for p in _pieces(tree, got) if p]
    if len(pieces) > 1:
        out["pieces"] = pieces
    # An unchecked anagram (a setter's slip, or a step taken as filed)
    # is listed too when its fodder's letters are known and are a slip's
    # reach from what it gives, so the ring deals them and
    # validate_annotations holds a slip to tools/data/setter_error.json.
    # Further out it is a structure the tree does not hold (cryptic-22514
    # 13A: a linked answer's 17 letters of fodder filed against one light's
    # SLEEPING), and listing it would misstate it.
    anas = [{"fodder": _fodder(n, got) or "".join(sorted(got[id(n)])), "gives": got[id(n)]}
            for n, _ in _walk(tree) if n.get("op") == "anagram" and id(n) in got
            and (not n.get("unchecked") or (len(_parts(n)) == 1 and id(_parts(n)[0]) in got
                                            and _slip_size(got[id(_parts(n)[0])], got[id(n)]) <= SLIP_LETTERS))]
    revs = [{"from": got[id(_parts(n)[0])], "to": got[id(n)]}
            for n, _ in _walk(tree) if n.get("op") == "reversal" and id(_parts(n)[0]) in got
            and not n.get("unchecked")
            # A reversal of a named stretch (wordplay._span_flips) is no whole-word
            # reversal: the list says from -> to read backwards, so it is left out.
            and _letters(got[id(_parts(n)[0])])[::-1] == _letters(got[id(n)])]
    if anas:
        out["anagrams"] = anas
    if revs:
        out["reversals"] = revs
    return out


def link_words(clue, spans):
    """The clue's runs of words no (at, text) span covers, punctuation trimmed."""
    # The uncovered gaps between the spans' merged intervals.
    n, out, pos = len(clue), [], 0
    for at, end in sorted((at, min(n, at + len(text))) for at, text in spans if 0 <= at < n and text):
        if at > pos:
            run = clue[pos:at].strip(LINK_STRIP)
            if run:
                out.append(run)
        pos = max(pos, end)
    if pos < n:
        run = clue[pos:].strip(LINK_STRIP)
        if run:
            out.append(run)
    return out


def definition_indicator_type(ann):
    """What an indicator on a definition signals: a second meaning when the
    clue has two definitions or more, else the whole clue read as one (&lit).
    These steer how the definitions read, not the letters, so they hang on a
    definition rather than on a wordplay op."""
    return "double_definition" if len(ann.get("definitions") or []) > 1 else "and_lit"


def view(ann, entry, puzzle=None):
    """A stored annotation (definitions, wordplay tree, explanation, ...)
    with the fields it implies, in the shape the app and the checks read: type,
    answer, indicators with `for`, linkWords, blocks and assembly. Two
    definitions make a double definition, with or without wordplay beside
    them. Raises wordplay.WordplayError when the tree does not give the
    answer, or names words the clue does not have."""

    import wordplay
    clue = ((entry or {}).get("clue") or {}).get("text") or ""
    defs = ann.get("definitions") or []
    tree = _clone(ann.get("wordplay"))
    # The setter's enumeration spaces the answer, whatever a spelling says.
    answer = spaced(ann.get("spelling") or display_answer(entry, puzzle), entry, puzzle)
    got, types = {}, (["double_definition"] if len(defs) > 1 else [])
    def_spans = [(d["at"], d["at"] + len(d["text"])) for d in defs if "at" in d]
    def_inds = [_clone(i) for d in defs for i in d.get("indicators") or []]
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
        # `meaning` is shown as the definition's block note.
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
    out["blocks"] = name_repeated_pieces(out["blocks"])
    out["blocks"] = unname_derived_block_text(out["blocks"], tree, answer)
    name_clue_words_in_indicator_notes(out)
    if tree and (asm := _assembly(tree, got)):
        out["assembly"] = asm
    if tree:
        # The located tree itself: the walkthrough rung steps through it (app.js wordplaySteps).
        out["wordplay"] = tree
    for key in ("explanation", "features", "hiddenLetter"):
        if key in ann:
            out[key] = ann[key]
    return out


def name_repeated_pieces(blocks):
    """A bare piece with no note whose letters an earlier block already gave
    is that block's letters used again (ins(del([new]N, ...), N): the N taken
    out goes back in). It is shown against the clue words that gave them the
    first time, which the first check's 'a block with no clueFragment' would
    otherwise refuse and send the run to write them out. A piece that has a
    note of its own (a theme's letters, a connective) is left as filed."""
    out, seen = [], {}
    for b in blocks:
        b = dict(b)
        key = _letters(b.get("gives"))
        if (not str(b.get("clueFragment") or "").strip() and key and not b.get("note")
                and not b.get("select") and not b.get("soundsLike") and key in seen):
            b["clueFragment"] = seen[key]
            b["note"] = f"{b['gives']} again: the letters {seen[key]!r} gave, used a second time"
        elif str(b.get("clueFragment") or "").strip() and key and key not in seen:
            seen[key] = b["clueFragment"]
        out.append(b)
    return out


#: The wording of an abbreviation gloss that cannot name an answer: none of its
#: fixed words ("standard", "abbreviation") is in it.
ABBREVIATION_GLOSS_PLAIN = "{gives} stands for {words}"


def unname_derived_block_text(blocks, tree, answer):
    """Blocks whose DERIVED abbreviation gloss names the answer, with the gloss
    reworded: text the run never wrote, so the first check's 'block note names
    the answer' would send it to rewrite something it cannot see. "ST is a
    standard abbreviation for street" on a clue whose answer is STANDARD (or
    ABBREVIATION) becomes "ST stands for street" (annotate audit 10-24/25: 3 of
    9 refusals that survived the note mend). A note the run wrote is left to
    the check."""
    if not tree or not answer:
        return blocks
    from find_answer_leaks import says
    glosses = {}
    for node, _ in _walk(tree):
        if "op" not in node and not node.get("note") and (g := abbreviation_gloss(node)):
            glosses[g] = ABBREVIATION_GLOSS_PLAIN.format(
                gives=node["gives"], words=g.split(" abbreviation for ", 1)[1])
    out = []
    for b in blocks:
        note = b.get("note")
        if note in glosses and says(note, answer) and not says(glosses[note], answer):
            b = {**b, "note": glosses[note]}
        out.append(b)
    return out


def name_clue_words_in_indicator_notes(v):
    """An indicator note may point at a block's clue words but never its
    letters (the indicators rung comes first): "the other letters go around
    the H" becomes "... around the “hospital”". Each capitalised word of a note
    that spells a block's letters is swapped, in the view, for the clue words
    that block parses, so the first check's 'gives away the letters' does not
    send the run back to reword it. Letters of the answer have no block to
    point at and are left for the check to name."""
    import validate_annotations as V
    for ind in v.get("indicators") or []:
        note = ind.get("note")
        if not note:
            continue
        for w in dict.fromkeys(V.letters_given_in(note, v)):
            frag = next((b["clueFragment"] for b in v.get("blocks") or []
                         if _letters(b.get("gives")).upper() == w and b.get("clueFragment")), None)
            if frag:
                note = re.sub(rf"\b{w}\b", lambda m: f"“{frag}”", note)
        ind["note"] = note


def view_puzzle(puzzle, problems=None):
    """The puzzle as every reader takes it: `series` and `name` derived,
    `prize`/`title`/`label` folded into the name, and each annotation
    replaced by view(). An annotation whose tree does not give its answer is
    left out, and (where, message) appended to `problems` when given. A view
    comes back as it is (it has `series`, which a file never stores), so
    view_puzzle(view_puzzle(p)) is view_puzzle(p)."""
    import puzzle_schema
    import series
    import wordplay
    if "series" in puzzle:
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
        if k in puzzle_schema.NAME_KEYS:
            continue
        out[k] = v
        if k == "number":
            out["series"] = series.parse_id(puzzle["id"])[0]
            out["name"] = series.display_name(puzzle)
    entries = []
    for i, e in enumerate(puzzle.get("entries") or []):
        x = dict(holder(e, f"$.entries[{i}].annotation"))
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
# from_model() turns it into the stored annotation, checking the letters.

# Keys the model shape passes through as they are (the stored annotation's own).
MODEL_PASS = ("definedByPreamble", "andLit", "explanation", "features", "hiddenLetter", "alteration")
MODEL_KEYS = ("def", "wp", "notes", "answer") + MODEL_PASS
# Keys a model-shape clue may not carry: view() derives them from `wp`.
DERIVED_KEYS = ("type", "blocks", "definitions", "indicators", "linkWords", "assembly")


def is_model(ann):
    """Whether `ann` is in the model's shape, not a stored annotation: it has
    `def` or `wp` (which a stored one never has), or has neither a stored
    tree nor any derived key. A model clue with a stray derived key stays
    the model's, so from_model names it."""
    if not isinstance(ann, dict):
        return False
    if "def" in ann or "wp" in ann:
        return True
    return (not any(k in ann for k in DERIVED_KEYS + ("wordplay",))
            and any(k in ann for k in ("definedByPreamble", "notes")))


def from_model(m, entry, puzzle=None):
    """The stored annotation for one clue in the model's shape, its
    wordplay evaluated against the answer (the entry's `alteration.from`
    where the preamble alters it). Raises wordplay.WordplayError, worded for
    the run to act on: a word not in the clue, a note naming no span, an
    unknown key, a parse whose letters are not the answer (naming the node)."""
    import definitions as D
    import wordplay
    unknown = sorted(set(m) - set(MODEL_KEYS))
    if unknown:
        hint = ""
        if set(unknown) & set(DERIVED_KEYS):
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
    if isinstance(wp, str) and "+" in wp:
        try:
            wordplay.parse(wp)
        except wordplay.WordplayError:
            # a charade's order word written as `+ +<after>` or a prefix `+<after>(a, b)`:
            # said the way the parser takes it, when that parses (translate still checks it)
            mended = wordplay.mend_charade_indicator(wp)
            if mended:
                try:
                    wordplay.parse(mended)
                    wp = mended
                except wordplay.WordplayError:
                    pass
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
        if display is None or said.casefold() != spaced(display, entry, puzzle).casefold():
            out["spelling"] = said
    if wp:
        alt = entry.get("alteration")
        want = (alt["from"] if isinstance(alt, dict) and alt.get("from")
                else out.get("spelling") or display)
        taken = [(d["at"], d["at"] + len(d["text"])) for d in defs]
        out["wordplay"] = wordplay.translate({"wp": wp, "notes": notes}, clue, want, taken, D.respell)
        # A note that only says the table's abbreviation is derivable: dropped,
        # not refused, since view() shows the same gloss from the table.
        strip_abbreviation_notes(out["wordplay"])
        fill_palindrome_fodder(out["wordplay"], defs, want)
        drop_vacuous_sound(out["wordplay"])
        merge_sounded_charade(out["wordplay"], clue)
    elif notes:
        raise wordplay.WordplayError(f"notes {sorted(notes)} name no definition, and there is no `wp`")
    elif len(defs) < 2 and not m.get("definedByPreamble"):
        raise wordplay.WordplayError("no `wp`: only a double definition (two `def`s) has no wordplay")
    for k in ("explanation", "features", "hiddenLetter", "alteration"):
        if k in m:
            out[k] = m[k]
    return out


def fill_palindrome_fodder(tree, defs, want):
    """pal<ind>() over a clue with one definition: the definition's own words are the
    palindrome ("Bread, either way" NAAN; the clue's two halves are the same words), the
    one shape validate_annotations.in_definition allows a leaf to share. The empty pal()
    gives no block, so the check called the clue missing its blocks (16 of the 66
    'missing annotation field' refusals in the annotate audit 10-24/25). Its one part
    becomes that leaf, in place; the answer was already proved a palindrome."""
    if (isinstance(tree, dict) and tree.get("op") == "palindrome" and not tree.get("parts")
            and len(defs) == 1 and "at" in defs[0] and want):
        import wordplay
        leaf = {"words": defs[0]["text"], "at": defs[0]["at"], "gives": wordplay.letters(want)}
        if defs[0].get("note"):
            leaf["note"] = defs[0]["note"]
        tree["parts"] = [leaf]


def drop_vacuous_sound(tree):
    """spoon(sound([head]HAIR, HAIR), b) swaps onsets in written letters, so
    the sound() beside it hears nothing (HEARD equals SPELT): the run added it
    to satisfy the sound check, which then failed it as 'nothing was heard'.
    Replaced by its leaf, in place, when the spoon names no SPELT of its own.
    The taught forms are spoon(a, b) and spoon(a, b, SPELT), neither with a
    sound() round a leaf; a spoon that names its SPELT keeps its sound()."""
    if not isinstance(tree, dict):
        return
    parts = tree.get("parts") or []
    for i, p in enumerate(parts):
        if (tree.get("op") == "spoonerism" and "spelt" not in tree
                and isinstance(p, dict) and p.get("op") == "homophone"
                and len(p.get("parts") or []) == 1 and not p.get("indicators")):
            leaf = p["parts"][0]
            import wordplay
            if "op" not in leaf and _letters(wordplay.leaf_letters(leaf)) == _letters(p.get("spelt")):
                parts[i] = leaf
                continue
        drop_vacuous_sound(p)


def merge_sounded_charade(tree, clue):
    """sound(A + B, SPELT) over leaves that sit side by side in the clue is
    one sound of the joined words: the single leaf [A B]ABGIVES the sound
    rung wants (soundsLike is a block field, and a charade has no one block to
    carry it). Merged in place, with a note joining the leaves' notes, so the
    run is not sent back to write what it already wrote. A charade with an
    indicator, a non-leaf part or words apart in the clue is left alone."""
    import wordplay
    if not isinstance(tree, dict):
        return
    parts = tree.get("parts") or []
    if tree.get("op") == "homophone" and len(parts) == 1 and parts[0].get("op") == "charade":
        leaves = parts[0].get("parts") or []
        ok = (len(leaves) > 1 and not parts[0].get("indicators")
              and all(isinstance(x, dict) and "op" not in x and x.get("words") and "at" in x
                      and not x.get("unchecked") and not x.get("select") for x in leaves))
        if ok:
            ok = all(not clue[a["at"] + len(a["words"]):b["at"]].strip()
                     and b["at"] >= a["at"] + len(a["words"])
                     for a, b in zip(leaves, leaves[1:]))
        if ok:
            first, last = leaves[0], leaves[-1]
            words = clue[first["at"]:last["at"] + len(last["words"])]
            gives = "".join(wordplay.leaf_letters(x) for x in leaves)
            notes = [x.get("note") or abbreviation_gloss(x) or article_gloss(x)
                     or f"{x['words']} gives {wordplay.leaf_letters(x)}" for x in leaves]
            parts[0] = {"words": words, "at": first["at"], "gives": gives,
                        "note": "; ".join(n.rstrip(". ") for n in notes)}
        return
    for p in parts:
        merge_sounded_charade(p, clue)


def to_model(ann):
    """A stored annotation in the model's shape (the prompt's worked
    examples, a run's existingAnnotations). Indicators on a definition and a
    double definition's `note` beside its `meaning` have no model form and
    are left out; an unchecked step renders as `?op(...)=LETTERS`."""
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
            # A note that only restates the abbreviation table is not one to copy.
            if span.get("note") and not restates_abbreviation(span):
                notes[name if seen[name] == 1 else f"{name}#{seen[name]}"] = span["note"]
    if notes:
        out["notes"] = notes
    for k in ("explanation", "features", "hiddenLetter"):
        if k in ann:
            out[k] = ann[k]
    return out
