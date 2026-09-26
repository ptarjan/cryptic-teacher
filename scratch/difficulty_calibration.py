#!/usr/bin/env python3
"""Measure external difficulty signals against tools/difficulty.py's index.

  python3 scratch/difficulty_calibration.py times    # TftT blogger minutes
  python3 scratch/difficulty_calibration.py bd44     # bigdave44 stars

Read-only: reads the blog caches and the difficulty.py output in
scratch/diff_all.txt (python3 tools/difficulty.py > scratch/diff_all.txt).
"""
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path.home() / "cryptic-setter-data"
sys.path.insert(0, str(ROOT / "tools"))


def index_table():
    out = {}
    for line in (ROOT / "scratch" / "diff_all.txt").read_text().splitlines()[1:]:
        f = line.split()
        out[f[0]] = float(f[1])
    return out


def ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2
        i = j + 1
    return r


def pearson(a, b):
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    sa = sum((x - ma) ** 2 for x in a) ** .5
    sb = sum((y - mb) ** 2 for y in b) ** .5
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sa * sb) if sa and sb else float("nan")


def spearman(a, b):
    return pearson(ranks(a), ranks(b))


def perm_p(a, b, trials=5000):
    import random
    rnd = random.Random(1)
    obs = abs(spearman(a, b))
    ra, rb = ranks(a), ranks(b)
    rb = list(rb)
    hit = 0
    for _ in range(trials):
        rnd.shuffle(rb)
        if abs(pearson(ra, rb)) >= obs:
            hit += 1
    return (hit + 1) / (trials + 1)


def text_of(field):
    s = field.get("rendered", "") if isinstance(field, dict) else (field or "")
    s = re.sub(r"<(br|p|div|li|tr|h\d)[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return html.unescape(s).replace("\xa0", " ")


# --- Times for the Times -------------------------------------------------

NUMWORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}
NUMWORDS.update({"thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "a": 1, "an": 1})
NUM = r"(\d{1,3}(?:\.\d)?|(?:twenty|thirty|forty|fifty)[- ](?:one|two|three|four|five|six|seven|eight|nine)|" \
      + "|".join(sorted((w for w in NUMWORDS if w not in ("a", "an", "zero")), key=len, reverse=True)) + ")"
# h:mm:ss, mm:ss, mm.ss, 15' 15"
CLOCK = re.compile(r"(?<![\d:.£$])(?:(\d):)?(\d{1,3})(?::|\.(?=\d\d\b)|[’']\s*)(\d{2})(?:\s*[”\"])?(?![\d:]|\s*(?:am|pm|%|p\.m|a\.m))", re.I)
MINUTES = re.compile(r"(?<![\d.:])" + NUM + r"\s*(?:-\s*)?(?:minutes?|mins?|m)\b(?!\s*(?:longer|shorter|quicker|faster|slower|more|less|over my|behind|ahead|outside|inside|of (?:the|my) (?:hour|time)))", re.I)
HOURS = re.compile(r"\b(?:(half) an hour|(an?|one|two|three|\d(?:\.\d)?)\s+(?:and\s+(?:a\s+)?(half|quarter)\s+)?hours?|(an?|one|two|three)\s+and\s+a\s+(half|quarter)\s+hours?|(an?|one|two|three)\s+hours?\s+and\s+" + NUM + r"\s+min)", re.I)
CUE = re.compile(r"(?i)\b(time|timer|clock|took|taken|taking|me\b|my\b|i\b|solv|finish|complet|done|in\s|at\s|for\s|under|over|about|around|needed|spent|occupied)")
OTHERS = re.compile(r"(?i)leaderboard|\b100\s*th|fastest|best time|top solvers|the average|median")
DNF = re.compile(r"\bDNF\b|did not finish|didn.t finish|\bfailed to finish", re.I)


def _num(tok):
    tok = tok.lower().replace("-", " ")
    if tok in NUMWORDS:
        return NUMWORDS[tok]
    if " " in tok:
        a, b = tok.split()
        return NUMWORDS[a] + NUMWORDS.get(b, 0)
    return float(tok)


def intro_of(text):
    """Blogger's opening prose: stop at the Across header or the first bare
    clue-number line, whichever comes first, and never past 2000 chars."""
    intro = text[:2000]
    cut = re.search(r"(?im)^\s*(?:across\b|1\s*(?:a|ac|across)?\s*$)", intro)
    return intro[:cut.start()] if cut else intro


def times_minutes(text):
    """The blogger's own solve time in minutes, "DNF", or None. First clock
    reading in the intro wins; then 'N minutes'; then hours."""
    intro = intro_of(text)
    lines = [l for l in intro.split("\n") if l.strip()]
    for line in lines:
        for m in CLOCK.finditer(line):
            h, mm, ss = m.groups()
            sep = line[m.start(2) + len(mm):m.start(3)]
            if int(ss) >= 60 or OTHERS.search(line[max(0, m.start() - 70):m.start()]):
                continue
            if "." in sep and not CUE.search(line[max(0, m.start() - 40):m.start()] + " ") \
                    and not re.search(r"(?i)leisurely|brisk|swift|quick|slow|steady|comfortable|decent", line[max(0, m.start() - 25):m.start()]):
                continue
            v = int(h or 0) * 60 + int(mm) + int(ss) / 60
            if 1 <= v <= 240:
                return v
    for line in lines:
        for m in MINUTES.finditer(line):
            ctx = line[max(0, m.start() - 70):m.end() + 30]
            if not CUE.search(ctx) or OTHERS.search(line[max(0, m.start() - 70):m.start()]):
                continue
            v = _num(m.group(1))
            base = 0
            hm = re.search(r"(?i)(an?|one|two)\s+hours?\s+and\s+$", line[max(0, m.start() - 20):m.start()])
            if hm:
                base = 60 * NUMWORDS.get(hm.group(1).lower(), 1)
            v += base
            if 1 <= v <= 240:
                return v
    for line in lines:
        m = re.search(r"(?i)\b(three[- ]quarters|a quarter|quarter|half) (?:of )?an hour", line)
        if m and CUE.search(line[max(0, m.start() - 70):m.end() + 30]):
            return {"t": 45.0, "a": 15.0, "q": 15.0, "h": 30.0}[m.group(1)[0].lower()]
        m = HOURS.search(line)
        if m and CUE.search(line[max(0, m.start() - 70):m.end() + 30]):
            g = m.groups()
            if g[0]:
                return 30.0
            if g[1]:
                n = NUMWORDS.get(g[1].lower()) or float(g[1])
                return 60 * (n + {"half": .5, "quarter": .25}.get((g[2] or "").lower(), 0))
            if g[3]:
                return 60 * (NUMWORDS[g[3].lower()] + {"half": .5, "quarter": .25}[g[4].lower()])
            if g[5]:
                return 60 * NUMWORDS[g[5].lower()] + _num(g[6])
    if any(DNF.search(l) for l in lines):
        return "DNF"
    return None


TFTT_SERIES = {"Daily Cryptic": "times", "Quick Cryptic": "timesquick",
               "Jumbo Cryptic": "timesjumbo"}


def tftt_series(r):
    s = r["series"]
    if s == "Weekend Cryptic":
        return "sundaytimes" if "sunday" in r["title"].lower() else "times"
    return TFTT_SERIES.get(s)


def run_times():
    idx = index_table()
    posts = DATA / "timesforthetimes" / "posts"
    rows = {}
    parsed_any = 0
    for line in (DATA / "timesforthetimes" / "parsed.jsonl").open():
        r = json.loads(line)
        s = tftt_series(r)
        if not s or not r.get("number"):
            continue
        pid = f"{s}-{r['number']}"
        if pid not in idx:
            continue
        d = json.loads((posts / f"{r['post_id']}.json").read_text())
        mins = times_minutes(text_of(d.get("content")))
        parsed_any += 1
        if isinstance(mins, float) or isinstance(mins, int):
            rows[pid] = (mins, idx[pid], r["link"], __import__("datetime").date.fromisoformat(r["date"]).weekday())
    print(f"scored Times puzzles with a TftT post: {parsed_any}; with a stated time: {len(rows)}")
    report(rows, "blogger minutes")
    blogger_adjusted(rows)
    return rows


def blogger_adjusted(rows):
    """Spearman of index vs log-minutes z-scored within (series, blogger), for
    post weekday as a blogger proxy (no author in the cache), >= 3 timed posts in that series; then pooled over series."""
    import math
    groups = {}
    for pid, (mins, ix, link, author) in rows.items():
        groups.setdefault((pid.rsplit("-", 1)[0], author), []).append((math.log(mins), ix))
    per = {}
    for (s, a), g in groups.items():
        if len(g) < 3:
            continue
        xs = [x for x, _ in g]
        m = sum(xs) / len(xs)
        sd = (sum((x - m) ** 2 for x in xs) / len(xs)) ** .5 or 1
        for x, ix in g:
            per.setdefault(s, []).append(((x - m) / sd, ix))
    print("within-blogger (z of log minutes per series x blogger, bloggers with >=3):")
    allz = []
    for s, g in sorted(per.items()):
        a = [x for x, _ in g]
        b = [y for _, y in g]
        allz += g
        nb = len({au for (ss, au), gg in groups.items() if ss == s and len(gg) >= 3})
        print(f"  {s:<12} n={len(g):>3} bloggers={nb}  rho={spearman(a, b):+.3f}  p={perm_p(a, b):.4f}")
    # pooled: index z-scored within series too
    a = [x for x, _ in allz]
    b = [y for _, y in allz]
    print(f"  {'pooled':<12} n={len(allz):>3}  rho={spearman(a, b):+.3f}  p={perm_p(a, b):.4f}")


def report(rows, label):
    by = {}
    for pid, row in rows.items():
        by.setdefault(pid.rsplit("-", 1)[0], []).append(row)
    print(f"{'series':<12} {'n':>4}  {'rho':>6}  {'p':>6}  median {label}")
    for s, rs in sorted(by.items()):
        a = [r[0] for r in rs]
        b = [r[1] for r in rs]
        if len(rs) >= 4:
            rho = spearman(a, b)
            p = perm_p(a, b)
            med = sorted(a)[len(a) // 2]
            print(f"{s:<12} {len(rs):>4}  {rho:+.3f}  {p:.4f}  {med}")
        else:
            print(f"{s:<12} {len(rs):>4}  (too few)")


# --- bigdave44 -----------------------------------------------------------

STARGROUP = re.compile(r"[*★]\s*/\s*2|[*★](?:[\s*★]*[*★])?(?:\s*/\s*[*★](?:[\s*★]*[*★])?)?\+?")
DIFF_WORD = re.compile(r"(?i)d\s*i\s*f\s*f\s*i\s*c\s*u\s*l\s*t\s*y")
ENJ_WORD = re.compile(r"(?i)e\s*n\s*j\s*o\s*y\s*m\s*e\s*n\s*t")


def star_value(g):
    if re.fullmatch(r"[*★]\s*/\s*2", g.strip()) or g.strip() == "*+*/2":
        return 0.5
    parts = [p for p in g.replace("+", "").split("/")]
    counts = [p.count("*") + p.count("★") for p in parts if p.count("*") + p.count("★")]
    return sum(counts) / len(counts) if counts else None


def bd_stars(d, text):
    """(difficulty, enjoyment) stars from the 'BD Rating' header line.
    '**/***' is 2.5. The header is 'BD Rating – Difficulty ** – Enjoyment ***'
    or, in full reviews, 'BD Rating – ** – ****' (difficulty first)."""
    head = text[:3000]
    line = next((l for l in head.split("\n") if "BD Rating" in l or DIFF_WORD.search(l)), None)
    if line is None:
        return None, None
    dm, em = DIFF_WORD.search(line), ENJ_WORD.search(line)
    dif = enj = None
    if dm:
        seg = line[dm.end():em.start() if em and em.start() > dm.end() else None]
        g = STARGROUP.search(seg)
        dif = star_value(g.group()) if g else None
        if em:
            g = STARGROUP.search(line[em.end():])
            enj = star_value(g.group()) if g else None
    else:
        seg = line[line.index("BD Rating") + 9:] if "BD Rating" in line else line
        gs = STARGROUP.findall(seg)
        if gs:
            dif = star_value(gs[0])
            enj = star_value(gs[1]) if len(gs) > 1 else None
    ok = lambda v: v if v is not None and v <= 6 else None
    return ok(dif), ok(enj)


def run_bd44(show=0):
    idx = index_table()
    posts = DATA / "bigdave44" / "posts"
    rows, erows, seen = {}, {}, 0
    for line in (DATA / "bigdave44" / "parsed.jsonl").open():
        r = json.loads(line)
        pid = f"{r['series']}-{r['number']}"
        if pid not in idx:
            continue
        seen += 1
        d = json.loads((posts / f"{r['post_id']}.json").read_text())
        dif, enj = bd_stars(d, text_of(d.get("content")))
        if dif is not None:
            rows[pid] = (dif, idx[pid], r["link"])
        if enj is not None:
            erows[pid] = (enj, idx[pid], r["link"])
    print(f"scored Telegraph puzzles with a BD44 post: {seen}; with difficulty stars: {len(rows)}")
    report(rows, "stars")
    return rows




def grid_only():
    """Large-n check: the two components every puzzle has (checking,
    obscurity), and their weighted z mix, against both external sources over
    ALL our Times/Telegraph puzzles, not just the annotated few. This is the
    'grid-only' score difficulty.py deliberately refuses to band."""
    import difficulty as D
    from fetch_puzzle import puzzle_files, read_puzzle_file
    rank, base = D.ranks(), D.load_baseline()
    comp = {}
    for path in puzzle_files():
        sid = path.stem.rsplit("-", 1)[0]
        if sid not in ("times", "timesquick", "timesjumbo", "sundaytimes",
                       "telegraph", "toughie", "sundaytel", "sundaytough"):
            continue
        puz = read_puzzle_file(path)
        r = D.raw(puz, rank)
        z = {k: (v - base[k]["mean"]) / base[k]["sd"] for k, v in r.items()
             if v is not None and k in base and base[k].get("sd") and k != "device"}
        if len(z) == 2:
            z["mix"] = sum(D.WEIGHTS[k] * v for k, v in z.items()) / sum(D.WEIGHTS[k] for k in z)
            comp[puz["id"]] = z
    ext = {}
    posts = DATA / "timesforthetimes" / "posts"
    for line in (DATA / "timesforthetimes" / "parsed.jsonl").open():
        r = json.loads(line)
        s = tftt_series(r)
        pid = f"{s}-{r['number']}"
        if s and pid in comp:
            v = times_minutes(text_of(json.loads((posts / f"{r['post_id']}.json").read_text()).get("content")))
            if isinstance(v, (int, float)):
                ext[pid] = v
    posts = DATA / "bigdave44" / "posts"
    for line in (DATA / "bigdave44" / "parsed.jsonl").open():
        r = json.loads(line)
        pid = f"{r['series']}-{r['number']}"
        if pid in comp:
            v = bd_stars({}, text_of(json.loads((posts / f"{r['post_id']}.json").read_text()).get("content")))[0]
            if v is not None:
                ext[pid] = v
    by = {}
    for pid, v in ext.items():
        by.setdefault(pid.rsplit("-", 1)[0], []).append((v, comp[pid]))
    print(f"{'series':<12} {'n':>5}  checking  obscurity  mix(0.45/0.30)")
    for s, rs in sorted(by.items()):
        a = [v for v, _ in rs]
        out = [f"{spearman(a, [c[k] for _, c in rs]):+.3f}" for k in ("checking", "obscurity", "mix")]
        print(f"{s:<12} {len(rs):>5}  {out[0]:>8}  {out[1]:>9}  {out[2]:>8}")
    return by




def snitch():
    """Join the SNITCH ratings (tools/data/snitch.json, from
    tools/fetch_snitch.py) to our index, the grid-only mix, and the blogger
    minutes."""
    import contextlib
    import io
    sn = {int(k.rpartition("-")[2]): v["nitch"]
          for k, v in json.loads((ROOT / "tools" / "data" / "snitch.json").read_text()).items()}
    idx = index_table()
    with contextlib.redirect_stdout(io.StringIO()):
        mins = run_times()
    for s in ("times", "sundaytimes"):
        pairs = [(sn[n], idx[f"{s}-{n}"]) for n in sn if f"{s}-{n}" in idx]
        if len(pairs) >= 4:
            a, b = zip(*pairs)
            print(f"{s:<12} SNITCH vs index      n={len(pairs):>3} rho={spearman(a, b):+.3f} p={perm_p(a, b):.4f}")
        pairs = [(sn[n], mins[f"{s}-{n}"][0]) for n in sn if f"{s}-{n}" in mins]
        if len(pairs) >= 4:
            a, b = zip(*pairs)
            print(f"{s:<12} SNITCH vs blog mins  n={len(pairs):>3} rho={spearman(a, b):+.3f} p={perm_p(a, b):.4f}")
    import difficulty as D
    from fetch_puzzle import read_puzzle_file
    rank, base = D.ranks(), D.load_baseline()
    for s in ("times", "sundaytimes"):
        rows = []
        for n, v in sn.items():
            path = ROOT / "puzzles" / f"{s}-{n}.json"
            if not path.exists():
                continue
            r = D.raw(read_puzzle_file(path), rank)
            z = {k: (x - base[k]["mean"]) / base[k]["sd"] for k, x in r.items() if x is not None and k != "device"}
            if len(z) == 2:
                rows.append((v, z["checking"], z["obscurity"],
                             (D.WEIGHTS["checking"] * z["checking"] + D.WEIGHTS["obscurity"] * z["obscurity"]) / .75))
        if len(rows) >= 4:
            a = [r[0] for r in rows]
            print(f"{s:<12} SNITCH vs grid-only  n={len(rows):>3} checking {spearman(a, [r[1] for r in rows]):+.3f}"
                  f" obscurity {spearman(a, [r[2] for r in rows]):+.3f} mix {spearman(a, [r[3] for r in rows]):+.3f}")


if __name__ == "__main__":
    {"times": run_times, "bd44": run_bd44, "grid": grid_only, "snitch": snitch}[sys.argv[1]]()
