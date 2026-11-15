#!/usr/bin/env python3
"""The Sunday Times Mephisto (2003-) read from the Sunday Times pages tools/gale_fetch.py downloads from
Gale's Sunday Times Historical Archive, one GALE_<docId>.pdf each in <Gale crosswords>/Mephisto/Fetched
(the solution pages in Mephisto/Solutions; both folders keep growing while the fetch walks back, so the
plan lists them afresh each time).

A page is a whole newspaper page: the Mephisto's 12x12 barred grid (bars drawn thick, the cell rules thin and
often broken, so tools/listener_grid's lattice finder, which wants unbroken rules, does not find it) stands
over the two clue columns (Across, Down) under a "Mephisto" title. The grid is found here by its long horizontal
rules (find_lattice), its bars read as tools/ios_barred reads a Beelzebub's (mirror pairs, 180-degree symmetric),
the clue columns cut under the grid and read as the Times' lists are (gale_listener.times_read). The page's
citation ('"Mephisto 2250." Sunday Times, 5 Oct. 2003, p. 382') gives the date and mostly the number; a bare
"Mephisto." has it from the page's text, or from the "Solution to Mephisto 2248" the page prints (two
puzzles back), always checked against the weekly count from No 2250 (2003-10-05). Only a puzzle with every
clue filed is written (fa.complete), unsolved; puzzles/mephisto's held numbers are never written over.

    python3 tools/gale_mephisto_read.py read NAME     # read one saved page
    python3 tools/gale_mephisto_read.py plan          # the pages not yet read

The standing pass plans each unread page as a unit (tools/edition_queue.py, paper "listener", rel
"mephisto:NAME"), ahead of the Listener's own pages.
"""
import datetime
import json
import os
import re
import sys
from pathlib import Path
import downloads
import gale_inbox as gi
import file_archive_org_puzzles as fa

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
SERIES = "mephisto"
TOOL = "tools/gale_mephisto_read.py"
SAVED = downloads.GALE_CROSSWORDS / "Mephisto" / "Fetched"
SOLUTIONS = downloads.GALE_CROSSWORDS / "Mephisto" / "Solutions"
STORE = Path(os.path.expanduser("~/.cache/gale_mephisto"))
LEDGER = "ledger.jsonl"
#: Bumped when the reading changes, so every page is read again.
VERSION = 4
PREFIX = "mephisto:"
CITED = re.compile(r'^\W*"([^"]*)"\s*(?:Sunday\s+)?Times\b\W*([0-3]?\d)\s+' + gi.MON + r"\s*(\d{4})", re.IGNORECASE)
TITLE_NUMBER = re.compile(r"mephisto\W{0,3}(\d{4})\b", re.IGNORECASE)
SOLUTION_TO = re.compile(r"solution\s+to\s+mephisto\W{0,3}(\d{4})\b", re.IGNORECASE)
TITLE_WORD = re.compile(r"^\W*mephisto\W*$", re.IGNORECASE)
STOP_WORD = re.compile(r"^\W*(?:solutions?|winners|prizes?|answers)\W*$", re.IGNORECASE)
#: The line heading last week's answers, as the OCR misreads it ("Soklstion to Mephisto 2283:").
STOP_LINE = re.compile(r"^\W*(?:so\w{3,8}n|answers)\s+to\s+m[a-z]{4,}o\b", re.IGNORECASE)
DOC_ID = re.compile(r"[A-Z]{2,6}\d{9,10}")
#: The first Mephisto the Sunday Times numbered No 2250 (2003-10-05); one a week, a number a page's text gives is
#: taken when within this many of the count (a Christmas week with no puzzle moves it by one).
FIRST = (2250, datetime.date(2003, 10, 5))
NEAR = 1
#: Dates whose weekly count is confirmed by the numbers pages gave (offsets 0, with a stray two-off misread).
COUNTED = (datetime.date(2001, 1, 1), datetime.date(2004, 12, 31))
#: The Mephisto is a 12x12 barred grid.
CELLS = 12
#: The grid's rules run this share of the page's width at least.
RULE_SHARE = 0.12
#: The grid's width over 12 cells' pitch agrees within this.
SQUARE = 0.08
#: A cell's width across may differ from its height by this much (a scan stretched one way), in this many steps.
SQUARE_SKEW = 0.12
SKEW_STEPS = 24


def estimate(day):
    """The number the weekly count gives a Mephisto of `day`."""
    return FIRST[0] + round((day - FIRST[1]).days / 7)


def cite_of(cite):
    """(number or None, date) the page's citation gives, or None."""
    m = CITED.search(re.sub(r"\s+", " ", cite or ""))
    if not m:
        return None
    n = TITLE_NUMBER.search(m.group(1))
    day = datetime.date(int(m.group(4)), gi.MONTHS[m.group(3)[:3].lower()], int(m.group(2)))
    return (int(n.group(1)) if n else None), day


def checked(n, day):
    """`n` when it is a Mephisto number near the weekly count for `day`, else None."""
    return n if n and abs(n - estimate(day)) <= NEAR else None


def number_of(cited, text):
    """(number, where from) of a page: the citation's, else the page's text ("Mephisto 2250"), else two more
    than the "Solution to Mephisto N" it prints; each checked against the weekly count."""
    day = cited[1]
    if checked(cited[0], day):
        return cited[0], "citation"
    for m in TITLE_NUMBER.finditer(text or ""):
        if not SOLUTION_TO.match(text[max(0, m.start() - 12):m.end()].strip()[-40:]) and checked(int(m.group(1)), day) \
                and "solution to" not in text[max(0, m.start() - 14):m.start()].lower():
            return int(m.group(1)), "page text"
    for m in SOLUTION_TO.finditer(text or ""):
        for step in (2, 1):
            if checked(int(m.group(1)) + step, day) and abs(int(m.group(1)) + step - estimate(day)) <= 1:
                return int(m.group(1)) + step, "solution printed"
    # No number printed: the weekly count itself, over the years the ledger's own numbers agree with it to the
    # week (every read page of 2001-2004 that gave a number, but a few misreads two off, has the count's).
    if COUNTED[0] <= day <= COUNTED[1]:
        return estimate(day), "weekly count"
    return None, None


def page_files(saved=SAVED):
    d = Path(saved)
    return sorted(p for p in d.iterdir() if p.suffix.lower() == ".pdf" and p.is_file()
                  and not p.name.startswith(".")) if d.is_dir() else []


def load_ledger(store=STORE):
    out = {}
    path = Path(store) / LEDGER
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            out[row["file"]] = row
    return out


def append_row(row, store=STORE):
    Path(store).mkdir(parents=True, exist_ok=True)
    with open(Path(store) / LEDGER, "a") as f:
        f.write(json.dumps(row) + "\n")


#: A page whose read crashed this many times is left as refused (a page that always raises).
CRASH_LIMIT = 3


def read_done(row):
    """Whether a ledger row is a verdict of this VERSION: a crashed attempt is not, so the page stays due."""
    return bool(row) and row.get("version") == VERSION and not (
        row.get("failed") and row.get("attempts", 1) < CRASH_LIMIT)


def plan(saved=SAVED, store=STORE):
    """One unit per saved page not read at VERSION (or whose last attempt crashed), newest first. The folder is
    listed each call: the fetch is still adding pages."""
    done = load_ledger(store)
    reason = "never read (Gale fetch)"
    todo = [p for p in page_files(saved) if not read_done(done.get(p.name))]
    todo.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"rel": PREFIX + p.name, "rank": fa.RANKS[reason], "reason": reason, "needs": []} for p in todo]


# ------------------------------------------------------------ the grid

def long_rules(ink, share=RULE_SHARE):
    """[(y, x0, x1)] of the long horizontal rules of `ink` (a boolean page): each run of rows (a rule's, a
    bar's thickness) holding a horizontal run of `share` of the width at least, its centre row and the run's ends."""
    import numpy as np
    import listener_grid as lg
    h, w = ink.shape
    long = lg.runs_at_least(ink, max(45, int(share * w)), 1)
    rows = np.flatnonzero(long.any(1))
    out, group = [], []
    for y in list(rows) + [None]:
        if group and (y is None or y - group[-1] > 3):
            ends = []
            for r in group:
                at = np.flatnonzero(long[r])
                # the longest unbroken stretch of the row
                cut = np.flatnonzero(np.diff(at) > 1)
                starts = np.r_[at[0], at[cut + 1]]
                stops = np.r_[at[cut], at[-1]]
                k = int(np.argmax(stops - starts))
                ends.append((int(starts[k]), int(stops[k])))
            out.append(((group[0] + group[-1]) / 2, int(np.median([e[0] for e in ends])),
                        int(np.median([e[1] for e in ends]))))
            group = []
        if y is not None:
            group.append(int(y))
    return out


#: A cell side is a bar when its ink is this share of the pitch wide.
BAR_WIDTH = 0.1
#: The lights a Mephisto's grid has (the clue counts read run 32-36).
LIGHTS = (24, 46)
#: Lines of a lattice that must be found of its 13 (the thin rules are printed broken).
MATCHED = 11
#: Lines wanted when too few rules are unbroken for MATCHED, and the share of the width then taken for a rule.
FEW_MATCHED = 8
SHORT_RULE_SHARE = 0.07
#: A cell's pitch is within these many pixels (a page scans at ~97 px a cell; the later pages are smaller).
PITCH = (24, 400)


def lattice_1d(pos, lo=PITCH[0], hi=PITCH[1], need=MATCHED):
    """(positions, count) of 13 evenly spaced lines among `pos` (centres of rules found along one axis): the
    pair of them 12 pitches apart (a pitch in lo..hi) that the most others lie within 15% of a pitch of the
    lattice between; the lattice refitted to the ones matched. None when fewer than `need` are matched."""
    got = lattices_1d(pos, lo, hi, need, limit=1)
    return (got[0], len(pos)) if got else None


def lattices_1d(pos, lo=PITCH[0], hi=PITCH[1], need=MATCHED, limit=6):
    """[positions] of up to `limit` different lattices of 13 evenly spaced lines among `pos`, best first (see
    lattice_1d for one): the same lattice (its first line within a pitch and its pitch within 10%) is kept once."""
    import numpy as np
    pos = sorted(pos)
    found = []
    for i, a in enumerate(pos):
        for b in pos[i + 1:]:
            p = (b - a) / CELLS
            if p < lo:
                continue
            if p > hi:
                break
            hits = []
            for k in range(CELLS + 1):
                at = a + k * p
                near = min(pos, key=lambda v: abs(v - at))
                if abs(near - at) <= 0.15 * p:
                    hits.append((k, near))
            # The widest pitch wins a near tie: a page's text lines are evenly spaced too, but closer than a cell.
            score = len(hits) + min(p, 150) / 40
            if len(hits) >= need:
                found.append((score, hits))
    out = []
    for score, hits in sorted(found, key=lambda f: -f[0]):
        slope, icept = np.polyfit([k for k, _ in hits], [v for _, v in hits], 1)
        if any(abs(icept - o[0]) < abs(o[1]) and abs(slope / o[1] - 1) < 0.1 for o in out):
            continue
        out.append((icept, slope))
        if len(out) >= limit:
            break
    return [[icept + slope * k for k in range(CELLS + 1)] for icept, slope in out]


def bar_fit(band, pitch, rules):
    """The 13 x lines of the grid in `band` (the ink between its first and last rule), or None: the thick vertical
    bars (columns with ink over a fifth of the band's height, 8-40 px wide: not the frame's 5 px or a thin rule)
    give the lattice's phase at `pitch` (circular mean of their centres), and the horizontal rules' right end
    which of its pitch-steps is the grid's own (the thick frame stands a little outside the lattice)."""
    import math
    import numpy as np
    prof = band.sum(0)
    on = np.flatnonzero(prof >= 0.2 * band.shape[0])
    centres, start, prev = [], None, 0
    for x in list(on) + [None]:
        if start is not None and (x is None or x - prev > 2):
            if 8 <= prev - start + 1 <= 40:
                centres.append((start + prev) / 2)
            start = None
        if x is not None:
            if start is None:
                start = x
            prev = x
    if len(centres) < 4 or not rules:
        return None
    # A page scanned a little wider than tall has a cell wider than it is tall (78 px by 75): the pitch across is
    # the one (within SQUARE_SKEW of the pitch down) the bars' centres lie most evenly on.
    best = None
    for k in range(-SKEW_STEPS, SKEW_STEPS + 1):
        p = pitch * (1 + SQUARE_SKEW * k / SKEW_STEPS)
        ang = [2 * math.pi * c / p for c in centres]
        r = math.hypot(sum(math.sin(a) for a in ang), sum(math.cos(a) for a in ang)) - 0.02 * abs(k)
        if best is None or r > best[0]:
            best = (r, p)
    pitch = best[1]
    ang = [2 * math.pi * c / pitch for c in centres]
    phase = math.atan2(sum(math.sin(a) for a in ang), sum(math.cos(a) for a in ang)) * pitch / (2 * math.pi)
    # The grid's left edge: the left end three or more rules share (a rule's right end is often lost to a break).
    starts = sorted(r[1] for r in rules)
    left = next((s for s in starts if sum(1 for t in starts if abs(t - s) <= 8) >= 3), starts[0])
    m = round((left - phase) / pitch)
    x0 = phase + m * pitch
    return [x0 + pitch * i for i in range(CELLS + 1)]


def find_lattice(ink, share=RULE_SHARE):
    """(ys, xs) of the 13 rules each way of the 12x12 grid on `ink`, or None: the horizontal rules lie on 13
    evenly spaced lines (lattice_1d); the vertical ones, long runs of ink between the first and the last, on
    13 more at the same pitch, else (the thin verticals too broken to find) the horizontal rules' own ends."""
    return next(iter(find_lattices(ink, share, limit=1)), None)


def find_lattices(ink, share=RULE_SHARE, limit=6):
    """[(ys, xs)] of the candidate 12x12 lattices on `ink`, the best set of evenly spaced rules first (a page's text
    lines and a diagram's rules make some too: the grid read tells them apart)."""
    out = []
    # A page whose thin rules are mostly broken shows too few of the 13 (11 wanted): fewer are taken (the bars'
    # symmetry and a Mephisto's lights still decide), and shorter rules counted, before the page is given up.
    for use, need in ((share, MATCHED), (share, FEW_MATCHED), (SHORT_RULE_SHARE, FEW_MATCHED)):
        rules = long_rules(ink, use)
        for ys in lattices_1d([r[0] for r in rules], limit=limit, need=need):
            xs = x_lines(ink, ys, rules)
            if xs:
                out.append((ys, xs))
        if out:
            break
    return out


def x_lines(ink, ys, rules):
    """The 13 x lines of the grid whose y lines are `ys`, or None (bar_fit, else the verticals' own, else the ink's)."""
    import numpy as np
    import listener_grid as lg
    pitch = (ys[-1] - ys[0]) / CELLS
    band = ink[max(0, int(ys[0] - pitch / 4)):int(ys[-1] + pitch / 4)]
    fitted = bar_fit(band, pitch, [r for r in rules if ys[0] - pitch / 2 <= r[0] <= ys[-1] + pitch / 2])
    if fitted:
        return fitted
    # The thin verticals are broken, so the lattice is fitted to the columns' ink: the x0 and pitch (2% either way)
    # whose 13 lines lie on the most ink (each column's ink spread 3 px either way, the grid's height over it).
    down = lg.runs_at_least(band, max(45, int(0.6 * pitch)), 0)
    cols = np.flatnonzero(down.sum(0) >= 0.4 * band.shape[0])
    centres, start, prev = [], None, 0
    for x in list(cols) + [None]:
        if start is not None and (x is None or x - prev > 3):
            centres.append((start + prev) / 2)
            start = None
        if x is not None:
            if start is None:
                start = x
            prev = x
    across = lattice_1d(centres, 0.92 * pitch, 1.08 * pitch, need=9)
    if across:
        return across[0]
    prof = np.minimum(band.sum(0).astype(float), 0.4 * band.shape[0])
    spread = np.maximum.reduce([np.roll(prof, s) for s in range(-12, 13)])
    best = None
    for scale in (0.98, 0.99, 1.0, 1.01, 1.02):
        p = pitch * scale
        offs = np.round(np.arange(CELLS + 1) * p).astype(int)
        width = len(prof) - int(offs[-1])
        if width <= 0:
            continue
        starts = np.arange(width)
        score = spread[starts[:, None] + offs[None, :]].sum(1)
        i = int(np.argmax(score))
        if best is None or score[i] > best[0]:
            best = (float(score[i]), i, p)
    if best is None or best[0] < 0.12 * (CELLS + 1) * band.shape[0]:
        return None
    return [best[1] + best[2] * i for i in range(CELLS + 1)]


#: Clues with a count the lists must give for the clue-fitted bars to stand, the lights the lists may leave
#: unlisted (a clue the OCR lost), and the pairs thick enough on one side to be tried as a bar.
FIT_CLUES = 20
FIT_UNLISTED = 3
FIT_TRY = 0.8
FIT_ROUNDS = 60


#: [clues missed, lights unlisted, clues counted] of the last mirror_fit's best bars (for a reader's report).
LAST_FIT = []


def wanted_of(laid):
    """[(numbers, direction, length)] of the clues `laid` ({"12-across": (text, enum, group)}) reads whose count
    gives the light's length: the clue list's own account of the grid, which fit_rows scores a bar set against."""
    out = []
    for lid, (_, enum, group) in laid.items():
        number, _, direction = lid.partition("-")
        counts = [int(x) for x in re.findall(r"\d+", enum or "")]
        if group or not number.isdigit() or not counts:
            continue
        out.append((frozenset({int(number)}), direction, sum(counts)))
    return out


def fits(rows, wanted):
    """(clues whose light is not on the grid at their count, lights no clue is listed for) of `rows`."""
    import reconstruct_grid as rg
    lights = rg.light_cells(rows)
    missed = sum(1 for numbers, d, length in wanted
                 if not any(dd == d and n in numbers and len(c) == length for (n, dd), c in lights.items()))
    unlisted = sum(1 for (n, d) in lights if not any(dd == d and n in nn for nn, dd, _ in wanted))
    return missed, unlisted


def mirror_fit(found, wanted):
    """The rows of listener_grid grid `found` whose bars are mirror pairs (180-degree symmetric, as a Mephisto's
    are, ios_barred's way) set so every light lies on a listed clue's number, direction and count, or None: the
    pairs read thick on one side at least are flipped one at a time from the pairs thick on both (and from those
    thick on average) while the lights agree better with the lists; the lists are the reader of the bars, so the
    bars' own symmetry threshold is not asked. Not taken for under FIT_CLUES counted clues, a clue off the grid, or
    more than FIT_UNLISTED lights no clue is listed for."""
    import ios_barred as ib
    import listener_grid as lg
    import reconstruct_grid as rg
    if len(wanted) < FIT_CLUES:
        return None
    pairs = ib.pair_ratios(found)
    n = len(found["rows"])
    free = [p for p, (_, high) in pairs.items() if high >= FIT_TRY]

    def lay(chosen):
        return ib.rows_of({s for p in chosen for s in (p, ib.mirror_of(p, n))}, n)

    best = None
    for start in ({p for p, (low, _) in pairs.items() if low >= lg.BAR_RATIO},
                  {p for p, (low, high) in pairs.items() if (low + high) / 2 >= lg.BAR_RATIO}):
        bars = set(start)
        score = ib.agreement(lay(bars), wanted)
        for _ in range(FIT_ROUNDS):
            tries = [(ib.agreement(lay(bars ^ {p}), wanted), -abs(sum(pairs[p]) / 2 - lg.BAR_RATIO), p) for p in free]
            top = max(tries, default=None)
            if top is None or top[0] <= score + 1e-9:
                break
            score = top[0]
            bars ^= {top[2]}
        if best is None or score > best[0]:
            best = (score, bars)
    rows = lay(best[1])
    missed, unlisted = fits(rows, wanted)
    LAST_FIT[:] = [missed, unlisted, len(wanted)]
    lights = len(rg.light_cells(rows))
    if missed or unlisted > FIT_UNLISTED or not LIGHTS[0] <= lights <= LIGHTS[1]:
        return None
    return rows



def window_shifts(ink, ys, xs, reach=14, top=6):
    """[dx] (cells, nearest zero first among equals) of the shifts of the lattice (ys, xs) along the page whose 13
    rule rows hold the most ink: a lattice found from a rule broken in the middle takes its left end from the
    break, half a grid off; the grid itself is the window the rules fill."""
    import numpy as np
    px = (xs[-1] - xs[0]) / CELLS
    rule = np.zeros(ink.shape[1], dtype=float)
    for y in ys:
        y = int(y)
        rule += ink[max(0, y - 2):y + 3].any(0)
    cum = np.r_[0.0, np.cumsum(rule)]
    scored = []
    for dx in range(-reach, reach + 1):
        a, b = int(xs[0] + dx * px), int(xs[-1] + dx * px)
        if dx and 0 <= a and b < ink.shape[1]:
            scored.append(((cum[b] - cum[a]) / (13 * (b - a)), dx))
    return [dx for _, dx in sorted(scored, key=lambda s: (-s[0], abs(s[1])))[:top]]


def read_barred(gray, lattice=None, wanted=None):
    """(rows, found, None) or (None, None, why) of the barred grid on `gray` (a page, uint8): the lattice found, its
    cell sides measured by listener_grid.read_box, the bars set as ios_barred.read_found sets them."""
    import numpy as np
    import listener_grid as lg
    binary = len(np.unique(gray[::7, ::7])) <= 2
    ink = gray < (128 if binary else max(lg.trove_grid.otsu(gray), 1))
    cands = [lattice] if lattice else find_lattices(ink)
    if not cands:
        return None, None, "no 12x12 lattice of rules on the page"
    first = None
    for ys, xs in cands:
        rows, found, why = read_lattice(gray, ink, ys, xs, wanted)
        if rows is not None:
            return rows, found, None
        first = first or (found, why)
    if not lattice:
        # The lattice's phase is a guess (the rules' broken left ends, a text line's rules): the same lattice a
        # cell or two along either way is tried, the symmetric bars and a Mephisto's lights saying which is the grid.
        shifts = sorted(((dx, dy) for dx in range(-5, 6) for dy in range(-2, 3) if dx or dy),
                        key=lambda s: (abs(s[0]) + abs(s[1]), abs(s[1])))
        for ys, xs in cands[:2]:
            px, py = (xs[-1] - xs[0]) / CELLS, (ys[-1] - ys[0]) / CELLS
            # first the shifts that put the grid where the rules' ink is (a lattice taken from a broken rule's far end)
            near = [(dx, 0) for dx in window_shifts(ink, ys, xs)]
            for dx, dy in near + [s for s in shifts if s not in near]:
                y2, x2 = [y + dy * py for y in ys], [x + dx * px for x in xs]
                if y2[0] < 0 or x2[0] < 0 or y2[-1] >= ink.shape[0] or x2[-1] >= ink.shape[1]:
                    continue
                rows, found, why = read_lattice(gray, ink, y2, x2, wanted)
                if rows is not None:
                    return rows, found, None
    return None, first[0], first[1]


def read_lattice(gray, ink, ys, xs, wanted=None):
    """(rows, found, None) or (None, found, why) of the grid on the lattice (ys, xs): bars by their widths, the
    reading standing when ios_barred's checks hold (symmetric bars) and its lights number a Mephisto's (24-46)."""
    import listener_grid as lg
    import ios_barred as ib
    import reconstruct_grid as rg
    pad = 6
    y0, x0 = max(0, int(ys[0]) - pad), max(0, int(xs[0]) - pad)
    sub = ink[y0:int(ys[-1]) + pad, x0:int(xs[-1]) + pad]
    dark = lg.darkness(gray[y0:int(ys[-1]) + pad, x0:int(xs[-1]) + pad])
    sys_, sxs = [y - y0 for y in ys], [x - x0 for x in xs]
    rows, sides, thin = lg.read_box(sub, dark, sys_, sxs)
    # The thin rules here are broken (their width reads ~nothing, so any ink beside one passes for a bar): a side
    # is a bar when it is BAR_WIDTH of a pitch wide (the bars are ~20 px at ~97), and the thin width stands at
    # the bar line's own ratio.
    pitch = (xs[-1] - xs[0]) / CELLS
    rows = ib.rows_of({k for k, v in sides.items() if v >= BAR_WIDTH * pitch})
    thin = BAR_WIDTH * pitch / lg.BAR_RATIO
    found = {"rows": rows, "sides": sides, "thin": thin, "lattice": (list(ys), list(xs)),
             "box": (int(xs[0]), int(ys[0]), int(xs[-1]), int(ys[-1]))}
    fitted, why = ib.read_found(found, wanted)
    if fitted is None and wanted:
        fitted = mirror_fit(found, wanted)
        why = why if fitted is None else None
    if fitted is None:
        return None, found, why
    lights = len(rg.light_cells(fitted))
    if not LIGHTS[0] <= lights <= LIGHTS[1]:
        return None, found, f"the grid has {lights} lights, not a Mephisto's"
    return fitted, found, None


# ------------------------------------------------------------ the clue lists

def lists_cut(words, box):
    """(box, masks) of the clue lists under the grid at `box` (x0, y0, x1, y1) on a page's `words`: from the
    Mephisto title under the grid (else a little under the grid) down to the first stop word ("Solution to
    Mephisto N", "Winners", "Prizes") or gap of three lines in the grid's columns."""
    import gale_listener as gl
    lh = gl.line_height(words)
    left, right = box[0] - lh, box[2] + lh
    inside = [w for w in words if left <= (w[0] + w[2]) / 2 <= right and w[1] > box[3]]
    titles = [w for w in inside if TITLE_WORD.match(w[4]) and w[1] - box[3] < 40 * lh]
    top = (min(titles, key=lambda w: w[1])[1] - lh) if titles else box[3] + lh
    bottom = top
    for w in sorted((w for w in inside if w[3] > top), key=lambda w: w[1]):
        # The stop is the heading of last week's answers ("Solution to Mephisto 2283:"), not the word "solutions"
        # in a note beside the lists ("the reference for all solutions except proper nouns").
        rest = " ".join(o[4] for o in sorted(inside, key=lambda o: o[0])
                        if o[0] >= w[0] - 1 and abs((o[1] + o[3]) / 2 - (w[1] + w[3]) / 2) < (w[3] - w[1]) / 2)
        if w[1] > top + 6 * lh and (STOP_LINE.match(rest) or (STOP_WORD.match(w[4]) and not re.match(
                r"(?i)(solutions?|answers)\s+(except|for|of|to the)\b", rest) and not rest.lower().startswith(
                    ("solutions", "solution ", "answers")))):
            break
        if w[1] - bottom > 3 * lh and bottom > top + 6 * lh:
            break
        bottom = max(bottom, w[3])
    return (int(left), int(top), int(right), int(bottom + lh / 2)), []


#: A clue number as the OCR reads it opening a line.
NUMBER_WORD = re.compile(r"^\d{1,2}[.,]?$")


def down_headed(block, gl):
    """`block` (image, key) of the clue lists with its page words given a "Down" heading word when the Across
    heading is read and no Down one is (the right-hand column is printed under no heading: the lists then read as
    one, "no reading parses"): the heading is put over the right column's first line, at its left edge. The cached
    words of the block are rewritten (the other readers take the heading from them, gale_listener.lend_heads)."""
    import statistics
    img, key = block
    words = gl.page_words(img, key)
    heads = gl.headings(words)
    across = next((w for w in sorted(heads, key=lambda w: w[1]) if gl.heading(w[4]) == "ACROSS"), None)
    if across is None or any(gl.heading(w[4]) == "DOWN" for w in heads):
        return block
    nums = [w for w in words if NUMBER_WORD.match(w[4]) and w[0] > across[0] + 0.3 * img.width]
    if len(nums) < 5:
        return block
    edge = statistics.median(w[0] for w in nums)
    col = [w for w in words if edge - 15 <= w[0] and w[1] >= 0 and re.search(r"\w", w[4])
           and abs(w[0] - edge) < 0.3 * img.width]
    top = min(w[1] for w in col)
    h = max(10, int(statistics.median(w[3] - w[1] for w in nums)))
    head = (int(edge), max(0, int(top) - h - 4), int(edge) + 4 * h, max(1, int(top) - 4), "Down")
    path = gl.OCR_CACHE / f"{key}.page.{gl.ocr_clues.reader_key('times')}.json"
    gl.write_whole(path, json.dumps([list(w) for w in words] + [list(head)]))
    return block


def right_edge(words, width, across_x):
    """The left edge of the clue lists' right-hand column on `words` (the median left end of the clue numbers
    right of the Across column), or None."""
    import statistics
    nums = [w for w in words if NUMBER_WORD.match(w[4]) and w[0] > across_x + 0.3 * width]
    return statistics.median(w[0] for w in nums) if len(nums) >= 5 else None


def tail_strip(words, cut, edge, gl):
    """(x0, y0, x1, y1) in page coordinates of the Down list's head, or None: the Mephisto prints the "Down" heading
    and the first Down clues (1, 2) at the foot of the left column, under the Across list (the list goes on at the
    top of the right column), beside last week's solution; the lists' cut stops at that solution's heading. The
    strip runs from the "Down" heading at the left edge down its clue lines to the gap before the note."""
    left, _, right, bottom = cut[0]
    x_cut = left + edge - 10
    heads = [w for w in words if gl.heading(w[4]) == "DOWN" and left <= w[0] <= left + 0.2 * (right - left)
             and bottom - 100 <= w[1] <= bottom + 400]
    if not heads:
        return None
    head = min(heads, key=lambda w: w[1])
    lines = {}
    for w in words:
        if left <= w[0] < x_cut and w[1] >= head[1] - 4 and re.search(r"\w", w[4]):
            lines.setdefault(round((w[1] + w[3]) / 2 / 8), []).append(w)
    mids = sorted(sum((w[1] + w[3]) / 2 for w in ws) / len(ws) for ws in lines.values())
    steps = sorted(b - a for a, b in zip(mids, mids[1:]) if b - a > 12)
    step = steps[len(steps) // 2] if steps else 40
    last = mids[0]
    for m in mids[1:]:
        if m - last > 1.7 * step:
            break
        last = m
    if last <= mids[0]:
        return None
    ws = [w for ws in lines.values() for w in ws if (w[1] + w[3]) / 2 <= last + 4]
    return (int(min(w[0] for w in ws)) - 6, int(head[1]) - 6, int(x_cut), int(max(w[3] for w in ws)) + 6)


def lists_block(img, key, words, cut, gl):
    """The clue lists' block (image, key) for `cut`, the lists' foot read as the Mephisto prints it: when the Down
    heading and the first Down clues stand at the left column's foot (tail_strip), they are stitched over the right
    column (the block shifted down for them), so the list reads in order; else a block with no Down heading is
    given one (down_headed). None when no block is found."""
    from PIL import Image
    block = gl.times_block(img, key, cut, words)
    if not block:
        return None
    bimg, bkey = block
    bwords = gl.page_words(bimg, bkey)
    across = next((w for w in gl.headings(bwords) if gl.heading(w[4]) == "ACROSS"), None)
    if across is None:
        return block
    edge = right_edge(bwords, bimg.width, across[0])
    strip = edge and tail_strip(words, cut, edge, gl)
    if not strip:
        return down_headed(block, gl)
    piece = img.crop(strip)
    shift = piece.height + 12
    canvas = Image.new(bimg.mode, (max(bimg.width, int(edge) + piece.width + 4), bimg.height + shift), "white")
    canvas.paste(bimg, (0, shift))
    canvas.paste(piece, (int(edge), 4))
    return canvas, gl.image_key(canvas)


def listed(img, key, words, found, gl):
    """wanted_of the clue lists under the grid at `found`, read without the grid's lengths ([] when none read)."""
    block = lists_block(img, key, words, lists_cut(words, found["box"]), gl)
    if not block:
        return []
    _, laid = gl.times_read([block], None)
    return wanted_of(laid or {})


def read_page(path, store=STORE, asker=None):
    """(verdict, puzzle or None) of one saved page. `asker` stands in for the VLM (gale_jumbo_read.vlm_mended)."""
    import numpy as np
    import gale_listener as gl
    import gale_jumbo_read as gj
    import archive_org_jumbo as aj
    import ocr_clues
    img, cite = gi.images(path)[0]
    verdict = {"file": path.name}
    cited = cite_of(cite)
    if not cited:
        verdict["refused"] = "no Sunday Times citation on the page"
        return verdict, None
    day = cited[1]
    key = gl.image_key(img)
    words = gl.page_words(img, key)
    n, how = number_of(cited, ocr_clues.lines_of(words))
    if n is None:
        verdict["refused"] = "no Mephisto number in the citation or the page text"
        return verdict, None
    verdict.update(number=n, numberFrom=how, date=day.isoformat())
    gray = np.asarray(img.convert("L"), dtype=np.uint8)
    rows, found, why = read_barred(gray)
    fitted = False
    if rows is None and found:
        # The bars alone do not read: the clue lists' counts, read without the grid, set them (mirror_fit).
        rows, found2, why2 = read_barred(gray, wanted=listed(img, key, words, found, gl))
        if rows is not None:
            found, fitted = found2, True
        else:
            why = why2 or why
    if rows is None:
        verdict["refused"] = f"grid unread: {why}"
        return verdict, None
    g = rows
    gpath = Path(store) / "grids" / f"{path.stem}.png"
    gpath.parent.mkdir(parents=True, exist_ok=True)
    img.crop(found["box"]).save(gpath)
    cut = lists_cut(words, found["box"])
    block = lists_block(img, key, words, cut, gl)
    if not block:
        verdict["refused"] = "no Mephisto clue lists found on the page"
        return verdict, None
    blocks = [block]
    lengths = {f"{k}-{d}": len(cells) for (k, d), cells in aj.rg.light_cells(g).items()}
    read, laid = gl.times_read(blocks, lengths)
    if laid is None and not fitted:
        # The bars read symmetric but the lights do not fit the lists: the lists' counts set the bars again.
        again, found2, _ = read_barred(gray, wanted=listed(img, key, words, found, gl))
        if again is not None and again != g:
            g, found, fitted = again, found2, True
            lengths = {f"{k}-{d}": len(cells) for (k, d), cells in aj.rg.light_cells(g).items()}
            read, laid = gl.times_read(blocks, lengths)
    if fitted:
        verdict["barsFitted"] = True
    verdict.update({k: v for k, v in read.items() if k in ("agreed", "clues", "refused")})
    if laid is None:
        return verdict, None
    voted = dict(laid)
    laid, blank = aj.lay_on(dict(laid), g)
    blank = {**(read.get("blank") or {}), **blank}
    tails = {t for _, _, group in laid.values() for t in (group or [])[1:]}
    for lid, (text, _, _) in laid.items():
        if lid not in tails and not (text or "").strip():
            blank.setdefault(lid, gj.UNLAID)
    laid, blank, asked = gj.vlm_mended(blocks, laid, blank, lengths, gl, asker, voted)
    if asked:
        verdict["vlmColumns"] = asked
    verdict["lights"] = len(laid)
    verdict["blank"] = sorted(blank)
    verdict["why"] = {k: str(v)[:80] for k, v in sorted(blank.items())}
    doc = DOC_ID.search(path.name.upper())
    url = f"https://link.gale.com/apps/doc/{doc.group(0)}/STHA?sid=bookmark-STHA" if doc else None
    puzzle = fa.build(n, day, g, "image", laid, None, 0, series=SERIES, name=f"Sunday Times Mephisto No {n}",
                      url=url, printed=read.get("asPrinted"))
    verdict["whole"] = bool(fa.complete(puzzle))
    if not verdict["whole"] and not blank:
        # Every clue has text, so what keeps the page from whole is a clue complete() refuses (a bracket it never
        # pairs, a word the OCR made up): named, so a "not whole, no blanks" row says which clues.
        verdict["unfit"] = sorted({f"{k}": str(v)[:60] for k, v in (fa.faults(puzzle) or {}).items()}.items()) + [
            f"{e['number']}-{e['direction']}: suspect" for e in puzzle["entries"]
            if fa.suspect((e.get("clue") or {}).get("text", ""), printed=(e.get("clue") or {}).get("asPrinted") or ())]
    return verdict, puzzle


def read_unit(rel, saved=SAVED, store=STORE):
    """Read one saved page (a unit's rel, "mephisto:NAME" or NAME), file its puzzle when whole and no file holds
    the number; the ledger row appended. Returns "read", "current" or "failed"."""
    import scan_queue
    from fetch_puzzle import puzzle_path, write_puzzle_file
    name = rel[len(PREFIX):] if rel.startswith(PREFIX) else rel
    path = Path(saved) / name
    before = load_ledger(store).get(name)
    if not path.exists() or read_done(before):
        return "current"
    try:
        verdict, puzzle = read_page(path, store)
    except Exception as e:  # any raise: the page stays due (read_done) until CRASH_LIMIT attempts
        attempts = (before or {}).get("attempts", 0) + 1
        verdict = {"file": name, "failed": f"crashed: {type(e).__name__}: {e}", "attempts": attempts}
        print(verdict["failed"], file=sys.stderr)
        append_row({**verdict, "version": VERSION if attempts >= CRASH_LIMIT else None}, store)
        return "failed"
    if puzzle is not None and verdict.get("whole"):
        target = puzzle_path(SERIES, verdict["number"])
        if target.exists():
            verdict["skip"] = "already held"
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            scan_queue.file_puzzle(write_puzzle_file, TOOL, target, puzzle, verdict)
    append_row({**verdict, "version": VERSION}, store)
    print(json.dumps(verdict))
    return "read"


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["plan"]:
        print(len(plan()))
        return 0
    if argv[:1] == ["read"] and len(argv) > 1:
        print(read_unit(argv[1]))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
