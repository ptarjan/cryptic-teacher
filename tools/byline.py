"""The setter a crossword's title prints beside its number, read from OCR words (read time only).

Measured per paper and era (tools/data/setter_unprinted.json holds the eras that print no name):
"Set by DANTE" (FT 1988 on), "No.5466 Saturday 24 April by Phi" / "CRYPTIC CROSSWORD 7344 BY PHI" /
"The Friday Crossword by Phi No 5992" (Independent weekdays, 1996 on), "TLS Crossword 946 by Tantalus"
(TLS No 894 on). A name is taken only from the title's own neighbourhood and never from clue text."""
import json
import re
from pathlib import Path

#: "Set by X", "by X", "BY X": the name is one capitalised word (the Independent's "Quixote", "Hypnos").
BYLINE = re.compile(r"(?i:set\s+by|compiled\s+by|\bby)\s+([A-Z][A-Za-z'’-]{2,20})\b")
#: Words that follow "by" in the title line without being a setter ("by Friday", the weekday and month names).
NOT_NAMES = frozenset(w.lower() for w in (
    "Monday Tuesday Wednesday Thursday Friday Saturday Sunday January February March April May June July "
    "August September October November December Solution Solutions Across Down Crossword Entries Answers "
    "The Mr Mrs").split())
UNPRINTED = Path(__file__).with_name("data") / "setter_unprinted.json"


def name_in(text):
    """The title-case setter the first "by X" of `text` names, or None."""
    for m in BYLINE.finditer(text):
        if m.group(1).lower() not in NOT_NAMES:
            return m.group(1).title()
    return None


def near_title(words, box, above=40, below=130, left=150, right=500):
    """The setter named by the words round a title `box` (x0, y0, x1, y1): words are
    (x0, y0, x1, y1, text), read in row then column order."""
    x0, y0, x1, y1 = box
    band = [w for w in words
            if y0 - above <= (w[1] + w[3]) / 2 <= y1 + below and x0 - left <= w[0] <= x1 + right]
    band.sort(key=lambda w: (round(w[1] / 20), w[0]))
    return name_in(" ".join(w[4] for w in band))


def unprinted():
    """{paper: [{"from": date or None, "to": date or None, ...}]} the eras measured to print no setter."""
    return json.loads(UNPRINTED.read_text())["eras"]


def is_unprinted(paper, date):
    """Whether `paper` is measured to print no setter on `date` (ISO)."""
    for e in unprinted().get(paper, ()):
        if (e.get("from") is None or date >= e["from"]) and (e.get("to") is None or date <= e["to"]):
            return True
    return False
