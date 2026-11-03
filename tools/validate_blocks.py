"""Block checks of validate_annotations.py: blocks account for the answer, decompose, keep order and carry notes.

Moved out of validate_annotations.py unchanged; that module re-exports every name here.
"""

import json
import annotation
from annotation import assembly, wordplay_letters
from hidden_messages import block_letters

from validate_base import types_of, letters
from validate_anagram import multiset_diff

# Mechanisms where the blocks legitimately do not add up to the answer: a
# deletion, substitution or composite anagram names letters that are taken away,
# a move names letters its fodder already holds (ALBION, and the O it moves),
# and the three definition-only types plus the sound types claim no letters at all.
UNBALANCED_TYPES = ("deletion", "substitution", "move", "composite_anagram", "cryptic_definition",
                    "double_definition", "homophone", "spoonerism", "and_lit")

# A clue whose whole mechanism is one letter selection hands over those letters
# and nothing else, so when the answer is longer the answer is DESCRIBING the
# extraction rather than being built from it — 12423 16A, MIDDLE OF NOWHERE.
# Matched exactly: a compound that merely includes a selection
# (charade + letter_selection) does have to add up.
UNBALANCED_EXACT_TYPES = (["letter_selection"],)

# The three block-shape checks below allow no per-puzzle tolerance. None of them
# has a false positive, so none has a reason to let a hit through: a tolerance
# would keep forgiving the same defect on every puzzle fetched.


def blocks_miss_letters(ann, entry):
    """Whether check_blocks_account_for_answer reports this entry: its blocks give
    letters, not the answer's, and its type builds from them."""
    atype = types_of(ann)
    if any(x in atype for x in UNBALANCED_TYPES) or atype in UNBALANCED_EXACT_TYPES:
        return False
    got = "".join(letters(b.get("gives")) for b in ann.get("blocks") or [] if isinstance(b, dict))
    want = block_letters(ann, wordplay_letters(ann, entry))
    # A repeat shows one copy as its blocks (annotation.repeat_copy_letters).
    got2 = got + annotation.repeat_copy_letters(ann.get("wordplay"), wordplay_letters(ann, entry))
    if bool(got) and sorted(got) != sorted(want) and sorted(got2) != sorted(want):
        # A selection over a built value shows the letters before the pick.
        cut, kept = annotation.selection_over_built(ann.get("wordplay"), wordplay_letters(ann, entry))
        if cut:
            from collections import Counter
            want3 = Counter(want) - Counter(cut) + Counter(kept)
            if want3 == Counter(got) or want3 == Counter(got2):
                return False
    return bool(got) and sorted(got) != sorted(want) and sorted(got2) != sorted(want) \
        and sorted(got) != sorted(slipped_letters(ann, want))


def slipped_letters(ann, want):
    """`want` as the blocks hand it over when an anagram of the annotation is a
    setter's slip (fodder that does not hold the letters it gives): its fodder
    as printed in place of what it gives. check_anagram_letters lets such an
    anagram stand only when tools/data/setter_error.json names it, so this
    forgives nothing else. (An unchecked step may instead have respelt a block to
    hide the slip; its blocks then add up to `want` itself.)"""
    from collections import Counter
    have = Counter(want)
    for a in assembly(ann).get("anagrams") or []:
        if not isinstance(a, dict):
            continue
        f, g = Counter(letters(a.get("fodder") or "")), Counter(letters(a.get("gives") or ""))
        if f != g and not (g - have):
            have = have - g + f
    return "".join(sorted(have.elements()))


def missing_link_word_fix(ann, extra, missing):
    """The exact edit when the blocks' missing letters are a word filed under
    linkWords: that word is fodder, so it becomes a block and leaves linkWords."""
    if extra or not missing:
        return ""
    for w in ann.get("linkWords") or []:
        if isinstance(w, str) and sorted(letters(w)) == sorted(missing):
            return (f". {w!r} is in linkWords but its letters are the missing ones: "
                    f"remove it from linkWords and add the block "
                    f"{{\"clueFragment\": {json.dumps(w)}, \"gives\": {json.dumps(letters(w))}}}")
    return ""


MAX_SURPLUS_EDITS = 3


def surplus_letters_fix(ann, extra, missing, want):
    """The single-block edits that take exactly the surplus letters away when the
    blocks give too many and none too few: drop a block whose letters are the
    surplus, or cut the surplus off one block's ends. Edits that also leave the
    blocks spelling the answer in order are listed first."""
    if missing or not extra:
        return ""
    blocks = [b for b in ann.get("blocks") or [] if isinstance(b, dict)]
    gives = [letters(b.get("gives")) for b in blocks]
    edits = []
    for i, g in enumerate(gives):
        if sorted(g) == sorted(extra):
            edits.append((i, ""))
            continue
        for k in range(len(extra) + 1):
            cut = g[k:len(g) - (len(extra) - k)]
            if cut and sorted(g[:k] + g[len(g) - (len(extra) - k):]) == sorted(extra) \
                    and (i, cut) not in edits:
                edits.append((i, cut))
    if not edits:
        return ""
    edits.sort(key=lambda e: "".join(e[1] if j == e[0] else g
                                     for j, g in enumerate(gives)) != want)
    said = []
    for i, cut in edits[:MAX_SURPLUS_EDITS]:
        frag = blocks[i].get("clueFragment")
        if cut:
            said.append(f"block {frag!r} gives {cut!r}, not {gives[i]!r}")
        else:
            said.append(f"drop block {frag!r} > {gives[i]!r}"
                        + (" (a word used for nothing goes in linkWords)" if frag else ""))
    head = ("one edit makes them add up: " if len(said) == 1 else
            "each of these single edits makes them add up — make the one the clue supports: ")
    tail = (". A cut block's note must name the cut word; if the clue itself removes "
            "the letters, type it deletion and list the indicator"
            if any(cut for _, cut in edits[:MAX_SURPLUS_EDITS]) else "")
    return f". {head}{'; or '.join(said)}{tail}"


def check_blocks_account_for_answer(entries, errors, warnings):
    """The letters the blocks hand over have to be the answer's letters.

    Not a restatement of the `pieces` check: `pieces` is the annotator's own
    summary and is checked against the answer, so a parse can have immaculate
    pieces and blocks that say something else entirely (pieces T/RIG/GER with
    blocks T + R + IG for TRIGGER). The blocks are what the app renders — they
    are what the learner reads.

    CALIBRATION: 0 of 671. The one exception, 12423 16A (MIDDLE OF NOWHERE), is
    not a defect: the answer describes where the H sits rather than being built
    out of letters, which is a property of its type, so UNBALANCED_EXACT_TYPES
    exempts that type. Any other hit is an error.
    """
    hits = []
    for e in entries:
        ann = e.get("annotation") or {}
        if not ann:
            continue
        if blocks_miss_letters(ann, e):
            got = "".join(letters(b.get("gives")) for b in ann.get("blocks", []))
            want = block_letters(ann, wordplay_letters(ann, e))
            tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
            hits.append(tag)
            extra, missing = multiset_diff(got, want)
            warnings.append(
                f"{tag}: the blocks give {got!r}, but the answer is {want!r}"
                + (f" (extra {extra!r})" if extra else "")
                + (f" (missing {missing!r})" if missing else "")
                + " — the blocks are what the learner actually reads, so they have "
                  "to be the parse, not a sketch of one"
                + missing_link_word_fix(ann, extra, missing)
                + surplus_letters_fix(ann, extra, missing, want))
    if hits:
        errors.append(
            f"puzzle: {len(hits)} clue(s) ({', '.join(hits)}) have blocks whose letters "
            f"are not the answer's. Letters that don't add up mean the wordplay was "
            f"described rather than worked out, or, when they build a real word a "
            f"letter or two from a printed answer that is not one, that the key is "
            f"misprinted: give that _ann entry \"answerTypo\": [\"<letters the "
            f"wordplay builds>\", \"<evidence>\"]")


def check_blocks_decompose(entries, errors, warnings):
    """If `pieces` takes the answer apart, the blocks must take it apart too.

    A charade with `pieces: ["SOD", "DEN"]` and one block reading
    `"Two types of earth" > SODDEN` has named the mechanism and then not
    performed it, which is the whole of what a learner came for.

    CALIBRATION: 0 of 398 clues with 2+ pieces, and errors on any hit. There is
    no case where the annotator is entitled to both fields disagreeing — one of
    the two is wrong, and which one is the annotator's call (ATOM: its wordplay
    yields the single string "A TO M" and nothing clues the TO, so the block is
    right and `pieces` describes a parse not done).
    """
    hits = []
    for e in entries:
        ann = e.get("annotation") or {}
        if not ann:
            continue
        pieces = assembly(ann).get("pieces") or []
        if len(pieces) < 2:
            continue
        # `pieces` spelled out letter by letter — A+L+F+A, N+U+D+I+T+Y — is an
        # anagram's letter list, not a charade's chunks, and one block holding the
        # whole fodder is exactly right there.
        if all(len(letters(p)) <= 1 for p in pieces):
            continue
        full = [b for b in ann.get("blocks", [])
                if letters(b.get("gives")) == wordplay_letters(ann, e)]
        lettered = [b for b in ann.get("blocks", []) if letters(b.get("gives"))]
        if full and len(lettered) == 1:
            tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
            hits.append(tag)
            warnings.append(
                f"{tag}: pieces are {'+'.join(pieces)} but there is one block "
                f"handing over the whole answer — split it, one block per piece. "
                f"Naming a charade is not doing the charade")
    if hits:
        errors.append(
            f"puzzle: {len(hits)} clue(s) ({', '.join(hits)}) name a multi-piece parse "
            f"and then give the answer in one block")


def check_blocks_in_answer_order(entries, errors, warnings):
    """A charade's blocks have to be listed in the order the answer reads.

    The app renders blocks top to bottom, so a learner reads them as the build.
    `PEAS` then `SWEET` for SWEET PEAS (1388 23A) hands over the right letters in
    the wrong order and quietly asks the learner to do the reassembly that the
    annotation exists to show. Nothing caught it: `check_blocks_account_for_answer`
    compares multisets, so a permutation passes it perfectly.

    The letters of such a clue are correct; the ORDER is the teaching, and it is
    wrong. Backlog size is not a reason to drop a check, only false positives
    are, and under the tight scope below there are none.

    SCOPE is the whole trick. It applies only to `type == ["charade"]` exactly.
    Any positional mechanism in the mix legitimately lists blocks out of final
    order: a container's inner piece goes inside rather than after, and a
    rotation is *defined* by blocks assembled before the spin — 30079 7D TSUNAMIS
    is A + MIST + SUN and only then cycled, which a looser scope flags and which
    is perfectly annotated. Widening from `charade` to "charade and nothing
    positional" adds 4 hits, 2 of them false. So it stays narrow.

    CALIBRATION: 10 of 127 pure charades, every one a genuine misordering (1388
    23A, 30039 24A, 30041 28D, 30042 8D, 30043 7D, 30044 19D, 30078 25A, 30079
    8D/11A/22A). Each clue still warns with its own letters, and any hit fails the puzzle: the
    fix is mechanical, since exactly one ordering of the blocks spells the answer.
    """
    hits = []
    for e in entries:
        ann = e.get("annotation") or {}
        if not ann:
            continue
        if types_of(ann) != ["charade"]:
            continue
        got = "".join(letters(b.get("gives")) for b in ann.get("blocks", []))
        want = wordplay_letters(ann, e)
        if not got or got == want:
            continue
        from collections import Counter
        # Wrong letters are a different fault, already reported by
        # check_blocks_account_for_answer. Only a permutation is this one.
        if Counter(got) != Counter(want):
            continue
        tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
        hits.append(tag)
        warnings.append(
            f"{tag}: the blocks read {got!r} but the answer is {want!r} — same "
            f"letters, wrong order. The app renders blocks top to bottom, so "
            f"list them in answer order and let each clueFragment point back at "
            f"wherever it sits in the clue")
    if hits:
        errors.append(
            f"puzzle: {len(hits)} charade(s) ({', '.join(hits)}) list their blocks in "
            f"clue order rather than answer order")


#: What the block warning says in place of "has no note", so the ratchet's
#: indicators.note marker ("has no note") cannot count it.
BLOCK_NO_NOTE = "has no block note"


def check_blocks_carry_notes(entries, warnings):
    """A block that claims letters has to say why it gets them.

    The `note` is where the convention lives — `worker` = ANT, `setter` = ME —
    and it is the only field that can be wrong in a way the letters can't reveal.
    An unexplained block is where an invented one hides. CALIBRATION: 1 of 1347 across this repo (30044 2D, `a` > A,
    where there is genuinely nothing to say). Warning only, for that reason.
    """
    for e in entries:
        ann = e.get("annotation") or {}
        if not ann:
            continue
        tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
        for b in ann.get("blocks", []):
            if not letters(b.get("gives")) or str(b.get("note") or "").strip():
                continue
            # No clue words: nothing to key a note on (`notes` is keyed by the
            # fragment, so the advice below would say `notes: {'': ...}`). The
            # block is either preamble-supplied letters or already an error in
            # _validate_puzzle ("a block with no clueFragment"); one cause, one line.
            if not str(b.get("clueFragment") or "").strip():
                continue
            # A fragment that is its own letters ('a' > A, 'in' > IN) has
            # nothing to teach and app.js shows its letters without a note.
            if letters(b.get("clueFragment")) == letters(b.get("gives")):
                continue
            frag = str(b.get("clueFragment") or "")
            warnings.append(
                f"{tag}: block {b.get('clueFragment')!r} > {b.get('gives')!r} {BLOCK_NO_NOTE}. "
                f"Say why those words give those letters — that sentence is the "
                f"teaching, and its absence is how an invented block hides. In the "
                f"annotation add the leaf's words to `notes`: \"notes\": {{{frag!r}: "
                f"\"<why {frag!r} gives {b.get('gives')}>\"}} (wp `[{frag}]{b.get('gives')}`); "
                f"this is a block note, not an indicator note"
                + (f". '{frag}' is also an indicator here: the note says what it gives AND that the same "
                   f"word signals the op" if any(letters(str(i.get("text"))) == letters(frag)
                                                  for i in ann.get("indicators", []) if isinstance(i, dict)) else ""))