#!/usr/bin/env python3
"""Decide whether a discarded annotation run is worth waking anyone for.

    python3 tools/discard_alert.py judge <ID> <validate-log> --dir DIR   # prints one verdict
    python3 tools/discard_alert.py clear <ID> --dir DIR                  # the puzzle annotated

Verdicts (puzzle_worker.sh's _worker_finish acts on them):
  silent  nothing a person or a rerun can mend: the puzzle awaits a preamble, or
          every error is a no-clueFragment / definedByPreamble one on a puzzle
          with no preamble. Parked, no alert, not counted.
  retry   the puzzle's first discard: leave it unparked so the next pick tries
          once more (a second run often passes), no alert.
  alert   the second discard, and its error class has not been seen before.
  ledger  the second discard of a class already seen: one line in DIR/discards.log.

State, in DIR: counts.json (discards per puzzle), seen_classes.txt, discards.log.
"""
import json
import re
import sys
import time
from pathlib import Path

PREAMBLE_ERRORS = ("definedByPreamble, but the puzzle has no preamble",
                   "a block with no clueFragment is for letters the preamble supplies")


def errors_of(text):
    return [l.strip()[len("ERROR"):].lstrip(": ") for l in text.splitlines()
            if l.startswith("  ERROR")]


def error_class(error):
    """The error with its tag, quoted words and numbers taken out, so the same
    kind of failure on another puzzle is the same class."""
    body = error.split(": ", 1)[-1] if re.match(r"^[\w,]+: ", error) else error
    body = re.sub(r"'[^']*'|\"[^\"]*\"|\d+", "", body)
    return " ".join(body.split())[:60]


def silent(puzzle, errors):
    if puzzle.get("awaitsPreamble"):
        return True
    return (not puzzle.get("preamble") and bool(errors)
            and all(any(p in e for p in PREAMBLE_ERRORS) for e in errors))


def judge(pid, errors, puzzle, d):
    if silent(puzzle, errors):
        return "silent"
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    cf = d / "counts.json"
    counts = json.loads(cf.read_text()) if cf.exists() else {}
    counts[pid] = counts.get(pid, 0) + 1
    cf.write_text(json.dumps(counts, sort_keys=True))
    cls = error_class(errors[0]) if errors else "(no error line)"
    seen_f = d / "seen_classes.txt"
    seen = set(seen_f.read_text().splitlines()) if seen_f.exists() else set()
    with open(d / "discards.log", "a") as f:
        f.write(f"{time.strftime('%F %T')} {pid} #{counts[pid]} [{cls}] {errors[0] if errors else ''}\n")
    if counts[pid] < 2:
        return "retry"
    if cls in seen:
        return "ledger"
    with open(seen_f, "a") as f:
        f.write(cls + "\n")
    return "alert"


def clear(pid, d):
    cf = Path(d) / "counts.json"
    if cf.exists():
        counts = json.loads(cf.read_text())
        if counts.pop(pid, None) is not None:
            cf.write_text(json.dumps(counts, sort_keys=True))


def main(argv):
    if len(argv) < 4 or argv[0] not in ("judge", "clear") or "--dir" not in argv:
        print(__doc__.strip())
        return 2
    d = argv[argv.index("--dir") + 1]
    if argv[0] == "clear":
        clear(argv[1], d)
        return 0
    import puzzle_paths
    from fetch_puzzle import read_puzzle_file
    path = puzzle_paths.find(argv[1])
    puzzle = read_puzzle_file(path) if path else {}
    print(judge(argv[1], errors_of(Path(argv[2]).read_text()), puzzle, d))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
