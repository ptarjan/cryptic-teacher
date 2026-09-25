#!/usr/bin/env python3
"""Put a puzzle's annotations into its file.

    python3 tools/apply_annotations.py 30098 tools/_ann_30098.json
    python3 tools/apply_annotations.py cryptic-30098          # the default path
    cat ann.json | python3 tools/apply_annotations.py 30098 -

The input is one JSON object keyed by entry id, each value the annotation object
`tools/annotate_prompt.md` describes:

    {"1-across": {"type": "charade", "answer": "...", ...},
     "12-across": null}

Every entry in the puzzle must appear as a key. A key whose value is `null` says
the clue is deliberately unsolved, which the prompt allows and which is very
different from forgetting one — so absence is an error and `null` is not.

This exists because the annotation run used to hand-write a throwaway Python
script per puzzle to do it. Eighty-four of them, in six spellings of the same
`sys.path` incantation; forty-eight re-typed the `/*JSON-START*/` markers by hand
instead of importing them, one in eighty-four used `puzzle_path()`, and several
stamped a `generator=` provenance naming a module they never imported. All of it
was scaffolding around a dict, rebuilt nightly and deleted, and none of it is the
part a model should be spending turns on: the annotations themselves are the
work, and they are all that goes in the JSON now.

Validation runs automatically once the write succeeds, because the write is never
the last step — `--no-validate` if you want it separately.

Every write records who wrote the hints, in provenance.annotatedBy (see
tools/provenance.py). Inside Claude Code that is the exact model id of the
session running this command, read off the session's own transcript, so it is
the model that actually ran and not the alias a script asked for. Outside a
session there is no model to read, so say who it was:

    python3 tools/apply_annotations.py 30098 ann.json --by human
    python3 tools/apply_annotations.py 30098 ann.json --by claude-opus-5-5
"""
import json
import os
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import provenance  # noqa: E402
from fetch_puzzle import read_puzzle_file, resolve_puzzle, write_puzzle_file  # noqa: E402

# The commands whose Bash call is the one running this file right now.
LANDING_COMMANDS = ("apply_annotations", "annotate_check")


def default_input(path):
    """Beside the tools, named for the puzzle, ignored by git (`tools/_*`)."""
    return TOOLS / f"_ann_{path.stem}.json"


def load_annotations(spec):
    if spec == "-":
        raw, where = sys.stdin.read(), "stdin"
    else:
        where = str(spec)
        if not Path(spec).exists():
            raise SystemExit(f"apply_annotations: no such file {where} — write the "
                             f"annotations there first, as one JSON object keyed by "
                             f"entry id")
        raw = Path(spec).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        # The whole point is that this file is hand-written, so say where.
        raise SystemExit(f"apply_annotations: {where} is not valid JSON — "
                         f"{e.msg} at line {e.lineno} column {e.colno}")
    if not isinstance(data, dict):
        raise SystemExit(f"apply_annotations: {where} must be a JSON object keyed "
                         f"by entry id, got {type(data).__name__}")
    return data


def session_model(session_id, pid):
    """The exact model id of the Claude Code session running this command.

    The CLI writes each assistant turn to its transcript before running the
    tool calls in it, so the Bash call that started this process is already on
    disk, carrying `message.model`. A subagent shares its parent's session id
    and writes its own transcript under <session>/subagents/, so all of them
    are read and the newest call to this tool wins, preferring one that names
    this puzzle. None when no transcript holds such a call.
    """
    root = Path(os.environ.get("CLAUDE_CONFIG_DIR")
                or Path.home() / ".claude") / "projects"
    files = (list(root.glob(f"*/{session_id}.jsonl"))
             + list(root.glob(f"*/{session_id}/subagents/*.jsonl")))
    # The call that started this process was written moments ago, so only the
    # transcripts touched in the last few minutes can hold it — a long
    # interactive session has hundreds of finished subagents.
    mtimes = {f: f.stat().st_mtime for f in files}
    newest = max(mtimes.values(), default=0)
    number = pid.rsplit("-", 1)[-1]
    best = None
    for f in (f for f, t in mtimes.items() if t >= newest - 600):
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            if '"tool_use"' not in line or not any(c in line for c in LANDING_COMMANDS):
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            msg = rec.get("message") or {}
            for block in msg.get("content") or []:
                if not (isinstance(block, dict) and block.get("type") == "tool_use"):
                    continue
                command = json.dumps(block.get("input"))
                if not any(c in command for c in LANDING_COMMANDS):
                    continue
                if not provenance.MODEL_ID.fullmatch(msg.get("model") or ""):
                    continue
                rank = (number in command, rec.get("timestamp") or "")
                if best is None or rank > best[0]:
                    best = (rank, msg.get("model"))
            if best and best[0][0]:
                break
    return best[1] if best else None


def annotator(by, pid):
    """Who is writing these hints: --by, else the running session's model."""
    if by:
        return by
    session = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not session:
        raise SystemExit(
            "apply_annotations: not inside a Claude Code session "
            "(no CLAUDE_CODE_SESSION_ID), so there is no model to record as "
            "the author of these hints. Say who wrote them: --by <exact model "
            "id>, --by human, or --by published.")
    model = session_model(session, pid)
    if not model:
        raise SystemExit(
            f"apply_annotations: session {session} has no transcript under "
            f"{os.environ.get('CLAUDE_CONFIG_DIR') or '~/.claude'}/projects "
            f"showing the call to this tool, so the model that wrote these "
            f"hints cannot be read. Pass --by <exact model id>.")
    return model


def apply(path, annotations, by=None):
    puzzle = read_puzzle_file(path)
    ids = [e["id"] for e in puzzle["entries"]]
    missing = [i for i in ids if i not in annotations]
    extra = [k for k in annotations if k not in ids]
    if missing or extra:
        why = []
        if missing:
            why.append("no annotation for " + ", ".join(missing) +
                       " — every entry needs a key, and null means you could not "
                       "solve it")
        if extra:
            why.append("not a clue in this puzzle: " + ", ".join(extra) +
                       " — the ids are " + ", ".join(ids[:4]) + ", ...")
        raise SystemExit(f"apply_annotations: {path.name}: " + "; ".join(why))
    had_hints = provenance.has_hints(puzzle)
    before = [e.get("annotation") for e in puzzle["entries"]]
    for entry in puzzle["entries"]:
        ann = annotations[entry["id"]]
        if ann is None:
            entry.pop("annotation", None)
        else:
            entry["annotation"] = ann
    # Credited only for hints it changed: re-applying the file as it stands
    # writes nothing, and must not put a second name on someone else's work.
    changed = before != [e.get("annotation") for e in puzzle["entries"]]
    if changed and provenance.has_hints(puzzle):
        try:
            puzzle = provenance.credit_annotator(
                puzzle, annotator(by, path.stem), had_hints)
        except ValueError as err:
            raise SystemExit(f"apply_annotations: cannot credit these hints: {err}")
    write_puzzle_file(path, puzzle)
    solved = sum(1 for v in annotations.values() if v is not None)
    return solved, len(ids)


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    validate = "--no-validate" not in argv
    argv = [a for a in argv if a != "--no-validate"]
    by = None
    if "--by" in argv:
        at = argv.index("--by")
        if at + 1 >= len(argv):
            raise SystemExit("apply_annotations: --by needs a value — an exact "
                             "model id, human, or published")
        by = argv[at + 1]
        del argv[at:at + 2]
    path = resolve_puzzle(argv[0])
    spec = argv[1] if len(argv) > 1 else default_input(path)
    solved, total = apply(path, load_annotations(spec), by)
    unsolved = total - solved
    tail = f", {unsolved} left null" if unsolved else ""
    print(f"apply_annotations: {solved}/{total} annotations -> "
          f"puzzles/{path.name}{tail}")
    if not validate:
        return 0
    return subprocess.run([sys.executable, str(TOOLS / "validate_annotations.py"),
                           path.stem]).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
