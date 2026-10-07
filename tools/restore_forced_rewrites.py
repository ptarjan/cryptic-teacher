#!/usr/bin/env python3
"""Put back hint text that a validator false positive made an annotate run rewrite.

    python3 tools/restore_forced_rewrites.py check_definition_fit           # list, write nothing
    python3 tools/restore_forced_rewrites.py check_definition_fit --apply   # restore

A check that rejected good annotations did not just cost turns: every run it
failed rewrote the flagged text to get past it, usually by contorting good
prose around the false hit, and those rewrites are what the corpus holds. So
relaxing or fixing a check is not finished until this has run for it.

For each annotate session (a transcript under $CLAUDE_CONFIG_DIR/projects/*cryptic*/)
in which CHECK flagged a clue, the session's writes to its _ann file (Write,
Edit, --patch, a full Read) are replayed to recover the flagged field as it
stood when the check first flagged it, and as the session left it. The earlier
value goes back when all of these hold:

  - the puzzle still holds the session's final value for that field;
  - the answer is the one the earlier annotation was written for;
  - today's validator reports nothing for the clue with the earlier value
    that it does not already report for the clue as it stands.

Only the field CHECK judges is restored, never the whole annotation, since
the same session may have fixed real problems elsewhere in the clue. RESTORE
lists the checks this knows a field for; add a row when another check is relaxed.
"""
import argparse
import collections
import copy
import json
import multiprocessing
import os
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import validate_annotations as va  # noqa: E402
from annotate_audit import load_templates, rule_name  # noqa: E402
from apply_annotations import normalize  # noqa: E402
from fetch_puzzle import read_puzzle_file, write_puzzle_file  # noqa: E402
from groups import entry_id  # noqa: E402
import puzzle_paths  # noqa: E402
from turn_cost import ANNOTATE_PREFIX, CLAUDE_DIR  # noqa: E402

LINE = re.compile(r"^\s*(?:ERROR|warn):\s*(\d+[AD]):\s*(.*?)(?:\s*\[(check_\w+)\])?\s*$")
TEMPLATES = None


def definition_fit(before, final, current, flags):
    """explanation.definitionFit as the run first wrote it."""
    was = (before.get("explanation") or {}).get("definitionFit")
    end = (final.get("explanation") or {}).get("definitionFit")
    now = (current.get("explanation") or {}).get("definitionFit")
    if not was or was == end or now != end:
        return None
    out = copy.deepcopy(current)
    out["explanation"]["definitionFit"] = was
    return out


def block_notes(before, final, current, flags):
    """Each block note the check quoted, on the block (same fragment, same
    letters) that still carries the session's final note."""
    def notes(a):
        return {(b.get("clueFragment"), b.get("gives")): b.get("note")
                for b in a.get("blocks") or [] if isinstance(b, dict)}
    was, end = notes(before), notes(final)
    out, changed = copy.deepcopy(current), False
    for b in out.get("blocks") or []:
        k = (b.get("clueFragment"), b.get("gives"))
        old = was.get(k)
        if old and old != end.get(k) and b.get("note") == end.get(k) \
                and any(repr(old) in f or f"'{old}'" in f for f in flags):
            b["note"], changed = old, True
    return out if changed else None


RESTORE = {
    "check_definition_fit": definition_fit,
    "check_block_notes_dont_name_the_answer": block_notes,
}


def text_of(c):
    if isinstance(c, str):
        return c
    return "\n".join(x.get("text", "") for x in c or [] if isinstance(x, dict))


def check_of(msg, named):
    global TEMPLATES
    if named:
        return named
    if TEMPLATES is None:
        TEMPLATES = load_templates(Path(va.__file__).read_text(encoding="utf-8"))
    return rule_name(msg, TEMPLATES)


def replay(path, check):
    """[(pid, entry id, value when first flagged, value at session end, flag lines)]."""
    try:
        rows = [json.loads(line) for line in open(path, encoding="utf-8")]
    except (OSError, ValueError):
        return []
    files, uses, pid, first = {}, {}, None, {}
    for o in rows:
        content = (o.get("message") or {}).get("content")
        if pid is None and o.get("type") == "user":
            m = re.match(re.escape(ANNOTATE_PREFIX) + r" (\S+)", text_of(content))
            if not m:
                return []
            pid = m.group(1)
        if not isinstance(content, list):
            continue
        for b in content:
            if b.get("type") == "tool_use":
                uses[b["id"]] = (b["name"], b.get("input") or {})
                continue
            if b.get("type") != "tool_result":
                continue
            name, inp = uses.get(b.get("tool_use_id"), (None, {}))
            # A failing annotate_check exits 1, so only a file tool's error means nothing changed.
            if b.get("is_error") and name != "Bash":
                continue
            res, fn = text_of(b.get("content")), os.path.basename(inp.get("file_path", ""))
            ann_fn = f"_ann_{pid}.json"
            if name == "Write":
                files[fn] = inp.get("content", "")
            elif name == "Edit":
                cur, old = files.get(fn), inp.get("old_string", "")
                files[fn] = (cur.replace(old, inp.get("new_string", ""), -1 if inp.get("replace_all") else 1)
                             if cur is not None and old in cur else None)
            elif name == "Read" and fn == ann_fn and not inp.get("offset") and not inp.get("limit"):
                body = "\n".join(re.sub(r"^\s*\d+\t", "", l, count=1) for l in res.splitlines())
                try:
                    json.loads(body)
                    files[fn] = body
                except ValueError:
                    pass
            elif name == "Bash" and "annotate_check" in inp.get("command", ""):
                m = re.search(r"--patch\s+(\S+)", inp["command"])
                if m and "merged" in res:
                    try:
                        ann = json.loads(files.get(ann_fn))
                        for eid, fields in json.loads(files.get(os.path.basename(m.group(1)))).items():
                            if not isinstance(fields, dict):
                                ann[eid] = fields
                                continue
                            ann[eid] = ann.get(eid) or {}
                            for k, v in fields.items():
                                if v is None:
                                    ann[eid].pop(k, None)
                                else:
                                    ann[eid][k] = v
                        files[ann_fn] = json.dumps(ann, ensure_ascii=False)
                    except (TypeError, ValueError, AttributeError):
                        files[ann_fn] = None
                try:
                    state = json.loads(files.get(ann_fn))
                except (TypeError, ValueError):
                    state = None
                for line in res.splitlines():
                    m = LINE.match(line)
                    if not m or check_of(m.group(2), m.group(3)) != check:
                        continue
                    tag = m.group(1)
                    eid = f"{tag[:-1]}-{'across' if tag[-1] == 'A' else 'down'}"
                    ann = state.get(eid) if isinstance(state, dict) else None
                    if isinstance(ann, dict):
                        first.setdefault(eid, (ann, []))[1].append(m.group(2))
    try:
        final = json.loads(files.get(f"_ann_{pid}.json"))
    except (TypeError, ValueError):
        return []
    return [(pid, eid, ann, final.get(eid), flags) for eid, (ann, flags) in first.items()
            if isinstance(final.get(eid), dict)]


def clue_lines(puzzle, tag):
    _, errors, warnings = va.validate_puzzle(puzzle)
    return {l for l in errors + warnings if l.startswith(f"{tag}:") or
            (l.startswith("puzzle") and re.search(rf"\b{tag}\b", l))}


def _replay(args):
    return replay(*args)


def main(argv):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("check", choices=sorted(RESTORE))
    p.add_argument("--apply", action="store_true", help="write the restored fields")
    p.add_argument("--transcripts", type=Path, default=CLAUDE_DIR / "projects")
    a = p.parse_args(argv)
    paths = sorted(a.transcripts.glob("*cryptic*/*.jsonl"), key=os.path.getmtime)
    with multiprocessing.Pool() as pool:
        found = pool.map(_replay, [(p_, a.check) for p_ in paths], chunksize=20)
    # The latest session to touch a clue is the one whose final value can still be live.
    latest = {}
    for hits in found:
        for pid, eid, before, final, flags in hits:
            latest[(pid, eid)] = (before, final, flags)
    by_pid = collections.defaultdict(dict)
    for (pid, eid), v in latest.items():
        by_pid[pid][eid] = v
    restored = skipped = 0
    for pid, clues in sorted(by_pid.items()):
        path = puzzle_paths.find(pid)
        if path is None:
            continue
        puzzle = read_puzzle_file(path)
        by_id = {entry_id(e): e for e in puzzle["entries"]}
        touched = False
        for eid, (before, final, flags) in sorted(clues.items()):
            e = by_id.get(eid)
            if e is None or not isinstance(e.get("annotation"), dict):
                continue
            norm = [normalize(copy.deepcopy(x), e, puzzle["entries"]) for x in (before, final)]
            want = (before.get("answer") or "").replace(" ", "").upper()
            new = RESTORE[a.check](*norm, e["annotation"], flags)
            if new is None or want != (e.get("solution") or "").replace(" ", "").upper():
                continue
            tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
            had, current = clue_lines(puzzle, tag), e["annotation"]
            e["annotation"] = new
            extra = clue_lines(puzzle, tag) - had
            if extra:
                e["annotation"] = current
                skipped += 1
                print(f"kept {pid} {eid}: the earlier text now gets {sorted(extra)[0][:120]}")
                continue
            restored += 1
            touched = True
            print(f"restore {pid} {eid}")
        if touched and a.apply:
            write_puzzle_file(path, puzzle)
    print(f"{a.check}: {restored} field(s) {'restored' if a.apply else 'to restore'}, "
          f"{skipped} kept because the earlier text fails today's validator")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
