#!/usr/bin/env python3
"""Fill held, unsolved TLS puzzles from the solution grid in a later issue's page PDF.

    python3 tools/tls_pdf_keys.py [--write] [--numbers 1412 1416 ...]

The TLS prints each puzzle's solution four issues on (tools/tls_puzzles.py SOLUTION_LAG). Since
2022 the site also hosts the page as a vector PDF whose solution grid is live text: one big
(font 80, scaled) uppercase letter per white cell, a row's runs of cells set as one string of
letters and spaces, a lone cell as a string of its own, rows 100 text units apart. pypdf reads
the strings and their text-matrix positions; no OCR is involved. The letters are put on the
held puzzle's lattice (the pitch tried against the held grid), and the answers are filled
only when the key's lettered cells are exactly the held grid's lights and every entry reads
off whole; the held puzzle's own answers are never overwritten.
"""
import argparse
import re
import sys
from collections import Counter
from pathlib import Path

import downloads
from fetch_puzzle import read_puzzle_file, write_puzzle_file

CACHE = downloads.ROOT / "tls"
GENERATOR = "tools/tls_puzzles.py"  # the filer whose files these are (acquiredBy is kept)
SOLUTION_LAG = 4
LETTERS = re.compile(r"^[A-Z ]+$")


def key_items(pdf):
    """[(x, y, text, font size, cm)] of every text string on the PDF's pages."""
    from pypdf import PdfReader
    items = []

    def visit(text, cm, tm, fd, fs):
        if text.strip():
            items.append((tm[4], tm[5], text, round(fs, 2), tuple(round(v, 3) for v in cm)))

    for page in PdfReader(str(pdf)).pages:
        page.extract_text(visitor_text=visit)
    return items


def key_cells(items, pitch_scale=None, n=15):
    """({(row, col): letter}, pitch) read off the grid strings among `items`, or ({}, None)."""
    grid = [i for i in items if LETTERS.match(i[2].rstrip("\n")) and i[3] >= 20]
    if not grid:
        return {}, None
    font, cm = Counter((i[3], i[4]) for i in grid for _ in re.findall("[A-Z]", i[2])).most_common(1)[0][0]
    grid = [i for i in grid if (i[3], i[4]) == (font, cm)]
    return grid, font


def cells_at(grid, pitch, dx=0.0, dy=0.0):
    """{(row, col): letter} with the strings' letters spread `pitch` text units a cell."""
    ymax = max(i[1] for i in grid)
    xmin = min(i[0] for i in grid)
    cells = {}
    for x, y, text, *_ in grid:
        row = round((ymax - y + dy) / pitch)
        col = round((x - xmin + dx) / pitch)
        for k, tok in enumerate(text.strip().split(" ")):
            if tok:
                if len(tok) != 1 or (row, col + k) in cells:
                    return None
                cells[(row, col + k)] = tok
    return cells


def lights_of(puzzle):
    cells = set()
    for e in puzzle["entries"]:
        x, y = e["position"]["x"], e["position"]["y"]
        for _ in range(e["length"]):
            cells.add((y, x))
            x, y = x + (e["direction"] == "across"), y + (e["direction"] == "down")
    return cells


def answers(puzzle, pdf):
    """({"n-direction": word}, None) from the PDF's key, or (None, why)."""
    items = key_items(pdf)
    grid, font = key_cells(items)
    if not grid:
        return None, "no grid letters in the PDF text"
    lights = lights_of(puzzle)
    tried = []
    cells = None
    for pitch in sorted({font * 1.25, font * 1.25 / 2, font * 1.25 * 2, font}):
        for dx in range(-45, 50, 5):
            for dy in range(-45, 50, 5):
                got = cells_at(grid, pitch, dx, dy)
                if got is None:
                    continue
                tried.append(len(got))
                if set(got) == lights:
                    cells = got
                    break
            if cells:
                break
        if cells:
            break
    if not cells:
        return None, f"key cells {sorted(set(tried))} do not fit the {len(lights)} lights"
    fill = {}
    for e in puzzle["entries"]:
        x, y = e["position"]["x"], e["position"]["y"]
        word = ""
        for _ in range(e["length"]):
            word += cells[(y, x)]
            x, y = x + (e["direction"] == "across"), y + (e["direction"] == "down")
        fill[f"{e['number']}-{e['direction']}"] = word
    return fill, None


def held_unsolved():
    out = {}
    for p in sorted((Path(__file__).resolve().parent.parent / "puzzles" / "tls").glob("*/tls-*.json")):
        puzzle = read_puzzle_file(p)
        if not all(e.get("solution") for e in puzzle["entries"]):
            out[puzzle["number"]] = p
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--numbers", type=int, nargs="*", help="puzzle numbers (not page numbers)")
    args = ap.parse_args(argv)
    import apply_solution
    from trove_solution_ocr import fill as put
    done = 0
    held_all = {}  # the other page's own puzzle is not excluded: a unique exact fit is the rule
    for number, path in held_unsolved().items():
        if args.numbers and number not in args.numbers:
            continue
        pdf = CACHE / "pdf" / f"{number + SOLUTION_LAG}.pdf"
        puzzle = read_puzzle_file(path)
        try:
            fill, why = answers(puzzle, pdf) if pdf.exists() else (None, "no PDF")
        except Exception as e:  # a PDF pypdf cannot read
            fill, why = None, f"{type(e).__name__}: {e}"
        if not fill:
            # The page may print another issue's key (2026: the previous one; 1589/1590's swapped):
            # take a page within 1-6 issues whose key is the one exactly fitting and not that page's own at lag 4.
            fits = []
            for lag in (1, 2, 3, 5, 6):
                alt = CACHE / "pdf" / f"{number + lag}.pdf"
                other = held_all.get(number + lag - SOLUTION_LAG)
                if alt.exists() and (other is None or other == path):
                    try:
                        got, _ = answers(puzzle, alt)
                    except Exception:
                        got = None
                    if got:
                        fits.append((lag, got))
            if len(fits) == 1:
                fill, why = fits[0][1], None
                print(f"tls-{number}: key on page {number + fits[0][0]} (lag {fits[0][0]})")
        if fill:
            held = {apply_solution.entry_id(e): fill[f"{e['number']}-{e['direction']}"] for e in puzzle["entries"]}
            _, _, problems = apply_solution.check_fill(puzzle, held)
            if problems:
                fill, why = None, problems[0]
        if not fill:
            print(f"tls-{number}: {why}")
            continue
        if args.write:
            put(puzzle, fill)
            write_puzzle_file(path, puzzle, generator=GENERATOR)
        done += 1
        print(f"tls-{number}: filled from page {number + SOLUTION_LAG}")
    print(f"{done} puzzles")
    return 0


if __name__ == "__main__":
    sys.exit(main())
