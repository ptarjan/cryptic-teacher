"""Hidden-word and reversal checks of validate_annotations.py.

Moved out of validate_annotations.py unchanged; that module re-exports every name here.
"""

import re
from annotation import assembly

from validate_base import types_of, indicator_texts, letters, words_of
from validate_link import joints

# A word, with any apostrophe or hyphen inside it: "friend's" and
# "ham-fistedly" are one word each. tools/build_authored_puzzle.py reads
# hidden words with it too.
HIDDEN_WORD_RE = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*")


def hidden_runs(clue, ann):
    """Where the answer, forwards or reversed, spells itself across a word break
    in the clue words outside every definition: (direction, words) pairs, the
    direction "forwards" or "reversed" and the words the run crosses. A run of
    whole words is not hidden (ASTI reverses "It's a" outright), so it is not
    reported."""
    answer = letters(ann.get("answer"))
    if len(answer) < 3:
        return []
    spans = [(d["at"], d["at"] + len(d["text"])) for d in ann.get("definitions") or []
             if isinstance(d, dict) and isinstance(d.get("at"), int)
             and isinstance(d.get("text"), str)]
    runs = []
    # A definition breaks the text into stretches; a run may not cross one.
    cuts = sorted(spans) + [(len(clue), len(clue))]
    start = 0
    for a, b in cuts:
        stretch = clue[start:a] if a > start else ""
        start = max(start, b)
        text, word, words = [], [], []
        for n, m in enumerate(HIDDEN_WORD_RE.finditer(stretch)):
            words.append(m.group())
            for ch in letters(m.group()):
                text.append(ch)
                word.append(n)
        text = "".join(text)
        targets = [("forwards", answer)]
        if answer != answer[::-1]:
            targets.append(("reversed", answer[::-1]))
        for direction, target in targets:
            for i in range(len(text) - len(target) + 1):
                j = i + len(target) - 1
                whole = ((i == 0 or word[i - 1] != word[i])
                         and (j + 1 == len(text) or word[j + 1] != word[j]))
                if text.startswith(target, i) and word[i] != word[j] and not whole:
                    run = (direction, " ".join(words[word[i]:word[j] + 1]))
                    if run not in runs:
                        runs.append(run)
    return runs


def inside_runs(clue, ann):
    """Where the answer, forwards or reversed, sits inside one clue word outside
    every definition without being all of it: (direction, word, left, right)
    tuples, left and right the counts of the word's letters on either side.
    A possessive's 's is not part of the word, so REMARK reversing "Kramer's"
    is a whole-word reversal."""
    answer = letters(ann.get("answer"))
    if len(answer) < 3:
        return []
    spans = [(d["at"], d["at"] + len(d["text"])) for d in ann.get("definitions") or []
             if isinstance(d, dict) and isinstance(d.get("at"), int)
             and isinstance(d.get("text"), str)]
    runs = []
    for m in HIDDEN_WORD_RE.finditer(clue):
        if any(m.start() < b and a < m.end() for a, b in spans):
            continue
        word = letters(re.sub(r"['’]s$", "", m.group(), flags=re.IGNORECASE))
        for direction, target in (("forwards", answer), ("reversed", answer[::-1])):
            if direction == "reversed" and target == answer:
                continue
            k = word.find(target)
            while k >= 0 and len(target) < len(word):
                run = (direction, m.group(), k, len(word) - k - len(target))
                if run not in runs:
                    runs.append(run)
                k = word.find(target, k + 1)
    return runs


# The devices that take a fixed stretch of one word: a deletion or selection
# keeps its front or back ("endless", "half", "first three") or its middle
# ("heart of", "uncovered", "centre"). An odd leftover puts the middle one
# letter off centre.
POSITIONAL_TYPES = {"deletion", "letter_selection"}


def trimmed_pieces(ann, words):
    """Whether blocks clue the run's words one by one, each giving its word whole
    or the front or back a deletion or selection keeps: APE from "a pet" as A +
    PE(T)."""
    frags = {letters(b.get("clueFragment")): letters(b.get("gives"))
             for b in ann.get("blocks") or [] if isinstance(b, dict)}
    for w in words.split():
        w, g = letters(w), frags.get(letters(w))
        if not g or not (w.startswith(g) or w.endswith(g)):
            return False
    return True


def check_unmarked_hidden_word(tag, ann, clue, errors):
    """An answer that spells itself across a word break in the wordplay is a
    hidden word, and its type says so, unless a block or indicator note says the
    run is a coincidence: pieces clued one by one that happen to sit side by
    side (TO + T in "to time", ILL + S in "will start").

    The same goes for an answer inside one word (TAR in "starting"), unless the
    type has a deletion or letter selection and the answer is the word's front,
    back or middle, the stretches those devices keep (TOSH as the heart of
    "Photoshop's", EXPO from "Sexpot stripped").

    CALIBRATION (published annotations, 2026-09-30): 57 of 85,250 hit it; 27
    were hidden words typed as something else (EGRET reversed in "after
    getting", ROUTINE in "Soldier out in Egypt"), 30 were coincidences. Inside
    one word, 82 non-hidden annotations hold the answer; 71 are a deletion's or
    selection's front, back or middle, and the other 11 were coincidences (TAR
    in "starting", PRESS opening "pressure")."""
    types = set(types_of(ann))
    if "hidden_word" in types:
        return
    notes = [str(x.get("note") or "") for key in ("blocks", "indicators")
             for x in ann.get(key) or [] if isinstance(x, dict)]
    if any("coinciden" in n.lower() for n in notes):
        return
    def fix(direction):
        return ("`hidden_word` and `reversal`" if direction == "reversed"
                else "`hidden_word`")
    positional = POSITIONAL_TYPES & types
    for direction, words in hidden_runs(clue, ann):
        if positional and direction == "forwards" and trimmed_pieces(ann, words):
            continue
        errors.append(
            f"{tag}: the answer runs {direction} across {words!r}, outside the "
            f"definition, but `type` has no hidden_word. Add {fix(direction)} to "
            f"`type` if the setter hid it there, or say in the note of the block "
            f"holding those words that it is a coincidence")
    for direction, word, left, right in inside_runs(clue, ann):
        if positional and (not left or not right or abs(left - right) <= 1):
            continue
        errors.append(
            f"{tag}: the answer sits {direction} inside {word!r} ({left} letters "
            f"before it, {right} after), outside the definition, but `type` has no "
            f"hidden_word. A deletion or letter selection keeps a word's front, back "
            f"or middle; a run anywhere else is a hidden word. Add {fix(direction)} "
            f"to `type` with {word!r} as the block, or say in that block's note "
            f"that it is a coincidence")


# A reversal runs along the entry, so the indicator has to name the entry's own
# direction. Which words name an axis is measured: tools/build_clue_joints.py
# binds a word to one when published reversal clues almost never use it on the
# other (`west` across, `up` down). Every other word is direction-neutral.


def check_reversal_direction(tag, ann, direction, errors):
    """A reversal indicator must point the way the entry runs.

    An across answer reads right to left when it is reversed, so `west`,
    `east` or `aback` fit it. A down answer reads bottom to top, so `up`,
    `rising`, `raised`, `climbing` or `north` fit it. Which words bind to an
    axis is measured by tools/build_clue_joints.py.

    CALIBRATION (published annotations): the convention is
    lopsided. Vertical words almost never reverse an across entry (`up` 2 of
    168 single-word uses). Horizontal words reverse down entries all the time:
    `back` sits on a down entry in 25 of 170 single-word uses and `returning`
    in 17 of 72. So `back` is neutral, not horizontal. With the measured lists,
    25 of 2,087 axis-word reversals cross over (1.2%).

    Only declared indicators are examined, and only on clues whose type or
    assembly.reversals say a reversal happens, so an ordinary `up` elsewhere in the
    surface is not the check's business (30039 11A reverses UP itself)."""
    if "reversal" not in types_of(ann) and not assembly(ann).get("reversals"):
        return
    wrong = set(joints()["vertical" if direction == "across" else "horizontal"])
    axis = ("an across entry reads right to left when reversed, so it wants "
            "west / east / aback"
            if direction == "across" else
            "a down entry reads bottom to top, so it wants up / rising / "
            "raised / climbing / north")
    for ind in indicator_texts(ann, "reversal"):
        hits = [w for w in words_of(ind) if w in wrong]
        if hits:
            errors.append(
                f"{tag}: reversal indicator {ind!r} points the wrong way for a "
                f"{direction} entry ({', '.join(hits)}) — {axis}, or a neutral word "
                f"such as turning, about or over (AUTHORING.md, "
                f"'A reversal runs along the entry')")