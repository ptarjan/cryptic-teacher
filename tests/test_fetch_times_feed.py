#!/usr/bin/env python3
# Does tools/fetch_times_feed.py turn the Times player's data.json into a
# puzzle, and refuse one whose clues do not cover the grid?
#
#     python3 tests/test_fetch_times_feed.py
import datetime
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import fetch_times_feed as f

fails = 0


def check(what, expected, got):
    global fails
    if expected == got:
        print(f"ok   {what}")
    else:
        print(f"FAIL {what}: expected [{expected}], got [{got}]")
        fails += 1


def convert(drop_clue):
    """One line per entry, or the refusal."""
    # 3x3 with a block in the middle; the solution string's space is the block,
    # so the lights are the four edges: 1 across, 1 down, 2 down, 3 across.
    data = {"headline": "Times Quick Cryptic (Number 01)", "copy": {
        "title": "Times Quick Cryptic (Number 01)", "id": "100", "setter": "Des",
        "crosswordtype": "Quick Cryptic", "gridsize": {"cols": "3", "rows": "3"},
        "settings": {"solution": "CATO EWED"},
        "clues": [
            {"title": "Across", "clues": [
                {"number": "1", "clue": "Pet", "format": "3", "answer": "CAT"},
                {"number": "3", "clue": "Married", "format": "1-2", "answer": "W-ED"}]},
            {"title": "Down", "clues": [
                {"number": "1", "clue": "Dairy animal", "format": "3", "answer": "COW"},
                {"number": "2", "clue": "Digit", "format": "3", "answer": "TED"}]}]}}
    if drop_clue:
        data["copy"]["clues"][1]["clues"].pop()
    p, why = f.convert(data, datetime.date(2014, 3, 10))
    if why:
        return why
    lines = [" ".join([p["id"], p["date"], p["setter"], p["source"]["url"]])]
    for e in p["entries"]:
        lines.append(" ".join(str(x) for x in (
            e["number"], e["direction"], e["position"]["x"], e["position"]["y"],
            e["clue"]["text"], e["clue"]["enumeration"], e.get("solution"))))
    return "\n".join(lines)


def daily():
    """A Daily's clue with HTML entities files as series "times", unescaped."""
    data = {"headline": "Times Cryptic No 26829", "copy": {
        "title": "Times Cryptic No 26829", "id": "26266", "setter": "",
        "crosswordtype": "Cryptic", "gridsize": {"cols": "3", "rows": "3"},
        "settings": {"solution": "CATO EWED"},
        "clues": [
            {"title": "Across", "clues": [
                {"number": "1", "clue": "Pet &mdash; it&rsquo;s", "format": "3", "answer": "CAT"},
                {"number": "3", "clue": "Married", "format": "1-2", "answer": "W-ED"}]},
            {"title": "Down", "clues": [
                {"number": "1", "clue": "Dairy animal", "format": "3", "answer": "COW"},
                {"number": "2", "clue": "Digit", "format": "3", "answer": "TED"}]}]}}
    p, why = f.convert(data, datetime.date(2017, 9, 13))
    first = why or (p["id"], p["series"], p["entries"][0]["clue"]["text"])
    return f"{first}\n{f.daily_dates(26830, {26829: datetime.date(2017, 9, 13)})[0].isoformat()}"


check("data.json becomes a puzzle: lights placed, enumerations kept, answers as letters",
      """timesquick-1 2014-03-10 Des https://feeds.thetimes.co.uk/puzzles/crossword/20140310/100/
1 across 0 0 Pet 3 CAT
3 across 0 2 Married 1-2 WED
1 down 0 0 Dairy animal 3 COW
2 down 2 0 Digit 3 TED""", convert(False))
check("a light with no clue is refused", "the clues do not cover the grid's lights", convert(True))
check("a Daily files as series times, entities unescaped; the next number is the next day",
      """('times-26829', 'times', 'Pet — it’s')
2017-09-14""", daily())

if fails:
    print(f"{fails} check(s) failed")
    sys.exit(1)
print("all checks passed")
