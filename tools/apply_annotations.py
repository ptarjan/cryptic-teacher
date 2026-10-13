#!/usr/bin/env python3
"""Put a puzzle's annotations into its file.

    python3 tools/apply_annotations.py 30098 tools/_ann_30098.json
    python3 tools/apply_annotations.py cryptic-30098          # the default path
    cat ann.json | python3 tools/apply_annotations.py 30098 -

The input is one JSON object keyed by entry id, each value an annotation in
the model's shape `tools/annotate_prompt.md` describes:

    {"1-across": {"def": "...", "wp": "[can]LOO + del<losing>([accept]BUY, [you]U)",
                  "notes": {...}, "explanation": {...}, "features": {...}},
     "12-across": null}

Every entry in the puzzle must appear as a key. A key whose value is `null` says
the clue is deliberately unsolved, which the prompt allows and which is very
different from forgetting one — so absence is an error and `null` is not.

Each clue is translated (annotation.from_model: the wordplay evaluated, a
parse that does not give the answer refused, naming the step) and written in
the shape of the file it goes into (normalize), so a file stays wholly one
shape: a legacy file takes annotation.view() of the tree, a format v2 file the
tree. A clue in the old shape (type, blocks: a run that started on the old
prompt) is still taken: `assembly` worked out from its blocks wherever they
reach the answer (tools/derive_assembly.py), clue words written as the clue
prints them (definitions.respell), and a one-letter block quoting its
selector ("Irish leader" gives I) split into the block "Irish" with `select`
and the indicator "leader"; into a v2 file it goes through convert_v2.check,
and one that does not convert is left as the file had it.

Except when the run's copy of the puzzle (tools/_puzzle_<ID>.json, written by
`annotate_check.py --view`) lists `annotateOnly`: then only those ids need a
key, every other entry keeps its annotation byte for byte, and a key that
would change one is refused.

The annotations themselves are the work, and they are all that goes in the
JSON: the file I/O, markers and provenance are this tool's job, not the run's.

On a grid a model solved (solutions.origin "model"), an annotation whose
`answer` differs from its light's letters corrects them, once the new fill
agrees with every crossing, every answer the paper printed and every blog we
hold (model_corrections); the change is listed in solutions.corrected. Anything
else is refused whole. Elsewhere the grid is the key and the validator refuses
the mismatch.

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
import definitions
import provenance
import puzzle_integrity
import groups  # linked answers
from derive_assembly import complete
from groups import entry_id
from validate_annotations import SELECT_NOUNS, committed_entries, selector_in_block
from fetch_puzzle import read_puzzle_file, resolve_puzzle, source_clue, write_puzzle_file

TOOLS = Path(__file__).resolve().parent

# The commands whose Bash call is the one running this file right now.
LANDING_COMMANDS = ("apply_annotations", "annotate_check")


#: The _ann file's key for the puzzle's `messages` (tools/hidden_messages.py).
MESSAGES_KEY = "messages"


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
    this puzzle. A call naming this puzzle's _ann file (a Write, or a Bash that
    builds it) counts as that call too: tools/puzzle_worker.sh runs
    annotate_check itself after a cold solve, so a model that only wrote the
    file never ran either command. None when no
    transcript holds such a call.
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
    ann_name = default_input(Path(pid)).name
    best = None
    for f in (f for f, t in mtimes.items() if t >= newest - 600):
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            if '"tool_use"' not in line or not (
                    ann_name in line or any(c in line for c in LANDING_COMMANDS)):
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
                wrote = ann_name in command
                if not (wrote or any(c in command for c in LANDING_COMMANDS)):
                    continue
                if not provenance.MODEL_ID.fullmatch(msg.get("model") or ""):
                    continue
                rank = (wrote or number in command, rec.get("timestamp") or "")
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


class Unlandable(ValueError):
    """An old-prompt annotation that cannot be written into a format v2 file:
    convert_v2.check found it contradicting itself or its entry."""


def file_is_v2(entries, puzzle=None):
    """Whether the file these entries come from is format v2
    (puzzle_schema.is_v2; from the annotations alone without the puzzle)."""
    import puzzle_schema
    if puzzle is not None and "entries" in puzzle and "number" in puzzle:
        return puzzle_schema.is_v2(puzzle)
    return any(puzzle_schema.is_v2_annotation(e.get("annotation"))
               for e in entries if e.get("annotation"))


def normalize(ann, entry, entries, v2=None, puzzle=None):
    """`ann` as it is stored in a file of the given shape (`v2`; None reads
    it off the entries), with what code can compute filled in.

    Two shapes come in. The model's shape (annotation.is_model: `def`, `wp`,
    `notes`) is translated by annotation.from_model, which evaluates the
    wordplay against the answer and raises wordplay.WordplayError when it does
    not give it. An old-prompt annotation (type, blocks, ...) from a run that
    started before the prompt changed is normalised the old way. A file is
    wholly one shape (puzzle_schema.format_problems), so each is then written
    in the file's: a v2 annotation goes into a legacy file as annotation.view()
    (the legacy fields it implies), and an old-prompt one into a v2 file
    through convert_v2.check (Unlandable when it does not convert)."""
    import annotation
    if not isinstance(ann, dict):
        return ann
    if v2 is None:
        v2 = file_is_v2(entries, puzzle)
    held = puzzle if puzzle is not None else {"entries": entries}
    if annotation.is_model(ann):
        stored = annotation.from_model(ann, entry, held)
        if v2:
            return stored
        here = {**entry, "alteration": stored["alteration"]} if "alteration" in stored else entry
        legacy = annotation.view(stored, here, held)
        # A double definition's meaning is its block's note in a legacy file.
        if legacy.get("definitions"):
            legacy["definitions"] = [{k: v for k, v in d.items() if k != "meaning"}
                                     for d in legacy["definitions"]]
        if "alteration" in stored:
            legacy["alteration"] = stored["alteration"]
        legacy = with_assembly(split_selectors(in_clue_spelling(legacy, entry["clue"].get("text") or "")), entry)
        # The tree's letters were checked step by step; a legacy file says so
        # with `pieces` (a selection or deletion builds the answer in one).
        asm = legacy.get("assembly") or {}
        if stored.get("wordplay") and not asm.get("pieces") and stored["wordplay"].get("op") != "cryptic":
            legacy["assembly"] = {"pieces": [annotation.wordplay_letters(legacy, here)], **asm}
        return legacy
    legacy = normalize_legacy(ann, entry, entries)
    if not v2:
        return legacy
    import convert_v2
    here = {**entry, "alteration": legacy["alteration"]} if isinstance(legacy.get("alteration"), dict) else entry
    status, kinds, new = convert_v2.check(legacy, here, held)
    if status == "failed":
        raise Unlandable(", ".join(sorted(kinds)))
    if "alteration" in legacy:
        new["alteration"] = legacy["alteration"]
    return new


def normalize_legacy(ann, entry, entries):
    """An old-prompt annotation (type, blocks, ...) with what code can
    compute filled in, so the run is not asked for it. Goes when the
    old-shape path does (the plan's step 9: a week with no old-shape file)."""
    ann = dict(ann)
    if not ann.get("answer"):
        derived = derived_answer(entry, entries)
        if derived:
            ann["answer"] = derived
    ann = in_clue_spelling(ann, entry["clue"].get("text") or "")
    ann = split_selectors(ann)
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


def in_clue_spelling(ann, clue):
    """`ann` with each block's, indicator's and link word's clue words spelt
    as the clue prints them (definitions.respell): a retyped apostrophe, a
    capital or a space is not a different word."""
    ann = dict(ann)
    for key, field in (("blocks", "clueFragment"), ("indicators", "text")):
        if isinstance(ann.get(key), list):
            ann[key] = [{**x, field: definitions.respell(x[field], clue)}
                        if isinstance(x, dict) and isinstance(x.get(field), str) else x
                        for x in ann[key]]
    if isinstance(ann.get("linkWords"), list):
        ann["linkWords"] = [definitions.respell(w, clue) for w in ann["linkWords"]]
    return ann


def split_selectors(ann):
    """`ann` with each one-letter block that quotes its selector ("Irish
    leader" gives I) split into the block of the word it selects from, with
    `select`, and the selector as a letter_selection indicator, the shape
    validate_annotations.check_selectors_are_indicators asks for."""
    blocks, inds = ann.get("blocks"), ann.get("indicators", [])
    if not isinstance(blocks, list) or not isinstance(inds, list):
        return ann
    out, added = [], []
    for b in blocks:
        found = (isinstance(b, dict)
                 and len(re.sub(r"[^A-Za-z]", "", str(b.get("gives") or ""))) == 1
                 and selector_in_block(b))
        where = found and len(found[1].split()) == 1 and next(
            (k for k in SELECT_NOUNS if b["gives"].strip().upper() == _pick(k, found[1])), None)
        if not where:
            out.append(b)
            continue
        sel, rest = found
        out.append({**b, "clueFragment": rest, "select": where})
        if not any(isinstance(i, dict) and i.get("text") == sel for i in inds + added):
            added.append({"text": sel, "for": "letter_selection",
                          "note": f"{sel!r} keeps only the {where} letter of {rest!r}"})
    if out == blocks:
        return ann
    types = ann.get("type")
    if isinstance(types, list) and "letter_selection" not in types:
        types = [*types, "letter_selection"]
    return {**ann, "type": types, "blocks": out, "indicators": [*inds, *added]}


def _pick(where, word):
    """The letter of `word` a first, last or middle selection keeps."""
    run = re.sub(r"[^A-Za-z]", "", word).upper()
    return {"first": run[:1], "last": run[-1:],
            "middle": run[(len(run) - 1) // 2:len(run) // 2 + 1]}[where]


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


def letters(text):
    return re.sub(r"[^A-Z]", "", str(text or "").upper())


def model_corrections(puzzle, annotations):
    """(entry id -> new letters, problems) for the lights of a model-solved grid
    whose annotation's `answer` spells something else.

    A cold solve's answer is a guess the crossings could not rule out, and the
    annotator reading the clue word by word is the first thing that can. So it
    may replace one, but only with a fill the solve's own gate would pass:
    every crossing agreeing, every printed answer and blog answer kept. A
    correction that needs a crossing changed must change that light's answer
    too, in the same file. ({}, []) on any other grid, and for an entry whose
    answer is altered before entry (its `answer` is not the grid's word)."""
    import apply_solution
    if provenance.solution_origin_from_file(puzzle) != "model" or not all(
            e.get("solution") for e in puzzle["entries"]):
        return {}, []
    by_id = {entry_id(e): e for e in puzzle["entries"]}
    fixes = {}
    for eid, ann in annotations.items():
        if not isinstance(ann, dict) or eid not in by_id or ann.get("alteration"):
            continue
        lights = [by_id.get(i) for i in by_id[eid].get("group") or [eid]]
        if not all(lights) or any(l.get("alteration") for l in lights):
            continue
        want, have = letters(ann.get("answer")), "".join(l["solution"] for l in lights)
        if not want or want == have or len(want) != len(have):
            continue                     # a wrong length is the validator's to name
        at = 0
        for light in lights:
            new = want[at:at + light["length"]]
            at += light["length"]
            if new != light["solution"]:
                fixes[entry_id(light)] = new
    if not fixes:
        return {}, []
    fill = {eid: fixes.get(eid, e["solution"]) for eid, e in by_id.items()}
    _, _, problems = apply_solution.check_fill(puzzle, fill)
    problems += apply_solution.check_printed(puzzle, fill)
    if not problems:
        problems = apply_solution.check_sources(puzzle, fill)
    return fixes, problems


ENTRY_PATH = re.compile(r"\$\.entries\[(\d+)\]")
BLOCKS_HELP = ("this clue is in the old shape (type, blocks): rewrite it as annotate_prompt.md's "
               "Schema shows, `def`, `wp` and `notes`, and the type and blocks are worked out from `wp`")


def refusal(path, puzzle, err):
    """One line per finding, keyed by the id the _ann file uses, not entries[N]."""
    lines = []
    for kind, _, what in err.flags:
        m = ENTRY_PATH.search(what)
        if m and int(m[1]) < len(puzzle["entries"]):
            eid = entry_id(puzzle["entries"][int(m[1])])
            rest = what[m.end():].removeprefix(".annotation")
            what = eid + (" " + rest[1:] if rest.startswith(".") else rest)
            if "missing required key 'blocks'" in what or "missing required key 'type'" in what:
                what += f" — {BLOCKS_HELP}"
        else:
            what = f"{kind} {what}"
        lines.append("  " + what)
    return (f"apply_annotations: {path.name}: refused to write, fix these in "
            f"the _ann file:\n" + "\n".join(lines))


def mend_clues(puzzle):
    """Write each source_clue_wrong.json row into `puzzle`'s clues. A row that
    gives a blank clue its printed words makes it a clue with words, so it
    stops being marked missing."""
    for entry in puzzle["entries"]:
        text = entry["clue"].get("text")
        printed = source_clue(puzzle["id"], entry_id(entry), text)
        if printed != text:
            entry["clue"]["text"] = printed
            if printed.strip():
                entry["clue"].pop("missing", None)
                entry["clue"].pop("missingNote", None)


def landed(ann, entry, entries, v2, eid, errors, skipped=None):
    """normalize(), with a wordplay that does not check appended to `errors`
    as "<eid>: why" (None back), and an old-prompt annotation that cannot
    enter a v2 file appended to `skipped` (None back: the clue is left as
    it was)."""
    import wordplay
    try:
        return normalize(ann, entry, entries, v2)
    except Unlandable as e:
        if skipped is None:
            errors.append(f"{eid}: {e}")
        else:
            skipped.append(f"{eid} ({e})")
    except wordplay.WordplayError as e:
        errors.append(f"{eid}: {e}")
    return None


def apply_also(puzzle, annotations, v2=None, errors=None, skipped=None):
    """Write each alsoLeads answer's annotation, keyed by its clue id
    ("22-across/2", groups.clue_id), in place: normalized as its light
    standing as that answer's leader (groups.as_leader); likewise each offGrid
    clue's. Others untouched. A clue whose wordplay does not check is left
    as it was and named in `errors`."""
    errors = [] if errors is None else errors
    v2 = file_is_v2(puzzle["entries"], puzzle) if v2 is None else v2
    for cid, i, k, item in groups.also_clues(puzzle["entries"]):
        if cid not in annotations:
            continue
        if annotations[cid] is None:
            item.pop("annotation", None)
        else:
            view = groups.as_leader(puzzle, i, k)["entries"]
            new = landed(annotations[cid], view[i], view, v2, cid, errors, skipped)
            if new is not None:
                item["annotation"] = new
    # A clue entered off the grid (offGrid, "1-offgrid"): normalized on a
    # light of its own (groups.alone).
    for cid, item in groups.off_grid(puzzle):
        if cid not in annotations:
            continue
        if annotations[cid] is None:
            item.pop("annotation", None)
        else:
            view = groups.alone(puzzle, cid)["entries"]
            new = landed(annotations[cid], view[0], view, v2, cid, errors, skipped)
            if new is not None:
                item["annotation"] = new


def apply(path, annotations, by=None):
    puzzle = read_puzzle_file(path)
    # The phrase a hidden-letter device spells is the puzzle's, not a clue's:
    # the _ann file carries it under "messages" beside the entry ids.
    annotations = dict(annotations)
    messages = annotations.pop(MESSAGES_KEY, None)
    continuations = groups.leader_of(puzzle["entries"])
    ids = [entry_id(e) for e in puzzle["entries"] if entry_id(e) not in continuations]
    # A further answer a light starts (alsoLeads) is a clue of its own.
    also = [cid for cid, _, _, _ in groups.also_clues(puzzle["entries"])]
    also += [cid for cid, _ in groups.off_grid(puzzle)]   # and each clue off the grid
    ids += also
    only = annotate_only(path)
    # The file's shape, read before anything is written into it.
    v2 = file_is_v2(puzzle["entries"], puzzle)
    if only is not None:
        current = {entry_id(e): e.get("annotation") for e in puzzle["entries"]}
        current.update({cid: item.get("annotation") for cid, _, _, item in groups.also_clues(puzzle["entries"])})
        current.update({cid: item.get("annotation") for cid, item in groups.off_grid(puzzle)})
        by_id = {entry_id(e): e for e in puzzle["entries"]}
        kept = [k for k in ids if k in annotations and k not in only and k not in also
                and current[k] not in (annotations[k], landed(
                    annotations[k], by_id[k], puzzle["entries"], v2, k, []))]
        if kept:
            raise SystemExit(
                f"apply_annotations: {path.name}: {', '.join(kept)} already "
                f"annotated, and those annotations stay as they are — this run "
                f"writes only {', '.join(only)} ({view_path(path).name} "
                f"annotateOnly). Drop the other keys.")
    # A clue the annotator found misprinted lands as SOURCE_CLUE_WRONG prints
    # it, whatever channel served it.
    mend_clues(puzzle)
    # A clue printed with no words has nothing to explain: it takes null.
    blank = {entry_id(e) for e in puzzle["entries"] if e["clue"].get("missing")}
    required = [i for i in (ids if only is None else [i for i in ids if i in only])
                if i not in blank]
    missing = [i for i in required if i not in annotations]
    wordless = [k for k in annotations if k in blank and annotations[k] is not None]
    extra = [k for k in annotations if k not in ids and k not in continuations]
    covered = [f"{k} (annotate it on {continuations[k]})" for k in annotations
               if k in continuations and annotations[k] is not None]
    if missing or extra or covered or wordless:
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
        if wordless:
            why.append("the paper printed no words for " + ", ".join(wordless) +
                       ", so there is no wordplay to explain — give them null")
        raise SystemExit(f"apply_annotations: {path.name}: " + "; ".join(why))
    by_id_all = {entry_id(e): e for e in puzzle["entries"]}
    import annotation
    # The model's shape names a corrected answer as `answer` itself, and is
    # translated only once the grid holds it.
    fixes, problems = model_corrections(puzzle, {
        k: v if annotation.is_model(v) else normalize_legacy(v, by_id_all[k], puzzle["entries"])
        for k, v in annotations.items()
        if k in required and k in by_id_all and isinstance(v, dict)})
    if problems:
        raise SystemExit(
            f"apply_annotations: {path.name}: refused to write — an `answer` here "
            f"replaces the model's {', '.join(f'{k} with {v}' for k, v in fixes.items())}, "
            f"but the fill it makes fails the grid:\n"
            + "\n".join(f"  {p}" for p in problems)
            + "\nA corrected answer must agree with every crossing and every answer "
            "the paper printed. Correct the crossing light's answer too if its clue "
            "gives that letter, or put the model's answer back and leave the clue null.")
    if fixes:
        today = time.strftime("%Y-%m-%d")
        log = list(provenance.solution_detail(puzzle).get("corrected") or [])
        for eid, new in fixes.items():
            log.append({"entry": eid, "was": by_id_all[eid]["solution"], "now": new,
                        "date": today})
            by_id_all[eid]["solution"] = new
        puzzle = provenance.with_solution_detail(
            puzzle, {**provenance.solution_detail(puzzle), "corrected": log})
    had_hints = provenance.has_hints(puzzle)
    def written():
        return [e.get("annotation") for e in puzzle["entries"]] + [
            item.get("annotation") for _, _, _, item in groups.also_clues(puzzle["entries"])] + [
            item.get("annotation") for _, item in groups.off_grid(puzzle)]
    before = written()
    # A null cannot blank a hint that is committed for the same answer and
    # clue: that hint validated and shipped, and a re-annotation that could not
    # parse the clue again knows less than the run that did (nation-3405 22D,
    # 10-12: run 2 nulled what run 1 had hinted, and the puzzle was discarded
    # for it). Its own uncommitted hints a run may still null.
    committed = committed_entries(path) or {}
    held = []
    # Wordplay that does not check (refuses the write), and old-prompt
    # annotations a v2 file cannot take (left as they were, and named).
    errors, skipped = [], []
    for entry in puzzle["entries"]:
        if entry_id(entry) in continuations or entry_id(entry) not in annotations:
            continue
        ann = annotations[entry_id(entry)]
        was = committed.get(entry_id(entry)) or {}
        if (ann is None and entry.get("annotation") and was.get("annotation") == entry["annotation"]
                and was.get("solution") == entry.get("solution")
                and (was.get("clue") or {}).get("text") == entry["clue"].get("text")):
            held.append(entry_id(entry))
            continue
        if ann is None:
            entry.pop("annotation", None)
        else:
            new = landed(ann, entry, puzzle["entries"], v2, entry_id(entry), errors, skipped)
            if new is not None:
                entry["annotation"] = new
                move_alteration(entry)
    apply_also(puzzle, annotations, v2, errors, skipped)
    if errors:
        raise SystemExit(
            f"apply_annotations: {path.name}: refused to write — fix these in the _ann "
            f"file:\n" + "\n".join(f"  {e}" for e in errors))
    if messages is not None:
        if messages:
            puzzle["messages"] = messages
        else:
            puzzle.pop("messages", None)
    # Credited only for hints it changed: re-applying the file as it stands
    # writes nothing, and must not put a second name on someone else's work.
    changed = before != written()
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
    for eid, new in fixes.items():
        print(f"apply_annotations: {eid} corrected to {new} — it agrees with every "
              f"crossing and printed answer (solutions.corrected)")
    if held:
        print(f"apply_annotations: {', '.join(held)} kept the committed hint your null "
              f"would have blanked — it validated before; give a hint to replace it")
    if skipped:
        print(f"apply_annotations: {', '.join(skipped)}: written in the old shape and could "
              f"not be converted for this format v2 file, so left as it was (the burn "
              f"re-annotates a clue with no hint)")
    solved = sum(1 for k in required if annotations[k] is not None or k in held)
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
