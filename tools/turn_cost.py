#!/usr/bin/env python3
"""How many turns an annotation session takes, measured from the transcripts.

    python3 tools/turn_cost.py               # one line: last 7 days vs the 28 before
    python3 tools/turn_cost.py --weeks 8     # median per ISO week, oldest first
    python3 tools/turn_cost.py --json        # the same numbers, for something else to read

An annotation session is one Claude Code transcript whose first user message
starts with ANNOTATE_PREFIX, the opening of the headless annotate prompt; a
one-clue fix or a fix-the-validator run opens differently. No output-token floor:
a cheap run is exactly the one a floor would drop, which biases the median up.
tools/annotate_audit.py reads the same sessions for what the turns went on.

This is a tool so the number can be re-derived: it runs nightly (daily_update.sh)
and every figure it prints comes from the transcripts, not from a hand
measurement that still gets quoted after nobody can reproduce it.

The count is API calls, not wall time or dollars: it is the thing that moves
when the prompt makes the model go and look something up, which is the failure
this was built to watch for.
"""
import argparse
import collections
import datetime
import json
import functools
import os
import pathlib
import statistics
import sys
import time

# The same directory the CLI wrote them to, which is not under $HOME once the
# run is not the Mac's: this is called with `|| true`, so a wrong path here
# reports nothing at all rather than failing.
CLAUDE_DIR = pathlib.Path(os.environ.get("CLAUDE_CONFIG_DIR")
                          or pathlib.Path.home() / ".claude")



@functools.cache
def transcripts():
    """The annotation runs' transcripts, globbed on first ask: ~21k files and
    half a second, which every importer (annotate_check.py, through
    blog_facts) paid at import when this was a module constant, though only
    sessions() reads it."""
    return sorted(CLAUDE_DIR.glob("projects/*cryptic*/*.jsonl"))
ANNOTATE_PREFIX = "Annotate the crossword"
# A cold-solve run (puzzle_worker.sh) opens with the solve and ends "by handing
# you this task: Annotate the crossword ...", so the prefix is not at the start.
ANNOTATE_HANDOFF = "handing you this task: " + ANNOTATE_PREFIX


def is_annotate_session(first_user):
    text = (first_user or "").strip()
    return text.startswith(ANNOTATE_PREFIX) or ANNOTATE_HANDOFF in text


#: Each transcript's (started, calls, text_turns, is_annotation), keyed by
#: path and remembered with its size and mtime: a finished session's file never
#: changes, so a nightly run parses only the transcripts written since the last
#: one. Reparsing all ~21k every night grew past the checks unit's whole limit
#: at nice 19 on a loaded box (2026-10-15: killed at 45m, >10m in this alone).
CACHE = pathlib.Path(os.environ.get("XDG_CACHE_HOME") or pathlib.Path.home() / ".cache") / "cryptic-teacher" / "turn_cost.json"


def _load_cache():
    try:
        return json.loads(CACHE.read_text())
    except (OSError, ValueError):
        return {}


def _save_cache(cache):
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache))
        tmp.replace(CACHE)
    except OSError:
        pass  # a cache that cannot be written costs the next run time, not the number


def sessions(since_days=None):
    """Yield (started, api_calls, text_turns) for every annotation transcript,
    or, with since_days, every one whose file was written within that many days
    (a session cannot have started after its transcript's last write)."""
    cache, seen, saved = _load_cache(), {}, time.monotonic()
    cut = None if since_days is None else datetime.datetime.now().timestamp() - since_days * 86400
    for path in transcripts():
        try:
            st = path.stat()
        except OSError:
            continue
        if cut is not None and st.st_mtime < cut:
            continue
        key, sig = str(path), [st.st_size, st.st_mtime]
        hit = cache.get(key)
        if hit and hit[0] == sig:
            row = hit[1]
        else:
            row = _parse(path)
            # Saved as it goes: a cold run (every transcript, 7.5 GB) can be
            # killed with the unit, and must still leave the next one less to do.
            if time.monotonic() - saved > 60:
                cache.update(seen)
                _save_cache(cache)
                saved = time.monotonic()
        seen[key] = [sig, row]
        if row and row[3]:
            yield datetime.datetime.fromisoformat(row[0]), row[1], row[2]
    # Entries outside this run's window are kept: a --weeks run reads them.
    cache.update(seen)
    _save_cache(cache)


def _parse(path):
    """[started, calls, text_turns, is_annotation] of one transcript, or None."""
    started, first_user = None, None
    # Keyed by the API's own message id, because the CLI writes one JSONL
    # line PER CONTENT BLOCK and stamps every one of them with the whole
    # turn's usage. Counting lines bills a turn once per block, and a line
    # holding only the text half of a turn that also called a tool looks
    # exactly like a turn that called nothing.
    turns = {}
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
                mid = msg.get("id") or rec.get("uuid")
                if mid not in turns:
                    turns[mid] = False
                body = msg.get("content")
                if isinstance(body, list) and any(
                        isinstance(c, dict) and c.get("type") == "tool_use" for c in body):
                    turns[mid] = True
    except OSError:
        return None
    if not started:
        return None
    is_annotation = is_annotate_session(first_user)
    calls = len(turns)
    text_turns = sum(1 for acted in turns.values() if not acted)
    return [started.replace("Z", "+00:00"), calls, text_turns, is_annotation]


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

    # The digest reads 35 days back (7 + the 28 before); a day of slack for
    # timezones and a session that ran across midnight.
    rows = sorted(sessions(since_days=(args.weeks * 7 if args.weeks else 35) + 1))
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
