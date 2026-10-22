#!/usr/bin/env python3
"""Replay the wordplay refusals annotation runs hit, through today's evaluator.

    python3 tools/refusal_replay.py --hours 24

annotate_audit.py --wake names a refusal ("the wordplay does not give the
answer") as the fix target, but the count alone does not say what to fix: later
commits may have fixed most of them already, and many of the rest are right
parses in the wrong notation. This reads the same transcripts, takes every
`<id>: the wordplay does not give ANS: WP gives ...` line the annotate_check
runs printed, and with no model call says:

  1. how many of the distinct refused wordplays still fail in the current
     tools/wordplay.translate, and how many a later commit already fixed;
  2. the still-failing ones grouped by the evaluator's current message shape,
     with a count and two real examples (clue, answer, wordplay, message);
  3. the retries each refusal cost: checks run after the first refusal until
     the entry stopped being refused;
  4. one line naming the likeliest cause class (cause_line below).

Cause rule. Each still-failing wordplay is tried with the known rewrites
(REWRITES: `+` to a comma list, a sound() wrapper dropped, both). Then:
  - 40% or more pass after a rewrite            -> "notation slip, so prompt or message"
  - else, 40% or more give the answer's letters in the wrong order (the first
    candidate in the message is an anagram of the answer) -> "evaluator gap"
  - else                                         -> "model invention"
The share is of still-failing items, so a fix that already landed does not
vote.
"""
import argparse
import collections
import datetime
import glob
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

REPO = pathlib.Path(__file__).resolve().parent.parent
LINE = re.compile(r"^\s+(\d+-(?:across|down)): the wordplay does not give ([A-Z]+): "
                  r"(.*?) gives (.*?); the answer needs (.*)$", re.M)
SLIP_SHARE = 0.40
ORDER_SHARE = 0.40
EXAMPLES = 2

REWRITES = (
    ("+ to comma", lambda w: w.replace(" + ", ", ")),
    ("sound() dropped", lambda w: re.sub(r"^sound(?:<[^>]*>)?\((.*)\)$", r"\1", w, flags=re.S)),
    ("both", lambda w: re.sub(r"^sound(?:<[^>]*>)?\((.*)\)$", r"\1", w.replace(" + ", ", "), flags=re.S)),
)


def _wordplay():
    import wordplay
    return wordplay


def puzzle_index():
    return {pathlib.Path(f).stem: f for f in glob.glob(str(REPO / "puzzles" / "*" / "*" / "*.json"))}


def clue_text(index, pid, eid):
    path = index.get(pid)
    if not path:
        return None
    for e in json.load(open(path, encoding="utf-8")).get("entries", []):
        if f"{e.get('number')}-{e.get('direction')}" == eid or e.get("id") == eid:
            return (e.get("clue") or {}).get("text")
    return None


# ------------------------------------------------------------ the transcripts

def refusals(paths, since):
    """[{pid, eid, ans, wp, sess, retries, cleared}] — one per refused (session, puzzle, entry),
    with the first refused wordplay. retries counts the checks of that puzzle run after the
    first refusal up to and including the one that no longer refused the entry."""
    import annotate_audit as aud
    out = []
    for path in paths:
        try:
            if pathlib.Path(path).stat().st_mtime < since.timestamp():
                continue
        except OSError:
            continue
        calls, first_user, checks = {}, None, []
        try:
            fh = open(path, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                content = (rec.get("message") or {}).get("content")
                if rec.get("type") == "user" and first_user is None:
                    first_user = aud._text(content) if isinstance(content, (str, list)) else ""
                    if not aud.is_audited(first_user):
                        break
                if not isinstance(content, list):
                    continue
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_use":
                        calls[b.get("id")] = (b.get("input") or {}).get("command") or ""
                    elif b.get("type") == "tool_result":
                        cmd = calls.get(b.get("tool_use_id"), "")
                        if "annotate_check" in cmd or "annotate_bag.py check" in cmd:
                            reports = (aud.bag_reports(aud._text(b.get("content")))
                                       if "annotate_bag.py check" in cmd
                                       else [(aud.single_check_id(cmd), aud._text(b.get("content")))])
                            checks.append((rec.get("timestamp"), reports))
        per = collections.defaultdict(list)       # pid -> [report text, in order]
        for _, reports in checks:
            for pid, text in reports:
                per[pid].append(text)
        for pid, texts in per.items():
            for eid in dict.fromkeys(m.group(1) for t in texts for m in LINE.finditer(t)):
                key = re.compile(r"^\s+" + re.escape(eid) + r": the wordplay does not give", re.M)
                hits = [i for i, t in enumerate(texts) if key.search(t)]
                first = next(m for m in LINE.finditer(texts[hits[0]]) if m.group(1) == eid)
                end = next((i for i in range(hits[0] + 1, len(texts)) if not key.search(texts[i])), None)
                out.append({"pid": pid, "eid": eid, "ans": first.group(2), "wp": first.group(3),
                            "sess": pathlib.Path(path).stem[:8], "cleared": end is not None,
                            "retries": (end - hits[0]) if end is not None else len(texts) - hits[0] - 1})
    return out


# ------------------------------------------------------------------ the replay

def try_translate(wp, clue, ans):
    """None when it passes, else the evaluator's current message."""
    try:
        _wordplay().translate({"wp": wp, "notes": {}}, clue, ans)
        return None
    except Exception as e:      # any failure is a message to group, not a crash
        return str(e)


def message_shape(msg, wp):
    """The evaluator's message with this item's own words taken out, so instances group."""
    out = outcome(msg, wp)
    if out.startswith("gives nothing"):
        kind = "gives nothing"
    elif "letters against" in out:
        kind = "wrong length"
    elif out.startswith("gives the letters"):
        kind = "letters, no order"
    elif " or " in out:
        kind = "several candidate strings"
    else:
        kind = "wrong letters"
    m = re.match(r"\s*([a-z]+)(?:<[^>]*>)?\(", wp)
    opens = m.group(1) + "(" if m else ("a span" if wp.lstrip().startswith("[") else "other")
    return f"{kind}; wordplay opens with {opens}"


def outcome(msg, wp=""):
    """What the evaluator says the wordplay gives: 'gives X (3 letters against 7)'."""
    m = re.search(r" (gives .*?); the answer needs [A-Z]+(?: here)?(?: \((.*?)\))?\s*$",
                  msg.replace(wp, "<wp>") if wp else msg)
    return (m.group(1) + (f" ({m.group(2)})" if m.group(2) else "")) if m else msg


def is_reorder(msg, ans):
    m = re.search(r" gives ([A-Z]+)", msg)
    return bool(m) and sorted(m.group(1)) == sorted(ans)


def replay(items, index=None):
    """Annotate each refusal with `now` ('fixed' or 'fails'), the current message, the rewrite
    that rescues it, and the clue."""
    index = puzzle_index() if index is None else index
    seen, out = {}, []
    for it in items:
        k = (it["pid"], it["eid"], it["wp"])
        if k not in seen:
            clue = clue_text(index, it["pid"], it["eid"])
            if clue is None:
                continue
            msg = try_translate(it["wp"], clue, it["ans"])
            fixed = next((n for n, f in REWRITES if msg and f(it["wp"]) != it["wp"]
                          and try_translate(f(it["wp"]), clue, it["ans"]) is None), None)
            seen[k] = dict(it, clue=clue, now="fixed" if msg is None else "fails",
                           msg=msg or "", rewrite=fixed if msg else None)
            out.append(seen[k])
        else:
            seen[k]["retries"] = max(seen[k]["retries"], it["retries"])
    return out


def cause(failing):
    """(line, slip share, reorder share) from the still-failing items."""
    n = len(failing)
    if not n:
        return "no cause: nothing still fails", 0.0, 0.0
    slip = sum(1 for f in failing if f["rewrite"]) / n
    order = sum(1 for f in failing if is_reorder(f["msg"], f["ans"])) / n
    if slip >= SLIP_SHARE:
        why = "notation slip, so prompt or message"
    elif order >= ORDER_SHARE:
        why = "evaluator gap"
    else:
        why = "model invention"
    return f"likeliest cause: {why} ({slip:.0%} fixed by a known rewrite, {order:.0%} right letters in the wrong order)", slip, order


# ------------------------------------------------------------------ the report

def shorten(s, n):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n - 1] + "…"


def report(items, budget=1500):
    """The wake's refusal section, mechanical, within `budget` characters."""
    if not items:
        return "replay: no refused wordplays found in the transcripts"
    fails = [i for i in items if i["now"] == "fails"]
    fixed = len(items) - len(fails)
    cleared = [i for i in items if i["cleared"]]
    lines = [f"replay through today's evaluator: {len(items)} distinct refused wordplays, "
             f"{len(fails)} still fail, {fixed} already fixed by later commits"]
    if cleared:
        r = sorted(i["retries"] for i in cleared)
        lines.append(f"retries each refusal cost before it cleared: median {r[len(r) // 2]}, "
                     f"max {r[-1]} extra checks ({len(cleared)} of {len(items)} cleared)")
    groups = collections.defaultdict(list)
    for f in fails:
        groups[message_shape(f["msg"], f["wp"])].append(f)
    lines.append(cause(fails)[0])
    for shape, fs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"{len(fs)}x {shape}")
        for f in fs[:EXAMPLES]:
            lines.append(f"  {f['pid']} {f['eid']} {shorten(f['clue'], 60)} = {f['ans']}: "
                         f"{shorten(f['wp'], 90)} -> {shorten(outcome(f['msg'], f['wp']), 60)}"
                         + (f" [fix: {f['rewrite']}]" if f["rewrite"] else ""))
    text = "\n".join(lines)
    while len(text) > budget and "\n  " in text:       # drop examples from the tail first
        text = text[:text.rindex("\n  ")]
    return text[:budget]


def audit_section(since, budget=1500):
    from turn_cost import CLAUDE_DIR
    paths = glob.glob(str(CLAUDE_DIR / "projects" / "*cryptic*" / "*.jsonl"))
    return report(replay(refusals(paths, since)), budget)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hours", type=int, default=24)
    args = ap.parse_args(argv)
    now = datetime.datetime.now(datetime.timezone.utc)
    print(audit_section(now - datetime.timedelta(hours=args.hours), 6000))
    return 0


if __name__ == "__main__":
    sys.exit(main())
