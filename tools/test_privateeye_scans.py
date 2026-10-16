#!/usr/bin/env python3
# Does tools/privateeye_scans.py find a Private Eye page's clue columns from
# its djvu words, take the crossword's number and not the entry address's,
# read a linked head and a cross-reference, and hand privateeye_wayback's
# read_capture a list it parses? And does the shared tidy read RapidOCR's
# full-width bracket as a round one?
#
#     python3 tools/test_privateeye_scans.py
#
# Offline: the page's words are written here.
import io
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

fails = 0


def check(what, want, got):
    global fails
    if want == got:
        print(f"ok   {what}")
    else:
        print(f"FAIL {what}: want [{want}] got [{got}]")
        fails += 1


# What the shell's $(...) captured: everything the checks below print.
_stdout = sys.stdout
sys.stdout = io.StringIO()


import privateeye_scans as ps
import privateeye_wayback as pw
import file_archive_org_puzzles as fa


def line(*words):
    """A djvu LINE of (x0, y0, x1, text) words, 30px tall."""
    return "<LINE>" + "".join(
        f'<WORD coords="{x0},{y0 + 30},{x1},{y0}">{t}</WORD>' for x0, y0, x1, t in words) + "</LINE>"


rows = [line((100, 50, 300, "EYE"), (320, 50, 600, "CROSSWORD"), (620, 50, 660, "13"), (680, 50, 900, "Cyclops"))]
left = ["ACROSS", "1 Clue one here (5)", "5 Clue five (4)", "7 Another clue (6)", "9 Last across (8)"]
right = ["DOWN", "1 First down clue (4,4)", "2 This crossword is first (4)", "20/12 Linked clue (6,6)",
         "12 (See 20 down)"]
y = 200
for a, b in zip(left, right):
    # archive.org's OCR runs a row of both columns into one LINE.
    wa = [(100 + 60 * k, y, 150 + 60 * k, t) for k, t in enumerate(a.split())]
    wb = [(1300 + 60 * k, y, 1350 + 60 * k, t) for k, t in enumerate(b.split())]
    rows.append(line(*(wa + wb)))
    y += 45
rows.append(line((1300, y + 20, 1500, "Send"), (1520, y + 20, 1700, "entries"), (1720, y + 20, 1800, "to"),
                 (1820, y + 20, 2000, "“Crossword”,"), (2020, y + 20, 2100, "Private"),
                 (2120, y + 20, 2200, "Eye,"), (2220, y + 20, 2240, "6")))
rows.append(line((1300, y + 80, 1500, "SOLUTION"), (1520, y + 80, 1560, "TO"),
                 (1580, y + 80, 1800, "CROSSWORD"), (1820, y + 80, 1850, "12")))
xml = ("<OBJECT>" + "".join(rows) + "</OBJECT>").encode()
lines = ps.page_lines(xml)
print("SPLIT", len(lines))
cols = ps.columns(lines)
print("COLS", len(cols), cols[0][0] < 200, cols[1][0] > 1200 and cols[1][3] > 200 + 45 * 4)
print("NUMBER", ps.number_of(lines, 858), ps.number_of(lines[1:], 858), ps.number_of(lines[1:], 900))
W = lambda *ts: [(0, 0, 1, 1, t) for t in ts]
ruled = [W("EYE", "CROSSWORD", "|", "|", "|_", "280"), W("Crossword", "279", "winner:", "PETER")]
print("RULED", ps.number_of(ruled, 1125), ps.number_of(ruled[1:], 1125))
words = [w for ws in lines for w in ws]
across, down = ps.column_cols(cols)(words)
print("SIDES", len(across), len(down), down[2][4])

laid = {"1-across": ("Clue one here", "5", None), "1-down": ("First down clue", "4,4", None),
        "20-down": ("Linked clue", "6,6", ["20-down", "12-down"]), "12-down": ("See 20", None, None)}
text = ps.page_text(13, laid)
print("TEXT", text)
cap = pw.read_capture(text.encode(), "utf-8", plain=True, issue=858)
print("CAPTURE", cap["number"], [(r["number"], r["clue"], r["enumeration"]) for r in cap["rows"]["down"]])

verdict = {"blank": {"12-down": "no count read", "5-across": "no count read"}}
reads = {k: words for k in ("a", "b")}
laid2, v2 = ps.see_filled({"12-down": ("", None, None), "5-across": ("", "4", None)}, verdict, reads,
                          ps.column_cols(cols))
print("SEE", laid2["12-down"][0], sorted(v2.get("blank", {})))
two = {"clues": [(f"{i}_page", {"across": [{"number": "1", "clue": c, "enumeration": "5"}], "down": []})
                 for i, c in ((974, "One"), (975, "Two"))]}
print("CLASH", pw.build(129, two)[1])
cross = ps.linked_across({"14-across": ("Ramble by the sea?", "10,6", ["14-across", "22-across"]),
                          "22-across": ("See 14", None, None), "22-down": ("", "14", None),
                          "12-across": ("See 20", None, None), "20-down": ("Linked", "6,6", ["20-down", "12-down"]),
                          "12-down": ("See 20", None, None)})
print("CROSS", sorted(cross), cross["22-down"][0], cross["12-across"][0])
print("SLASH3", ps.column_cols([(0, 0, 1000, 1000)])([(10, 10, 60, 40, "ACROSS"), (10, 60, 60, 90, "7,"),
      (70, 60, 140, 90, "17/23"), (150, 60, 300, 90, "Truss"), (310, 60, 400, 90, "(5,7,6)")])[0][0][4])
print("PLUS", ps.column_cols([(0, 0, 1000, 1000)])([(10, 10, 60, 40, "DOWN"), (10, 60, 70, 90, "14+16"),
      (80, 60, 140, 90, "Cops"), (150, 60, 300, 90, "dirty"), (310, 60, 400, 90, "(6)")])[1][0][4],
      bool(ps.STARTS.match("14+16 Cops")))
print("TIDY", fa.tidy("ACROSS\n23 Maybe Charles slips one inside 4）").splitlines()[-1])
# No 279: one reading's "61" for 6 down, the others' 6 (one reading lost it).
L = lambda *ts: [(0, 0, 0, 0, t) for t in ts]
rw = {"djvu": [L("1 a"), L("5 b", "6 c", "7 d")], "ch": [L("1 a"), L("5 b", "61 c", "7 d")],
      "en": [L("1 a"), L("5 b", "7 d")], "tm": [L("1 a"), L("5 b", "6 c", "7 d")]}
fx = ps.renumbered(rw, lambda ws: ws)
odd = {"djvu": [L(), L("4 a", "5 b", "6 c", "7 d")], "ch": [L(), L("4 a", "56 c", "7 d")], "tm": [L(), L("4 a", "5 b", "6 c", "7 d")]}
print("RENUM", [l[4] for l in fx(rw["ch"])[1]], [l[4] for l in ps.renumbered(odd, lambda ws: ws)(odd["ch"])[1]])
# No 281: "1, 1D" (a link to 1 down, its direction letter set on), 1 down "See 1".
print("DIRECTED", ps.column_cols([(0, 0, 1000, 1000)])([(10, 10, 60, 40, "ACROSS"), (10, 60, 60, 90, "1,"),
      (70, 60, 140, 90, "1D"), (150, 60, 300, 90, "Fellow"), (310, 60, 400, 90, "(8,4)")])[0][0][4])
dl = ps.directed_links({"1-across": ("Fellow", "8,4", None), "1-down": ("See 1 Across", None, None),
                        "5-down": ("See 7", None, None), "7-across": ("Clue", "4", None)})
print("LINKS", dl["1-across"][2], dl["1-down"][0], dl["5-down"], ps.page_text(281, ps.linked_across(dl)).split(" DOWN")[0])
# No 294's "4, 16ac./22dn." and No 112's "23, 4dn.": the head's own number
# goes to the vote, the tails keep their directions for named_links.
nc = ps.column_cols([(0, 0, 1000, 1000)])
got = nc([(10, 10, 60, 40, "DOWN"), (10, 60, 60, 90, "4,"), (70, 60, 200, 90, "16ac./22dn."),
          (210, 60, 300, 90, "Her"), (310, 60, 400, 90, "(4,2,3,4)")])
print("NAMED", got[1][0][4], nc.named)
nl = ps.named_links({"4-down": ("Her", "4,2,3,4", None), "16-across": ("See 4dn", None, None),
                     "22-down": ("", None, None), "16-down": ("Ringo", "7", None)}, nc.named)
print("NAMEDLINKS", nl["4-down"][2], nl["16-across"][0], nl["22-down"][0], nl["16-down"][0],
      ps.page_text(294, nl).split(" DOWN ")[1].split(" (")[0])
held = ps.named_links({"4-down": ("Her", "4,2,3,4", None), "16-across": ("Own words", "4", None)}, nc.named)
print("NAMEDHELD", held["4-down"][2], held["16-across"][0])
# privateeye_wayback: "23/4dn" keeps the tail's direction, and 4 down's
# "See 23" joins 23 across though 23 down has a clue of its own.
print("LINKSIDES", pw.clue_rows("20 William (4) 23/4dn Cook some fowl (7,9) 25 Piss (7)", scan=True)[1],
      pw.clue_rows("14/22 A sound (5) 15 Next (4)", scan=True)[0])
ents = [{"number": 23, "direction": "across", "clue": "Cook"}, {"number": 4, "direction": "down", "clue": "See 23"},
        {"number": 23, "direction": "down", "clue": "Gets"}]
was = pw.named_tails({"across": [{"number": "23,4", "linkSides": {"4": "down"}}]}, ents)
print("TAILS", was, ents[1]["clue"])
# No 269's clue list: two grids fit it (an edge down light in column 13 or 14).
import reconstruct_grid as rg
g269a = ["#............##", "#.#.#.#.#.#.##.", "......#........", "#.#.#.#.#.#.##.", "........#......",
         "###.#.#.#.####.", "....##.........", ".##.#.###.#.##.", ".........##....", ".####.#.#.#.###",
         "......#........", ".##.#.#.#.#.#.#", "........#......", ".##.#.#.#.#.#.#", "##............#"]
g269b = ["#............##", "#.#.#.#.#.#.#.#", "......#........", "#.#.#.#.#.#.#.#", "........#......",
         "###.#.#.#.###.#", "#....#.........", "#.#.#.###.#.#.#", ".........#....#", "#.###.#.#.#.###",
         "......#........", "#.#.#.#.#.#.#.#", "........#......", "#.#.#.#.#.#.#.#", "##............#"]
lights = rg.lights_from_grid(g269b)
rows = {d: [{"number": str(n), "clue": f"Clue {n}", "enumeration": str(size)}
            for n, dd, size in lights if dd == d] for d in ("across", "down")}
spec = [(n, d, size) for n, d, size in lights]
print("FITS", pw.grid_misfits(g269b, spec), pw.grid_misfits(g269a, spec)[:1])
print("AMBIG", pw.from_rows(269, rows)[1])
got, _ = pw.from_rows(269, rows, image=g269b)
print("IMAGE", list(rg.grid_of(got)) == g269b, got.get("gridFromScan"))
bad = [{2: "......#.......#", 4: "........#.....#", 6: "#....#........#"}.get(i, r) for i, r in enumerate(g269b)]
print("MISFIT", pw.from_rows(269, rows, image=bad)[1])
# A scan grid with one cell misread (No 44's 20ac): one flip prints the list.
one = [r if i != 9 else "#" + r[1:] if r[0] == "." else "." + r[1:] for i, r in enumerate(g269b)]
fixed, cells = pw.repair_grid(one, spec)
got, _ = pw.from_rows(269, rows, image=one)
print("REPAIR", fixed == g269b, cells, got.get("gridFromScan"), list(rg.grid_of(got)) == g269b)
# An OCR-misread count (No 30's 22dn "(6)" for "(5)"), put right only by a recorded row.
eid = f"{spec[0][0]}-across"
misread = {d: [dict(r) for r in rs] for d, rs in rows.items()}
misread["across"][0]["enumeration"] = "9"
fx = {("cyclops-269", eid): ({"enumeration": "9"}, {"enumeration": str(spec[0][2])}, "test")}
print("COUNTED", pw.correct_counts(269, misread, fx)["across"][0]["enumeration"] == str(spec[0][2]),
      pw.correct_counts(269, misread, {})["across"][0]["enumeration"],
      pw.correct_counts(269, rows, fx)["across"][0]["enumeration"] == str(spec[0][2]))
print("HINT", pw.count_hint(30, ["22 down counts 6, 5 cells"]).split(" = ")[0],
      repr(pw.count_hint(30, ["7 across is numbered 8"])))

out_text = sys.stdout.getvalue()
sys.stdout = _stdout


def got(key):
    return "\n".join(l[len(key) + 1:] for l in out_text.splitlines() if l.startswith(key + " "))


check('a LINE across both columns is cut at the gap',
      '13', got("SPLIT"))
check('two clue columns found, left then right, a clue saying crossword in them',
      '2 True True', got("COLS"))
check("the heading's number, else the solution's + 1, never the address's 6",
      '13 13 None', got("NUMBER"))
check('rules between the heading and its number skipped; Crossword N winner is not it',
      '280 None', got("RULED"))
check("the columns read ACROSS then DOWN, a linked head's slash a comma",
      '4 4 20, 12 Linked clue (6,6)', got("SIDES"))
check('a linked head prints 20/12 and a continuation See 20',
      'EYE CROSSWORD 13 ACROSS 1 Clue one here (5) DOWN 1 First down clue (4,4) 12 See 20 20/12 Linked clue (6,6)', got("TEXT"))
check('read_capture parses the page text',
      "13 [('1', 'First down clue', '4,4'), ('12', 'See 20', None), ('20,12', 'Linked clue', '6,6')]", got("CAPTURE"))
check('a blank two readings print as (See 20 down) is See 20; others stay blank',
      "See 20 ['5-across']", got("SEE"))
check('two pages reading one number with different clues are refused',
      "two scans' page images print different clues under this number", got("CLASH"))
check("a link across directions: the other direction's See light kept, the vote's made one gone",
      "['12-across', '14-across', '20-down', '22-down'] See 14 See 20", got("CROSS"))
check("a three-light head's slash after a comma is a comma too",
      '7, 17, 23 Truss (5,7,6)', got("SLASH3"))
check('a full-width bracket reads as a round one',
      '23 Maybe Charles slips one inside (4)', got("TIDY"))
check('a number one reading alone prints, a digit too many, is renumbered; an unsure one is not',
      "['5 b', '6 c', '7 d'] ['4 a', '56 c', '7 d']", got("RENUM"))
check("a link's tail with a direction letter is dropped before the vote",
      '1 Fellow (8,4)', got("DIRECTED"))
check("the other list's See 1 Across makes the link back, as the Eye's 1/1",
      "['1-across', '1-across'] See 1 ('See 7', None, None) EYE CROSSWORD 281 ACROSS 1/1 Fellow (8,4) 7 Clue (4)", got("LINKS"))
check("a head naming its tails' directions keeps only its number for the vote",
      "4 Her (4,2,3,4) {('down', 4): {((16, 'across'), (22, 'down')): 1}}", got("NAMED"))
check('named_links groups the head as printed, each tail See 4, another light left alone',
      "['4-down', '16-across', '22-down'] See 4 See 4 Ringo 4/16ac/22 Her", got("NAMEDLINKS"))
check('a named tail with words of its own leaves the head alone',
      'None Own words', got("NAMEDHELD"))
check("a link's tail direction is kept from 23/4dn; a clue's opening A is no direction",
      "{'number': '23,4', 'clue': 'Cook some fowl', 'enumeration': '7,9', 'linkSides': {'4': 'down'}} {'number': '14,22', 'clue': 'A sound', 'enumeration': '5'}", got("LINKSIDES"))
check("the named tail points at its head's direction for grouping, its printed clue kept",
      "{'4-down': 'See 23'} See 23 across", got("TAILS"))
check("both grids No 269's list allows print it exactly",
      '[] []', got("FITS"))
check('two grids fitting the clue list alone still refuse',
      'grid did not rebuild: at least 2 grids fit the clue list', got("AMBIG"))
check("the scan's grid, printing exactly the list's lights, settles it",
      'True True', got("IMAGE"))
check("a scan's grid that disagrees with the list settles nothing",
      "grid did not rebuild: at least 2 grids fit the clue list; the scan's grid: 9 across counts 8, 7 cells, 11 across counts 6, 5 cells, 13 across counts 9, 8 cells; if the page prints the scan's length, add fetch_puzzle.SOURCE_LIGHT_WRONG[('cyclops-269', '9-across')] = ({'enumeration': <as read>}, {'enumeration': <as printed, 7 letters>}, why)", got("MISFIT"))
check('a scan grid one misread cell off is flipped back, only when one flip fits',
      'True ((9, 0),) True True', got("REPAIR"))
check('a misread count is put right by a SOURCE_LIGHT_WRONG row, never without, a stale row left alone',
      'True 9 True', got("COUNTED"))
check('a plus-joined head is a link head, as a slash (No 152)',
      '14, 16 Cops dirty (6) True', got("PLUS"))
check('a count-only misfit names the row to add; a numbering misfit does not',
      "; if the page prints the scan's length, add fetch_puzzle.SOURCE_LIGHT_WRONG[('cyclops-30', '22-down')] ''", got("HINT"))

# A vote that lays a light with no words and names no blank must not win the
# fewest-blank choice: it is blank, left to the VLM, not "clues with no words".
import archive_org_listener as _AL
import privateeye_scans as _ps
_real_vote = _AL.vote


def _fake_vote(words, verdict, cols=None, lengths=None):
    if len(words) == 4:
        return {"blank": {"2-across": "x"}}, {"1-across": ("Whole clue", "8", None), "2-across": ("", "4", None)}
    return {}, {"1-across": ("", "8", None), "2-across": ("Other", "4", None)}


_AL.vote = _fake_vote
try:
    _v, _l = _ps.voted({"a": [], "b": [], "c": [], "d": []}, lambda w: ([], []))
finally:
    _AL.vote = _real_vote
check("voted counts a bare light as blank, so the reading with the clue wins",
      "{'2-across': 'x'} Whole clue", f"{_v.get('blank')} {_l['1-across'][0]}")

# No 215: two readers lost the "(9)" ending 18 across, so "20 Enjoy sport ..."
# ran into it and 20 across was lost from the list. A clue with no count is
# closed "(?)" where the next clue's number starts a line, a "See" clue and a
# wrapped line that starts with a digit are left, and a count the chosen
# reading lost is the one another reading laid.
def _line(text):
    return (0, 0, 0, 0, text)


_got = [l[4] for l in _ps.closed_clues([
    _line("15 Removed clothing and 'did'"), _line("someone? (6,3)"),
    _line("18 State if Tone's promises to voters"),
    _line("20 Enjoy sport with member but don't overdo"), _line("it (5)"),
    _line("22 Dutch produce crack loyalists (5)"), _line("24 See 10 ac."),
    _line("25 Pock-mark on star (7)"),
    _line("26 Wrapped clue about the"), _line("3 Oceans (7)"),
    _line("27 Exit (8)")])]
check("a clue whose count is lost is closed before the next clue",
      "18 State if Tone's promises to voters (?)", _got[2])
check("a clue with its count on the next line is left",
      "20 Enjoy sport with member but don't overdo", _got[3])
check("a See clue is left", "24 See 10 ac.", _got[6])
check("a wrapped line that starts with a number starts no clue", "26 Wrapped clue about the", _got[8])
_parsed, _ = _AL.parse("ACROSS\n" + "\n".join(_got[2:]) + "\nDOWN\n2 A (3)\n3 B (4)")
check("the closed list parses 18 and 20 as clues of their own", [18, 20, 22, 24, 25, 26, 27],
      [min(c["tokens"][0]) for c in _parsed["across"]])
# No 49: "6/15a Hurley's" is 6 and 15 across; the mark made "6, 15a" no head.
check("a tail marked with the list's own direction is a plain link", "6, 15 Hurley's (7,5,8)",
      _ps.same_side_tail("6, 15a Hurley's (7,5,8)", 0))
check("a tail marked with the other direction is left", "6, 15d Hurley's",
      _ps.same_side_tail("6, 15d Hurley's", 0))
check("a word 'a' after the tail is no mark", "6, 15 a Hurley's", _ps.same_side_tail("6, 15 a Hurley's", 0))
check("pick takes the count another reading laid when the sound reading lost it", "9",
      _AL.pick([{"18-across": ("State if Tones broken promises to voters", None, None)},
                {"18-across": ("State if Tones broken promises to voters", "9", None)}])["18-across"][1])

if fails:
    print(f"{fails} failed")
    sys.exit(1)
print("all ok")
