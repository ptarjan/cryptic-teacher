#!/usr/bin/env python3
"""The files a bag session (tools/annotate_bag_prompt.md) works from and writes.

    python3 tools/annotate_bag.py view ID [ID...]    # write tools/_bag_<ID>.txt
    python3 tools/annotate_bag.py check FILE         # tools/_ann_bag_<ID>.json

A bag session pays per puzzle for a Read of its view, a Write of its annotations
and a check run, each a tool round trip that re-sends the conversation so far
(measured 10-18: ~4.6k tokens a puzzle before any clue, over ~3 clues). So the
bag has ONE view and ONE annotations file:

  view   `tools/_bag_<first id>.txt`: per puzzle a header line and only the lines
         its run writes (the due clues, and the lights linked to them), with the
         draft/flagged/existing/grid blocks when the puzzle has them. Built from
         each puzzle's `tools/_puzzle_<id>.json` (annotate_check.write_view),
         which stays: apply_annotations reads `annotateOnly` back out of it, so
         the guard against rewriting a hinted clue is unchanged.
  check  FILE is one object {puzzle id: {entry id: annotation}}. Each puzzle's
         part is split to its own tools/_ann_<id>.json and annotate_check.main
         runs on it as it always did; a clean puzzle prints one line, a failing
         one its full report. A puzzle already reported clean is not run again.
         Fix a failing puzzle by Editing its part of FILE.
"""
import contextlib
import io
import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
DONE = "clean, index refreshed — done"
ADVISORY = "advisory warn — done"


def bag_path(first):
    return TOOLS / f"_bag_{first}.txt"


def ann_path(first):
    return TOOLS / f"_ann_bag_{first}.json"


def done_path(first):
    return TOOLS / f"_bag_{first}.done"


def due_lines(view):
    """The view's entry lines this run writes, plus the lights linked to them."""
    only = set(view.get("annotateOnly") or ())
    if not view.get("annotateOnly") and "annotateOnly" not in view:
        return list(view["entries"])  # the whole puzzle is due
    kept = only | set(view.get("existingAnnotations") or ())
    out = []
    for line in view["entries"]:
        eid, group = (p.strip() for p in line.split(" | ")[:2])
        linked = {g.strip() for g in group.replace("in ", "").split("+")} - {"-"}
        if eid in kept or linked & only:
            out.append(line)
    return out


def puzzle_block(pid, view):
    head = f"== {pid} | {view.get('name', '')} | {view.get('setter', '')}"
    ocr = (view.get("source") or {}).get("retrievedFrom")
    if ocr in ("newspaper", "book"):
        head += f" | OCR ({ocr}): a clue may be misread, see printedClue"
    out = [head]
    for k in ("preamble", "themeClue", "cluesUnplaced"):
        if view.get(k):
            out.append(f"{k}: {view[k]}")
    out += due_lines(view)
    flagged = view.get("flagged")
    if flagged:  # each reason is "...tree (WHY): parse again..." boilerplate; keep WHY
        why = {c: r.split("tree (", 1)[-1].split("): parse", 1)[0] for c, r in flagged.items()}
        out.append("flagged (hint on file has a wrongly shaped wp tree; write a new wp that "
                   "fixes the fault named): " + "; ".join(f"{c}: {r}" for c, r in why.items()))
    for k in ("draftAnnotations", "existingAnnotations", "grid", "scan"):
        if view.get(k):
            out.append(f"{k}: {json.dumps(view[k], ensure_ascii=False, separators=(',', ':'))}")
    return "\n".join(out)


def write_bag_view(ids):
    """Write the bag's one view from each puzzle's _puzzle_ copy; its path."""
    import annotate_check
    from fetch_puzzle import resolve_puzzle
    blocks = []
    for pid in ids:
        view = json.loads(annotate_check.write_view(resolve_puzzle(pid)).read_text(encoding="utf-8"))
        blocks.append(puzzle_block(pid, view))
    head = (f"Bag of {len(ids)} puzzles. Write every puzzle's annotations as one JSON object "
            f"{{puzzle id: {{entry id: annotation}}}} to tools/{ann_path(ids[0]).name}, "
            f"only for the lines below.")
    out = bag_path(ids[0])
    out.write_text(head + "\n\n" + "\n\n".join(blocks) + "\n", encoding="utf-8")
    done_path(ids[0]).unlink(missing_ok=True)
    return out


def run_one(pid):
    """annotate_check on pid: (rc, report, state) with state clean/advisory/failing."""
    import annotate_check
    buf = io.StringIO()
    rc = 2
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        try:
            rc = annotate_check.main([pid])
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else 2
    text = buf.getvalue().rstrip()
    last = next((l for l in reversed(text.splitlines()) if l.startswith("annotate_check ")), "")
    state = "clean" if last.endswith(DONE) else "advisory" if last.endswith(ADVISORY) else "failing"
    return rc, text, state


def check(path):
    path = Path(path)
    first = path.stem.removeprefix("_ann_bag_")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"annotate_bag: {path} is not a readable JSON object: {e}")
        return 2
    if not isinstance(data, dict) or not all(isinstance(v, dict) for v in data.values()):
        print("annotate_bag: the file must be one object {puzzle id: {entry id: annotation}}")
        return 2
    done = set(done_path(first).read_text().split()) if done_path(first).exists() else set()
    worst, failing = 0, []
    for pid, part in data.items():
        if pid in done:
            continue
        (TOOLS / f"_ann_{pid}.json").write_text(json.dumps(part, ensure_ascii=False, indent=1) + "\n",
                                                encoding="utf-8")
        rc, text, state = run_one(pid)
        if state == "failing":
            print(f"--- {pid}\n{text}\n")
            failing.append(pid)
            worst = max(worst, rc or 1)
        else:
            done.add(pid)
            print(f"{pid}: {state}")
    done_path(first).write_text("\n".join(sorted(done)) + "\n")
    if failing:
        print(f"{len(failing)} to fix in tools/{path.name}, one edit for all, then run this "
              f"command again: {', '.join(failing)}. Where a report above names _ann_<id>.json "
              f"or --patch, that is the puzzle's part of tools/{path.name}: edit it there. "
              f"The others are done and not re-run.")
    else:
        import annotate_check
        print(f"all {len(done)} puzzles checked.")
        print(annotate_check.STOP_NOW)
    return worst


def main(argv):
    if len(argv) >= 2 and argv[0] == "view":
        print(write_bag_view(argv[1:]).relative_to(TOOLS.parent))
        return 0
    if len(argv) == 2 and argv[0] == "check":
        return check(argv[1])
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
