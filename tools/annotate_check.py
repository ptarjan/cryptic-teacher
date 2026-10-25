#!/usr/bin/env python3
"""Everything that must be true of a puzzle's annotations, in one command.

    python3 tools/annotate_check.py cryptic-30098
    python3 tools/annotate_check.py --view cryptic-30098   # the run's input
    python3 tools/annotate_check.py cryptic-30098 --patch FILE
    python3 tools/annotate_check.py --reread times-18749   # misread? ask the OCR again
    python3 tools/annotate_check.py cryptic-30098 --by claude-opus-5-5  # hints another session wrote
    python3 tools/annotate_check.py cryptic-30098 --withdraw "why"  # take back this run's work

The _ann file is in the model's shape (annotate_prompt.md's Schema: `def`,
`wp`, `notes`, ...), which apply_annotations translates (annotation.from_model)
into the stored tree; a `wp` that does not give the answer stops the apply
with a line naming the step that broke.

--patch merges FILE, {"8-down": {"wp": "...", "notes": {"in": "..."}}},
into tools/_ann_<ID>.json first: each named field replaced, null removing it,
except `notes`, merged note by note (a null note removed), and deletes FILE.
Many clues' fixes are one Write and this one command, not a fix script, which
these runs cannot get approved.

An entry's `printedClue` (a misread clue mended), `setterError` (a setter's
slip) and `answerTypo` (the paper's key misprinted) are filed as its rows of
tools/data/source_clue_wrong.json, setter_error.json and
source_answer_wrong.json and taken off the entry (FILED), so filing one is a
field in the same write, not a hand edit of a sorted table. An `answerTypo`
also puts the corrected letters in the puzzle file's grid before the apply.

An entry the _ann file has no key for is filled in as null (not done yet), so
a file written a few clues at a time applies as it stands, and an `answer`
typed with the enumeration's commas is respelt with spaces. The run's view
shows `existingAnnotations` in the model's shape too (in_notation).

Applies tools/_ann_<ID>.json, validates, runs both audit tools and
syntax-checks the file — and prints one report with a count at the
top and one instruction at the bottom.

It exists because of what the annotation runs actually cost. Cost tracks the
number of turns, and roughly as its square, since every turn resends the whole
transcript before it; it does not track the puzzle. Five commands after every
edit is five turns, and chaining them into one is worse, because a compound
command needs an approval these runs cannot give and aborts whole, having run
nothing. Worse still is the shape the transcripts showed: fix one warning,
re-run, read the next warning, fix that. One run already knows everything that
is wrong, so this says all of it at once and asks for one edit back.

--withdraw is how a run takes back its own work when it cannot pass the
check honestly (solve_prompt.md: annotate nothing, stop). Each check has
already applied tools/_ann_<ID>.json to the puzzle file, and a run's
permissions refuse `git checkout`, so it cannot put the file back itself: this
leaves tools/_withdrawn_<ID>.txt holding the reason, and the harness
(tools/puzzle_worker.sh, worker_withdrawn) restores the file, drops the
annotations and ships nothing the run wrote. genius-268 (10-13) asked for a
checkout it could not run, and its 29 hints and guessed fills were committed.

--reread, run by tools/prereset_backfill.sh on a finished run before it
commits or discards it, asks the scan filer to read an OCR'd puzzle's source
again (scan_queue.request_reread) when the run met a misread clue: it filed
a printedClue row HEAD does not have, or check_clue_unchanged or
check_anagram_letters fails, or it left a clue null. Exit 0 when a re-read was queued.

Exit code is the validator's: 0 when the puzzle is publishable. Warnings and
audit hits are worth fixing and do not fail the build. 2 when the annotations
were not applied at all (STOPPED), so the puzzle file is as it was.
"""
import contextlib
import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from annotate_audit import load_templates, rule_name
import annotation
import apply_annotations
import blog_post
import fetch_puzzle
import clue_types
import corroborate
import definitions
import groups
import provenance
import puzzle_schema
import shape_queue
from groups import entry_id
import series
import validate_annotations
import wordplay
from apply_annotations import (
    annotate_only, apply_also, current_view, default_input, move_alteration, normalize, view_path)
from fetch_puzzle import clued, read_puzzle_file, resolve_puzzle
from json_merge import dump_lines
from validate_annotations import letters
from find_answer_leaks import leaks, light_solutions, names, pieces_of, unname
from find_renarration import scan

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
# Printed under a clean report: the run's whole remaining job is one line.
STOP_NOW = ("Stop now: end your turn with one short line (a cold solve: its "
            "confidence line). No summary, no review, no further pass.")


def run(args):
    """A step that has to be a subprocess, with its output kept.

    A missing binary comes back as a step that did not happen and says so,
    rather than as a traceback that loses every result already gathered.
    """
    try:
        p = subprocess.run(args, capture_output=True, text=True, cwd=ROOT)
    except FileNotFoundError:
        return None, f"{args[0]} is not on PATH, so this step did not run"
    return p.returncode, (p.stdout + p.stderr).strip()


# Which blog explains a series clue by clue, where tools/series.py does not
# already say. Every series here is covered by fifteensquared.net.
FIFTEENSQUARED = {"cryptic", "quiptic", "everyman", "independent", "indysunday",
                  "cyclops"}


def blog_of(puzzle):
    """(host, search words) for a blog that explains this puzzle, or None."""
    s = series.of(puzzle)
    host = (series.meta(s) or {}).get("blog") if s in series.SERIES else None
    host = host or ("fifteensquared.net" if s in FIFTEENSQUARED else None)
    if not host:
        return None
    kind = series.SERIES[s].get("kind", "")
    words = [host.split(".")[0], series.SERIES[s].get("publisher", "")]
    if kind not in ("", "Cryptic") and kind not in words[1]:
        words.append(kind)
    return host, " ".join(w for w in words + [str(puzzle.get("number", ""))] if w)


def unsolved(puzzle):
    """Entries still null that need an annotation: not a linked answer's
    continuation, not a clue the setter left blank, and not a blind run's miss (validate_annotations decides both)."""
    misses = validate_annotations.blind_misses(puzzle["id"])
    continuations = groups.leader_of(puzzle["entries"])
    # A further answer its light starts (alsoLeads) is a clue of its own,
    # seen as its light standing as that answer's leader.
    also = [groups.as_leader(puzzle, i, k)["entries"][i]
            for cid, i, k, item in groups.also_clues(puzzle["entries"])
            if not item.get("annotation") and cid not in misses]
    # A clue entered off the grid (offGrid) is a clue like any other.
    also += [groups.as_entry(puzzle, cid) for cid, item in groups.off_grid(puzzle)
             if not item.get("annotation") and cid not in misses]
    return [e for e in puzzle["entries"]
            if not e.get("annotation") and entry_id(e) not in misses
            and entry_id(e) not in continuations
            and not validate_annotations.is_blank_clue(e["clue"].get("text", ""))] + also


def is_blind(puzzle):
    """A blind run is hiding the key: a blog would hand it back."""
    return ((ROOT / ".blind" / f"{puzzle['id']}.json").exists()
            or any(not e.get("solution") for e in puzzle["entries"]))


# What the annotate run reads the puzzle from: the clues, answers and grid, and
# nothing that says where the answers came from. solutions.blog names the blog
# the key was taken from, and a run that can see that URL fetches it before
# trying a single clue; the blog is disclosed by notes() below, once the run is
# stuck, and not before. A whitelist, so a new top-level field stays hidden
# until someone decides the run should see it.
VIEW_KEYS = ("id", "number", "series", "name", "setter", "dimensions", "preamble",
             "themeClue", "cluesUnplaced", "entries")


def to_write(puzzle, before):
    """The ids a run on this puzzle annotates: the clues that lack a hint,
    plus `before`, the list the run started with, so a clue the run has since
    written stays its own to fix, and on an OCR'd puzzle the clues it shows
    blank. Every other annotation is fixed context.

    None, at the start of a run on a puzzle with no hints yet or none
    missing: the run takes the whole puzzle."""
    continuations = groups.leader_of(puzzle["entries"])
    clues = [e for e in puzzle["entries"] if entry_id(e) not in continuations]
    readable = {entry_id(e) for e in clued(clues)}
    if (puzzle.get("source") or {}).get("retrievedFrom") in provenance.OCR_CHANNELS:
        # A clue the OCR lost is the run's too: the scan may print it, and
        # a source_clue_wrong.json row with "" served restores it.
        readable |= {entry_id(e) for e in clues if validate_annotations.is_blank_clue(e["clue"].get("text", ""))}
    only = [entry_id(e) for e in clues if entry_id(e) in (before or ())
            or (not e.get("annotation") and entry_id(e) in readable)]
    only += [cid for cid, _, _, item in groups.also_clues(puzzle["entries"])
             if cid in (before or ()) or not item.get("annotation")]
    only += [cid for cid, item in groups.off_grid(puzzle)
             if cid in (before or ()) or not item.get("annotation")]
    # The shape re-annotation list's clues (tools/shape_queue.py): hinted
    # already, and the hint stays until the new one validates.
    only += [cid for cid in shape_queue.flagged(puzzle) if cid not in only]
    if before is None and (not only or not any(e.get("annotation") for e in clues)):
        return None
    return only


def nothing_due(puzzle):
    """Whether a run on this puzzle would have nothing to write: it has hints,
    every clue a run could write has one, and no clue is on the shape list.
    to_write answers None for that case (the whole puzzle), which is right
    for a hand-started re-annotation and wrong for the burn: a queue entry
    gone stale (its shape rows pruned since the plan was read) bought a
    whole-puzzle rewrite of azed-2573 (b5320ba868, ~114k tokens, 36 clues
    already hinted). The burn skips such a puzzle (pool_launch)."""
    clues = [e for e in puzzle["entries"] if entry_id(e) not in groups.leader_of(puzzle["entries"])]
    return (to_write(puzzle, None) is None
            and any(e.get("annotation") for e in clues))


def grid_rows(puzzle):
    """The filled grid as one string per row, `.` a block and `-` a square no
    answer fills yet, so crossings are read off the view rather than rebuilt
    from the puzzle file's positions by a script."""
    dims = puzzle.get("dimensions") or {}
    cols, rows = dims.get("cols"), dims.get("rows")
    if not cols or not rows:
        return None
    grid = [["."] * cols for _ in range(rows)]
    for e in puzzle["entries"]:
        pos = e.get("position") or {}
        x, y = pos.get("x"), pos.get("y")
        if x is None or y is None:
            continue
        # A numerical puzzle's squares hold digits (puzzle["numeric"]).
        letters = re.sub(r"[^A-Z0-9]" if puzzle.get("numeric") is True else r"[^A-Z]", "",
                         (e.get("solution") or "").upper())
        for i in range(e.get("length") or len(letters)):
            cx, cy = (x + i, y) if e.get("direction") == "across" else (x, y + i)
            if cy < rows and cx < cols:
                c = letters[i] if i < len(letters) else "-"
                if grid[cy][cx] in (".", "-"):
                    grid[cy][cx] = c
    return ["".join(r) for r in grid]


def view_line(e, leaders, model=()):
    """One entry as a line: id | group | SOLUTION | clue (enumeration). An
    answer in `model` is marked (MODEL): a cold solve's, which the run may
    correct (apply_annotations.model_corrections)."""
    clue = e["clue"]
    words = clue.get("text") or "(no clue printed)"
    if clue.get("enumeration"):
        words += f" ({clue['enumeration']})"
    eid = entry_id(e)
    group = "+".join(e["group"]) if e.get("group") else (
        f"in {leaders[eid]}" if eid in leaders else "-")
    solution = e.get("solution") or "?"
    if eid in model:
        solution += " (MODEL)"
    if e.get("solutionConfidence"):
        solution += f" ({e['solutionConfidence']})"
    if e.get("alteration"):
        solution += f" (alteration from {e['alteration']['from']})"
    return f"{eid} | {group} | {solution} | {words}"


def scan_path(puzzle):
    """tools/_scan_<id>.png, the printed clues of a puzzle OCR'd off an
    archive.org scan (tools/scan_crop.py), copied beside the run's view so
    its Read reaches it; None when the puzzle has no scan to show."""
    if (puzzle.get("source") or {}).get("retrievedFrom") not in provenance.OCR_CHANNELS:
        return None
    out = TOOLS / f"_scan_{puzzle['id']}.png"
    if out.exists():
        return out
    import scan_crop
    try:
        shutil.copyfile(scan_crop.crop(puzzle["id"]), out)
    except scan_crop.NoCrop:
        return None
    return out


def in_notation(ann, entry, puzzle):
    """A stored annotation as the run writes one (annotation.to_model: `def`,
    `wp`, `notes`), so the context it reads is in its own notation; one
    to_model cannot render is shown as stored."""
    try:
        return annotation.to_model(ann)
    except (ValueError, KeyError, TypeError, IndexError, StopIteration):
        return ann


def hidden_drafts(puzzle, only):
    """{entry id: `def`/`wp`/`notes`} for each clue the run writes that
    tools/prefill_hidden.py reads as a hidden word and whose draft validates:
    the mechanical wordplay, shown in `draftAnnotations` for the run to keep and
    complete with `explanation` and `features` (the prompt says how). Computed
    on the fly; empty, never an error, when the prefill cannot be built, since
    a draft is a convenience and the run can always parse the clue itself."""
    try:
        import prefill_hidden
        drafts = prefill_hidden.prefill_puzzle(puzzle)
    except Exception:
        return {}
    return {eid: d for eid, d in drafts.items() if only is None or eid in only}


def keep_words(puzzle, only):
    """{entry id: "w1 w2 ..."} for each clue being redone (hinted already): the
    old annotation's words the redo gate (validate_annotations.redo_regressions)
    refuses to lose, so the run keeps them in the new tree up front."""
    out = {}
    for e in puzzle["entries"]:
        eid = entry_id(e)
        if eid in only and e.get("annotation"):
            words = validate_annotations.redo_keep_words(e["annotation"], (e.get("clue") or {}).get("text"))
            if words:
                out[eid] = " ".join(words)
    return out


def write_view(path):
    """Write the annotate run's copy of the puzzle file, current as of now.

    JSON, since apply_annotations reads `annotateOnly` back out of it, but
    with `entries` one line each (`1-across | group | SOLUTION | clue (enum)`)
    in place of an object per entry: the run needs the clue, the answer and
    which lights are linked, and a pretty-printed object per entry was five
    times the reading for it. An annotation already on an entry the run
    leaves alone is kept in `existingAnnotations` only when linked (same group)
    to one being written; the others are left out of the view."""
    puzzle = read_puzzle_file(path)
    top = {**puzzle, "series": series.of(puzzle), "name": series.display_name(puzzle)}
    view = {k: top[k] for k in VIEW_KEYS if k in top and k != "entries"}
    if (puzzle.get("source") or {}).get("retrievedFrom"):
        view["source"] = {"retrievedFrom": puzzle["source"]["retrievedFrom"]}
    # A run that started on the whole puzzle stays on it; one that started on
    # the missing clues keeps that list.
    started = current_view(path)
    only = None if started is not None and "annotateOnly" not in started else \
        to_write(puzzle, (started or {}).get("annotateOnly"))
    pending = default_input(path)
    view["annotationsFile"] = (
        f"{pending.name} exists: Read it and continue from it" if pending.exists()
        else f"no {pending.name} yet: write it")
    if only is not None:
        view["annotateOnly"] = only
        # Why a hinted clue is being redone, so the run knows what was wrong.
        flagged = {c: r for c, r in shape_queue.flagged(puzzle).items() if c in only}
        if flagged:
            view["flagged"] = {c: f"the hint on file has a wrongly shaped wordplay tree ({r}): "
                                  f"parse the clue again and write a new `wp`; the check refuses "
                                  f"a tree with that fault, the old one included"
                               for c, r in flagged.items()}
        keep = keep_words(puzzle, only)
        if keep:
            view["keepWords"] = keep
    drafts = hidden_drafts(puzzle, only)
    if drafts:
        view["draftAnnotations"] = drafts
    leaders = groups.leader_of(puzzle["entries"])
    printed = provenance.printed_answers(puzzle)
    model = ({entry_id(e) for e in puzzle["entries"] if entry_id(e) not in printed}
             if provenance.solution_origin_from_file(puzzle) == "model" else set())
    view["entries"] = [view_line(e, leaders, model) for e in puzzle["entries"]]
    # Each further answer a light starts (alsoLeads) is its own line, keyed
    # "22-across/2": annotate it under that key.
    for cid, i, k, _ in groups.also_clues(puzzle["entries"]):
        line = view_line(groups.as_leader(puzzle, i, k)["entries"][i], leaders, model)
        view["entries"].insert(view["entries"].index(view_line(puzzle["entries"][i], leaders, model)) + 1 + k,
                               cid + line[len(entry_id(puzzle["entries"][i])):])
    # Each clue entered off the grid (offGrid) is its own line, "1-offgrid".
    view["entries"] += [view_line(groups.as_entry(puzzle, cid), leaders) for cid, _ in groups.off_grid(puzzle)]
    # A (MODEL) answer may be corrected only to one its crossings agree with.
    if model:
        grid = grid_rows(puzzle)
        if grid:
            view["grid"] = grid
    # Only annotations of lights linked (same group) to one being written are
    # context worth sending; the rest were ~90% of a tail run's puzzle read and
    # nothing in the check or apply path reads them back from the view.
    linked_ids = set()
    for e in puzzle["entries"]:
        eid = entry_id(e)
        members = set(e.get("group") or ()) | ({eid, leaders[eid]} if eid in leaders else set())
        if members and (members | {eid}) & set(only or ()):
            linked_ids |= members | {eid}
    kept = {entry_id(e): in_notation(e["annotation"], e, puzzle) for e in puzzle["entries"]
            if e.get("annotation") and only is not None and entry_id(e) not in only
            and entry_id(e) in linked_ids}
    kept.update({cid: in_notation(item["annotation"], groups.as_leader(puzzle, i, k)["entries"][i], puzzle)
                 for cid, i, k, item in groups.also_clues(puzzle["entries"])
                 if item.get("annotation") and only is not None and cid not in only
                 and entry_id(puzzle["entries"][i]) in linked_ids})
    if kept:
        view["existingAnnotations"] = kept
    scan = scan_path(puzzle)
    if scan:
        view["scan"] = f"{scan.relative_to(ROOT)}: the page these clues were OCR'd from"
    view_path(path).write_text(json.dumps(view, indent=1, ensure_ascii=False) + "\n",
                               encoding="utf-8")
    return view_path(path)


def stuck_allowance(total):
    """How few nulls count as the last few: everything else is done."""
    return max(3, total // 10)


def notes(puzzle, only=None):
    """Things worth knowing at this point in the run that are not failures.

    Each is said here rather than in tools/annotate_prompt.md because it only
    matters in the state that triggers it, and a rule in the prompt is paid for
    on every run whether or not it is about to matter.

    The blog lookup in particular is disclosed only once every clue but the
    last few is done. Stated up front as "look it up last", every trial run
    looked it up first, and a blog read before the clue is attempted replaces
    the solve rather than rescuing it.
    """
    out = []
    # Advice about annotations this run may not change (`only`) is no use to it.
    mine = [e for e in annotation.view_puzzle(puzzle)["entries"]
            if only is None or entry_id(e) in only]
    cds = [entry_id(e) for e in mine
           if (e.get("annotation") or {}).get("type") == ["cryptic_definition"]]
    if cds:
        out.append(
            f"{', '.join(cds)} typed `cryptic definition`: the one type with no "
            f"checkable wordplay, and the one an unparsed clue can hide in. Hunt for "
            f"the charade or container first (\"Periods on horseback where British "
            f"king into himself?\" reads as a whole-clue definition of CHUKKAS and is "
            f"CHAS around UK + K); keep the type only if the clue has no wordplay.")
    likely = [entry_id(e) for e in mine
              if e.get("solutionConfidence") == "LIKELY" and e.get("annotation")]
    if likely:
        out.append(
            f"{', '.join(likely)} have LIKELY letters: a model filled them from the "
            f"definition and crossings and their wordplay did not parse, and no "
            f"official key will ever correct them. Keep an annotation only if you "
            f"derived the whole answer from the clue yourself; otherwise set it to "
            f"null, because the site would present an invented parse as fact.")
    left = unsolved(puzzle)
    blog = blog_of(puzzle)
    if (left and blog and not is_blind(puzzle)
            and len(left) <= stuck_allowance(len(puzzle["entries"]))):
        host, words = blog
        how = (f"`python3 tools/blog_post.py {puzzle['id']}` prints its cached post and comments"
               if blog_post.find(puzzle["id"]) else
               f"WebSearch `{words}`, then WebFetch the post and its comments")
        out.append(
            f"Stuck on {', '.join(entry_id(e) for e in left)}? {host} blogs this puzzle "
            f"clue by clue: {how} (the comments often have what the blogger missed). "
            f"Take only the mechanism and write every field yourself in this file's "
            f"voice; if the blog does not settle it either, the clue stays null.")
    return out


_DECODER = json.JSONDecoder()


def _ws(text, i):
    while i < len(text) and text[i] in " \t\r\n":
        i += 1
    return i


def _node(text, i):
    """(start, end, members) of the JSON value at text[i]: members is
    [(key or index, key start, child node)] for a container, None
    for a scalar. Raises ValueError on anything that is not JSON."""
    i = _ws(text, i)
    if i >= len(text) or text[i] not in "{[":
        _, end = _DECODER.raw_decode(text, i)
        return i, end, None
    close, members, j = "}" if text[i] == "{" else "]", [], _ws(text, i + 1)
    if text[j:j + 1] == close:
        return i, j + 1, members
    while True:
        k0 = j
        if close == "}":
            key, j = _DECODER.raw_decode(text, j)
            j = _ws(text, j)
            if text[j:j + 1] != ":":
                raise ValueError(f"no colon at {j}")
        else:
            key, j = len(members), j - 1
        child = _node(text, j + 1)
        members.append((key, k0, child))
        j = _ws(text, child[1])
        if text[j:j + 1] == close:
            return i, j + 1, members
        if text[j:j + 1] != ",":
            raise ValueError(f"no comma at {j}")
        j = _ws(text, j + 1)


def _same(a, b):
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def _splice(text, node, new):
    """`new` written in the layout of the value `node` spans in `text`: every
    part `new` shares with it keeps its own characters, and only what changed
    is written afresh, on one line."""
    start, end, members = node
    if _same(json.loads(text[start:end]), new):
        return text[start:end]
    is_obj = isinstance(new, dict)
    if not members or is_obj != (text[start] == "{") or not isinstance(new, (dict, list)):
        return json.dumps(new, ensure_ascii=False)
    keys = list(new) if is_obj else range(len(new))
    old = {m[0]: (n, m) for n, m in enumerate(members)}
    seps = [text[members[n - 1][2][1]:members[n][1]] for n in range(1, len(members))]
    sep = seps[-1] if seps else ", "
    out = [text[start:members[0][1]]]
    for n, key in enumerate(keys):
        if key in old:
            k, (_, k0, child) = old[key]
            if n:
                out.append(seps[k - 1] if k else sep)
            out.append(text[k0:child[0]] + _splice(text, child, new[key]))
        else:
            out.append((sep if n else "")
                       + (json.dumps(key, ensure_ascii=False) + ": " if is_obj else "")
                       + json.dumps(new[key], ensure_ascii=False))
    out.append(text[members[-1][2][1]:end])
    return "".join(out)


def write_pending(pending, ann):
    """Write `ann` over `pending` keeping the run's own layout.

    The run edits the _ann file with string replacements of text it wrote;
    re-dumping the whole file in another layout after a fix-up here made its
    next replacement miss, a wasted turn in one run of eight. So only the
    values that changed are rewritten, and everything else stays byte for byte."""
    try:
        text = pending.read_text(encoding="utf-8")
        node = _node(text, 0)
        if text[_ws(text, node[1]):]:
            raise ValueError("trailing text")
        body = text[:node[0]] + _splice(text, node, ann) + text[node[1]:]
    except (OSError, ValueError):
        body = json.dumps(ann, ensure_ascii=False, indent=2) + "\n"
    pending.write_text(body, encoding="utf-8")


def patch(pending, fix):
    """Merge `fix`, {entry: {field: value or null}}, into `pending`; what is
    wrong, or None."""
    if fix is None or not fix.exists():
        return f"--patch needs a file of {{entry: {{field: value}}}}; got {fix}"
    if not pending.exists():
        return f"no {pending.name} to patch: edit the puzzle file directly"
    try:
        ann, changes = json.loads(pending.read_text(encoding="utf-8")), json.loads(fix.read_text(encoding="utf-8"))
    except ValueError as e:
        return f"not valid JSON: {e}"
    unknown = sorted(set(changes) - set(ann))
    if unknown:
        return f"{fix.name} names entries {pending.name} lacks: {', '.join(unknown)} (keys look like {next(iter(ann), '1-across')!r})"
    for eid, fields in changes.items():
        if not isinstance(fields, dict):     # a whole annotation, or null
            ann[eid] = fields
            continue
        ann[eid] = ann[eid] or {}
        for k, v in fields.items():
            if v is None:
                ann[eid].pop(k, None)
            elif k == "notes" and isinstance(v, dict) and isinstance(ann[eid].get(k), dict):
                # One note is the usual fix: notes merge key by key, null removing one.
                merged = {**ann[eid][k], **v}
                ann[eid][k] = {n: t for n, t in merged.items() if t is not None}
            else:
                ann[eid][k] = v
    write_pending(pending, ann)
    fix.unlink()
    return None


DATA = TOOLS / "data"
# _ann field -> (table it is filed in, what it must hold, an example). A row is
# keyed "<ID>/<entry id>"; printedClue's row opens with the clue as shown,
# answerTypo's with the letters the paper printed.
FILED = {
    "printedClue": ("source_clue_wrong", '["<clue as printed, no count>", "<evidence>"]',
                    '["Fudge the issue", "OCR misread: the anagram needs fudge"]'),
    "setterError": ("setter_error", '["<fodder words as printed>", "<letters the anagram should give>", "<evidence>"]',
                    '["skis Elf oil", "KISSOFLIFE", "the page prints Elf oil: one F short, one L over"]'),
    "answerTypo": ("source_answer_wrong", '["<letters the wordplay builds>", "<evidence>"]',
                   '["MINUSCULE", "NUS + CU in MILE; the grid prints MINISCULE, which the wordplay cannot give"]'),
    # Ours checked against a blog's reading and kept (validate_annotations.BLOG_DISAGREE).
    "blogDisagree": ("blog_disagree", '["<definition|type|blocks, comma separated>", "<why ours stands>"]',
                     '["definition", "the blog underlines Drink, which is the wordplay\'s DRAG; the definition is painter"]'),
}
# A key's misprint is a slipped letter or two; more is a different answer.
TYPO_LETTERS = 2


def answer_typo_problems(puzzle, eid, corrected, served, fixes):
    """What stops `served` at `eid` being filed as the paper's misprint of
    `corrected`, with `fixes` ({entry id: letters}) the batch's corrections."""
    entry = {entry_id(e): e for e in puzzle["entries"]}[eid]
    if not served:
        return ["names an answer the paper never printed: a model's fill is "
                "corrected through `answer`"]
    if len(served) != entry.get("length"):
        return [f"the printed {served} spans more than its light: file it by hand"]
    if len(corrected) != len(served):
        return [f"{corrected} is {len(corrected)} letters; the printed {served} is {len(served)}"]
    changed = [i for i, (a, b) in enumerate(zip(served, corrected, strict=True)) if a != b]
    if not changed:
        return [f"{corrected} is what the grid already holds"]
    if len(changed) > TYPO_LETTERS:
        return [(f"{corrected} changes {len(changed)} letters of the printed {served}; a "
                 f"misprint is at most {TYPO_LETTERS}, so re-read the wordplay")]
    grid = {}
    for e in puzzle["entries"]:
        word = fixes.get(entry_id(e)) or letters(e.get("solution"))
        if entry_id(e) != eid and len(word) == e.get("length"):
            for cell, ch in zip(corroborate.cells(e), word, strict=True):
                grid.setdefault(cell, []).append((entry_id(e), ch))
    mine = corroborate.cells(entry)
    return [f"its letter {i + 1} becomes {corrected[i]}, but crossing {other} has {ch} there"
            for i in changed for other, ch in grid.get(mine[i], ()) if ch != corrected[i]]


def file_rows(path, pending, data=DATA):
    """Move each entry's `printedClue`, `setterError` and `answerTypo` in `pending` into
    their tables (FILED); returns (["<field> <entry id>" filed], what is wrong
    or None).

    printedClue's row is [clue as shown, clue as printed, evidence], and
    answerTypo's [answer printed, letters corrected, evidence]. What was shown
    or printed is the row's own when the key is already filed, so a re-run does
    not record the mended text as what the source served. An answerTypo's
    letters go into the puzzle file's grid."""
    try:
        ann = json.loads(pending.read_text(encoding="utf-8"))
    except ValueError:
        return [], None
    if not isinstance(ann, dict):
        return [], None
    wants = [(field, eid, a[field]) for field in FILED for eid, a in ann.items()
             if isinstance(a, dict) and field in a]
    if not wants:
        return [], None
    for field, eid, v in wants:
        width = FILED[field][1].count('"<')
        if not (isinstance(v, list) and len(v) == width
                and all(isinstance(x, str) and x.strip() for x in v)):
            return [], (f"{eid}: {field} must be {FILED[field][1]}, "
                        f"e.g. {FILED[field][2]}; it is {json.dumps(v, ensure_ascii=False)}")
    puzzle = read_puzzle_file(path)
    by_id = {entry_id(e): e for e in puzzle["entries"]}
    unknown = sorted({eid for _, eid, _ in wants} - set(by_id))
    if unknown:
        return [], f"{', '.join(unknown)}: not an entry of {puzzle['id']}, so nothing to file"
    answer_rows = json.loads((data / "source_answer_wrong.json").read_text(encoding="utf-8"))
    clue_rows = json.loads((data / "source_clue_wrong.json").read_text(encoding="utf-8"))
    printed = provenance.printed_answers(puzzle)
    fixes = {eid: letters(v[0]) for field, eid, v in wants if field == "answerTypo"}
    served = {}
    for field, eid, v in wants:
        if field == "blogDisagree":
            problems = [f"names {f!r}; the fields are {', '.join(validate_annotations.BLOG_FIELDS)}"
                        for f in (x.strip() for x in v[0].split(","))
                        if f not in validate_annotations.BLOG_FIELDS]
        elif field == "setterError":
            problems = validate_annotations.setter_error_problems(puzzle, eid, v, ann[eid])
        elif field == "answerTypo":
            key = f"{puzzle['id']}/{eid}"
            served[eid] = (answer_rows[key][0] if key in answer_rows
                           else letters(printed.get(eid)))
            problems = answer_typo_problems(puzzle, eid, fixes[eid], served[eid], fixes)
        elif field == "printedClue":
            key = f"{puzzle['id']}/{eid}"
            held = clue_rows.get(key)
            shown = held[0] if held else (by_id[eid]["clue"].get("text") or "")
            problems = validate_annotations.clue_row_problems(
                "" if validate_annotations.is_blank_clue(shown) else shown, v[0], v[1])
            # A fixed clue is the words the file holds: a stray digit still
            # glued to a short word ("2as") is a scan speck left in.
            glued = re.search(r"\b\d(?:as|so|in|on|to|of|or|an|at|is|it|be|by|he|me|we)\b", v[0])
            if glued:
                problems.append(f"still has the scan speck {glued.group(0)!r} glued to a word: "
                                f"the fixed clue must read as the clue's own words")
            # The corpus check's rule, held at filing: an OCR'd clue's row
            # mends a misread, never rewords the clue, unless read off the scan.
            V = validate_annotations
            if ((puzzle.get("source") or {}).get("retrievedFrom") in provenance.OCR_CHANNELS
                    and not v[1].startswith(V.SCAN_READ)
                    and V.ocr_misread_edits(shown, v[0]) > V.OCR_MISREAD_EDITS):
                problems.append(
                    f"changes more than {V.OCR_MISREAD_EDITS} letters of the OCR's {shown!r}: "
                    f"a misread is a letter or two (judge for fudge), not a reword; leave "
                    f"the entry null unless the scan (tools/scan_crop.py) shows the clue "
                    f"and the evidence opens {V.SCAN_READ!r}")
        else:
            continue
        if problems:
            return [], f"{eid}: {field} " + "; ".join(problems)
    tables = {}
    for field, eid, v in wants:
        name = FILED[field][0]
        rows = tables.setdefault(name, json.loads((data / f"{name}.json").read_text(encoding="utf-8")))
        key = f"{puzzle['id']}/{eid}"
        row = [x.strip() for x in v]
        if field == "printedClue":
            shown = rows[key][0] if key in rows else (by_id[eid]["clue"].get("text") or "")
            row = ["" if validate_annotations.is_blank_clue(shown) else shown] + row
            fetch_puzzle.SOURCE_CLUE_WRONG[(puzzle["id"], eid)] = tuple(row)
        elif field == "answerTypo":
            row = [served[eid], fixes[eid], row[1]]
            fetch_puzzle.SOURCE_ANSWER_WRONG[(puzzle["id"], eid)] = tuple(row)
            by_id[eid]["solution"] = fixes[eid]
        elif field == "blogDisagree":
            row[0] = ",".join(x.strip() for x in row[0].split(","))
            validate_annotations.BLOG_DISAGREE[(puzzle["id"], eid)] = tuple(row)
        else:
            validate_annotations.SETTER_ERROR[(puzzle["id"], eid)] = tuple(row)
        rows[key] = row
        del ann[eid][field]
    for name, rows in tables.items():
        (data / f"{name}.json").write_text(dump_lines(rows), encoding="utf-8")
    if fixes:
        fetch_puzzle.write_puzzle_file(path, puzzle)
    write_pending(pending, ann)
    return [f"{field} {eid}" for field, eid, _ in wants], None


def fill_missing(path, pending):
    """Write null into `pending` for every entry it has no key for; the ids filled.

    A missing key and a null mean the same thing to the run (not done yet), and
    refusing the whole file over it costs a turn to type nulls."""
    try:
        ann = json.loads(pending.read_text(encoding="utf-8"))
    except ValueError:
        return []
    if not isinstance(ann, dict):
        return []
    puzzle = read_puzzle_file(path)
    entries = puzzle["entries"]
    continuations = groups.leader_of(entries)
    only = annotate_only(path)
    missing = [entry_id(e) for e in entries
               if entry_id(e) not in continuations and entry_id(e) not in ann
               and (only is None or entry_id(e) in only)]
    missing += [cid for cid, _, _, _ in groups.also_clues(entries)
                if cid not in ann and (only is None or cid in only)]
    missing += [cid for cid, _ in groups.off_grid(puzzle)
                if cid not in ann and (only is None or cid in only)]
    if missing:
        ann.update(dict.fromkeys(missing))
        write_pending(pending, ann)
    return missing


def respell_answers(pending):
    """Rewrite each `answer` typed with the enumeration's commas ("TITUS,
    ANDRONICUS") in display form, spaced; the entry ids changed.

    The comma is the enumeration's word break, and the letter strip counts it
    as a square; the separator check then fails on a fix no judgement goes into."""
    try:
        ann = json.loads(pending.read_text(encoding="utf-8"))
    except ValueError:
        return []
    changed = []
    for eid, a in (ann.items() if isinstance(ann, dict) else ()):
        if isinstance(a, dict) and isinstance(a.get("answer"), str) and "," in a["answer"]:
            a["answer"] = re.sub(r"\s*,\s*", " ", a["answer"]).strip()
            changed.append(eid)
    if changed:
        write_pending(pending, ann)
    return changed


def seen_as(a, entry, entries):
    """The model-shape clue `a` as the checks read it: translated
    (apply_annotations.normalize) and viewed (annotation.view)."""
    stored = normalize(a, entry, entries)
    here = {**entry, "alteration": stored["alteration"]} if "alteration" in stored else entry
    return annotation.view(stored, here, {"entries": entries})


def drop_derived_keys(pending):
    """Remove the keys view() derives (`assembly`, `type`, `blocks`, `indicators`,
    `linkWords`, and `definitions` beside a `def`) from each clue written in the
    model's shape; the entry ids changed.
    The validator's "Give `assembly.pieces`" warning invites a run to write them,
    and from_model refuses the whole file over "unknown key assembly" (658
    mentions in 48h): the key is derived from `wp`, so dropping it loses nothing
    and saves the turn."""
    try:
        ann = json.loads(pending.read_text(encoding="utf-8"))
    except ValueError:
        return []
    changed = []
    for eid, a in (ann.items() if isinstance(ann, dict) else ()):
        if not (isinstance(a, dict) and "wp" in a and annotation.is_model(a)):
            continue
        # Stored-shape keys a run copies from the validator's own wording
        # ("or the op is not in the clue" -> noIndicator; "spelling" is `answer`
        # here; `andLit: false` is the key left out): "unknown key noIndicator"
        # was 27 refusals, "spelling" 4, "andLit: false" 5, "wordplay" 3 in the
        # 10-15..17 window. The model shape cannot say the first and last
        # two, so dropping them loses nothing; `spelling` is renamed.
        if "spelling" in a and "answer" not in a and isinstance(a["spelling"], str):
            a["answer"] = a.pop("spelling")
            changed.append(eid)
        for k in annotation.DERIVED_KEYS + ("noIndicator", "spelling", "wordplay"):
            if k in a and (k != "definitions" or "def" in a):
                del a[k]
                if eid not in changed:
                    changed.append(eid)
        if a.get("andLit") is False:
            del a["andLit"]
            if eid not in changed:
                changed.append(eid)
    if changed:
        write_pending(pending, ann)
    return changed


def unname_block_notes(path, pending):
    """Rewrite each block note that names its answer, where find_answer_leaks.unname
    can do it without judgement, or else blank the answer's words in the note
    ("..."); the entry ids changed.
    check_block_notes_dont_name_the_answer is the commonest rejection, and each
    one it sends back costs a turn."""
    try:
        ann = json.loads(pending.read_text(encoding="utf-8"))
        entries = read_puzzle_file(path)["entries"]
    except (ValueError, OSError, KeyError):
        return []
    clues = {entry_id(e): (e.get("clue") or {}).get("text") or "" for e in entries
             if isinstance(e.get("clue"), dict)}
    by_id = {entry_id(e): e for e in entries}
    changed = []
    for eid, a in (ann.items() if isinstance(ann, dict) else ()):
        if annotation.is_model(a) and isinstance(a.get("notes"), dict) and eid in by_id:
            # The model's notes are its blocks' notes: read each against the
            # block it becomes (the view), rewrite it in `notes`.
            try:
                seen = seen_as(a, by_id[eid], entries)
            except (ValueError, KeyError, TypeError):
                continue
            lights = light_solutions(by_id[eid], by_id)
            pieces = pieces_of(seen)
            for key, note in list(a["notes"].items()):
                if not isinstance(note, str):
                    continue
                # A block's note is the run's note, or one that leads with more (a
                # rebus's reading, "XC; part of the word excessive is XC ...", a
                # sounded charade's joined leaf notes) and holds it.
                blocks = seen.get("blocks") or []
                block = next((b for b in blocks if b.get("note") == note), None) \
                    or next((b for b in blocks if note in str(b.get("note"))), None)
                if block is None:
                    continue
                # Rewriting for one name can leave another ("William Tell ... Will
                # Tell": TELL then WILL), so go round until no name is left.
                for _ in range(3):
                    again = False
                    for name in names(seen["answer"], lights):
                        gives = block.get("gives") if name == seen["answer"] else ""
                        # What no rule clears is blanked ("...") rather than sent back:
                        # 10-24, 8 of 8 refusals were quotes or fragments (apron strings,
                        # 'P and A') the model would only have written the same way
                        # with a word taken out, at a turn each.
                        new = unname(note, name, gives, clues.get(eid, ""), pieces,
                                     blank=True)
                        if new:
                            a["notes"][key] = note = new
                            changed.append(eid)
                            again = True
                    if not again:
                        break
    if changed:
        write_pending(pending, ann)
    return sorted(set(changed), key=changed.index)


BLANK_LINE = re.compile(r"^(\d+[AD](?:,\d+[AD])*): no annotation\. Every clue")


def drop_refused_blanks(line, refused):
    """`line` without the clues in `refused`, or "" if none is left.

    A clue the write refused is still blank in the previewed puzzle, so
    check_every_clue_is_annotated called it unwritten as well, though the run
    wrote it and the refusal above names it with the real reason. That echo
    was 56 of the 80 sessions the 10-14 audit counted as missing a clue
    (38% of first-check failures): runs went looking for a clue they had
    written. Only a clue absent from the _ann file is reported here now."""
    m = BLANK_LINE.match(line)
    if not m or not refused:
        return line
    tags = m.group(1).split(",")
    left = [t for t in tags if t not in refused]
    if not left:
        return ""
    line = ",".join(left) + line[m.end(1):]
    return re.sub(r"With \d+ blank", f"With {len(left)} blank", line) if len(left) > 1 else \
        re.sub(r" With \d+ blank, write every one before running the check again: "
               r"a check of a half-written file costs a turn\.", "", line)


def preview(path, pending):
    """(errors, warnings) the validator would give once `pending` applied.

    When the write is refused, the refusal is only the schema's half of what is
    wrong; without this the rest arrives one turn later, after the refusal is
    fixed. Best effort: an annotation too broken to validate yields nothing."""
    try:
        puzzle = read_puzzle_file(path)
        ann = json.loads(pending.read_text(encoding="utf-8"))
        continuations = groups.leader_of(puzzle["entries"])
        only = annotate_only(path)
        refused = set()
        for e in puzzle["entries"]:
            if entry_id(e) in continuations or (only is not None and entry_id(e) not in ann):
                continue
            if ann.get(entry_id(e)) is None:
                e.pop("annotation", None)
            else:
                # A clue whose wordplay does not check is named by the refusal;
                # the rest are still worth validating.
                new = apply_annotations.landed(ann[entry_id(e)], e, puzzle["entries"], "", [])
                if new is None:
                    refused.add(f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}")
                    continue
                e["annotation"] = new
                move_alteration(e)
        apply_also(puzzle, ann, [])
        try:
            definitions.place_puzzle(puzzle)
        except ValueError as err:
            return [str(err)], []
        with contextlib.redirect_stdout(io.StringIO()):
            _, errors, warnings = validate_annotations.validate_puzzle(puzzle)
        # The refusal above already names the schema's findings by entry id.
        errors = [drop_refused_blanks(e, refused) for e in errors if not e.startswith("schema:")]
        return [e for e in errors if e], warnings
    except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError):
        # An annotation too malformed to validate: the refusal itself still shows.
        return [], []


NO_NOTE_RE = re.compile(
    r"^\s*(?:ERROR|warn):\s*(\d+)([AD]): block ('(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\") "
    r"> '(\w+)' " + re.escape(validate_annotations.BLOCK_NO_NOTE))


def note_skeleton(report):
    """One --patch file naming every block the report says has no note, so the
    commonest first-check failure (a leaf with letters and no note, in over half
    of all runs) is one Write and one command rather than a fix per clue."""
    import ast
    notes = {}
    for line in report.splitlines():
        m = NO_NOTE_RE.match(line)
        if not m:
            continue
        num, d, frag, gives = m.groups()
        try:
            frag = ast.literal_eval(frag)
        except (ValueError, SyntaxError):
            continue
        key = f"{num}-{'across' if d == 'A' else 'down'}"
        notes.setdefault(key, {"notes": {}})["notes"][frag] = f"<why {frag!r} gives {gives}>"
    return json.dumps(notes, indent=1, ensure_ascii=False) if notes else ""


def name_checks(report):
    """`report` with each validator line ending in the check that wrote it.

    Without the name, a run wanting `--explain` guesses one from the message's
    words (`definition-overlap`) and is refused, a turn each time."""
    templates = load_templates(Path(validate_annotations.__file__).read_text(encoding="utf-8"))
    out = []
    for line in report.splitlines():
        if line.startswith((validate_annotations.ERROR_PREFIX, validate_annotations.WARN_PREFIX)):
            name = rule_name(re.sub(r"^\s*(ERROR|warn):\s*", "", line), templates)
            if name.startswith("check_"):
                line += f" [{name}]"
        out.append(line)
    return "\n".join(out)


def misread(path):
    """([(entry id, printed clue)] as HEAD has the puzzle (the source's
    reading), [what met a misread]) for the puzzle at `path`: "printedClue"
    for a source_clue_wrong.json row HEAD lacks, and each misread check that
    fails: check_clue_unchanged (the run rewrote the clue to fit its parse) and
    check_anagram_letters (the clue's fodder cannot give the answer's letters),
    and "lostClue" for an entry the run left null (a clue it could not parse,
    which on a scan is most often a garbled reading)."""
    puzzle = read_puzzle_file(path)
    pid = puzzle["id"]
    committed = validate_annotations.committed_entries(path)
    entries = committed if committed is not None else {entry_id(e): e for e in puzzle["entries"]}
    import enumeration
    clues = [(eid, enumeration.printed(e["clue"])) for eid, e in entries.items()]
    why = []
    rows = json.loads((DATA / "source_clue_wrong.json").read_text(encoding="utf-8"))
    head = subprocess.run(["git", "show", "HEAD:tools/data/source_clue_wrong.json"], cwd=ROOT,
                          capture_output=True, text=True, check=False)
    held = json.loads(head.stdout) if head.returncode == 0 else {}
    if any(k.split("/", 1)[0] == pid and held.get(k) != v for k, v in rows.items()):
        why.append("printedClue")
    errors = []
    validate_annotations.check_clue_unchanged(puzzle, path, errors)
    if errors:
        why.append("check_clue_unchanged")
    # A tree whose anagram fodder cannot give its letters fails the
    # evaluator, so view_puzzle leaves its annotation out: its problem is the
    # misread check_anagram_letters names.
    problems = []
    viewed = annotation.view_puzzle(puzzle, problems)
    failed = {where for where, _ in problems}

    def has_anagram(node):
        return node.get("op") == "anagram" or any(has_anagram(p) for p in wordplay.parts_of(node))
    if any(where in failed and has_anagram(ann.get("wordplay") or {})
           for where, _, ann in puzzle_schema.annotations(puzzle)):
        why.append("check_anagram_letters")
    for e in [] if "check_anagram_letters" in why else viewed["entries"]:
        errors = []
        if e.get("annotation"):
            tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
            validate_annotations.check_anagram_letters(pid, entry_id(e), tag, e["annotation"], errors)
        if errors:
            why.append("check_anagram_letters")
            break
    if any("annotation" in e and e["annotation"] is None for e in puzzle["entries"]):
        why.append("lostClue")
    return clues, why


def reread(pid):
    """Queue an OCR re-read of `pid`'s source when its run met a misread;
    0 when one was queued."""
    import scan_queue
    path = resolve_puzzle(pid)
    clues, why = misread(path)
    req = why and scan_queue.request_reread(read_puzzle_file(path), clues, why)
    if not req:
        return 1
    print(f"{pid}: queued an OCR re-read of {req['filer']} {req['source']} ({', '.join(req['why'])})")
    return 0


def withdrawn_path(path):
    """The marker a withdrawn run leaves for the harness (tools/puzzle_worker.sh)."""
    return default_input(path).with_name(f"_withdrawn_{path.stem}.txt")


def withdraw(path, why):
    """Mark this run's work on puzzle `path` as taken back: the harness puts
    the puzzle file back as committed and ships nothing the run wrote."""
    withdrawn_path(path).write_text((why.strip() or "no reason given") + "\n")
    shown = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    print(f"withdrawn: when this run ends, {shown} is put back as committed and "
          f"nothing this run wrote ships. Do not edit it or run git. Stop now: end "
          f"with your final line naming the entries that beat you.")
    return 0


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    if argv[0] == "--reread":
        return reread(argv[1])
    if argv[0] == "--nothing-due":  # exit 0: hinted, nothing missing, nothing listed
        try:
            return 0 if nothing_due(read_puzzle_file(resolve_puzzle(argv[1]))) else 1
        except (SystemExit, OSError, ValueError, KeyError):
            return 1
    if argv[0] == "--view":
        print(write_view(resolve_puzzle(argv[1])).relative_to(ROOT))
        # `python3 -c` over this file failed in ~100 runs a window: `entries` is a
        # list of STRINGS (d['entries'][0].get raises), and before this command ran
        # the file did not exist. Say both once, where the path is handed out.
        # (stderr: daily_update.sh captures stdout as the path)
        print("(JSON: `entries` is a list of strings '1-across | group | ANSWER | clue (enum)', "
              "not objects: Read the file, no script needed. The full puzzle is "
              "puzzles/<series>/<year>/<id>.json, whose entries have `number` and "
              "`direction`, no `id`.)", file=sys.stderr)
        return 0
    if argv[1:2] == ["--withdraw"]:
        return withdraw(resolve_puzzle(argv[0]), " ".join(argv[2:]))
    by = []
    if "--partial" in argv:   # a bag run: write the clues that pass, report the rest
        argv.remove("--partial")
        by = ["--partial"]
    if "--by" in argv:
        at = argv.index("--by")
        by += argv[at:at + 2]
        del argv[at:at + 2]
    path = resolve_puzzle(argv[0])
    stem = path.stem
    shown = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    pending = default_input(path)
    issues = []
    patched = None
    if argv[1:2] == ["--patch"]:
        err = patch(pending, Path(argv[2]) if len(argv) > 2 else None)
        if err:
            print(f"annotate_check {stem}: STOPPED — {err}")
            return 2
        patched = Path(argv[2]).name
        print(f"merged {patched} into {pending.name} and deleted it\n")

    if pending.exists():
        filed, err = file_rows(path, pending)
        if err:
            print(f"annotate_check {stem}: STOPPED — {err}")
            return 2
        if filed:
            print(f"filed in tools/data/ and taken off {pending.name}: "
                  f"{', '.join(filed)}\n")
        spaced = respell_answers(pending)
        if spaced:
            print(f"answers written with commas, now spaced in {pending.name}: "
                  f"{', '.join(spaced)}\n")
        derived = drop_derived_keys(pending)
        if derived:
            print(f"keys worked out from `wp` (assembly, type, blocks, ...), dropped "
                  f"from {pending.name}: {', '.join(derived)}\n")
        unnamed = unname_block_notes(path, pending)
        if unnamed:
            print(f"block notes that named the answer, rewritten without it in "
                  f"{pending.name}: {', '.join(unnamed)}\n")
        filled = fill_missing(path, pending)
        if filled:
            print(f"{pending.name} had no key for {', '.join(filled)}: filled in as null "
                  f"(not done yet)\n")
        rc, out = run([sys.executable, str(TOOLS / "apply_annotations.py"),
                       stem, str(pending), "--no-validate", *by])
        print(out)
        if rc:
            # Nothing downstream is about this puzzle if the annotations never
            # landed in it, and reporting the old file's state as this run's
            # would be a lie in the direction of "fine".
            errs, warns = preview(path, pending)
            if errs or warns:
                print("\nwhat the validator says about the same annotations, so both "
                      "lists are fixed in one edit:")
                print(name_checks("\n".join(
                    [f"{validate_annotations.WARN_PREFIX}{w}" for w in warns]
                    + [f"{validate_annotations.ERROR_PREFIX}{e}" for e in errs])))
            print(f"\nannotate_check {stem}: STOPPED — the annotations were not "
                  f"applied, so {shown} is unchanged. Fix everything above in "
                  f"{pending.name} in one edit and re-run.")
            return 2
    else:
        print(f"no {pending.name}, so nothing to apply — checking "
              f"{shown} as it stands")

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        vrc = validate_annotations.main([stem])
    vout = buf.getvalue().rstrip()
    print("\n" + name_checks(vout))
    errors = sum(l.startswith(validate_annotations.ERROR_PREFIX)
                 for l in vout.splitlines())
    warns = sum(l.startswith(validate_annotations.WARN_PREFIX)
                for l in vout.splitlines())

    skeleton = note_skeleton(vout)
    if skeleton:
        print("\nthe missing block notes as one --patch file (fill each \"<why ...>\" "
              "with the sentence, Write it, add `--patch <file>`):")
        print(skeleton)

    found = list(leaks([stem]))
    if found:
        print("\nblock notes that say the answer out loud "
              "(the walkthrough is the reveal, not the blocks):")
        for f in found:
            print(f"  {f['entry']} ({f['answer']}, {clue_types.labels(f['type'])})")
            for n in f["notes"]:
                print(f"      {n['clueFragment']}: {n['note']}")
        issues.append(f"{sum(len(f['notes']) for f in found)} answer leak(s)")

    rows = [r for r in scan(path) if r[0] == 0]
    if rows:
        print("\nwalkthroughs that only re-narrate their own blocks "
              "(say what the blocks CANNOT show):")
        for _, _, cid, answer, hits, walk in rows:
            print(f"  {cid} {answer} names {', '.join(hits)}\n      {walk}")
        issues.append(f"{len(rows)} re-narrated walkthrough(s)")

    # The puzzle is JSON; the .js shim is build output, so the file that has
    # to parse is this one, and json does it without shelling out to node.
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except ValueError as err:
        print(f"\n{shown} is not valid JSON:\n{err}")
        issues.append("the file is not valid JSON")

    write_view(path)
    advice = notes(read_puzzle_file(path), annotate_only(path))
    if advice:
        print("\nworth knowing now (not failures):")
        for line in advice:
            print(f"  - {line}")

    # Warnings alone leave the annotations applied and valid. Runs that chased
    # them (nation-1621: 6 of 7 post-OK rounds on one advisory line; across 82
    # sessions 305 checks after the first no-ERROR report, most of them on the
    # cryptic-definition cap and "never shows the intermediate letters") are
    # told here that the run is over. Blog warnings are the exception: a blog
    # backfill is asked to clear exactly those.
    blog = any("_against_blog]" in l for l in vout.splitlines()
               if l.startswith(validate_annotations.WARN_PREFIX))
    advisory = bool(warns) and not errors and not issues and not blog
    counts = ([f"{errors} ERROR"] if errors else []) + \
             ([f"{warns} warn"] if warns else []) + issues
    print(f"\nannotate_check {stem}: " + (
        "applied, index refreshed, " + f"{warns} advisory warn — done" if advisory
        else ", ".join(counts) if counts else "clean, index refreshed — done"))
    if advisory:
        print("The annotations are applied and valid; the warns above are advisory "
              "and several (the cryptic-definition cap, 'never shows the "
              "intermediate letters') often cannot be satisfied honestly. Do not "
              "run this command again to chase them. If one fix is obvious and "
              "cheap, make it in the same single edit and do not re-check.")
    if not counts or advisory:
        # Otherwise a clean run spends its last turn trying to `rm` the patch
        # file, which needs an approval the run cannot give.
        print("Nothing to tidy up: --patch files are deleted when merged and "
              "tools/_* is ignored by git. The run is finished.")
        # Runs kept going after a clean check, re-reading and summarising,
        # ~3-4% of the burn's spend (10-08..12): said here, where they look.
        print(STOP_NOW)
    if counts and not advisory:
        # Two callers: the annotate run, which hands over tools/_ann_<ID>.json,
        # and the field backfills, which edit the puzzle in place. Naming a file
        # that is not there is an invitation to go looking for it.
        where = (f"tools/{pending.name}" if pending.exists()
                 else f"{shown}")
        via = (" (for many clues, Write {entry: {field: value}} to a file and add "
               "`--patch <file>` to this command)" if pending.exists() else "")
        print(f"Fix ALL of these in one edit of {where}{via}, then run "
              f"this command again. Re-running to confirm one fix at a time "
              f"costs a turn per warning and tells you nothing this run did not.")
        print("Any line you cannot act on: "
              "`python3 tools/validate_annotations.py --explain <the [check_name] "
              "after it>` prints that check's own source. Do not open the file itself.")
    return vrc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
