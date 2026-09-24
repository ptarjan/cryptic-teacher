#!/bin/bash
# Does tools/file_times_puzzles.py file only complete, correctly numbered Times
# puzzles, and leave a filed one alone on the next run?
#
#     bash tools/test_file_times_puzzles.sh
#
# The nightly job re-runs it over the whole blog, so a second run that rewrote
# a file would throw away the annotations written into it since, and a row
# filed with a blank clue or a misread number would put a puzzle on the site
# that nobody can solve or find. The fixture is a hand-built 5x5 in a temp
# puzzles/, so nothing here reads the corpus or the blog cache.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() {  # check <what> <expected> <got>
  if [ "$2" = "$3" ]; then echo "ok   $1"; else
    echo "FAIL $1: expected [$2], got [$3]"; fails=$((fails + 1)); fi
}

out=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
import json, pathlib, tempfile
import fetch_puzzle, provenance
import reconstruct_grid as rg
import file_times_puzzles as F

TINY = ("..#..",
        ".....",
        "#...#",
        ".....",
        "..#..")
letter = lambda y, x: chr(ord("A") + (y * 5 + x) % 26)
cells = rg.light_cells(TINY)
answer = {k: "".join(letter(*c) for c in cs) for k, cs in cells.items()}

def rec(post_id, number, date, label="Daily Cryptic", clue=lambda k: f"Words for {k[0]} (%d)"):
    entries = []
    for k, a in answer.items():
        text = clue(k)
        entries.append({"number": k[0], "direction": k[1], "answer": a,
                        "clue": text and (text % len(a) if "%d" in text else text),
                        "enumeration": str(len(a))})
    return {"post_id": post_id, "date": date, "series": label, "number": number,
            "link": f"https://timesforthetimes.co.uk/p{post_id}", "entries": entries}

def row(r, **extra):
    return {"post_id": r["post_id"], "series": r["series"], "number": r["number"],
            "date": r["date"], "grid": list(TINY), "how": "unique", **extra}

tmp = pathlib.Path(tempfile.mkdtemp())
fetch_puzzle.PUZZLE_DIR = tmp / "puzzles"
fetch_puzzle.PUZZLE_DIR.mkdir()

recs = [rec(1, 100, "2026-01-05"), rec(2, 101, "2026-01-06"),
        rec(3, 2026, "2026-01-07"),               # a year read as the number
        rec(4, 102, "2026-01-08"),
        rec(5, 103, "2026-01-09", clue=lambda k: None if k == (1, "across") else "Clue (%d)"),
        rec(6, 104, "2026-01-10", clue=lambda k: "(%d)"),   # only the enumeration survived
        rec(7, 4321, "2026-01-11", label="Weekend Cryptic"),
        rec(8, 29000, "2026-01-12", label="Weekend Cryptic"),
        rec(9, 3200, "2026-01-12", label="Quick Cryptic")]
# The two-word light: 2-down is five cells, enumerated (2,3).
for e in recs[0]["entries"]:
    if (e["number"], e["direction"]) == (2, "down"):
        e["clue"], e["enumeration"] = "Two words (2,3)", "2,3"
# The blog mistyped 1-across on post 2; the grid row corrects it.
blog_typo = recs[1]["entries"][[(e["number"], e["direction"]) for e in recs[1]["entries"]].index((1, "across"))]
right = blog_typo["answer"]
blog_typo["answer"] = "ZZ"
rows = [row(r) for r in recs]
rows[1]["corrections"] = [{"number": 1, "direction": "across", "answer": right}]
# The Globe and Mail already holds the Quick from 3150 on.
(fetch_puzzle.PUZZLE_DIR / "globeandmail-3150.json").write_text("{}")

grids, parsed = tmp / "grids.jsonl", tmp / "parsed.jsonl"
grids.write_text("".join(json.dumps(r) + "\n" for r in rows))
parsed.write_text("".join(json.dumps(r) + "\n" for r in recs))

filed, skipped, drifted = F.run(grids, parsed)
print("FILED", ",".join(f"{s}:{n}" for s, n in sorted(filed.items())))
print("NO_CLUE", skipped["a light has no clue"])
print("OUT_OF_SEQUENCE", skipped["number out of sequence"])
print("REPRINTED", skipped["globeandmail reprints it"])

p = json.loads((fetch_puzzle.PUZZLE_DIR / "times-100.json").read_text())
by_id = {e["id"]: e for e in p["entries"]}
print("CLUE_KEEPS_COUNT", by_id["2-down"]["clue"])
print("SEPARATORS", json.dumps(by_id["2-down"].get("separatorLocations")))
print("SOLVED", all(e["solution"] for e in p["entries"]))
print("DATED", p["date"])
print("ORIGINS", p["provenance"]["gridOrigin"], p["provenance"]["solutionOrigin"])
print("PROV_CLEAN", provenance.check(p) == [])
fixed = json.loads((fetch_puzzle.PUZZLE_DIR / "times-101.json").read_text())
print("CORRECTED", {e["id"]: e for e in fixed["entries"]}["1-across"]["solution"] == right)
sunday = json.loads((fetch_puzzle.PUZZLE_DIR / "sundaytimes-4321.json").read_text())
print("PRIZE_UNDATED", sunday["date"], json.loads((fetch_puzzle.PUZZLE_DIR / "times-29000.json").read_text())["date"])

# A second run writes nothing, and a file that has drifted is named, not rewritten.
path = fetch_puzzle.PUZZLE_DIR / "times-102.json"
edited = json.loads(path.read_text())
edited["entries"][0]["clue"] = "Annotated since (2)"
path.write_text(json.dumps(edited))
before = {q.name: q.read_bytes() for q in fetch_puzzle.PUZZLE_DIR.iterdir()}
filed, _, drifted = F.run(grids, parsed)
print("RERUN_FILED", sum(filed.values()))
print("RERUN_UNTOUCHED", before == {q.name: q.read_bytes() for q in fetch_puzzle.PUZZLE_DIR.iterdir()})
print("DRIFTED", ",".join(drifted))
PY
)
echo "$out" | grep -v "^[A-Z_]* " | sed 's/^/  | /'
got() { echo "$out" | grep "^$1 " | cut -d' ' -f2-; }

check "files the complete, in-sequence rows" "sundaytimes:1,times:4" "$(got FILED)"
check "a light with no clue, or only its count, refuses the puzzle" "2" "$(got NO_CLUE)"
check "a misread number is refused" "1" "$(got OUT_OF_SEQUENCE)"
check "a number the Globe and Mail reprints is left to it" "1" "$(got REPRINTED)"
check "the clue keeps its enumeration" "Two words (2,3)" "$(got CLUE_KEEPS_COUNT)"
check "word breaks come from the enumeration" '{",": [2]}' "$(got SEPARATORS)"
check "filed with every answer" "True" "$(got SOLVED)"
check "a daily is dated by its post" "1767571200000" "$(got DATED)"
check "rebuilt grid, write-up answers" "reconstructed writeup" "$(got ORIGINS)"
check "provenance passes the validator" "True" "$(got PROV_CLEAN)"
check "the grid's correction beats the blog's typo" "True" "$(got CORRECTED)"
check "a prize puzzle carries no date" "None None" "$(got PRIZE_UNDATED)"
check "a second run files nothing" "0" "$(got RERUN_FILED)"
check "a second run rewrites nothing" "True" "$(got RERUN_UNTOUCHED)"
check "a drifted file is named" "times-102" "$(got DRIFTED)"

[ "$fails" -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
