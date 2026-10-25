#!/usr/bin/env python3
# Does tools/file_archive_org_puzzles.py find the Times cryptic's title and
# not its neighbours', read the clue columns in order, keep only the clues
# both readings agree on, and match a Canberra reprint only when it is one?
#
#     python3 tools/test_file_archive_org_puzzles.py
#
# Pure functions on made-up words and puzzles, nothing written outside a
# temp dir; one solution grid fixture is read by RapidOCR where installed.
import atexit
import contextlib
import io
import os
os.environ.setdefault("CT_VLM_BLIP_SECONDS", "0")  # no link-blip waits on a fake unreachable VLM
import shutil
import sys
import tempfile
import types
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
os.chdir(TOOLS)
sys.path.insert(0, str(TOOLS))
os.environ["TMP"] = tempfile.mkdtemp()
atexit.register(shutil.rmtree, os.environ["TMP"], True)

_buf = io.StringIO()
_stdout, sys.stdout = sys.stdout, _buf
import json, os
from pathlib import Path
import file_archive_org_puzzles as f
f.HELD_SERIES_CACHE = None  # no on-disk snapshot leaking in from ~/.cache; the snapshot case sets its own
import ocr_clues
import clue_repair

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

# A blank light no reading has any text for is never asked, so the picks for the page's other
# blanks cannot make it whole: skipped, unless the window is poor (another is read) or only
# one clue is blank.
_t = {"vlm": "ACROSS\n1 Old fashioned dance (5)\n3 Wet weather in town (4)\nDOWN\n4 Quiet place to rest (6)\n"}
check("two blanks, one no reading has: no pick asked", True, f.unpickable(_t, {"2-down": "x", "1-across": "y"}, 30))
check("both blanks have readings: picked", False, f.unpickable(_t, {"4-down": "x", "1-across": "y"}, 30))
check("one blank no reading has: nothing was asked anyway", False, f.unpickable(_t, {"2-down": "x"}, 30))
# A bare light the readers agree on is laid before the pick; one with a lost space after a stop is still asked.
check("a sentence end glued to the next word is left to the pick", True,
      bool(f.SENTENCE_GLUED.search("Sign of what happened.A small quantity")))
check("a clue with its spaces is laid early", False,
      bool(f.SENTENCE_GLUED.search("Sign of what happened. A small quantity")))
check("a stop inside an abbreviation is not a glue", False, bool(f.SENTENCE_GLUED.search("Exam, e.g. in Paris")))

check("disagreeing: none named in the verdict", set(), f.disagreeing({}))
check("disagreeing: the lights the verdict names", {"13-across", "8-down"},
      f.disagreeing({"imageDisagrees": "13-across: the enumeration reads as ['5,8,2'], the grid holds 10 letters; 8-down: x"}))
check("disagreeing: a disagreement naming no light is None (every column)", None,
      f.disagreeing({"imageDisagrees": "the grids differ"}))
check("disagreeing: a clue that lost its number names the next light", {"7-down"},
      f.disagreeing({"imageDisagrees": "down clue [] names no light the grid numbers after 6 (the next is 7-down)"}))


def _entry(n, d, text, enum="4", length=4, group=None):
    return {"number": n, "direction": d, "length": length,
            "clue": {"text": text, "enumeration": enum}, **({"group": group} if group else {})}


_mine = {"grid": ["g"], "entries": [_entry(1, "across", "ocr one"), _entry(2, "down", "ocr two"),
                                    _entry(3, "down", ""), _entry(4, "down", "ocr four", enum=None)]}
_theirs = {"grid": ["g"], "entries": [_entry(1, "across", "vlm one"), _entry(2, "down", "vlm two"),
                                      _entry(3, "down", "vlm three"), _entry(4, "down", "vlm four")]}
_v, _p = f.merged_read({"blank": {"3-down": "no reading"}}, _mine, {"agreed": 4}, _theirs, {"2-down"})
check("merged_read: asked, blank and countless lights come from the VLM, the rest stay",
      ["ocr one", "vlm two", "vlm three", "vlm four"],
      [e["clue"]["text"] for e in _p["entries"]])
check("merged_read: the blank taken from the VLM is no longer blank", None, _v.get("blank"))
check("merged_read: names what it took", ["2-down", "3-down", "4-down"], _v["vlmMerged"])
_v, _p = f.merged_read({}, _mine, {"agreed": 4}, {"grid": ["g"], "entries": _theirs["entries"][:2]}, {"2-down"})
check("merged_read: another set of lights: the VLM pass stands", 2, len(_p["entries"]))
check("a poor window is read again, picks and all", False, f.unpickable(_t, {"2-down": "x", "5-down": "y", "6-down": "z", "7-down": "w", "8-down": "v"}, 30))

# The readers' own list for a new puzzle that repeats a held puzzle's clues is refused as a copy
# at the write, so the VLM is not asked about it (held_copy).
import fetch_puzzle as _fp
from clue_index import ClueIndex as _CI
from pathlib import Path as _P
_idx = _CI()
_clues = [f"Clue number {i} for the held book puzzle (5)" for i in range(10)]
_ent = lambda cs: [{"clue": {"text": c}} for c in cs]
_idx.add("book-1", {"entries": _ent(_clues)})
_old = (_fp.clue_index, f.held_dates)
_fp.clue_index = lambda: _idx
f.held_dates = lambda series: set()
try:
    _d = _P("GaleTimes2013UKEnglish/2013-11-23")
    check("a list that is a held book's: a copy", "book-1", f.held_copy(_d, {"number": 25640}, {"id": "times-25640", "entries": _ent(_clues)}))
    check("one that is not: asked", None, f.held_copy(_d, {"number": 25640}, {"id": "times-25640", "entries": _ent(_clues[:3] + [f"Other {i} clue (4)" for i in range(7)])}))
    check("a blank-heavy list: asked", None, f.held_copy(_d, {"number": 25640}, {"id": "times-25640", "entries": _ent(_clues[:7] + [""] * 23)}))
    _ten = _clues + [f"Clue number {i} for the held book puzzle (5)" for i in range(10, 20)]
    _idx.add("book-2", {"entries": _ent(_ten)})
    check("a few blank, the printed clues are a held book's: a copy",
          "book-2", f.held_copy(_d, {"number": 25640}, {"id": "times-25640", "entries": _ent(_ten[:17] + [""] * 3)}))
    check("a few blank, the printed clues half another puzzle's: asked", None,
          f.held_copy(_d, {"number": 25640}, {"id": "times-25640", "entries": _ent(_ten[:10] + [f"Other {i} clue (4)" for i in range(7)] + [""] * 3)}))
    f.held_dates = lambda series: {25640}
    check("a number already held: asked as before", None, f.held_copy(_d, {"number": 25640}, {"id": "times-25640", "entries": _ent(_clues)}))
finally:
    _fp.clue_index, f.held_dates = _old

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
# A 2004 Monday's Saturday prize solution, "Solution to Crossword 22,845" (no "Prize" word): read clean
# as one of the prize numbers only, never a misread or another number.
check("a Monday's prize heading with no Prize word", [22845],
      [n for n, _ in f.prize_headings([line("Solution to Crossword 22,845")], {22845})])
check("... not a number off the prize's", [], [n for n, _ in f.prize_headings([line("Solution to Crossword 22,846")], {22845})])
check("... not a misread one", [], [n for n, _ in f.prize_headings([line("Solution to Crossword 22,84S")], {22845})])
# A host's misread "Solution" words (solutions_only, host_heading_lines): the 1945-46 Gale Times's
# small-type "SoL.UTION oF PvzzLe", a word run on from the clue column, a glued "SolutiontoCrossword",
# "The Solution of" over "Puzzle No 13,313" (1973); not "evolution" or "resolution".
check("misread Solution words are solution_like", [True] * 5 + [False] * 4,
      [f.solution_like(w) for w in ("SoL.UTION", "SoLuTinN", "sSolution", "SLuTIoN", "SolutiontoCrossword",
                                    "evolution", "resolution", "Solitaire", "Saturday's")])
check("... and start a solution band", "Solution oF", f.marked_solution("SoLuTinN oF"))


def host_reads(lines, near):
    lines = f.host_heading_lines(lines)
    lines += [ln[k:] for ln in lines for k in range(1, len(ln))
              if f.HEADING_START.match(ln[k][4]) or f.solution_like(ln[k][4])]
    return sorted({n for n, _ in f.GALE.headings(lines, list(range(near - 300, near + 300)))[1]})


check("a misread host heading reads", [4931], host_reads([line("SoL.UTION oF PvzzLe No. 4,931")], 4931))
check("... run on from the clue column", [13418],
      host_reads([line("26 Responsehough fruitful sSolution of Puzle No 13.418")], 13418))
check("... glued to its connective", [21584], host_reads([line("SolutiontoCrossword 21,584 Imaginative.no")], 21584))
check("... 'The Solution of' over its number", [13313],
      host_reads([line("The Solution of"), line("Puzzle No 13,313", y=120)], 13313))
check("... its number a line under (1980-08-07)", [15294],
      host_reads([line("k. Solution of Puzzle No"), line("15,294", y=120)], 15294))
check("... three RapidOCR phrases, a clue beside (1973-02-24)", [13313],
      host_reads([[(634, 4769, 849, 4820, "The Solution of")], [(667, 4820, 818, 4868, "Puzzle No.")],
                  [(705, 4875, 791, 4910, "13,313")], [(224, 4787, 560, 4835, "Wildly with a bad road (9).")]], 13313))
check("... its dot leader glued to its number, the next column run on (1962-07-28)", [10052],
      host_reads([line("Does the little pet stir ? (5). SE SOLUTION OF PUZZLE No. 10,052.... Era")], 10053))
check("... a speck before its number (1964-02-12, 1965-02-18), a dash and dots glued on (1963-05-27)",
      [[10530], [10846], [10308]],
      [host_reads([line("Solution of Puzzle No. 1 10,530 Unriva")], 10531),
       host_reads([line("Solution OF.PUZZLE No..1 10,846")], 10847),
       host_reads([line("Solution OF PUZZLE.No.-10,308..- Trustees' Sale")], 10309)])
check("... its 'Puzzt' not read as a number (u 0, z 2, t 1: 10221) before the number it prints (1964-02-12)",
      [10530], host_reads([line("SoL.uTioN OF Puzzt No. 10,530 Unrive")], 10531))
check("... a mark glued between 'Crossword' and its number (2001-03-17)", [[21677], [21677]],
      [host_reads([line("Solution to Crossword.21,677")], 21678), host_reads([line("Solution to Crossword. 21,677")], 21678)])
check("... the Monday's 'Competition Solution' of the Saturday prize (2006-11-27), not prose's 'competition'",
      [[23450], [], []], [host_reads([line("callywag Competition Solution 23,450")], 23457),
                          host_reads([line("the competition dissolution 23 times")], 23457),
                          # one reader's "23, 530" of 23,539 (2007-03-12): read clean or not at all
                          host_reads([line("Competition Solution 23, 530")], 23546)])
_day = [line("Solution to yesterday's", x=1480, y=3970) + line("Solution to last Saturday's", x=1714, y=3970),
        line("Crossword 22,204", x=1480, y=3990) + line("Crossword 22,199", x=1714, y=3990)]
check("'Solution to yesterday's' and 'Solution to last Saturday's' side by side over 'Crossword 22,204' and "
      "'Crossword 22,199' (2002-11-23): each the number under its own words", (22204, 22199),
      tuple(n for n, _ in f.day_headings(_day, _day, set(range(22190, 22210)))))
_day2 = [line("Solution to yesterday's", x=1520, y=3986), line("Crossword 22,204", x=1520, y=4000)]
check("... its 'Crossword' line opening above the heading's foot (the apostrophe's tall box, 2002-11-23)", [22204],
      [n for n, _ in f.day_headings(_day2, _day2, {22204})])
_prose = [line("a solution to yesterday's crisis", y=3970), line("Crossword 22,204", y=3990)]
check("... not prose's lowercase 'solution', nor 2012's 'The Solution to yesterday's' over a clue, no number",
      [[], []], [f.day_headings(_prose, _prose, {22204}),
                 f.day_headings([line("he Solution to yesterday's this with husband away (9")], [], {25116})])
check("... a title line alone is none", [], host_reads([line("Puzzle No 13,313")], 13313))
check("... nor an article's 'solution' over one", [],
      host_reads([line("a solution to the crisis"), line("Puzzle No 13,313", y=120)], 13313))
# HOST_RESCAN: a Gale host's solutions-only read made before REREAD_HOST_HEADINGS is due once more.
check("a Gale host with no solutions-only read since the fix is due", True, f.host_rescan_due(f.GALE, {"scan": {}}))
check("... not once read since", False, f.host_rescan_due(f.GALE, {"solOnly": {"at": "2099-01-01T00:00:00+00:00"}}))
check("... nor an archive.org Times edition", False, f.host_rescan_due(f.TIMES, {"scan": {}}))
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
# The Gale Times from 2000-03-13: "NO 21,362" on its own row under the title.
check("a bare NO row joins the THE TIMES CROSSWORD row over it", [21362],
      [n for n, _, _ in f.times_headings([line("THE TIMES CROSSWORD", 277, 3051), line("NO 21,362", 274, 3070)])[0]])
check("the words after CROSSWORD on the title's row are left out of the join", [21362],
      [n for n, _, _ in f.times_headings([line("THE TIMES Crossword wrong word to describe how", 274, 3046),
                                          line("NO 21,362", 274, 3068)])[0]])
check("a bare NO row far under the title does not join it", [],
      f.times_headings([line("THE TIMES CROSSWORD", 277, 3051), line("NO 21,362", 274, 3300)])[0])
check("a bare NO row under another line does not join it", [],
      f.times_headings([line("Schumacher cedes them all", 277, 3051), line("NO 21,362", 274, 3070)])[0])
# A scan cached by older heading code is made again, and a title it finds
# that no verdict covers makes the edition due.
import code_reach
reached = {d for m, d in code_reach.reach("file_archive_org_puzzles", f.SCAN_ROOTS)
           if m == "file_archive_org_puzzles"}
check("the scan key follows every name scan() reaches: the title pattern, the title OCR, the Gale page's "
      "headings and their band re-reads, the 1930 headings, the Paper method scan calls", set(),
      {"TITLE", "SOLUTION", "ocr_titles", "ocr_headings", "mend_misreads", "solution_bands", "band_solutions", "SOLUTION_BAND",
       "hint_strips", "HEADING_HINT", "PAGE_READERS", "HINT_PAD",
       "times1930_headings", "Paper.headings"} - reached)
check("and not the filing code: a change to it rescans nothing", set(), {"read_puzzle", "read_solution"} & reached)
# A band cache a killed read left empty or cut short is a miss: read again,
# rewritten whole, no temp file left.
_reads = []
_real_read_words = f.read_words
f.read_words = lambda im, which: _reads.append(which) or [(1, 2, 3, 4, "word")]
_band_dir = Path(os.environ["TMP"]) / "bands"
_band_dir.mkdir()
_band_img = Image.new("L", (50, 50), 255)
for _bad in ("", '{"box": [0, 0, 5'):
    _bad_path = _band_dir / "b.json"
    _bad_path.write_text(_bad)
    _reads.clear()
    check(f"an unreadable band cache {_bad!r} is read again", [(1 + 5, 2 + 6, 3 + 5, 4 + 6, "word")],
          f.band_words(_band_img, (5, 6, 20, 30), "ch", _bad_path))
    check("and rewritten whole", {"box": [5, 6, 20, 30], "words": [[6, 8, 8, 10, "word"]]}, json.loads(_bad_path.read_text()))
    check("with no temp file left", ["b.json"], [p.name for p in _band_dir.iterdir()])
    f.band_words(_band_img, (5, 6, 20, 30), "ch", _bad_path)
    check("a readable cache is not read again", 1, len(_reads))
f.read_words = _real_read_words
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
# Each paper's scan key covers the shared scan code and its own definition
# only: adding a paper (and listing it in the tables) or changing one moves
# that paper's key and no other, so it never re-scans the corpus; a change
# to the shared scan code moves every key.
src = Path("file_archive_org_puzzles.py").read_text()
opaque = code_reach.TRANSPORT + code_reach.SIZING
keys = f.scan_keys(opaque)
added = src.replace('''TELEGRAPH = Paper("telegraph", "telegraph", re.compile(r"(?:TheDaily|Sunday)Telegraph(19\\d\\d)UKEnglish$"),
                  "Telegraph cryptic crossword No {:,}", telegraph_expected_number, telegraph_headings, margin=15,''',
                    '''TELEGRAPH = Paper("telegraph", "telegraph", re.compile(r"(?:TheDaily|Sunday)Telegraph(19\\d\\d)UKEnglish$"),
                  "Telegraph cryptic crossword No {:,}", telegraph_expected_number, telegraph_headings, margin=16,''')
added = added.replace("FILERS = {**PAPERS, ", "NEWP = Paper('newp', 'newp', re.compile('NewP$'), "
                      "'New No {:,}', expected_number, ft_headings)\nFILERS = {**PAPERS, NEWP.key: NEWP, ")
moved = f.scan_keys(opaque, {"file_archive_org_puzzles": added})
shared = f.scan_keys(opaque, {"file_archive_org_puzzles": src.replace(
    "    if paper is TIMES and not found[\"puzzles\"]:", "    if paper is TIMES and not found[\"puzzles\"] and leaves:")})
check("adding a paper and changing another moves only the changed one's scan key; the new one gets its own",
      (added != src, {"TELEGRAPH"}, True),
      (added.count("NEWP") == 3, {k for k in keys if moved[k] != keys[k]}, "NEWP" in moved and moved["NEWP"] not in keys.values()))
check("(mirror) a change to the shared scan code moves every paper's scan key",
      set(keys), {k for k in keys if shared[k] != keys[k]})
check("a paper's scan key is its own: no two papers share one; scan_key() is the Times's",
      (len(keys), keys["TIMES"], keys["GALE_TELEGRAPH"]),
      (len(set(keys.values())), f.scan_key(), f.scan_key(f.GALE_TELEGRAPH)))
old_key = next(iter(f.CORPUS_KEYS))
f.CORPUS_KEYS[old_key] = {**f.CORPUS_KEYS[old_key], "times": f.scan_key()}  # the Times code as it stands
rk = Path(os.environ["TMP"]) / "rekey.jsonl"
rk.write_text("".join(json.dumps(r) + "\n" for r in (
    {"edition": "NewsUK1990UKEnglish/1990-01-01_1", "scanKey": old_key, "filesHash": "h", "scan": {}},
    {"edition": "GaleTelegraph1975UKEnglish/1975-03-04", "scanKey": old_key, "filesHash": "h", "scan": {}})))
stood = [f.scan_current(r, "h") for r in f.scan_queue.jsonl_rows(rk)]
check("a scan under the old corpus-wide key stands for a paper it names, and is re-keyed to that paper's; "
      "a paper it never named (a new one) is due",
      ([True, False], 1, [f.scan_key(), old_key], 0),
      (stood, f.rekey_scans(rk), [r["scanKey"] for r in f.scan_queue.jsonl_rows(rk)], f.rekey_scans(rk)))
f.CORPUS_KEYS[old_key] = {**f.CORPUS_KEYS[old_key], "times": "moved"}
check("(mirror) once that paper's key moves, a scan under the corpus-wide key is stale",
      False, f.scan_current({"edition": "NewsUK1990UKEnglish/x", "scanKey": old_key, "filesHash": "h", "scan": {}}, "h"))
f.CORPUS_KEYS[old_key] = {**f.CORPUS_KEYS[old_key], "times": f.scan_key()}
# The queue asks scan_current of every queued scan each pass: _paper_name,
# current_keys and the edition's paper are cached, answering as the
# uncached walk does, and a name re-bound is looked up again.
walk = lambda p: next(k for k, v in vars(f).items() if v is p and k.isupper())
fake_paper = object()
f.ZZ_CACHED = fake_paper
first = f._paper_name(fake_paper)
f.ZZ_CACHED = None
f.ZZ_MOVED = fake_paper
moved_to = f._paper_name(fake_paper)
del f.ZZ_CACHED, f.ZZ_MOVED
gt = f.GALE_TELEGRAPH
row = {"edition": "GaleTelegraph1975UKEnglish/1975-03-04", "scanKey": f.scan_key(gt), "filesHash": "h", "scan": {}}
check("scan_current's caches: a paper's name as the globals walk finds it, again after a re-bind; one key set "
      "shared by every ask; an edition named by string read as paper_of's (asked twice, by rel and by row)",
      (True, "ZZ_CACHED", "ZZ_MOVED", True, {f.scan_key(gt), f.sized_scan_key(gt), *f._BAND_CACHE_FIX[gt.key][:2],
                                                                      *f._LINES_FIX[gt.key][:2],
                                                                      *f._WORDS_CACHE_FIX[gt.key][:2],
                                                                      *f._SOLUTION_HEADINGS_FIX[gt.key][:2],
                                                                      *f._PRIZE_HEADINGS_FIX[gt.key][:2],
                                                                      *f._BAND_WIDTH_FIX[gt.key][:2],
                                                                      *f._GRID_CAP_FIX[gt.key][:2],
                                                                      *f._NEG_EXPECTED_FIX[gt.key][:2],
                                                                      *f._DOT_LEADER_FIX[gt.key][:2],
                                                                      *f._DAY_HEADING_FIX[gt.key][:2]},
       [True, True, True, False]),
      (all(f._paper_name(p) == walk(p) for p in f.FILERS.values()), first, moved_to,
       f.current_keys(gt) is f.current_keys(gt), set(f.current_keys(gt)),
       [f.scan_current(row, "h"), f.scan_current(row, "h"), f.scan_current(row, "h", row["edition"]),
        f.scan_current(row, "h", "NewsUK1990UKEnglish/1990-01-01_1")]))
# scan_stands keeps each (cache, rel)'s path facts (_STAND_DIRS), never its
# hash: off the media disk it lists the dir as input_hash does, a file added
# moving it; on it, it reads the manifest row afresh, a later row standing.
mm = f.media_manifest
sc = Path(os.environ["TMP"]) / "standcache"
(sc / "Item" / "e1").mkdir(parents=True)
(sc / "Item" / "e1" / "pages.json").write_text("[]")
off = [f._stand_hash(sc, "Item/e1"), f.input_hash(sc / "Item" / "e1")]
(sc / "Item" / "e1" / "p1.jpg").write_text("x")
off += [f._stand_hash(sc, "Item/e1"), f.input_hash(sc / "Item" / "e1")]
saved_root, saved_rows = mm.downloads.ROOT, mm.edition_rows
media = Path(os.environ["TMP"]) / "media"
manifest = {"Item/e2": {"files": "abc"}}
mm.downloads.ROOT, mm.edition_rows = media, lambda: manifest
on = [f._stand_hash(media, "Item/e2"), f.input_hash(media / "Item" / "e2")]
manifest["Item/e2"] = {"files": "def"}
on += [f._stand_hash(media, "Item/e2"), f.input_hash(media / "Item" / "e2")]
held = f._STAND_DIRS[(str(media), "Item/e2")]
mm.downloads.ROOT, mm.edition_rows = saved_root, saved_rows
check("scan_stands' input hash: input_hash's own off the media disk (moved by a new file) and on it "
      "(the manifest's latest row), its dir's path facts kept",
      (True, True, False, ["abc", "abc", "def", "def"], (media / "Item" / "e2", True, "Item/e2")),
      (off[0] == off[1], off[2] == off[3], off[0] == off[2], on, held))

# The other papers' Gale pages: each item is a paper of its own, filed as
# its series; the Telegraph's and FT's read in those runs.
check("each Gale item is its paper's, filed as its series, read by its run",
      [("galetelegraph", "telegraph", "telegraph"), ("galeft", "ftcryptic", "ft"),
       ("galeindependent", "independent", "galeindependent"), ("galesundaytimes", "sundaytimes", "galesundaytimes")],
      [(f.paper_of(f"x/{i}/d").key, f.paper_of(f"x/{i}/d").series, f.filer_of(f"{i}/d").key)
       for i in ("GaleTelegraph1975UKEnglish", "GaleFT1980UKEnglish", "GaleIndependent1990UKEnglish",
                 "GaleSundayTimes1950UKEnglish")])
check("a Gale Telegraph title: the ~1990 banner over the clues, the old 'No. N ACROSS', the solution heading",
      ([21502, 15301], [21501], []),
      ([n for t in ("CROSSWORD / 21,502", "No. 15,301 ACROSS") for n, _, _ in f.GALE_TELEGRAPH.headings([line(t)])[0]],
       [n for n, _ in f.GALE_TELEGRAPH.headings([line("SOLUTION No. 21,501")])[1]],
       f.GALE_TELEGRAPH.headings([line("QUICK CROSSWORD")])[0]))
check("an Independent title with its setter, and its solution headings; never the Quick or Concise",
      ([(1234, "Quixote"), (5678, None), (9101, None)], [1233, 1233], []),
      ([(n, s) for t in ("THE INDEPENDENT CROSSWORD No 1,234 Set by Quixote", "Saturday Crossword No. 5,678",
                         "Cryptic crossword #9,101") for n, _, s in f.GALE_INDEPENDENT.headings([line(t)])[0]],
       [n for t in ("Solution to No 1,233", "Yesterday's solution No. 1,233")
        for n, _ in f.GALE_INDEPENDENT.headings([line(t)])[1]],
       [h for t in ("QUICK CROSSWORD No 1,234", "Concise crossword No 12") for h in f.GALE_INDEPENDENT.headings([line(t)])[0]]))
check("a Sunday Times title from No 1 on, and its solution headings; never Mephisto",
      ([1, 2345, 3456], [1, 2344], []),
      ([n for t in ("Cross-word Puzzle—No. 1", "THE SUNDAY TIMES CROSSWORD No 2,345", "Prize Crossword No. 3,456")
        for n, _, _ in f.GALE_SUNDAY_TIMES.headings([line(t)])[0]],
       [n for t in ("Solution to Cross-word Puzzle No. 1", "SOLUTION TO No 2,344")
        for n, _ in f.GALE_SUNDAY_TIMES.headings([line(t)])[1]],
       f.GALE_SUNDAY_TIMES.headings([line("Mephisto No 1,234")])[0]))
check("a TLS title and its solution heading; never its entry address or winner line; its own run",
      ([835], [831], [], [], "galetls"),
      ([n for n, _, _ in f.GALE_TLS.headings([line("TLS CROSSWORD 835")])[0]],
       [n for n, _ in f.GALE_TLS.headings([line("SOLUTION TO CROSSWORD 831")])[1]],
       f.GALE_TLS.headings([line("TLS Crossword 835,")])[0], f.GALE_TLS.headings([line("The winner of Crossword 831 is")])[0],
       f.filer_of("GaleTLS2010UKEnglish/d").key))
import datetime as _d
check("the TLS numbers its dates imply run on into our tls files", (835, 1118, 1183),
      tuple(f.tls_expected_number(_d.date.fromisoformat(d)) for d in ("2010-06-04", "2016-03-25", "2017-07-07")))
check("the Independent and Sunday Times numbers their dates imply run on into our independent and sundaytimes files",
      (1, 7566, 1, 4589, 5000),
      (f.independent_expected_number(_d.date(1986, 10, 7)), f.independent_expected_number(_d.date(2011, 1, 15)),
       f.sunday_times_expected_number(_d.date(1925, 1, 11)), f.sunday_times_expected_number(_d.date(2014, 5, 11)),
       f.sunday_times_expected_number(_d.date(2022, 3, 27))))
check("a title no verdict covers makes the edition due", "titles changed",
      f.due_reason({"inputs": "h", "solutionsSeen": [], "verdicts": [], "vlm": "v",
                    "scan": {"puzzles": [{"number": 18862}]}}, "h", [], "v"))
# A read by another VLM version (a model change) is due, at the whole-corpus
# rank: behind never-read and every fix-driven reason, never jumping them.
by_old = {"inputs": "h", "solutionsSeen": [], "verdicts": [], "vlm": "old", "scan": {"puzzles": []}}
check("a read by another VLM version is due at the whole-corpus rank; the same version, or no VLM up, is not",
      ("read by another VLM", 3, None, None, True),
      (f.due_reason(by_old, "h", [], "new"), f.RANKS["read by another VLM"], f.due_reason(by_old, "h", [], "old"),
       f.due_reason(by_old, "h", [], None),
       f.RANKS["read by another VLM"] > max(r for k, r in f.RANKS.items() if k != "read by another VLM" and r < 3)))
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
check("a fix's re-read ranks before the whole-corpus ones (scan code, --reread)", [2, 2, 2, 3, 3],
      [f.rank_of_reason("short Times page, its third clue column read since"), f.rank_of_reason("refused not-a-grid before its fix"), f.rank_of_reason("solution moved"),
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
      ["refused not-a-grid before its fix", None, None, "refused crashed before its fix", None],
      [f.due_reason(refused("not-a-grid", "2026-10-01T00:00:00+00:00"), "h", [], "v"),
       f.due_reason(refused("not-a-grid", "2099-01-01T00:00:00+00:00"), "h", [], "v"),
       f.due_reason(refused("unlisted", "2026-10-01T00:00:00+00:00"), "h", [], "v"),
       f.due_reason(refused("crashed", "2026-10-01T00:00:00+00:00"), "h", [], "v"),
       f.due_reason(refused("crashed", "2099-01-01T00:00:00+00:00"), "h", [], "v")])
failed_write = lambda msg, at: {**refused(None, at), "verdicts": [{"number": 1, "writeFailed": msg}]}
check("a write that raised KeyError 'text' before its fix is due, ranked with the refusals; another message, or a later read, is not",
      ["refused writeFailed before its fix", None, None, 2],
      [f.due_reason(failed_write("KeyError: 'text'", "2026-10-11T13:41:23+00:00"), "h", [], "v"),
       f.due_reason(failed_write("KeyError: 'text'", "2099-01-01T00:00:00+00:00"), "h", [], "v"),
       f.due_reason(failed_write("OSError: disk full", "2026-10-11T13:41:23+00:00"), "h", [], "v"),
       f.rank_of_reason("refused writeFailed before its fix")])
part = lambda acc, refusal, key: {**refused(None, "2099-01-01T00:00:00+00:00"), "verdicts": [
    {"number": 1, "solution": {"accepted": acc, "lights": 30, **({"refused": refusal} if refusal else {})}}],
    **({"solutionKey": key} if key else {})}
short, unclassified = "solution short, read by other code", "solution short, its cells unclassified"
check("a solution read in part or refused by other solution code, or no key, is due; whole, or this code's, is not",
      [unclassified, short, unclassified, None, None, None],
      [f.due_reason(part(20, None, "other"), "h", [], "v"),
       f.due_reason(part(0, "its blocks are not the puzzle's", "other"), "h", [], "v"),
       f.due_reason(part(20, None, None), "h", [], "v"),
       f.due_reason(part(30, None, "other"), "h", [], "v"),
       f.due_reason(part(30, None, None), "h", [], "v"),
       f.due_reason(part(20, None, f.solution_key()), "h", [], "v")])
check("a grid refused unmatched is a rank 2 answers-only reread, once: a read after REREAD_REFUSED_GRID is not due",
      (2, True, False), (f.RANKS[f.REFUSED_GRID], f.REFUSED_GRID in f.SOLUTION_FIXES,
                         f.refused_grid({**part(0, "its blocks are not the puzzle's", None),
                                         "edition": "NewsUK1984UKEnglish/1984-05-01_61715"})))
classified_part = {**part(20, None, "other"), "verdicts": [
    {"number": 1, "solution": {"accepted": 20, "lights": 30, "classified": 3}}]}
ft_part = lambda key: {**part(20, None, key), "edition": "FinancialTimes1985UKEnglish/1985-01-02"}
check("a Times solution read short before the cell classifier is due as such, ranked 2; one it read, by other code; "
      "another paper's under a key before it stands, under any other is due",
      [unclassified, 2, short, None, short],
      [f.fix_reason(part(20, None, "other")), f.rank_of_reason(unclassified), f.fix_reason(classified_part),
       f.fix_reason(ft_part(next(iter(f.SOLUTION_UNCLASSIFIED)))), f.fix_reason(ft_part("other"))])
check("the cell classifier reads the Times papers' grids only", ("times", "gale"), f.CELLS_CLASSIFIED)
# A grid older code read short, its cells unclassified, under SURE_BLOCKS (short_again passes over it) for a
# puzzle held with every clue and not every answer is UNCLASSIFIED_HELD: an answers-only reread (10-24).
uh_row = {**part(20, None, "other"), "edition": "NewsUK1984UKEnglish/1984-05-01_61715", "verdicts": [
    {"number": 99999991, "id": "times-99999991", "solutionFrom": "1984-05-02 leaf 3",
     "solution": {"accepted": 20, "lights": 30, "blocks": 0.9}}]}
real_fs = f.filed_state
f.filed_state = lambda series, n: (False, True)
uh_short = f.fix_reason(uh_row)
f.filed_state = lambda series, n: (True, True)
uh_whole = f.fix_reason(uh_row)
f.filed_state = lambda series, n: None
uh_none = f.fix_reason(uh_row)
f.filed_state = real_fs
check("a grid read short unclassified for a puzzle held short is UNCLASSIFIED_HELD (rank 2, answers-only, once by key); "
      "held whole or not held, the plain reason",
      [f.UNCLASSIFIED_HELD, unclassified, unclassified, 2, True, None],
      [uh_short, uh_whole, uh_none, f.RANKS[f.UNCLASSIFIED_HELD], f.UNCLASSIFIED_HELD in f.SOLUTION_FIXES,
       f.fix_reason({**uh_row, "solutionKey": f.solution_key()})])
# A grid read short at blocks just under SURE_BLOCKS (a heavy print's letters read as blocks) for a puzzle
# held short is HEAVY_PRINT (10-25: read_framed classifies such a grid since, blocks_sure); once.
def heavy_row(blocks, at="2026-10-25T06:00:00+00:00"):
    return {"edition": "NewsUK1984UKEnglish/1984-05-01_61715", "readAt": at, "solutionKey": f.solution_key(),
            "verdicts": [{"number": 99999991, "id": "times-99999991", "solutionFrom": "1984-05-02 leaf 3",
                          "solution": {"accepted": 20, "lights": 30, "blocks": blocks}}]}
f.filed_state = lambda series, n: (False, True)
hv = [f.fix_reason(heavy_row(0.96)), f.heavy_short(heavy_row(0.9)), f.heavy_short(heavy_row(0.98)),
      f.heavy_short(heavy_row(0.96, "2026-10-26T00:00:00+00:00"))]
f.filed_state = lambda series, n: (True, True)
hv.append(f.heavy_short(heavy_row(0.96)))
f.filed_state = real_fs
check("a grid read short at 0.946-0.97 blocks for a puzzle held short is HEAVY_PRINT (rank 2, answers-only); "
      "not under the floor, at SURE_BLOCKS, read since, or held whole",
      [f.HEAVY_PRINT, False, False, False, False, 2, True],
      hv + [f.RANKS[f.HEAVY_PRINT], f.HEAVY_PRINT in f.SOLUTION_FIXES])
# The same read since REREAD_HEAVY, no cell classified at SOLUTION_BLOCKS-SURE_BLOCKS, is SURE_FRAMING (10-25
# evening: read_framed classifies on the best sure framing and very heavy prints since); once. A grid whose
# cells were classified (even none decoded) is not, nor one under SOLUTION_BLOCKS or held whole.
f.filed_state = lambda series, n: (False, True)
sf_after = "2026-10-25T14:00:00+00:00"
sf_cls = heavy_row(0.93, sf_after)
sf_cls["verdicts"][0]["solution"]["classified"] = 0
sf = [f.fix_reason(heavy_row(0.93, sf_after)), f.fix_reason(heavy_row(0.96, sf_after)), f.unsure_short(sf_cls),
      f.unsure_short(heavy_row(0.8, sf_after)), f.unsure_short(heavy_row(0.98, sf_after)),
      f.unsure_short(heavy_row(0.93, "2026-10-26T00:00:00+00:00"))]
f.filed_state = lambda series, n: (True, True)
sf.append(f.unsure_short(heavy_row(0.93, sf_after)))
f.filed_state = real_fs
check("a grid read short unclassified under SURE_BLOCKS since REREAD_HEAVY for a puzzle held short is SURE_FRAMING "
      "(rank 2, answers-only); not classified, under SOLUTION_BLOCKS, at SURE_BLOCKS, read since, or held whole",
      [f.SURE_FRAMING, f.SURE_FRAMING, False, False, False, False, False, 2, True],
      sf + [f.RANKS[f.SURE_FRAMING], f.SURE_FRAMING in f.SOLUTION_FIXES])
# A grid that gave answers for a puzzle held with a suspect clue (complete() refuses it) is SUSPECT_HELD, once:
# decide() sent its answers-only reading to --out before REREAD_SUSPECT (10-25).
def sh_row(at="2026-10-25T06:00:00+00:00", accepted=30):
    return {"edition": "NewsUK1984UKEnglish/1984-05-01_61715", "readAt": at, "solutionKey": f.solution_key(),
            "verdicts": [{"number": 99999991, "id": "times-99999991", "solutionFrom": "1984-05-02 leaf 3",
                          "answersOnly": True, "solution": {"accepted": accepted, "lights": 30, "blocks": 1.0}}]}
real_shf = f.suspect_held_file
f.filed_state = lambda series, n: (False, True)
f.suspect_held_file = lambda series, n: True
sh = [f.fix_reason(sh_row()), f.suspect_held(sh_row("2026-10-26T00:00:00+00:00")), f.suspect_held(sh_row(accepted=0))]
f.suspect_held_file = lambda series, n: False
sh.append(f.suspect_held(sh_row()))
f.suspect_held_file = real_shf
f.filed_state = real_fs
check("a grid read for a puzzle held with a suspect clue is SUSPECT_HELD (rank 2, answers-only, a LOW prefix); "
      "not read since, with no answer read, or held complete",
      [f.SUSPECT_HELD, False, False, False, 2, True, True],
      sh + [f.RANKS[f.SUSPECT_HELD], f.SUSPECT_HELD in f.SOLUTION_FIXES, f.SUSPECT_HELD.startswith("solution short")])
# A full read whose answers went to --out over a puzzle held with every clue (its copy answering a light the held file
# leaves blank), or whose write the gate refused over a mended held clue, is UNFILED_HELD, once (10-25).
def uh_row(at="2026-10-25T06:00:00+00:00", accepted=30, **v):
    return {"edition": "NewsUK1984UKEnglish/1984-05-01_61715", "readAt": at, "solutionKey": f.solution_key(),
            "verdicts": [{"number": 99999992, "id": "times-99999992", "solutionFrom": "1984-05-02 leaf 3",
                          "solution": {"accepted": accepted, "lights": 30, "blocks": 1.0}, **v}]}
real_ug = f.unfiled_gain
f.filed_state = lambda series, n: (False, True)
f.unfiled_gain = lambda series, n, pid: True
gate = "refusing to write times-99999992: SHAPE 14-across: clue 'one , owner' holds a space before a comma: x (punctuation.faults)"
uh = [f.fix_reason(uh_row(unfiled=2)), f.unfiled_held(uh_row(refusedWrite=gate)),
      f.unfiled_held(uh_row("2026-10-26T00:00:00+00:00", unfiled=2)), f.unfiled_held(uh_row(accepted=0, unfiled=2)),
      f.unfiled_held(uh_row(unfiled=2, answersOnly=True)), f.unfiled_held(uh_row(refusedWrite="refusing: CROSS cell (6, 6)"))]
f.filed_state = lambda series, n: (False, False)
uh.append(f.unfiled_held(uh_row(unfiled=2)))
f.filed_state = lambda series, n: (False, True)
f.unfiled_gain = lambda series, n, pid: False
uh.append(f.unfiled_held(uh_row(unfiled=2)))
f.unfiled_gain = real_ug
f.filed_state = real_fs
check("a full read filed to --out over a puzzle held with every clue, or refused over a mended clue, is UNFILED_HELD "
      "(rank 2, answers-only first, a LOW prefix); not read since, with no answer read, answers-only, another refusal, "
      "held with a clue blank, or its copy adding nothing",
      [f.UNFILED_HELD, True, False, False, False, False, False, False, 2, True, True],
      uh + [f.RANKS[f.UNFILED_HELD], f.UNFILED_HELD in f.SOLUTION_FIXES, f.UNFILED_HELD.startswith("solution short")])# A grid read 1-2 lights short at SURE_BLOCKS: before REREAD_UNLISTED, UNLISTED; read since, before
# REREAD_VLM_UNLISTED, VLM_UNLISTED (the VLM's unlisted strip words stand since); after it, nothing.
def vu_row(at, gap=1):
    return {"edition": "NewsUK1984UKEnglish/1984-05-01_61715", "readAt": at, "verdicts": [
        {"number": 99999991, "id": "times-99999991", "solutionFrom": "1984-05-02 leaf 3",
         "solution": {"accepted": 30 - gap, "lights": 30, "blocks": 1.0}}]}
f.filed_state = lambda series, n: (False, True)
vu = [f.short_again(vu_row("2026-10-24T12:00:00+00:00")), f.short_again(vu_row("2026-10-25T06:00:00+00:00")),
      f.short_again(vu_row("2026-10-25T06:00:00+00:00", gap=4)), f.short_again(vu_row("2026-10-26T00:00:00+00:00"))]
real_sb = f.strip_blank
f.strip_blank = lambda series, n, sol_dir: True
vu += [f.short_again(vu_row("2026-10-25T15:00:00+00:00")), f.short_again(vu_row("2026-10-25T15:00:00+00:00", gap=4))]
f.strip_blank = lambda series, n, sol_dir: False
vu.append(f.short_again(vu_row("2026-10-25T15:00:00+00:00")))
f.strip_blank = real_sb
f.filed_state = real_fs
check("a grid read 1-2 short: UNLISTED before REREAD_UNLISTED, VLM_UNLISTED since (not 3+ short), then nothing; "
      "rank 2, answers-only",
      [f.UNLISTED, f.VLM_UNLISTED, None, None, 2, True],
      vu[:4] + [f.RANKS[f.VLM_UNLISTED], f.VLM_UNLISTED in f.SOLUTION_FIXES])
check("read since REREAD_VLM_UNLISTED, before REREAD_VLM_FLOOR, 1-2 short with a strip of a light the held file leaves "
      "blank: VLM_FLOOR_SHORT (rank 2, answers-only, a LOW prefix); not 3+ short, nor with no such strip",
      [f.VLM_FLOOR_SHORT, None, None, 2, True, True],
      vu[4:] + [f.RANKS[f.VLM_FLOOR_SHORT], f.VLM_FLOOR_SHORT in f.SOLUTION_FIXES,
                f.VLM_FLOOR_SHORT.startswith("solution short")])
# A held file 1-2 answers short, a blank light of it with no strip in its reading (strip_missing): read
# since REREAD_VLM_UNLISTED, before REREAD_LATE_STRIPS, LATE_STRIPS (VLM_FLOOR_SHORT first where due).
f.filed_state = lambda series, n: (False, True)
real_sm, real_sb = f.strip_missing, f.strip_blank
f.strip_blank = lambda series, n, sol_dir: False
f.strip_missing = lambda series, n, sol_dir, most=None: most is None
ls = [f.short_again(vu_row("2026-10-25T15:00:00+00:00", gap=4)), f.short_again(vu_row("2026-10-25T19:50:00+00:00", gap=0)),
      f.short_again(vu_row("2026-10-26T00:00:00+00:00"))]
f.strip_blank = lambda series, n, sol_dir: True
ls.append(f.short_again(vu_row("2026-10-25T15:00:00+00:00")))
f.strip_blank = lambda series, n, sol_dir: False
f.strip_missing = lambda series, n, sol_dir, most=None: False
ls.append(f.short_again(vu_row("2026-10-25T19:50:00+00:00")))
# Held 3-5 blank (strip_missing only up to LATE_MAX): read since REREAD_UNLISTED, before REREAD_WIDE_STRIPS, WIDE_STRIPS;
# 1-2 blank ones stay LATE_STRIPS; read before REREAD_UNLISTED (SHORT_WIDE) or since REREAD_WIDE_STRIPS, not so.
f.strip_missing = lambda series, n, sol_dir, most=None: most == f.LATE_MAX
ws = [f.short_again(vu_row("2026-10-25T15:00:00+00:00", gap=4)), f.short_again(vu_row("2026-10-25T19:50:00+00:00", gap=4)),
      f.short_again(vu_row("2026-10-24T12:00:00+00:00", gap=4)), f.short_again(vu_row("2026-10-26T00:00:00+00:00", gap=4))]
f.strip_missing = lambda series, n, sol_dir, most=None: True
ws.append(f.short_again(vu_row("2026-10-25T15:00:00+00:00", gap=1)))
f.strip_missing, f.strip_blank = real_sm, real_sb
f.filed_state = real_fs
check("a held file 3-5 short with a blank light no strip was cut for, read since REREAD_UNLISTED: WIDE_STRIPS until "
      "REREAD_WIDE_STRIPS (rank 2, answers-only, a LOW prefix); SHORT_WIDE before REREAD_UNLISTED; LATE_STRIPS first "
      "where that is due",
      [f.WIDE_STRIPS, f.WIDE_STRIPS, f.SHORT_WIDE, None, f.LATE_STRIPS, 2, True, True, 5],
      ws + [f.RANKS[f.WIDE_STRIPS], f.WIDE_STRIPS in f.SOLUTION_FIXES, f.WIDE_STRIPS.startswith("solution short"),
            f.LATE_MAX])
# A Times row whose solutionsSeen (or stored titles) moved is due its answers-only fix, not the blanket reason
# only_evidence drops; another paper's keeps the blanket one (10-25: 251 SHORT_WIDE Times puzzles never planned).
real_fr = f.fix_reason
f.fix_reason = lambda row: f.SHORT_WIDE
bf = [f.blanket_or_fix({"edition": "NewsUK1984UKEnglish/1984-05-01_61715"}, "inputs changed"),
      f.blanket_or_fix({"edition": "GaleTimes1956UKEnglish/1956-08-09"}, "titles changed"),
      f.blanket_or_fix({"edition": "GaleTelegraph1984UKEnglish/1984-05-01"}, "inputs changed"),
      f.blanket_or_fix({"edition": "GaleTimes1956UKEnglish/1956-08-09", "scan": {"puzzles": [{"number": 8203}]},
                        "verdicts": [{"number": 8203}]}, "inputs changed"),
      f.blanket_or_fix({"edition": "GaleTimes1956UKEnglish/1956-08-09", "scan": {"puzzles": []},
                        "verdicts": [{"number": 8203}]}, "titles changed")]
# ... unless the lost title is its held puzzle's (held_titles): HELD_TITLE reads it under that number.
real_ht = f.held_titles
f.held_titles = lambda row, cache=None: [{"number": 8203, "leaf": 0, "box": None, "heldTitle": True}]
bf.append(f.blanket_or_fix({"edition": "GaleTimes1956UKEnglish/1956-08-09", "scan": {"puzzles": []},
                            "verdicts": [{"number": 8203}]}, "inputs changed"))
f.held_titles = real_ht
f.fix_reason = lambda row: "refused unparsed before its fix"
bf.append(f.blanket_or_fix({"edition": "NewsUK1984UKEnglish/1984-05-01_61715"}, "inputs changed"))
f.fix_reason = lambda row: None
bf.append(f.blanket_or_fix({"edition": "NewsUK1984UKEnglish/1984-05-01_61715"}, "inputs changed"))
f.fix_reason = real_fr
check("blanket_or_fix: a Times row's answers-only fix stands over inputs/titles changed; another paper's row, "
      "a row whose scan lost a verdict's title (not its held puzzle's), another fix, or none keeps the blanket reason",
      [f.SHORT_WIDE, f.SHORT_WIDE, "inputs changed", f.SHORT_WIDE, "titles changed", f.SHORT_WIDE, "inputs changed",
       "inputs changed"],
      bf)
check("a held file 1-2 short with a blank light no strip was cut for, read since REREAD_VLM_UNLISTED (its reading "
      "3+ short or whole): LATE_STRIPS (rank 2, answers-only, a LOW prefix); not read since REREAD_LATE_STRIPS, "
      "VLM_FLOOR_SHORT where that is due, nothing with every blank light's strip cut",
      [f.LATE_STRIPS, f.LATE_STRIPS, None, f.VLM_FLOOR_SHORT, None, 2, True, True],
      ls + [f.RANKS[f.LATE_STRIPS], f.LATE_STRIPS in f.SOLUTION_FIXES, f.LATE_STRIPS.startswith("solution short")])
# late_strips cuts and asks only for 1 to LATE_MAX blank lights, one at least never stripped.
ls_es = [{"number": n, "direction": "across", "solution": None} for n in (1, 3, 5, 7, 9, 11)]
ls_cut = []
real_cs = f.trove_solution_ocr.crop_strips
f.trove_solution_ocr.crop_strips = lambda crop, grid, keys: ls_cut.append(keys) or {}
ls_out = [f.late_strips(ls_es, {}, {"a": 1}, {}, [], {}, Path(__file__)),
          f.late_strips(ls_es, {"1-across": "ABC"}, {"a": 1}, {f"{n}-across": {} for n in (3, 5, 7, 9, 11)}, [], {},
                        Path(__file__))]
f.trove_solution_ocr.crop_strips = real_cs
check("late_strips: 6 blank lights (over LATE_MAX), or every blank one's strip cut already, cuts nothing and keeps "
      "the reading", [({}, {"a": 1}), ({"1-across": "ABC"}, {"a": 1}), []], ls_out + [ls_cut])
check("an answers-only grid read one letter off a word is a misread (a 1973 print's ADORESS for ADDRESS); "
      "a word, a listed name (William RUFUS), and words by their enumeration stand",
      [True, False, False, False, False, (12, "down")],
      [f.misread_word("ADORESS", "7"), f.misread_word("ADDRESS", "7"), f.misread_word("BULGARIA", "8"),
       f.misread_word("RUFUS", "5"), f.misread_word("KINGCOLE", "4,4"), f._light_key("12-down")])
check("the solution key is the solution reader's code, not the scan's", True,
      len(f.solution_key()) == 16 and f.solution_key() != f.scan_key())
import scan_queue
# A reread time is when its fix landed: one still ahead re-reads every row
# the pass reads until then, over and over.
check("no reread time is in the future", [],
      [t for t in (*f.REREAD_REFUSED.values(), *f.REREAD_WRITE_FAILED.values())
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
# Gale 2006-11-09 (ch): the grid's clue numbers open the title's row, and the
# title's number, its middle under theirs, still joins the title.
words = [(411, 4151, 447, 4191, "2"), (1616, 4154, 1650, 4191, "8"),
         (1774, 4140, 3030, 4236, "The TImES CROSSWOrD"), (3069, 4157, 3340, 4236, "23,442"),
         (3792, 4182, 4360, 4230, "Solution toCrossword 23,44l")]
check("a title's number joins the title's row a grid's clue numbers opened (Gale 2006-11-09)", [23442],
      [n for n, _, _ in f.TIMES.headings(f.printed_lines(words))[0]])
# (mirror) Gale 2008-05-21 (ch): a title beside a body line a fragment opened,
# the title a fifth taller, is no part of that line.
words = [(208, 1235, 251, 1247, "alou"), (518, 1231, 865, 1261, "and'theresilience thatwas on display"),
         (892, 1229, 1287, 1266, "Times Crossword 23,919")]
check("(mirror) a title does not join a body line's row a fragment opened (Gale 2008-05-21)", [23919],
      [n for n, _, _ in f.TIMES.headings(f.printed_lines(words))[0]])
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
# The solution heading with its opening misread (times-13683, 1974) still
# ends the column: else 22 down's count is no longer its clue's end.
for head in ("cotution of Puzzle No 13.682", "^j^on D f Puzzle No 13,682"):
    col = [line("DOWN", 470, 820), line("22 Bird dives back into the", 470, 840), line("iceberg (5).", 470, 860),
           line(head, 470, 880)]
    check(f"a misread solution heading ends the column: {head}",
          "DOWN\n22 Bird dives back into the\niceberg (5).", f.column_text(f.columns(col, grid)))
check("a clue ending on a number is no solution heading",
      [False, False], [f.stops(t) for t in ("puzzle no 1 (5).", "a business combine (8).")])

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

# The 2014 Times (Gale): the grid at the page's foot, the two clue columns right
# of it, "Yesterday's solution" under the first; the third column is not read.
from PIL import Image, ImageDraw
page = Image.new("L", (3296, 2849), 255)
ImageDraw.Draw(page).rectangle((1000, 2000, 1500, 2400), fill=0)  # clue-column text, as ink
check("clues right of a grid at the page's foot are found", (1675, 2531),
      f.right_columns(page, (196, 1598, 916, 2316)))
check("a grid with room under it for clues has none right of it", None, f.right_columns(page, (196, 500, 916, 1218)))
_gale = types.SimpleNamespace(key="gale")
check("a 1947 Gale page's clues are not read right of the grid", False, f.clues_may_be_right(_gale, Path("GaleTimes1947UKEnglish/1947-05-17")))
check("a 2014 Gale page's clues may be right of the grid", True, f.clues_may_be_right(_gale, Path("GaleTimes2014UKEnglish/2014-03-01")))
check("a blank strip right of the grid holds no clues", None,
      f.right_columns(Image.new("L", (3296, 2849), 255), (196, 1598, 916, 2316)))
page2 = Image.new("L", (3296, 2849), 255)
ImageDraw.Draw(page2).rectangle((1000, 2000, 1900, 2400), fill=0)  # clues out to 1.35 grids' widths
check("the 2005 Times' clues run out further right of the grid than the 2014's", (1960, 2531),
      f.right_columns(page2, (196, 1598, 916, 2316), f.RIGHT_SPAN_LEFT))
rwords = [[(960, 1620, 1250, 1645, "Across")], [(1330, 1620, 1620, 1645, "build-up? (5,5)")],
          [(960, 1650, 1250, 1675, "25 Drag performer by bar getting big")],
          [(960, 2330, 1250, 2355, "Yesterday's solution 25,732")],
          [(1330, 1650, 1640, 1675, "Down")], [(1330, 1680, 1640, 1705, "1 Man in the street (3,6)")]]
rgrid = (196, 1598, 916, 2316)
right = f.right_gutter(rwords, rgrid, (1675, 2531))
rcols = f.columns(rwords, rgrid, right=right)
check("the gutter lies between the right-hand columns", True, 1250 < right[1] < 1330)
check("the two columns right of the grid read in order, the solution's heading ending the first",
      [["Across", "25 Drag performer by bar getting big"], ["build-up? (5,5)", "Down", "1 Man in the street (3,6)"]],
      [[l[4] for l in col] for col in rcols])
check("a line headed Yesterday's solution stops a column", True, f.stops("Yesterday's solution 25,732"))
# The Feb to May 2014 pages: the solution box under the grid is inked like a third column.
ImageDraw.Draw(page).rectangle((1000, 2400, 1100, 2700), fill=0)
check("that box alone reads as a third column under the grid", True, f.overhang(page, (196, 1598, 916, 2316)) is not None)
check("clues right of the grid win over a third column read from that box", ((1675, 2531), None),
      f.right_or_over(page, (196, 1598, 916, 2316)))

# A reader cache a killed read left empty is read again, not fatal; a write leaves no half file.
import tempfile
from pathlib import Path
with tempfile.TemporaryDirectory() as tmpd:
    cp = Path(tmpd) / "sub" / "x.json"
    check("a missing cache reads as None", None, f.read_cache(cp))
    f.write_cache(cp, {"box": [1, 2, 3, 4], "words": []})
    check("a written cache reads back", {"box": [1, 2, 3, 4], "words": []}, f.read_cache(cp))
    check("no temporary file is left", ["x.json"], [p.name for p in cp.parent.iterdir()])
    cp.write_text("")
    check("an empty cache reads as None", None, f.read_cache(cp))
    cp.write_text('{"box": [1, 2')
    check("a half-written cache reads as None", None, f.read_cache(cp))

# The 2006-13 Times (Gale): a grid mid-page with three clue columns under it,
# the third overhanging the grid's right edge (2007-03-14, No 23,548).
ogrid = (1150, 1287, 1870, 1999)
opage = Image.new("L", (3296, 2955), 255)
ImageDraw.Draw(opage).rectangle((1900, 2050, 2121, 2600), fill=0)  # the third column's text, as ink
oend = f.overhang(opage, ogrid)
check("a third clue column under the grid, overhanging it, ends where its ink does (within the window)", True,
      oend is not None and 2121 <= oend <= 2121 + f.OVER_WINDOW)
check("a blank page under the grid has no third column", None, f.overhang(Image.new("L", (3296, 2955), 255), ogrid))
speck = Image.new("L", (3296, 2955), 255)
ImageDraw.Draw(speck).rectangle((2000, 2100, 2010, 2110), fill=0)
check("a speck in the margin is no third column", None, f.overhang(speck, ogrid))
check("a grid with no room under it has no third column", None, f.overhang(opage, (1150, 2500, 1870, 3200)))
check("a page with room under the grid keeps its third column", (None, oend), f.right_or_over(opage, ogrid))
check("a 2010 Gale page keeps its overhang path with the right columns off", (None, oend), f.right_or_over(opage, ogrid, f.clues_may_be_right(_gale, Path("GaleTimes2010UKEnglish/2010-03-01"))))
owords = [[(1110, 2050, 1420, 2072, "1 Nag CAMRA to move into")], [(1110, 2080, 1420, 2102, "stronger drink (8)")],
          [(1480, 2050, 1780, 2072, "23 Tough punishment suspending")], [(1480, 2080, 1780, 2102, "paratrooper (4,4)")],
          [(1805, 2050, 2105, 2072, "7 Sweet air must flow over one")], [(1805, 2080, 2105, 2102, "(8)")]]
og = f.over_gutters(owords, ogrid, 2121)
check("the gutters lie between the three columns, the last one ending where it was found", True,
      1420 < og[0] < 1480 and 1780 < og[1] < 1805 and og[2] == 2121)
ocols = f.columns(owords, ogrid, split=og)
check("three columns under the grid read in order, the third past the grid's edge",
      [["1 Nag CAMRA to move into", "stronger drink (8)"], ["23 Tough punishment suspending", "paratrooper (4,4)"],
       ["7 Sweet air must flow over one", "(8)"]], [[l[4] for l in col] for col in ocols])
check("the three windows start at the grid's outdented edge and end at the third's end",
      (1110, 2121), (f.windows(ogrid, split=og)[0][0], f.windows(ogrid, split=og)[2][1]))
# A held Times page short of clues, read before the third column was, is due again.
held = {"scan": {"item": "GaleTimes2007UKEnglish", "date": "2007-03-14"}, "readAt": "2026-10-12T19:37:42+00:00",
        "verdicts": [{"number": 23548, "clues": 22, "lights": 28, "complete": False}]}
check("a held Gale Times 2007 page short of clues is read again", "short Times page, its third clue column read since",
      f.fix_reason(held))
check("a whole one, a refused one, another paper's, a 2014 page, or one read since is not", [None] * 5,
      [f.fix_reason({**held, "verdicts": [{"clues": 28, "lights": 28, "complete": True}]}),
       f.fix_reason({**held, "verdicts": [{"refused": "x", "cause": "unlisted"}]}),
       f.fix_reason({**held, "scan": {"item": "GaleTelegraph2007UKEnglish", "date": "2007-03-14"}}),
       f.fix_reason({**held, "scan": {"item": "GaleTimes2014UKEnglish", "date": "2014-09-17"}}),
       f.fix_reason({**held, "readAt": "2099-01-01T00:00:00+00:00"})])
check("a short 2007 page read before the third column leads the stale-scan reasons; a 2009 or a whole one does not",
      [True, False, False],
      [f.third_column_first(held), f.third_column_first({**held, "scan": {**held["scan"], "date": "2009-03-14"}}),
       f.third_column_first({**held, "verdicts": [{"clues": 28, "lights": 28, "complete": True}]})])
# A Gale Times 2000-14 page read with no title found, by other scan code, is scanned and read again.
none = {"edition": "GaleTimes2000UKEnglish/2000-03-14", "inputs": "h", "scanKey": "old", "verdicts": [],
        "scan": {"item": "GaleTimes2000UKEnglish", "date": "2000-03-14", "puzzles": [], "solutions": []},
        "readAt": "2026-10-13T05:00:00+00:00"}
check("a Gale 2000 page no title was found on by older scan code is due; by the current code, with a title, "
      "read, failed to scan, of 1999 or another paper is not", [f.NO_TITLE_RESCAN] + [None] * 6,
      [f.fix_reason(none), f.fix_reason({**none, "scanKey": f.scan_key(f.paper_of(f.Path("GaleTimes2000UKEnglish/2000-03-14")))}),
       f.fix_reason({**none, "scan": {**none["scan"], "puzzles": [{"number": 21363}]}}),
       f.fix_reason({**none, "verdicts": [{"number": 1, "complete": True}]}),
       f.fix_reason({**none, "scan": {**none["scan"], "failed": "x"}}),
       f.fix_reason({**none, "scan": {**none["scan"], "date": "1999-12-31", "item": "GaleTimes1999UKEnglish"}}),
       f.fix_reason({**none, "scan": {**none["scan"], "item": "NewsUK2000UKEnglish"}})])
old = {**none, "edition": "GaleTimes1958UKEnglish/1958-12-31",
       "scan": {**none["scan"], "item": "GaleTimes1958UKEnglish", "date": "1958-12-31"}}
check("a Gale 1957-62 page no title was found on by older scan code is due too; one of 1956 or 1963 is not",
      [f.NO_TITLE_RESCAN, f.NO_TITLE_RESCAN, f.NO_TITLE_RESCAN, None, None],
      [f.fix_reason(old),
       f.fix_reason({**old, "scan": {**old["scan"], "item": "GaleTimes1957UKEnglish", "date": "1957-01-02"}}),
       f.fix_reason({**old, "scan": {**old["scan"], "item": "GaleTimes1962UKEnglish", "date": "1962-12-31"}}),
       f.fix_reason({**old, "scan": {**old["scan"], "item": "GaleTimes1956UKEnglish", "date": "1956-12-31"}}),
       f.fix_reason({**old, "scan": {**old["scan"], "item": "GaleTimes1963UKEnglish", "date": "1963-01-02"}})])
check("the third-column reread time is not in the future", True,
      scan_queue.when(f.REREAD_THREE_COLUMNS[2]) <= scan_queue.when("now"))
# A held 2005-06 Gale Times page, read before right_foreign() cut its clue window at the gutter, is due again.
beside = {"edition": "GaleTimes2005UKEnglish/2005-11-26", "inputs": "h",
          "scan": {"item": "GaleTimes2005UKEnglish", "date": "2005-11-26", "puzzles": [{"number": 99923144}]},
          "readAt": "2026-10-22T18:25:48+00:00",
          "verdicts": [{"number": 99923144, "id": "times-99923144", "clues": 29, "lights": 30, "complete": False,
                        "blank": {"24-down": "no reading laid a clue on it"}}]}
check("a held 2005 Gale Times page read before its window was cut at the gutter is read again, as evidence",
      [f.RIGHT_FOREIGN_READ, 2, True],
      [f.fix_reason(beside), f.RANKS[f.RIGHT_FOREIGN_READ], __import__("edition_queue").evidence_reason(f.RIGHT_FOREIGN_READ)])
check("a whole one, a refused one or write, a 2006-11 or 2004 page, another paper's, or one read since is not", [False] * 7,
      [f.right_foreign_held({**beside, "verdicts": [{"id": "times-99923144", "clues": 30, "lights": 30, "complete": True}]}),
       f.right_foreign_held({**beside, "verdicts": [{**beside["verdicts"][0], "refusedWrite": "a book's copy"}]}),
       f.right_foreign_held({**beside, "verdicts": [{"id": "times-99923144", "refused": "x", "cause": "unlisted"}]}),
       f.right_foreign_held({**beside, "scan": {**beside["scan"], "item": "GaleTimes2006UKEnglish", "date": "2006-11-02"}}),
       f.right_foreign_held({**beside, "scan": {**beside["scan"], "item": "GaleTimes2004UKEnglish", "date": "2004-11-26"}}),
       f.right_foreign_held({**beside, "scan": {**beside["scan"], "item": "GaleTelegraph2005UKEnglish"}}),
       f.right_foreign_held({**beside, "readAt": "2099-01-01T00:00:00+00:00"})])
check("the right-window reread time is not in the future", True,
      scan_queue.when(f.REREAD_RIGHT_FOREIGN[2]) <= scan_queue.when("now"))
# right_foreign(): the window pulled in to the gutter before the advert, its boxes dropped from every reading.
rgrid = (150, 1811, 870, 2510)
rap = {"ch": [[(1356, 2409, 1719, 2435, "20 Raise sympathy with attitude (6)")],
              [(1355, 2480, 1690, 2508, "24 Thick cushion for nestling (5)")],
              [(1824, 2396, 1913, 2419, "Books Fi")], [(1824, 2468, 1913, 2492, "Times re")]],
       "en5": [[(1356, 2409, 1719, 2435, "20 Raise sympathy with attitude (6)")]]}
rr, rk = f.right_foreign(rap, rgrid, (1914, 2726))
check("the 2005 window ends in the gutter, the advert's line ends dropped",
      [True, 2726, ["20 Raise sympathy with attitude (6)", "24 Thick cushion for nestling (5)"], 1],
      [1719 < rr[0] < 1824, rr[1], [ws[0][4] for ws in rk["ch"]], len(rk["en5"])])
check("a window cutting into no print stands", ((1914, 2726), rap["en5"]),
      (lambda r: (r[0], r[1]["en5"]))(f.right_foreign({"en5": rap["en5"]}, rgrid, (1914, 2726))))

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
laid, blank = f.unfit_blanked({"1-across": ("Like ignis fatuus", "6", None), "3-across": ("Like ignis", "6", None)},
                               {}, {"1-across": 6, "3-across": 6}, {"1-across": ["ignis", "fatuus"]})
check("a word the clue's asPrinted keeps is filed; the same word unvouched is not (mirror)",
      ({"1-across": ("Like ignis fatuus", "6", None), "3-across": ("", "6", None)}, ["3-across"]),
      (laid, sorted(blank)))
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
# The vote counts no brackets: one reading's "(" put back where the rest read
# "i", "I" glued on or nothing (times-14500 1 across, real readings).
got, blank = ocr_clues.reconcile({"1-across": ("Washing part of old Somerset Inew Aron) House ?", "8", None)},
                                 ["1 Washing part of old Somer-\nset i new Avon) House ? (8).",
                                  "1 Washing part of old Somer-\nset (new Aron) House ? (8).",
                                  "1 Washing part of old Somer\nset new Aron) House ? (8)."], {"1-across": 8})
check("a bracket the vote lost is put back where a reading prints it",
      ("Washing part of old Somerset (new Avon) House?", {}), (got["1-across"][0], blank))
check("a bracket two readings open at different words is not put back", None,
      ocr_clues.bracket_reopened("A b c) d", ["A b (c) d", "A (b c) d"]))
check("a bracket no reading opens is not put back", None, ocr_clues.bracket_reopened("A b c) d", ["A b c d"]))

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
class _Page:
    width, height = 2000, 3000
_junk = [(500, 536, 100, 133)]    # lines (y0, y1, x0, x1): a stray 33x36 px crop (FT 1987-02-07)
_column = [(500, 1500, 100, 480)]  # a clue column: 380x1000 px
_short = [(500, 780, 100, 480)]    # a column of a few clues: 380x280 px
_skipped = len(vlm_reader.SKIPPED_SMALL)
check("a crop too small to hold a clue column gets no VLM ask; real columns keep theirs",
      [None, True, True],
      [vlm_reader.boxes(_Page, [0], [[_junk]])[0]]
      + [vlm_reader.boxes(_Page, [0], [[c]])[0] is not None for c in (_column, _short)])
check("the skipped crop is noted", _skipped + 1, len(vlm_reader.SKIPPED_SMALL))
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
check("a line starting a lower-case down carries on the line before", "9 Engineer tbe break down (8)\n10 Next (4)",
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
# blocks_sure / sure_framing: a framing that finds every block, a few inked lights read as blocks too, is
# sure (a heavy print); one that misses a block is not, however well it fits; the classifier reads the
# best-fitting sure framing (times-20419: two framings at 0.969, the first missed a block).
rules5 = ([k * 60 for k in range(6)], [k * 60 for k in range(6)])
inked = gray.copy()
for r, c in [(0, 0), (3, 1), (4, 4)]:
    inked[r * 60 + 6:(r + 1) * 60, c * 60 + 6:(c + 1) * 60] = 10
lost = gray.copy()
lost[66:120, 66:120] = 240
fits5 = [round(tso.block_agreement(g, grid5, rules5), 3) for g in (lost, inked)]
check("an inked print with every block found is sure, a framing missing a block is not; the sure one is read",
      [[0.96, 0.88], True, False, 1, None],
      [fits5, tso.blocks_sure(inked, grid5, rules5, fits5[1]), tso.blocks_sure(lost, grid5, rules5, fits5[0]),
       tso.sure_framing([(lost, *rules5), (inked, *rules5)], grid5, fits5),
       tso.sure_framing([(lost, *rules5)], grid5, fits5[:1])])

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

# keep_held_clues(): a reading that improves() the file keeps the held clues it only spoils with
# the neighbouring print's words (times-18379), and takes a held blank and a real correction.
(pz / "held.json").write_text(json.dumps(p3(["Bow's used the wrong way by fiddler",
                                             "Get cross, having seen some petrol spilt", "", "Fudqe the dish"])))
spoiled = p3(["Bow's used the wrong way by For the fiddler", "Get cross, having seen some pet-code, rol spilt",
              "Blanket it provides protection", "Fudge the dish"])
check("a held clue the reread only spoils with stray words stays, a blank and a mend are taken",
      [[1, 2], ["Bow's used the wrong way by fiddler", "Get cross, having seen some petrol spilt",
                "Blanket it provides protection", "Fudge the dish"]],
      [sorted(int(i.split("-")[0]) for i in f.keep_held_clues(spoiled, json.loads((pz / "held.json").read_text()))),
       [e["clue"]["text"] for e in spoiled["entries"]]])

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
# issue_dated(): an FT item title's date is weighed against the editions
# numbered either side of its issue. #26722, titled Jul 16 1975 between #26721
# (Fri Jul 18) and #26723 (Mon Jul 21), is Saturday Jul 19 (ftcryptic-2833).
ft75 = ["1975-04-30_26654", "1975-05-01_26664", "1975-05-02_26656", "1975-05-10_26663", "1975-05-12_26664",
        "1975-05-13_26665", "1975-07-15_26718", "1975-07-16_26719", "1975-07-16_26722", "1975-07-17_26720",
        "1975-07-18_26721", "1975-07-21_26723"]
check("a title date out of order with its issue neighbours is the day both count to",
      (D("1975-07-19"), None, True), f.issue_dated("1975-07-16_26722", D("1975-07-16"), ft75))
check("(mirror) a title date its issue neighbours bracket stands, vouched for",
      (D("1975-07-16"), None, True), f.issue_dated("1975-07-16_26719", D("1975-07-16"), ft75))
check("a misread issue number (#26664 for #26655) counting to another edition's date leaves the title's",
      (D("1975-05-01"), None, False), f.issue_dated("1975-05-01_26664", D("1975-05-01"), ft75))
check("(mirror) the edition its shared issue number is right for stands, vouched for",
      (D("1975-05-12"), None, True), f.issue_dated("1975-05-12_26664", D("1975-05-12"), ft75))
ft89 = ["1989-01-20_30748", "1989-01-22_30749", "1989-01-23_30750", "1989-04-28_30830", "1989-04-30_30831",
        "1989-05-02_30832"]
check("an FT edition titled on a Sunday is the Saturday its issue neighbours count to",
      (D("1989-01-21"), None, True), f.issue_dated("1989-01-22_30749", D("1989-01-22"), ft89))
check("(mirror) a Sunday its issue neighbours do not settle is refused",
      (None, True), (lambda r: (r[0], bool(r[1])))(f.issue_dated("1989-04-30_30831", D("1989-04-30"), ft89)))
check("issue_step skips Sundays both ways", [D("1975-07-21"), D("1975-07-19"), D("1975-07-19")],
      [f.issue_step(D("1975-07-19"), 1), f.issue_step(D("1975-07-21"), -1), f.issue_step(D("1975-07-18"), 1)])
# ft_dated(): a date another number is filed for, or out of order with the
# puzzles numbered either side, moves to the day those count to.
# ftcryptic-2262, from #26148 titled Aug 30 1973 (a date its issue
# neighbours vouch for), is Aug 31: 2261 is filed for Aug 30, 2264 for Sep 3.
held73 = {2259: D("1973-08-28"), 2260: D("1973-08-29"), 2261: D("1973-08-30"), 2264: D("1973-09-03")}
check("a date another FT number is filed for moves to the day its numbered neighbours count to",
      (D("1973-08-31"), None), f.ft_dated(2262, D("1973-08-30"), held73, True))
check("... and placed() keeps its number there", (2262, None), f.placed(2262, D("1973-08-31"), held73))
held75 = {2829: D("1975-07-15"), 2832: D("1975-07-18"), 2834: D("1975-07-21")}
check("a date out of number order, not vouched for by issue, moves",
      (D("1975-07-19"), None), f.ft_dated(2833, D("1975-07-16"), held75, False))
check("(mirror) one vouched for by issue and filed for no other number stays: the number is the misread",
      (D("1975-07-16"), None), f.ft_dated(2833, D("1975-07-16"), held75, True))
check("(mirror) a date in number order stays", (D("1975-07-19"), None), f.ft_dated(2833, D("1975-07-19"), held75, True))
check("a taken date its numbered neighbours do not settle is refused",
      (None, True), (lambda r: (r[0], bool(r[1])))(f.ft_dated(2262, D("1973-08-30"),
                                                              {2261: D("1973-08-30"), 2264: D("1973-09-08")}, True)))
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
f._HELD_LISTED.clear()  # a new process
f.held_dates("times")
check("held_scans after held_dates parses no file again", [{(url, "1993-01-16"): [19129]}, 2],
      [f.held_scans("times"), len(parsed)])
os.utime(scan_root / "puzzles" / "times" / "1993" / "times-19131.json", ns=(1, 1))
f._HELD_LISTED.clear()  # an in-place change: seen once the listing is HELD_FRESH old
check("a file whose stat moved is parsed again, the other not",
      [{19129: D("1993-01-16"), 19131: D("1993-01-18")}, 3], [f.held_dates("times"), len(parsed)])
f.json.loads = real_loads
# held_dates and held_scans stand per listing version: a re-list finding
# what the last one did keeps the same Held, and a brief inside held_once
# on the listing before neither evicts nor is served the newer one.
kept = f.held_dates("times")
os.utime(scan_root / "puzzles" / "times" / "1993" / "times-19131.json", ns=(2, 2))
f._HELD_LISTED[("times")] = (float("-inf"), *f._HELD_LISTED["times"][1:])  # HELD_FRESH old
check("a re-list finding the same puzzles keeps the same Held", True, f.held_dates("times") is kept)
with f.held_once():
    inside = f.held_dates("times")
    (scan_root / "puzzles" / "times" / "1993" / "times-19132.json").write_text(json.dumps({"date": "1993-01-19"}))
    f._HELD_LISTED["times"] = (float("-inf"), *f._HELD_LISTED["times"][1:])
    now = f.held_dates("times")
    check("held_once keeps its listing's Held while another thread lists afresh", [True, False],
          [now is inside, 19132 in now])
fresh = f.held_dates("times")
check("outside held_once the new listing stands, and stays one object",
      [D("1993-01-19"), True, True], [fresh[19132], f.held_dates("times") is fresh, fresh is not inside])
(scan_root / "puzzles" / "times" / "1993" / "times-19132.json").unlink()
f._HELD_LISTED.clear()
f.ROOT = real_root

# solution_sources links an edition again only when the filed puzzles in its
# hosted_window differ: one filed months away reuses the last link, one the
# day before links afresh, and each equals linked_solutions of that held.
found = {"date": "1993-01-18", "puzzles": [{"number": 19131, "leaf": 3}],
         "solutions": [{"number": 19130, "leaf": 3}]}
d = Path("/nowhere/NewsUK1993UKEnglish/1993-01-18")
base = {19129: D("1993-01-16"), 19000: D("1992-08-17")}
k = (os.fspath(d), f.paper_of(d))
f._LINKED.pop(k, None)
first = f._linked(d, found, f.Held(base))
far = f.Held({**base, 18990: D("1992-08-05")})
again = f._linked(d, found, far)
near = f.Held({**base, 19130: D("1993-01-17")})
check("a puzzle filed far away reuses the link; one in the window relinks",
      [True, f.linked_solutions(f.TIMES, found, far), f.linked_solutions(f.TIMES, found, near), True],
      [again is first, again, f._linked(d, found, near), f._LINKED[k][3] == f.held_between(near, f._LINKED[k][2])])
# Another thread's fold of the ledger holds an equal scan, not the same object.
copy = json.loads(json.dumps(found))
check("an equal scan from another thread's rows reuses the link; a changed one relinks",
      [True, True, f.linked_solutions(f.TIMES, {**copy, "solutions": []}, near)],
      [f._linked(d, copy, near) is f._LINKED[k][4], f._LINKED[k][0] is copy,
       f._linked(d, {**copy, "solutions": []}, near)])
check("hosted_window spans SOLUTION_DAYS after and HOST_REACH days before", (D("1993-01-07"), D("1993-01-25")),
      f.hosted_window(f.TIMES, found))
check("an edition with no headings reads no held", None, f.hosted_window(f.TIMES, {**found, "solutions": []}))
# A 2000s Gale Monday prints the Saturday prize nine days before it ("Solution to Prize Crossword
# 23,420" under 2006-10-23's 23,427): hosted names it, hosted_window reaches it, host_days looks there.
pz = {"date": "2006-10-23", "item": "GaleTimes2006UKEnglish", "puzzles": [{"number": 23427, "leaf": 0}],
      "solutions": [{"number": 23420, "leaf": 0}]}
prize_held = {23420: D("2006-10-14"), 23426: D("2006-10-21")}
check("a Monday of the 2000s hosts the prize of the Saturday nine days before, a 1993 one does not; "
      "hosted_window reaches it", ({23426, 23420}, {23426}, (D("2006-10-12"), D("2006-10-30")), [True, False]),
      (f.hosted(pz, prize_held) & {23426, 23420}, f.hosted({**pz, "date": "1993-01-18"}, prize_held) & {23426, 23420},
       f.hosted_window(f.GALE, pz), [f.prize_monday(D("2006-10-23")), f.prize_monday(D("2006-10-24"))]))
check("a Saturday of 2000 on has the Monday week after as a second host; a weekday has one",
      ([D("2006-10-21"), D("2006-10-23")], [D("2006-10-18")]), (f.host_days(D("2006-10-14")), f.host_days(D("2006-10-17"))))
# Before 1981-07-04 a Saturday's solution prints on the Monday after (1970-05-11 holds 12,463 of 05-09),
# from it a week on (1981-07-11 holds 15,569 of 07-04); hosted reads the Monday's as its title's issue before.
check("a Saturday before 1981-07-04 is hosted by the Monday after, one from it by the Saturday after; "
      "the Monday hosts the Saturday's number",
      ([D("1970-05-11")], [D("1981-06-29")], [D("1981-07-11")], True),
      (f.host_days(D("1970-05-09")), f.host_days(D("1981-06-27")), f.host_days(D("1981-07-04")),
       12463 in f.hosted({"date": "1970-05-11", "item": "GaleTimes1970UKEnglish", "puzzles": [{"number": 12464, "leaf": 0}],
                          "solutions": [{"number": 12463, "leaf": 0}]}, {12463: D("1970-05-09")})))
# No Times on 25 Dec (none in the archive): its solutions print in the next issue; 26 Dec and Good
# Friday only some years, so a host there not on disk has the next issue too.
check("a solution due on 25 Dec or a Sunday prints in the next issue; 26 Dec off disk gives way to the next; "
      "the 27 Dec Monday hosts the 18 Dec Saturday's prize",
      ([D("2007-12-26"), D("2007-12-27")], [D("1993-12-27")], [D("2006-12-23"), D("2006-12-26")], [D("1990-12-26"), D("1990-12-27")],
       [D("2008-12-26")], [D("1974-04-12"), D("1974-04-13")], D("1974-04-11"), True, [D("1993-12-18")]),
      (f.host_days(D("2007-12-24")), f.host_days(D("1993-12-18")), f.host_days(D("2006-12-16"), {D("2006-12-26")}),
       f.host_days(D("1990-12-24"), {D("1990-12-27")}), f.host_days(D("2008-12-24"), {D("2008-12-26")}),
       f.host_days(D("1974-04-11")), f.good_friday(1974) - datetime.timedelta(days=1),
       19417 in f.hosted({"date": "1993-12-27", "item": "GaleTimes1993UKEnglish", "puzzles": [{"number": 19423, "leaf": 0}],
                          "solutions": [{"number": 19417, "leaf": 0}]}, {19417: D("1993-12-18"), 19422: D("1993-12-24")}),
       f.hosts_of(D("1993-12-27"))[-1:]))
_gk = f._PRIZE_HEADINGS_FIX["gale"]
_mon = {"edition": "GaleTimes2009UKEnglish/2009-08-17", "scanKey": _gk[0], "filesHash": "h", "scan": {}}
_tue = {**_mon, "edition": "GaleTimes2009UKEnglish/2009-08-18"}
check("a Gale Monday of the 2000s scanned before the prize headings is due again; its Tuesday, and a scan "
      "by the new code, stand", [False, True, True],
      [f.scan_current(_mon, "h"), f.scan_current(_tue, "h"), f.scan_current({**_mon, "scanKey": f.scan_key(f.GALE)}, "h")])
_bk = f._BAND_WIDTH_FIX["gale"]
_wide = {"edition": "GaleTimes2005UKEnglish/2005-09-05", "scanKey": _bk[0], "filesHash": "h", "scan": {}}
check("a Gale Times day of mid-2005 to mid-2006 scanned before the wider SOLUTION_BAND is due again, "
      "one of 2004 or 2007 and a scan by the new code stand; every pinned paper keeps its old scans",
      [False, True, True, True, True],
      [f.scan_current(_wide, "h"), f.scan_current({**_wide, "edition": "GaleTimes2004UKEnglish/2004-09-06"}, "h"),
       f.scan_current({**_wide, "edition": "GaleTimes2007UKEnglish/2007-09-05"}, "h"),
       f.scan_current({**_wide, "scanKey": f.scan_key(f.GALE)}, "h"),
       all(f.CORPUS_KEYS[v[0]] == {p: f._DAY_HEADING_FIX[p][2]} for p, v in f._GRID_CAP_FIX.items())])
_gk2 = f._GRID_CAP_FIX["gale"]
_wide2 = {"edition": "GaleTimes2005UKEnglish/2005-11-02", "scanKey": _gk2[0], "filesHash": "h", "scan": {}}
check("a Gale Times day of 2005-05 to 2006-09 scanned before the solution grid's cap grew with the page is due "
      "again (the wider band's scan too); one of 2004 or 2007 and a scan by the new code stand",
      [False, False, True, True, True],
      [f.scan_current(_wide2, "h"), f.scan_current({**_wide2, "scanKey": f._BAND_WIDTH_FIX["gale"][0]}, "h"),
       f.scan_current({**_wide2, "edition": "GaleTimes2004UKEnglish/2004-11-02"}, "h"),
       f.scan_current({**_wide2, "edition": "GaleTimes2007UKEnglish/2007-03-16"}, "h"),
       f.scan_current({**_wide2, "scanKey": f.scan_key(f.GALE)}, "h")])
check("every paper's pinned scan key after the grid cap fix is the one the negative-expected fix "
      "pins over, its pinned key the one the dot-leader fix pins over, its the one the day-heading fix pins "
      "over, whose pinned key is its real scan key, and the four fixes' old keys stand under it",
      [True, True, True, True, True],
      [all(v[2] == f._NEG_EXPECTED_FIX[k][0] for k, v in f._GRID_CAP_FIX.items()),
       all(v[2] == f._DOT_LEADER_FIX[k][0] for k, v in f._NEG_EXPECTED_FIX.items()),
       all(v[2] == f._DAY_HEADING_FIX[k][0] for k, v in f._DOT_LEADER_FIX.items()),
       all(v[2] == f.scan_key(next(p for p in (*f.FILERS.values(), *(q for qs in f.ALSO.values() for q in qs)) if p.key == k))
           for k, v in f._DAY_HEADING_FIX.items()),
       all(f.CORPUS_KEYS[o] == {k: f._DAY_HEADING_FIX[k][2]}
           for t in (f._GRID_CAP_FIX, f._NEG_EXPECTED_FIX, f._DOT_LEADER_FIX, f._DAY_HEADING_FIX)
           for k, v in t.items() for o in v[:2])])
_dk, _hk = f._DOT_LEADER_FIX["gale"], f._DAY_HEADING_FIX["gale"]
check("a Gale Times scan made before the dot-leader fix or the day-heading fix stands, a BAND_RESCAN day's too",
      [True, True, True, True],
      [f.scan_current({"edition": "GaleTimes1962UKEnglish/1962-07-28", "scanKey": _dk[0], "filesHash": "h", "scan": {}}, "h"),
       f.scan_current({"edition": "GaleTimes2005UKEnglish/2005-11-02", "scanKey": _dk[0], "filesHash": "h", "scan": {}}, "h"),
       f.scan_current({"edition": "GaleTimes2002UKEnglish/2002-11-23", "scanKey": _hk[0], "filesHash": "h", "scan": {}}, "h"),
       f.scan_current({"edition": "GaleTimes2005UKEnglish/2005-11-02", "scanKey": _hk[0], "filesHash": "h", "scan": {}}, "h")])
_wp, _np = Image.new("L", (4664, 10), 255), Image.new("L", (f.SCAN_WIDTH, 10), 255)
check("a solution grid 510 wide at SCAN_WIDTH is shaped on a 4664 px page (the cap grows with it), not on a "
      "3296 px page, and a puzzle's 1070 on neither", [True, False, False, False],
      [f.solution_shaped(_wp)((0, 0, 720, 720)), f.solution_shaped(_np)((0, 0, 510, 510)),
       f.solution_shaped(_wp)((0, 0, 1510, 1490)), f.solution_shaped(_np)((0, 0, 1070, 1060))])

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
# FT 1985-03-27: the DOWN list opens on "way (3, 2)" (1-down's number and first line lost) and
# "scattered (3, 6)" (13-down's) stands between 10 and 15: the list parses, each tail a clue with no
# number, instead of every light of the reading lost with it.
ft_lost = ftp.clues("""way (3, 2)
2 and 15: They deceive the
pupils (7, 9)
10 Ex-prime minister badly led
by the clergy (9)
scattered (3, 6)
15 See 2 down
17 Rude tot (7)""")
check("a clue tail with its number lost parses as a clue of no number",
      [(set(), "way"), ({2}, "and 15: They deceive the pupils"), ({10}, "Ex-prime minister badly led by the clergy"),
       (set(), "scattered"), ({15}, "See 2 down"), ({17}, "Rude tot")],
      [(c["tokens"][0], " ".join(c["text"].split())) for c in ft_lost[0]])
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
f._HELD_LISTED.clear()  # a new process
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
# A series' snapshot carries its parses to a new process, keyed on each file's stat.
f.HELD_SERIES_CACHE = str(hp / "series_cache")
f._HELD_LISTED.clear(); f._HELD.clear(); f._HELD_SAVED.clear()
f.held_files("zz")
f._HELD.clear(); f._HELD_LISTED.clear()
f._load_series_snapshot("zz")
check("series snapshot holds the series' parses", True, any("/zz/" in k for k in f._HELD))
f.HELD_SERIES_CACHE = None
# Across briefs the last listing stands while no year folder moved and it
# is under HELD_FRESH old: no file is stat'ed again. A file filed (its
# folder moves) is seen at once; an in-place rewrite once HELD_FRESH passes.
f._HELD_LISTED.clear()
base = sorted(n for n, _ in f.held_files("zz"))
real_stat, stats = Path.stat, []
Path.stat = lambda self, *a, **k: stats.append(self) or real_stat(self, *a, **k)
again = sorted(n for n, _ in f.held_files("zz"))
Path.stat = real_stat
check("held_files reuses its listing while no folder moved (no file stat'ed)", (base, []), (again, stats))
time.sleep(0.01)
(hp / "puzzles" / "zz" / "1999" / "zz-4.json").write_text('{"date": "1999-01-04"}')
check("a new file moves its folder: held_files lists again at once", base + [4],
      sorted(n for n, _ in f.held_files("zz")))
time.sleep(0.01)
(hp / "puzzles" / "zz" / "1999" / "zz-4.json").write_text('{"date": "1999-03-04", "x": 1}')
stale = dict(f.held_files("zz"))[4][0]
real_fresh, f.HELD_FRESH = f.HELD_FRESH, 0
fresh = dict(f.held_files("zz"))[4][0]
f.HELD_FRESH = real_fresh
check("an in-place rewrite stands HELD_FRESH, then is read",
      (datetime.date(1999, 1, 4), datetime.date(1999, 3, 4)), (stale, fresh))
# Under HELD_FRESH, a folder that moved is listed again alone: the other
# folders' files keep their entries, unstat'ed.
(hp / "puzzles" / "zz" / "2000").mkdir()
(hp / "puzzles" / "zz" / "2000" / "zz-5.json").write_text('{"date": "2000-01-05"}')
f.held_files("zz")
time.sleep(0.01)
(hp / "puzzles" / "zz" / "2000" / "zz-6.json").write_text('{"date": "2000-01-06"}')
listed, real_scandir = [], os.scandir  # files are stat'ed through scandir entries, so watch the folders listed
def watch_scandir(path, *a, **k):
    listed.append(Path(path).name)
    return real_scandir(path, *a, **k)
os.scandir = watch_scandir
moved = dict(f.held_files("zz"))
os.scandir = real_scandir
check("a moved folder is listed again alone, the others' entries kept",
      (base + [4, 5, 6], datetime.date(2000, 1, 6), ["2000"]),
      (sorted(moved), moved[6][0], [n for n in listed if n != "zz"]))  # "zz" is the series folder's own listing
f.ROOT = real_root
# plan() lists a settled dir once (dir_cache.seen): a replaced file, a new edition or
# a moved ledger row each make an edition due again; a fresh dir is not kept.
import scan_queue, time
f.vlm.reachable = lambda *a, **k: False
# The real corpus holds Times puzzles of these 1981 days filed without every
# answer, which would make the fixture's editions solution hosts (HOST_SCAN):
# the plan below is of the fixture alone.
real_answerless, f.answerless_puzzles = f.answerless_puzzles, lambda *a, **k: {}
pc =Path(os.environ["TMP"]) / "plancache"
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
# Every plan below is the paper's PaperPlan brought up to date row by row;
# each is checked against the paper planned whole afresh (no memo kept).
plan_diffs = []
def checked_plan(paper, cache):
    kept = f.plan(paper, cache)
    with f.held_once():
        whole = f._plan_paper_fresh(paper, cache, None, None, (), None)
    if list(kept) != list(whole):
        plan_diffs.append((list(kept), list(whole)))
    return kept
due = lambda: [(u["kind"], u["rel"].split("/")[1], u["reason"]) for u in sum(checked_plan(f.TIMES, pc), [])]
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
    return [(u["rank"], u["reason"]) for u in checked_plan(f.TIMES, pc)[1] if u["rel"].endswith("_1")]
check("a stale host of an answerless puzzle ranks 2; of a Saturday prize six on; else, refused or answered, 3",
      [[(2, "scan stale, answers missing")], [(2, "scan stale, answers missing")], [(3, "scan stale")],
       [(3, "scan stale")], [(3, "scan stale")]],
      [e1_reason("1981-02-02", {"number": 15435}), e1_reason("1981-01-31", {"number": 15430}),
       e1_reason("1981-01-31", {"number": 15435}), e1_reason("1981-02-02", {"number": 15435, "refused": True}),
       e1_reason("1981-02-02", {"number": 15435, "solutionFrom": "1981-02-03 leaf 1"})])
def stale_fixed(verdict):
    scan_queue.append(pl, [{**stale, "verdicts": [verdict]}, settled_row(e2)])
    return [(u["rank"], u["reason"]) for u in checked_plan(f.TIMES, pc)[1] if u["rel"].endswith("_1")]
check("a stale scan's read a reader fix can change ranks with the fixes, not the whole corpus",
      [[(2, "solution short, its cells unclassified")], [(2, "refused not-a-grid before its fix")],
       [(3, "scan stale")]],
      [stale_fixed({"number": 15436, "solutionFrom": "x", "solution": {"accepted": 20, "lights": 30}}),
       stale_fixed({"number": 15436, "refused": True, "cause": "not-a-grid"}),
       stale_fixed({"number": 15436, "solutionFrom": "x", "solution": {"accepted": 30, "lights": 30}})])
# The answerless puzzle's own edition ranks 2 too, its read waiting on the
# host's scan; not when no edition is dated within SOLUTION_DAYS after it
# (e2 is three months on), as nothing it waits on can link a heading.
check("a stale edition of its own answerless puzzle ranks 3 with no edition within SOLUTION_DAYS after it",
      [(3, "scan stale")], stale_fixed({"number": 15436}))
e4 = pc / "NewsUK1981UKEnglish" / "1981-02-04_4"
e4.mkdir()
(e4 / "pages.json").write_text("{}")
settle(e4, e4.parent, pc)
check("and 2 with one: the next issue, whose scan its read waits on",
      [(2, "scan stale, answers missing")], stale_fixed({"number": 15436}))
scan_queue.append(pl, [settled_row(e4)])
check("an answered or refused one still ranks 3", [[(3, "scan stale")], [(3, "scan stale")]],
      [stale_fixed({"number": 15436, "solutionFrom": "x", "solution": {"accepted": 30, "lights": 30}}),
       stale_fixed({"number": 15436, "refused": True})])
# A "scan stale" read unit_skip calls VLM-only (its puzzle held) is dropped, unless likely() has it
# "answers linked" (a heading links now the puzzle filed with every clue and no answers): then it is
# "scan stale, answers linked", answers_only's CPU read, not skipped before likely() runs.
real_skip, real_row_likely = f.unit_skip, f._row_likely
f.unit_skip = lambda *a, **k: "already held (VLM-only reason)"
try:
    answered = {"number": 15436, "solutionFrom": "x", "solution": {"accepted": 30, "lights": 30}}
    check("a stale read held already is skipped as VLM-only", [], stale_fixed(answered))
    f._row_likely = lambda st, series, rel, row, solutions: (
        ({f.LIKELY[0]: 1}, ()) if rel.endswith("_1") else real_row_likely(st, series, rel, row, solutions))
    check("... but not when its answers are linked now: it is read answers-only",
          [(f.RANKS[f.STALE_SCAN[2]], f.STALE_SCAN[2])], stale_fixed(answered))
finally:
    f.unit_skip, f._row_likely = real_skip, real_row_likely
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
due()
kept_plan = f._PAPER_PLANS[(str(pc), f.TIMES.key, str(f.ledger_of(pc, f.TIMES)))]
before = dict(kept_plan.reasons)
scan_queue.append(pl, [{**settled_row(e1), "readAt": "2026-02-01T00:00:00+00:00"}])
due()
check("a ledger row landing works its own edition out again, no other", ["1981-02-03_1"],
      sorted(rel.split("/")[1] for rel, hit in kept_plan.reasons.items() if before.get(rel) is not hit))
check("each plan brought up to date row by row equals the paper planned whole", [], plan_diffs)
f.answerless_puzzles = real_answerless
# A read start links every sister edition's headings (sister_solutions):
# kept until the sister ledger or the series' filed puzzles move.
linked, real_linked, real_held_dates = [], f.linked_solutions, f.held_dates
f.linked_solutions = lambda *a: (linked.append(a[0]), real_linked(*a))[1]
try:
    f.sister_solutions(pc, f.GALE)
    linked.clear()
    f.sister_solutions(pc, f.GALE)
    check("an unmoved sister ledger and filed puzzles: no heading linked again", [], linked)
    def cold():
        """sister_solutions with every memo of it dropped."""
        keep = dict(f._LINKED), dict(f._SISTER_LINKS)
        f._LINKED.clear()
        f._SISTER_LINKS.clear()
        try:
            return f.sister_solutions(pc, f.GALE)
        finally:
            f._LINKED.clear()
            f._LINKED.update(keep[0])
            f._SISTER_LINKS.clear()
            f._SISTER_LINKS.update(keep[1])
    scan_queue.append(pl, [settled_row(e1)])
    got, again = f.sister_solutions(pc, f.GALE), list(linked)
    check("the sister ledger appended to with unchanged scans: nothing linked again, the same links",
          ([], cold()), (again, got))
    linked.clear()
    f.held_dates = lambda series: f.Held({**real_held_dates(series), 99999: datetime.date(1999, 1, 1)})
    got, again = f.sister_solutions(pc, f.GALE), list(linked)
    check("a puzzle filed outside every edition's hosted_window: nothing linked again, the same links",
          ([], cold()), (again, got))
    linked.clear()
    f.held_dates = lambda series: f.Held({**real_held_dates(series), 15558: datetime.date(1981, 6, 21)})
    got, again = f.sister_solutions(pc, f.GALE), list(linked)
    check("one filed beside an edition with headings links it again, as a cold link does",
          (True, cold()), (bool(again), got))
finally:
    f.linked_solutions, f.held_dates = real_linked, real_held_dates
# filed.jsonl is every PAPERS run's ledger: a Guardian (or FT, Telegraph) row's heading under a Times number
# is that paper's puzzle's, never linked as the Times's (times-6003 took 7 answers off the FT's "No 6003").
real_linked_fn = f._linked
f._linked = lambda d, scan, held, paper=None: (
    [{"number": 424242, "leaf": 1}] if d.parent.name.startswith("TheGuardian") else real_linked_fn(d, scan, held, paper))
try:
    scan_queue.append(pl, [{"edition": "TheGuardian1981UKEnglish/1981-06-22_9",
                            "scan": {"date": "1981-06-22", "puzzles": [], "solutions": [{"number": 424242, "leaf": 1}]}}])
    check("a Guardian row in filed.jsonl links no heading as the Times's", False,
          424242 in f.sister_solutions(pc, f.GALE))
finally:
    f._linked = real_linked_fn
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
check("1987 weekday title with WORD lost to the print", [6319],
      [n for n, _, _ in f.ft_headings([line("FT  CROSS PUZZLE No. 6,319", 291, 2180)])[0]])
check("a lone \"cross\" and a number is no title", [],
      f.ft_headings([line("cross No. 6,319", 291, 2180)])[0])
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
pz = f.build(20540, datetime.date(1996, 1, 4), g, "image",
             {"1-across": ("Like ignis", "3", None), "4-across": ("Ancient patriarch", "3", None)},
             "TheGuardian1996UKEnglish", 15, series="cryptic", name="Cryptic crossword No 20,540",
             printed={"1-across": ["ignis", "gone"], "4-across": ["patriarch"]})
check("a built clue carries its asPrinted, only tokens of its text",
      {1: ["ignis"], 4: ["patriarch"]},
      {e["number"]: e["clue"]["asPrinted"] for e in pz["entries"] if e["clue"].get("asPrinted")})

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
# A blog's answers stand: only a blank light is filled, solutions.partial shrinks to the blanks left.
held = answered(["BAT", None, "TEA", None])
held["solutions"] = {"origin": "writeup", "blog": "b", "partial": ["1-down", "4-across"]}
got = f.merge_answers(held, answered(["BAY", "BAD", None, "DOX"]), reread=True)
check("a blog-keyed file keeps its answers on a reread, fills a blank not crossing a held letter, and shrinks partial",
      ({"1-down": "BAD"}, ["BAT", "BAD", "TEA", None], ["4-across"]),
      (got, [e["solution"] for e in held["entries"]], held["solutions"].get("partial")))
got = f.merge_answers(held, answered([None, None, None, "DOA"]), reread=True)
check("the last blank filled drops solutions.partial, the origin stays",
      ({"4-across": "DOA"}, False, "writeup"),
      (got, "partial" in held["solutions"], held["solutions"]["origin"]))
check("another tool's filing takes no answers", {},
      f.merge_answers(answered([None] * 4, tool="other"), answered(["BAT", None, None, None])))

# answers_only(): a title whose clues are filed whole and whose solution grid is
# linked now is read from the solution grid alone (no clue OCR): the held file's
# clues with the grid's answers, merged by decide() and never laid over by a
# whole reading; the full read when the held file is short of a clue, another
# tool's, from another page, or answered already. A held answer the grid reads otherwise is
# settled light by light (settle_held), not the whole reading refused.
def lights_held(sols, tool=f.TOOL, url="u"):
    lights = [(1, "across", 0, 0, 3), (1, "down", 0, 0, 3), (2, "down", 2, 0, 3), (3, "across", 0, 2, 3)]
    return {"id": "times-1", "number": 1, "source": {"acquiredBy": tool, "url": url, "gridOrigin": "published"},
            "dimensions": {"cols": 3, "rows": 3},
            "entries": [{"number": n, "direction": d, "position": {"x": x, "y": y}, "length": k,
                         "clue": {"text": f"clue {n} {d} words", "enumeration": str(k)}, "solution": s}
                        for (n, d, x, y, k), s in zip(lights, sols)]}
import copy
ao_held = [lights_held([None] * 4)]
ao_read = [{"1-across": "BAT", "1-down": "BED", "2-down": "TOE", "3-across": "DOE"}]
ao_stubbed = {n: getattr(f, n) for n in ("paper_of", "filed_number", "held_file", "page_url", "complete", "solved", "solution_source")}
f.paper_of = lambda d: f.TIMES
f.filed_number = lambda d, found, hit: (hit["number"], None, None)
f.held_file = lambda series, n: copy.deepcopy(ao_held[0])
f.page_url = lambda d, found, leaf: "u"
f.complete = lambda p: True
ao_seen = []
f.solved = lambda sol, grid, above=False, lean=False, enums=None: (
    ao_seen.append(enums) or (dict(ao_read[0]), {"accepted": len(ao_read[0]), "lights": 4, **ao_extra[0]}))
ao_extra = [{}]
f.solution_source = lambda sol: "src"
ao_args = (Path("NewsUK/1990-08-22_1"), {}, {"number": 1, "leaf": 3}, {1: {"dir": Path("NewsUK/1990-08-23_1")}})
ao_kept = f._KEEP_VLM["names"]
f._KEEP_VLM["names"] = set()
verdict, puzzle = f.answers_only(*ao_args)
check("an answers-linked title with its clues held is read off the solution grid alone: the held clues, each answer the grid read",
      (True, 0, 4, ["clue 1 across words", "clue 1 down words", "clue 2 down words", "clue 3 across words"],
       ["BAT", "BED", "TOE", "DOE"]),
      (verdict["answersOnly"], verdict["vlmAsks"], verdict["answers"], [e["clue"]["text"] for e in puzzle["entries"]],
       [e["solution"] for e in puzzle["entries"]]))
ao_held[0] = lights_held(["BAT", None, None, None])
check("a held answer the grid reads alike stands", ["BAT", "BED", "TOE", "DOE"],
      [e["solution"] for e in f.answers_only(*ao_args)[1]["entries"]])
ao_held[0] = lights_held(["BAD", None, None, None])
verdict, puzzle = f.answers_only(*ao_args)
check("a held answer the grid reads otherwise, failing a crossing the grid's word fits, gives way to it (not the "
      "whole reading refused: times-5432's AIDE for AIRS)",
      (["BAT", "BED", "TOE", "DOE"], {"1-across": {"held": "BAD", "read": "BAT", "took": "read"}}),
      ([e["solution"] for e in puzzle["entries"]], verdict["solution"]["heldClash"]))
# Held words the grid reads as other words fitting every crossing give way too: the held answers are older
# reads of the same grid (10-25: RIKSDAG for RIGSDAG, TITIS for TITUS, the reading right on every one).
ao_held[0] = lights_held(["BAT", None, "TOE", None])
ao_read[0] = {"1-across": "BAD", "1-down": "BED", "2-down": "DOE", "3-across": "DOE"}
verdict, puzzle = f.answers_only(*ao_args)
# Since 10-25 a letter read otherwise must be checked by a crossing light not itself clashing: here each
# differing letter is the one cell 1-across and 2-down share (one misread cell is no evidence for
# either), so both held words stand (times-7267's OOS for DOS, its first letter unchecked: COS).
check("held words whose differing letter only another clashing light crosses stand; the other answers file",
      (["BAT", "BED", "TOE", "DOE"], {"1-across": {"held": "BAT", "read": "BAD", "took": "held"},
                                     "2-down": {"held": "TOE", "read": "DOE", "took": "held"}}),
      ([e["solution"] for e in puzzle["entries"]], verdict["solution"]["heldClash"]))
check("settle_held: a read word whose differing letter a crossing checks gives way; one unchecked stands",
      ("read", "held"),
      (f.settle_held(lights_held(["BAD", None, None, None])["entries"],
                     {"1-across": "BAT", "1-down": "BED", "2-down": "TOE"})[2]["1-across"]["took"],
       f.settle_held(lights_held(["BAD", None, None, None])["entries"],
                     {"1-across": "BAT", "1-down": "BED"})[2]["1-across"]["took"]))
check("settle_held: a read answer crossing a kept held one on another letter goes with it",
      ({"3-across": "DOE"}, {"1-across": "BAT"}),
      f.settle_held(lights_held(["BAT", None, "TOE", None])["entries"],
                    {"1-across": "BAD", "1-down": "ZED", "3-across": "DOE"})[:2])
check("settle_held: a blog's held answer always stands", "held",
      f.settle_held(lights_held(["BAD", None, None, None])["entries"],
                    {"1-across": "BAT", "1-down": "BED", "2-down": "TOE"}, blog=True)[2]["1-across"]["took"])
# Another puzzle's grid (wrong_grid): its reading gives other words than 2+ held answers, agreeing on fewer
# (times-11998 off July's 11998), or a held neighbour holds more of its answers (times-21706 off 21707's).
check("wrong_grid: OCR slips and one whole-word clash are this puzzle's grid; two whole-word clashes are not",
      (None, None, True),
      (f.wrong_grid(lights_held(["BAD", None, "TOD", None])["entries"], ao_read[0], "times", 1),
       f.wrong_grid(lights_held(["SUN", "BED", None, None])["entries"], ao_read[0], "times", 1),
       "2 held answers" in (f.wrong_grid(lights_held(["SUN", None, "ZIP", None])["entries"], ao_read[0], "times", 1) or "")))
ao_held[0] = lights_held(["SUN", None, "ZIP", None])
ao_read[0] = {"1-across": "BAT", "1-down": "BED", "2-down": "TOE", "3-across": "DOE"}
verdict, puzzle = f.answers_only(*ao_args)
check("answers_only files nothing off another puzzle's grid (times-11998, times-20109)",
      (None, True, "src"), (puzzle, "another puzzle's" in verdict["skip"], verdict["solutionFrom"]))
ao_held[0] = lights_held([None] * 4)
real_ao_held = f.held_file
f.held_file = lambda series, n: lights_held(["BAT", "BED", "TOE", None]) if n == 2 else copy.deepcopy(ao_held[0])
try:
    verdict, puzzle = f.answers_only(*ao_args)
    check("... nor off a held neighbour's grid (times-21706 read off 21707's)", (None, True),
          (puzzle, "No 2's" in verdict["wrongGrid"]))
finally:
    f.held_file = real_ao_held
# HELD_CLASH requeues a held file whose grid's reading clashes with a held answer as an OCR slip (each
# clashing light within CLASH_LETTERS letters), not a reading of another puzzle's grid (whole words apart).
check("slip_clash: a held answer read a letter or two otherwise is a slip; a word apart, or no clash, is not",
      [True, False, False],
      [f.slip_clash(lights_held(["BAD", None, None, None]), {"1-across": "BAT", "1-down": "BED"}),
       f.slip_clash(lights_held(["BAD", None, None, None]), {"1-across": "ZOO"}),
       f.slip_clash(lights_held(["BAD", None, None, None]), {"1-across": "BAD", "1-down": "BED"})])
ao_held[0] = lights_held([None] * 4)
ao_read[0] = {"1-across": "BAT", "1-down": "BED", "2-down": "TOE", "3-across": "DOE"}
ao_held[0] = lights_held([None] * 4)
ao_read[0] = {"1-across": "BAT", "1-down": "XED"}
check("two answers crossing on different letters leave it to the full read", None, f.answers_only(*ao_args))
ao_read[0] = {"1-across": "BAT", "2-down": "TOES"}
check("an answer the light's length does not fit leaves it to the full read", None, f.answers_only(*ao_args))
ao_read[0] = {"1-across": "BAT"}
ao_held[0] = lights_held(["BAT", "BED", "TOE", "DOE"])
check("a puzzle answered whole needs no read", None, f.answers_only(*ao_args))
ao_held[0] = lights_held([None] * 4, tool="other")
check("another tool's file is read in full", None, f.answers_only(*ao_args))
ao_held[0] = lights_held([None] * 4, url="elsewhere")
check("a file from another page is read in full", None, f.answers_only(*ao_args))
ao_held[0] = lights_held([None] * 4)
f._KEEP_VLM["names"] = {"1990-08-22_1"}
check("an edition asked to be read again is read in full", None, f.answers_only(*ao_args))
f._KEEP_VLM["names"] = set()
ao_held[0]["entries"][1]["clue"].pop("enumeration")
# The grid reads every light (ao_read was left at {"1-across": "BAT"} by the checks above).
ao_read[0] = {"1-across": "BAT", "1-down": "BED", "2-down": "TOE", "3-across": "DOE"}
verdict, puzzle = f.answers_only(*ao_args)
check("a held clue filed with no enumeration is no reason for the full read: its answers merge, no VLM ask (times-24146 1-across)",
      (True, 0, ["BAT", "BED", "TOE", "DOE"], "clue 1 down words"),
      (verdict["answersOnly"], verdict["vlmAsks"], [e["solution"] for e in puzzle["entries"]], puzzle["entries"][1]["clue"]["text"]))
check("... and the grid's reading is given no enumeration for it", None, ao_seen[-1][(1, "down")])
# decide(): an answers-only reading merges into the held file even where complete() refuses its clues (a word
# OCR made up: suspect); with --out it went to the --out copy and the held file never took one (10-25, times-18329).
import tempfile
ao_held[0] = lights_held([None] * 4)
with tempfile.TemporaryDirectory() as dd_dir:
    (Path(dd_dir) / "held-1.json").write_text(json.dumps(lights_held([None] * 4)))
    dd_where = []
    f.complete = lambda p: False
    verdict, puzzle = f.answers_only(*ao_args)
    f.decide(verdict, puzzle, "times", dd_dir, set(), lambda where, p, v: dd_where.append(where and where[0]) or True,
             path=lambda where, series, puzzles: Path(dd_dir) / f"{where[0]}-{where[1]}.json")
    f.complete = lambda p: True
check("an answers-only reading of a held file complete() refuses merges its answers into the held file, not --out",
      (["held"], ["BAT", "BED", "DOE", "TOE"]), (dd_where[1:], sorted((verdict.get("answered") or {}).values())))
# decide(): an answers-only reading drops no held answer it gives none for (10-22..25: 312 Times files lost 986
# so, times-7522 all 26 for a reading that took none); only a named rule (held_drops) or a crossing read blanks one.
def ao_decide(held, read, crossed=False):
    ao_held[0] = held
    ao_read[0] = read
    with tempfile.TemporaryDirectory() as hd_dir:
        (Path(hd_dir) / "held-1.json").write_text(json.dumps(held))
        v, p = f.answers_only(*ao_args, crossed=crossed)
        f.decide(v, p, "times", hd_dir, set(), lambda where, p, vv: True,
                 path=lambda where, series, puzzles: Path(hd_dir) / f"{where[0]}-{where[1]}.json")
        return v, [e["solution"] for e in json.loads((Path(hd_dir) / "held-1.json").read_text())["entries"]]
verdict, sols = ao_decide(lights_held(["BAT", "BED", None, None]), {"2-down": "TOE", "3-across": "DOE"})
check("an answers-only reread keeps each held answer it did not read again (times-4766's GREET, MERRIMENT)",
      (["BAT", "BED", "TOE", "DOE"], {"2-down": "TOE", "3-across": "DOE"}), (sols, verdict.get("answered")))
verdict, sols = ao_decide(lights_held(["BAT", "BED", None, None]), {})
check("... one that reads none changes nothing", (["BAT", "BED", None, None], None), (sols, verdict.get("answered")))
verdict, sols = ao_decide(lights_held(["BAT", None, None, None]), {"2-down": "POE", "3-across": "DOE"})
check("... a read answer crossing a held one on another letter takes the light, named heldCrossed",
      ([None, None, "POE", "DOE"], ["1-across"]), (sols, verdict["solution"].get("heldCrossed")))
check("held_drops: heldMisread lights and each heldClash light settle_held dropped", {"1-down", "1-across"},
      f.held_drops({"solution": {"heldMisread": ["1-down"], "heldClash": {"1-across": {"took": "dropped"},
                                                                          "2-down": {"took": "read"}}}}))
held = lights_held(["BAT", "BED", None, None])
check("merge_answers drop: a held light named goes though not read, the rest stand",
      ({"1-down": None, "3-across": "DOE"}, ["BAT", None, None, "DOE"]),
      (f.merge_answers(held, lights_held([None, None, None, "DOE"]), drop={"1-down"}), [e["solution"] for e in held["entries"]]))
ao_held[0] = lights_held([None] * 4)
ao_read[0] = {"1-across": "BAT", "1-down": "BED", "2-down": "TOE", "3-across": "DOE"}
# decide(): a full reading not complete() (a clue blank) of a puzzle held with every clue merges its answers into the
# held file, not --out; only blank held lights take one, crossing no held letter on another, and no held answer goes
# (10-25: 227 Times grids, 3,825 answers in their --out copies).
def uh_decide(held, sols, solution=True):
    reading = lights_held(sols)
    reading["entries"][3]["clue"] = {"text": ""}
    with tempfile.TemporaryDirectory() as uh_dir:
        (Path(uh_dir) / "held-1.json").write_text(json.dumps(held))
        where = []
        v = {"number": 1, **({"solution": {"accepted": 4, "lights": 4}} if solution else {})}
        f.complete = lambda p: False
        f.decide(v, reading, "times", uh_dir, set(), lambda w, p, vv: where.append(w and w[0]) or True,
                 path=lambda w, series, puzzles: Path(uh_dir) / f"{w[0]}-{w[1]}.json")
        f.complete = lambda p: True
        return where[1:], v.get("answered"), v.get("heldWhole"), v.get("unfiled")
check("a full reading with a clue blank fills a held file with every clue: its blank lights, the held answer kept",
      (["held"], {"1-down": "BED", "2-down": "TOE", "3-across": "DOE"}, True, None),
      uh_decide(lights_held(["BIT", None, None, None]), ["BAT", "BED", "TOE", "DOE"]))
check("... an answer crossing a held letter on another stays out",
      (["held"], {"2-down": "TOE", "3-across": "DOE"}, True, None),
      uh_decide(lights_held(["BIT", None, None, None]), ["BAT", "XED", "TOE", "DOE"]))
uh_blank = lights_held([None] * 4)
uh_blank["entries"][2]["clue"] = {"text": ""}
check("... a held file with a clue blank: the reading goes to --out as before",
      ["out"], uh_decide(uh_blank, ["BAT", "BED", "TOE", "DOE"])[0])
check("... another tool's held file: --out as before",
      ["out"], uh_decide(lights_held([None] * 4, tool="other"), ["BAT", "BED", "TOE", "DOE"])[0])
check("merge_answers keep: no held answer changes or goes, a blank light crossing it otherwise stays blank",
      ({"2-down": "TOE"}, ["BIT", "BAD", "TOE", None]),
      (lambda held: (f.merge_answers(held, lights_held(["BAT", "XED", "TOE", None]), keep=True),
                     [e["solution"] for e in held["entries"]]))(lights_held(["BIT", "BAD", None, None])))
# full_read_answers(): a full read's answers off the solution grid take answers_only's checks (checked_answers:
# misread_word, uncrossed, settle_held against the held file), not filed as the grid gave them.
fr_real = {n: getattr(f, n) for n in ("misread_word", "uncrossed")}
fr_seen = []
f.misread_word = lambda w, enum=None: w == "BEX"
f.uncrossed = lambda answers, grid, enums=None, probs=None: (
    fr_seen.append((sorted(answers), probs is not None)) or ({"2-down"} & set(answers)))
try:
    ao_held[0] = lights_held(["BAD", None, None, "DOE"])
    fr_reading = lights_held([None] * 4)
    fr_args = ({"dir": Path("NewsUK/1990-08-23_1"), "number": 1}, f.trove_solution_ocr.puzzle_grid(fr_reading),
               {"1-across": "BAT", "1-down": "BEX", "2-down": "TOE", "3-across": "DOE"}, {"accepted": 4})
    answers, info = f.full_read_answers(f.TIMES, 1, fr_reading, *fr_args)
    check("a full read's answers: a misread goes, an uncrossed misread goes (the classifier asked), a held answer "
          "the grid reads otherwise on an unchecked letter stands (settle_held)",
          ({"1-across": "BAD", "3-across": "DOE"}, ["1-down"], ["2-down"], "held", 2,
           [(["1-across", "2-down", "3-across"], True)]),
          (answers, info.get("misread"), info.get("uncrossed"), info["heldClash"]["1-across"]["took"],
           info["accepted"], fr_seen))
    check("... a paper whose cells are not classified, and a refused reading, are filed as read",
          ([{"1-across": "BAT", "1-down": "BEX", "2-down": "TOE", "3-across": "DOE"}, {"accepted": 4}], {"refused": "x"}),
          (list(f.full_read_answers(f.FT, 1, fr_reading, *fr_args)),
           f.full_read_answers(f.TIMES, 1, fr_reading, *fr_args[:3], {"refused": "x"})[1]))
finally:
    for n, fn in fr_real.items():
        setattr(f, n, fn)
# decide(): a full read that read the solution grid drops no held answer it gives none for (no reread drop since
# 10-25, as answers-only): a held answer goes only by held_drops (heldMisread, a dropped clash) or a crossing read.
def fr_decide(held, sols, solution):
    ao_held[0] = held
    with tempfile.TemporaryDirectory() as fr_dir:
        (Path(fr_dir) / "held-1.json").write_text(json.dumps(held))
        v = {"number": 1, "solutionFrom": "src", "solution": solution}
        made = []
        f.decide(v, lights_held(sols), "times", fr_dir, set(),
                 lambda w, p, vv: made.append((w, [e["solution"] for e in p["entries"]])) or True,
                 path=lambda w, series, puzzles: Path(fr_dir) / f"{w[0]}-{w[1]}.json")
        return [s for w, s in made if w and w[0] == "held"][-1:]
check("a full read keeps each held answer it did not read again (before 10-25 a reread blanked them)",
      [["BAT", "BED", "TOE", "DOE"]],
      fr_decide(lights_held(["BAT", "BED", None, None]), [None, None, "TOE", "DOE"], {"accepted": 2, "lights": 4}))
check("... but for a held answer a named rule drops (heldMisread)",
      [["BAT", None, "TOE", "DOE"]],
      fr_decide(lights_held(["BAT", "BED", None, None]), [None, None, "TOE", "DOE"],
                {"accepted": 2, "lights": 4, "heldMisread": ["1-down"]}))
ao_held[0] = lights_held([None] * 4)
# unenumerated_held(): a row read before REREAD_UNENUMERATED that linked a grid, whose held puzzle is short of
# answers and has a clue with no enumeration, is read again once (fix_reason).
import tempfile
with tempfile.TemporaryDirectory() as ue_dir:
    ue_path = Path(ue_dir) / "times-1.json"
    ue_path.write_text(json.dumps(ao_held[0]))
    ue_old = f._HELD_PATH.get((f.TIMES.series, 1))
    f._HELD_PATH[f.TIMES.series, 1] = ue_path
    ue_row = {"edition": "NewsUK1990UKEnglish/1990-08-22_1", "readAt": "2026-10-22T16:00:00+00:00",
              "verdicts": [{"number": 1, "id": "times-1", "solutionFrom": "1990-08-23 leaf 0",
                            "solution": {"lights": 4, "accepted": 4}}]}
    check("a row read before the fix, its held puzzle short of answers with a clue bare of its count, is due",
          True, f.unenumerated_held(ue_row))
    check("... not once read after it", False, f.unenumerated_held({**ue_row, "readAt": "2026-10-22T16:31:00+00:00"}))
    check("... nor one read by answers_only", False, f.unenumerated_held({**ue_row, "verdicts": [{**ue_row["verdicts"][0], "answersOnly": True}]}))
    ue_held = lights_held([None] * 4)
    ue_path.write_text(json.dumps(ue_held))
    check("... nor with every clue counted", False, f.unenumerated_held(ue_row))
    # short_unfitted(): this solution code's full read left the grid 1 to STRIP_MAX lights short of a
    # puzzle held with every clue and no answer: read again once, answers-only (SHORT_UNFITTED).
    su_row = {**ue_row, "solutionKey": f.solution_key(),
              "verdicts": [{**ue_row["verdicts"][0], "solution": {"lights": 4, "accepted": 2}}]}
    su_v = su_row["verdicts"][0]
    check("a grid this code read two lights short, its puzzle held with every clue and no answer, is due",
          [True, 2, True, True],
          [f.short_unfitted(su_row), f.RANKS[f.SHORT_UNFITTED], f.SHORT_UNFITTED in f.SOLUTION_FIXES,
           f.keeps_vlm(f.SHORT_UNFITTED, {}, {}) is False])
    check("... not three short, nor whole, nor read after REREAD_SHORT_FITTED, nor by answers_only, nor by other code",
          [False] * 5,
          [f.short_unfitted({**su_row, "verdicts": [{**su_v, "solution": {"lights": 4, "accepted": 1}}]}),
           f.short_unfitted({**su_row, "verdicts": [{**su_v, "solution": {"lights": 4, "accepted": 4}}]}),
           f.short_unfitted({**su_row, "readAt": "2026-10-24T05:00:00+00:00"}),
           f.short_unfitted({**su_row, "verdicts": [{**su_v, "answersOnly": True}]}),
           f.short_unfitted({**su_row, "solutionKey": "old"})])
    if ue_old is None:
        del f._HELD_PATH[f.TIMES.series, 1]
    else:
        f._HELD_PATH[f.TIMES.series, 1] = ue_old
# held_titles(): a Gale Times page whose scan by current code finds no title, the one puzzle held for its
# date filed from it with every clue and not every answer (1956-09-15's 8,235, the 09-17 page printing its
# solution), is read answers-only under that number (HELD_TITLE), once, no VLM ask.
import datetime
with tempfile.TemporaryDirectory() as ht_dir:
    ht_ed = Path(ht_dir) / "GaleTimes1956UKEnglish" / "1956-09-15"
    ht_ed.mkdir(parents=True)
    ht_url = "https://go.gale.com/ps/retrieve.do?docId=GALE%7CCS235362095"
    (ht_ed / "pages.json").write_text(json.dumps({"url": ht_url, "date": "1956-09-15", "crossword_pages": [{"leaf": 0}]}))
    ht_file = Path(ht_dir) / "times-8235.json"
    ht_held = {"number": 8235, "source": {"acquiredBy": f.TOOL, "url": ht_url}, "entries": []}
    ht_file.write_text(json.dumps(ht_held))
    ht_saved = (f.held_dates, f.filed_state, f.current_keys, f._HELD_PATH.get((f.SERIES, 8235)))
    # held_titles matches the page's own pages.json url: the real page_url, not the answers_only cases' "u" stub.
    ht_page_url, f.page_url = f.page_url, ao_stubbed["page_url"]
    ht_days = [{8235: datetime.date(1956, 9, 15)}]
    ht_state = [(False, True)]
    f.held_dates = lambda series: f.Held(ht_days[0])
    f.filed_state = lambda series, n: ht_state[0] if n == 8235 else None
    f.current_keys = lambda paper: frozenset({"cur"})
    f._HELD_PATH[f.SERIES, 8235] = ht_file
    ht_row = {"edition": "GaleTimes1956UKEnglish/1956-09-15", "inputs": "x", "scanKey": "cur",
              "readAt": "2026-10-23T23:33:53+00:00",
              "scan": {"date": "1956-09-15", "item": "GaleTimes1956UKEnglish", "puzzles": [],
                       "solutions": [{"number": 8234, "leaf": 0, "box": [0, 0, 1, 1]}]}}
    ht_hit = {"number": 8235, "leaf": 0, "box": None, "heldTitle": True}
    check("an untitled page whose held puzzle, filed from it, waits on its answers is read under its number",
          [[ht_hit], [ht_hit], 2, True, False],
          [f.held_titles(ht_row, ht_dir), f.held_titled(ht_row, ht_dir)["puzzles"], f.RANKS[f.HELD_TITLE],
           f.HELD_TITLE in f.SOLUTION_FIXES, f.keeps_vlm(f.HELD_TITLE, {}, {})])
    ht_none = [f.held_titles({**ht_row, "readAt": "2026-10-25T07:00:00+00:00"}, ht_dir),
               f.held_titles({**ht_row, "scanKey": "old"}, ht_dir),
               f.held_titles({**ht_row, "scan": {**ht_row["scan"], "puzzles": [{"number": 8235, "leaf": 0}]}}, ht_dir),
               f.held_titles({**ht_row, "verdicts": [{"number": 8236}]}, ht_dir),
               f.held_titles({**ht_row, "verdicts": [{"number": 8235, "refused": True}]}, ht_dir),
               f.held_titles({**ht_row, "verdicts": [{"number": 8235}, {"number": 8236}]}, ht_dir),
               f.held_titles({k: v for k, v in ht_row.items() if k != "inputs"}, ht_dir)]
    # 10-25: 82 Times rows whose one verdict, the held puzzle's, an older scan read under the title the
    # current scan lost (1982-07-19's 15,885) stood "inputs changed", no held title read.
    check("an untitled page whose one verdict is its held puzzle's is read under that number too",
          [[ht_hit], [ht_hit]],
          [f.held_titles({**ht_row, "verdicts": [{"number": 8235, "id": "times-8235"}]}, ht_dir),
           f.held_titles({**ht_row, "verdicts": [{"number": 9, "read_as": 8235}]}, ht_dir)])
    ht_state[0] = (True, True)
    ht_none.append(f.held_titles(ht_row, ht_dir))
    ht_state[0] = (False, False)
    ht_none.append(f.held_titles(ht_row, ht_dir))
    ht_state[0] = (False, True)
    ht_days[0] = {8235: datetime.date(1956, 9, 15), 8236: datetime.date(1956, 9, 15)}
    ht_none.append(f.held_titles(ht_row, ht_dir))
    ht_days[0] = {8235: datetime.date(1956, 9, 15)}
    ht_file.write_text(json.dumps({**ht_held, "source": {"acquiredBy": f.TOOL, "url": "elsewhere"}}))
    ht_none.append(f.held_titles(ht_row, ht_dir))
    ht_file.write_text(json.dumps({**ht_held, "source": {"acquiredBy": "other", "url": ht_url}}))
    ht_none.append(f.held_titles(ht_row, ht_dir))
    check("... not read after REREAD_HELD_TITLE, by older scan code, with a title, a verdict of another number, "
          "refused, or two verdicts, never read, its puzzle answered whole or a clue short, two held that day, "
          "from another page or another tool", [[]] * 12, ht_none)
    f.held_dates, f.filed_state, f.current_keys = ht_saved[:3]
    f.page_url = ht_page_url
    if ht_saved[3] is None:
        del f._HELD_PATH[f.SERIES, 8235]
    else:
        f._HELD_PATH[f.SERIES, 8235] = ht_saved[3]
# read_puzzle(): a held title is read answers-only with no VLM ask, and never in full.
ht_calls = []
ht_ao, ht_rp = f.answers_only, f.read_page
f.answers_only = lambda *a, **k: ht_calls.append(k) or None
f.read_page = lambda *a, **k: (_ for _ in ()).throw(AssertionError("a held title read in full"))
ht_v, ht_p = f.read_puzzle(None, {"puzzles": [ht_hit]}, ht_hit, {})
f.answers_only, f.read_page = ht_ao, ht_rp
check("a held title its grid gives no answers is skipped, its answers read with no VLM ask",
      (None, True, 8235, [{"ask_vlm": False, "crossed": True}]), (ht_p, "skip" in ht_v, ht_v["number"], ht_calls))
# uncrossed(): an answer with a cell another light crosses unanswered is left out (one pass).
# 3x3 grid, its middle cell black: 1-across, 1-down, 2-down, 3-across round the edge.
ht_grid = [list("..."), list(".#."), list("...")]
check("an answer a letter of which only it gives, where another light crosses unanswered, is left out",
      [set(), {"1-across", "3-across"}],
      [f.uncrossed({"1-across": "BAT", "1-down": "BOG", "2-down": "TIN", "3-across": "GUN"}, ht_grid),
       f.uncrossed({"1-across": "BAT", "1-down": "BOG", "3-across": "GUN"}, ht_grid)])
check("... and one no word, its unchecked middle letter checked by nothing (10,927's RUSSUM for RUSTUM)",
      {"1-down"}, f.uncrossed({"1-across": "BAT", "1-down": "BXG", "2-down": "TIN", "3-across": "GUN"}, ht_grid))
import inspect
import numpy as np
def uc_reads(rows, at=None):
    # {cell: probabilities}: each cell reads its letter of `rows` at .97, or at[cell]'s letter at .95 (its own .02).
    out = {}
    for r, row in enumerate(rows):
        for c, ch in enumerate(row):
            if ch == "#":
                continue
            p = np.full(26, 0.0004)
            p[tso.AZ.index(ch)] = 0.97
            if at and (r, c) in at:
                p[tso.AZ.index(ch)], p[tso.AZ.index(at[r, c])] = 0.02, 0.95
            out[r, c] = p
    return out


uc_rows = ["BAT", "O#A", "GUN"]
uc_part = {"1-across": "BAT", "1-down": "BOG", "3-across": "GUN"}
check("... unless the classifier reads its lone letters as filed: one read as another letter making a listed word "
      "(8,564's BATES, its B read .035 under P: PATES) is left out, one read as no word is not; "
      "no crop read leaves every one out",
      [set(), {"1-across"}, set(), {"1-across", "3-across"}],
      [f.uncrossed(uc_part, ht_grid, probs=lambda: uc_reads(uc_rows)),
       f.uncrossed(uc_part, ht_grid, probs=lambda: uc_reads(uc_rows, {(0, 1): "I"})),
       f.uncrossed(uc_part, ht_grid, probs=lambda: uc_reads(uc_rows, {(0, 1): "X"})),
       f.uncrossed(uc_part, ht_grid, probs=lambda: None)])
check("misread_rival names the word", ["BIT", None],
      [f.misread_rival("BAT", [(1, (0, 1), "A")], uc_reads(uc_rows, {(0, 1): "I"})),
       f.misread_rival("BAT", [(1, (0, 1), "A")], uc_reads(uc_rows))])
# rival_stands: the rival is filed for an answer no corpus answer when it is one, or a word where the
# answer is none (AGHASI: AGHAST); a corpus answer (SETH: NETH) or a word read as no corpus answer stays out.
uc_corpus = tso.corpus_words
try:
    tso.corpus_words = lambda: {"AGHAST", "SETH", "BIT"}
    check("rival_stands takes AGHAST for AGHASI and GARDENERS for GARDENEDS, not NETH for SETH nor ELICKER for FLICKER",
          [True, True, False, False],
          [f.rival_stands("AGHASI", "AGHAST", "6"), f.rival_stands("GARDENEDS", "GARDENERS", "9"),
           f.rival_stands("SETH", "NETH", "4"), f.rival_stands("FLICKER", "ELICKER", "7")])
    uc_rivals = {}
    uc_out = f.uncrossed(uc_part, ht_grid, probs=lambda: uc_reads(uc_rows, {(0, 1): "I"}), rivals=uc_rivals)
    check("uncrossed names the rival that stands for an answer it leaves out", ({"1-across"}, {"1-across": "BIT"}),
          (uc_out, uc_rivals))
    tso.corpus_words = lambda: {"BAT", "BIT"}
    uc_rivals = {}
    f.uncrossed(uc_part, ht_grid, probs=lambda: uc_reads(uc_rows, {(0, 1): "I"}), rivals=uc_rivals)
    check("... none when the answer filed is a corpus answer itself", {}, uc_rivals)
finally:
    tso.corpus_words = uc_corpus
check("... and the crop is not read when no answer would be left out",
      set(), f.uncrossed({"1-across": "BAT", "1-down": "BOG", "2-down": "TIN", "3-across": "GUN"}, ht_grid,
                         probs=lambda: (_ for _ in ()).throw(AssertionError("crop read"))))
check("answers-only reads of every reason take the check (crossed by default)",
      True, inspect.signature(f.answers_only).parameters["crossed"].default)
ao_held[0] = lights_held([None] * 4)
ao_held[0]["entries"][2]["clue"]["text"] = ""
check("a held file with a blank clue is read in full", None, f.answers_only(*ao_args))
ao_held[0] = lights_held([None] * 4)
ao_held[0]["entries"][2]["clue"]["text"] = "-clue 2 down words"
ao_read[0] = {"1-across": "BAT", "1-down": "BED", "2-down": "TOE", "3-across": "DOE"}
verdict, puzzle = f.answers_only(*ao_args)
check("a held clue the readers left unsettled (a stray mark) is kept as filed: the answers merge, no VLM ask",
      (True, 0, "-clue 2 down words", "TOE"),
      (verdict["answersOnly"], verdict["vlmAsks"], puzzle["entries"][2]["clue"]["text"], puzzle["entries"][2]["solution"]))
check("the held clues' enumerations go to the grid's reading", {(1, "across"): "3", (1, "down"): "3", (2, "down"): "3", (3, "across"): "3"},
      ao_seen[-1])
# A light the grid's reading left (at most STRIP_MAX of them) is asked of the VLM once, as its row of
# squares with the letters its crossings hold: the word stands when it fits the light, agrees with
# each crossing, is listed, and the classifier finds each letter possible (14047: PLAT for FLAT).
import numpy as np
import trove_solution_ocr as tso
ao_held[0] = lights_held([None] * 4)
ao_read[0] = {"1-across": "BAT", "1-down": "BED", "2-down": "TOE"}
cells4 = np.full((30, 30), 255, np.uint8)
png4 = tso.light_strip(cells4, [0, 10, 20, 30], [0, 10, 20, 30], [(2, 0), (2, 1), (2, 2)])
check("a light's strip is a PNG", b"\x89PNG", __import__("base64").b64decode(png4)[:4])
flat = [1 / 26] * 26
ruled_out = [1 / 26] * 26
ruled_out[tso.AZ.index("I")] = 0.0
ao_extra[0] = {"strips": {"3-across": {"png": png4, "p": [flat, flat, flat]}}}
ao_asked = []
real_vlm = (f.vlm.ask, f.vlm.wanted)
f.vlm.wanted = lambda: True
try:
    for reply, probs4, want, why in (("DOE", [flat] * 3, "DOE", "the word the VLM names stands"),
                                      ("DOE\n", [flat] * 3, "DOE", "a reply's first line is its word"),
                                      ("DIE", [flat, ruled_out, flat], None, "a letter the classifier rules out is not taken"),
                                      ("DOES", [flat] * 3, None, "a word of another length is not taken"),
                                      ("BOE", [flat] * 3, None, "a word against a crossing letter is not taken"),
                                      ("DXE", [flat] * 3, None, "a word that is not listed is not taken"),
                                      ("", [flat] * 3, None, "no reply takes nothing")):
        ao_extra[0] = {"strips": {"3-across": {"png": png4, "p": probs4}}}
        f.vlm.ask = lambda img, prompt, max_tokens=1500, reply=reply: ao_asked.append(prompt) or reply
        verdict, puzzle = f.answers_only(*ao_args)
        check(f"VLM fallback: {why}", (want, "strips" in verdict["solution"]), (puzzle["entries"][3]["solution"], False))
    check("it is asked once, with the crossings' letters in the prompt", (7, True),
          (len(ao_asked), "D?E" in ao_asked[0] and "one word of 3 letters" in ao_asked[0]))
    ao_extra[0] = {"strips": {"3-across": {"png": png4, "p": [flat] * 3}}}
    f.vlm.ask = lambda *a, **k: (_ for _ in ()).throw(f.vlm.Spooled("spooled"))
    verdict, puzzle = f.answers_only(*ao_args)
    check("a spooled ask leaves the light unread (the read runs again once it is answered)", None, puzzle["entries"][3]["solution"])
    check("the VLM's lights are named in the verdict, not their pictures", (None, None),
          (verdict["solution"].get("strips"), verdict["solution"].get("vlmLights")))
    f.vlm.ask = lambda *a, **k: "DOE"
    verdict, puzzle = f.answers_only(*ao_args)
    check("the VLM's light is named and counted", (["3-across"], 4), (verdict["solution"]["vlmLights"], verdict["solution"]["accepted"]))
finally:
    f.vlm.ask, f.vlm.wanted = real_vlm
ao_extra[0] = {}
def cell_p(ch, p=0.9):
    v = [(1 - p) / 25] * 26
    v[tso.AZ.index(ch)] = p
    return v
check("a name no lexicon lists is not taken even where the classifier reads it alike (BALINITY for SALINITY)", None,
      f.vlm_word("BALINITY", "?ALINITY", [8], [cell_p(c) for c in "BALINITY"]))
check("a listed word the classifier finds possible is taken", "SALINITY",
      f.vlm_word("SALINITY", "?ALINITY", [8], [cell_p(c) for c in "SALINITY"]))
check("the VLM's word against the classifier's floor is not taken", None,
      f.vlm_word("PLAT", "?L?T", [4], [flat, cell_p("L"), cell_p("F"), cell_p("T")]))
def faint(word, at, p=0.005, rival="B"):
    """cell_p of `word`, its cell `at` read as `rival` (0.9) with the word's letter at `p`, under VLM_FLOOR."""
    cells = [cell_p(c) for c in word]
    cells[at] = [(0.1 - p) / 24] * 26
    cells[at][tso.AZ.index(rival)], cells[at][tso.AZ.index(word[at])] = 0.9, p
    return cells
check("a listed word one cell under the floor stands where its crossings leave the classifier no likelier "
      "listed word (LATITUDINARIANS' L at 0.003)", "SALINITY",
      f.vlm_word("SALINITY", "?ALINITY", [8], faint("SALINITY", 0)))
check("...not two cells under (CUBER), nor where the classifier decodes another listed word (HOSTER for HOSIER)",
      (None, None),
      (f.vlm_word("SALINITY", "?A?INITY", [8], faint("SALINITY", 0)[:2] + faint("SALINITY", 2, rival="T")[2:]),
       f.vlm_word("PLAT", "?L?T", [4], faint("PLAT", 0, rival="F"))))
check("a name no list holds, its letters the classifier's too and its count the clue's, is taken (PERSHORE)", "PERSHORE",
      f.vlm_word("PERSHORE", "?E?S?O?E", [8], [cell_p(c) for c in "PERSHORE"], "8"))
check("...even with BALINITY's count: SALINITY lies one open letter off", None,
      f.vlm_word("BALINITY", "?ALINITY", [8], [cell_p(c) for c in "BALINITY"], "8"))
check("...not with a letter the classifier reads unsure (STROGONOFF, its O at 0.38)", None,
      f.vlm_word("PERSHORE", "?E?S?O?E", [8], [cell_p(c, 0.38 if i == 6 else 0.9) for i, c in enumerate("PERSHORE")], "8"))
check("...nor with no count of its own (a linked light's \"See 8\") or a count it does not fill", (None, None),
      (f.vlm_word("PERSHORE", "?E?S?O?E", [8], [cell_p(c) for c in "PERSHORE"], None),
       f.vlm_word("PERSHORE", "?E?S?O?E", [8], [cell_p(c) for c in "PERSHORE"], "5,9")))
check("pieces of an enumeration: a phrase's words, else the light whole", ([4, 4, 3, 3], [12], [9], [4, 5]),
      (tso.pieces_of("4,4,3,3", 14), tso.pieces_of("4,4,3,3", 12), tso.pieces_of(None, 9), tso.pieces_of("4-5", 9)))
f._KEEP_VLM["names"] = ao_kept
# A reread due for its solution grid alone (SOLUTION_FIXES) is not kept for the VLM: answers_only reads
# it first (fitted reads, the VLM's strips); a refusal's fix, a forced unit and a bug reread still are.
real_fix = f.fix_reason
try:
    f.fix_reason = lambda row: row.get("fix")
    check("keeps_vlm: solution-only fixes read answers-only first; the rest keep the VLM",
          [False, False, False, True, True, True, False],
          [f.keeps_vlm("solution short, its cells unclassified", {"fix": "solution short, its cells unclassified"}, {}),
           f.keeps_vlm("inputs changed", {"fix": "answers held back by a clue with no enumeration"}, {}),
           f.keeps_vlm("solution short, read by other code", {}, {}),
           f.keeps_vlm("refused not-a-grid before its fix", {"fix": "refused not-a-grid before its fix"}, {}),
           f.keeps_vlm("solution short, read by other code", {}, {"force": True}),
           f.keeps_vlm(None, {}, None),
           f.keeps_vlm("inputs changed", {}, {})])
finally:
    f.fix_reason = real_fix

for n, fn in ao_stubbed.items():
    setattr(f, n, fn)

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
lead = ({(1, "across"): "CAT"}, {"cellsSure": 7, "blocks": 1.0}, {(0, 0): "C", (0, 1): "A", (0, 2): "T", (2, 2): "D"}, {})
other = ({(1, "across"): "COT", (1, "down"): "COB", (3, "across"): "BED", (2, "down"): "TOR"},
         {"cellsSure": 5, "blocks": 1.0}, {}, {})
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
# The leader's sure letters in a light it did not accept veto another
# lattice's word only where they still spell a word: 15921's leader read
# PROVISO as PB?VISO and NEWLOOK as NEWL?QK, its own cut's misreads, while
# NONET read as NONER (15549) stays in doubt.
def framed(lead_sure):
    tso.framings = lambda gray, grid: [("o", 0, 0), ("l", 0, 0)]
    tso.read_lattice = lambda g, ys, xs, grid: {"o": ({(3, "across"): "BED"}, {"cellsSure": 5, "blocks": 1.0}, {}, {}),
                                                "l": ({}, {"cellsSure": 7, "blocks": 1.0}, lead_sure, {})}[g]
    try:
        return tso.read_framed(os.path.join(os.environ["TMP"], "grid3.png"), grid3)[0].get((3, "across"))
    finally:
        tso.framings, tso.read_lattice = real_framings, real_lattice
check("a leader's sure misread spelling no word does not veto another lattice's word",
      "BED", framed({(2, 0): "B", (2, 1): "Q", (2, 2): "D"}))
check("a leader's sure letter spelling another word leaves the light unread",
      None, framed({(2, 0): "B", (2, 1): "E", (2, 2): "G"}))
# agreed_reads(): two lattices reading a light surely in every cell as the
# one listed word among its whole reads take it, though its numbered cell's
# glyph match refused it (16752 REPINED, 14290 EGGDANCE); a rival whole read
# that is a word leaves it unread (17469 DOUR, read with its number as BOUR).
def lattices(word, *printed):
    cells = [(0, i) for i in range(len(word))]
    return {(1, "across"): cells}, [({}, {"cellsSure": 9}, dict(zip(cells, word)), {(1, "across"): set(p)})
                                    for p in printed]
check("two lattices reading every cell as the one word among the whole reads take it",
      {(1, "across"): "REPINED"}, tso.agreed_reads(*lattices("REPINED", {"REPINED", "AEPINED"}, {"HEPINED"})))
check("a rival whole read that is a word leaves the light unread",
      {}, tso.agreed_reads(*lattices("BOUR", {"BOUR"}, {"BOUR", "DOUR"})))
lts, one = lattices("REPINED", {"REPINED"})
check("one lattice reading every cell is not two",
      {}, tso.agreed_reads(lts, one + [({}, {"cellsSure": 9}, {}, {})]))
# swapped_reads(): 1990s Times prints read an R as a sure A; the one listed
# word an A-to-R swap makes is taken (18976 ESCAITOIRE, 18471 WOAKSHY), but
# an R is never swapped to an A (BRLLOON stays unread, not BALLOON).
def swapped(word):
    lts = {(1, "across"): [(0, i) for i in range(len(word))]}
    every = dict(zip(lts[(1, "across")], word))
    return tso.swapped_reads(lts, every, {(1, "across"): {word}}, {}, every)
check("a sure A whose swap to R makes the one word a letter away is that word",
      {(1, "across"): "ESCRITOIRE"}, swapped("ESCAITOIRE"))
check("a sure R is not swapped to an A", {}, swapped("BRLLOON"))
# The cell classifier: a second reader of a Times print's cells. Each cell's
# 26 probabilities; a light is decoded as the listed word they make likeliest
# by CLASS_MARGIN over the next, its accepted crossings' letters held (8059's
# STONECROP, read by the recogniser as STONECBAD).
def sure_cells(word, p=0.99, at=(0, 0), across=True):
    out = {}
    for i, ch in enumerate(word):
        v = np.full(26, (1 - p) / 25)
        if ch != "?":
            v[tso.AZ.index(ch)] = p
        else:
            v[:] = 1 / 26
        out[(at[0], at[1] + i) if across else (at[0] + i, at[1])] = v
    return out
row = {(1, "across"): [(0, i) for i in range(9)]}
check("a light whose cells read surely is decoded as its listed word",
      {(1, "across"): "STONECROP"}, tso.classified_reads(row, {}, sure_cells("STONECROP")))
check("cells that make two listed words alike likely decode neither",
      {}, tso.classified_reads({(1, "across"): [(0, i) for i in range(4)]}, {}, sure_cells("RI?E")))
import hashlib
cross = {(1, "across"): [(0, 0), (0, 1), (0, 2), (0, 3)], (2, "down"): [(0, 2), (1, 2), (2, 2)]}
check("an accepted crossing's letter settles the cell the classifier cannot",
      {(1, "across"): "RIDE"}, tso.classified_reads(cross, {(2, "down"): "DUE"}, sure_cells("RI?E")))
check("a word whose letter the classifier rules out is not decoded",
      {}, tso.classified_reads(row, {}, {**sure_cells("STONECROP"), (0, 6): np.eye(26)[tso.AZ.index("B")] * 0.999 + 0.001 / 26}))
check("an accepted light the classifier reads otherwise is vetoed where a crossing light decodes against it too; "
      "on its own cells alone (UNION, SINAI on a 1974 print), or one it agrees with, it is not",
      ({(1, "across")}, set(), set()),
      (tso.vetoed(cross, {(1, "across"): "RIDE"}, {**sure_cells("?UE", at=(0, 2), across=False), **sure_cells("RICE")}),
       tso.vetoed(row, {(1, "across"): "STONECROP"}, {**sure_cells("STONECROP"), (0, 6): np.eye(26)[1] * 0.9999 + 1e-6}),
       tso.vetoed(row, {(1, "across"): "STONECROP"}, sure_cells("STONECROP"))))
check("a crossing the classifier reads otherwise pins no decoded light (14043: TIRINGS held, PREFERRER not taken)",
      {}, tso.classified_reads(cross, {(2, "down"): "CUE"}, {**sure_cells("?UE", at=(0, 2), across=False),
                                                              **sure_cells("RIDE")}))
# fitted_reads(): a light the classifier's top letters make words of its enumeration's pieces,
# with no other listed word that fits (24229: WENT OVER THE TOP, 4,4,3,3, no listed word as one).
phrase = {(9, "down"): [(i, 0) for i in range(14)]}
phrase_p = sure_cells("WENTOVERTHETOP", p=0.8, across=False)
check("a phrase of listed words, each cell read surely, is taken by its enumeration", {(9, "down"): "WENTOVERTHETOP"},
      tso.fitted_reads(phrase, {}, phrase_p, {(9, "down"): "4,4,3,3"}))
check("the same cells with no enumeration are no listed word", {}, tso.fitted_reads(phrase, {}, phrase_p, {}))
check("an enumeration that does not add up to the light is not used", {},
      tso.fitted_reads(phrase, {}, phrase_p, {(9, "down"): "4,4,3,2"}))
check("a piece that is no word leaves the light unread", {},
      tso.fitted_reads(phrase, {}, sure_cells("WENTOVERTHETXP", p=0.8, across=False), {(9, "down"): "4,4,3,3"}))
check("a cell read below FIT_TOP leaves the light unread", {},
      tso.fitted_reads(phrase, {}, sure_cells("WENTOVERTHETOP", p=0.5, across=False), {(9, "down"): "4,4,3,3"}))
rival_p = sure_cells("RIDE")
rival_p[(0, 2)] = np.full(26, 0.001)
rival_p[(0, 2)][tso.AZ.index("D")] = 0.9
rival_p[(0, 2)][tso.AZ.index("C")] = 0.07
check("a light with a rival word a letter off at 5% or more (RIDE, RICE) is not taken", {},
      tso.fitted_reads({(1, "across"): [(0, i) for i in range(4)]}, {}, rival_p, {}))
rival_p[(0, 2)][tso.AZ.index("C")] = 0.01
check("a rival under 5% leaves the one word", {(1, "across"): "RIDE"},
      tso.fitted_reads({(1, "across"): [(0, i) for i in range(4)]}, {}, rival_p, {}))
def margin_p(rival):
    out = sure_cells("RIDE")
    out[(0, 2)] = np.full(26, 0.001)
    out[(0, 2)][tso.AZ.index("D")] = 0.97
    out[(0, 2)][tso.AZ.index("C")] = rival
    return out
check("a light decodes at 50 to 1 over its rival word (RIDE 0.97, RICE 0.015) and not at 20 to 1 (0.05)",
      ({(1, "across"): "RIDE"}, {}),
      (tso.classified_reads(row4 := {(1, "across"): [(0, i) for i in range(4)]}, {}, margin_p(0.015)),
       tso.classified_reads(row4, {}, margin_p(0.05))))
check("a crossing's letter the classifier rules out stops it", {},
      tso.fitted_reads(cross, {(2, "down"): "CUE"}, {**sure_cells("?UE", at=(0, 2), across=False), **sure_cells("RIDE")}, {}))
# A surname cmudict alone lists is no word to win a margin (times-13764, 1974: the classifier
# decoded TROEGER for TRIGGER at 50 to 1, its I and G misread): it stands only where every cell
# not held reads it at UNLISTED_TOP, as a word no list holds does.
check("TROEGER is cmudict's alone; TRIGGER and ROAN are words", (True, False, False),
      (tso.name_only("TROEGER"), tso.name_only("TRIGGER"), tso.name_only("ROAN")))
row7 = {(1, "across"): [(0, i) for i in range(7)]}
check("a cmudict-only name read at 0.8 a cell is not decoded, at 0.99 it is; a word at 0.8 is",
      ({}, {(1, "across"): "TROEGER"}, {(1, "across"): "TRIGGER"}),
      (tso.classified_reads(row7, {}, sure_cells("TROEGER", p=0.8)),
       tso.classified_reads(row7, {}, sure_cells("TROEGER")),
       tso.classified_reads(row7, {}, sure_cells("TRIGGER", p=0.8))))
check("nor is it fitted at 0.8 a cell", ({}, {(1, "across"): "TROEGER"}),
      (tso.fitted_reads(row7, {}, sure_cells("TROEGER", p=0.8), {}),
       tso.fitted_reads(row7, {}, sure_cells("TROEGER"), {})))
check("the cell model on disk is the one CELL_MODEL_SHA names", True,
      hashlib.sha256(tso.CELL_MODEL.read_bytes()).hexdigest() == tso.CELL_MODEL_SHA)
glyphs = {(0, 0): np.zeros((tso.GLYPH + 2 * tso.GLYPH_SHIFT,) * 2, np.float32)}
check("the classifier gives each cell 26 probabilities summing to one", (26, True),
      (len(tso.classified(glyphs)[(0, 0)]), abs(tso.classified(glyphs)[(0, 0)].sum() - 1) < 1e-4))
# read_framed(classify=True): the classifier vetoes and decodes on the best
# lattice, only where its blocks are surely the puzzle's.
def framed_classify(blocks):
    tso.framings = lambda gray, grid: [("l", [0, 1, 2, 3], [0, 1, 2, 3])]
    tso.read_lattice = lambda g, ys, xs, grid: ({(1, "across"): "CAT"}, {"cellsSure": 7, "blocks": blocks}, {}, {})
    real_classified = tso.classified
    tso.classified = lambda glyphs: {**sure_cells("CAT"), **sure_cells("COB", across=False),
                                     **sure_cells("BED", at=(2, 0)), **sure_cells("TOD", at=(0, 2), across=False)}
    real_glyph = tso.glyph
    tso.glyph = lambda g, ys, xs, r, c: None
    try:
        return tso.read_framed(os.path.join(os.environ["TMP"], "grid3.png"), grid3, classify=True)
    finally:
        tso.framings, tso.read_lattice, tso.classified, tso.glyph = real_framings, real_lattice, real_classified, real_glyph
got, info = framed_classify(1.0)
check("a sure grid's other lights are decoded by the classifier",
      ({(1, "across"): "CAT", (1, "down"): "COB", (3, "across"): "BED", (2, "down"): "TOD"}, 3, 0),
      (got, info["classified"], info["vetoed"]))
check("a grid whose blocks read unsure is not classified", ({(1, "across"): "CAT"}, None),
      (framed_classify(0.9)[0], framed_classify(0.9)[1].get("classified")))
# numbered_swaps(): a clue number makes its cell's sure read a misread
# (15839 BVEREAT, 17215 YMPLORE); the one listed word a change of that cell
# makes is taken, where half the lights crossing it are accepted. A plain
# cell's change (BEEIZEBUB) is left to plain_swaps; a light in a grid read
# around it so little that the crop may be another day's is not taken
# (20372 TSQUARE).
def settled(swaps, word, crossings_accepted):
    across = [(1, i) for i in range(len(word))]
    lts = {(2, "across"): across, (1, "down"): [(0, 1), (1, 1)], (3, "down"): [(0, 3), (1, 3)]}
    accepted = {(1, "down"): "A" + word[1]} if crossings_accepted else {}
    return swaps(lts, accepted, [{}, dict(zip(across, word))])
check("a numbered cell's sure misread one letter from the only listed word is that word",
      {(2, "across"): "OVEREAT"}, settled(tso.numbered_swaps, "BVEREAT", True))
check("a plain cell's misread is not swapped", {}, settled(tso.numbered_swaps, "BEEIZEBUB", True))
check("a light whose crossings are mostly unread is not swapped", {}, settled(tso.numbered_swaps, "BVEREAT", False))
# listed_reads(): a sure read that is a listed word stands though its
# numbered cell's glyph match refused it (16684 MOWGLI, 15870 REALLY), unless
# another letter in that cell makes a listed word too (16777 BINNER for
# DINNER, 17469 BOUR for DOUR), or half its crossings are unread.
check("a sure listed read whose numbered cell no other letter fits stands",
      {(2, "across"): "MOWGLI"}, settled(tso.listed_reads, "MOWGLI", True))
check("a sure listed read whose numbered cell another letter makes a word of is unread",
      {}, settled(tso.listed_reads, "BINNER", True))
check("a sure listed read whose crossings are mostly unread is unread", {}, settled(tso.listed_reads, "MOWGLI", False))
# plain_swaps(): a plain cell's sure misread one letter from exactly one
# listed word is that word (15883 BEEIZEBUB, 19638 AOVENTURE); a second word
# a letter away (15883 BRANG: BHANG, BRAND) leaves it unread.
check("a plain cell's sure misread one letter from the only listed word is that word",
      {(2, "across"): "BEELZEBUB"}, settled(tso.plain_swaps, "BEEIZEBUB", True))
check("a sure misread a letter from two listed words is unread", {}, settled(tso.plain_swaps, "BRANG", True))
# whole_listed(): a heavy print's light read whole as one listed word is
# that word where accepted crossings hold every cell a letter's change makes
# another listed word in (15901 PETAL beside PINUP); where a crossing is
# unread, the read's first glyph may be an F (FETAL) and the light stays
# unread; a whole read an accepted crossing contradicts is no word there.
def whole(read, held_cols, crossing="PETAL"):
    lts = {(5, "across"): [(1, j) for j in range(5)]}
    lts.update({(j + 1, "down"): [(0, j), (1, j)] for j in range(5)})
    accepted = {(j + 1, "down"): "X" + crossing[j] for j in held_cols}
    return tso.whole_listed(lts, accepted, [{(5, "across"): set(read)}])
check("a whole read whose every changeable cell a crossing holds is taken",
      {(5, "across"): "PETAL"}, whole({"PETAL"}, range(5)))
check("a whole read with a changeable cell no crossing holds is unread", {}, whole({"PETAL"}, range(1, 5)))
check("a rival whole read a crossing contradicts leaves the word",
      {(5, "across"): "PETAL"}, whole({"PETAL", "PEDAL"}, range(5)))
check("a whole read a crossing contradicts is unread", {}, whole({"FETAL"}, range(5)))
# mended_reads(): an accepted light whole_listed() reads otherwise with it
# left out is that word (15901 FETAL, its first cell PINUP's P); one it
# reads alike, or not at all, stands.
def mended(accepted_word, read, held_cols):
    lts = {(5, "across"): [(1, j) for j in range(5)]}
    lts.update({(j + 1, "down"): [(0, j), (1, j)] for j in range(5)})
    accepted = {(j + 1, "down"): "X" + "PETAL"[j] for j in held_cols}
    return tso.mended_reads(lts, {**accepted, (5, "across"): accepted_word}, [{(5, "across"): set(read)}])
check("an accepted light its crossings and whole read settle otherwise is mended",
      {(5, "across"): "PETAL"}, mended("FETAL", {"PETAL"}, range(5)))
check("an accepted light read alike stands", {}, mended("PETAL", {"PETAL"}, range(5)))
check("an accepted light whose changed cell no crossing holds stands", {}, mended("FETAL", {"PETAL"}, range(1, 5)))
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
classify_seen = []
def fake(path, grid, tight=False, bounded=False, classify=False, lean=False, **kw):
    seen.append((Image.open(path).size, tight, bounded))
    classify_seen.append(classify)
    return {(1, "across"): "ABC"}, {"blocks": stats_blocks}
trove_solution_ocr.read_answers = fake
sol = {"dir": ed, "leaf": 3, "number": 7, "box": (100, 100, 400, 140)}
stats_blocks = 1.0
got, _ = f.read_solution(f.page(ed, 3), sol, ["..."])
check("solution answers keyed as fill() reads them, the grid cropped tight at 3x and read on its own rules",
      ({"1-across": "ABC"}, ((352 * 3, 352 * 3), True, True)), (got, seen[0]))
check("a Times edition's solution grid is read with the cell classifier (CELLS_CLASSIFIED)", True,
      classify_seen[0])
# A crop another cut left at the path is never read: each read cuts afresh.
stale = f.CROPS / "solutions" / f"{ed.name}_7.png"
Image.new("L", (90, 90), 255).save(stale)
seen.clear()
f.read_solution(f.page(ed, 3), sol, ["..."])
check("a solution crop saved by other code is not reused: the grid is cut again", (352 * 3, 352 * 3), seen[0][0])
stats_blocks = 0.8
got, info = f.read_solution(f.page(ed, 3), sol, ["..."])
check("a solution grid whose blocks are not the puzzle's gives no answers", ({}, True), (got, "refused" in info))
stats_blocks = 0.9
got, info = f.read_solution(f.page(ed, 3), sol, ["..."])
check("...and a noisy print of the puzzle's grid gives its bounded lights", ({"1-across": "ABC"}, False),
      (got, "refused" in info))
# A grid joined to a photo under it (1993: 344x426 ink, 103 refused for it) or to a
# neighbour's text beside it is read as its square part, and refused only when no cut's
# blocks are the puzzle's.
stats_blocks = 1.0
for name, rect, want in (("tall", (110, 160, 460, 640), 1), ("wide", (110, 160, 640, 510), 1)):
    led = Path(os.environ["TMP"]) / ("ed_" + name); led.mkdir()
    pg = Image.new("L", (1200, 1400), 255)
    ImageDraw.Draw(pg).rectangle(rect, fill=0)
    pg.save(led / "leaf_0003.jpg")
    seen.clear()
    got, info = f.read_solution(f.page(led, 3), {**sol, "dir": led}, ["..."])
    # The leaf is a JPEG: its ringing at the box's edges moves the Otsu cut a pixel or two
    # (the tall box's square part is 350 wide, not 352), so the cut is square and 352 +- 3.
    check(f"a {name} ink box (a grid and what is joined to it) is read as its square part",
          ({"1-across": "ABC"}, True, True),
          (got, seen[0][0][0] == seen[0][0][1], abs(seen[0][0][0] - 352 * 3) <= 3 * 3))
    stats_blocks = 0.8
    seen.clear()
    got, info = f.read_solution(f.page(led, 3), {**sol, "dir": led}, ["..."])
    check(f"...and a {name} one no cut of which has the puzzle's blocks is refused", ({}, True, True),
          (got, "refused" in info, len(seen) >= 1))
    stats_blocks = 1.0
# A heading box that lost its first words (Gale 2012: 137px of a 357px grid) cuts the grid's
# left and foot off the window: the window grows while the ink touches its edges.
stats_blocks = 1.0
seen.clear()
got, _ = f.read_solution(f.page(ed, 3), {**sol, "box": (300, 100, 440, 120)}, ["..."])
check("a grid cut by the window of a short heading is read whole", ({"1-across": "ABC"}, (352 * 3, 352 * 3)),
      (got, seen[0][0]))
check("a box far from square (a speck under the heading) has no square cut", [],
      f.squares(Image.new("L", (400, 400), 255), (0, 0, 300, 20)))
check("a square box has none", [], f.squares(Image.new("L", (400, 400), 255), (0, 0, 300, 296)))
# matched_box(): a grid whose ink joins a neighbour's (1974-78: a 444x434 box for a 313px grid) is
# found as the lattice whose blocks are the puzzle's.
mg = ["..#..", ".#.#.", "#...#", ".#.#.", "..#.."]
mw = Image.new("L", (520, 420), 255)
md = ImageDraw.Draw(mw)
md.rectangle((100, 100, 350, 350), outline=0, width=3)
for k in range(1, 5):
    md.line((100 + 50 * k, 100, 100 + 50 * k, 350), fill=0, width=2)
    md.line((100, 100 + 50 * k, 350, 100 + 50 * k), fill=0, width=2)
md.rectangle((350, 60, 470, 380), fill=0)
for r, row in enumerate(mg):
    for c, ch in enumerate(row):
        if ch == "#":
            md.rectangle((100 + 50 * c, 100 + 50 * r, 150 + 50 * c, 150 + 50 * r), fill=0)
m_agree, m_box, _ = f.matched_box(mw, mg, (200, 400))
check("a grid joined to a neighbour's ink is found by its blocks", (1.0, True),
      (m_agree, all(abs(a - b) <= 4 for a, b in zip(m_box, (100, 100, 350, 350)))))
# solved(): read_solution kept by what it reads from, so a re-read for a
# clue-vote change runs no solution OCR; another grid or heading reads again.
stats_blocks = 1.0
seen.clear()
first = f.solved(sol, ["..."])
again = f.solved(sol, ["..."])
check("a solution read once is kept: the second read opens no page and runs no OCR",
      (({"1-across": "ABC"}, {"blocks": 1.0}), 1), (again, len(seen)))
check("...and gives what the read gave", first, again)
f.solved(sol, [".#."])
f.solved({**sol, "box": (100, 100, 401, 140)}, [".#."])
check("...read again for another grid or another heading box", 3, len(seen))
check("solved() is not in read_solution's reach: solution_key() stays the reader's",
      False, ("file_archive_org_puzzles", "solved") in set(code_reach.reach("file_archive_org_puzzles", {"read_solution"})))

# rapid_lines(): a reader's clue reading is kept per crop, so a re-read after a
# post-processing change runs no clue OCR; a moved grid (new scan, locate fix)
# reads again.
_read_words, reads = f.read_words, []
f.read_words = lambda crop, which: reads.append((crop.size, which)) or [(5, 5, 60, 20, "1 Clue (4)")]
clue_page = Image.new("L", (1200, 1600), 255)
rp = Path(os.environ["TMP"]) / "rapid" / "1990-01-01_1.en5.json"
first = f.rapid_lines(clue_page, (200, 300, 700, 800), "en5", rp)
again = f.rapid_lines(clue_page, (200, 300, 700, 800), "en5", rp)
check("a clue reading is kept: the second identical read runs no OCR and gives the first's words",
      (1, first), (len(reads), again))
f.rapid_lines(clue_page, (200, 300, 700, 800), "en5", rp, above=120.5, x0=180.25)
f.rapid_lines(clue_page, (200, 300, 700, 800), "en5", rp, above=120.5, x0=180.25)
check("...a fractional `above` crop round-trips its JSON key: read once", 2, len(reads))
f.rapid_lines(clue_page, (204, 300, 704, 800), "en5", rp)
check("...and a moved grid is read again", 3, len(reads))
f.read_words = _read_words

# bounded_light(): a light off a grid whose blocks read unsure stands only
# where the image ends it with blocks and no lattice read another word there
# (times-19371 read off 19271's grid: TRACTA ran on into a letter).
bl = trove_solution_ocr.bounded_light
row = [(0, 1), (0, 2), (0, 3), (0, 4)]
blocks = {(0, 0): True, (0, 5): True}
check("a light its blocks bound, read as one word, stands", True,
      bl(row, "across", blocks, "TREK", [{"TREK"}, {"TREK", "TQEK"}]))
check("...not one the image runs on past (another puzzle's grid)", False,
      bl(row, "across", {(0, 0): True, (0, 5): False}, "TREK", [{"TREK"}]))
check("...nor one a lattice read whole as another word (PASTILLE beside BASTILLE)", False,
      bl(row, "across", blocks, "TREK", [{"TREK"}, {"TREE"}]))
check("...and the grid's edge bounds a light", True,
      bl([(0, 0), (0, 1), (0, 2), (0, 3)], "across", {(0, 4): True}, "TREK", [{"TREK"}]))

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
# The 1970s Telegraph (Gale 1975-03-05) indents its grid under the clues,
# the Quick crossword's clues in the gap: the across column starts at the
# title's left edge, not the grid's, or every across number is cut off.
grid = (421, 4160, 1196, 4935)
title = (237, 3247, 533, 3283)
lines = [line("No. 15,302 ACROSS", 237, 3247), line("DOWN", 898, 3249),
         line("1 & 9 Fortified ruler of un-", 245, 3290), line("2 One on a Scot of Greek", 733, 3282),
         line("washed scamps (4, 2, 3, 6)", 280, 3325), line("origin (6)", 757, 3313)]
x0 = f.clues_left(grid, title, 15)
top = title[1] - 10
span = (x0 + 15 + 0.3 * (grid[2] - x0 - 15), x0 + 15 + 0.75 * (grid[2] - x0 - 15))
split = f.gutter(lines, grid, top, *span)
right = f.gutter(lines, grid, top, grid[2] - f.OVERHANG, grid[2] + f.OVERHANG)
check("clues-above columns start at a title left of an indented grid; elsewhere at the grid",
      (222, 385, "ACROSS\n1 & 9 Fortified ruler of un-\nwashed scamps (4, 2, 3, 6)\nDOWN\n2 One on a Scot of Greek\norigin (6)"),
      (x0, f.clues_left((400, 0, 900, 0), (410, 0, 600, 0), 15),
       f.column_text(f.columns(lines, grid, None, 15, (top, split, right, x0)))))
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
# OCR first: the VLM is asked only for the columns holding a clue the scan's
# own readers leave blank or do not settle.
lens = {"1-across": [1] * 5, "6-across": [1] * 5, "1-down": [1] * 5}
filed_laid = {"1-across": ("Bird in a tree", "5", None), "6-across": ("Fish in the sea", "5", None),
              "1-down": ("Cat on a mat", "5", None)}
rd2 = {"djvu": good, "ch": good, "en5": good.replace("Fish in the", "Fisk in the")}
check("clues read alike by two readers are settled, a blank one is weak", {"7-across"},
      f.weak_lights(rd2, {**filed_laid, "7-across": ("", "5", None)}, {"7-across": "x"}, {**lens, "7-across": [1] * 5}))
rd3 = {"djvu": good, "ch": good.replace("Fish in the sea", "Fisk in the sea")}
check("a clue only one of two readings prints as filed is weak", {"6-across"},
      f.weak_lights(rd3, filed_laid, {}, lens))
# Gale 1965 (vlm_corpus.jsonl): one reader's slip in a word the other printed right, or an
# accent it dropped, is no disagreement; the VLM was asked 60 times for such lights.
slip_laid = {**filed_laid, "6-across": ("Fish flourish in the sea", "5", None)}
slip_rd = {"en5": good.replace("Fish in the", "Fish flourish in the"),
           "ch": good.replace("Fish in the", "Fish fourish in the")}
check("a reading with one slip in a word the other printed right settles the clue", set(),
      f.weak_lights(slip_rd, slip_laid, {}, lens))
check("a lone reading is still weak", True,
      "6-across" in f.weak_lights({"ch": slip_rd["ch"]}, slip_laid, {}, lens))
check("a reading two words off is no slip of it", False,
      clue_repair.slip_of("Fish flourish in the sea", "Fish fourish in tho sea"))
check("a dropped accent is no disagreement", True,
      clue_repair.slip_of("The cur\u00e9 is indisposed", "The cure is indisposed"))
check("a one for the I a clue opens with is a slip", True,
      clue_repair.slip_of("I am punctual with a film", "1 am punctual with a film"))
check("a slip that is another real word is no slip", False,
      clue_repair.slip_of("Fish flourish in the sea", "Fish flourishes in the sea"))
check("a word the clues print is no slip", False,
      clue_repair.slip_of("Seen in dance by Pyrrho", "Seen in dance by Pyrrhos"))
check("a run-together pair of words with one more slip is a slip", True,
      clue_repair.slip_of("and in the fire of Spring your garment of Repentance fling",
                          "and in the fire of Springyour, garment of Repentance fing"))
check("an accent a reading keeps is no disagreement for weak_lights", True,
      f.words_of("Omar Khayyám") == f.words_of("Omar Khayyam"))
# A "See N" tail is a clue of only a cross-reference: two readings printing it settle it, laid
# as "See 1" as filed puzzles have it, so the VLM is not asked for it.
seen = good.replace("7 Dog on a lead (5)", "7 See 1 across")
seen_rd = {"djvu": seen, "ch": seen.replace("See 1 across", "See 1")}
seen_lens = {**lens, "7-across": [1] * 5}
laid_see, blank_see = f.see_laid(seen_rd, filed_laid, {"7-across": "x"}, seen_lens, f.parse)
check("two readings of a bare See N clue lay it as See N", ("See 1", {}),
      (laid_see["7-across"][0], blank_see))
check("one reading of a See N clue does not settle it", {"7-across": "x"},
      f.see_laid({"djvu": seen, "ch": good}, filed_laid, {"7-across": "x"}, seen_lens, f.parse)[1])
check("a laid See N clue two readings print is not weak", set(),
      f.weak_lights(seen_rd, laid_see, {}, seen_lens))
check("a See N naming no numbered light is not laid", {"7-across": "x"},
      f.see_laid({k: t.replace("See 1", "See 9") for k, t in seen_rd.items()}, filed_laid,
                 {"7-across": "x"}, seen_lens, f.parse)[1])
# A reader that lost a clue's number, or ran its count into the next column's
# text, still printed the clue: two such readings settle it (1948 Gale pages:
# "These go before us", "Underground watchword (6) nem EDGES PuattsuiN").
nonum = {"ch": good.replace("6 Fish in the sea (5)", "Fish in the sea (5)"),
         "en5": good.replace("6 Fish in the sea (5)", "Fish in the sea (5) nem EDGES PuattsuiN Company, Limited")}
long_laid = {**filed_laid, "6-across": ("Fish in the sea off Cornwall", "5", None)}
nonum = {k: t.replace("Fish in the sea", "Fish in the sea off Cornwall") for k, t in nonum.items()}
check("two readings that print a clue with no number or with junk after it settle it", set(),
      f.weak_lights(nonum, long_laid, {}, {"6-across": [1] * 5}))
check("one such reading does not settle it", {"6-across"},
      f.weak_lights({"ch": nonum["ch"]}, long_laid, {}, {"6-across": [1] * 5}))
check("a short clue is not settled by a run inside another clue", False, f.prints_clue("Fish in the sea (5) Cat on a mat", "cat"))
colA = [(0, 10, 0, 50, "ACROSS"), (12, 22, 0, 50, "1 Bird in a tree (5)")]
colB = [(0, 10, 60, 110, "6 Fish in the sea (5)"), (12, 22, 60, 110, "DOWN 1 Cat on a mat (5)")]
colB = [(0, 10, 60, 110, "6 Fish in the sea (5)")]
colC = [(0, 10, 120, 170, "DOWN"), (12, 22, 120, 170, "2 Cow in a field (5)")]
check("the columns holding the weak lights' numbers are the ones read",
      {1}, f.columns_with([[colA, colB, colC]], ["6-across"]))
check("a number in no column's lines asks no column for it", set(),
      f.columns_with([[colA, colB, colC]], ["9-down"]))
check("a lost number does not widen the ask to every column", {1},
      f.columns_with([[colA, colB, colC]], ["6-across", "9-down"]))
check("the 1930 page still reads every column for a lost number", None,
      f.columns_with([[colA, colB, colC]], ["9-down"], True))
asked = []
def fake_page(d, found, hit, sols, vlm_for=False):
    asked.append(vlm_for)
    return ({"number": 1, "grid": "image", "_weak": set(PAGE_WEAK)} if vlm_for is False else {"number": 1, "grid": "image"}), {"id": "x"}
real_page = f.read_page
f.read_page = fake_page
PAGE_WEAK = []
v, p = f.read_puzzle(None, None, None, None)
check("a page the scan's readers settle is filed with no VLM look", ([False], 0, "_weak" in v), (asked, v.get("vlmAsks"), "_weak" in v))
asked.clear()
PAGE_WEAK = ["6-across"]
f.read_puzzle(None, None, None, None)
check("a page with a weak clue is read again with the VLM on that clue's columns only", [False, ["6-across"]], asked)
asked.clear()
f.read_puzzle(None, None, None, None, ocr_first=False)
check("ocr_first=False asks the VLM for every column, as before", [None], asked)
# The window the readers alone settled on is the one the VLM is shown first.
firsts = []
def fake_alt_page(d, found, hit, sols, vlm_for=False, first=None):
    firsts.append((vlm_for, first))
    return ({"number": 1, "grid": "image", "_weak": {"6-across"}, "_alt": ("plain", None)} if vlm_for is False else {"number": 1, "grid": "image"}), {"id": "x"}
f.read_page = fake_alt_page
f.read_puzzle(None, None, None, None)
check("the VLM pass is handed the window the readers settled on", [(False, None), (["6-across"], ("plain", None))], firsts)
f.read_page = real_page
tried = []
real_inner = f._read_page
def fake_inner(d, found, hit, sols, vlm_for, alt, alts, defer=False):
    tried.append(alt)
    if alts is not None:
        alts.extend([("lead", 1), ("plain", None)])
    good = alt == ("plain", None)
    return {"number": 1, "lights": 10, "agreed": 10 if good else 0, "blank": {}}, {"id": "x"}
f._read_page = fake_inner
v, p = f.read_page(None, None, None, None, ["6-across"], ("plain", None))
check("a first window that reads well is the only one the VLM is asked about", ([("plain", None)], "gutter"), (tried, v.get("cropFrom")))
tried.clear()
v, p = f.read_page(None, None, None, None, ["6-across"], ("lead", 1))
check("a poor first window falls back to the layout's, then the other windows",
      [("lead", 1), None, ("plain", None)], tried)
tried.clear()
v, p = f.read_page(None, None, None, None, False)
check("the readers' own pass keeps the window it settled on for the VLM pass", [None, ("lead", 1), ("plain", None)], tried)
check("and notes it", ("plain", None), v.get("_alt"))
def fake_full(d, found, hit, sols, vlm_for, alt, alts, defer=False):
    tried.append(alt)
    if alts is not None:
        alts.extend([("lead", 1), ("plain", None)])
    return {"number": 1, "lights": 10, "agreed": 10, "blank": {}, "imageDisagrees": "x"}, {"id": "x"}
f._read_page = fake_full
tried.clear()
f.read_page(None, None, None, None, ["6-across"])
check("a poor window that fills every light with none blank ends the VLM's search", [None], tried)
tried.clear()
f.read_page(None, None, None, None, False)
check("the readers' own pass still tries the other windows", [None, ("lead", 1), ("plain", None)], tried)
def fake_spooling(d, found, hit, sols, vlm_for, alt, alts, defer=False):
    tried.append(alt)
    if alts is not None:
        alts.extend([("lead", 1), ("plain", None)])
    f.vlm._UNANSWERED[0] += 1  # a pick or column read spooled for the drainer: its blanks are unanswered
    return {"number": 1, "lights": 10, "agreed": 0, "blank": {}}, {"id": "x"}
f._read_page = fake_spooling
tried.clear()
f.read_page(None, None, None, None, ["6-across"])
check("a window with asks spooled is not followed by the other windows' asks", [None], tried)
tried.clear()
f.read_page(None, None, None, None, ["6-across"], ("plain", None))
check("nor is the first window the readers settled on", [("plain", None)], tried)
lents = []
def fake_lending(d, found, hit, sols, vlm_for, alt, alts, lent=None, defer=False):
    lents.append((alt, lent))
    if alts is not None:
        alts.extend([("lead", 1), ("plain", None)])
    laid = {"1-across": ("One", "3", None), "2-down": ("Two", "4", None)} if alt is None else \
        {"1-across": ("One", "3", None), "2-down": ("Two", "4", None), "3-down": ("Three", "5", None)}
    return {"number": 1, "lights": 3, "agreed": len(laid), "blank": {"3-down": 1} if alt is None else {},
            "imageDisagrees": "x", "_laid": laid}, {"id": "x"}
f._read_page = fake_lending
f.read_page(None, None, None, None, ["6-across"])
check("a later window is lent the clues the best window so far has", [(None, None), (("lead", 1), {"1-across": ("One", "3", None), "2-down": ("Two", "4", None)})],
      lents)
v, p = f.read_page(None, None, None, None, ["6-across"])
check("and the lent clues are not left in the verdict", False, "_laid" in v)
lents.clear()
f.read_page(None, None, None, None, False)
check("the readers' own pass lends nothing", [(None, None), (("lead", 1), None), (("plain", None), None)], lents)
laid, blank, got = f.lend_laid({"1-across": ("", "3", None), "2-down": ("", "4", None), "3-down": ("", "5", None)},
                               {"1-across": 1, "2-down": 1, "3-down": 1},
                               {"1-across": ("One", "3", None), "2-down": ("Two", "5", None), "3-down": ("", "5", None)})
check("a blank light takes the clue lent for it when the count is the same, and not otherwise",
      ({"1-across": "One", "2-down": "", "3-down": ""}, ["2-down", "3-down"], {"1-across"}),
      ({k: v[0] for k, v in laid.items()}, sorted(blank), got))
# Picks wait for the best window: a poor window with another to try defers them.
reads = []
def fake_deferring(d, found, hit, sols, vlm_for, alt, alts, lent=None, defer=False):
    reads.append((alt, defer))
    if alts is not None:
        alts.extend([("lead", 1), ("plain", None)])
        defer = bool(alts)
    n = {None: 3, ("lead", 1): 6, ("plain", None): 5}[alt]  # blanks of each window
    v = {"number": 1, "lights": 10, "agreed": 10 - n, "blank": {f"{i}-down": 1 for i in range(n)}}
    if defer:
        v["_deferred"] = {"alt": alt, "lent": lent}
    else:
        v["agreed"], v["blank"] = v["agreed"] + 2, dict(list(v["blank"].items())[2:])  # the picks fill two
        v["picked"] = True
    return v, {"id": "x"}
f._read_page = fake_deferring
v, p = f.read_page(None, None, None, None, ["6-across"])
check("a poor window with others to try asks no pick; the best, chosen, is read again with them",
      [(None, None), (("lead", 1), True), (("plain", None), False), (None, False)], reads)
check("and that window's verdict is the one filed, picked, with no deferral left in it", (True, False), (v.get("picked"), "_deferred" in v))
f._read_page = real_inner
def fake_refused(d, found, hit, sols, vlm_for=False):
    asked.append(vlm_for)
    return {"number": 1, "cause": "not-a-grid"}, None
f.read_page = fake_refused
asked.clear()
f.read_puzzle(None, None, None, None)
check("a refusal the VLM cannot mend ends the read with no ask", [False], asked)
# A held puzzle is not put to the VLM when the held file leaves it nothing to mend.
class FakeDir:
    name = "ed1"
def fake_weak(d, found, hit, sols, vlm_for=False):
    asked.append(vlm_for)
    return ({"number": 7, "grid": "image", "_weak": {"6-across"}} if vlm_for is False else {"number": 7, "grid": "image"}), {"id": "x"}
f.read_page = fake_weak
real_paper_of, real_held_dates, real_held_file = f.paper_of, f.held_dates, f.held_file
f.paper_of = lambda d: f.TIMES
f.held_dates = lambda series: {7: None}
whole_clue = {"text": "Bird in a tree", "enumeration": "5"}
f.held_file = lambda series, n: {"source": {"acquiredBy": "someone else"}, "entries": [{"clue": {}}]}
asked.clear()
v, p = f.read_puzzle(FakeDir(), None, None, None)
check("a held puzzle another tool filed asks the VLM nothing", ([False], True, 0), (asked, v.get("heldSkip"), v.get("vlmAsks")))
f.held_file = lambda series, n: {"source": {"acquiredBy": f.TOOL}, "entries": [{"number": 1, "direction": "across", "clue": {}}]}
asked.clear()
f.read_puzzle(FakeDir(), None, None, None)
check("a held puzzle of this tool's with a blank clue keeps the VLM", [False, ["6-across"]], asked)
f.held_file = lambda series, n: {"source": {"acquiredBy": "someone else"}, "entries": []}
f._KEEP_VLM["names"] = {"ed1"}
asked.clear()
f.read_puzzle(FakeDir(), None, None, None)
check("an edition asked to be read again keeps the VLM for a held puzzle", [False, ["6-across"]], asked)
f._KEEP_VLM["names"] = set()
f.held_dates = lambda series: {}
asked.clear()
f.read_puzzle(FakeDir(), None, None, None)
check("a puzzle not held asks the VLM", [False, ["6-across"]], asked)
def fake_count(weak):
    def read(d, found, hit, sols, vlm_for=False, *a, **kw):
        asked.append(vlm_for)
        return ({"number": 7, "grid": "image", "imageDisagrees": "14-across: the enumeration reads as ['14'], the grid holds 4 letters",
                 "_weak": set(weak)} if vlm_for is False else {"number": 7, "grid": "image"}), \
            {"id": "x", "entries": [{"number": 14, "direction": "across", "clue": {"text": text14, "enumeration": enum14}}]}
    return read
text14, enum14 = "Stop a race", "4"
f.read_page = fake_count(set())
asked.clear()
v, p = f.read_puzzle(FakeDir(), None, None, None)
check("a count the grid settles on a light the readers confirm asks the VLM nothing", ([False], 0), (asked, v.get("vlmAsks")))
f.read_page = fake_count({"6-across"})
asked.clear()
f.read_puzzle(FakeDir(), None, None, None)
check("a count disagreement asks only the weak lights, not the light the grid settled", [False, ["6-across"]], asked)
f.read_page = fake_count(set())
for text14, enum14, what in (("Stop a race", None, "no enumeration"), ("Stop -a race", "4", "a stray mark"), ("", "4", "no text")):
    asked.clear()
    f.read_puzzle(FakeDir(), None, None, None)
    check(f"a count-disagreeing light with {what} is still asked", [False, ["14-across"]], asked)
text14, enum14 = "Stop a race", "4"
check("a clue's own hyphen or ellipsis is no stray mark", [None, None],
      [f.STRAY_MARK.search("Half-hearted - a stop"), f.STRAY_MARK.search("... and so on")])
f.paper_of, f.held_dates, f.held_file = real_paper_of, real_held_dates, real_held_file
# The queue's entrance: an edition whose titles the date checks refuse is not read.
real_fn, real_fs = f.filed_number, f.filed_state
f.filed_number = lambda d, found, hit: (None, None, "2026-10-18 is a Sunday and no daily cryptic")
scan0 = {"puzzles": [{"number": 7, "leaf": 1}], "date": "2026-10-18"}
check("an edition whose title is a Sunday is skipped", "sunday", f.unit_skip(f.TIMES, None, scan0, {}, "never read", {}))
check("a refusal read before its fix is kept", None, f.unit_skip(f.TIMES, None, scan0, {}, "refused not-a-grid before its fix", {}))
check("an annotation asked is kept", None, f.unit_skip(f.TIMES, None, scan0, {}, "annotation asked", {}))
f.filed_number = lambda d, found, hit: (7, datetime.date(2026, 10, 17), None)
f.filed_state = lambda series, n: (True, True)
held0 = {7: datetime.date(2026, 10, 17)}
check("an edition whose puzzle is held whole is skipped", "already held whole", f.unit_skip(f.TIMES, None, scan0, {}, "inputs changed", held0))
f.filed_state = lambda series, n: (False, True)
check("a held puzzle short of answers is kept for a content reason", None, f.unit_skip(f.TIMES, None, scan0, {}, "inputs changed", held0))
check("... but skipped for the VLM's own reason", "already held (VLM-only reason)", f.unit_skip(f.TIMES, None, scan0, {}, "read by another VLM", held0))
check("a puzzle not held is kept", None, f.unit_skip(f.TIMES, None, scan0, {}, "read by another VLM", {}))
f.filed_number, f.filed_state = real_fn, real_fs
f.read_page = real_page
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
check("the clean reading inside two others' table scraps is the clue (no pick asked)",
      "Hanker after an unknown make (5)",
      ocr_clues.clean_inside(["Hanker after an unknown Ipcome Growtb make (5)",
                              "Hanker after an unknown Incorme Gronth Aock - make (5)",
                              "Hanker after an unknown make (5)"], "5"))
check("a word two readings both add is a known word lost from the third: no clean reading", None,
      ocr_clues.clean_inside(["Sound made by cat to arouse bird (6)", "Sound made by the cat to arouse bird (6)",
                              "Sound made by the cat to arouse bird (6)"], "6"))
check("a clean reading whose count is not the light's is not taken", None,
      ocr_clues.clean_inside(["Hanker after an unknown Ipcome Growtb make (5)",
                              "Hanker after an unknown Incorme Gronth Aock - make (5)",
                              "Hanker after an unknown make (5)"], "7"))
check("three readings of the last across clue that differ only in the solution-box footer agree (no pick asked)",
      "Study applied to uninteresting poet (6)",
      ocr_clues.agreed_past_footer(["Study applied to uninteresting poet (6) 23,099 Solutic",
                                    "Study applied to uninteresting poet (6) 23,099 Soluti",
                                    "Study applied to uninteresting poet (6) WORD 23,099"], "6"))
check("a footer cut that leaves two readings unlike is no agreement (the pick is asked)", None,
      ocr_clues.agreed_past_footer(["Net I weaved with my needle (6) 23,095 Soluti",
                                    "Net I wove with my needle (6) SWORD 23,095"], "6"))
check("a torn 'Solution to' and a torn 'so' after the number are footer too (23,109, 23,105)",
      ["Don't be seen to collect feathers? (4,4)", "Cruel fellow has fixed trap for woman with brown hair (8)"],
      [ocr_clues.footer_cut("Don't be seen to collect feathers? (4,4) 23,109 Solution to"),
       ocr_clues.footer_cut("Cruel fellow has fixed trap for woman with brown hair (8) 23,105 so")])
check("a number torn at the crop edge ('WORD 23,0') is footer too (2005 pages)",
      "Division (8)", ocr_clues.footer_cut("Division (8) WORD 23,0"))
check("words after a count with no footer mark are a clue's, not cut", "Pun (4) so to",
      ocr_clues.footer_cut("Pun (4) so to"))
check("a second clue after a mid-text count is not a footer: nothing is cut",
      "Euclid's fifth proposition is game (9) perfect in conception (5)",
      ocr_clues.footer_cut("Euclid's fifth proposition is game (9) perfect in conception (5)"))
check("a laid clue that ran into the footer is cut at its count, not blanked for a pick",
      (("Which us sort", "6", None), {}),
      (lambda r: (r[0]["29-across"], r[1]))(f.unfit_blanked(
          {"29-across": ("Which us sort (6) WORD 22,9", None, None)}, {}, {"29-across": 6})))
check("a footer on a count that is not the light's stays blank",
      "29-across",
      next(iter(f.unfit_blanked({"29-across": ("Which us sort (6) WORD 22,9", None, None)}, {}, {"29-across": 7})[1])))
check("a footer_laid with no footer is None", None, ocr_clues.footer_laid("Which us sort (6)", 6))
# Gale 2005-03-17 28 across: the footer ran on after a count that fills the light, so unfit()
# passed the text and it was filed with the footer until the VLM's column read it clean.
check("a laid clue unfit() passes is cut at its count too when the footer follows it",
      (("Went to ground without hesitation, being sticky", "5", None), {}),
      (lambda r: (r[0]["28-across"], r[1]))(f.unfit_blanked(
          {"28-across": ("Went to ground without hesitation, being sticky (5) 22,926 Solutic", None, None)},
          {}, {"28-across": 5})))
# Gale 2005-03-17 13 down: every reader lost the cross-reference ("like 21"), so the readers
# agreed on a clue that ends in a word a reference follows; the VLM is asked for it.
open_rd = {"djvu": good.replace("Fish in the sea", "Fish in the sea like"),
           "ch": good.replace("Fish in the sea", "Fish in the sea like")}
check("a clue the readers agree on that ends in a word a reference follows is weak", {"6-across"},
      f.weak_lights(open_rd, {**filed_laid, "6-across": ("Fish in the sea like", "5", None)}, {}, lens))
check("a clue that ends in such a word with a mark after it is not", set(),
      f.weak_lights({k: t.replace("sea like", "sea, like?") for k, t in open_rd.items()},
                    {**filed_laid, "6-across": ("Fish in the sea, like?", "5", None)}, {}, lens))
# FT 1985: three readers, each with a slip in another word, no two alike on the whole line.
_lily = ["Lilyas head replaced by song in Jaunty manner", "Lily's head replaced by song in Jauuty manner",
         "Lily's head replaced by song in jaunty manner"]
check("a clue whose every word two readers print is confirmed though no two print it whole", True,
      f.words_confirmed("Lily's head replaced by song in jaunty manner", None, [(t, 0) for t in _lily]))
check("a clue with a word only one reader prints is not", False,
      f.words_confirmed("Benefit from a drink today", None,
                        [(t, 0) for t in ["Benefit from a drink today", "Beneft from a drink today", "Benefi from a drink today"]]))
check("a clue with a figure is not", False,
      f.words_confirmed("Bathsheba swallowed 8 doctor repellent", None,
                        [(t, 0) for t in ["Bathsheba swallowed 8 doctor repellent"] * 3]))
check("a footer cut to a count that is not the light's is not taken", None,
      ocr_clues.agreed_past_footer(["Study applied to uninteresting poet (6) 23,099 Solutic",
                                    "Study applied to uninteresting poet (6) 23,099 Soluti"], "7"))
check("readings already alike with no footer to cut are left to the pick", None,
      ocr_clues.agreed_past_footer(["Study applied to poet (6)", "Study applied to poet (6)"], "6"))
check("the last across clue the readings agree on past the footer is laid with no ask", "Study applied to uninteresting poet",
      ocr_clues.vlm_pick({"ch": "ACROSS\n1 Mender of slippery eels in water (5)\n4 Quiet horse runs in the lane (6)\n7 Chap leaves the tall old house (4)\n9 Study applied to uninteresting poet (6) 23,099 Solutic\nDOWN\n2 Strange tales from the mountain (7)\n3 Most of the cattle go west (4)\n",
                          "en5": "ACROSS\n1 Mender of slippery eels in water (5)\n4 Quiet horse runs in the lane (6)\n7 Chap leaves the tall old house (4)\n9 Study applied to uninteresting poet (6) 23,099 Soluti\nDOWN\n2 Strange tales from the mountain (7)\n3 Most of the cattle go west (4)\n",
                          "vlm": "ACROSS\n1 Mender of slippery eels in water (5)\n4 Quiet horse runs in the lane (6)\n7 Chap leaves the tall old house (4)\n9 Study applied to uninteresting poet (6) WORD 23,099\nDOWN\n2 Strange tales from the mountain (7)\n3 Most of the cattle go west (4)\n"},
                         {"9-across": ("", "6", None)}, {"9-across": "readings differ"}, f.parse,
                         lambda lid, cands: 1 / 0)[0]["9-across"][0])
check("a pick that copied the footer under the last across clue is laid without it (23,105's 28 across)",
      "Cruel fellow has fixed trap for woman with brown hair",
      ocr_clues.vlm_pick({"x": "x"}, {"28-across": ("", "8", None)}, {"28-across": "readings differ"},
                         lambda t: ({"across": [{"tokens": [{28}], "text": "Cruel fellow has fixed trap for woman with brown hair",
                                                 "enums": {"8"}, "see": None}], "down": []}, None),
                         lambda lid, cands: "Cruel fellow has fixed trap for woman with brown hair (8) WORD 23,105")[0]["28-across"][0])
check("the VLM's own reading beside an OCR slip of a letter is laid with no ask", "Mender of slippery eels in water",
      ocr_clues.vlm_pick({"ch": "ACROSS\n1 Mender of slippery eals in water (5)\n4 Quiet horse runs in the lane (6)\n7 Chap leaves the tall old house (4)\n9 Lost rain falls on a hill (5,3)\nDOWN\n2 Strange tales from the mountain (7)\n3 Most of the cattle go west (4)\n5 Bird in a bush is worth two (5)\n",
                          "vlm": "ACROSS\n1 Mender of slippery eels in water (5)\n4 Quiet horse runs in the lane (6)\n7 Chap leaves the tall old house (4)\n9 Lost rain falls on a hill (5,3)\nDOWN\n2 Strange tales from the mountain (7)\n3 Most of the cattle go west (4)\n5 Bird in a bush is worth two (5)\n"},
                         {"1-across": ("", "5", None)}, {"1-across": "readings differ"}, f.parse,
                         lambda lid, cands: 1 / 0)[0]["1-across"][0])

# FT 1984-09-20: worn type, three readers each garbling every clue differently
# (none within SETTLE_SIMILAR of another); the VLM's column reading was clean and
# every pick asked came back as that very text. Laid with no ask when its count is
# the light's and its words are known; asked when its count is not or a word is not.
WORN_OCR = {"ch": "ACROSS\n18Poet'siudycruwnrdwlth\npold (5)\nDOWN\n3Stir up volnily-.cherr\nllerorvel151\n",
            "en5": "ACROSS\n18 Poet's wludy crownrd with\nFold (5)\nDOWN\n3 Goree WiT\" wilh .1\ncomnon sl (9)\n"}
WORN_VLM = "ACROSS\n18 Poet's study crowned with\ngold (5)\nDOWN\n3 Gorge a wife with a\ncommon salt (9)\n"
check("the VLM's column reading beside three worn readers, its count the light's, is laid with no ask",
      "Poet's study crowned with gold",
      ocr_clues.vlm_pick({**WORN_OCR, "vlm": WORN_VLM}, {"18-across": ("", "5", None)},
                         {"18-across": "no other reading has"}, f.parse, lambda lid, cands: 1 / 0)[0]["18-across"][0])
check("the same reading for a light of another length is asked about, not laid", ["18-across"],
      sorted(ocr_clues.vlm_pick({**WORN_OCR, "vlm": WORN_VLM}, {"18-across": ("", "6", None)},
                                {"18-across": "no other reading has"}, f.parse, lambda lid, cands: None)[1]))
check("a column reading with a word no lexicon knows and no reader prints is asked about", ["18-across"],
      sorted(ocr_clues.vlm_pick({**WORN_OCR, "vlm": WORN_VLM.replace("study", "stuqdy")}, {"18-across": ("", "5", None)},
                                {"18-across": "no other reading has"}, f.parse, lambda lid, cands: None)[1]))

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
check("a re-read that drops a misread count filling the light corrects a held clue (count_dropped)",
      [True, True, True], [f.count_dropped("Song of joy 141", "Song of joy", 4, ()),
                           f.count_dropped("Third degree restaurant? 15-41", "Third degree restaurant?", 9, ()),
                           f.count_dropped("Overdone qualiry 7", "Overdone quality", 7, ())])
check("mirror: figures that do not fill the light, have a unit or are kept are no count dropped",
      [False, False, False, False], [f.count_dropped("Under extremes of 9", "Under extremes of", 5, ()),
                                     f.count_dropped("Goes down in 8s", "Goes down in", 8, ()),
                                     f.count_dropped("Song of joy 141", "Song of joy 141", 4, ()),
                                     f.count_dropped("Song of joy 141", "Song", 4, ())])
check("a reference to a light after See/No/Channel or a preposition is the clue's, no count left (count_left)",
      [None] * 5, [f.count_left("See 15", 5, {1, 15, 21}),
                   f.count_left("Mercenary backing Channel 5", 5, {5, 10}),
                   f.count_left("Sailor's main dish cooked to entertain occupant of No 10", 10, {10}),
                   f.count_left("A film about hilarious old company in 18", 8, {12, 18}),
                   f.count_left("Good quality that comes from being 8", 8, {7, 8})])
check("mirror: figures naming no light, or after a word a clue ends on, are a count left",
      ["See", "Compare with a man who is under", "Russian author employed as Kent ARP organizer"],
      [f.count_left("See 15", 5, {1, 21}), f.count_left("Compare with a man who is under 51", 5, {5, 15}),
       f.count_left("Russian author employed as Kent ARP organizer 9", 9, {9})])
check("a reading losing or swapping a real word, blank, unchanged, marks only or made up corrects nothing",
      [False] * 8, [f.corrects("Frontier cantonment.", "Frontier."),
                    f.corrects("Swearing and lying", "Swearing and lying (7). But not backward"),
                    f.corrects("A town (4)", "A town (4) 7"),
                    f.corrects('The shout "Last out"', 'The shout \u201cLast out\u201d'),
                    f.corrects("Fudge the issue", "Judge the issue"),
                    f.corrects("Frontier cantonment.", ""),
                    f.corrects("A town", "A town"),
                    f.corrects("A town", "A town xqzvb")])
check("a reread that cuts a word at its edge or turns a word to a non-word corrects nothing",
      [False] * 6, [f.corrects("The servant behind the 1st Earl of Ypres", "The servant behind the st Earl of Ypres"),
                    f.corrects("Scoundrel but good at heart", "Scoundrel but good at hear"),
                    f.corrects("Just like Bill Brewer", "Just ike Bill Brewer"),
                    f.corrects("Dickens family mad about Humpty Dumpty", "Dickens family mad about Humply Dumpty"),
                    f.corrects("Department of State about to recognise", "Department of State about 10 recognise"),
                    f.corrects("Waller receives a note from the Norms", "Waller receives a note from the Norns")])
check("a reread that gains a lone & corrects nothing (times-12467)",
      [False, False], [f.corrects("Lone wolf unimpeded by a weapon", "Lone wolf unimpeded by & a weapon"),
                       f.corrects("Lone wolf unimpeded by weapon", "Lone wolf unimpeded by & weapon")])
check("a reread that gains furniture, a leaked hyphen, E for £, a glued figure, an unpaired quote, "
      "1 for I or its count corrects nothing (clue_text.REFUSED_GLITCHES, tools/audit_updates.py)",
      [False] * 7,
      [f.corrects("About to entertain lavishly, look up place to eat",
                  "About to entertain lavishly, look times, up place to eat"),
       f.corrects("Knocks about Minehead looking for swindles", "Knocks about Minehead look- 2119. ing for swindles"),
       f.corrects("Locks secured, in the end, with £25 left", "Locks secured, in the end, with E25 left"),
       f.corrects("A former emperor rebuffed the follower of another",
                  "2A former emperor rebuffed the follower of another"),
       f.corrects('Oriental girl stars in "The Special Agents"', 'Oriental girl stars in "The Special Agents'),
       f.corrects("Featured in the newspaper. I live for danger", "Featured in the newspaper. 1 live for danger"),
       f.corrects("Bomb is not half an unpleasant experience", "Bomb is not half an unpleasant experience (5). code.")])
check("rewritten(): another clue's words over a held clue, not a reading of it",
      [True, True, False, False],
      [f.rewritten("Bill's relations", "Virtue"), f.rewritten("See 25", "Cambridge Park, E 11 01-989"),
       f.rewritten("Dry places ruined this old timer", "Dry places ruined this old-timer"),
       f.rewritten("", "Virtue")])

# keep_held_clues(): a count that trades word breaks the answer bears out for other
# breaks ("2,3,2,3,2" over ONTHEUPANDUP to "5,7", a neighbour's count: The Times
# 18,561 prints "(2,3,2,3,2)"), or a reading of other words, keeps the held clue; a
# lone count read off the print ("3,4" over REDWINE to "7": the 1950s-90s Times
# print CATCHUP "(7)", TIMEWORN "(8)" over the corpus's guessed "5,2", "4-4") and a
# count that gains breaks are taken.
def p7(clues, answer="REDWINE"):
    return {"source": {"acquiredBy": f.TOOL}, "dimensions": {"cols": len(answer), "rows": len(clues)},
            "entries": [{"number": i + 1, "direction": "across", "position": {"x": 0, "y": i}, "length": len(answer),
                         "clue": c, "solution": answer} for i, c in enumerate(clues)]}
held7 = p7([{"text": "Port, perhaps, in colour", "enumeration": "3,4"}, {"text": "Bill's relations", "enumeration": "7"},
            {"text": "Wine colour", "enumeration": "7"}])
read7 = p7([{"text": "Port, perhaps, in colour", "enumeration": "7"}, {"text": "Virtue", "enumeration": "7"},
            {"text": "Wine colour", "enumeration": "3,4"}])
check("another clue's words keep the held clue; a lone count read off the print over guessed breaks, "
      "and a count gaining breaks, are taken",
      [["2-across"], ["7", "7", "3,4"], ["Port, perhaps, in colour", "Bill's relations", "Wine colour"]],
      [sorted(f.keep_held_clues(read7, held7)), [e["clue"]["enumeration"] for e in read7["entries"]],
       [e["clue"]["text"] for e in read7["entries"]]])
held12 = p7([{"text": "Trustworthy, and still improving", "enumeration": "2,3,2,3,2",
              "separators": [{"at": n, "mark": ","} for n in (2, 5, 7, 10)]}], "ONTHEUPANDUP")
read12 = p7([{"text": "Trustworthy, and still improving", "enumeration": "5,7",
              "separators": [{"at": 5, "mark": ","}]}], "ONTHEUPANDUP")
for e in held12["entries"]:
    e["solution"] = None  # the answer the reread fills in bears the breaks out too
check("a count trading breaks the answer bears out for a neighbour's keeps the held clue, marks and all "
      "(times-18561)",
      [["1-across"], held12["entries"][0]["clue"]],
      [f.keep_held_clues(read12, held12), read12["entries"][0]["clue"]])
held8 = p7([{"text": "Port, perhaps, in colour", "enumeration": "3,4"}, {"text": "Wine colour", "enumeration": "7"}])
for e in held8["entries"]:
    e["solution"] = None
read8 = p7([{"text": "Port, perhaps, in colour", "enumeration": "7", "countFrom": "grid"},
            {"text": "Wine colour", "enumeration": "7", "countFrom": "grid"}])
for e in read8["entries"]:
    e["solution"] = None
check("a grid-length count over a printed count with breaks keeps the held clue, answer or not",
      [["1-across"], ["3,4", "7"]],
      [sorted(f.keep_held_clues(read8, held8)), [e["clue"]["enumeration"] for e in read8["entries"]]])
check("breaks_lost(): only breaks the answer bears out, traded for other breaks (ASKANCE's \"4,3\" may go; "
      "a lone count is the print's)",
      [True, False, False, False, False],
      [f.breaks_lost("2,3,2,3,2", "5,7", "ONTHEUPANDUP"), f.breaks_lost("3,4", "7", "REDWINE"),
       f.breaks_lost("5,2", "7", "CATCHUP"), f.breaks_lost("4,3", "7", "ASKANCE"),
       f.breaks_lost("2,3,2,3,2", "5,7", None)])
check("held_count(): the held count, its marks and countFrom over the reading's, the words kept",
      {"text": "Low laugh", "enumeration": "2-2", "separators": [{"at": 2, "mark": "-"}]},
      f.held_count({"text": "Low laugh", "enumeration": "4", "countFrom": "grid"},
                   {"text": "Lo laugh", "enumeration": "2-2", "separators": [{"at": 2, "mark": "-"}]}))
check("mirror: regressed() names those, and not a mend, a split word or a letter gained",
      ([True] * 3, [False] * 3),
      ([f.regressed("good at heart", "good at hear"), f.regressed("the 1st Earl", "the st Earl"),
        f.regressed("Humpty Dumpty", "Humply Dumpty")],
       [f.regressed("Fudqe the issue", "Fudge the issue"), f.regressed("fix the bathroom", "fix the bath-room"),
        f.regressed("Windblow soil", "Windblown soil")]))
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
# The Times to 1967-04-10 sets its grid under the title, indented from the
# title's left edge, with ACROSS and the first DOWN clues left of it (No
# 11,509); from No 11,510 the grid starts at the title's edge, its clues under it.
check("an indented grid under its title has a clue column left of it, a flush one none",
      ((121, 3865), None),
      (f.indented_column((271, 3802, 1148, 3865), (491, 3879, 1211, 4595)),
       f.indented_column((198, 2784, 911, 2819), (190, 2829, 912, 3535))))
# A title read from its second word ("CROSSWORD PUZZLE NO. ..." of "THE TIMES
# CROSSWORD ..."; Gale 1962-11-02) sits level with its grid: its printed line
# is walked left to the first word, so the clue column left of it is cropped.
from PIL import Image as _Image, ImageDraw as _Draw
_img = _Image.new("L", (1400, 200), 255)
_d = _Draw.Draw(_img)
for _x0 in (200, 340, 480):
    _d.rectangle((_x0, 100, _x0 + 110, 130), fill=0)  # words, gaps under a grid's TITLE_GAP
_d.rectangle((1300, 100, 1330, 130), fill=0)  # print far right: not the title
check("a title read from its second word is walked left to its line's start",
      (200, (0, 130)), (f.title_left(_img, (600, 100, 800, 130), (610, 140, 1210, 740))[0],
                         f.indented_column(f.title_left(_img, (600, 100, 800, 130), (610, 140, 1210, 740)),
                                           (610, 140, 1210, 740))))
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
check("a row's end spilled a little over a narrow gutter is cut there, not taken for a notice (FT 1981-10-19)",
      [(154, 0, 504, 20, "(25 and part. back (4,3,4)"), (505, 0, 590, 20, ":+:up!")],
      f.split_across([(154, 0, 590, 20, "(25 and part. back (4,3,4) :+:up!")], [505]))
check("a clue number read with a dash before it still cuts a row across the gutter",
      [(100, 0, 399, 20, "hole, but not in reverse (6). - -"), (400, 0, 700, 20, "3. Grotesque insect I caught")],
      [w[:4] + (w[4].strip(),) for w in f.split_across([(100, 0, 700, 20, "hole, but not in reverse (6). - -3. Grotesque insect I caught")], [400])][:2])
# FT 1981-10-19: the across clues no reader laid have no count, so the grid's gives it, and
# the VLM's clean column reading is laid with no pick (14 of 16 picks were for these).
check("a blank light no reader laid takes the grid's length as its count: the clean column reading is laid, no ask",
      "Poet's study crowned with gold",
      ocr_clues.vlm_pick({**WORN_OCR, "vlm": WORN_VLM}, {"18-across": ("", None, None)},
                         {"18-across": "no reading laid a clue on it"}, f.parse, lambda lid, cands: 1 / 0,
                         {"18-across": 5})[0]["18-across"][0])
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
# Only PAGE_READERS read a Gale page's whole ink; the other readers read the
# strips round their words a heading could be (hint_strips), or the whole ink
# when they read nothing there.
strip_img = Image.new("L", (f.SCAN_WIDTH, 2000), 255)
strip_img.putpixel((10, 10), 0)
check("a strip round each heading-like word, padded, clipped, overlaps merged",
      [(0, 70, 450, 130), (900, 1470, 1500, 1530)],
      f.hint_strips(strip_img, [(10, 90, 300, 110, "THE TIMES CROSSWORD"), (200, 95, 260, 110, "17,554"),
                                (1050, 1490, 1350, 1510, "Solution to Puzzle"), (500, 500, 600, 520, "Down clue 12")]))
check("(mirror) no heading-like word, no strip", [], f.hint_strips(strip_img, [(10, 90, 300, 110, "27 Order (5)")]))
asked = []
def strip_read(page_words):
    def words(img, box, which, path):
        asked.append((which, "page" if "_page." in str(path) else tuple(box)))
        return page_words if which in f.PAGE_READERS and "_page." in str(path) else \
            [(10, 90, 300, 110, "The Times Crossword Puzzle No 17,554")] if box[1] <= 90 else []
    asked.clear()
    f.band_words = words
    try:
        return [t[0] for t in f.ocr_headings(strip_img, f.GALE, "strip_read_test")[0]], sorted(set(asked))
    finally:
        f.band_words = saved_bw
heading = [(10, 90, 300, 110, "The Times Crossword Puzzle No 17,554")]
others = [r for r in f.READERS if r not in f.PAGE_READERS]
check("the other readers read only the heading strips, and vote with the page reader",
      ([17554], sorted([(r, "page") for r in f.PAGE_READERS] + [(r, (0, 70, 450, 130)) for r in others])), strip_read(heading))
check("(mirror) page readers that read nothing: the others read the whole ink",
      ([], sorted([(r, "page") for r in f.READERS])), strip_read([]))
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
ocr_remote.alert_once = lambda key, text: False  # never a real alert from a test (one reached the room, 2026-10-14)
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
        # A band (a heading strip, a solution band) reads the page's words in it too.
        return sorted({w for w in page.get(which, []) + band.get(which, [])
                       if box[0] <= w[0] and w[2] <= box[2] and box[1] <= w[1] and w[3] <= box[3]})
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
check("a run of the Times reads the 1930 issues too; the Telegraph and FT runs their Gale pages", (True, True, True),
      (f.TIMES_1930 in f.run_papers(f.TIMES), f.GALE_TELEGRAPH in f.run_papers(f.TELEGRAPH), f.GALE_FT in f.run_papers(f.FT)))
check("every paper's .also (archive_coverage and edition_queue read it) is its run's other papers", [],
      [p.key for p in (*f.FILERS.values(), f.TIMES_1930, f.GALE_TELEGRAPH) if f.run_papers(p) != (p, *p.also)])
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
ft2833 = {"date": "1975-07-16", "puzzles": [{"number": 2833, "leaf": 1}], "solutions": [],
          "editions": ["1975-07-16_26719", "1975-07-16_26722", "1975-07-18_26721", "1975-07-21_26723"]}
check("an FT title files for the day its edition's issue neighbours give, not the item title's (ftcryptic-2833)",
      (2833, _dt.date(1975, 7, 19), None),
      f.filed_number(Path("x/FinancialTimes1975UKEnglish/1975-07-16_26722"), ft2833, {"number": 2833, "leaf": 1}))
# A title its page's solution heading vouches for (No n - 1, the issue before) is not overruled
# by a count of issues: Times 22129 filed for 2002-08-28 (whose page prints No 22130) and 22232 on
# 12-26 count unbroken over Christmas Day, which had no paper, so the count put every title
# between them one low (08-29's No 22131 filed as 22130, 74 more after it).
_D = _dt.date.fromisoformat
xmas = f.Held({22129: _D("2002-08-28"), 22232: _D("2002-12-26")})
real_held_dates = f.held_dates
f.held_dates = lambda series: xmas
g0829 = Path("x/GaleTimes2002UKEnglish/2002-08-29")
found0829 = {"date": "2002-08-29", "item": "GaleTimes2002UKEnglish", "puzzles": [{"number": 22131, "leaf": 0}],
             "solutions": [{"number": 22130, "leaf": 0}]}
check("a title its page's heading of the issue before vouches for files as read, not as the count says",
      (22131, None), f.filed_number(g0829, found0829, {"number": 22131, "leaf": 0})[::2])
check("(mirror) with no heading to vouch for it the count still fixes the number",
      (22130, None), f.filed_number(g0829, {**found0829, "solutions": []}, {"number": 22131, "leaf": 0})[::2])
check("(mirror) placed: a vouched title the count agrees with, an unvouched one, or a vouched one more than one "
      "issue off (a digit the OCR misread in title and heading alike: 1968's 11999 over 11998 for 11909) files as the count says",
      [(22130, None), (22130, None), (22130, None)],
      [f.placed(22130, _D("2002-08-29"), xmas, True), f.placed(22131, _D("2002-08-29"), xmas),
       f.placed(22190, _D("2002-08-29"), xmas, True)])
check("a vouched title another day holds is refused, not filed a number off",
      (None, True), (lambda r: (r[0], bool(r[1])))(f.placed(22131, _D("2002-08-29"), f.Held({**xmas, 22131: _D("2002-08-30")}), True)))
# renumbered(): once its file is renamed to the title, an edition filed off it is due an answers-only
# reread (its host's heading names the title); one refused as taken, a full read once its title is free.
filed_low = {"edition": "GaleTimes2002UKEnglish/2002-08-29", "readAt": "2026-10-22T00:00:00+00:00",
             "scan": {"date": "2002-08-29"}, "verdicts": [{"number": 22130, "read_as": 22131, "id": "times-22130", "wrote": True}]}
taken = {"edition": "GaleTimes2002UKEnglish/2002-08-27", "readAt": "2026-10-24T00:00:00+00:00", "scan": {"date": "2002-08-27"},
         "verdicts": [{"number": 22129, "refused": "No 22129 is already filed for 2002-08-28, not 2002-08-27",
                       "cause": "number-date-mismatch"}]}
due = []
for held_now, row in ((f.Held({22131: _D("2002-08-29")}), filed_low), (f.Held({22130: _D("2002-08-29"), 22131: _D("2002-08-30")}), filed_low),
                      (f.Held({}), taken), (f.Held({22129: _D("2002-08-28")}), taken),
                      (f.Held({22131: _D("2002-08-29")}), {**filed_low, "readAt": "2026-10-26T00:00:00+00:00"})):
    f.held_dates = lambda series, h=held_now: h
    due.append(f.renumbered(row))
f.held_dates = real_held_dates
check("renumbered: filed off its title and since renamed to it is RENUMBERED; not yet renamed, not due; refused as "
      "taken and its title free is the refusal's reread, still taken not; read since the renumber, not due",
      [f.RENUMBERED, None, "refused number-date-mismatch before its fix", None, None], due)
check("RENUMBERED is a rank 2 answers-only reread", (2, True), (f.RANKS[f.RENUMBERED], f.RENUMBERED in f.SOLUTION_FIXES))
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
mon = datetime.date(2001, 4, 9)
check("a Gale page is one day: Monday's prize notice (No 21,696) does not move No 21,697 to Tuesday",
      mon, f.issue_day(mon, 21697, [21697, 21696], "GaleTimes2001UKEnglish"))
check("an archive.org item can still bind the next day's paper",
      datetime.date(2001, 4, 10), f.issue_day(mon, 21697, [21697, 21696], "NewsUK2001UKEnglish"))

check("why= names the lights an ask is for, blank or unsettled, with no space",
      "5d(blank),12a(unsettled)", f.why_lights({"12-across", "5-down"}, {"5-down"}))
check("why= caps a long list with +N",
      "1a(unsettled),2a(unsettled),+1", f.why_lights({"1-across", "2-across", "3-across"}, (), cap=2))
with f.vlm.because("fallback:no-reading-parses"):
    check("a reason set by the caller is the one the next ask carries", "fallback:no-reading-parses", f.vlm._WHY.get())
check("and it is gone after the read", "", f.vlm._WHY.get())
_fut = lambda paper, day: f.fallback_futile(paper, Path("x") / day)
check("no-reading-parses fallback asks are skipped for FT 1981 and Gale 1960-66 only",
      [True, True, True, False, False, False, False],
      [_fut(f.FT, "1981-10-02_28588"), _fut(f.GALE, "1960-01-04"), _fut(f.GALE, "1966-12-31"),
       _fut(f.FT, "1982-10-02_1"), _fut(f.FT, "1985-01-12_29522"), _fut(f.GALE, "1967-01-02"), _fut(f.GALE, "1945-04-11")])

print(f"FAILS {fails}")
sys.stdout = _stdout
out = _buf.getvalue().rstrip("\n")


def ocr_check():
    # Gale's 1987-01-07 solution grid (No 17,246, at the page's scale): clean,
    # but its rules lie unevenly, its rows shear and its clue numbers run into
    # the letters, and every light was refused but 2 of 30. Read now, most
    # lights are accepted and each is the answer a person reads off the scan.
    # Skipped where the OCR engine is not installed (CI's test job).
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            import os
            from pathlib import Path
            from PIL import Image
            # the body above stubs this module; the .sh read it in a fresh process
            sys.modules.pop("trove_solution_ocr", None)
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
        except SystemExit:
            pass
    return buf.getvalue().strip()


ocr = ocr_check()
if ocr == "skip":
    print("skip solution grid letters: rapidocr-onnxruntime not installed")
elif ocr == "ok":
    print("ok   Gale 1987-01-07's solution grid: 15+ of 30 lights read (was 2), each as a person reads it")
else:
    print(f"FAIL Gale 1987-01-07's solution grid: {ocr}")
    out += "\nFAILS 1"
print(out)
lines = out.splitlines()
if "FAILS 0" not in lines or any(ln.startswith("FAILS ") and ln[6:7] in "123456789" for ln in lines):
    print("test_file_archive_org_puzzles: failed")
    sys.exit(1)
print("test_file_archive_org_puzzles: all passed")
