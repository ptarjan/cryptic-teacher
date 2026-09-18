#!/usr/bin/env python3
"""Is the puzzle CORPUS sound — before anyone spends a model on annotating it?

Run it:

    python3 tools/puzzle_integrity.py            # every defect, with a per-check tally
    python3 tools/puzzle_integrity.py --quiet     # only the defects; silent when clean

Everything else in tools/ checks the work we ADD to a puzzle: validate_annotations.py
grades the annotation, coverage_report.py counts what each series holds. Nothing
checked the puzzle underneath, so a puzzle that arrived wrong stayed wrong and the
cost landed later — a duplicate gets annotated twice at full model price and then
shows up twice on the site, and a clue whose enumeration contradicts its own answer
teaches a learner to count wrong. Both are cheap to find mechanically and neither is
findable by eye at 6,800 puzzles. This is that sweep.

The flags, in the order they matter:

  DUPLICATE two or more files holding the same puzzle. Content-hashed over the
            entries — clue, solution, grid position, length — and over the grid
            dimensions, deliberately NOT over id, number, date, name, setter or
            annotation, because the question is whether the PUZZLE is the same and
            a resend arrives under a fresh number and date. Copies are grouped, so
            three files of one puzzle print as one group of three, not three pairs.
  LENGTH    an answer that contradicts the length the data itself states. Two
            statements exist per entry and both are checked: the grid's `length`
            field, and the (5,4)-style enumeration at the end of the clue. On a
            LINKED clue the enumeration is allowed to count either that light or
            the whole group, because the papers in this corpus do both — see
            check_length, which has the numbers. Three findings are excepted by
            name, in PUBLISHED_WRONG: what the Guardian printed there cannot be
            reconciled with the grid it printed beside it.
  CROSS     two entries that share a grid cell and disagree about its letter. One
            wrong answer normally breaks three or four of these, so a clean sheet
            is real evidence the fill is the paper's and not a mangling of it.
  SHAPE     data that cannot be right whatever the puzzle says: no entries at all,
            a clue that is blank once its enumeration is removed, a solution
            carrying something other than letters, the same entry id twice in one
            puzzle, a date in the future or before EARLIEST_YEAR, or an indexed
            file that is not on disk.

An entry whose solution carries non-letters is reported once, as SHAPE, and then
left out of LENGTH and CROSS — its letter count is not a second defect, it is the
same one counted again.

Puzzles published without answers (Saturday prize crosswords, until the paper
catches up about a week later) are not a defect: LENGTH and CROSS simply have
nothing to weigh for them and skip. Only entries that actually carry a solution
are checked, so an empty grid passes and a half-filled one is still checked as far
as it goes.

Cost: one pass, one read per file, no network. All four checks together read the
whole corpus in about five seconds — 6,859 puzzles, ~200k clues, on 2026-09-17 —
so every check is on by default and none sits behind a flag. Nothing here is
expensive enough to be worth the confusion of an off-by-default check.

Exits 1 if anything is flagged, so the nightly can alert on it. It reports and
never writes: a defect here is a fetcher bug or a bad source page, and the fix
belongs in the fetcher or in a re-fetch, not in a repair pass over the files.
"""

import hashlib
import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_solution import check_fill, normalise  # noqa: E402 — the crossing check
from fetch_puzzle import (ENUMERATION, PER_LIGHT_ENUMERATION,  # noqa: E402
                          PUZZLE_DIR, is_bare_letters, is_continuation,
                          read_puzzle_file)

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "puzzles" / "index.json"

# No cryptic crossword in this corpus predates the Guardian's, which began in 1929.
# A date below this is a page the publisher mis-filed or a fetcher that lost one,
# not an old puzzle. A backstop only: the Guardian serves such a page — its
# /crosswords/cryptic/1183 answers 200 with Quiptic 1,183's clues under a date of
# 1934-01-18 — but 1934 clears this bar, so what actually refuses it is the
# date-against-webPublicationDate check in fetch_puzzle.convert().
EARLIEST_YEAR = 1930

# The LENGTH findings that are the PAPER, not the data we made of it: an
# enumeration no reading of the grid the Guardian published can satisfy, so no
# fetcher or repair can ever clear them and they would otherwise sit in the
# report for ever, teaching everyone to skim it.
#
# Keyed by puzzle AND by the whole finding, because the point is to forgive these
# three sentences and nothing else. Any other defect in the same clue — a changed
# answer, a light regrouped, a second count gone wrong — reads as a different
# finding and still reports.
PUBLISHED_WRONG = {
    ("cryptic-23536", "23-down: clue says (5) = 5, answer holds 7"):
        "ERRHINE fills the seven cells the grid gives it under a clue printed (5)",
    ("cryptic-25949",
     "1-down + 26-across: clue says (4,5) = 9, answer holds 4 alone or 13 linked"):
        "1-down ASIL is counted (4,5) for ASIL NADIR, but NADIR is 28-across under "
        "a clue of its own and the paper linked 1-down to 26-across PANOPLIED (9)",
    ("cryptic-27173",
     "29-down + 23-down: clue says (4) = 4, answer holds 4 alone or 10 linked"):
        "29-down SHOE is counted (4) for its own light while 23-down OXFORD points "
        "at it, so the ten cells of OXFORD SHOE are nowhere counted",
}

# PER_LIGHT_ENUMERATION names the series whose linked clues are enumerated one
# light at a time, and is imported rather than restated: the fetcher dissolves a
# group whose every leg counts its own light (dissolve_false_groups), and this
# check forgives exactly that shape. Two lists would let one paper be forgiven
# here and taken apart there. The Guardian and the Independent count the whole
# answer on the leading clue, so they are held to the strict reading and a group
# that has gone wrong there still shows up — with one exception that is about
# the CLUE and not the paper: a leg printed "See 3 (6)", which the Guardian did
# routinely before about 2015, is counting its own cells, and check_length reads
# it that way in every series. fetch_puzzle.is_continuation decides which clues
# those are.


def content_hash(puzzle):
    """A puzzle's identity as a solver would judge it: the same clues, in the same
    cells, with the same answers, in a grid of the same size. Entries are sorted so
    that a re-fetch which happens to emit them in another order still matches."""
    entries = sorted(
        (e.get("id"), e.get("number"), e.get("direction"),
         (e.get("position") or {}).get("x"), (e.get("position") or {}).get("y"),
         e.get("length"), e.get("clue"), e.get("solution"))
        for e in puzzle.get("entries") or []
    )
    dims = puzzle.get("dimensions") or {}
    blob = json.dumps([dims.get("cols"), dims.get("rows"), entries], ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def check_shape(puzzle, today, flags):
    """Defects visible in one entry on its own, plus the puzzle-level ones.

    Returns the entries fit to weigh for LENGTH and CROSS — those whose solution is
    present and is letters only. Everything else has already been reported here."""
    pid = puzzle["id"]
    entries = puzzle.get("entries") or []
    if not entries:
        flags.append(("SHAPE", pid, "no entries at all"))
        return []

    ms = puzzle.get("date")
    if ms is None:
        # coverage_report.py owns DATELESS; it can see which series it thins out.
        pass
    else:
        d = datetime.fromtimestamp(ms / 1000, timezone.utc).date()
        if d > today:
            flags.append(("SHAPE", pid, f"dated {d}, which is in the future"))
        elif d.year < EARLIEST_YEAR:
            flags.append(("SHAPE", pid, f"dated {d}, before cryptics existed"))

    seen, checkable = set(), []
    for e in entries:
        eid = e.get("id")
        if eid in seen:
            flags.append(("SHAPE", pid, f"entry id {eid} appears twice"))
        seen.add(eid)

        # A clue is its words. Strip the enumeration before judging it empty, so
        # " (1,6,3,1,4)" — an entry the fetcher got the count for and not the text —
        # reads as the blank it is.
        #
        # Unless the paper printed it blank, which setters do as the trick itself:
        # cryptic-30098's 12-across is wordless so that its own number is the only
        # thing left pointing at NOONDAY, and cryptic-29345's 5-down is wordless
        # over (1,6,3,1,4) for I HAVEN'T GOT A CLUE. Both are the joke and must
        # never be filled in or filtered out. fetch_puzzle.convert() settles which
        # is which at fetch time, where the paper's own data is still in front of
        # it, and records the answer as clueMissing — so this reads that field
        # rather than guessing again from the text and reaching a different
        # verdict. An unmarked blank clue is still a defect and still reported.
        clue = e.get("clue") or ""
        if not e.get("clueMissing") and not ENUMERATION.sub("", clue).strip():
            flags.append(("SHAPE", pid, f"{eid}: clue is blank"))

        solution = e.get("solution")
        if not solution:
            continue
        # One rule, spelled in the fetcher: a solution is A-Z and nothing else.
        # convert() now refuses to WRITE anything that fails it — a page serving
        # a masked answer ("T?S?R", Guardian cryptic 28,691 3-down) is stored
        # unsolved instead — so anything caught here arrived before that guard
        # or from a fetcher that does not go through convert().
        if not is_bare_letters(solution):
            flags.append(("SHAPE", pid, f"{eid}: solution {solution!r} is not bare letters"))
            continue
        checkable.append(e)
    return checkable


def check_length(puzzle, checkable, flags):
    """The two length statements the data makes about an answer, against the answer.

    Grid length is per entry, and is checked per entry: an answer that does not fit
    its own light is wrong however the clue is printed.

    The enumeration is the looser one, because a LINKED clue is enumerated two ways
    and this corpus holds both. The Guardian and the Independent print the whole
    answer's count on the light that carries the clue and nothing on the others, so
    29,069's "(6,8,9)" belongs to LONDON + SYMPHONY + ORCHESTRA together. Private
    Eye prints each light its own count instead, on every light including the
    leading one: Cyclops 401's 2-down reads "(& 22dn.) … (4-6)" for its own ten
    cells while 22-down reads "see 2dn. (6)" for its six. Measured across 769
    linked Cyclops groups, 760 leading lights and 778 continuations count only
    their own light — and then nine leaders and two continuations print the group's
    whole count, in the same paper, so it is not even a rule per publisher.

    So a linked clue's enumeration is required to equal its own light or the whole
    group, and anything else is the defect. That is weaker than the unlinked check
    deliberately: the alternative is 1,538 Cyclops clues reported for obeying their
    own paper's convention, and a check nobody can read is a check nobody reads.
    The grid-length test above is untouched and still holds every light to its own
    cells, which is where a wrong ANSWER shows up; this one catches a wrong COUNT,
    and it still caught 29,069, whose clue promised 23 letters over a group the
    Guardian's own data had truncated to 15."""
    pid = puzzle["id"]
    by_id = {e["id"]: e for e in puzzle.get("entries") or []}
    for e in checkable:
        eid, solution = e["id"], e["solution"]
        if len(solution) != e.get("length"):
            flags.append(("LENGTH", pid, (f"{eid}: {solution} is {len(solution)} letters, "
                                          f"grid wants {e.get('length')}")))
            continue

        m = ENUMERATION.search(e.get("clue") or "")
        if not m:
            # A continuation leg ("See 23") carries no count of its own; its length
            # is stated once, on the leg that holds the clue.
            continue
        counts = [int(n) for n in re.findall(r"\d+", m.group(1))]
        if not counts:
            continue
        group = e.get("group") or [eid]
        legs = [by_id.get(gid, {}).get("solution") for gid in group]
        if any(not s for s in legs):
            continue  # part of the answer is unpublished; nothing to compare yet
        held = sum(len(normalise(s)) for s in legs)
        # A counted continuation counts its own light, in any paper. "See 2 (6)"
        # has no wordplay to count anything else with: cryptic-23578's 7-down is
        # that exactly, six cells of IGNATIUS LOYOLA whose "(8,6)" is printed
        # where it belongs, on 2-down. The Guardian did this routinely before
        # about 2015, so the reading is not a licence handed to a publisher but
        # one the clue itself asks for — see fetch_puzzle.is_continuation.
        per_light = (puzzle.get("series") in PER_LIGHT_ENUMERATION
                     or is_continuation(e.get("clue")))
        if sum(counts) == held or (len(group) > 1 and per_light
                                   and sum(counts) == len(solution)):
            continue
        where = eid if len(group) == 1 else " + ".join(group)
        holds = f"{held}" if len(group) == 1 else f"{len(solution)} alone or {held} linked"
        finding = (f"{where}: clue says ({m.group(1)}) = "
                   f"{sum(counts)}, answer holds {holds}")
        if (pid, finding) in PUBLISHED_WRONG:
            continue
        flags.append(("LENGTH", pid, finding))


def check_cross(puzzle, checkable, flags):
    """Crossing-letter agreement, from tools/apply_solution.py — the same check that
    gates a model-solved grid before it is written. It is handed only the entries
    that are answered and the right length, so every problem it returns is a
    crossing conflict and nothing has to be re-derived here."""
    if not checkable:
        return
    fill = {e["id"]: e["solution"] for e in checkable}
    _, _, problems = check_fill({**puzzle, "entries": checkable}, fill)
    for p in problems:
        flags.append(("CROSS", puzzle["id"], p))


def audit(rows, today):
    """One flat list of (flag, puzzle id, what) plus the duplicate groups."""
    flags = []
    by_content = defaultdict(list)
    for row in rows:
        path = PUZZLE_DIR / row["file"]
        if not path.exists():
            flags.append(("SHAPE", row["id"], f"indexed as {row['file']}, not on disk"))
            continue
        puzzle = read_puzzle_file(path)
        by_content[content_hash(puzzle)].append(puzzle["id"])
        checkable = check_shape(puzzle, today, flags)
        check_length(puzzle, checkable, flags)
        check_cross(puzzle, checkable, flags)
    copies = sorted(sorted(ids) for ids in by_content.values() if len(ids) > 1)
    return flags, copies


def main(argv):
    quiet = "--quiet" in argv
    started = time.time()
    index = json.loads(INDEX.read_text())
    rows = index["puzzles"]
    flags, copies = audit(rows, datetime.now(timezone.utc).date())

    for ids in copies:
        print(f"DUPLICATE {len(ids)} files hold the same puzzle: " + ", ".join(ids))
    by_flag = defaultdict(list)
    for flag, pid, what in flags:
        by_flag[flag].append((pid, what))
    for flag in ("LENGTH", "CROSS", "SHAPE"):
        for pid, what in by_flag[flag]:
            print(f"{flag:<9} {pid:<22} {what}")

    total = len(flags) + sum(len(ids) for ids in copies)
    if quiet:
        return 1 if total else 0

    elapsed = time.time() - started
    print(f"\n{len(rows)} puzzles read in {elapsed:.1f}s")
    print(f"  DUPLICATE {sum(len(i) for i in copies)} files in {len(copies)} groups")
    for flag in ("LENGTH", "CROSS", "SHAPE"):
        print(f"  {flag:<9} {len(by_flag[flag])}")
    if not total:
        print("\nno duplicates, every stated length agrees, every crossing agrees")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
