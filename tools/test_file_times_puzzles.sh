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
    # The blog's underlining and a byte lost in its decoding.
    if (e["number"], e["direction"]) == (1, "down"):
        e["clue"] = "Say \u201cit\u201d\x9d </u>quietly</u> (2)"
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

filed, skipped, drifted = F.run(grids, parsed, listing={})
print("FILED", ",".join(f"{s}:{n}" for s, n in sorted(filed.items())))
print("NO_CLUE", skipped["a light has no clue"])
print("OUT_OF_SEQUENCE", skipped["number out of sequence"])
print("REPRINTED", skipped["globeandmail reprints it"])

p = json.loads((fetch_puzzle.PUZZLE_DIR / "times-100.json").read_text())
by_id = {e["id"]: e for e in p["entries"]}
print("CLUE_KEEPS_COUNT", by_id["2-down"]["clue"])
print("CLEAN", by_id["1-down"]["clue"])
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
filed, _, drifted = F.run(grids, parsed, listing={})
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
check "markup and lost bytes are stripped from a clue" "Say “it” quietly (2)" "$(got CLEAN)"
check "word breaks come from the enumeration" '{",": [2]}' "$(got SEPARATORS)"
check "filed with every answer" "True" "$(got SOLVED)"
check "a daily is dated by its post" "1767571200000" "$(got DATED)"
check "rebuilt grid, write-up answers" "reconstructed writeup" "$(got ORIGINS)"
check "provenance passes the validator" "True" "$(got PROV_CLEAN)"
check "the grid's correction beats the blog's typo" "True" "$(got CORRECTED)"
check "a prize puzzle nothing dates carries no date" "None None" "$(got PRIZE_UNDATED)"
check "a second run files nothing" "0" "$(got RERUN_FILED)"
check "a second run rewrites nothing" "True" "$(got RERUN_UNTOUCHED)"
check "a drifted file is named" "times-102" "$(got DRIFTED)"

# Print dates. The prize puzzles are blogged a week or more after they are
# printed, so their post date is not their date; filing one by it put
# Saturday's puzzle on the next Saturday and the Sunday Times on a Saturday.
out=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
import datetime
import file_times_puzzles as F
import fetch_times_listing as L

D = datetime.date.fromisoformat
def rec(pid, label, number, posted, slug=""):
    return {"post_id": pid, "series": label, "number": number, "date": posted, "slug": slug}

recs = [
    # Mon 5 to Fri 9 January 2026, and Monday the 12th, each blogged the day
    # it was printed, but the Friday blogged on Thursday evening.
    rec(1, "Daily Cryptic", 29000, "2026-01-05"), rec(2, "Daily Cryptic", 29001, "2026-01-06"),
    rec(3, "Daily Cryptic", 29002, "2026-01-07"), rec(4, "Daily Cryptic", 29003, "2026-01-08"),
    rec(5, "Daily Cryptic", 29004, "2026-01-08"), rec(7, "Daily Cryptic", 29006, "2026-01-12"),
    # Saturday the 10th, blogged a week later with no date in its slug.
    rec(6, "Weekend Cryptic", 29005, "2026-01-17", "times-cryptic-29005"),
    # The Saturday before, titled; and one titled with the wrong Saturday.
    rec(8, "Weekend Cryptic", 28999, "2026-01-10", "times-28999-saturday-3-january-2026"),
    rec(9, "Daily Cryptic", 29007, "2026-01-13"), rec(10, "Daily Cryptic", 29008, "2026-01-14"),
    rec(11, "Daily Cryptic", 29009, "2026-01-15"), rec(12, "Daily Cryptic", 29010, "2026-01-16"),
    rec(13, "Weekend Cryptic", 29011, "2026-01-24", "times-29011-saturday-10-january-2026"),
    rec(14, "Daily Cryptic", 29012, "2026-01-19"),
    # The Sunday Times: two titled anchors three weeks apart, one untitled
    # between, and one past the last anchor.
    rec(20, "Weekend Cryptic", 5001, "2026-01-11", "sunday-times-5001-4-january-2026"),
    rec(21, "Weekend Cryptic", 5002, "2026-01-18", "sunday-times-cryptic-5002"),
    rec(24, "Weekend Cryptic", 5003, "2026-01-25", "sunday-times-cryptic-5003"),
    rec(22, "Weekend Cryptic", 5004, "2026-02-01", "sunday-times-5004-25-jan"),
    rec(23, "Weekend Cryptic", 5005, "2026-02-08", "sunday-times-5005"),
    # The Jumbo: two Saturdays two numbers apart with a bank-holiday Monday
    # between them, which no cadence can place.
    rec(30, "Jumbo Cryptic", 1700, "2026-01-17", "jumbo-1700-3-january-2026"),
    rec(31, "Jumbo Cryptic", 1701, "2026-01-24", "jumbo-1701"),
    rec(32, "Jumbo Cryptic", 1702, "2026-01-24", "jumbo-1702"),
    rec(33, "Jumbo Cryptic", 1703, "2026-01-31", "jumbo-1703-17-january"),
    # ...and a bank holiday the blog names, which places the Saturday after it.
    rec(34, "Jumbo Cryptic", 1710, "2026-02-21", "jumbo-1710-7-february-2026"),
    rec(35, "Jumbo Cryptic", 1711, "2026-02-21", "jumbo-1711-bank-holiday-monday-9-february"),
    rec(36, "Jumbo Cryptic", 1712, "2026-02-28", "jumbo-1712"),
    rec(37, "Jumbo Cryptic", 1713, "2026-03-07", "jumbo-1713-21-february-2026"),
]
dates, notes = F.print_dates(recs, listing={})
day = lambda s, n: dates.get((s, n)) and dates[(s, n)].strftime("%a %d")
print("SATURDAY", day("times", 29005))
print("TITLED", day("times", 28999))
print("WRONG_TITLE", day("times", 29011), any("times-29011" in n for n in notes))
print("FRIDAY", day("times", 29004))
print("SUNDAY_BETWEEN", day("sundaytimes", 5002), day("sundaytimes", 5003))
print("SUNDAY_PAST", day("sundaytimes", 5005))
print("JUMBO_GAP", day("timesjumbo", 1701), day("timesjumbo", 1702))
print("JUMBO_HOLIDAY", day("timesjumbo", 1711), day("timesjumbo", 1712))
listed = dict(listing={("sundaytimes", 5005): D("2026-02-01"), ("timesjumbo", 1701): D("2026-01-05"),
                       ("timesjumbo", 1702): D("2026-01-10")})
dates, notes = F.print_dates(recs, **listed)
print("LISTED", day("sundaytimes", 5005), day("timesjumbo", 1701), day("timesjumbo", 1702))

page = ('<a href="/puzzles/crossword/sunday-times-cryptic-no-5078-t38g8lcjm" data-testid="x">'
        '<span class="a">Sunday September 24</span><span class="b"> | No 5078</span>'
        '<a href="/puzzles/crossword/times-cryptic-jumbo-no-1680-abc">'
        '<span class="a">Monday December 27</span><span class="b">| No 1680</span>'  # a Wednesday
        '<a href="/puzzles/crossword/times-cryptic-no-29000-abc">'
        '<span class="a">Tuesday December 26</span><span class="b">| No 29000</span>')
print("CARDS", [(s, n, str(d)) for s, n, d in L.cards("20240103120000", page)])
PY
)
echo "$out" | grep -v "^[A-Z_]* " | sed 's/^/  | /'
check "Saturday's Times is the Saturday between its neighbours" "Sat 10" "$(got SATURDAY)"
check "a slug naming a Saturday dates it" "Sat 03" "$(got TITLED)"
check "a slug naming another Saturday than its neighbours' is refused, and named" "None True" "$(got WRONG_TITLE)"
check "a daily blogged the evening before is its week's Friday" "Fri 09" "$(got FRIDAY)"
check "a Sunday between anchors a week a number apart follows the cadence" "Sun 11 Sun 18" "$(got SUNDAY_BETWEEN)"
check "a Sunday past the last anchor stays undated" "None" "$(got SUNDAY_PAST)"
check "a Jumbo gap holding a bank holiday stays undated" "None None" "$(got JUMBO_GAP)"
check "a bank holiday the blog names lets the cadence past it" "Mon 09 Sat 14" "$(got JUMBO_HOLIDAY)"
check "the Times's listing dates what the cadence cannot" "Sun 01 Mon 05 Sat 10" "$(got LISTED)"
check "listing cards: year off the capture, weekday checked" \
  "[('sundaytimes', 5078, '2023-09-24'), ('times', 29000, '2023-12-26')]" "$(got CARDS)"

[ "$fails" -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
