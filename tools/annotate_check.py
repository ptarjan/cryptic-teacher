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
a file written a few clues at a time applies as it stands, an `answer`
typed with the enumeration's commas is respelt with spaces, and
`assembly.pieces` a slip away from the answer are recut from its letters.

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
import re
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

from annotate_audit import load_templates, rule_name  # noqa: E402
from annotation import wordplay_letters  # noqa: E402
import blog_post  # noqa: E402
import clue_types  # noqa: E402
import definitions  # noqa: E402
import groups  # noqa: E402
from groups import entry_id  # noqa: E402
import series  # noqa: E402
import validate_annotations  # noqa: E402
from apply_annotations import annotate_only, current_view, default_input, move_alteration, normalize, view_path  # noqa: E402
from fetch_puzzle import has_words, read_puzzle_file, resolve_puzzle  # noqa: E402
from find_answer_leaks import leaks, light_solutions, names, pieces_of, unname  # noqa: E402
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


def to_write(puzzle, before):
    """The ids a run on this puzzle annotates: the clues that lack a hint,
    plus `before`, the list the run started with, so a clue the run has since
    written stays its own to fix. Every other annotation is fixed context.

    None, at the start of a run on a puzzle with no hints yet or none
    missing: the run takes the whole puzzle."""
    continuations = groups.leader_of(puzzle["entries"])
    clues = [e for e in puzzle["entries"] if entry_id(e) not in continuations]
    only = [entry_id(e) for e in clues if entry_id(e) in (before or ())
            or (not e.get("annotation") and has_words(e["clue"].get("text", "")))]
    if before is None and (not only or not any(e.get("annotation") for e in clues)):
        return None
    return only


def view_line(e, leaders):
    """One entry as a line: id | group | SOLUTION | clue (enumeration)."""
    clue = e["clue"]
    words = clue.get("text") or "(no clue printed)"
    if clue.get("enumeration"):
        words += f" ({clue['enumeration']})"
    eid = entry_id(e)
    group = "+".join(e["group"]) if e.get("group") else (
        f"in {leaders[eid]}" if eid in leaders else "-")
    solution = e.get("solution") or "?"
    if e.get("solutionConfidence"):
        solution += f" ({e['solutionConfidence']})"
    if e.get("alteration"):
        solution += f" (alteration from {e['alteration']['from']})"
    return f"{eid} | {group} | {solution} | {words}"


def write_view(path):
    """Write the annotate run's copy of the puzzle file, current as of now.

    JSON, since apply_annotations reads `annotateOnly` back out of it, but
    with `entries` one line each (`1-across | group | SOLUTION | clue (enum)`)
    in place of an object per entry: the run needs the clue, the answer and
    which lights are linked, and a pretty-printed object per entry was five
    times the reading for it. An annotation already on an entry the run
    leaves alone is kept in `existingAnnotations`, for context."""
    puzzle = read_puzzle_file(path)
    view = {k: puzzle[k] for k in VIEW_KEYS if k in puzzle and k != "entries"}
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
    leaders = groups.leader_of(puzzle["entries"])
    view["entries"] = [view_line(e, leaders) for e in puzzle["entries"]]
    kept = {entry_id(e): e["annotation"] for e in puzzle["entries"]
            if e.get("annotation") and only is not None and entry_id(e) not in only}
    if kept:
        view["existingAnnotations"] = kept
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
    mine = [e for e in puzzle["entries"] if only is None or entry_id(e) in only]
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
    only = annotate_only(path)
    missing = [entry_id(e) for e in entries
               if entry_id(e) not in continuations and entry_id(e) not in ann
               and (only is None or entry_id(e) in only)]
    if missing:
        ann.update(dict.fromkeys(missing))
        pending.write_text(json.dumps(ann, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
        pending.write_text(json.dumps(ann, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed


def normalize_pending(path, pending):
    """Write into `pending` what apply_annotations.normalize computes (an
    `answer` left out, ...), so the steps before the apply see it too."""
    try:
        ann = json.loads(pending.read_text(encoding="utf-8"))
    except ValueError:
        return
    if not isinstance(ann, dict):
        return
    entries = read_puzzle_file(path)["entries"]
    by_id = {entry_id(e): e for e in entries}
    out = {k: normalize(v, by_id[k], entries) if k in by_id else v for k, v in ann.items()}
    if out != ann:
        pending.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _edits(a, b):
    """Levenshtein distance between two strings."""
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, cb in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (ca != cb))
    return row[-1]


def recut(pieces, want, gives=()):
    """`want` cut into as many chunks as `pieces`, or None.

    The chunks are the answer's own letters, so they always join to it: the
    pieces of a whole-answer reversal written in the order they were reversed
    from (RATS+RE+PUS for SUPERSTAR) are each turned round and listed back to
    front; otherwise each piece is matched to the run of `want` it differs
    least from, a run that is some block's `gives` preferred. Only a slip is recut: the same letters out of order, or at
    most two letters wrong. Anything further is a different parse or answer,
    and stays an error."""
    bare = [re.sub(r"[^A-Z]", "", str(p).upper()) for p in pieces]
    joined = "".join(bare)
    if not want or joined == want or not 0 < len(bare) <= len(want) or not all(bare):
        return None
    if joined[::-1] == want:
        return [p[::-1] for p in reversed(bare)]
    if sorted(joined) != sorted(want) and _edits(joined, want) > 2:
        return None
    k, n = len(bare), len(want)
    inf = float("inf")
    best = [[inf] * (n + 1) for _ in range(k + 1)]
    cut = [[0] * (n + 1) for _ in range(k + 1)]
    best[0][0] = 0
    for i in range(1, k + 1):
        for j in range(i, n - (k - i) + 1):
            for m in range(i - 1, j):
                if best[i - 1][m] < inf:
                    c = (best[i - 1][m] + _edits(bare[i - 1], want[m:j])
                         - 0.5 * (want[m:j] in gives))
                    if c < best[i][j]:
                        best[i][j], cut[i][j] = c, m
    out, j = [], n
    for i in range(k, 0, -1):
        out.append(want[cut[i][j]:j])
        j = cut[i][j]
    return out[::-1]


def recut_pieces(path, pending):
    """Recut each `assembly.pieces` that misses the answer by a slip (see
    `recut`); the entry ids changed, with the new pieces. `pieces` restates
    letters the blocks already give, and a slip in retyping them was the
    third commonest first-check failure, each costing a turn."""
    try:
        ann = json.loads(pending.read_text(encoding="utf-8"))
        entries = {entry_id(e): e for e in read_puzzle_file(path)["entries"]}
    except (ValueError, OSError, KeyError):
        return []
    changed = []
    for eid, a in (ann.items() if isinstance(ann, dict) else ()):
        build = a.get("assembly") if isinstance(a, dict) else None
        pieces = build.get("pieces") if isinstance(build, dict) else None
        if not isinstance(pieces, list) or not pieces:
            continue
        entry = dict(entries.get(eid) or {})
        if isinstance(a.get("alteration"), dict):
            entry["alteration"] = a["alteration"]
        gives = {re.sub(r"[^A-Z]", "", str(b.get("gives") or "").upper())
                 for b in a.get("blocks") or [] if isinstance(b, dict)}
        new = recut(pieces, wordplay_letters(a, entry), gives)
        if new:
            build["pieces"] = new
            changed.append((eid, new))
    if changed:
        pending.write_text(json.dumps(ann, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed


def unname_block_notes(path, pending):
    """Rewrite each block note that names its answer, where find_answer_leaks.unname
    can do it without judgement, or blank the answer in a note on one sense of
    a double definition; the entry ids changed.
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
        if not isinstance(a, dict) or not isinstance(a.get("answer"), str):
            continue
        lights = light_solutions(by_id.get(eid) or {}, by_id)
        pieces = pieces_of(a)
        senses = "double_definition" in (a.get("type") or [])
        for block in a.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            for name in names(a["answer"], lights):
                # "gives the answer" is true of the whole answer only, never of a light.
                gives = block.get("gives") if name == a["answer"] else ""
                new = unname(block.get("note"), name, gives, clues.get(eid, ""),
                             pieces, blank=senses and not block.get("gives"))
                if new:
                    block["note"] = new
                    changed.append(eid)
    if changed:
        pending.write_text(json.dumps(ann, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return sorted(set(changed), key=changed.index)


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
        for e in puzzle["entries"]:
            if entry_id(e) in continuations or (only is not None and entry_id(e) not in ann):
                continue
            if ann.get(entry_id(e)) is None:
                e.pop("annotation", None)
            else:
                e["annotation"] = normalize(ann[entry_id(e)], e, puzzle["entries"])
                move_alteration(e)
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
        normalize_pending(path, pending)
        spaced = respell_answers(pending)
        if spaced:
            print(f"answers written with commas, now spaced in {pending.name}: "
                  f"{', '.join(spaced)}\n")
        recut_done = recut_pieces(path, pending)
        if recut_done:
            print("assembly.pieces that did not join to the answer, recut from its "
                  f"letters in {pending.name}: "
                  + "; ".join(f"{eid} {'+'.join(p)}" for eid, p in recut_done) + "\n")
        unnamed = unname_block_notes(path, pending)
        if unnamed:
            print(f"block notes that named the answer, rewritten without it in "
                  f"{pending.name}: {', '.join(unnamed)}\n")
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
                print(name_checks("\n".join(
                    [f"{validate_annotations.WARN_PREFIX}{w}" for w in warns]
                    + [f"{validate_annotations.ERROR_PREFIX}{e}" for e in errs])))
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
    print("\n" + name_checks(vout))
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
    advice = notes(read_puzzle_file(path), annotate_only(path))
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
              "`python3 tools/validate_annotations.py --explain <the [check_name] "
              "after it>` prints that check's own source. Do not open the file itself.")
    return vrc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
