#!/usr/bin/env bash
# An OCR'd clue opens with a quote only when it is a quotation
# (tools/leading_quote.py): a stray unclosed quote and a clue number leaked
# after one go, an attributed quotation that lost its closing quote is closed,
# a matched quotation, an elision and a dropped h stand, offsets move with the
# text, a publisher's clue is never touched, both OCR readers finish a clue
# through it, and the write gate refuses what it would still mend.
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import copy
import leading_quote as lq
import light_spec
import ocr_clues
import parse_penguin_book
import provenance
import puzzle_integrity

fails = 0
def check(name, want, got):
    global fails
    fails += want != got
    print(("ok  " if want == got else "FAIL"), name, "" if want == got else f"want {want!r} got {got!r}")

CASES = [
    # Leaked numbers (book-43001 5-across, the reader's commit e0ec2947ff).
    ("quote + number", '"5 Covered with a coat and prepared for stardom perhaps',
     "Covered with a coat and prepared for stardom perhaps"),
    ("quote, space, number", "' 16 Trivial conversation about top fashion designer?",
     "Trivial conversation about top fashion designer?"),
    ("number glued on", '"2Foul language or rude play upon words', "Foul language or rude play upon words"),
    ("number and hyphen", '"49-Vision? Yes, in eight', "Vision? Yes, in eight"),
    ("number and dash", '"1 — Unfortunate woman', "Unfortunate woman"),
    ("number with a contraction later", "'18 He's such a card!", "He's such a card!"),
    # Stray quotes.
    ("stray double", '"Recant (anag.).', "Recant (anag.)."),
    ("stray single before a consonant", "'Hasten.", "Hasten."),
    ("stray single before a space", "' A savage place", "A savage place"),
    # Attributed quotation missing its closing quote.
    ("attributed, double", '"Alone and palely — (Keats)', '"Alone and palely —" (Keats)'),
    ("attributed, single", "'Hence loathed ! (Milton)", "'Hence loathed !' (Milton)"),
    # Left alone.
    ("matched quotation", "'Things are in the — , And ride mankind.' (Emerson)",
     "'Things are in the — , And ride mankind.' (Emerson)"),
    ("matched double", '"Much have I travelled in the realms of " (Keats)',
     '"Much have I travelled in the realms of " (Keats)'),
    ("quote closed after a word", "'Times' term, an outstanding example", "'Times' term, an outstanding example"),
    ("quoted number, closed", "'3 4 2 — 11' was said of 10", "'3 4 2 — 11' was said of 10"),
    ("decade", "'60s youths adopting upper-class manner", "'60s youths adopting upper-class manner"),
    ("elision 'Tis", "'Tis appropriate", "'Tis appropriate"),
    ("elision after a double", '"Tis appropriate', '"Tis appropriate'),
    ("elision 'Zine", "'Zine on web covering oxygen generator", "'Zine on web covering oxygen generator"),
    ("dropped h, capital vowel", "'Orrible situation", "'Orrible situation"),
    ("dropped h, lower case", "'ampshire town as before", "'ampshire town as before"),
    ("no quote", "5 Covered with a coat", "5 Covered with a coat"),
    ("a lone quote", '"', '"'),
]
for name, given, want in CASES:
    check(name, want, lq.clean(given))
    check(name + " (idempotent)", want, lq.clean(want))
    new, at = lq.mapped(given)
    check(name + " (map length)", len(given) + 1, len(at))

check("OCR_CHANNELS is provenance's", tuple(provenance.OCR_CHANNELS), lq.OCR_CHANNELS)

# Both OCR readers finish a clue through it: the book reader as its light
# spec hands the clue on to be filed.
book = {"across": [parse_penguin_book.parse_clue_chunk('"5 Covered with a coat (6)')], "down": []}
check("book reader", "Covered with a coat", light_spec.build_spec(book)[0][0][3]["clue"])
check("newspaper vote", "Covered with a coat", ocr_clues.trimmed('"5 Covered with a coat', "5-across"))
check("before the vote, left for the vote", '"5 Covered with a coat',
      ocr_clues.trimmed('"5 Covered with a coat', "5-across", voted=False))

# A puzzle: OCR clue mended with its definition's offset moved; a publisher's untouched.
def puzzle(channel, text, definition):
    return {"id": "times-1", "source": {"retrievedFrom": channel}, "entries": [
        {"id": "1-across", "number": 1, "direction": "across",
         "clue": {"text": text, "enumeration": "4"},
         "annotation": {"definitions": [{"text": definition, "at": text.index(definition)}]}}]}

p = puzzle("newspaper", '"20 Report of one hungering for glory?', "glory")
out = lq.normalise(p)
e = out["entries"][0]
check("OCR puzzle mended", "Report of one hungering for glory?", e["clue"]["text"])
check("definition offset moved", e["clue"]["text"].index("glory"), e["annotation"]["definitions"][0]["at"])
check("caller's puzzle untouched", '"20 Report of one hungering for glory?', p["entries"][0]["clue"]["text"])
check("LEAD flags the OCR clue", ["LEAD"], [f[0] for f in (lambda fl: (puzzle_integrity.check_leading_quotes(p, fl), fl)[1])([])])
check("LEAD clear once mended", [], (lambda fl: (puzzle_integrity.check_leading_quotes(out, fl), fl)[1])([]))
pub = puzzle("publisher", "'54 English railway company's insignia", "insignia")
check("publisher's clue untouched", pub, lq.normalise(pub))
check("publisher's clue not flagged", [], (lambda fl: (puzzle_integrity.check_leading_quotes(pub, fl), fl)[1])([]))

# Clues-only records (all book reads).
rec = {"id": "book-1", "clues": {"across": [{"clue": {"text": "'7 It is unsuitable"}}], "down": []}}
check("clues-only mended", "It is unsuitable", lq.normalise_clues_only(rec)["clues"]["across"][0]["clue"]["text"])
check("clues-only unclean", 1, len(lq.unclean_clues_only(rec)))

print("FAILS", fails)
raise SystemExit(1 if fails else 0)
PY
