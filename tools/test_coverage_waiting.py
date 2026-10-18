#!/usr/bin/env python3
# Does a puzzle held in clues_only/ keep its series from going STALE?
#
#     python3 tools/test_coverage_waiting.py
#
# genius-280 (2026-10-05) was fetched and held clues-only for its answers, but
# coverage_report read only puzzles/, so the report said "genius ... STALE
# nothing since 2026-09-07 (41d)" while the feed had answered on time.
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coverage_report

held = [{"id": f"genius-{n}", "series": "genius", "number": n, "date": d}
        for n, d in ((278, "2026-08-03"), (279, "2026-09-07"))]
today = date(2026, 10, 18)


def flags(waiting):
    return [f for row in coverage_report.audit(held, today, waiting) for f in row["flags"]
            if f.startswith("STALE")]


stale = flags(None)
assert stale and "2026-09-07" in stale[0], stale
assert flags({"genius": date(2026, 10, 5)}) == [], flags({"genius": date(2026, 10, 5)})
still = flags({"genius": date(2026, 8, 1)})
assert still and "2026-09-07" in still[0], still
print("ok")
