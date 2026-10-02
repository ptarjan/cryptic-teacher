#!/usr/bin/env bash
# /abbreviations/ ranks every list by clue count and shows the count: the most
# common list, the families and the members of each, and each A-to-Z row's
# readings. A reading no clue uses keeps its place, last, with no count.
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import json, re, tempfile
from pathlib import Path
import build_abbreviations as b

d = Path(tempfile.mkdtemp())
(d / "blocks.json").write_text(json.dumps({
    "ABOUT": {"RE": 50, "C": 90, "A": 5}, "SAILOR": {"AB": 40}, "ABBESS": {"ABB": 1},
    "CAUGHT": {"C": 70}, "KING": {"K": 3, "R": 30}, "QUEEN": {"Q": 2}, "MONK": {"BR": 9}}))
# sailor AB and monk BR: clues use them, no dictionary lists them. unused U: the
# dictionary lists it, no clue uses it.
(d / "dictionary.json").write_text(json.dumps({
    "about": ["A", "C", "RE"], "abbess": ["ABB"], "caught": ["C"], "king": ["K", "R"],
    "unused": ["U"]}))
b.LEXICON, b.DICTIONARY, b._USAGE, b._TABLE = d / "blocks.json", d / "dictionary.json", None, None
b.FAMILIES = [("Cards", "ace A, queen Q, king K"), ("Royals", "king R, rex R"),
              ("Others", "about A, caught C, abbess ABB")]
b.SYSTEMATIC = frozenset({"Cards"})
fails = 0
def check(name, want, got):
    global fails
    ok = want == got
    fails += not ok
    print(f"  {'ok' if ok else 'FAIL'}: {name}" + ("" if ok else f"\n    want {want}\n    got  {got}"))
plain = lambda h: re.sub(r"<[^>]+>|&nbsp;|&middot;|,", " ", h).split()
senses = b.by_word()

check("table(): dictionary senses clues use, plus SYSTEMATIC members, and nothing else",
      {"A": ["about", "ace"], "ABB": ["abbess"], "C": ["about", "caught"],
       "K": ["king"], "Q": ["queen"], "R": ["king"], "RE": ["about"]}, b.table())

check("most common: top n, most used first, each with its count",
      ["about", "C", "90", "caught", "C", "70", "about", "RE", "50"],
      plain(b.common_html(senses, 3)))
fam = b.families_html()
check("families: the most used family first, with its total",
      [("Others", "76"), ("Royals", "30"), ("Cards", "5")], re.findall(r"<dt>(\w+)&nbsp;<span[^>]*>(\d+)", fam))
check("a family that is not SYSTEMATIC shows only the members table() holds",
      ["king", "R", "30"], plain(re.search(r"<dt>Royals.*?<dd>(.*?)</dd>", fam).group(1)))
check("a family's members most used first; unused ones last, no count",
      ["king", "K", "3", "queen", "Q", "2", "ace", "A"],
      plain(re.search(r"<dt>Cards.*?<dd>(.*?)</dd>", fam).group(1)))
row = re.search(r'id="abbr-about"><dt>about</dt><dd>(.*?)</dd>', b.table_html(senses)).group(1)
check("an A-to-Z row's readings most used first, each with its count",
      ["C", "90", "RE", "50", "A", "5"], plain(row))
check("a rare word still shows its one clue",
      ["ABB", "1"], plain(re.search(r'id="abbr-abbess"><dt>abbess</dt><dd>(.*?)</dd>',
                                    b.table_html(senses)).group(1)))
raise SystemExit(fails)
PY
