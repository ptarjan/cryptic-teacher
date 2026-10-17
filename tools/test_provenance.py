#!/usr/bin/env python3
# Does provenance actually REFUSE a puzzle that lies about where it came from?
#
#     python3 tools/test_provenance.py
#
# The point of provenance is that a grid this repo cold-solved must never be
# indistinguishable from the setter's own answer key. That guarantee is worth
# exactly as much as the check behind it, and a check nobody exercises quietly
# stops checking — so every refusal the validator is supposed to make is made
# here, against a real puzzle mutated in memory.
#
# Four properties, in the order they matter:
#
#   1. THE ENUM IS ONE ENUM. tools/provenance.py's GRID_ORIGINS,
#      SOLUTION_ORIGINS, RETRIEVAL_CHANNELS and ACQUIRED_BY are the only lists
#      of allowed values in the repo. Proved by deletion rather than by reading:
#      remove a value from the dict and every puzzle using it must immediately
#      be flagged. A second copy of the list anywhere — in the validator, in the
#      README, in a fetcher — would keep those puzzles passing, and this test
#      would fail.
#
#   2. A TOOL NAMED IN ACQUIRED_BY IS A TOOL THAT EXISTS. The keys are command
#      lines, and a puzzle claiming to have been fetched by a script that was
#      renamed or deleted is a dead pointer dressed as a record. Every key is
#      resolved to a file on disk.
#
#   3. THE ORIGIN CANNOT CONTRADICT THE FILE IT SITS ON. Saying "published"
#      over solutions detail that says "model" is the exact failure provenance
#      exists to prevent, and it must be refused rather than preferred — as
#      must "unsolved" over a grid full of answers, and a retrieval channel
#      that disagrees with the tool that did the retrieving.
#
#   4. REAL PUZZLES PASS. Run against files on disk, not synthetic dicts. The
#      sample below holds one puzzle of every grid origin, solution origin and
#      retrieval channel in the corpus; walking all ~43,000 files (or the whole
#      git history, as backfill_provenance.py does without --only) is minutes,
#      and a test runs in seconds.
import copy
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.chdir(REPO)
sys.path.insert(0, str(REPO / "tools"))

import fetch_puzzle
import file_archive_org_puzzles as f
import provenance as p
import puzzle_integrity
import series as series_table

# One puzzle per value of every enum: published/reconstructed grids; published,
# writeup, model and unsolved answers; publisher, blog, wayback, newspaper,
# book and unknown channels; a model fill since confirmed (everyman-4165).
SAMPLE = ("cyclops-526 book-3027 book-8001 cryptic-30078 cryptic-12575 cryptic-26407 "
          "everyman-4165 everyman-3551 canberra-670714 metro-10048").split()
fails = 0


def same(what, got, want):
    global fails
    if got == want:
        print(f"  ok: {what}")
    else:
        print(f"  FAIL: {what}\n    want {want}\n    got  {got}")
        fails += 1


def load(pid):
    return fetch_puzzle.read_puzzle_file(fetch_puzzle.resolve_puzzle(pid))


print("every tool named in ACQUIRED_BY is a tool that exists")
root = Path(".")
missing = []
for key in p.ACQUIRED_BY:
    if key == "unknown":
        continue
    # The key is a command line: the script is its first word.
    script = key.split()[0]
    if not (root / script).is_file():
        missing.append(key)
# Every channel a tool claims must itself be a declared channel.
bad = [k for k, v in p.ACQUIRED_BY.items() if v["channel"] not in p.RETRIEVAL_CHANNELS]
# Every enum carries prose saying what the value MEANS -- a bare value added
# without one is a value nobody can use correctly.
undocumented = [v for table in (p.GRID_ORIGINS, p.SOLUTION_ORIGINS,
                                p.RETRIEVAL_CHANNELS, p.ANNOTATORS)
                for v, why in table.items() if not (why or "").strip()]
same("no ACQUIRED_BY key names a missing script", len(missing), 0)
same("every tool's channel is a declared RETRIEVAL_CHANNEL", len(bad), 0)
same("every enum value says what it means", len(undocumented), 0)

print("every Gale paper has a provenance row for its link.gale.com permalink")
gale = [x for k, x in f.FILERS.items() if k.startswith("gale") and x.series != "times"]
gale += [x for v in f.ALSO.values() for x in v if x.key.startswith("gale")]
gone = sorted({x.series for x in gale if ("%s" % x.series, "link.gale.com") not in p.ACQUISITION_BY_SOURCE})
same("some Gale papers were checked", len(gale) >= 4, True)
same("no Gale paper lacks a link.gale.com row", len(gone), 0)

print("the sample: every puzzle carries provenance the validator accepts")
no_blocks = flagged_n = 0
for pid in SAMPLE:
    puzzle = load(pid)
    if not (puzzle.get("source") and puzzle.get("solutions")):
        no_blocks += 1
    flagged_n += 1 if p.check(puzzle) else 0
same("every sample puzzle has a source and a solutions block", no_blocks, 0)
same("and not one of them is flagged", flagged_n, 0)

print("one enum, proved by deletion: removing a value flags every puzzle using it")
corpus = [load(pid) for pid in SAMPLE]


def flagged_count():
    return sum(1 for puzzle in corpus if p.check(puzzle))


using = {}
for label, getter in (
        ("gridOrigin", lambda z: (z.get("source") or {}).get("gridOrigin")),
        ("origin", lambda z: (z.get("solutions") or {}).get("origin")),
        ("retrievedFrom", lambda z: (z.get("source") or {}).get("retrievedFrom"))):
    counts = {}
    for puzzle in corpus:
        value = getter(puzzle)
        counts[value] = counts.get(value, 0) + 1
    using[label] = counts

clean = flagged_count()
# Drop the "published" grid value and every sample puzzle using it must be
# refused. If the allowed list were restated anywhere else, they would sail
# through against the copy.
kept = dict(p.GRID_ORIGINS)
p.GRID_ORIGINS = {k: v for k, v in kept.items() if k != "published"}
drop_grid = (flagged_count(), using["gridOrigin"].get("published", 0))
p.GRID_ORIGINS = kept

kept = dict(p.SOLUTION_ORIGINS)
p.SOLUTION_ORIGINS = {k: v for k, v in kept.items() if k != "writeup"}
drop_writeup = (flagged_count(), using["origin"].get("writeup", 0))
p.SOLUTION_ORIGINS = kept

kept = dict(p.RETRIEVAL_CHANNELS)
p.RETRIEVAL_CHANNELS = {k: v for k, v in kept.items() if k != "wayback"}
drop_wayback = (flagged_count(), using["retrievedFrom"].get("wayback", 0))
p.RETRIEVAL_CHANNELS = kept
restored = flagged_count()

same("the sample is clean to begin with", clean, 0)
for name, (got, want) in (("published-grid", drop_grid), ("writeup-solution", drop_writeup),
                          ("wayback-channel", drop_wayback)):
    same(f"dropping the {name} value flags exactly the puzzles that use it", got, want)
same("every value restored, sample clean again", restored, 0)

print("a provenance that contradicts its own file is refused")
# A real Cyclops: Private Eye ships the grid, fifteensquared supplies the
# answers. Two different origins on one puzzle, which is the case a single
# "source" field cannot express and the reason there are three fields.
base = load("cyclops-526")
pristine = len(p.check(base))
really_writeup = (base["solutions"]["origin"] == "writeup"
                  and base["source"]["retrievedFrom"] == "publisher")


def flagged(mutate, puzzle=base):
    puzzle = copy.deepcopy(puzzle)
    mutate(puzzle)
    return p.check(puzzle)


def says(findings, needle):
    return any(needle in x for x in findings)


# THE headline refusal: answers taken from a blog write-up, relabelled as the
# paper's own key. The file's own blog says "writeup".
fnd = flagged(lambda z: z["solutions"].update(origin="published"))
lie_published = (len(fnd), says(fnd, "the file says 'writeup'"))

# A value that is simply not in the enum.
off_enum = len(flagged(lambda z: z["solutions"].update(origin="probably right"))) > 0

# Dropping both blocks entirely.
fnd = flagged(lambda z: (z.pop("source"), z.pop("solutions")))
absent = (len(fnd), says(fnd, "no source or no solutions block"))

# "unsolved" over a grid that is full of answers.
false_unsolved = len(flagged(lambda z: z["solutions"].update(origin="unsolved"))) > 0

# A channel that disagrees with the tool that did the retrieving.
fnd = flagged(lambda z: z["source"].update(retrievedFrom="wayback"))
channel_mismatch = (len(fnd), says(fnd, "reads through 'publisher'"))

# A publisher that disagrees with the series the id states.
wrong_publisher = len(flagged(lambda z: z["source"].update(publisher="Guardian"))) > 0

# A puzzle that does not state its series, or states another than its id.
no_series = len(flagged(lambda z: z.pop("series", None)))
wrong_series = len(flagged(lambda z: z.update(series="cryptic")))

# A model fill relabelled as the publisher's, on a puzzle that says model.
book = load("book-3027")
book_pristine = len(p.check(book))
lied = copy.deepcopy(book)
lied["solutions"]["origin"] = "published"
book_lie = len(p.check(lied)) > 0
# ...and its reconstructed geometry passed off as the printed diagram.
lied = copy.deepcopy(book)
lied["source"]["gridOrigin"] = "published"
book_grid_lie = len(p.check(lied)) > 0

# A model fill over a blog's write-up: the blog is the answer key, so a light
# its parser missed is mended or left blank, never solved over. Refused by the
# validator and so by every write, whichever tool makes it.
blogged = load("timesquick-2471")
blog_pristine = len(p.check(blogged))
solved = p.with_solution_detail(copy.deepcopy(blogged), {
    "model": "opus", "date": "2026-10-09", "check": "24 entries, 0 conflicts"})
solved["solutions"]["origin"] = "model"
blog_model = says(p.check(solved), "retrieved from a blog")
try:
    puzzle_integrity.refuse_bad_write(solved, blogged)
    blog_model_write = "written"
except puzzle_integrity.RefusedWrite as e:
    blog_model_write = "refused" if "retrieved from a blog" in str(e) else "other"

same("the real cyclops passes", pristine, 0)
same("and it really is writeup answers off a publisher channel", really_writeup, True)
same("calling fifteensquared answers the paper's own key is one finding", lie_published[0], 1)
same("and it names the origin the file's own detail implies", lie_published[1], True)
same("a solutions.origin outside the enum is refused", off_enum, True)
same("no source or solutions at all is exactly one finding", absent[0], 1)
same("and it says so plainly", absent[1], True)
same("calling an answered grid unsolved is refused", false_unsolved, True)
same("a channel the fetching tool does not read through is one finding", channel_mismatch[0], 1)
same("and it names the channel that tool really uses", channel_mismatch[1], True)
same("a publisher contradicting the id's series is refused", wrong_publisher, True)
same("a puzzle with no series is no finding here (the format stores none: the id gives it)", no_series, 0)
same("a blog-retrieved write-up passes", blog_pristine, 0)
same("a model fill over a blog's write-up is refused", blog_model, True)
same("and no write can put it on disk", blog_model_write, "refused")
same("a series contradicting the id is one finding", wrong_series, 1)
same("the real book puzzle passes", book_pristine, 0)
same("its model fill cannot be relabelled published", book_lie, True)
same("nor its reconstruction relabelled a printed diagram", book_grid_lie, True)

print("hints say who wrote them, and cannot say it wrongly")
# cryptic-30078 is annotated; `bare` is it with every hint taken out, since
# the burn annotates any real unhinted puzzle out from under the test.
hinted = load("cryptic-30078")
# The burn adds its own model to a puzzle's credit each time it re-annotates, so
# pin the credit the assertions below are written against.
hinted["annotatedBy"] = ["claude-fable-5"]
bare = copy.deepcopy(hinted)
bare.pop("annotatedBy", None)
for e in bare["entries"]:
    e.pop("annotation", None)
hinted_pristine = len(p.check(hinted))
no_credit = len(flagged(lambda z: z.pop("annotatedBy"), hinted))
# An alias is a pointer that moves; the id it resolved to is the record.
alias = len(flagged(lambda z: z.update(annotatedBy=["opus"]), hinted))
not_a_list = len(flagged(lambda z: z.update(annotatedBy="claude-opus-5"), hinted))
human_ok = len(flagged(lambda z: z.update(annotatedBy=["human"]), hinted))
stale = len(flagged(lambda z: z.update(annotatedBy=["claude-opus-5"]), bare))

# A run on a puzzle that had hints adds itself once; a run on a puzzle that had
# none wrote every hint in it, so the old credits go.
once = p.credit_annotator(hinted, "claude-opus-5-5", had_hints=True)
twice = p.credit_annotator(once, "claude-opus-5-5", had_hints=True)
appends = ",".join(twice["annotatedBy"])
fresh = p.credit_annotator(hinted, "claude-opus-5-5", had_hints=False)
restarts = ",".join(fresh["annotatedBy"])
try:
    p.credit_annotator(hinted, "opus", had_hints=True)
    refuses_alias = False
except ValueError:
    refuses_alias = True

# Every write re-derives provenance: the credit survives it, and goes when the
# hints do.
survives_write = p.stamp(hinted, "tools/fetch_puzzle.py").get("annotatedBy")
stripped = copy.deepcopy(hinted)
for e in stripped["entries"]:
    e.pop("annotation", None)
dropped_with_hints = "annotatedBy" in p.stamp(stripped, "tools/fetch_puzzle.py")

same("an annotated puzzle with its credit passes", hinted_pristine, 0)
same("hints with no annotatedBy are one finding", no_credit, 1)
same("an alias is not an author", alias, 1)
same("annotatedBy must be a list", not_a_list, 1)
same("a person is a valid author", human_ok, 0)
same("credit on a puzzle with no hints is refused", stale, 1)
same("a second run by the same model is credited once", appends, "claude-fable-5,claude-opus-5-5")
same("annotating an unhinted puzzle starts the list afresh", restarts, "claude-opus-5-5")
same("crediting an alias raises", refuses_alias, True)
same("a rewrite keeps the credit", str(survives_write), "['claude-fable-5']")
same("and removing the hints removes it", dropped_with_hints, False)

print("a model fill replaced by real answers remembers it was ours")
# book-3027 is a model solve. Swap its solutions detail for a write-up's, as
# fetch_fifteensquared.py does when a blogger posts the answers, and stamp it:
# the block it is written over still says "model", and nothing else will.
book = load("book-3027")
was_model = book["solutions"]["origin"]
confirmed = p.with_solution_detail(copy.deepcopy(book), {
    "blog": "fifteensquared", "url": "https://fifteensquared.net/x",
    "date": "2026-01-01", "check": "checked"})
solutions = p.stamp(confirmed, "tools/file_penguin_puzzle.py")["solutions"]
now = solutions["origin"]
remembers = solutions.get("previousOrigin")
still_model = "previousOrigin" in p.stamp(book, "tools/file_penguin_puzzle.py")["solutions"]
same("the fixture really is a model solve", was_model, "model")
same("its answers are now the write-up's", now, "writeup")
same("and the file remembers they were once ours", remembers, "model")
same("a model fill rewritten as a model fill records nothing", still_model, False)

print("the backfill is idempotent: a second run over written puzzles changes nothing")
out5 = subprocess.run([sys.executable, "tools/backfill_provenance.py", "--dry-run", "--report",
                       "--only", *SAMPLE], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                      text=True).stdout
m = re.search(r"^([0-9]+) puzzles", out5, re.M)
same("all of the sample is read", m.group(1) if m else "", str(len(SAMPLE)))
m = re.search(r"would change ([0-9]+)", out5)
same("nothing left to change", m.group(1) if m else "", "0")

print("the authored puzzle's id parses like any other and stamps as ours")
puzzle = {
    "id": "authored-1", "number": 1, "setter": "x", "date": "2026-01-01",
    "dimensions": {"cols": 1, "rows": 1}, "entries": [],
}
stamped = p.stamp(puzzle, "tools/build_authored_puzzle.py")
same("parse_id reads the authored id's series", series_table.parse_id("authored-1")[0], "authored")
same("and its integer number", series_table.parse_id("authored-1")[1], 1)
same("provenance.series_of_id agrees", p.series_of_id("authored-1"), "authored")
# Fetched ids split on the last hyphen, and a bare pre-namespacing number
# has no series.
same("a hyphenated fetched id still splits on the last hyphen",
     series_table.parse_id("everyman-4165")[0], "everyman")
same("with an integer number", series_table.parse_id("everyman-4165")[1], 4165)
same("a bare pre-namespacing number still names no series", series_table.parse_id("30089")[0], None)
same("and still parses to an integer", series_table.parse_id("30089")[1], 30089)
same("stamping an authored puzzle doesn't crash and marks the grid as ours, not the publisher's",
     stamped["source"]["gridOrigin"], "authored")

print("every source key the schema allows survives a write")
puzzle = {"id": "canberra-770331", "number": 770331, "date": "1977-03-31", "entries": [],
          "source": {"url": "https://trove.nla.gov.au/newspaper/article/110731095",
                     "reprintOf": "times-14510", "feedId": "x"}}
reprint_of = p.stamp(puzzle, "tools/file_trove_puzzles.py")["source"].get("reprintOf")
# A key derive() neither works out nor carries is dropped on every write.
schema = json.load(open("tools/data/puzzle.schema.json"))
derived = set(p.derive(puzzle, "tools/file_trove_puzzles.py", "2026-10-04")["source"]) | {"book"}
lost = sorted(set(schema["$defs"]["source"]["properties"]) - derived - set(p.SOURCE_CARRIED))
same("a write keeps source.reprintOf", reprint_of, "times-14510")
same("every schema source key is derived or in SOURCE_CARRIED", len(lost), 0)

print("a filer's page at a host the table has no row for is refused, not stamped unknown")


def stamped_from(url, tool="tools/file_archive_org_puzzles.py", held=None):
    source = {"url": url, **({"acquiredBy": held} if held else {})}
    try:
        s = p.stamp({"id": "times-17246", "number": 17246, "entries": [], "source": source}, tool)["source"]
        return s["retrievedFrom"]
    except ValueError as e:
        return "refused" if "ACQUISITION_BY_SOURCE" in str(e) else repr(e)


same("a Gale Times page is an OCR'd newspaper page",
     stamped_from("https://go.gale.com/ps/retrieve.do?docId=GALE%7CIF0500004465&prodId=TTDA"), "newspaper")
same("a filer's first write from a host with no row is refused",
     stamped_from("https://example.org/page"), "refused")
same("another tool's file is left to derive as before",
     stamped_from("https://example.org/page", held="tools/fetch_puzzle.py"), "unknown")

print("provenance: all checks passed" if not fails else f"provenance: {fails} FAILED")
sys.exit(1 if fails else 0)
