"""Per clue: are '?' clues, anagram clues, long answers flagged hard / LOI more often, within puzzle?"""
import json, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import difficulty as D
ENUM = re.compile(r"\s*\([\d,.\s\-–']+\)\s*$")
cmt = json.loads((ROOT / "tools/data/blog_comment_difficulty.json").read_text())
stats = {}
def add(k, flag, m):
    s = stats.setdefault(k, {True: [0, 0, 0, 0], False: [0, 0, 0, 0]})[flag]
    s[0] += 1; s[1] += m[0] > 0; s[2] += m[1] > 0; s[3] += m[2] > 0
np_ = 0
for pid, v in cmt.items():
    if v.get("comments", 0) < 10: continue
    p = ROOT / "puzzles" / f"{pid}.json"
    if not p.exists(): continue
    puz = D.read_puzzle_file(p)
    np_ += 1
    for e in puz["entries"]:
        c = ENUM.sub("", e.get("clue") or "").strip()
        if not c or re.match(r"(?i)^see\b", c): continue
        m = v["clues"].get(e["id"], [0, 0, 0])
        t = [x.strip().lower() for x in ((e.get("annotation") or {}).get("type") or "").split("+") if x.strip()]
        add("qmark", c.endswith("?"), m)
        add("excl", c.endswith("!"), m)
        if t:
            add("anagram(typed)", "anagram" in t, m)
            add("defonly(typed)", set(t) <= {"double definition", "cryptic definition", "&lit"}, m)
        add("len>=12", e["length"] >= 12, m)
        add("phrase", bool(e.get("separatorLocations")), m)
print("puzzles", np_)
print(f"{'feature':16s} {'flag':5s} {'n':>6s} {'named':>6s} {'hard':>6s} {'loi':>6s}")
for k, d in stats.items():
    for f in (True, False):
        n, a, h, l = d[f]
        print(f"{k:16s} {str(f):5s} {n:6d} {a/n:6.3f} {h/n:6.3f} {l/n:6.3f}")
