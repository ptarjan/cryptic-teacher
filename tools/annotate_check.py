#!/usr/bin/env python3
"""Everything that must be true of a puzzle's annotations, in one command.

    python3 tools/annotate_check.py cryptic-30098
    python3 tools/annotate_check.py --view cryptic-30098   # the run's input
    python3 tools/annotate_check.py cryptic-30098 --patch FILE

--patch merges FILE, {"8-down": {"definitionFit": "...", "blocks": [...]}},
into tools/_ann_<ID>.json first: each named field replaced, null removing it,
and deletes FILE. Many clues' fixes are one Write and this one command, not a
fix script, which these runs cannot get approved.

An entry the _ann file has no key for is filled in as null (not done yet), so
a file written a few clues at a time applies as it stands.

Applies tools/_ann_<ID>.json, validates, runs both audit tools, syntax-checks
the file and refreshes the index — and prints one report with a count at the
top and one instruction at the bottom.

It exists because of what the annotation runs actually cost. Cost tracks the
number of turns, and roughly as its square, since every turn resends the whole
transcript before it; it does not track the puzzle. Five commands after every
edit is five turns, and chaining them into one is worse, because a compound
command needs an approval these runs cannot give and aborts whole, having run
nothing. Worse still is the shape the transcripts showed: fix one warning,
re-run, read the next warning, fix that. One run already knows everything that
is wrong, so this says all of it at once and asks for one edit back.

Exit code is the validator's: 0 when the puzzle is publishable. Warnings and
audit hits are worth fixing and do not fail the build.
"""
import contextlib
import io
import json
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

import blog_post  # noqa: E402
import clue_types  # noqa: E402
import definitions  # noqa: E402
import groups  # noqa: E402
from groups import entry_id  # noqa: E402
import series  # noqa: E402
import validate_annotations  # noqa: E402
from apply_annotations import default_input  # noqa: E402
from fetch_puzzle import read_puzzle_file, resolve_puzzle  # noqa: E402
from find_answer_leaks import leaks  # noqa: E402
from find_renarration import scan  # noqa: E402


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
    s = puzzle.get("series")
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
    return [e for e in puzzle["entries"]
            if not e.get("annotation") and entry_id(e) not in misses
            and entry_id(e) not in continuations
            and not validate_annotations.is_blank_clue(e["clue"].get("text", ""))]


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
             "entries")


def view_path(path):
    """Beside the annotations file, ignored by git (`tools/_*`)."""
    return TOOLS / f"_puzzle_{path.stem}.json"


def write_view(path):
    """Write the annotate run's copy of the puzzle file, current as of now."""
    puzzle = read_puzzle_file(path)
    view = {k: puzzle[k] for k in VIEW_KEYS if k in puzzle}
    # The run keys its annotations by entry id, so the view spells each one out.
    view["entries"] = [{"id": entry_id(e), **e} for e in view["entries"]]
    view_path(path).write_text(json.dumps(view, indent=1, ensure_ascii=False) + "\n",
                               encoding="utf-8")
    return view_path(path)


def stuck_allowance(total):
    """How few nulls count as the last few: everything else is done."""
    return max(3, total // 10)


def notes(puzzle):
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
    cds = [entry_id(e) for e in puzzle["entries"]
           if (e.get("annotation") or {}).get("type") == ["cryptic_definition"]]
    if cds:
        out.append(
            f"{', '.join(cds)} typed `cryptic definition`: the one type with no "
            f"checkable wordplay, and the one an unparsed clue can hide in. Hunt for "
            f"the charade or container first (\"Periods on horseback where British "
            f"king into himself?\" reads as a whole-clue definition of CHUKKAS and is "
            f"CHAS around UK + K); keep the type only if the clue has no wordplay.")
    likely = [entry_id(e) for e in puzzle["entries"]
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
            else:
                ann[eid][k] = v
    pending.write_text(json.dumps(ann, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fix.unlink()
    return None


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
    entries = read_puzzle_file(path)["entries"]
    continuations = groups.leader_of(entries)
    missing = [entry_id(e) for e in entries
               if entry_id(e) not in continuations and entry_id(e) not in ann]
    if missing:
        ann.update(dict.fromkeys(missing))
        pending.write_text(json.dumps(ann, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return missing


def preview(path, pending):
    """(errors, warnings) the validator would give once `pending` applied.

    When the write is refused, the refusal is only the schema's half of what is
    wrong; without this the rest arrives one turn later, after the refusal is
    fixed. Best effort: an annotation too broken to validate yields nothing."""
    try:
        puzzle = read_puzzle_file(path)
        ann = json.loads(pending.read_text(encoding="utf-8"))
        continuations = groups.leader_of(puzzle["entries"])
        for e in puzzle["entries"]:
            if entry_id(e) in continuations:
                continue
            if ann.get(entry_id(e)) is None:
                e.pop("annotation", None)
            else:
                e["annotation"] = ann[entry_id(e)]
        try:
            definitions.place_puzzle(puzzle)
        except ValueError as err:
            return [str(err)], []
        with contextlib.redirect_stdout(io.StringIO()):
            _, errors, warnings = validate_annotations.validate_puzzle(puzzle)
        # The refusal above already names the schema's findings by entry id.
        return [e for e in errors if not e.startswith("schema:")], warnings
    except Exception:  # noqa: BLE001 — a preview never hides the refusal itself
        return [], []


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    if argv[0] == "--view":
        print(write_view(resolve_puzzle(argv[1])).relative_to(ROOT))
        return 0
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
        filled = fill_missing(path, pending)
        if filled:
            print(f"{pending.name} had no key for {', '.join(filled)}: filled in as null "
                  f"(not done yet)\n")
        rc, out = run([sys.executable, str(TOOLS / "apply_annotations.py"),
                       stem, str(pending), "--no-validate"])
        print(out)
        if rc:
            # Nothing downstream is about this puzzle if the annotations never
            # landed in it, and reporting the old file's state as this run's
            # would be a lie in the direction of "fine".
            errs, warns = preview(path, pending)
            if errs or warns:
                print("\nwhat the validator says about the same annotations, so both "
                      "lists are fixed in one edit:")
                for w in warns:
                    print(f"{validate_annotations.WARN_PREFIX}{w}")
                for e in errs:
                    print(f"{validate_annotations.ERROR_PREFIX}{e}")
            print(f"\nannotate_check {stem}: STOPPED — the annotations were not "
                  f"applied, so {shown} is unchanged. Fix everything above in "
                  f"{pending.name} in one edit and re-run.")
            return rc
    else:
        print(f"no {pending.name}, so nothing to apply — checking "
              f"{shown} as it stands")

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        vrc = validate_annotations.main([stem])
    vout = buf.getvalue().rstrip()
    print("\n" + vout)
    errors = sum(l.startswith(validate_annotations.ERROR_PREFIX)
                 for l in vout.splitlines())
    warns = sum(l.startswith(validate_annotations.WARN_PREFIX)
                for l in vout.splitlines())

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

    # The puzzle is JSON now; the .js shim is build output, so the file that has
    # to parse is this one, and json does it without shelling out to node.
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except ValueError as err:
        print(f"\n{shown} is not valid JSON:\n{err}")
        issues.append("the file is not valid JSON")

    write_view(path)
    advice = notes(read_puzzle_file(path))
    if advice:
        print("\nworth knowing now (not failures):")
        for line in advice:
            print(f"  - {line}")

    counts = ([f"{errors} ERROR"] if errors else []) + \
             ([f"{warns} warn"] if warns else []) + issues
    print(f"\nannotate_check {stem}: " + (", ".join(counts) if counts else
                                          "clean, index refreshed — done"))
    if not counts:
        # The last turn of a clean run was spent trying to `rm` the patch file,
        # which needs an approval the run cannot give.
        print("Nothing to tidy up: --patch files are deleted when merged and "
              "tools/_* is ignored by git. The run is finished.")
    if counts:
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
              "`python3 tools/validate_annotations.py --explain <check-name>` "
              "prints that check's own source. Do not open the file itself.")
    return vrc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
