#!/usr/bin/env python3
"""Write a solved grid into a puzzle file — but only if the grid checks out.

Saturday prize puzzles publish without answers and only get them about a week
later, which used to mean they sat un-annotatable until the paper caught up.
This is the other route in: a model solves the puzzle cold and the fill lands
here, where it is checked against the grid before anything is written.

The check is the whole point. There is no answer key for these puzzles — that
is why we are solving them — so correctness cannot be verified directly. What
CAN be verified is self-consistency, mechanically and completely:

  * the grid itself coherent — every light on the board, no two lights in one
    direction on the same cell, one clue number per square, nothing uncrossed
    (check_geometry, which needs no fill and is what puzzle_integrity's GRID
    flag runs over the corpus)
  * every entry answered (a partial fill would publish a half-solved puzzle)
  * every answer the length the grid wants
  * letters only, so "?" and "TBC" can't sneak in as an answer
  * every answer's stated definition words of its clue, at one end of it
    (check_definitions)
  * every crossing cell agreeing between its across and its down
  * every answer a blog we hold for the puzzle names (tools/corroborate.py's
    sources), where it names one: a cell no down word crosses is checked by
    nothing else, and a blog that wrote the puzzle up is the answer key we
    were solving without

A 15x15 has around 60 crossings. A fill that satisfies all of them is not
proven right, but it cannot be casually wrong either: one bad answer normally
breaks three or four crossings. Anything short of a clean sheet writes nothing
at all and exits non-zero, because a puzzle with no answers is honest and a
puzzle with wrong answers is worse than useless to someone learning.

Solutions written this way are marked in the file's `solutions` detail, so the
site can say whose answers these are, refresh_unsolved keeps re-fetching until
the paper publishes, and the official key — when it lands — grades this fill
automatically instead of quietly replacing it.

Usage:
  python3 tools/apply_solution.py 30080 --fill fill.json --model opus
  python3 tools/apply_solution.py 30080 --fill fill.json --check-only
"""
import argparse
import datetime
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_puzzle import (read_puzzle_file, reindex,  # noqa: E402
                          resolve_puzzle, write_puzzle_file)
from grid_fill import MIN_CHECKED_RATIO  # noqa: E402 — the authoring rulebook's floor
from series import official_key  # noqa: E402
import corroborate  # noqa: E402
from definitions import QUOTES  # noqa: E402
import provenance  # noqa: E402
from groups import entry_id  # noqa: E402


def normalise(answer):
    """"POPULAR FRONT" -> "POPULARFRONT". Solutions are stored as bare letters;
    the word breaks live in the clue's separators, which come from the paper."""
    return re.sub(r"[^A-Z]", "", str(answer).upper())


def check_geometry(puzzle):
    """Do the entries describe a COHERENT GRID? Returns a list of problems.

    There is no block map in the puzzle format. The geometry IS the entry list:
    a start cell, a direction and a length per light, inside the puzzle's stated
    dimensions, and the shape of the grid has to be read back out of that. So a
    grid that was guessed or built off the wrong template can satisfy every
    length and every crossing and still be nonsense, and nothing else here would
    say so.

    The rules, each of which holds in every one of the 13,397 grids in puzzles/:

      * every light lies on the board, whole
      * no two lights in the same direction share a cell — two acrosses on one
        row means a template with the wrong blocks or a light split in two
      * lights starting in the same square carry the same clue number, because
        they are the same numbered square
      * every light longer than one cell is crossed by a light in the other
        direction; a cryptic has no unchecked word
      * checked cells are at least MIN_CHECKED_RATIO of the grid, the floor
        grid_fill applies to a grid we author ourselves. Imported rather than
        restated: one number, whether the grid arrived from a paper or from us.

    Fill-independent on purpose. An unsolved puzzle has a grid too, and the
    model-solve gate has to settle whether the grid is real BEFORE it weighs a
    fill against it — a fill checked against an incoherent grid proves nothing.
    """
    problems = []
    dims = puzzle.get("dimensions") or {}
    cols, rows = dims.get("cols"), dims.get("rows")
    if not cols or not rows:
        problems.append("the puzzle states no grid dimensions")

    placed, cells, starts = [], defaultdict(list), defaultdict(list)
    for entry in puzzle.get("entries") or []:
        eid = entry_id(entry)
        pos = entry.get("position") or {}
        x, y = pos.get("x"), pos.get("y")
        length, direction = entry.get("length"), entry.get("direction")
        if (direction not in ("across", "down")
                or not all(isinstance(v, int) for v in (x, y, length)) or length < 1):
            problems.append(f"{eid}: position {pos}, length {length!r}, "
                            f"direction {direction!r} does not place a light")
            continue
        across = direction == "across"
        far_x, far_y = (x + length - 1, y) if across else (x, y + length - 1)
        if x < 0 or y < 0 or (cols and far_x >= cols) or (rows and far_y >= rows):
            problems.append(f"{eid}: {length} cells {direction} from ({x},{y}) "
                            f"runs off a {cols}x{rows} grid")
            continue
        placed.append(entry)
        starts[(x, y)].append(entry)
        for i in range(length):
            cells[(x + i, y) if across else (x, y + i)].append(entry)

    for cell, occupants in sorted(cells.items()):
        for direction in ("across", "down"):
            same = sorted(entry_id(e) for e in occupants if e["direction"] == direction)
            if len(same) > 1:
                problems.append(f"cell {cell}: {len(same)} {direction} lights "
                                f"share it — " + ", ".join(same))

    for cell, here in sorted(starts.items()):
        if len({e.get("number") for e in here}) > 1:
            detail = ", ".join(f"{entry_id(e)} is numbered {e.get('number')}"
                               for e in sorted(here, key=lambda e: entry_id(e)))
            problems.append(f"cell {cell}: one square, {len(here)} clue "
                            f"numbers — {detail}")

    for entry in placed:
        if entry["length"] < 2:
            continue
        x, y = entry["position"]["x"], entry["position"]["y"]
        across = entry["direction"] == "across"
        crossed = any(
            o["direction"] != entry["direction"]
            for i in range(entry["length"])
            for o in cells[(x + i, y) if across else (x, y + i)])
        if not crossed:
            problems.append(f"{entry_id(entry)}: {entry['length']} cells "
                            f"{entry['direction']} from ({x},{y}), crossing nothing")

    if cells:
        checked = sum(1 for occ in cells.values()
                      if len({e["direction"] for e in occ}) > 1)
        ratio = checked / len(cells)
        if ratio < MIN_CHECKED_RATIO:
            problems.append(f"only {ratio:.0%} of the {len(cells)} cells are "
                            f"checked, under the {MIN_CHECKED_RATIO:.0%} a grid needs")
    return problems


def check_fill(puzzle, fill):
    """Return (cells, problems). Never raises on bad input — the caller decides
    what to do with the list, and an empty list is the only thing that writes."""
    problems = []
    by_id = {entry_id(e): e for e in puzzle["entries"]}

    for key in fill:
        if key not in by_id:
            problems.append(f"{key}: not an entry in this puzzle")

    cells = {}
    for entry in puzzle["entries"]:
        raw = fill.get(entry_id(entry))
        if raw is None or not str(raw).strip():
            problems.append(f"{entry_id(entry)}: no answer given")
            continue
        answer = normalise(raw)
        if not answer:
            problems.append(f"{entry_id(entry)}: {raw!r} has no letters in it")
            continue
        if len(answer) != entry["length"]:
            problems.append(
                f"{entry_id(entry)}: {raw!r} is {len(answer)} letters, grid wants {entry['length']}")
            continue
        x, y = entry["position"]["x"], entry["position"]["y"]
        for i, ch in enumerate(answer):
            cell = (x + i, y) if entry["direction"] == "across" else (x, y + i)
            cells.setdefault(cell, {})[entry_id(entry)] = ch

    crossings = 0
    for cell, occupants in sorted(cells.items()):
        if len(occupants) < 2:
            continue
        crossings += 1
        if len(set(occupants.values())) > 1:
            detail = ", ".join(f"{k}={v}" for k, v in sorted(occupants.items()))
            problems.append(f"cell {cell}: crossing letters disagree — {detail}")
    return cells, crossings, problems


def check_sources(puzzle, fill, sources=None):
    """Every answer another source prints for this puzzle that the fill does
    not have, as problems. A fill that agrees with its own crossings can still
    differ from the blog in an unchecked cell, and a written fill outranks a
    blog when corroborate settles the two, so a disagreement is refused here,
    before it is written, or it ships. A blog answer the fill's own crossings
    rule out (corroborate's grid rule) is the blog's misparse and is let go."""
    filled = {**puzzle, "entries": [{**e, "solution": normalise(fill.get(entry_id(e), ""))}
                                    for e in puzzle["entries"]]}
    problems = []
    for d in corroborate.resolve(filled, sources):
        if d.field != "answer" or d.rule == "grid":
            continue
        for value, src in d.candidates.items():
            if value != d.primary:
                problems.append(f"{d.entry}: the fill has {d.primary}, but "
                                f"{' and '.join(sorted(src))} gives {value}. A blog that wrote the "
                                "puzzle up is right far more often than a cold solve: re-parse this clue")
    return problems


#: Words that may stand between a definition and its end of the clue: link
#: words ("As theatre patron, agree: poor play") and example markers.
LINK_WORDS = {
    "a", "an", "the", "as", "to", "with", "such", "being", "in", "its", "it", "this",
    "so", "and", "for", "of", "from", "by", "is", "are", "be", "gets", "get", "that",
    "what", "here", "one", "ones", "perhaps", "say", "maybe", "possibly", "or", "at",
    "on", "s", "i", "im", "you", "we", "these", "those", "thus", "how", "when",
    "where", "which", "who", "like", "given", "giving", "makes", "make", "making",
    "can", "could", "may", "might", "would", "will", "ive", "youre", "theyre", "hes",
    "shes", "theres", "heres", "whats"}
#: At most this many link words between a definition and its end.
MAX_LINK = 3
#: A clue that only points at another entry's ("See 5"), and the "(& 6dn.)"
#: some papers print before the head of a linked clue.
SEE_CLUE = re.compile(r"(?i)\s*see\b")
LINKED_PREFIX = re.compile(r"(?i)^\s*\(?&\s*\d+\s*(?:ac|dn|across|down)?\.?\)?\s*")


def _fold(s):
    return re.sub(r"\s+", " ", str(s).translate(QUOTES).lower()).strip()


def _only_links(s):
    words = re.findall(r"[a-z]+", s.replace("'", ""))
    return len(words) <= MAX_LINK and all(w in LINK_WORDS for w in words)


def check_definitions(puzzle, definitions):
    """Every answer's stated definition as problems: missing, not words of its
    clue, or in the middle of it. A definition sits at one end of a cryptic
    clue; words stated as the definition from the middle are wordplay, and an
    answer fitting them is usually the word the wordplay starts from, before
    its change is applied (HALLWAY for "At midpoint of entrance area, having
    change of heart", which is HALFWAY). Over the corpus's 85,199 annotated
    clues the rule refuses 111 correct definitions (0.13%, one puzzle in 25),
    most of them written short of their end, which the refusal says to state
    whole."""
    problems = []
    for entry in puzzle["entries"]:
        eid = entry_id(entry)
        clue = LINKED_PREFIX.sub("", entry["clue"].get("text", ""))
        if not clue.strip() or SEE_CLUE.match(clue):
            continue
        d = _fold(definitions.get(eid) or "")
        if not d:
            problems.append(f"{eid}: no definition given")
            continue
        text = _fold(clue)
        spots = [m.start() for m in re.finditer(re.escape(d), text)]
        if not spots:
            problems.append(f"{eid}: the definition {definitions[eid]!r} is not "
                            f"words of the clue {clue!r}; give them verbatim")
        elif not any(_only_links(text[:i]) or _only_links(text[i + len(d):]) for i in spots):
            problems.append(
                f"{eid}: the definition {definitions[eid]!r} sits in the middle of "
                f"{clue!r}, but a definition sits at one end. Middle words are wordplay, "
                "so this answer is probably the word the wordplay starts from: reparse "
                "until every clue word has a job. If the definition does reach an end, "
                "state all of it")
    return problems


def split_fill(fill):
    """(entry id -> answer, entry id -> definition) from a fill whose values are
    {"answer": ..., "definition": ...}. A bare answer string has no definition,
    which check_definitions refuses."""
    answers, defs = {}, {}
    for eid, value in fill.items():
        if isinstance(value, dict):
            answers[eid], defs[eid] = value.get("answer"), value.get("definition")
        else:
            answers[eid] = value
    return answers, defs


def render_grid(puzzle, cells):
    w, h = puzzle["dimensions"]["cols"], puzzle["dimensions"]["rows"]
    rows = []
    for y in range(h):
        rows.append("".join(
            next(iter(cells[(x, y)].values())) if (x, y) in cells else "."
            for x in range(w)))
    return "\n".join(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    # A puzzle id ("everyman-4166") or the bare number ("4166"), the same pair
    # resolve_puzzle takes and every other tool here accepts. It was type=int,
    # which is what ids looked like before they were namespaced: from then until
    # 2026-08-28 the nightly job solved every unsolved non-Guardian puzzle with a
    # model, passed the id it had, and this exited on `invalid int value` before
    # reading the fill. The solve was paid for and thrown away, nightly.
    ap.add_argument("number", metavar="puzzle",
                    help="puzzle id (everyman-4166) or bare number (4166)")
    ap.add_argument("--fill", required=True,
                    help='JSON file mapping entry id -> answer and definition, e.g. '
                         '{"1-across": {"answer": "POPULAR FRONT", "definition": "Left-wing alliance"}}')
    ap.add_argument("--model", default="unknown", help="which model produced the fill")
    ap.add_argument("--check-only", action="store_true",
                    help="report and exit without touching the puzzle file")
    args = ap.parse_args()

    path = resolve_puzzle(args.number)
    puzzle = read_puzzle_file(path)

    fill = json.loads(Path(args.fill).read_text(encoding="utf-8"))
    if not isinstance(fill, dict):
        raise SystemExit('--fill must be a JSON object of entry id -> '
                         '{"answer": ..., "definition": ...}')
    fill, defs = split_fill(fill)

    cells, crossings, problems = check_fill(puzzle, fill)
    # The grid before the fill: a fill that agrees with an incoherent grid has
    # agreed with nothing, so nothing may be written into one.
    problems = check_geometry(puzzle) + problems + check_definitions(puzzle, defs)
    if not problems:
        problems = check_sources(puzzle, fill)
    print(f"{args.number}: {len(puzzle['entries'])} entries, {len(fill)} answers given, "
          f"{crossings} crossing cells")
    if problems:
        print(f"REJECTED — {len(problems)} problem(s), nothing written:")
        for p in problems[:40]:
            print(f"  {p}")
        if len(problems) > 40:
            print(f"  ... and {len(problems) - 40} more")
        raise SystemExit(1)

    print("all entries answered, all lengths right, every crossing agrees")
    print(render_grid(puzzle, cells))
    if args.check_only:
        return

    if any(e.get("solution") for e in puzzle["entries"]) and not provenance.solution_detail(puzzle):
        # Refuse to paint over the paper's own answers. Only a puzzle that is
        # unsolved, or already carrying a model fill, can be written here.
        raise SystemExit(f"{args.number} already has published solutions — refusing to overwrite")

    for entry in puzzle["entries"]:
        entry["solution"] = normalise(fill[entry_id(entry)])
    detail = {
        "model": args.model,
        "date": datetime.date.today().isoformat(),
        "check": f"{len(puzzle['entries'])} entries, {crossings} crossings, 0 conflicts",
    }
    # Whether a key is ever coming is a fact about the series, not about this
    # solve, so it is read from tools/series.py rather than carried in the fill.
    # It has to be stamped HERE as well as in tools/file_penguin_puzzle.py: a
    # Penguin reprint filed without answers is solved by the nightly job through
    # this function, and a reprint that reached the site without it would have
    # tools/build_seo_pages.py promise official answers "as soon as those
    # appear" for a book that prints its solutions as pictures.
    never = official_key(puzzle.get("series"))
    if never:
        detail["officialKey"] = never
    # No generator: this fills answers into a file a fetcher laid out, and
    # stamping its own name would erase which fetcher that was. What this tool
    # did is recorded in the solutions detail, above.
    puzzle = provenance.with_solution_detail(puzzle, detail)
    path = write_puzzle_file(path, puzzle)
    print(f"wrote {len(puzzle['entries'])} solutions into {path} (marked unofficial)")
    reindex()


if __name__ == "__main__":
    main()
