"""A paper's erratum is a fix to the puzzle, not a preamble.

The Guardian prints its corrections in the note above the clues, the same
field that carries a themed puzzle's special instructions, so a fetch reads
"Clue 5 down should read: ..." as if it were one. apply() reads each erratum
out of the preamble and acts on it:

- "N [across|down] should read <text> [(enumeration)]": that entry's clue
  becomes the text (and enumeration, through enumeration.split).
- "In N across, 'word' should be in italics": the clue gets that italic span.
- "the word X in 6d was changed to Y", "the spelling has been corrected to
  'Y'": the clue already reading Y confirms it; X still there is replaced.
- "the clue for N has been corrected" with no text: the page that carries the
  note carries the corrected clue, so the note is dropped.

What is left of the preamble is kept (a themed puzzle's instructions); none
left means no preamble. An erratum that cannot be acted on raises ValueError
naming it, and find() is the write gate's test that no stored preamble still
holds one (puzzle_integrity.check_puzzle).

A clue whose words the erratum changes (fetch_puzzle.clue_words) loses its
annotation: it explained the old words."""

import difflib
import re
import unicodedata

import enumeration
from groups import entry_id

DIRECTION = r"(?P<dir>acc?ross|down|ac|dn|a|d)\b"
NUMS = r"(?P<nums>\d+(?:\s*(?:,|&|\band\b|an')\s*\d+)*)"
REF = NUMS + r"\s*(?:" + DIRECTION + ")?"
QUOTE = {'"': '"', "'": "'", "“": "”", "‘": "’"}

SHOULD_READ = re.compile(
    r"(?:(?:The )?clue (?:for |to |at )?|In (?:clue )?)?" + REF
    + r"(?:\s*-\s*(?P<last>last word))?\s*(?:[-:,]\s*)?(?:clue\s*)?"
    r"should (?:read\s*[:;,]?|be\s*[:;])\s*", re.I)

ITALIC_WORD = r"(?:in italics|italicised|italicized)"
ITALIC = re.compile(r"[^.]*\b" + ITALIC_WORD + r"\b[^.]*(?:\.|$)", re.I)

# A dated note in front: "Note added 7 November 2018:", "15/9/2021", "April 20 2023".
DATE = (r"(?:\w+day )?(?:\d{1,2}\s*[A-Z][a-z]+(?: \d{4})?|[A-Z][a-z]+ \d{1,2}(?: \d{4})?"
        r"|\d{1,2}[./]\d{1,2}[./]\d{2,5}|[A-Z][a-z]+ \d{4})")
#: What a note's sentence split leaves behind: "Note added 16 August 2011."
#: or "7 August 2017: 15 down."
LEFTOVER = re.compile(r"(?:Note(?: added| posted)?[,:]?\s*)?(?:" + DATE + r")?\s*[:.,]?\s*(?:"
                      + REF + r")?\s*[:.,]?", re.I)

# A correction that names no new text. Each reads as the paper owning up to a
# change made on the page, never as an instruction for solving.
CORRECTED = re.compile(
    r"\b(?:has|have) been (?:corrected|amended|changed|edited|replaced|altered|"
    r"deleted|reinstated)\b"
    r"|\b(?:was|were) (?:corrected|amended|changed|edited|garbled|wrongly (?:numbered|listed)|"
    r"(?:originally |inadvertently |temporarily )?(?:left out|omitted|missing)|"
    r"(?:\w+ )?(?:published|uploaded|reprinted) in error)\b"
    r"|\bcorrected\b|\bnot originally (?:published|uploaded)\b|\bare now in the correct order\b"
    r"|\bchanged solution\b|\bwas missing\b|\bpublished in error\b|\bshould have been\b"
    r"|\bgave the number of letters\b|\bto correct an error\b|\boriginally failed\b"
    r"|\b(?:originally )?wrongly (?:listed|numbered)\b"
    r"|\bAs originally published, the clue\b",
    re.I)

# The paper saying its puzzle is wrong without printing a fix.
CONFESSED = re.compile(
    r"\bThere (?:was|is) an error in\b|\bis a misspelling\b|\bThere is a spelling mistake\b",
    re.I)

#: A target the note says the clue now reads: "changed to 'Drambuie'".
NOW_READS = re.compile(
    r"(?:reads|show) (?P<q2>[\"'‘“][^\"'’”]+[\"'’”]) rather than (?P<q3>[\"'‘“][^\"'’”]+[\"'’”])"
    r"|(?:corrected|changed|amended)(?: from (?P<q0>[\"'‘“][^\"'’”]+[\"'’”]))?"
    r" (?:to|reads) (?P<q1>[\"'‘“][^\"'’”]+[\"'’”]|\(?[\w-]+\)?(?=[.;]?$))"
    r"|(?:The word |the word )(?P<q4>[\"'‘“][^\"'’”]+[\"'’”]) [^.]*?(?:changed|corrected) to "
    r"(?P<q5>[\"'‘“][^\"'’”]+[\"'’”])",
    re.I)

#: An instruction the paper amended in place: "Five 5 solutions are not
#: further defined, not six as originally indicated" keeps all but the clause.
AMENDED = re.compile(r",?\s*not [\w ]+? as originally (?:indicated|stated|printed)", re.I)

#: "17 down should contain symbol for Pi and + but our tool cannot input these":
#: the clue spells out symbols the page could not print.
SHOULD_CONTAIN = re.compile(r"\b" + REF + r"\s*should contain (?:the )?symbols? for "
                            r"(?P<what>.+?)\s+but\b[^.]*(?:\.|$)", re.I)
SYMBOLS = {"pi": (r"(?i)(?<![a-z])pi(?![a-z])", "π"), "+": (r"(?i)\s*(?<![a-z])plus(?![a-z])\s*", " + ")}

ORDINAL = {"first": 1, "second": 2, "third": 3}


def fold(text):
    """Letters and digits only, accents folded, lower case."""
    text = unicodedata.normalize("NFKD", text or "")
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _direction(word):
    if not word:
        return None
    return "across" if word.lower().startswith("a") else "down"


def _numbers(text):
    return [int(n) for n in re.findall(r"\d+", text)]


def _unquote(text):
    text = text.strip()
    if text and text[0] in QUOTE and text.endswith(QUOTE[text[0]]):
        return text[1:-1].strip()
    return text


def _resolve(puzzle, nums, direction, new_text=None):
    """The entry an erratum names, or None when the reference is not unique."""
    entries = [e for e in puzzle.get("entries", []) if e.get("number") == nums[0]
               and (direction is None or e.get("direction") == direction)]
    if len(nums) > 1:
        # "1,3,16 across" names the group by its numbers; the direction
        # printed is the last light's, not necessarily the leader's.
        linked = [e for e in puzzle.get("entries", []) if e.get("number") == nums[0]
                  and [int(g.split("-")[0]) for g in e.get("group", [])] == nums]
        entries = linked or entries
    if len(entries) > 1:
        texted = [e for e in entries if e.get("clue", {}).get("text")
                  and not re.match(r"(?i)see\b", e["clue"]["text"])]
        entries = texted or entries
    if len(entries) > 1 and new_text:
        score = sorted(((difflib.SequenceMatcher(None, fold(e["clue"].get("text")),
                                                 fold(new_text)).ratio(), k)
                        for k, e in enumerate(entries)), reverse=True)
        if score[0][0] >= 0.6 and score[0][0] - score[1][0] >= 0.25:
            entries = [entries[score[0][1]]]
    return entries[0] if len(entries) == 1 else None


def _set_text(puzzle, entry, text, enum, reworded):
    """Give `entry` the clue text (and enumeration); note it in `reworded`
    when its words changed."""
    clue = entry["clue"]
    old = clue.get("text", "")
    if fold(old) != fold(text):
        reworded.add(entry_id(entry))
    if text != old:
        italics = []
        for r in clue.get("italics", []):
            span = old[r["at"]:r["at"] + r["length"]]
            at = text.find(span)
            if span and at >= 0:
                italics.append({"at": at, "length": len(span)})
        clue["text"] = text
        clue["italics"] = italics
        if not italics:
            del clue["italics"]
    if enum and enum != clue.get("enumeration"):
        clue["enumeration"] = enum
        if not entry.get("group") and entry.get("length"):
            import fetch_puzzle  # noqa: PLC0415 — it imports this module
            seps = fetch_puzzle.separators(enum, [entry["length"]])[0]
            if seps:
                clue["separators"] = seps
            else:
                clue.pop("separators", None)


def _adds(old, new):
    """Whether erratum text `new` says more than the stored `old`: other words,
    or a letter or symbol the page lost (an accent, "£", "°"). Text the same
    but for punctuation, a garbled character ("m¿ge") or an explanatory aside
    in brackets ("6 1/4% (six and a quarter per cent)") adds nothing."""
    if re.search(r"[¿\ufffd]", new) or fold(re.sub(r"\([^()]*\)", "", new)) == fold(old) != fold(new):
        return False
    if fold(old) != fold(new):
        return True
    return any(unicodedata.category(c)[0] in "LSN" and not c.isascii() or c in "£€°+=%&"
               for c in set(new) - set(old))


def _quoted_text(rest):
    """(text, consumed) for the clue text an erratum's "should read" starts:
    a quoted string with any enumeration printed after it, or the rest of the
    note up to the next erratum."""
    nxt = SHOULD_READ.search(rest)
    while nxt and nxt.start() and not re.search(r"[\s.\"'’”)]$", rest[:nxt.start()]):
        nxt = SHOULD_READ.search(rest, nxt.end())
    # The next erratum starts at its own number, so a clue ending in a quote
    # ("...(6,4)'17 across should read") is not read on into it.
    end = nxt.start() if nxt else len(rest)
    if nxt:
        head = re.search(r"(?:(?:The )?clue (?:for |to |at )?|In (?:clue )?)$", rest[:end], re.I)
        end = head.start() if head else end
    body = rest[:end]
    if body[:1] in QUOTE:
        # The closing quote is the first one the note goes on from: into an
        # enumeration, a new sentence, or nothing.
        closes = [k for k in range(1, len(body)) if body[k] in (QUOTE[body[0]], "’")
                  and re.match(r"\s*(?:\([^()]*\))?\s*[.;]?\s*(?:$|[A-Z0-9])", body[k + 1:])]
        close = closes[0] if closes else -1
        if close > 0:
            tail = re.match(r"\s*(\([^()]*\))?\s*[.;]?\s*", body[close + 1:])
            text = body[1:close].strip()
            if tail.group(1):
                text = f"{text} {tail.group(1)}"
            return text, close + 1 + tail.end()
        return body[1:].strip().rstrip("."), end
    text = body.strip()
    if text.endswith(".") and not text.endswith("..."):
        text = text[:-1]
    return text, end


def _should_read(puzzle, text, reworded, unresolved):
    """Apply every "should read" erratum; the preamble without them."""
    out, pos = [], 0
    while m := SHOULD_READ.search(text, pos):
        new, used = _quoted_text(text[m.end():])
        nums, direction = _numbers(m.group("nums")), _direction(m.group("dir"))
        # The group's numbers printed in front ("11 an'12,25: Kipling's ...")
        # are the label, not the clue.
        new = re.sub(r"^\d+(?:\s*(?:,|&|an'|and)\s*\d+)*\s*:\s*(?=\D)", "", new) if len(nums) > 1 else new
        body, enum = enumeration.split(new)
        if body and not enum and (tail := re.search(r"\s*\(\d[^()]*\)$", body)):
            body = body[:tail.start()]  # a count only a group's leader prints in words
        entry = _resolve(puzzle, nums, direction, body)
        if entry is None or not body:
            unresolved.append(text[m.start():m.end() + used].strip())
        elif m.group("last"):
            # "3 down - last word should read 'caf": the word as printed, cut short.
            words = entry["clue"].get("text", "").split()
            if not words or not fold(words[-1]).startswith(fold(body)):
                unresolved.append(text[m.start():m.end() + used].strip())
        elif _adds(entry["clue"].get("text", ""), body):
            _set_text(puzzle, entry, body, enum, reworded)
        out.append(text[pos:m.start()])
        pos = m.end() + used
    out.append(text[pos:])
    return " ".join(" ".join(out).split())


def _italic(puzzle, sentence, unresolved):
    """Apply an "in italics" erratum; False when the sentence is not one."""
    ref = re.search(r"(?:clue (?:for )?|In |at )?\b" + REF, sentence, re.I)
    if not ref:
        return False
    q = re.search(r"([\"'‘“])(.+?)([\"'’”])(?=\W|$)", sentence)
    word = q.group(2) if q else None
    if not word:
        m = (re.search(r"The words? (?P<q>.+?) in (?:clue )?\d", sentence, re.I)
             or re.search(r"In (?:clue )?" + REF + r",? (?:the words? )?(?P<q>.+?) "
                          r"(?:should|is|are|appears?)\b", sentence, re.I))
        word = m and m.group("q")
    nums, direction = _numbers(ref.group("nums")), _direction(ref.group("dir"))
    pattern = word and re.compile(r"(?<!\w)" + re.escape(word) + r"(?!\w)", re.I)
    entry = _resolve(puzzle, nums, direction)
    if word and not (entry and pattern.search(entry["clue"].get("text", ""))):
        # The note's direction is wrong or missing: the light of that number
        # whose clue holds the words.
        holding = [e for e in puzzle.get("entries", []) if e.get("number") == nums[0]
                   and pattern.search(e["clue"].get("text", ""))]
        entry = holding[0] if len(holding) == 1 else None
    text = entry and entry["clue"].get("text", "")
    nth = re.search(r"\b(first|second|third) use\b", sentence, re.I)
    found = [k.start() for k in pattern.finditer(text)] if word and text else []
    k = ORDINAL[nth.group(1).lower()] - 1 if nth else 0
    if not entry or len(found) <= k or (len(found) > 1 and not nth):
        unresolved.append(sentence)
        return True
    span = {"at": found[k], "length": len(word)}
    italics = entry["clue"].setdefault("italics", [])
    if not any(r["at"] <= span["at"] and span["at"] + span["length"] <= r["at"] + r["length"]
               for r in italics):
        italics.append(span)
        italics.sort(key=lambda r: r["at"])
    return True


def _confirmed(puzzle, sentence, unresolved):
    """A correction note naming its new text: the clue (or answer) reading it
    confirms the page holds the fix; the old text still there is replaced."""
    m = NOW_READS.search(sentence)
    if not m:
        return
    new = _unquote(m.group("q1") or m.group("q2") or m.group("q5") or "").strip("()")
    old = _unquote(m.group("q0") or m.group("q3") or m.group("q4") or "")
    new, old = new.rstrip(". "), old.rstrip(". ")
    texts = [(e, e["clue"].get("text", "")) for e in puzzle.get("entries", [])]
    ref = re.search(r"\b" + NUMS + r"\s*" + DIRECTION, sentence, re.I)
    if ref:
        entry = _resolve(puzzle, _numbers(ref.group("nums")), _direction(ref.group("dir")))
        texts = [(entry, entry["clue"].get("text", ""))] if entry else []
    seen = " ".join(f"{t} {e['clue'].get('enumeration', '')} {e.get('solution', '')}"
                    for e, t in texts)
    if fold(new) and fold(new) in fold(seen):
        return
    hit = [(e, t) for e, t in texts if old and old.rstrip(".").strip() in t]
    if len(hit) == 1:
        e, t = hit[0]
        e["clue"]["text"] = t.replace(old.rstrip(".").strip(), new, 1)
        return
    unresolved.append(sentence)


def _sentences(text):
    """The note cut into sentences, a bracketed "(Note ...)" aside whole."""
    out = []
    for k, chunk in enumerate(re.split(r"([\[(]\s*Note\b[^\])]*[\])])", text)):
        if k % 2:
            out.append(chunk[1:-1])
        else:
            out += re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\[(])", chunk)
    return [p.strip() for p in out if p and p.strip()]


def _symbols(puzzle, text, reworded, unresolved):
    """Apply every "should contain symbol for" erratum; the preamble without them."""
    def one(m):
        entry = _resolve(puzzle, _numbers(m.group("nums")), _direction(m.group("dir")))
        names = [w.strip().lower() for w in re.split(r",|\band\b", m.group("what")) if w.strip()]
        if entry is None or any(n not in SYMBOLS for n in names):
            unresolved.append(m.group(0))
            return ""
        new = entry["clue"].get("text", "")
        for n in names:
            new = re.sub(SYMBOLS[n][0], SYMBOLS[n][1], new)
        _set_text(puzzle, entry, " ".join(new.split()), None, reworded)
        return ""
    return SHOULD_CONTAIN.sub(one, text)


def find(preamble):
    """The errata a preamble still holds, as text; [] when it has none."""
    text = preamble or ""
    found = [m.group(0) for m in SHOULD_READ.finditer(text)]
    found += [m.group(0) for p in (SHOULD_CONTAIN, AMENDED) for m in p.finditer(text)]
    if CONFESSED.search(text):
        return found
    found += [s for s in _sentences(text) if ITALIC.search(s) or CORRECTED.search(s)]
    return found


def apply(puzzle):
    """Act on every erratum in `puzzle`'s preamble and take it out (in place);
    return the entry ids whose words changed, after clearing their annotation.
    Raises ValueError naming any erratum it cannot act on."""
    text = puzzle.get("preamble")
    if not text or not find(text):
        return set()
    reworded, unresolved = set(), []
    text = _should_read(puzzle, text, reworded, unresolved)
    text = AMENDED.sub("", _symbols(puzzle, text, reworded, unresolved))
    if CONFESSED.search(text):
        # The paper owning up to a flaw the grid keeps (an answer misspelt to
        # fit): no fix to apply, and the solver needs telling. Kept whole.
        if unresolved:
            raise ValueError(f"{puzzle.get('id')}: erratum not applied: " + " | ".join(unresolved))
        puzzle["preamble"] = text
        return reworded
    kept = []
    for sentence in _sentences(text):
        bare = sentence.strip()
        if ITALIC.search(bare) and _italic(puzzle, bare, unresolved):
            continue
        if CORRECTED.search(bare):
            before = {entry_id(e): e["clue"].get("text") for e in puzzle.get("entries", [])}
            _confirmed(puzzle, bare, unresolved)
            reworded |= {entry_id(e) for e in puzzle.get("entries", [])
                         if fold(e["clue"].get("text")) != fold(before[entry_id(e)])}
            continue
        if not LEFTOVER.fullmatch(bare):
            kept.append(bare)
    if unresolved:
        raise ValueError(f"{puzzle.get('id')}: erratum not applied: " + " | ".join(unresolved))
    import fetch_puzzle  # noqa: PLC0415 — it imports this module
    rest = fetch_puzzle.LINK_SENTENCE.sub("", " ".join(kept)).strip()
    rest = re.sub(r"^[\s\[\]().:;,-]+$", "", rest)
    if re.search(r"\w\w", rest):
        puzzle["preamble"] = rest
    else:
        puzzle.pop("preamble", None)
    for e in puzzle.get("entries", []):
        if entry_id(e) in reworded:
            e.pop("annotation", None)
    return reworded
