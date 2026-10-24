#!/usr/bin/env python3
"""Dry run: which wordplay did a validator false positive make the model throw away?

    nice -n 19 python3 tools/recover_fp_drafts.py [--before ISO] [--show N]

When a check turns out to be wrong (the PAWPAW case: check_blocks_account_for_answer
rejected every reduplicated answer, fb49e09), the fix stops new false positives
but the clues it already hit were rewritten by the annotate session into
something that passes. Nothing goes back and asks whether the first draft was
the better one. This reads the transcripts and answers that, WITHOUT writing
anything to a puzzle.

For every annotate session before --before (default: when fb49e09 was pushed):
replay the session's writes to tools/_ann_<ID>.json (Write, Edit, --patch
merges) up to each `annotate_check.py <ID>` run whose output carries the
blocks-check line ("the blocks give ... but the answer is"), take the FIRST
draft of each clue so rejected, and run the CURRENT validator on it
(annotation.from_model, which evaluates the wordplay, then
validate_annotations.blocks_miss_letters). Each clue lands in one bucket:

  a  the draft passes now and differs from the committed wordplay
  b  the draft passes now and matches the committed wordplay
  c  the draft still fails (a true rejection, or it cannot be evaluated)
  d  the clue is not committed (puzzle gone, or the clue has no annotation)
  x  the draft could not be rebuilt from the transcript (file not Written there)

Only the blocks check and the wordplay evaluation are re-run: a draft in bucket
a may still trip some other check, so this finds candidates, not safe swaps.
"""
import argparse
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

CUTOFF = "2026-10-24T03:36:52Z"  # fb49e09's commit time
TRANSCRIPTS = "/data/claude/projects/*cryptic-teacher*/*.jsonl"
MARK = "but the answer is"
TAG = re.compile(r"(?m)^\s*(?:warn: )?(\d+[AD]): the blocks give")
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


def rejections(path, before):
    """[(timestamp, pid, {tag: draft})] for each check run that named the blocks check."""
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
                    if use["name"] == "Bash" and MARK in text and stamp < before:
                        m = RUN.search(use["input"].get("command") or "")
                        mine = files.get(f"_ann_{m.group(1)}.json") if m else None
                        if mine is not None:
                            out.append((stamp, m.group(1), TAG.findall(text), mine))
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


def judge(pid, tag, draft):
    """(bucket, draft wp, committed wp, why)."""
    wp = draft.get("wp") if isinstance(draft, dict) else None
    try:
        puzzle = read_puzzle_file(resolve_puzzle(pid))
    except (SystemExit, OSError, ValueError, KeyError):
        return "d", wp, None, "puzzle not committed"
    num, direction = int(tag[:-1]), "across" if tag[-1] == "A" else "down"
    entry = next((e for e in puzzle["entries"]
                  if e.get("number") == num and e.get("direction") == direction), None)
    ann = (entry or {}).get("annotation")
    if not ann:
        return "d", wp, None, "clue not annotated"
    committed = annotation.to_model(ann).get("wp")
    if not isinstance(draft, dict) or not (wp or draft.get("blocks")):
        return "x", wp, committed, "draft not in the replayed file"
    try:
        if wp:
            stored = annotation.from_model(draft, entry, puzzle)
        else:
            # Early sessions wrote the stored tree (blocks, wordplay), not `wp`.
            stored = draft
            import wordplay
            tree = stored.get("wordplay")
            wp = wordplay.render(tree) if isinstance(tree, dict) else \
                "(blocks only) " + " + ".join(str(b.get("gives")) for b in stored["blocks"]
                                              if isinstance(b, dict))
        if V.blocks_miss_letters(stored, entry):
            return "c", wp, committed, "blocks still miss the answer's letters"
    except Exception as exc:  # WordplayError and kin: the draft does not evaluate
        return "c", wp, committed, f"{type(exc).__name__}: {str(exc)[:90]}"
    return ("b" if wp.strip() == (committed or "").strip() else "a"), wp, committed, ""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", default=CUTOFF)
    ap.add_argument("--show", type=int, default=5)
    args = ap.parse_args(argv)
    t0 = time.time()
    first = {}   # (pid, tag) -> (stamp, draft)
    sessions = 0
    for path in sorted(glob.glob(TRANSCRIPTS)):
        try:
            if MARK not in Path(path).read_text(encoding="utf-8", errors="replace"):
                continue
        except OSError:
            continue
        hit = rejections(path, args.before)
        sessions += bool(hit)
        for stamp, pid, tags, text in hit:
            try:
                draft = json.loads(text)
            except ValueError:
                draft = None
            for tag in tags:
                n, d = int(tag[:-1]), "across" if tag[-1] == "A" else "down"
                one = draft.get(f"{n}-{d}") if isinstance(draft, dict) else None
                if (pid, tag) not in first or stamp < first[(pid, tag)][0]:
                    first[(pid, tag)] = (stamp, one)
    buckets = {k: [] for k in "abcdx"}
    for (pid, tag), (stamp, one) in sorted(first.items()):
        bucket, wp, committed, why = judge(pid, tag, one)
        buckets[bucket].append((pid, tag, wp, committed, why))
    print(f"{sessions} session(s) with a blocks-check rejection before {args.before}; "
          f"{len(first)} distinct clue(s)")
    names = {"a": "draft passes now, differs from committed",
             "b": "draft passes now, matches committed",
             "c": "draft still fails", "d": "clue not committed",
             "x": "draft not rebuildable from the transcript"}
    for k in "abcdx":
        print(f"  ({k}) {len(buckets[k])}  {names[k]}")
    print()
    for pid, tag, wp, committed, _ in buckets["a"][:args.show]:
        print(f"{pid} {tag}\n  draft:     {wp}\n  committed: {committed}\n")
    print(f"ran in {time.time() - t0:.0f}s (dry run: nothing written)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
