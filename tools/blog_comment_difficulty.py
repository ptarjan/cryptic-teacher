#!/usr/bin/env python3
"""Which clues human solvers found hard, read off Times for the Times comments.

Readers there write answers in capitals and say which one was their last in
(LOI), which they failed on, and how long the puzzle took them. For every
puzzle whose post tools/blog_facts.py has joined, this counts, per clue, the
comments that name its answer in capitals, the ones that name it next to a
cue that the clue held them up (LOI, DNF, stuck, biffed, never heard of...),
and the ones that name it straight after LOI; and per puzzle the median of
the solve times the commenters state.

    python3 tools/blog_comment_difficulty.py            # write tools/data/blog_comment_difficulty.json
    python3 tools/blog_comment_difficulty.py --measure  # and print coverage and the checks against SNITCH

Rerun as tools/fetch_wp_blog.py --comments lands more months; it reads only
the caches under ~/cryptic-setter-data and rebuilds the whole table.
"""
import argparse
import html
import json
import math
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from blog_facts import DATA  # noqa: E402
from fetch_puzzle import read_puzzle_file  # noqa: E402
import puzzle_paths  # noqa: E402
from groups import entry_id  # noqa: E402

BLOG = DATA / "timesforthetimes"
OUT = ROOT / "tools/data/blog_comment_difficulty.json"
SERIES = ("times", "sundaytimes", "timesquick", "timesjumbo")

TAG = re.compile(r"<[^>]+>")
SENTENCE = re.compile(r"(?<=[.!?;])\s+|\n+")
#: A sentence with one of these in it says the answers it names held its
#: writer up.
HARD = re.compile(
    r"\bLOI\b|\blast (?:one )?in\b|\bDNF\b|\bstuck\b|\bheld (?:me )?up\b|"
    r"\bhold-?up\b|\bbeat me\b|\bfailed\b|\bcouldn.?t\b|\bno idea\b|"
    r"\bnever heard\b|\bdidn.?t know\b|\bunknown\b|\bbiff|\bdefeated\b|"
    r"\bgave up\b|\bresort(?:ed)? to\b|\breveal|\bcheat|\baids?\b|"
    r"\btook (?:me )?(?:ages|a while|forever)\b|\bstruggl", re.I)
LOI = re.compile(r"\bLOI\b|\blast (?:one )?in\b", re.I)
#: A comment with one of these in it says its writer did not finish.
DNF = re.compile(r"\bDNF\b|\bfailed\b|\bgave up\b|\bdefeated\b|\bbeat me\b|"
                 r"\breveal|\bcheat", re.I)
#: What may sit between LOI and the answer it names: "LOI: X", "LOI was X".
LEAD = re.compile(r"[\s:,\-–]*(?:(?:was|is|being|had to be)\s+)?", re.I)
#: "12 minutes", "25 mins", "40m". Hours and h:mm are left alone: "1:05" is as
#: often a clock time as a solve time.
MINUTES = re.compile(r"\b(\d{1,3}(?:\.\d+)?)\s*(?:minutes|mins?\b|m\b)", re.I)


def text(rendered):
    return html.unescape(TAG.sub(" ", rendered))


def answer_regex(solution):
    """The answer as a reader types it in capitals: THROW A WOBBLY, THROW-A-WOBBLY."""
    letters = [re.escape(c) for c in solution.upper() if c.isalpha()]
    return re.compile(r"(?<![A-Za-z])" + r"[\s\-']?".join(letters) + r"(?![A-Za-z])")


def comments_by_post():
    by = defaultdict(list)
    for f in sorted((BLOG / "comments").glob("????-??.json")):
        for row in json.loads(f.read_text(encoding="utf-8")):
            by[row["post"]].append(text(row["content"]["rendered"]))
    return by


def post_ids():
    ids = {}
    for f in (BLOG / "posts").glob("*.json"):
        p = json.loads(f.read_text(encoding="utf-8"))
        ids[p["link"].rstrip("/")] = p["id"]
    return ids


def score(puz, comments):
    answers = [(entry_id(e), answer_regex(e["solution"])) for e in puz["entries"]
               if sum(c.isalpha() for c in e.get("solution") or "") >= 3]
    clues, times, dnf = {}, [], 0
    lower = {eid: re.compile(rx.pattern, re.I) for eid, rx in answers}
    for c in comments:
        m = MINUTES.search(c)
        if m and 2 <= float(m.group(1)) <= 240:
            times.append(float(m.group(1)))
        dnf += bool(DNF.search(c))
        sentences = SENTENCE.split(c)
        for eid, rx in answers:
            hits = [s for s in sentences if rx.search(s)]
            if not hits:
                continue
            row = clues.setdefault(eid, [0, 0, 0])
            row[0] += 1
            row[1] += any(HARD.search(s) for s in hits)
        for eid in loi(c, answers, lower):
            clues.setdefault(eid, [1, 1, 0])[2] += 1
    return clues, times, dnf


def loi(comment, answers, lower):
    """The clue a comment names as its last one in: the first answer after LOI
    in its sentence, within 40 characters, in capitals, or in any case when it
    follows at once ("LOI apophthegm", "my LOI was agape"). "LOI after X" names the one before it,
    which the comment does not spell, so it credits nothing."""
    found = set()
    for s in SENTENCE.split(comment):
        for lm in LOI.finditer(s):
            at = LEAD.match(s, lm.end()).end()
            best = None
            for eid, rx in answers:
                am = rx.search(s, lm.end()) or lower[eid].match(s, at)
                if am and am.start() - lm.end() <= 40 and (best is None or am.start() < best[0]):
                    best = (am.start(), eid)
            if best and not re.search(r"\b(?:after|before)\b", s[lm.end():best[0]], re.I):
                found.add(best[1])
    return found


def build():
    by_post, ids = comments_by_post(), post_ids()
    table = {}
    for series in SERIES:
        facts = ROOT / f"tools/data/blog_facts/{series}.json"
        if not facts.exists():
            continue
        for pid, v in json.loads(facts.read_text()).items():
            if v.get("blog") != "timesforthetimes":
                continue
            post = ids.get(v["url"].rstrip("/"))
            comments = by_post.get(post)
            path = puzzle_paths.find(pid)
            if not comments or path is None:
                continue
            clues, times, dnf = score(read_puzzle_file(path), comments)
            table[pid] = {"comments": len(comments), "dnf": dnf,
                          "median_minutes": statistics.median(times) if times else None,
                          "stated_times": len(times),
                          "clues": clues}
    return table


def rho(a, b):
    import difficulty as D
    r = D._spearman(list(a), list(b))
    return r, len(a), math.erfc(abs(r) * math.sqrt(len(a) - 1) / math.sqrt(2))


def measure(table):
    months = sorted(p.stem for p in (BLOG / "comments").glob("????-??.json"))
    print(f"comment months on disk: {len(months)} ({months[0]}..{months[-1]})")
    print(f"puzzles with comments: {len(table)}; "
          f"median comments each: {statistics.median(v['comments'] for v in table.values())}")
    named = [n for v in table.values() for n in v["clues"].values()]
    print(f"clues named at all: {len(named)}; flagged hard: {sum(1 for n in named if n[1])}; "
          f"as LOI: {sum(1 for n in named if n[2])}")
    sn = json.loads((ROOT / "tools/data/snitch.json").read_text())
    both = [(v["median_minutes"], sn[k]["nitch"]) for k, v in table.items()
            if k in sn and v["median_minutes"] is not None and v["stated_times"] >= 3]
    if len(both) >= 20:
        r, n, p = rho(*zip(*both))
        print(f"median stated minutes vs SNITCH: rho {r:+.3f} (n={n}, p={p:.3g})")
    else:
        print(f"median stated minutes vs SNITCH: only {len(both)} puzzles overlap so far")


def per_puzzle(table):
    """Per Times daily: the share of comments that say DNF, and the share of
    answer mentions a hard cue sits beside, against our index and the SNITCH
    (raw, and minus its weekday mean, which the editorial ramp sets)."""
    from datetime import date

    import difficulty as D
    ctx, sn = D.context(), D.load_snitch()
    by_day = D.snitch_by_day(sn)
    rows = []
    for pid, v in table.items():
        if pid.rpartition("-")[0] != "times" or v["comments"] < 10:
            continue
        named = list(v["clues"].values())
        s = D.score(read_puzzle_file(puzzle_paths.find(pid)), ctx)
        nitch = sn.get(pid, {}).get("nitch")
        resid = nitch - by_day[date.fromisoformat(sn[pid]["date"]).weekday()] if nitch is not None else None
        rows.append({"dnf": v["dnf"] / v["comments"],
                     "hard": sum(n[1] for n in named) / max(1, sum(n[0] for n in named)),
                     "minutes": v["median_minutes"] if v["stated_times"] >= 3 else None,
                     "index": s["index"] if s else None, "nitch": nitch, "resid": resid})
    print(f"per puzzle, Times daily with 10+ comments ({len(rows)}):")
    for x in ("dnf", "hard", "minutes"):
        for y in ("index", "nitch", "resid"):
            pairs = [(r[x], r[y]) for r in rows if r[x] is not None and r[y] is not None]
            if len(pairs) >= 20:
                r, n, p = rho(*zip(*pairs))
                print(f"  {x:7s} vs {y:5s} rho {r:+.3f} (n={n}, p={p:.3g})")


def per_clue(table):
    """Within each annotated puzzle, which clues did the comments flag hard,
    against our per-clue wordplay cost and the answer's rarity. Ranked inside
    the puzzle so that a puzzle's comment count and its overall difficulty
    cancel out."""
    import difficulty as D
    rank = D.ranks()
    cols = defaultdict(list)
    puzzles = 0
    for pid, v in table.items():
        puz = read_puzzle_file(puzzle_paths.find(pid))
        if not D.puzzle_is_annotated(puz):
            continue
        rows = []
        for e in puz["entries"]:
            cost, ops = D.clue_cost(e), D.clue_machinery(e)
            words = (e.get("solution") or "").upper().split() or [""]
            rare = math.log10(max(max(rank.get(w, D.MISSING_RANK) for w in words), 10))
            n = v["clues"].get(entry_id(e), [0, 0, 0])
            if cost is not None:
                rows.append((cost, ops, rare, e["length"], n[1], n[2]))
        if len(rows) < 10:
            continue
        puzzles += 1
        for i, name in enumerate(("cost", "machinery", "rarity", "length", "hard", "loi")):
            cols[name] += [x - 0.5 for x in _pct([r[i] for r in rows])]
    if puzzles < 20:
        print(f"per clue: only {puzzles} annotated puzzles have comments on disk so far")
        return
    print(f"per clue, within {puzzles} annotated puzzles ({len(cols['hard'])} clues):")
    for x in ("cost", "machinery", "rarity", "length"):
        for y in ("hard", "loi"):
            r, n, p = rho(cols[x], cols[y])
            print(f"  {x:9s} vs {y:4s} rho {r:+.3f} (p={p:.3g})")


def _pct(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 / max(1, len(xs) - 1)
        i = j + 1
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--measure", action="store_true")
    a = ap.parse_args()
    table = build()
    # With no comment cache on disk (a fresh checkout, a moved volume) build()
    # finds nothing, and writing that would replace the committed table with {}.
    if not table:
        print(f"no Times for the Times comments under {BLOG}; {OUT.relative_to(ROOT)} left as it was",
              file=sys.stderr)
        return 1
    OUT.write_text(json.dumps(table, sort_keys=True, separators=(",", ":")) + "\n")
    print(f"wrote {len(table)} puzzles to {OUT.relative_to(ROOT)}")
    if a.measure:
        measure(table)
        per_puzzle(table)
        per_clue(table)


if __name__ == "__main__":
    raise SystemExit(main())
