#!/usr/bin/env python3
"""Write tools/data/lexicons/abbreviations.json: every abbreviation
English Wiktionary or Wikipedia's crossword abbreviation list gives, as clue
word -> the letters it abbreviates to. A sense is in when either source lists it.

    python3 tools/fetch_abbreviations.py

The first source is kaikki.org's wiktextract extract of English Wiktionary, read
through its per-tag downloads (abbreviation, initialism, acronym, contraction,
symbol), the Symbol part of speech, and Translingual's Symbol and Numeral
parts of speech, where chemical symbols, units and Roman numerals live: about 125 MB streamed line by line, so
the 3 GB full dump is never needed. A sense counts when it carries one of those
tags or is a Symbol, and its expansion is what the dictionary says it stands
for: the alt_of/form_of words, or a gloss of four words or fewer when it gives
none ("month" for mon, "copper" for Cu's "Chemical element symbol for copper").

The second is Wikipedia's "Crossword abbreviations" article, at the revision
LIST_REVISION pins: the setters' conventions Wiktionary has no sense for (son S,
old O, love O, cold C, sailor AB, at home IN). Each "* Word - <small>X</small>"
line gives its readings. A reading of three or more letters that is itself a
word in tools/data/lexicon.tsv is a synonym the list mentions (sailor TAR, work
OPUS), not an abbreviation, and is skipped.

Wiktionary and Wikipedia text is CC BY-SA 4.0; tools/data/README.md says so
beside the file. build_abbreviations.table() reads the result.
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
LIST = "https://en.wikipedia.org/w/index.php?action=raw&title=Crossword_abbreviations&oldid="
LIST_REVISION = 1375193762
LEXICON = ROOT / "tools" / "data" / "lexicon.tsv"
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


def unlink(text):
    """Wikitext with [[target|shown]] and [[shown]] links reduced to what they show."""
    return re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)


def list_senses(wikitext, words=frozenset()):
    """(clue word, letters) for each reading on the article's A-to-Z lines:
    "* Old – <small>O</small>, <small>OL</small> (e.g. ...)". A line may name
    several clue words ("Sleep, Snooze or Asleep"). `words` are dictionary
    words; a reading of three or more letters among them is a synonym."""
    for line in wikitext[wikitext.find("==A=="):].splitlines():
        m = re.match(r"\*\s*([^<\[{]+?)\s+[–—-]\s+(.*<small>.*)", line)
        if not m:
            continue
        readings = [letters_of(unlink(r)) for r in re.findall(r"<small>(.*?)</small>", m.group(2))]
        for w in re.split(r",\s*|\s+or\s+", m.group(1)):
            w = re.sub(r"\s+", " ", w).strip().lower()
            if not WORDS.fullmatch(w):
                continue
            for k in readings:
                if k and k != letters_of(w) and not (len(k) >= 3 and k in words):
                    yield w, k


def lexicon_words():
    return frozenset(line.split("\t", 1)[0] for line in LEXICON.read_text(encoding="utf-8")
                     .splitlines() if line and not line.startswith("#"))


def fetch():
    table = {}
    req = urllib.request.Request(LIST + str(LIST_REVISION), headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        for w, k in list_senses(r.read().decode("utf-8"), lexicon_words()):
            table.setdefault(w, set()).add(k)
    print(f"Crossword abbreviations: {sum(map(len, table.values())):,} senses",
          file=sys.stderr)
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
