#!/usr/bin/env python3
"""Puzzles held as their clues alone, until their answers give the grid.

    python3 tools/clues_only.py list           # every held id, one per line
    python3 tools/clues_only.py path ID         # the file holding ID
    python3 tools/clues_only.py check           # every file against the schema

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

import datetime
import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import puzzle_paths  # noqa: E402

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
            line = f"{text} ({count})" if count else text
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
    return unique_grid(spec, cols=dims["cols"], rows=dims["rows"], words=words,
                       max_nodes=NODE_BUDGET)


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


# (filer, grid kind) -> how its answers become the grid puzzle. A record whose
# pair is missing here cannot be written (refuse_bad_clues_only) or queued for
# a solve (solvable): its answers could never become a grid. A Listener book is
# "barred", and derive_grid places black squares, so it waits on a barred
# builder.
BUILDERS = {("tools/acquire_book.py", "blocked"): _book_build}


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


def builder(record):
    """The BUILDERS entry that promotes `record`, or None."""
    return BUILDERS.get(((record.get("source") or {}).get("acquiredBy"), grid_kind(record)))


def solvable(root=None):
    """[record] of every puzzle held under `root` (default DIR) a builder can
    promote: the only ones a solve queue may take. The rest stay held as data.
    A queue passes the clues_only/ beside the index it reads, so a queue run
    against another tree's index never takes this checkout's puzzles."""
    records = (json.loads(path.read_text(encoding="utf-8")) for path in files(root))
    return [r for r in records if builder(r)]


def promote(record, answers):
    """(puzzle, problems): the grid puzzle `record` becomes, unsolved, from
    `answers` ({"across": [...], "down": [...]}, letters, in clue order).
    tools/apply_solution.py checks the answers against it and writes both."""
    build = builder(record)
    if build is None:
        return None, [f"no builder for a {grid_kind(record)} grid filed by "
                      f"{record['source']['acquiredBy']} (clues_only.BUILDERS)"]
    puzzle, problems = build(record, answers)
    if problems:
        return None, problems
    puzzle["source"] = {**puzzle["source"], "acquiredOn": record["source"]["acquiredOn"]}
    return puzzle, []


def main(argv):
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
