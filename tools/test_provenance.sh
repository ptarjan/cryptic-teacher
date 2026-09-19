#!/bin/bash
# Does provenance actually REFUSE a puzzle that lies about where it came from?
#
#     bash tools/test_provenance.sh
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
#      over a solutionSource that says "model" is the exact failure provenance
#      exists to prevent, and it must be refused rather than preferred — as
#      must "unsolved" over a grid full of answers, and a retrieval channel
#      that disagrees with the tool that did the retrieving.
#
#   4. THE REAL CORPUS PASSES. Run against the files on disk, because a rule
#      that holds only on fixtures is a rule the corpus has not been held to.
set -uo pipefail
cd "$(dirname "$0")/.."
REPO="$PWD"
fails=0
same() { if [ "$2" = "$3" ]; then echo "  ok: $1"; else
  echo "  FAIL: $1"$'\n'"    want $3"$'\n'"    got  $2"; fails=$((fails + 1)); fi; }
field() { awk -v k="$1" '$1==k {print $2}' <<<"$2"; }

echo "every tool named in ACQUIRED_BY is a tool that exists"
out=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
from pathlib import Path
import provenance as p

root = Path(".")
missing = []
for key in p.ACQUIRED_BY:
    if key == "unknown":
        continue
    # The key is a command line: the script is its first word.
    script = key.split()[0]
    if not (root / script).is_file():
        missing.append(key)
print("TOOLS", len(p.ACQUIRED_BY))
print("MISSING", len(missing), *missing)
# Every channel a tool claims must itself be a declared channel.
bad = [k for k, v in p.ACQUIRED_BY.items() if v["channel"] not in p.RETRIEVAL_CHANNELS]
print("BAD_CHANNEL", len(bad), *bad)
# Every enum carries prose saying what the value MEANS -- a bare value added
# without one is a value nobody can use correctly.
undocumented = [v for table in (p.GRID_ORIGINS, p.SOLUTION_ORIGINS,
                                p.RETRIEVAL_CHANNELS)
                for v, why in table.items() if not (why or "").strip()]
print("UNDOCUMENTED", len(undocumented), *undocumented)
PY
)
same "no ACQUIRED_BY key names a missing script" "$(field MISSING "$out")" "0"
same "every tool's channel is a declared RETRIEVAL_CHANNEL" "$(field BAD_CHANNEL "$out")" "0"
same "every enum value says what it means" "$(field UNDOCUMENTED "$out")" "0"

echo "the corpus itself: every puzzle carries provenance the validator accepts"
out2=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
import fetch_puzzle
import provenance as p

missing = flagged = total = 0
for path in fetch_puzzle.puzzle_files():
    puzzle = fetch_puzzle.read_puzzle_file(path)
    total += 1
    if not puzzle.get("provenance"):
        missing += 1
    flagged += 1 if p.check(puzzle) else 0
print("TOTAL", total)
print("MISSING", missing)
print("FLAGGED", flagged)
PY
)
same "every puzzle has a provenance block" "$(field MISSING "$out2")" "0"
same "and not one of them is flagged" "$(field FLAGGED "$out2")" "0"

echo "one enum, proved by deletion: removing a value flags every puzzle using it"
out3=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
import fetch_puzzle
import provenance as p

corpus = [fetch_puzzle.read_puzzle_file(path)
          for path in fetch_puzzle.puzzle_files()]


def flagged():
    return sum(1 for puzzle in corpus if p.check(puzzle))


using = {}
for field, table in (("gridOrigin", p.GRID_ORIGINS),
                     ("solutionOrigin", p.SOLUTION_ORIGINS),
                     ("retrievedFrom", p.RETRIEVAL_CHANNELS)):
    counts = {}
    for puzzle in corpus:
        value = (puzzle.get("provenance") or {}).get(field)
        counts[value] = counts.get(value, 0) + 1
    using[field] = counts

print("CLEAN", flagged())
# "published" grids are 15,931 of the corpus; drop the value and every one of
# them must be refused. If the allowed list were restated anywhere else, they
# would sail through against the copy.
kept = dict(p.GRID_ORIGINS)
p.GRID_ORIGINS = {k: v for k, v in kept.items() if k != "published"}
print("DROP_PUBLISHED_GRID", flagged(), using["gridOrigin"].get("published", 0))
p.GRID_ORIGINS = kept

kept = dict(p.SOLUTION_ORIGINS)
p.SOLUTION_ORIGINS = {k: v for k, v in kept.items() if k != "writeup"}
print("DROP_WRITEUP", flagged(), using["solutionOrigin"].get("writeup", 0))
p.SOLUTION_ORIGINS = kept

kept = dict(p.RETRIEVAL_CHANNELS)
p.RETRIEVAL_CHANNELS = {k: v for k, v in kept.items() if k != "wayback"}
print("DROP_WAYBACK", flagged(), using["retrievedFrom"].get("wayback", 0))
p.RETRIEVAL_CHANNELS = kept

print("RESTORED", flagged())
PY
)
same "the corpus is clean to begin with" "$(field CLEAN "$out3")" "0"
for case in DROP_PUBLISHED_GRID:published-grid DROP_WRITEUP:writeup-solution DROP_WAYBACK:wayback-channel; do
  key=${case%%:*}; name=${case##*:}
  got=$(awk -v k="$key" '$1==k {print $2}' <<<"$out3")
  want=$(awk -v k="$key" '$1==k {print $3}' <<<"$out3")
  same "dropping the $name value flags exactly the puzzles that use it" "$got" "$want"
done
same "every value restored, corpus clean again" "$(field RESTORED "$out3")" "0"

echo "a provenance that contradicts its own file is refused"
out4=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
import copy
import fetch_puzzle
import provenance as p

# A real Cyclops: Private Eye ships the grid, fifteensquared supplies the
# answers. Two different origins on one puzzle, which is the case a single
# "source" field cannot express and the reason there are three fields.
base = fetch_puzzle.read_puzzle_file(fetch_puzzle.PUZZLE_DIR / "cyclops-526.json")
print("PRISTINE", len(p.check(base)))
print("REALLY_WRITEUP", (base["provenance"]["solutionOrigin"] == "writeup"
                         and base["provenance"]["retrievedFrom"] == "publisher"))


def flagged(mutate):
    puzzle = copy.deepcopy(base)
    mutate(puzzle)
    return p.check(puzzle)


def says(findings, needle):
    return any(needle in f for f in findings)


# THE headline refusal: answers taken from a blog write-up, relabelled as the
# paper's own key.
f = flagged(lambda z: z["provenance"].update(solutionOrigin="published"))
print("LIE_PUBLISHED", len(f), says(f, "solutionSource.kind is 'fifteensquared'"))

# A value that is simply not in the enum.
f = flagged(lambda z: z["provenance"].update(solutionOrigin="probably right"))
print("OFF_ENUM", len(f) > 0)

# Dropping the block entirely.
f = flagged(lambda z: z.pop("provenance"))
print("ABSENT", len(f), says(f, "no provenance object"))

# "unsolved" over a grid that is full of answers.
f = flagged(lambda z: z["provenance"].update(solutionOrigin="unsolved"))
print("FALSE_UNSOLVED", len(f) > 0)

# A channel that disagrees with the tool that did the retrieving.
f = flagged(lambda z: z["provenance"].update(retrievedFrom="wayback"))
print("CHANNEL_MISMATCH", len(f), says(f, "reads through 'publisher'"))

# A capture URL on a puzzle read from the publisher, where sourceUrl already IS
# the address fetched -- two fields describing different retrievals.
f = flagged(lambda z: z["provenance"].update(retrievedUrl="https://web.archive.org/x"))
print("STRAY_CAPTURE_URL", len(f) > 0)

# A publisher that disagrees with the series the id states.
f = flagged(lambda z: z["provenance"].update(publisher="Guardian"))
print("WRONG_PUBLISHER", len(f) > 0)

# A model fill relabelled as the publisher's, on a puzzle that says model.
book = fetch_puzzle.read_puzzle_file(fetch_puzzle.PUZZLE_DIR / "book-3027.json")
print("BOOK_PRISTINE", len(p.check(book)))
lied = copy.deepcopy(book)
lied["provenance"]["solutionOrigin"] = "published"
print("BOOK_LIE", len(p.check(lied)) > 0)
# ...and its reconstructed geometry passed off as the printed diagram.
lied = copy.deepcopy(book)
lied["provenance"]["gridOrigin"] = "published"
print("BOOK_GRID_LIE", len(p.check(lied)) > 0)
PY
)
same "the real cyclops passes" "$(field PRISTINE "$out4")" "0"
same "and it really is writeup answers off a publisher channel" \
  "$(field REALLY_WRITEUP "$out4")" "True"
same "calling fifteensquared answers the paper's own key is one finding" \
  "$(field LIE_PUBLISHED "$out4")" "1"
same "and the finding names the solutionSource it contradicts" \
  "$(awk '$1=="LIE_PUBLISHED" {print $3}' <<<"$out4")" "True"
same "a solutionOrigin outside the enum is refused" "$(field OFF_ENUM "$out4")" "True"
same "no provenance at all is exactly one finding" "$(field ABSENT "$out4")" "1"
same "and it says so plainly" "$(awk '$1=="ABSENT" {print $3}' <<<"$out4")" "True"
same "calling an answered grid unsolved is refused" "$(field FALSE_UNSOLVED "$out4")" "True"
same "a channel the fetching tool does not read through is one finding" \
  "$(field CHANNEL_MISMATCH "$out4")" "1"
same "and it names the channel that tool really uses" \
  "$(awk '$1=="CHANNEL_MISMATCH" {print $3}' <<<"$out4")" "True"
same "a capture URL on a publisher fetch is refused" \
  "$(field STRAY_CAPTURE_URL "$out4")" "True"
same "a publisher contradicting the id's series is refused" \
  "$(field WRONG_PUBLISHER "$out4")" "True"
same "the real book puzzle passes" "$(field BOOK_PRISTINE "$out4")" "0"
same "its model fill cannot be relabelled published" "$(field BOOK_LIE "$out4")" "True"
same "nor its reconstruction relabelled a printed diagram" \
  "$(field BOOK_GRID_LIE "$out4")" "True"

echo "the backfill is idempotent: a second run over a written corpus changes nothing"
out5=$(python3 tools/backfill_provenance.py --dry-run --report 2>&1)
same "nothing left to change" \
  "$(grep -oE 'would change [0-9]+' <<<"$out5" | awk '{print $3}')" "0"

[ "$fails" = 0 ] && echo "provenance: all checks passed" || echo "provenance: $fails FAILED"
exit $((fails > 0))
