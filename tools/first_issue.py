#!/usr/bin/env python3
"""Try every series' first puzzle while we lack it.

    python3 tools/first_issue.py            # try each missing No 1, say where it looked
    python3 tools/first_issue.py --dry-run  # say what it would try, fetch nothing
    python3 tools/first_issue.py --self-test

Paul, 2026-10-02: "Puzzle 1 is a special puzzle that is good to solve ... our
backfill should always try to get the first puzzles". A walk backwards stops
where its source runs out, and a first issue is often not where the run ends:
the Guardian serves Everyman No 1 (1946) thousands of numbers below the oldest
Everyman it serves in sequence. So every run asks each series' source for its
first issue directly, by number (series.first_number), until it is on disk.

SOURCES has one row per series with a first issue: the command that fetches
that one puzzle, and where it looks, or None and the reason no source can be
asked for it. A missing No 1 prints where it looked and what came back. Run by
tools/extend_archive.py, which the pre-reset burn runs at every start.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import series as series_meta  # noqa: E402
from puzzle_paths import puzzle_path  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
TIMEOUT = 300

_BLOG = ("filed only by tools/file_times_puzzles.py from timesforthetimes.co.uk, "
         "which began in 2006 and files no single number on request")
_TELEGRAPH = ("the Telegraph bucket's calendars start 2015 (cryptic), 2020 (Toughie) "
              "and 2022 (Sunday Toughie), and bigdave44.com starts in 2009 "
              "(tools/fetch_telegraph.py, tools/file_telegraph_puzzles.py)")

# series -> (command with {n} for the number, where it looks) or (None, why not)
SOURCES = {
    "cryptic": (["python3", "tools/fetch_puzzle.py", "cryptic-{n}"],
                "theguardian.com/crosswords/cryptic/{n} and /prize/{n}"),
    "quiptic": (["python3", "tools/fetch_puzzle.py", "quiptic-{n}"],
                "theguardian.com/crosswords/quiptic/{n}"),
    "everyman": (["python3", "tools/fetch_puzzle.py", "everyman-{n}"],
                 "theguardian.com/crosswords/everyman/{n}"),
    # The Indy feed is keyed by day, so it is asked for each paper's launch day.
    "independent": (["python3", "tools/fetch_independent.py", "861007"],
                    "the Independent feed's c_861007.xml (launch day, 1986-10-07)"),
    "indysunday": (["python3", "tools/fetch_independent.py", "900128"],
                   "the Independent feed's c_900128.xml (launch day, 1990-01-28)"),
    "cyclops": (["python3", "tools/fetch_privateeye.py", "{n}"],
                "private-eye.co.uk/pictures/crossword/download/{n}.puz"),
    "ftcryptic": (None, "fifteensquared.net's FT posts start in 2009, the FT PDFs "
                        "Wayback holds in 2006 (tools/ft_pdf_puzzles.py index), and the "
                        "archive.org FT scans in 1971 (tools/file_archive_org_puzzles.py)"),
    "listener": (None, "filed from the Listener Team's archive by tools/listener_puzzles.py"),
    "telegraph": (None, _TELEGRAPH),
    "toughie": (None, _TELEGRAPH),
    "sundaytel": (None, _TELEGRAPH),
    "sundaytough": (None, _TELEGRAPH),
    "times": (None, _BLOG + "; archive.org's pub_times scans The Times of 1930 "
                      "(Nos 1-~270), which no filer reads yet"),
    "timesquick": (None, _BLOG + "; its parse holds Quick Cryptic No 1 (2014-03-10)"),
    "timesjumbo": (None, _BLOG),
    "sundaytimes": (None, _BLOG),
    "timesclub": (None, _BLOG),
    "tls": (None, _BLOG),
    "mephisto": (None, _BLOG),
}


def wanted():
    """[(series, first number)] for every series that has a first issue."""
    return [(s, n) for s in series_meta.SERIES
            if (n := series_meta.first_number(s)) is not None]


def last_line(text):
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-1].strip()[:300] if lines else "no output"


def try_first(series, number, dry_run=False, run=subprocess.run):
    """One line saying whether the series' first issue is held, fetched now,
    or not available and where we looked."""
    pid = f"{series}-{number}"
    if puzzle_path(series, number).exists():
        return f"{pid}: held"
    cmd, where = SOURCES[series]
    if cmd is None:
        return f"{pid}: not available: no source to ask, {where}"
    where = where.format(n=number)
    if dry_run:
        return f"{pid}: would try {where}"
    try:
        out = run([a.format(n=number) for a in cmd], cwd=REPO, capture_output=True,
                  text=True, timeout=TIMEOUT)
        said = last_line(out.stderr + out.stdout) if out.returncode else last_line(out.stdout)
    except subprocess.TimeoutExpired:
        said = f"no answer in {TIMEOUT}s"
    if puzzle_path(series, number).exists():
        return f"{pid}: fetched now from {where}"
    return f"{pid}: not available: looked at {where}: {said}"


def self_test():
    bad = 0
    missing = sorted(s for s, _ in wanted() if s not in SOURCES)
    extra = sorted(set(SOURCES) - {s for s, _ in wanted()})
    if missing or extra:
        print(f"FAIL SOURCES lacks {missing}, has extra {extra}", file=sys.stderr)
        bad += 1
    calls = []

    def fake(cmd, **_):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, "", "HTTP Error 404: Not Found\n")
    got = try_first("cyclops", 999999, run=fake)
    if calls != [["python3", "tools/fetch_privateeye.py", "999999"]] or \
            got != ("cyclops-999999: not available: looked at private-eye.co.uk/pictures/"
                    "crossword/download/999999.puz: HTTP Error 404: Not Found"):
        print(f"FAIL try_first on a 404: {got!r} after {calls}", file=sys.stderr)
        bad += 1
    got = try_first("times", 999999, run=fake)
    if not got.startswith("times-999999: not available: no source to ask"):
        print(f"FAIL try_first with no source: {got!r}", file=sys.stderr)
        bad += 1
    print(f"first issue self-test FAILED: {bad}" if bad else "first issue self-test: 3 cases pass")
    return 1 if bad else 0


def main(argv):
    if "--self-test" in argv:
        return self_test()
    for series, number in wanted():
        print(try_first(series, number, dry_run="--dry-run" in argv), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
