#!/usr/bin/env python3
"""How many shards render the crawlable puzzle pages, from how many pages there are.

  python3 tools/plan_shards.py            # after the reindex: reads puzzles/index.json,
                                          # writes shards=N and pages=P to $GITHUB_OUTPUT

pages.yml renders the puzzle pages in steps of `--shard i/N`, one step per
shard, because a step has a time budget (tools/data/deploy_budgets.json, 90s).
A cold render costs about PAGE_SECONDS a page counting each shard's startup,
so PAGES_PER_SHARD pages keep a shard well under the budget, and N is
ceil(pages / PAGES_PER_SHARD): the corpus can grow and the shard count follows
it. The workflow lists MAX_SHARDS shard steps, each running only when its
number is below N; a corpus past MAX_SHARDS * PAGES_PER_SHARD fails here,
naming the cap and the page count, and is fixed by adding steps to pages.yml
and raising MAX_SHARDS together.

The count is the listed puzzles in the index, an upper bound on the pages (a
puzzle without a solution has none). The assemble step checks that the N
shards cover the pages exactly once, so a wrong N cannot ship a wrong site.
"""
import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
#: Seconds a cold render takes a page, startup included (about 12ms measured).
PAGE_SECONDS = 0.012
#: The step budget a shard has (deploy_budgets.json) and the room kept under it.
STEP_BUDGET_SECONDS = 90
HEADROOM = 1.35
PAGES_PER_SHARD = int(STEP_BUDGET_SECONDS / PAGE_SECONDS / HEADROOM)
#: Shard steps pages.yml lists.
MAX_SHARDS = 24


def shards_for(pages):
    """N for this many pages; SystemExit naming the cap when it does not fit."""
    n = max(1, math.ceil(pages / PAGES_PER_SHARD))
    if n > MAX_SHARDS:
        raise SystemExit(
            f"{pages} pages need {n} shards of {PAGES_PER_SHARD}, but pages.yml lists only "
            f"{MAX_SHARDS} shard steps (tools/plan_shards.py MAX_SHARDS): add shard steps to "
            "pages.yml and raise MAX_SHARDS")
    return n


def main():
    idx = json.loads((ROOT / "puzzles" / "index.json").read_text(encoding="utf-8"))
    pages = len(idx["puzzles"])
    n = shards_for(pages)
    print(f"plan_shards: {pages} pages, {PAGES_PER_SHARD} a shard: {n} shard(s) of {MAX_SHARDS} possible")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
            out.write(f"shards={n}\npages={pages}\n")


if __name__ == "__main__":
    sys.exit(main())
