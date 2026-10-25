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
parse that does not give the answer refused, naming the step) into the
stored tree (normalize).

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
import copy
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
import provenance
import puzzle_integrity
import shape_queue
import groups  # linked answers
from groups import entry_id
import lesson_checks
import validate_annotations
from validate_annotations import committed_entries
from fetch_puzzle import (corrected_clue, read_puzzle_file, reconstructed_clue, resolve_puzzle,
                          source_clue, write_puzzle_file)

TOOLS = Path(__file__).resolve().parent

# The commands whose Bash call is the one running this file right now.
LANDING_COMMANDS = ("apply_annotations", "annotate_check", "annotate_bag")


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
                    ann_name in line or "_ann_bag_" in line or any(c in line for c in LANDING_COMMANDS)):
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
                # A bag session (tools/annotate_bag.py) writes one _ann_bag_<first>.json
                # holding every puzzle's part, keyed by id: that Write is the
                # evidence for each id it names.
                wrote = ann_name in command or ("_ann_bag_" in command and pid in command)
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


#: Derived keys a run may not write: a clue carrying one goes to from_model,
#: which names them and says to write `def`, `wp` and `notes`.
VIEW_KEYS = ("type", "answer", "blocks", "indicators", "linkWords", "assembly")


def normalize(ann, entry, entries, puzzle=None):
    """`ann` as the file stores it. The model's shape (annotation.is_model:
    `def`, `wp`, `notes`) is translated by annotation.from_model, which
    evaluates the wordplay against the answer and raises
    wordplay.WordplayError when it does not give it, or names a key the
    model may not write. A stored annotation (a tree: a commit's own
    annotation re-applied, a human edit) is taken as it is."""
    import annotation
    if not isinstance(ann, dict):
        return ann
    held = puzzle if puzzle is not None else {"entries": entries}
    if annotation.is_model(ann) or any(k in ann for k in VIEW_KEYS):
        return annotation.from_model(ann, entry, held)
    out = dict(ann)
    if isinstance(out.get("wordplay"), dict):
        # a stored tree is parse -> evaluate -> normalize too: letters checked, shape made canonical
        import wordplay
        out["wordplay"] = wordplay.normalize(
            out["wordplay"], (entry.get("clue") or {}).get("text", ""), entry.get("solution", ""))[0]
    return out


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


def refusal(path, puzzle, err):
    """One line per finding, keyed by the id the _ann file uses, not entries[N]."""
    lines = []
    for kind, _, what in err.flags:
        m = ENTRY_PATH.search(what)
        if m and int(m[1]) < len(puzzle["entries"]):
            eid = entry_id(puzzle["entries"][int(m[1])])
            rest = what[m.end():].removeprefix(".annotation")
            what = eid + (" " + rest[1:] if rest.startswith(".") else rest)
        else:
            what = f"{kind} {what}"
        lines.append("  " + what)
    return (f"apply_annotations: {path.name}: refused to write, fix these in "
            f"the _ann file:\n" + "\n".join(lines))


def mend_clues(puzzle):
    """Write each source_clue_wrong.json row into `puzzle`'s clues. A row that
    gives a blank clue its printed words makes it a clue with words, so it
    stops being marked missing; one whose words are a reconstruction
    (fetch_puzzle.RECONSTRUCTED) marks the clue `reconstructed`."""
    for entry in puzzle["entries"]:
        text = entry["clue"].get("text")
        printed = source_clue(puzzle["id"], entry_id(entry), text)
        if printed != text:
            entry["clue"]["text"] = printed
            if printed.strip():
                entry["clue"].pop("missing", None)
                entry["clue"].pop("missingNote", None)
        if (reconstructed_clue(puzzle["id"], entry_id(entry))
                and entry["clue"].get("text") == corrected_clue(puzzle["id"], entry_id(entry))):
            entry["clue"]["reconstructed"] = True


def landed(ann, entry, entries, eid, errors):
    """normalize(), with a wordplay that does not check appended to `errors`
    as "<eid>: why" (None back)."""
    import wordplay
    try:
        return carry_indicators(repair_pool_gap(normalize(ann, entry, entries), entry), entry)
    except wordplay.WordplayError as e:
        errors.append(f"{eid}: {e}")
    return None


def carry_indicators(new, entry):
    """`new` with an indicator the redo trimmed ("after leaving" -> "leaving") given back the
    words the annotation on file had on it, so the redo gate's dropped_words (the biggest
    first-check refusal in the audit) never fires on a trim. Else `new` as it was."""
    old = entry.get("annotation")
    if not isinstance(new, dict) or not isinstance(old, dict):
        return new
    try:
        import validate_annotations as V
        return V.carry_old_indicators(old, new, (entry.get("clue") or {}).get("text", ""))
    except Exception:
        return new


def repair_pool_gap(new, entry):
    """`new` with its poolGap (an anagram pool read across words the anagram does not gather)
    mended by the shape sweep's own poolGap repair, when that clears it and the tree still
    gives the answer; else `new` as it was. The model never sees a fault the fixer owns."""
    wp = new.get("wordplay") if isinstance(new, dict) else None
    clue = (entry.get("clue") or {}).get("text", "")
    if not isinstance(wp, dict) or not clue:
        return new
    try:
        import fix_shape_suspects as F
        import validate_annotations as V
        import wordplay
        # poolGap, and unindicatedBare (the "missing wordplay.noIndicator" first-check failure,
        # 100 sessions and $27 after the check in one day): a word filed on the wrong node moves
        # to the bare op, or a spare clue word beside it becomes its indicator.
        for rule, count in (("poolGap", V.pool_gaps), ("unindicatedBare", lambda t, c: V.unindicated_ops(t)),
                            ("repeatedSelection", lambda t, c: V.repeated_selections(t))):
            if not count(wp, clue):
                continue
            fixed, used = F.repair_tree(wp, clue, entry.get("solution"), {rule: F.RULE_REPAIRS[rule]})
            if not used:
                continue
            fixed = wordplay.normalize(fixed, clue, entry.get("solution", ""))[0]
            better = count(fixed, clue) < count(wp, clue)
            if better and (rule != "poolGap" or not count(fixed, clue)):
                wp = fixed
        return new if wp is new.get("wordplay") else {**new, "wordplay": wp}
    except Exception:
        return new


def keep_spelling(new, entry, was):
    """Give `new` the `spelling` it left out when the value is not the model's to choose:
    the one the committed annotation of the same answer carries (check_spelling_kept
    refused 68 sessions' first checks in 48h) or the apostrophe/accent form the
    spelling.unsaid warning prescribes (66 sessions). Changes `new` in place."""
    if new.get("spelling"):
        return
    was_ann = (was or {}).get("annotation") or {}
    same = (was or {}).get("solution", "").upper() == (entry.get("solution") or "").upper()
    said = was_ann.get("spelling") if same else None
    said = said or lesson_checks.spelling_unsaid(new, entry.get("solution") or "",
                                                 (entry.get("clue") or {}).get("enumeration"))
    if said:
        new["spelling"] = said


# The fields that only word a hint: a redo that changes nothing else has
# changed nothing a learner can use.
PROSE_KEYS = frozenset({"note", "meaning", "walkthrough", "surface", "definitionFit",
                        "joke", "misdirectedWord", "explanation", "features"})
# A listed clue whose reason is about the prose is redone for the prose.
PROSE_REASONS = ("walkthrough", "ddMisses", "model-fixable")


def bones(ann):
    """`ann` less its prose: the tree, its letters, indicators, positions and
    flags (an `unchecked` still on a step is a difference)."""
    if isinstance(ann, dict):
        return {k: bones(v) for k, v in ann.items() if k not in PROSE_KEYS}
    if isinstance(ann, list):
        return [bones(v) for v in ann]
    return ann


def redo_adds_nothing(old, new, reason=None):
    """True when the redo `new` of the hint `old` is the same tree and letters
    in other words (or not different at all): the old hint stays, byte for
    byte (10-16..18: ~6% of reruns). A clue listed for its prose is exempt."""
    if not old or not new or any(r in str(reason or "") for r in PROSE_REASONS):
        return False
    return bones(old) == bones(new)


def apply_also(puzzle, annotations, errors=None):
    """Write each alsoLeads answer's annotation, keyed by its clue id
    ("22-across/2", groups.clue_id), in place: normalized as its light
    standing as that answer's leader (groups.as_leader); likewise each offGrid
    clue's. Others untouched. A clue whose wordplay does not check is left
    as it was and named in `errors`."""
    errors = [] if errors is None else errors
    for cid, i, k, item in groups.also_clues(puzzle["entries"]):
        if cid not in annotations:
            continue
        if annotations[cid] is None:
            item.pop("annotation", None)
        else:
            view = groups.as_leader(puzzle, i, k)["entries"]
            new = landed(annotations[cid], view[i], view, cid, errors)
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
            new = landed(annotations[cid], view[0], view, cid, errors)
            if new is not None:
                item["annotation"] = new


def apply(path, annotations, by=None, only=None, partial=False):
    """Write `annotations` into the puzzle at `path`. `only` (entry ids) is the
    annotateOnly list a caller passes directly, in place of the run's view file
    (tools/prefill_hidden.py --write): the other entries keep their hints."""
    puzzle = read_puzzle_file(path)
    # The phrase a hidden-letter device spells is the puzzle's, not a clue's:
    # the _ann file carries it under "messages" beside the entry ids.
    annotations = dict(annotations)
    messages = annotations.pop(MESSAGES_KEY, None)
    # Which clue states the theme is filed by hand, not by the annotator.
    if "themeClue" in annotations:
        raise SystemExit(
            f"apply_annotations: {path.name}: themeClue is the puzzle's, filed at "
            f"filing or review, and no annotation sets or changes it. Drop the key; "
            f"if a clue states the theme and the puzzle names none, withdraw and say which")
    continuations = groups.leader_of(puzzle["entries"])
    ids = [entry_id(e) for e in puzzle["entries"] if entry_id(e) not in continuations]
    # A further answer a light starts (alsoLeads) is a clue of its own.
    also = [cid for cid, _, _, _ in groups.also_clues(puzzle["entries"])]
    also += [cid for cid, _ in groups.off_grid(puzzle)]   # and each clue off the grid
    ids += also
    only = annotate_only(path) if only is None else list(only)
    if only is not None:
        current = {entry_id(e): e.get("annotation") for e in puzzle["entries"]}
        current.update({cid: item.get("annotation") for cid, _, _, item in groups.also_clues(puzzle["entries"])})
        current.update({cid: item.get("annotation") for cid, item in groups.off_grid(puzzle)})
        by_id = {entry_id(e): e for e in puzzle["entries"]}
        kept = [k for k in ids if k in annotations and k not in only and k not in also
                and current[k] not in (annotations[k], landed(
                    annotations[k], by_id[k], puzzle["entries"], k, []))]
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
    # The model's shape names a corrected answer as `answer` itself, and is
    # translated only once the grid holds it.
    fixes, problems = model_corrections(puzzle, {
        k: v for k, v in annotations.items()
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
    unchanged = []   # redone clues whose tree and letters did not change
    # A clue on the shape re-annotation list (tools/shape_queue.py) keeps its
    # old hint against a null too, committed or not: it is live until a new
    # one validates.
    # The detectors are its gate: a tree they still flag is refused, so the
    # old tree re-filed with new prose does not pass for a re-annotation.
    relisted = shape_queue.listed(puzzle)
    # Wordplay that does not check refuses the write.
    errors = []
    for entry in puzzle["entries"]:
        if entry_id(entry) in continuations or entry_id(entry) not in annotations:
            continue
        # A run scoped to some clues (annotateOnly) writes only those: the
        # others stay byte for byte, even when the run sends them back as
        # they are (landing them again re-derives their positions and prose).
        if only is not None and entry_id(entry) not in only:
            continue
        ann = annotations[entry_id(entry)]
        was = committed.get(entry_id(entry)) or {}
        if (ann is None and entry.get("annotation") and (entry_id(entry) in relisted or (
                was.get("annotation") == entry["annotation"]
                and was.get("solution") == entry.get("solution")
                and (was.get("clue") or {}).get("text") == entry["clue"].get("text")))):
            held.append(entry_id(entry))
            continue
        if ann is None:
            entry.pop("annotation", None)
        else:
            new = landed(ann, entry, puzzle["entries"], entry_id(entry), errors)
            if new is not None:
                keep_spelling(new, entry, was)
            found = []
            if new is not None and entry_id(entry) in relisted:
                detected = shape_queue.findings(entry, new)
                found = detected + shape_queue.regressions(entry, new)
                if not detected and found:   # only what the redo lost: not the old fault
                    errors.append(f"{entry_id(entry)}: this redo gives up what the annotation on file had: "
                                  f"{'; '.join(found)}. Or give null to keep the old hint.")
                    found, new = [], None
            elif new is not None and entry.get("annotation"):
                # Every redo of an annotated clue, listed or not, may not give up
                # what the old one had (timesjumbo-1784 6d: a redo dropped
                # "displayed, in"); the one comparison is
                # validate_annotations.redo_regressions.
                if lost := shape_queue.regressions(entry, new):
                    errors.append(
                        f"{entry_id(entry)}: this redo gives up what the annotation on file had: "
                        f"{'; '.join(lost)}. Keep every clue word explained and the wordplay tree "
                        f"as real as it was, or give null to keep the old hint.")
                    new = None
            if found:
                same = (new.get("wordplay") == (entry.get("annotation") or {}).get("wordplay"))
                errors.append(
                    f"{entry_id(entry)}: is on the shape re-annotation list ({relisted[entry_id(entry)]}) "
                    f"and this {'is the same tree as the one on file' if same else 'tree is still flagged'}: "
                    f"{'; '.join(found)}. Write the wordplay tree again so no step has those faults "
                    f"(changing only the prose does not settle it), or give null to keep the old hint.")
                new = None
            old = (was.get("annotation") if (
                was.get("solution") == entry.get("solution")
                and (was.get("clue") or {}).get("text") == entry["clue"].get("text")) else None)
            # Only a scoped run (a re-annotation by hand takes the whole puzzle
            # to refresh its prose), and only against the committed hint (the
            # run's own earlier write may still be getting its prose mended).
            if (new is not None and only is not None
                    and redo_adds_nothing(old, new, relisted.get(entry_id(entry)))):
                entry["annotation"] = copy.deepcopy(old)
                unchanged.append(entry_id(entry))
                continue
            if new is not None:
                entry["annotation"] = new
                move_alteration(entry)
    apply_also(puzzle, annotations, errors)
    if errors and partial:
        # A bag run: each failing clue is already left as it was (its new tree is
        # None above), so the clues that passed are written and these are reported
        # one per line ("<id>: why", which annotate_audit parses).
        print(f"apply_annotations: {path.name}: {len(errors)} clue(s) left out, "
              f"the rest written; the left-out ones keep their old annotation:")
        for e in errors:
            print(e)
    elif errors:
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
    shape_queue.done(puzzle, {k for k, v in annotations.items() if v is not None and k not in held
                      and k not in unchanged and (only is None or k in only)},
                     {k for k in [*held, *unchanged] if k in relisted})
    for eid, new in fixes.items():
        print(f"apply_annotations: {eid} corrected to {new} — it agrees with every "
              f"crossing and printed answer (solutions.corrected)")
    if held:
        print(f"apply_annotations: {', '.join(held)} kept the committed hint your null "
              f"would have blanked — it validated before; give a hint to replace it")
    if unchanged:
        print(f"apply_annotations: {', '.join(unchanged)} redone as the same tree and letters "
              f"as the hint on file — the old hint stays as it was")
    solved = sum(1 for k in required if annotations[k] is not None or k in held)
    return solved, len(required)


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    validate = "--no-validate" not in argv
    partial = "--partial" in argv
    argv = [a for a in argv if a not in ("--no-validate", "--partial")]
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
    solved, total = apply(path, load_annotations(spec), by, partial=partial)
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
