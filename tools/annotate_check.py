#!/usr/bin/env python3
"""Everything that must be true of a puzzle's annotations, in one command.

    python3 tools/annotate_check.py cryptic-30098
    python3 tools/annotate_check.py --view cryptic-30098   # the run's input

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
    """Entries still null that need an annotation: not a clue the setter left
    blank, and not a blind run's miss (validate_annotations decides both)."""
    misses = validate_annotations.blind_misses(puzzle["id"])
    return [e for e in puzzle["entries"]
            if not e.get("annotation") and e["id"] not in misses
            and not validate_annotations.is_blank_clue(e["clue"])]


def is_blind(puzzle):
    """A blind run is hiding the key: a blog would hand it back."""
    return ((ROOT / ".blind" / f"{puzzle['id']}.json").exists()
            or any(not e.get("solution") for e in puzzle["entries"]))


# What the annotate run reads the puzzle from: the clues, answers and grid, and
# nothing that says where the answers came from. solutionSource names the blog
# the key was taken from, and a run that can see that URL fetches it before
# trying a single clue; the blog is disclosed by notes() below, once the run is
# stuck, and not before. A whitelist, so a new top-level field stays hidden
# until someone decides the run should see it.
VIEW_KEYS = ("id", "number", "series", "name", "setter", "dimensions", "entries")


def view_path(path):
    """Beside the annotations file, ignored by git (`tools/_*`)."""
    return TOOLS / f"_puzzle_{path.stem}.json"


def write_view(path):
    """Write the annotate run's copy of puzzles/<ID>.json, current as of now."""
    puzzle = read_puzzle_file(path)
    view = {k: puzzle[k] for k in VIEW_KEYS if k in puzzle}
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
    cds = [e["id"] for e in puzzle["entries"]
           if (e.get("annotation") or {}).get("type") == "cryptic definition"]
    if cds:
        out.append(
            f"{', '.join(cds)} typed `cryptic definition`: the one type with no "
            f"checkable wordplay, and the one an unparsed clue can hide in. Hunt for "
            f"the charade or container first (\"Periods on horseback where British "
            f"king into himself?\" reads as a whole-clue definition of CHUKKAS and is "
            f"CHAS around UK + K); keep the type only if the clue has no wordplay.")
    likely = [e["id"] for e in puzzle["entries"]
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
        out.append(
            f"Stuck on {', '.join(e['id'] for e in left)}? {host} blogs this puzzle "
            f"clue by clue: WebSearch `{words}`, then WebFetch the post (its comments "
            f"often have what the blogger missed). Take only the mechanism and write "
            f"every field yourself in this file's voice; if the blog does not settle "
            f"it either, the clue stays null.")
    return out


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    if argv[0] == "--view":
        print(write_view(resolve_puzzle(argv[1])).relative_to(ROOT))
        return 0
    path = resolve_puzzle(argv[0])
    stem = path.stem
    pending = default_input(path)
    issues = []

    if pending.exists():
        rc, out = run([sys.executable, str(TOOLS / "apply_annotations.py"),
                       stem, str(pending), "--no-validate"])
        print(out)
        if rc:
            # Nothing downstream is about this puzzle if the annotations never
            # landed in it, and reporting the old file's state as this run's
            # would be a lie in the direction of "fine".
            print(f"\nannotate_check {stem}: STOPPED — the annotations were not "
                  f"applied, so everything below would be about the previous "
                  f"contents of puzzles/{path.name}. Fix {pending.name} and re-run.")
            return rc
    else:
        print(f"no {pending.name}, so nothing to apply — checking "
              f"puzzles/{path.name} as it stands")

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
            print(f"  {f['entry']} ({f['answer']}, {f['type']})")
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
        print(f"\npuzzles/{path.name} is not valid JSON:\n{err}")
        issues.append("the file is not valid JSON")

    rc, out = run([sys.executable, str(TOOLS / "fetch_puzzle.py"), "--reindex"])
    if rc:
        print(f"\nthe index was not rebuilt:\n{out}")
        issues.append("puzzles/index.json and index.js were not rebuilt")

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
    if counts:
        # Two callers: the annotate run, which hands over tools/_ann_<ID>.json,
        # and the field backfills, which edit the puzzle in place. Naming a file
        # that is not there is an invitation to go looking for it.
        where = (f"tools/{pending.name}" if pending.exists()
                 else f"puzzles/{path.name}")
        print(f"Fix ALL of these in one edit of {where}, then run "
              f"this command again. Re-running to confirm one fix at a time "
              f"costs a turn per warning and tells you nothing this run did not.")
        print("Any line you cannot act on: "
              "`python3 tools/validate_annotations.py --explain <check-name>` "
              "prints that check's own source. Do not open the file itself.")
    return vrc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
