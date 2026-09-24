#!/usr/bin/env python3
"""Rebuild every `t:<puzzle>` vote tally from the raw `v:` keys.

  python3 tools/vote_tally_backfill.py            # write them
  python3 tools/vote_tally_backfill.py --dry-run  # print them

GET /v on the sync worker reads one tally key per puzzle instead of listing
the votes, and POST /v keeps that key current with a read-modify-write that
can drop a vote to a concurrent one. The raw keys are the source of truth, so
this is how a tally is made right again, and how the keys were first built.

It costs one list pass over `v:` (a list is 1,000 a day on the free tier) and
one bulk write.
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kv  # noqa: E402

VOTE_TTL = 60 * 60 * 24 * 365  # sync/worker.js VOTE_TTL
VERDICTS = ("up", "down")


def tallies(names):
    """{puzzle: {target: {up, down}}} from key names
    v:<kind>:<puzzle>[:<clue>]:<verdict>:<day>:<uuid>."""
    out = defaultdict(dict)
    for name in names:
        parts = name.split(":")
        if len(parts) < 6 or parts[0] != "v" or parts[-3] not in VERDICTS:
            continue
        target = ":".join(parts[1:-3])
        t = out[parts[2]].setdefault(target, {"up": 0, "down": 0})
        t[parts[-3]] += 1
    return dict(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    by_puzzle = tallies(k["name"] for k in kv.list_keys(prefix="v:"))
    pairs = [{"key": "t:" + p, "value": json.dumps(t), "expiration_ttl": VOTE_TTL}
             for p, t in sorted(by_puzzle.items())]
    if args.dry_run:
        for pair in pairs:
            print(pair["key"], pair["value"])
        return
    if pairs:
        kv.put_many(pairs)
    print(f"wrote {len(pairs)} tally keys")


if __name__ == "__main__":
    main()
