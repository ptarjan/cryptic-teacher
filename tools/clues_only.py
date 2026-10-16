#!/usr/bin/env python3
"""Puzzles held as their clues alone, until their answers give the grid.

    python3 tools/clues_only.py list           # every held id, one per line
    python3 tools/clues_only.py path ID         # the file holding ID
    python3 tools/clues_only.py check           # every file against the schema
    python3 tools/clues_only.py implausible ID  # 1, saying why, when no grid can hold ID

Only the clues are mandatory; the grid is derived. A filer that has a clue list
but cannot place it (the search found no grid, several, or ran out of budget;
the scan lost the clue numbers) files it here, in clues_only/<series>/<id>.json,
shaped by $defs/cluesOnly in tools/data/puzzle.schema.json: each direction's
lights in printed order, each with its clue and, when the enumeration says, its
length. No numbers, no positions, no answers, so there is no half-placed grid
to write.

THE BACKFILL FINISHES IT, for a record BUILDERS can promote: its filer and its
grid kind (its book's `grid` in tools/data/books.json). The rest cannot be
written, and those already held are never queued (solvable): the Listener
book's barred grids wait on a barred builder. tools/daily_update.sh and
tools/prereset_plan.py queue the promotable ones with the unsolved puzzles. The solver answers each clue in order; tools/apply_solution.py then
derives the one grid those answers cross in (tools/reconstruct_grid.py with
`words`, no clue numbers), numbers it, files the puzzle in puzzles/ through the
filer's own builder with every check a solved grid gets, and this file goes:
write_puzzle_file removes the clues-only copy of any id it files. A puzzle is
in exactly one of the two states.

The site never sees this folder: it reads puzzles/ alone.
"""
from __future__ import annotations

import clue_text
import datetime
import json
import re
import sys
from pathlib import Path
import puzzle_paths

TOOLS = Path(__file__).resolve().parent


ROOT = TOOLS.parent
DIR = ROOT / "clues_only"
DIRECTIONS = ("across", "down")
# The derivation's search budget: the one acquire_book.py searches under.
NODE_BUDGET = 8_000_000


def path_for(pid, root=None):
    """Where clues-only puzzle `pid` is held, whether or not it is. `root` is
    a scratch tree's clues_only/ (acquire_book.py without --puzzle-dir)."""
    return (root or DIR) / puzzle_paths.series_folder(pid) / f"{pid}.json"


def find(pid, root=None):
    """The clues-only file for `pid`, or None."""
    path = path_for(pid, root)
    return path if path.is_file() else None


def read(pid, root=None):
    path = find(pid, root)
    return json.loads(path.read_text(encoding="utf-8")) if path else None


def files(root=None):
    """Every held clues-only file under `root` (default DIR)."""
    return sorted((root or DIR).glob("*/*.json"))


def lights_from_spec(across, down):
    """({"across": [...], "down": [...]}, problems) from light_spec lights
    ([number, length, source, printed]). A light with no clue text is a problem:
    nothing could answer it, so the puzzle would never leave this state."""
    import enumeration
    from fetch_puzzle import has_words
    clues, problems = {}, []
    for direction, spec in (("across", across), ("down", down)):
        if not spec:
            problems.append(f"no {direction} clues were read: the split lost "
                            f"that list or its heading, so these are not the "
                            f"puzzle's clues")
        out = []
        for i, light in enumerate(spec, 1):
            printed = light[3] if len(light) > 3 else None
            text = (printed or {}).get("clue")
            if not text:
                problems.append(f"{direction} light {i} has no clue text")
                continue
            count = (printed or {}).get("enumeration")
            # A count that withholds its breaks, "(7, two words)", is already
            # in the words (tools/parse_penguin_book.py), its total the count.
            line = f"{text} ({count})" if count and not enumeration.worded(text) else text
            item = {"clue": enumeration.clue(
                line, missing=not has_words(enumeration.split(line)[0]))}
            if light[1]:
                item["length"] = light[1]
            out.append(item)
        clues[direction] = out
    return clues, problems


def write(record, root=None):
    """Write `record` ($defs/cluesOnly) and return its path. Refused, with
    puzzle_integrity.RefusedWrite, when it breaks the schema or the id is
    already filed with a grid; the first day held is kept across re-reads."""
    import puzzle_integrity
    import puzzle_schema
    import dashes
    import leading_quote
    import quotes
    record = quotes.straighten_clues_only(record)   # stored straight, like puzzles/
    record = dashes.normalise_clues_only(record)    # house dash and ellipsis, likewise
    record = leading_quote.normalise_clues_only(record)  # no stray leading quote or leaked number
    old = read(record["id"], root)
    if old:
        first = min(old["source"]["acquiredOn"], record["source"]["acquiredOn"])
        record = {**record, "source": {**record["source"], "acquiredOn": first}}
    record = puzzle_schema.order(puzzle_schema.prune(record), puzzle_schema.CLUES_ONLY)
    puzzle_integrity.refuse_bad_clues_only(record)
    path = path_for(record["id"], root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path


def from_book(meta, across, down, generator):
    """(record, problems) for a book puzzle whose grid was not found. `meta` is
    file_penguin_puzzle.build's puzzle for it (id, number, name, setter, year,
    source.url), so the id and title are the ones the grid puzzle will carry."""
    clues, problems = lights_from_spec(across, down)
    record = {key: meta[key] for key in ("id", "number", "series", "name", "setter",
                                         "date", "year") if meta.get(key)}
    record.update({"dimensions": {"cols": 15, "rows": 15},
                   "source": {"url": meta["source"]["url"], "acquiredBy": generator,
                              "acquiredOn": datetime.date.today().isoformat()},
                   "clues": clues})
    return record, problems


def from_jigsaw(meta, clues, preamble, generator):
    """(record, problems) for a book jigsaw: one list of clues printed with no
    numbers and no across or down, under the instruction `preamble` ("Method:
    solve the clues and enter the answers jigsaw-wise, wherever they will go").
    `clues` are [(text, enumeration)] in printed order. The record holds them
    as `unplaced` with `cluesUnplaced`; the solve answers them in that order
    and _jigsaw_build fits the answers into the grid."""
    import enumeration
    from fetch_puzzle import has_words
    out, problems = [], []
    for i, (text, count) in enumerate(clues, 1):
        if not text:
            problems.append(f"clue {i} has no clue text")
            continue
        line = f"{text} ({count})" if count else text
        item = {"clue": enumeration.clue(line, missing=not has_words(enumeration.split(line)[0]))}
        cells = clue_text.count_total(count or "")
        if cells:
            item["length"] = cells
        out.append(item)
    if not out:
        problems.append("no clues were read")
    record = {key: meta[key] for key in ("id", "number", "series", "name", "setter",
                                         "date", "year") if meta.get(key)}
    record.update({**({"preamble": preamble} if preamble else {}), "cluesUnplaced": True,
                   "dimensions": {"cols": 15, "rows": 15},
                   "source": {"url": meta["source"]["url"], "acquiredBy": generator,
                              "acquiredOn": datetime.date.today().isoformat()},
                   "clues": {"unplaced": out}})
    return record, problems


# ----------------------------------------------------------- the derivation

def derive_grid(record, answers):
    """(grid rows, None) when exactly one grid holds these answers crossing,
    else (None, why). `answers` is {"across": [...], "down": [...]} in clue
    order. No clue number goes in: the grid numbers the lights."""
    from reconstruct_grid import unique_grid
    spec, words = [], []
    for direction in DIRECTIONS:
        lights, given = record["clues"][direction], answers.get(direction) or []
        if len(given) != len(lights):
            return None, (f"{len(given)} {direction} answers for "
                          f"{len(lights)} {direction} clues")
        for light, word in zip(lights, given):
            spec.append((None, direction, light.get("length") or len(word)))
            words.append(word)
    dims = record["dimensions"]
    key = grid_key(spec, dims, words)
    hit = _read_grid_cache(key)
    if hit is not None:
        return hit
    import ocr_remote  # the search runs on the desktop when one answers, here when not
    got = unique_grid(spec, cols=dims["cols"], rows=dims["rows"], words=words,
                      max_nodes=NODE_BUDGET, search=ocr_remote.reconstruct)
    _write_grid_cache(key, got)
    return got


#: Where derive_grid keeps each search's answer: apply_solution checks a fill
#: (--check-only), then writes it, then the annotation run checks again, and
#: one search costs minutes of CPU. Keyed by the search's inputs and
#: reconstruct_grid.py's own source, so new search code searches again.
GRID_CACHE = Path.home() / ".cache" / "clues_only_grids"


def grid_key(spec, dims, words):
    import hashlib
    code = (Path(__file__).resolve().parent / "reconstruct_grid.py").read_bytes()
    blob = json.dumps([spec, dims["cols"], dims["rows"], words, NODE_BUDGET], default=str)
    return hashlib.sha256(code + b"\0" + blob.encode()).hexdigest()[:32]


def _read_grid_cache(key):
    try:
        got = json.loads((GRID_CACHE / f"{key}.json").read_text())
        return got["grid"], got["why"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write_grid_cache(key, got):
    import os
    grid, why = got
    if why and ("budget" in why or "unusable" in why):  # a host-dependent or odd outcome: search again next time
        return
    try:
        GRID_CACHE.mkdir(parents=True, exist_ok=True)
        tmp = GRID_CACHE / f"{key}.{os.getpid()}.tmp"
        tmp.write_text(json.dumps({"grid": grid, "why": why}))
        os.replace(tmp, GRID_CACHE / f"{key}.json")
    except OSError:
        pass


def entries_from_grid(grid, across, down):
    """The puzzle's entry list: grid geometry married to the printed clues.

    THE NUMBERS COME FROM THE GRID, never from the OCR. tools/puzzle_integrity
    .py checks that a puzzle's clue numbers are a function of its grid, so the
    derived numbering is the only one that can be right -- and the OCR'd digit,
    which is among the worst-read tokens on the page, is corroboration only.
    Both lists are in printed (row-major) order, which is the order
    tools/light_spec.py emits and the order this walk produces, so they zip.
    """
    rows, cols = len(grid), len(grid[0])
    white = [[c == "." for c in row] for row in grid]
    slots = {"across": [], "down": []}
    number = 0
    for y in range(rows):
        for x in range(cols):
            if not white[y][x]:
                continue
            a = (x == 0 or not white[y][x - 1]) and x + 1 < cols and white[y][x + 1]
            d = (y == 0 or not white[y - 1][x]) and y + 1 < rows and white[y + 1][x]
            if not (a or d):
                continue
            number += 1
            if a:
                run = 1
                while x + run < cols and white[y][x + run]:
                    run += 1
                slots["across"].append((number, x, y, run))
            if d:
                run = 1
                while y + run < rows and white[y + run][x]:
                    run += 1
                slots["down"].append((number, x, y, run))

    entries, problems = [], []
    for direction, spec in (("across", across), ("down", down)):
        got = slots[direction]
        if len(got) != len(spec):
            problems.append(
                f"the grid prints {len(got)} {direction} lights but the clue "
                f"list holds {len(spec)}; they cannot be matched up")
            continue
        for (num, x, y, run), light in zip(got, spec):
            printed = light[3] if len(light) > 3 else None
            clue = (printed or {}).get("clue")
            if not clue:
                problems.append(
                    f"{num}-{direction} has no clue text: it is a linked light "
                    f"whose partner printed no 'See' entry, so the book's own "
                    f"words for it were never on the page this was read from")
                continue
            if run != light[1] and light[1] is not None:
                problems.append(
                    f"{num}-{direction} is {run} cells in the grid but its "
                    f"enumeration reads {light[1]}")
            entries.append({"number": num,
                            "direction": direction, "position": {"x": x, "y": y},
                            "length": run, "clue": clue,
                            "enumeration": (printed or {}).get("enumeration")})
    entries.sort(key=lambda e: (e["number"], e["direction"] != "across"))
    return entries, problems


def _book_build(record, answers):
    """(puzzle, problems): the blocked grid `answers` cross in, as the grid
    puzzle, unsolved, through file_penguin_puzzle.build: the same builder a
    book puzzle whose grid was found at read time goes through."""
    import series
    from file_penguin_puzzle import build
    grid, why = derive_grid(record, answers)
    if grid is None:
        return None, [f"no single grid holds these answers: {why}"]
    index, position = divmod(record["number"], series.POSITIONS_PER_BOOK)
    identifier = next(b["identifier"] for b in series.BOOKS.values()
                      if b["book_index"] == index)
    lights = {d: [[None, light.get("length"), "clues-only",
                   {"clue": light["clue"].get("text"),
                    "enumeration": light["clue"].get("enumeration")}]
                  for light in record["clues"][d]] for d in DIRECTIONS}
    entries, problems = entries_from_grid(grid, lights["across"], lights["down"])
    if problems:
        return None, problems
    puzzle = build({"book_number": position, "setter": record.get("setter"),
                    "puzzle": {"dimensions": {"cols": len(grid[0]), "rows": len(grid)},
                               "entries": entries}},
                   identifier, "unsolved", unsolved=True)
    return puzzle, []


# The jigsaw fitter's budget: a real 15x15 proves its one grid in a few hundred
# nodes when the answers are right; a wrong answer can cost the whole budget.
JIGSAW_BUDGET = 400_000


def slots_of(grid):
    """[(number, x, y, length, direction)] of a blocked grid's lights, numbered
    in reading order, as entries_from_grid numbers them."""
    rows, cols = len(grid), len(grid[0])
    white = [[c != "#" for c in row] for row in grid]
    out, number = [], 0
    for y in range(rows):
        for x in range(cols):
            if not white[y][x]:
                continue
            a = (x == 0 or not white[y][x - 1]) and x + 1 < cols and white[y][x + 1]
            d = (y == 0 or not white[y - 1][x]) and y + 1 < rows and white[y + 1][x]
            if not (a or d):
                continue
            number += 1
            for direction, ok, dx, dy in (("across", a, 1, 0), ("down", d, 0, 1)):
                if not ok:
                    continue
                run = 1
                while (x + dx * run < cols and y + dy * run < rows
                       and white[y + dy * run][x + dx * run]):
                    run += 1
                out.append((number, x, y, run, direction))
    return out


def fit_jigsaw(record, answers):
    """(entries, part by entry id, problems) for a jigsaw: the grid its answers
    (`answers["unplaced"]`, letters, in the printed order) interlock in
    (tools/jigsaw_fit.py), numbered, each light given its clue. A linked
    answer's leader carries the clue and the whole count; its continuation
    reads "See N", the shape every book's linked lights take. The part map is
    {entry id: (clue index, letters in that light)}, how apply_solution hands
    each light its share of the answer."""
    import jigsaw_fit
    from groups import entry_id
    lights, given = record["clues"]["unplaced"], answers.get("unplaced") or []
    if len(given) != len(lights):
        return None, None, [f"{len(given)} answers for {len(lights)} jigsaw clues"]
    for n, (light, word) in enumerate(zip(lights, given), 1):
        if light.get("length") and light["length"] != len(word):
            return None, None, [f"clue {n}'s answer {word} is {len(word)} letters; "
                                f"its enumeration says {light['length']}"]
    dims = record["dimensions"]
    rows, placed, why = jigsaw_fit.fit(given, dims["cols"], dims["rows"],
                                       max_nodes=JIGSAW_BUDGET)
    if rows is None:
        return None, None, [f"the answers fit no single grid: {why}"]
    at = {(x, y, d): (n, part, w) for n, part, w, x, y, d in placed}
    slots = slots_of(rows)
    leader = {at[(x, y, d)][0]: num for num, x, y, _, d in slots if at[(x, y, d)][1] == 0}
    entries, parts = [], {}
    for num, x, y, run, d in slots:
        n, part, letters = at[(x, y, d)]
        clue = lights[n]["clue"]
        entry = {"number": num, "direction": d, "position": {"x": x, "y": y},
                 "length": run}
        if part == 0:
            entry.update({"clue": clue.get("text"), "enumeration": clue.get("enumeration")})
        else:
            entry.update({"clue": f"See {leader[n]}", "enumeration": None})
        entries.append(entry)
        parts[entry_id(entry)] = (n, letters)
    entries.sort(key=lambda e: (e["number"], e["direction"] != "across"))
    return entries, parts, []


def _jigsaw_build(record, answers):
    """(puzzle, problems): a book jigsaw filed as the grid puzzle its answers
    fit, unsolved, through file_penguin_puzzle.build like any book puzzle; it
    keeps `cluesUnplaced` and its preamble so the page shows the clues as the
    book printed them. puzzle["_parts"] carries fit_jigsaw's part map to
    tools/apply_solution.py, which pops it before anything is written."""
    import series
    from file_penguin_puzzle import build
    entries, parts, problems = fit_jigsaw(record, answers)
    if problems:
        return None, problems
    index, position = divmod(record["number"], series.POSITIONS_PER_BOOK)
    identifier = next(b["identifier"] for b in series.BOOKS.values()
                      if b["book_index"] == index)
    dims = record["dimensions"]
    puzzle = build({"book_number": position, "setter": record.get("setter"),
                    "puzzle": {"dimensions": {"cols": dims["cols"], "rows": dims["rows"]},
                               "entries": entries}},
                   identifier, "unsolved", unsolved=True)
    puzzle["cluesUnplaced"] = True
    if record.get("preamble"):
        puzzle["preamble"] = record["preamble"]
    puzzle["_parts"] = parts
    return puzzle, []


# (filer, grid kind) -> how its answers become the grid puzzle. A record whose
# pair is missing here cannot be written (refuse_bad_clues_only) or queued for
# a solve (solvable): its answers could never become a grid. A Listener book is
# "barred", and derive_grid places black squares, so it waits on a barred
# builder.
def _nation_build(record, answers):
    """The Nation's (tools/fetch_nation.py): its held page rebuilt on the
    grid the answers cross in. Imported late: that filer imports this module."""
    import fetch_nation
    return fetch_nation.promote(record, answers)


def _genius_numbered_build(record, answers):
    """A Genius whose numbered clue list no grid read took, filed on the grid
    its answers cross in (genius_puzzles.promote_numbered). Imported late: it
    imports this."""
    import genius_puzzles
    return genius_puzzles.promote_numbered(record, answers)


# A series with no grid kind (grid_kind() None) keys on None: its filer's
# builder knows its own grids (the Nation's are blocked 15x15 or 13x13).
def _blog_build(record, answers):
    """A blog post whose answers fit no grid, even with the untrusted ones
    left unknown (file_blog_puzzles.hold_clues), filed on the grid the solve's
    answers cross in (file_blog_puzzles.promote). Imported late: it imports
    times_grids, which is heavy."""
    import file_blog_puzzles
    return file_blog_puzzles.promote(record, answers)


# Every blog filer: a blog series keys on None, its grid a blocked square.
BLOG_FILERS = ("tools/file_georgeho_puzzles.py", "tools/file_times_puzzles.py",
               "tools/file_telegraph_puzzles.py")

BUILDERS = {("tools/acquire_book.py", "blocked"): _book_build,
            ("tools/fetch_nation.py", None): _nation_build,
            ("tools/genius_puzzles.py", None): _genius_numbered_build,
            **{(tool, None): _blog_build for tool in BLOG_FILERS}}


def grid_kind(record):
    """series.GRIDS' word for the grid `record` needs: its book's `grid`. None
    for a series that does not say, which no builder takes."""
    import series
    if not series.is_book(record.get("series")) or not isinstance(record.get("number"), int):
        return None
    try:
        return series.grid(record["series"], record["number"])
    except (KeyError, ValueError):
        return None


# A jigsaw (`cluesUnplaced`) of these filers: its answers are fitted into the
# grid (fit_jigsaw), since they say nothing of where each goes.
def _genius_jigsaw_build(record, answers):
    """A Genius printing every clue unnumbered, placed on the grid its PDF
    prints (genius_puzzles.promote_jigsaw). Imported late: it imports this."""
    import genius_puzzles
    return genius_puzzles.promote_jigsaw(record, answers)


JIGSAW_BUILDERS = {("tools/acquire_book.py", "blocked"): _jigsaw_build,
                   ("tools/genius_puzzles.py", None): _genius_jigsaw_build}


def builder(record):
    """The BUILDERS entry that promotes `record`, or None; a jigsaw's comes
    from JIGSAW_BUILDERS."""
    key = ((record.get("source") or {}).get("acquiredBy"), grid_kind(record))
    if record.get("cluesUnplaced"):
        return JIGSAW_BUILDERS.get(key)
    return BUILDERS.get(key)


def solvable(root=None):
    """[record] of every puzzle held under `root` (default DIR) a builder can
    promote: the only ones a solve queue may take. The rest stay held as data.
    A queue passes the clues_only/ beside the index it reads, so a queue run
    against another tree's index never takes this checkout's puzzles."""
    records = (json.loads(path.read_text(encoding="utf-8")) for path in files(root))
    return [r for r in records if builder(r)]


def promote(record, answers):
    """(puzzle, problems): the grid puzzle `record` becomes, unsolved, from
    `answers` ({"across": [...], "down": [...]}, or a jigsaw's {"unplaced":
    [...]}, letters, in clue order).
    tools/apply_solution.py checks the answers against it and writes both."""
    build = builder(record)
    if build is None:
        return None, [f"no builder for a {grid_kind(record)} grid filed by "
                      f"{record['source']['acquiredBy']} (clues_only.BUILDERS)"]
    puzzle, problems = build(record, answers)
    if problems:
        return None, problems
    puzzle["source"] = {**puzzle["source"], "acquiredOn": record["source"]["acquiredOn"]}
    # The clue that states the theme was filed by hand on the record, under
    # the id its printed number gives; the grid puzzle keeps it.
    if record.get("themeClue"):
        from groups import entry_id   # late, as in fit_jigsaw
        if record["themeClue"] not in {entry_id(e) for e in puzzle["entries"]}:
            return None, [f"themeClue {record['themeClue']!r} is not an entry of the "
                          f"grid these answers build"]
        puzzle["themeClue"] = record["themeClue"]
    return puzzle, []


def implausible(record):
    """Why no grid can hold this clue list, or None when one may: checked
    before a cold solve is paid for, since only its answers place the grid.

    The full search from lengths alone takes minutes, so this asks something
    cheaper. A blocked grid with half-turn symmetry prints its across lengths
    as a palindrome, and its down lengths pair off, but for at most one
    odd-length light through the centre. Every one of the 1,559 book and
    canberra grids filed on 10-12 passes. Of the 72 solves the ledger held for
    "no single grid holds these answers" in that run, 23 fail it (an OCR'd clue
    lost or doubled), and 409 untried clues-only puzzles did too. A light of
    unknown length may be anything, so it only loosens the test.
    """
    clues = record["clues"]
    if "across" not in clues or "down" not in clues:
        return None   # a jigsaw (cluesUnplaced): no grid to argue from
    across = [light.get("length") for light in clues["across"]]
    down = [light.get("length") for light in clues["down"]]
    for i in range(len(across) // 2):
        a, b = across[i], across[-1 - i]
        if a is not None and b is not None and a != b:
            return (f"its across lengths are not symmetric (light {i + 1} is {a}, "
                    f"light {len(across) - i} is {b}), so the clue list misses or "
                    f"repeats a light")
    counts = {}
    for length in down:
        if length is not None:
            counts[length] = counts.get(length, 0) + 1
    unpaired = sorted(n for n, c in counts.items() if c % 2)
    # One odd-length light may run through the centre; unknown lengths can
    # partner the rest.
    odd = [n for n in unpaired if n % 2]
    if odd:
        unpaired.remove(odd[0])
    if len(unpaired) > down.count(None):
        return (f"its down lengths do not pair off as a symmetric grid's do "
                f"(unpaired: {', '.join(map(str, unpaired))}), so the clue list "
                f"misses or repeats a light")
    return None


def main(argv):
    if argv[:1] == ["implausible"] and len(argv) == 2:
        record = read(argv[1])
        why = implausible(record) if record else None
        if why:
            print(f"{argv[1]}: no grid can hold this clue list: {why}")
            return 1
        return 0
    if argv[:1] == ["list"]:
        for path in files():
            print(path.stem)
        return 0
    if argv[:1] == ["path"] and len(argv) == 2:
        path = find(argv[1])
        if path is None:
            print(f"{argv[1]} is not held clues-only", file=sys.stderr)
            return 1
        print(path)
        return 0
    if argv[:1] == ["check"]:
        import puzzle_integrity
        failed = 0
        for path in files():
            try:
                puzzle_integrity.refuse_bad_clues_only(
                    json.loads(path.read_text(encoding="utf-8")))
            except puzzle_integrity.RefusedWrite as err:
                failed += 1
                print(err)
        print(f"clues-only: {len(files())} file(s), {failed} refused")
        return 1 if failed else 0
    print(__doc__.split("\n\n")[0], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
