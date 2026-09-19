#!/usr/bin/env python3
"""Write a `provenance` block into every puzzle that hasn't got one.

    python3 tools/backfill_provenance.py            # write it
    python3 tools/backfill_provenance.py --dry-run  # count what would change
    python3 tools/backfill_provenance.py --report   # the per-bucket tally only

IDEMPOTENT: the provenance it writes is a pure function of the puzzle file, the
file's banner comment and git's record of when the path first appeared, so a
second run rewrites the same bytes and reports 0 changed. That matters because
this is meant to be re-run after a rebase, to catch puzzles other work landed in
the meantime.

WHAT IT DERIVES, AND FROM WHAT

  publisher, series   the id's series prefix, through tools/series.py. Read off
                      the ID, never the `series` FIELD: 35 files (the first
                      cryptics ever fetched) have no series field at all, and
                      reading the field would have filed them under the default
                      without anyone noticing.

  acquiredBy          the tool named in the file's first-line banner, checked
                      against provenance.ACQUISITION_BY_SOURCE — which tools can
                      actually produce this (series, host). The banner names the
                      last tool to WRITE the file rather than the one that
                      fetched it, so it is believed only where it is possible
                      and overruled by the table where it is not. See that
                      table's comment for the two tools that used to overwrite it.

  acquiredOn          the date the file's path first appears in git. That is
                      what is knowable: no fetcher recorded a fetch time, and
                      the commit that added the file is the closest honest
                      statement of when the puzzle arrived. Puzzles added before
                      2026-08-19 were renamed by the id-namespacing commit, so
                      those are re-resolved with `git log --follow` to reach the
                      real first appearance rather than the rename.

  retrievedFrom       the channel that tool reads through — the publisher's own
                      site, a Wayback capture, a blog, a book scan. Derived from
                      acquiredBy so the two can never disagree. This is the
                      distinction sourceUrl could not make: 492 Guardian puzzles
                      and 50 of the 52 Metro ones were recovered from archive
                      captures of pages that no longer exist, and on disk they
                      looked exactly like a same-morning fetch.

  retrievedUrl        the capture actually read, when it differs from sourceUrl.
                      Only the fetcher can know it, so this is carried across
                      from the file rather than derived — null for everything
                      retrieved before the field existed, because the archive
                      URL was printed to stdout and never stored.

  gridOrigin          "reconstructed" for the Penguin-book volumes, whose black
                      squares were worked out from the clue list by
                      tools/reconstruct_grid.py, and "published" everywhere
                      else. Not a guess: file_penguin_puzzle.py is the only tool
                      in the repo that builds a puzzle out of a reconstruction.

  solutionOrigin      "unsolved" when no entry carries an answer; "writeup" or
                      "model" when solutionSource says so; "published"
                      otherwise. That last reading is an argument about this
                      corpus, not an assumption, and it is set out below.

WHY "PUBLISHED" IS HONEST FOR THE FILES THAT SAY NOTHING

The worry this whole field exists to answer is a grid we cold-solved being
indistinguishable from the setter's own key. For this corpus it IS
distinguishable — but NOT by the obvious test, and the wrong reasoning is worth
recording so nobody re-derives it.

THE TEST THAT DOES NOT WORK: "were the answers in the file's first commit?"
15,819 of 15,936 files were already full at their first commit, because fetch
and solve both happen before anything is committed. Worse, of the 443 files we
KNOW are not publisher keys, 440 pass that same test — one commit, 9dc627f,
landed Guardian published-key puzzles and fifteensquared-sourced Cyclops
answers together. The test has almost no discriminating power and must not be
cited as evidence. (Per-file archaeology is also 0.86-1.2s a file, ~4 hours for
the corpus. Don't.)

WHAT ACTUALLY SETTLES IT is an audit of the code that can write an answer,
because the set of such code is small and its whole history is here:

  * The history is complete and unsquashed — 1,052 commits, 2026-07-26 to
    2026-09-18, 640 of them touching puzzles/. There is no bulk import to hide
    behind.
  * Every publisher fetcher takes the answers out of the publisher's own
    payload and cannot invent one: fetch_puzzle.py, fetch_independent.py,
    fetch_observer.py, fetch_globeandmail.py and fetch_metro.py each read a
    solution field off the source document. fetch_wayback.py only stores a
    capture in which every entry already has one.
  * Only three routes produce an answer the publisher did not give, and all
    three mark it, each from its own first commit: apply_solution.py (model,
    a858eb5, 2026-08-12), fetch_privateeye.py (fifteensquared, 8d11dfb,
    2026-09-17) and file_penguin_puzzle.py (model). apply_solution.py has also,
    from that same first commit, refused outright to touch a puzzle that
    already has answers — there was never a version of it that could leave a
    model fill unmarked.
  * The coverage arithmetic corroborates it exactly. solutionSource sits
    precisely where the non-publisher routes ran: 434 of 518 Cyclops, and the
    other 84 Cyclops files have no answers at all — so every Cyclops file that
    HAS answers is labelled. Same for all 5 penguin5. What is left unlabelled
    is entirely series served by publisher fetchers.
  * Finally, only 19 commits in the whole history modify the answers of an
    already-existing file (`git log --diff-filter=M -G'"solution": "[A-Z]'
    -- puzzles/`). Every one was read: that apply_solution run; daily re-fetches
    filling in a Saturday prize puzzle's key about a week after publication
    (+28 to +30 solution lines, one puzzle's worth, from the paper); re-fetches
    replacing misfiled source data; accent-stripping (ROSÉ -> ROSE); and four
    single-letter repairs of garbled transcription — XETOPHILY -> XEROPHILY,
    GETSTEADY -> GETSREADY, HALLWAY -> HALFWAY, CHOCOLOHICS -> CHOCOHOLICS —
    every one of which moves the file TOWARDS the published answer.

So "answers present and no solutionSource" means the publisher's key, and the
87 puzzles carrying no answers at all are recorded as "unsolved" rather than
being quietly counted as anything. If a later import ever breaks that invariant
— someone fills a grid without stamping solutionSource — the argument above
stops holding and the right change is to mark the affected range "unknown"
here, not to keep asserting "published" because this file once did.

The one thing the backfill genuinely cannot recover is which leaf of the
Penguin scan each of the five book puzzles was read off: the solve records that
knew were temporary files, long gone. provenance.book.leaf is null for all five.
"""
import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import provenance  # noqa: E402
from fetch_puzzle import (generator_of, puzzle_files,  # noqa: E402
                          read_puzzle_file, write_puzzle_file)

ROOT = Path(__file__).resolve().parent.parent

# The commit that renamed puzzles/<n>.js to puzzles/<series>-<n>.js
# ("A puzzle's id is its series and its number", 06894ae). A path whose first
# appearance is on or before this is a path that may only have existed since the
# rename, so its real arrival is looked up the slow, correct way.
NAMESPACING_DATE = "2026-08-20"

def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args],
                          capture_output=True, text=True, check=True).stdout


def add_dates():
    """path -> the date it first appears, in ONE traversal of the history.

    --no-renames matters: git's similarity detection pairs near-identical
    puzzle files into renames it invented, and those paths then never show up
    as an A at all. Turning it off is what makes this cover every file rather
    than 15,673 of them.
    """
    out = git("log", "--no-renames", "--diff-filter=A", "--name-only",
              "--format=C %ad", "--date=short", "--", "puzzles/")
    dates, date = {}, None
    for line in out.splitlines():
        if line.startswith("C "):
            date = line[2:].strip()
        elif line.startswith("puzzles/") and line.endswith(".js"):
            dates[line] = date      # newest first, so the last write is the oldest
    return dates


def machine_solved_ever():
    """Every puzzle a model has EVER filled, including ones since overwritten.

    Two tree-wide pickaxes rather than 15,936 per-file histories — those were
    measured at 0.86s each, which is 3.8 hours; these are about a minute
    together. -S counts occurrences of the string per commit and reports the
    commits where the count CHANGED, so a file shows up whether the marker was
    being added or later removed, which is the whole point: fetch_observer.py
    deletes solutionSource the day the real key lands.

    Commit SUBJECTS are no use here and it is worth saying why, because it is
    the obvious thing to try: the nightly cold-solve lands under the very same
    subject as the nightly fetch, "Daily update: fetch latest cryptic /
    annotate backlog". The header banner and the marker are the only signal.
    """
    paths = set()
    for needle in ('Generated by tools/apply_solution.py', '"kind": "model"'):
        out = git("log", "--name-only", "--format=", f"-S{needle}", "--", "puzzles/")
        paths.update(line for line in out.splitlines()
                     if line.startswith("puzzles/") and line.endswith(".js"))

    # A path from before the id-namespacing commit names a file that no longer
    # exists under that name. Resolve it by its number, and ONLY when exactly
    # one puzzle on disk has that number — two papers reaching one number is
    # the collision namespacing exists to prevent, and guessing between them
    # would put one puzzle's history on another's file.
    by_number = {}
    for path in puzzle_files():
        stem = path.stem
        by_number.setdefault(stem.rsplit("-", 1)[-1], []).append(f"puzzles/{path.name}")

    resolved, unresolved = set(), []
    for rel in paths:
        if (ROOT / rel).exists():
            resolved.add(rel)
            continue
        hits = by_number.get(Path(rel).stem.rsplit("-", 1)[-1], [])
        if len(hits) == 1:
            resolved.add(hits[0])
        else:
            unresolved.append(rel)
    return resolved, unresolved


def followed_add_date(rel):
    """The slow, rename-following answer for one path."""
    out = git("log", "--follow", "--diff-filter=A", "--format=%ad",
              "--date=short", "--", rel)
    lines = out.split()
    return lines[-1] if lines else None


def acquired_on(rel, bulk, existing):
    """The earliest defensible arrival date for one path.

    A value already in the file is trusted when it is no later than the bulk
    answer, because the only way an earlier one got there is a previous run's
    rename-following — which is the better answer and costs a subprocess to
    recompute. That is what keeps a re-run cheap: the ~200 pre-namespacing
    files are followed once, ever.
    """
    date = bulk.get(rel)
    if existing and provenance.ISO_DATE.fullmatch(existing or ""):
        return min(existing, date) if date else existing
    if date and date <= NAMESPACING_DATE:
        return followed_add_date(rel) or date
    return date


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="derive and tally, write nothing")
    ap.add_argument("--report", action="store_true",
                    help="the per-bucket tally only, no per-file output")
    args = ap.parse_args(argv)

    bulk = add_dates()
    solved_ever, unresolved = machine_solved_ever()
    buckets = {k: {} for k in ("acquiredBy", "acquiredOn", "retrievedFrom",
                               "retrievedUrl", "gridOrigin", "solutionOrigin")}
    changed = unchanged = 0
    carried = []

    for path in puzzle_files():
        puzzle = read_puzzle_file(path)
        rel = f"puzzles/{path.name}"
        existing = (puzzle.get("provenance") or {}).get("acquiredOn")
        prov = provenance.derive(puzzle, generator_of(path),
                                 acquired_on(rel, bulk, existing),
                                 previously="model" if rel in solved_ever else None)
        if prov.get("previousSolutionOrigin"):
            carried.append(f"{path.stem} ({prov['solutionOrigin']} now)")
        for field in ("gridOrigin", "solutionOrigin", "acquiredBy", "retrievedFrom"):
            buckets[field][prov[field]] = buckets[field].get(prov[field], 0) + 1
        for field, unknown in (("acquiredOn", prov["acquiredOn"] == "unknown"),
                               ("retrievedUrl", not prov["retrievedUrl"])):
            key = "not recorded" if unknown else "recorded"
            buckets[field][key] = buckets[field].get(key, 0) + 1

        if puzzle.get("provenance") == prov:
            unchanged += 1
            continue
        changed += 1
        if not args.dry_run:
            # The banner is preserved, not restamped: this tool fills a field in
            # a file a fetcher laid out, and putting its own name on top would
            # destroy the very acquisition record it is here to write down.
            write_puzzle_file(path, provenance.place(puzzle, prov))
        if not args.report and args.dry_run:
            print(f"would write provenance into {path.name}")

    verb = "would change" if args.dry_run else "changed"
    print(f"\n{changed + unchanged} puzzles: {verb} {changed}, already correct {unchanged}")
    for field in ("acquiredBy", "acquiredOn", "retrievedFrom", "retrievedUrl",
                  "gridOrigin", "solutionOrigin"):
        print(f"\n  {field}")
        for value, n in sorted(buckets[field].items(), key=lambda kv: -kv[1]):
            print(f"    {n:6d}  {value}")
    print(f"\n  {len(carried)} grid(s) this repo once solved itself and the "
          f"publisher has since confirmed:")
    for line in sorted(carried):
        print(f"    {line}")
    if unresolved:
        # Said out loud rather than swallowed: a pre-namespacing path whose
        # number now belongs to more than one puzzle is a piece of history this
        # backfill is DECLINING to attach, not one it failed to find.
        print(f"\n  {len(unresolved)} machine-solve record(s) could not be tied to "
              f"exactly one puzzle on disk and were dropped:")
        for rel in sorted(unresolved):
            print(f"    {rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
