#!/usr/bin/env python3
"""Guard: OCR / text fixes live in the central modules, never in a per-source
reader or fetcher. See docs/OCR.md "One home for text fixes".

    python3 tools/test_ocr_text_central.py

An OCR / text fix is a rewrite of clue, heading, preamble or count text that
undoes damage done by the print, the scan, the OCR engine, the PDF or the page
encoding. This test finds one by what it is made of, whatever it is called, in
every tools/*.py that is not a central module (CENTRAL below):

  1. translate / maketrans: a character-for-character table;
  2. a sub / subn / replace whose string argument holds a typographic mark an
     OCR or encoding gives (dashes, curly quotes, ellipsis, ligatures, Mac
     Roman punctuation): dash, quote and ellipsis normalisation;
  3. a regex character class holding a letter-for-digit confusion
     ([|lI], [1l], [O0], ...): l/1/I/|/O/0 tables;
  4. a dict or str of single characters mapping to single characters, three or
     more of them: a confusion table.

Legitimate per-source code (page layout, finding the puzzle page, grid
geometry, HTML parsing, URL logic) holds none of these. A hit that is not a
text fix (a comparison key, a search index) is listed in ALLOWED with a reason;
a fix goes into tools/clue_text.py (or quotes.py, dashes.py, enumeration.py)
where every source gets it. The test fails with the file, line and call.
"""
import ast
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent

#: The modules that own text fixes: these may do anything.
CENTRAL = {
    "clue_text.py": "the one pipeline: headings, counts, numbering, see/run-on repair",
    "clue_repair.py": "list repair from voting readings",
    "ocr_clues.py": "the OCR readers and their vote",
    "quotes.py": "quote, ligature and apostrophe normalisation",
    "dashes.py": "dash normalisation",
    "enumeration.py": "enumeration/count text and space collapsing",
    "punctuation.py": "clue punctuation",
    "leading_quote.py": "a clue's opening quote",
    "collapse_clue_spaces.py": "space collapsing in clues",
    "mend_clue_punctuation.py": "clue punctuation mending",
    "vlm_reader.py": "the VLM reader",
}

#: (file, enclosing function) -> why a hit there is not an OCR/text fix.
#: Keep it short: a real text fix moves to clue_text.py instead of landing here.
ALLOWED = {
    ("gale_listener.py", "lookalike"): "Greek-to-Latin comparison key between two readings; never written back",
    ("gale_listener.py", "<module>"): "the LOOKALIKE comparison table lookalike() uses",
    ("apply_solution.py", "_fold"): "folds an answer to a lookup key (definitions.LOOKALIKES); answers, not clue text",
    ("ctc_transcripts.py", "norm"): "word key for matching transcript words; never written back",
    ("fetch_abbreviations.py", "expansions"): "HTML parsing: drops bracketed/quoted notes round an abbreviation's meanings",
    ("fetch_puzzle.py", "separators"): "a format string's apostrophe, not clue text",
    ("ft_pdf_puzzles.py", "parse_clues"): "possessive 's stripped to compare words for a layout test",
    ("genius_puzzles.py", "read_pdf"): "layout: drops the numbers of a jigsaw's alphabetical list from its preamble",
    ("parse_bigdave44.py", "rendered_lines"): "HTML parsing: writes the blog's answer separator, not repairing text",
    ("train_archive_org_tesseract.py", "<module>"): "the ASCII table of tesseract's training charset",
    ("train_archive_org_tesseract.py", "words"): "training-corpus word key",
    ("train_archive_org_tesseract.py", "real"): "ASCII fold to the tesseract model's charset",
    ("train_archive_org_tesseract.py", "corpus_clues"): "ASCII fold to the tesseract model's charset",
}

CONFUSION_CLASS = re.compile(r"\[[^\]]*(?:1l|l1|0O|O0|Il|lI|1I|I1|\|[lI1])[^\]]*\]")
#: Typographic marks an OCR, a PDF or an encoding puts in text.
MARKS = re.compile("[‐-―‘-‟…−­ﬀ-ﬆ"
                   "ÕÔÒÓÐÑ«»‚„]")
CALLS = {"sub", "subn", "replace"}


def literals(node):
    return "".join(n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str))


def scopes(tree):
    """Each node with the name of the function it sits in ("<module>" at top)."""
    out = {}

    def walk(node, where):
        for child in ast.iter_child_nodes(node):
            w = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else where
            out[child] = w
            walk(child, w)
    walk(tree, "<module>")
    return out


def hits(path):
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    where = scopes(tree)
    found = []
    for n in ast.walk(tree):
        why = None
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            lits = literals(n)
            if n.func.attr in ("translate", "maketrans"):
                why = f"{n.func.attr}: a character table"
            elif n.func.attr in CALLS and MARKS.search(lits):
                why = "dash/quote/ellipsis/ligature normalisation"
            elif n.func.attr in CALLS and CONFUSION_CLASS.search(lits):
                why = "letter-for-digit confusion class"
            elif n.func.attr == "replace" and len(n.args) >= 2 and all(
                    isinstance(a, ast.Constant) and isinstance(a.value, str) and len(a.value) == 1 for a in n.args[:2]
            ) and {a.value.isdigit() for a in n.args[:2]} == {True, False} and any(
                    a.value in "lIO|SZBoq" for a in n.args[:2]):
                why = "a letter replaced by a lookalike digit (or back)"
        elif isinstance(n, ast.Dict) and len(n.keys) >= 3 and all(
                isinstance(k, ast.Constant) and isinstance(k.value, str) and len(k.value) == 1
                and isinstance(v, ast.Constant) and isinstance(v.value, str) and len(v.value) == 1
                for k, v in zip(n.keys, n.values)):
            why = "a table of single characters to single characters"
        if why:
            seg = (ast.get_source_segment(src, n) or "").replace("\n", " ")[:90]
            found.append((n.lineno, where.get(n, "<module>"), why, seg))
    return found


#: A module is a source reader when its name says it fetches, files or parses a
#: paper's puzzles, or when it imports an OCR / PDF / image library or the OCR
#: readers: that catches a new reader under any name.
READER_NAME = re.compile(r"(fetch_|file_|parse_|.*_puzzles|privateeye_|andlit_|gale_|archive_org_|ft_|ctc_|trove_|"
                         r"cyclops_|listener_|scan_|train_|clues_only|apply_solution|acquire_|book_|recover_)")
READER_IMPORT = {"ocr_clues", "pypdf", "pdfplumber", "fitz", "pytesseract", "rapidocr_onnxruntime", "PIL", "cv2"}


def imports(tree):
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            names |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            names.add(n.module.split(".")[0])
    return names


def is_reader(path):
    return bool(READER_NAME.match(path.stem)) or bool(imports(ast.parse(path.read_text(encoding="utf-8"))) & READER_IMPORT)


def violations():
    bad, used = [], set()
    for path in sorted(TOOLS.glob("*.py")):
        if path.name.startswith("test_") or path.name in CENTRAL or not is_reader(path):
            continue
        for line, fn, why, seg in hits(path):
            if (path.name, fn) in ALLOWED:
                used.add((path.name, fn))
                continue
            bad.append(f"tools/{path.name}:{line} in {fn}(): {why}: {seg}")
    return bad, used


def main():
    bad, used = violations()
    stale = sorted(set(ALLOWED) - used)
    missing = sorted(f for f in CENTRAL if not (TOOLS / f).exists())
    if bad or stale or missing:
        for b in bad:
            print("FAIL", b)
        if bad:
            print("\nAn OCR/text fix belongs in tools/clue_text.py (or quotes.py, dashes.py,"
                  " enumeration.py), where every source gets it. Move it there with a test in"
                  " tools/test_clue_text.py and call it from the reader. If the hit is not a"
                  " text fix, add (file, function): reason to ALLOWED in this file.")
        for s in stale:
            print("FAIL stale ALLOWED entry (no hit there any more, remove it):", s)
        for m in missing:
            print("FAIL CENTRAL names a module that is gone:", m)
        return 1
    print(f"ok   no OCR/text fix outside the {len(CENTRAL)} central modules ({len(ALLOWED)} allowed non-fixes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
