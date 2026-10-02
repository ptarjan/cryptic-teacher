#!/bin/bash
# Does tools/times_grids.py rebuild the right grid, and admit it when it cannot?
#
#     bash tools/test_times_grids.sh
#
# This module turns a blog post into a GRID that gets published as if The Times
# had printed it, and a wrong grid is not obviously wrong to anyone looking at
# it. Two ways to get that wrong quietly: narrowing a shortlist with the
# answers and keeping a candidate whose crossings disagree, and reporting a
# search that ran out of budget as a puzzle no grid fits — the first ships a
# lie, the second sends someone back to re-read a blog post that was fine.
#
# The fixture is a hand-built 5x5 with a made-up series, so nothing here
# depends on the corpus, on the cache, or on how long a real search takes.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() {  # check <what> <expected> <got>
  if [ "$2" = "$3" ]; then echo "ok   $1"; else
    echo "FAIL $1: expected [$2], got [$3]"; fails=$((fails + 1)); fi
}

out=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
import reconstruct_grid as rg
import times_grids as T
import parse_timesforthetimes as P

TINY = ("..#..",
        ".....",
        "#...#",
        ".....",
        "..#..")
T.SIZE["Test"] = 5

# Letters that actually constrain each other: every white cell gets its own,
# so two lights that cross agree on one square and on no other.
letter = lambda y, x: chr(ord("A") + (y * 5 + x) % 26)
cells = rg.light_cells(TINY)
rec = {"series": "Test", "entries": [
    {"number": n, "direction": d, "answer": "".join(letter(*c) for c in cs)}
    for (n, d), cs in cells.items()]}

# The light list this module feeds the solver must BE the one the grid would
# print, in printed order. A different order is a different puzzle.
print("PRINTED_ORDER", T.triples(rec) == rg.lights_from_grid(TINY))

grids, how = T.solve(rec)
print("SOLVED_HOW", how)
print("SOLVED_IS_IT", len(grids) == 1 and grids[0] == TINY)

print("FIT_TRUE", T.answers_fit(TINY, rec))
clash = {"series": "Test", "entries": [dict(e) for e in rec["entries"]]}
clash["entries"][0]["answer"] = "Z" * len(clash["entries"][0]["answer"])
print("FIT_CLASH", T.answers_fit(TINY, clash))

# Out of budget is not the same fact as no grid fits, and the caller acts on
# the difference: one is a knob, the other is a blog post to go and re-read.
print("BUDGET", T.solve(rec, max_nodes=1)[1])

# A light list no grid of this size can print is a light list, not a budget:
# it must read as "no grid" even though the search also finished, because the
# only fix for it is to go back to the blog post.
toolong = {"series": "Test", "entries": [
    {"number": 1, "direction": "across", "answer": "A" * 9}]}
print("TOOLONG", T.solve(toolong)[1])

# A run over the whole corpus is tens of hours and gets killed. The next one
# has to keep what the last one solved: read back the ids it wrote, tolerate
# the torn last line a kill leaves, and append rather than truncate.
import json, pathlib, tempfile
tmp = pathlib.Path(tempfile.mkdtemp()) / "grids.jsonl"
tmp.write_text(json.dumps({"post_id": 111}) + "\n" + '{"post_id": 222, "gri')
T.OUT = tmp
print("RESUME", sorted(T.solved_already()))
T.open_out(False).close()
print("KEPT", tmp.read_text().startswith('{"post_id": 111}'))
T.open_out(True).close()
print("FRESH", tmp.read_text())

# A run skips every post with an attempt on record, whatever search, budget
# or settle() wrote it: the failures are the expensive ones — a Jumbo spends
# the whole budget and finds nothing — and a code change that could fix them
# retries them once, by hand, naming the outcomes it can fix.
T.ATTEMPTS = tmp.parent / "attempts.jsonl"
T.ATTEMPTS.write_text("".join(json.dumps({"post_id": pid, "how": how, "max_nodes": n}) + "\n"
    for pid, how, n in ((1, "no grid", 6000000), (2, "truncated", 400000),
                        (3, "refused: 5 down EJTY fits no word", 6000000),
                        (4, "truncated", 6000000), (4, "no grid", 6000000))))
print("TRIED", sorted(T.attempted()))
print("RETRY_SOME", sorted({1, 2, 3, 4} - T.attempted(retry=("refused", "truncated"))))
print("RETRY_ALL", sorted(T.attempted(retry=())))
# A linked answer the post prints whole (the Times and Telegraph parsers keep
# its letters and count, no word breaks) is split by the grid: the search
# that left it out fitted no grid for want of its lights. A post holding one
# that a search tried without splitting it is tried again.
two = [k for k in cells if k[1] == "across" and len(cells[k]) == 5]
whole = "".join(e["answer"] for e in rec["entries"] if (e["number"], e["direction"]) in two)
linked = {"series": "Test", "entries": [e for e in rec["entries"]
                                        if (e["number"], e["direction"]) not in two],
          "unsplit": [{"lights": [list(k) for k in two], "answer": whole,
                       "enumeration": "5,5", "clue": "Linked (5,5)"}]}
grids, how = T.solve(dict(linked))
print("LINKED", grids == [TINY], how)
split = T.split_by(linked, TINY)
print("LINKED_SPLIT", "unsplit" in split,
      [e["clue"] for e in T.printed(split) if (e["number"], e["direction"]) in two]
      == ["Linked (5,5)", f"See {two[0][0]}"])
# The pointer names the direction where the number has both, and the leader
# keeps the answer as printed (toughie-641's 1-down SICK AS A DOG).
both = T.with_split({"entries": [{"number": 1, "direction": "across", "answer": "SEMI"}],
                     "unsplit": [{"clue": "Ill (4,2,1,3)", "enumeration": "4,2,1,3",
                                  "answer_printed": "SICK AS A DOG"}]},
                    ([((1, "down"), "SICK"), ((16, "across"), "ASADOG")],))
print("LINKED_POINTER", [(e["clue"], e.get("answer_spaced")) for e in both["entries"][1:]])
# "24d" typed in the Across list: the parser keeps the heading beside the
# suffix, and the grid decides which was mistyped.
last = max(k for k in cells if k[1] == "across")
typed = {"series": "Test", "entries": [
    dict(e, direction="down", heading="across") if (e["number"], e["direction"]) == last else e
    for e in rec["entries"]]}
grids, how = T.solve(typed)
print("HEADED", grids == [TINY], how, T.headed_by(dict(typed), TINY)["entries"][-1].get("heading"))

# Answers that refute EVERY candidate are the opposite of an ambiguous grid:
# the right grid is not in the list, so the light list or an answer is wrong.
# This said "crossings ruled out none", which reads as the exact opposite, and
# the one puzzle it fired on got quoted as a grid the crossings could not
# settle. Two candidates, neither of which the answers fit.
real = rg.reconstruct
# The search given the answers finds neither; without them, both.
rg.reconstruct = lambda *a, **k: (
    [] if k.get("words") else
    [TINY, (".#...", ".....", "#...#", ".....", "...#.")], {"truncated": False})
print("REFUTED", T.solve(clash)[1])
rg.reconstruct = real

# A puzzle's searches share one budget. A list no grid fits runs a dozen or
# more (retries, each freed light, each split of a linked answer); each
# bounded alone, a 23x23 spent ten silent minutes in them all. Here every
# search spends all it is allowed and finds nothing, so only a shared budget
# stops the chain -- and each search, and the post, is named on stderr.
import io, sys
spent = []
def greedy(*a, **k):
    spent.append(k["max_nodes"])
    return [], {"nodes": k["max_nodes"], "truncated": False}
rg.reconstruct, err, sys.stderr = greedy, sys.stderr, io.StringIO()
try:
    cap = 4 * 1000                  # PUZZLE_SEARCHES searches of max_nodes
    how = T.solve(dict(clash, post_id=4242), max_nodes=1000)[1]
    print("BOUNDED", sum(spent) <= cap, how.split(":")[0])
    spent.clear()
    many = [dict(g, enumeration=",".join("1" * 10)) for g in linked["unsplit"]]
    how = T.solve(dict(linked, unsplit=many, post_id=4242), max_nodes=1000)[1]
    print("BOUNDED_LINKED", sum(spent) <= cap, how.split(":")[0])
finally:
    logged, sys.stderr = sys.stderr.getvalue(), err
print("LOGGED", "post 4242 answers in:" in logged)
rg.reconstruct = real

# The answers are written in DURING the search: a light whose letters clash
# with a crossing one is never placed, so the real search, given the answers,
# returns no grid the answers do not fit.
spec = T.triples(clash)
words = [e["answer"] for e in T.printed(clash)]
print("WORDS_PRUNE", rg.reconstruct(spec, cols=5, rows=5, words=words)[0],
      len(rg.reconstruct(spec, cols=5, rows=5)[0]))

# Numbering is dense: a list that skips a number lost a light, and says so
# without searching.
gappy = {"series": "Test", "entries": [e for e in rec["entries"] if e["number"] != 2]}
print("GAP", T.solve(gappy)[1])

# The cap on a line of blocks is enforced, and only as long as the caller asks:
# this grid's only fill has a row of three.
BARS = (".....", ".###.", ".....", ".###.", ".....")
bl = rg.lights_from_grid(BARS)
print("CAP", rg.reconstruct(bl, 5, 5, strict=False)[0] == [BARS],
      rg.reconstruct(bl, 5, 5, strict=False, max_black_run=2)[0],
      rg.reconstruct(bl, 5, 5, strict=False, max_black_run=3)[0] == [BARS])

# A grid symmetric about a diagonal and not under a half turn -- the shape
# some Quick Cryptics print -- is rebuilt, and said to be; a grid with no
# symmetry of any kind is what a lost light builds, and is not taken.
def solved(grid, **edit):
    cs = rg.light_cells(grid)
    r = {"series": "Test", "entries": [
        {"number": k[0], "direction": k[1], "enumeration": None,
         "answer": "".join(letter(*c) for c in v)} for k, v in cs.items()]}
    return r, T.solve(r)
DIAG = (".....", ".....", "...#.", "..#..", ".....")
NONE = (".....", ".#...", "...#.", ".#...", "..#..")
r, (g, how) = solved(DIAG)
print("DIAGONAL", how, g == [DIAG], rg.reconstruct(rg.lights_from_grid(DIAG), 5, 5)[0])
print("NO_SYMMETRY", T.solve(solved(NONE)[0])[1].startswith("unique"))

# An answer blogged at the wrong length under an enumeration that has it right
# is rebuilt at the enumeration's length; with no enumeration to say so, one
# wrong light is still found, when freeing it lands on one grid.
wrong = {"series": "Test", "entries": [dict(e) for e in rec["entries"]]}
first = T.printed(wrong)[0]
first["enumeration"] = str(len(first["answer"]))
first["answer"] += "Q"
g, how = T.solve(wrong)
print("ENUM_LENGTH", how, g == [TINY])
# An answer cut off at a break in a phrase still starts its light; a
# one-word answer under a longer count is a typo and gives no letters.
print("ENUM_CUT", T.by_enumeration({"series": "Test", "entries": [
    {"number": 1, "direction": "across", "answer": "WORST", "clue": "c (5-4,8)",
     "enumeration": "5-4,8"},
    {"number": 2, "direction": "down", "answer": "STAVE", "clue": "c (6)", "enumeration": "6"},
    {"number": 3, "direction": "down", "answer": "CAT", "clue": "c (3)", "enumeration": "3"}]}))
first["enumeration"] = None
g, how = T.solve(wrong)
print("ONE_WRONG", how, g == [TINY])

# A light printed under the wrong number keeps its length and letters, but the
# number pins where it starts, so no grid fits it even with its letters freed:
# two 10-acrosses and no 11 (timesjumbo-1334), and 7-down under a 7-across it
# does not start with (timesjumbo-1304's 14-down MALONE). Its number is freed,
# and the grid gives the number back, to the solver and to the filer alike.
def misnumbered(key, to):
    r = {"series": "Test", "entries": [dict(e) for e in rec["entries"]]}
    for e in r["entries"]:
        if (e["number"], e["direction"]) == key:
            e["number"] = to
    return r
for name, key, to in (("MISNUMBERED_TWICE", (11, "across"), 10),
                      ("MISNUMBERED_CLASH", (8, "down"), 7)):
    r = misnumbered(key, to)
    print(name, T.numbering_faults(T.triples(r), [e["answer"] for e in T.printed(r)]) != [],
          T.numbered_by(misnumbered(key, to), TINY)["entries"] == rec["entries"])
    g, how = T.solve(r)
    print(name + "_SOLVED", how, g == [TINY], r["entries"] == rec["entries"])

# A grid taken despite an answer that disagrees with it carries the corrected
# answer, and only when the correction is determined: each letter a correct
# crossing's or the blogger's own, the result a real word. DIAG's 5 down is
# EJOTY; its middle square is crossed by nothing.
def rec_of(grid, **typo):
    r = {"series": "Test", "entries": [
        {"number": k[0], "direction": k[1], "enumeration": None,
         "answer": "".join(letter(*c) for c in v)} for k, v in rg.light_cells(grid).items()]}
    for e in r["entries"]:
        e["answer"] = typo.get(f"{e['number']}{e['direction'][0]}", e["answer"])
    return r
vocab = {5: {"EJOTY"}}
fixes = lambda r, v=vocab: T.settle(DIAG, r, v)
show = lambda f: (" ".join(f"{c['number']}{c['direction'][0]}:{c['blogged']}>{c['answer']}"
                           for c in f[0]) if f[1] is None else f[1])
print("FIX_NONE", show(fixes(rec_of(DIAG))))
print("FIX_LETTER", show(fixes(rec_of(DIAG, **{"5d": "EXOTY"}))))
print("FIX_SWAP", show(fixes(rec_of(DIAG, **{"5d": "EOJTY"}))))
print("FIX_LENGTH", show(fixes(rec_of(DIAG, **{"5d": "EJOTYEJOTY"}))))
print("FIX_UNCHECKED", show(fixes(rec_of(DIAG, **{"5d": "EJTY"}))))
print("FIX_NOT_A_WORD", show(fixes(rec_of(DIAG, **{"5d": "EXOTY"}), {5: set()})))
print("FIX_EITHER", show(fixes(rec_of(DIAG, **{"5d": "EXOTY"}), {5: {"EJOTY", "FGHIX"}})))
print("FIX_TWO_WORDS", show(fixes(rec_of(DIAG, **{"5d": "EOJTY"}), {5: {"EJOTY", "EJJTY", "FGHIO"}})))
# A count typed over the same short answer -- THEOREM (7) in an eight-letter
# light -- is the blogger's slip twice, so it cannot veto the correction; a
# phrase the lexicon only knows word by word (TAKES STOCK) is still real.
def counted(blog, enum):
    r = rec_of(DIAG, **{"5d": blog})
    next(e for e in r["entries"] if (e["number"], e["direction"]) == (5, "down"))["enumeration"] = enum
    return r
print("FIX_DROPPED_COUNT", show(fixes(counted("EOTY", "4"))))
print("FIX_PHRASE", show(fixes(counted("EOTY", "2,2"), {2: {"EJ"}, 3: {"OTY"}})))
print("FIX_PHRASE_ONE_WORD", show(fixes(counted("EOTY", "4"), {2: {"EJ"}, 3: {"OTY"}})))
print("FIX_LENGTH_EITHER", show(fixes(counted("EOTY", "5"), {5: {"EJOTY", "EJETY"}})))
blank = rec_of(DIAG, **{"5d": ""})
print("FIX_BLANK", T.answers_fit(DIAG, blank), show(fixes(blank)))
print("FIX_WRONG_GRID", show(T.settle(TINY, rec_of(DIAG), vocab))[:39])

# The job itself applies it: a run writes the corrections into the grid row,
# answers() reads them back, a refused puzzle gets no row and its attempt says
# why, and --resettle does the same to grids a run wrote before.
d = pathlib.Path(tempfile.mkdtemp())
T.PARSED, T.OUT, T.ATTEMPTS = d / "parsed.jsonl", d / "grids.jsonl", d / "attempts.jsonl"
T.LEXICON, T.ANSWERS = d / "none.tsv", d / "answers.json"
post = lambda pid, r, clue: dict(r, post_id=pid, slug=str(pid), number=pid, date="2026-01-0" + str(pid),
                                 entries=[dict(e, clue=clue) for e in r["entries"]])
typo = post(1, rec_of(TINY), "a clue")
T.printed(typo)[5]["answer"] = "Z" + T.printed(typo)[5]["answer"][1:]
lone = post(2, rec_of(TINY), "a clue")
T.printed(lone)[6]["answer"] = "Z" + T.printed(lone)[6]["answer"][1:]
# No clues, so never solved; but the one answer it blogs is a word.
elsewhere = post(3, dict(rec_of(TINY), entries=[T.printed(rec_of(TINY))[5]]), None)
T.PARSED.write_text("".join(json.dumps(r) + "\n" for r in (typo, elsewhere)))
T.run()
rows = [json.loads(l) for l in T.OUT.open()]
print("RUN_ROW", [(r["post_id"], [(c["blogged"], c["answer"]) for c in r.get("corrections", [])]) for r in rows])
print("RUN_ANSWERS", T.answers_fit(TINY, {"entries": T.answers(typo, rows[0])}))
T.PARSED.write_text("".join(json.dumps(r) + "\n" for r in (lone, elsewhere)))
T.OUT.write_text("")
T.run(fresh=True)
print("RUN_REFUSED", T.OUT.read_text() == "", json.loads(T.ATTEMPTS.read_text())["how"][:7])
# A failure already tried is skipped, unless the run is told to retry it,
# and a grid already written never is.
calls = []
stub = lambda rec, max_nodes: (calls.append(rec["post_id"]), ([], "no grid"))[1]
T.run(solver=stub)
skipped = list(calls)
T.run(solver=stub, retry=())
print("RETRY_FAILED", skipped, calls)
# An answer settled from the wordplay rebuilds the refused puzzle when it is
# retried.
k = T.printed(lone)[6]
T.ANSWERS.write_text(json.dumps({"_doc": "", "2": {"_puzzle": "", f"{k['number']} {k['direction']}": {
    "answer": T.printed(rec_of(TINY))[6]["answer"], "wordplay": ""}}}))
T.run(retry=())
print("SETTLED", [(r["post_id"], [c["blogged"][0] for c in r.get("corrections", [])])
                  for r in map(json.loads, T.OUT.open())])
T.ANSWERS.unlink()
# More wrong answers than typos explain is a wrong grid.
messy = post(4, rec_of(TINY), "a clue")
for e in T.printed(messy)[:T.MAX_WRONG + 1]:
    e["answer"] += "Q"
T.PARSED.write_text("".join(json.dumps(r) + "\n" for r in (typo, messy, elsewhere)))
T.OUT.write_text("".join(json.dumps({"post_id": r["post_id"], "series": "Test", "number": 1,
                                     "date": None, "grid": list(TINY), "how": "unique"}) + "\n"
                         for r in (typo, messy, elsewhere)))
T.ATTEMPTS.write_text("")
T.resettle()
print("RESETTLE", [(r["post_id"], len(r.get("corrections", []))) for r in map(json.loads, T.OUT.open())],
      [json.loads(l)["post_id"] for l in T.ATTEMPTS.open()])

# Barred puzzles have no black squares, so numbering inverts to nothing. They
# are parsed and then deliberately not sized here; a typo in the name would
# look identical, so check both halves.
print("BARRED", sorted(s for s in P.SERIES.values() if s not in T.SIZE), sorted(T.BARRED))
# The Sunday Times's Christmas puzzle is a Jumbo in the weekly's numbering:
# the entry count, not the label, sizes it.
many = lambda series, k: {"series": series, "entries": [{}] * k}
print("SIZE", T.size(many("Weekend Cryptic", 30)), T.size(many("Weekend Cryptic", 60)),
      T.size(many("Daily Cryptic", 60)), T.size(many("Monthly Club Special", 30)),
      T.size(many("TLS Crossword", 30)))
print("SUPERJUMBO", T.size(many("timesjumbo", 62)), T.size(many("timesjumbo", 90)),
      T.size(many("Jumbo Cryptic", 90)))
e = {"number": 1, "direction": "across", "answer": "AB"}
print("CLUES", T.has_clues({"entries": [dict(e, clue="Clue (2)")] * 10}),
      T.has_clues({"entries": [dict(e, clue="")] * 10}))
PY
)
echo "$out"
field() { awk -v k="$1" '$1==k {$1=""; sub(/^ /,""); print}' <<<"$out"; }

check "the solver is fed the light list the grid would print" True "$(field PRINTED_ORDER)"
check "a complete light list pins one grid down" unique "$(field SOLVED_HOW)"
check "and it is the grid the lights came from" True "$(field SOLVED_IS_IT)"
check "answers that agree at every crossing fit" True "$(field FIT_TRUE)"
check "one answer that disagrees at a crossing does not" False "$(field FIT_CLASH)"
check "a search that ran out of budget says so" truncated "$(field BUDGET)"
check "a light no grid could hold reads as no grid, not as truncated" \
      "no grid" "$(field TOOLONG)"
check "a killed run reads back what it already solved" "[111]" "$(field RESUME)"
check "and appends to it rather than truncating" True "$(field KEPT)"
check "only --fresh starts the file over" "" "$(field FRESH)"
check "a post with any attempt on record is not tried again" "[1, 2, 3, 4]" "$(field TRIED)"
check "a retry names the outcomes it retries, by the latest attempt" "[2, 3]" "$(field RETRY_SOME)"
check "an empty retry retries every failure" "[]" "$(field RETRY_ALL)"
check "a linked answer printed whole is split by the grid that fits" \
      "True unique, linked answer split by the grid" "$(field LINKED)"
check "the split record carries the clue on its leader and See N on the rest" \
      "False True" "$(field LINKED_SPLIT)"
check "a pointer names its direction where the number has both; the leader keeps the printed answer" \
  "[('Ill (4,2,1,3)', 'SICK AS A DOG'), ('See 1 down', None)]" "$(field LINKED_POINTER)"
check "a suffix against its heading: the grid takes the heading's direction" \
      "True unique, directions as headed None" "$(field HEADED)"
check "answers refuting every candidate does not read as an unsettled tie" \
      "answers fit none of 2" "$(field REFUTED)"
check "the search itself refuses a grid its answers clash in" "[] 1" "$(field WORDS_PRUNE)"
check "a list that skips a number is no grid, found without search" "no grid: no light numbered 2" "$(field GAP)"
check "a line of blocks past the cap is refused, one at the cap is not" "True [] True" "$(field CAP)"
check "a diagonal-symmetric grid is rebuilt, and no half-turn one fits it" \
      "unique, mirror symmetry True []" "$(field DIAGONAL)"
check "a grid with no symmetry at all is not taken" False "$(field NO_SYMMETRY)"
check "an answer at the wrong length is rebuilt at its enumeration's" \
      "unique, enumeration length True" "$(field ENUM_LENGTH)"
check "an answer cut off inside a phrase keeps its letters; a short one-word answer does not" \
  "([(1, 'across', 17), (2, 'down', 6), (3, 'down', 3)], ['WORST', None, 'CAT'])" "$(field ENUM_CUT)"
check "one wrong light with no enumeration is found by freeing it" \
      "unique, one light wrong at 1 across True" "$(field ONE_WRONG)"
check "two lights under one number are told apart by the grid" "True True" "$(field MISNUMBERED_TWICE)"
check "and the grid numbers the second one" \
      "unique, number freed: 10 across to 11 True True" "$(field MISNUMBERED_TWICE_SOLVED)"
check "a light under a number another light starts differently is renumbered by the grid" \
      "True True" "$(field MISNUMBERED_CLASH)"
check "and the grid rebuilds with it renumbered" \
      "unique, number freed: 7 down to 8 True True" "$(field MISNUMBERED_CLASH_SOLVED)"
check "answers that fit the grid need no correction" "" "$(field FIX_NONE)"
check "a letter a crossing contradicts is corrected from the crossing" \
      "5d:EXOTY>EJOTY" "$(field FIX_LETTER)"
check "two letters typed the wrong way round are put back" \
      "5d:EOJTY>EJOTY" "$(field FIX_SWAP)"
check "an answer at the wrong length is corrected to the light's" \
      "5d:EJOTYEJOTY>EJOTY" "$(field FIX_LENGTH)"
check "a short answer no word corrects is blanked for the answer fill, not filled in" \
      "5d:EJTY>" "$(field FIX_UNCHECKED)"
check "a correction that is not a word is refused" \
      "refused: 5 down EXOTY fits no word; 6 across FGHIJ fits no word" "$(field FIX_NOT_A_WORD)"
check "two corrections that are both words are refused" \
      "refused: answers correct 5 down EJOTY or 6 across FGHIX" "$(field FIX_EITHER)"
check "a light that could be either of two words is refused, whatever else fits" \
      "refused: answers correct 5 down EJJTY or EJOTY or 6 across FGHIO" "$(field FIX_TWO_WORDS)"
check "a count typed over the dropped letter does not veto the correction" \
      "5d:EOTY>EJOTY" "$(field FIX_DROPPED_COUNT)"
check "a phrase is a real word when each of its words is" \
      "5d:EOTY>EJOTY" "$(field FIX_PHRASE)"
check "but only when the blog wrote it as that many words; else it is blanked" \
      "5d:EOTY>" "$(field FIX_PHRASE_ONE_WORD)"
check "a short answer two words correct is blanked, not guessed between" \
      "5d:EOTY>" "$(field FIX_LENGTH_EITHER)"
check "a blank answer is no answer: it fits any grid and is never corrected" \
      "True" "$(field FIX_BLANK)"
check "a grid its answers do not number is refused, not corrected" \
      "refused: lights differ from the grid at" "$(field FIX_WRONG_GRID)"
check "a run writes the corrected answer into the grid row" \
      "[(1, [('ZJ', 'EJ')])]" "$(field RUN_ROW)"
check "and answers() reads the corrected answers back" True "$(field RUN_ANSWERS)"
check "a run refuses a puzzle whose typo no word corrects" "True refused" "$(field RUN_REFUSED)"
check "a tried failure is retried only when the run is told to" "[] [2]" "$(field RETRY_FAILED)"
check "a retried refusal rebuilds with a wordplay-settled answer, as a correction" \
      "[(2, ['Z'])]" "$(field SETTLED)"
check "--resettle corrects the grids already written and refuses the rest" \
      "[(1, 1)] [4]" "$(field RESETTLE)"
check "only the Mephisto of the barred series is rebuilt, by the parsed names" \
      "['Other Crosswords'] ['Mephisto', 'mephisto']" "$(field BARRED)"
check "a Weekend post with a Jumbo's entries is rebuilt at 23x23; the Club and TLS at 15x15" \
      "15 23 15 15 15" "$(field SIZE)"
check "a Jumbo with more lights than a 23x23 holds is rebuilt at 27x27" \
      "23 27 27" "$(field SUPERJUMBO)"
check "every search a puzzle runs draws on one budget" "True truncated" "$(field BOUNDED)"
check "so does every split of a linked answer" "True truncated" "$(field BOUNDED_LINKED)"
check "each search is logged under its post" True "$(field LOGGED)"
check "a post that gives only the answers is not searched" "True False" "$(field CLUES)"

if [ "$fails" -gt 0 ]; then echo "$fails FAILURE(S)"; exit 1; fi
echo "times_grids: all checks passed"
