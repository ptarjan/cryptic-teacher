#!/bin/bash
# Does corroboration fill, keep, settle and ledger the way tools/corroborate.py
# says, and does every write go through it?
#
#     bash tools/test_corroborate.sh
#
# Offline: every source here is a stub, so nothing reads a cache or the
# network. One case per rule, each built so that rule and no earlier one
# decides it.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
REPO="$PWD"
fails=0
same() { if [ "$2" = "$3" ]; then echo "  ok: $1"; else
  echo "  FAIL: $1"$'\n'"    want $3"$'\n'"    got  $2"; fails=$((fails + 1)); fi; }
field() { awk -v k="$1" '$1==k {$1=""; sub(/^ /, ""); print}' <<<"$2"; }

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

export TMP REPO
out=$(PYTHONPATH="$REPO/tools" python3 - 2>"$TMP/stderr" <<'PY'
import json
import os
from pathlib import Path

import corroborate as c
import fetch_puzzle

tmp = Path(os.environ["TMP"])
c.LEDGER = tmp / "ledger.json"
fetch_puzzle.ROOT = tmp
fetch_puzzle.PUZZLE_DIR = tmp / "puzzles"
fetch_puzzle.PUZZLE_DIR.mkdir()


def light(number, direction, x, y, solution, clue="A clue (3)", group=None):
    e = {"id": f"{number}-{direction}", "number": number, "direction": direction,
         "position": {"x": x, "y": y}, "length": len(solution), "clue": clue,
         "solution": solution}
    if group:
        e["group"] = group
    return e


def puzzle(pid, entries, **extra):
    series, _, number = pid.rpartition("-")
    return {"id": pid, "series": series, "number": int(number), "setter": "Paul",
            "date": c.day_ms("2020-01-02"), "entries": entries, **extra}


def source(name, origin, **fields):
    answers = fields.pop("answers", {})
    clues = fields.pop("clues", {})
    rec = c.Record(name, origin, answers={(int(k.split("-")[0]), k.split("-")[1]): v
                                          for k, v in answers.items()},
                   clues={(int(k.split("-")[0]), k.split("-")[1]): v
                          for k, v in clues.items()}, **fields)
    return lambda _puzzle: [rec]


def settled(p, *sources):
    return {(d.field, d.entry): (d.rule, d.winner) for d in c.resolve(p, sources)}


# Four lights that agree with every source, so a record is recognisably about
# this grid; the cases add their own lights beside them.
AGREED = [light(20, "across", 0, 20, "SUN"), light(21, "across", 0, 22, "HAT"),
          light(22, "across", 0, 24, "PEN"), light(23, "across", 0, 26, "OAK")]
AGREED_ANSWERS = {"20-across": "SUN", "21-across": "HAT", "22-across": "PEN",
                  "23-across": "OAK"}

# grid: 1-across BAT clashes with 2-down's R; the source's CAR does not. 1-down
# shares only its first cell, with 1-across, so BOX v COX is settled by
# solving the two together, not by any fixed crosser.
grid = puzzle("cryptic-500", AGREED + [
    light(1, "across", 0, 0, "BAT"), light(1, "down", 0, 0, "BOX"),
    light(2, "down", 2, 0, "RUN")])
blog = source("fifteensquared", "fifteensquared",
              answers={**AGREED_ANSWERS, "1-across": "CAR", "1-down": "COX", "2-down": "RUN"})
r = settled(grid, blog)
print("GRID", *r[("answer", "1-across")])
print("JOINT", *r[("answer", "1-down")])
fixed = c.corroborate(grid, [blog])
print("WRITTEN", {e["id"]: e["solution"] for e in fixed["entries"]}["1-across"])

# votes, and copies of one origin counting once: the differing cell of PEIR is
# unchecked, so the grid cannot help.
unchecked = puzzle("everyman-600", AGREED + [light(7, "across", 0, 10, "PEIR", "Pier (4)")])
two = settled(unchecked,
              source("fifteensquared", "fifteensquared", answers={**AGREED_ANSWERS, "7-across": "PEER"}),
              source("other", "times-listing", answers={**AGREED_ANSWERS, "7-across": "PEER"}))
print("VOTES", *two[("answer", "7-across")])
copies = settled(unchecked,
                 source("fifteensquared", "fifteensquared", answers={**AGREED_ANSWERS, "7-across": "PEER"}),
                 source("georgeho:fifteensquared", "fifteensquared",
                        answers={**AGREED_ANSWERS, "7-across": "PEER"}))
print("COPIES", *copies[("answer", "7-across")])

# rank, which is also no-overwrite: one blog against the paper keeps the
# paper's setter.
kept = settled(unchecked, source("fifteensquared", "fifteensquared",
                                 answers=AGREED_ANSWERS, setter="Puck"))
print("RANK", *kept[("setter", "")])

# fill: an empty setter and a blank clue take the source's.
blank = puzzle("cryptic-501", AGREED + [light(1, "across", 0, 0, "CAR", clue="")], setter="")
filled = c.corroborate(blank, [source("fifteensquared", "fifteensquared",
                                      answers=AGREED_ANSWERS, setter="Tramp",
                                      clues={"1-across": "Motor (3)"})])
print("FILL_SETTER", filled["setter"])
print("FILL_CLUE", filled["entries"][-1]["clue"])

# enumeration: of two clues offered for a blank, only one counts the light.
enum = settled(blank, source("a", "fifteensquared", answers=AGREED_ANSWERS,
                             clues={"1-across": "Motor car (5)"}),
               source("b", "times-listing", clues={"1-across": "Motor (3)"}))
print("ENUMERATION", *enum[("clue", "1-across")])

# sequence: the neighbours on disk put 501 between 2020-01-01 and -03, so the
# file's 2021 date loses to the source's.
for n, d in ((500, "2020-01-01"), (502, "2020-01-03")):
    (fetch_puzzle.PUZZLE_DIR / f"cryptic-{n}.json").write_text(
        json.dumps({"id": f"cryptic-{n}", "date": c.day_ms(d)}))
dated = puzzle("cryptic-501", AGREED, date=c.day_ms("2021-06-01"))
seq = settled(dated, source("a", "times-listing", date=c.day_ms("2020-01-02")))
print("SEQUENCE", seq[("date", "")][0], c.day(seq[("date", "")][1]))

# unresolved: one origin on both sides, an unchecked cell, and the file keeps
# the primary's answer without raising.
times = puzzle("timesquick-700", AGREED + [light(18, "across", 0, 12, "SAWS")],
               solutionSource={"kind": "timesforthetimes"},
               provenance={"retrievedFrom": "blog"})
same_origin = source("georgeho:times_xwd_times", "timesforthetimes",
                     answers={**AGREED_ANSWERS, "18-across": "SOWN"})
kept = c.corroborate(times, [same_origin])
print("UNRESOLVED", {e["id"]: e["solution"] for e in kept["entries"]}["18-across"])

# but not from the primary's own origin, which it has already read: the Times
# filer leaves the daily's setter null because the blog names none.
anonymous = c.corroborate({**times, "setter": None},
                          [source("georgeho:times_xwd_times", "timesforthetimes",
                                  answers=AGREED_ANSWERS, setter="Someone")])
print("SAME_ORIGIN", anonymous["setter"])

# no second source: the puzzle comes back as it went in, and nothing is written.
alone = puzzle("independent-800", AGREED)
print("ALONE", c.corroborate(alone, [lambda _p: []]) is alone,
      json.loads(c.LEDGER.read_text()).get("independent-800 setter") is None)

# a record that disagrees on most lights is another puzzle's, and says nothing.
other = settled(grid, source("fifteensquared", "fifteensquared",
                             answers={"20-across": "TEN", "21-across": "BOW", "22-across": "ZIP",
                                      "1-across": "CAR"}, setter="Puck"))
print("MISFILED", len(other))

# SOURCE_ANSWER_WRONG: the file's corrected letters stand against a source
# repeating the paper's, and a file carrying the paper's is corrected on write.
wrong = puzzle("cryptic-23053", AGREED + [light(18, "across", 0, 14, "GETSREADY")])
print("KNOWN_WRONG", len(settled(wrong, source("f", "fifteensquared",
                                                answers={**AGREED_ANSWERS, "18-across": "GETSTEADY"}))))
served = puzzle("cryptic-23053", AGREED + [light(18, "across", 0, 14, "GETSTEADY")])
print("CORRECTED", c.corroborate(served, [lambda _p: []])["entries"][-1]["solution"])

# normalising: case, spaces, hyphens, accents, alternatives, a linked answer.
print("LETTERS", c.letters("gets-ready"), c.letters("Détente"), c.answer_letters("ANYONE/CERISE"))
linked = puzzle("quiptic-900", AGREED + [
    light(8, "across", 0, 16, "TEAM", group=["8-across", "9-across"]),
    light(9, "across", 5, 16, "MATE", group=["8-across", "9-across"])])
print("LINKED", len(settled(linked, source("f", "fifteensquared",
                                            answers={**AGREED_ANSWERS, "8-across": c.letters("TEAM MATE")}))))

# naming a blog post
print("TITLES", c.blog_puzzle_id("Guardian Quiptic 1,357 by Hectence"),
      c.blog_puzzle_id("Independent On Sunday 1127 18 September 2011Nitsy"),
      c.blog_puzzle_id("Azed 2067Wip"),
      c.blog_puzzle_id("QC1575", c.TIMES_SERIES),
      c.blog_puzzle_id("Sunday Times 4589", c.TIMES_SERIES),
      c.blog_puzzle_id("Mephisto 2958", c.TIMES_SERIES))
print("SETTERS", c.blog_setter("Guardian 25749 Brendan"), c.blog_setter("Independent 12,225 by Tack"),
      c.blog_setter("Everyman 3,906/22 August"))

# the ledger names every settled dispute and the rule that settled it
ledger = json.loads(c.LEDGER.read_text())
print("LEDGER", ledger["cryptic-500 answer 1-across"]["rule"],
      ledger["timesquick-700 answer 18-across"]["rule"],
      ledger["cryptic-501 setter"]["rule"])

# and every write goes through it. The write refuses what the corpus sweep
# would report, so this one is a real puzzle with its setter left empty.
real = fetch_puzzle.read_puzzle_file(Path(os.environ["REPO"]) / "puzzles" / "cryptic-24104.json")
c.SOURCES = (source("fifteensquared", "fifteensquared", setter="Tramp",
                    answers={e["id"]: e["solution"] for e in real["entries"]}),)
path = fetch_puzzle.puzzle_path("cryptic", 24104)
fetch_puzzle.write_puzzle_file(path, {**real, "setter": None}, generator="tools/fetch_puzzle.py")
print("WRITE_PATH", fetch_puzzle.read_puzzle_file(path)["setter"])

# but only into the corpus: a fixture written elsewhere is left as it came
elsewhere = tmp / "fixtures"
elsewhere.mkdir()
fetch_puzzle.PUZZLE_DIR = elsewhere
fetch_puzzle.write_puzzle_file(elsewhere / "cryptic-24104.json", {**real, "setter": None},
                               generator="tools/fetch_puzzle.py")
print("FIXTURE", repr(fetch_puzzle.read_puzzle_file(elsewhere / "cryptic-24104.json")["setter"]))

# and a puzzle with no grid is not read against anything
gridless = {"id": "cryptic-502", "series": "cryptic", "number": 502, "setter": "",
            "entries": [{"id": "1-across", "number": 1, "direction": "across", "solution": "CAR"}]}
print("GRIDLESS", c.corroborate(gridless, [source("f", "fifteensquared", setter="Tramp")]) is gridless)
PY
)
echo "$out" | grep -q GRIDLESS || { echo "the script died:"; cat "$TMP/stderr"; exit 1; }

echo "the rules, each deciding a case"
same "grid: the source's answer that agrees with its crossers wins" "$(field GRID "$out")" "grid CAR"
same "grid: disputed crossers are solved together" "$(field JOINT "$out")" "grid COX"
same "and the file is written with the winner" "$(field WRITTEN "$out")" "CAR"
same "votes: two origins beat one" "$(field VOTES "$out")" "votes PEER"
same "copies of one origin are one vote, so rank decides" "$(field COPIES "$out")" "rank PEIR"
same "rank: the paper's setter stands against one blog" "$(field RANK "$out")" "rank Paul"
same "sequence: the date the neighbours allow wins" "$(field SEQUENCE "$out")" "sequence 2020-01-02"
same "enumeration: the clue that counts the light wins" "$(field ENUMERATION "$out")" \
  "enumeration Motor (3)"
same "unresolved: the primary's answer is kept, nothing raised" "$(field UNRESOLVED "$out")" "SAWS"
same "and it is said loudly, naming both candidates" \
  "$(grep -c 'no rule settles timesquick-700 18-across answer: SAWS from primary; SOWN from georgeho:times_xwd_times' "$TMP/stderr")" "1"

echo "fill, and nothing else"
same "an empty setter is filled" "$(field FILL_SETTER "$out")" "Tramp"
same "a blank clue is filled" "$(field FILL_CLUE "$out")" "Motor (3)"
same "but never from the origin the primary already read" "$(field SAME_ORIGIN "$out")" "None"
same "no second source: unchanged, no ledger entry" "$(field ALONE "$out")" "True True"
same "a record about another grid is ignored" "$(field MISFILED "$out")" "0"

echo "known-wrong keys and normalising"
same "a source repeating the paper's known error is no dispute" "$(field KNOWN_WRONG "$out")" "0"
same "a file carrying the paper's error is corrected on write" "$(field CORRECTED "$out")" "GETSREADY"
same "case, hyphens, accents, alternatives" "$(field LETTERS "$out")" "GETSREADY DETENTE None"
same "a linked answer on its first light agrees with the lights it spans" "$(field LINKED "$out")" "0"
same "blog titles name our puzzles, and only ours" "$(field TITLES "$out")" \
  "quiptic-1357 indysunday-1127 None timesquick-1575 sundaytimes-4589 None"
same "blog titles name setters, and a month is not one" "$(field SETTERS "$out")" "Brendan Tack None"

echo "the ledger and the write path"
same "the ledger names the rule for each" "$(field LEDGER "$out")" "grid unresolved filled"
same "write_puzzle_file corroborates every write to the corpus" "$(field WRITE_PATH "$out")" "Tramp"
same "and no write anywhere else" "$(field FIXTURE "$out")" "None"
same "a puzzle with no grid is left alone" "$(field GRIDLESS "$out")" "True"

[ "$fails" = 0 ] && echo "corroborate: all checks passed" || echo "corroborate: $fails FAILED"
exit $((fails > 0))
