#!/usr/bin/env python3
"""How many turns an annotation session takes, measured from the transcripts.

    python3 tools/turn_cost.py               # one line: last 7 days vs the 28 before
    python3 tools/turn_cost.py --weeks 8     # median per ISO week, oldest first
    python3 tools/turn_cost.py --json        # the same numbers, for something else to read

An annotation session is one Claude Code transcript whose first user message
starts with "Annotate" and whose assistant records sum to at least 20,000 output
tokens — the token floor is what separates a real annotation from a one-clue fix
that happens to open with the same word.

WHY THIS IS A TOOL AND NOT A SCRIPT SOMEBODY RAN ONCE. Turn cost was measured by
hand twice. The first measurement recorded a jump from a median of 47 API calls
per session to 66, and two rounds of work were justified as undoing it; the
second, on 2026-09-05 over 235 sessions, could not reproduce the 66 at all —
that window measures 51, and the real shape is a slow creep of 47 -> 51 -> 54
across three windows. A number nobody can re-derive is worse than no number,
because it still gets quoted. So the method lives here, runs nightly, and every
figure in this docstring can be checked by running the file.

The count is API calls, not wall time or dollars: it is the thing that moves
when the prompt makes the model go and look something up, which is the failure
this was built to watch for.
"""
import argparse
import collections
import datetime
import json
import pathlib
import statistics
import sys

TRANSCRIPTS = sorted(pathlib.Path.home().glob(".claude/projects/*cryptic*/*.jsonl"))
MIN_OUTPUT_TOKENS = 20000


def sessions():
    """Yield (started, api_calls, text_turns) for every annotation transcript."""
    for path in TRANSCRIPTS:
        started, first_user, calls, text_turns, out_tokens = None, None, 0, 0, 0
        try:
            with path.open(encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    msg = rec.get("message") or {}
                    if started is None and rec.get("timestamp"):
                        started = rec["timestamp"]
                    if first_user is None and rec.get("type") == "user":
                        content = msg.get("content")
                        if isinstance(content, list):
                            content = " ".join(c.get("text", "") for c in content
                                               if isinstance(c, dict))
                        first_user = (content or "") if isinstance(content, str) else ""
                    if rec.get("type") != "assistant":
                        continue
                    calls += 1
                    out_tokens += (msg.get("usage") or {}).get("output_tokens") or 0
                    body = msg.get("content")
                    if isinstance(body, list) and not any(
                            isinstance(c, dict) and c.get("type") == "tool_use" for c in body):
                        text_turns += 1
        except OSError:
            continue
        if not started or not (first_user or "").strip().startswith("Annotate"):
            continue
        if out_tokens < MIN_OUTPUT_TOKENS:
            continue
        yield datetime.datetime.fromisoformat(started.replace("Z", "+00:00")), calls, text_turns


def summarise(rows):
    if not rows:
        return None
    return {"n": len(rows),
            "calls": statistics.median(c for _, c, _ in rows),
            "text": statistics.median(t for _, _, t in rows)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--weeks", type=int, help="median per ISO week instead of the digest")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    rows = sorted(sessions())
    if not rows:
        print("turn cost: no annotation transcripts found")
        return 0
    now = datetime.datetime.now(datetime.timezone.utc)

    if args.weeks:
        buckets = collections.defaultdict(list)
        for row in rows:
            if (now - row[0]).days <= args.weeks * 7:
                buckets[row[0].strftime("%G-W%V")].append(row)
        out = {wk: summarise(v) for wk, v in sorted(buckets.items())}
        if args.json:
            json.dump(out, sys.stdout, indent=1)
            return 0
        for wk, s in out.items():
            print(f"{wk}  n={s['n']:3d}  median {s['calls']:.0f} calls, "
                  f"{s['text']:.0f} text turns")
        return 0

    recent = summarise([r for r in rows if (now - r[0]).days <= 7])
    prior = summarise([r for r in rows if 7 < (now - r[0]).days <= 35])
    if args.json:
        json.dump({"recent": recent, "prior": prior}, sys.stdout, indent=1)
        return 0

    if not recent:
        # Silence would read as "measured, nothing to say". A week with no
        # annotation at all is a fact about the pipeline, not about turn cost.
        print("turn cost: no annotation sessions in the last 7 days")
        return 0
    if not prior:
        print(f"turn cost: median {recent['calls']:.0f} calls over {recent['n']} "
              f"session(s) this week; no earlier window to compare against")
        return 0
    delta = recent["calls"] - prior["calls"]
    print(f"turn cost: median {recent['calls']:.0f} calls "
          f"({recent['text']:.0f} text) over {recent['n']} session(s) this week "
          f"vs {prior['calls']:.0f} ({prior['text']:.0f}) over {prior['n']} "
          f"in the 4 weeks before — {delta:+.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
