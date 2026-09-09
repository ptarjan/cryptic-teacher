#!/usr/bin/env python3
"""Refill gaps in the Minute Cryptic daily archive from their own video titles.

    python3 tools/recover_minutecryptic.py --dry-run
    python3 tools/recover_minutecryptic.py

tools/fetch_minutecryptic.js can only ever see the rolling window their API
offers, so any day the nightly capture does not run is lost to it for good. It
is not lost to YouTube: Minute Cryptic upload one video per clue and put the
clue verbatim in the title, as `Minute Cryptic <n>: <clue> (<enumeration>)`.
Publisher's own text, enumeration intact -- which the auto-generated captions
are not. ASR on a fan re-post misheard a word of the clue itself and narrated
"(5)" as prose, so captions are not a source and this does not read them.

DATE COMES FROM THE CLUE NUMBER, NOT THE UPLOAD DATE, which lags the clue by
nought to seven days and cannot be trusted. Clue numbers run one per day, so
date = EPOCH + n. EPOCH is not typed in here: it is derived by matching titles
against clues already archived from the API, and the run aborts unless every
one of those agrees on it. That is the whole check -- a channel that renumbers,
skips, or changes its title format shows up as disagreement rather than as a
year of clues quietly filed under the wrong dates.

Rows written here carry `source: "youtube-title"` and the video id, and omit
the fields a title cannot know (clueAuthor, solverCount, solveStatus) rather
than inventing them. Their id is `yt:<videoId>`, which is not a shape the API
mints, so the append-only dedupe in fetch_minutecryptic.js cannot confuse the
two.

Needs yt-dlp on PATH. Nothing else here does, and it is not in the container
image, so this is a recovery run rather than a nightly job.
"""
import argparse
import collections
import datetime
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

CHANNEL = "https://www.youtube.com/channel/UC5MqhxfGwksL2ze71gNSCAw/videos"
ARCHIVE = Path(__file__).resolve().parent / "data" / "minutecryptic" / "daily.jsonl"
# The numbered form is the only one that carries a clue. The channel also
# posts explainers and older differently-titled clues; those are skipped.
TITLE = re.compile(r"Minute Cryptic (\d+):\s*(.+?)\s*\(([^()]*)\)\s*$")


def scrape():
    if not shutil.which("yt-dlp"):
        sys.exit("ERROR: yt-dlp is not on PATH — install it or add ~/.local/bin")
    out = subprocess.run(["yt-dlp", "--flat-playlist", "--print", "%(id)s|%(title)s",
                          CHANNEL], capture_output=True, text=True)
    if out.returncode:
        sys.exit(f"ERROR: yt-dlp exited {out.returncode}: {out.stderr.strip()[-300:]}")
    titles = {}
    for line in out.stdout.splitlines():
        vid, _, title = line.partition("|")
        m = TITLE.match(title)
        if m:
            titles[int(m.group(1))] = (m.group(2), m.group(3), vid)
    return titles


def epoch_from(titles, rows):
    """The date clue 0 would have had, agreed by every clue we already hold."""
    by_text = {r["clueText"].strip(): r for r in rows if r.get("clueText")}
    votes = collections.Counter()
    for n, (clue, _pattern, _vid) in titles.items():
        row = by_text.get(clue.strip())
        if row:
            day = datetime.date.fromisoformat(row["availableDate"])
            votes[day - datetime.timedelta(days=n)] += 1
    if not votes:
        sys.exit("ERROR: no archived clue matched any video title — the title "
                 "format has changed; re-read TITLE before trusting this.")
    (best, agree), = votes.most_common(1)
    if len(votes) > 1:
        sys.exit(f"ERROR: archived clues disagree on the clue-number epoch "
                 f"({dict(votes)}) — numbering is not one per day over this "
                 f"range, so the mapping is unsafe. Nothing written.")
    return best, agree


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="say what it would add")
    args = ap.parse_args()

    rows = [json.loads(line) for line in ARCHIVE.read_text().splitlines() if line.strip()]
    titles = scrape()
    epoch, agree = epoch_from(titles, rows)
    print(f"{len(titles)} numbered titles; clue 0 = {epoch}, agreed by all {agree} "
          f"of the {len(rows)} archived clues that matched a title")

    have = {r["availableDate"] for r in rows}
    day, today = min(datetime.date.fromisoformat(d) for d in have), datetime.date.today()
    new = []
    while day <= today:
        n = (day - epoch).days
        if day.isoformat() not in have and n in titles:
            clue, pattern, vid = titles[n]
            new.append({"id": f"yt:{vid}", "type": "DAILY", "clueText": clue,
                        "answerPattern": pattern, "subtitle": "Daily clue",
                        "availableDate": day.isoformat(), "source": "youtube-title"})
        day += datetime.timedelta(days=1)

    gaps = sum(1 for d in (epoch + datetime.timedelta(days=i)
                           for i in range((today - epoch).days + 1))
               if d >= min(datetime.date.fromisoformat(x) for x in have)
               and d.isoformat() not in have)
    print(f"{gaps} gap(s); {len(new)} recoverable from a title")
    for r in new:
        print(f"  {'would add' if args.dry_run else 'add'} {r['availableDate']}  ({r['answerPattern']})")
    if new and not args.dry_run:
        with ARCHIVE.open("a") as fh:
            for r in new:
                fh.write(json.dumps(r) + "\n")
        print(f"appended {len(new)} row(s) to {ARCHIVE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
