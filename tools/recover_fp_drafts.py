#!/usr/bin/env python3
"""Dry run: which wordplay did a validator false positive make the model throw away?

    nice -n 19 python3 tools/recover_fp_drafts.py [--since ISO] [--show N]

When a check turns out to be wrong (the PAWPAW case: check_blocks_account_for_answer
rejected every reduplicated answer, fb49e09), the fix stops new false positives
but the clues it already hit were rewritten by the annotate session into
something that passes. Nothing goes back and asks whether the rejected draft was
the better one. This reads the transcripts and answers that, WITHOUT writing
anything to a puzzle.

For every annotate session since --since (default 2026-10-14): replay the
session's writes to tools/_ann_<ID>.json (Write, Edit, --patch merges) up to
each `annotate_check.py <ID>` run that printed an ERROR line on a clue, and keep
each distinct `wp`-format draft of that clue so rejected, with the checks that
rejected it. That takes several minutes (2 processes), so the drafts are cached
in --cache (default /tmp/fp_drafts_all.json; --refresh re-reads the transcripts).

Then, per draft: apply it to an in-memory copy of the current puzzle, run the
FULL current validator (validate_annotations.validate_puzzle), and keep that
clue's errors. A draft with none passes everything today: whatever rejected it
has since been fixed (or the draft was never the problem). Report how many pass,
how many of those differ from the committed wordplay, and which checks rejected
them first. Drafts for different clues of one puzzle are validated together, so
a cross-clue check could blame one for another's; the count is a bound.
"""
import argparse
import copy
import glob
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import annotation  # noqa: E402
import validate_annotations as V  # noqa: E402
from fetch_puzzle import read_puzzle_file, resolve_puzzle  # noqa: E402

SINCE = "2026-10-14T00:00:00Z"
TRANSCRIPTS = "/data/claude/projects/*cryptic-teacher*/*.jsonl"
MARK = "  ERROR: "
ERR = re.compile(r"(?m)^  ERROR: (\d+[AD]): (.*)$")
CHECK = re.compile(r"\[(check_\w+)\]\s*$")
RUN = re.compile(r"annotate_check\.py\s+(\S+)(?:\s+--patch\s+(\S+))?")
KEY = re.compile(r"^(\d+)-(across|down)$")


def merge_patch(text, patch):
    """annotate_check.patch(): fields replaced, null removes, notes merged by note."""
    data = json.loads(text)
    for clue, fields in patch.items():
        if fields is None:
            data[clue] = None
            continue
        cur = data.get(clue)
        if not isinstance(cur, dict):
            cur = data[clue] = {}
        for k, v in fields.items():
            if k == "notes" and isinstance(v, dict):
                notes = dict(cur.get("notes") or {})
                for nk, nv in v.items():
                    if nv is None:
                        notes.pop(nk, None)
                    else:
                        notes[nk] = nv
                cur["notes"] = notes
            elif v is None:
                cur.pop(k, None)
            else:
                cur[k] = v
    return json.dumps(data, indent=1)


def rejections(path, since):
    """[(timestamp, pid, [(tag, message)], _ann_ text)] for each check run since `since`
    that reported an ERROR line on a clue."""
    files, patches, uses, seen_use, seen_res = {}, {}, {}, set(), set()
    out, stamp = [], ""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            stamp = rec.get("timestamp") or stamp
            content = (rec.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use" and b["id"] not in seen_use:
                    seen_use.add(b["id"])
                    uses[b["id"]] = b
                elif b.get("type") == "tool_result" and b.get("tool_use_id") not in seen_res:
                    use = uses.get(b.get("tool_use_id"))
                    seen_res.add(b.get("tool_use_id"))
                    if not use:
                        continue
                    text = b.get("content")
                    if not isinstance(text, str):
                        text = json.dumps(text)
                    replay(use, b.get("is_error"), text, files, patches)
                    if use["name"] == "Bash" and MARK in text and stamp >= since:
                        m = RUN.search(use["input"].get("command") or "")
                        mine = files.get(f"_ann_{m.group(1)}.json") if m else None
                        errs = ERR.findall(text)
                        if mine is not None and errs:
                            out.append((stamp, m.group(1), errs, mine))
    return out


def replay(use, is_error, result, files, patches):
    """Keep the text of each _ann_/_patch_ file as the session left it."""
    name, args = use["name"], use["input"]
    target = Path(args.get("file_path") or "x").name
    if is_error:
        return
    if name == "Write" and target.startswith(("_ann_", "_patch_")):
        (files if target.startswith("_ann_") else patches)[target] = args.get("content", "")
    elif name == "Edit" and target in files:
        old, new = args.get("old_string", ""), args.get("new_string", "")
        files[target] = (files[target].replace(old, new) if args.get("replace_all")
                         else files[target].replace(old, new, 1))
    elif name == "Bash":
        m = RUN.search(args.get("command") or "")
        if m and m.group(2) and f"_ann_{m.group(1)}.json" in files:
            patch = patches.get(Path(m.group(2)).name)
            if patch is not None:
                try:
                    files[f"_ann_{m.group(1)}.json"] = merge_patch(
                        files[f"_ann_{m.group(1)}.json"], json.loads(patch))
                except (ValueError, TypeError, AttributeError):
                    pass


def file_records(args):
    """[[stamp, pid, tag, draft, [messages]]] for one transcript: one row per clue
    named by an ERROR line, with the clue's draft as the session had it then."""
    path, since = args
    try:
        if MARK not in Path(path).read_text(encoding="utf-8", errors="replace"):
            return []
    except OSError:
        return []
    rows = []
    for stamp, pid, errs, text in rejections(path, since):
        try:
            draft = json.loads(text)
        except ValueError:
            continue
        by_tag = {}
        for tag, msg in errs:
            by_tag.setdefault(tag, []).append(msg)
        for tag, msgs in by_tag.items():
            n, d = int(tag[:-1]), "across" if tag[-1] == "A" else "down"
            one = draft.get(f"{n}-{d}") if isinstance(draft, dict) else None
            if isinstance(one, dict) and one.get("wp"):
                rows.append([stamp, pid, tag, one, msgs])
    return rows


def extract(since):
    """({"pid|tag|wp": record}, sessions): each distinct `wp` draft the checks rejected,
    at its earliest rejection (record = {stamp, pid, tag, draft, msgs})."""
    from multiprocessing import Pool
    paths = [p for p in sorted(glob.glob(TRANSCRIPTS))
             if time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(Path(p).stat().st_mtime)) >= since]
    drafts, sessions = {}, 0
    with Pool(2) as pool:
        for rows in pool.imap(file_records, [(p, since) for p in paths], chunksize=4):
            sessions += bool(rows)
            for stamp, pid, tag, one, msgs in rows:
                key = f"{pid}|{tag}|{one['wp']}"
                if key not in drafts or stamp < drafts[key]["stamp"]:
                    drafts[key] = {"stamp": stamp, "pid": pid, "tag": tag, "draft": one, "msgs": msgs}
    return drafts, sessions


def load_cache(path, since, refresh):
    """Extraction takes ~400s, so keep its result in `path`."""
    if not refresh and Path(path).exists():
        data = json.loads(Path(path).read_text())
        return data["drafts"], data["sessions"]
    drafts, sessions = extract(since)
    Path(path).write_text(json.dumps({"since": since, "sessions": sessions, "drafts": drafts}))
    return drafts, sessions


_PUZZLES = {}


def prepared_puzzle(pid):
    if pid not in _PUZZLES:
        _PUZZLES[pid] = read_puzzle_file(resolve_puzzle(pid))
    return _PUZZLES[pid]


def full_errors(pairs, puzzle):
    """[this clue's errors] for each (stored, entry) in `pairs` (distinct clues): the
    drafts applied to an in-memory copy of the puzzle, the full current validator run
    once, and each clue's own ERROR lines kept. Nothing is written."""
    p = copy.deepcopy(puzzle)
    mine = []
    for stored, entry in pairs:
        for e in p["entries"]:
            if e.get("number") == entry["number"] and e.get("direction") == entry["direction"]:
                e["annotation"] = stored
                mine.append((f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}:",
                             f"{V.entry_id(e)}:"))
    try:
        _, errors, _ = V.validate_puzzle(p)
    except Exception as exc:  # a draft the validator cannot even read is a rejection
        return [[f"{type(exc).__name__}: {exc}"] for _ in pairs]
    return [[m.strip() for m in errors if m.strip().startswith(k)] for k in mine]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=SINCE)
    ap.add_argument("--cache", default="/tmp/fp_drafts_all.json")
    ap.add_argument("--extract-only", action="store_true")
    ap.add_argument("--sample", type=int, default=0, help="judge only N seeded-random puzzles")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--show", type=int, default=5)
    args = ap.parse_args(argv)
    t0 = time.time()
    drafts, sessions = load_cache(args.cache, args.since, args.refresh)
    print(f"{sessions} session(s); {len(drafts)} distinct rejected wp draft(s) "
          f"since {args.since} ({time.time() - t0:.0f}s)", flush=True)
    if args.extract_only:
        return 0
    return judge_all(drafts, args, t0)


def check_names(msgs):
    """The checks that wrote these ERROR lines: `[check_x]` suffix, else the message's
    first word (a schema or evaluation error that has no check name)."""
    out = set()
    for m in msgs:
        c = CHECK.search(m)
        out.add(c.group(1) if c else "(no check name) " + " ".join(m.split()[:2]))
    return out


def judge_all(drafts, args, t0):
    """Run the full validator on every draft; print the counts and examples."""
    from collections import Counter
    prepared = {}  # pid -> [(rec, stored, entry, puzzle, committed)]
    skipped = Counter()
    if args.sample:  # ~0.75s a puzzle: judge only the drafts of N puzzles, seeded
        import random
        pids = sorted({r["pid"] for r in drafts.values()})
        keep = set(random.Random(0).sample(pids, min(args.sample, len(pids))))
        drafts = {k: r for k, r in drafts.items() if r["pid"] in keep}
        print(f"sample: {len(keep)} of {len(pids)} puzzles, {len(drafts)} drafts", flush=True)
    for rec in drafts.values():
        pid, tag = rec["pid"], rec["tag"]
        try:
            puzzle = prepared_puzzle(pid)
        except (SystemExit, OSError, ValueError, KeyError):
            skipped["puzzle gone"] += 1
            continue
        num, direction = int(tag[:-1]), "across" if tag[-1] == "A" else "down"
        entry = next((e for e in puzzle["entries"]
                      if e.get("number") == num and e.get("direction") == direction), None)
        if not entry:
            skipped["clue not in puzzle"] += 1
            continue
        try:
            stored = annotation.from_model(rec["draft"], entry, puzzle)
        except Exception:
            skipped["draft does not evaluate"] += 1
            continue
        committed = annotation.to_model(entry["annotation"]).get("wp") if entry.get("annotation") else None
        prepared.setdefault(pid, []).append((rec, stored, entry, puzzle, committed))
    print(f"prepared {sum(map(len, prepared.values()))} of {len(drafts)}; skipped {dict(skipped)} "
          f"({time.time() - t0:.0f}s)", flush=True)
    passed, still = [], 0
    for n, (pid, items) in enumerate(sorted(prepared.items())):
        # One validate_puzzle per round: a round holds at most one draft per clue.
        queue = {}
        for item in items:
            queue.setdefault(item[0]["tag"], []).append(item)
        while queue:
            batch = [lst.pop(0) for lst in queue.values()]
            queue = {t: l for t, l in queue.items() if l}
            errs = full_errors([(b[1], b[2]) for b in batch], batch[0][3])
            for b, e in zip(batch, errs):
                if e:
                    still += 1
                else:
                    passed.append(b)
        if n % 25 == 0:
            print(f"  {n}/{len(prepared)} puzzles, {len(passed)} pass ({time.time() - t0:.0f}s)",
                  file=sys.stderr, flush=True)
    total = sum(map(len, prepared.values()))
    differ = [b for b in passed if (b[0]["draft"]["wp"] or "").strip() != (b[4] or "").strip()]
    print(f"\nrejected wp drafts judged: {total}\npass the full validator now: {len(passed)}\n"
          f"  of those differ from committed: {len(differ)}\n"
          f"  of those identical to committed: {len(passed) - len(differ)}\n")
    by_check = Counter(c for b in differ for c in check_names(b[0]["msgs"]))
    print("original rejecting check, drafts that pass now and differ (a draft counts once per check):")
    for c, k in by_check.most_common(10):
        print(f"  {k:4d}  {c}")
    seen, shown = set(), 0
    print()
    for b in sorted(differ, key=lambda b: ("rep<" not in b[0]["draft"]["wp"], b[0]["stamp"])):
        cs = sorted(check_names(b[0]["msgs"]))
        if shown >= args.show or (set(cs) <= seen and "rep<" not in b[0]["draft"]["wp"]):
            continue
        seen |= set(cs)
        shown += 1
        print(f"{b[0]['pid']} {b[0]['tag']}  rejected by {cs}\n  {b[0]['msgs'][0][:200]}\n"
              f"  draft:     {b[0]['draft']['wp']}\n  committed: {b[4]}\n")
    print(f"ran in {time.time() - t0:.0f}s (dry run: nothing written)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
