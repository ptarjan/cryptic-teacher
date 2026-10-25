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
import re
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
                   "fixes the fault named): " + "; ".join(f"{c}: {r}" for c, r in why.items())
                   + ". Passing = a re-parsed tree with none of those faults (new prose on the "
                   "same tree is refused), losing no clue word the old one explained; "
                   "`check` runs this gate")
    keep = view.get("keepWords")
    if keep:  # the words the redo gate refuses to lose (annotate_check.keep_words)
        out.append("keep these words in the new tree unless wrong: "
                   + "; ".join(f"{c}: {w}" for c, w in keep.items()))
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
            rc = annotate_check.main([pid, "--partial"])
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else 2
    text = buf.getvalue().rstrip()
    last = next((l for l in reversed(text.splitlines()) if l.startswith("annotate_check ")), "")
    state = "clean" if last.endswith(DONE) else "advisory" if last.endswith(ADVISORY) else "failing"
    return rc, text, state


def redo_gate(puzzle, part):
    """The apply step's redo gate on one puzzle's annotations `part`: as error
    strings, a listed clue whose new tree is still flagged (or the same tree),
    and any redo that gives up what the annotation on file had."""
    import shape_queue
    from apply_annotations import landed
    relisted = shape_queue.listed(puzzle)
    errors = []
    for entry in puzzle["entries"]:
        eid = f"{entry['number']}-{entry['direction']}"
        ann = part.get(eid)
        if not ann or not entry.get("annotation"):
            continue
        bad = []
        new = landed(ann, entry, puzzle["entries"], eid, bad)
        if new is None:
            continue  # annotate_check reports a tree that does not parse
        detected = shape_queue.findings(entry, new) if eid in relisted else []
        lost = shape_queue.regressions(entry, new)
        if detected:
            same = new.get("wordplay") == entry["annotation"].get("wordplay")
            errors.append(f"redo gate {eid}: on the shape list ({relisted[eid]}) and this "
                          f"{'is the same tree as on file' if same else 'tree is still flagged'}: "
                          f"{'; '.join(detected + lost)}. Write the wordplay tree again so no step has "
                          f"those faults (prose alone does not settle it), or null to keep the old hint.")
        elif lost:
            errors.append(f"redo gate {eid}: gives up what the annotation on file had: "
                          f"{'; '.join(lost)}. Keep those clue words explained, or null to keep the old hint.")
    return errors


def bag_redo_gate(pid, part):
    """redo_gate on puzzle pid's file; [] if it cannot be read (annotate_check says so)."""
    try:
        from annotate_check import read_puzzle_file
        from fetch_puzzle import resolve_puzzle
        return redo_gate(read_puzzle_file(resolve_puzzle(pid)), part)
    except Exception:
        return []


LINE_CAP = 700
WARN_RE = re.compile(r"^(\s*)(warn|ERROR): (\d+[AD]): (.*)$")
BOILER = ("Fix ALL of these in one edit of", "Any line you cannot act on:", "apply_annotations: ")


def compact(text):
    """A failing report with the repeats folded: the per-puzzle advice lines (the bag's
    footer says them once) dropped, one [check] message that hits many clues printed
    once with its clue ids, and any line capped at LINE_CAP characters."""
    out, groups = [], {}
    for line in text.splitlines():
        if line.startswith(BOILER) or re.match(r"^\S+: \d+/\d+ annotated — OK$", line):
            continue
        m = WARN_RE.match(line)
        if m:
            key = (m[2], re.sub(r"\d+", "#", m[4]))
            if key not in groups:
                groups[key] = [m[4], []]
                out.append(key)
            groups[key][1].append(m[3])
            continue
        out.append(line[:LINE_CAP] + (" …" if len(line) > LINE_CAP else ""))
    lines = []
    for item in out:
        if isinstance(item, tuple):
            msg, ids = groups[item]
            lines.append(f"  {item[0]} [{', '.join(ids)}]: {msg[:LINE_CAP]}")
        else:
            lines.append(item)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def patch_bag(path, fix):
    """Merge `fix`, {puzzle id: {entry id: {field: value or null}}}, into the bag
    file `path`; what is wrong, or None. A fix by Edit has to reproduce the
    file's bytes from memory and often misses; a patch names only fields."""
    import annotate_check
    try:
        bag, changes = json.loads(path.read_text(encoding="utf-8")), json.loads(fix.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return f"{path.name} or {fix.name} is not readable JSON: {e}"
    unknown = sorted(set(changes) - set(bag))
    if unknown:
        return f"{fix.name} names puzzles {path.name} lacks: {', '.join(unknown)}"
    tmp, tmpfix = path.with_name("_patch_tmp_part.json"), path.with_name("_patch_tmp_fix.json")
    for pid, entries in changes.items():
        tmp.write_text(json.dumps(bag[pid], ensure_ascii=False), encoding="utf-8")
        tmpfix.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
        err = annotate_check.patch(tmp, tmpfix)
        if err:
            tmp.unlink(missing_ok=True)
            tmpfix.unlink(missing_ok=True)
            return f"{pid}: {err}"
        bag[pid] = json.loads(tmp.read_text(encoding="utf-8"))
    tmp.unlink(missing_ok=True)
    path.write_text(json.dumps(bag, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    fix.unlink()
    return None


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
        gate = bag_redo_gate(pid, part) if state != "failing" else []
        # a clue the apply step already left out is reported above; the gate would
        # only say the same again about the old annotation still on file
        gate = [g for g in gate if not re.search(rf"^{re.escape(g.split()[2].rstrip(':'))}: ", text, re.M)]
        if gate:
            text, state, rc = "\n".join(gate), "failing", rc or 1
        if state == "failing":
            print(f"--- {pid}\n{compact(text)}\n")
            failing.append(pid)
            worst = max(worst, rc or 1)
        else:
            done.add(pid)
            print(f"{pid}: {state}")
    done_path(first).write_text("\n".join(sorted(done)) + "\n")
    if failing:
        print(f"{len(done)} puzzles clean, {len(failing)} to fix in tools/{path.name}: "
              f"{', '.join(failing)}. Write ONE small patch file {{puzzle id: {{entry id: {{field: "
              f"new value, or null to drop it}}}}}} naming only the fields to change (notes merge key by "
              f"key) and run `python3 tools/annotate_bag.py check tools/{path.name} --patch <patchfile>`: "
              f"an Edit must match the file's bytes exactly and often misses. Where a report "
              f"names _ann_<id>.json or --patch, that is the puzzle's part of tools/{path.name}. "
              f"A line you cannot act on: `python3 tools/validate_annotations.py --explain "
              f"<[check_name]>` (print it once, do not cat it to a file). The clean ones are "
              f"not re-run.")
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
    if len(argv) == 4 and argv[0] == "check" and argv[2] == "--patch":
        err = patch_bag(Path(argv[1]), Path(argv[3]))
        if err:
            print(f"annotate_bag: {err}")
            return 2
        return check(argv[1])
    if argv[:1] in (["--help"], ["-h"], ["help"]):
        print(__doc__.strip())      # asking for the usage is not a failure
        return 0
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
