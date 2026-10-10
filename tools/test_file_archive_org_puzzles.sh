#!/bin/bash
# Does tools/file_archive_org_puzzles.py find the Times cryptic's title and
# not its neighbours', read the clue columns in order, keep only the clues
# both readings agree on, and match a Canberra reprint only when it is one?
#
#     bash tools/test_file_archive_org_puzzles.sh
#
# Pure functions on made-up words and puzzles, nothing written outside a
# temp dir; one solution grid fixture is read by RapidOCR where installed.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

out=$(cd "$REPO/tools" && TMP="$tmp" python3 - <<'EOF'
import json, os
from pathlib import Path
import file_archive_org_puzzles as f
import ocr_clues

fails = 0
def check(what, want, got):
    global fails
    if want == got:
        print(f"ok   {what}")
    else:
        fails += 1
        print(f"FAIL {what}: expected {want!r}, got {got!r}")

def line(text, x=100, y=100):
    words, out = text.split(), []
    for w in words:
        out.append((x, y, x + 10 * len(w), y + 16, w))
        x += 10 * len(w) + 8
    return out

# A grid whose grey blocks are stippled thresholds to specks: grids_on still
# finds it, so ocr_titles reads its title (1980-04-16, No 15,200: 13% ink).
from PIL import Image, ImageDraw
pg = Image.new("L", (3296, 4672), 240)
dr = ImageDraw.Draw(pg)
dr.rectangle([2000, 3500, 3000, 4500], fill=120)
x0, y0, cell = 300, 2900, 40
for k in range(16):
    dr.line([(x0 + k * cell, y0), (x0 + k * cell, y0 + 15 * cell)], fill=0, width=1)
    dr.line([(x0, y0 + k * cell), (x0 + 15 * cell, y0 + k * cell)], fill=0, width=1)
for r in range(15):
    for c in range(15):
        if (r * 7 + c * 3) % 5 == 0:
            for yy in range(0, cell, 6):
                for xx in range(0, cell, 6):
                    dr.point((x0 + c * cell + xx + 3, y0 + r * cell + yy + 3), fill=0)
check("a stippled-block grid is a grid to read a title by", 1, len(f.grids_on(pg)))
dr.rectangle([1500, 500, 2300, 1300], outline=0, width=3)
check("a frame round a panel is not", 1, len(f.grids_on(pg)))

# The title: the daily cryptic's, its number, a box ending at the number.
hits = f.headings([line("THE TIMES CROSSWORD NO 19,742 1 1 times weathercall")], f.TITLE)
check("1990s title read, junk after the number left out", (19742, 100 + 10*3+8 + 10*5+8 + 10*9+8 + 10*2+8 + 10*6),
      (hits[0][0], hits[0][1][2]))
check("1970s title read", [13677], [n for n, _ in f.headings([line("The Times Crossword Puzzle No 13,677")], f.TITLE)])
check("Concise, Times Two and Jumbo titles are not the cryptic's", [],
      f.headings([line("CONCISE CROSSWORD NO 2065"), line("Times Two Crossword, page 32"),
                  line("Times Jumbo Crossword No 812")], f.TITLE))
# Real misread titles from scans the pass found no title on (1977-03-31,
# 1975-06-05, 1992-03-10, 1999-03-31).
check("misread titles read: first word, a mark before Crossword, a split number, a comma read as *",
      [14564, 14012, 18862, 21065],
      [n for t in ("Hie Times Crossword Puzzle No 14,564", "The Times 'Crossword Puzzle No 14,012",
                   "THE TIMES CROSSWORD PUZZLE NO 1 8,862", "THE TIMES CROSSWORD NO 21*065")
       for n, _ in f.headings([line(t)], f.TITLE)])
# A scan cached by older heading code is made again, and a title it finds
# that no verdict covers makes the edition due.
import code_reach
reached = {d for m, d in code_reach.reach("file_archive_org_puzzles", f.SCAN_ROOTS)
           if m == "file_archive_org_puzzles"}
check("the scan key follows every name scan() reaches: the title pattern, the title OCR, the Gale page's "
      "headings and their band re-reads, the 1930 headings, the Paper method scan calls", set(),
      {"TITLE", "SOLUTION", "ocr_titles", "ocr_headings", "mend_misreads", "solution_bands", "band_solutions", "SOLUTION_BAND",
       "times1930_headings", "Paper.headings"} - reached)
check("and not the filing code: a change to it rescans nothing", set(), {"read_puzzle", "read_solution"} & reached)
# The mirror: the key moves with code scan() runs and stays with code it
# does not, here and in another module.
base = {"m": "import n\nclass P:\n    def __init__(self):\n        self.k = K\n    def used(self, x):\n"
             "        return n.helper(x)\n    def unused(self):\n        return 1\nK = 1\n"
             "def scan():\n    \"\"\"Doc.\"\"\"\n    page = P().used(2)  # a local named like a def\n    return page\n"
             "def page():\n    return 9\ndef other():\n    return 3\n",
        "n": "def helper(x):\n    return x + 1\ndef spare():\n    return 0\n"}
def key_of(**edits):
    texts = dict(base)
    for mod, (old, new) in edits.items():
        assert old in texts[mod], old
        texts[mod] = texts[mod].replace(old, new)
    return code_reach.key("m", {"scan"}, texts=texts)
k0 = key_of()
check("an edit scan() runs moves the key: a called method, a class constant, another module's helper",
      [True, True, True],
      [key_of(m=("return n.helper(x)", "return n.helper(x) * 2")) != k0, key_of(m=("K = 1", "K = 2")) != k0,
       key_of(n=("return x + 1", "return x + 2")) != k0])
check("an edit it never runs leaves it: an uncalled method, another function, another module's spare, "
      "a docstring, a comment, a def named like a local",
      [k0] * 6,
      [key_of(m=("return 1", "return 7")), key_of(m=("return 3", "return 4")), key_of(n=("return 0", "return 5")),
       key_of(m=("Doc.", "Other doc.")), key_of(m=("# a local", "# the local")), key_of(m=("return 9", "return 8"))])
helper_out = code_reach.TRANSPORT + ("n.helper",)
check("a definition named opaque (code_reach.SIZING's form) leaves the key: its edit moves nothing",
      [code_reach.key("m", {"scan"}, texts=base, opaque=helper_out), False],
      [code_reach.key("m", {"scan"}, texts={**base, "n": base["n"].replace("return x + 1", "return x + 2")},
                      opaque=helper_out), code_reach.key("m", {"scan"}, texts=base, opaque=helper_out) == k0])
sized = {f"{m}.{d}" for m, d in code_reach.reach("file_archive_org_puzzles", f.SCAN_ROOTS)}
narrow = {f"{m}.{d}" for m, d in code_reach.reach("file_archive_org_puzzles", f.SCAN_ROOTS,
                                                  opaque=code_reach.TRANSPORT + code_reach.SIZING)}
check("scan() reaches each thread-pool sizing definition, and its key leaves them out: a thread cap rescans nothing",
      (set(code_reach.SIZING), set(), True),
      (set(code_reach.SIZING) & sized, set(code_reach.SIZING) & narrow, f.sized_scan_key() != f.scan_key()))
check("a title no verdict covers makes the edition due", "titles changed",
      f.due_reason({"inputs": "h", "solutionsSeen": [], "verdicts": [], "vlm": "v",
                    "scan": {"puzzles": [{"number": 18862}]}}, "h", [], "v"))
# Gale 1991-04-13 read No 18,579's answers off 1991-04-03, a page the
# solution pairing no longer links: due once, and not again once read off
# the page it now links from.
moved = {"inputs": "h", "solutionsSeen": [18579], "vlm": "v", "scan": {"puzzles": [{"number": 18579}]},
         "verdicts": [{"number": 18579, "solutionFrom": "1991-04-03 leaf 0"}]}
check("a solution read off a page that no longer links it is due; one off any page that does is not",
      ["solution moved", None, None],
      [f.due_reason(moved, "h", [18579], "v", None, {18579: {"1991-04-20 leaf 0"}}),
       f.due_reason(moved, "h", [18579], "v", None, {18579: {"1991-04-20 leaf 0", "1991-04-03 leaf 0"}}),
       f.due_reason({**moved, "verdicts": [{"number": 18579}]}, "h", [18579], "v", None, {18579: {"1991-04-20 leaf 0"}})])
check("a fix's re-read ranks before the whole-corpus ones (scan code, --reread)", [2, 2, 3, 3],
      [f.rank_of_reason("refused not-a-grid before its fix"), f.rank_of_reason("solution moved"),
       f.rank_of_reason("scan stale"), f.rank_of_reason("--reread")])
check("every refusal cause's fix has its rank", True,
      all(f"refused {c} before its fix" in f.RANKS for c in f.REFUSALS))
refused = lambda cause, at: {"inputs": "h", "solutionsSeen": [], "vlm": "v", "readAt": at,
                             "scan": {"puzzles": [{"number": 1}]}, "verdicts": [{"number": 1, "cause": cause}]}
check("a title filed as another number than it read is not due again", None,
      f.due_reason({"inputs": "h", "solutionsSeen": [], "vlm": "v", "scan": {"puzzles": [{"number": 19453}]},
                    "verdicts": [{"number": 19458, "read_as": 19453}]}, "h", [], "v"))
# solution_title(): real headings on title-lost pages (1980-06-30 one-sided,
# 1994-02-05 Saturday prize +6, 1977-05-02 "14,539" for 14,589), and the
# mirror: a heading the neighbours' count does not fit is refused.
D = lambda s: __import__("datetime").date.fromisoformat(s)
check("solution headings take the number the filed neighbours give",
      [15262, 19458, 14590, None, None],
      [f.solution_title(D("1980-06-30"), [15261], {15259: D("1980-06-26"), 15310: D("1980-09-01")})[0],
       f.solution_title(D("1994-02-05"), [19452], {19456: D("1994-02-03"), 19459: D("1994-02-07")})[0],
       f.solution_title(D("1977-05-02"), [14539], {14587: D("1977-04-28"), 14591: D("1977-05-03")})[0],
       f.solution_title(D("1994-02-05"), [19440], {19456: D("1994-02-03"), 19459: D("1994-02-07")})[0],
       f.solution_title(D("1994-02-05"), [19452], {})[0]])
# linked_solutions(): 1997-09-09's leaf read no title from the text, so
# "20379" (20,579's heading) came through SOLUTION exact; the OCR title, or
# the filed neighbours' count, mends it, and the mirror drops one nothing fits.
edition = lambda date, titles, sols: {"date": date, "puzzles": [{"number": n, "leaf": 23} for n in titles],
                                      "solutions": [{"number": n, "leaf": 23} for n in sols]}
link = lambda found, held={}, paper=f.TIMES: [s["number"] for s in f.linked_solutions(paper, found, held)]
check("a heading read where no title was links only as a number the title or neighbours fit",
      [[20579], [20579], [], [], [16364], [16567], [], [20379]],
      [link(edition("1997-09-09", [20580], [20379])),
       link(edition("1997-09-09", [], [20379]), {20579: D("1997-09-08"), 20581: D("1997-09-10")}),
       link(edition("1997-09-09", [], [20379])),
       link(edition("1997-09-09", [], [20379]), {20400: D("1997-09-08")}),
       # 1984-03-03: a strike broke the run, so the prize is 16,364 at lag 5
       link(edition("1984-03-03", [], [16364]), {16364: D("1984-02-25"), 16368: D("1984-03-02"), 16370: D("1984-03-05")}),
       link(edition("1984-10-25", [16568], [10567])),
       # 1981-03-05: "13485" mends to a title printed in the edition itself
       link(edition("1981-03-05", [15465, 15466], [13485])),
       link(edition("1997-09-09", [], [20379]), {}, f.FT)])
# hosted(): a solution prints in the next issue, a Saturday prize's also in
# the next Saturday's (the 1970s Monday's); "19233" on a Tuesday (19,238's
# heading) and a heading a week after a puzzle whose next issue is missing
# link nothing.
check("a heading links only to a puzzle its edition hosts, never a week-later stranger",
      [[], [19237], [13996], [], [13687], [], [16364]],
      [link(edition("1993-05-25", [19239], [19233])),
       link(edition("1993-05-29", [19243], [19237])),
       link(edition("1975-05-19", [13997], [13996])),
       link(edition("1974-05-22", [], [13687]), {13687: D("1974-05-15")}),
       link(edition("1974-05-16", [], [13687]), {13687: D("1974-05-15")}),
       link(edition("1994-02-24", [19474], [19468]), {}, f.GALE),
       link(edition("1984-03-03", [16370], [16364]), {16364: D("1984-02-25")}, f.GALE)])
check("a 0 read as two marks costs one misread; marks that are not a 0's sides do not",
      [20443, 20287, None, 21443],
      [f.solution_number("211443", {20443, 20438}), f.solution_number("2IL287", {20287, 20282}),
       f.solution_number("277443", {20443, 20438}), f.solution_number("211443", {21443, 21438})])
check("Crossword split by the OCR reads", 15795, f.TITLE.search("The Times Or ossword Puzzle No 15,795") and
      int(f.TITLE.search("The Times Or ossword Puzzle No 15,795")[1].replace(",", "")))
check("a refusal read before its cause's fix is due; after it, or another cause, is not",
      ["refused not-a-grid before its fix", None, None],
      [f.due_reason(refused("not-a-grid", "2026-10-01T00:00:00+00:00"), "h", [], "v"),
       f.due_reason(refused("not-a-grid", "2099-01-01T00:00:00+00:00"), "h", [], "v"),
       f.due_reason(refused("crashed", "2026-10-01T00:00:00+00:00"), "h", [], "v")])
part = lambda acc, refusal, key: {**refused(None, "2099-01-01T00:00:00+00:00"), "verdicts": [
    {"number": 1, "solution": {"accepted": acc, "lights": 30, **({"refused": refusal} if refusal else {})}}],
    **({"solutionKey": key} if key else {})}
short = "solution short, read by other code"
check("a solution read in part or refused by other solution code, or no key, is due; whole, or this code's, is not",
      [short, short, short, None, None, None],
      [f.due_reason(part(20, None, "other"), "h", [], "v"),
       f.due_reason(part(0, "its blocks are not the puzzle's", "other"), "h", [], "v"),
       f.due_reason(part(20, None, None), "h", [], "v"),
       f.due_reason(part(30, None, "other"), "h", [], "v"),
       f.due_reason(part(30, None, None), "h", [], "v"),
       f.due_reason(part(20, None, f.solution_key()), "h", [], "v")])
check("the solution key is the solution reader's code, not the scan's", True,
      len(f.solution_key()) == 16 and f.solution_key() != f.scan_key())
import scan_queue
# A reread time is when its fix landed: one still ahead re-reads every row
# the pass reads until then, over and over.
check("no reread time is in the future", [],
      [t for t in f.REREAD_REFUSED.values()
       if scan_queue.when(t) > scan_queue.when("now")])
# Real titles the pass found no title on (no-crossword-found):
# "Times" garbled past one word, a mark after Crossword, "No" run on or
# dropped, a space in the number, its 1 read as i.
check("garbled titles read",
      [13831, 14887, 15548, 16404, 16587, 16268, 17111, 15543, 19102, 19350],
      [n for t in ("TThe Times Crossword Puzzle No 13,831", "Tfee Th:es Crossword Puzzle No 14,887",
                   "The Times Crossword . No. 15,548", "I he l imes Crossword Puzzle No 16,404",
                   "The Tiroes Crossword PuzzleNo 16,587", "The Times Crossword Puzzle 16,268",
                   "The Times Crossword Puzzle No 17,1 11", "The Times Crossword Puzzle No i.5,543",
                   "THE TIMES CROSSWORDNO 19,102", "THE TI MES CROSSWORD NO 19,350")
       for n, _ in f.headings([line(t)], f.TITLE)])
check("a garbled \"Puzzle\" before \"No\" is read (1986-05-10, 1984-04-14, 1978-10-03, 1977-06-24)",
      [17042, 16405, 15020, 14636],
      [n for t in ("Times Crossword Pnzzle No 17,042", "Times Crossword Pu/zle No 16,405",
                   "Times Crossword PozzleNo 15,020", "Times Crossword Ficzzle No 14,636")
       for n, _ in f.headings([line(t)], f.TITLE)])
check("(mirror) a word after Crossword with no \"No\" before the number is no title", [],
      [n for t in ("Concise Crossword page 12,345", "Times Crossword Competition 12,345")
       for n, _ in f.headings([line(t)], f.TITLE)])
check("a garbled Concise, solution, Listener or index line is no title", [],
      [n for t in ("CONCfSE CROSSWORD NO 20,991", "SOLUTION TO CROSSWORD NO 19,055", "USTENER CROSSWORD No 13,430",
                   "Crossword 32.", "Times Two Crossword No 10,747")
       for n, _ in f.headings([line(t)], f.TITLE)])
check("a title run together with its \"The\" is read (1995-04-12)", [19827],
      [n for n, _ in f.headings([line("THETIMES CROSSWORD NO 19,827")], f.TITLE)])
check("a title with \"Times\" run into \"Crossword\" is read (Gale 1987-01-19, ch)", [17257, 17242],
      [n for t in ("The TimesCrosswordPuzzleNo 17,257", "TheTimesCrosswordPuzzleNo17,242")
       for n, _ in f.headings([line(t)], f.TITLE)])
check("(mirror) a Concise run into \"Crossword\" is still no title", [],
      [n for t in ("ConciseCrossword No 1154", "The ConciseCrosswordNo 1,154") for n, _ in f.headings([line(t)], f.TITLE)])
words = [(2108, 2835, 2214, 2853, "Horthern Bank Ltd"), (2504, 2828, 2845, 2869, "CROSSWORD"),
         (2262, 2729, 2293, 2947, "*922393s93s"), (2108, 2896, 2183, 2914, "Rea Brothers"),
         (2468, 2892, 2882, 2924, "No.7,869 Set by CINEPHILE")]
got = [" ".join(w[4] for w in l) for l in f.printed_lines(words)]
check("OCR words make printed lines: a column apart is its own line, a column rule read as a word "
      "(FT 1992-06-10) does not join the title to its number line",
      (True, True, True), ("CROSSWORD" in got, "No.7,869 Set by CINEPHILE" in got, "Rea Brothers" in got))
check("the Sunday Times's title is not the daily's", [], f.headings([line("The Sunday Times Crossword No 2,345")], f.TITLE))
check("the cryptic's solution heading read", [18179],
      [n for n, _ in f.headings([line("Solution to Puzzle No 18,179"), line("SOLUTION TO NO 2064")], f.SOLUTION)])
check("1970s solution heading read", [13676],
      [n for n, _ in f.headings([line("Solution of Puzzle No 13,676 B.A. &so.")], f.SOLUTION)])
# A misread solution heading is found by the number one before (or, a
# Saturday's prize, six before) the page's title, its digits read loosely.
_, sols = f.TIMES.headings([line("The Times Crossword Puzzle No 15,646"), line("Solution of Push No. 15,645")])
check("a misread 'Puzzle' heading anchored on the title", [15645], [n for n, _ in sols])
_, sols = f.TIMES.headings([line("The Times Crossword Puzzle No 15,428"),
                            line("25 »2?E? one 01 Pan s Solution of Puzzle No 15,427")])
check("a heading run on from the clue column", [15427], [n for n, _ in sols])
_, sols = f.TIMES.headings([line("The Times Crossword Puzzle No 15,139"), line("Solution to Tuzzle No I5.13S")])
check("a garbled number repaired to the one before the title", [15138], [n for n, _ in sols])
_, sols = f.TIMES.headings([line("The Times Crossword Puzzle No 13,989"), line("Solution of Puzzle No 33,988")])
check("a misread digit repaired", [13988], [n for n, _ in sols])
check("a misread 'No' and a number read in pieces", [[15696], [15040], [15751], [19711]],
      [[n for n, _ in f.TIMES.headings([line(f"The Times Crossword Puzzle No {t}"), line(h)])[1]]
       for t, h in (("15,697", "Solution of Puzzle N©. 15^96"), ("15,041", "- Solution 01 Pom. Mo 15.040"),
                    ("15,752", "Solution of Puzzle No 15 ,751"), ("19,712", "Solution to Puzzle No 19,7 1 1"))])
_, sols = f.TIMES.headings([line("The Times Crossword Puzzle No 16,220", y=50), line("The Solution", 400, 900),
                            line("No. 16,219", 410, 920)])
check("'The Solution' over its number, the two lines one heading", [16219], [n for n, _ in sols])
_, sols = f.TIMES.headings([line("The Times Crossword Puzzle No 16,220", y=50), line("The Solution", 400, 900),
                            line("No. 16,219", 1400, 920)])
check("(mirror) a number in another column is not its", [], sols)
_, sols = f.TIMES.headings([line("The Times Crossword Puzzle No 15,688"), line("Solution of Puzzle No 15,682"),
                            line("Solution of Puzzle No 15,687")])
check("a Saturday's two headings, each its own", [15682, 15687], sorted(n for n, _ in sols))
# 15,682's solution printed under 15,683 and read "15,683": neither its own
# title's number nor one confusable with the day before's is guessed at.
_, sols = f.TIMES.headings([line("The Times Crossword Puzzle No 15,683"), line("Solution of Puzzle No 15,683")])
check("a heading read as its own title's number is dropped", [], sols)
_, sols = f.TIMES.headings([line("The Times Crossword Puzzle No 15,684"), line("Solution of Puzzle No 15,682")])
check("a clean heading near the title but not before it is dropped", [], sols)
_, sols = f.TIMES.headings([line("The Times Crossword Puzzle No 15,646"), line("Solution of Push No. 12,345"),
                            line("Paste on a card 4 No 15,645")])
check("a heading whose number is not the one expected, or whose words are not one, is no heading", [], sols)
check("with no title on the leaf, only an exact heading", [[18179], []],
      [[n for n, _ in f.TIMES.headings([line(t)])[1]] for t in ("Solution to Puzzle No 18,179", "Solution of Push No 18,179")])
check("two headings run into one line, each read", [[19243, 19248], [14503, 14508]],
      [sorted(n for n, _ in f.TIMES.headings([line(f"The Times Crossword Puzzle No {t}"), line(h)])[1])
       for t, h in (("19,249", "Solution to Puzzle No 19,243 Solution to Punk No 19.248"),
                    ("14,509", "Solution of Puzzle No 14,503 Solution of Puzzle No 14J50&"))])
check("(mirror) a second heading on the line numbered neither lag is no heading", [19243],
      [n for n, _ in f.TIMES.headings([line("The Times Crossword Puzzle No 19,249"),
                                       line("Solution to Puzzle No 19,243 Solution to Puzzle No 19,312")])[1]])
check("a number read in short pieces", [[19037], [15244]],
      [[n for n, _ in f.TIMES.headings([line(f"The Times Crossword Puzzle No {t}"), line(h)])[1]]
       for t, h in (("19,038", "Solution to Puzzle No 1 9.037"), ("15,245", "Solution of Puzzle No . 15, 244"))])
check("1986's 'Solution to No' heading, no 'Puzzle' word", [16983],
      [n for n, _ in f.TIMES.headings([line("The Times Crossword Puzzle No 16,984"), line("Solution to No 16,983")])[1]])
# A speck read as a word, or a mark the OCR glued between the heading's
# words (Gale 1976-1989 bands), is no part of it.
check("a speck or glued mark between a heading's words", [[14277], [14276], [17559], [17581], [16725], [17997]],
      [[n for n, _ in f.TIMES.headings([line(f"The Times Crossword Puzzle No {t}"), ws])[1]]
       for t, ws in (("14,278", [(100, 100, 196, 123, "Solution"), (185, 100, 436, 129, "n of Puzzle No 14,277")]),
                     ("14,277", line("Solution of Puzzle No : 14,276")), ("17,560", line("Solution to.Puzzle No 17,559")),
                     ("17,582", line("Solution 1 to Puzzle No 17,581")), ("16,726", line("Solution of Puzzle:No.16,725")),
                     ("17,998", line("Solution to Puzzle-No 17,997")))])
check("(mirror) unspecked, a heading still needs its lag's number and a 'Solution' or 'Puzzle' word", [[], [], []],
      [f.TIMES.headings([line(f"The Times Crossword Puzzle No {t}"), line(h)])[1]
       for t, h in (("17,582", "Solution 1 to Puzzle No 17,590"), ("16,984", "Paste-on No 16,983"),
                    ("16,984", "Paste i on No 16,983"))])
check("(mirror) with no middle word the first must read 'Solution'", [],
      f.TIMES.headings([line("The Times Crossword Puzzle No 16,984"), line("Paste on No 16,983")])[1])
# The OCR ran the connective into "Puzzle" (1983-06-11's Saturday prize).
check("a connective run into 'Puzzle' still reads, the prize six before the title", [[16147, 16152], [20105]],
      [sorted(n for n, _ in f.TIMES.headings([line("The Times Crossword Puzzle No 16,153"),
                                              line("Solution oTPnzzle No 16.147 Solution ofPitaie No 16,152")])[1]),
       [n for n, _ in f.TIMES.headings([line("The Times Crossword Puzzle No 20,111"), line("Solution tnPuzzlc No 20.105")])[1]]])
check("(mirror) a run-in heading whose number is no lag's, or both lags' alike, is no heading", [[], []],
      [f.TIMES.headings([line("The Times Crossword Puzzle No 16,153"), line("Solution oTPnzzle No 16.150")])[1],
       f.TIMES.headings([line("The Times Crossword Puzzle No 14,060"), line("Solution ofPuzzle No 14, OSS")])[1]])
# Christmas took an issue: 16,618 (Saturday 1984-12-22) under 16,622, four
# before. A clean read four or five before passes the scan; the filed dates
# decide its link, so in a full week it links nothing.
xmas = [n for n, _ in f.TIMES.headings([line("The Times Crossword Puzzle No 16,622"), line("Solution of Pnzzk No 16,618")])[1]]
check("a holiday week's prize read clean links by the filed dates, a full week's not at all", [[16618], [16618], []],
      [xmas, link(edition("1984-12-29", [16622], xmas), {16618: D("1984-12-22"), 16621: D("1984-12-28")}),
       link(edition("1984-12-29", [16622], xmas), {16616: D("1984-12-22"), 16621: D("1984-12-28")})])
check("(mirror) a garbled read four or five before is no heading", [],
      f.TIMES.headings([line("The Times Crossword Puzzle No 16,323"), line("Sohtian of Puzzle No 16J18")])[1])
check("(mirror) pieces costing alike to both lags are no heading", [],
      f.TIMES.headings([line("The Times Crossword Puzzle No 14,060"), line("Solution of Puzzle No 14, OSS")])[1])
_, sols = f.TIMES.headings([line("The Times Crossword Puzzle No 16,577", y=50), line("The Solution", 400, 900),
                            line("Prize Puzzle", 405, 925), line("No 16,576", 420, 950)])
check("'The Solution' over 'Prize Puzzle' over its number", [16576], [n for n, _ in sols])
_, sols = f.TIMES.headings([line("The Times Crossword Puzzle No 16,577", y=50), line("The Solution", 400, 900),
                            line("Puzzle closes", 405, 925), line("No 16,576", 420, 950)])
check("(mirror) any other line between them is not skipped", [], sols)

# The columns: left then right, a number read apart joined to its row, a
# second copy of words dropped, cut at the solution heading.
grid = (100, 100, 800, 800)
lines = [line("ACROSS", 100, 820), [(100, 842, 118, 858, "1")], line("Nymph with broken heart (8)", 130, 840),
         line("DOWN", 470, 820), line("2 Hermit is strangely secure (7)", 470, 840),
         line("2 Hermit is strangely secure (7)", 470, 841),
         line("Solution to Puzzle No 13,676", 100, 870), line("rubbish (3)", 100, 890)]
check("columns read left then right, a row joined, a copy dropped, cut at the solution",
      "ACROSS\n1 Nymph with broken heart (8)\nDOWN\n2 Hermit is strangely secure (7)",
      f.column_text(f.columns(lines, grid)))
far = [line("ACROSS", 100, 820), line("1 Nymph (8)", 100, 840), line("9 Gap (5)", 100, 840 + f.GAP + 40)]
check("a gap ends a column", "ACROSS\n1 Nymph (8)", f.column_text(f.columns(far, grid)))
# A clue's run-on line that opens on a STOP word ends nothing; the notice does.
run_on = [line("DOWN", 100, 820), line("1 See last stages of Le Mans", 100, 840),
          line("championship, possibly (4).", 130, 860), line("2 Impressive maiden (7).", 100, 880),
          line("Championship final tomorrow", 100, 900), line("3 Not a clue (5)", 100, 920)]
check("a run-on line opening on a STOP word is the clue's, a notice ends the column",
      "DOWN\n1 See last stages of Le Mans\nchampionship, possibly (4).\n2 Impressive maiden (7).",
      f.column_text(f.columns(run_on, grid)))

# tidy(): OCR's slips in the print's shape.
check("braces and square brackets read as round ones", "1 Poet's way (5)\n2 Talks (3,2)",
      f.tidy("1 Poet's way {5}\n2 Talks [3,2]"))
check("a number run into its word split off", "1 Mythical king (9)", f.tidy("1Mythical king (9)"))
check("a number lost after a count marked for the grid", "10 Nurse (7)\n? Holds fast (5)",
      f.tidy("10 Nurse (7)\nHolds fast (5)"))
check("a number lost after the heading marked", "ACROSS\n? Nymph (8)", f.tidy("ACROSS\nNymph (8)"))
check("a wrapped line is not marked", "10 Nurse holding\nNote (7)", f.tidy("10 Nurse holding\nNote (7)"))
check("a count with a broken close read as one", "19 Stole pig (3)", f.tidy("19 Stole pig off3j".replace(" off", "")))

# Page text after the list's last count: a speck after the count ("(5). _")
# is no text, so the footer after it is dropped, not read as a clue.
check("a speck after a count is dropped and the footer with it",
      "DOWN\n24 Realism is the beauty of Keats\n(5)",
      f.tidy("DOWN\n24 Realism is the beauty of Keats\n(5). _\nConte crossword, base 22"))
check("a pointer to another page's puzzle ends the column",
      [True, True, True, False, False],
      [bool(f.STOP.match(t)) for t in ("Conte crossword, base 22", "Coacise crosswurd, page 22",
                                       "The solution to the Collins Competition", "Cross words about 22",
                                       "Crossed words, quite 2")])
# The list's last clue holding the next one (its count lost) is split.
p, _ = f.parse("ACROSS\n1 Walpole nominated as poet (6)\nDOWN\n22 No good having female in group\n"
               "24 Realism is the beauty of Keats\n(5)")
check("the last clue's run-on clue is split off",
      [({22}, "No good having female in group", set()), ({24}, "Realism is the beauty of Keats", {"5"})],
      [(c["tokens"][0], c["text"], c["enums"]) for c in p["down"]])
p, _ = f.parse("ACROSS\n1 Walpole nominated as poet (6)\nDOWN\n22 Rest at 2 Downing Street (5)")
check("a reference in the last clue is not split", ["Rest at 2 Downing Street"], [c["text"] for c in p["down"]])
# The columns under the grid split at their gutter, not the grid's middle:
# a right-hand clue whose number starts left of the middle is the right
# column's, never run into the left column's row (ftcryptic-9091).
grid = (2270, 3000, 2905, 3400)
words = [[(2253, 3462, 2565, 3486, "28 Take part of case for leisure")],
         [(2577, 3462, 2886, 3484, "22 Affected by American univer-")],
         [(2581, 3419, 2889, 3442, "20 Corrects sexually innocent")],
         [(2270, 3415, 2569, 3435, "1 Graduate teachers object to")]]
split = f.under_gutter(words, grid)
cols = f.columns(words, grid, split=split)
check("the gutter lies between the columns", True, 2569 < split < 2577)
check("a right-hand clue left of the grid's middle stays in its column",
      ["1 Graduate teachers object to", "28 Take part of case for leisure"], [l[4] for l in cols[0]])

# fault(): what the filer refuses to file, and what the print really has.
for text, enum, cells, want in [
        ("Corrects sexually innocent Poles 22 Affected by American", "8", 8, "holds a clue number"),
        ("The solution of Saturday's Prize Puzzle No 18,178 will appear next Saturday 26 The point is", "9", 9,
         "holds a clue number"),
        ("Conte crossword, page 22", "5", 5, "holds the page's text"),
        ("Untie reef knots (41. Times Two Crossword, page 44", "4", 4, "holds the page's text"),
        ("The solution to the Collins Competition will now Qualifier puzzle", "4", 4, "holds the page's text"),
        ("None", "5", 5, "the text is the word None"),
        ("Fine island, jolly compact", "5", 4, "its count"),
        # ftcryptic-7261 8-down: the scan prints (7,6), one reading "(7.8) ' -".
        ("Advice note can change ' prior announcement (7.8) ' -", "7,6", 13, "its words end in a count"),
        ("Mother's cross raised (3);", "4", 4, None),
        ("Laugh immoderately as Jack gets into quarrel", "4,5", 9, None),
        ("3 3 on the watch", "5", 5, None),
        ("under twenty-one", "5", 5, None),
        ("Clumsy and old-fashioned in hack work", "11", 11, None),
        ("Mournful supporter in English lac", "7", 7, None),
        ("Basic material for 9 or Junius?", "9", 9, None),
        ("Making notes to phone about the 18", "9", 9, None),
        ("Removal of 25 I notice in distress outside", "8", 8, None),
        ("See 9 Across", None, 5, None),
        ("Market town supplying meat on 24 and 31 December?", "5", 5, None),
        ('"Hollow pamper\'d Jades of - (2 Hen. IV)', "4", 4, None),
        ('Thomas Huxley\'s 73 "organized common sense', "7", 7, None)]:
    got = ocr_clues.fault(text, enum, cells)
    check(f"fault {text[:30]!r}", want, got and got[:len(want)] if want else got)
laid, blank = f.unfit_blanked({"22-down": ("Poles 22 Affected by it", "6", None), "1-across": ("Fine", "6", None),
                               "3-across": ("Too long", "9", None)}, {}, {"22-down": 6, "1-across": 6, "3-across": 6})
check("an unfit clue is filed blank, its count kept when it fills the light",
      ({"22-down": ("", "6", None), "1-across": ("Fine", "6", None), "3-across": ("", None, None)},
       ["22-down", "3-across"]), (laid, sorted(blank)))
laid, blank = f.unfit_blanked({"1-across": ("Stop to0 late", "6", None), "2-down": ("Long", "4,3", ["2-down", "3-down"])},
                               {}, {"1-across": 6, "2-down": 4, "3-down": 3, "4-down": 5})
check("a suspect word, or a light no reading laid, is filed blank, a linked tail is not",
      ({"1-across": ("", "6", None), "2-down": ("Long", "4,3", ["2-down", "3-down"]), "4-down": ("", None, None)},
       ["1-across", "4-down"]), (laid, sorted(blank)))
check("a dash or comma run into the words either side is spaced",
      ["Hang play \u2014 change", "Two elements \u2014 somewhat", "now \u2014 then", "Good rum, as do, too",
       "usage: acceptable", "1,000 men", "self-made", "Why? Yes!"],
      [ocr_clues.clean(t) for t in ("Hang play--change", "Two elements\u2014somewhat", "now -- then",
                                    "Good rum,as do,too", "usage:acceptable", "1,000 men", "self-made",
                                    "Why\uff1f Yes\uff01")])
check("a non-Latin character or a full stop inside a word is suspect", [True, True, False, False, False],
      [bool(ocr_clues.suspect(t)) for t in ("\u738b4 Hang play", "Mutilate many.fish", "Caf\u00e9 \u2014 \u2018so\u2019 \u00a35",
                                            "Oval . . . the C.I.D. man", "e.g. a dog")])
check("a clue spaced by clean() is no longer suspect", [], ocr_clues.suspect(ocr_clues.clean("Agreed\u2014an unruly sort,as")))
puz = {"entries": [{"number": 1, "direction": "across", "length": 6, "clue": {"text": "Fine", "enumeration": "6"}},
                   {"number": 2, "direction": "down", "length": 4, "group": ["2-down", "3-down"],
                    "clue": {"text": "Long 2 Joined", "enumeration": "4,3"}},
                   {"number": 3, "direction": "down", "length": 3, "clue": {"text": "See 2"}}]}
check("faults() counts a linked clue's lights together", ["2-down"], sorted(f.faults(puz)))
check("a puzzle with a fault is not complete", False, f.complete(puz))

# A word two other readings share that is no word goes in mended.
others = [ocr_clues.tokens("This lener may be umsigned it should be remembered"),
          ocr_clues.tokens("This ietter may be umsigned it should be remnembered"),
          ocr_clues.tokens("This letter be 14")]
check("a word lost from this reading goes in as the known word the others misread",
      "This letter may be unsigned it should be remembered",
      ocr_clues.agree("This letter may be it should be remembered", others)[0])

# agree(): only what both readings say, or what the dictionary settles.
stream = ocr_clues.tokens("8 Hope created this exalted 9 Bottom of a ship (3) 10 Nurse hoiding note (7) 11 Prinz Ahdk (5)")
check("both readings agree", ("Bottom of a ship", "agree"), ocr_clues.agree("Bottom of a ship", stream))
check("a misread settled by the other reading's dictionary word",
      ("Nurse holding note", "settled by the dictionary"), ocr_clues.agree("Nurse holding note", stream))
check("the clue's misread replaced by the other reading's word",
      ("Hope created this exalted", "settled by the dictionary"), ocr_clues.agree("Hope crealed this exalted", stream))
check("two non-words are a disagreement", None, ocr_clues.agree("Prinz Ahdq", stream)[0])
check("a word the other reading lacks is a disagreement", None, ocr_clues.agree("Bottom of a big ship", stream)[0])
check("both readers' one non-word mended to the known word a letter off", "Nurse holding note",
      ocr_clues.agree("Nurse hoiding note", stream)[0])

check("a capital only one reader saw inside the clue dropped", ("What is stated", "settled by the dictionary"),
      ocr_clues.agree("What Is stated", ocr_clues.tokens("27 What is stated (9)")))
got, _ = ocr_clues.reconcile({"25-across": ("As worn by agitator in back- street", "8", None)},
                     "25 As worn by agitator in back-\nstreet (8)")
check("a word hyphenated over a line end is joined as the corpus prints it", "As worn by agitator in backstreet",
      got["25-across"][0])
check("the clue's first word keeps its capital", ("Bottom of a ship", "agree"),
      ocr_clues.agree("Bottom of a ship", ocr_clues.tokens("bottom of a ship")))

# Three readings: a word the other two share outvotes mine; a mark no other
# reading has is dropped; a non-word all three read is kept.
two = [ocr_clues.marked("8 Wisdom shown by school-head when dress is questionable (10)"),
       ocr_clues.marked("8 Wisdom shown by school-head when dress is questionabie (10)")]
check("a lone comma no other reading has dropped",
      "Wisdom shown by school-head when dress is questionable",
      ocr_clues.agree("Wisdom shown by, school-head when dress is questionable", two)[0])
check("a comma two readings have kept", "Talk, about a fellow",
      ocr_clues.agree("Talk, about a fellow", [ocr_clues.marked("Talk, about a fellow"), ocr_clues.marked("Talk about a fellow")])[0])
check("the spelling the other two readings share outvotes mine (dictionary words both)",
      "Cashing in on Nigel's air", ocr_clues.agree("Cashing in on Nigel's ail",
                                           [ocr_clues.marked("Cashing in on Nigel's air")] * 2)[0])
check("a word one of two other readings has stands", "Sun god's not out",
      ocr_clues.agree("Sun god's not out", [ocr_clues.marked("Son god's not out"), ocr_clues.marked("Sun gods not out")])[0])
check("a non-word all three readings have, no letter from a word, kept", "Get production up qzxvbn",
      ocr_clues.agree("Get production up qzxvbn", [ocr_clues.marked("Get production up qzxvbn")] * 2)[0])
check("a name the corpus's clues know is a word", "Captain Hornblower at sea",
      ocr_clues.agree("Captain Hornblower at sea", [ocr_clues.marked("3 Captain Hornblower at sea (7)", breaks=True)] * 2)[0])
check("a lone letter no other reading has is a speck", "Annual production",
      ocr_clues.agree("Annual l production", [ocr_clues.marked("4 Annual production (5)", breaks=True)] * 2)[0])
got, blank = ocr_clues.reconcile({"8-down": ("Wisdom shown by, school-head", "10", None)},
                         ["8 Wisdom shown by school-head (10)", "8 Wisdom shown by school-head (10)"])
check("reconcile votes with every reading it is given", "Wisdom shown by school-head", got["8-down"][0])

# A real word misread as another (real readings off the gold editions).
def vote(clue, *readings):
    return ocr_clues.agree(clue, [ocr_clues.marked(t, breaks=True) for t in readings])[0]
check("a number standing for a word it looks like takes the word: \"10\" for \"to\" (Times 18,180 12A)",
      "When in quarters, be agreeable to forming a unit",
      vote("When in quarters, be agreeabie 10 forming a unit",
           "1 When in quartets , be agreeable to forming a unit 1",
           "1 When in quarters , be agreeable Io forming a unit 1",
           "yt be tempted by partnership 1 Smoothed an upset in"))
check("\"3\" for \"a\" where the other readings read \"a\" (Times 13,678 19A)", "A boy is backward, and not a girl",
      vote("A bny is backward, and not 3 girl", "1 A boy Is backward , and not a girl 1",
           "1 A bny is backward , and not a gir 1", "1 A boy is backward , and pot a girl 1"))
check("a number the other readings print as a number stays", "Like a don in trouble with Homer in 3",
      vote("Like a don in trouble with Homer in 3", "15 Like a don in trouble with Homer in 3 (5)",
           "15 Like a don in trouble with Homer in 3 (5)"))
check("a word one confused letter from a commoner one a reader has that fits far better (Times 16,786 20D)",
      "Innovator of single element in breakwater",
      vote("Innovator of single clement in breakwater", "1 Innovalor of singic clement in brcakwaleri 1",
           "1 Innovator of singie element in breakwaler 1", "1 Innovator of single clement in reakwater 1"))
check("\"ad\" for \"an\", one reader reading \"an\" (Times 13,682 23A)", "Its rate is adjusted for an entertainer",
      vote("Its rate is Jdijusted for ad entertainer", "1 Its rare is adjusted for ad entertainer f",
           "1 Irs rate is aujusted for ad cntertainer f", "1 tts rate is adjusted for an 1"))
check("a non-word every reader shares, one confused letter from a word (Times 13,682 13A)",
      "In its turn it does us a power of good",
      vote("In its turn it does us a power ot good", "1 In its turn it does us a power ot good f",
           "1 In its turn it does usa power ot good 1", "1 In its turn it does us a power ot good 1"))
check("two readings' \"al\" gives way to \"at\" (Times 18,179 22D)", "In the Orient reeds are served at dinner",
      vote("In the Orient reeds are served at dinner", "1 In the Orient reeds are served al dinner 1",
           "1 In the Orient reeds are served al dinner 1", "wros they or reckon are following the"))
check("a word three readings share is no slip of a commoner one that fits no better (Times 19,742 28A)",
      "Result may be tame but filling food",
      vote("Resull may be tame but filling food", "Times Two Crossword ,",
           "1 Result may be tame but filling food 1", "1 Result may be tame but hifing food 1"))
for clue in ("Chance it perhaps if over 50", "Lace it tight round top of stocking",
             "Excellent worker in firm, one co-opted originally", "Disturbed when riding on 19ac"):
    check(f"a word every reading has stays, however a confused letter would fit: {clue!r}", clue,
          vote(clue, f"4 {clue} (5)", f"4 {clue} (5)", f"4 {clue} (5)"))

# Words and marks this reading lost, and the print's commonest mark slips.
three = [ocr_clues.marked(t, breaks=True) for t in ("9 Hurtful stuff, nicer as a cocktail? (7)",
                                            "9 Hurtful stuff, nicer as a cocktail? (7)",
                                            "9 Hurtfui stuff nicer as a cocktail (7)")]
check("a comma most other readings have put in", "Hurtful stuff, nicer as a cocktail?",
      ocr_clues.agree("Hurtful stuff nicer as a cocktail?", three)[0])
lost = [ocr_clues.marked(t, breaks=True) for t in ("18 It's no go when caught (8)", "18 It's no go when caught (8)",
                                           "18 Its no go when caught (8)")]
check("lost opening words most readings have put in, with the capital", "It's no go when caught",
      ocr_clues.agree("Go when caught", lost)[0])
check("lost opening words the readings differ on blank the clue", None,
      ocr_clues.agree("Go when caught", [ocr_clues.marked(t, breaks=True) for t in
                                 ("18 It's no go when caught (8)", "18 Is so go when caught (8)")])[0])
check("lost closing words most readings have put in", "Girls were well sustained by it",
      ocr_clues.agree("Girls were well sustained by", [ocr_clues.marked("19 Girls were well sustained by it (7)", breaks=True)] * 2)[0])
check("a dictionary tie goes to the word the corpus's clues put there", "A boy is backward",
      ocr_clues.agree("A bny is backward", [ocr_clues.marked("19 A boy is backward (4)", breaks=True),
                                    ocr_clues.marked("19 A bay is backward (4)", breaks=True)])[0])
check("a dictionary tie no neighbour settles blanks the word", None,
      ocr_clues.agree("Qxv bny qxv", [ocr_clues.marked("1 Qxv boy qxv (3)", breaks=True),
                              ocr_clues.marked("1 Qxv bay qxv (3)", breaks=True)])[0])
check("one reading's far shorter dictionary word is no rival", "Chucked one in",
      ocr_clues.agree("Chucked one in", [ocr_clues.marked("24 Chuckeu one in (5)", breaks=True),
                                 ocr_clues.marked("24 Che one in (5)", breaks=True)])[0])
check("a rare word one ink slip from a far commoner one takes the commoner", "Bob hangs on to this",
      ocr_clues.agree("Bob hangs ou to this", [ocr_clues.marked("3 Bob hangs ou to this (5)", breaks=True)] * 3)[0])
check("the next clue run on is cut off, the count from the grid",
      ({"5-down": ("Twists ends of osier into knot", "7", None)}, {}),
      ocr_clues.reconcile({"5-down": ("Twists ends of osier into knot (7k 6 Protection for working", None, None)},
                  ["5 Twists ends of osier into knot (7) 6 Protection for working"], {"5-down": 7, "6-down": 3}))
check("a lone letter after the clue is its misread count, the count from the grid",
      ({"2-down": ("A bit of nice dark wood", "5", None)}, {}),
      ocr_clues.reconcile({"2-down": ("A bit of nice dark wood", None, None)},
                  ["2 A bit of nice dark wood s 3 Next", "2 A bit of nice dark wood a 3 Next"], {"2-down": 5}))
check("a mark dropped between two words leaves their space", "Lack of spirit after a storm",
      ocr_clues.agree("Lack of spirit:after a storm", [ocr_clues.marked("1 Lack of spirit after a storm (4)", breaks=True)] * 2)[0])
check("a misread clue number before the capital dropped", "Not small horse-pistols",
      ocr_clues.agree("I Not small horse-pistols", [ocr_clues.marked(t, breaks=True) for t in
                                            ("21 Not small horse-pistols (5)", "21 Not smal horse-pistols (5)")])[0])
check("a full stop before a lower-case word is a comma", "Let nine go loose, being merciful",
      ocr_clues.clean("Let nine go loose. being merciful"))
check("an ellipsis and an abbreviation keep their stops", "Oval . . . the C.I.D. man",
      ocr_clues.clean("Oval . . . the C.I.D. man"))
check("a stop read twice after a word is one; an ellipsis stands (No 3's 52A, mirror)",
      ["heard in 1857.", "for many years.", "Oval ... end..."],
      [ocr_clues.clean(t) for t in ("heard in 1857..", "for many years..", "Oval ... end...")])
check("a speck read as a hyphen after a lone A or to is a space (No 3's 5A, 26A)",
      ["A town in the Punjab", "applied to part of India"],
      [ocr_clues.clean(t) for t in ("A-town in the Punjab", "applied to-part of India")])
check("the hyphens clues print after A or to stand (mirror)", ["to-day and to-morrow", "an A-bomb", "a-hunting we go"],
      [ocr_clues.clean(t) for t in ("to-day and to-morrow", "an A-bomb", "a-hunting we go")])
check("a misread clue number dropped takes its stop (No 3's 52D)", "Frontier cantonment.",
      ocr_clues.agree("A. Frontier cantonment.", [ocr_clues.marked(t, breaks=True) for t in
                                              ("52 Frontier cantonment. 53 Next", "52 Frontier cantoment. 53 Next")])[0])
check("an I last before the count is an exclamation mark", "Flirted outrageously! (7)",
      ocr_clues.clean("Flirted outrageously I (7)"))
check("a word broken over a line end is joined", "Almost admire a lieutenant unknown",
      ocr_clues.clean("Almost admire a lieutenant un-\nknown"))
check("a line-end hyphen the corpus's clues print closed is the line break's", "agitator in backstreet",
      ocr_clues.clean("agitator in back-\nstreet"))
check("a line-end hyphen the corpus's clues print hyphenated is the compound's", "start is short-lived",
      ocr_clues.clean("start is short-\nlived"))
check("a name hyphenated over a line end is joined", "resembling Palgrave's Treasury",
      ocr_clues.clean("resembling Pal-\ngrave's Treasury"))
check("a compound the corpus never prints keeps its hyphen", "Wisdom shown by school-head",
      ocr_clues.clean("Wisdom shown by school-\nhead"))
check("a hyphen inside a line breaking a lexicon word is joined",
      ["Kohoutek's brilliant predecessor", "Becoming a supporter with obvious hesitation", "to do housework"],
      [ocr_clues.unhyphen(t) for t in ("Kohoutek's brilliant pre-decessor",
                                       "Becoming a supporter with ob-vious hesitation", "to do house-work")])
check("a hyphen inside a line stands where the corpus's clues print that form",
      ["in back-street", "Sea-bird", "It's breath-taking", "to co-operate", "is short-lived", "by school-head",
       "an Anglo-Saxon", "a well-to-do man"],
      [ocr_clues.unhyphen(t) for t in ("in back-street", "Sea-bird", "It's breath-taking", "to co-operate",
                                       "is short-lived", "by school-head", "an Anglo-Saxon", "a well-to-do man")])
import vlm_reader
_ask = vlm_reader.ask
vlm_reader.ask = lambda image, prompt, max_tokens=0: "14 Kohoutek's brilliant pre-decessor (7, 5)"
check("the VLM's column and pick readings have a line end's hyphen joined",
      ["14 Kohoutek's brilliant predecessor (7, 5)", "14 Kohoutek's brilliant predecessor (7, 5)"],
      [vlm_reader.read(None), vlm_reader.pick_in(None, "14-across", [])])
vlm_reader.ask = _ask
got, _ = ocr_clues.reconcile({"8-down": ("Odd minorities can with right bring counter-charges", "14", None)},
                             ["8 Odd minorities can with right bring counter-charges\n(14)"] * 2)
check("an OCR reading's hyphen inside a line is the print's own", "Odd minorities can with right bring counter-charges",
      got["8-down"][0])
check("a 1 standing as a word inside a clue is an I", "in letter I posted (4)", ocr_clues.clean("in letter 1 posted (4)"))
check("a 1 naming a light stays", ["see 1 down", "Cross 1 and 2 (5)", "in 1 Across (4)", "in 1982 film"],
      [ocr_clues.clean(t) for t in ("see 1 down", "Cross 1 and 2 (5)", "in 1 Across (4)", "in 1982 film")])
check("a lone I some reading lacks is a speck", ["Turn on at length an item", "Turn on at length an item"],
      [ocr_clues.agree("Turn on at length an item", [ocr_clues.marked(t, breaks=True) for t in (
           "8 Turn on at length 1 an item (6)", "8 Turn on at length 1 an item (6)", "8 Turn on at length an item (6)")])[0],
       ocr_clues.agree("Turn on at length I an item", [ocr_clues.marked(t, breaks=True) for t in (
           "8 Turn on at length an item (6)", "8 Turn on at length an item (6)", "8 Turn on at length I an item (6)")])[0]])
check("a lone I every reading has stands", "in letter I posted",
      ocr_clues.agree("in letter I posted", [ocr_clues.marked(ocr_clues.clean("8 in letter 1 posted (6)"), breaks=True)] * 3)[0])
got, blank = ocr_clues.reconcile({"1-down": ("Unusual way over the mountains", "7", None)},
                         ["25 Vanquished (8)\nDOWN\nI Unusual way over the mountains (7)"] * 2)
check("the DOWN heading over 1 down is no lost word of it", "Unusual way over the mountains", got["1-down"][0])
check("a heading read badly is still the heading; a stray capital word is not",
      ["DOWN", "DOWN", "ACROSS", None, None],
      [f.heading_of(t) for t in ("DOW'N", "DOIN", "AROSS", "Down in", "SOLUTION")])
check("a line starting a lower-case down carries on the line before", "9 Engineer tbe break down (8).\n10 Next (4)",
      f.tidy("9 Engineer tbe break\ndown (8).\n10 Next (4)"))
check("a possessive of a dictionary word is a word", True, ocr_clues.is_word("Lear's") and ocr_clues.is_word("bookie's"))

# The solution grid's blocks: a heavy print's block flecked with paper is a
# block; a light whose letter is fat is not.
import numpy as np, trove_solution_ocr as tso
rng = np.random.default_rng(1)
gray = np.full((300, 300), 255, np.uint8)
for k in range(6):
    gray[k * 60:k * 60 + 6, :] = 0
    gray[:, k * 60:k * 60 + 6] = 0
gray[60:120, 60:120] = 0
fleck = rng.random((60, 60)) < 0.15
gray[60:120, 60:120][fleck] = 255           # the block: 15% white flecks
gray[130:170, 140:160] = 0                  # a fat letter in the light at (2, 2)
gray[130:150, 125:175] = 0
gray = np.where(gray == 0, rng.integers(0, 40, gray.shape), rng.integers(200, 256, gray.shape)).astype(np.uint8)
grid5 = [".....", ".#...", ".....", ".....", "....."]
check("a flecked block read as a block, a fat letter's light as a light", 1.0,
      tso.block_agreement(gray, grid5, (0, 0, 60, 60)))

# improves(): a reading replaces a file this tool filed when it beats it.
pz = Path(os.environ["TMP"]) / "pz"; pz.mkdir()
def p3(texts, acq=f.TOOL):
    return {"source": {"acquiredBy": acq}, "dimensions": {"cols": 3, "rows": len(texts)},
            "entries": [{"number": i + 1, "direction": "across", "position": {"x": 0, "y": i}, "length": 3,
                         "clue": {"text": t}, "solution": None} for i, t in enumerate(texts)]}
(pz / "own.json").write_text(json.dumps(p3([""])))
(pz / "theirs.json").write_text(json.dumps(p3([""], "tools/acquire_book.py")))
(pz / "two.json").write_text(json.dumps(p3(["Top", "", ""])))
check("a fuller reading that blanks a clue the file has does not replace it", False,
      f.improves(p3(["", "Low", "Mid"]), pz / "two.json"))
check("a fuller reading replaces this tool's file, never another tool's or an equal one",
      [True, False, False], [f.improves(p3(["Top"]), pz / "own.json"),
                             f.improves(p3(["Top"]), pz / "theirs.json"),
                             f.improves(p3([""]), pz / "own.json")])

# expected_number(): a misdated item is caught, a dated one passes.
import datetime
check("numbers the dates imply, either side of the shutdown",
      [True, True, True, True, False],
      [abs(n - f.expected_number(datetime.date.fromisoformat(d))) <= f.NUMBER_SLACK
       for d, n in [("1974-05-02", 13677), ("1985-07-11", 16786), ("1995-01-03", 19742),
                    ("1998-07-25", 20853), ("1965-07-05", 20212)]])

# placed(): the edition's date fixes a misread number when its filed
# neighbours run unbroken, and refuses one out of date order (times-18873
# was read as 18879 between 18872 on Saturday and 18874 on Tuesday).
D = datetime.date.fromisoformat
held = {18872: D("1992-03-21"), 18874: D("1992-03-24")}
check("a number misread between unbroken neighbours files as the one its date fixes",
      (18873, None), f.placed(18879, D("1992-03-23"), held))
gap = {18872: D("1992-03-21"), 18880: D("1992-04-02")}
check("across a gap, a number out of date order is refused and one in order kept",
      [None, 18875], [f.placed(18890, D("1992-03-25"), gap)[0], f.placed(18875, D("1992-03-25"), gap)[0]])
check("a number filed for another day is refused",
      None, f.placed(18880, D("1992-03-25"), {18880: D("1992-04-02")})[0])
# mended_digit(): the 1983 FT's "1" read as "4" ("5,401" on 1983-02-18, when
# the date implies 5,099) is mended by the number its filed neighbours imply,
# or with none, by the one digit worth 100 or more that brings it near the
# date's number. Anything else stays refused.
check("a number one digit off what its unbroken neighbours imply is theirs",
      5101, f.mended_digit(5401, D("1983-02-18"), 5099, {5100: D("1983-02-17"), 5102: D("1983-02-19")}))
check("a number one digit short of what its unbroken neighbours imply is theirs (1930's 8 for 88)",
      88, f.mended_digit(8, D("1930-05-15"), 88, {87: D("1930-05-14"), 89: D("1930-05-16")}))
check("(mirror) a number one digit short of nothing its neighbours imply mends nothing",
      None, f.mended_digit(9, D("1930-05-15"), 88, {87: D("1930-05-14"), 89: D("1930-05-16")}))
check("(mirror) neighbours implying a number two digits off mend nothing",
      None, f.mended_digit(5421, D("1983-02-18"), 5099, {5100: D("1983-02-17"), 5102: D("1983-02-19")}))
check("with no neighbours, the hundreds digit that brings it near the date's number is mended",
      5101, f.mended_digit(5401, D("1983-02-18"), 5099, {}))
check("(mirror) a number two digits from the date's, or only its units digit, is not mended",
      [None, None, None], [f.mended_digit(5481, D("1983-02-18"), 5099, {}),
                           f.mended_digit(20212, D("1965-07-05"), 10914, {}),
                           f.mended_digit(200, D("1930-10-03"), 209, {})])
check("six issues a week, none on Sunday", [1, 6, 7], [f.issues_between(D("1992-03-21"), D("1992-03-23")),
      f.issues_between(D("1992-03-21"), D("1992-03-28")), f.issues_between(D("1992-03-21"), D("1992-03-30"))])

# same_scan(): a scan page already filed under another number for that day
# is refused (times-19130 was times-19129 misread); a refile of the same
# number, or the page on another day, is not.
scan_root = Path(os.environ["TMP"]) / "scan_root"
(scan_root / "puzzles" / "times" / "1993").mkdir(parents=True)
edition_dir = Path(os.environ["TMP"]) / "NewsUK1993UKEnglish" / "1993-01-16_64544"
edition_dir.mkdir(parents=True)
(edition_dir / "pages.json").write_text(json.dumps(
    {"item": "NewsUK1993UKEnglish", "edition": "Jan 16 1993, The Times, #64544, UK (en)"}))
url = f.PAGE_URL.format(edition=f.edition_of(edition_dir, {"item": "NewsUK1993UKEnglish"}), leaf=17)
check("the scan url names the edition's file inside the item, not the item alone",
      "https://archive.org/details/NewsUK1993UKEnglish/Jan%2016%201993%2C%20The%20Times%2C%20%2364544%2C%20UK%20%28en%29"
      "/page/n17/mode/1up", url)
check("a second edition of the item has a different url",
      True, url != f.PAGE_URL.format(edition="NewsUK1993UKEnglish/Jan%2018%201993%2C%20The%20Times%2C%20%2364545%2C%20UK%20%28en%29", leaf=17))
(scan_root / "puzzles" / "times" / "1993" / "times-19129.json").write_text(
    json.dumps({"date": "1993-01-16", "source": {"url": url}}))
real_root, f.ROOT = f.ROOT, scan_root
check("a scan page held under another number that day is refused, naming both",
      True, "19130" in (f.same_scan(19130, url, D("1993-01-16"), "times") or "")
      and "19129" in f.same_scan(19130, url, D("1993-01-16"), "times"))
check("a refile of the number holding the page, and the page on another day, are not",
      [None, None], [f.same_scan(19129, url, D("1993-01-16"), "times"),
                     f.same_scan(19130, url, D("1993-01-18"), "times")])

# held_dates() and held_scans() share one parse per file (held_files): a
# read unit forked after plan() warmed it parses no file of the series,
# and a file that changes is parsed again.
(scan_root / "puzzles" / "times" / "1993" / "times-19131.json").write_text(json.dumps({"date": "1993-01-18"}))
parsed, real_loads = [], f.json.loads
f.json.loads = lambda text, *a, **k: parsed.append(text) or real_loads(text, *a, **k)
f._HELD.clear()
f.held_dates("times")
check("held_scans after held_dates parses no file again", [{(url, "1993-01-16"): [19129]}, 2],
      [f.held_scans("times"), len(parsed)])
os.utime(scan_root / "puzzles" / "times" / "1993" / "times-19131.json", ns=(1, 1))
check("a file whose stat moved is parsed again, the other not",
      [{19129: D("1993-01-16"), 19131: D("1993-01-18")}, 3], [f.held_dates("times"), len(parsed)])
f.json.loads = real_loads
f.ROOT = real_root

# lay_loose(): each clue alone on its own light; a misread count is not laid.
g = ["...", ".#.", "..."]
parsed = {"across": [{"tokens": [{1}], "text": "Top", "enums": {"3"}, "see": None},
                     {"tokens": [{3}], "text": "Bottom", "enums": {"5"}, "see": None}],
          "down": [{"tokens": [{1}], "text": "Left", "enums": {"3"}, "see": None},
                   {"tokens": [{2, 3}], "text": "Right", "enums": {"3"}, "see": None}]}
loose, bad = f.lay_loose(parsed, g)
check("clues laid on their own lights, a number read two ways on the one light it names; a wrong count not",
      ({"1-across": "Top", "1-down": "Left", "2-down": "Right"}, ["3-across"]),
      ({k: v[0] for k, v in loose.items()}, bad))

# A clue whose number was lost takes the one light its neighbours leave free.
g = ["...#...", ".......", "...#..."]
lost = {"across": [{"tokens": [{1}], "text": "Top", "enums": {"3"}, "see": None},
                   {"tokens": [set()], "text": "Lost", "enums": {"3"}, "see": None},
                   {"tokens": [{7}], "text": "Middle", "enums": {"7"}, "see": None},
                   {"tokens": [{8}], "text": "Low", "enums": {"3"}, "see": None},
                   {"tokens": [{9}], "text": "End", "enums": {"3"}, "see": None}],
        "down": []}
base = {"1-across": "Top", "7-across": "Middle", "8-across": "Low", "9-across": "End"}
check("a lost number laid between its neighbours only on the second pass, with every reading's numbered lights known",
      (base, {**base, "4-across": "Lost"}, {**base, "4-across": "Lost"}),
      tuple({k: v[0] for k, v in f.lay_loose(lost, g, *t)[0].items()} for t in ((), (set(),), ({"4-across"},))))

# Real readings whose list headings the OCR lost. The lists are put back
# where the clue numbers start rising again (file_trove_puzzles.heads).
# The Times, 1974-05-14, archive.org's reading: no ACROSS, and DOWN read
# "DORVN" (left out here: no heading at all).
times_13686 = """1 The sort of look to keEp a
pet in iuhpense ? |7).
5 Unconventionally mad sort
ot hcreen success (7).
9 No oao around for her (S).
10 Here's a Up i9>.
12 The poet has a donkey to gel
around 1 5).
15 Stress importance of tne
Tube (9).
25 Electrical effect of bringing
in the new vicar (9).
27 Unhappv Is the good man sei
aback by their cruelty (7).
2s Rose shade in ballet (7).
1 Are they too sweet to be
taken seriously? (?l-
2 Only two ducks in the team
of ISO It seems i4. 51-
3 Dog calls for silence 1 51. _
5 Fed np with getting dates
wrong (5).
6 Rare set-up for creating
openings (9).
14 Do they make for perfection
in the Health Service ? f9>*
16 Doctor Border's bed-clearing
operations (9)."""
p, why = f.parse(times_13686)
check("both headings lost: across runs 1 to 28 (read '2s'), down from 1 to 16 (split from 14, whose count reads 'f9>*')",
      ([{1}, {25, 28}], [{1}, {16}]),
      p and ([p["across"][0]["tokens"][0], p["across"][-1]["tokens"][0]],
             [p["down"][0]["tokens"][0], p["down"][-1]["tokens"][0]]) or why)
# The Times, 1974-05-04, archive.org's reading: ACROSS kept, DOWN lost
# along with 2-down's number. DOWN goes back before "3 Norfolk"; the
# unnumbered lines stay with 27-across, for the vote to cut.
import file_trove_puzzles as ftp
times_13679 = """ACROSS
1 Succeed In &«?mns apple, one
over ten feet f4. 4i-
24 Deceive lover with a torch
(81-
25 Article with two points gives
penetration (6L
27 However doctored tapes are
. distinct (81-
honoured "TOSeS
• whh Russell, an old Greek
(7J- .
3 Norfolk town lo register as !
nonconformist (91. I
4 Smuggled Benedictine — J
that’s Irregular <6i.
S Etisineer MP’S recall iSI.
7 After ten maybe drink makes
one weave about f7j."""
check("DOWN lost: put back where the numbers fall from 27 to 3",
      "(7J- .\nDOWN\n3 Norfolk town lo register as !",
      "\n".join(ftp.heads(times_13679.splitlines())[11:14]))
# 1984-01-02, RapidOCR: the grid's crop took ACROSS; DOWN is there.
times_16324 = """1 Meaningless sounds occur in nis
brig. perhaps (9).
6 Sciled opinion of an intelligent
judge (5).
9 Miss Wickfield(5).
10 Chichcsier. cg.or parts of
Cathy's island (9).
DOWN
1 A changc. mabe, for this
soldier?(9).
2 Ecccnirc bom an unknown
place (6)."""
check("ACROSS lost: put back before the first numbered line", "ACROSS",
      ftp.heads(times_16324.splitlines())[0])
check("a lone run of numbers gets no heading made up", ["1 One (3)", "2 Two (3)", "3 Three (5)"],
      ftp.heads(["1 One (3)", "2 Two (3)", "3 Three (5)"]))
# A speck or star before the first number after a heading (1977-01-08,
# 1985-01-02): the number still leads the clue.
check("a speck or star before a clue's number is not text",
      ["DOWN", "1 Miss Write's worried about everything (5)", "1 Land of Hope and—(7)"],
      f.tidy("DOWN\n. 1 Miss Write's worried about everything (5)\nDOWN\n*1 Land of Hope and—(7)")
      .splitlines()[:2] + f.tidy("DOWN\n*1 Land of Hope and—(7)").splitlines()[1:])

# A misread number ("74" for 4) or the list's lost last number: the clue
# takes the light its laid neighbours leave, when its count fills it; a
# clue that ran into the next ("(7) 9 Two") never does.
g = ["...#...", ".......", "...#..."]
mis = {"across": [{"tokens": [{1}], "text": "Top", "enums": {"3"}, "see": None},
                  {"tokens": [{74}], "text": "Misread", "enums": {"3"}, "see": None},
                  {"tokens": [{7}], "text": "Middle", "enums": {"7"}, "see": None},
                  {"tokens": [{8}], "text": "Low", "enums": {"3"}, "see": None},
                  {"tokens": [set()], "text": "End", "enums": {"3"}, "see": None}],
       "down": []}
check("a misread number and a lost last one laid by the grid's numbering",
      {"1-across": "Top", "4-across": "Misread", "7-across": "Middle", "8-across": "Low", "9-across": "End"},
      {k: v[0] for k, v in f.lay_loose(mis, g, set())[0].items()})
mis["across"][1]["text"] = "Misread (7). 9 Two clues"
check("a run-on clue is not laid by position", False,
      "4-across" in f.lay_loose(mis, g, set())[0])

# Short last line: "turn (6)" under a line whose box overhangs it is kept;
# a second copy of the line is not.
rows = f.merge_rows([(4264, 4302, 2279, 2590, "3 The friends got sea sick in"), (4286, 4315, 2303, 2382, "turn (6)"),
                     (4266, 4300, 2280, 2588, "3 The friends got sea sick in"), (4270, 4290, 2250, 2270, "5")])
check("a short line under an overhanging box kept, a copy dropped, a number beside joined",
      ["5 3 The friends got sea sick in", "turn (6)"], [r[4] for r in rows])

# ch's and en5's boxes off Listener No 3: the first box ends inside "this",
# reading its "t" again, and the next box reads the whole word.
rows = f.merge_rows([(1770, 1811, 1455, 1775, "45. Insert an A and t"), (1776, 1806, 1761, 2024, "this is what every")])
check("a box's end cut through the next box's first word is dropped",
      ["45. Insert an A and this is what every"], [r[4] for r in rows])
rows = f.merge_rows([(1770, 1811, 1455, 1740, "45. Insert an A and t"), (1776, 1806, 1761, 2024, "this is what every")])
check("a short word before a box it does not overlap stays",
      ["45. Insert an A and t this is what every"], [r[4] for r in rows])

# RapidOCR's boxes off 1975-06-06 (times-14013): "Am-" sits a little above
# "understood", and both above "1 Fistorlan", all one printed row.
rows = f.merge_rows([(4188, 4211, 232, 351, "understood"), (4188, 4205, 363, 409, "Am-"),
                     (4192, 4221, 97, 217, "1 Fistorlan"), (4212, 4241, 119, 223, "erica (7)."),
                     (4226, 4268, 96, 411, "2 Some well-endowed girl (5).")])
check("a clue's number joins its row when the row's pieces sit at different heights",
      ["1 Fistorlan understood Am-", "erica (7).", "2 Some well-endowed girl (5)."], [r[4] for r in rows])
# A clue's first line with its number run into a speck or read as one
# (real readings: 1977-10-05 ch, 1976-03-24 ch, 1978-09-27 djvu and ch,
# 1980-10-07 ch, 1997-04-01 ch and en5, 1985-02-01 djvu, 1976 ch, 1979 en5).
starts = ["1'Iathe direcdion ofthe -Netberlands ? (7)", "1.Aesociatc's cry of pain (6)",
          "l^Floisiicd curl asainst the blower (6)", "1_Fiaishcd curl agzinst the blower (6)",
          "1'Humphrey's artless look (8)", "JTool able to retract nails (4-3)",
          ") With physical training, is able to see (6)", "IPheasant for instance (4,4)",
          ". 1. Maltreat composer's daughter (7)", "-1--He said No, oddly enough (5)", "'Twas brillig (5)"]
check("a list's first clue keeps its number through a speck; a number lost to specks is left for the grid",
      ["1 Iathe", "1 Aesociatc's", "1 Floisiicd", "1 Fiaishcd", "1 Humphrey's", "1 Tool", "? With",
       "1 Pheasant", "1 Maltreat", "1 He", "'Twas brillig"],
      [" ".join(f.tidy("ACROSS\n" + t).splitlines()[1].split()[:2]) for t in starts])
check("a count with both brackets torn: ( read as T, ) as j or l; 12l is 12 or 2, unsure",
      ["9 Leggy beatera (10)", "12 Only about two penny pieces (6)", "19 Settle with a judge in vulgar money (6)",
       "14 Fish 12l"],
      f.counts_mended(["9 Leggy beatera T10", "12 Only about two penny pieces 16j",
                       "19 Settle with a judge in vulgar money I6l", "14 Fish 12l", "15 End (4)"])[:4])
# Tesseract's reading of 1974-05-07 (times-13681) loses a count's "(": the
# count before the next clue's number still ends the clue.
got, _ = f.parse("ACROSS\n5 Littlewood carries every-\nthing from the break-\ndown 8).\n"
                 "9 Engineer takes part in flight\nwith bishop 10).\nDOWN\n1 Fish (4)")
check("a count read without its opening bracket ends its clue",
      [([5], ["8"]), ([9], ["10"])], [(sorted(c["tokens"][0]), sorted(c["enums"])) for c in got["across"]])
# A comma one reading lacks costs less than a word: the words after it pair.
others = [ocr_clues.marked(ocr_clues.clean(t), breaks=True) for t in ("27 Only. 28 A leisurely drink, doubtless, inside (8) 29 The",
                                                      "28 A leisurely drink, doubtless, inslde (8) 29 The")]
check("a lost comma put back, not the clue's end lost", "A leisurely drink, doubtless, inside",
      ocr_clues.agree("A leisurely drink, doubtless inside", others)[0])
check("a word split at a line end joined again; two words are not", (["people", "tastefully", "dressed"], ["lots", "of", "fish"]),
      (ocr_clues.rejoin(["people", "taste", ",", "fully", "dressed"], ["tastefully"]),
       ocr_clues.rejoin(["lots", "of", "fish"], ["offish"])))

laid = {"1-across": ("Bottom of a ship", "3", None), "2-across": ("Bottom of a ship", None, None),
        "3-across": ("Smoothed it 18 Warning of one", "7", None), "4-down": ("See 1", None, None),
        "5-down": ("s about a ship", "3", None)}
got, blank = ocr_clues.reconcile(laid, "Bottom of a ship (3)")
check("a clue without a count, holding another clue's number, or starting mid-clue filed blank; See kept",
      ({"1-across": "Bottom of a ship", "2-across": "", "3-across": "", "4-down": "See 1", "5-down": ""},
       ["2-across", "3-across", "5-down"]),
      ({k: v[0] for k, v in got.items()}, sorted(blank)))

# A capital misread small is the print's opening when another reading has
# the clue's number before the same two words (No 20,282, 24 across); a
# first line lost (17 across) is still a clue starting mid-clue.
got, blank = ocr_clues.reconcile({"24-across": ("fish enjqycd on board", "5", None),
                                  "17-across": ("in judgment, as staged in 1934", "5,4", None)},
                                 ["22 Pole steps on dangerous ground (9).\n24 Fish enjoyed on board (5).\n"
                                  "17 When Cleopatra was green\nin judgment, as staged in 1934 (5, 4).\n26 Sherry"] * 2)
check("a misread capital opens the clue the print has; a lost first line still blanks",
      ({"24-across": "Fish enjoyed on board", "17-across": ""}, ["17-across"]),
      ({k: v[0] for k, v in got.items()}, sorted(blank)))
# A word split over a line end in the other readings ("hair.\nStyle") is
# no word lost after the clue's end (No 16,205, 21 across); a clue whose
# last word is lost is.
stream = ["20 Painter (7).\n21 Vain display with a severe hair.\nStyle (9).\n23 Intransigent supporter"] * 2
check("a word the other readings split over a line end is the clue's whole last word, not a lost end",
      ("Vain display with a severe hairstyle", None),
      (ocr_clues.reconcile({"21-across": ("Vain display with a severe hair¬ style", "9", None)}, stream)[0]["21-across"][0],
       ocr_clues.reconcile({"21-across": ("Vain display with a severe hair¬ style", "9", None)}, stream)[1].get("21-across")))
check("a clue whose last word the reading lost, the others disagreeing on it, still blanks", ["21-across"],
      sorted(ocr_clues.reconcile({"21-across": ("Vain display with a severe hair", "9", None)},
                                 [stream[0], stream[0].replace("Style", "Stylus")])[1]))
# A list's heading is never a clue's text: a line of its own wherever the
# column read it (times-16363 1D "Down i Beginning", times-18195 13A "on
# the DOWN board"), and a clue still holding one is unfit.
check("a heading read onto its first clue's line, after a count or inside a line is no clue's text",
      ["ACROSS\n1 Fish dish (4)\n5 Sign on the board (5)\nDOWN\n1 Beginning to take a chance (6)\n2 Toast (4)"] * 2,
      [f.tidy("ACROSS\n1 Fish dish (4)\n5 Sign on the DOWN board (5) DOWN\n1 Beginning to take a chance (6)\n2 Toast (4)"),
       f.tidy("ACROSS\n1 Fish dish (4)\n5 Sign on the board (5)\nDown i Beginning to take a chance (6)\n2 Toast (4)")])
check("a heading left in a clue's text is cut", ["Beginning to take a chance", "Bilingual agreement on the board",
                                               "Down payment covering openers", "Flag is down, and safe"],
      [ocr_clues.trimmed(t, lid) for t, lid in (("Down i Beginning to take a chance", "1-down"),
                                                ("Bilingual agreement on the DOWN board", "13-across"),
                                                ("Down payment covering openers", "3-down"),
                                                ("Flag is down, and safe", "1-across"))])
# A bracket a clue never pairs is a speck or a count torn open: cut where
# it opens or closes the text, and unfit anywhere else.
check("a torn count closing a clue, or a speck bracket opening it, is cut",
      ["Wave provided by hair-dresser", "Try to get money from low land", "Headed paper?",
       "During which Nature tried her hand on man (Burns)", "Wildly excited when it's put up in foreign currency",
       "Order flowers on island", "Conflict with the law", "Looking back to Solomon's", "Taken from Henry (2 Hen. IV) on stage"],
      [ocr_clues.trimmed(t, "5-down") for t in (
          "Wave provided by hair-dresser (6", "Try to get money from low land (5.41.", "Headed paper? ( 8 .",
          "During which Nature tried her hand on man (Burns) +).",
          "Wildly excited when it's put up in foreign currency 1 7).", "( Order flowers on island",
          ")Conflict with the law", "Looking back to Solomon's [9]", "Taken from Henry (2 Hen. IV) on stage")])
check("a heading or an unpaired or square bracket is unfit; paired brackets and a lower-case down are not",
      [True, True, True, True, True, False, False, False],
      [bool(ocr_clues.fault(t, None, None)) for t in (
          "Bilingual agreement on the DOWN board", "Down i Beginning to take a chance", "Just a Liberal) reformer beheaded!",
          "A chance (out east) to) go wild", "Rum [sounding] idol", "Bottom (of a ship) here", "Flag is down, and safe",
          "Across the border the outsiders exercise")])
check("a bracket the clue never closes is a misread; a closed one stands",
      ([("(this", "a bracket never closed or opened")], []),
      (ocr_clues.suspect("Information influencing children initially is (this"),
       ocr_clues.suspect("Bottom (of a ship) here")))

# edition_dirs(): the years in turn, so a capped run reaches every decade.
cache = Path(os.environ["TMP"]) / "cache"
for item, eds in (("NewsUK1974UKEnglish", ["1974-05-01_1", "1974-05-02_2"]),
                  ("NewsUK1990UKEnglish", ["1990-01-02_3"]), ("FinancialTimes1975UKEnglish", ["1975-01-01_4"])):
    for e in eds:
        (cache / item / e).mkdir(parents=True)
        (cache / item / e / "pages.json").write_text("{}")
check("editions taken a year at a time, the FT left out", ["1974-05-01_1", "1990-01-02_3", "1974-05-02_2"],
      [d.name for d in f.edition_dirs(cache)])
check("the FT's editions are the FT phase's, and their paper is the FT",
      (["1975-01-01_4"], "ftcryptic", "times"),
      ([d.name for d in f.edition_dirs(cache, f.FT)], f.paper_of(cache / "FinancialTimes1975UKEnglish" / "x").series,
       f.paper_of(cache / "NewsUK1990UKEnglish" / "x").series))
# The Gale Times pages are a paper of their own: the Times runs never read
# them, the Gale run reads them alone, and a re-read request goes to its run.
(cache / "GaleTimes1987UKEnglish" / "1987-03-02").mkdir(parents=True)
(cache / "GaleTimes1987UKEnglish" / "1987-03-02" / "pages.json").write_text("{}")
check("a Gale page is the Gale run's, never the Times run's, and files as the Times",
      (["1974-05-01_1", "1990-01-02_3", "1974-05-02_2"], ["1987-03-02"], "gale", "times", "filed-gale.jsonl"),
      ([d.name for d in f.edition_dirs(cache)], [d.name for d in f.edition_dirs(cache, f.GALE)],
       f.paper_of(cache / "GaleTimes1987UKEnglish" / "x").key, f.GALE.series, f.LEDGER_NAMES["gale"]))
# edition_dirs() looks again at no edition found holding pages.json while
# its item is unmoved; one removed whole, or new and yet to get its
# pages.json, is still seen.
import shutil, time
wc = Path(os.environ["TMP"]) / "withpages"
it = wc / "NewsUK1982UKEnglish"
for e in ("1982-01-01_1", "1982-01-02_2"):
    (it / e).mkdir(parents=True)
    (it / e / "pages.json").write_text("{}")
(it / "1982-01-03_3").mkdir()
def settle_all():
    for d in (*it.iterdir(), it, wc):
        os.utime(d, (time.time() - 600, time.time() - 600))
settle_all()
names = lambda: [d.name for d in f.edition_dirs(wc)]
first = names()
looked = []
real_listed = f.dir_cache.listed
f.dir_cache.listed = lambda d: (looked.append(Path(d).name), real_listed(d))[1]
again = names()
f.dir_cache.listed = real_listed
(it / "1982-01-03_3" / "pages.json").write_text("{}")
grown = names()
check("an edition holding pages.json in an unmoved item is not looked at again; one yet to hold it is",
      (["1982-01-01_1", "1982-01-02_2"], first, ["1982-01-03_3"]),
      (again, first, [n for n in looked if n != "withpages"]))
check("a new pages.json in an unmoved item is seen", ["1982-01-01_1", "1982-01-02_2", "1982-01-03_3"], grown)
shutil.rmtree(it / "1982-01-02_2")
(it / "1982-01-02_2").mkdir()
settle_all()
check("an edition removed whole and laid out again without pages.json is gone (its item moved)",
      ["1982-01-01_1", "1982-01-03_3"], names())
# held_files: one brief() reads a series once, whoever asks; outside one, each call looks again.
hp = Path(os.environ["TMP"]) / "heldroot"
(hp / "puzzles" / "zz" / "1999").mkdir(parents=True)
(hp / "puzzles" / "zz" / "1999" / "zz-1.json").write_text('{"date": "1999-01-01"}')
real_root, f.ROOT = f.ROOT, hp
f._HELD_NOW.files = {}
before = f.held_files("zz")
(hp / "puzzles" / "zz" / "1999" / "zz-2.json").write_text('{"date": "1999-01-02"}')
inside = f.held_files("zz")
f._HELD_NOW.files = None
check("held_files within a brief is its first read; outside it a new file is seen",
      ([1], [1], [1, 2]), ([n for n, _ in before], [n for n, _ in inside], sorted(n for n, _ in f.held_files("zz"))))
# held_once nests (the outer read stands); save_held/load_held carry the parses to a
# new process, and a file whose stat moved since is parsed again.
with f.held_once():
    first = f.held_files("zz")
    (hp / "puzzles" / "zz" / "1999" / "zz-3.json").write_text('{"date": "1999-01-03"}')
    with f.held_once():
        nested = f.held_files("zz")
check("held_once nested keeps the outer read", [1, 2], sorted(n for n, _ in nested))
hc = hp / "held.pickle"
f.held_files("zz")
f.save_held(hc)
f._HELD.clear()
f.load_held(hc)
f._HELD_MOVED.clear()
import time
time.sleep(0.01)
(hp / "puzzles" / "zz" / "1999" / "zz-1.json").write_text('{"date": "1999-02-01", "moved": 1}')
loaded = dict(f.held_files("zz"))
check("a loaded parse stands for an unmoved file; a moved one is read again",
      (datetime.date(1999, 1, 2), datetime.date(1999, 2, 1), [hp / "puzzles" / "zz" / "1999" / "zz-1.json"]),
      (loaded[2][0], loaded[1][0], f._HELD_MOVED))
f.save_held(hc)
check("save_held writes only after a parse", [], f._HELD_MOVED)
f.ROOT = real_root
# plan() lists a settled dir once (dir_cache.seen): a replaced file, a new edition or
# a moved ledger row each make an edition due again; a fresh dir is not kept.
import scan_queue, time
f.vlm.reachable = lambda *a, **k: False
pc = Path(os.environ["TMP"]) / "plancache"
def settle(*ds):
    for d in ds:
        os.utime(d, (time.time() - 600, time.time() - 600))
e1 = pc / "NewsUK1981UKEnglish" / "1981-02-03_1"
e1.mkdir(parents=True)
(e1 / "pages.json").write_text("{}")
(e1 / "leaf_0001.jpg").write_bytes(b"x")
settle(e1, e1.parent, pc)
def settled_row(d):
    fh, found = f.input_hash(d), {"puzzles": [], "solutions": []}
    return {"edition": f"{d.parent.name}/{d.name}", "filesHash": fh, "scanKey": f.scan_key(), "scan": found,
            "inputs": f.inputs_of(fh, found, f.TIMES.series), "solutionsSeen": [], "verdicts": [],
            "readAt": "2026-01-01T00:00:00+00:00"}
pl = pc / "filed.jsonl"
scan_queue.append(pl, [settled_row(e1)])
settle(pc)
due = lambda: [(u["kind"], u["rel"].split("/")[1], u["reason"]) for u in sum(f.plan(f.TIMES, pc), [])]
check("a settled edition whose row is current is due for nothing, and its listing is kept", ([], True),
      (due(), e1 in f.dir_cache._SEEN))
old = os.stat(e1).st_mtime_ns
(e1 / "leaf_0001.tmp").write_bytes(b"xy")
os.replace(e1 / "leaf_0001.tmp", e1 / "leaf_0001.jpg")
os.utime(e1, ns=(old, old))
check("a file replaced under an unmoved mtime makes it due again (the ctime moved)",
      [("scan", "1981-02-03_1", "scan stale"), ("read", "1981-02-03_1", "inputs changed")], due())
scan_queue.append(pl, [settled_row(e1)])
e2 = pc / "NewsUK1981UKEnglish" / "1981-05-06_2"
e2.mkdir()
(e2 / "pages.json").write_text("{}")
check("a new edition in a listed item is planned", [("scan", "1981-05-06_2", "never scanned"),
                                                    ("read", "1981-05-06_2", "never read")], due())
scan_queue.append(pl, [settled_row(e2), {**settled_row(e1), "inputs": "moved"}])
check("a moved ledger row makes its edition due again", [("read", "1981-02-03_1", "inputs changed")], due())
scan_queue.compact(pl, "edition")
check("a ledger replaced whole (compact) plans the same", [("read", "1981-02-03_1", "inputs changed")], due())
# A stale scan's read ranks with the fixes when its titles follow a puzzle
# read without answers: the issue printing that solution (a Saturday prize's
# six on), whose heading the new scan code may read.
stale = {**settled_row(e1), "scanKey": "old",
         "scan": {"date": "1981-02-03", "puzzles": [{"number": 15436, "leaf": 1}], "solutions": []}}
def e1_reason(day, verdict):
    scan_queue.append(pl, [stale, {**settled_row(e2), "scan": {"date": day, "puzzles": [], "solutions": []},
                                   "verdicts": [verdict]}])
    return [(u["rank"], u["reason"]) for u in f.plan(f.TIMES, pc)[1] if u["rel"].endswith("_1")]
check("a stale host of an answerless puzzle ranks 2; of a Saturday prize six on; else, refused or answered, 3",
      [[(2, "scan stale, answers missing")], [(2, "scan stale, answers missing")], [(3, "scan stale")],
       [(3, "scan stale")], [(3, "scan stale")]],
      [e1_reason("1981-02-02", {"number": 15435}), e1_reason("1981-01-31", {"number": 15430}),
       e1_reason("1981-01-31", {"number": 15435}), e1_reason("1981-02-02", {"number": 15435, "refused": True}),
       e1_reason("1981-02-02", {"number": 15435, "solutionFrom": "1981-02-03 leaf 1"})])
def stale_fixed(verdict):
    scan_queue.append(pl, [{**stale, "verdicts": [verdict]}, settled_row(e2)])
    return [(u["rank"], u["reason"]) for u in f.plan(f.TIMES, pc)[1] if u["rel"].endswith("_1")]
check("a stale scan's read a reader fix can change ranks with the fixes, not the whole corpus",
      [[(2, "solution short, read by other code")], [(2, "refused not-a-grid before its fix")],
       [(3, "scan stale")]],
      [stale_fixed({"number": 15436, "solutionFrom": "x", "solution": {"accepted": 20, "lights": 30}}),
       stale_fixed({"number": 15436, "refused": True, "cause": "not-a-grid"}),
       stale_fixed({"number": 15436, "solutionFrom": "x", "solution": {"accepted": 30, "lights": 30}})])
scan_queue.append(pl, [settled_row(e1), settled_row(e2)])
(e2 / "pages.json").write_text("{\"x\": 1}")
check("a dir changed within SETTLED is listed afresh, an in-place write seen", (False, "inputs changed"),
      (e2 in f.dir_cache._SEEN, dict((r, why) for _, r, why in due()).get("1981-05-06_2")))
# A Times puzzle's solution prints in the next issue, which may be a Gale page
# alone (archive.org lacks that issue), and the reverse: each run sees the
# other ledger's last headings, so a heading read there makes it due.
e3 = pc / "NewsUK1981UKEnglish" / "1981-06-19_3"
e3.mkdir()
(e3 / "pages.json").write_text("{}")
found3 = {"puzzles": [{"number": 15556, "leaf": 20}], "solutions": []}
fh3 = f.input_hash(e3)
scan_queue.append(pl, [settled_row(e2), settled_row(e1),
                       {**settled_row(e3), "scan": found3, "inputs": f.inputs_of(fh3, found3, f.TIMES.series),
                        "verdicts": [{"number": 15556}]}])
settle(e3, e3.parent, pc)
check("an archive.org puzzle with no solution heading anywhere is due for nothing", [], due())
g3 = "GaleTimes1981UKEnglish/1981-06-20"
scan_queue.append(pc / f.LEDGER_NAMES["gale"], [{"edition": g3, "scan": {"date": "1981-06-20", "puzzles": [{"number": 15557, "leaf": 0}],
                                                                       "solutions": [{"number": 15556, "leaf": 0}]}}])
check("its solution heading read in the Gale page of the next issue makes it due, the solution's dir that page",
      ([("read", "1981-06-19_3", "inputs changed")], pc / g3, {}),
      (due(), f.sister_solutions(pc, f.TIMES)[15556]["dir"], f.sister_solutions(pc, f.FT)))
scan_queue.append(pl, [{**settled_row(e2), "scan": {"date": "1981-06-22", "puzzles": [],
                                                      "solutions": [{"number": 15557, "leaf": 1}]}}])
check("and a Gale run sees the archive.org scans' headings", {15557: pc / "NewsUK1981UKEnglish" / "1981-05-06_2"},
      {n: s["dir"] for n, s in f.sister_solutions(pc, f.GALE).items()})
# A read start links every sister edition's headings (sister_solutions):
# kept until the sister ledger or the series' filed puzzles move.
linked, real_linked, real_held_dates = [], f.linked_solutions, f.held_dates
f.linked_solutions = lambda *a: (linked.append(a[0]), real_linked(*a))[1]
try:
    f.sister_solutions(pc, f.GALE)
    linked.clear()
    f.sister_solutions(pc, f.GALE)
    check("an unmoved sister ledger and filed puzzles: no heading linked again", [], linked)
    scan_queue.append(pl, [settled_row(e1)])
    f.sister_solutions(pc, f.GALE)
    check("mirror: the sister ledger appended to: its headings linked again", True, bool(linked))
    linked.clear()
    f.held_dates = lambda series: f.Held({**real_held_dates(series), 99999: datetime.date(1999, 1, 1)})
    f.sister_solutions(pc, f.GALE)
    check("mirror: a puzzle filed in the series: its headings linked again", True, bool(linked))
finally:
    f.linked_solutions, f.held_dates = real_linked, real_held_dates
held = f.Held({15556: datetime.date(1981, 6, 19), 15557: datetime.date(1981, 6, 20), 15550: datetime.date(1981, 6, 12)})
check("neighbours: the nearest filed either side, by bisecting the sorted dates",
      ((datetime.date(1981, 6, 12), 15550), (datetime.date(1981, 6, 20), 15557)),
      f.neighbours(datetime.date(1981, 6, 19), held))
try:
    held[1] = datetime.date(1981, 1, 1)
    check("Held is read-only", "raised", "set")
except TypeError:
    check("Held is read-only", "raised", "raised")
check("filer_of: each edition to the run that reads it (the 1930 Times the Times run's)",
      ["gale", "times", "times", "ft", None],
      [getattr(f.filer_of(r), "key", None) for r in ("GaleTimes1987UKEnglish/1987-03-02", "NewsUK1990UKEnglish/x",
                                                       "per_times_the-times_1930-03-04_45452/x",
                                                       "FinancialTimes1975UKEnglish/x", "Elsewhere/x")])

# The FT: "CROSSWORD" over "No. 8,650 Set by DANTE" (1990s), one line in the
# 1970s; "Solution 8,650", or "SOLUTION TO PUZZLE" over "No. 2,765".
titles, sols = f.ft_headings([line("CROSSWORD", 2429, 2957), line("No. 8,650 Set by DANTE", 2417, 3017),
                              line("Solution 8,649", 2691, 3958),
                              line("Solution to Saturday's prize puzzle on Saturday January 14.", 2253, 4293),
                              line("No. 1,234 reasons to buy", 900, 100)])
check("1990s FT title over its number line, setter read, box the grid's width; prize-date line no heading",
      ([(8650, "Dante", f.FT_GRID_SPAN)], [8649]),
      ([(n, s, b[2] - b[0]) for n, b, s in titles], [n for n, _ in sols]))
check("a byline our files or the dictionary know stands without a second reading", ["Dante", "Vixen", None],
      [f.byline(None, {"setterRead": "Dante"}), f.byline(None, {"setterRead": "Vixen"}), f.byline(None, {})])
titles, sols = f.ft_headings([line("F.T. CROSSWORD PUZZLE No. 2,766", 200, 2841),
                              line("SOLUTION TO PUZZLE", 573, 4049), line("No. 2,765", 656, 4073)])
check("1970s FT title on one line, solution number on the line under", ([2766], [2765]),
      ([n for n, _, _ in titles], [n for n, _ in sols]))
titles, _ = f.ft_headings([line("F.T. CROSSWORD", 1749, 3265), line("PUZZLE No. 5,094", 1750, 3301)])
check("1980s FT title over \"PUZZLE No. N\" on the line under", [5094], [n for n, _, _ in titles])
titles, _ = f.ft_headings([[(204, 2926, 469, 2970, "~nTupblfih“parkCtT-"), (470, 2928, 709, 2957, "CROSSWORD"),
                            (710, 2928, 900, 2957, "PUZZLE"), (901, 2928, 990, 2957, "NO."),
                            (991, 2928, 1100, 2957, "1,652")]])
check("a title behind a word the OCR ran in from the next column; box from the title on",
      [(1652, (470 + 1100) // 2)], [(n, (b[0] + b[2]) // 2) for n, b, _ in titles])
check("a comma the OCR reads as ? or ^", [3034, 4780],
      [n for t in ("F.T. CROSSWORD PUZZLE No. 3?034 r", "F.T. CROSSWORD PUZZLE No. 4^780")
       for n, _, _ in f.ft_headings([line(t, 291, 2180)])[0]])
check("a no-crossword notice over the solution's number is no title", [],
      f.ft_headings([line("No crossword appears in today's", 586, 3307), line("puzzle. No 5,355, will be pub-", 586, 3399)])[0])
check("prose with a crossword in it and no number is no title", [],
      f.ft_headings([line("the paper's crossword setter retired", 200, 300)])[0])
check("FT numbers the dates imply, and our first ftcryptic's", [True, True, True, False],
      [abs(n - f.ft_expected_number(datetime.date.fromisoformat(d))) <= f.NUMBER_SLACK
       for d, n in [("1975-05-01", 2766), ("1992-06-11", 7870), ("2009-11-12", 13232), ("1995-01-03", 19742)]])

# The Guardian: "Guardian Crossword No 20,538" over "Set by Rufus" (1990s),
# "CROSSWORD 17,101" (1980s); the solution label under its grid; the Quick
# crossword's title is not the cryptic's.
titles, sols = f.guardian_headings([line("Guardian Crossword No 20,538", 1942, 3103), line("Set by Rufus", 1942, 3155),
                                    line("□□ CROSSWORD SOLUTION 20^537", 2592, 3510),
                                    line("CROSSWORD 17,101", 200, 900), line("QUICK CROSSWORD No. 4,575", 200, 200)])
check("Guardian titles with the setter under, the solution label with a comma read as ^, no Quick",
      ([(20538, "Rufus"), (17101, None)], [20537]), ([(n, s_) for n, _, s_ in titles], [n for n, _ in sols]))
check("a solution label whose number is misread is the page's one title's previous puzzle", [20926],
      [n for n, _ in f.guardian_headings([line("Guardian Crossword No 20,927", 1942, 3103),
                                          line("□□ CROSSWORD BOLUTION 20^27", 2592, 3510)])[1]])
check("the Guardian's editions file as cryptic, numbered as the feed's",
      ("cryptic", [True, True, True]),
      (f.paper_of(cache / "TheGuardian1996UKEnglish" / "x").series,
       [abs(n - f.guardian_expected_number(datetime.date.fromisoformat(d))) <= 5
        for d, n in [("1971-03-16", 12748), ("1996-01-02", 20538), ("1998-04-03", 21239)]]))
# Three columns: the third right of the grid from under the solution grid
# (its foot at 3530, its label 15px under);
# a speck left of the grid's margin and the imprint after "Solution
# tomorrow" (however misread) are not clues; "Across" in title case heads.
grid = (1954, 3263, 2586, 3865)
lines = [line("m", 1916, 3880), line("Across", 1957, 3880), line("1,4 Ancient patriarch (6,8)", 1973, 3909),
         line("Down", 2284, 3880), line("1 Called once (4,4)", 2284, 3909),
         line("20^39", 2700, 3545), line("10 Hell of a clue for Pi! (10,3)", 2617, 3726),
         line("22 Fishy drawing (5)", 2617, 3760), line("Soiuton tamorrow", 2617, 3790),
         line("Published by Guardian Newspapers", 2617, 3812)]
check("Guardian columns: left, right, then right of the grid; specks, label and imprint left out",
      "Across\n1,4 Ancient patriarch (6,8)\nDown\n1 Called once (4,4)\n10 Hell of a clue for Pi! (10,3)\n22 Fishy drawing (5)",
      f.column_text(f.columns(lines, grid, (f.GUARDIAN_THIRD, 3530 + f.LABEL_DROP), 15)))
check("a linked clue's numbers read, commas and 'dn' not taken for clue numbers",
      [[{1}, {4}], [{10}, {9}], [{26}, {27}, {14}], [{4}]],
      [c["tokens"] for c in f.parse("Across\n1,4 Ancient (6,8)\n10,9dn I am (4,10,3)\n"
                                    "26,27,14dn That which (10,4,7)\nDown\n4 See 26 ac\n6 Bound (6)")[0]
       ["across"] + f.parse("Across\n1 A (3)\nDown\n4 See 26 ac\n6 Bound (6)")[0]["down"][:1]])
check("a clue's opening A run into its next word split; a word, or a commoner word misspelt, kept",
      "15 A danger out east (5)\n3 Abed (4)\n4 Arived (7)", f.tidy("15 Adanger out east (5)\n3 Abed (4)\n4 Arived (7)"))
# A word is_word has but the lexicon does not rank ("whore") is no crash:
# a commoner spelling ("ashore") keeps the line as read.
check("an unranked word after a glued A is compared as rarest",
      "5 Awhore (6)", f.tidy("5 Awhore (6)"))
check("rn read as m mended", True, "carnivore" in ocr_clues.edits("camivore"))
g = ["...#...", "...#...", "......."]
pz = f.build(20540, datetime.date(1996, 1, 4), g, "image",
             {"1-across": ("Ancient patriarch", "3,3", ["1-across", "4-across"])}, "TheGuardian1996UKEnglish", 15,
             series="cryptic", name="Cryptic crossword No {:,}".format(20540))
check("a built puzzle's source url is the edition url given",
      "https://archive.org/details/TheGuardian1996UKEnglish/page/n15/mode/1up", pz["source"]["url"])
check("a linked light the paper prints no clue for reads 'See 1'", "See 1",
      next(e["clue"]["text"] for e in pz["entries"] if (e["number"], e["direction"]) == (4, "across")))
pz = f.build(20540, datetime.date(1996, 1, 4), g, "image",
             {"1-across": ("(8)", "3", None), "4-across": ("Ancient patriarch", "3", None)},
             "TheGuardian1996UKEnglish", 15, series="cryptic", name="Cryptic crossword No 20,540")
one = next(e["clue"] for e in pz["entries"] if (e["number"], e["direction"]) == (1, "across"))
check("a reading that kept only a count (ftcryptic-9610 3-down) is filed missing, with no text",
      {"enumeration": "3", "missing": True}, one)

# match_canberra(): the reading sharing the clue list, printed first, same grid.
def puzzle(pid, date, clues, cols=3):
    return {"id": pid, "date": date, "dimensions": {"cols": cols, "rows": 3},
            "entries": [{"number": i + 1, "direction": "across", "position": {"x": 0, "y": i},
                         "length": cols, "clue": {"text": t}} for i, t in enumerate(clues)]}
words = [chr(97 + i // 26) + chr(97 + i % 26) + "x" for i in range(30)]
clues = [" ".join(words[k * 10:k * 10 + 10]) for k in range(3)]
src = Path(os.environ["TMP"]) / "src"; src.mkdir()
(src / "times-13677.json").write_text(json.dumps(puzzle("times-13677", "1974-05-02", clues)))
(src / "times-13678.json").write_text(json.dumps(puzzle("times-13678", "1974-05-03", ["quite other words here and there", "x y z", "q r s"])))
can = Path(os.environ["TMP"]) / "canberra"; (can / "1975").mkdir(parents=True)
misread = [clues[0].replace("abx", "abz"), clues[1], clues[2]]
(can / "1975" / "canberra-750101.json").write_text(json.dumps(puzzle("canberra-750101", "1975-01-01", misread)))
(can / "1975" / "canberra-750102.json").write_text(json.dumps(puzzle("canberra-750102", "1975-01-02", clues, cols=4)))
(can / "1973").mkdir()
(can / "1973" / "canberra-730101.json").write_text(json.dumps(puzzle("canberra-730101", "1973-01-01", clues)))
import io
got = f.match_canberra(src, write=False, out=io.StringIO(), canberra=can)
check("a reprint matched through a misread; another grid, or a print before the London one, is not", {"canberra-750101": "times-13677"}, got)
(src / "times-13679.json").write_text(json.dumps(puzzle("times-13679", "1974-05-04", clues)))
got = f.match_canberra(src, write=False, out=io.StringIO(), canberra=can)
check("two readings sharing the clue list alike name neither: the best must lead MATCH_LEAD times over", {}, got)

# merge_answers(): a re-read's answers go into the held filing (17246's two
# answers were lost when its "_" mend wrote the held file back), replace a
# held answer read otherwise (17247 20a BAYED, now DATED), and drop a held
# answer a new one crosses on another letter; another tool's file is left.
def answered(sols, tool=f.TOOL):
    lights = [(1, "across", 0, 0, 3), (1, "down", 0, 0, 3), (2, "down", 2, 0, 3), (4, "across", 0, 2, 3)]
    return {"source": {"acquiredBy": tool}, "dimensions": {"cols": 3, "rows": 3},
            "entries": [{"number": n, "direction": d, "position": {"x": x, "y": y}, "length": k,
                         "clue": {"text": "c", "enumeration": str(k)}, "solution": s,
                         **({"annotation": {"definitions": []}} if s else {})}
                        for (n, d, x, y, k), s in zip(lights, sols)]}
held = answered([None, "BAD", "YES", None])
got = f.merge_answers(held, answered(["BAT", None, None, "DOE"]))
check("a re-read's answers merge into the held filing: new ones in, a crossed one out, the rest kept",
      ({"1-across": "BAT", "2-down": None, "4-across": "DOE"}, ["BAT", "BAD", None, "DOE"], None),
      (got, [e["solution"] for e in held["entries"]], held["entries"][2].get("annotation")))
held = answered(["BAY", None, None, None])
check("a held answer read otherwise now takes the new read, its annotation dropped",
      ({"1-across": "BAT"}, None), (f.merge_answers(held, answered(["BAT", None, None, None])),
                                   held["entries"][0].get("annotation")))
held = answered(["BAY", "BAD", None, None])
check("a re-read of the solution grid drops each held answer it did not read again",
      ({"1-across": None, "1-down": None, "4-across": "DOE"}, [None, None, None, "DOE"]),
      (f.merge_answers(held, answered([None, None, None, "DOE"]), reread=True), [e["solution"] for e in held["entries"]]))
check("another tool's filing takes no answers", {},
      f.merge_answers(answered([None] * 4, tool="other"), answered(["BAT", None, None, None])))

# rules(): a printed solution grid's rules lie unevenly and its rows shear
# against its columns (Gale's 1987-01-07, ~1px a cell, 8px over the grid);
# straightened() squares them and rules() finds each one where it lies.
import numpy as np
import trove_solution_ocr as tso
grid17246 = ["..........#....", ".#.#.#.#.#.#.#.", ".......#.......", ".#.#.#.#.#.#.#.",
             ".........#.....", "##.#.#.#.#.###.", ".....#.........", ".#.#.#####.#.#.",
             ".........#.....", ".###.#.#.#.#.##", ".....#.........", ".#.#.#.#.#.#.#.",
             ".......#.......", ".#.#.#.#.#.#.#.", "....#.........."]
step = [46, 49, 44, 47, 45, 50, 43, 46, 48, 45, 47, 44, 49, 46, 45]
edges = [0] + list(np.cumsum(step))
side = edges[-1] + 1
ink = np.zeros((side, side), bool)
for k, e in enumerate(edges):
    w = 4 if k in (0, len(edges) - 1) else 2
    ink[:, max(0, e - w):e + w + 1] = True
    ink[max(0, e - w):e + w + 1, :] = True
for r, row in enumerate(grid17246):
    for c, ch in enumerate(row):
        if ch == "#":
            ink[edges[r]:edges[r + 1] + 1, edges[c]:edges[c + 1] + 1] = True
        else:
            # A letter's upright, a fifth of a cell from its left rule.
            ink[edges[r] + 12:edges[r + 1] - 12, edges[c] + 9:edges[c] + 13] = True
drawn = Image.fromarray(np.where(ink, 0, 255).astype(np.uint8))
sheared = tso.sheared(drawn, 0, 0.012)
ys, xs = tso.rules(np.asarray(tso.straightened(sheared)), grid17246)
inner = edges[1:-1]
check("each inner rule of an uneven, sheared grid found within 2px",
      (True, True), (max(abs(a - b) for a, b in zip(xs[1:-1], inner)) <= 2,
                     max(abs(a - b) for a, b in zip(ys[1:-1], inner)) <= 2))
# A heavy print's edge column, blocks every other row and fat letters
# between, is ink down most of its first cell: the frame's middle is still
# at the frame (Times 1981-10-15 put it a third of a cell in, and lost the
# column's letters).
edge = ["#" + "." * 14 if r % 2 else "." * 15 for r in range(15)]
heavy = np.zeros((side, side), bool)
for k, e in enumerate(edges):
    w = 4 if k in (0, len(edges) - 1) else 2
    heavy[:, max(0, e - w):e + w + 1] = True
    heavy[max(0, e - w):e + w + 1, :] = True
for r in range(15):
    top, foot = edges[r], edges[r + 1]
    if r % 2:
        heavy[top:foot + 1, :edges[1] + 1] = True
    else:
        # An H: two fat uprights and a bar, paper between them.
        heavy[top + 8:foot - 8, 7:16] = heavy[top + 8:foot - 8, 30:39] = True
        heavy[(top + foot) // 2 - 3:(top + foot) // 2 + 3, 7:39] = True
ys, xs = tso.rules(np.where(heavy, 0, 255).astype(np.uint8), edge)
check("a frame beside a heavy edge column found within 2px of its middle", True, abs(xs[0] - 2) <= 2)
# read_framed(): the lattice reading most cells surely leads, and another
# lattice's lights stand where they agree with its letters. Times 20352 on
# rules() lost MERCILESS, RACER, ICECAP that an even lattice a few pixels
# off read; a light whose cell the leader surely reads otherwise does not
# stand (13977's even lattice read CREATED's D as an R).
grid3 = ["...", ".#.", "..."]
lead = ({(1, "across"): "CAT"}, {"cellsSure": 7}, {(0, 0): "C", (0, 1): "A", (0, 2): "T", (2, 2): "D"})
other = ({(1, "across"): "COT", (1, "down"): "COB", (3, "across"): "BED", (2, "down"): "TOR"},
         {"cellsSure": 5}, {})
real_framings, real_lattice = tso.framings, tso.read_lattice
tso.framings = lambda gray, grid: [("o", 0, 0), ("l", 0, 0)]
tso.read_lattice = lambda g, ys, xs, grid: {"o": other, "l": lead}[g]
try:
    Image.new("L", (30, 30), 255).save(os.path.join(os.environ["TMP"], "grid3.png"))
    accepted, stats = tso.read_framed(os.path.join(os.environ["TMP"], "grid3.png"), grid3)
finally:
    tso.framings, tso.read_lattice = real_framings, real_lattice
check("the surest lattice's lights stand; another's where every cell agrees",
      ({(1, "across"): "CAT", (1, "down"): "COB", (3, "across"): "BED"}, 2),
      (accepted, stats["lattices"]))
# crossed_reads(): an unread light's cells take accepted crossings' letters
# and plain cells' sure reads (Gale 1987: ?MADEUS, ?LEANOR); a numbered
# cell's own sure read is no letter (DUCKINGSTOOL's D read as a sure B),
# and a crossing that a sure read contradicts leaves the light unread.
cat_cob = {(1, "across"): "CAT", (1, "down"): "COB"}
check("an unread light whose cells crossings and plain sure reads fill stands",
      {(3, "across"): "BED"}, tso.crossed_reads(tso.lights(grid3), cat_cob, {(2, 1): "E", (2, 2): "D"}))
check("a numbered cell's own sure read fills no light",
      {}, tso.crossed_reads(tso.lights(grid3), {(1, "across"): "CAT"},
                            {(1, 0): "O", (2, 0): "B", (2, 1): "E", (2, 2): "D"}))
check("a crossing a sure read contradicts fills no light",
      {}, tso.crossed_reads(tso.lights(grid3), {(1, "across"): "CAT", (3, "across"): "BED"},
                            {(1, 2): "O", (2, 2): "T"}))
# numbers_printed(): a Times solution grid from the mid-1980s prints no clue
# numbers; blanking its numbered cells' corners makes a D a sure J (20006
# DELETE lost), so only a grid whose numbered corners carry ink is blanked.
lts = tso.lights(grid17246)
numbered = {cells[0]: n for (n, _), cells in lts.items()}
cells = {rc for c in lts.values() for rc in c}
def solution_ink(numbers_too):
    a = np.zeros((side, side), bool)
    for k, e in enumerate(edges):
        a[:, max(0, e - 2):e + 3] = a[max(0, e - 2):e + 3, :] = True
    for r, c in cells:
        a[edges[r] + 12:edges[r + 1] - 12, edges[c] + 18:edges[c] + 24] = True
        if numbers_too and (r, c) in numbered:
            a[edges[r] + 4:edges[r] + 14, edges[c] + 4:edges[c] + 12] = True
    return np.where(a, 0, 255).astype(np.uint8)
inner = list(map(float, edges))
check("a grid printing its clue numbers is read as one; the same letters without them are not",
      (True, False), tuple(bool(tso.numbers_printed(solution_ink(n), inner, inner, numbered, cells))
                           for n in (True, False)))
# unnumbered_reads(): in a grid printing no numbers a numbered cell takes the
# letter its plain and blanked reads agree on surely, unless its whole glyph
# best matches another letter (a light's first I read as a sure T lost
# INSTEP, filed TRILOGY's I as T).
gside = tso.GLYPH + 2 * tso.GLYPH_SHIFT
def drawn_letter(ch):
    g = np.zeros((gside, gside), np.float32)
    g[6:32, 17:22] = 1
    if ch == "T":
        g[6:11, 8:31] = 1
    return g
glyphs = {(0, 1): drawn_letter("I"), (0, 2): drawn_letter("T"), (1, 0): drawn_letter("I"),
          (2, 0): drawn_letter("T"), (3, 0): drawn_letter("T")}
read = {(0, 1): "I", (0, 2): "T"}
numbered = {(1, 0): 1, (2, 0): 2, (3, 0): 3}
check("a numbered cell read surely both ways stands only as its glyph's best match; one way is not enough",
      {(2, 0): "T"}, tso.unnumbered_reads({(1, 0): "T", (2, 0): "T", (3, 0): "T"}, {(1, 0): "T", (2, 0): "T"},
                                          glyphs, read, numbered))
# best_match(): a letter no plain cell was read as has no model, so the glyph
# cannot veto it (GERFALCON, GATECRASH and PEGASUS lost their numbered G in
# times-19998); a letter with a model still yields to a better match.
check("a numbered cell's letter with no model stands; one a likelier model beats does not",
      (True, False, True),
      tuple(tso.best_match(drawn_letter(drawn), tso.letter_models(glyphs, read), 1, ch)
            for drawn, ch in (("I", "G"), ("I", "T"), ("T", "T"))))
check("run-together words of 3+ letters are an answer only when read whole: not A + ALLEY, A + DO + IS + ON",
      (False, False, True, True, False),
      (tso.answer("AALLEY", set()), tso.answer("AALLEY", {"AALLEY"}), tso.answer("TUCKSHOP", {"TUCKSHOP"}),
       tso.answer("ALLEY", set()), tso.answer("ADOISON", {"ADOISON"})))
# numbered_letters(): in a grid printing its numbers a light's one unread
# numbered cell takes the one allowed letter making a word the light was
# read whole as (?UEUE: QUEUE, 15893); not a run-together (H read as N:
# NARD + COURT), not two words (BRIER/DRIER), not a word never read whole,
# and not against a crossing read in full.
def numbered_case(word, allowed, printed, cross=None):
    lts = {(1, "across"): [(0, c) for c in range(len(word))]}
    letters = {(0, c): ch for c, ch in enumerate(word) if c}
    if cross:
        lts[(1, "down")] = [(r, 0) for r in range(len(cross))]
        letters.update({(r, 0): ch for r, ch in enumerate(cross) if r})
    return tso.numbered_letters(lts, letters, {(0, 0): 1}, {(0, 0): set(allowed)},
                                {(1, "across"): set(printed)})
check("a numbered first cell takes the one allowed letter making a word read whole, and only that",
      ({(0, 0): "Q"}, {}, {}, {}, {}, {(0, 0): "D"}),
      (numbered_case("?UEUE", "BDQ", {"BUEUE", "QUEUE"}), numbered_case("?ARDCOURT", "N", {"NARDCOURT"}),
       numbered_case("?RIER", "BD", {"BRIER", "DRIER"}), numbered_case("?UEUE", "Q", {"BUEUE"}),
       numbered_case("?YNE", "D", {"DYNE"}, cross="?XQZ"), numbered_case("?YNE", "D", {"DYNE"}, cross="?ARE")))
# whole_reads(): a light read whole as exactly one word takes its letters
# where the word agrees with every letter settled; not two words (HEADS and
# MEADS), not against a settled letter, and a numbered cell left open only
# as its glyph's best match to a letter model (DROWN read as BROWN, 13773).
def whole_case(printed, settled=None, number=None, drawn="T"):
    lts = {(1, "across"): [(5, c) for c in range(len(next(iter(printed))))]}
    gl = {**glyphs, (5, 0): drawn_letter(drawn)}
    return tso.whole_reads(lts, settled or {}, {rc: set(tso.AZ) for rc in lts[(1, "across")]},
                           {(1, "across"): set(printed)}, {(5, 0): 1} if number else {}, gl,
                           tso.letter_models(glyphs, read))
check("a light read whole as one word takes its open letters, the numbered first one as its glyph's best match",
      ("SLUMP", {}, {}, "TIDE", {}, {}),
      ("".join(whole_case({"SLUMP", "SLOMP"}, {(5, 2): "U"}).get((5, c), "U") for c in range(5)),
       whole_case({"HEADS", "MEADS"}), whole_case({"SLUMP"}, {(5, 2): "O"}),
       "".join(whole_case({"TIDE"}, number=True)[(5, c)] for c in range(4)),
       whole_case({"TIDE"}, number=True, drawn="I"), whole_case({"BROWN"}, number=True)))

# read_solution(): the solution grid under its heading, answers keyed as
# trove_solution_ocr.fill() looks them up, nothing from a grid of other blocks.
from PIL import Image, ImageDraw
ed = Path(os.environ["TMP"]) / "ed"; ed.mkdir()
im = Image.new("L", (1200, 1400), 255)
ImageDraw.Draw(im).rectangle((110, 160, 460, 510), fill=0)
im.save(ed / "leaf_0003.jpg")
f.CROPS = Path(os.environ["TMP"]) / "crops"
import trove_solution_ocr
seen = []
def fake(path, grid, tight=False):
    seen.append((Image.open(path).size, tight))
    return {(1, "across"): "ABC"}, {"blocks": stats_blocks}
trove_solution_ocr.read_answers = fake
sol = {"dir": ed, "leaf": 3, "number": 7, "box": (100, 100, 400, 140)}
stats_blocks = 1.0
got, _ = f.read_solution(f.page(ed, 3), sol, ["..."])
check("solution answers keyed as fill() reads them, the grid cropped tight at 3x and read on its own rules",
      ({"1-across": "ABC"}, ((352 * 3, 352 * 3), True)), (got, seen[0]))
stats_blocks = 0.9
got, info = f.read_solution(f.page(ed, 3), sol, ["..."])
check("a solution grid whose blocks are not the puzzle's gives no answers", ({}, True), (got, "refused" in info))

check("a complete puzzle goes to the corpus, with or without --out",
      [None, None], [f.destination("out", True), f.destination(None, True)])
check("a puzzle with a blank clue goes to --out or nowhere, never the corpus",
      ["out", False], [f.destination("out", False), f.destination(None, False)])
check("complete() is every clue having text, none with a made-up word", [True, False, False],
      [f.complete({"entries": [{"clue": {"text": "A"}}, {"clue": {"text": "B"}}]}),
       f.complete({"entries": [{"clue": {"text": "A"}}, {"clue": {"text": " "}}]}),
       f.complete({"entries": [{"clue": {"text": "A"}}, {"clue": {"text": "Start trom Hint"}}]})])

import fetch_puzzle
ed_dir = Path(os.environ["TMP"]) / "runcache" / "NewsUK1990UKEnglish" / "1990-01-01_1"
ed_dir.mkdir(parents=True)
wrote = []
saved = (f.edition_dirs, f.scan, f.read_puzzle, f.input_hash, f.held_numbers,
         fetch_puzzle.puzzle_path, fetch_puzzle.write_puzzle_file)
f.edition_dirs = lambda cache, paper=None: [ed_dir]
f.scan = lambda d: {"date": "1990-01-01", "item": "NewsUK1990UKEnglish", "solutions": [],
                    "puzzles": [{"number": 18179, "leaf": 1, "box": None},
                                {"number": 18180, "leaf": 2, "box": None}]}
def fake_read(d, found, hit, solutions):
    blank = hit["number"] == 18179
    return {"number": hit["number"]}, {"id": f"times-{hit['number']}", "number": hit["number"],
            "entries": [{"clue": {"text": "Top"}}, {"clue": {"text": "" if blank else "Left"}}]}
f.read_puzzle = fake_read
f.input_hash = lambda d: "h"
f.held_numbers = lambda series="times": set()
fetch_puzzle.puzzle_path = lambda series, n: Path(os.environ["TMP"]) / "corpus" / f"times-{n}.json"
fetch_puzzle.write_puzzle_file = lambda path, puzzle, generator: wrote.append(path.parent.name + "/" + path.name)
rows = f.run(cache=ed_dir.parent.parent, puzzles=Path(os.environ["TMP"]) / "unfiled",
             source=Path(os.environ["TMP"]) / "src", out=open(os.devnull, "w"))
check("run files the complete puzzle in the corpus and the one with a blank clue in --out",
      ["unfiled/times-18179.json", "corpus/times-18180.json"], sorted(wrote, reverse=True))
wrote.clear()
rows = f.run(cache=ed_dir.parent.parent, ledger=Path(os.environ["TMP"]) / "l2.jsonl",
             source=Path(os.environ["TMP"]) / "src", out=open(os.devnull, "w"))
check("without --out a puzzle with a blank clue is written nowhere", ["corpus/times-18180.json"], wrote)
# One puzzle whose write raises is a verdict: the run files the rest, and
# its summary counts the failure.
import io
def failing_write(path, puzzle, generator):
    if puzzle["id"] == "times-18179":
        raise ValueError("times-18179 22-down: definition 'x' is not in the clue ''")
    wrote.append(path.parent.name + "/" + path.name)
wrote.clear()
fetch_puzzle.write_puzzle_file = failing_write
summary = io.StringIO()
rows = f.run(cache=ed_dir.parent.parent, puzzles=Path(os.environ["TMP"]) / "unfiled",
             ledger=Path(os.environ["TMP"]) / "l3.jsonl", source=Path(os.environ["TMP"]) / "src", out=summary)
failed = [v for r in rows for v in r["verdicts"] if v.get("writeFailed")]
check("a puzzle whose write raises is logged, counted and skipped; the rest are filed",
      (["corpus/times-18180.json"], [18179], True, True),
      (wrote, [v["number"] for v in failed], "is not in the clue" in failed[0]["writeFailed"],
       "1  write failed: ValueError" in summary.getvalue()))
# --edition limits the scans as well as the reads: the named edition and
# the days after it (its solution) are scanned, no other edition.
eds = [ed_dir.parent / n for n in ("1990-01-01_1", "1990-01-02_2", "1990-03-01_50")] + \
      [ed_dir.parent.parent / "NewsUK1991UKEnglish" / "1991-01-02_9"]
scanned, read = [], []
f.edition_dirs = lambda cache, paper=None: eds
f.scan = lambda d: scanned.append(d.name) or {"puzzles": [{"number": 1, "leaf": 1, "box": None}], "solutions": []}
f.read_puzzle = lambda d, found, hit, solutions: read.append(d.name) or ({"number": 1}, None)
f.run(cache=ed_dir.parent.parent, write=False, ledger=Path(os.environ["TMP"]) / "l4.jsonl",
      source=Path(os.environ["TMP"]) / "src", out=open(os.devnull, "w"),
      editions=["NewsUK1990UKEnglish/1990-01-01_1"])
check("--edition scans that edition and the days after it, reads it alone",
      (["1990-01-01_1", "1990-01-02_2"], ["1990-01-01_1"]), (sorted(scanned), read))
# A run's (and so a read unit's) stale scans are made whole on the desktop
# when it answers, as a scan unit's are: scan() here only when it does not.
import ocr_remote
remote_scanned, _remote_scan = [], ocr_remote.scan
ocr_remote.scan = lambda d: remote_scanned.append(d.name) or {"puzzles": [{"number": 1, "leaf": 1, "box": None}],
                                                              "solutions": []}
scanned.clear(); read.clear()
f.run(cache=ed_dir.parent.parent, write=False, ledger=Path(os.environ["TMP"]) / "l4r.jsonl",
      source=Path(os.environ["TMP"]) / "src", out=open(os.devnull, "w"),
      editions=["NewsUK1990UKEnglish/1990-01-01_1"])
ocr_remote.scan = _remote_scan
check("a run's scans are made on the desktop when it answers, none here",
      (["1990-01-01_1", "1990-01-02_2"], []), (sorted(remote_scanned), scanned))
# --no-scan scans nothing and reads only the due editions whose read waits
# on no scan: not 1990-01-01, whose next day (its solution) is unscanned.
l5 = Path(os.environ["TMP"]) / "l5.jsonl"
l5.write_text("".join(json.dumps({"edition": f"{d.parent.name}/{d.name}", "filesHash": "h", "scanKey": f.scan_key(),
                                  "scan": {"puzzles": [{"number": 1, "leaf": 1, "box": None}], "solutions": []}}) + "\n"
                      for d in (eds[0], eds[2])))
scanned.clear(); read.clear()
summary = io.StringIO()
f.run(cache=ed_dir.parent.parent, write=False, ledger=l5, source=Path(os.environ["TMP"]) / "src", out=summary,
      scan_new=False)
check("--no-scan scans nothing and reads only the editions no unscanned day's solution waits on",
      ([], ["1990-03-01_50"], True), (scanned, read, "3 wait on a scan" in summary.getvalue()))
# --paper gale --newer-than: only the editions laid out since then are
# scanned (with the days after them) and read, the latest laid out first,
# under the Gale ledger, never filed.jsonl.
gcache = Path(os.environ["TMP"]) / "galecache"
geds = [gcache / "GaleTimes1987UKEnglish" / n for n in ("1987-03-02", "1987-03-03", "1987-03-04", "1987-06-01")]
for k, d in enumerate(geds):
    d.mkdir(parents=True)
    (d / "pages.json").write_text("{}")
    os.utime(d / "pages.json", (1000 + k, 1000 + k))
os.utime(geds[0] / "pages.json", (5000, 5000))
os.utime(geds[1] / "pages.json", (4000, 4000))
scanned.clear(); read.clear()
f.edition_dirs = lambda cache, paper=None: geds if paper is f.GALE else []
f.run(cache=gcache, paper=f.GALE, source=Path(os.environ["TMP"]) / "src", out=open(os.devnull, "w"), newer=3000)
check("--newer-than reads only the editions laid out since, latest laid out first, scanning their next days too",
      (["1987-03-02", "1987-03-03", "1987-03-04"], ["1987-03-02", "1987-03-03"]), (sorted(scanned), read))
check("the Gale run keeps its own ledger", (True, False),
      ((gcache / "filed-gale.jsonl").exists(), (gcache / "filed.jsonl").exists()))
scanned.clear(); read.clear()
f.run(cache=gcache, paper=f.GALE, source=Path(os.environ["TMP"]) / "src", out=open(os.devnull, "w"))
check("without it, every due Gale edition is read, the never-read latest laid out first",
      ["1987-06-01", "1987-03-04"], read)
(f.edition_dirs, f.scan, f.read_puzzle, f.input_hash, f.held_numbers,
 fetch_puzzle.puzzle_path, fetch_puzzle.write_puzzle_file) = saved
check("unsettled: an unscanned edition holds back itself and the SOLUTION_DAYS before it, not after",
      ["1990-01-01_1", "1990-01-02_2"], sorted(d.name for d in f.unsettled(eds, [eds[1]])))
check("unsettled: an edition the scan of a dir dated SOLUTION_DAYS later still holds back; one day more does not",
      [True, False], [Path("x/1990-01-01_1") in f.unsettled([Path("x/1990-01-01_1")], [Path(f"x/1990-01-0{k}_2")])
                      for k in (1 + f.SOLUTION_DAYS, 2 + f.SOLUTION_DAYS)])
check("unsettled: nothing unscanned holds nothing back; an undated unscanned dir holds back every dir",
      [set(), set(eds)], [f.unsettled(eds, []), f.unsettled(eds, [Path("x/listener_x")])])
check("edition_date finds the date anywhere in the name", [__import__("datetime").date(1930, 2, 1), None],
      [f.edition_date(Path("per_times_the-times_1930-02-01_45426")), f.edition_date(Path("listener_x"))])

import cross_validate
a = cross_validate.ArchiveOrg()
check("archiveorg does not compare a file it filed with itself", [False, True],
      [a.covers({"source": {"acquiredBy": "tools/file_archive_org_puzzles.py"}}),
       a.covers({"source": {"acquiredBy": "tools/acquire_book.py"}})])
# A retrained Tesseract model gets its own cache name; RapidOCR's keep theirs.
model = Path(os.environ["TMP"]) / "m.traineddata"
saved = dict(ocr_clues.TESS_MODELS), dict(ocr_clues._MODEL_HASHES)
ocr_clues.TESS_MODELS["times"] = model
# The Telegraph: "No. 18,340 ACROSS" heads the left clue column, DOWN the
# right, the grid under both; "SOLUTION No. 18,339" over the last grid.
titles, sols = f.telegraph_headings([line("No. T8,338ACROSS", 168, 2517), line("Ko. 18.339 ACROSS", 217, 2492),
                                     line("No. 18-340ACROM", 210, 2335), line("SOLUTION No. 18,339", 991, 3698),
                                     line("QUICK CROSSWORD", 189, 3848), line("No. 12 Down Street", 900, 100)])
check("Telegraph titles however misread, the solution box the solution grid's width, no Quick",
      ([18338, 18339, 18340], [(18339, f.TELEGRAPH_SOLUTION_SPAN)]),
      ([n for n, _, _ in titles], [(n, b[2] - b[0]) for n, b in sols]))
check("the Telegraph's editions file as telegraph, numbered as the feed's",
      ("telegraph", "telegraph", [True, True]),
      (f.paper_of(cache / "TheDailyTelegraph1985UKEnglish" / "x").series,
       f.paper_of(cache / "SundayTelegraph1971UKEnglish" / "x").series,
       [abs(n - f.telegraph_expected_number(datetime.date.fromisoformat(d))) <= 5
        for d, n in [("1985-01-02", 18338), ("2009-02-07", 25846)]]))
check("a heading led by the puzzle's number, a zero read for O; a street name no heading",
      ["ACROSS", "ACROSS", None], [f.numbered_heading(t_) for t_ in ("No. 18.339ACR0SS", "No. T8,338ACROSS",
                                                                       "No. 12 Down Street")])
# Clues over the grid: split at the gutter, which the left column's long
# lines pass the grid's middle to reach; the right column overhangs the
# grid but ends before the next column's words; specks are no line.
grid = (200, 3100, 900, 3800)
lines = [line("No. 18,340ACROSS", 210, 2335), line("DOWN", 700, 2335),
         line("1 Plumber who puts on airs in", 215, 2365), line("Local", 570, 2365, ),
         line("trader providing people", 640, 2365), line("Lak", 935, 2365),
         line("Scotland (5)", 240, 2390), line("(8)", 600, 2390), line(", . .", 600, 2415)]
lines[3] = [(570, 2365, 620, 2381, "1"), (630, 2365, 680, 2381, "Local")]
top = 2325
split = f.gutter(lines, grid, top)
right = f.gutter(lines, grid, top, grid[2] - f.OVERHANG, grid[2] + f.OVERHANG)
check("gutter between the columns, right edge before the next column", (True, True),
      (520 <= split < 570, 866 <= right < 935))
check("clues-above columns: the title read as ACROSS, specks and the next column left out",
      "ACROSS\n1 Plumber who puts on airs in\nScotland (5)\nDOWN\n1 Local trader providing people\n(8)",
      f.column_text(f.columns(lines, grid, None, 15, (top, split, right))))
check("a 1 read as I or l at a clue's start, '<' for '(', specks after a count, a count left open at a list's end",
      "ACROSS\n1 A fruitful cause (5)\n17 More than two (5-8)\n29 Swallows (5)\nDOWN\n1 Some (5-\n4)",
      f.tidy("ACROSS\nIA fruitful cause <5)'\nI7 More than two (5-8).\n29 Swallows (5r\nDOWN\n1 Some (5-\n4)"))
g = ["...#...", "...#...", "......."]
laid, _ = f.lay_loose(f.parse("ACROSS\n1 & 4 Linked words (3,3)\nDOWN\n1 Down (3)")[0], g)
check("a linked clue laid on the lights its numbers name when one count fills them; the tail reads See",
      (("Linked words", "3,3", ["1-across", "4-across"]), "See 1"), (laid.get("1-across"), laid.get("4-across", ("",))[0]))
laid, _ = f.lay_loose(f.parse("ACROSS\n1 & 4 Linked words (7)\nDOWN\n1 Down (3)")[0], g)
check("a linked clue whose count does not fill its lights is not laid", None, laid.get("1-across"))
got, _ = ocr_clues.reconcile({"15-down": ("Entice Fortune, but provoke Nemesis? (5,4) - . 18 & 25 The point of", "9",
                                          ["15-down", "24-down"])},
                         ["15 & 24 Entice Fortune, but provoke Nemesis? (5,4)"], {"15-down": 5, "24-down": 4, "25-down": 5})
check("a run-on cut at the next clue; the count left inside ends the clue and is its count",
      ("Entice Fortune, but provoke Nemesis?", "5,4"), got["15-down"][:2])
check("text run in ahead of a clue's own number, with a number in it, is cut off",
      ["The point is there's a proposition", "One who acquires a farm building"],
      [ocr_clues.trimmed("The solution of Prize Puzzle No 18,178 will appear 26 The point is there's a proposition",
                         "26-across"),
       ocr_clues.trimmed("Tried to join paper 7. 4 Not fully understood 5 One who acquires a farm building", "5-down")])
check("a clue that prints its own number keeps it", "Like a don in trouble with Homer in 15 Down",
      ocr_clues.trimmed("Like a don in trouble with Homer in 15 Down", "15-across"))
check("a lone small i, a heading on 1 down and specks inside a line-end hyphen go",
      ["Religious system uniting man", "Poet's way to frame a line", "She reverts to foolish buying method",
       "One accepted as likewise a great artist"],
      [ocr_clues.trimmed(t, lid) for t, lid in (("Religious system i uniting man", "9-across"),
                                                ("Down i Poet's way to frame a line", "1-down"),
                                                ("She reverts to foolish buy- 4 ing method", "16-across"),
                                                ("One accepted as like- .wise a great artist", "19-down"))])
check("the newspaper i, a heading word in a later clue and a stutter stand",
      ["Showing true colours, posh editor supports this paper but not the i", "Across Aegean rain falls",
       "Gladly f-fib first"],
      [ocr_clues.trimmed(t, lid) for t, lid in (("Showing true colours, posh editor supports this paper but not the i",
                                                 "8-down"), ("Across Aegean rain falls", "21-across"),
                                                ("Gladly f-fib first", "21-across"))])
check("a broken count or symbols after the last word go; a percentage and a cross-reference stand",
      ["Girl named in a Lords amendment", "In memory of former days?", "Twice reduced by 50%", "Don't 23!"],
      [ocr_clues.trimmed(t, "5-down") for t in ("Girl named in a Lords amendment S).",
                                                "In memory of former days? &%S4),", "Twice reduced by 50%",
                                                "Don't 23!")])
got, blank = ocr_clues.reconcile({"1-across": ("19, we hear, in the crew", "5", None)},
                                 ["1 19, we hear, in the crew (5)"] * 2, {"1-across": 5, "19-across": 5})
check("a clue opening on another light's number is no lost opening", ("19, we hear, in the crew", {}),
      (got["1-across"][0], blank))
# Two clues run together win the vote when every reading runs them together
# the same way: the Times of 3 April 1985's 2 down and 1 May 1975's 28
# across filed as one clue each. Such a text is blanked, never filed.
merged_2d = "Where everybody goes in to sweep around the floor? 2 Seek fresh increases"
merged_28a = "Confused by a divine the Spanish backed (15) 2 Master of the Rolls surrounds aesthetic victim"
check("a voted clue with a clue number and another clue inside it is blanked",
      ({"2-down": ("", "8", None)}, {"2-down": "two clues run together"}),
      ocr_clues.reconcile({"2-down": (merged_2d, "8", None)}, [f"2 {merged_2d} (8)"] * 2, {"2-down": 8}))
check("a voted clue with a count and another clue after it is blanked",
      ({"28-across": ("", "6", None)}, {"28-across": "two clues run together"}),
      ocr_clues.reconcile({"28-across": (merged_28a, "6", None)}, [f"28 {merged_28a} (6)"] * 2, {"28-across": 6}))
check("numbers a setter writes are no merged clue", [None] * 7,
      [ocr_clues.merged(t) for t in ("Catch 22 Hero", "Over 18? Join", "Of the Vale, turn to Map 10 E",
                                     "Bird (4)", "Dad up to no good, scoffing (26) wild snappers?",
                                     "Massive commercial transaction? 3 Down!",
                                     "Halt opening exchange in No. 1 Court feature")])
check("two counts in one clue are two clues", "two clues run together",
      ocr_clues.merged("Harsh one (9) avoiding repetition (5) of"))
check("a clue cut at its own count when text follows it", ["Entice Fortune?", "Entice Fortune? (5,4)"],
      [ocr_clues.cut_at_count("Entice Fortune? (5,4) - 18 &", "5,4"), ocr_clues.cut_at_count("Entice Fortune? (5,4)", "5,4")])

# The desktop VLM's failures (Times heldout, VLM alone): a reading of another
# part of the page (No 20,989), a reading with every clue blank (No 19,742),
# and its pick's single-word misreads ("gain" for gait, "linner" for linnet).
g5 = ["....."] * 5
good = ("ACROSS\n1 Bird in a tree (5)\n6 Fish in the sea (5)\n7 Dog on a lead (5)\n"
        "DOWN\n1 Cat on a mat (5)\n2 Cow in a field (5)\n3 Hen in a coop (5)")
elsewhere = ("ACROSS\n1 Advantageous position not the first part (6,5)\n4 One accepted by Constable (7)\n"
             "12 Sounds like sort of horse (5)\nDOWN\n14 Encouragement after slipping (3-1-5)\n"
             "16 Improperly assigned to throne (2,3,4)")
same_slots = ("ACROSS\n1 Seize illegal drugs (5)\n6 Thoughts of leader (5)\n7 Tried to get editor (5)\n"
              "DOWN\n1 Again request harvest (5)\n2 Servant with carriage (5)\n3 Child looked after (5)")
kept, dropped = f.screened({"djvu": good, "ch": good.replace("tree", "trec"), "vlm": elsewhere}, g5)
check("a reading whose clues name no light of the grid with their count is dropped",
      (["ch", "djvu"], ["vlm"]), (sorted(kept), sorted(dropped)))
kept, dropped = f.screened({"djvu": good, "ch": good.replace("tree", "trec"), "vlm": same_slots}, g5)
check("a reading that fits the slots but disagrees with every other reading's clue of each number is dropped",
      ["vlm"], sorted(dropped))
kept, dropped = f.screened({"djvu": good, "ch": good, "vlm": "ACROSS\n1 (5)\n6 (5)\nDOWN\n1 (5)\n2 (5)"}, g5)
check("a reading with every clue blank is no reading", {"vlm": "no clue words"}, dropped)
kept, dropped = f.screened({"djvu": good, "vlm": "\n".join(good.splitlines()[:3] + ["DOWN"])}, g5)
check("a partial reading still votes: its clues lose to the others clue by clue", ({}, 2), (dropped, len(kept)))
got, _ = ocr_clues.reconcile({"21-across": ("Poet's", "6", None)},
                             ["21 Poet's uninteresting study (6)", "21 Poet's uninteresting study (6)"])
check("words a partial reading lost are put back from the others", "Poet's uninteresting study", got["21-across"][0])
check("a pick's real word no reading has, where every reading has one a letter off, takes theirs",
      "Walk the street unsteady gait", ocr_clues.held("Walk the street unsteady gain", ["Walk the street unsteady gait (6)"]))
check("a pick's non-word takes the lexicon word another reading has there",
      "For example, a linnet entangled in a bush",
      ocr_clues.held("For example, a linner entangled in a bush", ["For example, a linnet entangled in a bush (9)",
                                                                  "For exampie, a llnner entangled ia a bush"]))
check("a pick's non-word no reading has a lexicon word for fails the pick", "",
      ocr_clues.held("For example, a linner entangled in a bush", ["For example, a linner entangled in a bush (9)"]))
check("a pick that is another clue's text (No 20,989's 1 across read as 11 down) fails", "",
      ocr_clues.held("Advantageous position - not the first part of record?",
                     ["First issue in 1999, for example (5,6)"]))
laid, blank = ocr_clues.vlm_pick({"vlm": "x"}, {"13-across": ("", "9", None)}, {"13-across": "readings differ"},
                                 lambda t: ({"across": [{"tokens": [{13}], "text": "For example, a linner entangled",
                                                         "enums": {"9"}, "see": None}], "down": []}, None),
                                 lambda lid, cands: "For example, a linner entangled")
check("the VLM's pick of a non-word no reading corrects is not filed", ("", ["13-across"]),
      (laid["13-across"][0], sorted(blank)))

# Times 13,998 as an older reading filed it: the loose lay put 18 across's
# clue on 15 across too, where a misread number laid it, and 15 across's own
# clue ("An Athenian acted in any element", ANTIMONY) was lost.
laid_13998 = {"14-across": ("A man's man (if not hero's)", "5", None),
              "15-across": ("Occasional raid cops turn out for", "8", None),
              "18-across": ("Occasional raid cops turn out for", "8", None),
              "16-down": ("Picture by satellite has space problem", "9", None),
              "17-down": ("See 16", None, None), "19-down": ("See 16", None, None)}
laid, blank = f.one_light_each(laid_13998, {}, fits={"15-across", "18-across"})
check("one clue on two lights its count fills both: filed on neither, both read again (Times 13,998)",
      (["15-across", "18-across"], "", "", "A man's man (if not hero's)", "See 16"),
      (sorted(blank), laid["15-across"][0], laid["18-across"][0], laid["14-across"][0], laid["19-down"][0]))
laid, blank = f.one_light_each(laid_13998, {}, fits={"18-across"})
check("one clue on two lights its count fills one of: kept there, the other read again",
      (["15-across"], "", "Occasional raid cops turn out for"),
      (sorted(blank), laid["15-across"][0], laid["18-across"][0]))
# Listener No 3 prints "An exclamation." under both lists, for 32A and 2D.
laid, blank = f.one_light_each({"32-across": ("An exclamation.", None, None), "2-down": ("An exclamation.", None, None)}, {})
check("one clue in both lists is printed twice: kept on both",
      ({}, "An exclamation.", "An exclamation."), (blank, laid["32-across"][0], laid["2-down"][0]))

# A held filing with one clue on two lights takes this reading's clue for
# each of them, blank where it has none; the rest of the file stands.
def held_13998(texts):
    return {"id": "times-13998", "source": {"acquiredBy": f.TOOL}, "dimensions": {"cols": 8, "rows": 3},
            "entries": [{"number": n, "direction": "across", "position": {"x": 0, "y": y}, "length": 8,
                         "clue": {"text": t, "enumeration": "8"} if t else {"text": "", "missing": True},
                         "solution": a}
                        for (n, y, a), t in zip([(14, 0, "VALETTTT"), (15, 1, "ANTIMONY"), (18, 2, "SPORADIC")],
                                                texts)]}
occasional = "Occasional raid cops turn out for"
path = Path(os.environ["TMP"]) / "times-13998.json"
path.write_text(json.dumps(held_13998(["A man's man", occasional, occasional])))
mended, now = f.mend_held(held_13998(["A man's man", "An Athenian acted in any element", occasional]), path)
check("a held clue on two lights takes this reading's clue for each, answers kept",
      (["A man's man", "An Athenian acted in any element", occasional], {"15-across": "An Athenian acted in any element", "18-across": occasional}, "ANTIMONY"),
      ([e["clue"]["text"] for e in mended["entries"]], now, mended["entries"][1]["solution"]))
mended, now = f.mend_held(held_13998(["A man's man", "", occasional]), path)
check("a light this reading has no clue for is filed blank", ("", True),
      (mended["entries"][1]["clue"].get("text", ""), mended["entries"][1]["clue"].get("missing")))
path.write_text(json.dumps(held_13998(["A man's man", occasional, occasional])))
mended, now = f.mend_held(None, path)
check("with no reading, each light a held clue sits on twice is blank", {"15-across": "", "18-across": ""}, now)
check("a held filing with no clue on two lights is left alone", None,
      f.mend_held(held_13998(["A man's man", "x", "y"]), path.write_text(json.dumps(
          held_13998(["A man's man", "An Athenian", occasional]))) and path))

# A refused held clue under an annotation (ftcryptic-9091 22 down): this
# reading's clue replaces it and the annotation, written against the old
# words, goes; with no clue read for it the held clue goes blank: no write
# keeps another clue's text (scan_queue.file_puzzle), and check_rewrite lets
# such a clue go.
import copy, definitions, puzzle_integrity, puzzle_schema
held = held_13998(["A man's man", "Occasional raid 18 Cops turn out", "Sporadic"])
held["entries"][1]["annotation"] = {"definitions": [{"text": "Cops turn out", "at": 19}]}
held["source"]["retrievedFrom"] = "newspaper"
path.write_text(json.dumps(held))
mended, now = f.mend_held(held_13998(["A man's man", "An Athenian acted in any element", "Sporadic"]), path)
check("a held clue the filer now refuses takes this reading's clue, its annotation dropped",
      ({"15-across": "An Athenian acted in any element"}, None),
      (now, mended["entries"][1].get("annotation")))
for reading in (None, held_13998(["A man's man", "", "Sporadic"])):
    blanked, now = f.mend_held(reading, path)
    flags = []
    puzzle_integrity.check_rewrite(held, blanked, flags)
    check("a held clue holding another clue no reading has goes blank, annotation and all, and may be written",
          ({"15-across": ""}, None, True, []),
          (now, blanked["entries"][1].get("annotation"), blanked["entries"][1]["clue"].get("missing"), flags))
mended, now = f.mend_held(held_13998(["A man's man", "An Athenian acted in any element", "Sporadic"]), path)
flags = []
puzzle_integrity.check_rewrite(held, definitions.place_puzzle(puzzle_schema.prune(copy.deepcopy(mended))), flags)
check("a mended filing places its definitions and passes the rewrite check", [], flags)

# A reader's fix to a held clue's words reaches the file (corrected_clues):
# Listener No 3's 52D gained its opening "A". A reading that drops a real
# word, swaps one, blanks a clue or makes one up does not land; nor does
# one under an annotation or a source_clue_wrong row, written against the
# held words, nor one that improves() the file (it replaces it whole).
check("a reading adding a word, or mending a misread non-word, corrects a held clue",
      [True, True, True], [f.corrects("Frontier cantonment.", "A Frontier cantonment."),
                           f.corrects("Fudqe the issue", "Fudge the issue"),
                           f.corrects("A 100 of 58 across.", "A 100 of 56 across.")])
check("the vote's speck removal, a stop after a lone letter dropped, corrects a held clue (No 3's 27D and 50D)",
      [True, True], [f.corrects("A. junction on the East Indian Railway.", "A junction on the East Indian Railway."),
                     f.corrects("A. Frontier cantonment.", "A Frontier cantonment.")])
check("other marks alone correct nothing (mirror)",
      [False, False], [f.corrects("A town.", "A town,"), f.corrects("A. Smith wrote it", "A. Smith, wrote it")])
# Stored archive.org readings would have landed these; each is refused, its
# mirror taken.
refused = [("Watch salesman with consumer", "Watch salesman with consumer sumer."),  # a neighbour's fragment
           ("Protest over first of buses put out of service", "Protest over first of buses put out of sen service"),
           ("Be responsible for flooring?", "Is Be responsible for flooring?"),  # an opener before a capital
           ("How much work in Schönberg's music?", "How much work in Schö- berg's music?"),  # a hyphen split
           ("Coin-in-the-slot source, medication?", "Coin-in-the-slot source-of medication?"),  # a short word hyphened on
           ("Doctor enters a ring, or pulpit", "Doctor enters a ring, pulpit or pulpit"),  # a word read twice
           ("Foolhardy in war, as Hot spur was?", "Foolhardy in war, as Hot was spur?"),  # words reordered
           ("Distant object worth very little until 1961", "Distant object worth very little until 196"),
           ("Controversial poet receives £1 for subsistence", "Controversial poet receives I for subsistence"),
           ("Spirit-raising shattered Mather", "Spirit-raising shattered Mother"),  # a name to a word
           ("Underclothing adjusted in this restaurant", "Underclothing I adjusted in this restaurant"),
           ("In revised text pirate is the look-out man", "In La revised text pirate is the look-out man"),
           ("Letter from the girl I have cut.", "Letter from the girl I have oil cut."),  # no corpus pair
           ('Extend onself. There\'s time "inside"', 'Extend oneself. There\'s time "*inside"')]  # a speck symbol
check("a re-read's fragment, opener, hyphen split, reorder, figure lost, name swapped or speck corrects nothing",
      [], [r for r in refused if f.corrects(*r)])
taken = [("Watch salesman with consumer", "Watch salesman with a consumer"),
         ("in trouble, blame Ella", "If in trouble, blame Ella"),  # an opener restoring the capital
         ("How much work Schönberg's music?", "How much work in Schönberg's music?"),
         ("Anxious to get hearted West Indian music", "Anxious to get half-hearted West Indian music"),
         ("Cut 3 dash during keep fit session", "Cut a dash during keep fit session"),
         ("Drilled one of Byrun's mighty tribes", "Drilled one of Byron's mighty tribes"),
         ("Dealer about to take manager", "Dealer about to take a manager")]
check("(mirror) a lost article, opener, word, misread figure or name mended corrects a held clue",
      [], [t for t in taken if not f.corrects(*t)])
check("a reading losing or swapping a real word, blank, unchanged, marks only or made up corrects nothing",
      [False] * 8, [f.corrects("Frontier cantonment.", "Frontier."),
                    f.corrects("Swearing and lying", "Swearing and lying (7). But not backward"),
                    f.corrects("A town (4)", "A town (4) 7"),
                    f.corrects('The shout "Last out"', 'The shout \u201cLast out\u201d'),
                    f.corrects("Fudge the issue", "Judge the issue"),
                    f.corrects("Frontier cantonment.", ""),
                    f.corrects("A town", "A town"),
                    f.corrects("A town", "A town xqzvb")])
held = held_13998(["A man's man", "Occasional raid cops turn out", "Sporadic"])
path.write_text(json.dumps(held))
mended, now = f.mend_held(held_13998(["A man's man", "Occasional raid cops turn out for", "Sporadic"]), path)
check("a held filing takes a reading's added word, answers kept, the rest as held",
      ({"15-across": "Occasional raid cops turn out for"}, "ANTIMONY", "A man's man"),
      (now, mended["entries"][1]["solution"], mended["entries"][0]["clue"]["text"]))
flags = []
puzzle_integrity.check_rewrite(held, mended, flags)
check("a corrected filing passes the rewrite check", [], flags)
check("a reading losing a held word leaves the file alone", None,
      f.mend_held(held_13998(["A man's man", "Occasional raid cops turn", "Sporadic"]), path))
check("a reading with a clue blank leaves the held clue alone", None,
      f.mend_held(held_13998(["A man's man", "", "Sporadic"]), path))
check("a reading laying another light's words on a light corrects nothing", None,
      f.mend_held(held_13998(["A man's man", "Occasional raid cops turn out", "Occasional raid cops turn out"]), path))
held["entries"][1]["annotation"] = {"definitions": [{"text": "turn out", "at": 21}]}
path.write_text(json.dumps(held))
check("an annotated held clue keeps its words and annotation", None,
      f.mend_held(held_13998(["A man's man", "Occasional raid cops turn out for", "Sporadic"]), path))
del held["entries"][1]["annotation"]
path.write_text(json.dumps(held))
import fetch_puzzle
fetch_puzzle.SOURCE_CLUE_WRONG[("times-13998", "15-across")] = ("Occasional", "Occasional raid cops turn out", "x")
check("a held clue a source_clue_wrong row names keeps its words", None,
      f.mend_held(held_13998(["A man's man", "Occasional raid cops turn out for", "Sporadic"]), path))
del fetch_puzzle.SOURCE_CLUE_WRONG[("times-13998", "15-across")]
path.write_text(json.dumps(held_13998(["A man's man", "Occasional raid cops turn out", ""])))
check("a reading that improves() the file is no correction: it replaces the file", None,
      f.mend_held(held_13998(["A man's man", "Occasional raid cops turn out for", "Sporadic"]), path))
other = held_13998(["A man's man", "Occasional raid cops turn out", "Sporadic"])
other["source"]["acquiredBy"] = "tools/acquire_book.py"
path.write_text(json.dumps(other))
check("another tool's file is never corrected", None,
      f.mend_held(held_13998(["A man's man", "Occasional raid cops turn out for", "Sporadic"]), path))

check("a one read as l before a digit, and the space lost after a question mark, mended",
      "Worried? Pulse for a 19th-century school", ocr_clues.clean("Worried?Pulse for a l9th-century school"))

for body in (b"old", b"new"):
    model.write_bytes(body)
    ocr_clues._MODEL_HASHES.clear()
    check(f"reader_key hashes the model ({body.decode()})", True,
          ocr_clues.reader_key("times").startswith("times-"))
    if body == b"old":
        old_key = ocr_clues.reader_key("times")
check("a changed model changes the cache name", True, ocr_clues.reader_key("times") != old_key)
check("RapidOCR readers keep their name", "en5", ocr_clues.reader_key("en5"))
ocr_clues.TESS_MODELS.clear(); ocr_clues.TESS_MODELS.update(saved[0])
ocr_clues._MODEL_HASHES.clear(); ocr_clues._MODEL_HASHES.update(saved[1])

# Real page crops (tools/fixtures/archive-org-grids, cases.json gives each
# one's scan and title box): the grid is the one the title heads wherever it
# lies, whole.
from PIL import Image
fix = Path("fixtures/archive-org-grids")
cases = json.loads((fix / "cases.json").read_text())
def located(name):
    """The grid box found in a region of a page, laid on a page as wide as
    the scan's (a grid's size is judged against the page's width)."""
    region = Image.open(fix / f"{name}.jpg").convert("L")
    pg = Image.new("L", (cases[name].get("pageWidth", f.SCAN_WIDTH), region.height), 255)
    pg.paste(region, (0, 0))
    box, side = f.locate_grid(pg, cases[name]["title"])
    return side, f.shaped_on(pg, box), box
side, shaped, box = located("times-20117-below-far")
check("a grid further under its title than the first crop reaches is read whole (Times 20,117)",
      ("below", True, True), (side, shaped, abs((box[3] - box[1]) - (box[2] - box[0])) < 30))
side, shaped, box = located("times-16977-clues-joined")
check("a grid whose ink joins the clue column under it is found under its title (Times 16,977)",
      ("below", True, True), (side, shaped, box[3] - box[1] < 700))
side, shaped, box = located("times-14132-flush-title")
check("a grid flush under its title, which the under-crop cuts, is found whole (Times 14,132)",
      ("below", True), (side, shaped))
side, shaped, box = located("times-16988-prize-solutions")
check("a Saturday prize grid under the last puzzles' two solution grids is found under them (Times 16,988)",
      ("below", True, True), (side, shaped, box[1] > 700))
saved_shaped, f.solution_shaped = f.solution_shaped, lambda img: lambda box: False
check("(mirror) taking the solution grid for any other ink under the title, it is refused", None,
      located("times-16988-prize-solutions")[0])
f.solution_shaped = saved_shaped
side, shaped, box = located("times-17001-above")
check("a grid printed over its title is found (Times 17,001)", ("above", True), (side, shaped))
side, shaped, gbox = located("ftcryptic-8649-left")
check("a grid left of its title is found, not ink under the title (FT Monday Prize 8,649)",
      ("left", True), (side, shaped))
side, shaped, _ = located("ftcryptic-5607-right")
check("a grid right of its title, the title's box past the page's left edge (FT 1985-01-02, 5,607)",
      ("right", True), (side, shaped))
side, shaped, box = located("ftcryptic-5101-article-above")
check("an article's ink far over the title is no grid over it: the grid right of it is (FT 1983-02-18, 5,101)",
      ("right", True, True), (side, shaped, box[0] > cases["ftcryptic-5101-article-above"]["title"][2] - 300))
f.ABOVE_GAP, saved_gap = 10 ** 6, f.ABOVE_GAP
check("(mirror) with no bound on the gap, the article is taken for the grid", "above",
      located("ftcryptic-5101-article-above")[0])
f.ABOVE_GAP = saved_gap
lines = [[tuple(w) for w in ws] for ws in cases["ftcryptic-8649-left"]["lines"]]
text = f.column_text(f.columns(lines, gbox, left=f.left_columns(lines, gbox)))
check("the clue columns left of the grid are read, across then down",
      (True, True), (text.startswith("ACROSS\nI Footwear"), "\nDOWN\n2 Fruit" in text))
# The 1983-86 FT: ACROSS and the first DOWN clues in a column under the title,
# left of the grid; the rest of DOWN in two columns under the grid, a clue
# running on from each column into the next (RapidOCR's words, 5,607).
_, _, gbox = located("ftcryptic-5607-right")
lines = [[tuple(w) for w in ws] for ws in cases["ftcryptic-5607-right"]["lines"]]
lead = f.lead_split(lines, gbox, f.lead_column(cases["ftcryptic-5607-right"]["title"], gbox))
cols = f.columns(lines, gbox, lead=lead, split=f.under_gutter(lines, gbox))
text = f.column_text(cols)
parsed, _ = f.parse(text)
check("the column beside the grid is read first, then the two under it",
      ("ACROSS", "cause lock-jaw(7)", "ofNewport（5)"), tuple(c[0][4] for c in cols))
check("a clue's run-on line opens the next column and stays with its clue",
      (True, True), ("6 Chewing nuts with tea may\ncause lock-jaw" in text,
                     "22 Music for one in outskirts\nofNewport" in text))
check("an under-grid clue's number outdented past the grid's edge stays in its column",
      True, any(l[4].startswith("10 It's simple") for l in cols[1]))
# This one reading's own slips (25 read as 23, 19 run into 17) are the vote's
# to mend: the 15 across and 12 of the 13 down parse.
check("every across and down clue of the layout parses",
      (15, 12), tuple(len(parsed[k]) for k in ("across", "down")) if parsed else None)
check("(mirror) read as two columns under the grid, no reading parses", None,
      f.parse(f.column_text(f.columns(lines, gbox, split=f.under_gutter(lines, gbox))))[0])

side, shaped, box = located("times1930-54-fold")
check("a grid is found when a fold in the paper runs down through its title and into it (1930 No 54)",
      ("below", True), (side, shaped))
f.CLEAR_SHARE, saved_clear = -1, f.CLEAR_SHARE
check("(mirror) without the clear row under the title the folded grid is refused", None, located("times1930-54-fold")[0])
f.CLEAR_SHARE = saved_clear

side, shaped, box = located("gale-times-17247-tight-title")
check("a grid whose top frame lies 2px under its title's foot, a descender over it, is the title's (Gale 1987-01-07)",
      ("below", True), (side, shaped))
f.TITLE_OVERLAP, saved_overlap = 0, f.TITLE_OVERLAP
check("looking for the clear row over the title's foot only, a crop beside the title finds it whole under it",
      "below", located("gale-times-17247-tight-title")[0])
f.TITLE_OVERLAP = saved_overlap

side, shaped, box = located("times-16960-foot")
check("a grid box ends at the grid's foot frame, not under the ACROSS line touching it (Times 16,960)",
      ("below", 711), (side, box[3]))
side, shaped, box = located("times-20778-faint-foot")
check("a grid box keeps its last row of cells when its foot frame is too faint to be one (Times 20,778)",
      ("below", 838), (side, box[3]))
cut = Path(os.environ["TMP"]) / "20778.png"
Image.open(fix / "times-20778-faint-foot.jpg").crop((box[0] - 6, box[1] - 6, box[2] + 6, box[3] + 6)).save(cut)
check("its grid reads whole off the box", 15, len(f.trove_grid.read_grid(cut)[0] or ()))
# The 1970s-80s Times prints its blocks as a halftone stipple, in places so
# pale that the paper between its dots is a patch as big as a light's
# (Times 15,725 read "not 180-degree symmetric", 16,331 "r4c8 is neither a
# light nor a block").
for name in ("times-15725-grey-blocks", "times-16331-grey-blocks-noisy"):
    check(f"grey stippled blocks read as blocks, cell for cell ({name})",
          (cases[name]["grid"], None), f.trove_grid.read_grid(fix / f"{name}.jpg"))
# A lattice fit that holds where the scan does not: two stipples merged
# without a rule leave a patch half a cell off, which chained a column's
# patches into the next column's (Times 15,174); a warped corner (14,653);
# a stray mark cutting a light's paper short (14,797); a sticker over four
# rows, read from the cells' mirrors (15,773).
for name in ("times-15174-column-half-off", "times-14653-warped", "times-14797-stray-mark",
             "times-15773-sticker"):
    check(f"the lattice is fitted and every cell read ({name})",
          (cases[name]["grid"], None), f.trove_grid.read_grid(fix / f"{name}.jpg"))
check("a column's patches are not chained into the next by one half a cell between",
      [0, 0, 0, 1, 1], f.trove_grid.steps([2.0, 2.05, 2.5, 2.95, 3.0]))
# A page scanned at twice the usual width: its grid is twice as wide, not
# too big to be one (Times 17,186 cut the solution grid over its title).
side, shaped, box = located("times-17186-double-width")
check("a grid on a double-width page is found under its title (Times 17,186)",
      ("below", True), (side, shaped))
cut = Path(os.environ["TMP"]) / "17186.png"
Image.open(fix / "times-17186-double-width.jpg").crop((box[0] - 6, box[1] - 6, box[2] + 6, box[3] + 6)).save(cut)
check("its grid reads off the box, the puzzle's and not the filled solution's",
      (cases["times-17186-double-width"]["grid"], None), f.trove_grid.read_grid(cut))
check("a light with no neighbouring light is no crossword's", "the light at r1c1 has no neighbouring light",
      f.trove_grid.unchecked([".#.", "#..", "..."]))
check("lights in two patches are no crossword's", "the lights are not one connected patch",
      f.trove_grid.unchecked(["..#", "###", "#.."]))
check("one patch of lights, each with a neighbour, is a crossword's", None,
      f.trove_grid.unchecked(["...", ".#.", "..."]))
side, shaped, box = located("times-16357-title")
check("a grid whose top frame reaches into its title's box is the title's grid (Times 16,357)",
      ("below", True), (side, shaped))

# Real clue readings (tools/fixtures/archive-org-clues: each edition's
# column texts as the readers read them and its scanned grid; times-16960
# also has RapidOCR's words and the grid box): the clue each reading spoils
# is filed whole.
import file_trove_puzzles as ftp
import reconstruct_grid as rg
clue_cases = json.loads(Path("fixtures/archive-org-clues/cases.json").read_text())
def readings_of(name):
    c = clue_cases[name]
    lengths = {f"{n}-{d}": len(cells) for (n, d), cells in rg.light_cells(c["grid"]).items()}
    return c["texts"], lengths
def parsed_of(name, reader):
    p, why = f.parse(clue_cases[name]["texts"][reader])
    assert p, why
    return {(n, d): c for d in ("across", "down") for c in p[d]
            for n in (c["tokens"][0] if len(c["tokens"][0]) == 1 else ())}
def voted(name, reader, lid, text, enum):
    texts, lengths = readings_of(name)
    return ocr_clues.reconcile({lid: (text, enum, None)}, [t for k, t in texts.items() if k != reader],
                               lengths)[0][lid][0]
check("a clue the print opens in lower case, every reading with its number before it, is filed (Times 15,122 13A)",
      "under twenty-one", voted("times-15122", "djvu", "13-across", "under twenty-one", "5"))
check("a clue opening on two cross-references is filed (Times 15,122 5D)",
      "3 3 on the watch", voted("times-15122", "djvu", "5-down", "3 3 on the watch", "5"))
check("a cross-reference read apart is one number where most readings have it (Times 16,376 19D)",
      "Agaric, maybe, confused with 15's first reformer",
      voted("times-16376", "djvu", "19-down", "Agaric, maybe, confused with 1 5's first reformer", "7"))
check("a cross-reference before \"I\" is no next clue run on (Times 16,357 16D)",
      "Removal of 25 I notice in distress outside",
      voted("times-16357", "ch", "16-down", "Removal of 25 I notice in distress outside", "8"))
d16960 = parsed_of("times-16960", "djvu")
check("a count read as a bracket and a digit on its own line ends its clue, the grid giving it (Times 16,960 20A)",
      ("What Ractatraw, in spite of all temptations, remained", set(), "Fine island, jolly compact"),
      (d16960[20, "across"]["text"], d16960[20, "across"]["enums"], d16960[21, "across"]["text"]))
check("a notice printed between two clues is in neither (Times 16,960 5D, 6D)",
      ("Be responsible for burning high church taper", "Peer inside the pearly gates"),
      (d16960[5, "down"]["text"], d16960[6, "down"]["text"]))
c = clue_cases["times-16960"]
text = f.column_text(f.columns([[tuple(w)] for w in c["chWords"]], tuple(c["gbox"])))
check("a line printed across both clue columns ends the column (Times 16,960)",
      (False, True), ("Collins" in text, "\nPeer inside the pearty gztes" in text))
def case_columns(name):
    c = clue_cases[name]
    words, gbox = [[tuple(w)] for w in c["chWords"]], tuple(c["gbox"])
    return [[l[4] for l in col] for col in f.columns(words, gbox, split=f.under_gutter(words, gbox))]
c16136 = case_columns("times-16136")
check("a row RapidOCR reads across a narrow gutter is cut at the right clue's number, not read as a notice"
      " (Times 16,136)",
      ("11 Scandinavian hzs no right to", "perhaps? (10).", "12 Sympathetic type on long desert", "(4)."),
      (c16136[0][6], c16136[0][26], c16136[1][7], c16136[1][-1]))
c15328 = case_columns("times-15328")
check("a line across the gutter is cut at a misread number (\"l4\", \"I6\") and one starting just left of it"
      " (Times 15,328)",
      (["12 Poct hrrs the uurk 'e", "13Thev nere unr!hy"], ["l4 Aias Peter Simple? The real",
                                                            "I6 DeniedhrJack-aaed ton.", "24 Paper. set up balf their"]),
      ([t for t in c15328[0] if t.startswith(("12 ", "13"))],
       [t for t in c15328[1] if t.startswith(("l4", "I6", "24"))]))
c17231 = case_columns("times-17231")
check("a skewed page's right-column line overhanging the grid by under the crop's reach is kept, not its"
      " continuation alone (Times 17,231 17D, 24D)",
      ["17 Top position for apprentice", "in boat (8).", "24 Unusuafly close to the foot", "of the cofumn (5)."],
      [t for t in c17231[1] if t.startswith(("17 ", "in boat", "24 ", "of the"))])
c17001 = case_columns("times-17001")
check("a skewed page's right-column line starting just left of the gutter is the right column's, not run into"
      " the left column's row (Times 17,001 24D, 26A)",
      (["26 Unhappily forgel rule-"], True),
      ([t for t in c17001[0] if t.startswith("26 ")], "24 Present from the queen (5)." in c17001[1]))
check("a column opening on clue 1 read as \"I\" keeps that line (Times 21,083 1A)",
      ["I Very late at night louts, having", "lost out, run wild (4.5)."], case_columns("times-21083")[0][:2])
c13696 = case_columns("times-13696")
check("a line across the gutter at two rows' heights is cut so the line under its right half is kept"
      " (Times 13,696 24D)",
      (["Charles on the river (6).", "24 Jobs for the boys, such as", "Horner ? (5)."], True),
      (c13696[1][c13696[1].index("24 Jobs for the boys, such as") - 1:][:3],
       "20 Shnor the works-ike Isa-" in c13696[0]))
c = clue_cases["times-17382"]
gbox, djvu = tuple(c["gbox"]), [[tuple(w) for w in ws] for ws in c["djvuLines"]]
column = f.left_column(djvu, gbox)
texts = [f.column_text(f.columns(ws, gbox, left=column)) for ws in (djvu, [[tuple(w)] for w in c["chWords"]])]
check("the one clue column left of a Saturday prize grid is read, ACROSS to the last DOWN clue under the grid's"
      " foot (Times 17,382)",
      [(True, True, True)] * 2,
      [(t.startswith("ACROSS\n"), "\n4 Spectacle for a grea" in t, t.rstrip().endswith("bill (4).")) for t in texts])
c = clue_cases["times-16136"]
check("(mirror) a grid whose clues are under it has no column left of it (Times 16,136)", None,
      f.left_column([[tuple(w)] for w in c["chWords"]], tuple(c["gbox"])))
check("a centred notice with no clue number near the gutter still spans it",
      [(100, 0, 700, 20, "Prize Crossword in The Times tomorrow")],
      f.split_across([(100, 0, 700, 20, "Prize Crossword in The Times tomorrow")], [400]))
check("a clue number far from the gutter does not cut a line across it",
      [(100, 0, 700, 20, "12 Poet shows the work returned again and again here")],
      f.split_across([(100, 0, 700, 20, "12 Poet shows the work returned again and again here")], [400]))
d16626 = parsed_of("times-16626", "djvu")
check("\"Prize Crossword in\" between two clues is in neither (Times 16,626 3D, 4D)",
      ("Bones of little girl in centre of trail", "Of great significance to chaps in Missouri.all French"),
      (d16626[3, "down"]["text"], d16626[4, "down"]["text"]))
check("a count torn at a clue's end is read as its count: \"17).\", \"IS).\" (Times 16,626 5A, 19A)",
      (("Definitely the product of a writer", {"7"}), ("Souvenir exhibited by Kildare licensee", True)),
      ((d16626[5, "across"]["text"], d16626[5, "across"]["enums"]),
       (d16626[19, "across"]["text"], "5" in d16626[19, "across"]["enums"])))
check("a word split at a line end is joined where this clue misreads it by a letter (Times 16,626 20D)",
      "Half-clad and primitive, obviously",
      voted("times-16626", "djvu", "20-down", "Half-clad and primitive, obviousJy", "7"))
check("a speck read as a full stop gives way to the comma the other readings have (Times 16,626 4D)",
      "Of great significance to chaps in Missouri, all French",
      voted("times-16626", "djvu", "4-down", "Of great significance to chaps in Missouri.all French", "9"))
p, _ = f.parse(clue_cases["times-13683"]["texts"]["en5"])
p, _ = ftp.renumber(p)
nums = [next(iter(c["tokens"][0])) for c in p["across"] if len(c["tokens"][0]) == 1]
check("a clue number its list's order refuses is left for the grid to place (Times 13,683: 19 between 9 and 12)",
      (True, set()), (nums == sorted(set(nums)), next(c for c in p["across"] if c["text"].startswith("Man"))["tokens"][0]))

# Real page crops whose archive.org text has no crossword title
# (tools/fixtures/archive-org-titles; cases.json gives each one's scan, its
# paper and date, and the words our readers read in each title band, so no
# OCR runs here): the grid is found, the title read over or under it, and the
# number is the one its date implies.
import datetime
tfix = Path("fixtures/archive-org-titles")
tcases = json.loads((tfix / "cases.json").read_text())
band_words = f.band_words
for name, what in (("cryptic-21238", "Guardian 1998-04-02, its title over the grid's left"),
                   ("ftcryptic-9705", "FT 1998-06-11, its number line unread"),
                   ("ftcryptic-7869", "FT 1992-06-10, a column rule beside its title"),
                   ("times-19801", "Times 1995-03-13, its title 250px over the grid"),
                   ("ftcryptic-5607", "FT 1985-01-02, \"F.T. CROSSWORD\" over \"PUZZLE No.\" left of the grid")):
    c = tcases[name]
    f.band_words = lambda img, band, which, path, c=c: [tuple(w) for w in c["bands"][",".join(map(str, band))][which]]
    paper, day = f.PAPERS[c["paper"]], datetime.date.fromisoformat(c["date"])
    got = f.ocr_titles(Image.open(tfix / f"{name}.jpg"), paper, day, name)
    want = int(name.split("-")[1])
    check(f"a title archive.org's text lacks is read by ours: {what}", ([want], True),
          ([t[0] for t in got], bool(got) and abs(got[0][0] - paper.expected(day)) <= f.NUMBER_SLACK))
f.band_words = band_words

# A grid at the page's top edge has a title band over it with no height
# (title_bands clips it to the page): it reads as no words, it does not
# stop the scan. No OCR runs: the band is empty before any reader sees it.
os.environ.pop("OCR_REMOTE", None)
page_img = Image.new("RGB", (400, 600), "white")
band = f.title_bands(page_img, (100, 0, 300, 200))[0]
check("a title band over a grid at the page's top edge has no height", 0, band[3] - band[1])
check("the far band reaches a grid's height over it, the grid's width (a Saturday prize title over its entry form)",
      (3, (100, 100, 300, 300)), (len(f.title_bands(page_img, (100, 300, 300, 500))),
                                  f.title_bands(page_img, (100, 300, 300, 500), far=True)[-1]))
# A Gale page whose whole-page read finds no title has the bands round its
# grid read, the far one too.
gd = Path(os.environ["TMP"]) / "GaleTimes1987UKEnglish" / "1987-07-02"
gd.mkdir(parents=True)
page_img.save(gd / "leaf_0000.jpg")
(gd / "pages.json").write_text(json.dumps({"date": "1987-07-02", "item": "GaleTimes1987UKEnglish",
                                           "crossword_pages": [{"leaf": 0}]}))
saved_h, saved_t = f.ocr_headings, f.ocr_titles
asked = []
saved_bw = f.band_words
f.band_words = lambda img, band, which, path: []
f.ocr_titles = lambda img, paper, day, key, far=False: asked.append(far) or [(17398, (0, 0, 1, 1), None, ["ch", "en5"])]
check("a Gale page with no whole-page title is read in the bands round its grid", ([17398], [True]),
      ([p["number"] for p in f._scan(gd)["puzzles"]], asked))
f.band_words = saved_bw
f.ocr_headings = lambda img, paper, key, day=None: ([(17398, (0, 0, 1, 1), None, ["ch", "en5"])], [])
asked.clear()
check("(mirror) one whose whole-page read has its title is not read again", ([17398], []),
      ([p["number"] for p in f._scan(gd)["puzzles"]], asked))
# A solution heading read as its own edition's title (15,682's grid under
# 15,683, read "15,683") is dropped from the scan: 15,683 never takes it.
f.ocr_headings = lambda img, paper, key, day=None: ([(15683, (0, 0, 1, 1), None, ["ch", "en5"])],
                                          [(15683, (0, 2, 1, 3)), (15682, (0, 4, 1, 5))])
check("a scan drops a solution numbered like its own edition's title", [15682],
      [s["number"] for s in f._scan(gd)["solutions"]])
f.ocr_headings, f.ocr_titles = saved_h, saved_t
# A Times leaf whose archive.org text garbles its solution heading ("Solution
# to Puzzle No 21X162", 1996-05-09) has the heading's band read by our
# readers: a number half of them read one SOLUTION_LAGS before a title
# stands. The mirrors: one reader alone, or a number neither lag gives, is
# no heading; a text that reads the heading is not read again.
saved_bw, saved_sb = f.band_words, f.solution_bands
f.solution_bands = lambda img, words: [(0, 0, 400, 40)]
def band_reads(texts):
    f.band_words = lambda img, band, which, path: ([(10, 10, 60, 30, "Solution"), (70, 10, 90, 30, "to"),
                                                    (100, 10, 150, 30, "Puzzle"), (160, 10, 180, 30, "No"),
                                                    (190, 10, 260, 30, texts[which])] if texts.get(which) else [])
    return [n for n, _ in f.band_solutions(page_img, [20163], [], "band_test")]
check("a garbled text heading is read in its band by our readers", [20162],
      band_reads({"ch": "20. 162", "en5": "20,162", "times": "20,162"}))
check("(mirror) one reader alone is no heading", [], band_reads({"times": "20,162"}))
check("(mirror) a number neither lag before a title gives is no heading", [],
      band_reads({"ch": "20,150", "en5": "20,150", "times": "20,150"}))
td = Path(os.environ["TMP"]) / "NewsUK1996UKEnglish" / "1996-05-09_65575"
td.mkdir(parents=True)
page_img.save(td / "leaf_0023.jpg")
(td / "djvu.xml.gz").write_bytes(b"")
(td / "pages.json").write_text(json.dumps({"date": "1996-05-09", "item": "NewsUK1996UKEnglish",
                                           "crossword_pages": [{"leaf": 23}]}))
saved_ll, called = f.leaf_lines, []
band_reads({"ch": "20,162", "en5": "20,162", "times": "20,162"})
f.solution_bands = lambda img, words: called.append(1) or [(0, 0, 400, 40)]
for heading, want in (("Solution to Puzzle No 21X162", ([20162], [1])),
                      ("Solution to Puzzle No 20,162", ([20162], []))):
    called.clear()
    f.leaf_lines = lambda path, leaves, h=heading: {23: [line("THE TIMES CROSSWORD NO 20,163", y=100), line(h, y=900)]}
    got = f._scan(td)
    check(f"a Times text leaf reading {heading!r} under its title: the band re-read only when the text has no heading",
          want, ([s["number"] for s in got["solutions"]], called))
# A leaf whose text holds no word of its solution heading and whose solution
# grid grids_on misses (1986-08-12) places no band: the strip under its
# title, down the page, is read instead. The mirrors: no title box reads no
# strip; a band that reads the heading is not followed by the strip.
def strip_reads(bands, boxes, heading_in):
    read = []
    f.solution_bands = lambda img, words: bands
    def words(img, band, which, path):
        read.append(band)
        return ([(band[0] + 10, band[1] + 300, band[0] + 60, band[1] + 320, "Solution"),
                 (band[0] + 70, band[1] + 300, band[0] + 90, band[1] + 320, "to"),
                 (band[0] + 100, band[1] + 300, band[0] + 150, band[1] + 320, "Puzzle"),
                 (band[0] + 160, band[1] + 300, band[0] + 180, band[1] + 320, "No"),
                 (band[0] + 190, band[1] + 300, band[0] + 260, band[1] + 320, "20,162")]
                if band == heading_in else [])
    f.band_words = words
    return [n for n, _ in f.band_solutions(page_img, [20163], [], "strip_test", boxes)], sorted(set(read))
strip = (26, 90, 139, 600)  # 40 and 900 px at SCAN_WIDTH, on a 400px page
check("no band from text or grid: the strip under the title is read", ([20162], [strip]),
      strip_reads([], [(30, 50, 300, 90)], strip))
check("(mirror) a band that reads nothing, then the strip", ([20162], [(0, 0, 400, 40), strip]),
      strip_reads([(0, 0, 400, 40)], [(30, 50, 300, 90)], strip))
check("(mirror) no title box, no strip", ([], []), strip_reads([], [], strip))
check("(mirror) a band that reads the heading: no strip", ([20162], [(0, 0, 400, 40)]),
      strip_reads([(0, 0, 400, 40)], [(30, 50, 300, 90)], (0, 0, 400, 40)))
f.band_words, f.solution_bands, f.leaf_lines = saved_bw, saved_sb, saved_ll
# A reader timing out on a whole Gale page (tesseract, 300s, Gale
# 1987-08-06) reads nothing; the others' title still stands.
import subprocess
saved_bw = f.band_words
def timed_out(img, band, which, path):
    if which == "times":
        raise subprocess.TimeoutExpired("tesseract", 300)
    return [(10, 10, 300, 40, "The TimesCrosswordPuzzleNo17,428")]
f.band_words = timed_out
check("a reader's timeout on a whole page reads as nothing, not a failed scan", [(17428, ["ch", "en5"])],
      [(n, r) for n, _, _, r in f.ocr_headings(Image.new("RGB", (400, 600), "black"), f.GALE, "timeout_test")[0]])
f.band_words = saved_bw
check("a band with no height reads as no words, not a crash", [],
      f.band_words(page_img, band, "times", Path(os.environ["TMP"]) / "band.json"))
check("an image with no width reads as no words", [], ocr_clues.read_words(Image.new("RGB", (0, 40)), "ch"))
check("a sliver RapidOCR would scale to no pixels reads as no words, not ResizeImgError", [],
      ocr_clues.read_words(Image.new("RGB", (1800, 12), "black"), "ch"))
check("a thin band it can still scale is read", False, ocr_clues.too_thin(1800 * 2, 20 * 2, "ch"))

# The desktop not answering: the crop is read here (None from ocr_remote),
# the reason logged, and no second attempt until RETRY has passed.
import contextlib, io, time
import ocr_remote
os.environ["OCR_REMOTE"] = "nobody@127.0.0.1"
ocr_remote.SSH = ocr_remote.SSH + ["-p", "1"]
ocr_remote.versions = lambda: {}
err = io.StringIO()
with contextlib.redirect_stderr(err):
    t = time.monotonic()
    first = ocr_remote.words(page_img, "ch")
    second = ocr_remote.words(page_img, "ch")
    took = time.monotonic() - t
check("a desktop that is off: read here, the reason logged, not retried at once, no hang",
      (None, None, True, True), (first, second, "unavailable (nobody@127.0.0.1: " in err.getvalue(), took < 30))
os.environ.pop("OCR_REMOTE")

# A Sunday edition filed under "The Times" is refused: the daily prints none.
sunday = {"date": "1994-08-14", "puzzles": [{"number": 19620}]}
n, day, why = f.filed_number(Path("x/NewsUK1994UKEnglish/ed"), sunday, {"number": 19620, "leaf": 1})
check("a Sunday Times-item puzzle is refused, not filed on a Sunday", (None, True), (n, bool(why and "Sunday" in why)))
n, day, why = f.filed_number(Path("x/GaleTimes1994UKEnglish/1994-08-14"), sunday, {"number": 19620, "leaf": 1})
check("and so is one off a Gale page", (None, True), (n, bool(why and "Sunday" in why)))

# A Gale page's headings (ocr_headings): "Crossword" misread is read as the
# word, and a title fewer than half the readers read stands when the page's
# solution heading names the day before's puzzle (1987-01-08, -09).
from PIL import Image
gale_img = Image.new("L", (400, 400), 255)
gale_img.putpixel((10, 10), 0)
def gale_words(by_reader):
    saved_bw = f.band_words
    f.band_words = lambda img, box, which, path: by_reader.get(which, [])
    try:
        return f.ocr_headings(gale_img, f.GALE, "test")
    finally:
        f.band_words = saved_bw
title = lambda text: [(10 + 60 * k, 10, 60 + 60 * k, 30, w) for k, w in enumerate(text.split())]
sol = [(10, 300, 40, 320, "Solution"), (45, 300, 60, 320, "to"), (65, 300, 90, 320, "Puzzle"),
       (95, 300, 110, 320, "No"), (115, 300, 160, 320, "17,247")]
rs = list(f.READERS)
got = gale_words({rs[0]: title("The Times CresswordPuzzle No 17,248") + sol,
                  rs[1]: title("The Times Cressword Puzzle No 17,248") + sol})
check("a title read 'Cressword' is the title", ([17248], [17247]), ([t[0] for t in got[0]], [s_[0] for s_ in got[1]]))
got = gale_words({rs[2]: title("The Times Crossword Puzzle NO 17,249"),
                  rs[0]: [(*w[:4], "17,248" if w[4] == "17,247" else w[4]) for w in sol],
                  rs[1]: [(*w[:4], "17,248" if w[4] == "17,247" else w[4]) for w in sol]})
check("a title one reader read stands after the solution heading the others read", [17249], [t[0] for t in got[0]])
got = gale_words({rs[2]: title("The Times Crossword Puzzle No 17,300")})
check("one reader's title with no solution heading to back it is not", [], got[0])
ran_on = [(10, 300, 30, 320, "27"), (35, 300, 80, 320, "Order"), (85, 300, 120, 320, "con-")]
got = gale_words({r: ran_on + [(w[0] + 140, w[1], w[2] + 140, w[3], "Solotion" if w[4] == "Solution" else w[4])
                               for w in sol] for r in rs[:2]})
check("a solution heading read on the end of a clue line, 'Solotion', is read once a reader", ([17247], []),
      ([s_[0] for s_ in got[1]], got[0]))
# A solution heading is read again in its own band: a whole-page read misses
# its small type (two of three readers read nothing there, Gale's 1987-01-10)
# or splits it at a wide gap ("Solution tn Puzzle" ... "No 17,245", 1987-01-06).
def gale_bands(page, band):
    saved_bw = f.band_words
    def words(img, box, which, path):
        if "_page." in str(path):
            return page.get(which, [])
        return [w for w in band.get(which, []) if box[0] <= w[0] and w[2] <= box[2] and box[1] <= w[1] and w[3] <= box[3]]
    f.band_words = words
    try:
        return f.ocr_headings(wide_img, f.GALE, "test")
    finally:
        f.band_words = saved_bw
wide_img = Image.new("L", (f.SCAN_WIDTH, 600), 255)
wide_img.putpixel((10, 10), 0)
gapped = [(40, 300, 110, 320, "Solution"), (115, 300, 135, 320, "tn"), (140, 300, 190, 320, "Puzzle"),
          (260, 300, 280, 320, "No"), (285, 300, 340, 320, "17,245")]
got = gale_bands({rs[2]: gapped[:1]}, {r: gapped for r in rs})
check("a heading one reader saw on the page and every reader read in its band, gapped and 'tn', stands",
      [17245], [s_[0] for s_ in got[1]])
got = gale_bands({rs[2]: gapped[:1]}, {rs[2]: gapped})
check("(mirror) one reader in its band is not enough", [], got[1])
# A band is read against the page's titles (Gale 1988-06-28: "Puzzie" under
# 17,707 read by every reader): the loose heading stands for title-1 only.
puzzie = [(40, 300, 110, 320, "Solution"), (115, 300, 135, 320, "to"), (140, 300, 190, 320, "Puzzie"),
          (195, 300, 215, 320, "No"), (220, 300, 275, 320, "17,706")]
titled = {r: title("The Times Crossword Puzzle No 17,707") + puzzie[:1] for r in rs}
got = gale_bands(titled, {r: puzzie for r in rs})
check("a loose heading in its band stands as the page's title-1", [17706], [s_[0] for s_ in got[1]])
got = gale_bands({r: puzzie[:1] for r in rs}, {r: puzzie for r in rs})
check("(mirror) with no title read on the page it is not", [], got[1])
got = gale_bands({r: title("The Times Crossword Puzzle No 17,720") + puzzie[:1] for r in rs}, {r: puzzie for r in rs})
check("(mirror) nor under a title it is no lag before", [], got[1])
# A page no title has half the readers on (Gale 1989-06-20: "PUZZLE NO
# 18,013" a line under "THE TIMES CROSSWORD") reads its bands against the
# titles ocr_titles finds round its grids, given the edition's day.
solation = [(40, 300, 110, 320, "Solation"), (115, 300, 135, 320, "to"), (140, 300, 190, 320, "Puzzle"),
            (195, 300, 215, 320, "No"), (220, 300, 275, 320, "18,012")]
saved_t = f.ocr_titles
f.ocr_titles = lambda img, paper, day, key, far=False: [(18013, (0, 0, 1, 1), None, ["ch", "en5"])]
def gale_day(day):
    saved_bw = f.band_words
    f.band_words = lambda img, box, which, path: [(40, 300, 110, 320, "Solution")] if "_page." in str(path) else solation
    try:
        return f.ocr_headings(wide_img, f.GALE, "test", day)
    finally:
        f.band_words = saved_bw
got = gale_day(D("1989-06-20"))
check("a heading read against the titles round the grid where the page voted none", ([18013], [18012]),
      ([t[0] for t in got[0]], [s_[0] for s_ in got[1]]))
got = gale_day(None)
check("(mirror) with no day, no grid titles: only an exact heading stands", ([], []), got)
f.ocr_titles = saved_t
notice = title("The solution of Saturday's Prize Puzzle No 17,250 will appear next Saturday")
notice = [(w[0], 300, w[2], 320, w[4]) for w in notice]
got = gale_bands({r: notice for r in rs}, {r: notice for r in rs})
check("a notice that the solution will appear is no heading (1987-01-12)", [], got[1])
# A solution grid no reader's page pass read a heading over (1987-01-17):
# its band is over the grid's top, and the heading read there stands.
from PIL import ImageDraw
sol_page = Image.new("L", (f.SCAN_WIDTH, 1400), 255)
sd = ImageDraw.Draw(sol_page)
gx, gy, cell = 600, 700, 22
for k in range(16):
    sd.line([(gx + k * cell, gy), (gx + k * cell, gy + 15 * cell)], fill=0, width=2)
    sd.line([(gx, gy + k * cell), (gx + 15 * cell, gy + k * cell)], fill=0, width=2)
for r in range(15):
    for c in range(15):
        if (r * 7 + c * 3) % 4 == 0:
            sd.rectangle([gx + c * cell, gy + r * cell, gx + (c + 1) * cell, gy + (r + 1) * cell], fill=0)
bands = f.solution_bands(sol_page, [])
check("a band over a solution grid's top, though no reader read a 'Solution' word", True,
      len(bands) == 1 and bands[0][1] < gy - 40 and gy <= bands[0][3] <= gy + 10 and bands[0][0] <= gx)
check("and one heading's word and grid make one band", 1,
      len(f.solution_bands(sol_page, [(gx + 10, gy - 40, gx + 90, gy - 15, "Solution")])))
# A solution grid whose frame the scan broke is boxed whole (1987-01-15).
sd.rectangle([gx + 5 * cell - 1, gy - 2, gx + 5 * cell, gy + 15 * cell + 2], fill=255)
sd.rectangle([gx - 2, gy + 7 * cell - 1, gx + 15 * cell + 2, gy + 7 * cell], fill=255)
crop = sol_page.crop((gx - 60, gy - 20, gx + 15 * cell + 60, gy + 15 * cell + 60))
whole = f.ink_box(crop, f.SOLUTION_CLOSE)
check("a solution grid with its frame broken is boxed whole once the gap is closed", True,
      whole is not None and whole[2] - whole[0] >= 15 * cell - 4 and whole[3] - whole[1] >= 15 * cell - 4)
part = f.ink_box(crop)
check("(mirror) unclosed, the largest ink is a part of it", True, part[2] - part[0] < 15 * cell - 4 or part[3] - part[1] < 15 * cell - 4)

# The 1930 Times (pub_times, one item an issue): its paper, its 1-3 digit
# numbers held to the date, four clue columns, and counts from the grid.
d1930 = Path("x/per_times_the-times_1930-03-04_45452/per_times_the-times_1930-03-04_45452")
check("a pub_times issue is the 1930 Times, read 4x smaller, filed as times",
      ("times1930", 4, "times"), (f.paper_of(d1930).key, f.paper_of(d1930).shrink, f.paper_of(d1930).series))
check("a run of the Times reads the 1930 issues too", True, f.TIMES_1930 in f.TIMES.also)
import datetime as _dt
check("1930 numbers run six a week from No 1 on 1 Feb, none on Good Friday",
      [1, 27, 54, 94, 129, 209],
      [f.times1930_expected_number(_dt.date.fromisoformat(x)) for x in
       ("1930-02-01", "1930-03-04", "1930-04-04", "1930-05-22", "1930-07-02", "1930-10-03")])
t30, s30 = f.times1930_headings([line("LT THE TIMES CROSSWORD PUZZLE No. 129"), line("SOLUTION OF PUZZLE No. 126.", y=900)])
check("1930 title and solution heading read", ([129], [126]), ([n for n, _, _ in t30], [n for n, _ in s30]))
t30, _ = f.times1930_headings([line("THE TIMES CROSSWORD PUZZLE No."), line("SOLUTION OF PUZZLE No. 53", y=900)])
check("a 1930 title whose number was not read is the one after the page's solution", [54], [n for n, _, _ in t30])
t30 = [f.times1930_headings([line(t)])[0] for t in (
    "eat htheketesigant Sacx| THE TIMES CROSSWORD PUZZLE No. 40", "THE TIMES CROSS WORD PUZZLE No. 71",
    "THE TIMES CROSSWORD PUZ ZLE No. 12", "THE TIMES CROSSWORD PUBZLE NO. 4")]
check("1930 titles behind the next column's words, split or misread (1930-03-19, 04-25, 02-14, 02-05)",
      [40, 71, 12, 4], [h[0][0] for h in t30])
check("a 1930 title behind the next column's words is boxed from TIMES on", 100 + 10 * 25 + 8 * 4,
      t30[0][0][1][0])
t30 = f.times1930_headings([line("a THE TIMES ROBSWORD PUZZLE No. 55")])[0]
check("after TIMES a misread CROSSWORD is still the title (1930-04-05)", [55], [n for n, _, _ in t30])
t30, _ = f.times1930_headings([line("SIDCUP events' four, 7 a THE TIM ES CROSS WORD PUZZLE No."),
                                line("SOLUTION OF PUZZLE No. 51", y=900)])
check("a numberless title behind run-on words and a split TIMES takes the solution's next (1930-04-02)",
      [52], [n for n, _, _ in t30])
check("(mirror) TIMES and PUZZLE with words between them are no title", ([], []),
      f.times1930_headings([line("THE TIMES of the many puzzle solvers No. 12")]))
check("the note under the clues is no title", ([], []),
      f.times1930_headings([line("The fifty-fifth crossword puzzle in this series, together with the solution of puzzle No. 54,")]))
found30 = {"date": "1930-10-03", "puzzles": [{"number": 200, "leaf": 4}], "solutions": [{"number": 208, "leaf": 4}]}
f.held_dates, f.same_scan, f.page_url = (lambda series: {}), (lambda *a: None), (lambda *a: "")
check("a misread 1930 number (200 for 209) is the page's solution's next",
      (209, None), f.filed_number(d1930, found30, {"number": 200, "leaf": 4})[::2])
found30["solutions"] = []
check("with no solution heading to say so it is refused",
      (None, True), (lambda r: (r[0], bool(r[2])))(f.filed_number(d1930, found30, {"number": 200, "leaf": 4})))
ft83 = {"date": "1983-02-18", "puzzles": [{"number": 5401, "leaf": 1}], "solutions": []}
check("an FT title read 5,401 on 1983-02-18 files as 5,101, not refused as misdated",
      (5101, None), f.filed_number(Path("x/FinancialTimes1983UKEnglish/1983-02-18_29003"), ft83,
                                   {"number": 5401, "leaf": 1})[::2])
# Four columns under the grid: ACROSS down the first two over the DOWN
# heading, DOWN under it and on down the third and fourth, which stop at the
# previous solution's heading.
g30 = (100, 100, 900, 900)
rows = [line("ACROSS", 250, 920), line("1 Cornstalks, or in-", 100, 950), line("versely blemishes.", 120, 970),
        line("28 Louder.", 300, 950), line("29 Broaden.", 300, 970),
        line("DOWN", 260, 1000), line("2 Have a shot", 100, 1030), line("9 This yawns", 300, 1030),
        line("22 The desert's", 500, 950), line("32 Split this aim", 700, 950),
        line("SOLUTION OF PUZZLE NO. 26", 520, 1100), line("STEPPES COUNSEL", 520, 1130)]
gut = [300 - 5, 500 - 5, 700 - 5]
check("1930 columns read in the lists' order",
      "ACROSS\n1 Cornstalks, or in-\nversely blemishes.\n28 Louder.\n29 Broaden.\nDOWN\n2 Have a shot\n"
      "9 This yawns\n22 The desert's\n32 Split this aim",
      f.column_text(f.columns_of_four(rows, g30, gut, f.down_at(rows, g30, gut))))
grid30 = ["...#", "....", "#...", "...."]
check("1930 clues take their counts from the grid; a line that is no clue's number carries on",
      "ACROSS\n1 Toe (3)\n4 Dose of a\nlong cure (4)\n6 Ask (3)\n7 Hop (4)\nDOWN\n1 Lone\nis far (2)\n2 Ox (4)\n"
      "3 Up (4)\n5 Go (3)",
      f.counted("ACROSS\n1 Toe\n4 Dose of a\nlong cure\n6 Ask\n7 Hop\nDOWN\n1 Lone\nis far\n2 Ox\n3 Up\n5 Go", grid30))
# A lost number runs one clue into the next, and the grid's count fits
# whatever text it is given (No 129, 1930-07-02: "+ Nitrate (anag.)", 4d's
# number read "+", filed as 3d). The list must name the grid's lights in
# order, or the clue next to the break is dropped.
check("a clue followed by a later light's than the next (one skipped) is dropped, the skipped light left blank",
      "ACROSS\n6 Ask (3)\n7 Hop (4)",
      f.counted("ACROSS\n1 Toe\nin Dickens\n+ Dose of a cure\n6 Ask\n7 Hop", grid30))
check("a clue ending its list before the list's last light is dropped",
      "ACROSS\n1 Toe (3)\n4 Dose (4)\nDOWN\n1 Lone (2)\n2 Ox (4)",
      f.counted("ACROSS\n1 Toe\n4 Dose\n6 Ask\nhop\nDOWN\n1 Lone\n2 Ox\n3 Up", grid30))
check("a number at or before the last clue's drops the clue it ran into",
      "ACROSS\n1 Toe (3)\n6 Ask (3)\n7 Hop (4)",
      f.counted("ACROSS\n1 Toe\n4 Dose\n1 Ask again\n6 Ask\n7 Hop", grid30))
check("a guessed number the print then names drops the guess and the clue it was cut from",
      "ACROSS\n1 Toe (3)\n6 Ask (3)\n7 Hop (4)",
      f.counted("ACROSS\n1 Toe\n4 Dose of a cure.\nThat is London.\n6 Ask\n7 Hop", grid30))
check("a break after guessed numbers drops them back to the last number read (No 54: 36a took 37a's words, the guesses ran one light behind)",
      "ACROSS\n7 Hop (4)",
      f.counted("ACROSS\n1 Toe\nthe offence.\nAsk again.\n7 Hop", grid30))
check("a number read with a speck holding the next light's starts its clue (\"151\" for 15)",
      "ACROSS\n1 Toe. (3)\n4 Dose (4)\n6 Ask (3)\n7 Hop (4)",
      f.counted("ACROSS\n1 Toe.\n141 Dose\n6 Ask\n7 Hop", grid30))
check("a capital after a clue's full stop is the next light's clue, its number lost; the number run into its word",
      "ACROSS\n1 Toe. (3)\n4 Dose of a\nLondon cure. (4)\n6 Ask (3)\n7 Hop (4)",
      f.counted("ACROSS\n1 Toe.\nDose of a\nLondon cure.\n6.Ask\n7Hop", grid30))
check("1930 words RapidOCR ran together put apart, specks between words dropped",
      "These people are flat and in \u201cThe Tempest\u201d Hornblower",
      f.spaced("Thesepeopleare flat.and in\u201cThe Tempest\u201d Hornblower"))
check("1930 spacing leaves a known word, a word broken over a line end, and splits a run after its clue number",
      "41 Neat gem (anag.)\n25 Holds an esta-\nblished ap-\npearance",
      f.spaced("41 Neat gem (anag.)\n25Holdsan esta-\nblished ap-\npearance"))

import datetime
tue = datetime.date(1996, 6, 11)
check("a stray lower number does not date the edition's own puzzle later (Guardian 1996-06-11 read No 20673 beside No 20676)",
      tue, f.issue_day(tue, 20676, [20676, 20673]))
check("each number of an unbroken run above the edition's own is one issue later, skipping Sunday",
      datetime.date(1996, 6, 17), f.issue_day(datetime.date(1996, 6, 15), 20681, [20680, 20681]))
check("a number above a gap is not a later issue",
      tue, f.issue_day(tue, 20679, [20676, 20677, 20679]))

print(f"FAILS {fails}")
EOF
)
# Gale's 1987-01-07 solution grid (No 17,246, at the page's scale): clean,
# but its rules lie unevenly, its rows shear and its clue numbers run into
# the letters, and every light was refused but 2 of 30. Read now, most
# lights are accepted and each is the answer a person reads off the scan.
# Skipped where the OCR engine is not installed (CI's test job).
ocr=$(cd "$REPO/tools" && TMP="$tmp" python3 - <<'EOF'
import os
from pathlib import Path
from PIL import Image
import trove_solution_ocr as tso
if tso.available():
    print("skip")
    raise SystemExit
hand = ["BEDOFROSES#AGED", "A#O#I#N#A#O#R#I", "BROWNIE#REPRESS", "E#N#D#R#L#E#E#P", "LIEGELORD#RANGE",
        "##S#R#U#O#A###R", "EMBUS#SOMETIMES", "N#I#K#####I#U#A", "WITNESSED#OFFAL", "R###E#C#U#N#F##",
        "EQUIP#ASSESSING", "A#N#E#N#T#R#N#O", "TUTORED#BLOOMER", "H#I#S#A#I#O#A#G", "EVEN#BLANCMANGE"]
grid = ["".join("#" if ch == "#" else "." for ch in row) for row in hand]
small = Image.open("fixtures/archive-org-grids/gale-times-17246-solution.png")
path = Path(os.environ["TMP"]) / "sol.png"
small.resize((small.width * 3, small.height * 3), Image.BICUBIC).save(path)
got, stats = tso.read_answers(path, grid, tight=True)
lts = tso.lights(grid)
wrong = {k: w for k, w in got.items() if w != "".join(hand[r][c] for r, c in lts[k])}
print("ok" if len(got) >= 15 and not wrong and stats["blocks"] == 1 else (len(got), wrong, stats))
EOF
)
if [ "$ocr" = skip ]; then
  echo "skip solution grid letters: rapidocr-onnxruntime not installed"
elif [ "$ocr" = ok ]; then
  echo "ok   Gale 1987-01-07's solution grid: 15+ of 30 lights read (was 2), each as a person reads it"
else
  echo "FAIL Gale 1987-01-07's solution grid: $ocr"
  out="$out
FAILS 1"
fi
echo "$out"
grep -q '^FAILS 0$' <<<"$out" && ! grep -q '^FAILS [1-9]' <<<"$out" || { echo "test_file_archive_org_puzzles: failed"; exit 1; }
echo "test_file_archive_org_puzzles: all passed"
