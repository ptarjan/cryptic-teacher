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
import datetime, json, pathlib, tempfile
import enumeration, fetch_puzzle, provenance, puzzle_paths
import reconstruct_grid as rg
import file_times_puzzles as F
from groups import entry_id

TINY = ("..#..",
        ".....",
        "#...#",
        ".....",
        "..#..")
letter = lambda y, x: chr(ord("A") + (y * 5 + x) % 26)
cells = rg.light_cells(TINY)
answer = {k: "".join(letter(*c) for c in cs) for k, cs in cells.items()}

def rec(post_id, number, date, label="Daily Cryptic", clue=lambda k: f"Words for {k[0]} (%d)", title=""):
    entries = []
    for k, a in answer.items():
        text = clue(k)
        entries.append({"number": k[0], "direction": k[1], "answer": a,
                        "clue": text and (text % len(a) if "%d" in text else text),
                        "enumeration": str(len(a))})
    return {"post_id": post_id, "date": date, "series": label, "number": number,
            "link": f"https://timesforthetimes.co.uk/p{post_id}", "title": title,
            "entries": entries}

def row(r, **extra):
    return {"post_id": r["post_id"], "series": r["series"], "number": r["number"],
            "date": r["date"], "grid": list(TINY), "how": "unique", **extra}

# The lone Sunday Times has no neighbour to date it by; the paper's listing does.
LISTING = {("sundaytimes", 4321): datetime.date(2026, 1, 11)}

tmp = pathlib.Path(tempfile.mkdtemp())
puzzle_paths.PUZZLE_DIR = tmp / "puzzles"
puzzle_paths.PUZZLE_DIR.mkdir()

recs = [rec(1, 100, "2026-01-05"), rec(2, 101, "2026-01-06"),
        rec(3, 2026, "2026-01-07"),               # a year read as the number
        rec(4, 102, "2026-01-08"),
        rec(5, 103, "2026-01-09", clue=lambda k: None if k == (1, "across") else "Clue (%d)"),
        rec(6, 104, "2026-01-10", clue=lambda k: "(%d)"),   # only the enumeration survived
        rec(7, 4321, "2026-01-11", label="Weekend Cryptic",
            title="Sunday Times Cryptic No 4321, by Dean Mayer — x"),
        rec(8, 29000, "2026-01-12", label="Weekend Cryptic",
            title="Times 29000 by the seaside"),
        rec(9, 3200, "2026-01-12", label="Quick Cryptic")]
# The two-word light: 2-down is five cells, enumerated (2,3).
for e in recs[0]["entries"]:
    if (e["number"], e["direction"]) == (2, "down"):
        e["clue"], e["enumeration"] = "Two words (2,3)", "2,3"
    # The blog's underlining and a byte lost in its decoding.
    if (e["number"], e["direction"]) == (1, "down"):
        e["clue"] = "Say \u201cit\u201d\x9d </u>quietly</u> (2)"
# A count in words (the Mephisto's) is kept as printed when the answer the
# blog wrote has no breaks to read; a blogger's "should say" note is taken
# only as the answer's own breaks.
row1 = next(k for k, cs in cells.items() if k[1] == "across" and cs[0][0] == 1)
for e in recs[0]["entries"]:
    if (e["number"], e["direction"]) == row1:
        e["clue"] = "Worded (5, two words)"
for e in recs[1]["entries"]:
    if (e["number"], e["direction"]) == (2, "down"):
        e["clue"], e["enumeration"] = "Noted (5, should say \u201ctwo words\u201d)", "2,3"
# The blog mistyped 1-across on post 2; the grid row corrects it.
blog_typo = recs[1]["entries"][[(e["number"], e["direction"]) for e in recs[1]["entries"]].index((1, "across"))]
right = blog_typo["answer"]
blog_typo["answer"] = "ZZ"
rows = [row(r) for r in recs]
rows[1]["corrections"] = [{"number": 1, "direction": "across", "answer": right}]
# The Globe and Mail already holds the Quick from 3150 on.
(puzzle_paths.PUZZLE_DIR / "globeandmail" / "undated").mkdir(parents=True)
(puzzle_paths.PUZZLE_DIR / "globeandmail" / "undated" / "globeandmail-3150.json").write_text("{}")

grids, parsed = tmp / "grids.jsonl", tmp / "parsed.jsonl"
grids.write_text("".join(json.dumps(r) + "\n" for r in rows))
parsed.write_text("".join(json.dumps(r) + "\n" for r in recs))

filed, skipped, drifted = F.run(grids, parsed, listing=LISTING)
print("FILED", ",".join(f"{s}:{n}" for s, n in sorted(filed.items())))
print("NO_CLUE", skipped["a light has no clue"])
print("OUT_OF_SEQUENCE", skipped["number out of sequence"])
print("REPRINTED", skipped["globeandmail reprints it"])

p = json.loads(puzzle_paths.find("times-100").read_text())
by_id = {entry_id(e): e for e in p["entries"]}
print("CLUE_KEEPS_COUNT", enumeration.printed(by_id["2-down"]["clue"]))
print("CLEAN", enumeration.printed(by_id["1-down"]["clue"]))
print("WORDED", enumeration.printed(by_id["%d-%s" % row1]["clue"]))
print("SEPARATORS", json.dumps(by_id["2-down"]["clue"].get("separators")))
print("SOLVED", all(e["solution"] for e in p["entries"]))
print("DATED", p["date"])
print("ORIGINS", p["source"]["gridOrigin"], p["solutions"]["origin"])
print("PROV_CLEAN", provenance.check(p) == [])
fixed = json.loads(puzzle_paths.find("times-101").read_text())
print("CORRECTED", {entry_id(e): e for e in fixed["entries"]}["1-across"]["solution"] == right)
print("NOTED", enumeration.printed({entry_id(e): e for e in fixed["entries"]}["2-down"]["clue"]))
sunday = json.loads(puzzle_paths.find("sundaytimes-4321").read_text())
print("PRIZE_UNDATED", sunday["date"], json.loads(puzzle_paths.find("times-29000").read_text())["date"])

# A second run writes nothing, and a file that has drifted is named, not rewritten.
path = puzzle_paths.find("times-102")
edited = json.loads(path.read_text())
edited["entries"][0]["clue"] = {"text": "Annotated since", "enumeration": "2"}
path.write_text(json.dumps(edited))
before = {q.name: q.read_bytes() for q in puzzle_paths.PUZZLE_DIR.rglob("*") if q.is_file()}
filed, _, drifted = F.run(grids, parsed, listing=LISTING)
print("RERUN_FILED", sum(filed.values()))
print("RERUN_UNTOUCHED", before == {q.name: q.read_bytes() for q in puzzle_paths.PUZZLE_DIR.rglob("*") if q.is_file()})
print("DRIFTED", ",".join(drifted))
print("SETTERS", sunday["setter"], json.loads(puzzle_paths.find("times-29000").read_text()).get("setter"))

# A clue filed before a parser fix is tidied by the next run as the parser
# now reads it: a definition slash goes, the rest of the file stays.
path = puzzle_paths.find("times-100")
old = json.loads(path.read_text())
old["entries"][0]["clue"]["text"] = "Irish city /seal"
path.write_text(json.dumps(old))
F.run(grids, parsed, listing=LISTING)
new = json.loads(puzzle_paths.find("times-100").read_text())
print("TIDIED", new["entries"][0]["clue"]["text"],
      [e["solution"] for e in new["entries"]] == [e["solution"] for e in old["entries"]])
import file_blog_puzzles as B
import parse_timesforthetimes as P
def annotated(text, **ann):
    return {"entries": [{"clue": {"text": text, "enumeration": "8"}, "annotation": ann}]}
got, _ = B.retext(annotated("Hide behind young woman [as] neccessary?",
                            definitions=[{"text": "[as] neccessary?", "at": 24}]), P.tidy)
kept, n = B.retext(annotated("Trainee / in the wrong", blocks=[{"clueFragment": "/"}]), P.tidy)
print("TIDIED_NOTE", got["entries"][0]["annotation"]["definitions"][0]["text"], "|",
      kept["entries"][0]["clue"]["text"], n)

# A number inside the Globe's run that it never printed is still filed here.
(puzzle_paths.PUZZLE_DIR / "globeandmail" / "undated" / "globeandmail-3152.json").write_text("{}")
held = F.reprinted_from()
print("REPRINT_GAP", ",".join(str(F.reprinted_by(held, "timesquick", n)) for n in (3150, 3151, 3200)))

# A title one typing slip from the only unclaimed number that fits is renumbered.
fits = lambda date, n: 5040 <= n <= 5050
print("RETYPED", F.retyped({"number": 5445, "date": "2023-02-12"}, fits, {5044, 5046}),
      F.retyped({"number": 5445, "date": "2023-02-12"}, fits, {5045}),
      F.retyped({"number": 2019, "date": "2019-02-23"}, fits, set()))

# A puzzle filed with no setter is given the title's; a name never is replaced.
sp = puzzle_paths.find("sundaytimes-4321")
for key, held in (("PLACEHOLDER", None), ("NAMED", "Someone")):
    sp.write_text(json.dumps({k: v for k, v in {**sunday, "setter": held}.items()
                              if v is not None}))
    F.run(grids, parsed, listing=LISTING)
    print(f"RENAMED_{key}", json.loads(sp.read_text())["setter"])

# "See 5 Across (3)" under a light 5-across's clue names, each light counting
# only itself, is a pointer to where its clue is, not a linked answer; a
# pointer the leader's clue never names stays a group, held on the leader.
import enumeration
import file_blog_puzzles as B
from groups import entry_id
pointed = rec(10, 105, "2026-01-13")
for e in pointed["entries"]:
    k = (e["number"], e["direction"])
    if k == (5, "across"):
        e["clue"] = "Path to 7 coloured red (5)"
    if k == (7, "across"):
        e["clue"] = "See 5 Across (3)"
    if k == (3, "down"):
        e["clue"] = "See 2 (5)"
built, why = B.build(pointed, row(pointed), "times", None, None)
groups = {entry_id(e): e.get("group") for e in built["entries"]}
print("COMPOSITE", groups["5-across"], groups["7-across"], groups["2-down"], groups["3-down"])

# The grid proves the answers, so a count the blog mistyped is recounted from
# them -- 5-across typed (4), 2-down typed (0,5) -- and named in the check;
# a two-word count typed over one-word answers has lost a word and is refused.
typo = rec(11, 106, "2026-01-14")
for e in typo["entries"]:
    k = (e["number"], e["direction"])
    if k == (5, "across"):
        e["clue"], e["enumeration"] = "Mistyped (4)", "4"
    if k == (2, "down"):
        e["clue"], e["enumeration"] = "Zero first (0,5)", "0,5"
built, why = B.build(typo, row(typo), "times", None, None)
by_id = {entry_id(e): e for e in built["entries"]}
print("RECOUNTED", enumeration.printed(by_id["5-across"]["clue"]), "|",
      enumeration.printed(by_id["2-down"]["clue"]), "|",
      built["solutions"]["check"].split("; ")[-1])
for e in typo["entries"]:
    if (e["number"], e["direction"]) == (5, "across"):
        e["clue"], e["enumeration"] = "Lost a word (2,4)", "2,4"
print("UNRECOUNTABLE", B.build(typo, row(typo), "times", None, None)[1])
linked = dict(typo, unsplit=[{"lights": [[1, "across"], [25, "across"]],
                                             "answer": "HANDLEBARMOUSTACHE", "enumeration": "9,9"}])
print("UNSPLIT", B.build(linked, row(linked), "times", None, None)[1])
# One the grid does split files: the leader takes the clue, the rest See N.
pair = [k for k in cells if k[1] == "across" and len(cells[k]) == 5]
whole = rec(12, 107, "2026-01-15")
whole["entries"] = [e for e in whole["entries"] if (e["number"], e["direction"]) not in pair]
whole["unsplit"] = [{"lights": [list(k) for k in pair], "answer": answer[pair[0]] + answer[pair[1]],
                     "enumeration": "5,5", "clue": "Linked words (5,5)"}]
built, why = B.build(whole, row(whole), "times", None, None)
by_id = {entry_id(e): e for e in built["entries"]} if built else {}
print("SPLIT_FILED", why, [enumeration.printed(by_id[f"{n}-{d}"]["clue"]) for n, d in pair],
      by_id[f"{pair[0][0]}-across"].get("group"))
PY
)
echo "$out" | grep -v "^[A-Z_]* " | sed 's/^/  | /'
got() { echo "$out" | grep "^$1 " | cut -d' ' -f2-; }

check "files the complete, in-sequence rows" "sundaytimes:1,times:4" "$(got FILED)"
check "a light with no clue, or only its count, refuses the puzzle" "2" "$(got NO_CLUE)"
check "a misread number is refused" "1" "$(got OUT_OF_SEQUENCE)"
check "a number the Globe and Mail reprints is left to it" "1" "$(got REPRINTED)"
check "a number the Globe skipped inside its run is filed as the Quick" \
  "globeandmail,None,globeandmail" "$(got REPRINT_GAP)"
check "a mistyped title is renumbered only onto one free slot that fits" \
  "5045 None None" "$(got RETYPED)"
check "the clue keeps its enumeration" "Two words (2,3)" "$(got CLUE_KEEPS_COUNT)"
check "markup and lost bytes are stripped from a clue" "Say “it” quietly (2)" "$(got CLEAN)"
check "a count in words with no breaks to read is filed as printed" "Worded (5, two words)" "$(got WORDED)"
check "a blogger's \"should say\" note becomes the answer's breaks" "Noted (2,3)" "$(got NOTED)"
check "word breaks come from the enumeration" '[{"at": 2, "mark": ","}]' "$(got SEPARATORS)"
check "filed with every answer" "True" "$(got SOLVED)"
check "a daily is dated by its post" "2026-01-05" "$(got DATED)"
check "rebuilt grid, write-up answers" "reconstructed writeup" "$(got ORIGINS)"
check "provenance passes the validator" "True" "$(got PROV_CLEAN)"
check "the grid's correction beats the blog's typo" "True" "$(got CORRECTED)"
check "a prize puzzle takes its listed day, and one nothing dates a best fit" "2026-01-11 2026-01-12" "$(got PRIZE_UNDATED)"
check "a second run files nothing" "0" "$(got RERUN_FILED)"
check "a filed clue is tidied as the parser now reads it" "Irish city seal True" "$(got TIDIED)"
check "an annotation's quotations are tidied with its clue; one the tidied clue loses keeps the clue" \
  "as neccessary? | Trainee / in the wrong 0" "$(got TIDIED_NOTE)"
check "a second run rewrites nothing" "True" "$(got RERUN_UNTOUCHED)"
check "a drifted file is named" "times-102" "$(got DRIFTED)"
check "the Sunday Times takes its setter from the title; the Times stays anonymous" \
  "Dean Mayer None" "$(got SETTERS)"
check "a puzzle filed with no setter is named" "Dean Mayer" "$(got RENAMED_PLACEHOLDER)"
check "a setter already named is never overwritten" "Someone" "$(got RENAMED_NAMED)"
check "a pointer into the leader's clue is no group; an unnamed pointer is one, held by its leader alone" \
  "None None ['2-down', '3-down'] None" "$(got COMPOSITE)"
check "a count the grid-proved answers contradict is recounted from them, and said" \
  "Mistyped (5) | Zero first (5) | the grid proves the blog's enumeration wrong at 2 down, 5 across, recounted from the answer here" \
  "$(got RECOUNTED)"
check "a count with more words than the answers hold is refused" \
  "an enumeration disagrees with its light, and the answer holds too few words to take the count from" \
  "$(got UNRECOUNTABLE)"
check "a linked clue the blog does not split refuses the puzzle, not its grid without it" \
  "a linked clue the blog does not split" "$(got UNSPLIT)"
check "a linked answer the grid splits files, the leader holding the clue" \
  "None ['Linked words (5,5)', 'See 5'] ['5-across', '8-across']" "$(got SPLIT_FILED)"

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
        '<span class="a">Tuesday December 26</span><span class="b">| No 29000</span>'
        # Since 2025: no "No", more attributes, and "Today" (no date to read).
        '<a href="/puzzles/crossword/sunday-times-cryptic-no-5143-abc">'
        '<span class=" c" color="inkBase">Today</span><span class=" d" color="inkBase">| 5143</span>'
        '<a href="/puzzles/crossword/sunday-times-cryptic-no-5142-abc">'
        '<span class=" c" color="inkBase">Sunday December 31</span><span class=" d">| 5142</span>')
print("CARDS", [(s, n, str(d)) for s, n, d in L.cards("20240103120000", page)])

# A Jumbo title states its date as the slug may not: "(18/11/17)", "April1,
# 2017", or a holiday's name. Before the title was read these stayed null.
said = lambda posted, title: str(F.blog_date(
    {"date": posted, "slug": "jumbo", "title": title}, "timesjumbo"))
print("TITLE_NUMERIC", said("2017-12-02", "Times Cryptic Jumbo No 1294 (18/11/17): Feline Groovy"))
print("TITLE_GLUED", said("2017-04-15", "Jumbo 1257 April1, 2017 – a classical clanger?"))
print("TITLE_HOLIDAYS", said("2018-01-06", "Boxing Day Jumbo 1300"),
      said("2017-04-29", "Easter Monday Bank Holiday Jumbo Cryptic 1260"),
      said("2018-09-08", "Summer Bank Holiday Jumbo 1340"),
      said("2019-01-13", "Jumbo 1360 (New Year’s Day)"))
print("TITLE_BARE_HOLIDAY", said("2018-06-09", "Bank Holiday Jumbo 1326"))
# Two stated Saturdays with a bank holiday's number between them: no cadence
# joins them, but the numbers fit the days, so both dates stand.
fit = [rec(40, "Jumbo Cryptic", 1810, "2026-03-14", "jumbo-1810-7-march-2026"),
       rec(41, "Jumbo Cryptic", 1811, "2026-03-21", "jumbo-1811"),
       rec(42, "Jumbo Cryptic", 1812, "2026-03-21", "jumbo-1812"),
       rec(43, "Jumbo Cryptic", 1813, "2026-03-28", "jumbo-1813-21-march-2026")]
dates, _ = F.print_dates(fit, listing={})
print("JUMBO_FITS", day("timesjumbo", 1810), day("timesjumbo", 1813), day("timesjumbo", 1811))
# A gap with one number more than its Saturdays and one bank holiday in it:
# Easter Monday 2021 between Saturdays 1490 and 1492.
easter = [rec(50, "Jumbo Cryptic", 1490, "2021-04-17", "jumbo-1490-3-april-2021"),
          rec(51, "Jumbo Cryptic", 1491, "2021-04-17", "jumbo-1491"),
          rec(52, "Jumbo Cryptic", 1492, "2021-04-24", "jumbo-1492-10-april-2021")]
dates, _ = F.print_dates(easter, listing={})
print("JUMBO_EASTER", day("timesjumbo", 1491))
# A post whose slug mistypes its number (5121 for 5021), filed under the
# number run() settles on, is dated from its neighbours.
slip = [rec(60, "Weekend Cryptic", 5020, "2022-08-21", "sunday-times-5020-14-august-2022"),
        rec(61, "Weekend Cryptic", 5121, "2022-08-28", "sunday-times-cryptic-5121"),
        rec(62, "Weekend Cryptic", 5022, "2022-09-04", "sunday-times-5022-28-august-2022")]
dates, _ = F.print_dates(slip, listing={}, renumbered={61: 5021})
print("RENUMBERED", dates.get(("sundaytimes", 5021)))
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
check "a Jumbo title's d/m/yy date dates it" "2017-11-18" "$(got TITLE_NUMERIC)"
check "a Jumbo title's month glued to its day dates it" "2017-04-01" "$(got TITLE_GLUED)"
check "a Jumbo title naming a holiday dates it" "2017-12-26 2017-04-17 2018-08-27 2019-01-01" "$(got TITLE_HOLIDAYS)"
check "a bare 'Bank Holiday' names no day" "None" "$(got TITLE_BARE_HOLIDAY)"
check "stated Jumbo dates stand where the numbers fit the days; the gap stays undated" \
  "Sat 07 Sat 21 None" "$(got JUMBO_FITS)"
check "a Jumbo gap one number over its Saturdays takes its one bank holiday" "Mon 05" "$(got JUMBO_EASTER)"
check "a post filed under a retyped number is dated from its neighbours" "2022-08-21" "$(got RENUMBERED)"
check "listing cards: year off the capture, weekday checked" \
  "[('sundaytimes', 5078, '2023-09-24'), ('times', 29000, '2023-12-26'), ('sundaytimes', 5142, '2023-12-31')]" "$(got CARDS)"

# The Club Monthly Special and the TLS file as series of their own; the TLS is
# a Friday paper, so its title's date is read on Fridays.
check "Club and TLS rows file under their own series; a TLS title dates it on a Friday" \
  "timesclub True|tls False|Talos|2016-05-06" \
  "$(PYTHONPATH="$REPO/tools" python3 -c '
import file_times_puzzles as F
row = lambda label: {"post_id": 1, "series": label, "number": 1124}
rec = {"date": "2016-05-27", "slug": "tls-crossword-1124-by-talos-may-6-2016",
       "title": "TLS Crossword 1124 by Talos - May 6, 2016"}
print("|".join(["%s %s" % F.target(row("Monthly Club Special")), "%s %s" % F.target(row("TLS Crossword")),
                F.setter(rec, "tls"), str(F.blog_date(rec, "tls"))]))')"

[ "$fails" -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
