#!/bin/bash
# Is every filed Times, Times Jumbo and Sunday Times puzzle dated on a day its
# paper could have printed it?
#
#     bash tools/test_times_dates.sh
#
# The prize puzzles are blogged a week or more after they are printed, so a
# prize dated by its blog post lands on the wrong day: Saturday's Times on the
# next Saturday, the Sunday Times on a Saturday. tools/file_times_puzzles.py
# derives the print date instead; this holds the corpus to what that date must
# satisfy, whoever wrote it:
#
#   - the Sunday Times on a Sunday, one number a week at most;
#   - the Jumbo on a Saturday, or a weekday for a bank-holiday Jumbo, never a
#     Sunday;
#   - the Times never on a Sunday, and its dates rising with its numbers, so
#     Saturday's puzzle, between Friday's and Monday's, can only be dated the
#     Saturday;
#   - none of them after the blog post that wrote it up (a daily is sometimes
#     blogged the evening before, so a day's grace).
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"

python3 - "$REPO/puzzles" <<'PY'
import datetime, json, pathlib, sys

SATURDAY, SUNDAY = 5, 6
held = {}
for series in ("times", "timesjumbo", "sundaytimes"):
    rows = []
    for path in pathlib.Path(sys.argv[1]).glob(f"{series}-[0-9]*.json"):
        p = json.loads(path.read_text(encoding="utf-8"))
        if p.get("date"):
            day = datetime.datetime.fromtimestamp(p["date"] / 1000, datetime.timezone.utc).date()
            posted = (p.get("solutionSource") or {}).get("date")
            rows.append((p["number"], day, posted and datetime.date.fromisoformat(posted)))
    held[series] = sorted(rows)

bad = []
for series, rows in held.items():
    for n, day, posted in rows:
        pid = f"{series}-{n}"
        if series == "sundaytimes" and day.weekday() != SUNDAY:
            bad.append(f"{pid}: {day:%a %d %b %Y}, not a Sunday")
        if series != "sundaytimes" and day.weekday() == SUNDAY:
            bad.append(f"{pid}: {day:%a %d %b %Y}, and the Times prints nothing on Sunday")
        if posted and day > posted + datetime.timedelta(days=1):
            bad.append(f"{pid}: dated {day}, after the blog post of {posted} that wrote it up")
    for (a, da, _), (b, db, _) in zip(rows, rows[1:]):
        if db <= da:
            bad.append(f"{series}-{b}: dated {db}, not after {series}-{a}'s {da}")
        elif series == "sundaytimes" and (db - da).days < 7 * (b - a):
            bad.append(f"{series}-{b}: {db}, too soon after {series}-{a}'s {da} for one a week")

for line in bad[:40]:
    print("FAIL " + line)
if len(bad) > 40:
    print(f"... and {len(bad) - 40} more")
counted = ", ".join(f"{s} {len(r)}" for s, r in held.items())
print(f"{len(bad)} failed of the dated {counted}" if bad else f"all passed: dated {counted}")
sys.exit(1 if bad else 0)
PY
