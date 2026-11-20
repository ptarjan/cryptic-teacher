#!/usr/bin/env python3
"""Rewrite the parts of README.md and docs/ that the repo already knows the answer to.

A README goes stale one true sentence at a time. Every count in it was correct
the day it was typed, every tool in its file list existed, every default it
quoted matched the script -- and then the nightly job added a puzzle, someone
added a tool, someone changed a default, and the file quietly started lying.
Nothing fails when that happens, which is exactly why it keeps happening.

So the facts are not typed here at all. Regions of README.md,
docs/NIGHTLY.md are generated between HTML-comment markers, from the same files
the app and the schedulers read:

    LADDER   the hint rungs, with app.js's own labels and in its order
    KNOBS    the scheduling defaults, parsed out of the shell scripts (docs/NIGHTLY.md)

Everything outside those markers is prose about how the thing works, which is
the part a person should be writing. If you find yourself wanting to type a
number into it, put the number in here instead.

    python3 tools/build_readme.py           rewrite the generated regions
    python3 tools/build_readme.py --check   exit 1 if they are out of date

tools/daily_update.sh runs it when its rebase conflicts. Counts of puzzles and
clues are not generated here: they change every day, so they live on the live
site (/progress/, built from the same puzzle files at each deploy). The check
is what makes the regions safe: a tool added without a description, or a
default changed without the README following, fails it rather than rotting
quietly.
"""
import re
import subprocess
import sys
from pathlib import Path

import app_src

REPO = Path(__file__).resolve().parent.parent
README = REPO / "README.md"
NIGHTLY_DOC = REPO / "docs" / "NIGHTLY.md"

# Where each scheduling default really lives. docs/NIGHTLY.md quotes these numbers in
# prose; parsing them from the script is what keeps the prose honest, and a knob
# that gets renamed fails the build instead of leaving a plausible wrong number
# on the page.
KNOB_FILES = {
    "ANNOTATE_MAX": "tools/daily_update.sh",
    "ANNOTATE_MAX_WEEKLY_PCT": "tools/daily_update.sh",
    "SOLVE_MAX": "tools/daily_update.sh",
}


def fail(msg):
    print(f"build_readme: {msg}", file=sys.stderr)
    raise SystemExit(1)


def tracked_files():
    out = subprocess.run(["git", "-C", str(REPO), "ls-files"],
                         capture_output=True, text=True, check=True).stdout
    return [p for p in out.splitlines() if p]


def read_knobs():
    """Every default in KNOB_FILES, as {name: value}, straight from the shell."""
    knobs = {}
    for name, rel in KNOB_FILES.items():
        text = (REPO / rel).read_text(encoding="utf-8")
        m = re.search(rf'^{name}="\$\{{{name}:-([^}}]*)\}}"', text, re.M)
        if not m:
            fail(f"{rel} no longer sets a default for {name}. Either it was "
                 f"renamed — update KNOB_FILES — or docs/NIGHTLY.md should stop "
                 f"quoting it.")
        knobs[name] = m.group(1)
    return knobs


def build_knobs(k):
    return (
        f"The two scheduled jobs split the quota deliberately: the nightly's "
        f"units, started by a tick every ten minutes, annotate every puzzle from "
        f"the last two days plus at most {k['ANNOTATE_MAX']} a day from the "
        f"backlog, and only below {k['ANNOTATE_MAX_WEEKLY_PCT']}% of the week "
        f"(re-checked as each puzzle starts), while the hourly one spends "
        f"everything else with no gate: as many runs as land the weekly meter at "
        f"its limit right at the weekly reset, net of the bridge's own spend, "
        f"until the weekly meter is spent or the week resets."
    )


#: The tools that turn a job's raw log into the human log Paul reads.
HUMAN_LOGS = ("burn_log", "ocr_log")


def build_logs():
    """One row per human-log tool, from the first line of its own docstring."""
    import ast
    rows = []
    for name in HUMAN_LOGS:
        tree = ast.parse((REPO / "tools" / f"{name}.py").read_text(encoding="utf-8"))
        doc = ast.get_docstring(tree)
        if not doc:
            fail(f"tools/{name}.py has no docstring, so the README cannot say what its log is.")
        rows.append(f"- `tools/{name}.py` — {doc.splitlines()[0]}")
    return "\n".join(rows)


# What each rung is FOR. The name beside it is not written here: app.js owns the
# labels, because they are what the buttons say, and a README that renamed them
# in prose would be describing a site that does not exist. A rung added to app.js with no line here fails this
# script rather than quietly going undescribed.
RUNG_NOTES = {
    "type": "anagram? charade? container? hidden word? …",
    "definition": "the definition part of the clue is highlighted",
    "indicators": "the anagram, container, reversal and homophone signal words "
                  "are highlighted",
    "blocks": "the fodder and the synonym breakdown, a piece at a time "
              "(\u201chost = ARMY; part of TV duo = ANT\u201d). A double "
              "definition has none: its halves are the definition rung's",
    "walkthrough": "the whole assembly, step by step",
}


def build_ladder():
    """The ladder, named with app.js's own button labels and in its own order."""
    app = app_src.read(REPO)
    import app_tables
    # The numbering is app.js's own: `ladder()` reads the ordered LABELS map the
    # app sorts its rungs by, and raises if app.js stops deriving the order from
    # it. A copy of the order here would keep printing the old order after the
    # app reordered its rungs.
    labels = app_tables.ladder(app)
    missing = [k for k, _ in labels if k not in RUNG_NOTES]
    if missing:
        fail("these rungs are in app.js but have no line in RUNG_NOTES in this "
             "script, so the README would not say what they teach: "
             + ", ".join(missing))
    fill = re.search(r'const FILL_LABEL = "([^"]+)"', app)
    if not fill:
        fail("app.js has no `const FILL_LABEL`, which names the way out of a clue.")
    # No full stop after a note that already ends in one — "hidden word? \u2026."
    # is what writing a sentence in two places looks like.
    lines = [f"{i}. **{name}** \u2014 {RUNG_NOTES[key]}"
             + ("" if RUNG_NOTES[key][-1] in ".?\u2026" else ".")
             for i, (key, name) in enumerate(labels, 1)]
    lines.append("")
    lines.append(f"**{fill.group(1)}** writes the solution into the grid. It is the "
                 "way out of a clue rather than a step in it, so it is offered "
                 "alongside the rungs once the building blocks are up, and it is "
                 "not counted as one.")
    return "\n".join(lines)


# Which generated region lives in which file. The README is for a visitor, so it
# carries only the ladder and the corpus line; the quota split belongs with the
# nightly jobs it describes.
REGIONS = {
    README: {"LADDER": build_ladder},
    NIGHTLY_DOC: {"KNOBS": lambda: build_knobs(read_knobs()), "LOGS": build_logs},
}


def render(path):
    text = path.read_text(encoding="utf-8")
    blocks = dict(REGIONS[path])
    for name, build in blocks.items():
        pattern = re.compile(
            rf"(<!-- {name}-START[^>]*-->).*?(<!-- {name}-END -->)", re.S)
        if not pattern.search(text):
            fail(f"{path.name} has no <!-- {name}-START --> … <!-- {name}-END --> "
                 f"markers. They are what makes this region generated; put them "
                 f"back rather than hand-writing the block.")
        text = pattern.sub(
            lambda m: f"{m.group(1)}\n{build()}\n{m.group(2)}", text, count=1)
    # Deliberately no substitution outside the markers. A placeholder anywhere
    # else would be consumed the first time this ran — the number would replace
    # it in the file, and the next run would have nothing left to substitute and
    # would happily agree with a value that had since changed. Inside the markers
    # the block is rebuilt from nothing every time, which is what makes the check
    # meaningful; so a knob is quoted once, there, and the prose points at it.
    return text


def main():
    # An unknown flag (--help included) must not fall through to the full
    # rebuild: that is a multi-process corpus pass on a shared host.
    unknown = [a for a in sys.argv[1:]
               if a != "--check"]
    if unknown:
        print(__doc__, file=sys.stderr)
        print(f"unknown argument: {' '.join(unknown)}", file=sys.stderr)
        return 2
    check = "--check" in sys.argv[1:]
    stale = []
    for path in REGIONS:
        new = render(path)
        if new == path.read_text(encoding="utf-8"):
            print(f"{path.name} is up to date")
            continue
        if check:
            stale.append(path.name)
            continue
        path.write_text(new, encoding="utf-8")
        print(f"{path.name} rewritten")
    if stale:
        print(f"{', '.join(stale)} out of date — run tools/build_readme.py",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
