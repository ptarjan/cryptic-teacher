#!/usr/bin/env python3
"""Why did that annotation run die? Read it off the transcript, not off a log.

    python3 tools/annotate_postmortem.py <session-id> [--puzzle ID]
    python3 tools/annotate_postmortem.py <session-id> --json

daily_update.sh calls this whenever an annotation attempt ends without a clean
annotation, and puts the output IN the alert. The point is that the alert
arrives already carrying the evidence: a message saying "independent-12459 ran
past 90m" tells its reader to go and open a 270k-line log on a machine they are
not sitting at, which is the same as telling them nothing.

WHAT IT LOOKS FOR, and why these and not others. On 2026-09-11 and 09-12 two
Independent puzzles ran 3h44m and 1h21m and annotated nothing. The shape was
not a tool loop: it was turns that spent the ENTIRE 128,000-token output ceiling
on thinking, emitted no text and no tool call, and were retried verbatim. A
turn like that makes no progress, is charged in full, and --max-turns cannot
see it, because a turn that calls no tool is not a turn as far as that limit is
concerned. So the first thing this prints is how many turns ended that way.

The thinking figure is read from usage.output_tokens_details.thinking_tokens
rather than measured off the `thinking` blocks: on an adaptive-thinking model
those blocks carry an opaque signature and no readable text, so their length
says nothing about what the turn spent.

Every failure here is a no-op that still prints a line. This runs inside a run
that is already going wrong, and a post-mortem that raises turns one failure
into two.
"""
import argparse
import collections
import datetime
import json
import os
import pathlib
import sys

CLAUDE_DIR = pathlib.Path(os.environ.get("CLAUDE_CONFIG_DIR")
                          or pathlib.Path.home() / ".claude")
# The ceiling a turn is killed at. Only used to say "at the ceiling" rather than
# "a lot", so a wrong value here costs a word, not a conclusion.
CEILING = int(os.environ.get("CLAUDE_CODE_MAX_OUTPUT_TOKENS") or 128000)


def find_transcript(session):
    """The session's JSONL, wherever the CLI filed it."""
    path = pathlib.Path(session)
    if path.is_file():
        return path
    hits = sorted(CLAUDE_DIR.glob(f"projects/*/{session}.jsonl"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    return hits[0] if hits else None


def read_turns(path):
    """One entry per API turn, keyed by the API's own message id.

    The CLI writes one line per content block and stamps every one of them with
    the whole turn's usage, so counting lines bills a turn once per block and
    makes a turn that called a tool look like two turns, one of which did not.
    """
    turns = {}
    order = []
    first_ts = last_ts = None
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            ts = rec.get("timestamp")
            if ts:
                first_ts = first_ts or ts
                last_ts = ts
            if rec.get("type") != "assistant":
                continue
            msg = rec.get("message") or {}
            mid = msg.get("id") or rec.get("uuid")
            if mid not in turns:
                usage = msg.get("usage") or {}
                details = usage.get("output_tokens_details") or {}
                turns[mid] = {
                    "out": usage.get("output_tokens") or 0,
                    "thinking": details.get("thinking_tokens") or 0,
                    "stop": msg.get("stop_reason"),
                    "tools": [],
                    "text": "",
                }
                order.append(mid)
            body = msg.get("content")
            if not isinstance(body, list):
                continue
            for block in body:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    turns[mid]["tools"].append(
                        (block.get("name") or "?", block.get("input") or {}))
                elif block.get("type") == "text" and block.get("text", "").strip():
                    turns[mid]["text"] = block["text"].strip()
    return [turns[m] for m in order], first_ts, last_ts


def span(first_ts, last_ts):
    try:
        a = datetime.datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
        b = datetime.datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None, ""
    mins = int((b - a).total_seconds() // 60)
    return mins, (f"{mins // 60}h{mins % 60:02d}m" if mins >= 60 else f"{mins}m")


def describe_call(name, args):
    """One short line naming what a tool call actually did."""
    for key in ("command", "file_path", "pattern", "path", "query"):
        if isinstance(args.get(key), str):
            return f"{name} {args[key][:110]}"
    return name


def report(session, puzzle=None):
    path = find_transcript(session)
    if path is None:
        return [f"no transcript for session {session} under {CLAUDE_DIR}/projects "
                f"— nothing to go on but the log"], {}
    turns, first_ts, last_ts = read_turns(path)
    if not turns:
        return [f"transcript {path.name} holds no assistant turns — "
                f"the run died before the model answered once"], {}

    mins, pretty = span(first_ts, last_ts)
    stalled = [t for t in turns if t["stop"] == "max_tokens"]
    total_out = sum(t["out"] for t in turns)
    burnt = sum(t["out"] for t in stalled)
    peak_think = max((t["thinking"] for t in turns), default=0)
    tally = collections.Counter(n for t in turns for n, _ in t["tools"])
    last_call = next((describe_call(*t["tools"][-1])
                      for t in reversed(turns) if t["tools"]), None)
    last_text = next((t["text"] for t in reversed(turns) if t["text"]), "")

    who = puzzle or session[:8]
    lines = [f"{who} — {len(turns)} turn(s) over {pretty or '?'}, "
             f"{total_out:,} output tokens, {tally.total()} tool call(s)"]
    if stalled:
        # The finding, first, because it is the one that explains the clock.
        lines.append(
            f"  {len(stalled)} turn(s) hit the {CEILING:,}-token output ceiling and "
            f"emitted no tool call — {burnt:,} tokens bought nothing, and --max-turns "
            f"cannot see a turn that calls nothing")
    if peak_think:
        asked = os.environ.get("MAX_THINKING_TOKENS")
        note = (f", though MAX_THINKING_TOKENS asked for {int(asked):,}"
                if asked and asked.isdigit() and peak_think > int(asked) else "")
        lines.append(f"  peak thinking in one turn: {peak_think:,} tokens{note}")
    if tally:
        lines.append("  tools: " + ", ".join(f"{n}x{c}" for n, c in tally.most_common(6)))
    if last_call:
        lines.append(f"  last tool call: {last_call}")
    if last_text:
        lines.append(f"  last words: {last_text[:200]}")
    lines.append(f"  transcript: {path}")
    facts = {"session": session, "puzzle": puzzle, "turns": len(turns),
             "minutes": mins, "output_tokens": total_out,
             "ceiling_turns": len(stalled), "wasted_tokens": burnt,
             "peak_thinking": peak_think, "tool_calls": dict(tally),
             "transcript": str(path)}
    return lines, facts


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("session", help="session id, or a path to the .jsonl")
    ap.add_argument("--puzzle", help="the puzzle it was annotating, for the headline")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        lines, facts = report(args.session, args.puzzle)
    except Exception as exc:  # noqa: BLE001 — see the docstring: never two failures
        print(f"post-mortem failed to read session {args.session}: "
              f"{type(exc).__name__}: {exc}")
        return 0
    if args.json:
        json.dump(facts, sys.stdout, indent=1)
        print()
    else:
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
