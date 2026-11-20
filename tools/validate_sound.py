"""Sound-clue checks of validate_annotations.py: a homophone or spoonerism names its source.

Moved out of validate_annotations.py unchanged; that module re-exports every name here.
"""

from validate_base import types_of, letters

SOUND_TYPES = ("homophone", "spoonerism")


def _sound_over_step(tree):
    """The op of a step (first, del, hid, ...) a sound() wraps, else None."""
    nodes = [tree]
    while nodes:
        n = nodes.pop()
        if isinstance(n, dict):
            if n.get("op") == "homophone":
                for p in n.get("parts") or []:
                    if isinstance(p, dict) and p.get("op") not in (None, "homophone"):
                        return p["op"]
            nodes.extend(n.get("parts") or [])
    return None


def plain_spoonerism(ann):
    """True when the only sound in the clue is a spoon: spoon(a, b) swaps the
    onsets in the letters the two blocks give (CORE FAST -> FORE CAST), and
    spoon(a, b, SPELT) swaps them by sound, the blocks giving the words said
    ([marry]MARRY, [fan]FAN) and SPELT the answer's spelling (FERRYMAN). Either
    way the heard words are the blocks' own `gives`, so there is nothing for
    `soundsLike` to carry; demanding one trapped runs into sound([x]W, W),
    which fails the 'nothing was heard' rule instead. A spoon filed over a
    sound() (the older form) has a homophone type, so it is not plain and is
    still held to the sound rule."""
    if "homophone" in types_of(ann):
        return False
    nodes, found = [ann.get("wordplay")], []
    while nodes:
        n = nodes.pop()
        if isinstance(n, dict):
            if n.get("op") == "spoonerism":
                found.append(n)
            nodes.extend(n.get("parts") or [])
    return bool(found)


def check_sound_names_its_source(tag, ann, errors, warnings):
    """A homophone must name the word you say aloud, as a field, not as prose.

    In "Cockney mob loudly" → OARED, a block reading “Cockney mob” → OARED
    leaves every step of the actual clue off-screen: a mob is a HORDE, a Cockney
    drops the aitch to leave ’ORDE, and ’ORDE said aloud is OARED. That rung
    asserts the answer and teaches nothing.

    The source word cannot live only in a note, because a note is prose and
    prose is unenforceable: a horde mentioned in passing, buried mid-sentence,
    still reads as a leap. So `soundsLike` is a tracked
    field on the block that does the sounding, it is required on every clue
    whose type declares a sound, and it must differ from what the block gives —
    a `soundsLike` equal to the output is not a homophone, it is a spelling.
    """
    is_sound = any(t in types_of(ann) for t in SOUND_TYPES) and not plain_spoonerism(ann)
    heard = [b for b in ann.get("blocks", []) if b.get("soundsLike")]
    for b in heard:
        if not b.get("gives"):
            errors.append(f"{tag}: block {b.get('clueFragment')!r} has soundsLike "
                          f"{b['soundsLike']!r} but no `gives` — say what it comes out as")
        elif letters(b["soundsLike"]) == letters(b["gives"]):
            errors.append(f"{tag}: soundsLike {b['soundsLike']!r} and gives "
                          f"{b['gives']!r} are the same letters, so nothing was heard. "
                          f"A homophone is two spellings of one sound")
        elif letters(b["soundsLike"]) == letters(ann.get("answer") or ""):
            errors.append(f"{tag}: soundsLike {b['soundsLike']!r} is the answer itself, "
                          f"and the blocks rung prints it before the walkthrough. "
                          f"soundsLike is the word you say aloud and gives is what it "
                          f"comes out as: swap them (soundsLike {b['gives']!r}, gives "
                          f"{b['soundsLike']!r})")
    if not is_sound:
        if heard and not plain_spoonerism(ann):
            errors.append(f"{tag}: a block declares soundsLike but the type is "
                          f"{ann.get('type')!r} — add the sound to the type or drop the field")
        return
    if not heard:
        blocks = [b for b in ann.get("blocks", []) if b.get("clueFragment") and b.get("gives")]
        ours = [b for b in blocks if letters(b["gives"]) == letters(ann.get("answer") or "")]
        pick = (ours or blocks[-1:] or [None])[-1]
        here = ""
        if pick:
            frag, gives = pick["clueFragment"], pick["gives"]
            here = (f"In this clue the block to fix is {frag!r} > {gives!r}: write it in "
                    f"`wp` as sound<indicator>([{frag}]HEARD, {gives}) with HEARD the "
                    f"word you say aloud for {frag!r}, not {gives!r} itself. ")
        over = _sound_over_step(ann.get("wordplay"))
        if over:
            here = (f"Here sound() wraps a `{over}` step, and a sound takes ONE leaf: "
                    f"write the letters that step gives as the leaf, "
                    f"sound<indicator>([the clue words]LETTERS, SPELT), and say in the "
                    f"leaf's note how the words give those letters. ") + here
        errors.append(
            f"{tag}: type {ann.get('type')!r} but no block says what is said aloud. "
            f"{here}"
            f"Add `soundsLike` to the block that does the sounding: the word you "
            f"HEAR is the clue's whole mechanism, and a block that jumps a "
            f"fragment straight to the answer has taught none of it. The note "
            f"carries the step before the sound: \"Cockney mob loudly\" -> OARED is "
            f"soundsLike ’ORDE, gives OARED, the note saying a mob is a HORDE and a "
            f"Cockney drops the aitch. A mechanism feeding the sound gets its own "
            f"earlier block. In `wp` that block is `sound<indicator>(x, SPELT)` "
            f"where x is ONE leaf, [the clue words you say]LETTERS HEARD (merge a "
            f"charade of leaves into a single leaf, or put the charade outside the "
            f"sound), and SPELT is the letters it comes out as. A Spoonerism is "
            f"not written with sound(): swap written letters with `spoon(a, b)`, or "
            f"swap by sound with `spoon<indicator>([marry]MARRY, [fan]FAN, FERRYMAN)`, "
            f"the leaves giving the words said and the third argument the answer")


def check_sound_is_not_a_letter_swap(tag, ann, errors, warnings):
    """A spoonerism trades SOUNDS. A soundsLike made by trading letters is a fake.

    In quiptic 1398 9A, blocks giving DOUGH and NOUGHT followed by a third block
    declaring the pair sounded like "NOUGH DOUGHT" is a string arrived at by
    exchanging the two words' first LETTERS and re-spelling nothing else. It is
    not a word, not a pronunciation and not anything the solver can say aloud,
    so the rung ends at gibberish and the reader must leap from it to NO DOUBT
    unaided. Spooner swaps the opening sounds: "doh" and "nawt" become "noh" and
    "dawt", which are then SPELT NO and DOUBT, and the respelling is the lesson.

    The tell is arithmetic. When a sounded form uses exactly the letters the
    earlier blocks already gave, only in a different order, no sound was
    recorded — the annotator shuffled characters between the chunks. In the
    corpus: 3 hits in 328 sound clues (quiptic-1398 9A "NOUGH DOUGHT",
    independent-12412 5D "FOG BOE", indysunday-1871 13A "FONE CALL"), all the
    same defect. A sounded form that legitimately restates the earlier
    blocks — everyman-4134's SOLELY + HE -> "SOLELY HE" — is those letters in
    the SAME order, and is left alone.
    """
    blocks = ann.get("blocks", [])
    for i, b in enumerate(blocks):
        said = letters(b.get("soundsLike") or "")
        if not said:
            continue
        prior = "".join(letters(x.get("gives") or "") for x in blocks[:i])
        if prior and said != prior and sorted(said) == sorted(prior):
            errors.append(
                f"{tag}: soundsLike {b['soundsLike']!r} is the earlier blocks' own "
                f"letters ({prior}) rearranged, so it records a letter swap and not "
                f"a sound. Give each half of the answer its own block — the word it "
                f"sounds like before the swap, and the letters it comes out as after")