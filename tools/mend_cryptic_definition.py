"""Mechanical mends for a pure cryptic definition's blocks (validate_answers.
check_cryptic_definition_blocks), so the first check does not spend a model turn on them.

A cryptic definition has no wordplay, so a block's `gives` is only ever the whole
answer wearing a block's clothes: it is dropped. Text in it that is not the answer
moves into the block's `note`, unless that would spell the answer. A note that is
nothing but the answer ("= WATCHSTRAP", "the answer is WATCHSTRAP") is stripped.
Anything subtler (a definition that hides the answer, a note that works the answer
into a sentence) is the model's to retype or reword.

The check reads letters, not words, so a note that merely carries the answer inside a longer
word ("Lancelot" for LANCE, "typewriter" for TYPE, "distilling" for STILL) fails it as much as
one that names it. `blank_note_words` writes "..." over each such word, the corpus's way of
quoting a phrase without its missing word."""
import re


def _bare(s):
    return re.sub(r"[^a-z]", "", str(s or "").lower())


def _bare_answer_part(part, ans):
    """Whether `part` says nothing but the answer: "= X", "the answer is X", "it's X"."""
    if _bare(part) == ans:
        return bool(re.match(r"\W*(?:=|->|→)", part))
    p = re.sub(r"^\W*(?:=|->|→|(?:so|thus|that is|that's|it is|it's|is|(?:the )?answer(?: is)?)\b)\W*",
               "", part.strip(), flags=re.IGNORECASE)
    return bool(p) and _bare(p) == ans


def mend_block(b, ans):
    """Mend block `b` in place for a cryptic definition answering `ans` (letters only);
    whether it changed."""
    changed = False
    gives = b.pop("gives", None)
    if gives is not None:
        changed = True
        g = str(gives).strip()
        if g and _bare(g) != ans:
            note = str(b.get("note") or "").strip()
            moved = f"{note} ({g})" if note else g
            if ans not in _bare(b.get("clueFragment")) + _bare(moved):
                b["note"] = moved
    note = b.get("note")
    if isinstance(note, str) and ans:
        parts = re.split(r"(?<=[.;])\s+|\s*;\s*", note)
        kept = [p for p in parts if not _bare_answer_part(p, ans)]
        if len(kept) != len(parts):
            changed = True
            text = " ".join(kept).strip()
            if text:
                b["note"] = text
            else:
                b.pop("note")
    return changed


def mend(ann, answer):
    """Mend annotation `ann` (stored shape) in place; whether it changed."""
    if not isinstance(ann, dict) or ann.get("type") != ["cryptic_definition"]:
        return False
    ans = _bare(answer or ann.get("answer"))
    changed = False
    for b in ann.get("blocks") or []:
        if isinstance(b, dict):
            changed |= mend_block(b, ans)
    return changed


def blank_note_words(note, answer):
    """`note` with every whitespace-separated word that holds `answer`'s letters (letters only,
    4 or more) blanked to "...", or None when nothing holds them, when the letters only appear
    across a word join (not mendable by blanking a word), or when too little of the note is left
    to teach anything (under 4 words, or under 40% of its letters)."""
    ans = _bare(answer)
    if not isinstance(note, str) or len(ans) < 4 or ans not in _bare(note):
        return None
    words = note.split()
    out = [re.sub(r"[A-Za-z\u2019']+", "...", w) if ans in _bare(w) else w for w in words]
    new = " ".join(out)
    if new == note or ans in _bare(new):
        return None
    if len(_bare(new)) < 0.4 * len(_bare(note)) or sum(w != "..." for w in out) < 4:
        return None
    return new
