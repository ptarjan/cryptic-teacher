"""Mend an anagram whose fodder carries one link word too many.

The annotate runs' 'wordplay does not give the answer' refusals on 11-16 included
`ana<smashing>([Lion] + [and] + [ape])` for OPALINE, `ana<disaster>([a real])` for EARL and
`ana<broken>([the leg rotten])` for LORGNETTE: the fodder is the right words plus a link word
('and', 'a', 'the') at the start, the end or between two pieces. The evaluator even says so
("the fodder has ADN to spare"). When dropping exactly one such word makes the fodder an anagram
of the answer, and no other single word does, the word is dropped here: the fodder was wrong
only by a word the clue uses as a link, which is unambiguous.

Only a bare fodder (leaves with clue words and no letters of their own, joined as a charade or a
single multi-word leaf), only a whole word, and only an edge word of a multi-word leaf (an interior
word would split the leaf), so the tree stays a valid located tree. wordplay.translate keeps the
change only when the tree then gives the answer.
"""
import re


def _bare_words(part):
    return ("op" not in part and part.get("words") and not part.get("gives")
            and not part.get("unchecked") and "at" in part)


def _candidates(parts):
    """[(part index, 'whole'|'first'|'last')] for each word that could go."""
    out = []
    for i, p in enumerate(parts):
        n = len(p["words"].split())
        if n == 1:
            out.append((i, "whole"))
        else:
            out += [(i, "first"), (i, "last")]
    return out


def _letters(s):
    return "".join(sorted(re.sub(r"[^A-Z]", "", s.upper())))


def drop_surplus_fodder_word(tree, answer):
    """Number of anagram fodders changed (0 or more) in `tree`, in place."""
    want = _letters(answer)
    changed = 0
    stack = [tree]
    while stack:
        node = stack.pop()
        stack.extend(node.get("parts") or [])
        if node.get("op") != "anagram":
            continue
        parts = node.get("parts") or []
        if not parts or not all(_bare_words(p) for p in parts):
            continue
        have = _letters("".join(p["words"] for p in parts))
        if have == want or len(have) <= len(want):
            continue
        hits = [(i, how) for i, how in _candidates(parts) if _only_words(parts, i, how, want)]
        if len(hits) != 1:
            continue
        i, how = hits[0]
        p = parts[i]
        if how == "whole":
            if len(parts) == 1:
                continue
            del parts[i]
        else:
            if how == "first":
                cut = re.match(r"\s*\S+\s*", p["words"]).end()
                p["words"], p["at"] = p["words"][cut:], p["at"] + cut
            else:
                p["words"] = re.sub(r"\s*\S+\s*$", "", p["words"])
        changed += 1
    return changed


def _only_words(parts, i, how, want):
    """The fodder left after dropping that word, letters sorted, equals the answer's."""
    left = []
    for j, p in enumerate(parts):
        ws = p["words"].split()
        if j == i:
            ws = ws[1:] if how == "first" else ws[:-1] if how == "last" else []
        left.append("".join(ws))
    return _letters("".join(left)) == want
