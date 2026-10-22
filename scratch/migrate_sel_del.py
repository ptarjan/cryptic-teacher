"""Rewrite a multi-letter first/last/middle pick from a synonym as the deletion it is.

    python3 scratch/migrate_sel_del.py            # count
    python3 scratch/migrate_sel_del.py --write    # rewrite in place
"""
import copy, json, os, re, sys, collections
sys.path.insert(0, "tools")
import annotation
import wordplay
import validate_annotations as V
from puzzle_paths import puzzle_files

L = wordplay.letters


def candidate(n):
    if not isinstance(n, dict) or n.get("op") not in ("first", "last", "middle") or n.get("unchecked"):
        return None
    parts = n.get("parts") or []
    if len(parts) != 1:
        return None
    p = parts[0]
    if not isinstance(p, dict) or "op" in p or p.get("select") or p.get("unchecked") or not p.get("gives"):
        return None
    said = [str(i.get("text") or "") for i in n.get("indicators") or [] if isinstance(i, dict)]
    if any(V._HALVING.search(t) and not V._NOT_A_HALVING.search(t) for t in said):
        return None  # a halving stays a selection (validate_annotations HALVED_AS_DELETION)
    w = p.get("words") or ""
    g = L(p["gives"])
    if g in (L(w), L(re.sub(r"['’]s\b", "", w))):
        return None
    return p


def walk(n, removed=False):
    """Every node, except one a deletion, substitution or move takes out or puts in:
    a selection there names letters, it is not a word that keeps them."""
    if isinstance(n, dict):
        if not removed:
            yield n
        for k, p in enumerate(n.get("parts") or []):
            yield from walk(p, removed or (k > 0 and n.get("op") in ("deletion", "substitution", "move")))


def answer_of(e):
    alt = e.get("alteration")
    return alt["from"] if isinstance(alt, dict) and alt.get("from") else e.get("solution")


def rewrite(n, p, pick):
    g = L(p["gives"])
    op = n["op"]
    if op == "first" and g.startswith(pick):
        removed = [g[len(pick):]]
    elif op == "last" and g.endswith(pick):
        removed = [g[:len(g) - len(pick)]]
    elif op == "middle" and (len(g) - len(pick)) % 2 == 0 and len(pick) < len(g):
        k = (len(g) - len(pick)) // 2
        if g[k:len(g) - k] != pick:
            return None
        removed = [g[:k], g[-k:]]
    else:
        return None
    new = {"op": "deletion"}
    for key, v in n.items():
        if key not in ("op", "parts", "n"):
            new[key] = v
    new["parts"] = [p] + [{"gives": r} for r in removed]
    return new


def fix_tree(tree, answer):
    got = wordplay.evaluate(tree, answer)
    subs = []
    for n in walk(tree):
        p = candidate(n)
        if p is None:
            continue
        pick = got.get(id(n))
        if not pick or len(pick) < 2 or len(pick) >= len(L(p["gives"])):
            continue
        new = rewrite(n, p, pick)
        if new:
            subs.append((n, new))
    for n, new in subs:
        if SHOW:
            SHOW.append(f"{wordplay.render(n)}  =>  {wordplay.render(new)}")
        n.clear()
        n.update(new)
    return len(subs)


SHOW = ["-"] if "--show" in sys.argv else []


def main():
    write = "--write" in sys.argv
    only = [a for a in sys.argv[1:] if not a.startswith("--")]
    stats = collections.Counter()
    files = []
    for f in puzzle_files():
        if only and not any(f.name.startswith(o + ".") for o in only):
            continue
        raw = f.read_text(encoding="utf-8")
        try:
            d = json.loads(raw)
        except Exception:
            continue
        changed = 0
        for e in d.get("entries", []):
            a = e.get("annotation")
            if not isinstance(a, dict) or not isinstance(a.get("wordplay"), dict):
                continue
            if not any(candidate(n) for n in walk(a["wordplay"])):
                continue
            before = copy.deepcopy(a)
            try:
                k = fix_tree(a["wordplay"], answer_of(e))
                if k:
                    annotation.view(a, e, d)
                    wordplay.evaluate(a["wordplay"], answer_of(e))
            except Exception as ex:
                e["annotation"] = before
                stats["error"] += 1
                print("ERR", f.name, e.get("number"), e.get("direction"), ex, file=sys.stderr)
                continue
            changed += k
        if changed:
            stats["nodes"] += changed
            stats["files"] += 1
            files.append(f)
            if write:
                part = f.with_name(f".{f.name}.part")
                part.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
                os.replace(part, f)
    print(stats)
    if SHOW:
        import random
        random.seed(1)
        for s in random.sample(SHOW[1:], 50):
            print(s)
    if "--list" in sys.argv:
        for f in files:
            print(f.stem)


main()
