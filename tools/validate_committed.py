"""Checks of validate_annotations.py that read a clue or its text against what is committed: markup, groups, spelling, unchanged rows, abbreviation notes.

Moved out of validate_annotations.py unchanged; that module re-exports every name here.
"""

import difflib
import json
import re
import subprocess
import definitions
import enumeration
import groups
import provenance
from fetch_puzzle import clue_words, corrected_clue, has_words, leaders_named, source_clue, SOURCE_CLUE_WRONG
from groups import entry_id

from validate_base import ROOT

#: A tag, an entity, or a tag's remnant with its "<" lost to a reader that
#: began mid-tag: genius's article reader filed ` class="dcr-47amn7">` as
#: the preamble of 25 puzzles.
MARKUP_RE = re.compile(r"</?[a-zA-Z][^>]*>|&(?:[a-zA-Z]+|#\d+);"
                       r"|\b(?:class|style|id|href|src|data-[\w-]+)\s*=\s*[\"'][^\"']*[\"']"
                       r"|\bdcr-[a-z0-9]{4,}\b")
# Bytes 0x80-0x9F are punctuation in Windows-1252 and unprintable control
# codes in Unicode, so a source decoded as latin-1 turns every dash and curly
# quote into one of these and the browser draws a box. Some of them reached
# the site. Repairing them is a lookup, so the message carries it.
CP1252_C1 = {0x82: "\u201a", 0x83: "\u0192", 0x84: "\u201e", 0x85: "\u2026",
             0x86: "\u2020", 0x87: "\u2021", 0x88: "\u02c6", 0x89: "\u2030",
             0x8b: "\u2039", 0x91: "\u2018", 0x92: "\u2019", 0x93: "\u201c",
             0x94: "\u201d", 0x95: "\u2022", 0x96: "\u2013", 0x97: "\u2014",
             0x99: "\u2122", 0x9b: "\u203a"}
C1_RE = re.compile(r"[\x80-\x9f\ufffd]")


def verbatim_hint(fragment, clue):
    """What to say when a fragment is not verbatim in its clue: the clue's own
    spelling of it (definitions.respell), or the clue words its words skip."""
    spelt = definitions.respell(str(fragment), clue)
    if spelt != fragment:
        return (f" — the clue spells it {spelt!r}: copy it from the file rather "
                f"than retyping it")
    misread = respelt_words(str(fragment), clue)
    if misread:
        return (f" — the clue prints {' and '.join(f'{c!r} where this has {f!r}' for c, f in misread)}. "
                f"Quote the clue as it stands; if the page prints your word and the "
                f"clue is misread, give the entry `printedClue`: [\"<clue as printed, "
                f"no count>\", \"OCR misread: <what the wordplay needs>\"]")
    skipped = skipped_words(str(fragment), clue)
    if skipped:
        return (f" — its words are not consecutive in the clue, which prints "
                f"{' and '.join(map(repr, skipped))} between them. Quote one unbroken "
                f"run of clue words; the words between are their own block, "
                f"indicator or link word")
    return (" — copy it character for character from the clue, which is the "
            "only text it may be")


def respelt_words(fragment, clue):
    """[(clue word, fragment word)] where `fragment` is a run of clue words
    with one or two of them spelt a letter or two differently ("jumbled" for
    the clue's "iumbled"): a clue misread, or retyped. [] otherwise."""
    fold = lambda w: w.translate(definitions.LOOKALIKES).casefold()
    want = definitions.WORD.findall(fragment)
    words = definitions.WORD.findall(clue)
    for k in range(len(words) - len(want) + 1):
        pairs = [(c, f) for c, f in zip(words[k:k + len(want)], want) if fold(c) != fold(f)]
        if pairs and len(pairs) <= 2 and len(pairs) < len(want) + (len(want) == 1) and all(
                len(f) > 2 and difflib.SequenceMatcher(None, fold(c), fold(f)).ratio() >= 0.75
                for c, f in pairs):
            return pairs
    return []


def skipped_words(fragment, clue):
    """The clue words between `fragment`'s words, where its words are clue
    words in clue order with others between them: the fewest skipped of any
    such reading. [] when there is no such reading."""
    fold = lambda w: w.translate(definitions.LOOKALIKES).casefold()
    want = [fold(w) for w in definitions.WORD.findall(fragment)]
    words = list(definitions.WORD.finditer(clue))
    best = None
    for k in range(len(words)):
        at, gaps = k, []
        for j, w in enumerate(want):
            start = at
            while at < len(words) and fold(words[at].group()) != w:
                at += 1
            if at == len(words) or (j == 0 and at != k):
                break
            if at > start and j:
                gaps.append(clue[words[start].start():words[at - 1].end()])
            at += 1
        else:
            if want and gaps and (best is None or len(gaps) < len(best)):
                best = gaps
    return best or []


def is_pointer_text(e):
    """Is entry e's clue a bare pointer ("See 17", counted or not)?"""
    return groups.is_pointer(e["clue"].get("text", ""), counted=True)


def check_groups(puzzle, errors):
    """A linked answer is one answer over several lights. Its leader carries
    `group`, the answer's lights in word order, and the whole annotation;
    every other light carries neither a group nor an annotation. No group at
    all is the ordinary case: the entry is its own answer.

    The leader is the light that prints the clue, and it is first in its
    group unless the paper printed the clue on a later light of the answer:
    cryptic-21673 prints VESTED INTEREST's clue at 26-across, so 26-across
    holds ["25-across", "26-across"]. Each light before such a leader prints
    no clue of its own (blank, or a pointer), or is named in `selfClued`
    (cryptic-23821's 23-down RIGHT has its own clue and also starts 22-across's
    RIGHT AS RAIN).

    A light may continue more than one answer, and then it is in more than one
    group, but only when its own clue names more than one leader. Cryptic
    28,687's 1-down is CLUB, the second word of both GOLDFISH CLUB (8,4) at
    19-down and MONDAY CLUB (6,4) at 22-down, and reads "See 19, 22". A
    continuation naming one leader is in one group: Cyclops 683's 23-down reads
    "see 9ac.", so 11-across listing it too is an error. The count lives in
    fetch_puzzle.leaders_named, which prune_one_sided_members asks too, so the
    fetcher and this check exempt the same clues.
    """
    by_id = {entry_id(e): e for e in puzzle["entries"]}
    held_by = {}
    for e in puzzle["entries"]:
        also = e.get("alsoLeads") or []
        if also and not e.get("group"):
            errors.append(f"{entry_id(e)}: alsoLeads with no group. A light's first "
                          f"linked answer is its own clue and group; alsoLeads holds the rest")
        seen = [e.get("group")]
        for item in also:
            if item.get("group") in seen:
                errors.append(f"{entry_id(e)}: alsoLeads repeats the group {item.get('group')}. "
                              f"Each linked answer it starts is listed once")
            seen.append(item.get("group"))
    for e, holder in groups.linked(puzzle["entries"]):
        group = holder["group"]
        if len(set(group)) < 2:
            errors.append(f"{entry_id(e)}: group {group} must name two or more "
                          f"different lights. A clue that is its own answer "
                          f"carries no group at all.")
            continue
        if entry_id(e) not in group:
            errors.append(f"{entry_id(e)}: group {group} does not name this entry. "
                          f"Only the leader carries the group, and it is one of its lights")
            continue
        clued = groups.self_clued(holder)
        for gid in sorted(clued - set(group) | (clued & {entry_id(e)})):
            errors.append(f"{entry_id(e)}: selfClued names {gid}, which is not another "
                          f"light of its group {group}")
        if group[0] != entry_id(e):
            if is_pointer_text(e) or not has_words(e["clue"].get("text", "")):
                errors.append(f"{entry_id(e)}: group {group} starts on another light, "
                              f"but this entry prints no clue to lead it from. A group "
                              f"starts with its leader unless the paper printed the "
                              f"clue on a later light")
            for gid in group[:group.index(entry_id(e))]:
                other = by_id.get(gid)
                if other is None or gid in clued:
                    continue
                if has_words(other["clue"].get("text", "")) and not is_pointer_text(other):
                    errors.append(f"{entry_id(e)}: group {group} starts on {gid}, whose "
                                  f"clue is a clue of its own. A leader prints its clue "
                                  f"on a later light only when the answer's first light "
                                  f"prints none (blank, or \"See N\"), or names that "
                                  f"light in selfClued")
        for gid in dict.fromkeys(group):
            if gid == entry_id(e):
                continue                  # the leader, or an answer that repeats it
            other = by_id.get(gid)
            if other is None:
                errors.append(f"{entry_id(e)}: group names {gid}, which is not in this puzzle")
                continue
            if gid in clued:
                # An answer of its own that this one also runs through: it
                # keeps its own clue (cryptic-21893's THERE in BATTLE HYMN OF
                # THE REPUBLIC), or it continues another answer (cryptic-25126's
                # MINOR, "See 17", ends both MAJOR AND MINOR and ASIA MINOR).
                # A pointer continuing nothing else is a plain continuation.
                elsewhere = any(gid in h["group"] and gid != entry_id(lead)
                                and gid not in groups.self_clued(h)
                                for lead, h in groups.linked(puzzle["entries"]))
                if is_pointer_text(other) and not elsewhere:
                    errors.append(f"{gid}: in {entry_id(e)}'s selfClued, but its clue is a "
                                  f"pointer and it continues no other answer; a light whose "
                                  f"clue is \"See N\" is a plain continuation")
                continue
            held_by.setdefault(gid, []).append(entry_id(e))
            if other.get("annotation"):
                errors.append(f"{gid}: continues {entry_id(e)}'s linked answer, so it "
                              f"carries no annotation; the whole answer is "
                              f"annotated on {entry_id(e)}")
            if other.get("group"):
                errors.append(f"{gid}: continues {entry_id(e)}'s group {group} and "
                              f"leads its own {other['group']} — a light starts "
                              f"one answer at most, and only as its first light")
    for gid, leads in held_by.items():
        if len(leads) > 1 and leaders_named(by_id[gid]["clue"].get("text", "")) < 2:
            errors.append(f"{gid}: in the groups of {' and '.join(leads)}, but its "
                          f"clue names one leader. A light continues more than "
                          f"one answer only when its clue says so")


def check_no_markup(puzzle, errors):
    """No HTML anywhere in a puzzle file. Every string here is displayed
    escaped, so a tag reaches the solver as a tag: "<span>Film part of </span><i>
    Black Narcissus</i>?" would appear on the page verbatim. Both papers ship clues as
    HTML and tools/fetch_puzzle.plain_text flattens them on the way in; this
    is the guard that says so out loud if a third source, or a hand edit, ever
    puts one back.

    It also protects the hint highlighting, which locates its <mark> spans by
    character offset into the clue string: markup in the clue shifts every
    offset after it, so an annotation could no longer point at its own words.
    Walks the whole object rather than a list of fields, because the next
    field someone adds should not have to be remembered here.
    """
    for e in puzzle["entries"]:
        text = e["clue"].get("text", "")
        for r in e["clue"].get("italics") or []:
            at, length = r.get("at"), r.get("length")
            ok = (isinstance(at, int) and isinstance(length, int)
                  and at >= 0 and length > 0 and at + length <= len(text))
            if not ok:
                errors.append(f"{entry_id(e)}: clue.italics range {r!r} is not inside the "
                              f"{len(text)}-character clue text. The ranges index the clue "
                              f"text, so editing one without the other silently italicises "
                              f"the wrong words.")
        lost = [t for t in e["clue"].get("asPrinted") or () if t not in text.split()]
        if lost:
            errors.append(f"{entry_id(e)}: clue.asPrinted {lost!r} is no token of the clue text "
                          f"{text!r}: it keeps the print's own spelling of words in the text, so "
                          f"an edit to the text must carry it.")

    text_errors(puzzle, errors)


def text_errors(obj, errors):
    """check_no_markup's walk: every string in `obj`, a puzzle or a
    clues-only record, free of markup and of C1 control characters."""
    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, f"{path}.{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f"{path}[{i}]")
        elif isinstance(o, str):
            m = MARKUP_RE.search(o)
            if m:
                errors.append(f"{path.lstrip('.')}: HTML in text — {m.group(0)!r} in "
                              f"{o[:70]!r}. Puzzle text is displayed escaped; run it "
                              f"through fetch_puzzle.plain_text().")
            c1 = C1_RE.search(o)
            if c1:
                want = CP1252_C1.get(ord(c1.group()), "")
                errors.append(f"{path.lstrip('.')}: U+{ord(c1.group()):04X} is not text "
                              f"— it draws as a box"
                              + (f", and is Windows-1252's {want!r}: the source was "
                                 f"decoded as latin-1, decode it as cp1252"
                                 if want else ", so a byte was lost in decoding")
                              + f". In {o[:70]!r}.")
    walk(obj, "")


def committed_entries(path):
    """{entry id: entry} as HEAD has this puzzle, or None when it is not committed."""
    was = committed_top(path)
    return None if was is None else {entry_id(e): e for e in was.get("entries", [])}


def committed_top(path):
    """The puzzle as HEAD has it, or None when it is not committed."""
    try:
        rel = path.resolve().relative_to(ROOT)
    except ValueError:
        return None
    shown = subprocess.run(["git", "show", f"HEAD:{rel.as_posix()}"], cwd=ROOT,
                           capture_output=True, text=True, check=False)
    return None if shown.returncode else json.loads(shown.stdout)


def check_theme_clue_unchanged(puzzle, path, errors):
    """`themeClue` is filed at filing or review, never by an annotator: it is
    what lets a run's clue-word-less blocks stand, so a run that wrote it
    would be granting itself the exception. A file whose themeClue differs
    from HEAD's (added, changed or dropped) is refused."""
    was = committed_top(path)
    if was is None:
        return
    if was.get("themeClue") != puzzle.get("themeClue"):
        errors.append(
            f"themeClue changed from {was.get('themeClue')!r} to "
            f"{puzzle.get('themeClue')!r}. It names the clue that states the theme "
            f"and is filed by hand, not by the annotator: put it back. If a clue "
            f"states the theme and none is filed, withdraw and say which")


def check_spelling_kept(puzzle, path, errors):
    """A re-annotation may not drop the `spelling` HEAD's annotation of the same
    answer carries. The `spelling.unsaid` ratchet counts clues per puzzle, not
    which clue, so an allowance left over from before the spelling was filled
    (book-26021 22D, APERÇU, 10-17) absorbed the loss and CI caught it
    hours later. Comparing with HEAD sees it in the run itself."""
    committed = committed_entries(path)
    if committed is None:
        return
    for e in puzzle["entries"]:
        was = committed.get(entry_id(e))
        if not was or (was.get("solution") or "").upper() != (e.get("solution") or "").upper():
            continue
        spelling = (was.get("annotation") or {}).get("spelling")
        if spelling and e.get("annotation") and not e["annotation"].get("spelling"):
            errors.append(
                f"{entry_id(e)}: the committed annotation spells the answer {spelling!r} "
                f"and this one has no spelling. Keep it: in the model's shape write "
                f"`answer` as {spelling!r}")


#: The letters an OCR'd clue's SOURCE_CLUE_WRONG correction may change: a
#: misread letter or two ("judge" for "fudge", "rn" for "m"), never a reword.
OCR_MISREAD_EDITS = 3


def edit_distance(a, b):
    """Levenshtein distance between two strings."""
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, cb in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (ca != cb))
    return row[-1]


def ocr_misread_edits(served, printed):
    """The letters an OCR'd clue's correction changes, by clue_words. A run of
    capitals the OCR glued on before the clue ("BEBGOWNAURWN A second
    Cromwell?", a page header read into the column) is stray text dropped,
    not the clue reworded, so it is measured without that run when the
    printed clue does not open with it."""
    edits = edit_distance(clue_words(served), clue_words(printed))
    head = re.match(r"\s*([A-Z]{6,})\s+(?=\S)", served or "")
    if head and not clue_words(printed).startswith(head.group(1).lower()):
        edits = min(edits, edit_distance(clue_words(served[head.end():]), clue_words(printed)))
    return edits


#: How a SOURCE_CLUE_WRONG row's evidence opens when its clue was read off
#: the printed page (tools/scan_crop.py), not mended from the wordplay.
SCAN_READ = "Scan reads: "


def clue_row_problems(served, printed, why):
    """What stops a SOURCE_CLUE_WRONG row [served, printed, why] being a
    correction with evidence: it must change the text, and its note must argue
    the case (an OCR misread needs only a short one, a clue read off the scan
    is evidenced by the page however short the clue). One rule for the filer
    (annotate_check) and tests/test_source_answer_wrong.py."""
    floor = (len(SCAN_READ) + 1 if why.startswith(SCAN_READ)
             else 25 if why.startswith("OCR misread: ") else 40)
    problems = []
    if served.strip() == printed.strip():
        problems.append("corrects nothing: the clue as printed is the clue as shown, "
                        "so put the corrected clue first and the evidence second")
    if len(why) < floor:
        problems.append(f"the evidence {why!r} is under {floor} characters: say what the "
                        f"OCR read and what the page prints")
    return problems


def scan_read(pid, eid):
    """Whether light `eid`'s SOURCE_CLUE_WRONG row was read off `pid`'s scan,
    which tools/scan_crop.py can show: a clue read off the page is the
    print's, however far the OCR strayed from it."""
    why = SOURCE_CLUE_WRONG.get((pid, eid), (None, None, ""))[2]
    if not why.startswith(SCAN_READ):
        return False
    import scan_crop
    try:
        scan_crop.crop(pid)
    except scan_crop.NoCrop:
        return False
    return True


def check_clue_unchanged(puzzle, path, errors):
    """An annotation explains the clue it was written against, and the clue is
    the source's. An annotated entry whose clue's words differ from the
    committed file's is a run that rewrote the clue to suit its parse, unless
    the new words are the ones fetch_puzzle.SOURCE_CLUE_WRONG prints for that
    light: a correction filed there is what every re-fetch writes, so the
    annotation written for it stands in the same run. An OCR'd clue
    (provenance.OCR_CHANNELS) takes one only within OCR_MISREAD_EDITS letters,
    unless it was read off the scan (scan_read). Typography (quotes,
    dashes, accents, spacing) is not a different clue."""
    committed = committed_entries(path)
    if committed is None:
        return                  # not committed yet: nothing to compare with
    was = {i: enumeration.printed(e["clue"]) for i, e in committed.items()}
    for e in puzzle["entries"]:
        now = enumeration.printed(e["clue"])
        if (e.get("annotation") is None or entry_id(e) not in was
                or clue_words(was[entry_id(e)]) == clue_words(now)):
            continue
        filed = corrected_clue(puzzle.get("id"), entry_id(e))
        ocr = (puzzle.get("source") or {}).get("retrievedFrom") in provenance.OCR_CHANNELS
        if filed is not None and clue_words(filed) == clue_words(e["clue"].get("text")):
            # Measured on the committed clue's text, as the row's printed words are: its count's digits
            # are no letter the correction changes ("Pnde" for "Pride" under (6,4) is 2, not 4).
            misread = ocr_misread_edits(committed[entry_id(e)]["clue"].get("text") or was[entry_id(e)], filed)
            if not ocr or misread <= OCR_MISREAD_EDITS or scan_read(puzzle.get("id"), entry_id(e)):
                continue
            errors.append(
                f"{entry_id(e)}: SOURCE_CLUE_WRONG changes {misread} letters of the "
                f"OCR's {was[entry_id(e)]!r}; a misread is at most {OCR_MISREAD_EDITS} "
                f"(judge for fudge). A clue that needs more is not the OCR's to mend: "
                f"put it back and leave the entry null, unless the puzzle has a scan "
                f"(tools/scan_crop.py) and the row's evidence opens {SCAN_READ!r}")
            continue
        errors.append(
            f"{entry_id(e)}: clue changed from {was[entry_id(e)]!r} to {now!r} "
            f"under an annotation. The clue text is the source's, not the "
            f"annotator's: put it back, or, when the source serves it wrong, "
            f"give its _ann entry \"printedClue\": [\"<clue as printed, no "
            f"count>\", \"<evidence>\"], which files the change so it and this "
            f"annotation pass together")


def check_clue_rows_held(puzzle, errors):
    """A puzzle holds every tools/data/source_clue_wrong.json row filed for
    it: a clue still as the source served it, where the row prints it
    otherwise, ships the misprint beside the row that mends it.
    tools/annotate_check.py writes the rows in (apply_annotations.mend_clues)."""
    for e in puzzle["entries"]:
        text = e["clue"].get("text")
        printed = source_clue(puzzle.get("id"), entry_id(e), text)
        if clue_words(printed) != clue_words(text):
            errors.append(
                f"{entry_id(e)}: tools/data/source_clue_wrong.json prints this clue "
                f"as {printed!r}, but the file holds {text!r}. Run python3 "
                f"tools/annotate_check.py {puzzle.get('id')}, which writes the row in")


# The indicators rung is a tier below the building blocks, and a note written as
# the operation happens hands the blocks over: "returning means RATS becomes
# STAR" solves the clue before the solver has found a piece. A note may point at
# a block's clue words ("returning means the word rats is read backwards"),
# since the solver can read those in the clue, but never at its letters: a
# block's `gives` where that is not just its clue words, or the answer. Every
# note in the corpus is held to it, so the app renders a note as written.
def letters_given_in(note, ann):
    """The capitalised words of `note` that spell a block's letters, where those
    are not just its own clue words, or the answer or one of its words."""
    bare = lambda s: re.sub(r"[^A-Za-z]", "", str(s or "")).upper()
    blocks = ann.get("blocks") or []
    letters = {bare(b.get("gives")) for b in blocks
               if bare(b.get("gives")) and bare(b.get("gives")) != bare(b.get("clueFragment"))}
    answer = str(ann.get("answer") or "")
    letters |= {bare(w) for w in [answer, *re.split(r"[\s-]+", answer)] if bare(w)}
    return [w for w in re.findall(r"\b[A-Z]+\b", str(note or ""))
            if w in letters and w not in ("A", "I")]


def check_indicator_notes_name_no_block(tag, ann, errors):
    """An indicator note spells no block's letters and not the answer."""
    for ind in ann.get("indicators") or []:
        if not isinstance(ind, dict):
            continue
        named = letters_given_in(ind.get("note"), ann)
        if named:
            errors.append(
                f"{tag}: note on indicator {ind.get('text')!r} gives away the "
                f"letters {', '.join(dict.fromkeys(named))} — {ind.get('note')!r}. "
                f"The indicators rung comes before the blocks, so say what these "
                f"words mean and what they do; a block's clue words may be named, "
                f"never its letters or the answer: \"returning means the word rats "
                f"is read backwards\", not \"returning means RATS becomes STAR\"")


# "the two end letters of touchy" reads as the last two letters, HY, beside a
# block that takes the outer pair, TY (timesquick-3456 23A, reported). Every one
# of the 1,486 corpus uses meant first and last, so the phrase is banned outright.
# "the end letters" alone is not caught: the corpus also uses it, fairly, for the
# last letters of several words.
TWO_END_LETTERS = re.compile(r"\btwo end letters?\b", re.I)


def _prose_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _prose_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _prose_strings(v)


def check_no_two_end_letters(tag, ann, errors):
    """No prose says "two end letters": solvers read it as the last two."""
    for s in dict.fromkeys(_prose_strings(ann)):
        if TWO_END_LETTERS.search(s):
            errors.append(
                f"{tag}: {s!r} says \"two end letters\", which reads as the last "
                f"two letters. Say \"first and last letters\" (\"extremely means "
                f"the first and last letters of touchy are taken\"), or \"last two "
                f"letters\" if that is what is meant")


# A selector is an indicator: "capital of Bahrain" giving B is the indicator
# "capital of" and the block "Bahrain" (telegraph-31356 24D). A block that swallows its selector teaches the
# letters with the instruction hidden inside them. The phrases are the ones the
# corpus uses to take a word's first, last or middle letters; a block is held to
# the rule only when its letters are that selection of the words left over, so
# "head of state" giving some other piece is not caught. Checked on the entries
# a run wrote, the way check_clue_unchanged is.
SELECT_NOUNS = {
    "first": "first|capital|head|heads|leader|leaders|start|starts|beginning|beginnings"
             "|opening|openings|top|front|source|origin|origins|onset|starter|starters"
             "|introduction|tip|foremost|entrance|face",
    "last": "last|end|ends|ending|close|back|tail|rear|finish|conclusion|finale|bottom"
            "|edge|terminal|ultimate",
    "middle": "middle|centre|center|heart|core|focus|inside",
}
SELECT_ADVERBS = {
    "first": "initially|originally|primarily|principally|firstly|at first|first of all"
             "|first|to begin with|for starters|at the outset|in the beginning|to start"
             "|beginning to|starting to|starts to|start to|first to|heading for|heading to"
             "|head for|leading",
    "last": "finally|ultimately|at last|lastly|in the end|at the end|eventually|last",
    "middle": "essentially|centrally|at heart|at the centre",
}


def _select_groups(table):
    return "|".join(f"(?P<{k}>{v})" for k, v in table.items())


SELECTOR_LEADS = [
    re.compile(r"^(?P<sel>(?:the\s+)?(?:" + _select_groups(SELECT_NOUNS)
               + r")\s+(?:of|to|for|in|from))\s+(?P<rest>.+)$", re.IGNORECASE),
    re.compile(r"^(?P<sel>" + _select_groups(SELECT_ADVERBS) + r"),?\s+(?P<rest>.+)$",
               re.IGNORECASE),
]
SELECTOR_TAIL_WORDS = _select_groups(
    {k: f"{SELECT_ADVERBS[k]}|(?:(?:at|in|to)\\s+(?:the\\s+)?)?(?:{SELECT_NOUNS[k]})"
     for k in SELECT_NOUNS})
SELECTOR_TAIL = re.compile(
    r"^(?P<rest>.+?)(?:['\u2019]s)?,?\s+(?P<sel>" + SELECTOR_TAIL_WORDS + r")$",
    re.IGNORECASE)
SELECTOR_ALONE = re.compile(r"^(?:" + SELECTOR_TAIL_WORDS + r")$", re.IGNORECASE)


def selector_in_block(block):
    """(selector words, source words) when `block`'s clue words are a letter
    selector plus the words it selects from and its letters are that selection
    (a first, last or middle letter, or one from each word); else None."""
    bare = lambda s: re.sub(r"[^A-Za-z]", "", str(s or "")).upper()
    fragment = str(block.get("clueFragment") or "").strip()
    gives = bare(block.get("gives"))
    if not gives or len(fragment.split()) < 2 or SELECTOR_ALONE.match(fragment):
        return None
    for pattern in [*SELECTOR_LEADS, SELECTOR_TAIL]:
        m = pattern.match(fragment)
        if not m:
            continue
        where = next(k for k in SELECT_NOUNS if m.group(k))
        words = [bare(w) for w in m.group("rest").split() if bare(w)]
        run = "".join(words)
        if not run:
            continue
        kept = {"first": {run[0], "".join(w[0] for w in words)},
                "last": {run[-1], "".join(w[-1] for w in words)},
                "middle": {run[(len(run) - 1) // 2:len(run) // 2 + 1]}}[where]
        if gives in kept:
            return m.group("sel").strip(" ,"), m.group("rest").strip(" ,")
    return None


def check_selectors_are_indicators(puzzle, path, errors):
    """A new or changed annotation's letter-selection block holds only the
    words it selects from; the selector is an indicator."""
    import annotation
    committed = committed_entries(path) or {}
    # Changed is judged on the stored annotation; the blocks are derived
    # (the file stores a tree, so they come from view()).
    for e, seen in zip(puzzle["entries"], annotation.view_puzzle(puzzle)["entries"]):
        ann = e.get("annotation")
        if not isinstance(ann, dict) or ann == (committed.get(entry_id(e)) or {}).get("annotation"):
            continue
        for b in (seen.get("annotation") or {}).get("blocks") or []:
            found = isinstance(b, dict) and selector_in_block(b)
            if found:
                sel, rest = found
                errors.append(
                    f"{entry_id(e)}: block {b.get('clueFragment')!r} gives "
                    f"{b.get('gives')!r} with its selector inside it. {sel!r} is the "
                    f"instruction, so it is an indicator ({{\"text\": {sel!r}, \"for\": "
                    f"\"letter_selection\"}}, letter_selection in type), and the block "
                    f"is the source alone: {{\"clueFragment\": {rest!r}, \"gives\": "
                    f"{b.get('gives')!r}, \"select\": ...}}")