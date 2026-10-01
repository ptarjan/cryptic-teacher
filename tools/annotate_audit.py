#!/usr/bin/env python3
"""What the annotation runs are spending their turns on, ranked — from the transcripts.

    python3 tools/annotate_audit.py              # last 48h vs the 48h before, ranked
    python3 tools/annotate_audit.py --hours 168  # a wider window
    python3 tools/annotate_audit.py --json
    python3 tools/annotate_audit.py --wake       # the daily job: save, wake only on news
    python3 tools/annotate_audit.py --wake --dry-run   # print the wake, send and record nothing

The bill is the fix loop. Nearly every headless annotate run fails its first
`tools/annotate_check.py`, and every turn after that re-sends the whole
transcript, so the next thing to fix is whichever check or refusal costs the
most sessions a turn. This reads the transcripts and says which, with no model
call: every figure is arithmetic over the JSONL the CLI already wrote.

A session is a transcript under $CLAUDE_CONFIG_DIR/projects/*cryptic*/ whose
first user message starts with turn_cost.ANNOTATE_PREFIX. Findings are ranked by the
share of the window's sessions they touch (one session counts once, however
many lines it produced), so the first line is what to fix next.

Error lines are named by the check that wrote them: every `f"{tag}: ..."`
message in tools/validate_annotations.py is read out of its AST and becomes a
pattern, so a reworded message moves with its check and nothing here has to be
kept in step by hand. A line no pattern matches is shown as its first words.

--wake is the scheduled form. It saves the report to .annotate_audit/ (ignored
by git) and wakes the room only when one of the top three findings is new, or
has clearly grown since the room was last told about it, or median cost or
turns regressed against the previous window. What it told the room is kept in
.annotate_audit/state.json, so an unchanged finding never wakes it twice.
Below MIN_SESSIONS sessions in either window it reports and stays quiet.
"""
import argparse
import ast
import collections
import datetime
import json
import os
import pathlib
import re
import statistics
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from turn_cost import (
    ANNOTATE_PREFIX,
    CLAUDE_DIR,
)

REPO = pathlib.Path(__file__).resolve().parent.parent
VALIDATOR = REPO / "tools" / "validate_annotations.py"
STATE_DIR = REPO / ".annotate_audit"
WAKE_SH = os.environ.get("WAKE_SH", "/Users/pt/github/household/tools/wake.sh")
ROOM = os.environ.get("HOUSEHOLD_ROOM", "cryptic-crosswords")

# $/MTok: input, output, cache read, 5-minute cache write, 1-hour cache write.
PRICES = {"claude-opus-5-5": (4, 20, 0.20, 5, 8)}
MIN_SESSIONS = 30          # per window, before a trend or a finding may wake anyone
WAKE_SHARE = 0.10          # a finding must touch this share of sessions to wake
WORSE_RATIO, WORSE_POINTS = 1.25, 0.10   # "clearly worse" than when last woken
REGRESSION = 0.15          # median cost or turns up this much vs the window before
FORGET_DAYS = 7            # a finding gone this long is new again if it returns
KEEP_REPORTS = 30

REFUSED = {  # tool_result error text -> kind; these are the permission layer saying no
    "brace with quote": "heredoc or inline fix script refused (brace with quote)",
    "multiple operations": "compound command refused (&&, ;, | or xargs)",
    "Output redirection": "output redirection outside the worktree refused",
    "was blocked": "path outside the worktree blocked",
    "sed command requires approval": "sed with a write flag refused",
    "requires approval": "command needs an approval the run cannot give",
    "needs approval": "command needs an approval the run cannot give",
}


# ---------------------------------------------------------------- rule names

def load_templates(source):
    """[(regex, check name, literal chars)] for every `f"{tag}: ..."` message."""
    out = []
    for fn in ast.parse(source).body:
        if not isinstance(fn, ast.FunctionDef):
            continue
        for node in ast.walk(fn):
            if not isinstance(node, ast.JoinedStr) or len(node.values) < 2:
                continue
            head, lit = node.values[0], node.values[1]
            if not (isinstance(head, ast.FormattedValue) and isinstance(head.value, ast.Name)
                    and head.value.id == "tag" and isinstance(lit, ast.Constant)
                    and str(lit.value).startswith(": ")):
                continue
            parts, chars = [], 0
            for v in node.values[1:]:
                if isinstance(v, ast.Constant):
                    parts.append(re.escape(str(v.value)))
                    chars += len(str(v.value))
                else:
                    parts.append(".*?")
                if chars >= 40:
                    break
            name = fn.name
            if not name.startswith("check_"):
                name = f"{fn.name}: {' '.join(str(lit.value)[2:].split()[:4])}"
            out.append((re.compile(r"\S+" + "".join(parts), re.DOTALL), name, chars))
    return out


def rule_name(line, templates):
    """The check an ERROR line came from, or its first words if none matches."""
    body = re.sub(r"^\s*ERROR:\s*", "", line).strip()
    best = max(((c, n) for rx, n, c in templates if rx.match(body)), default=None)
    if best:
        return best[1]
    if body.startswith("schema:"):
        return "schema: " + re.sub(r"\$\.entries\[\d+\]\.?", "", body[7:]).strip()[:70]
    body = re.sub(r"^\S+:\s*", "", body)
    body = re.sub(r"'[^']*'|\"[^\"]*\"", "'…'", body)
    return " ".join(body.split()[:7])


def stopped_names(text):
    """Why annotate_check refused to apply: each schema complaint, entry index dropped."""
    found = {re.sub(r"\$\.entries\[\d+\]\.?", "", m).strip()
             for m in re.findall(r"SCHEMA (\$[^;\n]*)", text)}
    # apply_annotations' refusal: one "  <entry id>[ field]: finding" per line.
    listed = text.partition("refused to write, fix these in the _ann file:\n")[2]
    for line in listed.split("\n\n")[0].splitlines():
        m = re.match(r"\s+\d+-(?:across|down)\s*(.*?)(?: — .*)?$", line)
        if m:
            found.add(re.sub(r"\[\d+\]", "[]", m.group(1)).lstrip(":").strip())
    if found:
        return {f"apply refused: schema {f}" for f in found}
    m = re.search(r"STOPPED — (.{0,60})", text)
    return {"STOPPED: " + (m.group(1) if m else "?")}


def failed_command(command):
    """The command whose status a Bash call returned: the last of a `;` or `|` chain.

    The commands before it ran and delivered their output, so naming the call by
    its first word blames a `cat` for the `ls` after it. Quoted strings and heredoc
    bodies are blanked first, so a `;` inside `python3 -c "..."` splits nothing."""
    body = re.sub(r"<<-?\s*['\"]?(\w+)['\"]?.*?\n\1\b", "", command, flags=re.DOTALL)
    body = re.sub(r"'[^']*'|\"(?:[^\"\\]|\\.)*\"", "''", body)
    return ([seg.strip() for seg in re.split(r"[;|\n]", body) if seg.strip()] or [""])[-1]


def tool_error_kind(tool, command, text):
    """Name a failed tool call, or None when nothing was wasted: annotate_check
    reporting errors, or an `ls` answering that a file is not there yet."""
    if "annotate_check" in command and text.startswith("Exit code"):
        return None
    for needle, kind in REFUSED.items():
        if needle in text[:200]:
            return kind
    if re.search(r"no `[^`]+` in validate_annotations\.py", text):
        return "--explain given a field name, not a check name"
    if "File does not exist" in text:
        return f"{tool} of a file that does not exist"
    if "No changes to make" in text:
        return "Edit with old_string == new_string"
    if re.search(r"Found \d+ matches", text):
        return "Edit whose old_string matches more than once"
    if "String to replace not found" in text:
        return "Edit whose old_string is not in the file"
    if text.startswith("Exit code"):
        last = failed_command(command)
        if (re.match(r"ls\b", last) and "ls:" in text and all(
                "No such file or directory" in ln for ln in text.splitlines() if ln.startswith("ls:"))):
            return None     # an existence probe answered "not yet": no call wasted
        word = (last.split() or ["?"])[0]
        word = "python3 -c" if last.startswith("python3 -c") else word
        return f"{tool} `{word}` exited non-zero"
    return f"{tool}: " + " ".join(text.split()[:5])


# ---------------------------------------------------------------- one session

def _text(content):
    if isinstance(content, str):
        return content
    return "\n".join(c.get("text", "") for c in content or [] if isinstance(c, dict))


def _cost(model, usage):
    p = PRICES.get(model)
    if not p:
        return None
    cc = usage.get("cache_creation") or {}
    w5 = cc.get("ephemeral_5m_input_tokens", 0) if cc else usage.get("cache_creation_input_tokens", 0)
    return (usage.get("input_tokens", 0) * p[0] + usage.get("output_tokens", 0) * p[1]
            + usage.get("cache_read_input_tokens", 0) * p[2] + w5 * p[3]
            + cc.get("ephemeral_1h_input_tokens", 0) * p[4]) / 1e6


def read_session(path, templates):
    """One annotate transcript's numbers, or None if it is not an annotate run."""
    first_user, t0, t1, model = None, None, None, None
    turns = collections.OrderedDict()       # message id -> (usage, after first check)
    calls, check_ids, check_outs = {}, set(), []
    s = {"tool_errors": collections.Counter(), "memory": False, "validator_reads": 0, "max_tokens": 0}
    try:
        fh = open(path, encoding="utf-8", errors="replace")  # noqa: SIM115 — closed by `with fh` below
    except OSError:
        return None
    with fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("timestamp"):
                t1 = rec["timestamp"]
                t0 = t0 or t1
            msg = rec.get("message") or {}
            if rec.get("type") == "user":
                content = msg.get("content")
                if first_user is None:
                    first_user = _text(content) if isinstance(content, (str, list)) else ""
                    if not first_user.startswith(ANNOTATE_PREFIX):
                        return None
                for b in content if isinstance(content, list) else []:
                    if not isinstance(b, dict) or b.get("type") != "tool_result":
                        continue
                    text = _text(b.get("content"))
                    if b.get("tool_use_id") in check_ids:
                        check_outs.append(text)
                    if b.get("is_error"):
                        tool, cmd = calls.get(b.get("tool_use_id"), ("?", ""))
                        kind = tool_error_kind(tool, cmd, text)
                        if kind:
                            s["tool_errors"][kind] += 1
            elif rec.get("type") == "assistant":
                model = msg.get("model") or model
                mid = msg.get("id") or rec.get("uuid")
                if mid not in turns:
                    turns[mid] = (msg.get("usage") or {}, bool(check_ids))
                    s["max_tokens"] += msg.get("stop_reason") == "max_tokens"
                for b in msg.get("content") or []:
                    if not isinstance(b, dict) or b.get("type") != "tool_use":
                        continue
                    inp = b.get("input") or {}
                    cmd = inp.get("command") or inp.get("file_path") or ""
                    calls[b.get("id")] = (b.get("name"), cmd)
                    blob = json.dumps(inp)
                    if "/memory/" in blob or "MEMORY.md" in blob:
                        s["memory"] = True
                    if "validate_annotations.py" in cmd and "--explain" not in cmd and (
                            b.get("name") == "Read" or re.search(r"\b(grep|sed|cat|head|tail|awk)\b", cmd)):
                        s["validator_reads"] += 1
                    if b.get("name") == "Bash" and "annotate_check" in cmd:
                        check_ids.add(b.get("id"))
    if not first_user or not turns or not t0:
        return None
    costs = [(_cost(model, u), after) for u, after in turns.values()]
    first_usage = next(iter(turns.values()))[0]
    s.update(
        start=datetime.datetime.fromisoformat(t0.replace("Z", "+00:00")),
        model=model, turns=len(turns),
        wall_min=(datetime.datetime.fromisoformat(t1.replace("Z", "+00:00"))
                  - datetime.datetime.fromisoformat(t0.replace("Z", "+00:00"))).total_seconds() / 60,
        cost=None if any(c is None for c, _ in costs) else sum(c for c, _ in costs),
        cost_after_check=sum(c or 0 for c, after in costs if after),
        turns_after_check=sum(1 for _, after in costs if after),
        first_ctx=sum(first_usage.get(k, 0) for k in
                      ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")),
        cache_1h=any((u.get("cache_creation") or {}).get("ephemeral_1h_input_tokens")
                     for u, _ in turns.values()),
        checks=len(check_outs), first_fail=None, first_rules=collections.Counter(),
        all_rule_lines=collections.Counter())
    for i, out in enumerate(check_outs):
        errs = [ln for ln in out.splitlines() if ln.lstrip().startswith("ERROR:")]
        names = collections.Counter(rule_name(ln, templates) for ln in errs)
        if "STOPPED" in out:
            names.update(stopped_names(out))
        s["all_rule_lines"].update(names)
        if i == 0:
            s["first_fail"] = bool(names)
            s["first_rules"] = names
    return s


def sessions(since, templates):
    floor = since.timestamp() - 86400    # mtime is the LAST write; a run can start earlier
    for path in CLAUDE_DIR.glob("projects/*cryptic*/*.jsonl"):
        try:
            if path.stat().st_mtime < floor:
                continue
        except OSError:
            continue
        s = read_session(path, templates)
        if s and s["start"] >= since:
            yield s


# ---------------------------------------------------------------- the report

def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def summarise(rows):
    checked = [r for r in rows if r["first_fail"] is not None]
    total = sum(r["cost"] or 0 for r in rows)
    return {
        "n": len(rows),
        "turns": med(r["turns"] for r in rows),
        "cost": med(r["cost"] for r in rows),
        "wall_min": med(r["wall_min"] for r in rows),
        "checks": med(r["checks"] for r in rows),
        "first_fail": (sum(r["first_fail"] for r in checked) / len(checked)) if checked else None,
        "first_errors": med(sum(r["first_rules"].values()) for r in checked),
        "after_check_share": (sum(r["cost_after_check"] for r in rows) / total) if total else None,
        "turns_after_check": med(r["turns_after_check"] for r in rows),
        "first_ctx": med(r["first_ctx"] for r in rows),
    }


def findings(rows):
    """[{key, title, share, detail}] ranked by share of sessions touched."""
    n = len(rows)
    if not n:
        return []
    out = []
    failed = [r for r in rows if r["first_fail"]]
    by_sessions, by_lines = collections.Counter(), collections.Counter()
    for r in rows:
        by_sessions.update(set(r["first_rules"]))
        by_lines.update(r["first_rules"])
    for name, k in by_sessions.items():
        out.append({"key": f"rule:{name}", "title": f"first check fails on `{name}`", "share": k / n,
                        "detail": f"{k} of {n} sessions ({k / max(len(failed), 1):.0%} of first-check "
                               f"failures), {by_lines[name]} error lines"})
    kinds, calls = collections.Counter(), collections.Counter()
    for r in rows:
        kinds.update(set(r["tool_errors"]))
        calls.update(r["tool_errors"])
    for kind, k in kinds.items():
        out.append({"key": f"tool:{kind}", "title": kind, "share": k / n,
                        "detail": f"{k} of {n} sessions, {calls[kind]} calls"})
    waste = [
        ("waste:memory", "auto-memory touched", lambda r: r["memory"], None),
        ("waste:validator", "validate_annotations.py read instead of --explain",
         lambda r: r["validator_reads"], "validator_reads"),
        ("waste:max_tokens", "turn hit the output-token ceiling", lambda r: r["max_tokens"], "max_tokens"),
        ("waste:cache_1h", "1-hour cache writes (5m TTL not applied)", lambda r: r["cache_1h"], None),
    ]
    for key, title, hit, field in waste:
        k = sum(1 for r in rows if hit(r))
        if k:
            extra = f", {sum(r[field] for r in rows)} turns" if field else ""
            out.append({"key": key, "title": title, "share": k / n, "detail": f"{k} of {n} sessions{extra}"})
    out.sort(key=lambda f: (-f["share"], f["key"]))
    return out


def trend_items(cur, prev):
    """A median that regressed against the previous window, as a finding."""
    out = []
    if cur["n"] < MIN_SESSIONS or prev["n"] < MIN_SESSIONS:
        return out
    for field, label, fmt in (("cost", "median cost per puzzle", "${:.2f}"),
                              ("turns", "median turns per puzzle", "{:.0f}")):
        a, b = cur[field], prev[field]
        if a is not None and b and a >= b * (1 + REGRESSION):
            out.append({"key": f"trend:{field}", "title": f"{label} regressed", "share": 1.0, "value": a,
                            "detail": f"{fmt.format(a)} over {cur['n']} sessions vs "
                                   f"{fmt.format(b)} over {prev['n']} ({a / b - 1:+.0%})"})
    return out


def decide(top, trends, state):
    """Which items are news: [(item, why)] — never told, or clearly worse since."""
    news = []
    seen = state.get("items", {})
    for item in trends + top:
        last = seen.get(item["key"])
        value = item.get("value", item["share"])
        if last is None:
            if item["key"].startswith("trend:") or item["share"] >= WAKE_SHARE:
                news.append((item, "new"))
        elif item["key"].startswith("trend:"):
            if value >= last["value"] * (1 + REGRESSION / 2):
                news.append((item, f"worse since {last['woken'][:10]}"))
        elif value >= last["value"] * WORSE_RATIO and value - last["value"] >= WORSE_POINTS:
            news.append((item, f"up from {last['value']:.0%} on {last['woken'][:10]}"))
    return news


def record(live_items, state, now):
    """Stamp what is still live; forget a woken item gone FORGET_DAYS, so its return is news."""
    seen = state.setdefault("items", {})
    stamp = now.isoformat(timespec="seconds")
    live = {i["key"] for i in live_items}
    for key in list(seen):
        if key in live:
            seen[key]["seen"] = stamp
        elif (now - datetime.datetime.fromisoformat(seen[key]["seen"])).days >= FORGET_DAYS:
            del seen[key]


def mark_woken(news, state, now):
    stamp = now.isoformat(timespec="seconds")
    for item, _ in news:
        state.setdefault("items", {})[item["key"]] = {
            "value": item.get("value", item["share"]), "woken": stamp, "seen": stamp}


def share(f):
    return "REGR" if f["key"].startswith("trend:") else f"{f['share']:.0%}"


def fmt_money(x):
    return "—" if x is None else f"${x:.2f}"


def report(cur, prev, ranked, trends, hours, n_prev_note):
    def delta(field, fmt):
        a, b = cur[field], prev[field]
        if a is None:
            return "—"
        s = fmt.format(a)
        if b is not None and prev["n"] >= MIN_SESSIONS and cur["n"] >= MIN_SESSIONS:
            s += f" (was {fmt.format(b)})"
        return s
    lines = [(f"annotate audit: {cur['n']} sessions in the last {hours}h, "
             f"{prev['n']} in the {hours}h before{n_prev_note}"),
             (f"  median {delta('turns', '{:.0f}')} turns, {delta('cost', '${:.2f}')} a puzzle, "
             f"{delta('wall_min', '{:.1f}')} min, {delta('checks', '{:.0f}')} annotate_check runs")]
    if cur["first_fail"] is not None:
        lines.append(f"  first check fails {delta('first_fail', '{:.0%}')} (median "
                     f"{cur['first_errors'] or 0:.0f} error lines); after it: "
                     f"{cur['after_check_share'] or 0:.0%} of cost, "
                     f"{cur['turns_after_check'] or 0:.0f} turns; first-turn context "
                     f"{(cur['first_ctx'] or 0) / 1000:.1f}k tokens")
    lines.append("")
    lines.append("ranked by share of sessions touched — the first line is what to fix next:")
    for i, f in enumerate(trends + ranked[:15], 1):
        lines.append(f"{i:3d}. {share(f):>4}  {f['title']} — {f['detail']}")
    if not ranked and not trends:
        lines.append("  nothing to rank")
    return "\n".join(lines)


def wake_text(news, top3, cur):
    newkeys = {i["key"]: why for i, why in news}
    lines = [(f"annotate audit ({cur['n']} runs, median {cur['turns'] or 0:.0f} turns, "
             f"{fmt_money(cur['cost'])}/puzzle, first check fails {cur['first_fail'] or 0:.0%}). "
             f"Top 3 to fix:")]
    for i, f in enumerate(top3, 1):
        tag = f" [{newkeys[f['key']]}]" if f["key"] in newkeys else ""
        lines.append(f"{i}. {f['title']} ({share(f)}): {f['detail']}{tag}")
    lines.append("Spawn a fix worker for #1. Fix it with a tool, a validator message that says "
                 "what to write, or an auto-fix in annotate_check — not prose padding in "
                 "annotate_prompt.md. If the prompt already states the rule, the prose is "
                 "not working: change a tool. `python3 tools/annotate_audit.py` reprints this; "
                 "full report in .annotate_audit/latest.txt.")
    return "\n".join(lines)[:1900]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hours", type=int, default=48)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--wake", action="store_true", help="save the report, wake the room on news")
    ap.add_argument("--dry-run", action="store_true", help="with --wake: print, send nothing")
    args = ap.parse_args(argv)

    now = datetime.datetime.now(datetime.timezone.utc)
    templates = load_templates(VALIDATOR.read_text(encoding="utf-8"))
    window = datetime.timedelta(hours=args.hours)
    rows = list(sessions(now - 2 * window, templates))
    cur_rows = [r for r in rows if r["start"] >= now - window]
    prev_rows = [r for r in rows if r["start"] < now - window]
    cur, prev = summarise(cur_rows), summarise(prev_rows)
    ranked = findings(cur_rows)
    trends = trend_items(cur, prev)
    note = "" if cur["n"] >= MIN_SESSIONS else f" — under {MIN_SESSIONS}, so no wake"

    if args.json:
        json.dump({"current": cur, "previous": prev, "trends": trends, "findings": ranked},
                  sys.stdout, indent=1, default=str)
        return 0
    text = report(cur, prev, ranked, trends, args.hours, note)
    print(text)
    if not args.wake:
        return 0

    STATE_DIR.mkdir(exist_ok=True)
    state_path = STATE_DIR / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    top3 = ranked[:3]
    news = decide(top3, trends, state) if cur["n"] >= MIN_SESSIONS else []
    if args.dry_run:
        print("\n--- would wake ---\n" + wake_text(news, trends + top3, cur) if news
              else "\n--- no news: would stay quiet ---")
        return 0
    (STATE_DIR / f"{now:%Y-%m-%d}.txt").write_text(text + "\n")
    (STATE_DIR / "latest.txt").write_text(text + "\n")
    for old in sorted(STATE_DIR.glob("20*.txt"))[:-KEEP_REPORTS]:
        old.unlink()
    if cur["n"] >= MIN_SESSIONS:
        record(trends + ranked, state, now)
    if news:
        msg = wake_text(news, (trends + top3)[:3], cur)
        rc = subprocess.run([WAKE_SH, "-c", ROOM, msg], check=False).returncode
        if rc:
            # Unrecorded, so tomorrow's run tries again; non-zero, so the
            # plugin runner tells the room this job is broken.
            print(f"annotate audit: {WAKE_SH} exited {rc}; nothing recorded", file=sys.stderr)
            return rc
        mark_woken(news, state, now)
    state_path.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")
    print(f"\n{'woke #' + ROOM if news else 'no news; stayed quiet'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
