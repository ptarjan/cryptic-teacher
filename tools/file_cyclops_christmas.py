#!/usr/bin/env python3
"""File a Private Eye Cyclops Christmas special from its grid image and its fifteensquared post.

Usage:
  python3 tools/file_cyclops_christmas.py 511 563 ...    # file these numbers
  python3 tools/file_cyclops_christmas.py --dry-run 511  # check and print, write nothing

The Christmas double issue has no .puz download (tools/fetch_privateeye.py), but
the Eye serves its grid as an image at private-eye.co.uk/pictures/crossword/<issue>.gif,
where <issue> is the previous puzzle's issue + 1. The grid is read from that image
by pixel sampling: grid lines are the image's full-height and full-width dark runs,
and each cell is classed black, white or shaded from the dark-pixel fraction and
mean brightness of three small patches clear of the clue number (top left) and of
any printed letter (centre). A glyph in the centre marks a letter printed in the grid.

The clues and answers come from the fifteensquared post. A light is a run of
non-black cells that does not lie wholly in an unclued shaded run, numbered in
the usual order; the post must clue every light. A linked answer's continuation
leg, which the post folds into its leader's row ("28/21"), gets the Eye's own
"see 28ac." text. The puzzle is then built by fetch_privateeye.convert and its
answers joined by fetch_privateeye.solve_from_fifteensquared, which refuses on
any length, crossing or link mismatch.

Each shaded run of 20 or more cells is an unclued light (`unclued`): a closed
ring is read clockwise, a line from its end nearest the top left. Its letters
are the crossing answers' plus, for the cells no answer crosses, the post's
quotation, found by matching the checked letters against the post's letter
stream at every starting cell of the ring. The match must be exact on checked
cells except where the grid overrides a typo in the post, and the unchecked
letters must equal the multiset the preamble lists. Anything less is refused.
"""
import argparse
import html
import json
import os
import re
import sys
import unicodedata
import urllib.request
from collections import Counter
from pathlib import Path

from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_privateeye as fp  # noqa: E402
import provenance  # noqa: E402
from fetch_puzzle import write_puzzle_file  # noqa: E402

GENERATOR = "tools/file_cyclops_christmas.py"
POSTS = Path.home() / "cryptic-setter-data" / "fifteensquared" / "posts"
IMAGE_URL = "https://www.private-eye.co.uk/pictures/crossword/{issue}.gif"

# number: (issue, fifteensquared cache file id, preamble start, preamble end).
# The preamble is quoted from the post between the two markers, inclusive.
SPECIALS = {
    485: (1330, 53256, "Answers to asterisked clues", "appears in square brackets."),
    511: (1356, 68999, "Running clockwise around the shaded squares, starting top left, is an extract from a Diary",
          "WWWW"),
    563: (1408, 93880, "Running clockwise around the shaded squares are the", "V W Y"),
    589: (1434, 104939, "Running clockwise around the shaded squares, starting top left, are two sentences",
          "U WWW Y"),
    641: (1486, 125981, "Running clockwise around the shaded squares, starting top left, is an extract (slightly",
          "UUUU YY"),
    743: (1588, 168681, "Running clockwise around the shaded squares, starting top left, is an extract (with",
          "W W W Y"),
    768: (1613, 179769, "A quote appearing in Commentatorballs", "U W Y"),
    794: (1639, 191222, "Running clockwise round the shaded squares from the top LH corner",
          "AAAABDEEEEEEEGHHIIIIIKLLLMNNNOOOPRRRSSSTTTTTUY"),
}

TAG = re.compile(r"<[^>]+>")
ENUM = re.compile(r"\(\s*\d+(?:\s*(?:[,\-.;:/']|and|\s)\s*\d+)*\s*\)")
AMP = re.compile(r"^\(?\s*&\s*((?:\d+\s*(?:ac|dn|a|d|across|down)?\.?\s*[/,&]?\s*)+)\)?\s*", re.I)
UNCLUED_MIN = 20


# ---------- the grid image ----------

def _runs(prof, thr):
    out, cur = [], None
    for i, v in enumerate(prof):
        if v >= thr:
            cur = [i, i] if cur is None else [cur[0], i]
        elif cur is not None:
            out.append(cur)
            cur = None
    if cur:
        out.append(cur)
    return [(a + b) / 2 for a, b in out]


def read_grid(path):
    """Image -> rows of cell codes: '#' black, '.' white, 's' shaded, 'p' pink; '+G' a printed glyph."""
    rgb = Image.open(path).convert("RGB")
    grey = rgb.convert("L")
    W, H = grey.size
    gp, cp = grey.load(), rgb.load()
    xs = _runs([sum(gp[x, y] < 100 for y in range(H)) / H for x in range(W)], 0.93)
    ys = _runs([sum(gp[x, y] < 100 for x in range(W)) / W for y in range(H)], 0.93)
    bp = grey.filter(ImageFilter.BoxBlur(2)).load()
    grid = []
    for r in range(len(ys) - 1):
        row = []
        for c in range(len(xs) - 1):
            x0, y0, w, h = xs[c], ys[r], xs[c + 1] - xs[c], ys[r + 1] - ys[r]

            def patch(fx0, fx1, fy0, fy1):
                dark = n = 0
                tot = [0, 0, 0]
                for yy in range(int(y0 + h * fy0), int(y0 + h * fy1)):
                    for xx in range(int(x0 + w * fx0), int(x0 + w * fx1)):
                        n += 1
                        dark += gp[xx, yy] < 128
                        for i in range(3):
                            tot[i] += cp[xx, yy][i]
                return dark / n, tot[0] / n - tot[2] / n, sum(tot) / (3 * n)

            ps = [patch(.72, .9, .4, .62), patch(.4, .62, .78, .92), patch(.72, .9, .75, .92)]
            dark = sorted(p[0] for p in ps)[1]
            mean = sorted(p[2] for p in ps)[1]
            if dark > 0.85:
                kind = "#"
            elif sum(p[1] > 25 for p in ps) >= 2:
                kind = "p"
            elif dark > 0.08 or mean < 235:
                kind = "s"
            else:
                kind = "."
            ink = n = 0
            for yy in range(int(y0 + h * .3), int(y0 + h * .78)):
                for xx in range(int(x0 + w * .3), int(x0 + w * .75)):
                    n += 1
                    ink += bp[xx, yy] < 70
            row.append(kind + ("G" if kind != "#" and ink / n > 0.06 else ""))
        grid.append(row)
    return grid


def components(grid, kind):
    H, W = len(grid), len(grid[0])
    seen, comps = set(), []
    for y in range(H):
        for x in range(W):
            if (x, y) in seen or not grid[y][x].startswith(kind):
                continue
            stack, comp = [(x, y)], []
            seen.add((x, y))
            while stack:
                cx, cy = stack.pop()
                comp.append((cx, cy))
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if 0 <= nx < W and 0 <= ny < H and (nx, ny) not in seen and grid[ny][nx].startswith(kind):
                        seen.add((nx, ny))
                        stack.append((nx, ny))
            comps.append(comp)
    return comps


def unclued_paths(grid):
    """Each shaded run of UNCLUED_MIN+ cells as an ordered cell list, or raise."""
    paths = []
    for comp in [c for c in components(grid, "s") + components(grid, "p") if len(c) >= UNCLUED_MIN]:
        cells = set(comp)
        nb = {c: [n for n in ((c[0] + 1, c[1]), (c[0] - 1, c[1]), (c[0], c[1] + 1), (c[0], c[1] - 1))
                  if n in cells] for c in cells}
        if all(len(v) == 2 for v in nb.values()):
            start = min(cells, key=lambda c: (c[1], c[0]))
            prev, cur, path = start, max(nb[start], key=lambda c: c[0]), [start]
            while cur != start:
                path.append(cur)
                a, b = nb[cur]
                prev, cur = cur, (b if a == prev else a)
            paths.append((True, path))
        elif all(len(v) <= 2 for v in nb.values()) and sum(len(v) == 1 for v in nb.values()) == 2:
            start = min((c for c, v in nb.items() if len(v) == 1), key=lambda c: (c[1], c[0]))
            prev, cur, path = None, start, [start]
            while True:
                nxt = [n for n in nb[cur] if n != prev]
                if not nxt:
                    break
                prev, cur = cur, nxt[0]
                path.append(cur)
            paths.append((False, path))
        else:
            raise ValueError(f"shaded region of {len(cells)} cells is neither a ring nor a line")
    return paths


def lights(grid, unclued_cells):
    H, W = len(grid), len(grid[0])

    def black(x, y):
        return not (0 <= x < W and 0 <= y < H) or grid[y][x] == "#"

    out, n = [], 0
    for y in range(H):
        for x in range(W):
            if black(x, y):
                continue
            found = []
            for d, (dx, dy) in (("across", (1, 0)), ("down", (0, 1))):
                if black(x - dx, y - dy) and not black(x + dx, y + dy):
                    length = 0
                    while not black(x + dx * length, y + dy * length):
                        length += 1
                    if not all((x + dx * i, y + dy * i) in unclued_cells for i in range(length)):
                        found.append((d, length))
            if found:
                n += 1
                out.extend((n, d, x, y, length) for d, length in found)
    return out


# ---------- the post ----------

def post_text(post):
    return html.unescape(TAG.sub(" ", post["content"]["rendered"].replace("</p>", "\n")))


def letter_stream(text):
    return re.sub(r"[^A-Z]", "", unicodedata.normalize("NFKD", text).upper())


def post_rows(content):
    direction, rows = None, []
    for m in re.finditer(r"<tr.*?</tr>|<h\d[^>]*>.*?</h\d>|<p[^>]*>\s*(?:<[^>]+>\s*)*(?:Across|Down)\s*(?:<[^>]+>\s*)*</p>",
                         content, re.S):
        t = m.group(0)
        heading = re.search(r">\s*(Across|Down)\s*<", t)
        cells = [re.sub(r"\s+", " ", html.unescape(TAG.sub("", c))).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", t, re.S)]
        if heading and (not cells or all(c in ("", "Across", "Down") for c in cells)):
            direction = heading.group(1).lower()
            continue
        if len(cells) < 2:
            continue
        key = re.sub(r"\s+", "", cells[0]).strip("*").replace(".", "")
        if re.match(r"^\d+[a-z]*(/\d+[a-z]*)*$", key, re.I):
            rows.append((key, direction, cells))
    return rows


def clue_of(cells):
    """The clue text, through its enumeration, from a row's cells after the answer."""
    rest = " ".join(c for c in cells[2:] if c)
    m = ENUM.search(rest)
    if not m:
        return None
    text = rest[:m.end()].strip()
    amp = AMP.match(text)
    if amp:
        text = f"(& {amp.group(1).strip().rstrip('.')}.) " + text[amp.end():]
    return text


def _dir(suffix, default):
    return {"a": "across", "d": "down"}.get(suffix[:1].lower(), default)


def clues_for(post, light_list):
    lightset = {(n, d) for n, d, *_ in light_list}
    rows = post_rows(post["content"]["rendered"])
    clues = {}
    for key, d, cells in rows:
        m = re.match(r"^(\d+)([a-z]?)", key, re.I)
        text = clue_of(cells)
        if text:
            clues.setdefault((int(m.group(1)), _dir(m.group(2), d)), text)
    for key, d, cells in rows:
        parts = re.findall(r"(\d+)([a-z]*)", key, re.I)
        amp = re.match(r"^\(& ([^)]*)\)", clue_of(cells) or "")
        if amp and len(parts) == 1:
            parts += re.findall(r"(\d+)\s*([a-z]*)", amp.group(1), re.I)
        if len(parts) < 2:
            continue
        lead_n, lead_d = int(parts[0][0]), _dir(parts[0][1], d)
        for n, suffix in parts[1:]:
            n, md = int(n), _dir(suffix, d)
            own = clues.get((n, md))
            if (n, md) not in lightset or (own and not own.startswith("see ")):
                md = "down" if md == "across" else "across"
            if (n, md) in lightset and (n, md) not in clues:
                clues[(n, md)] = f"see {lead_n}{'ac' if lead_d == 'across' else 'dn'}."
    return clues


def preamble_of(post, start, end):
    text = re.sub(r"\s+", " ", post_text(post))
    i = text.index(start)
    j = text.index(end, i) + len(end)
    return text[i:j].strip()


def listed_letters(preamble):
    """The preamble's closing list of unchecked letters, as a Counter; None if it has none."""
    tail = preamble.rsplit(":", 1)
    return Counter(letter_stream(tail[1])) if len(tail) == 2 else None


def quote_for(pattern, letters, ring):
    """(rotation, letters) of every exact match of `pattern` ('?' = unchecked) in the post's letter stream."""
    found = []
    for r in (range(len(pattern)) if ring else [0]):
        p = pattern[r:] + pattern[:r]
        for m in re.finditer("(?=(" + p.replace("?", ".") + "))", letters):
            found.append((r, m.group(1)))
    return found


def near_quote(pattern, letters, ring, limit=2):
    """The single best alignment with at most `limit` checked-cell disagreements, or None."""
    best = None
    for r in (range(len(pattern)) if ring else [0]):
        p = pattern[r:] + pattern[:r]
        known = [(i, ch) for i, ch in enumerate(p) if ch != "?"]
        for s in range(len(letters) - len(p) + 1):
            miss = 0
            for i, ch in known:
                if letters[s + i] != ch:
                    miss += 1
                    if miss > limit:
                        break
            else:
                if best is None or miss < best[0]:
                    best = (miss, r, letters[s:s + len(p)])
    return best


# ---------- assembly ----------

def build(num, image_dir):
    issue, post_id, pre_start, pre_end = SPECIALS[num]
    image = Path(image_dir) / f"{issue}.gif"
    if not image.exists():
        req = urllib.request.Request(IMAGE_URL.format(issue=issue), headers={"User-Agent": "Mozilla/5.0"})
        image.write_bytes(urllib.request.urlopen(req, timeout=30).read())
    grid = read_grid(image)
    if len(grid) != 27 or any(len(r) != 27 for r in grid):
        raise ValueError(f"grid read as {len(grid[0])}x{len(grid)}, not 27x27")
    paths = unclued_paths(grid)
    unclued_cells = {c for _, p in paths for c in p}
    light_list = lights(grid, unclued_cells)
    post = json.loads((POSTS / f"{post_id}.json").read_text(encoding="utf-8"))
    clues = clues_for(post, light_list)
    order = sorted(light_list, key=lambda t: (t[1] != "across", t[0]))
    missing = [(n, d) for n, d, *_ in order if (n, d) not in clues]
    if missing:
        raise ValueError(f"post gives no clue for {missing}")
    extra = set(clues) - {(n, d) for n, d, *_ in order}
    if extra:
        raise ValueError(f"post clues lights the grid lacks: {sorted(extra)}")

    original = fp.number_grid
    fp.number_grid = lambda solution, width, height: order
    try:
        puzzle = fp.convert(num, {
            "width": 27, "height": 27,
            "solution": "".join(fp.BLACK if c == "#" else "X" for r in grid for c in r),
            "title": f"Eye {issue}/{num}", "author": fp.SETTER,
            "clues": [clues[(n, d)] for n, d, *_ in order], "scrambled": False})
    finally:
        fp.number_grid = original
    solutions, problem = fp.solve_from_fifteensquared(puzzle, post)
    if problem:
        raise ValueError(f"answers do not fit the grid: {problem}")
    at = {}
    for e in puzzle["entries"]:
        e["solution"] = solutions[f"{e['number']}-{e['direction']}"]
        x, y = e["position"]["x"], e["position"]["y"]
        for i, ch in enumerate(e["solution"]):
            at[(x + i, y) if e["direction"] == "across" else (x, y + i)] = ch

    stray = [(x, y) for y, row in enumerate(grid) for x, c in enumerate(row)
             if c != "#" and (x, y) not in at and (x, y) not in unclued_cells]
    if stray:
        raise ValueError(f"white cells in no light: {stray}")

    preamble = preamble_of(post, pre_start, pre_end)
    listed = listed_letters(preamble) if paths else None
    letters = letter_stream(post_text(post))
    unclued, unchecked = [], Counter()
    for ring, path in paths:
        pattern = "".join(at.get(c, "?") for c in path)
        hits = quote_for(pattern, letters, ring)
        if hits:
            # Prefer the reading that starts where the path starts (the preambles say
            # "starting top left"); a ring of separate names may start anywhere.
            r, quote = min(hits, key=lambda h: h[0])
        else:
            near = near_quote(pattern, letters, ring)
            if near is None:
                raise ValueError(f"no quotation in the post fits the {len(path)}-cell unclued light")
            _, r, quote = near
        path = path[r:] + path[:r]
        # Checked cells take the grid's letter: a disagreement there is the post's typo.
        solution = "".join(at.get(c, ch) for c, ch in zip(path, quote))
        unchecked.update(ch for c, ch in zip(path, solution) if c not in at)
        unclued.append({"cells": [{"x": x, "y": y} for x, y in path], "solution": solution})
    if listed is not None and unchecked != listed:
        raise ValueError(f"unchecked letters {sorted(unchecked.elements())} differ from the preamble's list")

    printed = [{"x": x, "y": y, "letter": at.get((x, y)) or next(
        u["solution"][i] for u in unclued for i, c in enumerate(u["cells"]) if (c["x"], c["y"]) == (x, y))}
        for y, row in enumerate(grid) for x, c in enumerate(row) if c.endswith("G")]

    puzzle["preamble"] = preamble
    puzzle["source"] = {"url": IMAGE_URL.format(issue=issue)}
    if unclued:
        puzzle["unclued"] = unclued
    if printed:
        puzzle["printed"] = printed
    puzzle["solutions"] = provenance.with_solution_detail(puzzle, {
        "blog": "fifteensquared", "url": post["link"], "date": post["date"][:10],
        "check": f"{len(solutions)} entries verified against the grid image (lengths, crossings, "
                 "linked-clue mapping); unclued letters checked against the preamble's list",
    })["solutions"]
    return puzzle


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("numbers", nargs="+", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--images", default=os.environ.get("TMPDIR", "/tmp"))
    args = ap.parse_args(argv)
    failed = 0
    for num in args.numbers:
        try:
            puzzle = build(num, args.images)
        except Exception as err:  # noqa: BLE001 — report every number, refuse each failure
            print(f"cyclops-{num}: refused — {err}")
            failed += 1
            continue
        if args.dry_run:
            print(f"cyclops-{num}: ok, {len(puzzle['entries'])} entries, "
                  f"{len(puzzle.get('unclued', []))} unclued, {len(puzzle.get('printed', []))} printed")
            continue
        path = write_puzzle_file(fp.puzzle_path(fp.SERIES, num), puzzle, generator=GENERATOR)
        print(f"cyclops-{num}: wrote {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
