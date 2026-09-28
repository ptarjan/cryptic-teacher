#!/usr/bin/env python3
"""Can fifteensquared / bigdave44 comments give a per-puzzle solver signal like TftT's?

Per blog and series: share of posts with >=1 / >=3 stated solve times, DNF and
needed-help mention rates, puzzles clearing the TftT bars (>=3 times; >=30
such puzzles per series), and BD44's reader star ratings ("3*/4*": first is
difficulty). Validation: per-puzzle rho of each signal against score()'s clue
index within series, and series medians for the gentle-series ordering.

Reads the fifteensquared comment cache and the bigdave44 sample from
scratch/blog_solve_times_fetch.py.
"""
import html, json, re, statistics, sys
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from blog_comment_difficulty import MINUTES, DNF  # noqa: E402
from fetch_puzzle import read_puzzle_file  # noqa: E402
import difficulty as D  # noqa: E402

FS = Path.home() / "cryptic-setter-data/fifteensquared"
BD = Path.home() / ".cache/blog_solve_times/bigdave44"
BLOGGER = re.compile(r"Difficulty\W{0,6}?([*★](?:\s*[*★]){0,4})\s*(½)?")
TAG = re.compile(r"<[^>]+>")
HELP = re.compile(r"\bneeded (?:some |a lot of |lots of )?help\b|\bhad to (?:use|resort|look|check|google)|"
                  r"\bresort(?:ed)? to\b|\bcheck (?:button|function)|\bcheat|\breveal|\bgave up\b|"
                  r"\bDNF\b|\bdefeated\b|\bbeat me\b|\bwith (?:the )?(?:help|hints)\b|\bneeded (?:the )?hints?\b|"
                  r"\belectronic (?:help|assistance)|\bword ?finder|\bgoogl", re.I)
STAR = re.compile(r"(?<![\d/.*])(\d(?:\.5)?)\s*\*\s*/\s*\d(?:\.5)?\s*\*|(?<![*\w])(\*{1,5})\s*/\s*\*{1,5}(?!\*)")


def text(r):
    return html.unescape(TAG.sub(" ", r["content"]["rendered"]))


def stats(comments):
    times, dnf, helped, stars = [], 0, 0, []
    for c in comments:
        m = MINUTES.search(c)
        if m and 2 <= float(m.group(1)) <= 240:
            times.append(float(m.group(1)))
        dnf += bool(DNF.search(c))
        helped += bool(HELP.search(c))
        s = STAR.search(c)
        if s:
            v = float(s.group(1)) if s.group(1) else len(s.group(2))
            if 0.5 <= v <= 5:
                stars.append(v)
    return {"n": len(comments), "times": times, "dnf": dnf, "help": helped, "stars": stars}


def load():
    out = {}  # pid -> stats
    link = {}
    ids = json.loads((FS / "by_puzzle.json").read_text())["ids"]
    for pid, posts in ids.items() if "BD_ONLY" not in __import__("os").environ else ():
        rows = []
        for p in posts:
            f = FS / f"comments/{p}.json"
            if f.exists():
                rows += json.loads(f.read_text())
        if any((FS / f"comments/{p}.json").exists() for p in posts):
            out[("fifteensquared", pid)] = stats([text(r) for r in rows])
    sample = json.loads((BD / "sample.json").read_text())
    for pid, post in sample.items():
        f = BD / f"{post}.json"
        if f.exists():
            out[("bigdave44", pid)] = st = stats([text(r) for r in json.loads(f.read_text())])
            post_f = Path.home() / f"cryptic-setter-data/bigdave44/posts/{post}.json"
            m = BLOGGER.search(text(json.loads(post_f.read_text())))
            st["blogger"] = sum(c in "*★" for c in m.group(1)) + 0.5 * bool(m.group(2)) if m else None
    return out


def rho(pairs):
    if len(pairs) < 15:
        return f"n={len(pairs)}"
    a, b = zip(*pairs)
    return f"{D._spearman(list(a), list(b)):+.2f} (n={len(pairs)})"


def main():
    data = load()
    ctx = D.context()
    by = defaultdict(list)
    for (blog, pid), s in data.items():
        by[(blog, pid.rpartition("-")[0])].append((pid, s))
    print(f"{'blog':15s} {'series':12s} {'posts':>5s} {'medC':>4s} {'>=1t':>5s} {'>=3t':>5s} "
          f"{'dnf%':>5s} {'help%':>5s} {'>=3star':>7s}  | index rho: dnf-share help-share median-star  median-min")
    series_rows = {}
    for (blog, series), rows in sorted(by.items()):
        rows = [r for r in rows if r[1]["n"] > 0]
        if len(rows) < 10:
            continue
        n = len(rows)
        t1 = sum(len(s["times"]) >= 1 for _, s in rows)
        t3 = [(p, s) for p, s in rows if len(s["times"]) >= 3]
        s3 = [(p, s) for p, s in rows if len(s["stars"]) >= 3]
        comm = sum(s["n"] for _, s in rows)
        dnf = sum(s["dnf"] for _, s in rows) / comm
        hlp = sum(s["help"] for _, s in rows) / comm
        idx = {}
        for p, s in rows:
            path = ROOT / "puzzles" / f"{p}.json"
            if path.exists():
                sc = D.score(read_puzzle_file(path), ctx)
                if sc:
                    idx[p] = sc["index"]
        big = [(p, s) for p, s in rows if s["n"] >= 10 and p in idx]
        r_dnf = rho([(s["dnf"] / s["n"], idx[p]) for p, s in big])
        r_help = rho([(s["help"] / s["n"], idx[p]) for p, s in big])
        r_star = rho([(statistics.median(s["stars"]), idx[p]) for p, s in s3 if p in idx])
        r_min = rho([(statistics.median(s["times"]), idx[p]) for p, s in t3 if p in idx])
        print(f"{blog:15s} {series:12s} {n:5d} {statistics.median(s['n'] for _, s in rows):4.0f} "
              f"{t1 / n:5.1%} {len(t3) / n:5.1%} {dnf:5.1%} {hlp:5.1%} {len(s3):7d}  | "
              f"{r_dnf:14s} {r_help:14s} {r_star:14s} {r_min}")
        if blog == "bigdave44":
            bl = [(p, s) for p, s in rows if s.get("blogger")]
            print(f"    blogger rating on {len(bl)}: comment-star vs blogger "
                  f"{rho([(statistics.median(s['stars']), s['blogger']) for p, s in s3 if s.get('blogger')])}; "
                  f"blogger vs index {rho([(s['blogger'], idx[p]) for p, s in bl if p in idx])}; "
                  f"help-share vs blogger {rho([(s['help'] / s['n'], s['blogger']) for p, s in bl if s['n'] >= 10])}; "
                  f"dnf-share vs blogger {rho([(s['dnf'] / s['n'], s['blogger']) for p, s in bl if s['n'] >= 10])}; "
                  f"median blogger {statistics.median(s['blogger'] for p, s in bl) if bl else None}")
        series_rows[(blog, series)] = {
            "help_share": statistics.median(s["help"] / s["n"] for _, s in big) if big else None,
            "dnf_share": statistics.median(s["dnf"] / s["n"] for _, s in big) if big else None,
            "star": statistics.median(statistics.median(s["stars"]) for _, s in s3) if s3 else None,
            "minutes": statistics.median(statistics.median(s["times"]) for _, s in t3) if t3 else None,
            "index": statistics.median(idx.values()) if idx else None, "big": len(big)}
    print("\nseries medians (posts with 10+ comments for shares; >=3 ratings for stars):")
    for k, v in series_rows.items():
        print(f"  {k[0]:15s} {k[1]:12s} " + "  ".join(
            f"{a}={v[a]:.3f}" if isinstance(v[a], float) else f"{a}={v[a]}" for a in v))


main()
