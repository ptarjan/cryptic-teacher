#!/usr/bin/env python3
"""Put a puzzle's annotations into its file.

    python3 tools/apply_annotations.py 30098 tools/_ann_30098.json
    python3 tools/apply_annotations.py cryptic-30098          # the default path
    cat ann.json | python3 tools/apply_annotations.py 30098 -

The input is one JSON object keyed by entry id, each value the annotation object
`tools/annotate_prompt.md` describes:

    {"1-across": {"type": ["charade"], "answer": "...", ...},
     "12-across": null}

Every entry in the puzzle must appear as a key. A key whose value is `null` says
the clue is deliberately unsolved, which the prompt allows and which is very
different from forgetting one — so absence is an error and `null` is not.

`assembly` is worked out from the blocks wherever they reach the answer
(tools/derive_assembly.py): filled in when absent, and `pieces` with the right
letters in the wrong order redone.

Except when the run's copy of the puzzle (tools/_puzzle_<ID>.json, written by
`annotate_check.py --view`) lists `annotateOnly`: then only those ids need a
key, every other entry keeps its annotation byte for byte, and a key that
would change one is refused.

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

Every write records who wrote the hints, in the top-level `annotatedBy` (see
tools/provenance.py). Inside Claude Code that is the exact model id of the
session running this command, read off the session's own transcript, so it is
the model that actually ran and not the alias a script asked for. Outside a
session there is no model to read, so say who it was:

    python3 tools/apply_annotations.py 30098 ann.json --by human
    python3 tools/apply_annotations.py 30098 ann.json --by claude-opus-5-5
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import provenance  # noqa: E402
import puzzle_integrity  # noqa: E402
import groups  # noqa: E402 — linked answers
from derive_assembly import complete  # noqa: E402
from groups import entry_id  # noqa: E402
from fetch_puzzle import read_puzzle_file, resolve_puzzle, source_clue, write_puzzle_file  # noqa: E402

# The commands whose Bash call is the one running this file right now.
LANDING_COMMANDS = ("apply_annotations", "annotate_check")


def default_input(path):
    """Beside the tools, named for the puzzle, ignored by git (`tools/_*`)."""
    return TOOLS / f"_ann_{path.stem}.json"


def view_path(path):
    """The annotate run's copy of the puzzle, beside the annotations file."""
    return TOOLS / f"_puzzle_{path.stem}.json"


# A run that is cut off resumes within hours (the five-hour window); a copy
# older than this is a crashed run's leftover, not the current run's contract.
VIEW_MAX_AGE_S = 12 * 3600


def current_view(path):
    """The current run's copy of the puzzle as a dict, or None."""
    try:
        if time.time() - view_path(path).stat().st_mtime > VIEW_MAX_AGE_S:
            return None
        view = json.loads(view_path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return view if isinstance(view, dict) else None


def annotate_only(path):
    """The ids the run may write, from its copy's `annotateOnly`; None for all.

    A puzzle that already has hints and lacks some, most often because a data
    fix cleared the entries whose clue or answer changed, is annotated only
    where it lacks them: re-solving the rest buys hints it already has and
    risks rewriting good ones."""
    only = (current_view(path) or {}).get("annotateOnly")
    return list(only) if isinstance(only, list) else None


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


def derived_answer(entry, entries):
    """The answer in display form, from the grid solution and the enumeration
    the paper printed: a hyphen or apostrophe stays, every other break is a
    space, so (2-3,4) over ABCDEFGHI gives "AB-CDE FGHI". A linked answer's leader joins its lights. None when the entry has no
    solution, or the counts do not add up to its letters (then the model
    writes it)."""
    by_id = {entry_id(e): e for e in entries}
    lights = [by_id.get(i) for i in entry.get("group") or [entry_id(entry)]]
    if not all(lights) or not all(l.get("solution") for l in lights):
        return None
    word = "".join(l["solution"] for l in lights)
    enum = entry["clue"].get("enumeration") or ""
    counts = [int(n) for n in re.findall(r"\d+", enum)]
    if not counts or sum(counts) != len(word):
        return word
    marks = [m.strip() for m in re.split(r"\d+", enum)[1:-1]]
    out, at = "", 0
    for i, n in enumerate(counts):
        out += word[at:at + n]
        at += n
        if i < len(marks):
            out += marks[i] if marks[i] in ("-", "'") else " "
    return out


def normalize(ann, entry, entries):
    """`ann` with what code can compute filled in, so the run is not asked for it."""
    if not isinstance(ann, dict):
        return ann
    ann = dict(ann)
    if not ann.get("answer"):
        derived = derived_answer(entry, entries)
        if derived:
            ann["answer"] = derived
    blocks = [b for b in ann.get("blocks") or [] if isinstance(b, dict)]
    types = ann.get("type")
    if (any("select" in b for b in blocks) and isinstance(types, list)
            and "letter_selection" not in types):
        ann["type"] = [*types, "letter_selection"]
    # Where a block or indicator sits in the clue is computed from its words.
    for key in ("blocks", "indicators"):
        if isinstance(ann.get(key), list):
            ann[key] = [{k: v for k, v in x.items() if k != "at"} if isinstance(x, dict) else x
                        for x in ann[key]]
    return with_assembly(ann, entry)


def with_assembly(ann, entry):
    """`ann` with the assembly its blocks reach filled in (derive_assembly.complete),
    read against the entry's alteration, which the _ann file may carry."""
    if not isinstance(ann, dict):
        return ann
    if isinstance(ann.get("alteration"), dict):
        entry = {**entry, "alteration": ann["alteration"]}
    return complete(ann, entry)


def move_alteration(entry):
    """Move an `alteration` the annotation carries onto the entry, where the
    schema keeps it: the preamble's change to the answer before grid entry."""
    ann = entry.get("annotation")
    alteration = ann.pop("alteration", None) if isinstance(ann, dict) else None
    if alteration:
        entry["alteration"] = alteration


ENTRY_PATH = re.compile(r"\$\.entries\[(\d+)\]")
BLOCKS_HELP = ("write `blocks` as annotate_prompt.md shows: a cryptic_definition has "
               "2+ blocks without `gives`; a double_definition has one block per definition")


def refusal(path, puzzle, err):
    """One line per finding, keyed by the id the _ann file uses, not entries[N]."""
    lines = []
    for kind, _, what in err.flags:
        m = ENTRY_PATH.search(what)
        if m and int(m[1]) < len(puzzle["entries"]):
            eid = entry_id(puzzle["entries"][int(m[1])])
            rest = what[m.end():].removeprefix(".annotation")
            what = eid + (" " + rest[1:] if rest.startswith(".") else rest)
            if "missing required key 'blocks'" in what:
                what += f" — {BLOCKS_HELP}"
        else:
            what = f"{kind} {what}"
        lines.append("  " + what)
    return (f"apply_annotations: {path.name}: refused to write, fix these in "
            f"the _ann file:\n" + "\n".join(lines))


def apply(path, annotations, by=None):
    puzzle = read_puzzle_file(path)
    continuations = groups.leader_of(puzzle["entries"])
    ids = [entry_id(e) for e in puzzle["entries"] if entry_id(e) not in continuations]
    only = annotate_only(path)
    if only is not None:
        current = {entry_id(e): e.get("annotation") for e in puzzle["entries"]}
        by_id = {entry_id(e): e for e in puzzle["entries"]}
        kept = [k for k in ids if k in annotations and k not in only
                and current[k] not in (annotations[k], normalize(
                    annotations[k], by_id[k], puzzle["entries"]))]
        if kept:
            raise SystemExit(
                f"apply_annotations: {path.name}: {', '.join(kept)} already "
                f"annotated, and those annotations stay as they are — this run "
                f"writes only {', '.join(only)} ({view_path(path).name} "
                f"annotateOnly). Drop the other keys.")
    required = ids if only is None else [i for i in ids if i in only]
    missing = [i for i in required if i not in annotations]
    extra = [k for k in annotations if k not in ids and k not in continuations]
    covered = [f"{k} (annotate it on {continuations[k]})" for k in annotations
               if k in continuations and annotations[k] is not None]
    if missing or extra or covered:
        why = []
        if missing:
            why.append("no annotation for " + ", ".join(missing) +
                       " — every entry needs a key, and null means you could not "
                       "solve it")
        if extra:
            why.append("not a clue in this puzzle: " + ", ".join(extra) +
                       " — the ids are " + ", ".join(ids[:4]) + ", ...")
        if covered:
            why.append("continues a linked answer, so it takes null and its "
                       "leader's annotation covers the whole answer: "
                       + ", ".join(covered))
        raise SystemExit(f"apply_annotations: {path.name}: " + "; ".join(why))
    had_hints = provenance.has_hints(puzzle)
    before = [e.get("annotation") for e in puzzle["entries"]]
    # An OCR'd clue the annotator found misread lands as SOURCE_CLUE_WRONG
    # prints it, the way a re-fetch reads every served clue.
    if (puzzle.get("source") or {}).get("retrievedFrom") in provenance.OCR_CHANNELS:
        for entry in puzzle["entries"]:
            text = entry["clue"].get("text")
            printed = source_clue(puzzle["id"], entry_id(entry), text)
            if printed != text:
                entry["clue"]["text"] = printed
    for entry in puzzle["entries"]:
        if entry_id(entry) in continuations or entry_id(entry) not in annotations:
            continue
        ann = annotations[entry_id(entry)]
        if ann is None:
            entry.pop("annotation", None)
        else:
            entry["annotation"] = normalize(ann, entry, puzzle["entries"])
            move_alteration(entry)
    # Credited only for hints it changed: re-applying the file as it stands
    # writes nothing, and must not put a second name on someone else's work.
    changed = before != [e.get("annotation") for e in puzzle["entries"]]
    if changed and provenance.has_hints(puzzle):
        try:
            puzzle = provenance.credit_annotator(
                puzzle, annotator(by, path.stem), had_hints)
        except ValueError as err:
            raise SystemExit(f"apply_annotations: cannot credit these hints: {err}")
    try:
        write_puzzle_file(path, puzzle)
    except puzzle_integrity.RefusedWrite as err:
        raise SystemExit(refusal(path, puzzle, err))
    solved = sum(1 for k in required if annotations[k] is not None)
    return solved, len(required)


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
          f"{os.path.relpath(path, TOOLS.parent)}{tail}")
    if not validate:
        return 0
    return subprocess.run([sys.executable, str(TOOLS / "validate_annotations.py"),
                           path.stem]).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
