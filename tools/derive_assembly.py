"""An annotation's `assembly`, worked out from its blocks.

The blocks already hand over the wordplay's letters in the order they are
assembled, so for most clues the rebuild is a search, not something a model
has to retype: concatenation always, and a reversal, one piece put inside
another, or an anagram of a run of blocks where the entry's `type` names that
operation. `complete(ann, entry)` fills in the assembly where it is missing,
and redoes `pieces` that hold the right letters in the wrong order.
"""
import copy
import functools

from annotation import _letters, assembly, whole_anagram, wordplay_letters

# Types whose answer is not built from block letters; their assembly is absent.
NOTHING_TO_BUILD = {"hidden_word", "double_definition", "cryptic_definition", "homophone"}
# Types that build by concatenation alone outside an anagram's fodder.
STRUCTURAL = {"charade", "container", "reversal"}


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


KINDS = ("reversal", "container", "anagram")
# Lettered blocks beyond which the search is not tried: it grows with their
# count, and no clue's wordplay has this many parts.
MAX_BLOCKS = 12


def search(gives, want, types, limits=None):
    """The best build of `want` from the strings `gives`, in their order, or
    None: a dict of pieces, reversals and anagrams. Every operation keeps the
    letter count, so a run of blocks always rebuilds a run of `want` as long as
    its own letters. `limits` caps each of KINDS (each needs an indicator in
    the clue), one apiece by default; a kind `types` does not name is never
    used, and one it names has to be: blocks that already give the reversed
    or shuffled letters leave that step unsaid, so they are no build."""
    gives = tuple(gives)
    cap = tuple((limits or {}).get(k, 1) if k in types else 0 for k in KINDS)
    starts = [0]
    for g in gives:
        starts.append(starts[-1] + len(g))
    size = lambda i, j: starts[j] - starts[i]
    bag = [["".join(sorted("".join(gives[i:j]))) for j in range(len(gives) + 1)]
           for i in range(len(gives) + 1)]

    def add(found, used, build):
        """Keep `build` if within the caps and the fewest letters shuffled for
        its count of each kind."""
        if all(u <= c for u, c in zip(used, cap)) and (
                used not in found or build[0] < found[used][0]):
            found[used] = build

    def join(a, b):
        """Every pairing of the builds in a and b, side by side."""
        for ua, (sa, pa, ra, na) in a.items():
            for ub, (sb, pb, rb, nb) in b.items():
                yield tuple(x + y for x, y in zip(ua, ub)), (sa + sb, pa, pb, ra + rb, na + nb)

    @functools.cache
    def best(i, j, t, may_reverse=True):
        """{(reversals, insertions, anagrams): (letters shuffled, pieces,
        reversals, anagrams)} building t from gives[i:j]. A reversal turns
        round letters that read differently backwards, and nothing inside it
        is reversed again."""
        found = {}
        if bag[i][j] != "".join(sorted(t)):
            return found
        if j - i == 1 and gives[i] == t:
            add(found, (0, 0, 0), (0, (t,), (), ()))
        for k in range(i + 1, j):
            p = size(i, k)
            for used, (sh, pa, pb, rs, ns) in join(best(i, k, t[:p], may_reverse),
                                                    best(k, j, t[p:], may_reverse)):
                add(found, used, (sh, pa + pb, rs, ns))
        if cap[0] and may_reverse and t != t[::-1]:
            for (r, b, m), (sh, ps, rs, ns) in best(i, j, t[::-1], False).items():
                add(found, (r + 1, b, m), (sh, tuple(p[::-1] for p in reversed(ps)),
                                           rs + ((t[::-1], t),), ns))
        if cap[2]:
            fodder = "".join(gives[i:j])
            if fodder != t:
                add(found, (0, 0, 1), (len(t), (t,), (), ((" ".join(gives[i:j]), t),)))
        if cap[1]:
            for k in range(i + 1, j):
                for (oi, oj), (ii, ij) in (((i, k), (k, j)), ((k, j), (i, k))):
                    n = size(ii, ij)
                    for at in range(1, size(oi, oj)):
                        outer = best(oi, oj, t[:at] + t[at + n:], may_reverse)
                        if not outer:
                            continue
                        inner = best(ii, ij, t[at:at + n], may_reverse)
                        for (r, b, m), (sh, po, pi, rs, ns) in join(outer, inner):
                            head, tail = _cut(po, at)
                            add(found, (r, b + 1, m), (sh, tuple(head) + pi + tuple(tail), rs, ns))
        return found

    if not gives or len(gives) > MAX_BLOCKS or bag[0][len(gives)] != "".join(sorted(want)):
        return None
    if cap[2] and not set(types) & STRUCTURAL:
        # A bare anagram shuffles every block, even one already in place.
        if "".join(gives) == want:
            return None
        return {"anagrams": [{"fodder": " ".join(gives), "gives": want}]}
    builds = [(used, b) for used, b in best(0, len(gives), want).items()
              if all(u or not c for u, c in zip(used, cap))]
    if not builds:
        return None
    # The fewest letters shuffled (HO(SEPI)PE, not all of HOPE+PIES), then the
    # fewest steps.
    _, (_, pieces, revs, anas) = min(builds, key=lambda ub: (ub[1][0], sum(ub[0])))
    out = {"pieces": list(pieces)}
    if revs:
        out["reversals"] = [{"from": f, "to": t} for f, t in revs]
    if anas:
        out["anagrams"] = [{"fodder": f, "gives": g} for f, g in anas]
        if len(pieces) == 1:
            del out["pieces"]
    return out


def derive(ann, entry=None):
    """The assembly the blocks and `type` reach, or None."""
    if not isinstance(ann, dict) or not isinstance(ann.get("type"), list):
        return None
    if NOTHING_TO_BUILD & set(ann["type"]):
        return None
    gives = [_letters(b.get("gives")) for b in ann.get("blocks") or [] if isinstance(b, dict)]
    signals = [i.get("for") for i in ann.get("indicators") or [] if isinstance(i, dict)]
    limits = {k: max(1, signals.count(k)) + signals.count(None) for k in KINDS}
    return search([g for g in gives if g], wordplay_letters(ann, entry), ann["type"], limits)


def complete(ann, entry=None):
    """`ann` with its assembly derived where the blocks reach it: filled in when
    there are no pieces and no whole-answer anagram, and `pieces` redone when
    they hold the answer's letters in the wrong order. A key the annotation
    already has is kept. Returns a new dict, or `ann` itself when nothing
    changed; a failed search changes nothing, and the blocks' own check
    reports why."""
    if not isinstance(ann, dict):
        return ann
    build = assembly(ann)
    pieces = build.get("pieces")
    want = wordplay_letters(ann, entry)
    if isinstance(pieces, list) and pieces:
        joined = _letters("".join(map(str, pieces)))
        if joined == want or sorted(joined) != sorted(want):
            return ann
    elif whole_anagram(ann, entry):
        return ann
    found = derive(ann, entry)
    if not found:
        return ann
    out = copy.deepcopy(ann)
    merged = dict(assembly(out))
    if "pieces" in found:
        merged["pieces"] = found["pieces"]
    else:
        merged.pop("pieces", None)
    for key in ("reversals", "anagrams"):
        if key in found and not merged.get(key):
            merged[key] = found[key]
    out["assembly"] = merged
    return out
