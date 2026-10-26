#!/usr/bin/env python3
"""hintless_overdue.overdue() on fixtures: only a recent, solved, hintless, unblocked puzzle past the threshold."""
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import hintless_overdue as H

NOW = 1_800_000_000.0
TODAY = datetime.date(2026, 10, 16)


def puzzle(pid, date="2026-10-15", solved=True, hinted=False, **extra):
    entry = {"number": 1, "direction": "across", "clue": {"text": "Test"}, "length": 4,
             "solution": "TEST" if solved else ""}
    if hinted:
        entry["annotation"] = {"type": "x"}
    return {"id": pid, "date": date, "entries": [entry], **extra}


def hours_ago(h):
    return NOW - h * 3600


fixtures = {
    "late-1": puzzle("late-1"),
    "late-2": puzzle("late-2"),
    "young-1": puzzle("young-1"),
    "done-1": puzzle("done-1", hinted=True),
    "unsolved-1": puzzle("unsolved-1", solved=False),
    "preamble-1": puzzle("preamble-1", awaitsPreamble=True),
    "failed-1": puzzle("failed-1"),
    "backfill-1": puzzle("backfill-1", date="2020-01-01"),
}
filed = {pid: (hours_ago(60 if pid == "late-2" else 40), f"{pid}.json") for pid in fixtures}
filed["young-1"] = (hours_ago(H.OVERDUE_HOURS - 1), "young-1.json")
filed["gone-1"] = (hours_ago(50), "gone-1.json")

got = H.overdue(filed, lambda path: fixtures.get(path[:-5]), NOW, blocked={"failed-1"}, today=TODAY)
assert [pid for pid, _ in got] == ["late-2", "late-1"], got
assert abs(got[0][1] - 60) < 1e-6 and abs(got[1][1] - 40) < 1e-6, got
assert H.overdue({}, lambda path: None, NOW, today=TODAY) == []
print("ok")
