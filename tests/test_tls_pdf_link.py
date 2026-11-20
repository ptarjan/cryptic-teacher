#!/usr/bin/env python3
# Does tools/tls_puzzles.py's pdf_link find the page PDF the-tls.com hosts for a crossword article?
#
#     python3 tests/test_tls_pdf_link.py
import _path  # puzzles tools/ on sys.path
import tls_puzzles as t

html = '<p><a href="https://www.the-tls.com/wp-content/uploads/2025/09/TLS.047.1GM.19sep_1683684557_cropped.pdf">PDF</a></p>'
assert t.pdf_link(html) == "https://www.the-tls.com/wp-content/uploads/2025/09/TLS.047.1GM.19sep_1683684557_cropped.pdf"
assert t.pdf_link('<img src="https://www.the-tls.com/wp-content/uploads/2025/09/Crossword-1621.png">') is None
assert t.pdf_link(None) is None
# the article's "sites/7" path 404s; the file is served without it
assert t.pdf_link('<a href="https://www.the-tls.com/wp-content/uploads/sites/7/2025/01/pdfresizer.com-pdf-crop-2.pdf">x</a>') \
    == "https://www.the-tls.com/wp-content/uploads/2025/01/pdfresizer.com-pdf-crop-2.pdf"
print("ok")
