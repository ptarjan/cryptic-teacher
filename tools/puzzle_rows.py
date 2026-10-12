#!/usr/bin/env python3
"""The rows of the per-puzzle tables, which go wherever their puzzle file goes.

    python3 tools/puzzle_rows.py retire OLD [NEW]   # carry OLD's rows to NEW, or discard them
    python3 tools/puzzle_rows.py --check-staged     # pre-commit: refuse a staged deletion that leaves rows
    python3 tools/puzzle_rows.py --check            # every row's puzzle file is on disk

A table here describes one puzzle file's content, keyed by its id ("<id>" or
"<id>/<entry id>"): a clue, answer or light the source got wrong, a setter's
error, a nina, a light the solver missed, the newspaper id a book file is. A
row whose file is gone names nothing, and tools/test_source_answer_wrong.sh
fails on it.

So whatever deletes or renames a puzzle file takes its rows in the same commit:
on a rename (the same file under a new id) they move to the new id, on any
other deletion they go. durable.sh
retires the id of every D or R line it commits and carries the tables in that
commit; the pre-commit hook runs --check-staged, which refuses the rest.
SOURCE_LIGHT_WRONG is code in fetch_puzzle.py, not data, so it is checked but
edited by hand.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "tools" / "data"
#: Keyed "<id>/<entry id>". Every table here is one line per key
#: (json_merge.dump_lines) and merged per key (.gitattributes json-keys).
ENTRY_TABLES = ("source_clue_wrong", "source_answer_wrong", "setter_error", "blog_disagree")
#: Keyed "<id>".
PUZZLE_TABLES = ("ninas", "blind_misses", "diagnosed_misses", "book_twins")
TABLES = ENTRY_TABLES + PUZZLE_TABLES
LIGHT_TABLE = "tools/fetch_puzzle.py"
PUZZLE_FILE = re.compile(r"^puzzles/(?:.*/)?([a-z][a-z0-9]*-\d+)\.json$")


def table_path(name, root=ROOT):
    return Path(root) / "tools" / "data" / f"{name}.json"


def key_id(key):
    return key.split("/", 1)[0]


def dump(name, rows):
    from json_merge import dump_lines
    return dump_lines(rows)


def light_ids(text):
    """The ids SOURCE_LIGHT_WRONG keys, from fetch_puzzle.py's text."""
    m = re.search(r"^SOURCE_LIGHT_WRONG = \{(.*?)^\}", text, re.S | re.M)
    return set(re.findall(r'^    \("([a-z][a-z0-9]*-\d+)", "', m.group(1), re.M)) if m else set()


def retire(old, new=None, root=ROOT):
    """Move old's rows to new (a rename), or drop them (new None). A row new
    already has is kept and old's is dropped. Returns the table files written."""
    written = []
    for name in TABLES:
        path = table_path(name, root)
        if not path.exists():
            continue
        rows = json.loads(path.read_text(encoding="utf-8"))
        out, changed = {}, False
        for key, value in rows.items():
            if key_id(key) != old:
                out.setdefault(key, value)
                continue
            changed = True
            if new is not None:
                moved = new + key[len(old):]
                if moved not in rows:
                    out[moved] = value
        if changed:
            path.write_text(dump(name, out), encoding="utf-8")
            written.append(path)
    light = Path(root) / LIGHT_TABLE
    if light.exists() and old in light_ids(light.read_text(encoding="utf-8")):
        print(f"puzzle_rows: SOURCE_LIGHT_WRONG in {LIGHT_TABLE} keys {old}; "
              f"{'rekey it to ' + new if new else 'delete it'} by hand", file=sys.stderr)
    return written


def _git(*args, root=ROOT):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                          text=True, check=False)


def staged_gone(root=ROOT):
    """{old id: new id or None} for each puzzle file the index deletes against
    HEAD and does not add back under its id: a rename git pairs gets its new id."""
    out = _git("diff", "--cached", "-M", "--name-status", "--", "puzzles/", root=root).stdout
    gone, came = {}, set()
    for line in out.splitlines():
        f = line.split("\t")
        ids = [m.group(1) if (m := PUZZLE_FILE.match(p)) else None for p in f[1:]]
        if f[0].startswith("R") and ids[0] and ids[1]:
            if ids[0] != ids[1]:
                gone[ids[0]] = ids[1]
                came.add(ids[1])
        elif f[0] == "D" and ids[0]:
            gone.setdefault(ids[0], None)
        elif f[0] == "A" and ids[0]:
            came.add(ids[0])
    return {i: n for i, n in gone.items() if i not in came}


def leftovers(gone, read):
    """[(table, key)] rows of a gone id; read(relative path) gives a file's text or None."""
    left = []
    for name in TABLES:
        text = read(f"tools/data/{name}.json")
        if text:
            left += [(name, k) for k in json.loads(text) if key_id(k) in gone]
    text = read(LIGHT_TABLE)
    if text:
        left += [("SOURCE_LIGHT_WRONG", i) for i in sorted(light_ids(text) & set(gone))]
    return left


def check_staged(root=ROOT):
    gone = staged_gone(root)
    if not gone:
        return 0

    def read(rel):
        r = _git("show", f":{rel}", root=root)
        return r.stdout if r.returncode == 0 else None

    if left := leftovers(gone, read):
        ids = sorted({key_id(k) for _, k in left})
        fix = "; ".join(f"python3 tools/puzzle_rows.py retire {i}"
                        f"{' ' + gone[i] if gone[i] else ''}" for i in ids)
        print(f"pre-commit: the staged deletion of {', '.join(ids)} leaves "
              f"{len(left)} row(s) in the per-puzzle tables "
              f"({', '.join(f'{t}:{k}' for t, k in left[:4])}), which then name no "
              f"puzzle and fail CI. Fix: {fix}; then stage the tables", file=sys.stderr)
        return 1
    return 0


def check(root=ROOT):
    sys.path.insert(0, str(Path(root) / "tools"))
    import puzzle_paths
    ids = set()
    for name in TABLES:
        path = table_path(name, root)
        if path.exists():
            ids |= {key_id(k) for k in json.loads(path.read_text(encoding="utf-8"))}
    ids |= light_ids((Path(root) / LIGHT_TABLE).read_text(encoding="utf-8"))
    bad = sorted(i for i in ids if puzzle_paths.find(i) is None)
    for i in bad:
        print(f"puzzle_rows: rows keyed {i}, which has no puzzle file", file=sys.stderr)
    return 1 if bad else 0


def main(argv):
    if argv[:1] == ["retire"] and len(argv) in (2, 3):
        for path in retire(argv[1], argv[2] if len(argv) == 3 else None):
            print(path.relative_to(ROOT))
        return 0
    if argv == ["--check-staged"]:
        return check_staged()
    if argv == ["--check"]:
        return check()
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
