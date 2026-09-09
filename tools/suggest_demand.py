#!/usr/bin/env python3
"""Probe Google autocomplete for puzzle-number demand.

Search Console can only measure puzzles whose pages already rank, and most of
the annotation backlog never ranks at all, so this asks the query logs instead.
Advisory only: nothing downstream sorts on it. The annotation queue runs newest
first, because an impression count rises with a page's age and so ranks the
archive above the puzzles people are actually searching for.

Endpoint: https://suggestqueries.google.com/complete/search?client=firefox&q=...
No key, but it 429s if hit too fast or without a browser User-Agent, so we
sleep between requests and abort loudly on a 429 rather than limping on.

READING RULE (measured 2026-09-08, load-bearing): autocomplete volunteers
real puzzle numbers scraped from other people's query logs, but past a
certain depth it starts padding with a straight numeric fill -- a run of
consecutive integers Google invented to fill out ten suggestions, not
evidence anyone searched for them. A single query's suggestion list can mix
both: a couple of real, scattered numbers plus a run of filler. So the
filter is applied per-query, not globally: within one query's response,
any maximal run of >=4 consecutive integers is discarded as filler; short
runs and scattered singletons are kept as query-log evidence.

Demand score for a number = how many *different* prefixes volunteered it
(after the run filter), on the theory that a number several unrelated
queries converge on is more wanted than one only one query happened to
mention.
"""

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ENDPOINT = "https://suggestqueries.google.com/complete/search"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
SLEEP_SECONDS = 0.5
RUN_MIN_LEN = 4  # a maximal run of >= this many consecutive ints is filler

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = REPO_ROOT / "puzzles" / "index.json"
OUT_PATH = REPO_ROOT / "tools" / "suggest_demand.json"

# One base autocomplete prefix per series -- the phrasing people actually type.
SERIES_PREFIX = {
    "cryptic": "guardian cryptic crossword ",
    "quiptic": "guardian quiptic ",
    "everyman": "everyman crossword ",
    "independent": "independent crossword ",
    "indysunday": "independent on sunday crossword ",
}


def fetch_suggestions(query):
    """Return the list of suggestion strings for `query`, or raise on 429."""
    url = ENDPOINT + "?" + urllib.parse.urlencode(
        {"client": "firefox", "q": query}
    )
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    # firefox client shape: [query, [suggestion, ...], ...]
    return data[1] if len(data) > 1 else []


def extract_runs_filtered(numbers):
    """Given a set/list of ints from one query, drop maximal runs of
    >= RUN_MIN_LEN consecutive integers (Google's numeric fill), keep the
    rest. Returns (kept, dropped) as sorted lists."""
    nums = sorted(set(numbers))
    kept, dropped = [], []
    i = 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        run = nums[i : j + 1]
        if len(run) >= RUN_MIN_LEN:
            dropped.extend(run)
        else:
            kept.extend(run)
        i = j + 1
    return kept, dropped


def build_queries(series_ranges):
    """Yield (series, query_string) for every prefix we probe."""
    for series, base in SERIES_PREFIX.items():
        lo, hi = series_ranges[series]
        # 1. bare prefix -- whatever Google offers with no number typed at all
        yield series, base.strip()

        # 2. number-stub walk: truncate the archive's number range to its
        # hundreds prefix and walk every stub in that band, e.g. archive
        # 4089-4168 -> stubs "40", "41" -> "everyman crossword 40", "...41"
        stub_lo, stub_hi = lo // 100, hi // 100
        stubs = [str(s) for s in range(stub_lo, stub_hi + 1)]
        for stub in stubs:
            yield series, base + stub

        # 3. intent variants on the same stubs -- catches suggestions Google
        # only offers once a searcher signals they want answers, not just
        # the puzzle itself
        for stub in stubs:
            yield series, base + stub + " answers"
            yield series, base + stub + " explained"


def numbers_in_suggestion(text):
    return [int(n) for n in re.findall(r"\d{3,6}", text)]


def main():
    index = json.loads(INDEX_PATH.read_text())
    puzzles = index["puzzles"]

    series_ranges = {}
    known_ids = {}  # (series, number) -> id
    for p in puzzles:
        s, n = p["series"], p["number"]
        known_ids[(s, n)] = p["id"]
        lo, hi = series_ranges.get(s, (n, n))
        series_ranges[s] = (min(lo, n), max(hi, n))

    queries = list(build_queries(series_ranges))
    print(f"Probing {len(queries)} autocomplete queries across "
          f"{len(SERIES_PREFIX)} series...", file=sys.stderr)

    # per-number bookkeeping
    prefixes_per_number = {}  # (series, number) -> set of query strings
    raw_kept_total = 0
    raw_dropped_total = 0
    per_query_log = []  # for reporting

    for i, (series, query) in enumerate(queries):
        try:
            suggestions = fetch_suggestions(query)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print(f"STOPPING: got HTTP 429 (rate limited) on query "
                      f"{i+1}/{len(queries)}: {query!r}", file=sys.stderr)
                break
            print(f"WARNING: HTTP {e.code} on {query!r}, skipping",
                  file=sys.stderr)
            time.sleep(SLEEP_SECONDS)
            continue
        except Exception as e:  # noqa: BLE001
            print(f"WARNING: {type(e).__name__} on {query!r}: {e}, skipping",
                  file=sys.stderr)
            time.sleep(SLEEP_SECONDS)
            continue

        lo, hi = series_ranges[series]
        raw_numbers = set()
        for s in suggestions:
            for n in numbers_in_suggestion(s):
                if query.strip() == SERIES_PREFIX[series].strip():
                    # bare prefix: no typed stub to anchor on, so just
                    # sanity-range it against this series' known archive
                    if lo - 150 <= n <= hi + 150:
                        raw_numbers.add(n)
                else:
                    # stub-anchored query: only trust numbers that actually
                    # continue the digits we typed (real completions), not
                    # unrelated numbers (e.g. years) the suggestion also
                    # contains
                    stub = query[len(SERIES_PREFIX[series]):].split()[0]
                    if str(n).startswith(stub):
                        raw_numbers.add(n)

        kept, dropped = extract_runs_filtered(raw_numbers)
        raw_kept_total += len(kept)
        raw_dropped_total += len(dropped)
        per_query_log.append((series, query, len(kept), len(dropped)))

        for n in kept:
            key = (series, n)
            prefixes_per_number.setdefault(key, set()).add(query)

        time.sleep(SLEEP_SECONDS)

    # Build output scores keyed by our puzzle id, restricted to numbers that
    # match a puzzle we actually have in the archive.
    scores = {}
    for (series, n), prefix_set in prefixes_per_number.items():
        pid = known_ids.get((series, n))
        if pid is None:
            continue
        scores[pid] = len(prefix_set)

    out = {
        "_why": (
            "Google autocomplete co-occurrence. Search Console can only "
            "measure puzzles whose pages already rank, so ~95 of ~132 "
            "queued-for-annotation puzzles are invisible to it. This is "
            "NOT impressions and NOT click volume -- it is how many "
            "distinct autocomplete prefixes volunteered a given puzzle "
            "number, which is query-log-derived signal from searches "
            "across the web, not just our own site. A puzzle scoring 0 or "
            "absent here was not offered by any probed prefix; it is not "
            "proven low-demand, only unprobed or below Google's return "
            "threshold. Consecutive numeric runs (Google's autocomplete "
            "filling out results, not real query-log entries) are "
            "filtered out per-query before scoring."
        ),
        "_window": {
            "date": "2026-09-08",
            "endpoint": ENDPOINT,
            "run_filter_min_consecutive": RUN_MIN_LEN,
        },
        "scores": scores,
    }
    OUT_PATH.write_text(json.dumps(out, indent=1) + "\n")

    print(f"\nQueries run: {len(per_query_log)}/{len(queries)}",
          file=sys.stderr)
    print(f"Raw numbers kept (scattered, treated as evidence): "
          f"{raw_kept_total}", file=sys.stderr)
    print(f"Raw numbers dropped (consecutive-run filler): "
          f"{raw_dropped_total}", file=sys.stderr)
    print(f"Distinct puzzle ids scored: {len(scores)}", file=sys.stderr)
    print(f"Wrote {OUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
