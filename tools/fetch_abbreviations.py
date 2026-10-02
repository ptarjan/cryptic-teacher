#!/usr/bin/env python3
"""Write tools/data/lexicons/abbreviations.json: every abbreviation
English Wiktionary lists, as clue word -> the letters it abbreviates to.

    python3 tools/fetch_abbreviations.py

The source is kaikki.org's wiktextract extract of English Wiktionary, read
through its per-tag downloads (abbreviation, initialism, acronym, contraction,
symbol), the Symbol part of speech, and Translingual's Symbol and Numeral
parts of speech, where chemical symbols, units and Roman numerals live: about 125 MB streamed line by line, so
the 3 GB full dump is never needed. A sense counts when it carries one of those
tags or is a Symbol, and its expansion is what the dictionary says it stands
for: the alt_of/form_of words, or a gloss of four words or fewer when it gives
none ("month" for mon, "copper" for Cu's "Chemical element symbol for copper").

Wiktionary text is CC BY-SA 4.0 and GFDL; tools/data/README.md says so beside
the file. build_abbreviations.table() reads the result.
"""
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tools" / "data" / "lexicons" / "abbreviations.json"
BASE = "https://kaikki.org/dictionary/"
SOURCES = [
    "English/tags/Tx/abbreviation/kaikki.org-dictionary-English-tag-abbreviation.jsonl",
    "English/tags/nY/initialism/kaikki.org-dictionary-English-tag-initialism.jsonl",
    "English/tags/om/acronym/kaikki.org-dictionary-English-tag-acronym.jsonl",
    "English/tags/1T/contraction/kaikki.org-dictionary-English-tag-contraction.jsonl",
    "English/tags/t2/symbol/kaikki.org-dictionary-English-tag-symbol.jsonl",
    "English/pos-symbol/kaikki.org-dictionary-English-by-pos-symbol.jsonl",
    # Chemical symbols, units and Roman numerals are Translingual entries.
    "Translingual/pos-symbol/kaikki.org-dictionary-Translingual-by-pos-symbol.jsonl",
    "Translingual/pos-num/kaikki.org-dictionary-Translingual-by-pos-num.jsonl",
]
TAGS = {"abbreviation", "initialism", "acronym", "contraction", "symbol"}
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
# An abbreviation is written in ASCII letters and digits; dots and apostrophes
# are punctuation and drop out (St. is ST, I'll is ILL).
FORM = re.compile(r"[A-Za-z0-9.']+")
# What an expansion may be: a word or phrase of plain letters.
WORDS = re.compile(r"[a-z0-9][a-z0-9 '\-]*")
# Gloss openers that name the relation rather than the expansion.
OPENER = re.compile(r"^(?:[\w\- ]{0,40}?\b(?:abbreviation|initialism|acronym|contraction|"
                    r"clipping|ellipsis|symbol)s? (?:of|for) )+", re.I)
ARTICLE = re.compile(r"^(?:the|a|an) ", re.I)
# An expansion that points at another entry instead of naming a meaning.
POINTER = re.compile(r"^(?:alternative|obsolete|archaic|dated|misspelling|synonym|"
                     r"plural|see)\b", re.I)


def letters_of(s):
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def expansions(raw, letters):
    """The clue words one alt_of word or short gloss names: parentheticals cut,
    'X or Y' split, 'run(s)' as run and runs, and a leading article dropped
    unless the letters spell it (the gram is G; th'one is THE ONE)."""
    raw = re.sub(r"\(s\)", "\0", raw)
    raw = re.sub(r"\([^)]*\)|\[[^\]]*\]|“[^”]*”", " ", raw)
    out = []
    for part in re.split(r"(?<=\w)/(?=\w)| or | and/or ", raw):
        part = OPENER.sub("", part.strip().rstrip(".:").strip())
        article = ARTICLE.match(part)
        if article and not letters.startswith(letters_of(article.group())[:2]):
            part = part[article.end():]
        if not part or POINTER.match(part):
            continue
        for p in ([part.replace("\0", ""), part.replace("\0", "s")] if "\0" in part else [part]):
            p = re.sub(r"\s+", " ", p).strip().lower()
            if WORDS.fullmatch(p):
                out.append(p)
    return out


def gloss_head(gloss):
    """A gloss up to its first comma, colon or semicolon, parentheticals cut:
    'newton, the SI unit of force.' is newton."""
    head = re.split(r"[,;:]", re.sub(r"\([^)]*\)", " ", gloss))[0].strip().rstrip(".")
    return OPENER.sub("", head)


def senses(entry):
    """(clue word, letters) for each abbreviation sense of one wiktextract entry."""
    form = entry.get("word", "")
    if not FORM.fullmatch(form):
        return
    letters = letters_of(form)
    if not letters:
        return
    for s in entry.get("senses", []):
        if not (TAGS & set(s.get("tags", [])) or entry.get("pos") == "symbol"):
            continue
        # wiktextract splits a gloss's commas into alt_of entries: the first is
        # the expansion and a second is a trailing remark ("Abbreviation of
        # company, alternative form of Co."), while three or more are one
        # phrase cut apart (TRBL: top, right, bottom, left) and name nothing.
        linked = [w.get("word") for w in (s.get("alt_of") or []) + (s.get("form_of") or [])]
        if len(linked) >= 3:
            continue
        named = linked[:1] if linked and linked[0] else []
        if not linked:
            named = [g for g in (gloss_head(g) for g in s.get("glosses", [])[:1])
                     if len(g.split()) <= 3]
        for raw in named:
            for w in expansions(raw, letters):
                if letters_of(w) != letters:
                    yield w, letters


def fetch():
    table = {}
    for path in SOURCES:
        req = urllib.request.Request(BASE + path, headers=UA)
        with urllib.request.urlopen(req, timeout=120) as r:
            for line in r:
                entry = json.loads(line)
                if entry.get("lang_code") not in ("en", "mul"):
                    continue
                for w, k in senses(entry):
                    table.setdefault(w, set()).add(k)
        print(f"{path.rsplit('/', 1)[1]}: {sum(map(len, table.values())):,} senses so far",
              file=sys.stderr)
    return table


def dump(table):
    """One line per clue word, sorted, so a refetch diffs by row."""
    rows = [f"{json.dumps(w)}: {json.dumps(sorted(table[w]))}" for w in sorted(table)]
    return "{\n" + ",\n".join(rows) + "\n}\n"


if __name__ == "__main__":
    t = fetch()
    OUT.write_text(dump(t), encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}: {len(t):,} clue words, "
          f"{sum(map(len, t.values())):,} senses")
