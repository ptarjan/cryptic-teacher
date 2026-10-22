import sys, re, json
sys.path.insert(0, "tools")
from puzzle_paths import puzzle_files
from wordplay import SELECT
L = lambda s: re.sub(r"[^A-Za-z]", "", str(s or "")).upper()


def walk(n, f, tag, out):
    if not isinstance(n, dict):
        return
    if n.get("op") in SELECT:
        for p in n.get("parts") or []:
            if isinstance(p, dict) and "op" not in p and p.get("gives"):
                w = p.get("words", "")
                if L(p["gives"]) not in (L(w), L(re.sub(r"['’]s\b", "", w))):
                    out.append((f.name, tag, n["op"], w, p["gives"], len(L(p["gives"]))))
    for p in n.get("parts") or []:
        walk(p, f, tag, out)


out = []
for f in puzzle_files():
    try:
        d = json.load(open(f))
    except Exception:
        continue
    for e in d.get("entries", []):
        a = e.get("annotation")
        if isinstance(a, dict):
            walk(a.get("wordplay"), f, f"{e.get('number')}{str(e.get('direction','?'))[0]} {a.get('answer')}", out)
import collections
if "--count" in sys.argv:
    c = collections.Counter((o[2], o[5] == 1) for o in out)
    for k, v in c.most_common():
        print(v, k)
    sys.exit()
for o in out:
    print(*o, sep=" | ")
print(len(out), file=sys.stderr)
