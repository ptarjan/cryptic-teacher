#!/usr/bin/env python3
# Does tools/andlit_azed.py read the Guardian's printable Azed copies: the
# bars off a PDF's ruled lines (stroked or filled, next to a smaller solution
# grid), the HTML print page's bordered table, and the clue list?
#
#     python3 tests/test_andlit_azed.py
#
# Hand-built inputs only. Nothing here reads the network, the cache or the corpus.
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
fails = 0


def check(what, expected, got):
    global fails
    if expected == got:
        print(f"ok   {what}")
    else:
        print(f"FAIL {what}: expected [{expected}], got [{got}]")
        fails += 1


PROG = r'''import andlit_azed as A
import listener_puzzles as L
import reconstruct_grid as rg

# A 6x6 grid at pitch 20 whose bars sit right of (1, 2) and below (3, 4),
# beside a 6x6 solution grid at pitch 10 with a bar of its own.
def lattice_ops(x0, y0, pitch, thin, bars, stroked):
    ops = []
    def line(x1, y1, x2, y2, w):
        if stroked:
            ops.extend([([w], b"w"), ([x1, y1], b"m"), ([x2, y2], b"l"), ([], b"S")])
        elif x1 == x2:
            ops.extend([([x1 - w / 2, y1, w, y2 - y1], b"re"), ([], b"f")])
        else:
            ops.extend([([x1, y1 - w / 2, x2 - x1, w], b"re"), ([], b"f")])
    top = y0 + 6 * pitch
    for i in range(7):
        line(x0 + i * pitch, y0, x0 + i * pitch, top, thin)
        line(x0, y0 + i * pitch, x0 + 6 * pitch, y0 + i * pitch, thin)
    for kind, y, x in bars:
        if kind == "r":     # the line right of cell (y, x), drawn 1pt off it
            line(x0 + (x + 1) * pitch + 1, top - (y + 1) * pitch, x0 + (x + 1) * pitch + 1, top - y * pitch, 2.5)
        else:
            line(x0 + x * pitch, top - (y + 1) * pitch, x0 + (x + 1) * pitch, top - (y + 1) * pitch, 2.5)
    return ops

for stroked in (True, False):
    ops = (lattice_ops(300, 300, 10, 0.25, [("b", 0, 0)], stroked)
           + lattice_ops(40, 100, 20, 0.5, [("r", 1, 2), ("b", 3, 4)], stroked))
    grid, xs, ys = A.read_bars(A.segments(ops))
    print(f"bars-{'stroked' if stroked else 'filled'}", "/".join(grid))

# Cell numbers that came out of the text as one string are split as the grid reads them.
starts = {(0, 0): 1, (0, 8): 8, (0, 9): 9}
print("split", sorted(A.split_numbers({(0, 0): "1", (0, 8): "89"}, starts).items()))
print("nosplit", sorted(A.split_numbers({(0, 0): "1", (0, 8): "89", (0, 9): "9"}, starts).items()))

# The HTML print page: a 2px right or bottom border is a bar; the frame is not.
cell = '<td valign="top" id=square{}><font>{}</font></td>'
rows = []
for y in range(3):
    tds = ""
    for x in range(3):
        style = []
        if (y, x) == (0, 1) or x == 2:
            style.append("border-right: solid 2px black;")
        if (y, x) == (1, 0) or y == 2:
            style.append("border-bottom: solid 2px black;")
        num = {(0, 0): "1", (0, 1): "2", (0, 2): "3", (1, 0): "4"}.get((y, x), "&nbsp;")
        tds += cell.format(f' style="{"".join(style)}"' if style else "", num)
    rows.append(f"<tr>{tds}</tr>")
page = ("<h1>Azed Crossword No. 1736</h1><B>Special instructions: </B>The Chambers Dictionary"
        " (2003) is recommended.</font><table>" + "".join(rows) + "</table>"
        "<B>Across</b><TR><TD><B>1</B>&nbsp;</TD><TD>Some clue&nbsp;(2)</TD></TR></table>")
h = A.read_html(page)
print("html", h["number"], "/".join(h["grid"]), sorted(h["printed"].items()))
print("plain", A.special("Plain", h), A.special("", h), A.special("‘Playfair’", h))

# A clue opens only on the next light the grid numbers, and ends at its count,
# so the notes and form lines between clues fall away.
lines = {"across": ["1 First clue that runs", "on (5)", "Name", "Address", "1, anag. note",
                    "7Second (4)"],
         "down": ["2 Down one (3, 2 words)", "Post code", "3 Down two (4)"]}
print("clues", A.clue_list(lines, {(1, "across"), (7, "across"), (2, "down"), (3, "down")}))
print("entry", A.entry_of((2, "down"), "Down one (3, 2 words)", {})["clue"])

# An unanswered light is written from crossings that cover every one of its cells.
grid = ["...", "...", "..."]
lights = rg.light_cells(grid)
entries = [{"number": n, "direction": d, "answer": a} for (n, d), a in zip(
    sorted(lights), ["CAT", "COW", None, "TED", "ORE", "WED"])]
filled = A.fill_from_crossings(grid, entries)
print("fill", filled and [e["answer"] for e in filled])

# Ligature and digit glyphs an encoding's /Differences names.
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject
font = DictionaryObject({NameObject("/Encoding"): DictionaryObject({NameObject("/Differences"): ArrayObject(
    [NumberObject(27), NameObject("/T_h"), NameObject("/ffl"), NameObject("/fi"),
     NameObject("/figuredash"), NameObject("/f.short"), NameObject("/one")])})})
chars, _ = L._font_table(font)
print("glyphs", [chars[c] for c in range(27, 33)])

# A scan's stored reading (read_scan's vote and fitted grid): every clue
# agreed files, a lost count taken from its light; one clue the readers do
# not agree on, or whose words OCR wrote, holds the copy.
voted = {"1-across": ["Feline found in the attic", "3"], "4-across": ["Bovine animal", None],
         "5-across": ["Exist, they say (3)", None], "1-down": ["Teddy, at heart", "3"],
         "2-down": ["Mineral in store", "3"], "3-down": ["Married in a wedding", "3"]}
stored = {"sha": "x", "version": A.SCAN_VERSION, "verdict": {}, "rows": grid, "exact": True, "clues": voted}
p, cause, _ = A.assemble(1800, A.scan_copy(stored), "u", None, None, "Plain")
print("scan-files", cause, p and [e["clue"]["text"] for e in sorted(p["entries"], key=lambda e: (e["direction"], e["number"]))][:3])
# Clues are the only must-have: a special files with no post, carrying its
# preamble, or awaitsPreamble when none was read; its count may be the full
# answer's (Letters Latent) and a wordless "*5 (3)" light is "See preamble".
# A plain puzzle's count that misses its light still holds (mirror).
sp = A.scan_copy(stored)
p, cause, _ = A.assemble(1800, dict(sp, preamble="Answers to clues in italics are encoded."), "u", None, None, "‘Playfair’")
print("special-files", cause, p and p.get("preamble"), p and p.get("awaitsPreamble"))
p, cause, _ = A.assemble(1800, sp, "u", None, None, "‘Playfair’")
print("special-awaits", cause, p and p.get("awaitsPreamble"))
long = A.scan_copy(dict(stored, clues=dict(voted, **{"2-down": ["Mineral in store", "4"], "5-across": ["", "3"]})))
long["clues"][(5, "across")] = "(3)"
p, cause, _ = A.assemble(1800, dict(long, preamble="Letters Latent: one letter omitted."), "u", None, None, "‘Letters Latent’")
print("special-loose", cause, p and [e["clue"] for e in p["entries"] if e["number"] in (2, 5)])
print("plain-loose", A.assemble(1800, dict(long, clues={**long["clues"], (5, "across"): "Exist (3)"}), "u", None, None, "Plain")[1])
# The PDF's instructions: form labels dropped, a full-width line cut in two
# by column_lines joined (an overprinted number kept once), Playfair rows
# moved after the text, and the Chambers line taken out only when whole.
runs = [(0, 40, 300, 7.0, "Name"), (0, 40, 290, 7.0, "In a Playfair square the code-"),
        (0, 40, 280, 7.0, "word is first. A clue to 37"), (0, 150, 280, 7.0, "37 is wanted."),
        (0, 40, 270, 7.0, "E S T I C"), (0, 40, 250, 9.0, "ACROSS")]
print("pdf-preamble", repr(A.pdf_preamble(runs, [(0, 0, "ACROSS")], 9.0, [30, 200], [320, 310])))
print("chambers", repr(A.CHAMBERS.sub("", "The Chambers Dictionary (2003) is recommended. Ten clues are odd.").strip()),
      repr(A.CHAMBERS.sub("", "The Chambers Dictionary (2003) is recommended but lacks 30.")))
print("lost-bracket", A.entry_of((1, "across"), "You can’t —— that! 6)", {})["enumeration"],
      A.entry_of((1, "across"), "Alert and savvy (11, 3 words, apostrophe)", {})["clue"])
print("overprint", [r[4] for r in A.overprinted_once([(0, 1, 2, 7, "2 Latent"), (0, 1, 2, 7, "2 Latent From the"), (0, 1, 2, 7, "x"), (0, 1, 2, 7, "x")])])
blanked = dict(stored, clues=dict(voted, **{"2-down": ["", "3"]}))
print("scan-blank", A.assemble(1800, A.scan_copy(blanked), "u", None, None, "Plain")[1])
joined = dict(stored, clues=dict(voted, **{"2-down": ["Mineral instorexq", "3"]}))
print("scan-no-clues", A.assemble(1800, A.scan_copy(dict(stored, clues={})), "u", None, None, "Plain")[1])
print("scan-suspect", A.assemble(1800, A.scan_copy(joined), "u", None, None, "Plain")[1])
# A number the fitted grid has no light for (No 1823's "83" for 8 Down,
# No 1835's "1" for 11 Down): empty, or another light's clue again, it is
# a misread number and dropped; with words of its own it is a lost clue.
phantom = dict(voted, **{"83-down": ["", "3"], "11-down": ["Mineral in store", None]})
print("scan-phantom", A.assemble(1800, A.scan_copy(dict(stored, clues=phantom)), "u", None, None, "Plain")[1])
own = dict(voted, **{"11-down": ["Wholly another clue", None]})
print("scan-phantom-own", A.assemble(1800, A.scan_copy(dict(stored, clues=own)), "u", None, None, "Plain")[1])
# Two words a reader ran together pass the lexicon ("maybe"+"heard", the
# rare "undertime" whose pair the corpus prints): held. A real compound
# ("afresh") and a dialect "climbin'" are no such pair, nor are No 1822's
# "cookroom" and "rodmen" (rare lexicon words whose halves the corpus never
# prints as a pair), No 1839's "inbuilt" (the corpus prints it whole) or
# the name "Notus".
print("real-words", [A.run_together(w) for w in ("cookroom", "rodmen", "inbuilt", "Notus")])
print("real-words-mirror", [A.run_together(w) for w in ("undertime", "notus")])
for name, text in (("ran-together", "Mineral maybeheard in store"), ("ran-together-rare", "Black undertime a store"),
                   ("not-ran-together", "Mineral afresh in store")):
    print(name, A.assemble(1800, A.scan_copy(dict(stored, clues=dict(voted, **{"2-down": [text, "3"]}))),
                           "u", None, None, "Plain")[1])
# Two words every reader ran together, one split alone into a pair the
# corpus prints ("stuckinto"): spaced and filed. A dropped g ("climbin")
# could be "climbin'" or "climb in": held.
for name, text in (("split-run", "Mineral stuckinto store"), ("split-run-mirror", "Mineral climbin store")):
    got = A.scan_copy(dict(stored, clues=dict(voted, **{"2-down": [text, "3"]})))
    print(name, A.assemble(1800, got, "u", None, None, "Plain")[1], got["clues"][(2, "down")])
# The voted count's tail glued to the last word, its bracket lost (No
# 1769's "centrepiece(10,3words"): put back as the count. A tail whose
# number is not the voted count stays, and holds.
for name, text in (("glued-count", "Mineral in(3,2words"), ("glued-count-mirror", "Mineral in(4,2words")):
    got = A.scan_copy(dict(stored, clues=dict(voted, **{"2-down": [text, "3"]})))
    print(name, A.assemble(1800, got, "u", None, None, "Plain")[1], got["clues"][(2, "down")])
print("dropped-g", A.run_together("climbin'"), A.run_together("climbin"))

# A rotated page reads like the upright one: by /Rotate, or (No 2482) by a cm
# matrix that draws the whole landscape page sideways with no /Rotate. The
# grid's lines are filled four-corner polygons there, not `re`.
import io, pypdf
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject

def fixture(wrap="", rotate=0):
    body = ["0.25 w"]
    for i in range(7):
        body.append(f"{100 + 20 * i} 500 m {100 + 20 * i} 620 l S 100 {500 + 20 * i} m 220 {500 + 20 * i} l S")
    # the bar right of cell (1, 2): a filled quad, 2.5pt thick
    body.append("159 600 m 159 580 l 161.5 580 l 161.5 600 l h f")
    body.append("BT /F1 12 Tf 100 700 Td (Azed No. 1800 Plain) Tj ET BT /F1 5 Tf 102 616 Td (1) Tj ET")
    body.append("BT /F1 8 Tf 100 480 Td (ACROSS) Tj ET BT /F1 8 Tf 100 470 Td (1 Some clue \\(2\\)) Tj ET")
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(595, 842)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    stream = DecodedStreamObject()
    stream.set_data((wrap + "\n".join(body) + ("\nQ" if wrap else "")).encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    if rotate:
        page[NameObject("/Rotate")] = NumberObject(rotate)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()

def look(data):
    r = A.read_pdf(data)
    return r["number"], "/".join(r["grid"] or ["none"]), sorted(r["printed"].items()), r["lines"]

upright_read = look(fixture())
print("rot-upright", upright_read[0], upright_read[1], upright_read[2])
# a page turned 90 degrees clockwise by its content, and 90 / 180 / 270 by /Rotate
print("rot-cm", look(fixture("q 0 -1 1 0 0 842 cm\n")) == upright_read)
print("rot-cm-ccw", look(fixture("q 0 1 -1 0 595 0 cm\n")) == upright_read)
print("rot-cm-half", look(fixture("q -1 0 0 -1 595 842 cm\n")) == upright_read)
print("rot-flag", [look(fixture(rotate=r)) == upright_read for r in (90, 180, 270)])

# A PDF that is one page image goes to the scan reader, not "not text".
import io, pathlib, tempfile
from PIL import Image
buf = io.BytesIO()
Image.new("RGB", (40, 40), "white").save(buf, "PDF")
scan = pathlib.Path(tempfile.mkdtemp()) / "1800.pdf"
scan.write_bytes(buf.getvalue())
print("scan-routed", A.read(scan, 1800, scans=False), A.page_image(scan).size)'''

proc = subprocess.run([sys.executable, "-"], input=PROG, text=True, stdout=subprocess.PIPE,
                      env={**__import__("os").environ, "PYTHONPATH": str(REPO / "tools")})
out = proc.stdout.rstrip("\n")
for ln in out.split("\n"):
    print("  | " + ln)


def line(key):
    for ln in out.split("\n"):
        if ln.startswith(key + " "):
            return ln.split(" ", 1)[1]
    return ""


check('PDF bars, stroked, beside a smaller grid',
      '....../..r.../....../....b./....../......', line('bars-stroked'))
check('PDF bars, filled rectangles',
      '....../..r.../....../....b./....../......', line('bars-filled'))
check('two cell numbers run together are split',
      '[((0, 0), 1), ((0, 8), 8), ((0, 9), 9)]', line('split'))
check('a number whose neighbour prints its own stays',
      '[((0, 0), 1), ((0, 8), 89), ((0, 9), 9)]', line('nosplit'))
check('HTML bars and numbers',
      '1736 .r./b../... [((0, 0), 1), ((0, 1), 2), ((0, 2), 3), ((1, 0), 4)]', line('html'))
check('the Chambers line alone is a plain puzzle',
      'False False True', line('plain'))
check('clues read past notes and form lines',
      "{(1, 'across'): 'First clue that runs on (5)', (7, 'across'): 'Second (4)', (2, 'down'): 'Down one (3, 2 words)', (3, 'down'): 'Down two (4)'}", line('clues'))
check('a count in figures is written in words',
      'Down one (3, two words)', line('entry'))
check('a missing answer comes from its crossings',
      "['CAT', 'COW', 'ARE', 'TED', 'ORE', 'WED']", line('fill'))
check('ligature and digit glyphs',
      "['Th', 'ffl', 'fi', '–', 'f', '1']", line('glyphs'))
check('a scan whose clues all agree files',
      "None ['Feline found in the attic', 'Bovine animal', 'Exist, they say']", line('scan-files'))
check('a special files with no post, carrying its preamble',
      'None Answers to clues in italics are encoded. None', line('special-files'))
check('a special with no preamble read files awaiting one',
      'None True', line('special-awaits'))
check("a special's count need not measure its entry; a wordless light is See preamble",
      "None [{'text': 'Mineral in store', 'enumeration': '4'}, {'text': 'See preamble', 'enumeration': '3'}]", line('special-loose'))
check('a plain count that misses its light still holds (mirror)',
      'enumeration', line('plain-loose'))
check('PDF preamble: labels out, full-width line joined, square after',
      "'In a Playfair square the codeword is first. A clue to 37 is wanted.\\nESTIC'", line('pdf-preamble'))
check('the Chambers line goes only when it is a whole sentence',
      "'Ten clues are odd.' 'The Chambers Dictionary (2003) is recommended but lacks 30.'", line('chambers'))
check("a count's lost bracket and an apostrophe count are read",
      '6 Alert and savvy (11, three words, apostrophe)', line('lost-bracket'))
check('bold overprints are kept once',
      "['2 Latent From the', 'x']", line('overprint'))
check('a scan with a clue unagreed is held',
      'ocr-blank', line('scan-blank'))
check('a scan cut off above its clues is held as such',
      'scan-no-clues', line('scan-no-clues'))
check('a scan clue OCR wrote is held',
      'ocr-blank', line('scan-suspect'))
check('an empty or copied clue on a light the grid lacks is dropped',
      'None', line('scan-phantom'))
check('a clue of its own on a light the grid lacks holds (mirror)',
      'clues-differ', line('scan-phantom-own'))
check('two words every reader ran together are spaced and filed',
      'None Mineral stuck into store (3)', line('split-run'))
check('a dropped g is not split, and holds (mirror)',
      'ocr-blank ', line('split-run-mirror'))
check('a count glued to the last word is put back',
      'None Mineral in (3, 2 words)', line('glued-count'))
check('a glued tail that is not the voted count holds (mirror)',
      'ocr-blank ', line('glued-count-mirror'))
check('a scan clue with two words run together is held',
      'ocr-blank', line('ran-together'))
check('a rare lexicon word that is two common ones is held',
      'ocr-blank', line('ran-together-rare'))
check('a compound is no words run together',
      'None', line('not-ran-together'))
check('real words run_together once held are words',
      '[None, None, None, None]', line('real-words'))
check('a rare word whose pair the corpus prints, or a small notus, is still two (mirror)',
      "['under time', 'not us']", line('real-words-mirror'))
check('a dropped g is none either, though its letters are',
      'None climb in', line('dropped-g'))
check('the upright fixture reads its grid, bar and number',
      "1800 ....../..r.../....../....../....../...... [((0, 0), '1')]", line('rot-upright'))
check('a page drawn sideways by a cm matrix reads like the upright one',
      'True', line('rot-cm'))
check('a page drawn the other way up reads the same',
      'True', line('rot-cm-ccw'))
check('a page drawn upside down reads the same',
      'True', line('rot-cm-half'))
check('a page with /Rotate reads the same',
      '[True, True, True]', line('rot-flag'))
check('an image-only PDF is a scan, not not-text',
      'scan (40, 40)', line('scan-routed'))

if fails == 0:
    print("all passed")
else:
    print(f"{fails} failed")
    sys.exit(1)
