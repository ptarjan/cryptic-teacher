#!/usr/bin/env python3
"""Re-place the new puzzle files a cross-file DATE finding holds out of a commit.

Two editions read at the same minute are each placed (file_archive_org_puzzles.
placed, indy_count_off) against the puzzles filed so far, and neither is a
filed neighbour of the other: their filed neighbours may not exist yet, so no
count checks either. One misread title (3661 for the 3667 of 1998-07-20) then
files beside a right one (3666 of 07-18), and puzzle_integrity's DATE finding
("dated 1998-07-18, not after independent-3661's 1998-07-20") holds both out of
every commit, for ever: nothing places them again once their neighbours are
filed.

The rule (replace_pair): for each DATE finding naming two new files (not in
HEAD), each file is placed again, as the filer places a title, against the
series as filed now without the files held out (placement: placed(), its
neighbours' count, and the paper's own count check). A file the count now
contradicts while its partner agrees is deleted from the working tree, never
committed, and its edition's ledger row is replaced by a bare row (no
"inputs": due_reason's "never read"), so the edition is read again with its
full neighbours and files under the number its date implies. Both agreeing or
both contradicted, nothing is changed: both stay held.

    python3 tools/replace_held_pair.py <tree>   < "<path>\\t<why>" lines of
    puzzle_integrity.py --refused

prints each file it deleted. Never raises: a failure is reported on stderr and
the commit goes ahead as it would have.
"""
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

FINDING = re.compile(r"DATE (\S+): dated (\d{4}-\d\d-\d\d), not after (\S+)-(\d+)'s (\d{4}-\d\d-\d\d)")


def pairs_of(refused):
    """[(path, other path)] for each DATE finding in `refused` ({path: why text}) whose two puzzles
    are both refused files: the finding's puzzle and the numbered one it is not after."""
    by_id = {}
    for path in refused:
        m = re.fullmatch(r"(puzzles/.+/)([^/]+)\.json", path)
        if m:
            by_id[m.group(2)] = path
    out = []
    for path, why in refused.items():
        for pid, _day, series, number, _other_day in FINDING.findall(why):
            a, b = by_id.get(pid), by_id.get(f"{series}-{number}")
            if a and b and a != b and (a, b) not in out and (b, a) not in out:
                out.append((a, b))
    return out


def read_puzzle(path):
    """(id, number, date) of the puzzle file at `path`, or None when it does not parse."""
    try:
        p = json.loads(Path(path).read_text(encoding="utf-8"))
        return p["id"], int(p["number"]), datetime.date.fromisoformat(p["date"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def series_held(tree, series, days, exclude):
    """{number: date} of the puzzles of `series` in `tree` (excluding the relative paths `exclude`)
    in the year folders of `days` and the years either side (the paper's count reaches 60 days, its steady
    neighbours 150 puzzles)."""
    years = {d.year + k for d in days for k in (-1, 0, 1)}
    held = {}
    for year in sorted(years):
        for path in sorted((Path(tree) / "puzzles" / series / str(year)).glob("*.json")):
            if path.relative_to(tree).as_posix() in exclude:
                continue
            got = read_puzzle(path)
            if got and got[0].rsplit("-", 1)[0] == series:
                held[got[1]] = got[2]
    return held


def contradicted(fa, paper, number, day, held):
    """Why the filer's placement of title `number` on `day` against `held` ({number: date}) is not
    `number`, or None when it keeps it: placed() (the count its neighbours give, date order), then
    the paper's own count check."""
    held = fa.Held(held)
    got, why = fa.placed(number, day, held)
    if got is None:
        return why
    if got != number:
        return f"No {number} on {day} is No {got} by the count of its filed neighbours"
    check = {fa.GALE_INDEPENDENT.key: fa.indy_count_off, fa.GALE_SUNDAY_TIMES.key: fa.sunday_count_off}.get(paper.key)
    return check(number, day, held) if check else None


def paper_of_series(fa, series):
    """The Paper whose filer files `series`, or None."""
    for filer in fa.FILERS.values():
        for p in fa.run_papers(filer):
            if p.series == series:
                return p
    return None


def in_head(tree, path):
    return subprocess.run(["git", "-C", str(tree), "cat-file", "-e", f"HEAD:{path}"],
                          capture_output=True).returncode == 0


def reset_edition(fa, paper, pid, ledger=None):
    """Append to `paper`'s ledger a bare row for the edition whose last row wrote puzzle `pid`: no
    "inputs", so due_reason says "never read" and the edition is read again whatever its old verdict
    said. The filed state is the file, not the row's "wrote": a file gone with the row left would
    only be a LOST_WRITE reread, and one dated before REREAD_LOST would never be asked. Returns the
    edition's name, or None when no row wrote it (it is unread already)."""
    ledger = fa.ledger_of(fa.CACHE, paper, ledger)
    needle = f'"id": "{pid}"'
    edition = None
    try:
        with open(ledger, "rb") as f:
            for line in f:
                if needle.encode() in line:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if any(v.get("id") == pid for v in row.get("verdicts") or ()):
                        edition = row["edition"]
    except OSError:
        return None
    if edition is None:
        return None
    import scan_queue
    scan_queue.append(Path(ledger), [{"edition": edition, "replaced": pid}])
    return edition


def replace_pair(tree, refused, fa=None, ledger=None):
    """Delete from `tree` each new refused puzzle file of a DATE pair that its series' count now
    contradicts while its partner's agrees (see the module doc). `refused` is {path: why}.
    Returns [(deleted path, edition or None, why)]."""
    pairs = pairs_of(refused)
    if not pairs:
        return []
    if fa is None:
        import file_archive_org_puzzles as fa
    tree = Path(tree).resolve()
    reads = {p: read_puzzle(tree / p) for pair in pairs for p in pair}
    new = {p: r for p, r in reads.items() if r and not in_head(tree, p)}
    verdict = {}
    for a, b in pairs:
        if a not in new or b not in new:
            continue
        for path in (a, b):
            if path in verdict:
                continue
            pid, number, day = new[path]
            series = pid.rsplit("-", 1)[0]
            paper = paper_of_series(fa, series)
            verdict[path] = None if paper is None else (
                contradicted(fa, paper, number, day,
                             series_held(tree, series, [new[a][2], new[b][2]], set(refused))), paper)
    done = []
    for a, b in pairs:
        if a not in verdict or b not in verdict:
            continue
        bad = [p for p in (a, b) if verdict[p] and verdict[p][0]]
        if len(bad) != 1:
            continue
        path = bad[0]
        why, paper = verdict[path]
        edition = reset_edition(fa, paper, new[path][0], ledger)
        (tree / path).unlink()
        done.append((path, edition, why))
    return done


def main(argv):
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    refused = {}
    for line in sys.stdin.read().splitlines():
        path, _, why = line.partition("\t")
        if path:
            refused[path] = why
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        done = replace_pair(argv[0], refused)
    except Exception as e:  # the commit goes ahead; the pre-push still judges what is committed
        print(f"replace_held_pair failed, both files stay held: {type(e).__name__}: {e}", file=sys.stderr)
        return 0
    for path, edition, why in done:
        print(f"removed from the tree to be read again ({edition or 'no ledger row'}): {path}: {why}", file=sys.stderr)
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
