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

--apply writes them. For each puzzle it takes the differing drafts from --results
(the dry run's passing list), skips a draft with an identity op (sound(X, X)) or whose
clue was changed by a commit after the session's own, applies the rest to the file as it
is now, and writes only if the full validator gives no clue of theirs an error and the
puzzle no error it did not already have. Prints applied and skipped-by-reason counts.
"""
import argparse
import copy
import glob
import json
import re
import sys
import time
from pathlib import Path

import annotation
import validate_annotations as V
from fetch_puzzle import read_puzzle_file, resolve_puzzle

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
                    if use["name"] == "Bash" and stamp >= since and (
                            MARK in text or "refused to write" in text or "STOPPED" in text):
                        m = RUN.search(use["input"].get("command") or "")
                        mine = files.get(f"_ann_{m.group(1)}.json") if m else None
                        errs = ERR.findall(text) + refused(text)
                        if mine is not None and errs:
                            out.append((stamp, m.group(1), errs, mine))
    return out


def refused(text):
    """[(tag, finding)] for the clues apply_annotations refused ("refused to write ...:"
    then "  [TAG ]9-across: finding" lines, or the bag's STOPPED compact form), parsed
    as annotate_audit.stopped_names does. These drafts never reach an ERROR line."""
    line_rx = re.compile(r"^[ \t]*(?:[A-Z]+ )?(\d+)-(across|down)\b:?[ \t]*(.*)$")
    lines = []
    listed = re.split(r"refused to write[^\n]*:\n", text, maxsplit=1)[1:]
    if listed:
        lines += listed[0].split("\n\n")[0].splitlines()
    if "STOPPED" in text:
        lines += [ln for ln in text.splitlines() if re.match(r"^[ \t]*(?:[A-Z]+ )?\d+-(?:across|down):", ln)]
    out = []
    for ln in lines:
        m = line_rx.match(ln)
        if m:
            out.append((m.group(1) + ("A" if m.group(2) == "across" else "D"),
                        "apply refused: " + m.group(3).strip()))
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
        body = Path(path).read_text(encoding="utf-8", errors="replace")
        if MARK not in body and "refused to write" not in body and "STOPPED" not in body:
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


_ALLOWED = []


def validate_puzzle(puzzle):
    """V.validate_puzzle as the deploy judges it (check_one under --deploy): corpus
    rules, and the per-puzzle backlog allowances, so a recovered clue counts as newly
    annotated (a restored draft that needs "allowed 0" fields fails the deploy)."""
    annotated, errors, warnings = V.validate_puzzle(puzzle, corpus=True)
    if not _ALLOWED:
        _ALLOWED.append(V.load_backlog())
    if annotated:
        errors = errors + V.backlog_errors(puzzle["id"], warnings, _ALLOWED[0])
    return annotated, errors, warnings


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
        _, errors, _ = validate_puzzle(p)
    except Exception as exc:  # a draft the validator cannot even read is a rejection
        return [[f"{type(exc).__name__}: {exc}"] for _ in pairs]
    return [[m.strip() for m in errors if m.strip().startswith(k)] for k in mine]


CALL = re.compile(r"(\w+)(?:<[^<>]*>)?\(")


def plain(arg):
    """The letters of an argument that is just `[label]LETTERS` or `LETTERS`, else None."""
    m = re.fullmatch(r"\s*(?:\[[^\]]*\])?\s*([A-Za-z' -]+?)\s*", arg)
    return re.sub(r"[^A-Za-z]", "", m.group(1)).upper() if m else None


def split_args(body):
    """Top-level comma split of a call body, ignoring commas in [..] and (..)."""
    out, depth, cur = [], 0, ""
    for ch in body:
        if ch in "[(":
            depth += 1
        elif ch in "])":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    return out + [cur]


def call_bodies(wp):
    """[(op, body)] for every op call in a wp string, nested ones too."""
    out = []
    for m in CALL.finditer(wp):
        depth, i = 1, m.end()
        while i < len(wp) and depth:
            if wp[i] == "[":
                j = wp.find("]", i)
                i = j if j >= 0 else len(wp) - 1
            elif wp[i] == "(":
                depth += 1
            elif wp[i] == ")":
                depth -= 1
            i += 1
        out.append((m.group(1), wp[m.end():i - 1]))
    return out


def identity_op(wp):
    """The first op of `wp` whose input equals its output (sound(X, X), sub(.., X, X)), else None."""
    for op, body in call_bodies(wp):
        args = [plain(a) for a in split_args(body)]
        if op == "sound" and len(args) == 2 and args[0] and args[0] == args[1]:
            return f"{op}({body})"
        if op == "sub" and len(args) == 3 and args[1] and args[1] == args[2]:
            return f"{op}({body})"
    return None


HISTORY = {}  # rel path -> [(commit time, hash)] oldest first, commits since SINCE only


def load_history(since_epoch):
    """One `git log --name-only` over the window, instead of a log per puzzle."""
    import subprocess
    from fetch_puzzle import ROOT
    out = subprocess.run(["git", "-C", str(ROOT), "log", f"--since={since_epoch - 86400}",
                          "--format=C %H %ct", "--name-only", "--", "puzzles"],
                         capture_output=True, text=True).stdout
    cur = None
    for line in out.split("\n"):
        if line.startswith("C "):
            _, h, ct = line.split()
            cur = (int(ct), h)
        elif line.strip() and cur:
            HISTORY.setdefault(line.strip(), []).append(cur)
    for v in HISTORY.values():
        v.reverse()


def clue_versions(path, tag, after):
    """How many commits after epoch `after` changed this clue's stored annotation.
    A file with at most one commit after `after` has at most one change: no git show."""
    import subprocess
    from fetch_puzzle import ROOT
    rel = Path(path).resolve().relative_to(Path(ROOT).resolve()).as_posix()
    later = [(ct, h) for ct, h in HISTORY.get(rel, []) if ct > after]
    if len(later) < 2:
        return len(later)
    num, direction = int(tag[:-1]), "across" if tag[-1] == "A" else "down"

    def ann_at(rev):
        out = subprocess.run(["git", "-C", str(ROOT), "show", f"{rev}:{rel}"],
                             capture_output=True, text=True)
        try:
            ents = json.loads(out.stdout)["entries"]
        except (ValueError, KeyError):
            return None
        return next((e.get("annotation") for e in ents
                     if e.get("number") == num and e.get("direction") == direction), None)
    prev, changes = ann_at(later[0][1] + "^"), 0
    for _, h in later:
        ann = ann_at(h)
        changes += ann != prev
        prev = ann
    return changes


def stamp_epoch(stamp):
    import calendar
    return calendar.timegm(time.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S"))


def apply_puzzle(job):
    """({reason: n}, [applied]) for one puzzle's differing drafts: skip the identity-op
    ones and the clues edited since the session, validate the rest against the file as it
    is NOW, and write only if validate_puzzle gains no error."""
    pid, recs = job
    skipped, applied = {}, []

    def skip(why, n=1):
        skipped[why] = skipped.get(why, 0) + n
    try:
        path = resolve_puzzle(pid)
        puzzle = read_puzzle_file(path)
    except (SystemExit, OSError, ValueError, KeyError):
        return {"puzzle gone": len(recs)}, []
    latest = {}
    for rec in sorted(recs, key=lambda r: r["stamp"]):
        if rec["tag"] in latest:
            skip("superseded by a later draft of the same clue")
        latest[rec["tag"]] = rec
    p = copy.deepcopy(puzzle)
    chosen = []  # (rec, entry in p, committed wp)
    for tag, rec in latest.items():
        wp = rec["draft"]["wp"]
        num, direction = int(tag[:-1]), "across" if tag[-1] == "A" else "down"
        entry = next((e for e in p["entries"]
                      if e.get("number") == num and e.get("direction") == direction), None)
        if not entry:
            skip("clue not in puzzle")
            continue
        committed = annotation.to_model(entry["annotation"]).get("wp") if entry.get("annotation") else None
        if (wp or "").strip() == (committed or "").strip():
            skip("already identical to committed")
        elif identity_op(wp):
            skip("identity op")
        elif clue_versions(path, tag, stamp_epoch(rec["stamp"])) > 1:
            skip("committed clue edited after the draft's session")
        else:
            chosen.append((rec, entry, committed))

    def trial(items):
        import puzzle_schema  # the file writer puts keys in schema order; validate that form
        q = copy.deepcopy(p)
        mine = []
        for rec, entry, _ in items:
            e = next(x for x in q["entries"]
                     if x.get("number") == entry["number"] and x.get("direction") == entry["direction"])
            try:
                # from_model fills unset optional fields with null; the schema rejects
                # null, and every normal write goes through prune() to drop them.
                e["annotation"] = puzzle_schema.prune(annotation.from_model(rec["draft"], e, q))
            except Exception:
                return None, None, rec
            mine.append((f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}:", rec))
        q = puzzle_schema.order(q)
        try:
            _, errors, _ = validate_puzzle(q)
        except Exception as exc:
            return q, [f"{type(exc).__name__}: {exc}"], None
        return q, [m.strip() for m in errors], mine

    while chosen:
        q, errors, mine = trial(chosen)
        if q is None:
            chosen = [c for c in chosen if c[0] is not mine]
            skip("draft does not evaluate")
            continue
        if mine is None:  # the validator crashed on the whole set
            skip("validator crashed", len(chosen))
            chosen = []
            break
        bad = {rec["tag"] for k, rec in mine if any(m.startswith(k) for m in errors)}
        if bad:
            skip("fails the validator now", len(bad))
            chosen = [c for c in chosen if c[0]["tag"] not in bad]
            continue
        if errors:  # something else fails: only a problem if the file already did
            try:
                _, base, _ = validate_puzzle(copy.deepcopy(puzzle))
            except Exception:
                base = []
            new = [m for m in errors if m not in {b.strip() for b in base}]
            if new:
                skip("puzzle gains a validator error", len(chosen))
                chosen = []
                break
        import fetch_puzzle
        try:
            fetch_puzzle.write_puzzle_file(path, q)
        except ValueError:  # puzzle_integrity.RefusedWrite cannot cross the Pool pickle
            skip("integrity gate refused the write", len(chosen))
            break
        for rec, entry, committed in chosen:
            applied.append({"pid": pid, "tag": rec["tag"], "clue": (entry.get("clue") or {}).get("text"),
                            "before": committed, "after": rec["draft"]["wp"]})
        break
    return skipped, applied


def apply_all(drafts, args, t0):
    """Write the passing, differing drafts into the puzzle files; print the counts."""
    from collections import Counter
    from multiprocessing import Pool
    results = json.loads(Path(args.results).read_text())
    want = {(i["pid"], i["tag"], i["draft"]["wp"]) for i in results["items"] if i["differs"]}
    by_pid = {}
    for key, rec in drafts.items():
        if (rec["pid"], rec["tag"], rec["draft"]["wp"]) in want:
            by_pid.setdefault(rec["pid"], []).append(rec)
    print(f"{len(want)} differing passing draft(s) in {args.results}; "
          f"{sum(map(len, by_pid.values()))} in {len(by_pid)} puzzle(s) to re-validate", flush=True)
    skipped, applied = Counter(), []
    jobs = sorted(by_pid.items())
    load_history(min(stamp_epoch(r["stamp"]) for rs in by_pid.values() for r in rs))
    print(f"history of {len(HISTORY)} puzzle file(s) loaded ({time.time() - t0:.0f}s)", flush=True)
    with Pool(2) as pool:
        for n, (sk, ap) in enumerate(pool.imap_unordered(apply_puzzle, jobs, chunksize=2)):
            skipped.update(sk)
            applied += ap
            if n % 25 == 0:
                print(f"  {n}/{len(jobs)} puzzles, {len(applied)} applied, skipped "
                      f"{dict(skipped)} ({time.time() - t0:.0f}s)", flush=True)
    Path(args.applied).write_text(json.dumps(applied, indent=1))
    print(f"\napplied: {len(applied)} clue(s) in {len({a['pid'] for a in applied})} puzzle(s) "
          f"(list in {args.applied})\nskipped: {sum(skipped.values())}")
    for why, k in skipped.most_common():
        print(f"  {k:4d}  {why}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=SINCE)
    ap.add_argument("--apply", action="store_true",
                    help="write the passing, differing drafts into the puzzle files")
    ap.add_argument("--results", default="/tmp/fp_full_results.json",
                    help="the dry run's passing drafts (--apply re-validates each)")
    ap.add_argument("--applied", default="/tmp/fp_applied.json")
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
    if args.apply:
        return apply_all(drafts, args, t0)
    return judge_all(drafts, args, t0)


def check_names(msgs):
    """The checks that wrote these ERROR lines: `[check_x]` suffix, else the message's
    first word (a schema or evaluation error that has no check name)."""
    out = set()
    for m in msgs:
        c = CHECK.search(m)
        out.add(c.group(1) if c else "(no check name) " + " ".join(m.split()[:2]))
    return out


def save_results(path, passed):
    """Write the passing drafts to --results (the list --apply reads); called as it goes."""
    items = [{"pid": b[0]["pid"], "tag": b[0]["tag"], "draft": {"wp": b[0]["draft"]["wp"]},
              "differs": (b[0]["draft"]["wp"] or "").strip() != (b[4] or "").strip()} for b in passed]
    Path(path).write_text(json.dumps({"items": items}))


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
            save_results(args.results, passed)
    save_results(args.results, passed)
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
