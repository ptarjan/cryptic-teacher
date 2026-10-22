import sys, re, json, collections
sys.path.insert(0, "tools")
from puzzle_paths import puzzle_files
L = lambda s: re.sub(r"[^A-Za-z]", "", str(s or "")).upper()
c = collections.Counter()
ex = collections.defaultdict(list)


def walk(n, f):
    if not isinstance(n, dict):
        return
    if n.get("op") == "deletion":
        ps = n.get("parts") or []
        p = ps[0] if ps else {}
        if isinstance(p, dict) and "op" not in p and p.get("gives") and L(p["gives"]) != L(p.get("words")):
            rest = [L(q.get("gives")) for q in ps[1:] if isinstance(q, dict)]
            g = L(p["gives"])
            kind = "other"
            if len(rest) == 1 and rest[0]:
                r = rest[0]
                if g.startswith(r): kind = "head"
                elif g.endswith(r): kind = "tail"
                elif len(r) == 2 and g[0] == r[0] and g[-1] == r[1]: kind = "ends"
            elif len(rest) == 2 and rest[0] == g[:1] and rest[1] == g[-1:]:
                kind = "ends2"
            elif not rest:
                kind = "nopart"
            c[kind] += 1
            if len(ex[kind]) < 3:
                ex[kind].append((f.name, json.dumps(n)[:300]))
    for p in n.get("parts") or []:
        walk(p, f)


for f in puzzle_files():
    try:
        d = json.load(open(f))
    except Exception:
        continue
    for e in d.get("entries", []):
        a = e.get("annotation")
        if isinstance(a, dict):
            walk(a.get("wordplay"), f)
print(c)
for k, v in ex.items():
    print(k)
    for x in v:
        print("  ", *x)
