#!/usr/bin/env python3
"""Fill held, unsolved TLS puzzles from the solution grid printed on a later issue's page picture.

    python3 tools/tls_image_keys.py [--write] [--workers 20] [--numbers 1304 1305 ...]

The page picture (CACHE/image/<N+4>.jpg|png, kept by tools/tls_puzzles.py --pages) prints the
solution of issue N, four numbers back. This reads it as tools/gale_tls_read.py reads a Gale page:
the grid is cut from the picture (CACHE/solution/<page>.png when tls_puzzles already cut it, else
tls_puzzles.solution_crop), enlarged twice, framed by gale_tls_read.square_lattice when that fits
the held grid's blocks, and read by trove_solution_ocr.read_answers (tight, names kept). A light
is filled only when the reading accepts it and apply_solution.check_fill finds every crossing
agreeing and every enumeration met; a puzzle with some lights read is filled in part. A held
answer is never overwritten (trove_solution_ocr.fill skips it). Puzzles whose PDF key
tools/tls_pdf_keys.py reads are left to it.
"""
import argparse
import json
import sys
from multiprocessing import Pool

import downloads

CACHE = downloads.ROOT / "tls"
GENERATOR = "tools/tls_puzzles.py"  # the filer whose files these are (acquiredBy is kept)
SOLUTION_LAG = 4
SCALE = 2
FIT = 0.97


def page_image(page):
    for ext in ("jpg", "png"):
        p = CACHE / "image" / f"{page}.{ext}"
        if p.exists():
            return p
    return None


def crop_of(page):
    """The solution grid of page `page` as a PIL image, or None."""
    import tls_puzzles
    from PIL import Image
    saved = CACHE / "solution" / f"{page}.png"
    if saved.exists():
        return Image.open(saved)
    path = page_image(page)
    if path is None:
        return None
    img = Image.open(path)
    img.load()
    return tls_puzzles.solution_crop(img)


def read_one(job):
    """(number, {"n-direction": word} or None, why) for one held puzzle's file."""
    number, path = job
    try:
        import numpy as np
        import apply_solution
        import gale_tls_read as gtr
        import trove_solution_ocr as tso
        from fetch_puzzle import read_puzzle_file
        from PIL import Image
        page = number + SOLUTION_LAG
        crop = crop_of(page)
        if crop is None:
            return number, None, "no solution grid found on the page"
        puzzle = read_puzzle_file(path)
        grid = tso.puzzle_grid(puzzle)
        big = crop.convert("L").resize((crop.width * SCALE, crop.height * SCALE), Image.LANCZOS)
        out = CACHE / "solution_x2" / f"{page}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        big.save(out)
        fit, lat = gtr.square_lattice(np.asarray(big), grid)
        framing = lat if fit >= FIT else None
        read, _ = tso.read_answers(out, grid, tight=True, named=True, framing=framing)
        fill = {f"{n}-{d}": w for (n, d), w in read.items()}
        if not fill:
            return number, None, f"no light read (block fit {fit:.2f})"
        held = {apply_solution.entry_id(e): fill[f"{e['number']}-{e['direction']}"]
                for e in puzzle["entries"] if f"{e['number']}-{e['direction']}" in fill}
        _, _, problems = apply_solution.check_fill(puzzle, held)
        problems = [p for p in problems if "no answer given" not in p]  # a part fill leaves lights blank
        if problems:
            return number, None, problems[0]
        return number, fill, f"{len(fill)} of {len(puzzle['entries'])} lights (block fit {fit:.2f})"
    except Exception as e:  # one bad page is a verdict
        return number, None, f"{type(e).__name__}: {e}"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--numbers", type=int, nargs="*", help="puzzle numbers (not page numbers)")
    args = ap.parse_args(argv)
    import tls_pdf_keys
    from fetch_puzzle import read_puzzle_file, write_puzzle_file
    from trove_solution_ocr import fill as put
    jobs = []
    for number, path in tls_pdf_keys.held_unsolved().items():
        if args.numbers and number not in args.numbers:
            continue
        if page_image(number + SOLUTION_LAG) is None:
            continue
        if (CACHE / "pdf" / f"{number + SOLUTION_LAG}.pdf").exists() and not args.numbers:
            fill, _ = tls_pdf_keys.answers(read_puzzle_file(path), CACHE / "pdf" / f"{number + SOLUTION_LAG}.pdf")
            if fill:
                continue
        jobs.append((number, path))
    results = {}
    with Pool(args.workers) as pool:
        for number, fill, why in pool.imap_unordered(read_one, jobs):
            results[number] = (fill, why)
            print(json.dumps({"number": number, "read": bool(fill), "why": why}), flush=True)
    whole = part = 0
    for number, path in jobs:
        fill, why = results[number]
        if not fill or not args.write:
            continue
        puzzle = read_puzzle_file(path)
        put(puzzle, fill)
        try:
            write_puzzle_file(path, puzzle, generator=GENERATOR)
        except Exception as e:  # the write gate's refusal: the file stands as held
            print(json.dumps({"number": number, "refused": f"{type(e).__name__}: {e}"}), flush=True)
            continue
        if all(e.get("solution") for e in puzzle["entries"]):
            whole += 1
        else:
            part += 1
    print(json.dumps({"whole": whole, "part": part}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
