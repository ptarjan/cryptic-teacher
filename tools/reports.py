#!/usr/bin/env python3
"""Read the bad-hint reports people have sent from the site.

  python3 tools/reports.py                 # everything, newest first
  python3 tools/reports.py --since 7       # the last week
  python3 tools/reports.py --done r:2026-08-28:...   # delete one, once fixed

WHY THERE IS NO ENDPOINT FOR THIS. The reports go into the same KV namespace as
the saves, written by POST /r on the sync worker, and they are read here through
wrangler with the account's own credentials. A GET route would mean anybody who
guessed the path could read what strangers typed into a text box, and there is
no login on that worker to put in front of it — the sync code is the only
identity it has, and that is deliberately not an identity.

A record is what the reporter chose to send plus the day: the puzzle, the clue,
which rung was open, and their sentence. No address, no code, no clock finer
than the date. Same posture as the event counting next to it, for the same
reason — there is nothing here to join two reports into one person with.

Deleting is the workflow. A report stays in the list until somebody has fixed
what it names, so the list IS the queue; --done takes the key printed above each
one. They expire after a year regardless.

ONE REPORT IS A SAMPLE, NOT AN INCIDENT. Nobody reports the second clue with the
same fault; they close the tab. So fixing the clue named here is half the job —
the other half is measuring the shape across every walkthrough in puzzles/, and
if it is tight enough to match without false positives, adding it to
tools/validate_annotations.py and tools/annotate_prompt.md so it cannot come
back. That is how the two walkthrough-opener and closer rules got written on
2026-09-06. Where the shape is real but too fuzzy to match, say so in the commit
and fix the one clue: a judgement call recorded is not the same as a fault
ignored.
"""
import argparse
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import kv

PREFIX = "r:"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", type=int, metavar="DAYS",
                    help="only reports from the last DAYS days")
    ap.add_argument("--done", metavar="KEY", help="delete one report, by the key printed above it")
    args = ap.parse_args()

    if args.done:
        gone = kv.delete_key(args.done)
        if gone is not True:
            raise SystemExit(f"could not delete {args.done}: {gone}")
        print(f"deleted {args.done}")
        return 0

    keys = [k["name"] for k in kv.list_keys(prefix=PREFIX)]
    if args.since:
        cutoff = (datetime.date.today() - datetime.timedelta(days=args.since)).isoformat()
        keys = [k for k in keys if k.split(":")[1] >= cutoff]
    if not keys:
        print("no bad-hint reports" + (f" in the last {args.since} days" if args.since else ""))
        return 0

    for key in sorted(keys, reverse=True):
        r = json.loads(kv.get_key(key))
        where = " ".join(x for x in (r.get("puzzle"), r.get("clue"),
                                     f"({r['rung']})" if r.get("rung") else "") if x)
        print(f"\n{r.get('day', '?')}  {where}\n  {r.get('note', '')}\n  {key}")
    print(f"\n{len(keys)} report(s). Fix one, then: python3 tools/reports.py --done <key>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
