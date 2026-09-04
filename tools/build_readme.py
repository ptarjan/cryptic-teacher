#!/usr/bin/env python3
"""Rewrite the parts of README.md that the repo already knows the answer to.

A README goes stale one true sentence at a time. Every count in it was correct
the day it was typed, every tool in its file list existed, every default it
quoted matched the script -- and then the nightly job added a puzzle, someone
added a tool, someone changed a default, and the file quietly started lying.
Nothing fails when that happens, which is exactly why it keeps happening.

So the facts are not typed here at all. Three regions of README.md are generated
between HTML-comment markers, from the same files the app and the schedulers
read:

    CORPUS   how many puzzles and clues there are, and how many are annotated
    LAYOUT   what is in the repo, file by file
    KNOBS    the scheduling defaults, parsed out of the shell scripts

Everything outside those markers is prose about how the thing works, which is
the part a person should be writing. If you find yourself wanting to type a
number into it, put the number in here instead.

    python3 tools/build_readme.py           rewrite the generated regions
    python3 tools/build_readme.py --check   exit 1 if they are out of date

tools/daily_update.sh runs the first before it commits, so the corpus block
cannot drift by more than one run. The second is what makes the other two
regions safe: a tool added without a description, or a default changed without
the README following, fails the check rather than rotting quietly.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
README = REPO / "README.md"

# What each tracked file is for, in one line. This table is the reason the
# layout block cannot go stale: build_layout() compares its keys against the
# files git is actually tracking and refuses to write anything if the two
# disagree, so a tool added without a description is a build failure and a
# description left behind by a deleted tool is the same. Order is the order the
# README prints; the blank-string keys are section headings.
LAYOUT = [
    ("", "index.html, style.css, app.js", "the app (vanilla HTML/CSS/JS)"),
    ("", "abbreviations.js", "generated letter→clue-word map, read by app.js"),
    ("", "analytics.js", "the one shared GA snippet every page loads, so there is exactly one id"),
    ("", "learn/", "the “How cryptic clues work” lesson, built from tools/tutorial.html"),
    ("", "abbreviations/", "the glossary of standard abbreviations the blocks rung links into"),
    ("", "og/", "one 1200x630 social card per puzzle, drawn from one of its clues"),
    ("", "puzzles/index.json", "manifest: one row per puzzle (latest first)"),
    ("", "puzzles/index.js", "the same manifest as a script (so file:// works)"),
    ("", "puzzles/<series>-<n>.js", "one puzzle per file, JSON between /*JSON-START*/ … /*JSON-END*/"),

    ("the rest of the site", "site.webmanifest", "PWA name, icons and display mode"),
    ("the rest of the site", "robots.txt", "crawler policy, and where the sitemap is"),
    ("the rest of the site", "sitemap.xml", "every URL, regenerated with the static pages"),
    ("the rest of the site", "og.png", "the default social card, for pages that aren’t one puzzle"),
    ("the rest of the site", "favicon.*, icon-*.png, apple-touch-icon.png",
     "the icon set, all rendered from one source by tools/make_icons.py"),

    ("fetching", "tools/fetch_puzzle.py", "fetch/convert the Guardian cryptic, Saturday prize and Quiptic, --latest/--backfill/--extend/--reindex"),
    ("fetching", "tools/fetch_independent.py", "the Independent’s daily and Sunday"),
    ("fetching", "tools/fetch_observer.py", "the Observer’s Everyman"),
    ("fetching", "tools/extend_archive.py", "walks the archives backwards to keep the annotation queue deeper than the job's best week"),
    ("fetching", "tools/fetch_minutecryptic.js", "Minute Cryptic’s daily hints, as a corpus to be measured against"),
    ("fetching", "tools/fetch_lexicon.sh", "downloads the Lufz/Exet lexicon the grid filler needs"),

    ("annotating", "tools/annotate_prompt.md", "the prompt the daily Claude Code job follows to annotate"),
    ("annotating", "tools/build_annotate_prompt.py", "regenerates that prompt’s reference block from the code’s own tables"),
    ("annotating", "STYLE.md", "the standing style rules, read whole by every annotating run"),
    ("annotating", "APP.md", "how the app presents an annotation and how it ships — separate from style"),
    ("annotating", "tools/validate_annotations.py", "proves every annotation actually spells its answer, plus the other rules about what a rung may and may not say"),
    ("annotating", "tools/apply_annotations.py", "writes a run’s annotation JSON into the puzzle file, and validates the result"),
    ("annotating", "tools/annotation_backlog.json", "how many clues of each OLD puzzle predate a required field; a puzzle not listed is allowed none, so new rules bind new puzzles"),
    ("annotating", "tools/check_annotation_loss.py", "shouts when an annotation run leaves clues it could not solve, so a weak night can't pass for a good one"),
    ("annotating", "tools/find_answer_leaks.py", "finds a block note that says the answer out loud, a rung before the walkthrough sells it"),
    ("annotating", "tools/find_renarration.py", "flags a walkthrough that only restates the blocks instead of teaching past them"),
    ("annotating", "tools/clue_quality.py", "warns about the clue shapes that lost to human setters in blind grading"),
    ("annotating", "tools/annotate_model.sh", "sourced: turns $ANNOTATE_MODEL into the right Co-Authored-By trailer"),
    ("annotating", "tools/app_tables.py", "the clue-family table, read by the tools so there is no port of the app’s wording to keep in step"),

    ("setting our own puzzles", "tools/AUTHORING.md", "how an original puzzle gets set: the grid is filled first, the clues written by hand after"),
    ("setting our own puzzles", "tools/grid_rules.py", "what makes a British blocked grid legal, in one place"),
    ("setting our own puzzles", "tools/grid_fill.py", "fills a legal grid with answers you can actually write clues for"),
    ("setting our own puzzles", "tools/clueability.py", "scores how easy a fair cryptic clue for a word would be"),
    ("setting our own puzzles", "tools/build_lexicon.js", "extracts the fillable word list (rank, region, family, phonetics) from the lexicon"),
    ("setting our own puzzles", "tools/build_authored_puzzle.py", "merges a fill and its hand-written clues into a publishable puzzle file"),

    ("solving the puzzles whose answers aren’t published yet",
     "tools/solve_packet.py", "the clues and the grid’s crossing map, for a cold solve"),
    ("solving the puzzles whose answers aren’t published yet",
     "tools/solve_prompt.md", "the method the model follows"),
    ("solving the puzzles whose answers aren’t published yet",
     "tools/apply_solution.py", "writes a blind solve in only if every crossing letter agrees"),

    ("building and checking the site", "tools/build_seo_pages.py", "one static page per puzzle, for search engines and unfurls"),
    ("building and checking the site", "tools/build_abbreviations.py", "builds abbreviations/ from the annotations that cite them"),
    ("building and checking the site", "tools/build_readme.py", "this: rewrites the generated regions of README.md, --check fails on drift"),
    ("building and checking the site", "tools/make_og_card.py", "picks a puzzle’s best clue and lays out its social card"),
    ("building and checking the site", "tools/make_og.sh", "screenshots those cards with headless Chrome"),
    ("building and checking the site", "tools/make_icons.py", "renders every favicon and PWA icon from one source of truth"),
    ("building and checking the site", "tools/stamp_assets.py", "cache-busting ?v= stamps; the smoke test fails on a stale one"),
    ("building and checking the site", "tools/smoke_test.js", "the whole app driven headless against the real corpus"),
    ("building and checking the site", "tools/fake_dom.js", "the fake DOM that boots the real app.js under Node, shared by every harness"),
    ("building and checking the site", "tools/e2e_analytics.py", "drives a real browser through a solve and checks every event lands in KV"),
    ("building and checking the site", "tools/wait_for_deploy.py", "blocks until Pages is serving the pushed commit, so nobody is told to reload early"),
    ("building and checking the site", "tools/tutorial.html", "source of the learn/ lesson"),
    ("building and checking the site", "tools/og_card.html", "source and type for og.png, the site’s one social card"),

    ("syncing between devices, with no login and no accounts",
     "sync/worker.js", "the Cloudflare Worker: stores and merges saves and events in KV"),
    ("syncing between devices, with no login and no accounts",
     "sync/merge.js", "union rules, so two devices combine instead of asking which one wins"),
    ("syncing between devices, with no login and no accounts",
     "sync/events.js", "the exhaustive list of milestones the app and the Worker may report"),
    ("syncing between devices, with no login and no accounts",
     "sync/wrangler.toml", "the Worker’s deploy config and KV binding"),

    ("scheduling", "tools/daily_update.sh", "daily script: fetch latest, annotate backlog, validate, commit"),
    ("scheduling", "tools/nightly_worktree.sh", "sourced first: re-execs a scheduled job in its own worktree, never the editor’s"),
    ("scheduling", "tools/alert.sh", "posts a run’s failures to Discord instead of burying them in a log"),
    ("scheduling", "tools/com.pt.cryptic-teacher.plist", "LaunchAgent that runs daily_update.sh at 06:15"),
    ("scheduling", "tools/weekly_usage.py", "how much of a Claude quota window is spent, and when it resets"),
    ("scheduling", "tools/prereset_backfill.sh", "burns the tail of the weekly quota on backfills, ungated"),
    ("scheduling", "tools/prereset_plan.py", "how many puzzles the remaining quota will carry before the reset"),
    ("scheduling", "tools/backlog_burndown.py", "the annotation backlog over time, rebuilt from git history, and how long the rest will take at that pace"),
    ("scheduling", "tools/com.pt.cryptic-teacher-prereset.plist", "LaunchAgent that polls prereset_backfill.sh hourly"),

    ("finding out whether any of it is working", "tools/reports.py", "reads and clears the bad-hint reports solvers sent in"),
    ("finding out whether any of it is working", "tools/rung_report.py", "where on the ladder solvers give up, from synced hintsShown data"),
    ("finding out whether any of it is working", "tools/usage_report.py", "counts the solving milestones in KV, with no way to identify who did what"),
    ("finding out whether any of it is working", "tools/ga_report.py", "the same milestones as Google Analytics counts them, to see what a blocker hides"),
    ("finding out whether any of it is working", "tools/ga_wire_check.py", "watches the wire to confirm GA hits actually leave the browser"),
    ("finding out whether any of it is working", "tools/difficulty.py", "rates a puzzle from what its own file contains, banded against the corpus"),
    ("finding out whether any of it is working", "tools/make_hint_packets.js", "blind solve-packets, to grade a hint by whether it gets a solver unstuck"),
    ("finding out whether any of it is working", "tools/grade_clues.py", "blind A/B/C/D packets of our clues against real setters’ for the same answers"),
    ("finding out whether any of it is working", "tools/score_grading.py", "joins the blind scores back to provenance: the ours-vs-human head-to-head"),
    ("finding out whether any of it is working", "tools/compare_mc.py", "word-count and shape comparison of our hints against Minute Cryptic’s"),

    ("tables everything else reads", "tools/series.py", "the one table of facts about each series: publisher, naming, URL shape"),
    ("tables everything else reads", "tools/kv.py", "the one helper for reading the sync KV namespace through wrangler"),
    ("tables everything else reads", "tools/data/README.md", "what in tools/data is committed, what is fetched, and under what licence"),
    ("tables everything else reads", "tools/data/abbreviations.json", "the hand-built starter table of standard abbreviations"),
    ("tables everything else reads", "tools/data/unclueable.json", "words rejected as answers, with reasons; grid_fill.py vetoes them"),
    ("tables everything else reads", "tools/data/difficulty_baseline.json", "the frozen distribution difficulty.py normalises against"),
    ("tables everything else reads", "tools/data/grading_rubric.md", "the five axes a blind judge scores a clue on"),
    ("tables everything else reads", "tools/data/sample_fill_11.json", "the worked 11x11 fill tools/AUTHORING.md walks through"),
    ("tables everything else reads", "tools/data/authored_A001_clues.json", "the hand-written clues for that fill"),
]

# Files that are deliberately absent from the layout table: scratch, data the
# table already covers as a glob, and things nobody reading the README needs to
# be shown. Anything else under tools/ must be described or the build fails.
LAYOUT_EXEMPT = re.compile(r"""
      ^tools/_                      # scratch scripts, named with a leading underscore
    | ^tools/__pycache__/
    | ^puzzles/                     # covered by the <series>-<n>.js line
    | ^og/                          # covered by the og/ line
    | ^learn/ | ^abbreviations/
    | ^favicon | ^icon- | ^apple-touch-icon   # covered by the icon-set line
    | ^\. | /\.                     # dotfiles: .nojekyll, .gitignore, .github/
    | ^README\.md$ | ^LICENSE
    | ^index\.html$ | ^style\.css$ | ^app\.js$
""", re.X)

# Where each scheduling default really lives. The README quotes these numbers in
# prose; parsing them from the script is what keeps the prose honest, and a knob
# that gets renamed fails the build instead of leaving a plausible wrong number
# on the page.
KNOB_FILES = {
    "ANNOTATE_MAX": "tools/daily_update.sh",
    "ANNOTATE_MAX_WEEKLY_PCT": "tools/daily_update.sh",
    "ANNOTATE_MAX_SESSION_PCT": "tools/daily_update.sh",
    "SOLVE_MAX": "tools/daily_update.sh",
    "FORCE_HOURS": "tools/prereset_backfill.sh",
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
                 f"renamed — update KNOB_FILES — or the README should stop "
                 f"quoting it.")
        knobs[name] = m.group(1)
    return knobs


SERIES_NAMES = {
    "cryptic": "Guardian cryptic",
    "quiptic": "Guardian Quiptic",
    "everyman": "Observer Everyman",
    "independent": "Independent daily",
    "indysunday": "Independent Sunday",
}


def build_corpus():
    index = json.loads((REPO / "puzzles/index.json").read_text(encoding="utf-8"))
    rows = index["puzzles"]

    by_series = {}
    for r in rows:
        by_series[r["series"]] = by_series.get(r["series"], 0) + 1
    unknown = set(by_series) - set(SERIES_NAMES)
    if unknown:
        fail(f"a new series is being fetched that the README has no name for: "
             f"{', '.join(sorted(unknown))}. Add it to SERIES_NAMES.")

    # Counted from the puzzle files rather than the index, because "annotated"
    # in the index is a per-puzzle flag and the interesting number is per clue:
    # a puzzle counts as annotated with one clue left blank.
    clues = done = 0
    for r in rows:
        text = (REPO / "puzzles" / r["file"]).read_text(encoding="utf-8")
        body = text.split("/*JSON-START*/", 1)[1].rsplit("/*JSON-END*/", 1)[0]
        for e in json.loads(body).get("entries", []):
            clues += 1
            if e.get("annotation"):
                done += 1

    annotated = sum(1 for r in rows if r.get("annotated"))
    parts = ", ".join(f"{SERIES_NAMES[s]} {n}"
                      for s, n in sorted(by_series.items(),
                                         key=lambda kv: -kv[1]))
    pct = round(100 * done / clues) if clues else 0
    return (
        f"**Corpus** — {len(rows):,} puzzles across {len(by_series)} series "
        f"({parts}). {annotated:,} of them are annotated clue-for-clue, all six "
        f"rungs, machine-validated: {done:,} of {clues:,} clues, or {pct}%. The "
        f"rest are backlog the daily job is still draining — they show an "
        f"<em>auto hints</em> badge and degrade gracefully (checking and letter "
        f"reveals still work; the teaching ladder appears once a puzzle is "
        f"annotated)."
    )


def build_layout():
    described = {path for _, path, _ in LAYOUT}
    tracked = set(tracked_files())
    # Every file that has to be named individually: the exempt ones are the ones a
    # directory or glob line already stands for.
    on_disk = {p for p in tracked if not LAYOUT_EXEMPT.search(p)}

    missing = sorted(on_disk - described)
    if missing:
        fail("these tracked files have no line in the README's layout table:\n  "
             + "\n  ".join(missing)
             + "\nAdd one to LAYOUT in this script (or to LAYOUT_EXEMPT if a "
               "reader of the README genuinely does not need to know).")
    # A line that names several files, or a directory, or a glob, stands for a set
    # the exempt list covers; only the lines naming exactly one path can be checked
    # for having outlived it.
    gone = sorted(d for d in described - tracked
                  if not any(c in d for c in "<*,") and not d.endswith("/"))
    if gone:
        fail("the README's layout table describes files that no longer exist:\n  "
             + "\n  ".join(gone) + "\nRemove them from LAYOUT in this script.")

    width = max(len(path) for _, path, _ in LAYOUT) + 2
    lines, section = [], None
    for sec, path, desc in LAYOUT:
        if sec != section:
            if section is not None or sec:
                lines.append("")
            if sec:
                lines.append(sec)
            section = sec
        head = f"{path.ljust(width)}{desc}"
        # Wrapped to the same column the descriptions start in, so a long line
        # reads as one entry rather than as a new file.
        wrapped, line = [], head
        while len(line) > 96:
            cut = line.rfind(" ", 0, 96)
            wrapped.append(line[:cut])
            line = " " * width + line[cut + 1:]
        wrapped.append(line)
        lines.extend(wrapped)
    return "```\n" + "\n".join(lines) + "\n```"


def build_knobs(k):
    return (
        f"The two scheduled jobs split the quota deliberately: the 06:15 one "
        f"annotates at most {k['ANNOTATE_MAX']} puzzles and only below "
        f"{k['ANNOTATE_MAX_WEEKLY_PCT']}% of the week (and "
        f"{k['ANNOTATE_MAX_SESSION_PCT']}% of the rolling five-hour window, "
        f"re-checked between puzzles), while the hourly one does nothing at all "
        f"until `weekly_usage.py --resets-in` says the weekly window is within "
        f"{k['FORCE_HOURS']} hour of turning over — at which point unspent quota "
        f"is about to vanish, so it spends the remainder with no gate."
    )


REGIONS = {
    "CORPUS": build_corpus,
    "LAYOUT": build_layout,
}


def render():
    knobs = read_knobs()
    text = README.read_text(encoding="utf-8")
    blocks = dict(REGIONS)
    blocks["KNOBS"] = lambda: build_knobs(knobs)
    for name, build in blocks.items():
        pattern = re.compile(
            rf"(<!-- {name}-START[^>]*-->).*?(<!-- {name}-END -->)", re.S)
        if not pattern.search(text):
            fail(f"README.md has no <!-- {name}-START --> … <!-- {name}-END --> "
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
    check = "--check" in sys.argv[1:]
    new = render()
    old = README.read_text(encoding="utf-8")
    if new == old:
        print("README.md is up to date")
        return 0
    if check:
        print("README.md is out of date — run tools/build_readme.py",
              file=sys.stderr)
        return 1
    README.write_text(new, encoding="utf-8")
    print("README.md rewritten")
    return 0


if __name__ == "__main__":
    sys.exit(main())
