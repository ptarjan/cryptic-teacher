"""Mechanical mends for a pure cryptic definition's blocks (validate_answers.
check_cryptic_definition_blocks), so the first check does not spend a model turn on them.

A cryptic definition has no wordplay, so a block's `gives` is only ever the whole
answer wearing a block's clothes: it is dropped. Text in it that is not the answer
moves into the block's `note`, unless that would spell the answer. A note that is
nothing but the answer ("= WATCHSTRAP", "the answer is WATCHSTRAP") is stripped.
Anything subtler (a definition that hides the answer, a note that works the answer
into a sentence) is the model's to retype or reword."""
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
