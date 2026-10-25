#!/usr/bin/env python3
"""What the annotation runs are spending their turns on, ranked — from the transcripts.

    python3 tools/annotate_audit.py              # last 48h vs the 48h before, ranked
    python3 tools/annotate_audit.py --hours 168  # a wider window
    python3 tools/annotate_audit.py --json
    python3 tools/annotate_audit.py --wake       # the daily job: save, wake with one fix target
    python3 tools/annotate_audit.py --wake --dry-run   # print the wake, send and record nothing

The bill is the fix loop. Nearly every headless annotate run fails its first
`tools/annotate_check.py`, and every turn after that re-sends the whole
transcript, so the next thing to fix is whichever check or refusal costs the
most sessions a turn. This reads the transcripts and says which, with no model
call: every figure is arithmetic over the JSONL the CLI already wrote.

A session is a transcript under $CLAUDE_CONFIG_DIR/projects/*cryptic*/ whose
first user message starts with turn_cost.ANNOTATE_PREFIX (or hands it over, as a cold-solve run does). Findings are ranked by the
share of the window's sessions they touch (one session counts once, however
many lines it produced), so the first line is what to fix next.

Error lines are named by the check that wrote them: every `f"{tag}: ..."`
message in tools/validate_annotations.py is read out of its AST and becomes a
pattern, so a reworded message moves with its check and nothing here has to be
kept in step by hand. A line no pattern matches is shown as its first words.

--wake is the scheduled form. It saves the report to .annotate_audit/ (ignored
by git) and wakes the room every run with exactly one fix target, chosen by
pick(): a finding the room was woken about that has since clearly grown (or a
median cost/turns regression that is new or worse) comes first; otherwise the
highest-ranked finding not woken in the last COOLDOWN_DAYS, so successive days
work down the ranking instead of re-sending one item. Only findings touching at
least FIX_FLOOR of sessions qualify; when none does, it stays quiet. Each wake
is stamped on its item and appended to "attempts" in .annotate_audit/state.json,
and a target woken before says so, so the room knows the last fix did not move
it. Below MIN_SESSIONS sessions in the current window it reports and stays
quiet; a trend needs MIN_SESSIONS in both windows.
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

from turn_cost import (
    is_annotate_session,
    CLAUDE_DIR,
)

REPO = pathlib.Path(__file__).resolve().parent.parent
VALIDATOR = REPO / "tools" / "validate_annotations.py"
# The scheduled run executes in a worktree (tools/annotate_audit.sh); what it
# last told the room lives in the main checkout so it survives the worktree.
STATE_DIR = pathlib.Path(os.environ.get("CT_MAIN_CHECKOUT", REPO)) / ".annotate_audit"
WAKE_SH = os.environ.get("WAKE_SH") or __import__("local_config").path("household_dir") + "/tools/wake.sh"
ROOM = os.environ.get("HOUSEHOLD_ROOM", "cryptic-crosswords")

# $/MTok: input, output, cache read, 5-minute cache write, 1-hour cache write.
PRICES = {"claude-opus-5-5": (4, 20, 0.20, 5, 8)}
MIN_SESSIONS = 30          # per window, before a trend or a finding may wake anyone
FIX_FLOOR = 0.03           # a finding must touch this share of sessions to be a fix target
COOLDOWN_DAYS = 7          # a woken finding is skipped this long unless it has grown
KEEP_ATTEMPTS = 60
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
    """[(regex, check name, literal chars)] for every `f"{tag}: ..."` and
    `f"puzzle: ..."` message."""
    out = []
    for fn in ast.parse(source).body:
        if not isinstance(fn, ast.FunctionDef):
            continue
        for node in ast.walk(fn):
            if not isinstance(node, ast.JoinedStr) or len(node.values) < 2:
                continue
            head, lit = node.values[0], node.values[1]
            if (isinstance(head, ast.FormattedValue) and isinstance(head.value, ast.Name)
                    and head.value.id == "tag" and isinstance(lit, ast.Constant)
                    and str(lit.value).startswith(": ")):
                body, prefix, first = node.values[1:], r"\S+", str(lit.value)
            elif isinstance(head, ast.Constant) and str(head.value).startswith("puzzle: "):
                body, prefix = node.values, ""
                first = ":" + " ".join(str(v.value) for v in body if isinstance(v, ast.Constant))[7:]
            else:
                continue
            parts, chars = [], 0
            for v in body:
                if isinstance(v, ast.Constant):
                    parts.append(re.escape(str(v.value)))
                    chars += len(str(v.value))
                else:
                    parts.append(".*?")
                if chars >= 40:
                    break
            # `f"{tag}: {p}"` passes on another function's message, and as a
            # pattern it would match every line, so it names nothing.
            words = re.sub(r"^(puzzle)?:", "", "".join(
                str(v.value) for v in body if isinstance(v, ast.Constant))).split()
            if not words:
                continue
            name = fn.name
            if not name.startswith("check_"):
                name = f"{fn.name}: {' '.join(first[2:].split()[:4])}"
            out.append((re.compile(prefix + "".join(parts), re.DOTALL), name, chars))
    return out


# A message the validator no longer prints describes a check that has since
# changed, so its lines are named SUPERSEDED + check and kept out of the
# ranking: the fix for them has already landed.
SUPERSEDED = "superseded: "


def retired_templates(since, current):
    """Templates of every validator version in use since `since` that the
    current validator no longer has."""
    revs = subprocess.run(
        ["git", "log", "--format=%H", f"--since={since.isoformat()}", "--",
         str(VALIDATOR.relative_to(REPO))],
        cwd=REPO, capture_output=True, text=True, check=False).stdout.split()
    out = {}
    for rev in revs:
        shown = subprocess.run(["git", "show", f"{rev}^:{VALIDATOR.relative_to(REPO).as_posix()}"],
                               cwd=REPO, capture_output=True, text=True, check=False)
        if shown.returncode:
            continue
        try:
            old = load_templates(shown.stdout)
        except SyntaxError:
            continue
        out.update((rx.pattern, t) for t in retire(old, current) for rx in [t[0]])
    return list(out.values())


def retire(old, current):
    """The templates of `old` that `current` lacks, named SUPERSEDED + check."""
    have = {rx.pattern for rx, _, _ in current}
    return [(rx, SUPERSEDED + name, chars) for rx, name, chars in old if rx.pattern not in have]


def rule_name(line, templates, retired=()):
    """The check an ERROR line came from, or its first words if none matches.
    A line only a retired template matches is named SUPERSEDED + its check."""
    body = re.sub(r"^\s*ERROR:\s*", "", line).strip()
    for pool in (templates, retired):
        best = max(((c, n) for rx, n, c in pool if rx.match(body)), default=None)
        if best:
            return best[1]
    if body.startswith("schema:"):
        return "schema: " + re.sub(r"\$\.entries\[\d+\]\.?", "", body[7:]).strip()[:70]
    body = re.sub(r"^\S+:\s*", "", body)
    body = re.sub(r"'[^']*'|\"[^\"]*\"", "'…'", body)
    return " ".join(body.split()[:7])


def stopped_names(text):
    """Why annotate_check refused to apply: each schema complaint, entry index dropped."""
    found = {"schema " + re.sub(r"\$\.entries\[\d+\]\.?", "", m).strip()
             for m in re.findall(r"SCHEMA (\$[^;\n]*)", text)}
    # apply_annotations' refusal: one "  <entry id>: finding" per line, after a header
    # that reads "refused to write, fix these in" or "refused to write — fix these in".
    listed = re.split(r"refused to write[^\n]*:\n", text, maxsplit=1)[1:]
    for line in (listed[0].split("\n\n")[0].splitlines() if listed else []):
        # a refusal may carry a tag before the id: "  QUOTE 9-across: indicator ..."
        m = re.match(r"\s+(?:[A-Z]+ )?\d+-(?:across|down)\s*(.*)$", line)
        if m:
            found.add(refusal_class(m.group(1)))
    if "STOPPED" in text:
        # The bag's compact() strips the header, leaving "  <id>: finding" lines (the
        # first unindented); the colon after the id tells them from walkthrough lines.
        for m in re.finditer(r"^[ \t]*(?:[A-Z]+ )?\d+-(?:across|down):[ \t]*(.*)$", text, re.M):
            found.add(refusal_class(m.group(1)))
    if found:
        return {f"apply refused: {f}" for f in found}
    m = re.search(r"STOPPED — (.{0,200})", text)
    # The path ends the sentence the same way every time: one class, not one per series.
    return {"STOPPED: " + re.sub(r"puzzles/\S+", "<puzzle>", m.group(1))[:60] if m else "STOPPED: ?"}


def refusal_class(rest):
    """Name one apply_annotations refusal line (entry id already cut), with the clue's own
    words, numbers and offsets taken out so every instance of a class is one name."""
    rest = rest.lstrip(": ").strip()
    if "re-annotation list" in rest:
        why = re.search(r"still flagged: (\w+)", rest)
        return "redo gate: " + (why.group(1) if why else re.sub(r"\(.*?\)", "", rest)[:40].strip())
    if rest.startswith("this redo gives up"):
        return "redo gate: gives up what the hint had"
    named = (("name no span of the wordplay", "notes name no span"), ("unknown op", "unknown op"),
             ("does not give", "wordplay does not give the answer"),
             ("is not in the clue", "quote not in clue"))
    for needle, name in named:
        if needle in rest:
            return name
    rest = re.sub(r"\$\.entries\[\d+\]\.?", "", rest.partition(" — ")[0])
    rest = re.sub(r"\[\d+\]", "[]", rest)
    if "missing required key" not in rest:    # the key named is the class; other quotes are the clue's
        rest = re.sub(r"'[^']*'|\"[^\"]*\"", "'…'", rest)
    rest = re.sub(r"(?<![\w'])\d+", "N", rest)
    return "schema " + " ".join(rest.split()[:9])


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
    if ("annotate_check" in command or "annotate_bag.py check" in command
            or ("apply_solution.py" in command and "--check-only" in command)) and text.startswith("Exit code"):
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


BAG_PREFIX = "Annotate these crosswords"
BAG_IDS = re.compile(r"^Annotate these crosswords[^:\n]*:\s*(.+?)\.(?:\s|$)", re.DOTALL)
ENTRY_KEY = re.compile(r'^\s*"\d+-(?:across|down)"\s*:\s*\{', re.MULTILINE)


def is_audited(first_user):
    """An annotate run: solo, cold-solve handoff, or a bag of puzzles in one session."""
    return is_annotate_session(first_user) or (first_user or "").strip().startswith(BAG_PREFIX)


def bag_ids(first_user):
    """The puzzle ids a bag session was handed; a solo or handoff run is one puzzle."""
    m = BAG_IDS.match((first_user or "").strip())
    return m.group(1).split() if m else []


def clues_written(writes):
    """Annotations in the session's annotation files: entry keys of the last Write to
    each tools/_ann_*.json (a solo file's keys, or every puzzle's keys in a bag file)."""
    return sum(len(ENTRY_KEY.findall(text)) for text in writes.values())


def _cost(model, usage):
    p = PRICES.get(model)
    if not p:
        return None
    cc = usage.get("cache_creation") or {}
    w5 = cc.get("ephemeral_5m_input_tokens", 0) if cc else usage.get("cache_creation_input_tokens", 0)
    return (usage.get("input_tokens", 0) * p[0] + usage.get("output_tokens", 0) * p[1]
            + usage.get("cache_read_input_tokens", 0) * p[2] + w5 * p[3]
            + cc.get("ephemeral_1h_input_tokens", 0) * p[4]) / 1e6


def read_session(path, templates, retired=()):
    """One annotate transcript's numbers, or None if it is not an annotate run."""
    first_user, t0, t1, model = None, None, None, None
    turns = collections.OrderedDict()       # message id -> (usage, after first check)
    calls, check_ids, check_outs, writes = {}, set(), [], {}
    s = {"tool_errors": collections.Counter(), "memory": False, "validator_reads": 0, "max_tokens": 0}
    try:
        fh = open(path, encoding="utf-8", errors="replace")  # closed by `with fh` below
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
                    if not is_audited(first_user):
                        return None
                for b in content if isinstance(content, list) else []:
                    if not isinstance(b, dict) or b.get("type") != "tool_result":
                        continue
                    text = _text(b.get("content"))
                    if b.get("tool_use_id") in check_ids:
                        check_outs.append((calls[b["tool_use_id"]][1], text))
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
                    if b.get("name") == "Write" and re.search(r"/_ann_[^/]*\.json$", cmd):
                        writes[cmd] = str(inp.get("content") or "")
                    blob = json.dumps(inp)
                    if "/memory/" in blob or "MEMORY.md" in blob:
                        s["memory"] = True
                    if "validate_annotations.py" in cmd and "--explain" not in cmd and (
                            b.get("name") == "Read" or re.search(r"\b(grep|sed|cat|head|tail|awk)\b", cmd)):
                        s["validator_reads"] += 1
                    if b.get("name") == "Bash" and ("annotate_check" in cmd or "annotate_bag.py check" in cmd):
                        check_ids.add(b.get("id"))
    if not first_user or not turns or not t0:
        return None
    costs = [(_cost(model, u), after) for u, after in turns.values()]
    first_usage = next(iter(turns.values()))[0]
    s.update(
        start=datetime.datetime.fromisoformat(t0.replace("Z", "+00:00")),
        model=model, turns=len(turns),
        puzzles=len(bag_ids(first_user)) or 1, clues=clues_written(writes),
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
    s["first_units"] = s["first_failed"] = 0
    seen_pids = set()
    for cmd, out in check_outs:
        # A unit is one puzzle's first check: a solo session has one; a bag has one per
        # puzzle, whether it ran `annotate_bag.py check` or annotate_check on each.
        if "annotate_bag.py check" in cmd:
            reports = bag_reports(out)
        else:
            reports = [(single_check_id(cmd) if bag_ids(first_user) else "", out)]
        units = [(pid, text) for pid, text in reports if pid not in seen_pids]
        seen_pids.update(pid for pid, _ in units)
        for _, text in units:
            names = report_names(text, templates, retired)
            s["all_rule_lines"].update(names)
            s["first_units"] += 1
            s["first_failed"] += bool(names)
            s["first_rules"].update(names)
            s["first_fail"] = bool(s["first_failed"])
    return s


def single_check_id(cmd):
    """The puzzle a `tools/annotate_check.py ID ...` command checks (the command itself if unclear)."""
    m = re.search(r"annotate_check(?:\.py)?\b.*?\b([a-z][a-z0-9]*-\d+)\b", cmd)
    return m.group(1) if m else cmd


def report_names(text, templates, retired=()):
    """The failing checks named in one annotate_check report."""
    errs = [ln for ln in text.splitlines() if ln.lstrip().startswith("ERROR:")]
    names = collections.Counter(rule_name(ln, templates, retired) for ln in errs)
    if "STOPPED" in text:
        names.update(stopped_names(text))
    return names


def bag_reports(out):
    """[(puzzle id, report text)] from one `annotate_bag.py check` output: a failing puzzle
    is a `--- <id>` section with its full report, a clean one a line `<id>: clean ...`."""
    found = [(m.group(1), "") for m in re.finditer(r"^(\S+): (?:clean|advisory)", out, re.MULTILINE)]
    parts = re.split(r"^--- (\S+)\n", out, flags=re.MULTILINE)
    # parts = [preamble, id, body, id, body...]; a body runs to the next section
    for pid, body in zip(parts[1::2], parts[2::2]):
        found.append((pid, body))
    return found


def sessions(since, templates, retired=()):
    floor = since.timestamp() - 86400    # mtime is the LAST write; a run can start earlier
    for path in CLAUDE_DIR.glob("projects/*cryptic*/*.jsonl"):
        try:
            if path.stat().st_mtime < floor:
                continue
        except OSError:
            continue
        s = read_session(path, templates, retired)
        if s and s["start"] >= since:
            yield s


# ---------------------------------------------------------------- the report

def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def pooled(rows, field, per):
    """Sum of `field` over the sum of `per` across the rows that have both: a bag of 11
    redo puzzles and a solo run of one full puzzle weigh by the work they did, not 1 each."""
    use = [r for r in rows if r.get(field) is not None and r.get(per)]
    d = sum(r[per] for r in use)
    return sum(r[field] for r in use) / d if d else None


def summarise(rows):
    checked = [r for r in rows if r["first_fail"] is not None]
    total = sum(r["cost"] or 0 for r in rows)
    return {
        "n": len(rows),
        "puzzles": sum(r.get("puzzles", 1) for r in rows),
        "clues": sum(r.get("clues", 0) for r in rows),
        "cost_per_puzzle": pooled(rows, "cost", "puzzles"),
        "cost_per_clue": pooled(rows, "cost", "clues"),
        "turns_per_clue": pooled(rows, "turns", "clues"),
        "turns": med(r["turns"] for r in rows),
        "cost": med(r["cost"] for r in rows),
        "wall_min": med(r["wall_min"] for r in rows),
        "checks": med(r["checks"] for r in rows),
        # per checked unit: a solo session is one, a bag session one per puzzle in it
        "first_fail": (sum(r["first_failed"] for r in checked)
                       / max(sum(r["first_units"] for r in checked), 1)) if checked else None,
        "first_units": sum(r["first_units"] for r in checked),
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
    after = collections.Counter()
    for r in rows:
        by_sessions.update(set(r["first_rules"]))
        by_lines.update(r["first_rules"])
        for name in set(r["first_rules"]):
            after[name] += r.get("cost_after_check") or 0
    for name, k in by_sessions.items():
        if name.startswith(SUPERSEDED):
            continue
        out.append({"key": f"rule:{name}", "title": f"first check fails on `{name}`", "share": k / n,
                        "detail": f"{k} of {n} sessions ({k / max(len(failed), 1):.0%} of first-check "
                               f"failures), {by_lines[name]} error lines, "
                               f"${after[name]:.2f} spent after the check in those sessions"})
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
    # Per clue is the fair figure: a bag's redo puzzles have ~3 clues, a fresh one ~27.
    for field, label, fmt in (("cost_per_clue", "cost per clue", "${:.3f}"),
                              ("turns_per_clue", "turns per clue", "{:.2f}")):
        a, b = cur[field], prev[field]
        if a is not None and b and a >= b * (1 + REGRESSION):
            out.append({"key": f"trend:{field}", "title": f"{label} regressed", "share": 1.0, "value": a,
                            "detail": f"{fmt.format(a)} over {cur['n']} sessions vs "
                                   f"{fmt.format(b)} over {prev['n']} ({a / b - 1:+.0%}); "
                                   f"{cur['puzzles']} puzzles, {cur['clues']} clues vs "
                                   f"{prev['puzzles']} puzzles, {prev['clues']} clues"})
    return out


def grown(item, last):
    """Clearly worse than when the room was last woken about it."""
    value = item.get("value", item["share"])
    if item["key"].startswith("trend:"):
        return value >= last["value"] * (1 + REGRESSION / 2)
    return value >= last["value"] * WORSE_RATIO and value - last["value"] >= WORSE_POINTS


def level(key, value):
    return f"{value:g}" if key.startswith("trend:") else f"{value:.0%}"


def pick(ranked, trends, state, now):
    """The one fix target as (item, why), or None when nothing reaches FIX_FLOOR.

    A woken item that has clearly grown, or a new trend, jumps the cooldown;
    otherwise the highest-ranked item not woken within COOLDOWN_DAYS."""
    seen = state.get("items", {})
    pool = trends + [f for f in ranked if f["share"] >= FIX_FLOOR]
    for item in pool:
        last = seen.get(item["key"])
        if last and grown(item, last):
            return item, f"up from {level(item['key'], last['value'])} on {last['woken'][:10]}"
        if not last and item["key"].startswith("trend:"):
            return item, "new regression"
    for item in pool:
        last = seen.get(item["key"])
        if last is None:
            return item, "never targeted"
        age = (now - datetime.datetime.fromisoformat(last["woken"])).days
        if age >= COOLDOWN_DAYS:
            return item, (f"targeted {last['woken'][:10]} at {level(item['key'], last['value'])}"
                          f" and still here: that fix did not take, try another way")
    return None


def record(live_items, state, now):
    """Stamp what is still live; forget a woken item gone FORGET_DAYS, so its return is a fresh target."""
    seen = state.setdefault("items", {})
    stamp = now.isoformat(timespec="seconds")
    live = {i["key"] for i in live_items}
    for key in list(seen):
        if key in live:
            seen[key]["seen"] = stamp
        elif (now - datetime.datetime.fromisoformat(seen[key]["seen"])).days >= FORGET_DAYS:
            del seen[key]


def mark_woken(item, why, state, now):
    """Stamp the target for the cooldown and log the attempt."""
    stamp = now.isoformat(timespec="seconds")
    value = item.get("value", item["share"])
    state.setdefault("items", {})[item["key"]] = {"value": value, "woken": stamp, "seen": stamp}
    attempts = state.setdefault("attempts", [])
    attempts.append({"woken": stamp, "key": item["key"], "title": item["title"],
                     "value": value, "why": why})
    del attempts[:-KEEP_ATTEMPTS]


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
    lines = [(f"annotate audit: {cur['n']} sessions ({cur['puzzles']} puzzles, {cur['clues']} clues) in the "
              f"last {hours}h, {prev['n']} ({prev['puzzles']} puzzles, {prev['clues']} clues) in the "
              f"{hours}h before{n_prev_note}"),
             (f"  per session, median {delta('turns', '{:.0f}')} turns, {delta('cost', '${:.2f}')}, "
              f"{delta('wall_min', '{:.1f}')} min, {delta('checks', '{:.0f}')} annotate_check runs"),
             (f"  normalised: {delta('cost_per_puzzle', '${:.2f}')} a puzzle, "
              f"{delta('cost_per_clue', '${:.3f}')} a clue, {delta('turns_per_clue', '{:.2f}')} turns a clue")]
    if cur["first_fail"] is not None:
        lines.append(f"  first check fails {delta('first_fail', '{:.0%}')} of {cur['first_units']} "
                     f"checked puzzles (solo runs and each bag puzzle) (median "
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


WAKE_CAP = 2500
REFUSAL_KEY = "rule:apply refused: wordplay does not give"


def refusal_section(item, hours, now):
    """The mechanical replay for a wordplay-refusal target (tools/refusal_replay.py), else ''."""
    if not item["key"].startswith(REFUSAL_KEY):
        return ""
    import refusal_replay
    try:
        return refusal_replay.audit_section(now - datetime.timedelta(hours=hours), 1500)
    except Exception as e:      # the wake must still go out without its extra
        return f"replay failed: {e}"


def wake_text(item, why, cur, extra=""):
    tail = ("Spawn a fix worker to land a fix for this today and push it. Prefer a tool, "
         "validator or check change (a message that says what to write, an auto-fix in "
         "annotate_check) over prose in annotate_prompt.md: if the prompt already states "
         "the rule, the prose is not working. If it cannot be fixed, say why in the room. "
         "`python3 tools/annotate_audit.py` reprints the ranking; full report in "
         ".annotate_audit/latest.txt.")
    head = (f"annotate audit ({cur['n']} runs, median {cur['turns'] or 0:.0f} turns, "
            f"{fmt_money(cur.get('cost_per_puzzle'))}/puzzle, first check fails {cur['first_fail'] or 0:.0%}). "
            f"Today's fix target [{why}]:\n{item['title']} ({share(item)}): {item['detail']}")
    room = max(WAKE_CAP - len(head) - len(tail) - 2, 0)
    # the section is cut at a line end, so a half example never ships
    extra = extra if len(extra) <= room else extra[:room].rsplit("\n", 1)[0] if room else ""
    return "\n".join(p for p in (head, extra, tail) if p)[:WAKE_CAP]


def causes(rows):
    """Ranked causes as data: [{label, sessions, cost_after_check}], most sessions first
    (then most dollars). Same keys as findings(); one session counts once per cause."""
    n, out = len(rows), []
    for f in findings(rows):
        hit = [r for r in rows if _touches(r, f["key"])]
        out.append({"label": f["title"], "key": f["key"], "sessions": len(hit),
                    "share": round(len(hit) / n, 4) if n else 0,
                    "cost_after_check": round(sum(r.get("cost_after_check") or 0 for r in hit), 4)})
    out.sort(key=lambda c: (-c["sessions"], -c["cost_after_check"], c["key"]))
    return out


def _touches(r, key):
    kind, _, name = key.partition(":")
    if kind == "rule":
        return name in r["first_rules"]
    if kind == "tool":
        return name in r["tool_errors"]
    return bool({"waste:memory": r["memory"], "waste:validator": r["validator_reads"],
                 "waste:max_tokens": r["max_tokens"], "waste:cache_1h": r["cache_1h"]}.get(key))


def window_audit(since, until):
    """The exact window [since, until) as one dict: what the ledger row and --json print."""
    templates = load_templates(VALIDATOR.read_text(encoding="utf-8"))
    retired = retired_templates(since, templates)
    rows = [r for r in sessions(since, templates, retired) if not until or r["start"] < until]
    s = summarise(rows)
    return {"since": since.isoformat(), "until": until.isoformat() if until else None,
            "sessions": s["n"], "puzzles": s["puzzles"], "clues": s["clues"],
            "cost": round(sum(r["cost"] or 0 for r in rows), 4),
            "cost_per_clue": s["cost_per_clue"], "turns_per_clue": s["turns_per_clue"],
            "first_fail": s["first_fail"], "causes": causes(rows)}


def parse_time(text):
    t = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    return t if t.tzinfo else t.astimezone()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hours", type=int, default=48)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--since", help="audit exactly [--since, --until) (ISO time) instead of --hours windows")
    ap.add_argument("--until", help="with --since: end of the window (default now)")
    ap.add_argument("--wake", action="store_true", help="save the report, wake the room with one fix target")
    ap.add_argument("--dry-run", action="store_true", help="with --wake: print, send nothing")
    args = ap.parse_args(argv)

    now = datetime.datetime.now(datetime.timezone.utc)
    if args.since:
        res = window_audit(parse_time(args.since), parse_time(args.until) if args.until else None)
        if args.json:
            json.dump(res, sys.stdout, indent=1, default=str)
            print()
        else:
            print(f"{res['since']} .. {res['until'] or 'now'}: {res['sessions']} sessions, "
                  f"{res['puzzles']} puzzles, {res['clues']} clues, ${res['cost']:.2f}, "
                  f"{fmt_money(res['cost_per_clue']) if res['cost_per_clue'] is None else '$%.3f' % res['cost_per_clue']}/clue, "
                  f"{res['turns_per_clue'] or 0:.2f} turns/clue")
            for i, c in enumerate(res["causes"][:10], 1):
                print(f"{i:3d}. {c['sessions']:3d} sessions ${c['cost_after_check']:.2f}  {c['label']}")
        return 0
    templates = load_templates(VALIDATOR.read_text(encoding="utf-8"))
    window = datetime.timedelta(hours=args.hours)
    retired = retired_templates(now - 2 * window, templates)
    rows = list(sessions(now - 2 * window, templates, retired))
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
    gone = collections.Counter(n for r in cur_rows for n in set(r["first_rules"])
                               if n.startswith(SUPERSEDED))
    if gone:
        text += "\n\nnot ranked, the validator has since reworded or dropped the message:\n" + "\n".join(
            f"  {n[len(SUPERSEDED):]} — {k} of {cur['n']} sessions" for n, k in gone.most_common())
    print(text)
    if not args.wake:
        return 0

    STATE_DIR.mkdir(exist_ok=True)
    state_path = STATE_DIR / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    target = pick(ranked, trends, state, now) if cur["n"] >= MIN_SESSIONS else None
    extra = refusal_section(target[0], args.hours, now) if target else ""
    if args.dry_run:
        print("\n--- would wake ---\n" + wake_text(*target, cur, extra) if target
              else "\n--- nothing to fix: would stay quiet ---")
        return 0
    (STATE_DIR / f"{now:%Y-%m-%d}.txt").write_text(text + "\n")
    (STATE_DIR / "latest.txt").write_text(text + "\n")
    for old in sorted(STATE_DIR.glob("20*.txt"))[:-KEEP_REPORTS]:
        old.unlink()
    if cur["n"] >= MIN_SESSIONS:
        record(trends + ranked, state, now)
    if target:
        msg = wake_text(*target, cur, extra)
        rc = subprocess.run([WAKE_SH, "-c", ROOM, msg], check=False).returncode
        if rc:
            # Unrecorded, so tomorrow's run tries again; non-zero, so the
            # plugin runner tells the room this job is broken.
            print(f"annotate audit: {WAKE_SH} exited {rc}; nothing recorded", file=sys.stderr)
            return rc
        mark_woken(*target, state, now)
    state_path.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")
    print(f"\n{'woke #' + ROOM if target else 'nothing to fix; stayed quiet'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
