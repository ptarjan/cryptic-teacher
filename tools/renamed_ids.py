#!/usr/bin/env python3
"""Every puzzle id the repo has renamed, and the id each one is at now.

    python3 tools/renamed_ids.py --check-staged   # pre-commit: refuse a staged rename the map lacks
    python3 tools/renamed_ids.py --stage          # add the staged renames to the map
    python3 tools/renamed_ids.py --check          # the map against the whole history
    python3 tools/renamed_ids.py --write          # rebuild the map from the whole history

A rename is what tools/commit_subject.py calls one: a commit that deletes
puzzles/.../<old id>.json (or a .js, from before the corpus was JSON) and adds
puzzles/.../<new id>.json, paired by git's rename detection. A file that moves
directory or extension keeps its id and is not one. Git compares only the ids
that left against the ids that arrived in that commit, so a commit moving
every file still pairs its few renames exhaustively.

tools/data/renamed_ids.json holds {old id: new id}, the newest rename of each
old id, and the site build reads that file rather than history, because the
build's checkout is shallow. Every commit that renames a puzzle carries its
row: the pre-commit hook refuses one that does not, and tools/durable.sh and
tools/daily_update.sh stage it. One line per id, merged per key
(.gitattributes json-keys), since several jobs rename at once.

current() turns the rows into {old id: the id its puzzle has now}.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAP = ROOT / "tools" / "data" / "renamed_ids.json"
PUZZLE_FILE = re.compile(r"^puzzles/(?:.*/)?([a-z][a-z0-9]*-\d+)\.(?:json|js)$")
README = ("Every puzzle id renamed: {old id: new id}. Written by "
          "tools/renamed_ids.py; tools/build_seo_pages.py writes a redirect page "
          "at each old id that no live puzzle holds.")


def _git(root, *args):
    out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                         check=False)
    if out.returncode != 0:
        raise SystemExit(f"git {' '.join(args[:4])} in {root} failed "
                         f"({out.returncode}): {out.stderr.strip()}")
    return out.stdout


def _ids(lines):
    """{status: {id: [paths]}} from --name-status lines of A and D rows."""
    out = {"A": {}, "D": {}}
    for line in lines:
        status, path = line.split("\t", 1)
        if status in out and (m := PUZZLE_FILE.match(path)):
            out[status].setdefault(m.group(1), []).append(path)
    return out


def _pairs(root, diff_args, lines):
    """[(old id, new id)] that one diff's A and D rows rename."""
    got = _ids(lines)
    gone = {i: p for i, p in got["D"].items() if i not in got["A"]}
    came = {i: p for i, p in got["A"].items() if i not in got["D"]}
    if not gone or not came:
        return []
    paths = [p for ps in [*gone.values(), *came.values()] for p in ps]
    out = _git(root, "diff", "-M", "-l0", "--diff-filter=R", "--name-status", *diff_args,
               "--", *paths)
    pairs = []
    for line in out.splitlines():
        _, old, new = line.split("\t")
        a, b = PUZZLE_FILE.match(old).group(1), PUZZLE_FILE.match(new).group(1)
        if a != b and (a, b) not in pairs:
            pairs.append((a, b))
    return pairs


def from_history(root=ROOT):
    """[(old, new)] for every rename HEAD can reach, oldest first."""
    if _git(root, "rev-parse", "--is-shallow-repository").strip() == "true":
        raise SystemExit(f"{root} is a shallow clone: renames need the whole history "
                         "(git fetch --unshallow)")
    log = _git(root, "log", "--reverse", "--topo-order", "--no-renames", "--diff-filter=AD",
               "--name-status", "--format=@%H %P", "HEAD", "--", "puzzles/")
    pairs, commit, lines = [], None, []

    def flush():
        if commit and len(commit) == 2:   # a root commit renames nothing
            pairs.extend(_pairs(root, [commit[1], commit[0]], lines))

    for line in log.splitlines():
        if line.startswith("@"):
            flush()
            commit, lines = line[1:].split(), []
        elif line:
            lines.append(line)
    flush()
    return pairs


def staged(root=ROOT):
    """[(old, new)] the index renames against HEAD."""
    lines = _git(root, "diff", "--cached", "--no-renames", "--diff-filter=AD",
                 "--name-status", "--", "puzzles/").splitlines()
    return _pairs(root, ["--cached"], lines)


def read(path=MAP):
    """{old id: new id}."""
    rows = json.loads(path.read_text(encoding="utf-8"))
    rows.pop("README", None)
    return rows


def write(renamed, path=MAP):
    """In json_merge.dump_lines' layout, one line per key, which its merge keeps."""
    held = {"README": README, **renamed}
    path.write_text("{\n" + ",\n".join(f" {json.dumps(k)}: {json.dumps(held[k])}"
                                         for k in sorted(held)) + "\n}\n", encoding="utf-8")


def current(renamed, live):
    """{old id: the live id its puzzle has now}. A chain a->b->c lands on c,
    stopping at the first live id, which is where the puzzle is (b may have
    been renamed away before a was renamed to it). An old id a live puzzle
    holds is that puzzle's, and an old id whose chain ends at a deleted
    puzzle has no current id: neither is in the result."""
    out = {}
    for old, now in renamed.items():
        if old in live:
            continue
        seen = {old}
        while now not in live and now in renamed and now not in seen:
            seen.add(now)
            now = renamed[now]
        if now in live:
            out[old] = now
    return out


def reprinted_in(renamed, live):
    """{old id: the live id now} for each puzzle of a series that carries
    reprints (series.carries_reprints: a book, the Globe and Mail, the Canberra
    Times) renamed to a puzzle of another series: it reprints that puzzle, so
    its series still lists it and counts it at its own number
    (fetch_puzzle.renamed_reprint_rows, coverage.held_numbers, coverage.trove).
    A rename within a series, or out of one that carries no reprints
    (indysunday -> independent, a misfiled daily) or is gone from the table
    (herald, penguin -> book), is a correction and is not in it."""
    import series as series_meta
    out = {}
    for old, now in current(renamed, live).items():
        carrier = series_meta.parse_id(old)[0]
        if (series_meta.carries_reprints(carrier)
                and series_meta.parse_id(now)[0] != carrier):
            out[old] = now
    return out


def main(argv):
    if argv == ["--write"]:
        # A later rename of an id wins. A row history cannot pair (an id
        # deleted in a commit of its own, not renamed) stays.
        renamed = {**read(), **dict(from_history())}
        write(renamed)
        print(f"{MAP.relative_to(ROOT)}: {len(renamed)} renamed id(s)")
        return 0
    if argv == ["--check"]:
        # Sorted: a job's batch can stage its rows in path order and commit
        # its renames in another.
        # A row history does not pair stands (see --write).
        have, want = read(), dict(from_history())
        if any(have.get(a) != b for a, b in want.items()):
            missing = [f"{a} -> {b}" for a, b in want.items() if have.get(a) != b]
            extra = [f"{a} -> {b}" for a, b in have.items() if a in want and want[a] != b]
            print(f"{MAP.relative_to(ROOT)} disagrees with history: missing {missing[:5]}"
                  f"{' ...' if len(missing) > 5 else ''}, not in history {extra[:5]}; "
                  "run python3 tools/renamed_ids.py --write", file=sys.stderr)
            return 1
        return 0
    if argv in (["--stage"], ["--check-staged"]):
        new = staged()
        if not new:
            return 0
        if argv == ["--stage"]:
            write({**read(), **dict(new)})
            _git(ROOT, "add", "--", str(MAP))
            return 0
        index = MAP.relative_to(ROOT).as_posix()
        have = json.loads(_git(ROOT, "show", f":{index}"))
        if missing := [(a, b) for a, b in new if have.get(a) != b]:
            print(f"pre-commit: {len(missing)} staged puzzle rename(s) missing from "
                  f"{index} ({', '.join(f'{a} -> {b}' for a, b in missing[:3])}), so the "
                  "old address would 404; run python3 tools/renamed_ids.py --stage",
                  file=sys.stderr)
            return 1
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
